import asyncio
import socket
from logger import logger

class LeaderElection:
    def __init__(self, redis_client, lock_key: str, ttl: int = 60):
        self.redis = redis_client
        self.lock_key = lock_key
        self.ttl = ttl
        self.is_leader = False
        self.hostname = socket.gethostname()
    
    async def try_acquire(self) -> bool:
        acquired = await self.redis.set(
            self.lock_key,
            self.hostname,
            ex=self.ttl,
            nx=True
        )
        self.is_leader = acquired
        if acquired:
            logger.info(f"Acquired leadership: {self.lock_key}")
        return acquired
    
    async def renew(self):
        if self.is_leader:
            await self.redis.expire(self.lock_key, self.ttl)
    
    async def release(self):
        if self.is_leader:
            await self.redis.delete(self.lock_key)
            logger.info(f"Released leadership: {self.lock_key}")
            self.is_leader = False
