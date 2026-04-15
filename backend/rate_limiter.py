#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rate Limiting Module
AutoDialer Ultimate v3.0.0

Предоставляет различные стратегии ограничения скорости:
- Token Bucket (локальный)
- Sliding Window (Redis)
- Fixed Window (Redis)
- Leaky Bucket (Redis)
- Global CPS Limiter
- Adaptive CPS с EMA сглаживанием
- Quota Manager
- Multi-Limiter

ВКЛЮЧЕНЫ ВСЕ ИСПРАВЛЕНИЯ:
- Adaptive CPS с EMA сглаживанием
- Минимальный CPS = 0.5
- Feedback loop (учёт успешности originate)
- Динамическое регулирование на основе очереди и активных каналов
- Защита от резких скачков (smoothing)
"""

import asyncio
import time
import hashlib
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List, Union
from enum import Enum
from dataclasses import dataclass, field

from logger import logger


# =============================================
# Rate Limit Exceptions
# =============================================
class RateLimitExceeded(Exception):
    """Исключение при превышении лимита."""
    
    def __init__(self, message: str, retry_after: float = 1.0):
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


class QuotaExceeded(Exception):
    """Исключение при превышении квоты."""
    
    def __init__(self, message: str, reset_at: Optional[datetime] = None):
        self.message = message
        self.reset_at = reset_at
        super().__init__(message)


# =============================================
# Rate Limit Result
# =============================================
@dataclass
class RateLimitResult:
    """Результат проверки лимита."""
    allowed: bool
    remaining: int
    reset_at: datetime
    retry_after: float = 0.0
    limit: int = 0
    current: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "remaining": self.remaining,
            "reset_at": self.reset_at.isoformat(),
            "retry_after": self.retry_after,
            "limit": self.limit,
            "current": self.current
        }


# =============================================
# Token Bucket (Local)
# =============================================
class TokenBucket:
    """
    Локальный token bucket rate limiter.
    
    Подходит для однопоточного ограничения скорости.
    Использует алгоритм token bucket для плавного ограничения.
    """
    
    def __init__(self, rate: float, capacity: Optional[float] = None):
        """
        Инициализация token bucket.
        
        Args:
            rate: Токенов в секунду
            capacity: Максимальное количество токенов (по умолчанию = rate)
        """
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        
        # Статистика
        self._stats = {
            'acquired': 0,
            'rejected': 0,
            'total_wait_time': 0.0
        }
    
    async def acquire(self, tokens: float = 1.0) -> bool:
        """
        Получить токены из корзины (с ожиданием).
        
        Args:
            tokens: Количество токенов
        
        Returns:
            True (всегда, может ожидать)
        """
        if tokens > self.capacity:
            raise ValueError(f"Нельзя получить больше capacity ({self.capacity})")
        
        async with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self._stats['acquired'] += 1
                return True
            
            # Расчёт времени ожидания
            needed = tokens - self.tokens
            wait_time = needed / self.rate
            
            self._stats['total_wait_time'] += wait_time
            
            await asyncio.sleep(wait_time)
            
            self._refill()
            self.tokens -= tokens
            self._stats['acquired'] += 1
            return True
    
    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """
        Попытаться получить токены без ожидания.
        
        Args:
            tokens: Количество токенов
        
        Returns:
            True если получено, False иначе
        """
        async with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self._stats['acquired'] += 1
                return True
            
            self._stats['rejected'] += 1
            return False
    
    def _refill(self):
        """Пополнение токенов на основе прошедшего времени."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def get_available_tokens(self) -> float:
        """Получить доступное количество токенов."""
        self._refill()
        return self.tokens
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику."""
        return {
            'rate': self.rate,
            'capacity': self.capacity,
            'available_tokens': self.get_available_tokens(),
            'acquired': self._stats['acquired'],
            'rejected': self._stats['rejected'],
            'avg_wait_time': self._stats['total_wait_time'] / max(1, self._stats['acquired'])
        }
    
    def reset(self):
        """Сбросить корзину до полной ёмкости."""
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
    
    def update_rate(self, new_rate: float):
        """Обновить скорость (CPS)."""
        self.rate = new_rate


# =============================================
# Sliding Window Rate Limiter (Redis)
# =============================================
class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter с использованием Redis sorted sets.
    
    Обеспечивает точное ограничение в распределённых системах.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Lua скрипт для атомарного sliding window
        self._lua_script = """
            local key = KEYS[1]
            local window = tonumber(ARGV[1])
            local limit = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            
            -- Удаляем устаревшие записи
            redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
            
            -- Считаем текущие
            local count = redis.call('ZCARD', key)
            
            if count < limit then
                -- Добавляем новую запись
                local member = now .. ':' .. count
                redis.call('ZADD', key, now, member)
                redis.call('EXPIRE', key, window)
                return {1, count + 1, limit - count - 1}
            else
                -- Получаем самую старую запись для retry-after
                local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
                local retry_after = 0
                if oldest[2] then
                    retry_after = tonumber(oldest[2]) + window - now
                end
                return {0, count, 0, retry_after}
            end
        """
        
        self._script = self.redis.register_script(self._lua_script)
    
    async def check(
        self,
        key: str,
        limit: int,
        window: int = 60
    ) -> RateLimitResult:
        """
        Проверить, находится ли запрос в пределах лимита.
        
        Args:
            key: Уникальный ключ (например, "rate:user:123")
            limit: Максимальное количество запросов в окне
            window: Временное окно в секундах
        
        Returns:
            RateLimitResult с деталями
        """
        redis_key = f"rate_limit:{key}"
        now = time.time()
        
        try:
            result = await self._script(
                keys=[redis_key],
                args=[window, limit, now]
            )
            
            allowed = result[0] == 1
            current = result[1]
            remaining = result[2] if allowed else 0
            retry_after = result[3] if len(result) > 3 else 0
            
            reset_at = datetime.fromtimestamp(now + window)
            
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=max(0.1, retry_after),
                limit=limit,
                current=current
            )
            
        except Exception as e:
            logger.error(f"Sliding window rate limit check failed: {e}")
            # Fail open
            return RateLimitResult(
                allowed=True,
                remaining=limit - 1,
                reset_at=datetime.now() + timedelta(seconds=window),
                limit=limit,
                current=0
            )
    
    async def get_status(self, key: str, window: int = 60) -> Dict[str, Any]:
        """Получить текущий статус без потребления."""
        redis_key = f"rate_limit:{key}"
        now = time.time()
        
        await self.redis.zremrangebyscore(redis_key, 0, now - window)
        count = await self.redis.zcard(redis_key)
        
        return {
            'key': key,
            'current': count,
            'window': window,
            'oldest_timestamp': await self.redis.zrange(redis_key, 0, 0, withscores=True)
        }
    
    async def reset(self, key: str):
        """Сбросить лимит для ключа."""
        redis_key = f"rate_limit:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Fixed Window Rate Limiter (Redis)
# =============================================
class FixedWindowRateLimiter:
    """
    Fixed window rate limiter с использованием Redis.
    
    Проще чем sliding window, но может пропускать всплески на границах окон.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        self._lua_script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            
            local current = redis.call('GET', key)
            
            if current == false then
                redis.call('SETEX', key, window, 1)
                return {1, limit - 1, window}
            end
            
            current = tonumber(current)
            if current < limit then
                local ttl = redis.call('TTL', key)
                redis.call('INCR', key)
                return {1, limit - current - 1, ttl}
            else
                local ttl = redis.call('TTL', key)
                return {0, 0, ttl}
            end
        """
        
        self._script = self.redis.register_script(self._lua_script)
    
    async def check(
        self,
        key: str,
        limit: int,
        window: int = 60
    ) -> RateLimitResult:
        """Проверить лимит."""
        redis_key = f"fixed_rate:{key}"
        
        try:
            result = await self._script(
                keys=[redis_key],
                args=[limit, window]
            )
            
            allowed = result[0] == 1
            remaining = result[1]
            ttl = result[2]
            
            reset_at = datetime.now() + timedelta(seconds=ttl)
            
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=ttl if not allowed else 0,
                limit=limit,
                current=limit - remaining - 1 if allowed else limit
            )
            
        except Exception as e:
            logger.error(f"Fixed window rate limit check failed: {e}")
            return RateLimitResult(
                allowed=True,
                remaining=limit - 1,
                reset_at=datetime.now() + timedelta(seconds=window),
                limit=limit,
                current=0
            )
    
    async def get_remaining(self, key: str, limit: int) -> int:
        """Получить оставшиеся запросы без потребления."""
        redis_key = f"fixed_rate:{key}"
        current = await self.redis.get(redis_key)
        
        if current is None:
            return limit
        
        return max(0, limit - int(current))
    
    async def reset(self, key: str):
        """Сбросить лимит."""
        redis_key = f"fixed_rate:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Leaky Bucket (Redis)
# =============================================
class LeakyBucketRateLimiter:
    """
    Leaky bucket rate limiter с использованием Redis.
    
    Обрабатывает запросы с постоянной скоростью, очередь избыточных.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        self._lua_script = """
            local key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local rate = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local requested = tonumber(ARGV[4])
            
            -- Получаем текущее состояние
            local state = redis.call('HMGET', key, 'water', 'last_update')
            local water = tonumber(state[1]) or 0
            local last_update = tonumber(state[2]) or now
            
            -- Вычисляем утечку
            local elapsed = now - last_update
            local leaked = elapsed * rate
            water = math.max(0, water - leaked)
            
            -- Проверяем, помещается ли запрос
            if water + requested <= capacity then
                water = water + requested
                redis.call('HMSET', key, 'water', water, 'last_update', now)
                redis.call('EXPIRE', key, math.ceil(capacity / rate) + 10)
                return {1, capacity - water}
            else
                return {0, capacity - water}
            end
        """
        
        self._script = self.redis.register_script(self._lua_script)
    
    async def check(
        self,
        key: str,
        capacity: int,
        rate: float,
        requested: int = 1
    ) -> Tuple[bool, float]:
        """
        Проверить, помещается ли запрос в корзину.
        
        Args:
            key: Уникальный ключ
            capacity: Максимальная ёмкость
            rate: Скорость утечки (единиц в секунду)
            requested: Запрошенное количество
        
        Returns:
            (allowed, remaining_capacity)
        """
        redis_key = f"leaky:{key}"
        now = time.time()
        
        try:
            result = await self._script(
                keys=[redis_key],
                args=[capacity, rate, now, requested]
            )
            
            return result[0] == 1, result[1]
            
        except Exception as e:
            logger.error(f"Leaky bucket check failed: {e}")
            return True, capacity - requested
    
    async def get_water_level(self, key: str, capacity: int, rate: float) -> float:
        """Получить текущий уровень воды."""
        redis_key = f"leaky:{key}"
        state = await self.redis.hmget(redis_key, 'water', 'last_update')
        
        water = float(state[0]) if state[0] else 0.0
        last_update = float(state[1]) if state[1] else time.time()
        
        elapsed = time.time() - last_update
        leaked = elapsed * rate
        
        return max(0, water - leaked)
    
    async def reset(self, key: str):
        """Сбросить корзину."""
        redis_key = f"leaky:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Global CPS Limiter
# =============================================
class GlobalRateLimiter:
    """
    Глобальный ограничитель CPS (Calls Per Second).
    
    Использует Redis для координации между экземплярами.
    """
    
    def __init__(self, redis_client, key: str, rate: float, burst: Optional[float] = None):
        """
        Инициализация глобального ограничителя.
        
        Args:
            redis_client: Клиент Redis
            key: Уникальный ключ
            rate: Токенов в секунду
            burst: Максимальный размер всплеска (по умолчанию = rate)
        """
        self.redis = redis_client
        self.key = f"global_rate:{key}"
        self.rate = rate
        self.burst = burst or rate
        
        self._lua_script = """
            local key = KEYS[1]
            local rate = tonumber(ARGV[1])
            local burst = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local requested = tonumber(ARGV[4])
            
            local current = redis.call('GET', key)
            local tokens, last_update
            
            if current then
                local parts = {}
                for part in string.gmatch(current, '[^:]+') do
                    table.insert(parts, part)
                end
                tokens = tonumber(parts[1])
                last_update = tonumber(parts[2])
            else
                tokens = burst
                last_update = now
            end
            
            -- Вычисляем пополнение
            local elapsed = now - last_update
            local new_tokens = math.min(burst, tokens + elapsed * rate)
            
            if new_tokens >= requested then
                new_tokens = new_tokens - requested
                redis.call('SET', key, string.format('%.6f:%d', new_tokens, now))
                redis.call('EXPIRE', key, math.ceil(burst / rate) + 10)
                return {1, new_tokens}
            else
                local wait_time = (requested - new_tokens) / rate
                redis.call('SET', key, string.format('%.6f:%d', new_tokens, now))
                redis.call('EXPIRE', key, math.ceil(burst / rate) + 10)
                return {0, new_tokens, wait_time}
            end
        """
        
        self._script = self.redis.register_script(self._lua_script)
    
    async def acquire(self, tokens: float = 1.0) -> bool:
        """Получить токены без ожидания."""
        try:
            result = await self._script(
                keys=[self.key],
                args=[self.rate, self.burst, time.time(), tokens]
            )
            return result[0] == 1
        except Exception as e:
            logger.error(f"Global rate limiter failed: {e}")
            return True  # Fail open
    
    async def acquire_with_wait(self, tokens: float = 1.0, max_wait: float = 5.0) -> bool:
        """Получить токены с ожиданием."""
        start_time = time.time()
        
        while True:
            result = await self._script(
                keys=[self.key],
                args=[self.rate, self.burst, time.time(), tokens]
            )
            
            if result[0] == 1:
                return True
            
            wait_time = result[2] if len(result) > 2 else 0.1
            wait_time = min(wait_time, max_wait - (time.time() - start_time))
            
            if wait_time <= 0:
                return False
            
            await asyncio.sleep(wait_time)
    
    async def get_available_tokens(self) -> float:
        """Получить доступное количество токенов."""
        current = await self.redis.get(self.key)
        
        if not current:
            return self.burst
        
        parts = current.split(':')
        tokens = float(parts[0])
        last_update = float(parts[1])
        
        elapsed = time.time() - last_update
        new_tokens = min(self.burst, tokens + elapsed * self.rate)
        
        return new_tokens
    
    async def reset(self):
        """Сбросить ограничитель."""
        await self.redis.delete(self.key)


# =============================================
# Adaptive CPS Limiter (🔥 КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ)
# =============================================
class AdaptiveCPSLimiter:
    """
    Адаптивный ограничитель CPS с обратной связью.
    
    Особенности:
    - EMA сглаживание для избежания резких скачков
    - Минимальный CPS = 0.5 (защита от полной остановки)
    - Учёт успешности originate (feedback loop)
    - Динамическое регулирование на основе очереди и активных каналов
    """
    
    def __init__(
        self,
        base_rate: float,
        redis_client,
        max_calls: int = 50,
        min_rate: float = 0.5,
        alpha: float = 0.3
    ):
        """
        Инициализация адаптивного CPS ограничителя.
        
        Args:
            base_rate: Базовая скорость (CPS)
            redis_client: Клиент Redis
            max_calls: Максимальное количество одновременных каналов
            min_rate: Минимальная скорость (защита от полной остановки)
            alpha: Коэффициент сглаживания EMA (0 < alpha <= 1)
        """
        self.base_rate = base_rate
        self.redis = redis_client
        self.max_calls = max_calls
        self.min_rate = min_rate
        self.alpha = alpha
        
        # Текущая скорость и EMA
        self.current_rate = base_rate
        self.ema_rate = base_rate
        
        # Feedback loop: успешность originate (EWMA)
        self.success_rate = 1.0
        self._success_alpha = 0.1
        
        # Статистика
        self._stats = {
            'adjustments': 0,
            'min_rate_seen': base_rate,
            'max_rate_seen': base_rate
        }
        
        logger.info(f"AdaptiveCPSLimiter initialized: base={base_rate}, max_calls={max_calls}, min={min_rate}")
    
    async def get_rate(self) -> float:
        """
        Получить текущую рекомендованную скорость.
        
        Учитывает:
        - Размер очереди
        - Количество активных каналов
        - Успешность originate
        """
        try:
            queue_size = await self.redis.llen("dial_queue")
            active_calls = await self.redis.scard("active_channels")
        except Exception as e:
            logger.error(f"Failed to get metrics for CPS: {e}")
            return self.ema_rate
        
        # 🔥 Расчёт целевой скорости на основе очереди
        if self.success_rate < 0.5:
            # Много ошибок originate — сильно снижаем
            target_rate = self.base_rate * 0.3
            reason = "low_success_rate"
        elif queue_size > 1000:
            target_rate = self.base_rate * 0.2
            reason = "queue_gt_1000"
        elif queue_size > 500:
            target_rate = self.base_rate * 0.4
            reason = "queue_gt_500"
        elif queue_size > 100:
            target_rate = self.base_rate * 0.7
            reason = "queue_gt_100"
        elif queue_size > 50:
            target_rate = self.base_rate * 0.85
            reason = "queue_gt_50"
        else:
            target_rate = self.base_rate
            reason = "normal"
        
        # 🔥 Учёт доступных слотов (не превышаем)
        available_slots = self.max_calls - active_calls
        max_safe_cps = max(self.min_rate, available_slots / 5)  # 5 секунд на заполнение
        
        target_rate = max(self.min_rate, min(target_rate, max_safe_cps))
        
        # 🔥 EMA сглаживание для избежания резких скачков
        self.ema_rate = self.alpha * target_rate + (1 - self.alpha) * self.ema_rate
        self.current_rate = self.ema_rate
        
        # Обновляем статистику
        self._stats['adjustments'] += 1
        self._stats['min_rate_seen'] = min(self._stats['min_rate_seen'], self.current_rate)
        self._stats['max_rate_seen'] = max(self._stats['max_rate_seen'], self.current_rate)
        
        # Логируем изменения
        if abs(self.current_rate - self.base_rate) > self.base_rate * 0.1:
            logger.debug(
                f"CPS adjusted: {self.current_rate:.2f} (target={target_rate:.2f}, "
                f"reason={reason}, queue={queue_size}, active={active_calls}, "
                f"success_rate={self.success_rate:.2f})"
            )
        
        return self.current_rate
    
    def record_success(self):
        """Записать успешный originate."""
        self.success_rate = (1 - self._success_alpha) * self.success_rate + self._success_alpha * 1.0
    
    def record_failure(self):
        """Записать неудачный originate."""
        self.success_rate = (1 - self._success_alpha) * self.success_rate + self._success_alpha * 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику."""
        return {
            'base_rate': self.base_rate,
            'current_rate': round(self.current_rate, 2),
            'ema_rate': round(self.ema_rate, 2),
            'success_rate': round(self.success_rate, 2),
            'min_rate': self.min_rate,
            'adjustments': self._stats['adjustments'],
            'min_rate_seen': round(self._stats['min_rate_seen'], 2),
            'max_rate_seen': round(self._stats['max_rate_seen'], 2)
        }
    
    def reset(self):
        """Сбросить состояние."""
        self.current_rate = self.base_rate
        self.ema_rate = self.base_rate
        self.success_rate = 1.0


# =============================================
# Quota Manager
# =============================================
class QuotaManager:
    """
    Управление квотами (дневные, месячные лимиты).
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        self._lua_script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local increment = tonumber(ARGV[3])
            
            local current = redis.call('GET', key)
            
            if current == false then
                redis.call('SETEX', key, window, increment)
                return {1, limit - increment}
            end
            
            current = tonumber(current)
            if current < limit then
                local new_value = redis.call('INCRBY', key, increment)
                return {1, limit - new_value}
            else
                local ttl = redis.call('TTL', key)
                return {0, 0, ttl}
            end
        """
        
        self._script = self.redis.register_script(self._lua_script)
    
    async def check_and_increment(
        self,
        key: str,
        limit: int,
        window: int,
        increment: int = 1
    ) -> RateLimitResult:
        """
        Проверить квоту и увеличить использование.
        
        Args:
            key: Ключ квоты (например, "daily_calls:user:123")
            limit: Максимально разрешённое количество
            window: Временное окно в секундах
            increment: На сколько увеличить
        
        Returns:
            RateLimitResult
        """
        redis_key = f"quota:{key}"
        
        try:
            result = await self._script(
                keys=[redis_key],
                args=[limit, window, increment]
            )
            
            allowed = result[0] == 1
            remaining = result[1] if allowed else 0
            ttl = result[2] if len(result) > 2 else window
            
            reset_at = datetime.now() + timedelta(seconds=ttl)
            
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=reset_at,
                limit=limit,
                current=limit - remaining
            )
            
        except Exception as e:
            logger.error(f"Quota check failed: {e}")
            return RateLimitResult(
                allowed=True,
                remaining=limit - increment,
                reset_at=datetime.now() + timedelta(seconds=window),
                limit=limit,
                current=0
            )
    
    async def get_usage(self, key: str, limit: int) -> Dict[str, Any]:
        """Получить текущее использование квоты."""
        redis_key = f"quota:{key}"
        current = await self.redis.get(redis_key)
        ttl = await self.redis.ttl(redis_key)
        
        usage = int(current) if current else 0
        
        return {
            'key': key,
            'limit': limit,
            'used': usage,
            'remaining': max(0, limit - usage),
            'reset_in': ttl if ttl > 0 else 0,
            'usage_percent': round((usage / limit * 100) if limit > 0 else 0, 2)
        }
    
    async def reset(self, key: str):
        """Сбросить квоту."""
        redis_key = f"quota:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Multi-Limiter
# =============================================
class MultiLimiter:
    """
    Комбинирует несколько ограничителей.
    
    Запрос проходит только если все ограничители разрешают.
    """
    
    def __init__(self):
        self._limiters: List[Tuple[str, Any, Dict]] = []
    
    def add_limiter(self, name: str, limiter: Any, **kwargs):
        """Добавить ограничитель в цепочку."""
        self._limiters.append((name, limiter, kwargs))
    
    async def check(self, key: str) -> RateLimitResult:
        """
        Проверить все ограничители.
        
        Returns:
            Самый строгий результат.
        """
        most_restrictive: Optional[RateLimitResult] = None
        
        for name, limiter, kwargs in self._limiters:
            limiter_key = f"{name}:{key}"
            
            if isinstance(limiter, SlidingWindowRateLimiter):
                result = await limiter.check(limiter_key, **kwargs)
            elif isinstance(limiter, FixedWindowRateLimiter):
                result = await limiter.check(limiter_key, **kwargs)
            elif isinstance(limiter, GlobalRateLimiter):
                allowed = await limiter.acquire(**kwargs)
                result = RateLimitResult(
                    allowed=allowed,
                    remaining=0,
                    reset_at=datetime.now(),
                    limit=0,
                    current=0
                )
            elif isinstance(limiter, AdaptiveCPSLimiter):
                rate = await limiter.get_rate()
                result = RateLimitResult(
                    allowed=True,
                    remaining=int(rate),
                    reset_at=datetime.now(),
                    limit=int(limiter.base_rate),
                    current=0
                )
            else:
                continue
            
            if not result.allowed:
                return result
            
            if most_restrictive is None or result.remaining < most_restrictive.remaining:
                most_restrictive = result
        
        return most_restrictive or RateLimitResult(
            allowed=True,
            remaining=-1,
            reset_at=datetime.now(),
            limit=-1,
            current=0
        )


# =============================================
# Utility Functions
# =============================================
def get_client_key(ip: str, user_id: Optional[int] = None) -> str:
    """Сгенерировать ключ для клиента."""
    if user_id:
        return f"user:{user_id}"
    
    # Хешируем IP для приватности
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    return f"ip:{ip_hash}"


def get_endpoint_key(endpoint: str, client_key: str) -> str:
    """Сгенерировать ключ для эндпоинта + клиента."""
    return f"{endpoint}:{client_key}"


# =============================================
# Rate Limit Middleware (для FastAPI)
# =============================================
async def rate_limit_middleware(
    request,
    limiter: SlidingWindowRateLimiter,
    limit: int = 100,
    window: int = 60
):
    """
    Middleware для ограничения частоты запросов.
    
    Usage:
        app.add_middleware(rate_limit_middleware, limiter=limiter, limit=100)
    """
    client_ip = request.client.host if request.client else "unknown"
    
    # Используем X-Forwarded-For если запрос от доверенного прокси
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded:
        client_ip = forwarded
    
    path = request.url.path
    key = get_endpoint_key(path, get_client_key(client_ip))
    
    result = await limiter.check(key, limit, window)
    
    if not result.allowed:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(result.reset_at.timestamp())),
                "Retry-After": str(int(result.retry_after))
            }
        )
    
    return result
