#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leader Election Module - Distributed Locking and Leadership
AutoDialer Ultimate v3.0.0

Предоставляет распределённое лидерство с использованием Redis.
Координирует фоновые задачи между несколькими экземплярами.

ВКЛЮЧЕНЫ ВСЕ ИСПРАВЛЕНИЯ:
- Safe distributed lock с owner check
- Heartbeat loop с автоматическим восстановлением
- Graceful release с проверкой владельца
- Health checking с автоматическим отказом
- Реестр для управления множеством выборов
- Task runner для автоматического запуска задач
- Контекстный менеджер
"""

import asyncio
import socket
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, Dict, Set, List
from contextlib import asynccontextmanager
from enum import Enum

from logger import logger


# =============================================
# Leader Election Exception
# =============================================
class LeaderElectionError(Exception):
    """Базовое исключение для leader election."""
    pass


class NotLeaderError(LeaderElectionError):
    """Операция требует лидерства."""
    pass


class LockAcquisitionError(LeaderElectionError):
    """Не удалось захватить блокировку."""
    pass


# =============================================
# Leadership Status Enum
# =============================================
class LeadershipStatus(Enum):
    """Статус лидерства."""
    LEADER = "leader"
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    UNKNOWN = "unknown"


# =============================================
# Leader Election Base Class
# =============================================
class LeaderElection:
    """
    Распределённое лидерство через Redis SET NX.
    
    Обеспечивает выполнение задач только на одном экземпляре.
    
    Особенности:
    - Безопасная блокировка с проверкой владельца
    - Heartbeat с автоматическим восстановлением
    - Graceful release
    - Статистика
    """
    
    def __init__(
        self,
        redis_client,
        lock_key: str,
        ttl: int = 30,
        instance_id: Optional[str] = None,
        renew_interval: Optional[int] = None,
        on_leader_start: Optional[Callable] = None,
        on_leader_stop: Optional[Callable] = None,
        on_leader_lost: Optional[Callable] = None
    ):
        """
        Инициализация leader election.
        
        Args:
            redis_client: Клиент Redis
            lock_key: Уникальный ключ блокировки
            ttl: TTL блокировки в секундах
            instance_id: Уникальный ID экземпляра (авто-генерация если None)
            renew_interval: Интервал продления (по умолчанию ttl // 3)
            on_leader_start: Callback при получении лидерства
            on_leader_stop: Callback при добровольной потере лидерства
            on_leader_lost: Callback при непредвиденной потере лидерства
        """
        self.redis = redis_client
        self.lock_key = f"leader:{lock_key}"
        self.ttl = ttl
        self.renew_interval = renew_interval or max(1, ttl // 3)
        self.instance_id = instance_id or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        
        # Callbacks
        self.on_leader_start = on_leader_start
        self.on_leader_stop = on_leader_stop
        self.on_leader_lost = on_leader_lost
        
        # Состояние
        self.is_leader = False
        self.status = LeadershipStatus.FOLLOWER
        self._renew_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._running = False
        self._acquired_at: Optional[datetime] = None
        
        # Статистика
        self._stats = {
            'acquire_attempts': 0,
            'acquire_successes': 0,
            'acquire_failures': 0,
            'renew_attempts': 0,
            'renew_successes': 0,
            'renew_failures': 0,
            'leadership_lost_count': 0,
            'total_leadership_time': 0.0,
            'last_acquired': None,
            'last_lost': None
        }
        
        # Lua скрипты
        self._init_lua_scripts()
        
        logger.info(
            f"LeaderElection initialized: {self.lock_key} "
            f"(instance: {self.instance_id}, ttl: {ttl}s, renew: {self.renew_interval}s)"
        )
    
    def _init_lua_scripts(self):
        """Инициализация Lua скриптов для атомарных операций."""
        
        # Продление блокировки с проверкой владельца
        self.RENEW_LUA = """
            local key = KEYS[1]
            local expected_owner = ARGV[1]
            local ttl = tonumber(ARGV[2])
            
            local current = redis.call('GET', key)
            if current == expected_owner then
                return redis.call('EXPIRE', key, ttl)
            end
            return 0
        """
        
        # Освобождение блокировки с проверкой владельца
        self.RELEASE_LUA = """
            local key = KEYS[1]
            local expected_owner = ARGV[1]
            
            local current = redis.call('GET', key)
            if current == expected_owner then
                return redis.call('DEL', key)
            end
            return 0
        """
        
        # Захват блокировки с TTL
        self.ACQUIRE_LUA = """
            local key = KEYS[1]
            local owner = ARGV[1]
            local ttl = tonumber(ARGV[2])
            
            return redis.call('SET', key, owner, 'NX', 'EX', ttl)
        """
    
    @property
    def leader_id(self) -> Optional[str]:
        """ID текущего лидера (если это мы)."""
        return self.instance_id if self.is_leader else None
    
    @property
    def leadership_duration(self) -> Optional[float]:
        """Длительность текущего лидерства в секундах."""
        if self._acquired_at:
            return (datetime.now() - self._acquired_at).total_seconds()
        return None
    
    async def try_acquire(self) -> bool:
        """
        Попытаться захватить лидерство.
        
        Returns:
            True если лидерство получено, False иначе
        """
        async with self._lock:
            if self.is_leader:
                return True
            
            self._stats['acquire_attempts'] += 1
            self.status = LeadershipStatus.CANDIDATE
            
            try:
                # 🔥 Атомарный захват с TTL
                result = await self.redis.eval(
                    self.ACQUIRE_LUA,
                    1,
                    self.lock_key,
                    self.instance_id,
                    self.ttl
                )
                
                if result:
                    self.is_leader = True
                    self.status = LeadershipStatus.LEADER
                    self._acquired_at = datetime.now()
                    self._stats['acquire_successes'] += 1
                    self._stats['last_acquired'] = self._acquired_at
                    
                    logger.info(f"✅ Лидерство получено: {self.lock_key} by {self.instance_id}")
                    
                    # Запускаем heartbeat
                    self._running = True
                    self._renew_task = asyncio.create_task(self._heartbeat_loop())
                    
                    # Вызываем callback
                    if self.on_leader_start:
                        try:
                            if asyncio.iscoroutinefunction(self.on_leader_start):
                                await self.on_leader_start()
                            else:
                                self.on_leader_start()
                        except Exception as e:
                            logger.error(f"on_leader_start callback failed: {e}")
                    
                    return True
                else:
                    self._stats['acquire_failures'] += 1
                    self.status = LeadershipStatus.FOLLOWER
                    
                    # Проверяем, кто текущий лидер
                    current_leader = await self.redis.get(self.lock_key)
                    logger.debug(f"Лидерство не получено, текущий лидер: {current_leader}")
                    return False
                    
            except Exception as e:
                self._stats['acquire_failures'] += 1
                self.status = LeadershipStatus.UNKNOWN
                logger.error(f"Ошибка при захвате лидерства: {e}")
                return False
    
    async def _heartbeat_loop(self):
        """Надёжный heartbeat с автоматическим восстановлением."""
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while self._running and self.is_leader:
            try:
                success = await self._renew()
                
                if success:
                    consecutive_failures = 0
                    self._stats['renew_successes'] += 1
                else:
                    consecutive_failures += 1
                    self._stats['renew_failures'] += 1
                    logger.warning(f"Не удалось продлить лидерство (попытка {consecutive_failures})")
                    
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error("Потеряно лидерство после нескольких неудачных продлений")
                        await self._handle_leadership_lost()
                        break
                    
                    # Пытаемся перезахватить
                    if await self.try_acquire():
                        consecutive_failures = 0
                        logger.info("Лидерство перезахвачено")
                    else:
                        logger.warning("Не удалось перезахватить лидерство")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Ошибка в heartbeat: {e}")
            
            await asyncio.sleep(self.renew_interval)
    
    async def _renew(self) -> bool:
        """Продление блокировки с проверкой владельца."""
        self._stats['renew_attempts'] += 1
        
        try:
            result = await self.redis.eval(
                self.RENEW_LUA,
                1,
                self.lock_key,
                self.instance_id,
                self.ttl
            )
            
            if result:
                logger.debug(f"Лидерство продлено: {self.lock_key}")
                return True
            else:
                logger.warning(f"Не удалось продлить лидерство (блокировка у другого)")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка продления: {e}")
            return False
    
    async def _handle_leadership_lost(self):
        """Обработка потери лидерства."""
        async with self._lock:
            if not self.is_leader:
                return
            
            logger.warning(f"Потеря лидерства: {self.lock_key}")
            
            self._running = False
            self.is_leader = False
            self.status = LeadershipStatus.FOLLOWER
            self._stats['leadership_lost_count'] += 1
            self._stats['last_lost'] = datetime.now()
            
            if self._acquired_at:
                delta = (datetime.now() - self._acquired_at).total_seconds()
                self._stats['total_leadership_time'] += delta
                self._acquired_at = None
            
            # Отменяем heartbeat задачу
            if self._renew_task and not self._renew_task.done():
                self._renew_task.cancel()
                try:
                    await self._renew_task
                except asyncio.CancelledError:
                    pass
                self._renew_task = None
            
            # Вызываем callback
            if self.on_leader_lost:
                try:
                    if asyncio.iscoroutinefunction(self.on_leader_lost):
                        await self.on_leader_lost()
                    else:
                        self.on_leader_lost()
                except Exception as e:
                    logger.error(f"on_leader_lost callback failed: {e}")
    
    async def release(self):
        """Добровольное освобождение лидерства."""
        async with self._lock:
            if not self.is_leader:
                return
            
            logger.info(f"Добровольное освобождение лидерства: {self.lock_key}")
            
            self._running = False
            self.is_leader = False
            self.status = LeadershipStatus.FOLLOWER
            self._stats['last_lost'] = datetime.now()
            
            if self._acquired_at:
                delta = (datetime.now() - self._acquired_at).total_seconds()
                self._stats['total_leadership_time'] += delta
                self._acquired_at = None
            
            # Отменяем heartbeat задачу
            if self._renew_task and not self._renew_task.done():
                self._renew_task.cancel()
                try:
                    await self._renew_task
                except asyncio.CancelledError:
                    pass
                self._renew_task = None
            
            # 🔥 Безопасное освобождение с проверкой владельца
            await self._release_lock()
            
            # Вызываем callback
            if self.on_leader_stop:
                try:
                    if asyncio.iscoroutinefunction(self.on_leader_stop):
                        await self.on_leader_stop()
                    else:
                        self.on_leader_stop()
                except Exception as e:
                    logger.error(f"on_leader_stop callback failed: {e}")
    
    async def _release_lock(self):
        """Освобождение блокировки с проверкой владельца."""
        try:
            await self.redis.eval(
                self.RELEASE_LUA,
                1,
                self.lock_key,
                self.instance_id
            )
            logger.debug(f"Блокировка освобождена: {self.lock_key}")
        except Exception as e:
            logger.error(f"Ошибка освобождения блокировки: {e}")
    
    async def wait_for_leadership(self, timeout: Optional[float] = None) -> bool:
        """
        Ожидать получения лидерства.
        
        Args:
            timeout: Максимальное время ожидания в секундах
        
        Returns:
            True если лидерство получено, False по таймауту
        """
        start_time = time.monotonic()
        
        while True:
            if await self.try_acquire():
                return True
            
            if timeout:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    return False
            
            await asyncio.sleep(1)
    
    def require_leader(self):
        """
        Декоратор для функций, требующих лидерства.
        
        Usage:
            @election.require_leader()
            async def leader_only_task():
                pass
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                if not self.is_leader:
                    raise NotLeaderError(f"Операция требует лидерства: {self.lock_key}")
                return await func(*args, **kwargs)
            return wrapper
        return decorator
    
    async def get_current_leader(self) -> Optional[str]:
        """Получить ID текущего лидера."""
        return await self.redis.get(self.lock_key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику лидерства."""
        stats = self._stats.copy()
        stats['is_leader'] = self.is_leader
        stats['status'] = self.status.value
        stats['instance_id'] = self.instance_id
        stats['lock_key'] = self.lock_key
        stats['ttl'] = self.ttl
        stats['renew_interval'] = self.renew_interval
        stats['leadership_duration'] = self.leadership_duration
        
        if self._stats['last_acquired']:
            stats['last_acquired'] = self._stats['last_acquired'].isoformat()
        if self._stats['last_lost']:
            stats['last_lost'] = self._stats['last_lost'].isoformat()
        
        return stats
    
    def reset_stats(self):
        """Сбросить статистику."""
        self._stats = {
            'acquire_attempts': 0,
            'acquire_successes': 0,
            'acquire_failures': 0,
            'renew_attempts': 0,
            'renew_successes': 0,
            'renew_failures': 0,
            'leadership_lost_count': 0,
            'total_leadership_time': 0.0,
            'last_acquired': None,
            'last_lost': None
        }


# =============================================
# Leader Election with Health Check
# =============================================
class HealthCheckingLeaderElection(LeaderElection):
    """
    Leader election с проверкой здоровья.
    
    Автоматически отказывается от лидерства при проблемах со здоровьем.
    """
    
    def __init__(
        self,
        redis_client,
        lock_key: str,
        ttl: int = 30,
        instance_id: Optional[str] = None,
        health_check: Optional[Callable[[], bool]] = None,
        health_check_interval: int = 10,
        unhealthy_threshold: int = 3,
        on_leader_start: Optional[Callable] = None,
        on_leader_stop: Optional[Callable] = None,
        on_leader_lost: Optional[Callable] = None
    ):
        """
        Инициализация с проверкой здоровья.
        
        Args:
            health_check: Функция проверки здоровья (должна возвращать bool)
            health_check_interval: Интервал проверки в секундах
            unhealthy_threshold: Количество последовательных неудач для отказа
        """
        super().__init__(
            redis_client, lock_key, ttl, instance_id,
            on_leader_start, on_leader_stop, on_leader_lost
        )
        self.health_check = health_check
        self.health_check_interval = health_check_interval
        self.unhealthy_threshold = unhealthy_threshold
        self._health_check_task: Optional[asyncio.Task] = None
        self._healthy = True
        self._consecutive_failures = 0
    
    async def try_acquire(self) -> bool:
        """Захват лидерства с запуском проверки здоровья."""
        acquired = await super().try_acquire()
        
        if acquired and self.health_check:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        return acquired
    
    async def _health_check_loop(self):
        """Фоновая проверка здоровья."""
        while self._running and self.is_leader:
            await asyncio.sleep(self.health_check_interval)
            
            if self.health_check:
                try:
                    if asyncio.iscoroutinefunction(self.health_check):
                        healthy = await self.health_check()
                    else:
                        healthy = self.health_check()
                    
                    if healthy:
                        self._consecutive_failures = 0
                        if not self._healthy:
                            self._healthy = True
                            logger.info(f"Экземпляр снова здоров: {self.instance_id}")
                    else:
                        self._consecutive_failures += 1
                        if self._healthy and self._consecutive_failures >= self.unhealthy_threshold:
                            self._healthy = False
                            logger.warning(f"Экземпляр стал нездоровым, отказ от лидерства")
                            await self._handle_leadership_lost()
                            
                except Exception as e:
                    self._consecutive_failures += 1
                    logger.error(f"Ошибка проверки здоровья: {e}")
    
    async def _handle_leadership_lost(self):
        """Обработка потери лидерства с остановкой проверки здоровья."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
        
        await super()._handle_leadership_lost()
    
    async def release(self):
        """Освобождение лидерства с остановкой проверки здоровья."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
        
        await super().release()


# =============================================
# Leader Election Registry
# =============================================
class LeaderElectionRegistry:
    """Реестр для управления несколькими leader election."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self._elections: Dict[str, LeaderElection] = {}
        self._lock = asyncio.Lock()
    
    async def create(
        self,
        name: str,
        ttl: int = 30,
        instance_id: Optional[str] = None,
        health_check: Optional[Callable] = None,
        **kwargs
    ) -> LeaderElection:
        """
        Создать или получить leader election.
        
        Args:
            name: Уникальное имя
            ttl: TTL блокировки
            instance_id: ID экземпляра
            health_check: Функция проверки здоровья
            **kwargs: Дополнительные аргументы
        
        Returns:
            Экземпляр LeaderElection
        """
        async with self._lock:
            if name not in self._elections:
                if health_check:
                    self._elections[name] = HealthCheckingLeaderElection(
                        self.redis, name, ttl, instance_id,
                        health_check=health_check, **kwargs
                    )
                else:
                    self._elections[name] = LeaderElection(
                        self.redis, name, ttl, instance_id, **kwargs
                    )
            return self._elections[name]
    
    def get(self, name: str) -> Optional[LeaderElection]:
        """Получить leader election по имени."""
        return self._elections.get(name)
    
    async def try_acquire_all(self) -> Dict[str, bool]:
        """Попытаться захватить все зарегистрированные выборы."""
        results = {}
        for name, election in self._elections.items():
            results[name] = await election.try_acquire()
        return results
    
    async def release_all(self):
        """Освободить все выборы."""
        for election in self._elections.values():
            await election.release()
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Получить статистику всех выборов."""
        return {
            name: election.get_stats()
            for name, election in self._elections.items()
        }
    
    def get_leaders(self) -> List[str]:
        """Получить список имён, где мы лидеры."""
        return [
            name for name, election in self._elections.items()
            if election.is_leader
        ]
    
    async def remove(self, name: str) -> bool:
        """Удалить выборы из реестра."""
        async with self._lock:
            if name in self._elections:
                election = self._elections[name]
                if election.is_leader:
                    await election.release()
                del self._elections[name]
                return True
            return False


# =============================================
# Leader-Only Task Runner
# =============================================
class LeaderTaskRunner:
    """
    Запуск задач только когда экземпляр является лидером.
    
    Автоматически запускает/останавливает задачи при смене статуса.
    """
    
    def __init__(self, election: LeaderElection):
        self.election = election
        self._tasks: Set[asyncio.Task] = set()
        self._task_factories: Dict[str, Callable] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    def add_task(self, name: str, factory: Callable[[], asyncio.Task]):
        """
        Добавить задачу для запуска при лидерстве.
        
        Args:
            name: Имя задачи
            factory: Фабрика, возвращающая asyncio.Task
        """
        self._task_factories[name] = factory
        logger.debug(f"Добавлена задача лидера: {name}")
    
    def remove_task(self, name: str):
        """Удалить задачу."""
        if name in self._task_factories:
            del self._task_factories[name]
            logger.debug(f"Удалена задача лидера: {name}")
    
    async def start(self):
        """Запустить мониторинг лидерства."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"LeaderTaskRunner запущен для {self.election.lock_key}")
    
    async def stop(self):
        """Остановить мониторинг и все задачи."""
        self._running = False
        
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        await self._stop_all_tasks()
        logger.info(f"LeaderTaskRunner остановлен для {self.election.lock_key}")
    
    async def _monitor_loop(self):
        """Мониторинг статуса лидерства."""
        was_leader = False
        
        while self._running:
            is_leader = self.election.is_leader
            
            if is_leader and not was_leader:
                logger.info(f"Стали лидером, запуск задач")
                await self._start_all_tasks()
            elif not is_leader and was_leader:
                logger.info(f"Потеряли лидерство, остановка задач")
                await self._stop_all_tasks()
            
            was_leader = is_leader
            await asyncio.sleep(5)
    
    async def _start_all_tasks(self):
        """Запустить все зарегистрированные задачи."""
        for name, factory in self._task_factories.items():
            try:
                task = factory()
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                logger.info(f"Запущена задача лидера: {name}")
            except Exception as e:
                logger.error(f"Ошибка запуска задачи {name}: {e}")
    
    async def _stop_all_tasks(self):
        """Остановить все запущенные задачи."""
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Ошибка остановки задачи: {e}")
        self._tasks.clear()
    
    def get_running_tasks(self) -> List[str]:
        """Получить список имён запущенных задач."""
        return list(self._task_factories.keys()) if self.election.is_leader else []


# =============================================
# Context Manager for Leadership
# =============================================
@asynccontextmanager
async def leader_context(
    redis_client,
    lock_key: str,
    ttl: int = 30,
    instance_id: Optional[str] = None,
    wait_timeout: Optional[float] = None
):
    """
    Контекстный менеджер для временного лидерства.
    
    Usage:
        async with leader_context(redis, "my-task") as is_leader:
            if is_leader:
                # Выполняем работу, требующую лидерства
                pass
    """
    election = LeaderElection(redis_client, lock_key, ttl, instance_id)
    
    acquired = False
    try:
        if wait_timeout:
            acquired = await election.wait_for_leadership(wait_timeout)
        else:
            acquired = await election.try_acquire()
        
        yield acquired
        
    finally:
        if acquired:
            await election.release()


# =============================================
# Utility Functions
# =============================================
async def run_as_leader(
    redis_client,
    lock_key: str,
    func: Callable,
    *args,
    ttl: int = 30,
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    **kwargs
) -> Any:
    """
    Выполнить функцию только если этот экземпляр лидер.
    
    Args:
        redis_client: Клиент Redis
        lock_key: Ключ блокировки
        func: Функция для выполнения
        ttl: TTL блокировки
        wait: Ждать лидерства
        wait_timeout: Таймаут ожидания
    
    Returns:
        Результат функции или None если не лидер
    """
    election = LeaderElection(redis_client, lock_key, ttl)
    
    try:
        if wait:
            acquired = await election.wait_for_leadership(wait_timeout)
        else:
            acquired = await election.try_acquire()
        
        if acquired:
            return await func(*args, **kwargs)
        else:
            logger.debug(f"Не лидер, пропуск выполнения: {lock_key}")
            return None
            
    finally:
        if election.is_leader:
            await election.release()


async def get_or_create_leader(
    redis_client,
    lock_key: str,
    ttl: int = 30,
    instance_id: Optional[str] = None
) -> LeaderElection:
    """
    Получить или создать синглтон leader election для ключа.
    
    Args:
        redis_client: Клиент Redis
        lock_key: Ключ блокировки
        ttl: TTL блокировки
        instance_id: ID экземпляра
    
    Returns:
        Экземпляр LeaderElection
    """
    if not hasattr(get_or_create_leader, '_cache'):
        get_or_create_leader._cache = {}
    
    if lock_key not in get_or_create_leader._cache:
        get_or_create_leader._cache[lock_key] = LeaderElection(
            redis_client, lock_key, ttl, instance_id
        )
    
    return get_or_create_leader._cache[lock_key]


# =============================================
# Импорт для декоратора
# =============================================
from functools import wraps
