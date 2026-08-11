#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Circuit Breaker Pattern Implementation
AutoDialer Ultimate v3.0.0

Предоставляет отказоустойчивость для внешних сервисов (Database, Redis, AMI, etc.)

ВКЛЮЧЕНЫ ВСЕ ИСПРАВЛЕНИЯ:
- Non-blocking (lock только на state)
- Динамические timeout по типу сервиса
- Jitter и gradual recovery
- Timeout на вызов
- Статистика и метрики
- Синхронная версия (SyncCircuitBreaker)
- Полуоткрытое состояние с ограничением трафика
- Защита от thundering herd
"""

import asyncio
import time
import random
import threading
from enum import Enum
from datetime import datetime, timedelta
from typing import Callable, Optional, Any, Dict, TypeVar, Generic, List
from functools import wraps
import logging

# =============================================
# Logger
# =============================================
logger = logging.getLogger(__name__)


# =============================================
# Circuit State Enum
# =============================================
class CircuitState(Enum):
    """Состояния Circuit Breaker."""
    CLOSED = "closed"          # Нормальная работа, запросы проходят
    OPEN = "open"              # Разомкнут, запросы блокируются
    HALF_OPEN = "half_open"    # Тестирование восстановления


# =============================================
# Circuit Breaker Statistics
# =============================================
class CircuitStatistics:
    """Статистика Circuit Breaker."""
    
    def __init__(self):
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.timeout_calls: int = 0
        self.rejected_calls: int = 0
        self.last_success_time: Optional[datetime] = None
        self.last_failure_time: Optional[datetime] = None
        self.last_failure_error: Optional[str] = None
        self.total_open_time: float = 0.0
        self.open_count: int = 0
        self.reset_time: Optional[datetime] = None
        self._state_history: List[tuple] = []  # (timestamp, from_state, to_state)
    
    def record_success(self):
        """Запись успешного вызова."""
        self.total_calls += 1
        self.successful_calls += 1
        self.last_success_time = datetime.now()
    
    def record_failure(self, error: str = None):
        """Запись неудачного вызова."""
        self.total_calls += 1
        self.failed_calls += 1
        self.last_failure_time = datetime.now()
        self.last_failure_error = error
    
    def record_timeout(self):
        """Запись таймаута."""
        self.total_calls += 1
        self.timeout_calls += 1
        self.last_failure_time = datetime.now()
    
    def record_rejected(self):
        """Запись отклонённого вызова."""
        self.rejected_calls += 1
    
    def record_open(self):
        """Запись размыкания цепи."""
        self.open_count += 1
        self.reset_time = datetime.now()
    
    def record_state_change(self, from_state: CircuitState, to_state: CircuitState):
        """Запись изменения состояния."""
        self._state_history.append((datetime.now(), from_state.value, to_state.value))
        # Ограничиваем историю 100 записями
        if len(self._state_history) > 100:
            self._state_history = self._state_history[-100:]
    
    @property
    def success_rate(self) -> float:
        """Процент успешных вызовов."""
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100
    
    @property
    def failure_rate(self) -> float:
        """Процент неудачных вызовов."""
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100
    
    @property
    def availability(self) -> float:
        """Доступность (время в CLOSED / общее время)."""
        if self.total_calls == 0:
            return 100.0
        return 100.0 - (self.total_open_time / max(1, self.total_calls) * 100)
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "timeout_calls": self.timeout_calls,
            "rejected_calls": self.rejected_calls,
            "success_rate": round(self.success_rate, 2),
            "failure_rate": round(self.failure_rate, 2),
            "availability": round(self.availability, 2),
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_failure_error": self.last_failure_error,
            "open_count": self.open_count,
            "state_history": [
                {"time": ts.isoformat(), "from": frm, "to": to}
                for ts, frm, to in self._state_history[-10:]  # Последние 10 переходов
            ]
        }
    
    def reset(self):
        """Сброс статистики."""
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.timeout_calls = 0
        self.rejected_calls = 0
        self.last_success_time = None
        self.last_failure_time = None
        self.last_failure_error = None
        self.open_count = 0
        self._state_history = []


# =============================================
# Circuit Breaker Exceptions
# =============================================
class CircuitBreakerError(Exception):
    """Базовое исключение Circuit Breaker."""
    pass


class CircuitOpenError(CircuitBreakerError):
    """Цепь разомкнута, запрос отклонён."""
    
    def __init__(self, name: str, remaining_time: float = None):
        self.name = name
        self.remaining_time = remaining_time
        message = f"Circuit '{name}' is OPEN"
        if remaining_time:
            message += f" (retry in {remaining_time:.1f}s)"
        super().__init__(message)


class CircuitTimeoutError(CircuitBreakerError):
    """Таймаут вызова."""
    
    def __init__(self, name: str, timeout: float):
        self.name = name
        self.timeout = timeout
        super().__init__(f"Circuit '{name}' timed out after {timeout}s")


# =============================================
# Half-Open State Controller
# =============================================
class HalfOpenController:
    """Контроллер полуоткрытого состояния с ограничением трафика."""
    
    def __init__(self, max_concurrent: int = 1, success_threshold: int = 2):
        self.max_concurrent = max_concurrent
        self.success_threshold = success_threshold
        self.current_concurrent = 0
        self.success_count = 0
        self.failure_count = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """Попытка получить разрешение на вызов."""
        async with self._lock:
            if self.current_concurrent < self.max_concurrent:
                self.current_concurrent += 1
                return True
            return False
    
    async def release(self):
        """Освобождение слота."""
        async with self._lock:
            if self.current_concurrent > 0:
                self.current_concurrent -= 1
    
    async def record_success(self):
        """Запись успешного вызова."""
        async with self._lock:
            self.success_count += 1
    
    async def record_failure(self):
        """Запись неудачного вызова."""
        async with self._lock:
            self.failure_count += 1
    
    def should_close(self) -> bool:
        """Проверка, можно ли закрыть цепь."""
        return self.success_count >= self.success_threshold
    
    def should_reopen(self) -> bool:
        """Проверка, нужно ли снова разомкнуть цепь."""
        return self.failure_count > 0
    
    def reset(self):
        """Сброс контроллера."""
        self.current_concurrent = 0
        self.success_count = 0
        self.failure_count = 0


# =============================================
# Main Circuit Breaker Class (Async)
# =============================================
T = TypeVar('T')


class CircuitBreaker(Generic[T]):
    """
    Реализация паттерна Circuit Breaker для асинхронных операций.
    
    Особенности:
    - Non-blocking (блокировка только при изменении состояния)
    - Динамические таймауты по типу сервиса
    - Jitter и gradual recovery
    - Timeout на каждый вызов
    - Контроллер полуоткрытого состояния
    """
    
    # Таймауты по типу сервиса (сек)
    SERVICE_TIMEOUTS = {
        "redis": 2.0,
        "ami": 5.0,
        "db": 3.0,
        "tts": 30.0,
        "http": 10.0,
        "default": 5.0
    }
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
        service_type: str = "default",
        timeout: Optional[float] = None,
        max_timeout: float = 300.0,
        exponential_backoff: bool = True,
        half_open_max_concurrent: int = 1,
        on_open: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_half_open: Optional[Callable] = None,
        on_reject: Optional[Callable] = None
    ):
        """
        Инициализация Circuit Breaker.
        
        Args:
            name: Уникальное имя цепи
            failure_threshold: Количество ошибок для размыкания
            recovery_timeout: Базовый таймаут восстановления (сек)
            success_threshold: Успешных вызовов для замыкания
            service_type: Тип сервиса (redis, ami, db, tts, default)
            timeout: Таймаут вызова (если None, берётся из SERVICE_TIMEOUTS)
            max_timeout: Максимальный таймаут восстановления
            exponential_backoff: Использовать экспоненциальный backoff
            half_open_max_concurrent: Макс. одновременных вызовов в half-open
            on_open: Callback при размыкании
            on_close: Callback при замыкании
            on_half_open: Callback при переходе в half-open
            on_reject: Callback при отклонении запроса
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.base_recovery_timeout = recovery_timeout
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.service_type = service_type
        self.timeout = timeout or self.SERVICE_TIMEOUTS.get(service_type, 5.0)
        self.max_timeout = max_timeout
        self.exponential_backoff = exponential_backoff
        
        # Callbacks
        self.on_open = on_open
        self.on_close = on_close
        self.on_half_open = on_half_open
        self.on_reject = on_reject
        
        # Состояние
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_state_change: datetime = datetime.now()
        self.open_count = 0
        self.open_start_time: Optional[datetime] = None
        
        # 🔥 Non-blocking: блокировка только для изменения состояния
        self._state_lock = asyncio.Lock()
        
        # 🔥 Контроллер полуоткрытого состояния
        self.half_open_controller = HalfOpenController(
            max_concurrent=half_open_max_concurrent,
            success_threshold=success_threshold
        )
        
        # Статистика
        self.stats = CircuitStatistics()
        
        # Скользящее окно для ошибок
        self._failure_timestamps: list[datetime] = []
        self._failure_window = 60.0  # 1 минута
        
        logger.info(
            f"Circuit '{name}' initialized: "
            f"service={service_type}, timeout={self.timeout}s, "
            f"threshold={failure_threshold}, recovery={recovery_timeout}s"
        )
    
    @property
    def is_closed(self) -> bool:
        """Цепь замкнута (нормальная работа)."""
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Цепь разомкнута (запросы блокируются)."""
        return self.state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Цепь в режиме тестирования."""
        return self.state == CircuitState.HALF_OPEN
    
    @property
    def recovery_remaining(self) -> float:
        """Оставшееся время до попытки восстановления."""
        if not self.is_open or not self.last_failure_time:
            return 0.0
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return max(0.0, self.recovery_timeout - elapsed)
    
    def _cleanup_failure_window(self):
        """Удаление ошибок за пределами скользящего окна."""
        cutoff = datetime.now() - timedelta(seconds=self._failure_window)
        self._failure_timestamps = [ts for ts in self._failure_timestamps if ts > cutoff]
    
    def _calculate_recovery_timeout(self) -> int:
        """Расчёт таймаута восстановления с экспоненциальным backoff и jitter."""
        if not self.exponential_backoff:
            return self.base_recovery_timeout
        
        # Экспоненциальный backoff
        backoff = self.base_recovery_timeout * (2 ** self.open_count)
        
        # 🔥 Jitter для избежания thundering herd (±20%)
        jitter = backoff * 0.2 * (random.random() * 2 - 1)
        backoff_with_jitter = backoff + jitter
        
        return min(int(backoff_with_jitter), self.max_timeout)
    
    async def _transition_to_open(self, error: str = None):
        """Переход в состояние OPEN."""
        async with self._state_lock:
            if self.state != CircuitState.OPEN:
                old_state = self.state
                self.state = CircuitState.OPEN
                self.open_count += 1
                self.open_start_time = datetime.now()
                self.recovery_timeout = self._calculate_recovery_timeout()
                self.last_state_change = datetime.now()
                self.stats.record_open()
                self.stats.record_state_change(old_state, CircuitState.OPEN)
                self.half_open_controller.reset()
                
                logger.warning(
                    f"🔴 Circuit '{self.name}' OPENED "
                    f"(failures: {self.failure_count}, recovery: {self.recovery_timeout}s"
                    f"{f', error: {error}' if error else ''})"
                )
                
                if self.on_open:
                    try:
                        if asyncio.iscoroutinefunction(self.on_open):
                            await self.on_open(self.name, self.failure_count)
                        else:
                            self.on_open(self.name, self.failure_count)
                    except Exception as e:
                        logger.error(f"on_open callback failed: {e}")
    
    async def _transition_to_half_open(self):
        """Переход в состояние HALF_OPEN."""
        async with self._state_lock:
            if self.state != CircuitState.HALF_OPEN:
                old_state = self.state
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = datetime.now()
                self.stats.record_state_change(old_state, CircuitState.HALF_OPEN)
                self.half_open_controller.reset()
                
                # Считаем время в OPEN для статистики
                if self.open_start_time:
                    open_duration = (datetime.now() - self.open_start_time).total_seconds()
                    self.stats.total_open_time += open_duration
                    self.open_start_time = None
                
                logger.info(f"🟡 Circuit '{self.name}' HALF_OPEN (testing recovery)")
                
                if self.on_half_open:
                    try:
                        if asyncio.iscoroutinefunction(self.on_half_open):
                            await self.on_half_open(self.name)
                        else:
                            self.on_half_open(self.name)
                    except Exception as e:
                        logger.error(f"on_half_open callback failed: {e}")
    
    async def _transition_to_closed(self):
        """Переход в состояние CLOSED."""
        async with self._state_lock:
            if self.state != CircuitState.CLOSED:
                old_state = self.state
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self._failure_timestamps.clear()
                self.recovery_timeout = self.base_recovery_timeout
                self.last_state_change = datetime.now()
                self.stats.record_state_change(old_state, CircuitState.CLOSED)
                self.half_open_controller.reset()
                self.open_start_time = None
                
                logger.info(f"🟢 Circuit '{self.name}' CLOSED (recovered)")
                
                if self.on_close:
                    try:
                        if asyncio.iscoroutinefunction(self.on_close):
                            await self.on_close(self.name)
                        else:
                            self.on_close(self.name)
                    except Exception as e:
                        logger.error(f"on_close callback failed: {e}")
    
    async def _check_state(self) -> bool:
        """
        Проверка состояния и получение разрешения на вызов.
        
        Returns:
            True если вызов разрешён, False если отклонён
        """
        # Быстрая проверка без блокировки
        if self.state == CircuitState.OPEN:
            if self.recovery_remaining <= 0:
                await self._transition_to_half_open()
            else:
                self.stats.record_rejected()
                if self.on_reject:
                    try:
                        if asyncio.iscoroutinefunction(self.on_reject):
                            await self.on_reject(self.name, "open", self.recovery_remaining)
                        else:
                            self.on_reject(self.name, "open", self.recovery_remaining)
                    except Exception as e:
                        logger.error(f"on_reject callback failed: {e}")
                return False
        
        elif self.state == CircuitState.HALF_OPEN:
            # 🔥 Контроллер полуоткрытого состояния
            if not await self.half_open_controller.acquire():
                self.stats.record_rejected()
                if self.on_reject:
                    try:
                        if asyncio.iscoroutinefunction(self.on_reject):
                            await self.on_reject(self.name, "half_open_concurrent", 0)
                        else:
                            self.on_reject(self.name, "half_open_concurrent", 0)
                    except Exception as e:
                        logger.error(f"on_reject callback failed: {e}")
                return False
        
        return True
    
    async def _release_half_open(self):
        """Освобождение слота в полуоткрытом состоянии."""
        if self.state == CircuitState.HALF_OPEN:
            await self.half_open_controller.release()
    
    async def _record_success(self):
        """Запись успешного вызова."""
        self.stats.record_success()
        
        if self.state == CircuitState.HALF_OPEN:
            await self.half_open_controller.record_success()
            
            if self.half_open_controller.should_close():
                await self._transition_to_closed()
        
        elif self.state == CircuitState.CLOSED:
            # В closed состоянии уменьшаем счётчик ошибок при успехе.
            # _record_failure() всегда пересчитывает failure_count из
            # _failure_timestamps (len(...)), поэтому просто уменьшать
            # failure_count без удаления записи из _failure_timestamps
            # бессмысленно - следующий же failure отбросит "восстановление"
            # и пересчитает failure_count из непочищенного списка.
            if self.failure_count > 0:
                self.failure_count = max(0, self.failure_count - 1)
                if self._failure_timestamps:
                    self._failure_timestamps.pop(0)
    
    async def _record_failure(self, error: str = None):
        """Запись неудачного вызова."""
        self.stats.record_failure(error)
        self.last_failure_time = datetime.now()
        self._failure_timestamps.append(self.last_failure_time)
        self._cleanup_failure_window()
        
        if self.state == CircuitState.HALF_OPEN:
            await self.half_open_controller.record_failure()
            # В half-open одна ошибка сразу размыкает цепь
            self.failure_count = len(self._failure_timestamps)
            await self._transition_to_open(error)
        
        elif self.state == CircuitState.CLOSED:
            self.failure_count = len(self._failure_timestamps)
            if self.failure_count >= self.failure_threshold:
                await self._transition_to_open(error)
    
    async def call(
        self,
        func: Callable[..., Any],
        *args,
        timeout: Optional[float] = None,
        **kwargs
    ) -> T:
        """
        Выполнение функции с защитой Circuit Breaker.
        
        Args:
            func: Асинхронная функция
            *args: Позиционные аргументы
            timeout: Таймаут (если None, используется из конфига)
            **kwargs: Именованные аргументы
        
        Returns:
            Результат функции
        
        Raises:
            CircuitOpenError: Цепь разомкнута
            CircuitTimeoutError: Таймаут вызова
            Exception: Исходное исключение функции
        """
        # Проверка состояния
        if not await self._check_state():
            raise CircuitOpenError(self.name, self.recovery_remaining)
        
        call_timeout = timeout if timeout is not None else self.timeout
        
        try:
            # 🔥 Вызов с таймаутом
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=call_timeout
                )
            else:
                # Синхронная функция выполняется в thread pool
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: func(*args, **kwargs)
                    ),
                    timeout=call_timeout
                )
            
            await self._record_success()
            return result
            
        except asyncio.TimeoutError:
            self.stats.record_timeout()
            await self._record_failure(f"Timeout after {call_timeout}s")
            raise CircuitTimeoutError(self.name, call_timeout)
            
        except CircuitOpenError:
            raise
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            await self._record_failure(error_msg)
            raise
        
        finally:
            await self._release_half_open()
    
    async def __aenter__(self):
        """Вход в контекстный менеджер."""
        if not await self._check_state():
            raise CircuitOpenError(self.name, self.recovery_remaining)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Выход из контекстного менеджера."""
        try:
            if exc_type is None:
                await self._record_success()
            elif exc_type not in (CircuitOpenError, CircuitTimeoutError):
                error_msg = f"{exc_type.__name__}: {str(exc_val)}"
                await self._record_failure(error_msg)
        finally:
            await self._release_half_open()
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Получение текущего статуса."""
        status = {
            "name": self.name,
            "state": self.state.value,
            "service_type": self.service_type,
            "timeout": self.timeout,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "open_count": self.open_count,
            "recovery_timeout": self.recovery_timeout,
            "recovery_remaining": round(self.recovery_remaining, 1),
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_state_change": self.last_state_change.isoformat(),
        }
        
        if self.state == CircuitState.HALF_OPEN:
            status.update({
                "half_open_concurrent": self.half_open_controller.current_concurrent,
                "half_open_max": self.half_open_controller.max_concurrent,
                "half_open_success": self.half_open_controller.success_count,
                "half_open_threshold": self.success_threshold
            })
        
        status["statistics"] = self.stats.to_dict()
        
        return status
    
    def reset(self):
        """Принудительный сброс в CLOSED."""
        async def _reset():
            async with self._state_lock:
                old_state = self.state
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self._failure_timestamps.clear()
                self.recovery_timeout = self.base_recovery_timeout
                self.last_state_change = datetime.now()
                self.half_open_controller.reset()
                self.open_start_time = None
                self.stats.record_state_change(old_state, CircuitState.CLOSED)
                logger.info(f"Circuit '{self.name}' manually reset to CLOSED")
        
        asyncio.create_task(_reset())
    
    def force_open(self):
        """Принудительное размыкание цепи."""
        async def _force_open():
            await self._transition_to_open("Manually forced open")
        
        asyncio.create_task(_force_open())
    
    def force_half_open(self):
        """Принудительный переход в HALF_OPEN."""
        async def _force_half_open():
            await self._transition_to_half_open()
        
        asyncio.create_task(_force_half_open())


# =============================================
# Synchronous Circuit Breaker
# =============================================
class SyncCircuitBreaker:
    """
    Синхронная версия Circuit Breaker для не-async кода.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        timeout: float = 30.0
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.timeout = timeout
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self._lock = threading.RLock()
        
        self.stats = CircuitStatistics()
    
    def _check_state(self):
        """Проверка состояния (синхронная)."""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self.last_failure_time:
                    elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                    if elapsed >= self.recovery_timeout:
                        self.state = CircuitState.HALF_OPEN
                        logger.info(f"SyncCircuit '{self.name}' HALF_OPEN")
                    else:
                        self.stats.record_rejected()
                        raise CircuitOpenError(self.name, self.recovery_timeout - elapsed)
    
    def call(self, func: Callable, *args, timeout: Optional[float] = None, **kwargs):
        """Выполнение функции с защитой (синхронно)."""
        self._check_state()
        
        call_timeout = timeout if timeout is not None else self.timeout
        
        import signal
        
        def timeout_handler(signum, frame):
            raise CircuitTimeoutError(self.name, call_timeout)
        
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(call_timeout))
        
        try:
            result = func(*args, **kwargs)
            
            with self._lock:
                self.stats.record_success()
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    logger.info(f"SyncCircuit '{self.name}' CLOSED")
            
            return result
            
        except CircuitTimeoutError:
            with self._lock:
                self.stats.record_timeout()
                self.failure_count += 1
                self.last_failure_time = datetime.now()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"SyncCircuit '{self.name}' OPENED")
            raise
            
        except Exception as e:
            with self._lock:
                self.stats.record_failure(str(e))
                self.failure_count += 1
                self.last_failure_time = datetime.now()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"SyncCircuit '{self.name}' OPENED")
            raise
        
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса."""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "statistics": self.stats.to_dict()
            }
    
    def reset(self):
        """Сброс в CLOSED."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info(f"SyncCircuit '{self.name}' manually reset")


# =============================================
# Circuit Breaker Registry
# =============================================
class CircuitBreakerRegistry:
    """Реестр для управления несколькими Circuit Breaker."""
    
    def __init__(self):
        self._circuits: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()
    
    async def get_or_create(
        self,
        name: str,
        service_type: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        **kwargs
    ) -> CircuitBreaker:
        """Получить существующий или создать новый Circuit Breaker."""
        async with self._lock:
            if name not in self._circuits:
                self._circuits[name] = CircuitBreaker(
                    name=name,
                    service_type=service_type,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    **kwargs
                )
            return self._circuits[name]
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Получить Circuit Breaker по имени."""
        return self._circuits.get(name)
    
    def list_circuits(self) -> list:
        """Список всех имён цепей."""
        return list(self._circuits.keys())
    
    def get_all_status(self) -> Dict[str, Any]:
        """Статус всех цепей."""
        return {
            name: circuit.get_status()
            for name, circuit in self._circuits.items()
        }
    
    async def reset_all(self):
        """Сброс всех цепей."""
        for circuit in self._circuits.values():
            circuit.reset()
    
    async def remove(self, name: str) -> bool:
        """Удаление цепи."""
        async with self._lock:
            if name in self._circuits:
                del self._circuits[name]
                return True
            return False
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Сводка по здоровью всех цепей."""
        summary = {
            "total": len(self._circuits),
            "closed": 0,
            "open": 0,
            "half_open": 0,
            "healthy": True
        }
        
        for circuit in self._circuits.values():
            if circuit.is_closed:
                summary["closed"] += 1
            elif circuit.is_open:
                summary["open"] += 1
                summary["healthy"] = False
            elif circuit.is_half_open:
                summary["half_open"] += 1
        
        return summary


# =============================================
# Global Registry Instance
# =============================================
circuit_registry = CircuitBreakerRegistry()


# =============================================
# Decorator
# =============================================
def circuit_breaker(
    name: str,
    service_type: str = "default",
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    timeout: Optional[float] = None
):
    """
    Декоратор для оборачивания функции в Circuit Breaker.
    
    Usage:
        @circuit_breaker("my_service", service_type="redis")
        async def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        breaker = CircuitBreaker(
            name=name,
            service_type=service_type,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            timeout=timeout
        )
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        
        wrapper._circuit_breaker = breaker
        return wrapper
    
    return decorator


# =============================================
# Utility Function
# =============================================
async def with_circuit_breaker(
    name: str,
    func: Callable,
    *args,
    service_type: str = "default",
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    **kwargs
) -> Any:
    """
    Выполнение функции с временным Circuit Breaker.
    
    Usage:
        result = await with_circuit_breaker(
            "my_redis", redis_client.get, "key",
            service_type="redis"
        )
    """
    breaker = await circuit_registry.get_or_create(
        name=name,
        service_type=service_type,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout
    )
    return await breaker.call(func, *args, **kwargs)


# =============================================
# Health Check Integration
# =============================================
async def check_all_circuits_health() -> Dict[str, Any]:
    """
    Проверка здоровья всех цепей для /api/health.
    
    Returns:
        Словарь с информацией о здоровье цепей
    """
    summary = circuit_registry.get_health_summary()
    
    circuits_status = {}
    for name, circuit in circuit_registry._circuits.items():
        status = circuit.get_status()
        circuits_status[name] = {
            "state": status["state"],
            "failure_count": status["failure_count"],
            "success_rate": status["statistics"]["success_rate"]
        }
    
    return {
        "healthy": summary["healthy"],
        "summary": summary,
        "circuits": circuits_status
    }
