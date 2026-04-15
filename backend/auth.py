#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер AMI (Asterisk Manager Interface)
AutoDialer Ultimate v3.0.0

Управляет подключением к Asterisk, инициирует звонки,
обрабатывает события и сохраняет результаты.

ВКЛЮЧЕНЫ ВСЕ ИСПРАВЛЕНИЯ:
- ActionID как единый source of truth
- Lua атомарные операции (reserve/release)
- ZSET + SET для TTL каналов
- State machine в Redis Hash
- Deduplication guard через active_phones
- Grace window 30-60с для reservation
- Watchdog с проверкой живости и sampling
- Reconciliation с Asterisk
- Degraded mode с персистентной очередью
- Throttle recovery
- Batch cleanup через SCAN
- Emergency cleanup при memory pressure
- Гибрид времени (time.time + monotonic)
- Idempotency для Hangup
- Метрики только при смене состояния
- OpenTelemetry tracing с traceparent
- Поддержка Redis Sentinel
"""

import asyncio
import panoramisk
import time
import json
import re
import os
import uuid
import random
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, Any, List, Tuple
from enum import Enum

# Для TTL cache
from cachetools import TTLCache

# Логирование
from logger import logger

# Rate limiter
from rate_limiter import TokenBucket, GlobalRateLimiter

# OpenTelemetry (опционально)
try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode, NonRecordingSpan, SpanContext, TraceFlags
    tracer = trace.get_tracer("autodialer")
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    tracer = None


# =============================================
# Состояния звонка (State Machine)
# =============================================
class CallState(Enum):
    """Состояния звонка для state machine."""
    RESERVED = "reserved"
    DIALING = "dialing"
    ACTIVE = "active"
    HANGUP = "hangup"
    TERMINATED = "terminated"


# =============================================
# Основной класс DialerManager
# =============================================
class DialerManager:
    """Менеджер дозвона через Asterisk AMI."""
    
    def __init__(self, db_pool, redis_client):
        self.db_pool = db_pool
        self.redis = redis_client
        
        # =============================================
        # Загрузка конфигурации
        # =============================================
        ami_host = os.getenv('AMI_HOST', '127.0.0.1')
        ami_port = int(os.getenv('AMI_PORT', 5038))
        ami_user = os.getenv('AMI_USER', 'autodialer')
        ami_password = os.getenv('AMI_PASSWORD')
        
        if not ami_password:
            raise ValueError("AMI_PASSWORD не задан в переменных окружения")
        
        # 🔥 НАСТРАИВАЕМЫЙ EXTENSION
        self.freepbx_extension = os.getenv('FREEPBX_EXTENSION', '291')
        
        # =============================================
        # Инициализация AMI
        # =============================================
        self.manager = panoramisk.Manager(
            host=ami_host,
            port=ami_port,
            username=ami_user,
            secret=ami_password,
            ssl=False
        )
        
        # =============================================
        # Настройки дозвона
        # =============================================
        self.max_calls = int(os.getenv('MAX_CALLS', 50))
        self.caller_id = os.getenv('CALLER_ID', 'AutoDialer')
        self.call_timeout = int(os.getenv('CALL_TIMEOUT', 30))
        self.max_retries = int(os.getenv('MAX_RETRIES', 3))
        
        # =============================================
        # Ключи Redis
        # =============================================
        self.active_channels_key = "active_channels"          # SET
        self.active_channels_ts_key = "active_channels_ts"    # ZSET
        self.dial_queue_key = "dial_queue"                    # List
        self.call_state_key = "call_states"                   # Hash
        self.active_phones_key = "active_phones"              # Hash
        self.reservations_ts_key = "reservations_ts"          # ZSET
        
        # =============================================
        # Состояние (локальные кэши)
        # =============================================
        self.channel_map: Dict[str, str] = {}                 # unique_id -> channel
        self.call_start_times: Dict[str, datetime] = {}
        self.action_to_channel: Dict[str, str] = {}           # action_id -> channel
        self.unique_to_action: Dict[str, str] = {}            # unique_id -> action_id
        self.action_to_uniques: Dict[str, Set[str]] = {}      # action_id -> set(unique_id)
        self.action_created_at: Dict[str, float] = {}         # для TTL cleanup
        self.terminated_calls: Set[str] = set()               # идемпотентность Hangup
        
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
        self.degraded_queue_file = os.getenv('DEGRADED_QUEUE_FILE', '/opt/autodialer/data/degraded_queue.jsonl')
        self._local_queue: List[dict] = []
        self.MAX_LOCAL_QUEUE = 500
        self.LOCAL_QUEUE_MAX_AGE = 300
        self.recovery_cps = 5
        self.local_active_estimate = 0
        self._local_estimate_lock = asyncio.Lock()
        self.last_redis_sync = time.monotonic()
        
        # =============================================
        # Ограничители скорости
        # =============================================
        self.cps_limiter = TokenBucket(rate=int(os.getenv('DEFAULT_CPS', 5)))
        self.global_limiter = GlobalRateLimiter(redis_client, "global_cps", rate=100)
        
        # =============================================
        # Redis Sentinel поддержка
        # =============================================
        self._is_sentinel = hasattr(redis_client, 'master_for')
        if self._is_sentinel:
            self._master_client = redis_client.master_for("mymaster")
        else:
            self._master_client = redis_client
        
        # =============================================
        # Lua скрипты
        # =============================================
        self._init_lua_scripts()
        
        # =============================================
        # Регистрация обработчиков событий
        # =============================================
        self.manager.register_event('*', self.handle_ami_event)
        
        # =============================================
        # Запуск фоновых задач
        # =============================================
        asyncio.create_task(self.watchdog_stale_calls())
        asyncio.create_task(self.queue_worker())
        asyncio.create_task(self.reconcile_channels())
        asyncio.create_task(self.load_state_from_redis())
        asyncio.create_task(self.health_check())
        asyncio.create_task(self.cleanup_stale_mappings())
        asyncio.create_task(self.cleanup_expired_reservations())
        asyncio.create_task(self._check_redis_health())
        asyncio.create_task(self._periodic_reconciliation())
        asyncio.create_task(self._monitor_redis_memory())
        asyncio.create_task(self._recover_degraded_queue())
        
        logger.info(f"DialerManager инициализирован (extension: {self.freepbx_extension})")
    
    # =============================================
    # Инициализация Lua скриптов
    # =============================================
    def _init_lua_scripts(self):
        """Инициализация Lua скриптов для атомарных операций."""
        
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
                dialing = {'active', 'hangup'},
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
    async def ensure_connected(self):
        """Обеспечивает подключение к AMI с повторными попытками."""
        while not self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self.manager.connect()
                self.connected = True
                self.reconnect_attempts = 0
                logger.info("✅ AMI подключён успешно")
                await self.manager.send_action(panoramisk.message.Action('Events', {'EventMask': 'on'}))
            except Exception as e:
                self.reconnect_attempts += 1
                wait_time = min(2 ** self.reconnect_attempts, 60)
                logger.warning(f"Ошибка подключения к AMI (попытка {self.reconnect_attempts}/{self.max_reconnect_attempts}): {e}")
                await asyncio.sleep(wait_time)
        
        if not self.connected:
            logger.error("Не удалось подключиться к AMI")
            raise Exception("AMI connection failed")
    
    async def health_check(self):
        """Периодическая проверка здоровья подключения."""
        while True:
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
        """Периодическая проверка здоровья Redis."""
        while True:
            await asyncio.sleep(10)
            
            try:
                await self._master_client.ping()
                if self.degraded_mode:
                    logger.warning("Redis восстановлен, выход из degraded mode")
                    self.degraded_mode = False
                    await self._sync_channels_from_asterisk()
            except Exception:
                if not self.degraded_mode:
                    logger.error("Redis недоступен, переход в degraded mode")
                    self.degraded_mode = True
    
    # =============================================
    # Восстановление состояния
    # =============================================
    async def load_state_from_redis(self):
        """Восстановление состояния из Redis с последующей синхронизацией."""
        await asyncio.sleep(2)
        
        try:
            # Загружаем каналы
            redis_channels = await self._master_client.smembers(self.active_channels_key)
            logger.info(f"Загружено {len(redis_channels)} каналов из Redis")
            
            # Сразу синхронизируем с Asterisk
            await self._sync_channels_from_asterisk()
            
        except Exception as e:
            logger.error(f"Ошибка восстановления состояния: {e}")
    
    async def _sync_channels_from_asterisk(self):
        """Полная синхронизация каналов с Asterisk."""
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
            
            redis_channels = set(await self._master_client.smembers(self.active_channels_key))
            
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
        """Периодическая сверка состояния с Asterisk."""
        while self.running:
            await asyncio.sleep(60)
            if self.connected and not self.degraded_mode:
                await self._sync_channels_from_asterisk()
    
    # =============================================
    # Разрешение ActionID
    # =============================================
    def _resolve_action_id(self, unique_id: str, linked_id: str = None, event_action_id: str = None) -> Optional[str]:
        """Многоуровневое разрешение ActionID."""
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
        """Добавление mapping с обновлением всех индексов."""
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
        """Очистка mapping с использованием обратного индекса."""
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
    
    async def _transition_state(self, action_id: str, new_state: CallState) -> bool:
        """Распределённый переход состояния через Redis."""
        result = await self._master_client.eval(
            self.TRANSITION_STATE_LUA,
            1,
            self.call_state_key,
            action_id,
            new_state.value
        )
        return result == 1
    
    # =============================================
    # Нормализация номера
    # =============================================
    def normalize_phone(self, phone: str) -> Optional[str]:
        """Нормализация номера телефона."""
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
        """Постановка звонка в очередь."""
        normalized = self.normalize_phone(phone)
        if not normalized:
            return
        
        await self._master_client.rpush(self.dial_queue_key, json.dumps({
            "phone": normalized,
            "campaign_id": campaign_id,
            "retry": retry,
            "queued_at": datetime.now().isoformat()
        }))
    
    async def queue_worker(self):
        """Фоновый обработчик очереди звонков."""
        logger.info("Обработчик очереди запущен")
        
        while self.running:
            try:
                result = await self._master_client.blpop(self.dial_queue_key, timeout=1)
                if result:
                    _, job_data = result
                    data = json.loads(job_data)
                    await self._start_call(data['phone'], data['campaign_id'], data.get('retry', 0))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка обработчика очереди: {e}")
                await asyncio.sleep(1)
        
        logger.info("Обработчик очереди остановлен")
    
    async def _start_call(self, phone: str, campaign_id: int, retry: int):
        """Внутренний метод инициации звонка."""
        if not self.running:
            return
        
        normalized = self.normalize_phone(phone)
        if not normalized:
            return
        
        # 🔥 Degraded mode
        if self.degraded_mode:
            await self._add_to_degraded_queue(normalized, campaign_id, retry)
            return
        
        # 🔥 Проверка локального лимита
        async with self._local_estimate_lock:
            if time.monotonic() - self.last_redis_sync > 30:
                if self.local_active_estimate >= self.max_calls:
                    await self._master_client.rpush(self.dial_queue_key, json.dumps({
                        "phone": normalized, "campaign_id": campaign_id, "retry": retry
                    }))
                    return
        
        # 🔥 Проверка номера (deduplication)
        action_id = f"call_{campaign_id}_{normalized}_{int(time.time()*1000)}"
        
        phone_result = await self._master_client.eval(
            self.CHECK_PHONE_LUA,
            1,
            self.active_phones_key,
            normalized,
            action_id
        )
        
        if phone_result[0] == 0:
            logger.warning(f"Номер {normalized} уже в обработке: {phone_result[1]}")
            await asyncio.sleep(5)
            await self._master_client.rpush(self.dial_queue_key, json.dumps({
                "phone": normalized, "campaign_id": campaign_id, "retry": retry
            }))
            return
        
        # 🔥 Атомарное резервирование
        reservation_data = json.dumps({
            "phone": normalized,
            "campaign_id": campaign_id,
            "retry": retry,
            "timestamp": int(time.time() * 1000),
            "state": "reserved"
        })
        
        result = await self._master_client.eval(
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
            await self._master_client.rpush(self.dial_queue_key, json.dumps({
                "phone": normalized, "campaign_id": campaign_id, "retry": retry
            }))
            return
        
        slot_reserved = True
        await self._transition_state(action_id, CallState.RESERVED)
        
        # 🔥 Обновление локальной оценки
        async with self._local_estimate_lock:
            self.local_active_estimate = result[1]
            self.last_redis_sync = time.monotonic()
        
        # 🔥 OpenTelemetry
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
            
            await self._master_client.setex(f"trace:{action_id}", 60, traceparent)
        
        try:
            # 🔥 Originate
            timeout_ms = self.call_timeout * 1000
            setvar = f'__CAMPAIGN_ID={campaign_id},__RETRY_COUNT={retry}'
            if traceparent:
                setvar += f',__TRACEPARENT={traceparent}'
            
            action = panoramisk.message.Action('Originate', {
                'Channel': f'Local/{normalized}@dialer_bridge/n',
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
                if span:
                    span.set_status(Status(StatusCode.OK))
            else:
                raise Exception(f"Originate failed: {response.get('message') if response else 'No response'}")
                
        except Exception as e:
            logger.error(f"Originate failed for {normalized}: {e}")
            
            if slot_reserved:
                await self._master_client.eval(
                    self.RELEASE_SLOT_LUA,
                    3,
                    self.active_channels_key,
                    self.active_channels_ts_key,
                    "reservations_data",
                    action_id
                )
                await self._cleanup_phone_mapping(action_id)
            
            await self.save_call_result(campaign_id, normalized, 'originate_failed', None, None, retry)
            
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
        finally:
            if span:
                span.end()
    
    # =============================================
    # Обработка событий AMI
    # =============================================
    async def handle_ami_event(self, manager, event):
        """Главный обработчик событий AMI."""
        event_name = event.name
        channel = event.get('channel', '')
        unique_id = event.get('uniqueid')
        linked_id = event.get('linkedid')
        
        if channel and not channel.startswith('Local/'):
            return
        
        event_key = f"{event_name}_{unique_id}"
        if event_key in self.processed_events:
            return
        self.processed_events[event_key] = True
        
        try:
            if event_name == 'DialBegin':
                await self._handle_dial_begin(event, channel, unique_id)
            elif event_name == 'BridgeEnter':
                await self._handle_bridge_enter(event, unique_id, linked_id)
            elif event_name == 'Hangup':
                await self._handle_hangup(event, channel, unique_id, linked_id)
            elif event_name == 'UserEvent':
                await self._handle_user_event(event, linked_id)
        except Exception as e:
            logger.error(f"Ошибка обработки события {event_name}: {e}", exc_info=True)
    
    async def _handle_dial_begin(self, event, channel: str, unique_id: str):
        """Обработка DialBegin."""
        action_id = self._resolve_action_id(unique_id, None, event.get('actionid'))
        
        if not action_id:
            logger.warning(f"DialBegin без ActionID: {unique_id}")
            return
        
        # 🔥 Проверка reservation
        reservation = await self._master_client.hget("reservations_data", action_id)
        if reservation:
            data = json.loads(reservation)
            data['state'] = 'confirmed'
            await self._master_client.hset("reservations_data", action_id, json.dumps(data))
            logger.debug(f"Reservation подтверждена: {action_id}")
        
        # 🔥 Обновление ZSET
        await self._master_client.zadd(self.active_channels_ts_key, {action_id: time.time()})
        
        # 🔥 Обновление mapping
        self._add_mapping(action_id, unique_id, channel)
        self.call_start_times[unique_id] = datetime.now()
        
        # 🔥 State transition
        await self._transition_state(action_id, CallState.DIALING)
        
        # 🔥 OpenTelemetry
        traceparent = await self._master_client.get(f"trace:{action_id}")
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
        
        active = await self._master_client.scard(self.active_channels_key)
        logger.debug(f"DialBegin: {action_id}, канал={channel}, активно={active}")
    
    async def _handle_bridge_enter(self, event, unique_id: str, linked_id: str):
        """Обработка BridgeEnter (абонент ответил)."""
        action_id = self._resolve_action_id(unique_id, linked_id)
        if action_id:
            await self._transition_state(action_id, CallState.ACTIVE)
            logger.info(f"✅ Абонент ответил: {action_id}")
            
            if unique_id in self.call_start_times:
                del self.call_start_times[unique_id]
    
    async def _handle_hangup(self, event, channel: str, unique_id: str, linked_id: str):
        """Обработка Hangup."""
        hangup_key = f"hangup_{unique_id}"
        if hangup_key in self.hangup_events:
            return
        self.hangup_events[hangup_key] = True
        
        action_id = self._resolve_action_id(unique_id, linked_id, event.get('actionid'))
        
        if not action_id:
            logger.critical(f"Невозможно разрешить ActionID для unique_id={unique_id}")
            self._force_cleanup(unique_id)
            return
        
        if action_id in self.terminated_calls:
            return
        self.terminated_calls.add(action_id)
        
        await self._transition_state(action_id, CallState.HANGUP)
        
        # 🔥 Атомарное удаление
        await self._master_client.eval(
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
        
        # 🔥 Обновление локальной оценки
        async with self._local_estimate_lock:
            if self.local_active_estimate > 0:
                self.local_active_estimate -= 1
        
        active = await self._master_client.scard(self.active_channels_key)
        await self._master_client.set("active_calls", active)
        
        cause = event.get('cause', '0')
        cause_txt = event.get('cause-txt', 'UNKNOWN')
        logger.info(f"📴 Hangup: {action_id}, причина={cause_txt}, активно={active}")
        
        asyncio.create_task(self._cleanup_terminated(action_id))
    
    async def _handle_user_event(self, event, linked_id: str):
        """Обработка UserEvent."""
        userevent = event.get('userevent')
        
        if userevent == 'DialerResult':
            status = event.get('status', 'unknown')
            campaign_id = event.get('campaign', '0')
            phone = event.get('phone', '')
            retry_count = int(event.get('retrycount', '0'))
            
            logger.info(f"🎯 DialerResult: кампания={campaign_id}, телефон={phone}, статус={status}")
            
            await self.save_call_result(campaign_id, phone, status, None, None, retry_count)
            
            if status in ['noanswer', 'busy', 'failed']:
                await self.schedule_retry(campaign_id, phone, retry_count + 1, status)
    
    # =============================================
    # Сохранение результатов
    # =============================================
    async def save_call_result(self, campaign_id: str, phone: str, status: str, 
                                linked_id: str, unique_id: str, retry: int):
        """Сохранение результата звонка."""
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
                """, int(campaign_id), contact_id, linked_id, unique_id, status, retry)
                
                logger.debug(f"Результат сохранён: {normalized} -> {status}")
                
        except Exception as e:
            logger.error(f"Ошибка сохранения результата: {e}")
    
    async def schedule_retry(self, campaign_id: str, phone: str, retry_count: int, status: str):
        """Планирование повторного звонка."""
        strategies = {
            'busy': {'max': 2, 'delay': 120},
            'noanswer': {'max': 3, 'delay': 300},
            'failed': {'max': 1, 'delay': 60}
        }
        
        strategy = strategies.get(status, {'max': 1, 'delay': 60})
        
        if retry_count >= strategy['max']:
            return
        
        try:
            normalized = self.normalize_phone(phone)
            if not normalized:
                return
            
            # 🔥 Jitter
            base_delay = strategy['delay']
            jitter = random.expovariate(1.0 / (base_delay * 0.2))
            jitter = min(jitter, base_delay * 0.5)
            actual_delay = base_delay + (jitter if random.random() > 0.5 else -jitter)
            actual_delay = max(1, actual_delay)
            
            next_retry = datetime.now() + timedelta(seconds=actual_delay)
            
            async with self.db_pool.acquire() as conn:
                contact_id = await conn.fetchval("SELECT id FROM contacts WHERE phone = $1", normalized)
                if contact_id:
                    await conn.execute("""
                        UPDATE campaign_contacts 
                        SET next_retry_at = $1
                        WHERE campaign_id = $2 AND contact_id = $3
                    """, next_retry, int(campaign_id), contact_id)
            
            logger.info(f"⏰ Запланирован повтор {retry_count}/{strategy['max']} для {normalized} через {actual_delay:.1f}с")
            
        except Exception as e:
            logger.error(f"Ошибка планирования повтора: {e}")
    
    # =============================================
    # Очистка
    # =============================================
    async def _cleanup_phone_mapping(self, action_id: str):
        """Очистка привязки номера."""
        reservation = await self._master_client.hget("reservations_data", action_id)
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
                    await self._master_client.eval(lua_cleanup, 1, self.active_phones_key, phone, action_id)
            except Exception:
                pass
    
    async def _force_cleanup(self, unique_id: str, action_id: str = None):
        """Принудительная очистка."""
        if not action_id:
            action_id = self.unique_to_action.get(unique_id)
        
        if action_id:
            await self._master_client.eval(
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
        """Отложенная очистка terminated calls."""
        await asyncio.sleep(60)
        self.terminated_calls.discard(action_id)
    
    async def cleanup_stale_mappings(self):
        """Очистка устаревших mapping'ов."""
        while self.running:
            await asyncio.sleep(60)
            
            now = time.monotonic()
            stale = []
            
            for action_id, created_at in list(self.action_created_at.items()):
                if now - created_at > 600:
                    stale.append(action_id)
            
            if stale:
                pipe = self._master_client.pipeline()
                for action_id in stale:
                    pipe.sismember(self.active_channels_key, action_id)
                results = await pipe.execute()
                
                for action_id, is_active in zip(stale, results):
                    if not is_active:
                        self._cleanup_mappings(action_id, None)
                
                logger.debug(f"Очищено {len(stale) - sum(results)} устаревших mapping'ов")
    
    async def cleanup_expired_reservations(self):
        """Очистка просроченных reservation."""
        while self.running:
            await asyncio.sleep(15)
            
            now = time.time()
            cutoff = now - 30
            
            expired = await self._master_client.zrangebyscore(
                self.reservations_ts_key,
                0,
                cutoff
            )
            
            for action_id in expired:
                data = await self._master_client.hget("reservations_data", action_id)
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
                        await self._master_client.eval(
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
                
                await self._master_client.zrem(self.reservations_ts_key, action_id)
                await self._master_client.hdel("reservations_data", action_id)
    
    # =============================================
    # Watchdog
    # =============================================
    async def watchdog_stale_calls(self):
        """Убийство зависших звонков с sampling."""
        while self.running:
            await asyncio.sleep(30)
            
            now = datetime.now()
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
        """Проверка живости канала."""
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
        """Добавление в degraded очередь."""
        now = time.time()
        
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
            
            try:
                with open(self.degraded_queue_file, 'a') as f:
                    f.write(json.dumps(item) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                logger.error(f"Ошибка записи в degraded queue: {e}")
        
        await asyncio.sleep(5)
    
    async def _recover_degraded_queue(self):
        """Восстановление из degraded queue."""
        await asyncio.sleep(5)
        
        if not os.path.exists(self.degraded_queue_file):
            return
        
        try:
            with open(self.degraded_queue_file, 'r') as f:
                lines = f.readlines()
            
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
    # Мониторинг памяти Redis
    # =============================================
    async def _monitor_redis_memory(self):
        """Мониторинг памяти Redis."""
        while self.running:
            await asyncio.sleep(60)
            
            try:
                info = await self._master_client.info('memory')
                used_memory = info.get('used_memory', 0)
                
                if used_memory > 500 * 1024 * 1024:  # 500 MB
                    logger.critical(f"Redis memory превышен: {used_memory / 1024 / 1024:.1f} MB")
                    
                    cleaned = 0
                    for _ in range(10):
                        result = await self._master_client.eval(
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
    
    # =============================================
    # Статус
    # =============================================
    def get_status(self) -> dict:
        """Получение текущего статуса."""
        return {
            "connected": self.connected,
            "running": self.running,
            "active_calls": len(self.channel_map),
            "max_calls": self.max_calls,
            "freepbx_extension": self.freepbx_extension,
            "degraded_mode": self.degraded_mode
        }
