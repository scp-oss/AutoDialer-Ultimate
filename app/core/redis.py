#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль Redis клиента
AutoDialer Ultimate v3.0.0

Предоставляет:
- Singleton Redis клиент с автоматическим переподключением
- Redis Sentinel поддержку
- Redis Cache с TTL
- Redis Lock (распределённые блокировки)
- Redis Queue (очереди)
- Pub/Sub для real-time уведомлений
- Lua скрипты для атомарных операций
- Health check с автоматическим восстановлением
- Метрики Prometheus

ИСПРАВЛЕНИЯ:
- ✅ Корректное управление подключением (connect/disconnect)
- ✅ Graceful shutdown
- ✅ Health check с переподключением
- ✅ Поддержка Sentinel для высокой доступности
- ✅ Pipeline для batch операций
"""

import asyncio
import json
import time
import hashlib
from typing import Optional, Any, Dict, List, Set, Union, Callable, Awaitable, Tuple
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
    ResponseError as RedisResponseError,
)

from app.core.config import settings
from app.core.logger import logger

# Prometheus метрики (опционально)
try:
    from prometheus_client import Counter, Gauge, Histogram
    
    redis_connections_gauge = Gauge(
        'autodialer_redis_connections',
        'Active Redis connections'
    )
    redis_commands_counter = Counter(
        'autodialer_redis_commands_total',
        'Total Redis commands',
        ['command']
    )
    redis_command_duration = Histogram(
        'autodialer_redis_command_duration_seconds',
        'Redis command duration',
        ['command']
    )
    redis_errors_counter = Counter(
        'autodialer_redis_errors_total',
        'Redis errors',
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
    
    redis_connections_gauge = _DummyMetric()
    redis_commands_counter = _DummyMetric()
    redis_command_duration = _DummyMetric()
    redis_errors_counter = _DummyMetric()


# =============================================
# Исключения Redis
# =============================================
class RedisError(Exception):
    """Базовое исключение Redis"""
    pass


class RedisConnectionFailed(RedisError):
    """Ошибка подключения к Redis"""
    pass


class RedisLockError(RedisError):
    """Ошибка блокировки Redis"""
    pass


class RedisQueueError(RedisError):
    """Ошибка очереди Redis"""
    pass


# =============================================
# Константы ключей Redis
# =============================================
class RedisKeys:
    """Константы ключей Redis для проекта"""
    
    # Системные
    SYSTEM_ENABLED = "system_enabled"
    ACTIVE_CALLS = "active_calls"
    GLOBAL_CPS = "global_cps"
    
    # Дозвон
    ACTIVE_CHANNELS = "active_channels"
    ACTIVE_CHANNELS_TS = "active_channels_ts"
    ACTIVE_PHONES = "active_phones"
    DIAL_QUEUE = "dial_queue"
    CALL_STATES = "call_states"
    RESERVATIONS_DATA = "reservations_data"
    RESERVATIONS_TS = "reservations_ts"
    
    # Кампании
    CAMPAIGN_SETTINGS = "campaign_settings"
    CAMPAIGN_PROGRESS = "campaign_progress"
    
    # Контакты
    CONTACT_CACHE = "contact"
    BLACKLIST_PHONES = "blacklist:phones"
    
    # Транскрибация
    TRANSCRIPTION_QUEUE = "transcription_queue"
    TRANSCRIPTION_STATUS = "transcription_status"
    
    # Аутентификация
    REFRESH_TOKEN = "refresh"
    LOGIN_ATTEMPTS = "login_attempts"
    RATE_LIMIT = "rate_limit"
    
    # Лидерство
    LEADER_PREFIX = "leader"
    
    # Кеш
    CACHE_PREFIX = "cache"
    
    # Сессии
    SESSION_PREFIX = "session"
    
    # WebSocket
    WS_CONNECTIONS = "ws_connections"
    WS_CHANNELS = "ws_channels"
    
    # Метрики
    METRICS_PREFIX = "metrics"
    
    @classmethod
    def campaign_lock(cls, campaign_id: int) -> str:
        return f"campaign_start_lock:{campaign_id}"
    
    @classmethod
    def contact_key(cls, phone: str) -> str:
        return f"{cls.CONTACT_CACHE}:{phone}"
    
    @classmethod
    def refresh_token_key(cls, jti: str) -> str:
        return f"{cls.REFRESH_TOKEN}:{jti}"
    
    @classmethod
    def login_attempts_key(cls, username: str) -> str:
        return f"{cls.LOGIN_ATTEMPTS}:{username}"
    
    @classmethod
    def rate_limit_key(cls, identifier: str) -> str:
        return f"{cls.RATE_LIMIT}:{identifier}"
    
    @classmethod
    def leader_key(cls, name: str) -> str:
        return f"{cls.LEADER_PREFIX}:{name}"
    
    @classmethod
    def cache_key(cls, key: str) -> str:
        return f"{cls.CACHE_PREFIX}:{key}"
    
    @classmethod
    def session_key(cls, session_id: str) -> str:
        return f"{cls.SESSION_PREFIX}:{session_id}"
    
    @classmethod
    def hangup_key(cls, unique_id: str) -> str:
        return f"hangup:{unique_id}"
    
    @classmethod
    def trace_key(cls, action_id: str) -> str:
        return f"trace:{action_id}"

REDIS_KEYS = RedisKeys()


# =============================================
# Декоратор для метрик
# =============================================
def track_redis_command(command: str):
    """Декоратор для отслеживания метрик Redis команд"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            start_time = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                
                if METRICS_ENABLED:
                    redis_commands_counter.labels(command=command).inc()
                    redis_command_duration.labels(command=command).observe(
                        time.monotonic() - start_time
                    )
                
                return result
            except Exception as e:
                if METRICS_ENABLED:
                    redis_errors_counter.labels(error_type=type(e).__name__).inc()
                raise
        return wrapper
    return decorator


# =============================================
# Основной Redis клиент
# =============================================
class RedisClient:
    """
    Singleton Redis клиент с поддержкой Sentinel.
    
    Особенности:
    - Автоматическое переподключение
    - Health check
    - Поддержка Sentinel
    - Pipeline операции
    - Pub/Sub
    """
    
    def __init__(self):
        self._client: Optional[Redis] = None
        self._sentinel: Optional[Sentinel] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._connected = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._health_check_task: Optional[asyncio.Task] = None
        self._last_health_check: Optional[datetime] = None
        
        # Подписчики
        self._subscribers: Dict[str, List[Callable]] = {}
        self._pubsub_task: Optional[asyncio.Task] = None
        
        # Статистика
        self._stats = {
            'commands_executed': 0,
            'errors': 0,
            'reconnects': 0,
            'last_error': None,
            'last_error_time': None,
        }
        
        # Circuit Breaker (опционально)
        self._circuit_breaker = None
        
        logger.info("RedisClient создан")
    
    @property
    def is_connected(self) -> bool:
        """Проверка подключения"""
        return self._connected and self._client is not None and not self._closed
    
    @property
    def client(self) -> Redis:
        """Получить клиент Redis"""
        if not self.is_connected:
            raise RedisConnectionFailed("Redis не подключен")
        return self._client
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Получить статистику"""
        return {
            **self._stats,
            'connected': self._connected,
            'reconnect_attempts': self._reconnect_attempts,
            'last_health_check': self._last_health_check.isoformat() if self._last_health_check else None,
        }
    
    def set_circuit_breaker(self, breaker):
        """Установить Circuit Breaker"""
        self._circuit_breaker = breaker
    
    async def connect(self) -> None:
        """Подключиться к Redis"""
        async with self._lock:
            if self._client and not self._closed:
                logger.warning("Redis уже подключен")
                return
            
            try:
                if settings.REDIS_SENTINEL_ENABLED:
                    await self._connect_sentinel()
                else:
                    await self._connect_standalone()
                
                # Проверка подключения
                await self._client.ping()
                
                self._connected = True
                self._closed = False
                self._reconnect_attempts = 0
                self._last_health_check = datetime.now()
                
                # Запуск health check
                if not self._health_check_task or self._health_check_task.done():
                    self._health_check_task = asyncio.create_task(self._health_check_loop())
                
                # Обновление метрик
                if METRICS_ENABLED:
                    redis_connections_gauge.set(1)
                
                logger.info(f"✅ Redis подключен: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка подключения к Redis: {e}")
                self._stats['errors'] += 1
                self._stats['last_error'] = str(e)
                self._stats['last_error_time'] = datetime.now()
                
                if METRICS_ENABLED:
                    redis_errors_counter.labels(error_type='connection').inc()
                
                raise RedisConnectionFailed(f"Failed to connect to Redis: {e}")
    
    async def _connect_standalone(self) -> None:
        """Подключение к standalone Redis"""
        connection_kwargs = {
            'host': settings.REDIS_HOST,
            'port': settings.REDIS_PORT,
            'db': settings.REDIS_DB,
            'decode_responses': True,
            'socket_connect_timeout': settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            'socket_timeout': settings.REDIS_SOCKET_TIMEOUT,
            'socket_keepalive': True,
            'health_check_interval': settings.REDIS_HEALTH_CHECK_INTERVAL,
            'retry_on_timeout': settings.REDIS_RETRY_ON_TIMEOUT,
            'max_connections': settings.REDIS_MAX_CONNECTIONS,
        }
        
        if settings.REDIS_PASSWORD:
            connection_kwargs['password'] = settings.REDIS_PASSWORD
        if settings.REDIS_USERNAME:
            connection_kwargs['username'] = settings.REDIS_USERNAME
        
        self._client = redis.Redis(**connection_kwargs)
    
    async def _connect_sentinel(self) -> None:
        """Подключение через Redis Sentinel"""
        sentinel_nodes = []
        for node in settings.REDIS_SENTINEL_NODES.split(','):
            if ':' in node:
                host, port = node.strip().split(':')
                sentinel_nodes.append((host, int(port)))
        
        if not sentinel_nodes:
            raise RedisConnectionFailed("Не заданы узлы Sentinel")
        
        self._sentinel = Sentinel(
            sentinel_nodes,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            decode_responses=True,
        )
        
        self._client = self._sentinel.master_for(
            settings.REDIS_SENTINEL_MASTER,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            decode_responses=True,
            db=settings.REDIS_DB,
        )
        
        logger.info(f"Подключение через Sentinel: мастер {settings.REDIS_SENTINEL_MASTER}")
    
    async def disconnect(self) -> None:
        """Отключиться от Redis"""
        async with self._lock:
            self._closed = True
            
            # Остановка health check
            if self._health_check_task and not self._health_check_task.done():
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None
            
            # Остановка Pub/Sub
            if self._pubsub_task and not self._pubsub_task.done():
                self._pubsub_task.cancel()
                try:
                    await self._pubsub_task
                except asyncio.CancelledError:
                    pass
                self._pubsub_task = None
            
            # Закрытие клиента
            if self._client:
                try:
                    await self._client.aclose()
                except Exception as e:
                    logger.warning(f"Ошибка при закрытии Redis: {e}")
                self._client = None
            
            self._connected = False
            
            if METRICS_ENABLED:
                redis_connections_gauge.set(0)
            
            logger.info("Redis отключен")
    
    async def _health_check_loop(self) -> None:
        """Фоновый health check"""
        while self._connected and not self._closed:
            await asyncio.sleep(settings.REDIS_HEALTH_CHECK_INTERVAL)
            
            if not self._client or self._closed:
                continue
            
            try:
                await asyncio.wait_for(self._client.ping(), timeout=5.0)
                self._last_health_check = datetime.now()
                self._reconnect_attempts = 0
                logger.debug("Health check Redis пройден")
            except Exception as e:
                logger.warning(f"Health check Redis не пройден: {e}")
                self._stats['errors'] += 1
                await self._try_reconnect()
    
    async def _try_reconnect(self) -> bool:
        """Попытка переподключения"""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Достигнут лимит попыток переподключения к Redis")
            return False
        
        self._reconnect_attempts += 1
        wait_time = min(2 ** self._reconnect_attempts, 60)
        
        logger.info(f"Попытка переподключения к Redis {self._reconnect_attempts}/{self._max_reconnect_attempts} через {wait_time}с")
        await asyncio.sleep(wait_time)
        
        try:
            if self._client:
                await self._client.ping()
                self._reconnect_attempts = 0
                self._stats['reconnects'] += 1
                return True
        except Exception:
            pass
        
        return False
    
    async def _execute_with_breaker(self, func: Callable, *args, **kwargs) -> Any:
        """Выполнить команду с Circuit Breaker"""
        if self._circuit_breaker:
            return await self._circuit_breaker.call(func, *args, **kwargs)
        return await func(*args, **kwargs)
    
    # =============================================
    # Базовые команды
    # =============================================
    @track_redis_command("ping")
    async def ping(self) -> bool:
        """Проверить подключение"""
        try:
            return await self.client.ping()
        except Exception as e:
            raise RedisConnectionFailed(f"Ping failed: {e}")
    
    @track_redis_command("get")
    async def get(self, key: str) -> Optional[str]:
        """Получить значение по ключу"""
        return await self.client.get(key)
    
    @track_redis_command("set")
    async def set(self, key: str, value: str, ex: Optional[int] = None, nx: bool = False, xx: bool = False) -> bool:
        """Установить значение"""
        return await self.client.set(key, value, ex=ex, nx=nx, xx=xx)
    
    @track_redis_command("setex")
    async def setex(self, key: str, ex: int, value: str) -> None:
        """Установить значение с TTL"""
        await self.client.setex(key, ex, value)
    
    @track_redis_command("setnx")
    async def setnx(self, key: str, value: str) -> bool:
        """Установить значение если ключ не существует"""
        return await self.client.setnx(key, value)
    
    @track_redis_command("delete")
    async def delete(self, *keys: str) -> int:
        """Удалить ключи"""
        return await self.client.delete(*keys)
    
    @track_redis_command("exists")
    async def exists(self, *keys: str) -> int:
        """Проверить существование ключей"""
        return await self.client.exists(*keys)
    
    @track_redis_command("expire")
    async def expire(self, key: str, seconds: int) -> bool:
        """Установить TTL для ключа"""
        return await self.client.expire(key, seconds)
    
    @track_redis_command("ttl")
    async def ttl(self, key: str) -> int:
        """Получить оставшийся TTL"""
        return await self.client.ttl(key)
    
    @track_redis_command("incr")
    async def incr(self, key: str, amount: int = 1) -> int:
        """Инкрементировать значение"""
        return await self.client.incrby(key, amount)
    
    @track_redis_command("decr")
    async def decr(self, key: str, amount: int = 1) -> int:
        """Декрементировать значение"""
        return await self.client.decrby(key, amount)
    
    @track_redis_command("keys")
    async def keys(self, pattern: str) -> List[str]:
        """Получить ключи по паттерну (осторожно в production!)"""
        return await self.client.keys(pattern)
    
    @track_redis_command("scan")
    async def scan(self, cursor: int = 0, match: Optional[str] = None, count: Optional[int] = None) -> Tuple[int, List[str]]:
        """Сканировать ключи (безопасно)"""
        return await self.client.scan(cursor=cursor, match=match, count=count)
    
    @track_redis_command("mget")
    async def mget(self, *keys: str) -> List[Optional[str]]:
        """Получить множество значений"""
        return await self.client.mget(*keys)
    
    @track_redis_command("mset")
    async def mset(self, mapping: Dict[str, str]) -> None:
        """Установить множество значений"""
        await self.client.mset(mapping)
    
    # =============================================
    # Хеши (Hash)
    # =============================================
    @track_redis_command("hget")
    async def hget(self, name: str, key: str) -> Optional[str]:
        """Получить значение из хеша"""
        return await self.client.hget(name, key)
    
    @track_redis_command("hset")
    async def hset(self, name: str, key: str, value: str) -> int:
        """Установить значение в хеш"""
        return await self.client.hset(name, key, value)
    
    @track_redis_command("hmset")
    async def hmset(self, name: str, mapping: Dict[str, str]) -> None:
        """Установить множество значений в хеш"""
        await self.client.hmset(name, mapping)
    
    @track_redis_command("hgetall")
    async def hgetall(self, name: str) -> Dict[str, str]:
        """Получить все значения из хеша"""
        return await self.client.hgetall(name)
    
    @track_redis_command("hdel")
    async def hdel(self, name: str, *keys: str) -> int:
        """Удалить ключи из хеша"""
        return await self.client.hdel(name, *keys)
    
    @track_redis_command("hexists")
    async def hexists(self, name: str, key: str) -> bool:
        """Проверить существование ключа в хеше"""
        return await self.client.hexists(name, key)
    
    @track_redis_command("hincrby")
    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        """Инкрементировать значение в хеше"""
        return await self.client.hincrby(name, key, amount)
    
    @track_redis_command("hkeys")
    async def hkeys(self, name: str) -> List[str]:
        """Получить все ключи хеша"""
        return await self.client.hkeys(name)
    
    @track_redis_command("hvals")
    async def hvals(self, name: str) -> List[str]:
        """Получить все значения хеша"""
        return await self.client.hvals(name)
    
    @track_redis_command("hlen")
    async def hlen(self, name: str) -> int:
        """Получить количество ключей в хеше"""
        return await self.client.hlen(name)
    
    # =============================================
    # Множества (Set)
    # =============================================
    @track_redis_command("sadd")
    async def sadd(self, name: str, *values: str) -> int:
        """Добавить значения в множество"""
        return await self.client.sadd(name, *values)
    
    @track_redis_command("srem")
    async def srem(self, name: str, *values: str) -> int:
        """Удалить значения из множества"""
        return await self.client.srem(name, *values)
    
    @track_redis_command("sismember")
    async def sismember(self, name: str, value: str) -> bool:
        """Проверить наличие значения в множестве"""
        return await self.client.sismember(name, value)
    
    @track_redis_command("smembers")
    async def smembers(self, name: str) -> Set[str]:
        """Получить все значения множества"""
        return await self.client.smembers(name)
    
    @track_redis_command("scard")
    async def scard(self, name: str) -> int:
        """Получить размер множества"""
        return await self.client.scard(name)
    
    @track_redis_command("spop")
    async def spop(self, name: str, count: Optional[int] = None) -> Union[str, List[str], None]:
        """Извлечь случайный элемент"""
        return await self.client.spop(name, count)
    
    @track_redis_command("srandmember")
    async def srandmember(self, name: str, count: Optional[int] = None) -> Union[str, List[str], None]:
        """Получить случайный элемент без удаления"""
        return await self.client.srandmember(name, count)
    
    # =============================================
    # Сортированные множества (Sorted Set / ZSET)
    # =============================================
    @track_redis_command("zadd")
    async def zadd(self, name: str, mapping: Dict[str, float]) -> int:
        """Добавить значения в ZSET"""
        return await self.client.zadd(name, mapping)
    
    @track_redis_command("zrem")
    async def zrem(self, name: str, *values: str) -> int:
        """Удалить значения из ZSET"""
        return await self.client.zrem(name, *values)
    
    @track_redis_command("zrange")
    async def zrange(self, name: str, start: int, end: int, withscores: bool = False) -> List:
        """Получить диапазон значений"""
        return await self.client.zrange(name, start, end, withscores=withscores)
    
    @track_redis_command("zrangebyscore")
    async def zrangebyscore(
        self, 
        name: str, 
        min_score: float, 
        max_score: float, 
        start: Optional[int] = None,
        num: Optional[int] = None,
        withscores: bool = False
    ) -> List:
        """Получить значения по score"""
        return await self.client.zrangebyscore(
            name, min_score, max_score, 
            start=start, num=num, 
            withscores=withscores
        )
    
    @track_redis_command("zremrangebyscore")
    async def zremrangebyscore(self, name: str, min_score: float, max_score: float) -> int:
        """Удалить значения по score"""
        return await self.client.zremrangebyscore(name, min_score, max_score)
    
    @track_redis_command("zcard")
    async def zcard(self, name: str) -> int:
        """Получить размер ZSET"""
        return await self.client.zcard(name)
    
    @track_redis_command("zscore")
    async def zscore(self, name: str, value: str) -> Optional[float]:
        """Получить score значения"""
        return await self.client.zscore(name, value)
    
    @track_redis_command("zrank")
    async def zrank(self, name: str, value: str) -> Optional[int]:
        """Получить ранг значения"""
        return await self.client.zrank(name, value)
    
    # =============================================
    # Списки (List)
    # =============================================
    @track_redis_command("lpush")
    async def lpush(self, name: str, *values: str) -> int:
        """Добавить значения в начало списка"""
        return await self.client.lpush(name, *values)
    
    @track_redis_command("rpush")
    async def rpush(self, name: str, *values: str) -> int:
        """Добавить значения в конец списка"""
        return await self.client.rpush(name, *values)
    
    @track_redis_command("lpop")
    async def lpop(self, name: str, count: Optional[int] = None) -> Union[str, List[str], None]:
        """Извлечь значения из начала списка"""
        return await self.client.lpop(name, count)
    
    @track_redis_command("rpop")
    async def rpop(self, name: str, count: Optional[int] = None) -> Union[str, List[str], None]:
        """Извлечь значения из конца списка"""
        return await self.client.rpop(name, count)
    
    @track_redis_command("blpop")
    async def blpop(self, keys: Union[str, List[str]], timeout: int = 0) -> Optional[Tuple[str, str]]:
        """Блокирующее извлечение из начала списка"""
        if isinstance(keys, str):
            keys = [keys]
        return await self.client.blpop(keys, timeout)
    
    @track_redis_command("brpop")
    async def brpop(self, keys: Union[str, List[str]], timeout: int = 0) -> Optional[Tuple[str, str]]:
        """Блокирующее извлечение из конца списка"""
        if isinstance(keys, str):
            keys = [keys]
        return await self.client.brpop(keys, timeout)
    
    @track_redis_command("llen")
    async def llen(self, name: str) -> int:
        """Получить длину списка"""
        return await self.client.llen(name)
    
    @track_redis_command("lrange")
    async def lrange(self, name: str, start: int, end: int) -> List[str]:
        """Получить диапазон значений списка"""
        return await self.client.lrange(name, start, end)
    
    @track_redis_command("ltrim")
    async def ltrim(self, name: str, start: int, end: int) -> None:
        """Обрезать список"""
        await self.client.ltrim(name, start, end)
    
    # =============================================
    # Pub/Sub
    # =============================================
    @track_redis_command("publish")
    async def publish(self, channel: str, message: Union[str, Dict]) -> int:
        """Опубликовать сообщение"""
        if isinstance(message, dict):
            message = json.dumps(message)
        return await self.client.publish(channel, message)
    
    async def subscribe(self, channel: str, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """Подписаться на канал"""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
        
        # Запускаем слушатель если ещё не запущен
        if not self._pubsub_task or self._pubsub_task.done():
            self._pubsub_task = asyncio.create_task(self._pubsub_listener())
        
        logger.debug(f"Подписка на канал: {channel}")
    
    async def unsubscribe(self, channel: str, callback: Optional[Callable] = None) -> None:
        """Отписаться от канала"""
        if channel in self._subscribers:
            if callback:
                self._subscribers[channel] = [cb for cb in self._subscribers[channel] if cb != callback]
            else:
                del self._subscribers[channel]
        
        logger.debug(f"Отписка от канала: {channel}")
    
    async def _pubsub_listener(self) -> None:
        """Слушатель Pub/Sub сообщений"""
        while self._connected and not self._closed:
            try:
                self._pubsub = self.client.pubsub()
                
                channels = list(self._subscribers.keys())
                if channels:
                    await self._pubsub.subscribe(*channels)
                    logger.info(f"Pub/Sub слушатель запущен для каналов: {channels}")
                
                async for message in self._pubsub.listen():
                    if message['type'] == 'message':
                        channel = message['channel']
                        data = message['data']
                        
                        if channel in self._subscribers:
                            for callback in self._subscribers[channel]:
                                try:
                                    await callback(channel, data)
                                except Exception as e:
                                    logger.error(f"Ошибка в Pub/Sub колбэке для {channel}: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка Pub/Sub слушателя: {e}")
                await asyncio.sleep(5)
            finally:
                if self._pubsub:
                    try:
                        await self._pubsub.unsubscribe()
                        await self._pubsub.aclose()
                    except:
                        pass
                    self._pubsub = None
    
    # =============================================
    # Lua скрипты
    # =============================================
    @track_redis_command("eval")
    async def eval(self, script: str, num_keys: int, *keys_and_args) -> Any:
        """Выполнить Lua скрипт"""
        return await self.client.eval(script, num_keys, *keys_and_args)
    
    def register_script(self, script: str) -> redis.commands.Script:
        """Зарегистрировать Lua скрипт"""
        return self.client.register_script(script)
    
    # =============================================
    # Pipeline (batch операции)
    # =============================================
    def pipeline(self, transaction: bool = True) -> redis.client.Pipeline:
        """Создать pipeline для batch операций"""
        return self.client.pipeline(transaction=transaction)
    
    @asynccontextmanager
    async def batch(self, transaction: bool = True):
        """Контекстный менеджер для batch операций"""
        pipe = self.pipeline(transaction=transaction)
        try:
            yield pipe
            await pipe.execute()
        finally:
            await pipe.reset()
    
    # =============================================
    # Утилиты для проекта
    # =============================================
    async def get_active_calls(self) -> int:
        """Получить количество активных звонков"""
        return await self.scard(REDIS_KEYS.ACTIVE_CHANNELS)
    
    async def get_queue_size(self) -> int:
        """Получить размер очереди дозвона"""
        return await self.llen(REDIS_KEYS.DIAL_QUEUE)
    
    async def is_system_enabled(self) -> bool:
        """Проверить, включена ли система"""
        value = await self.get(REDIS_KEYS.SYSTEM_ENABLED)
        return value != "false"
    
    async def enable_system(self) -> None:
        """Включить систему"""
        await self.set(REDIS_KEYS.SYSTEM_ENABLED, "true")
    
    async def disable_system(self) -> None:
        """Выключить систему"""
        await self.set(REDIS_KEYS.SYSTEM_ENABLED, "false")
    
    async def clear_dial_queue(self) -> int:
        """Очистить очередь дозвона"""
        return await self.delete(REDIS_KEYS.DIAL_QUEUE)
    
    async def add_to_blacklist(self, phone: str) -> int:
        """Добавить номер в чёрный список"""
        return await self.sadd(REDIS_KEYS.BLACKLIST_PHONES, phone)
    
    async def remove_from_blacklist(self, phone: str) -> int:
        """Удалить номер из чёрного списка"""
        return await self.srem(REDIS_KEYS.BLACKLIST_PHONES, phone)
    
    async def is_blacklisted(self, phone: str) -> bool:
        """Проверить, в чёрном ли списке номер"""
        return await self.sismember(REDIS_KEYS.BLACKLIST_PHONES, phone)
    
    async def get_info(self) -> Dict[str, Any]:
        """Получить информацию о Redis сервере"""
        try:
            info = await self.client.info()
            return {
                'version': info.get('redis_version'),
                'used_memory': info.get('used_memory'),
                'used_memory_human': info.get('used_memory_human'),
                'connected_clients': info.get('connected_clients'),
                'uptime_days': info.get('uptime_in_days'),
                'keyspace': info.get('keyspace', {}),
            }
        except Exception as e:
            return {'error': str(e)}
    
    async def memory_usage(self, key: str) -> int:
        """Получить использование памяти ключом"""
        return await self.client.memory_usage(key) or 0


# =============================================
# Redis Cache
# =============================================
class RedisCache:
    """
    Кеш с TTL на базе Redis.
    
    Использование:
        cache = RedisCache(redis_client, prefix="myapp", default_ttl=3600)
        await cache.set("key", {"data": "value"})
        value = await cache.get("key")
    """
    
    def __init__(
        self,
        client: "RedisClient",
        prefix: str = "cache",
        default_ttl: int = 3600
    ):
        self.client = client
        self.prefix = prefix
        self.default_ttl = default_ttl
    
    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кеша"""
        value = await self.client.get(self._key(key))
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Сохранить значение в кеш"""
        ttl = ttl or self.default_ttl
        if not isinstance(value, str):
            value = json.dumps(value)
        await self.client.setex(self._key(key), ttl, value)
    
    async def delete(self, key: str) -> int:
        """Удалить значение из кеша"""
        return await self.client.delete(self._key(key))
    
    async def exists(self, key: str) -> bool:
        """Проверить существование в кеше"""
        return await self.client.exists(self._key(key)) > 0
    
    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[Any]], ttl: Optional[int] = None) -> Any:
        """Получить из кеша или создать и сохранить"""
        value = await self.get(key)
        if value is not None:
            return value
        
        value = await factory()
        if value is not None:
            await self.set(key, value, ttl)
        return value
    
    async def clear_prefix(self) -> int:
        """Очистить все ключи с префиксом"""
        deleted = 0
        cursor = 0
        pattern = f"{self.prefix}:*"
        
        while True:
            cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
            if keys:
                deleted += await self.client.delete(*keys)
            if cursor == 0:
                break
        
        return deleted


# =============================================
# Redis Lock (распределённая блокировка)
# =============================================
class RedisLock:
    """
    Распределённая блокировка на базе Redis.
    
    Использование:
        lock = RedisLock(redis_client, "my_lock", ttl=30)
        async with lock:
            # Критическая секция
            await do_something()
    """
    
    def __init__(
        self,
        client: "RedisClient",
        name: str,
        ttl: int = 30,
        retry_interval: float = 0.1,
        retry_timeout: Optional[float] = None
    ):
        self.client = client
        self.name = f"lock:{name}"
        self.ttl = ttl
        self.retry_interval = retry_interval
        self.retry_timeout = retry_timeout
        self._lock_value: Optional[str] = None
    
    async def acquire(self) -> bool:
        """Захватить блокировку"""
        import uuid
        self._lock_value = uuid.uuid4().hex
        
        start_time = time.monotonic()
        
        while True:
            acquired = await self.client.set(
                self.name, 
                self._lock_value, 
                ex=self.ttl, 
                nx=True
            )
            
            if acquired:
                logger.debug(f"Блокировка захвачена: {self.name}")
                return True
            
            if self.retry_timeout:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.retry_timeout:
                    return False
            
            await asyncio.sleep(self.retry_interval)
    
    async def release(self) -> bool:
        """Освободить блокировку"""
        if not self._lock_value:
            return False
        
        # Lua скрипт для безопасного освобождения
        script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
        """
        
        result = await self.client.eval(script, 1, self.name, self._lock_value)
        
        if result:
            logger.debug(f"Блокировка освобождена: {self.name}")
            self._lock_value = None
            return True
        
        return False
    
    async def extend(self, ttl: Optional[int] = None) -> bool:
        """Продлить блокировку"""
        if not self._lock_value:
            return False
        
        ttl = ttl or self.ttl
        
        script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('expire', KEYS[1], ARGV[2])
            else
                return 0
            end
        """
        
        return await self.client.eval(script, 1, self.name, self._lock_value, ttl) == 1
    
    async def __aenter__(self) -> "RedisLock":
        acquired = await self.acquire()
        if not acquired:
            raise RedisLockError(f"Не удалось захватить блокировку: {self.name}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.release()


# =============================================
# Redis Queue
# =============================================
class RedisQueue:
    """
    Очередь на базе Redis списков.
    
    Использование:
        queue = RedisQueue(redis_client, "my_queue")
        await queue.push({"task": "data"})
        task = await queue.pop()
    """
    
    def __init__(self, client: "RedisClient", name: str):
        self.client = client
        self.name = f"queue:{name}"
    
    async def push(self, data: Any, priority: bool = False) -> int:
        """Добавить задачу в очередь"""
        if not isinstance(data, str):
            data = json.dumps(data)
        
        if priority:
            return await self.client.lpush(self.name, data)
        else:
            return await self.client.rpush(self.name, data)
    
    async def push_many(self, items: List[Any], priority: bool = False) -> int:
        """Добавить множество задач"""
        data = [json.dumps(item) if not isinstance(item, str) else item for item in items]
        if priority:
            return await self.client.lpush(self.name, *data)
        else:
            return await self.client.rpush(self.name, *data)
    
    async def pop(self, timeout: int = 0) -> Optional[Any]:
        """Извлечь задачу из очереди (блокирующий)"""
        result = await self.client.blpop(self.name, timeout)
        if result:
            _, data = result
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return None
    
    async def pop_nowait(self) -> Optional[Any]:
        """Извлечь задачу без ожидания"""
        data = await self.client.lpop(self.name)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return None
    
    async def size(self) -> int:
        """Размер очереди"""
        return await self.client.llen(self.name)
    
    async def clear(self) -> int:
        """Очистить очередь"""
        return await self.client.delete(self.name)
    
    async def peek(self, count: int = 10) -> List[Any]:
        """Посмотреть задачи без извлечения"""
        items = await self.client.lrange(self.name, 0, count - 1)
        result = []
        for item in items:
            try:
                result.append(json.loads(item))
            except json.JSONDecodeError:
                result.append(item)
        return result


# =============================================
# Глобальный экземпляр
# =============================================
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Получить глобальный клиент Redis"""
    global _redis_client
    if _redis_client is None:
        raise RuntimeError("Redis не инициализирован. Вызовите init_redis()")
    return _redis_client


async def init_redis() -> RedisClient:
    """Инициализировать подключение к Redis"""
    global _redis_client
    
    if _redis_client is not None:
        logger.warning("Redis уже инициализирован")
        return _redis_client
    
    client = RedisClient()
    await client.connect()
    _redis_client = client
    
    # Установка начальных значений
    if not await client.exists(REDIS_KEYS.SYSTEM_ENABLED):
        await client.set(REDIS_KEYS.SYSTEM_ENABLED, "true")
    
    if not await client.exists(REDIS_KEYS.ACTIVE_CALLS):
        await client.set(REDIS_KEYS.ACTIVE_CALLS, "0")
    
    return client


async def close_redis() -> None:
    """Закрыть подключение к Redis"""
    global _redis_client
    if _redis_client:
        await _redis_client.disconnect()
        _redis_client = None


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Константы
    "REDIS_KEYS",
    "RedisKeys",
    
    # Исключения
    "RedisError",
    "RedisConnectionFailed",
    "RedisLockError",
    "RedisQueueError",
    
    # Клиент
    "RedisClient",
    
    # Утилиты
    "RedisCache",
    "RedisLock",
    "RedisQueue",
    
    # Глобальные функции
    "init_redis",
    "close_redis",
    "get_redis_client",
]
