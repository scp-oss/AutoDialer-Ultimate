#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления дозвоном (Dialer)
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Управления подключением к Asterisk AMI
- Инициации звонков
- Обработки событий AMI
- Управления состоянием звонков
- Адаптивного CPS
- Degraded mode при потере Redis
"""

import asyncio
import json
import os
import re
import time
import uuid
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Set, List, Any, Tuple
from enum import Enum
from dataclasses import dataclass, field

import panoramisk
from cachetools import TTLCache

from app.core.config import settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from utils.rate_limiter import TokenBucket, GlobalRateLimiter, AdaptiveCPSLimiter
from prometheus_client import Counter, Gauge, Histogram


# =============================================
# Метрики
# =============================================
active_calls_gauge = Gauge(
    'autodialer_active_calls',
    'Active calls count'
)
calls_initiated_counter = Counter(
    'autodialer_calls_initiated_total',
    'Total calls initiated',
    ['campaign_id']
)
calls_answered_counter = Counter(
    'autodialer_calls_answered_total',
    'Total calls answered',
    ['campaign_id']
)
calls_failed_counter = Counter(
    'autodialer_calls_failed_total',
    'Total calls failed',
    ['campaign_id', 'reason']
)
call_duration_histogram = Histogram(
    'autodialer_call_duration_seconds',
    'Call duration',
    buckets=[10, 30, 60, 120, 180, 300, 600, 900, 1800]
)
cps_gauge = Gauge(
    'autodialer_current_cps',
    'Current Calls Per Second'
)
queue_size_gauge = Gauge(
    'autodialer_queue_size',
    'Dial queue size'
)
degraded_mode_gauge = Gauge(
    'autodialer_degraded_mode',
    'Degraded mode active'
)

# OpenTelemetry (опционально)
try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode, SpanContext, TraceFlags
    tracer = trace.get_tracer("autodialer.dialer")
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    tracer = None


# =============================================
# Исключения
# =============================================
class DialerError(Exception):
    """Базовое исключение сервиса дозвона"""
    pass


class AMIConnectionError(DialerError):
    """Ошибка подключения к AMI"""
    pass


class OriginateError(DialerError):
    """Ошибка инициации звонка"""
    pass


class DialerNotReadyError(DialerError):
    """Дозвон не готов"""
    pass


# =============================================
# Состояния звонка (State Machine)
# =============================================
class CallState(str, Enum):
    """Состояния звонка для state machine"""
    RESERVED = "reserved"       # Слот зарезервирован
    DIALING = "dialing"         # Идёт набор
    RINGING = "ringing"         # Идут гудки
    ACTIVE = "active"           # Разговор
    HANGUP = "hangup"           # Завершён
    TERMINATED = "terminated"   # Полностью завершён


# =============================================
# Модели данных
# =============================================
@dataclass
class CallContext:
    """Контекст активного звонка"""
    action_id: str
    campaign_id: int
    phone: str
    retry_count: int = 0
    state: CallState = CallState.RESERVED
    unique_id: Optional[str] = None
    linked_id: Optional[str] = None
    channel: Optional[str] = None
    started_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    hungup_at: Optional[datetime] = None
    duration: Optional[int] = None
    hangup_cause: Optional[str] = None
    dtmf_digits: List[str] = field(default_factory=list)
    traceparent: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        return self.state in (CallState.DIALING, CallState.RINGING, CallState.ACTIVE)
    
    @property
    def is_answered(self) -> bool:
        return self.state == CallState.ACTIVE


# =============================================
# DialerManager (основной класс)
# =============================================
class DialerManager:
    """
    Менеджер дозвона через Asterisk AMI.
    
    Особенности:
    - ActionID как единый source of truth
    - Атомарные операции через Lua скрипты
    - State machine в Redis Hash
    - Дедупликация звонков
    - Grace window 30-60с для reservation
    - Watchdog с sampling
    - Reconciliation с Asterisk
    - Degraded mode с персистентной очередью
    - Адаптивный CPS с обратной связью
    - OpenTelemetry tracing
    - Поддержка Redis Sentinel
    """
    
    def __init__(
        self,
        db_pool: ConnectionPool,
        redis_client: RedisClient,
        call_result_service=None
    ):
        self.db_pool = db_pool
        self.redis = redis_client
        self.call_result_service = call_result_service
        
        # =============================================
        # Загрузка конфигурации
        # =============================================
        ami_host = settings.AMI_HOST
        ami_port = settings.AMI_PORT
        ami_user = settings.AMI_USER
        ami_password = settings.AMI_PASSWORD
        
        if not ami_password:
            raise ValueError("AMI_PASSWORD не задан в переменных окружения")
        
        self.freepbx_extension = settings.FREEPBX_EXTENSION
        
        # =============================================
        # Инициализация AMI
        # =============================================
        self.manager = panoramisk.Manager(
            host=ami_host,
            port=ami_port,
            username=ami_user,
            secret=ami_password,
            ssl=settings.AMI_SSL
        )
        
        # =============================================
        # Настройки дозвона
        # =============================================
        self.max_calls = settings.MAX_CALLS
        self.caller_id = settings.CALLER_ID
        self.call_timeout = settings.CALL_TIMEOUT
        self.max_retries = settings.MAX_RETRIES
        
        # =============================================
        # Ключи Redis
        # =============================================
        self.active_channels_key = REDIS_KEYS.ACTIVE_CHANNELS
        self.active_channels_ts_key = REDIS_KEYS.ACTIVE_CHANNELS_TS
        self.dial_queue_key = REDIS_KEYS.DIAL_QUEUE
        self.call_state_key = REDIS_KEYS.CALL_STATES
        self.active_phones_key = REDIS_KEYS.ACTIVE_PHONES
        self.reservations_ts_key = REDIS_KEYS.RESERVATIONS_TS
        
        # =============================================
        # Состояние (локальные кэши)
        # =============================================
        self.channel_map: Dict[str, str] = {}                 # unique_id -> channel
        self.call_start_times: Dict[str, datetime] = {}       # unique_id -> start_time
        self.action_to_channel: Dict[str, str] = {}           # action_id -> channel
        self.unique_to_action: Dict[str, str] = {}            # unique_id -> action_id
        self.action_to_uniques: Dict[str, Set[str]] = {}      # action_id -> set(unique_id)
        self.action_created_at: Dict[str, float] = {}         # для TTL cleanup
        self.terminated_calls: Set[str] = set()              # идемпотентность Hangup
        self.call_contexts: Dict[str, CallContext] = {}       # action_id -> CallContext
        
        # =============================================
        # Дедупликация событий
        # =============================================
        self.processed_events = TTLCache(maxsize=100000, ttl=300)
        self.hangup_events = TTLCache(maxsize=50000, ttl=60)
        
        # =============================================
        # Состояние работы
        # =============================================
        self.running = True
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.degraded_mode = False
        
        # =============================================
        # Degraded mode
        # =============================================
        self.degraded_queue_file = settings.DEGRADED_QUEUE_FILE
        self._local_queue: List[dict] = []
        self.MAX_LOCAL_QUEUE = settings.DEGRADED_QUEUE_MAX_SIZE
        self.LOCAL_QUEUE_MAX_AGE = settings.DEGRADED_QUEUE_MAX_AGE
        self.recovery_cps = settings.DEGRADED_RECOVERY_CPS
        self.local_active_estimate = 0
        self._local_estimate_lock = asyncio.Lock()
        self.last_redis_sync = time.monotonic()
        
        # =============================================
        # Ограничители скорости
        # =============================================
        self.cps_limiter = TokenBucket(rate=settings.DEFAULT_CPS)
        self.global_limiter = GlobalRateLimiter(redis_client, "global_cps", rate=100)
        self.adaptive_cps = AdaptiveCPSLimiter(
            base_rate=settings.DEFAULT_CPS,
            redis_client=redis_client,
            max_calls=self.max_calls,
            min_rate=settings.MIN_CPS,
            alpha=settings.ADAPTIVE_CPS_ALPHA
        ) if settings.ADAPTIVE_CPS_ENABLED else None
        
        # =============================================
        # Lua скрипты
        # =============================================
        self._init_lua_scripts()
        
        # =============================================
        # Регистрация обработчиков событий
        # =============================================
        self.manager.register_event('*', self.handle_ami_event)
        
        # =============================================
        # Фоновые задачи
        # =============================================
        self._background_tasks: List[asyncio.Task] = []
        
        logger.info(f"DialerManager инициализирован (extension: {self.freepbx_extension})")
    
    # =============================================
    # Инициализация Lua скриптов
    # =============================================
    def _init_lua_scripts(self):
        """Инициализация Lua скриптов для атомарных операций"""
        
        # Резервирование слота с записью reservation
        self.RESERVE_WITH_RESERVATION_LUA = """
            local set_key = KEYS[1]
            local zset_key = KEYS[2]
            local reservations_key = KEYS[3]
            local limit = tonumber(ARGV[1])
            local channel_key = ARGV[2]
            local timestamp = tonumber(ARGV[3])
            local reservation_data = ARGV[4]
            
            local current = redis.call('SCARD', set_key)
            if current >= limit then
                return {0, limit}
            end
            
            redis.call('SADD', set_key, channel_key)
            redis.call('ZADD', zset_key, timestamp, channel_key)
            redis.call('HSET', reservations_key, channel_key, reservation_data)
            
            local set_exists = redis.call('EXISTS', set_key)
            if set_exists == 0 then
                redis.call('EXPIRE', set_key, 300)
                redis.call('EXPIRE', zset_key, 300)
                redis.call('EXPIRE', reservations_key, 300)
            end
            
            return {1, current + 1}
        """
        
        # Освобождение слота
        self.RELEASE_SLOT_LUA = """
            local set_key = KEYS[1]
            local zset_key = KEYS[2]
            local reservations_key = KEYS[3]
            local channel_key = ARGV[1]
            
            redis.call('SREM', set_key, channel_key)
            redis.call('ZREM', zset_key, channel_key)
            redis.call('HDEL', reservations_key, channel_key)
            
            return 1
        """
        
        # Проверка номера телефона (deduplication)
        self.CHECK_PHONE_LUA = """
            local key = KEYS[1]
            local phone = ARGV[1]
            local action_id = ARGV[2]
            
            local existing = redis.call('HGET', key, phone)
            
            if existing then
                local is_active = redis.call('SISMEMBER', 'active_channels', existing)
                if is_active == 1 then
                    return {0, existing}
                else
                    redis.call('HDEL', key, phone)
                end
            end
            
            redis.call('HSET', key, phone, action_id)
            redis.call('EXPIRE', key, 600)
            return {1, nil}
        """
        
        # Очистка устаревших каналов (батчами)
        self.CLEANUP_BATCHED_LUA = """
            local set_key = KEYS[1]
            local zset_key = KEYS[2]
            local timeout = tonumber(ARGV[1])
            local now = tonumber(ARGV[2])
            local batch_size = tonumber(ARGV[3]) or 100
            
            local stale = redis.call('ZRANGEBYSCORE', zset_key, 0, now - timeout, 'LIMIT', 0, batch_size)
            
            for _, channel in ipairs(stale) do
                redis.call('SREM', set_key, channel)
                redis.call('ZREM', zset_key, channel)
            end
            
            return #stale
        """
        
        # Переход состояния (state machine)
        self.TRANSITION_STATE_LUA = """
            local key = KEYS[1]
            local action_id = ARGV[1]
            local new_state = ARGV[2]
            
            local current = redis.call('HGET', key, action_id) or 'none'
            
            local allowed = {
                none = {'reserved'},
                reserved = {'dialing', 'hangup'},
                dialing = {'ringing', 'active', 'hangup'},
                ringing = {'active', 'hangup'},
                active = {'hangup'},
                hangup = {'terminated'},
                terminated = {}
            }
            
            local is_allowed = false
            for _, s in ipairs(allowed[current] or {}) do
                if s == new_state then
                    is_allowed = true
                    break
                end
            end
            
            if is_allowed then
                redis.call('HSET', key, action_id, new_state)
                redis.call('EXPIRE', key, 600)
                return 1
            end
            
            return 0
        """
    
    # =============================================
    # Управление подключением
    # =============================================
    async def connect(self) -> None:
        """Подключиться к AMI"""
        await self.ensure_connected()
        
        # Запускаем фоновые задачи
        self._start_background_tasks()
    
    async def ensure_connected(self):
        """Обеспечить подключение к AMI с повторными попытками"""
        while not self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self.manager.connect()
                self.connected = True
                self.reconnect_attempts = 0
                logger.info("✅ AMI подключён успешно")
                
                # Подписываемся на все события
                await self.manager.send_action(
                    panoramisk.message.Action('Events', {'EventMask': 'on'})
                )
                
            except Exception as e:
                self.reconnect_attempts += 1
                wait_time = min(2 ** self.reconnect_attempts, 60)
                logger.warning(
                    f"Ошибка подключения к AMI (попытка {self.reconnect_attempts}/{self.max_reconnect_attempts}): {e}"
                )
                await asyncio.sleep(wait_time)
        
        if not self.connected:
            raise AMIConnectionError("Не удалось подключиться к AMI")
    
    def _start_background_tasks(self):
        """Запустить фоновые задачи"""
        tasks = [
            self.watchdog_stale_calls(),
            self.queue_worker(),
            self.reconcile_channels(),
            self.load_state_from_redis(),
            self.health_check(),
            self.cleanup_stale_mappings(),
            self.cleanup_expired_reservations(),
            self._check_redis_health(),
            self._periodic_reconciliation(),
            self._monitor_redis_memory(),
            self._recover_degraded_queue(),
            self._update_metrics_loop(),
        ]
        
        for task_coro in tasks:
            task = asyncio.create_task(task_coro)
            self._background_tasks.append(task)
        
        logger.info(f"Запущено {len(tasks)} фоновых задач")
    
    async def disconnect(self) -> None:
        """Отключиться от AMI"""
        self.running = False
        
        # Останавливаем фоновые задачи
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._background_tasks.clear()
        
        # Останавливаем все активные звонки
        await self.stop_all_calls()
        
        # Закрываем соединение
        if self.connected:
            try:
                await self.manager.close()
            except Exception as e:
                logger.warning(f"Ошибка при закрытии AMI: {e}")
            self.connected = False
        
        logger.info("DialerManager отключён")
    
    async def health_check(self):
        """Периодическая проверка здоровья подключения"""
        while self.running:
            await asyncio.sleep(30)
            
            if not self.connected:
                logger.warning("AMI отключён, попытка переподключения...")
                await self.ensure_connected()
                continue
            
            try:
                action = panoramisk.message.Action('Ping')
                response = await asyncio.wait_for(
                    self.manager.send_action(action),
                    timeout=5.0
                )
                if not response or response.get('response') != 'Success':
                    raise Exception("Ping failed")
            except Exception as e:
                logger.error(f"Проверка здоровья AMI не пройдена: {e}")
                self.connected = False
                await self.ensure_connected()
    
    async def _check_redis_health(self):
        """Периодическая проверка здоровья Redis"""
        while self.running:
            await asyncio.sleep(10)
            
            try:
                await self.redis.ping()
                if self.degraded_mode:
                    logger.warning("Redis восстановлен, выход из degraded mode")
                    self.degraded_mode = False
                    degraded_mode_gauge.set(0)
                    await self._sync_channels_from_asterisk()
            except Exception:
                if not self.degraded_mode:
                    logger.error("Redis недоступен, переход в degraded mode")
                    self.degraded_mode = True
                    degraded_mode_gauge.set(1)
    
    # =============================================
    # Восстановление состояния
    # =============================================
    async def load_state_from_redis(self):
        """Восстановление состояния из Redis"""
        await asyncio.sleep(2)
        
        try:
            redis_channels = await self.redis.smembers(self.active_channels_key)
            logger.info(f"Загружено {len(redis_channels)} каналов из Redis")
            await self._sync_channels_from_asterisk()
        except Exception as e:
            logger.error(f"Ошибка восстановления состояния: {e}")
    
    async def _sync_channels_from_asterisk(self):
        """Полная синхронизация каналов с Asterisk"""
        if not self.connected:
            return
        
        try:
            action = panoramisk.message.Action('CoreShowChannels')
            response = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=10.0
            )
            
            asterisk_channels = set()
            for event in response.events:
                if event.get('event') == 'CoreShowChannel':
                    channel = event.get('channel')
                    unique_id = event.get('uniqueid')
                    if channel and channel.startswith('Local/'):
                        action_id = self._resolve_action_id(unique_id, None)
                        if action_id:
                            asterisk_channels.add(action_id)
            
            redis_channels = set(await self.redis.smembers(self.active_channels_key))
            
            missing = asterisk_channels - redis_channels
            phantom = redis_channels - asterisk_channels
            
            if missing:
                logger.warning(f"Каналы в Asterisk, но не в Redis: {len(missing)}")
            if phantom:
                logger.warning(f"Каналы в Redis, но не в Asterisk: {len(phantom)}")
                for action_id in phantom:
                    await self._force_cleanup(action_id, None)
            
            logger.info(f"Синхронизировано: Redis={len(redis_channels)}, Asterisk={len(asterisk_channels)}")
            
        except Exception as e:
            logger.error(f"Ошибка синхронизации каналов: {e}")
    
    async def _periodic_reconciliation(self):
        """Периодическая сверка состояния с Asterisk"""
        while self.running:
            await asyncio.sleep(60)
            if self.connected and not self.degraded_mode:
                await self._sync_channels_from_asterisk()
    
    # =============================================
    # Разрешение ActionID
    # =============================================
    def _resolve_action_id(
        self,
        unique_id: str,
        linked_id: Optional[str] = None,
        event_action_id: Optional[str] = None
    ) -> Optional[str]:
        """Многоуровневое разрешение ActionID"""
        if event_action_id:
            return event_action_id
        
        action_id = self.unique_to_action.get(unique_id)
        if action_id:
            return action_id
        
        if linked_id:
            action_id = self.unique_to_action.get(linked_id)
            if action_id:
                self.unique_to_action[unique_id] = action_id
                return action_id
        
        channel = self.channel_map.get(unique_id)
        if channel:
            for aid, ch in self.action_to_channel.items():
                if ch == channel:
                    self.unique_to_action[unique_id] = aid
                    return aid
        
        return None
    
    def _add_mapping(self, action_id: str, unique_id: str, channel: str = None):
        """Добавление mapping с обновлением всех индексов"""
        now = time.monotonic()
        
        self.action_to_channel[action_id] = channel
        self.unique_to_action[unique_id] = action_id
        self.action_created_at[action_id] = now
        
        if action_id not in self.action_to_uniques:
            self.action_to_uniques[action_id] = set()
        self.action_to_uniques[action_id].add(unique_id)
        
        if channel:
            self.channel_map[unique_id] = channel
    
    def _cleanup_mappings(self, action_id: str, unique_id: str = None):
        """Очистка mapping с использованием обратного индекса"""
        if action_id in self.action_to_channel:
            del self.action_to_channel[action_id]
        
        if action_id in self.action_to_uniques:
            for uid in self.action_to_uniques[action_id]:
                if uid in self.unique_to_action:
                    del self.unique_to_action[uid]
                if uid in self.channel_map:
                    del self.channel_map[uid]
                if uid in self.call_start_times:
                    del self.call_start_times[uid]
            del self.action_to_uniques[action_id]
        
        if unique_id and unique_id in self.unique_to_action:
            del self.unique_to_action[unique_id]
        
        if action_id in self.action_created_at:
            del self.action_created_at[action_id]
        
        # Удаляем контекст звонка
        if action_id in self.call_contexts:
            del self.call_contexts[action_id]
    
    async def _transition_state(self, action_id: str, new_state: CallState) -> bool:
        """Распределённый переход состояния через Redis"""
        result = await self.redis.eval(
            self.TRANSITION_STATE_LUA,
            1,
            self.call_state_key,
            action_id,
            new_state.value
        )
        
        if result == 1 and action_id in self.call_contexts:
            self.call_contexts[action_id].state = new_state
        
        return result == 1
    
    # =============================================
    # Нормализация номера
    # =============================================
    def normalize_phone(self, phone: str) -> Optional[str]:
        """Нормализация номера телефона"""
        if not phone:
            return None
        
        phone = re.sub(r'[^\d]', '', phone)
        
        if len(phone) == 11 and phone.startswith('7'):
            return phone
        elif len(phone) == 11 and phone.startswith('8'):
            return '7' + phone[1:]
        elif len(phone) == 10 and phone.startswith('9'):
            return '7' + phone
        
        if len(phone) >= 10:
            return phone
        
        return None
    
    # =============================================
    # Инициирование звонка
    # =============================================
    async def start_call(self, phone: str, campaign_id: int, retry: int = 0):
        """Постановка звонка в очередь"""
        normalized = self.normalize_phone(phone)
        if not normalized:
            logger.warning(f"Пропуск невалидного номера: {phone}")
            return
        
        # Проверяем чёрный список
        if await self.redis.is_blacklisted(normalized):
            logger.info(f"Пропуск номера из чёрного списка: {normalized}")
            return
        
        # Добавляем в очередь
        await self.redis.rpush(self.dial_queue_key, json.dumps({
            "phone": normalized,
            "campaign_id": campaign_id,
            "retry": retry,
            "queued_at": datetime.utcnow().isoformat()
        }))
        
        queue_size = await self.redis.llen(self.dial_queue_key)
        queue_size_gauge.set(queue_size)
        
        logger.debug(f"Звонок в очереди: {normalized} (кампания {campaign_id}), размер очереди: {queue_size}")
    
    async def queue_worker(self):
        """Фоновый обработчик очереди звонков"""
        logger.info("Обработчик очереди запущен")
        
        while self.running:
            try:
                result = await self.redis.blpop(self.dial_queue_key, timeout=1)
                
                if result:
                    _, job_data = result
                    data = json.loads(job_data)
                    await self._start_call(
                        data['phone'],
                        data['campaign_id'],
                        data.get('retry', 0)
                    )
                
                queue_size_gauge.set(await self.redis.llen(self.dial_queue_key))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка обработчика очереди: {e}")
                await asyncio.sleep(1)
        
        logger.info("Обработчик очереди остановлен")
    
    async def _start_call(self, phone: str, campaign_id: int, retry: int):
        """Внутренний метод инициации звонка"""
        if not self.running:
            return
        
        if not self.connected:
            logger.warning("AMI не подключен, звонок не может быть совершён")
            return
        
        normalized = self.normalize_phone(phone)
        if not normalized:
            return
        
        # Проверка, включена ли система
        if not await self.redis.is_system_enabled():
            logger.debug("Система отключена, звонок пропущен")
            return
        
        # Degraded mode
        if self.degraded_mode:
            await self._add_to_degraded_queue(normalized, campaign_id, retry)
            return
        
        # Проверка локального лимита
        async with self._local_estimate_lock:
            if time.monotonic() - self.last_redis_sync > 30:
                if self.local_active_estimate >= self.max_calls:
                    await self._requeue_call(normalized, campaign_id, retry)
                    return
        
        # Проверка номера (deduplication)
        action_id = f"call_{campaign_id}_{normalized}_{int(time.time()*1000)}"
        
        phone_result = await self.redis.eval(
            self.CHECK_PHONE_LUA,
            1,
            self.active_phones_key,
            normalized,
            action_id
        )
        
        if phone_result[0] == 0:
            logger.warning(f"Номер {normalized} уже в обработке: {phone_result[1]}")
            await asyncio.sleep(5)
            await self._requeue_call(normalized, campaign_id, retry)
            return
        
        # Проверка лимита каналов
        active = await self.redis.scard(self.active_channels_key)
        if active >= self.max_calls:
            await self._requeue_call(normalized, campaign_id, retry)
            return
        
        # Адаптивный CPS
        if self.adaptive_cps:
            cps_rate = await self.adaptive_cps.get_rate()
            self.cps_limiter.update_rate(cps_rate)
            cps_gauge.set(cps_rate)
        
        # Проверка CPS
        if not await self.cps_limiter.try_acquire():
            await self._requeue_call(normalized, campaign_id, retry)
            return
        
        # Атомарное резервирование
        reservation_data = json.dumps({
            "phone": normalized,
            "campaign_id": campaign_id,
            "retry": retry,
            "timestamp": int(time.time() * 1000),
            "state": "reserved"
        })
        
        result = await self.redis.eval(
            self.RESERVE_WITH_RESERVATION_LUA,
            3,
            self.active_channels_key,
            self.active_channels_ts_key,
            "reservations_data",
            self.max_calls,
            action_id,
            time.time(),
            reservation_data
        )
        
        if result[0] == 0:
            await self._requeue_call(normalized, campaign_id, retry)
            return
        
        slot_reserved = True
        await self._transition_state(action_id, CallState.RESERVED)
        
        # Создаём контекст звонка
        ctx = CallContext(
            action_id=action_id,
            campaign_id=campaign_id,
            phone=normalized,
            retry_count=retry,
            started_at=datetime.utcnow()
        )
        self.call_contexts[action_id] = ctx
        
        # Обновление локальной оценки
        async with self._local_estimate_lock:
            self.local_active_estimate = result[1]
            self.last_redis_sync = time.monotonic()
        
        # OpenTelemetry
        span = None
        traceparent = None
        if OTEL_AVAILABLE and tracer:
            span = tracer.start_span("originate", kind=SpanKind.CLIENT)
            span.set_attribute("action_id", action_id)
            span.set_attribute("phone", normalized)
            span.set_attribute("campaign_id", campaign_id)
            
            span_context = span.get_span_context()
            trace_id = format(span_context.trace_id, '032x')
            span_id = format(span_context.span_id, '016x')
            trace_flags = '01' if span_context.trace_flags.sampled else '00'
            traceparent = f"00-{trace_id}-{span_id}-{trace_flags}"
            ctx.traceparent = traceparent
            
            await self.redis.setex(f"trace:{action_id}", 60, traceparent)
        
        try:
            # Originate
            timeout_ms = self.call_timeout * 1000
            setvar = f'__CAMPAIGN_ID={campaign_id},__RETRY_COUNT={retry}'
            if traceparent:
                setvar += f',__TRACEPARENT={traceparent}'
            
            channel = f'Local/{normalized}@dialer_bridge/n'
            
            action = panoramisk.message.Action('Originate', {
                'Channel': channel,
                'Async': 'true',
                'Timeout': str(timeout_ms),
                'CallerID': f'"Camp_{campaign_id}" <{self.caller_id}>',
                'Setvar': setvar,
                'ActionID': action_id
            })
            
            response = await self.manager.send_action(action)
            
            if response and response.get('response') == 'Success':
                self._add_mapping(action_id, None, None)
                logger.info(f"📞 Originate OK: {action_id} -> {normalized}")
                
                calls_initiated_counter.labels(campaign_id=str(campaign_id)).inc()
                active_calls_gauge.set(len(self.channel_map))
                
                if self.adaptive_cps:
                    self.adaptive_cps.record_success()
                
                if span:
                    span.set_status(Status(StatusCode.OK))
            else:
                error_msg = response.get('message') if response else 'No response'
                raise OriginateError(f"Originate failed: {error_msg}")
                
        except Exception as e:
            logger.error(f"Originate failed for {normalized}: {e}")
            
            if self.adaptive_cps:
                self.adaptive_cps.record_failure()
            
            calls_failed_counter.labels(
                campaign_id=str(campaign_id),
                reason='originate_failed'
            ).inc()
            
            if slot_reserved:
                await self.redis.eval(
                    self.RELEASE_SLOT_LUA,
                    3,
                    self.active_channels_key,
                    self.active_channels_ts_key,
                    "reservations_data",
                    action_id
                )
                await self._cleanup_phone_mapping(action_id)
                self._cleanup_mappings(action_id)
            
            await self._save_call_result(
                campaign_id, normalized, 'originate_failed', None, None, retry
            )
            
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
        finally:
            if span:
                span.end()
    
    async def _requeue_call(self, phone: str, campaign_id: int, retry: int):
        """Переставить звонок в очередь"""
        await self.redis.rpush(self.dial_queue_key, json.dumps({
            "phone": phone,
            "campaign_id": campaign_id,
            "retry": retry
        }))
    
    # =============================================
    # Обработка событий AMI
    # =============================================
    async def handle_ami_event(self, manager, event):
        """Главный обработчик событий AMI"""
        event_name = event.name
        channel = event.get('channel', '')
        unique_id = event.get('uniqueid')
        linked_id = event.get('linkedid')
        
        # Пропускаем не наши каналы
        if channel and not channel.startswith('Local/'):
            return
        
        # Дедупликация
        event_key = f"{event_name}_{unique_id}"
        if event_key in self.processed_events:
            return
        self.processed_events[event_key] = True
        
        try:
            if event_name == 'DialBegin':
                await self._handle_dial_begin(event, channel, unique_id)
            elif event_name == 'DialEnd':
                await self._handle_dial_end(event, unique_id)
            elif event_name == 'BridgeEnter':
                await self._handle_bridge_enter(event, unique_id, linked_id)
            elif event_name == 'Hangup':
                await self._handle_hangup(event, channel, unique_id, linked_id)
            elif event_name == 'UserEvent':
                await self._handle_user_event(event, linked_id)
            elif event_name == 'DTMF':
                await self._handle_dtmf(event, unique_id)
        except Exception as e:
            logger.error(f"Ошибка обработки события {event_name}: {e}", exc_info=True)
    
    async def _handle_dial_begin(self, event, channel: str, unique_id: str):
        """Обработка DialBegin"""
        action_id = self._resolve_action_id(unique_id, None, event.get('actionid'))
        
        if not action_id:
            logger.warning(f"DialBegin без ActionID: {unique_id}")
            return
        
        # Проверка reservation
        reservation = await self.redis.hget("reservations_data", action_id)
        if reservation:
            data = json.loads(reservation)
            data['state'] = 'confirmed'
            await self.redis.hset("reservations_data", action_id, json.dumps(data))
            logger.debug(f"Reservation подтверждена: {action_id}")
        
        # Обновление ZSET
        await self.redis.zadd(self.active_channels_ts_key, {action_id: time.time()})
        
        # Обновление mapping
        self._add_mapping(action_id, unique_id, channel)
        self.call_start_times[unique_id] = datetime.utcnow()
        
        # Обновление контекста
        if action_id in self.call_contexts:
            ctx = self.call_contexts[action_id]
            ctx.unique_id = unique_id
            ctx.channel = channel
        
        # State transition
        await self._transition_state(action_id, CallState.DIALING)
        
        # OpenTelemetry
        traceparent = await self.redis.get(f"trace:{action_id}")
        if traceparent and OTEL_AVAILABLE:
            parts = traceparent.split('-')
            if len(parts) == 4:
                remote_context = SpanContext(
                    trace_id=int(parts[1], 16),
                    span_id=int(parts[2], 16),
                    is_remote=True,
                    trace_flags=TraceFlags(int(parts[3], 16))
                )
                with tracer.start_as_current_span("dial_begin", context=remote_context) as span:
                    span.set_attribute("action_id", action_id)
                    span.add_event("channel_created")
        
        active = await self.redis.scard(self.active_channels_key)
        active_calls_gauge.set(active)
        
        logger.debug(f"DialBegin: {action_id}, канал={channel}, активно={active}")
    
    async def _handle_dial_end(self, event, unique_id: str):
        """Обработка DialEnd"""
        dial_status = event.get('dialstatus', 'UNKNOWN')
        logger.debug(f"DialEnd: {unique_id}, status: {dial_status}")
    
    async def _handle_bridge_enter(self, event, unique_id: str, linked_id: str):
        """Обработка BridgeEnter (абонент ответил)"""
        action_id = self._resolve_action_id(unique_id, linked_id)
        if action_id:
            await self._transition_state(action_id, CallState.ACTIVE)
            
            if action_id in self.call_contexts:
                ctx = self.call_contexts[action_id]
                ctx.answered_at = datetime.utcnow()
                ctx.linked_id = linked_id
                
                calls_answered_counter.labels(campaign_id=str(ctx.campaign_id)).inc()
            
            if unique_id in self.call_start_times:
                del self.call_start_times[unique_id]
            
            logger.info(f"✅ Абонент ответил: {action_id}")
    
    async def _handle_hangup(self, event, channel: str, unique_id: str, linked_id: str):
        """Обработка Hangup"""
        # Дедупликация
        hangup_key = f"hangup_{unique_id}"
        if hangup_key in self.hangup_events:
            return
        self.hangup_events[hangup_key] = True
        
        # Redis дедупликация
        redis_hangup_key = REDIS_KEYS.hangup_key(unique_id)
        if not await self.redis.set(redis_hangup_key, "1", ex=10, nx=True):
            return
        
        action_id = self._resolve_action_id(unique_id, linked_id, event.get('actionid'))
        
        if not action_id:
            logger.critical(f"Невозможно разрешить ActionID для unique_id={unique_id}")
            self._force_cleanup(unique_id)
            return
        
        if action_id in self.terminated_calls:
            return
        self.terminated_calls.add(action_id)
        
        await self._transition_state(action_id, CallState.HANGUP)
        
        cause = event.get('cause', '0')
        cause_txt = event.get('cause-txt', 'UNKNOWN')
        
        # Обновление контекста
        ctx = self.call_contexts.get(action_id)
        if ctx:
            ctx.hungup_at = datetime.utcnow()
            ctx.hangup_cause = cause_txt
            
            if ctx.answered_at:
                ctx.duration = int((ctx.hungup_at - ctx.answered_at).total_seconds())
                if ctx.duration > 0:
                    call_duration_histogram.observe(ctx.duration)
        
        # Атомарное удаление
        await self.redis.eval(
            self.RELEASE_SLOT_LUA,
            3,
            self.active_channels_key,
            self.active_channels_ts_key,
            "reservations_data",
            action_id
        )
        
        await self._cleanup_phone_mapping(action_id)
        self._cleanup_mappings(action_id, unique_id)
        
        await self._transition_state(action_id, CallState.TERMINATED)
        
        # Обновление локальной оценки
        async with self._local_estimate_lock:
            if self.local_active_estimate > 0:
                self.local_active_estimate -= 1
        
        active = await self.redis.scard(self.active_channels_key)
        await self.redis.set(REDIS_KEYS.ACTIVE_CALLS, str(active))
        active_calls_gauge.set(active)
        
        # Сохраняем результат
        if ctx:
            status = self._map_hangup_cause_to_status(cause_txt)
            if ctx.answered_at:
                status = 'agreed'  # Упрощённо, в реальности зависит от DTMF
            await self._save_call_result(
                ctx.campaign_id,
                ctx.phone,
                status,
                linked_id,
                unique_id,
                ctx.retry_count
            )
        
        logger.info(f"📴 Hangup: {action_id}, причина={cause_txt}, активно={active}")
        
        asyncio.create_task(self._cleanup_terminated(action_id))
    
    async def _handle_user_event(self, event, linked_id: str):
        """Обработка UserEvent"""
        userevent = event.get('userevent')
        
        if userevent == 'DialerResult':
            status = event.get('status', 'unknown')
            campaign_id = event.get('campaign', '0')
            phone = event.get('phone', '')
            retry_count = int(event.get('retrycount', '0'))
            
            logger.info(f"🎯 DialerResult: кампания={campaign_id}, телефон={phone}, статус={status}")
            
            await self._save_call_result(
                int(campaign_id) if campaign_id else 0,
                phone,
                status,
                linked_id,
                None,
                retry_count
            )
            
            if status in ['noanswer', 'busy', 'failed']:
                await self._schedule_retry(int(campaign_id) if campaign_id else 0, phone, retry_count + 1, status)
    
    async def _handle_dtmf(self, event, unique_id: str):
        """Обработка DTMF"""
        digit = event.get('digit')
        action_id = self._resolve_action_id(unique_id, None)
        
        if action_id and action_id in self.call_contexts:
            ctx = self.call_contexts[action_id]
            ctx.dtmf_digits.append(digit)
            logger.debug(f"DTMF: {action_id} -> {digit}")
    
    def _map_hangup_cause_to_status(self, cause: str) -> str:
        """Преобразование причины Hangup в статус"""
        cause_upper = cause.upper()
        
        if 'BUSY' in cause_upper:
            return 'busy'
        elif 'NO_ANSWER' in cause_upper or 'NOANSWER' in cause_upper:
            return 'noanswer'
        elif 'CONGESTION' in cause_upper:
            return 'congestion'
        elif 'CANCEL' in cause_upper:
            return 'canceled'
        elif 'CHANUNAVAIL' in cause_upper:
            return 'chanunavail'
        else:
            return 'failed'
    
    # =============================================
    # Сохранение результатов
    # =============================================
    async def _save_call_result(
        self,
        campaign_id: int,
        phone: str,
        status: str,
        linked_id: Optional[str],
        unique_id: Optional[str],
        retry: int
    ):
        """Сохранение результата звонка"""
        if self.call_result_service:
            try:
                from app.models.call import CallResultCreateRequest, CallResultStatus
                
                request = CallResultCreateRequest(
                    campaign_id=campaign_id if campaign_id > 0 else None,
                    phone=phone,
                    status=CallResultStatus(status) if status in [s.value for s in CallResultStatus] else CallResultStatus.FAILED,
                    unique_id=unique_id,
                    linked_id=linked_id,
                    retry_count=retry
                )
                
                await self.call_result_service.save_call_result(request)
            except Exception as e:
                logger.error(f"Ошибка сохранения результата звонка: {e}")
        else:
            # Fallback: сохраняем напрямую в БД
            try:
                normalized = self.normalize_phone(phone)
                if not normalized:
                    return
                
                async with self.db_pool.acquire() as conn:
                    contact_id = await conn.fetchval("""
                        INSERT INTO contacts (phone) VALUES ($1) 
                        ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone 
                        RETURNING id
                    """, normalized)
                    
                    await conn.execute("""
                        INSERT INTO call_results 
                        (campaign_id, contact_id, linked_id, unique_id, status, retry_count)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, campaign_id if campaign_id > 0 else None, contact_id, linked_id, unique_id, status, retry)
                    
                    logger.debug(f"Результат сохранён: {normalized} -> {status}")
                    
            except Exception as e:
                logger.error(f"Ошибка сохранения результата: {e}")
    
    async def _schedule_retry(self, campaign_id: int, phone: str, retry_count: int, status: str):
        """Планирование повторного звонка"""
        strategies = {
            'busy': {'max': 2, 'delay': settings.RETRY_BUSY_DELAY},
            'noanswer': {'max': 3, 'delay': settings.RETRY_NOANSWER_DELAY},
            'failed': {'max': 1, 'delay': settings.RETRY_FAILED_DELAY},
            'timeout': {'max': 1, 'delay': 60}
        }
        
        strategy = strategies.get(status, {'max': 1, 'delay': 60})
        
        if retry_count >= strategy['max']:
            logger.info(f"Достигнут максимум повторов ({strategy['max']}) для {phone}")
            return
        
        if campaign_id <= 0:
            return
        
        try:
            normalized = self.normalize_phone(phone)
            if not normalized:
                return
            
            # Jitter
            base_delay = strategy['delay']
            jitter = random.expovariate(1.0 / (base_delay * 0.2))
            jitter = min(jitter, base_delay * 0.5)
            actual_delay = base_delay + (jitter if random.random() > 0.5 else -jitter)
            actual_delay = max(1, actual_delay)
            
            next_retry = datetime.utcnow() + timedelta(seconds=actual_delay)
            
            async with self.db_pool.acquire() as conn:
                contact_id = await conn.fetchval(
                    "SELECT id FROM contacts WHERE phone = $1", normalized
                )
                if contact_id:
                    await conn.execute("""
                        UPDATE campaign_contacts 
                        SET next_retry_at = $1, retry_count = $2
                        WHERE campaign_id = $3 AND contact_id = $4
                    """, next_retry, retry_count, campaign_id, contact_id)
            
            logger.info(f"⏰ Запланирован повтор {retry_count}/{strategy['max']} для {normalized} через {actual_delay:.1f}с")
            
        except Exception as e:
            logger.error(f"Ошибка планирования повтора: {e}")
    
    # =============================================
    # Очистка
    # =============================================
    async def _cleanup_phone_mapping(self, action_id: str):
        """Очистка привязки номера"""
        reservation = await self.redis.hget("reservations_data", action_id)
        if reservation:
            try:
                data = json.loads(reservation)
                phone = data.get('phone')
                if phone:
                    lua_cleanup = """
                        local key = KEYS[1]
                        local phone = ARGV[1]
                        local action_id = ARGV[2]
                        local current = redis.call('HGET', key, phone)
                        if current == action_id then
                            redis.call('HDEL', key, phone)
                            return 1
                        end
                        return 0
                    """
                    await self.redis.eval(lua_cleanup, 1, self.active_phones_key, phone, action_id)
            except Exception:
                pass
    
    async def _force_cleanup(self, unique_id: str, action_id: str = None):
        """Принудительная очистка"""
        if not action_id:
            action_id = self.unique_to_action.get(unique_id)
        
        if action_id:
            await self.redis.eval(
                self.RELEASE_SLOT_LUA,
                3,
                self.active_channels_key,
                self.active_channels_ts_key,
                "reservations_data",
                action_id
            )
            await self._cleanup_phone_mapping(action_id)
            self._cleanup_mappings(action_id, unique_id)
    
    async def _cleanup_terminated(self, action_id: str):
        """Отложенная очистка terminated calls"""
        await asyncio.sleep(60)
        self.terminated_calls.discard(action_id)
    
    async def cleanup_stale_mappings(self):
        """Очистка устаревших mapping'ов"""
        while self.running:
            await asyncio.sleep(60)
            
            now = time.monotonic()
            stale = []
            
            for action_id, created_at in list(self.action_created_at.items()):
                if now - created_at > 600:
                    stale.append(action_id)
            
            if stale:
                pipe = self.redis.pipeline()
                for action_id in stale:
                    pipe.sismember(self.active_channels_key, action_id)
                results = await pipe.execute()
                
                for action_id, is_active in zip(stale, results):
                    if not is_active:
                        self._cleanup_mappings(action_id, None)
                
                logger.debug(f"Очищено {len(stale) - sum(results)} устаревших mapping'ов")
    
    async def cleanup_expired_reservations(self):
        """Очистка просроченных reservation"""
        while self.running:
            await asyncio.sleep(15)
            
            now = time.time()
            cutoff = now - 30
            
            expired = await self.redis.zrangebyscore(
                self.reservations_ts_key,
                0,
                cutoff
            )
            
            for action_id in expired:
                data = await self.redis.hget("reservations_data", action_id)
                if not data:
                    continue
                
                try:
                    reservation = json.loads(data)
                    res_timestamp = reservation.get('timestamp', 0) / 1000
                    age = now - res_timestamp
                    state = reservation.get('state', 'reserved')
                    
                    if state == 'reserved' and 30 <= age < 60:
                        continue  # Grace window
                    
                    if state == 'reserved' and age >= 60:
                        await self.redis.eval(
                            self.RELEASE_SLOT_LUA,
                            3,
                            self.active_channels_key,
                            self.active_channels_ts_key,
                            "reservations_data",
                            action_id
                        )
                        logger.warning(f"Откат просроченной reservation: {action_id}")
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки reservation {action_id}: {e}")
                
                await self.redis.zrem(self.reservations_ts_key, action_id)
                await self.redis.hdel("reservations_data", action_id)
    
    # =============================================
    # Watchdog
    # =============================================
    async def watchdog_stale_calls(self):
        """Убийство зависших звонков с sampling"""
        logger.info("Watchdog запущен")
        
        while self.running:
            await asyncio.sleep(30)
            
            now = datetime.utcnow()
            max_duration = timedelta(minutes=5)
            
            candidates = []
            for unique_id, start_time in list(self.call_start_times.items()):
                if now - start_time > max_duration:
                    candidates.append(unique_id)
            
            if not candidates:
                continue
            
            sample_size = min(20, max(1, len(candidates) // 10))
            to_check = random.sample(candidates, sample_size) if len(candidates) > sample_size else candidates
            
            killed = 0
            for unique_id in to_check:
                action_id = self.unique_to_action.get(unique_id)
                channel = self.channel_map.get(unique_id)
                
                if channel and action_id:
                    is_alive = await self._check_channel_alive(channel)
                    
                    if not is_alive:
                        await self._force_cleanup(unique_id, action_id)
                        killed += 1
                    else:
                        try:
                            await self.manager.send_action(
                                panoramisk.message.Action('Hangup', {'Channel': channel})
                            )
                        except Exception as e:
                            logger.error(f"Ошибка Hangup: {e}")
                        
                        await self._force_cleanup(unique_id, action_id)
                        killed += 1
            
            if killed > 0:
                logger.info(f"Watchdog: убито {killed} звонков (проверено {len(to_check)})")
    
    async def _check_channel_alive(self, channel: str) -> bool:
        """Проверка живости канала"""
        if not self.connected:
            return False
        
        try:
            action = panoramisk.message.Action('CoreShowChannel', {'Channel': channel})
            response = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=2.0
            )
            for event in response.events:
                if event.get('event') == 'CoreShowChannel':
                    return True
            return False
        except Exception:
            return False
    
    # =============================================
    # Degraded mode
    # =============================================
    async def _add_to_degraded_queue(self, phone: str, campaign_id: int, retry: int):
        """Добавление в degraded очередь"""
        now = time.time()
        
        # Очистка старых записей
        self._local_queue = [
            item for item in self._local_queue
            if now - item.get('timestamp', 0) < self.LOCAL_QUEUE_MAX_AGE
        ]
        
        if len(self._local_queue) < self.MAX_LOCAL_QUEUE:
            item = {
                "_id": str(uuid.uuid4()),
                "phone": phone,
                "campaign_id": campaign_id,
                "retry": retry,
                "timestamp": now
            }
            self._local_queue.append(item)
            
            # Сохраняем в файл
            try:
                os.makedirs(os.path.dirname(self.degraded_queue_file), exist_ok=True)
                with open(self.degraded_queue_file, 'a') as f:
                    f.write(json.dumps(item) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                logger.error(f"Ошибка записи в degraded queue: {e}")
        
        await asyncio.sleep(5)
    
    async def _recover_degraded_queue(self):
        """Восстановление из degraded queue"""
        await asyncio.sleep(5)
        
        if not os.path.exists(self.degraded_queue_file):
            return
        
        try:
            with open(self.degraded_queue_file, 'r') as f:
                lines = f.readlines()
            
            # Очищаем файл
            with open(self.degraded_queue_file, 'w') as f:
                f.truncate(0)
            
            items = []
            for line in lines:
                try:
                    items.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass
            
            logger.info(f"Восстановление {len(items)} звонков из degraded queue")
            
            for item in items:
                age = time.time() - item.get('timestamp', 0)
                if age < 3600:
                    await self.start_call(item['phone'], item['campaign_id'], item.get('retry', 0))
                    await asyncio.sleep(1.0 / self.recovery_cps)
            
        except Exception as e:
            logger.error(f"Ошибка восстановления degraded queue: {e}")
    
    # =============================================
    # Мониторинг
    # =============================================
    async def _monitor_redis_memory(self):
        """Мониторинг памяти Redis"""
        while self.running:
            await asyncio.sleep(60)
            
            try:
                info = await self.redis.client.info('memory')
                used_memory = info.get('used_memory', 0)
                
                if used_memory > 500 * 1024 * 1024:  # 500 MB
                    logger.critical(f"Redis memory превышен: {used_memory / 1024 / 1024:.1f} MB")
                    
                    cleaned = 0
                    for _ in range(10):
                        result = await self.redis.eval(
                            self.CLEANUP_BATCHED_LUA,
                            2,
                            self.active_channels_key,
                            self.active_channels_ts_key,
                            30,
                            time.time(),
                            100
                        )
                        cleaned += result
                        if result < 100:
                            break
                        await asyncio.sleep(0.1)
                    
                    logger.warning(f"Экстренная очистка: удалено {cleaned} записей")
                    
            except Exception as e:
                logger.error(f"Ошибка мониторинга памяти Redis: {e}")
    
    async def _update_metrics_loop(self):
        """Обновление метрик"""
        while self.running:
            await asyncio.sleep(15)
            
            try:
                active = len(self.channel_map)
                active_calls_gauge.set(active)
                
                queue_size = await self.redis.llen(self.dial_queue_key)
                queue_size_gauge.set(queue_size)
                
                if self.adaptive_cps:
                    cps_gauge.set(await self.adaptive_cps.get_rate())
            except Exception as e:
                logger.error(f"Ошибка обновления метрик: {e}")
    
    # =============================================
    # Управление звонками
    # =============================================
    async def stop_all_calls(self) -> int:
        """Экстренная остановка всех звонков"""
        killed = 0
        
        for unique_id, channel in list(self.channel_map.items()):
            try:
                if self.connected:
                    action = panoramisk.message.Action('Hangup', {'Channel': channel})
                    await self.manager.send_action(action)
                    killed += 1
                    logger.info(f"Принудительно завершён звонок: {unique_id} на {channel}")
            except Exception as e:
                logger.error(f"Ошибка принудительного завершения {unique_id}: {e}")
        
        # Очистка состояния
        await self.redis.delete(self.active_channels_key)
        await self.redis.delete(self.active_channels_ts_key)
        await self.redis.delete(self.channels_hash_key)
        await self.redis.set(REDIS_KEYS.ACTIVE_CALLS, "0")
        
        self.channel_map.clear()
        self.call_start_times.clear()
        self.call_contexts.clear()
        
        active_calls_gauge.set(0)
        
        logger.warning(f"Экстренная остановка завершена, убито {killed} звонков")
        return killed
    
    async def reconcile_channels(self):
        """Периодическая сверка каналов"""
        while self.running:
            await asyncio.sleep(300)  # Каждые 5 минут
            
            if not self.running or not self.connected:
                continue
            
            try:
                redis_count = await self.redis.scard(self.active_channels_key)
                local_count = len(self.channel_map)
                
                if abs(redis_count - local_count) > max(5, redis_count * 0.1):
                    logger.warning(f"Расхождение каналов: Redis={redis_count}, Local={local_count}")
                    await self._sync_channels_from_asterisk()
            except Exception as e:
                logger.error(f"Ошибка сверки каналов: {e}")
    
    # =============================================
    # Статус
    # =============================================
    def get_status(self) -> dict:
        """Получить текущий статус"""
        return {
            "connected": self.connected,
            "running": self.running,
            "active_calls": len(self.channel_map),
            "max_calls": self.max_calls,
            "queue_size": 0,
            "cps_rate": self.cps_limiter.rate,
            "adaptive_cps": self.adaptive_cps.get_stats() if self.adaptive_cps else None,
            "freepbx_extension": self.freepbx_extension,
            "degraded_mode": self.degraded_mode,
            "reconnect_attempts": self.reconnect_attempts
        }
    
    async def get_queue_size(self) -> int:
        """Получить размер очереди"""
        return await self.redis.llen(self.dial_queue_key)
    
    async def get_active_channels(self) -> list:
        """Получить список активных каналов"""
        channels = []
        for unique_id, channel in self.channel_map.items():
            start_time = self.call_start_times.get(unique_id)
            ctx = None
            for c in self.call_contexts.values():
                if c.unique_id == unique_id:
                    ctx = c
                    break
            
            channels.append({
                "unique_id": unique_id,
                "channel": channel,
                "action_id": self.unique_to_action.get(unique_id),
                "campaign_id": ctx.campaign_id if ctx else None,
                "phone": ctx.phone if ctx else None,
                "state": ctx.state.value if ctx else "unknown",
                "started_at": start_time.isoformat() if start_time else None,
                "duration": (datetime.utcnow() - start_time).seconds if start_time else 0
            })
        return channels


# =============================================
# Сервис-обёртка
# =============================================
class DialerService:
    """
    Сервис-обёртка для DialerManager.
    Предоставляет удобный интерфейс для работы с дозвоном.
    """
    
    def __init__(self, dialer_manager: DialerManager):
        self.manager = dialer_manager
        logger.info("DialerService инициализирован")
    
    async def start_call(self, phone: str, campaign_id: int, retry: int = 0):
        """Запустить звонок"""
        await self.manager.start_call(phone, campaign_id, retry)
    
    async def stop_all_calls(self) -> int:
        """Остановить все звонки"""
        return await self.manager.stop_all_calls()
    
    async def get_status(self) -> dict:
        """Получить статус"""
        return self.manager.get_status()
    
    async def get_active_calls(self) -> list:
        """Получить активные звонки"""
        return await self.manager.get_active_channels()
    
    async def get_queue_size(self) -> int:
        """Получить размер очереди"""
        return await self.manager.get_queue_size()
    
    async def enable_system(self):
        """Включить систему"""
        self.manager.running = True
        await self.manager.redis.enable_system()
    
    async def disable_system(self):
        """Выключить систему"""
        self.manager.running = False
        await self.manager.redis.disable_system()
        await self.stop_all_calls()
        await self.manager.redis.clear_dial_queue()
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья"""
        return {
            "status": "healthy" if self.manager.connected else "unhealthy",
            "connected": self.manager.connected,
            "active_calls": len(self.manager.channel_map),
            "queue_size": await self.get_queue_size(),
            "degraded_mode": self.manager.degraded_mode
        }
    
    async def shutdown(self):
        """Корректное завершение"""
        await self.manager.disconnect()


# =============================================
# Глобальные экземпляры
# =============================================
_dialer_manager: Optional[DialerManager] = None
_dialer_service: Optional[DialerService] = None


async def init_dialer(
    db_pool: ConnectionPool,
    redis_client: RedisClient,
    call_result_service=None
) -> DialerManager:
    """Инициализировать DialerManager"""
    global _dialer_manager, _dialer_service
    
    _dialer_manager = DialerManager(db_pool, redis_client, call_result_service)
    await _dialer_manager.connect()
    
    _dialer_service = DialerService(_dialer_manager)
    
    return _dialer_manager


async def close_dialer():
    """Закрыть DialerManager"""
    global _dialer_manager, _dialer_service
    
    if _dialer_manager:
        await _dialer_manager.disconnect()
        _dialer_manager = None
        _dialer_service = None


def get_dialer_manager() -> Optional[DialerManager]:
    """Получить глобальный экземпляр DialerManager"""
    return _dialer_manager


def get_dialer_service() -> Optional[DialerService]:
    """Получить глобальный экземпляр DialerService"""
    return _dialer_service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "DialerManager",
    "DialerService",
    "CallState",
    "CallContext",
    "DialerError",
    "AMIConnectionError",
    "OriginateError",
    "DialerNotReadyError",
    "init_dialer",
    "close_dialer",
    "get_dialer_manager",
    "get_dialer_service",
]
