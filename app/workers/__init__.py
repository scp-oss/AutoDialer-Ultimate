#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Фоновые задачи (Workers)
AutoDialer Ultimate v3.0.0

Центральный модуль, управляющий всеми фоновыми задачами:
- Очистка старых аудиофайлов
- Обработка очереди повторных звонков
- Обновление метрик
- Обработка очереди транскрибации
- Очистка старых логов
- Мониторинг здоровья
- Синхронизация с Asterisk
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from app.core.config import settings
from app.core.logger import logger
from app.core.database import get_db_pool
from app.core.redis import get_redis_client, REDIS_KEYS
from app.utils.leader_election import LeaderElection
from app.utils.task_registry import get_task_registry, TaskRegistry


# =============================================
# Глобальные переменные
# =============================================
_workers_started = False
_workers: List[asyncio.Task] = []
_leader_election: Optional[LeaderElection] = None


# =============================================
# Импорт воркеров
# =============================================
from app.workers.cleanup import cleanup_old_audio_files
from app.workers.retry import process_retry_queue
from app.workers.metrics import update_metrics_periodically
from app.workers.transcription_queue import process_transcription_queue
from app.workers.log_cleanup import cleanup_old_logs
from app.workers.health_monitor import health_monitor
from app.workers.reconciliation import reconcile_with_asterisk


# =============================================
# Управление воркерами
# =============================================
async def start_all_workers():
    """
    Запустить все фоновые задачи.
    
    Вызывается при старте приложения.
    """
    global _workers_started, _workers, _leader_election
    
    if _workers_started:
        logger.warning("Воркеры уже запущены")
        return
    
    logger.info("=" * 50)
    logger.info("Запуск фоновых задач (workers)...")
    logger.info("=" * 50)
    
    redis_client = get_redis_client()
    
    # Инициализация leader election для задач, которые должны выполняться только на одном экземпляре
    _leader_election = LeaderElection(
        redis_client=redis_client,
        lock_key="workers:leader",
        ttl=60,
        instance_id=settings.INSTANCE_ID if hasattr(settings, 'INSTANCE_ID') else None
    )
    
    # Список воркеров для запуска
    worker_configs = [
        # (функция, имя, интервал, требует лидерства, только в production)
        (cleanup_old_audio_files, "cleanup_audio", 86400, True, False),
        (process_retry_queue, "retry_queue", 10, False, False),
        (update_metrics_periodically, "metrics", 15, False, False),
        (process_transcription_queue, "transcription_queue", 5, False, False),
        (cleanup_old_logs, "log_cleanup", 86400, True, False),
        (health_monitor, "health_monitor", 30, False, False),
        (reconcile_with_asterisk, "asterisk_reconciliation", 300, True, True),
    ]
    
    task_registry = get_task_registry()
    
    for worker_func, name, interval, requires_leader, only_production in worker_configs:
        # Пропускаем если только для production
        if only_production and settings.ENVIRONMENT != "production":
            logger.info(f"⏭️ Пропуск {name} (только для production)")
            continue
        
        # Создаём обёртку с leader election если нужно
        if requires_leader:
            async def leader_wrapper(func=worker_func, w_name=name, w_interval=interval):
                while True:
                    try:
                        # Пытаемся стать лидером
                        if await _leader_election.try_acquire():
                            logger.info(f"👑 Стали лидером для задачи: {w_name}")
                            await func()
                            await _leader_election.release()
                        else:
                            logger.debug(f"Не лидер для задачи: {w_name}, ожидание...")
                    except Exception as e:
                        logger.error(f"Ошибка в leader wrapper {w_name}: {e}")
                    
                    await asyncio.sleep(w_interval)
            
            worker_coro = leader_wrapper()
        else:
            async def simple_wrapper(func=worker_func, w_name=name, w_interval=interval):
                while True:
                    try:
                        await func()
                    except Exception as e:
                        logger.error(f"Ошибка в воркере {w_name}: {e}")
                    
                    await asyncio.sleep(w_interval)
            
            worker_coro = simple_wrapper()
        
        # Запускаем задачу
        task = asyncio.create_task(worker_coro)
        task_id = await task_registry.register(
            worker_coro,
            name=f"worker:{name}",
            category="worker"
        )
        
        _workers.append(task)
        logger.info(f"✅ Воркер запущен: {name} (интервал: {interval}с, лидер: {requires_leader})")
    
    _workers_started = True
    
    logger.info("=" * 50)
    logger.info(f"✅ Запущено {len(_workers)} фоновых задач")
    logger.info("=" * 50)


async def stop_all_workers():
    """
    Остановить все фоновые задачи.
    
    Вызывается при завершении приложения.
    """
    global _workers_started, _workers, _leader_election
    
    if not _workers_started:
        return
    
    logger.info("Остановка фоновых задач...")
    
    # Освобождаем лидерство
    if _leader_election:
        try:
            await _leader_election.release()
        except Exception as e:
            logger.warning(f"Ошибка освобождения лидерства: {e}")
    
    # Отменяем все задачи
    task_registry = get_task_registry()
    await task_registry.cancel_by_category("worker")
    
    for task in _workers:
        if not task.done():
            task.cancel()
    
    # Ждём завершения
    await asyncio.gather(*_workers, return_exceptions=True)
    
    _workers.clear()
    _workers_started = False
    
    logger.info("✅ Все фоновые задачи остановлены")


async def restart_worker(name: str) -> bool:
    """
    Перезапустить конкретный воркер.
    
    Args:
        name: Имя воркера
    
    Returns:
        True если перезапущен
    """
    task_registry = get_task_registry()
    
    # Находим задачу по имени
    tasks = task_registry.get_tasks_by_name(f"worker:{name}")
    if not tasks:
        logger.warning(f"Воркер {name} не найден")
        return False
    
    # Отменяем старую
    await task_registry.cancel_by_name(f"worker:{name}")
    
    # Запускаем новую (зависит от имени)
    worker_map = {
        "cleanup_audio": cleanup_old_audio_files,
        "retry_queue": process_retry_queue,
        "metrics": update_metrics_periodically,
        "transcription_queue": process_transcription_queue,
        "log_cleanup": cleanup_old_logs,
        "health_monitor": health_monitor,
        "asterisk_reconciliation": reconcile_with_asterisk,
    }
    
    if name not in worker_map:
        logger.warning(f"Неизвестный воркер: {name}")
        return False
    
    worker_func = worker_map[name]
    
    async def wrapper():
        while True:
            try:
                await worker_func()
            except Exception as e:
                logger.error(f"Ошибка в воркере {name}: {e}")
            await asyncio.sleep(60)  # Интервал по умолчанию
    
    task = asyncio.create_task(wrapper())
    await task_registry.register(task, name=f"worker:{name}", category="worker")
    
    logger.info(f"✅ Воркер перезапущен: {name}")
    return True


def get_workers_status() -> Dict[str, Any]:
    """
    Получить статус всех воркеров.
    
    Returns:
        Словарь со статусами
    """
    task_registry = get_task_registry()
    
    status = {
        "started": _workers_started,
        "total": len(_workers),
        "workers": []
    }
    
    for task_info in task_registry.get_tasks(category="worker"):
        status["workers"].append({
            "name": task_info.name.replace("worker:", ""),
            "status": task_info.status.value,
            "started_at": task_info.started_at.isoformat() if task_info.started_at else None,
            "duration": task_info.duration,
            "error": task_info.error
        })
    
    # Добавляем информацию о лидерстве
    if _leader_election:
        status["leader"] = {
            "is_leader": _leader_election.is_leader,
            "instance_id": _leader_election.instance_id,
            "current_leader": _leader_election.get_current_leader()
        }
    
    return status


# =============================================
# Декоратор для периодических задач
# =============================================
def periodic_task(interval: int, name: str = None, requires_leader: bool = False):
    """
    Декоратор для создания периодической фоновой задачи.
    
    Args:
        interval: Интервал выполнения в секундах
        name: Имя задачи
        requires_leader: Требует лидерства
    
    Usage:
        @periodic_task(interval=60, name="my_task")
        async def my_periodic_task():
            pass
    """
    def decorator(func):
        task_name = name or func.__name__
        
        async def wrapper():
            redis_client = get_redis_client()
            leader_election = None
            
            if requires_leader:
                leader_election = LeaderElection(
                    redis_client=redis_client,
                    lock_key=f"workers:{task_name}",
                    ttl=interval * 2
                )
            
            while True:
                try:
                    if requires_leader:
                        if await leader_election.try_acquire():
                            await func()
                            await leader_election.release()
                    else:
                        await func()
                except Exception as e:
                    logger.error(f"Ошибка в задаче {task_name}: {e}")
                
                await asyncio.sleep(interval)
        
        # Регистрируем задачу
        async def register():
            task_registry = get_task_registry()
            task = asyncio.create_task(wrapper())
            await task_registry.register(task, name=f"worker:{task_name}", category="worker")
            return task
        
        wrapper.register = register
        return wrapper
    
    return decorator


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Управление
    "start_all_workers",
    "stop_all_workers",
    "restart_worker",
    "get_workers_status",
    
    # Воркеры
    "cleanup_old_audio_files",
    "process_retry_queue",
    "update_metrics_periodically",
    "process_transcription_queue",
    "cleanup_old_logs",
    "health_monitor",
    "reconcile_with_asterisk",
    
    # Декоратор
    "periodic_task",
]
