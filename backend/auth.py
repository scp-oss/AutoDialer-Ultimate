#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер AMI (Asterisk Manager Interface)
AutoDialer Ultimate v3.0.0

Управляет подключением к Asterisk, инициирует звонки,
обрабатывает события и сохраняет результаты.
"""

import asyncio
import panoramisk
import time
import json
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, Any
from cachetools import TTLCache

from logger import logger
from rate_limiter import TokenBucket, GlobalRateLimiter


class DialerManager:
    """
    Менеджер дозвона через Asterisk AMI.
    
    Отвечает за:
    - Подключение к AMI
    - Инициирование звонков через очередь
    - Обработку событий (DialBegin, Hangup, UserEvent)
    - Сохранение результатов в БД
    - Планирование повторных попыток
    - Контроль активных каналов
    """
    
    def __init__(self, db_pool, redis_client):
        """
        Инициализация менеджера.
        
        Args:
            db_pool: Пул соединений с PostgreSQL
            redis_client: Клиент Redis
        """
        self.db_pool = db_pool
        self.redis = redis_client
        
        # =============================================
        # Загрузка конфигурации из переменных окружения
        # =============================================
        ami_host = os.getenv('AMI_HOST', '127.0.0.1')
        ami_port = int(os.getenv('AMI_PORT', 5038))
        ami_user = os.getenv('AMI_USER', 'autodialer')
        ami_password = os.getenv('AMI_PASSWORD')
        
        if not ami_password:
            raise ValueError("AMI_PASSWORD не задан в переменных окружения")
        
        # Номер extension на FreePBX (настраиваемый!)
        self.freepbx_extension = os.getenv('FREEPBX_EXTENSION', '291')
        
        # =============================================
        # Инициализация подключения к AMI
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
        self.active_channels_key = "active_channels"
        self.channels_hash_key = "channels"
        self.dial_queue_key = "dial_queue"
        
        # =============================================
        # Состояние
        # =============================================
        self.channel_map: Dict[str, str] = {}      # unique_id -> channel
        self.call_start_times: Dict[str, datetime] = {}
        self.contact_map: Dict[str, int] = {}      # phone -> contact_id
        
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
        
        # =============================================
        # Ограничители скорости
        # =============================================
        self.cps_limiter = TokenBucket(rate=int(os.getenv('DEFAULT_CPS', 5)))
        self.global_limiter = GlobalRateLimiter(redis_client, "global_cps", rate=100)
        
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
        
        logger.info(f"DialerManager инициализирован (extension: {self.freepbx_extension})")
    
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
                
                # Подписка на все события
                await self.manager.send_action(panoramisk.message.Action('Events', {'EventMask': 'on'}))
                
            except Exception as e:
                self.reconnect_attempts += 1
                wait_time = min(2 ** self.reconnect_attempts, 60)
                logger.warning(f"Ошибка подключения к AMI (попытка {self.reconnect_attempts}/{self.max_reconnect_attempts}): {e}")
                logger.info(f"Повтор через {wait_time} сек...")
                await asyncio.sleep(wait_time)
        
        if not self.connected:
            logger.error("Не удалось подключиться к AMI после максимального количества попыток")
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
    
    # =============================================
    # Восстановление состояния
    # =============================================
    async def load_state_from_redis(self):
        """Восстановление состояния из Redis после перезапуска."""
        await asyncio.sleep(2)
        
        try:
            channels = await self.redis.hgetall(self.channels_hash_key)
            self.channel_map = dict(channels)
            
            for unique_id in self.channel_map:
                self.call_start_times[unique_id] = datetime.now()
            
            logger.info(f"Восстановлено {len(self.channel_map)} каналов из Redis")
            
            # Восстановление кэша контактов
            contact_keys = await self.redis.keys("contact:*")
            for key in contact_keys:
                phone = key.replace("contact:", "")
                contact_id = await self.redis.get(key)
                if contact_id:
                    self.contact_map[phone] = int(contact_id)
            
            logger.info(f"Восстановлено {len(self.contact_map)} контактов из кэша")
            
        except Exception as e:
            logger.error(f"Ошибка восстановления состояния из Redis: {e}")
    
    async def reconcile_channels(self):
        """Периодическая сверка состояния каналов с Asterisk."""
        while True:
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
    
    async def _sync_channels_from_asterisk(self):
        """Полная синхронизация каналов с Asterisk через CoreShowChannels."""
        try:
            action = panoramisk.message.Action('CoreShowChannels')
            response = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=10.0
            )
            
            await self.redis.delete(self.active_channels_key)
            await self.redis.delete(self.channels_hash_key)
            self.channel_map.clear()
            self.call_start_times.clear()
            
            for event in response.events:
                if event.get('event') == 'CoreShowChannel':
                    channel = event.get('channel')
                    unique_id = event.get('uniqueid')
                    
                    if channel and channel.startswith('Local/'):
                        key = f"{channel}:{unique_id}"
                        await self.redis.sadd(self.active_channels_key, key)
                        await self.redis.hset(self.channels_hash_key, unique_id, channel)
                        self.channel_map[unique_id] = channel
                        self.call_start_times[unique_id] = datetime.now()
            
            synced_count = await self.redis.scard(self.active_channels_key)
            logger.info(f"Синхронизировано {synced_count} каналов с Asterisk")
            
            await self.redis.set("active_calls", synced_count)
            await self.redis.expire("active_calls", 120)
            
        except Exception as e:
            logger.error(f"Ошибка синхронизации каналов: {e}")
    
    # =============================================
    # Нормализация номера телефона
    # =============================================
    def normalize_phone(self, phone: str) -> Optional[str]:
        """
        Нормализация номера телефона в международный формат.
        
        Args:
            phone: Исходный номер телефона
            
        Returns:
            Нормализованный номер или None, если номер невалидный
        """
        if not phone:
            return None
        
        # Удаление всех нецифровых символов
        phone = re.sub(r'[^\d]', '', phone)
        
        # Российские номера
        if len(phone) == 11 and phone.startswith('7'):
            return phone
        elif len(phone) == 11 and phone.startswith('8'):
            return '7' + phone[1:]
        elif len(phone) == 10 and phone.startswith('9'):
            return '7' + phone
        
        # Международные номера (10+ цифр)
        if len(phone) >= 10:
            return phone
        
        logger.warning(f"Невалидный формат номера: {phone}")
        return None
    
    async def get_or_create_contact(self, phone: str) -> Optional[int]:
        """
        Получение или создание контакта по номеру телефона.
        
        Args:
            phone: Нормализованный номер телефона
            
        Returns:
            ID контакта или None
        """
        normalized = self.normalize_phone(phone)
        if not normalized:
            return None
        
        # Проверка кэша в памяти
        if normalized in self.contact_map:
            return self.contact_map[normalized]
        
        # Проверка кэша Redis
        cached = await self.redis.get(f"contact:{normalized}")
        if cached:
            contact_id = int(cached)
            self.contact_map[normalized] = contact_id
            return contact_id
        
        # Запрос к базе данных
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    """INSERT INTO contacts (phone) VALUES ($1) 
                       ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone 
                       RETURNING id""",
                    normalized
                )
                contact_id = result['id']
                
                # Кэширование в Redis (1 час)
                await self.redis.setex(f"contact:{normalized}", 3600, contact_id)
                self.contact_map[normalized] = contact_id
                
                return contact_id
        except Exception as e:
            logger.error(f"Ошибка получения/создания контакта {normalized}: {e}")
            return None
    
    # =============================================
    # Инициирование звонков
    # =============================================
    async def start_call(self, phone: str, campaign_id: int, retry: int = 0):
        """
        Постановка звонка в очередь.
        
        Args:
            phone: Номер телефона
            campaign_id: ID кампании
            retry: Счётчик повторных попыток
        """
        normalized = self.normalize_phone(phone)
        if not normalized:
            logger.warning(f"Пропуск невалидного номера: {phone}")
            return
        
        # Проверка чёрного списка
        blacklisted = await self.redis.sismember("blacklist:phones", normalized)
        if blacklisted:
            logger.info(f"Пропуск номера из чёрного списка: {normalized}")
            return
        
        # Добавление в очередь
        await self.redis.rpush(self.dial_queue_key, json.dumps({
            "phone": normalized,
            "campaign_id": campaign_id,
            "retry": retry,
            "queued_at": datetime.now().isoformat()
        }))
        
        queue_size = await self.redis.llen(self.dial_queue_key)
        logger.debug(f"Звонок в очереди: {normalized} (кампания {campaign_id}), размер очереди: {queue_size}")
    
    async def queue_worker(self):
        """Фоновый обработчик очереди звонков."""
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
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка обработчика очереди: {e}")
                await asyncio.sleep(1)
        
        logger.info("Обработчик очереди остановлен")
    
    async def _start_call(self, phone: str, campaign_id: int, retry: int):
        """
        Внутренний метод инициации звонка.
        
        Args:
            phone: Нормализованный номер
            campaign_id: ID кампании
            retry: Счётчик повторных попыток
        """
        # Проверка состояния системы
        if not self.running:
            logger.debug("Дозвон остановлен, пропуск звонка")
            return
        
        enabled = await self.redis.get("system_enabled") or "true"
        if enabled != "true":
            logger.debug("Система отключена, пропуск звонка")
            return
        
        # Проверка глобального CPS
        if not await self.global_limiter.acquire():
            await asyncio.sleep(0.1)
            await self.redis.rpush(self.dial_queue_key, json.dumps({
                "phone": phone,
                "campaign_id": campaign_id,
                "retry": retry
            }))
            return
        
        normalized = self.normalize_phone(phone)
        if not normalized:
            return
        
        # Повторная проверка чёрного списка
        blacklisted = await self.redis.sismember("blacklist:phones", normalized)
        if blacklisted:
            logger.info(f"Пропуск номера из чёрного списка: {normalized}")
            return
        
        # Проверка лимита каналов
        active = await self.redis.scard(self.active_channels_key)
        if active >= self.max_calls:
            await self.redis.rpush(self.dial_queue_key, json.dumps({
                "phone": normalized,
                "campaign_id": campaign_id,
                "retry": retry
            }))
            logger.debug(f"Достигнут лимит каналов ({active}/{self.max_calls}), возврат в очередь")
            return
        
        # Проверка, не звоним ли уже на этот номер
        for channel in self.channel_map.values():
            if normalized in channel:
                logger.debug(f"Уже звоним на {normalized}, пропуск")
                return
        
        # Подготовка и отправка Originate
        timeout_ms = self.call_timeout * 1000
        
        action = panoramisk.message.Action('Originate', {
            'Channel': f'Local/{normalized}@dialer_bridge/n',
            'Async': 'true',
            'Timeout': str(timeout_ms),
            'CallerID': f'"Camp_{campaign_id}" <{self.caller_id}>',
            'Setvar': f'__CAMPAIGN_ID={campaign_id},__RETRY_COUNT={retry},__ORIGINAL_PHONE={normalized}',
            'ActionID': f'call_{campaign_id}_{normalized}_{int(time.time()*1000)}'
        })
        
        try:
            response = await self.manager.send_action(action)
            
            if response and response.get('response') == 'Success':
                unique_id = response.get('uniqueid')
                self.call_start_times[unique_id] = datetime.now()
                logger.info(f"📞 Originate OK: {unique_id} -> {normalized} (кампания {campaign_id}, попытка {retry})")
                
                # Обновление метрик
                try:
                    from prometheus_client import Counter
                    calls_counter = Counter('autodialer_calls_initiated', 'Calls initiated', ['campaign_id'])
                    calls_counter.labels(campaign_id=str(campaign_id)).inc()
                except ImportError:
                    pass
                
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                logger.error(f"Originate не удался для {normalized}: {error_msg}")
                
                await self.save_call_result(campaign_id, normalized, 'failed', None, None, retry)
                
                if retry < 1:
                    await self.schedule_retry(campaign_id, normalized, retry + 1, 'failed')
                    
        except Exception as e:
            logger.error(f"Исключение при originate для {normalized}: {e}")
            await self.save_call_result(campaign_id, normalized, 'failed', None, None, retry)
    
    # =============================================
    # Обработка событий AMI
    # =============================================
    async def handle_ami_event(self, manager, event):
        """
        Обработчик событий AMI.
        
        Args:
            manager: Экземпляр менеджера
            event: Событие AMI
        """
        event_name = event.name
        channel = event.get('channel', '')
        unique_id = event.get('uniqueid')
        linked_id = event.get('linkedid')
        
        # Пропуск не наших каналов
        if channel and not channel.startswith('Local/'):
            return
        
        # Дедупликация событий
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
                
            elif event_name == 'VarSet':
                await self._handle_var_set(event, unique_id)
                
        except Exception as e:
            logger.error(f"Ошибка обработки события {event_name}: {e}", exc_info=True)
    
    async def _handle_dial_begin(self, event, channel: str, unique_id: str):
        """Обработка события DialBegin."""
        if not channel.startswith('Local/'):
            return
        
        key = f"{channel}:{unique_id}"
        
        await self.redis.sadd(self.active_channels_key, key)
        await self.redis.hset(self.channels_hash_key, unique_id, channel)
        await self.redis.expire(self.active_channels_key, 120)
        
        self.channel_map[unique_id] = channel
        
        active = await self.redis.scard(self.active_channels_key)
        await self.redis.set("active_calls", active)
        await self.redis.expire("active_calls", 120)
        
        logger.debug(f"DialBegin: {unique_id} на {channel}, активно: {active}")
    
    async def _handle_dial_end(self, event, unique_id: str):
        """Обработка события DialEnd."""
        dial_status = event.get('dialstatus', 'UNKNOWN')
        logger.debug(f"DialEnd: {unique_id}, статус: {dial_status}")
    
    async def _handle_bridge_enter(self, event, unique_id: str, linked_id: str):
        """Обработка события BridgeEnter (абонент ответил)."""
        logger.info(f"✅ Абонент ответил: {unique_id} (linked: {linked_id})")
        
        if unique_id in self.call_start_times:
            del self.call_start_times[unique_id]
    
    async def _handle_hangup(self, event, channel: str, unique_id: str, linked_id: str):
        """Обработка события Hangup."""
        # Дедупликация через Redis
        hangup_key = f"hangup_{unique_id}"
        if hangup_key in self.hangup_events:
            return
        self.hangup_events[hangup_key] = True
        
        redis_hangup_key = f"hangup:{unique_id}"
        if not await self.redis.set(redis_hangup_key, "1", ex=10, nx=True):
            return
        
        cause = event.get('cause', '0')
        cause_txt = event.get('cause-txt', 'UNKNOWN')
        
        if unique_id in self.channel_map:
            channel = self.channel_map[unique_id]
            key = f"{channel}:{unique_id}"
            
            await self.redis.srem(self.active_channels_key, key)
            await self.redis.hdel(self.channels_hash_key, unique_id)
            del self.channel_map[unique_id]
        
        if unique_id in self.call_start_times:
            del self.call_start_times[unique_id]
        
        active = await self.redis.scard(self.active_channels_key)
        await self.redis.set("active_calls", active)
        
        logger.info(f"📴 Hangup: {unique_id}, причина: {cause_txt} ({cause}), активно: {active}")
    
    async def _handle_user_event(self, event, linked_id: str):
        """Обработка пользовательских событий из диалплана."""
        userevent = event.get('userevent')
        
        if userevent == 'DialerResult':
            status = event.get('status', 'unknown')
            campaign_id = event.get('campaign', '0')
            phone = event.get('phone', '')
            retry_count = int(event.get('retrycount', '0'))
            
            logger.info(f"🎯 DialerResult: кампания={campaign_id}, телефон={phone}, статус={status}, попытка={retry_count}")
            
            await self.save_call_result(campaign_id, phone, status, linked_id, None, retry_count)
            
            if status in ['noanswer', 'busy', 'failed']:
                await self.schedule_retry(campaign_id, phone, retry_count + 1, status)
            
            # Обновление метрик
            try:
                from prometheus_client import Counter
                result_counter = Counter('autodialer_call_results', 'Call results', ['status', 'campaign_id'])
                result_counter.labels(status=status, campaign_id=campaign_id).inc()
            except ImportError:
                pass
            
        elif userevent == 'DialerHangup':
            channel = event.get('channel', '')
            status = event.get('status', '')
            logger.debug(f"DialerHangup: {channel}, статус: {status}")
    
    async def _handle_var_set(self, event, unique_id: str):
        """Обработка события VarSet."""
        variable = event.get('variable', '')
        value = event.get('value', '')
        
        if variable == 'CAMPAIGN_ID' and unique_id:
            logger.debug(f"VarSet: {unique_id} campaign={value}")
    
    # =============================================
    # Сохранение результатов
    # =============================================
    async def save_call_result(
        self,
        campaign_id: str,
        phone: str,
        status: str,
        linked_id: Optional[str],
        unique_id: Optional[str],
        retry: int
    ):
        """
        Сохранение результата звонка в базу данных.
        
        Args:
            campaign_id: ID кампании
            phone: Номер телефона
            status: Статус звонка
            linked_id: LinkedID из AMI
            unique_id: UniqueID из AMI
            retry: Счётчик попыток
        """
        try:
            contact_id = await self.get_or_create_contact(phone)
            if not contact_id:
                logger.error(f"Не удалось получить/создать контакт для {phone}")
                return
            
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO call_results 
                    (campaign_id, contact_id, linked_id, unique_id, status, retry_count)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, int(campaign_id), contact_id, linked_id, unique_id, status, retry)
                
                await conn.execute("""
                    UPDATE campaign_contacts 
                    SET retry_count = $1, last_call_at = NOW()
                    WHERE campaign_id = $2 AND contact_id = $3
                """, retry, int(campaign_id), contact_id)
                
                logger.debug(f"Результат сохранён: кампания={campaign_id}, телефон={phone}, статус={status}")
                
        except Exception as e:
            logger.error(f"Ошибка сохранения результата: {e}")
    
    async def schedule_retry(self, campaign_id: str, phone: str, retry_count: int, status: str):
        """
        Планирование повторного звонка.
        
        Args:
            campaign_id: ID кампании
            phone: Номер телефона
            retry_count: Текущий счётчик попыток
            status: Статус, вызвавший повтор
        """
        strategies = {
            'busy': {'max': 2, 'delay': 120},
            'noanswer': {'max': 3, 'delay': 300},
            'failed': {'max': 1, 'delay': 60},
            'timeout': {'max': 1, 'delay': 60}
        }
        
        strategy = strategies.get(status, {'max': 1, 'delay': 60})
        
        if retry_count >= strategy['max']:
            logger.info(f"Достигнут максимум попыток ({strategy['max']}) для {phone} (статус: {status})")
            return
        
        try:
            contact_id = await self.get_or_create_contact(phone)
            if not contact_id:
                return
            
            next_retry = datetime.now() + timedelta(seconds=strategy['delay'])
            
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE campaign_contacts 
                    SET next_retry_at = $1
                    WHERE campaign_id = $2 AND contact_id = $3
                """, next_retry, int(campaign_id), contact_id)
            
            logger.info(f"⏰ Запланирован повтор {retry_count}/{strategy['max']} для {phone} через {strategy['delay']}с")
            
        except Exception as e:
            logger.error(f"Ошибка планирования повтора: {e}")
    
    # =============================================
    # Watchdog и очистка
    # =============================================
    async def watchdog_stale_calls(self):
        """Убийство зависших звонков."""
        logger.info("Watchdog запущен")
        
        while self.running:
            await asyncio.sleep(15)
            
            now = datetime.now()
            stale_timeout = timedelta(seconds=90)
            
            for unique_id, start_time in list(self.call_start_times.items()):
                if now - start_time > stale_timeout:
                    channel = self.channel_map.get(unique_id)
                    if channel:
                        logger.warning(f"⚠️ Watchdog убивает зависший звонок: {unique_id} на {channel} (возраст: {(now - start_time).seconds}с)")
                        
                        try:
                            action = panoramisk.message.Action('Hangup', {'Channel': channel})
                            await self.manager.send_action(action)
                        except Exception as e:
                            logger.error(f"Ошибка watchdog hangup для {unique_id}: {e}")
                    
                    if unique_id in self.call_start_times:
                        del self.call_start_times[unique_id]
    
    async def stop_all_calls(self) -> int:
        """
        Экстренная остановка всех звонков.
        
        Returns:
            Количество убитых звонков
        """
        killed = 0
        
        for unique_id, channel in list(self.channel_map.items()):
            try:
                action = panoramisk.message.Action('Hangup', {'Channel': channel})
                await self.manager.send_action(action)
                killed += 1
                logger.info(f"Принудительно завершён звонок: {unique_id} на {channel}")
            except Exception as e:
                logger.error(f"Ошибка принудительного завершения {unique_id}: {e}")
        
        await self.redis.delete(self.active_channels_key)
        await self.redis.delete(self.channels_hash_key)
        await self.redis.set("active_calls", "0")
        
        self.channel_map.clear()
        self.call_start_times.clear()
        
        logger.warning(f"Экстренная остановка завершена, убито {killed} звонков")
        return killed
    
    # =============================================
    # Статус и мониторинг
    # =============================================
    def get_status(self) -> dict:
        """Получение текущего статуса дозвонщика."""
        return {
            "connected": self.connected,
            "running": self.running,
            "active_calls": len(self.channel_map),
            "max_calls": self.max_calls,
            "queue_size": 0,
            "cps_rate": self.cps_limiter.rate,
            "reconnect_attempts": self.reconnect_attempts,
            "freepbx_extension": self.freepbx_extension
        }
    
    async def get_queue_size(self) -> int:
        """Получение размера очереди."""
        return await self.redis.llen(self.dial_queue_key)
    
    async def get_active_channels(self) -> list:
        """Получение списка активных каналов."""
        channels = []
        for unique_id, channel in self.channel_map.items():
            start_time = self.call_start_times.get(unique_id)
            channels.append({
                "unique_id": unique_id,
                "channel": channel,
                "started_at": start_time.isoformat() if start_time else None,
                "duration": (datetime.now() - start_time).seconds if start_time else 0
            })
        return channels
