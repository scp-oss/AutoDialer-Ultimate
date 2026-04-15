import time
import asyncio
from logger import logger

class TokenBucket:
    def __init__(self, rate: float):
        self.rate = rate
        self.tokens = rate
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_refill = now
            
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait)
                self.tokens = 0
                self.last_refill = time.monotonic()
            else:
                self.tokens -= 1

class GlobalRateLimiter:
    def __init__(self, redis_client, key: str, rate: float):
        self.redis = redis_client
        self.key = key
        self.rate = rate
        self._lua = """
            local key = KEYS[1]
            local rate = tonumber(ARGV[1])
            local now = tonumber(ARGV[2])
            
            local current = redis.call('GET', key) or '0:0'
            local tokens, last = current:match('([^:]+):([^:]+)')
            tokens = tonumber(tokens)
            last = tonumber(last)
            
            local elapsed = now - last
            local new_tokens = math.min(rate, tokens + elapsed * rate)
            
            if new_tokens >= 1 then
                redis.call('SET', key, string.format('%.6f:%d', new_tokens - 1, now))
                redis.call('EXPIRE', key, 10)
                return 1
            else
                redis.call('SET', key, string.format('%.6f:%d', new_tokens, now))
                redis.call('EXPIRE', key, 10)
                return 0
            end
        """
    
    async def acquire(self) -> bool:
        result = await self.redis.eval(self._lua, 1, self.key, self.rate, time.time())
        return result == 1

SLIDING_WINDOW = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)

if count < limit then
    redis.call('ZADD', key, now, now .. ':' .. count)
    redis.call('EXPIRE', key, window)
    return {1, count + 1}
else
    return {0, count}
end
"""

class SlidingWindowRateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def check(self, key: str, limit: int = 100, window: int = 60) -> bool:
        result = await self.redis.eval(SLIDING_WINDOW, 1, key, window, limit, time.time())
        return result[0] == 1
