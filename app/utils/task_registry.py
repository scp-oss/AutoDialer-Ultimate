#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task Registry Module - Управление асинхронными задачами
AutoDialer Ultimate v3.0.0

Предоставляет централизованное управление asyncio задачами:
- Регистрация и отслеживание
- Graceful cancellation
- Мониторинг статуса
- Автоматическая очистка

ВКЛЮЧЕНЫ ВСЕ ИСПРАВЛЕНИЯ:
- Auto-cleanup callback (устранение memory leak)
- Watchdog с timeout (завершение зависших задач)
- Статистика выполнения
- Группировка задач по категориям
- Лимиты на количество задач
"""

import asyncio
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Any, Callable, Awaitable, List, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager

from logger import logger


# =============================================
# Task Status Enum
# =============================================
class TaskStatus(str, Enum):
    """Статус выполнения задачи."""
    PENDING = "pending"        # Ожидает запуска
    RUNNING = "running"        # Выполняется
    COMPLETED = "completed"    # Успешно завершена
    FAILED = "failed"          # Завершилась с ошибкой
    CANCELLED = "cancelled"    # Отменена
    TIMEOUT = "timeout"        # Превышен таймаут
    ZOMBIE = "zombie"          # Зависшая (убита watchdog)


# =============================================
# Task Priority Enum
# =============================================
class TaskPriority(int, Enum):
    """Приоритет задачи."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# =============================================
# Task Info Dataclass
# =============================================
@dataclass
class TaskInfo:
    """Информация о зарегистрированной задаче."""
    task_id: str
    name: str
    task: Optional[asyncio.Task] = None
    coro: Optional[Awaitable] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    category: str = "default"
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None
    _timeout_handler: Optional[asyncio.TimerHandle] = None
    _watchdog_task: Optional[asyncio.Task] = None
    
    @property
    def duration(self) -> Optional[float]:
        """Длительность выполнения в секундах."""
        if self.started_at:
            end = self.completed_at or datetime.now()
            return (end - self.started_at).total_seconds()
        return None
    
    @property
    def age(self) -> float:
        """Возраст задачи в секундах."""
        return (datetime.now() - self.created_at).total_seconds()
    
    @property
    def is_done(self) -> bool:
        """Завершена ли задача."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
            TaskStatus.ZOMBIE
        )
    
    @property
    def is_active(self) -> bool:
        """Активна ли задача."""
        return self.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority.value,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration": self.duration,
            "age": self.age,
            "error": self.error,
            "metadata": self.metadata,
            "timeout": self.timeout,
            "is_done": self.is_done,
            "is_active": self.is_active
        }


# =============================================
# Task Registry Statistics
# =============================================
@dataclass
class RegistryStats:
    """Статистика реестра задач."""
    total_registered: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_cancelled: int = 0
    total_timeout: int = 0
    total_zombie: int = 0
    active_count: int = 0
    pending_count: int = 0
    running_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_registered": self.total_registered,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_cancelled": self.total_cancelled,
            "total_timeout": self.total_timeout,
            "total_zombie": self.total_zombie,
            "active_count": self.active_count,
            "pending_count": self.pending_count,
            "running_count": self.running_count
        }


# =============================================
# Task Registry
# =============================================
class TaskRegistry:
    """
    Реестр для управления asyncio задачами.
    
    Особенности:
    - Регистрация с уникальными ID
    - Отмена задач (индивидуально или все)
    - Отслеживание статуса
    - Автоматическая очистка завершённых
    - Watchdog для зависших задач
    - Лимиты на количество активных задач
    """
    
    def __init__(
        self,
        max_history: int = 1000,
        default_timeout: Optional[float] = None,
        max_concurrent: Optional[int] = None,
        max_per_category: Optional[Dict[str, int]] = None
    ):
        """
        Инициализация реестра задач.
        
        Args:
            max_history: Максимальное количество завершённых задач в истории
            default_timeout: Таймаут по умолчанию для задач (сек)
            max_concurrent: Максимальное количество одновременно выполняемых задач
            max_per_category: Лимиты по категориям
        """
        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = asyncio.Lock()
        
        self.max_history = max_history
        self.default_timeout = default_timeout
        self.max_concurrent = max_concurrent
        self.max_per_category = max_per_category or {}
        
        self._history: List[TaskInfo] = []
        self._stats = RegistryStats()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Семафор для ограничения конкурентности
        self._concurrent_semaphore: Optional[asyncio.Semaphore] = None
        if max_concurrent:
            self._concurrent_semaphore = asyncio.Semaphore(max_concurrent)
        
        # Семафоры по категориям
        self._category_semaphores: Dict[str, asyncio.Semaphore] = {}
        for category, limit in self.max_per_category.items():
            self._category_semaphores[category] = asyncio.Semaphore(limit)
        
        logger.info(
            f"TaskRegistry initialized: max_history={max_history}, "
            f"max_concurrent={max_concurrent}, default_timeout={default_timeout}"
        )
    
    async def start(self):
        """Запустить реестр (фоновые задачи очистки и watchdog)."""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("TaskRegistry запущен")
    
    async def stop(self, grace_period: float = 5.0):
        """
        Остановить реестр и отменить все задачи.
        
        Args:
            grace_period: Время ожидания завершения задач (сек)
        """
        if not self._running:
            return
        
        self._running = False
        
        # Отменяем фоновые задачи
        for task in [self._cleanup_task, self._watchdog_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Отменяем все зарегистрированные задачи
        await self.cancel_all(grace_period)
        
        logger.info("TaskRegistry остановлен")
    
    async def _cleanup_loop(self):
        """Фоновая очистка завершённых задач."""
        while self._running:
            await asyncio.sleep(60)
            await self._cleanup_completed()
    
    async def _cleanup_completed(self):
        """Удаление завершённых задач из активного реестра."""
        async with self._lock:
            completed_ids = []
            
            for task_id, info in self._tasks.items():
                if info.task and info.task.done():
                    completed_ids.append(task_id)
                    
                    # Обновляем статус если нужно
                    if info.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                        self._update_task_status_from_result(info)
                    
                    # Переносим в историю
                    self._add_to_history(info)
            
            for task_id in completed_ids:
                del self._tasks[task_id]
            
            if completed_ids:
                logger.debug(f"Очищено {len(completed_ids)} завершённых задач")
    
    def _update_task_status_from_result(self, info: TaskInfo):
        """Обновление статуса задачи на основе результата."""
        if not info.task:
            return
        
        if info.task.cancelled():
            info.status = TaskStatus.CANCELLED
            self._stats.total_cancelled += 1
        else:
            try:
                exc = info.task.exception()
                if exc:
                    info.status = TaskStatus.FAILED
                    info.error = str(exc)
                    self._stats.total_failed += 1
                else:
                    info.status = TaskStatus.COMPLETED
                    self._stats.total_completed += 1
            except asyncio.CancelledError:
                info.status = TaskStatus.CANCELLED
                self._stats.total_cancelled += 1
            except Exception as e:
                info.status = TaskStatus.FAILED
                info.error = str(e)
                self._stats.total_failed += 1
        
        info.completed_at = datetime.now()
        
        # Отменяем timeout handler
        if info._timeout_handler:
            info._timeout_handler.cancel()
            info._timeout_handler = None
        
        # Отменяем watchdog
        if info._watchdog_task and not info._watchdog_task.done():
            info._watchdog_task.cancel()
            info._watchdog_task = None
    
    def _add_to_history(self, info: TaskInfo):
        """Добавление завершённой задачи в историю."""
        self._history.append(info)
        
        # Обрезаем историю
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]
    
    async def _watchdog_loop(self):
        """Фоновая проверка зависших задач."""
        while self._running:
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
            
            async with self._lock:
                now = datetime.now()
                zombie_tasks = []
                
                for task_id, info in self._tasks.items():
                    # Проверяем задачи с таймаутом
                    if info.timeout and info.started_at:
                        if now - info.started_at > timedelta(seconds=info.timeout):
                            zombie_tasks.append((task_id, info))
                    
                    # Проверяем задачи без таймаута, но висящие > 1 часа
                    elif info.started_at and not info.timeout:
                        if now - info.started_at > timedelta(hours=1):
                            zombie_tasks.append((task_id, info))
                
                for task_id, info in zombie_tasks:
                    logger.warning(f"Watchdog: обнаружена зависшая задача '{info.name}' ({task_id})")
                    
                    if info.task and not info.task.done():
                        info.task.cancel()
                        info.status = TaskStatus.ZOMBIE
                        info.error = f"Watchdog timeout after {info.timeout or 3600}s"
                        info.completed_at = now
                        self._stats.total_zombie += 1
                        
                        # Переносим в историю
                        self._add_to_history(info)
                        del self._tasks[task_id]
    
    def _generate_task_id(self, prefix: str = "") -> str:
        """Генерация уникального ID задачи."""
        return f"{prefix}{uuid.uuid4().hex[:12]}"
    
    def _create_timeout_handler(self, task_id: str, timeout: float):
        """Создание обработчика таймаута."""
        loop = asyncio.get_event_loop()
        
        def on_timeout():
            asyncio.create_task(self._handle_timeout(task_id))
        
        return loop.call_later(timeout, on_timeout)
    
    async def _handle_timeout(self, task_id: str):
        """Обработка таймаута задачи."""
        async with self._lock:
            if task_id not in self._tasks:
                return
            
            info = self._tasks[task_id]
            
            if info.is_done:
                return
            
            logger.warning(f"Задача '{info.name}' ({task_id}) превысила таймаут {info.timeout}с")
            
            info.status = TaskStatus.TIMEOUT
            info.error = f"Timeout after {info.timeout}s"
            info.completed_at = datetime.now()
            self._stats.total_timeout += 1
            
            if info.task and not info.task.done():
                info.task.cancel()
            
            # Переносим в историю
            self._add_to_history(info)
            del self._tasks[task_id]
    
    async def _check_limits(self, category: str) -> bool:
        """Проверка лимитов на запуск задачи."""
        # Проверка общего лимита
        if self._concurrent_semaphore:
            if self._concurrent_semaphore.locked():
                return False
        
        # Проверка лимита по категории
        if category in self._category_semaphores:
            semaphore = self._category_semaphores[category]
            if semaphore.locked():
                return False
        
        # Подсчёт активных задач
        async with self._lock:
            active_count = sum(1 for info in self._tasks.values() if info.is_active)
            if self.max_concurrent and active_count >= self.max_concurrent:
                return False
            
            category_count = sum(
                1 for info in self._tasks.values()
                if info.is_active and info.category == category
            )
            if category in self.max_per_category:
                if category_count >= self.max_per_category[category]:
                    return False
        
        return True
    
    async def _acquire_limits(self, category: str):
        """Захват семафоров для задачи."""
        if self._concurrent_semaphore:
            await self._concurrent_semaphore.acquire()
        
        if category in self._category_semaphores:
            await self._category_semaphores[category].acquire()
    
    def _release_limits(self, category: str):
        """Освобождение семафоров."""
        if self._concurrent_semaphore:
            self._concurrent_semaphore.release()
        
        if category in self._category_semaphores:
            self._category_semaphores[category].release()
    
    async def register(
        self,
        coro: Union[Awaitable[Any], Callable[[], Awaitable[Any]]],
        name: str = "unnamed",
        task_id: Optional[str] = None,
        timeout: Optional[float] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        category: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
        start: bool = True,
        wait_for_limit: bool = True
    ) -> str:
        """
        Зарегистрировать и запустить задачу.
        
        Args:
            coro: Корутина или фабрика корутины
            name: Человеко-читаемое имя
            task_id: Пользовательский ID (авто-генерация если None)
            timeout: Таймаут в секундах
            priority: Приоритет задачи
            category: Категория задачи
            metadata: Дополнительные метаданные
            start: Запустить немедленно
            wait_for_limit: Ждать освобождения лимитов
        
        Returns:
            ID задачи
        """
        # Проверка лимитов
        if not await self._check_limits(category):
            if wait_for_limit:
                logger.debug(f"Ожидание лимитов для задачи '{name}' ({category})")
                # Ждём освобождения
                while not await self._check_limits(category):
                    await asyncio.sleep(0.5)
            else:
                raise RuntimeError(f"Превышены лимиты для категории '{category}'")
        
        # Генерация ID
        if task_id is None:
            prefix = f"{name.replace(' ', '_')}_"
            task_id = self._generate_task_id(prefix)
        
        # Проверка дубликата
        async with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"Задача с ID '{task_id}' уже существует")
            
            # Создание информации
            info = TaskInfo(
                task_id=task_id,
                name=name,
                status=TaskStatus.PENDING,
                priority=priority,
                category=category,
                timeout=timeout or self.default_timeout,
                metadata=metadata or {}
            )
            
            self._tasks[task_id] = info
            self._stats.total_registered += 1
        
        # Захват семафоров
        await self._acquire_limits(category)
        
        try:
            # Создание задачи
            if start:
                if asyncio.iscoroutinefunction(coro):
                    async_task = asyncio.create_task(coro())
                elif hasattr(coro, '__await__'):
                    async_task = asyncio.create_task(coro)
                else:
                    async_task = asyncio.create_task(coro())
            else:
                if asyncio.iscoroutinefunction(coro):
                    info.coro = coro()
                else:
                    info.coro = coro
                async_task = None
            
            if async_task:
                info.task = async_task
                info.status = TaskStatus.RUNNING
                info.started_at = datetime.now()
                
                # Добавляем callback
                async_task.add_done_callback(
                    lambda t: asyncio.create_task(self._on_task_done(task_id, t))
                )
                
                # Устанавливаем обработчик таймаута
                if info.timeout:
                    info._timeout_handler = self._create_timeout_handler(task_id, info.timeout)
            
            logger.debug(f"Задача зарегистрирована: {name} ({task_id}) [{category}]")
            
            return task_id
            
        except Exception as e:
            # Освобождаем лимиты при ошибке
            self._release_limits(category)
            
            async with self._lock:
                if task_id in self._tasks:
                    del self._tasks[task_id]
            
            raise e
    
    async def _on_task_done(self, task_id: str, task: asyncio.Task):
        """Callback при завершении задачи."""
        async with self._lock:
            if task_id not in self._tasks:
                return
            
            info = self._tasks[task_id]
            
            # Обновляем статус
            self._update_task_status_from_result(info)
            
            # Освобождаем лимиты
            self._release_limits(info.category)
            
            # Переносим в историю
            self._add_to_history(info)
            del self._tasks[task_id]
            
            logger.debug(f"Задача завершена: {info.name} ({task_id}) -> {info.status.value}")
    
    async def start_task(self, task_id: str):
        """Запустить зарегистрированную, но не запущенную задачу."""
        async with self._lock:
            if task_id not in self._tasks:
                raise ValueError(f"Задача '{task_id}' не найдена")
            
            info = self._tasks[task_id]
            
            if info.status != TaskStatus.PENDING:
                raise ValueError(f"Задача '{task_id}' уже запущена")
            
            if not info.coro:
                raise ValueError(f"Задача '{task_id}' не имеет корутины")
            
            # Проверка лимитов
            if not await self._check_limits(info.category):
                raise RuntimeError(f"Превышены лимиты для категории '{info.category}'")
            
            # Захват лимитов
            await self._acquire_limits(info.category)
            
            # Запуск
            info.task = asyncio.create_task(info.coro)
            info.status = TaskStatus.RUNNING
            info.started_at = datetime.now()
            
            info.task.add_done_callback(
                lambda t: asyncio.create_task(self._on_task_done(task_id, t))
            )
            
            if info.timeout:
                info._timeout_handler = self._create_timeout_handler(task_id, info.timeout)
    
    async def cancel(self, task_id: str) -> bool:
        """
        Отменить задачу по ID.
        
        Returns:
            True если отменена, False если не найдена или уже завершена
        """
        async with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"Задача '{task_id}' не найдена")
                return False
            
            info = self._tasks[task_id]
            
            if info.task and not info.task.done():
                logger.info(f"Отмена задачи: {info.name} ({task_id})")
                return info.task.cancel()
            
            return False
    
    async def cancel_all(self, grace_period: float = 5.0) -> int:
        """
        Отменить все зарегистрированные задачи.
        
        Args:
            grace_period: Время ожидания отмены
        
        Returns:
            Количество отменённых задач
        """
        async with self._lock:
            tasks_to_cancel = []
            
            for task_id, info in self._tasks.items():
                if info.task and not info.task.done():
                    tasks_to_cancel.append((task_id, info))
            
            if not tasks_to_cancel:
                return 0
            
            logger.info(f"Отмена {len(tasks_to_cancel)} задач (grace: {grace_period}с)")
            
            for _, info in tasks_to_cancel:
                info.task.cancel()
            
            await asyncio.wait(
                [info.task for _, info in tasks_to_cancel],
                timeout=grace_period
            )
            
            return len(tasks_to_cancel)
    
    async def cancel_by_category(self, category: str) -> int:
        """Отменить все задачи в категории."""
        async with self._lock:
            cancelled = 0
            for task_id, info in list(self._tasks.items()):
                if info.category == category and info.task and not info.task.done():
                    info.task.cancel()
                    cancelled += 1
            return cancelled
    
    async def cancel_by_name(self, name: str) -> int:
        """Отменить все задачи с указанным именем."""
        async with self._lock:
            cancelled = 0
            for task_id, info in list(self._tasks.items()):
                if info.name == name and info.task and not info.task.done():
                    info.task.cancel()
                    cancelled += 1
            return cancelled
    
    async def cancel_by_metadata(self, key: str, value: Any) -> int:
        """Отменить задачи по метаданным."""
        async with self._lock:
            cancelled = 0
            for task_id, info in list(self._tasks.items()):
                if info.metadata.get(key) == value and info.task and not info.task.done():
                    info.task.cancel()
                    cancelled += 1
            return cancelled
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Получить информацию о задаче по ID."""
        return self._tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Получить статус задачи по ID."""
        info = self._tasks.get(task_id)
        return info.status if info else None
    
    def get_tasks(
        self,
        status: Optional[TaskStatus] = None,
        category: Optional[str] = None
    ) -> List[TaskInfo]:
        """
        Получить все задачи с опциональной фильтрацией.
        
        Args:
            status: Фильтр по статусу
            category: Фильтр по категории
        
        Returns:
            Список TaskInfo
        """
        tasks = list(self._tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        if category:
            tasks = [t for t in tasks if t.category == category]
        
        return tasks
    
    def get_active_tasks(self, category: Optional[str] = None) -> List[TaskInfo]:
        """Получить все активные задачи."""
        tasks = [t for t in self._tasks.values() if t.is_active]
        if category:
            tasks = [t for t in tasks if t.category == category]
        return tasks
    
    def get_tasks_by_name(self, name: str) -> List[TaskInfo]:
        """Получить задачи по имени."""
        return [t for t in self._tasks.values() if t.name == name]
    
    def get_count(self, category: Optional[str] = None) -> int:
        """Получить количество зарегистрированных задач."""
        if category:
            return sum(1 for t in self._tasks.values() if t.category == category)
        return len(self._tasks)
    
    def get_active_count(self, category: Optional[str] = None) -> int:
        """Получить количество активных задач."""
        tasks = [t for t in self._tasks.values() if t.is_active]
        if category:
            tasks = [t for t in tasks if t.category == category]
        return len(tasks)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику реестра."""
        # Обновляем счётчики
        self._stats.active_count = self.get_active_count()
        self._stats.pending_count = len([t for t in self._tasks.values() if t.status == TaskStatus.PENDING])
        self._stats.running_count = len([t for t in self._tasks.values() if t.status == TaskStatus.RUNNING])
        
        return {
            **self._stats.to_dict(),
            "total_tasks": len(self._tasks),
            "history_size": len(self._history)
        }
    
    def get_stats_by_category(self) -> Dict[str, Dict[str, int]]:
        """Получить статистику по категориям."""
        stats = {}
        
        for info in self._tasks.values():
            if info.category not in stats:
                stats[info.category] = {"total": 0, "active": 0, "completed": 0, "failed": 0}
            
            stats[info.category]["total"] += 1
            if info.is_active:
                stats[info.category]["active"] += 1
            if info.status == TaskStatus.COMPLETED:
                stats[info.category]["completed"] += 1
            elif info.status == TaskStatus.FAILED:
                stats[info.category]["failed"] += 1
        
        return stats
    
    def get_history(self, limit: int = 100, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить историю задач."""
        history = self._history
        if category:
            history = [h for h in history if h.category == category]
        
        history = history[-limit:] if limit else history
        return [h.to_dict() for h in history]
    
    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        Ожидать завершения задачи и вернуть результат.
        
        Args:
            task_id: ID задачи
            timeout: Таймаут ожидания
        
        Returns:
            Результат задачи
        
        Raises:
            ValueError: Задача не найдена
            asyncio.TimeoutError: Превышен таймаут
            Exception: Ошибка задачи
        """
        info = self._tasks.get(task_id)
        if not info:
            raise ValueError(f"Задача '{task_id}' не найдена")
        
        if not info.task:
            raise ValueError(f"Задача '{task_id}' не запущена")
        
        try:
            return await asyncio.wait_for(info.task, timeout=timeout)
        except asyncio.TimeoutError:
            info.status = TaskStatus.TIMEOUT
            info.error = f"Wait timeout after {timeout}s"
            raise
    
    async def wait_for_all(self, timeout: Optional[float] = None) -> List[Any]:
        """
        Ожидать завершения всех активных задач.
        
        Args:
            timeout: Таймаут ожидания
        
        Returns:
            Список результатов (или исключений)
        """
        active = self.get_active_tasks()
        if not active:
            return []
        
        tasks = [info.task for info in active if info.task]
        
        done, pending = await asyncio.wait(
            tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED
        )
        
        results = []
        for task in done:
            try:
                results.append(task.result())
            except Exception as e:
                results.append(e)
        
        return results
    
    def clear_history(self, category: Optional[str] = None):
        """Очистить историю задач."""
        if category:
            self._history = [h for h in self._history if h.category != category]
        else:
            self._history.clear()
        logger.debug(f"История задач очищена (category={category})")
    
    def reset_stats(self):
        """Сбросить статистику."""
        self._stats = RegistryStats()
        logger.debug("Статистика сброшена")
    
    def update_limits(self, max_concurrent: Optional[int] = None, max_per_category: Optional[Dict[str, int]] = None):
        """Обновить лимиты."""
        if max_concurrent is not None:
            self.max_concurrent = max_concurrent
            self._concurrent_semaphore = asyncio.Semaphore(max_concurrent) if max_concurrent else None
        
        if max_per_category is not None:
            self.max_per_category = max_per_category
            self._category_semaphores = {
                cat: asyncio.Semaphore(limit)
                for cat, limit in max_per_category.items()
            }
        
        logger.info(f"Лимиты обновлены: max_concurrent={max_concurrent}, categories={max_per_category}")


# =============================================
# Global Task Registry Instance
# =============================================
_task_registry: Optional[TaskRegistry] = None


def get_task_registry() -> TaskRegistry:
    """Получить глобальный экземпляр реестра задач."""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry()
    return _task_registry


def set_task_registry(registry: TaskRegistry):
    """Установить глобальный экземпляр реестра задач."""
    global _task_registry
    _task_registry = registry


# =============================================
# Convenience Functions
# =============================================
async def register_task(
    coro: Awaitable[Any],
    name: str = "unnamed",
    timeout: Optional[float] = None,
    category: str = "default",
    **metadata
) -> str:
    """
    Зарегистрировать и запустить задачу.
    
    Args:
        coro: Корутина
        name: Имя задачи
        timeout: Таймаут
        category: Категория
        **metadata: Метаданные
    
    Returns:
        ID задачи
    """
    registry = get_task_registry()
    return await registry.register(coro, name=name, timeout=timeout, category=category, metadata=metadata)


async def cancel_task(task_id: str) -> bool:
    """Отменить задачу по ID."""
    registry = get_task_registry()
    return await registry.cancel(task_id)


async def cancel_tasks_by_campaign(campaign_id: int) -> int:
    """Отменить все задачи для кампании."""
    registry = get_task_registry()
    return await registry.cancel_by_metadata("campaign_id", campaign_id)


def get_active_task_count(category: Optional[str] = None) -> int:
    """Получить количество активных задач."""
    registry = get_task_registry()
    return registry.get_active_count(category)


def get_task_info(task_id: str) -> Optional[Dict[str, Any]]:
    """Получить информацию о задаче по ID."""
    registry = get_task_registry()
    info = registry.get_task(task_id)
    return info.to_dict() if info else None


def list_active_tasks(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Список всех активных задач."""
    registry = get_task_registry()
    return [info.to_dict() for info in registry.get_active_tasks(category)]


# =============================================
# Task Decorator
# =============================================
def tracked_task(
    name: str = None,
    timeout: float = None,
    category: str = "default",
    priority: TaskPriority = TaskPriority.NORMAL,
    auto_register: bool = True
):
    """
    Декоратор для автоматической регистрации корутины как отслеживаемой задачи.
    
    Usage:
        @tracked_task(name="my_task", timeout=60, category="campaign")
        async def my_coroutine():
            pass
    """
    def decorator(func):
        task_name = name or func.__name__
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if auto_register:
                registry = get_task_registry()
                
                async def wrapped_coro():
                    return await func(*args, **kwargs)
                
                task_id = await registry.register(
                    wrapped_coro,
                    name=task_name,
                    timeout=timeout,
                    priority=priority,
                    category=category,
                    metadata={
                        "function": func.__name__,
                        "args": str(args),
                        "kwargs": str(kwargs)
                    }
                )
                
                info = registry.get_task(task_id)
                if info and info.task:
                    return await info.task
                return None
            else:
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# =============================================
# Context Manager for Task Group
# =============================================
@asynccontextmanager
async def task_group(name: str = "group", cancel_on_exit: bool = True):
    """
    Контекстный менеджер для группы задач.
    
    Usage:
        async with task_group("my_group") as group:
            await group.register(coro1, "task1")
            await group.register(coro2, "task2")
            # Все задачи будут отменены при выходе
    """
    registry = get_task_registry()
    task_ids = []
    
    class Group:
        async def register(self, coro, task_name="unnamed", **kwargs):
            task_id = await registry.register(coro, name=f"{name}/{task_name}", **kwargs)
            task_ids.append(task_id)
            return task_id
        
        async def wait_all(self, timeout=None):
            return await asyncio.gather(*[
                registry.wait_for_task(tid, timeout)
                for tid in task_ids
            ], return_exceptions=True)
    
    group = Group()
    
    try:
        yield group
    finally:
        if cancel_on_exit:
            for task_id in task_ids:
                await registry.cancel(task_id)
