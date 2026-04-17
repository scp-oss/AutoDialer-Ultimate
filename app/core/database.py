#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль базы данных PostgreSQL
AutoDialer Ultimate v3.0.0

Предоставляет:
- ConnectionPool с автоматическим управлением соединениями
- QueryBuilder для построения динамических SQL запросов
- BaseRepository и специализированные репозитории
- Миграции через MigrationManager
- Circuit Breaker интеграцию
- Метрики Prometheus

ИСПРАВЛЕНИЯ:
- ✅ Корректное получение/освобождение соединений во всех методах
- ✅ Закрытие транзакций при ошибках
- ✅ Graceful shutdown
- ✅ Health check с переподключением
"""

import asyncio
import asyncpg
import os
import re
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Any, List, Dict, Union, AsyncGenerator, Callable, TypeVar, Generic
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logger import logger

# Prometheus метрики (опционально)
try:
    from prometheus_client import Counter, Gauge, Histogram
    
    db_connections_gauge = Gauge(
        'autodialer_db_connections', 
        'Active database connections',
        ['pool']
    )
    db_queries_counter = Counter(
        'autodialer_db_queries_total', 
        'Total database queries',
        ['operation', 'table']
    )
    db_query_duration = Histogram(
        'autodialer_db_query_duration_seconds',
        'Database query duration',
        ['operation']
    )
    db_errors_counter = Counter(
        'autodialer_db_errors_total',
        'Database errors',
        ['error_type']
    )
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    
    def _dummy_metric(*args, **kwargs):
        pass
    
    class _DummyMetric:
        def __getattr__(self, name):
            return _dummy_metric
    
    db_connections_gauge = _DummyMetric()
    db_queries_counter = _DummyMetric()
    db_query_duration = _DummyMetric()
    db_errors_counter = _DummyMetric()


# =============================================
# Типы для репозиториев
# =============================================
T = TypeVar('T')


# =============================================
# Конфигурация базы данных
# =============================================
@dataclass
class DatabaseConfig:
    """Конфигурация подключения к PostgreSQL"""
    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "autodialer"
    user: str = "autodialer"
    password: str = ""
    min_size: int = 5
    max_size: int = 50
    max_queries: int = 50000
    max_inactive_connection_lifetime: int = 300
    command_timeout: int = 60
    statement_cache_size: int = 100
    server_settings: Dict[str, str] = field(default_factory=lambda: {
        'application_name': 'autodialer',
        'timezone': 'UTC',
        'client_encoding': 'UTF8',
        'DateStyle': 'ISO, DMY',
    })
    
    @classmethod
    def from_settings(cls) -> "DatabaseConfig":
        """Создать конфигурацию из настроек приложения"""
        return cls(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            min_size=settings.DB_POOL_MIN_SIZE,
            max_size=settings.DB_POOL_MAX_SIZE,
            max_queries=settings.DB_MAX_QUERIES,
            max_inactive_connection_lifetime=settings.DB_MAX_INACTIVE_LIFETIME,
            command_timeout=settings.DB_COMMAND_TIMEOUT,
            statement_cache_size=settings.DB_STATEMENT_CACHE_SIZE,
        )
    
    @property
    def dsn(self) -> str:
        """DSN строка для подключения"""
        auth = f"{self.user}:{self.password}" if self.password else self.user
        return f"postgresql://{auth}@{self.host}:{self.port}/{self.database}"


# =============================================
# Исключения базы данных
# =============================================
class DatabaseError(Exception):
    """Базовое исключение базы данных"""
    pass


class ConnectionError(DatabaseError):
    """Ошибка подключения"""
    pass


class QueryError(DatabaseError):
    """Ошибка выполнения запроса"""
    
    def __init__(self, message: str, query: str = None, params: tuple = None):
        self.query = query
        self.params = params
        super().__init__(message)


class TransactionError(DatabaseError):
    """Ошибка транзакции"""
    pass


class UniqueViolationError(QueryError):
    """Нарушение уникальности"""
    pass


class ForeignKeyViolationError(QueryError):
    """Нарушение внешнего ключа"""
    pass


class RecordNotFoundError(QueryError):
    """Запись не найдена"""
    pass


# =============================================
# Connection Pool с исправлениями
# =============================================
class ConnectionPool:
    """
    Пул соединений PostgreSQL с автоматическим управлением.
    
    Особенности:
    - Автоматическое получение и освобождение соединений
    - Health check с автоматическим восстановлением
    - Интеграция с Circuit Breaker
    - Метрики Prometheus
    - Graceful shutdown
    """
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_settings()
        self.pool: Optional[asyncpg.Pool] = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._closed = False
        self._last_health_check: Optional[datetime] = None
        self._health_check_interval = 30
        self._health_check_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        
        # Статистика
        self._stats = {
            'total_acquires': 0,
            'total_releases': 0,
            'total_queries': 0,
            'total_errors': 0,
            'total_transactions': 0,
            'last_error': None,
            'last_error_time': None,
            'pool_size': 0,
            'pool_free': 0,
            'pool_used': 0,
        }
        
        # Circuit Breaker (опционально)
        self._circuit_breaker = None
        
        logger.info(f"ConnectionPool создан: {self.config.host}:{self.config.port}/{self.config.database}")
    
    @property
    def is_connected(self) -> bool:
        """Проверка подключения"""
        return self._connected and self.pool is not None and not self._closed
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Получить статистику пула"""
        stats = self._stats.copy()
        
        if self.pool:
            try:
                stats['pool_size'] = self.pool.get_size()
                stats['pool_free'] = self.pool.get_idle_size()
                stats['pool_used'] = stats['pool_size'] - stats['pool_free']
            except:
                pass
        
        stats['connected'] = self._connected
        stats['last_health_check'] = self._last_health_check.isoformat() if self._last_health_check else None
        
        return stats
    
    def set_circuit_breaker(self, breaker):
        """Установить Circuit Breaker для защиты вызовов"""
        self._circuit_breaker = breaker
    
    async def connect(self) -> None:
        """Создать пул соединений"""
        async with self._lock:
            if self.pool and not self._closed:
                logger.warning("Пул соединений уже существует")
                return
            
            if not self.config.password and not self.config.database:
                raise ValueError("Не заданы параметры подключения к БД")
            
            try:
                logger.info(
                    f"Подключение к PostgreSQL: {self.config.host}:{self.config.port}/{self.config.database}"
                )
                
                self.pool = await asyncpg.create_pool(
                    host=self.config.host,
                    port=self.config.port,
                    database=self.config.database,
                    user=self.config.user,
                    password=self.config.password,
                    min_size=self.config.min_size,
                    max_size=self.config.max_size,
                    max_queries=self.config.max_queries,
                    max_inactive_connection_lifetime=self.config.max_inactive_connection_lifetime,
                    command_timeout=self.config.command_timeout,
                    statement_cache_size=self.config.statement_cache_size,
                    server_settings=self.config.server_settings,
                )
                
                # Тестовое подключение
                async with self.pool.acquire() as conn:
                    version = await conn.fetchval("SELECT version()")
                    logger.info(f"✅ Подключено к PostgreSQL: {version[:50]}...")
                
                self._connected = True
                self._closed = False
                self._reconnect_attempts = 0
                self._last_health_check = datetime.now()
                
                # Запуск health check
                if not self._health_check_task or self._health_check_task.done():
                    self._health_check_task = asyncio.create_task(self._health_check_loop())
                
                logger.info(
                    f"Пул соединений создан (min={self.config.min_size}, max={self.config.max_size})"
                )
                
            except Exception as e:
                logger.error(f"❌ Ошибка подключения к БД: {e}")
                self._stats['total_errors'] += 1
                self._stats['last_error'] = str(e)
                self._stats['last_error_time'] = datetime.now()
                
                if METRICS_ENABLED:
                    db_errors_counter.labels(error_type='connection').inc()
                
                raise ConnectionError(f"Failed to connect: {e}")
    
    async def disconnect(self) -> None:
        """Закрыть пул соединений"""
        async with self._lock:
            if self._health_check_task and not self._health_check_task.done():
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None
            
            if self.pool:
                try:
                    await asyncio.wait_for(self.pool.close(), timeout=10.0)
                    logger.info("Пул соединений закрыт")
                except asyncio.TimeoutError:
                    logger.warning("Таймаут закрытия пула, принудительное завершение")
                    self.pool.terminate()
                finally:
                    self.pool = None
                    self._connected = False
                    self._closed = True
    
    async def _health_check_loop(self) -> None:
        """Фоновый health check пула"""
        while self._connected and not self._closed:
            await asyncio.sleep(self._health_check_interval)
            
            if not self.pool or self._closed:
                continue
            
            try:
                async with self.pool.acquire() as conn:
                    await asyncio.wait_for(conn.execute("SELECT 1"), timeout=5.0)
                
                self._last_health_check = datetime.now()
                self._reconnect_attempts = 0
                logger.debug("Health check БД пройден")
                
                # Обновление метрик
                if METRICS_ENABLED:
                    try:
                        db_connections_gauge.labels(pool='main').set(self.pool.get_size())
                    except:
                        pass
                
            except Exception as e:
                logger.warning(f"Health check БД не пройден: {e}")
                self._stats['total_errors'] += 1
                self._stats['last_error'] = str(e)
                self._stats['last_error_time'] = datetime.now()
                
                # Попытка переподключения
                await self._try_reconnect()
    
    async def _try_reconnect(self) -> bool:
        """Попытка переподключения к БД"""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Достигнут лимит попыток переподключения к БД")
            return False
        
        self._reconnect_attempts += 1
        wait_time = min(2 ** self._reconnect_attempts, 60)
        
        logger.info(f"Попытка переподключения {self._reconnect_attempts}/{self._max_reconnect_attempts} через {wait_time}с")
        await asyncio.sleep(wait_time)
        
        try:
            # Пробуем выполнить простой запрос
            if self.pool:
                async with self.pool.acquire() as conn:
                    await conn.execute("SELECT 1")
                self._reconnect_attempts = 0
                return True
        except Exception:
            pass
        
        return False
    
    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Получить соединение из пула.
        
        Использование:
            async with db_pool.acquire() as conn:
                result = await conn.fetch("SELECT ...")
        """
        if not self.pool or self._closed:
            raise ConnectionError("База данных не подключена")
        
        self._stats['total_acquires'] += 1
        
        conn = None
        try:
            # Используем Circuit Breaker если задан
            if self._circuit_breaker:
                conn = await self._circuit_breaker.call(self.pool.acquire)
            else:
                conn = await self.pool.acquire()
            
            yield conn
            
        except asyncpg.exceptions.UniqueViolationError as e:
            self._stats['total_errors'] += 1
            if METRICS_ENABLED:
                db_errors_counter.labels(error_type='unique_violation').inc()
            raise UniqueViolationError(str(e))
        
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            self._stats['total_errors'] += 1
            if METRICS_ENABLED:
                db_errors_counter.labels(error_type='foreign_key').inc()
            raise ForeignKeyViolationError(str(e))
        
        except Exception as e:
            self._stats['total_errors'] += 1
            self._stats['last_error'] = str(e)
            self._stats['last_error_time'] = datetime.now()
            
            if METRICS_ENABLED:
                db_errors_counter.labels(error_type='general').inc()
            
            logger.error(f"Ошибка получения соединения: {e}")
            raise QueryError(f"Failed to acquire connection: {e}")
        
        finally:
            if conn is not None:
                try:
                    await self.pool.release(conn)
                    self._stats['total_releases'] += 1
                except Exception as e:
                    logger.error(f"Ошибка освобождения соединения: {e}")
    
    async def execute(self, query: str, *args, timeout: Optional[float] = None) -> str:
        """
        Выполнить запрос и вернуть статус.
        
        Args:
            query: SQL запрос с $1, $2, ...
            *args: Параметры запроса
            timeout: Таймаут запроса
        
        Returns:
            Статус выполнения (например, "INSERT 0 1")
        """
        start_time = time.monotonic()
        self._stats['total_queries'] += 1
        
        try:
            async with self.acquire() as conn:
                if timeout:
                    result = await asyncio.wait_for(
                        conn.execute(query, *args),
                        timeout=timeout
                    )
                else:
                    result = await conn.execute(query, *args)
                
                # Метрики
                if METRICS_ENABLED:
                    operation = query.strip().split()[0].upper()
                    db_queries_counter.labels(operation=operation, table='').inc()
                    db_query_duration.labels(operation=operation).observe(
                        time.monotonic() - start_time
                    )
                
                return result
                
        except asyncio.TimeoutError:
            self._stats['total_errors'] += 1
            if METRICS_ENABLED:
                db_errors_counter.labels(error_type='timeout').inc()
            raise QueryError(f"Query timeout after {timeout}s")
        
        except Exception as e:
            self._stats['total_errors'] += 1
            logger.error(f"Ошибка выполнения запроса: {e}\nQuery: {query}\nArgs: {args}")
            raise QueryError(str(e), query, args)
    
    async def executemany(self, query: str, args_list: List[tuple]) -> None:
        """Выполнить запрос множество раз"""
        self._stats['total_queries'] += len(args_list)
        
        try:
            async with self.acquire() as conn:
                await conn.executemany(query, args_list)
                
            if METRICS_ENABLED:
                operation = query.strip().split()[0].upper()
                db_queries_counter.labels(operation=operation, table='').inc(len(args_list))
                
        except Exception as e:
            self._stats['total_errors'] += 1
            logger.error(f"Ошибка executemany: {e}")
            raise QueryError(str(e), query, args_list)
    
    async def fetch(
        self, 
        query: str, 
        *args, 
        timeout: Optional[float] = None
    ) -> List[asyncpg.Record]:
        """
        Получить множество строк.
        
        Returns:
            Список записей (asyncpg.Record)
        """
        start_time = time.monotonic()
        self._stats['total_queries'] += 1
        
        try:
            async with self.acquire() as conn:
                if timeout:
                    result = await asyncio.wait_for(
                        conn.fetch(query, *args),
                        timeout=timeout
                    )
                else:
                    result = await conn.fetch(query, *args)
                
                if METRICS_ENABLED:
                    operation = query.strip().split()[0].upper()
                    db_queries_counter.labels(operation=operation, table='').inc()
                    db_query_duration.labels(operation=operation).observe(
                        time.monotonic() - start_time
                    )
                
                return result
                
        except Exception as e:
            self._stats['total_errors'] += 1
            logger.error(f"Ошибка fetch: {e}")
            raise QueryError(str(e), query, args)
    
    async def fetchrow(
        self, 
        query: str, 
        *args, 
        timeout: Optional[float] = None
    ) -> Optional[asyncpg.Record]:
        """
        Получить одну строку.
        
        Returns:
            Запись или None
        """
        start_time = time.monotonic()
        self._stats['total_queries'] += 1
        
        try:
            async with self.acquire() as conn:
                if timeout:
                    result = await asyncio.wait_for(
                        conn.fetchrow(query, *args),
                        timeout=timeout
                    )
                else:
                    result = await conn.fetchrow(query, *args)
                
                if METRICS_ENABLED:
                    operation = query.strip().split()[0].upper()
                    db_queries_counter.labels(operation=operation, table='').inc()
                    db_query_duration.labels(operation=operation).observe(
                        time.monotonic() - start_time
                    )
                
                return result
                
        except Exception as e:
            self._stats['total_errors'] += 1
            logger.error(f"Ошибка fetchrow: {e}")
            raise QueryError(str(e), query, args)
    
    async def fetchval(
        self, 
        query: str, 
        *args, 
        timeout: Optional[float] = None,
        default: Any = None
    ) -> Any:
        """
        Получить одно значение.
        
        Returns:
            Значение или default если не найдено
        """
        start_time = time.monotonic()
        self._stats['total_queries'] += 1
        
        try:
            async with self.acquire() as conn:
                if timeout:
                    result = await asyncio.wait_for(
                        conn.fetchval(query, *args),
                        timeout=timeout
                    )
                else:
                    result = await conn.fetchval(query, *args)
                
                if METRICS_ENABLED:
                    operation = query.strip().split()[0].upper()
                    db_queries_counter.labels(operation=operation, table='').inc()
                    db_query_duration.labels(operation=operation).observe(
                        time.monotonic() - start_time
                    )
                
                return result if result is not None else default
                
        except Exception as e:
            self._stats['total_errors'] += 1
            logger.error(f"Ошибка fetchval: {e}")
            raise QueryError(str(e), query, args)
    
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Выполнить операции в транзакции.
        
        Использование:
            async with db_pool.transaction() as conn:
                await conn.execute("INSERT ...")
                await conn.execute("UPDATE ...")
        """
        self._stats['total_transactions'] += 1
        
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    async def check_connection(self) -> bool:
        """Проверить подключение к БД"""
        if not self.pool or self._closed:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                await asyncio.wait_for(conn.execute("SELECT 1"), timeout=5.0)
            return True
        except Exception:
            return False
    
    async def get_table_size(self, table: str) -> int:
        """Получить примерный размер таблицы"""
        query = """
            SELECT reltuples::bigint AS estimate 
            FROM pg_class 
            WHERE relname = $1
        """
        return await self.fetchval(query, table) or 0
    
    async def vacuum_table(self, table: str) -> None:
        """Выполнить VACUUM таблицы (только для admin)"""
        await self.execute(f"VACUUM ANALYZE {table}")
        logger.info(f"VACUUM выполнен для таблицы {table}")
    
    def reset_stats(self):
        """Сбросить статистику"""
        self._stats = {
            'total_acquires': 0,
            'total_releases': 0,
            'total_queries': 0,
            'total_errors': 0,
            'total_transactions': 0,
            'last_error': None,
            'last_error_time': None,
            'pool_size': 0,
            'pool_free': 0,
            'pool_used': 0,
        }


# =============================================
# Query Builder
# =============================================
class QueryBuilder:
    """
    Построитель динамических SQL запросов.
    
    Использование:
        query, params = (QueryBuilder("campaigns")
                        .select(["id", "name"])
                        .where("status = $1", "running")
                        .order_by("created_at", "DESC")
                        .limit(10)
                        .build())
    """
    
    def __init__(self, table: str):
        self.table = table
        self._select_fields = ["*"]
        self._where_conditions = []
        self._where_params = []
        self._order_by = []
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None
        self._joins = []
        self._group_by = []
        self._having = []
        self._returning: Optional[str] = None
    
    def select(self, fields: Union[str, List[str]]) -> "QueryBuilder":
        """Установить поля для SELECT"""
        if isinstance(fields, str):
            self._select_fields = [f.strip() for f in fields.split(',')]
        else:
            self._select_fields = fields
        return self
    
    def where(self, condition: str, *params) -> "QueryBuilder":
        """Добавить WHERE условие"""
        self._where_conditions.append(condition)
        self._where_params.extend(params)
        return self
    
    def where_if(self, condition: bool, sql: str, *params) -> "QueryBuilder":
        """Добавить WHERE если condition == True"""
        if condition:
            self._where_conditions.append(sql)
            self._where_params.extend(params)
        return self
    
    def where_in(self, field: str, values: List[Any]) -> "QueryBuilder":
        """Добавить WHERE field IN (...)"""
        if values:
            placeholders = ','.join([f'${len(self._where_params) + i + 1}' for i in range(len(values))])
            self._where_conditions.append(f"{field} IN ({placeholders})")
            self._where_params.extend(values)
        return self
    
    def where_not_in(self, field: str, values: List[Any]) -> "QueryBuilder":
        """Добавить WHERE field NOT IN (...)"""
        if values:
            placeholders = ','.join([f'${len(self._where_params) + i + 1}' for i in range(len(values))])
            self._where_conditions.append(f"{field} NOT IN ({placeholders})")
            self._where_params.extend(values)
        return self
    
    def where_null(self, field: str) -> "QueryBuilder":
        """Добавить WHERE field IS NULL"""
        self._where_conditions.append(f"{field} IS NULL")
        return self
    
    def where_not_null(self, field: str) -> "QueryBuilder":
        """Добавить WHERE field IS NOT NULL"""
        self._where_conditions.append(f"{field} IS NOT NULL")
        return self
    
    def where_between(self, field: str, start: Any, end: Any) -> "QueryBuilder":
        """Добавить WHERE field BETWEEN start AND end"""
        self._where_conditions.append(
            f"{field} BETWEEN ${len(self._where_params) + 1} AND ${len(self._where_params) + 2}"
        )
        self._where_params.extend([start, end])
        return self
    
    def where_like(self, field: str, pattern: str) -> "QueryBuilder":
        """Добавить WHERE field LIKE pattern"""
        self._where_conditions.append(f"{field} LIKE ${len(self._where_params) + 1}")
        self._where_params.append(pattern)
        return self
    
    def where_ilike(self, field: str, pattern: str) -> "QueryBuilder":
        """Добавить WHERE field ILIKE pattern"""
        self._where_conditions.append(f"{field} ILIKE ${len(self._where_params) + 1}")
        self._where_params.append(pattern)
        return self
    
    def where_json_contains(self, field: str, key: str, value: Any) -> "QueryBuilder":
        """Добавить WHERE field->>'key' = value (для JSONB)"""
        self._where_conditions.append(f"{field}->>${len(self._where_params) + 1} = ${len(self._where_params) + 2}")
        self._where_params.extend([key, str(value)])
        return self
    
    def join(self, table: str, on: str, join_type: str = "INNER") -> "QueryBuilder":
        """Добавить JOIN"""
        self._joins.append(f"{join_type} JOIN {table} ON {on}")
        return self
    
    def left_join(self, table: str, on: str) -> "QueryBuilder":
        """Добавить LEFT JOIN"""
        return self.join(table, on, "LEFT")
    
    def right_join(self, table: str, on: str) -> "QueryBuilder":
        """Добавить RIGHT JOIN"""
        return self.join(table, on, "RIGHT")
    
    def group_by(self, *fields: str) -> "QueryBuilder":
        """Добавить GROUP BY"""
        self._group_by.extend(fields)
        return self
    
    def having(self, condition: str, *params) -> "QueryBuilder":
        """Добавить HAVING"""
        self._having.append(condition)
        self._where_params.extend(params)
        return self
    
    def order_by(self, field: str, direction: str = "ASC") -> "QueryBuilder":
        """Добавить ORDER BY"""
        direction = direction.upper()
        if direction not in ("ASC", "DESC"):
            direction = "ASC"
        self._order_by.append(f"{field} {direction}")
        return self
    
    def limit(self, limit: int) -> "QueryBuilder":
        """Установить LIMIT"""
        self._limit = limit
        return self
    
    def offset(self, offset: int) -> "QueryBuilder":
        """Установить OFFSET"""
        self._offset = offset
        return self
    
    def returning(self, fields: str) -> "QueryBuilder":
        """Установить RETURNING"""
        self._returning = fields
        return self
    
    def build_select(self) -> tuple[str, list]:
        """Построить SELECT запрос"""
        sql = f"SELECT {', '.join(self._select_fields)} FROM {self.table}"
        
        if self._joins:
            sql += " " + " ".join(self._joins)
        
        if self._where_conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in self._where_conditions)
        
        if self._group_by:
            sql += " GROUP BY " + ", ".join(self._group_by)
        
        if self._having:
            sql += " HAVING " + " AND ".join(f"({c})" for c in self._having)
        
        if self._order_by:
            sql += " ORDER BY " + ", ".join(self._order_by)
        
        if self._limit is not None:
            sql += f" LIMIT {self._limit}"
        
        if self._offset is not None:
            sql += f" OFFSET {self._offset}"
        
        return sql, self._where_params
    
    def build_count(self) -> tuple[str, list]:
        """Построить COUNT запрос"""
        sql = f"SELECT COUNT(*) FROM {self.table}"
        
        if self._joins:
            sql += " " + " ".join(self._joins)
        
        if self._where_conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in self._where_conditions)
        
        return sql, self._where_params
    
    def build_insert(self, data: Dict[str, Any]) -> tuple[str, list]:
        """Построить INSERT запрос"""
        fields = list(data.keys())
        placeholders = [f"${i+1}" for i in range(len(fields))]
        
        sql = f"""
            INSERT INTO {self.table} ({', '.join(fields)})
            VALUES ({', '.join(placeholders)})
        """
        
        if self._returning:
            sql += f" RETURNING {self._returning}"
        
        return sql, list(data.values())
    
    def build_update(self, data: Dict[str, Any]) -> tuple[str, list]:
        """Построить UPDATE запрос"""
        set_parts = [f"{k} = ${i+1}" for i, k in enumerate(data.keys())]
        params = list(data.values())
        
        sql = f"UPDATE {self.table} SET {', '.join(set_parts)}"
        
        if self._where_conditions:
            where_clause = " AND ".join(f"({c})" for c in self._where_conditions)
            sql += f" WHERE {where_clause}"
            
            # Переиндексация параметров WHERE
            offset = len(params)
            for param in self._where_params:
                params.append(param)
        
        if self._returning:
            sql += f" RETURNING {self._returning}"
        
        return sql, params
    
    def build_delete(self) -> tuple[str, list]:
        """Построить DELETE запрос"""
        sql = f"DELETE FROM {self.table}"
        
        if self._where_conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in self._where_conditions)
        
        if self._returning:
            sql += f" RETURNING {self._returning}"
        
        return sql, self._where_params
    
    def build(self) -> tuple[str, list]:
        """Построить SELECT запрос (алиас для build_select)"""
        return self.build_select()


# =============================================
# Базовый репозиторий
# =============================================
class BaseRepository(Generic[T]):
    """Базовый репозиторий с CRUD операциями"""
    
    def __init__(self, pool: ConnectionPool, table: str):
        self.pool = pool
        self.table = table
    
    def query(self) -> QueryBuilder:
        """Создать новый QueryBuilder для этой таблицы"""
        return QueryBuilder(self.table)
    
    async def find_by_id(self, id: Any) -> Optional[Dict[str, Any]]:
        """Найти запись по ID"""
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
        """Найти все записи с пагинацией"""
        rows = await self.pool.fetch(
            f"SELECT * FROM {self.table} ORDER BY {order_by} LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(row) for row in rows]
    
    async def find_one(self, conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Найти одну запись по условиям"""
        qb = self.query()
        for field, value in conditions.items():
            qb.where(f"{field} = ${len(qb._where_params) + 1}", value)
        qb.limit(1)
        
        query, params = qb.build_select()
        row = await self.pool.fetchrow(query, *params)
        return dict(row) if row else None
    
    async def find_many(
        self,
        conditions: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Найти множество записей по условиям"""
        qb = self.query()
        for field, value in conditions.items():
            qb.where(f"{field} = ${len(qb._where_params) + 1}", value)
        
        if order_by:
            field, direction = order_by.split() if ' ' in order_by else (order_by, 'ASC')
            qb.order_by(field, direction)
        
        qb.limit(limit).offset(offset)
        
        query, params = qb.build_select()
        rows = await self.pool.fetch(query, *params)
        return [dict(row) for row in rows]
    
    async def insert(self, data: Dict[str, Any], returning: str = "id") -> Any:
        """Вставить запись"""
        qb = self.query().returning(returning)
        query, params = qb.build_insert(data)
        return await self.pool.fetchval(query, *params)
    
    async def insert_returning(self, data: Dict[str, Any], returning: str = "*") -> Dict[str, Any]:
        """Вставить запись и вернуть её"""
        qb = self.query().returning(returning)
        query, params = qb.build_insert(data)
        row = await self.pool.fetchrow(query, *params)
        return dict(row) if row else {}
    
    async def insert_many(self, data_list: List[Dict[str, Any]]) -> int:
        """Вставить множество записей"""
        if not data_list:
            return 0
        
        fields = list(data_list[0].keys())
        placeholders = [f"${i+1}" for i in range(len(fields))]
        
        query = f"""
            INSERT INTO {self.table} ({', '.join(fields)})
            VALUES ({', '.join(placeholders)})
        """
        
        args_list = [tuple(item.values()) for item in data_list]
        await self.pool.executemany(query, args_list)
        return len(args_list)
    
    async def update(self, id: Any, data: Dict[str, Any]) -> bool:
        """Обновить запись по ID"""
        if not data:
            return False
        
        qb = self.query().where(f"id = ${len(data) + 1}", id)
        query, params = qb.build_update(data)
        
        result = await self.pool.execute(query, *params)
        return "UPDATE 1" in result
    
    async def update_where(self, conditions: Dict[str, Any], data: Dict[str, Any]) -> int:
        """Обновить записи по условиям"""
        if not data or not conditions:
            return 0
        
        qb = self.query()
        for field, value in conditions.items():
            qb.where(f"{field} = ${len(qb._where_params) + 1}", value)
        
        query, params = qb.build_update(data)
        
        result = await self.pool.execute(query, *params)
        
        match = re.search(r'UPDATE (\d+)', result)
        return int(match.group(1)) if match else 0
    
    async def upsert(
        self,
        data: Dict[str, Any],
        conflict_fields: List[str],
        update_fields: Optional[List[str]] = None
    ) -> Any:
        """
        Вставить или обновить запись (UPSERT).
        
        Args:
            data: Данные для вставки
            conflict_fields: Поля для ON CONFLICT
            update_fields: Поля для обновления (если None - все кроме conflict)
        
        Returns:
            ID записи
        """
        fields = list(data.keys())
        placeholders = [f"${i+1}" for i in range(len(fields))]
        
        if update_fields is None:
            update_fields = [f for f in fields if f not in conflict_fields]
        
        update_clause = ", ".join([f"{f} = EXCLUDED.{f}" for f in update_fields])
        conflict_clause = ", ".join(conflict_fields)
        
        query = f"""
            INSERT INTO {self.table} ({', '.join(fields)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT ({conflict_clause}) DO UPDATE SET
            {update_clause}
            RETURNING id
        """
        
        return await self.pool.fetchval(query, *data.values())
    
    async def delete(self, id: Any) -> bool:
        """Удалить запись по ID"""
        result = await self.pool.execute(
            f"DELETE FROM {self.table} WHERE id = $1",
            id
        )
        return "DELETE 1" in result
    
    async def delete_where(self, conditions: Dict[str, Any]) -> int:
        """Удалить записи по условиям"""
        if not conditions:
            return 0
        
        qb = self.query()
        for field, value in conditions.items():
            qb.where(f"{field} = ${len(qb._where_params) + 1}", value)
        
        query, params = qb.build_delete()
        result = await self.pool.execute(query, *params)
        
        match = re.search(r'DELETE (\d+)', result)
        return int(match.group(1)) if match else 0
    
    async def count(self, conditions: Optional[Dict[str, Any]] = None) -> int:
        """Посчитать количество записей"""
        if conditions:
            qb = self.query()
            for field, value in conditions.items():
                qb.where(f"{field} = ${len(qb._where_params) + 1}", value)
            query, params = qb.build_count()
            return await self.pool.fetchval(query, *params) or 0
        else:
            return await self.pool.fetchval(f"SELECT COUNT(*) FROM {self.table}") or 0
    
    async def exists(self, id: Any) -> bool:
        """Проверить существование записи"""
        count = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM {self.table} WHERE id = $1",
            id
        )
        return count > 0
    
    async def exists_where(self, conditions: Dict[str, Any]) -> bool:
        """Проверить существование записей по условиям"""
        return await self.count(conditions) > 0


# =============================================
# Специализированные репозитории
# =============================================
class CampaignRepository(BaseRepository):
    """Репозиторий для кампаний"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "campaigns")
    
    async def find_with_stats(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        """Получить кампанию со статистикой"""
        query = """
            SELECT c.*,
                   COUNT(DISTINCT cc.contact_id) as total_contacts,
                   COUNT(DISTINCT cr.id) as total_calls,
                   SUM(CASE WHEN cr.status = 'agreed' THEN 1 ELSE 0 END) as agreed_calls,
                   SUM(CASE WHEN cr.status = 'declined' THEN 1 ELSE 0 END) as declined_calls,
                   SUM(CASE WHEN cr.status = 'busy' THEN 1 ELSE 0 END) as busy_calls,
                   SUM(CASE WHEN cr.status = 'noanswer' THEN 1 ELSE 0 END) as noanswer_calls,
                   SUM(CASE WHEN cr.status = 'failed' THEN 1 ELSE 0 END) as failed_calls,
                   AVG(cr.duration) as avg_duration,
                   SUM(cr.duration) as total_duration
            FROM campaigns c
            LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
            LEFT JOIN call_results cr ON c.id = cr.campaign_id
            WHERE c.id = $1
            GROUP BY c.id
        """
        row = await self.pool.fetchrow(query, campaign_id)
        return dict(row) if row else None
    
    async def get_running_campaigns(self) -> List[Dict[str, Any]]:
        """Получить все запущенные кампании"""
        rows = await self.pool.fetch(
            "SELECT * FROM campaigns WHERE status = 'running'"
        )
        return [dict(row) for row in rows]
    
    async def update_status(self, campaign_id: int, status: str) -> bool:
        """Обновить статус кампании"""
        result = await self.pool.execute(
            "UPDATE campaigns SET status = $1, updated_at = NOW() WHERE id = $2",
            status, campaign_id
        )
        return "UPDATE 1" in result


class ContactRepository(BaseRepository):
    """Репозиторий для контактов"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "contacts")
    
    async def find_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Найти контакт по номеру телефона"""
        return await self.find_one({"phone": phone})
    
    async def upsert_contact(self, phone: str, data: Dict[str, Any]) -> int:
        """Вставить или обновить контакт"""
        return await self.upsert(
            {**data, "phone": phone},
            conflict_fields=["phone"],
            update_fields=["name", "email", "group_id", "tags", "custom_fields", "updated_at"]
        )
    
    async def get_blacklisted_phones(self) -> set:
        """Получить все номера в чёрном списке"""
        rows = await self.pool.fetch(
            "SELECT phone FROM contacts WHERE blacklisted = TRUE"
        )
        return {row['phone'] for row in rows}
    
    async def mark_blacklisted(self, phone: str, reason: Optional[str] = None) -> bool:
        """Пометить контакт как заблокированный"""
        result = await self.pool.execute(
            "UPDATE contacts SET blacklisted = TRUE, blacklist_reason = $1, updated_at = NOW() WHERE phone = $2",
            reason, phone
        )
        return "UPDATE" in result


class CallResultRepository(BaseRepository):
    """Репозиторий для результатов звонков"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "call_results")
    
    async def get_stats_by_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Получить статистику по кампании"""
        row = await self.pool.fetchrow("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'agreed' THEN 1 ELSE 0 END) as agreed,
                SUM(CASE WHEN status = 'declined' THEN 1 ELSE 0 END) as declined,
                SUM(CASE WHEN status = 'busy' THEN 1 ELSE 0 END) as busy,
                SUM(CASE WHEN status = 'noanswer' THEN 1 ELSE 0 END) as noanswer,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'timeout' THEN 1 ELSE 0 END) as timeout,
                AVG(duration) as avg_duration,
                SUM(duration) as total_duration
            FROM call_results
            WHERE campaign_id = $1
        """, campaign_id)
        return dict(row) if row else {}
    
    async def get_daily_stats(self, days: int = 7) -> List[Dict[str, Any]]:
        """Получить дневную статистику"""
        rows = await self.pool.fetch("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'agreed' THEN 1 ELSE 0 END) as agreed,
                SUM(CASE WHEN status = 'declined' THEN 1 ELSE 0 END) as declined,
                SUM(CASE WHEN status = 'busy' THEN 1 ELSE 0 END) as busy,
                SUM(CASE WHEN status = 'noanswer' THEN 1 ELSE 0 END) as noanswer,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM call_results
            WHERE created_at >= CURRENT_DATE - INTERVAL '1 day' * $1
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """, days)
        return [dict(row) for row in rows]


class UserRepository(BaseRepository):
    """Репозиторий для пользователей"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "users")
    
    async def find_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Найти пользователя по имени"""
        return await self.find_one({"username": username})
    
    async def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Найти пользователя по email"""
        return await self.find_one({"email": email})
    
    async def update_last_login(self, user_id: int, ip_address: Optional[str] = None) -> None:
        """Обновить время последнего входа"""
        await self.pool.execute(
            "UPDATE users SET last_login = NOW(), last_ip = $1 WHERE id = $2",
            ip_address, user_id
        )
    
    async def change_password(self, user_id: int, password_hash: str) -> bool:
        """Изменить пароль пользователя"""
        result = await self.pool.execute(
            "UPDATE users SET password_hash = $1, force_password_change = FALSE, updated_at = NOW() WHERE id = $2",
            password_hash, user_id
        )
        return "UPDATE 1" in result


class SettingsRepository(BaseRepository):
    """Репозиторий для настроек"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "settings")
    
    async def get_all_as_dict(self) -> Dict[str, str]:
        """Получить все настройки как словарь"""
        rows = await self.pool.fetch("SELECT key, value FROM settings")
        return {row['key']: row['value'] for row in rows}
    
    async def get_value(self, key: str, default: Any = None) -> Any:
        """Получить значение настройки"""
        value = await self.pool.fetchval(
            "SELECT value FROM settings WHERE key = $1",
            key
        )
        return value if value is not None else default
    
    async def set_value(self, key: str, value: str, updated_by: Optional[int] = None) -> None:
        """Установить значение настройки"""
        await self.pool.execute("""
            INSERT INTO settings (key, value, updated_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
        """, key, value, updated_by)


class AudioFileRepository(BaseRepository):
    """Репозиторий для аудиофайлов"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "audio_files")
    
    async def find_by_campaign(self, campaign_id: int) -> List[Dict[str, Any]]:
        """Найти аудиофайлы кампании"""
        rows = await self.pool.fetch(
            "SELECT * FROM audio_files WHERE campaign_id = $1 ORDER BY created_at DESC",
            campaign_id
        )
        return [dict(row) for row in rows]
    
    async def get_old_files(self, days: int = 30) -> List[Dict[str, Any]]:
        """Получить старые аудиофайлы для удаления"""
        rows = await self.pool.fetch("""
            SELECT id, file_path FROM audio_files 
            WHERE created_at < NOW() - INTERVAL '1 day' * $1
            AND campaign_id IS NULL
        """, days)
        return [dict(row) for row in rows]
    
    async def delete_by_ids(self, ids: List[int]) -> int:
        """Удалить аудиофайлы по ID"""
        if not ids:
            return 0
        result = await self.pool.execute(
            "DELETE FROM audio_files WHERE id = ANY($1)",
            ids
        )
        match = re.search(r'DELETE (\d+)', result)
        return int(match.group(1)) if match else 0


class AuditLogRepository(BaseRepository):
    """Репозиторий для аудит логов"""
    
    def __init__(self, pool: ConnectionPool):
        super().__init__(pool, "audit_log")
    
    async def log(
        self,
        user_id: Optional[int],
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> int:
        """Записать аудит событие"""
        return await self.insert({
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": json.dumps(details) if details else None,
            "ip_address": ip_address,
            "user_agent": user_agent,
        })


# =============================================
# Глобальный экземпляр
# =============================================
_db_pool: Optional[ConnectionPool] = None


def get_db_pool() -> ConnectionPool:
    """Получить глобальный пул БД"""
    global _db_pool
    if _db_pool is None:
        raise RuntimeError("База данных не инициализирована. Вызовите init_database()")
    return _db_pool


def set_db_pool(pool: ConnectionPool) -> None:
    """Установить глобальный пул БД"""
    global _db_pool
    _db_pool = pool


async def init_database(config: Optional[DatabaseConfig] = None) -> ConnectionPool:
    """Инициализировать подключение к БД"""
    global _db_pool
    
    if _db_pool is not None:
        logger.warning("База данных уже инициализирована")
        return _db_pool
    
    pool = ConnectionPool(config)
    await pool.connect()
    _db_pool = pool
    
    return pool


async def close_database() -> None:
    """Закрыть подключение к БД"""
    global _db_pool
    if _db_pool:
        await _db_pool.disconnect()
        _db_pool = None


# =============================================
# Удобные функции для запросов
# =============================================
async def execute(query: str, *args) -> str:
    """Выполнить запрос через глобальный пул"""
    return await get_db_pool().execute(query, *args)


async def fetch(query: str, *args) -> List[asyncpg.Record]:
    """Получить множество строк через глобальный пул"""
    return await get_db_pool().fetch(query, *args)


async def fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    """Получить одну строку через глобальный пул"""
    return await get_db_pool().fetchrow(query, *args)


async def fetchval(query: str, *args, default: Any = None) -> Any:
    """Получить одно значение через глобальный пул"""
    return await get_db_pool().fetchval(query, *args, default=default)


@asynccontextmanager
async def transaction():
    """Контекстный менеджер для транзакции через глобальный пул"""
    async with get_db_pool().transaction() as conn:
        yield conn


# =============================================
# Миграции
# =============================================
class MigrationManager:
    """Управление миграциями базы данных"""
    
    def __init__(self, pool: ConnectionPool):
        self.pool = pool
    
    async def ensure_migrations_table(self) -> None:
        """Создать таблицу миграций"""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                version VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255),
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checksum VARCHAR(64)
            )
        """)
    
    async def get_applied_migrations(self) -> set:
        """Получить список применённых миграций"""
        await self.ensure_migrations_table()
        rows = await self.pool.fetch("SELECT version FROM schema_migrations")
        return {row['version'] for row in rows}
    
    async def apply_migration(self, version: str, name: str, sql: str, checksum: Optional[str] = None) -> bool:
        """Применить миграцию"""
        try:
            async with self.pool.transaction() as conn:
                await conn.execute(sql)
                await conn.execute(
                    """INSERT INTO schema_migrations (version, name, checksum) 
                       VALUES ($1, $2, $3)""",
                    version, name, checksum
                )
            logger.info(f"✅ Миграция применена: {version} - {name}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка применения миграции {version}: {e}")
            return False
    
    async def rollback_migration(self, version: str, sql: str) -> bool:
        """Откатить миграцию"""
        try:
            async with self.pool.transaction() as conn:
                await conn.execute(sql)
                await conn.execute(
                    "DELETE FROM schema_migrations WHERE version = $1",
                    version
                )
            logger.info(f"↩️ Миграция откачена: {version}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отката миграции {version}: {e}")
            return False


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Конфигурация
    "DatabaseConfig",
    
    # Исключения
    "DatabaseError",
    "ConnectionError",
    "QueryError",
    "TransactionError",
    "UniqueViolationError",
    "ForeignKeyViolationError",
    "RecordNotFoundError",
    
    # Пул соединений
    "ConnectionPool",
    
    # Query Builder
    "QueryBuilder",
    
    # Репозитории
    "BaseRepository",
    "CampaignRepository",
    "ContactRepository",
    "CallResultRepository",
    "UserRepository",
    "SettingsRepository",
    "AudioFileRepository",
    "AuditLogRepository",
    
    # Глобальные функции
    "init_database",
    "close_database",
    "get_db_pool",
    "set_db_pool",
    "execute",
    "fetch",
    "fetchrow",
    "fetchval",
    "transaction",
    
    # Миграции
    "MigrationManager",
]
