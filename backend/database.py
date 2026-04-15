#!/usr/bin/env python3
"""
Database Module - PostgreSQL Connection Pool and Utilities
AutoDialer Ultimate v3.0.0
"""

import asyncio
import asyncpg
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Any, List, Dict, Union, AsyncGenerator
from contextlib import asynccontextmanager

from logger import logger


# =============================================
# Database Configuration
# =============================================
class DatabaseConfig:
    """Database configuration from environment"""
    
    @staticmethod
    def from_env() -> dict:
        """Load configuration from environment variables"""
        return {
            'host': os.getenv('DB_HOST', '127.0.0.1'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'database': os.getenv('DB_NAME', 'autodialer'),
            'user': os.getenv('DB_USER', 'autodialer'),
            'password': os.getenv('DB_PASSWORD', ''),
            'min_size': int(os.getenv('DB_POOL_MIN_SIZE', '5')),
            'max_size': int(os.getenv('DB_POOL_MAX_SIZE', '50')),
            'max_queries': int(os.getenv('DB_MAX_QUERIES', '50000')),
            'max_inactive_connection_lifetime': int(os.getenv('DB_MAX_INACTIVE_LIFETIME', '300')),
            'command_timeout': int(os.getenv('DB_COMMAND_TIMEOUT', '60')),
            'statement_cache_size': int(os.getenv('DB_STATEMENT_CACHE_SIZE', '100')),
        }


# =============================================
# Connection Pool Manager
# =============================================
class ConnectionPool:
    """Manage asyncpg connection pool with health checks"""
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or DatabaseConfig.from_env()
        self.pool: Optional[asyncpg.Pool] = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._last_health_check: Optional[datetime] = None
        self._health_check_interval = 30  # seconds
        self._stats = {
            'total_acquires': 0,
            'total_releases': 0,
            'total_queries': 0,
            'total_errors': 0,
            'last_error': None,
            'last_error_time': None
        }
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self.pool is not None
    
    async def connect(self) -> None:
        """Create connection pool"""
        async with self._lock:
            if self.pool:
                logger.warning("Connection pool already exists")
                return
            
            try:
                # Validate required config
                if not self.config.get('password'):
                    raise ValueError("Database password is required")
                
                logger.info(f"Connecting to database at {self.config['host']}:{self.config['port']}/{self.config['database']}")
                
                self.pool = await asyncpg.create_pool(
                    host=self.config['host'],
                    port=self.config['port'],
                    database=self.config['database'],
                    user=self.config['user'],
                    password=self.config['password'],
                    min_size=self.config.get('min_size', 5),
                    max_size=self.config.get('max_size', 50),
                    max_queries=self.config.get('max_queries', 50000),
                    max_inactive_connection_lifetime=self.config.get('max_inactive_connection_lifetime', 300),
                    command_timeout=self.config.get('command_timeout', 60),
                    statement_cache_size=self.config.get('statement_cache_size', 100),
                    server_settings={
                        'application_name': 'autodialer',
                        'timezone': 'UTC',
                        'client_encoding': 'UTF8'
                    }
                )
                
                # Test connection
                async with self.pool.acquire() as conn:
                    version = await conn.fetchval("SELECT version()")
                    logger.info(f"Connected to PostgreSQL: {version[:50]}...")
                
                self._connected = True
                self._last_health_check = datetime.now()
                
                # Start health check task
                asyncio.create_task(self._health_check_loop())
                
                logger.info(f"Database connection pool created (min={self.config.get('min_size', 5)}, max={self.config.get('max_size', 50)})")
                
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                self._stats['total_errors'] += 1
                self._stats['last_error'] = str(e)
                self._stats['last_error_time'] = datetime.now()
                raise
    
    async def disconnect(self) -> None:
        """Close connection pool"""
        async with self._lock:
            if self.pool:
                try:
                    await asyncio.wait_for(self.pool.close(), timeout=10.0)
                    logger.info("Database connection pool closed")
                except asyncio.TimeoutError:
                    logger.warning("Pool close timeout, forcing termination")
                    self.pool.terminate()
                finally:
                    self.pool = None
                    self._connected = False
    
    async def _health_check_loop(self) -> None:
        """Periodic health check of the connection pool"""
        while self._connected:
            await asyncio.sleep(self._health_check_interval)
            
            if not self.pool:
                continue
            
            try:
                async with self.pool.acquire() as conn:
                    await asyncio.wait_for(conn.execute("SELECT 1"), timeout=5.0)
                self._last_health_check = datetime.now()
                logger.debug("Database health check passed")
            except Exception as e:
                logger.warning(f"Database health check failed: {e}")
                self._stats['total_errors'] += 1
                self._stats['last_error'] = str(e)
                self._stats['last_error_time'] = datetime.now()
    
    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Acquire a connection from the pool"""
        if not self.pool:
            raise RuntimeError("Database not connected")
        
        self._stats['total_acquires'] += 1
        
        try:
            async with self.pool.acquire() as conn:
                yield conn
        except Exception as e:
            self._stats['total_errors'] += 1
            self._stats['last_error'] = str(e)
            self._stats['last_error_time'] = datetime.now()
            raise
        finally:
            self._stats['total_releases'] += 1
    
    async def execute(self, query: str, *args) -> str:
        """Execute a query and return status"""
        self._stats['total_queries'] += 1
        async with self.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def executemany(self, query: str, args_list: List[tuple]) -> None:
        """Execute a query multiple times"""
        self._stats['total_queries'] += len(args_list)
        async with self.acquire() as conn:
            await conn.executemany(query, args_list)
    
    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        """Fetch multiple rows"""
        self._stats['total_queries'] += 1
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """Fetch a single row"""
        self._stats['total_queries'] += 1
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args) -> Any:
        """Fetch a single value"""
        self._stats['total_queries'] += 1
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Start a transaction"""
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    def get_stats(self) -> dict:
        """Get pool statistics"""
        stats = self._stats.copy()
        
        if self.pool:
            try:
                stats['pool_size'] = len(self.pool._holders)
                stats['pool_free'] = len(self.pool._queue._queue) if hasattr(self.pool, '_queue') else 0
            except:
                stats['pool_size'] = 'unknown'
                stats['pool_free'] = 'unknown'
        
        stats['connected'] = self._connected
        stats['last_health_check'] = self._last_health_check.isoformat() if self._last_health_check else None
        
        return stats
    
    async def check_connection(self) -> bool:
        """Check if database connection is alive"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                await asyncio.wait_for(conn.execute("SELECT 1"), timeout=5.0)
            return True
        except Exception:
            return False


# =============================================
# Query Builder
# =============================================
class QueryBuilder:
    """Helper for building dynamic SQL queries"""
    
    def __init__(self, table: str):
        self.table = table
        self._select_fields = ["*"]
        self._where_conditions = []
        self._where_params = []
        self._order_by = []
        self._limit = None
        self._offset = None
        self._joins = []
        self._group_by = []
        self._having = []
    
    def select(self, fields: Union[str, List[str]]) -> 'QueryBuilder':
        """Set SELECT fields"""
        if isinstance(fields, str):
            self._select_fields = [f.strip() for f in fields.split(',')]
        else:
            self._select_fields = fields
        return self
    
    def where(self, condition: str, *params) -> 'QueryBuilder':
        """Add WHERE condition"""
        self._where_conditions.append(condition)
        self._where_params.extend(params)
        return self
    
    def where_if(self, condition: bool, sql: str, *params) -> 'QueryBuilder':
        """Add WHERE condition if condition is True"""
        if condition:
            self._where_conditions.append(sql)
            self._where_params.extend(params)
        return self
    
    def where_in(self, field: str, values: List[Any]) -> 'QueryBuilder':
        """Add WHERE IN condition"""
        if values:
            placeholders = ','.join([f'${i+1}' for i in range(len(values))])
            self._where_conditions.append(f"{field} IN ({placeholders})")
            self._where_params.extend(values)
        return self
    
    def join(self, table: str, on: str, join_type: str = "INNER") -> 'QueryBuilder':
        """Add JOIN clause"""
        self._joins.append(f"{join_type} JOIN {table} ON {on}")
        return self
    
    def left_join(self, table: str, on: str) -> 'QueryBuilder':
        """Add LEFT JOIN clause"""
        return self.join(table, on, "LEFT")
    
    def right_join(self, table: str, on: str) -> 'QueryBuilder':
        """Add RIGHT JOIN clause"""
        return self.join(table, on, "RIGHT")
    
    def group_by(self, *fields: str) -> 'QueryBuilder':
        """Add GROUP BY clause"""
        self._group_by.extend(fields)
        return self
    
    def having(self, condition: str, *params) -> 'QueryBuilder':
        """Add HAVING condition"""
        self._having.append(condition)
        self._where_params.extend(params)
        return self
    
    def order_by(self, field: str, direction: str = "ASC") -> 'QueryBuilder':
        """Add ORDER BY clause"""
        self._order_by.append(f"{field} {direction}")
        return self
    
    def limit(self, limit: int) -> 'QueryBuilder':
        """Set LIMIT"""
        self._limit = limit
        return self
    
    def offset(self, offset: int) -> 'QueryBuilder':
        """Set OFFSET"""
        self._offset = offset
        return self
    
    def build(self) -> tuple[str, list]:
        """Build the SQL query and return with parameters"""
        # SELECT clause
        sql = f"SELECT {', '.join(self._select_fields)} FROM {self.table}"
        
        # JOIN clauses
        if self._joins:
            sql += " " + " ".join(self._joins)
        
        # WHERE clause
        if self._where_conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in self._where_conditions)
        
        # GROUP BY clause
        if self._group_by:
            sql += " GROUP BY " + ", ".join(self._group_by)
        
        # HAVING clause
        if self._having:
            sql += " HAVING " + " AND ".join(f"({c})" for c in self._having)
        
        # ORDER BY clause
        if self._order_by:
            sql += " ORDER BY " + ", ".join(self._order_by)
        
        # LIMIT and OFFSET
        if self._limit is not None:
            sql += f" LIMIT {self._limit}"
        if self._offset is not None:
            sql += f" OFFSET {self._offset}"
        
        return sql, self._where_params
    
    def build_count(self) -> tuple[str, list]:
        """Build COUNT query"""
        sql = f"SELECT COUNT(*) FROM {self.table}"
        
        if self._joins:
            sql += " " + " ".join(self._joins)
        
        if self._where_conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in self._where_conditions)
        
        return sql, self._where_params


# =============================================
# Repository Base Class
# =============================================
class BaseRepository:
    """Base repository with common CRUD operations"""
    
    def __init__(self, pool: ConnectionPool, table: str):
        self.pool = pool
        self.table = table
    
    def query(self) -> QueryBuilder:
        """Create a new query builder for this table"""
        return QueryBuilder(self.table)
    
    async def find_by_id(self, id: int) -> Optional[Dict[str, Any]]:
        """Find record by ID"""
        row = await self.pool.fetchrow(
            f"SELECT * FROM {self.table} WHERE id = $1",
            id
        )
        return dict(row) if row else None
    
    async def find_all(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "id DESC"
    ) -> List[Dict[str, Any]]:
        """Find all records with pagination"""
        rows = await self.pool.fetch(
            f"SELECT * FROM {self.table} ORDER BY {order_by} LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(row) for row in rows]
    
    async def find_one(self, conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find one record by conditions"""
        where_parts = [f"{k} = ${i+1}" for i, k in enumerate(conditions.keys())]
        where_clause = " AND ".join(where_parts)
        
        row = await self.pool.fetchrow(
            f"SELECT * FROM {self.table} WHERE {where_clause} LIMIT 1",
            *conditions.values()
        )
        return dict(row) if row else None
    
    async def find_many(
        self,
        conditions: Dict[str, Any],
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Find many records by conditions"""
        where_parts = [f"{k} = ${i+1}" for i, k in enumerate(conditions.keys())]
        where_clause = " AND ".join(where_parts)
        
        rows = await self.pool.fetch(
            f"SELECT * FROM {self.table} WHERE {where_clause} LIMIT $1 OFFSET $2",
            *conditions.values(), limit, offset
        )
        return [dict(row) for row in rows]
    
    async def insert(self, data: Dict[str, Any], returning: str = "id") -> Any:
        """Insert a record"""
        fields = list(data.keys())
        placeholders = [f"${i+1}" for i in range(len(fields))]
        
        query = f"""
            INSERT INTO {self.table} ({', '.join(fields)})
            VALUES ({', '.join(placeholders)})
            RETURNING {returning}
        """
        
        return await self.pool.fetchval(query, *data.values())
    
    async def insert_returning(self, data: Dict[str, Any], returning: str = "*") -> Dict[str, Any]:
        """Insert a record and return full row"""
        fields = list(data.keys())
        placeholders = [f"${i+1}" for i in range(len(fields))]
        
        query = f"""
            INSERT INTO {self.table} ({', '.join(fields)})
            VALUES ({', '.join(placeholders)})
            RETURNING {returning}
        """
        
        row = await self.pool.fetchrow(query, *data.values())
        return dict(row) if row else {}
    
    async def update(self, id: int, data: Dict[str, Any]) -> bool:
        """Update a record by ID"""
        if not data:
            return False
        
        set_parts = [f"{k} = ${i+1}" for i, k in enumerate(data.keys())]
        query = f"""
            UPDATE {self.table}
            SET {', '.join(set_parts)}
            WHERE id = ${len(data) + 1}
        """
        
        result = await self.pool.execute(query, *data.values(), id)
        return result == "UPDATE 1"
    
    async def update_where(self, conditions: Dict[str, Any], data: Dict[str, Any]) -> int:
        """Update records matching conditions"""
        if not data or not conditions:
            return 0
        
        set_parts = [f"{k} = ${i+1}" for i, k in enumerate(data.keys())]
        where_parts = [f"{k} = ${i+1+len(data)}" for i, k in enumerate(conditions.keys())]
        
        query = f"""
            UPDATE {self.table}
            SET {', '.join(set_parts)}
            WHERE {' AND '.join(where_parts)}
        """
        
        result = await self.pool.execute(query, *data.values(), *conditions.values())
        
        # Parse affected rows
        import re
        match = re.search(r'UPDATE (\d+)', result)
        return int(match.group(1)) if match else 0
    
    async def delete(self, id: int) -> bool:
        """Delete a record by ID"""
        result = await self.pool.execute(
            f"DELETE FROM {self.table} WHERE id = $1",
            id
        )
        return result == "DELETE 1"
    
    async def delete_where(self, conditions: Dict[str, Any]) -> int:
        """Delete records matching conditions"""
        if not conditions:
            return 0
        
        where_parts = [f"{k} = ${i+1}" for i, k in enumerate(conditions.keys())]
        query = f"DELETE FROM {self.table} WHERE {' AND '.join(where_parts)}"
        
        result = await self.pool.execute(query, *conditions.values())
        
        import re
        match = re.search(r'DELETE (\d+)', result)
        return int(match.group(1)) if match else 0
    
    async def count(self, conditions: Optional[Dict[str, Any]] = None) -> int:
        """Count records"""
        if conditions:
            where_parts = [f"{k} = ${i+1}" for i, k in enumerate(conditions.keys())]
            query = f"SELECT COUNT(*) FROM {self.table} WHERE {' AND '.join(where_parts)}"
            return await self.pool.fetchval(query, *conditions.values())
        else:
            return await self.pool.fetchval(f"SELECT COUNT(*) FROM {self.table}")
    
    async def exists(self, id: int) -> bool:
        """Check if record exists"""
        count = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM {self.table} WHERE id = $1",
            id
        )
        return count > 0


# =============================================
# Specific Repositories
# =============================================
class CampaignRepository(BaseRepository):
    """Repository for campaigns"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "campaigns")
    
    async def find_with_stats(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        """Get campaign with statistics"""
        query = """
            SELECT c.*,
                   COUNT(DISTINCT cc.contact_id) as total_contacts,
                   COUNT(DISTINCT cr.id) as total_calls,
                   SUM(CASE WHEN cr.status = 'agreed' THEN 1 ELSE 0 END) as agreed_calls,
                   SUM(CASE WHEN cr.status = 'busy' THEN 1 ELSE 0 END) as busy_calls,
                   SUM(CASE WHEN cr.status = 'noanswer' THEN 1 ELSE 0 END) as noanswer_calls
            FROM campaigns c
            LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
            LEFT JOIN call_results cr ON c.id = cr.campaign_id
            WHERE c.id = $1
            GROUP BY c.id
        """
        row = await self.pool.fetchrow(query, campaign_id)
        return dict(row) if row else None
    
    async def get_running_campaigns(self) -> List[Dict[str, Any]]:
        """Get all running campaigns"""
        rows = await self.pool.fetch(
            "SELECT * FROM campaigns WHERE status = 'running'"
        )
        return [dict(row) for row in rows]


class ContactRepository(BaseRepository):
    """Repository for contacts"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "contacts")
    
    async def find_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Find contact by phone number"""
        return await self.find_one({"phone": phone})
    
    async def upsert(self, phone: str, data: Dict[str, Any]) -> int:
        """Insert or update contact"""
        query = """
            INSERT INTO contacts (phone, name, email, group_id, tags)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (phone) DO UPDATE SET
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                group_id = EXCLUDED.group_id,
                tags = EXCLUDED.tags,
                updated_at = NOW()
            RETURNING id
        """
        return await self.pool.fetchval(
            query,
            phone,
            data.get('name'),
            data.get('email'),
            data.get('group_id'),
            data.get('tags', [])
        )
    
    async def get_blacklisted_phones(self) -> set:
        """Get all blacklisted phone numbers"""
        rows = await self.pool.fetch(
            "SELECT phone FROM contacts WHERE blacklisted = TRUE"
        )
        return {row['phone'] for row in rows}


class CallResultRepository(BaseRepository):
    """Repository for call results"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "call_results")
    
    async def get_stats_by_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Get statistics for a campaign"""
        row = await self.pool.fetchrow("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'agreed' THEN 1 ELSE 0 END) as agreed,
                SUM(CASE WHEN status = 'declined' THEN 1 ELSE 0 END) as declined,
                SUM(CASE WHEN status = 'busy' THEN 1 ELSE 0 END) as busy,
                SUM(CASE WHEN status = 'noanswer' THEN 1 ELSE 0 END) as noanswer,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                AVG(duration) as avg_duration
            FROM call_results
            WHERE campaign_id = $1
        """, campaign_id)
        return dict(row) if row else {}
    
    async def get_daily_stats(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get daily statistics for last N days"""
        rows = await self.pool.fetch("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'agreed' THEN 1 ELSE 0 END) as agreed
            FROM call_results
            WHERE created_at >= CURRENT_DATE - INTERVAL '1 day' * $1
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """, days)
        return [dict(row) for row in rows]


class UserRepository(BaseRepository):
    """Repository for users"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "users")
    
    async def find_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Find user by username"""
        return await self.find_one({"username": username})
    
    async def update_last_login(self, user_id: int, ip_address: str = None) -> None:
        """Update last login time"""
        await self.pool.execute(
            "UPDATE users SET last_login = NOW(), last_ip = $1 WHERE id = $2",
            ip_address, user_id
        )


class SettingsRepository(BaseRepository):
    """Repository for settings"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "settings")
    
    async def get_all_as_dict(self) -> Dict[str, str]:
        """Get all settings as key-value dict"""
        rows = await self.pool.fetch("SELECT key, value FROM settings")
        return {row['key']: row['value'] for row in rows}
    
    async def get_value(self, key: str, default: str = None) -> Optional[str]:
        """Get a single setting value"""
        value = await self.pool.fetchval(
            "SELECT value FROM settings WHERE key = $1",
            key
        )
        return value if value is not None else default
    
    async def set_value(self, key: str, value: str) -> None:
        """Set a setting value"""
        await self.pool.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, key, value)


class AudioFileRepository(BaseRepository):
    """Repository for audio files"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "audio_files")
    
    async def find_by_campaign(self, campaign_id: int) -> List[Dict[str, Any]]:
        """Find audio files for a campaign"""
        rows = await self.pool.fetch(
            "SELECT * FROM audio_files WHERE campaign_id = $1 ORDER BY created_at DESC",
            campaign_id
        )
        return [dict(row) for row in rows]
    
    async def get_old_files(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get audio files older than N days"""
        rows = await self.pool.fetch("""
            SELECT id, file_path FROM audio_files 
            WHERE created_at < NOW() - INTERVAL '1 day' * $1
            AND campaign_id IS NULL
        """, days)
        return [dict(row) for row in rows]


# =============================================
# Global Database Instance
# =============================================
_db_pool: Optional[ConnectionPool] = None


def get_db_pool() -> Optional[ConnectionPool]:
    """Get the global database pool"""
    return _db_pool


def set_db_pool(pool: ConnectionPool) -> None:
    """Set the global database pool"""
    global _db_pool
    _db_pool = pool


async def init_database(config: Optional[dict] = None) -> ConnectionPool:
    """Initialize database connection"""
    global _db_pool
    pool = ConnectionPool(config)
    await pool.connect()
    _db_pool = pool
    return pool


async def close_database() -> None:
    """Close database connection"""
    global _db_pool
    if _db_pool:
        await _db_pool.disconnect()
        _db_pool = None


# =============================================
# Convenience Functions
# =============================================
async def execute(query: str, *args) -> str:
    """Execute a query using global pool"""
    if not _db_pool:
        raise RuntimeError("Database not initialized")
    return await _db_pool.execute(query, *args)


async def fetch(query: str, *args) -> List[asyncpg.Record]:
    """Fetch rows using global pool"""
    if not _db_pool:
        raise RuntimeError("Database not initialized")
    return await _db_pool.fetch(query, *args)


async def fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    """Fetch single row using global pool"""
    if not _db_pool:
        raise RuntimeError("Database not initialized")
    return await _db_pool.fetchrow(query, *args)


async def fetchval(query: str, *args) -> Any:
    """Fetch single value using global pool"""
    if not _db_pool:
        raise RuntimeError("Database not initialized")
    return await _db_pool.fetchval(query, *args)


@asynccontextmanager
async def transaction():
    """Start a transaction using global pool"""
    if not _db_pool:
        raise RuntimeError("Database not initialized")
    async with _db_pool.transaction() as conn:
        yield conn


# =============================================
# Migration Utilities
# =============================================
class MigrationManager:
    """Manage database migrations"""
    
    def __init__(self, pool: ConnectionPool):
        self.pool = pool
    
    async def ensure_migrations_table(self) -> None:
        """Create migrations table if not exists"""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                version VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255),
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    async def get_applied_migrations(self) -> set:
        """Get set of applied migration versions"""
        await self.ensure_migrations_table()
        rows = await self.pool.fetch("SELECT version FROM schema_migrations")
        return {row['version'] for row in rows}
    
    async def apply_migration(self, version: str, name: str, sql: str) -> bool:
        """Apply a single migration"""
        try:
            async with self.pool.transaction() as conn:
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                    version, name
                )
            logger.info(f"Applied migration {version}: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply migration {version}: {e}")
            return False
    
    async def rollback_migration(self, version: str, sql: str) -> bool:
        """Rollback a migration"""
        try:
            async with self.pool.transaction() as conn:
                await conn.execute(sql)
                await conn.execute(
                    "DELETE FROM schema_migrations WHERE version = $1",
                    version
                )
            logger.info(f"Rolled back migration {version}")
            return True
        except Exception as e:
            logger.error(f"Failed to rollback migration {version}: {e}")
            return False
