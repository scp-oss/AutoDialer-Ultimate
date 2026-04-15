"""
Database connection and utilities
"""

import os
import asyncpg
from typing import Optional, Any, List, Dict
from contextlib import asynccontextmanager
from logger import logger

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.config = {
            'host': os.getenv('DB_HOST', '127.0.0.1'),
            'port': int(os.getenv('DB_PORT', 5432)),
            'database': os.getenv('DB_NAME', 'autodialer'),
            'user': os.getenv('DB_USER', 'autodialer'),
            'password': os.getenv('DB_PASSWORD'),
            'min_size': 5,
            'max_size': 50,
            'command_timeout': 60,
            'max_queries': 50000,
            'max_inactive_connection_lifetime': 300
        }
    
    async def connect(self):
        """Create connection pool"""
        try:
            self.pool = await asyncpg.create_pool(**self.config)
            logger.info("Database connection pool created")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    async def disconnect(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool"""
        if not self.pool:
            raise Exception("Database not connected")
        
        async with self.pool.acquire() as conn:
            yield conn
    
    async def execute(self, query: str, *args) -> str:
        """Execute a query"""
        async with self.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        """Fetch multiple rows"""
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """Fetch a single row"""
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args) -> Any:
        """Fetch a single value"""
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    async def transaction(self):
        """Start a transaction"""
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn

# Global database instance
db = Database()
