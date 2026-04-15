#!/usr/bin/env python3
"""
Rate Limiting Module
AutoDialer Ultimate v3.0.0

Provides various rate limiting strategies:
- Token Bucket (local)
- Sliding Window (Redis)
- Fixed Window (Redis)
- Leaky Bucket (Redis)
- Global CPS Limiter
"""

import asyncio
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from enum import Enum
from dataclasses import dataclass, field

from logger import logger


# =============================================
# Rate Limit Exceptions
# =============================================
class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded"""
    
    def __init__(self, message: str, retry_after: float = 1.0):
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


class QuotaExceeded(Exception):
    """Raised when quota is exceeded"""
    
    def __init__(self, message: str, reset_at: Optional[datetime] = None):
        self.message = message
        self.reset_at = reset_at
        super().__init__(message)


# =============================================
# Rate Limit Result
# =============================================
@dataclass
class RateLimitResult:
    """Result of a rate limit check"""
    allowed: bool
    remaining: int
    reset_at: datetime
    retry_after: float = 0.0
    limit: int = 0
    current: int = 0


# =============================================
# Token Bucket (Local)
# =============================================
class TokenBucket:
    """
    Local token bucket rate limiter.
    
    Suitable for single-instance rate limiting.
    Uses the token bucket algorithm for smooth rate limiting.
    """
    
    def __init__(self, rate: float, capacity: Optional[float] = None):
        """
        Initialize token bucket.
        
        Args:
            rate: Tokens per second
            capacity: Maximum tokens (defaults to rate)
        """
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        
        # Statistics
        self._stats = {
            'acquired': 0,
            'rejected': 0,
            'total_wait_time': 0.0
        }
    
    async def acquire(self, tokens: float = 1.0) -> bool:
        """
        Acquire tokens from the bucket.
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            True if acquired (always true, may wait)
        """
        if tokens > self.capacity:
            raise ValueError(f"Cannot acquire more than capacity ({self.capacity})")
        
        async with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self._stats['acquired'] += 1
                return True
            
            # Calculate wait time
            needed = tokens - self.tokens
            wait_time = needed / self.rate
            
            self._stats['total_wait_time'] += wait_time
            
            # Wait for tokens
            await asyncio.sleep(wait_time)
            
            self._refill()
            self.tokens -= tokens
            self._stats['acquired'] += 1
            return True
    
    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            True if acquired, False otherwise
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
        """Refill tokens based on elapsed time"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def get_available_tokens(self) -> float:
        """Get currently available tokens"""
        self._refill()
        return self.tokens
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bucket statistics"""
        return {
            'rate': self.rate,
            'capacity': self.capacity,
            'available_tokens': self.get_available_tokens(),
            'acquired': self._stats['acquired'],
            'rejected': self._stats['rejected'],
            'avg_wait_time': self._stats['total_wait_time'] / max(1, self._stats['acquired'])
        }
    
    def reset(self):
        """Reset the bucket to full capacity"""
        self.tokens = self.capacity
        self.last_refill = time.monotonic()


# =============================================
# Sliding Window Rate Limiter (Redis)
# =============================================
class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter using Redis sorted sets.
    
    Provides accurate rate limiting across distributed instances.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Lua script for atomic sliding window check
        self._lua_script = """
            local key = KEYS[1]
            local window = tonumber(ARGV[1])
            local limit = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            
            -- Remove expired entries
            redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
            
            -- Count current entries
            local count = redis.call('ZCARD', key)
            
            if count < limit then
                -- Add new entry with unique score
                local member = now .. ':' .. count
                redis.call('ZADD', key, now, member)
                redis.call('EXPIRE', key, window)
                return {1, count + 1, limit - count - 1}
            else
                -- Get oldest entry to calculate retry-after
                local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
                local retry_after = 0
                if oldest[2] then
                    retry_after = tonumber(oldest[2]) + window - now
                end
                return {0, count, 0, retry_after}
            end
        """
        
        # Register script
        self._script = self.redis.register_script(self._lua_script)
    
    async def check(
        self,
        key: str,
        limit: int,
        window: int = 60
    ) -> RateLimitResult:
        """
        Check if request is within rate limit.
        
        Args:
            key: Unique key for the limit (e.g., "rate:user:123")
            limit: Maximum requests in the window
            window: Time window in seconds
        
        Returns:
            RateLimitResult with details
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
            logger.error(f"Rate limit check failed: {e}")
            # Fail open
            return RateLimitResult(
                allowed=True,
                remaining=limit - 1,
                reset_at=datetime.now() + timedelta(seconds=window),
                limit=limit,
                current=0
            )
    
    async def get_status(self, key: str, window: int = 60) -> Dict[str, Any]:
        """Get current rate limit status without consuming"""
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
        """Reset rate limit for a key"""
        redis_key = f"rate_limit:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Fixed Window Rate Limiter (Redis)
# =============================================
class FixedWindowRateLimiter:
    """
    Fixed window rate limiter using Redis.
    
    Simpler than sliding window but may allow bursts at window boundaries.
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
        """
        Check if request is within rate limit.
        """
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
        """Get remaining requests without consuming"""
        redis_key = f"fixed_rate:{key}"
        current = await self.redis.get(redis_key)
        
        if current is None:
            return limit
        
        return max(0, limit - int(current))
    
    async def reset(self, key: str):
        """Reset rate limit for a key"""
        redis_key = f"fixed_rate:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Leaky Bucket (Redis)
# =============================================
class LeakyBucketRateLimiter:
    """
    Leaky bucket rate limiter using Redis.
    
    Processes requests at a constant rate, queues excess.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        self._lua_script = """
            local key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local rate = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local requested = tonumber(ARGV[4])
            
            -- Get current state
            local state = redis.call('HMGET', key, 'water', 'last_update')
            local water = tonumber(state[1]) or 0
            local last_update = tonumber(state[2]) or now
            
            -- Calculate leakage
            local elapsed = now - last_update
            local leaked = elapsed * rate
            water = math.max(0, water - leaked)
            
            -- Check if request fits
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
        Check if request fits in the bucket.
        
        Args:
            key: Unique key
            capacity: Maximum bucket capacity
            rate: Leak rate (units per second)
            requested: Requested units
        
        Returns:
            Tuple of (allowed, remaining_capacity)
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
        """Get current water level"""
        redis_key = f"leaky:{key}"
        state = await self.redis.hmget(redis_key, 'water', 'last_update')
        
        water = float(state[0]) if state[0] else 0.0
        last_update = float(state[1]) if state[1] else time.time()
        
        elapsed = time.time() - last_update
        leaked = elapsed * rate
        
        return max(0, water - leaked)
    
    async def reset(self, key: str):
        """Reset leaky bucket"""
        redis_key = f"leaky:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Global CPS Limiter
# =============================================
class GlobalRateLimiter:
    """
    Global rate limiter for CPS (Calls Per Second).
    
    Uses Redis to coordinate rate limiting across multiple instances.
    """
    
    def __init__(self, redis_client, key: str, rate: float, burst: Optional[float] = None):
        """
        Initialize global rate limiter.
        
        Args:
            redis_client: Redis client
            key: Unique key for this limiter
            rate: Tokens per second
            burst: Maximum burst size (defaults to rate)
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
            
            -- Calculate refill
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
        """
        Acquire tokens from the global limiter.
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            True if acquired, False otherwise
        """
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
        """
        Acquire tokens, waiting if necessary.
        
        Args:
            tokens: Number of tokens to acquire
            max_wait: Maximum time to wait in seconds
        
        Returns:
            True if acquired within timeout, False otherwise
        """
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
        """Get currently available tokens"""
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
        """Reset the global limiter"""
        await self.redis.delete(self.key)


# =============================================
# Quota Manager
# =============================================
class QuotaManager:
    """
    Manage usage quotas (daily, monthly limits).
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
        window: int,  # seconds
        increment: int = 1
    ) -> RateLimitResult:
        """
        Check quota and increment usage.
        
        Args:
            key: Quota key (e.g., "daily_calls:user:123")
            limit: Maximum allowed in window
            window: Time window in seconds
            increment: Amount to increment
        
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
        """Get current quota usage"""
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
            'usage_percent': (usage / limit * 100) if limit > 0 else 0
        }
    
    async def reset(self, key: str):
        """Reset quota for a key"""
        redis_key = f"quota:{key}"
        await self.redis.delete(redis_key)


# =============================================
# Multi-Limiter
# =============================================
class MultiLimiter:
    """
    Combine multiple rate limiters.
    
    Request passes only if all limiters allow it.
    """
    
    def __init__(self):
        self._limiters: List[Tuple[str, Any, Dict]] = []
    
    def add_limiter(self, name: str, limiter: Any, **kwargs):
        """Add a limiter to the chain"""
        self._limiters.append((name, limiter, kwargs))
    
    async def check(self, key: str) -> RateLimitResult:
        """
        Check all limiters.
        
        Returns the most restrictive result.
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
    """Generate a consistent key for a client"""
    if user_id:
        return f"user:{user_id}"
    
    # Hash IP for privacy
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    return f"ip:{ip_hash}"


def get_endpoint_key(endpoint: str, client_key: str) -> str:
    """Generate a key for an endpoint + client"""
    return f"{endpoint}:{client_key}"


async def rate_limit_middleware(
    request,
    limiter: SlidingWindowRateLimiter,
    limit: int = 100,
    window: int = 60
):
    """FastAPI-compatible rate limiting middleware"""
    client_ip = request.client.host
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
