#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Вспомогательные утилиты
AutoDialer Ultimate v3.0.0

Центральный модуль, экспортирующий все утилиты:
- AMI Manager (DialerManager)
- Circuit Breaker
- Rate Limiter
- Leader Election
- Task Registry

ИСПОЛЬЗОВАНИЕ:
    from app.utils import (
        CircuitBreaker, CircuitOpenError,
        TokenBucket, SlidingWindowRateLimiter, GlobalRateLimiter,
        LeaderElection, leader_context,
        TaskRegistry, tracked_task
    )
"""

from __future__ import annotations

# =============================================
# Circuit Breaker
# =============================================
from app.utils.circuit_breaker import (
    # Основной класс
    CircuitBreaker,
    SyncCircuitBreaker,
    
    # Состояния
    CircuitState,
    
    # Исключения
    CircuitBreakerError,
    CircuitOpenError,
    CircuitTimeoutError,
    
    # Статистика
    CircuitStatistics,
    
    # Контроллер полуоткрытого состояния
    HalfOpenController,
    
    # Реестр
    CircuitBreakerRegistry,
    circuit_registry,
    
    # Декоратор
    circuit_breaker as circuit_breaker_decorator,
    
    # Утилиты
    with_circuit_breaker,
    check_all_circuits_health,
)


# =============================================
# Rate Limiter
# =============================================
from app.utils.rate_limiter import (
    # Token Bucket (локальный)
    TokenBucket,
    
    # Sliding Window (Redis)
    SlidingWindowRateLimiter,
    
    # Fixed Window (Redis)
    FixedWindowRateLimiter,
    
    # Leaky Bucket (Redis)
    LeakyBucketRateLimiter,
    
    # Global CPS Limiter
    GlobalRateLimiter,
    
    # Adaptive CPS
    AdaptiveCPSLimiter,
    
    # Quota Manager
    QuotaManager,
    
    # Multi-Limiter
    MultiLimiter,
    
    # Исключения
    RateLimitExceeded,
    QuotaExceeded,
    
    # Результат
    RateLimitResult,
    
    # Утилиты
    get_client_key,
    get_endpoint_key,
    rate_limit_middleware,
)


# =============================================
# Leader Election
# =============================================
from app.utils.leader_election import (
    # Основной класс
    LeaderElection,
    HealthCheckingLeaderElection,
    
    # Статусы
    LeadershipStatus,
    
    # Исключения
    LeaderElectionError,
    NotLeaderError,
    LockAcquisitionError,
    
    # Реестр
    LeaderElectionRegistry,
    
    # Task Runner
    LeaderTaskRunner,
    
    # Контекстный менеджер
    leader_context,
    
    # Утилиты
    run_as_leader,
    get_or_create_leader,
)


# =============================================
# Task Registry
# =============================================
from app.utils.task_registry import (
    # Основной класс
    TaskRegistry,
    
    # Статусы и приоритеты
    TaskStatus,
    TaskPriority,
    
    # Информация о задаче
    TaskInfo,
    
    # Статистика
    RegistryStats,
    
    # Глобальные функции
    get_task_registry,
    set_task_registry,
    register_task,
    cancel_task,
    cancel_tasks_by_campaign,
    get_active_task_count,
    get_task_info,
    list_active_tasks,
    
    # Декоратор
    tracked_task,
    
    # Контекстный менеджер
    task_group,
)


# =============================================
# Телефонные номера (российский план нумерации)
# =============================================
from app.utils.phone import (
    normalize_phone,
    validate_phone_number,
    format_phone_display,
)


# =============================================
# AMI Manager
# =============================================
# Реализация DialerManager (AMI/Originate через panoramisk) находится в
# app.services.dialer — это более высокоуровневый и единственный
# используемый вариант; здесь оставлен только флаг доступности panoramisk.
try:
    import panoramisk  # noqa: F401
    AMI_AVAILABLE = True
except ImportError:
    AMI_AVAILABLE = False


# =============================================
# Дополнительные утилиты
# =============================================
class AsyncRateLimiter:
    """
    Комбинированный асинхронный ограничитель скорости.
    
    Использует SlidingWindowRateLimiter для распределённого ограничения
    и TokenBucket для локального сглаживания.
    """
    
    def __init__(self, redis_client, rate: float, window: int = 60, key_prefix: str = "rate"):
        self.redis_limiter = SlidingWindowRateLimiter(redis_client)
        self.local_limiter = TokenBucket(rate=rate)
        self.rate = rate
        self.window = window
        self.key_prefix = key_prefix
    
    async def acquire(self, key: str, tokens: int = 1) -> bool:
        """Получить разрешение на выполнение"""
        # Проверяем локальный лимит
        if not await self.local_limiter.try_acquire(tokens):
            return False
        
        # Проверяем распределённый лимит
        redis_key = f"{self.key_prefix}:{key}"
        result = await self.redis_limiter.check(redis_key, limit=self.rate, window=self.window)
        
        return result.allowed
    
    async def wait_and_acquire(self, key: str, tokens: int = 1, timeout: float = None) -> bool:
        """Получить разрешение с ожиданием"""
        import time
        start = time.monotonic()
        
        while True:
            if await self.acquire(key, tokens):
                return True
            
            if timeout and (time.monotonic() - start) >= timeout:
                return False
            
            await asyncio.sleep(0.1)
    
    def get_status(self, key: str) -> Dict[str, Any]:
        """Получить статус лимитов"""
        return {
            "local": self.local_limiter.get_stats(),
            "redis": {"key": f"{self.key_prefix}:{key}"}
        }


class RetryHandler:
    """
    Обработчик повторных попыток с экспоненциальной задержкой.
    
    Использование:
        handler = RetryHandler(max_retries=3, base_delay=1.0)
        
        @handler.retry(on_exception=[ConnectionError, TimeoutError])
        async def unstable_operation():
            ...
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential: bool = True,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential = exponential
        self.jitter = jitter
    
    def calculate_delay(self, attempt: int) -> float:
        """Рассчитать задержку для попытки"""
        if self.exponential:
            delay = self.base_delay * (2 ** (attempt - 1))
        else:
            delay = self.base_delay * attempt
        
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            jitter_amount = delay * 0.1 * random.random()
            delay = delay + jitter_amount if random.random() > 0.5 else delay - jitter_amount
        
        return max(0.1, delay)
    
    def retry(self, on_exception: List[type] = None, on_result: callable = None):
        """
        Декоратор для повторных попыток.
        
        Args:
            on_exception: Список исключений, при которых повторять
            on_result: Функция проверки результата (True если нужно повторить)
        """
        import asyncio
        from functools import wraps
        
        on_exception = on_exception or [Exception]
        
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exception = None
                
                for attempt in range(1, self.max_retries + 1):
                    try:
                        result = await func(*args, **kwargs)
                        
                        # Проверяем результат
                        if on_result and on_result(result):
                            if attempt < self.max_retries:
                                delay = self.calculate_delay(attempt)
                                await asyncio.sleep(delay)
                                continue
                        
                        return result
                        
                    except tuple(on_exception) as e:
                        last_exception = e
                        
                        if attempt < self.max_retries:
                            delay = self.calculate_delay(attempt)
                            logger.debug(f"Повтор {attempt}/{self.max_retries} через {delay:.2f}с: {e}")
                            await asyncio.sleep(delay)
                        else:
                            raise
                
                if last_exception:
                    raise last_exception
                
                return None
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                import time
                last_exception = None
                
                for attempt in range(1, self.max_retries + 1):
                    try:
                        result = func(*args, **kwargs)
                        
                        if on_result and on_result(result):
                            if attempt < self.max_retries:
                                delay = self.calculate_delay(attempt)
                                time.sleep(delay)
                                continue
                        
                        return result
                        
                    except tuple(on_exception) as e:
                        last_exception = e
                        
                        if attempt < self.max_retries:
                            delay = self.calculate_delay(attempt)
                            logger.debug(f"Повтор {attempt}/{self.max_retries} через {delay:.2f}с: {e}")
                            time.sleep(delay)
                        else:
                            raise
                
                if last_exception:
                    raise last_exception
                
                return None
            
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper
        
        return decorator


# =============================================
# Импорт для корректной работы
# =============================================
import asyncio
import random
from typing import Dict, Any, List
from app.core.logger import logger


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "SyncCircuitBreaker",
    "CircuitState",
    "CircuitBreakerError",
    "CircuitOpenError",
    "CircuitTimeoutError",
    "CircuitStatistics",
    "CircuitBreakerRegistry",
    "circuit_registry",
    "circuit_breaker_decorator",
    "with_circuit_breaker",
    "check_all_circuits_health",
    
    # Rate Limiter
    "TokenBucket",
    "SlidingWindowRateLimiter",
    "FixedWindowRateLimiter",
    "LeakyBucketRateLimiter",
    "GlobalRateLimiter",
    "AdaptiveCPSLimiter",
    "QuotaManager",
    "MultiLimiter",
    "RateLimitExceeded",
    "QuotaExceeded",
    "RateLimitResult",
    "get_client_key",
    "get_endpoint_key",
    "rate_limit_middleware",
    
    # Leader Election
    "LeaderElection",
    "HealthCheckingLeaderElection",
    "LeadershipStatus",
    "LeaderElectionError",
    "NotLeaderError",
    "LockAcquisitionError",
    "LeaderElectionRegistry",
    "LeaderTaskRunner",
    "leader_context",
    "run_as_leader",
    "get_or_create_leader",
    
    # Task Registry
    "TaskRegistry",
    "TaskStatus",
    "TaskPriority",
    "TaskInfo",
    "RegistryStats",
    "get_task_registry",
    "set_task_registry",
    "register_task",
    "cancel_task",
    "cancel_tasks_by_campaign",
    "get_active_task_count",
    "get_task_info",
    "list_active_tasks",
    "tracked_task",
    "task_group",
    
    # Телефонные номера
    "normalize_phone",
    "validate_phone_number",
    "format_phone_display",

    # AMI
    "AMI_AVAILABLE",
    
    # Дополнительные утилиты
    "AsyncRateLimiter",
    "RetryHandler",
]
