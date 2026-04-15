#!/usr/bin/env python3
"""
AMI Manager for Asterisk
"""

import asyncio
import panoramisk
import time
import json
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
from cachetools import TTLCache

from logger import logger
from rate_limiter import GlobalRateLimiter

class DialerManager:
    def __init__(self, db_pool, redis_client):
        self.db_pool = db_pool
        self.redis = redis_client
        
        ami_host = os.getenv('AMI_HOST', '127.0.0.1')
        ami_port = int(os.getenv('AMI_PORT', 5038))
        ami_user = os.getenv('AMI_USER', 'autodialer')
        ami_password = os.getenv('AMI_PASSWORD')
        
        self.manager = panoramisk.Manager(
            host=ami_host, port=ami_port,
            username=ami_user, secret=ami_password, ssl=False
        )
        
        self.max_calls = int(os.getenv('MAX_CALLS', 50))
        self.caller_id = os.getenv('CALLER_ID', 'AutoDialer')
        
        self.active_channels_key = "active_channels"
        self.channels_hash_key = "channels"
        
        self.channel_map: Dict[str, str] = {}
        self.call_start_times: Dict[str, datetime] = {}
        
        self.processed_events = TTLCache(maxsize=100000, ttl=300)
        
        self.running = True
        self.connected = False
        
        from rate_limiter import TokenBucket
        self.cps_limiter = TokenBucket(rate=int(os.getenv('DEFAULT_CPS', 5)))
        self.global_limiter = GlobalRateLimiter(redis_client, "global_cps", rate=100)
        
        self.manager.register_event('*', self.handle_ami_event)
        
        asyncio.create_task(self.watchdog_stale_calls())
        asyncio.create_task(self.queue_worker())
        asyncio.create_task(self.reconcile_channels())
        asyncio.create_task(self.load_state_from_redis())
    
    async def ensure_connected(self):
        retries = 0
        while not self.connected:
            try:
                await self.manager.connect()
                self.connected = True
                logger.info("AMI Connected successfully")
            except Exception as e:
                retries += 1
                logger.warning(f"AMI connection failed (attempt {retries}): {e}")
                await asyncio.sleep(5)
    
    async def load_state_from_redis(self):
        await asyncio.sleep(2)
        channels = await self.redis.hgetall(self.channels_hash_key)
        self.channel_map = dict(channels)
        for unique_id in self.channel_map:
            self.call_start_times[unique_id] = datetime.now()
        logger.info(f"Restored {len(self.channel_map)} channels from Redis")
    
    async def reconcile_channels(self):
        while True:
            await asyncio.sleep(300)
            if not self.running:
                continue
            
            redis_count = await self.redis.scard(self.active_channels_key)
            local_count = len(self.channel_map)
            
            if abs(redis_count - local_count) > max(5, redis_count * 0.1):
                logger.warning(f"Channel mismatch: Redis={redis_count}, Local={local_count}")
                await self._sync_channels_from_asterisk()
    
    async def _sync_channels_from_asterisk(self):
        try:
            action = panoramisk.message.Action('CoreShowChannels')
            response = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=10.0
            )
            
            await self.redis.delete(self.active_channels_key)
            await self.redis.delete(self.channels_hash_key)
            
            for event in response.events:
                if event.get('event') == 'CoreShowChannel':
                    channel = event.get('channel')
                    unique_id = event.get('uniqueid')
                    
                    if channel and channel.startswith('Local/'):
                        key = f"{channel}:{unique_id}"
                        await self.redis.sadd(self.active_channels_key, key)
                        await self.redis.hset(self.channels_hash_key, unique_id, channel)
            
            logger.info(f"Synced {await self.redis.scard(self.active_channels_key)} channels")
        except Exception as e:
            logger.error(f"Channel sync failed: {e}")
    
    def normalize_phone(self, phone: str) -> Optional[str]:
        phone = re.sub(r'[^\d]', '', phone)
        if len(phone) == 11 and phone.startswith('7'):
            return phone
        elif len(phone) == 11 and phone.startswith('8'):
            return '7' + phone[1:]
        elif len(phone) == 10 and phone.startswith('9'):
            return '7' + phone
        elif len(phone) >= 10:
            return phone
        return None
    
    async def start_call(self, phone: str, campaign_id: int, retry: int = 0):
        await self.redis.lpush("dial_queue", json.dumps({
            "phone": phone, "campaign_id": campaign_id, "retry": retry
        }))
    
    async def queue_worker(self):
        while self.running:
            try:
                _, job = await self.redis.brpop("dial_queue", timeout=1)
                if job:
                    data = json.loads(job)
                    await self._start_call(data['phone'], data['campaign_id'], data['retry'])
            except Exception as e:
                logger.error(f"Queue worker error: {e}")
    
    async def _start_call(self, phone: str, campaign_id: int, retry: int):
        if not self.running:
            return
        
        enabled = await self.redis.get("system_enabled") or "true"
        if enabled != "true":
            return
        
        if not await self.global_limiter.acquire():
            await self.redis.lpush("dial_queue", json.dumps({
                "phone": phone, "campaign_id": campaign_id, "retry": retry
            }))
            await asyncio.sleep(0.1)
            return
        
        normalized = self.normalize_phone(phone)
        if not normalized:
            logger.warning(f"Invalid phone: {phone}")
            return
        
        active = await self.redis.scard(self.active_channels_key)
        if active >= self.max_calls:
            await self.redis.lpush("dial_queue", json.dumps({
                "phone": phone, "campaign_id": campaign_id, "retry": retry
            }))
            return
        
        action = panoramisk.message.Action('Originate', {
            'Channel': f'Local/{normalized}@dialer_bridge/n',
            'Async': 'true',
            'Timeout': str(int(os.getenv('CALL_TIMEOUT', 30)) * 1000),
            'CallerID': f'"Camp_{campaign_id}" <{self.caller_id}>',
            'Setvar': f'__CAMPAIGN_ID={campaign_id},__RETRY_COUNT={retry}',
            'ActionID': f'call_{campaign_id}_{normalized}_{int(time.time())}'
        })
        
        response = await self.manager.send_action(action)
        if response and response.get('response') == 'Success':
            unique_id = response.get('uniqueid')
            self.call_start_times[unique_id] = datetime.now()
            logger.debug(f"Originate OK: {unique_id} -> {normalized}")
        else:
            logger.error(f"Originate failed: {normalized}")
    
    async def handle_ami_event(self, manager, event):
        channel = event.get('channel', '')
        unique_id = event.get('uniqueid')
        linked_id = event.get('linkedid')
        
        event_key = f"{event.name}_{unique_id}"
        if event_key in self.processed_events:
            return
        self.processed_events[event_key] = True
        
        if event.name == 'DialBegin' and channel.startswith('Local/'):
            key = f"{channel}:{unique_id}"
            await self.redis.sadd(self.active_channels_key, key)
            await self.redis.hset(self.channels_hash_key, unique_id, channel)
            self.channel_map[unique_id] = channel
            
        elif event.name == 'BridgeEnter':
            logger.debug(f"Call answered: {unique_id}")
            
        elif event.name == 'Hangup':
            hangup_key = f"hangup_{unique_id}"
            if not await self.redis.set(hangup_key, "1", ex=10, nx=True):
                return
            
            if unique_id in self.channel_map:
                channel = self.channel_map[unique_id]
                key = f"{channel}:{unique_id}"
                await self.redis.srem(self.active_channels_key, key)
                await self.redis.hdel(self.channels_hash_key, unique_id)
                del self.channel_map[unique_id]
            
            if unique_id in self.call_start_times:
                del self.call_start_times[unique_id]
                
        elif event.name == 'UserEvent' and event.get('userevent') == 'DialerResult':
            status = event.get('status')
            campaign_id = event.get('campaign')
            phone = event.get('phone')
            retry_count = int(event.get('retrycount', '0'))
            
            await self.save_call_result(campaign_id, phone, status, linked_id, retry_count)
            
            # Retry logic
            if status in ['noanswer', 'busy']:
                await self.schedule_retry(campaign_id, phone, retry_count + 1, status)
    
    async def save_call_result(self, campaign_id: str, phone: str, status: str, linked_id: str, retry: int):
        try:
            async with self.db_pool.acquire() as conn:
                contact_id = await conn.fetchval("""
                    INSERT INTO contacts (phone) VALUES ($1) 
                    ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone 
                    RETURNING id
                """, phone)
                
                await conn.execute("""
                    INSERT INTO call_results (campaign_id, contact_id, linked_id, status, retry_count)
                    VALUES ($1, $2, $3, $4, $5)
                """, int(campaign_id), contact_id, linked_id, status, retry)
                
                await conn.execute("""
                    UPDATE campaign_contacts 
                    SET retry_count = $1, last_call_at = NOW()
                    WHERE campaign_id = $2 AND contact_id = $3
                """, retry, int(campaign_id), contact_id)
                
                logger.info(f"Call result: Campaign {campaign_id}, Phone {phone}, Status {status}")
        except Exception as e:
            logger.error(f"Failed to save result: {e}")
    
    async def schedule_retry(self, campaign_id: str, phone: str, retry_count: int, status: str):
        strategies = {
            'busy': {'max': 2, 'delay': 120},
            'noanswer': {'max': 3, 'delay': 300},
            'failed': {'max': 1, 'delay': 60}
        }
        
        strategy = strategies.get(status, {'max': 1, 'delay': 60})
        if retry_count >= strategy['max']:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                contact_id = await conn.fetchval("SELECT id FROM contacts WHERE phone = $1", phone)
                if contact_id:
                    next_retry = datetime.now() + timedelta(seconds=strategy['delay'])
                    await conn.execute("""
                        UPDATE campaign_contacts 
                        SET next_retry_at = $1
                        WHERE campaign_id = $2 AND contact_id = $3
                    """, next_retry, int(campaign_id), contact_id)
                    logger.info(f"Scheduled retry {retry_count} for {phone} in {strategy['delay']}s")
        except Exception as e:
            logger.error(f"Failed to schedule retry: {e}")
    
    async def watchdog_stale_calls(self):
        while True:
            await asyncio.sleep(30)
            now = datetime.now()
            for unique_id, start_time in list(self.call_start_times.items()):
                if now - start_time > timedelta(seconds=90):
                    channel = self.channel_map.get(unique_id)
                    if channel:
                        logger.warning(f"Watchdog killing stale call: {unique_id}")
                        await self.manager.send_action(
                            panoramisk.message.Action('Hangup', {'Channel': channel})
                        )
                    del self.call_start_times[unique_id]
    
    async def stop_all_calls(self) -> int:
        killed = 0
        for unique_id, channel in list(self.channel_map.items()):
            try:
                await self.manager.send_action(
                    panoramisk.message.Action('Hangup', {'Channel': channel})
                )
                killed += 1
            except Exception as e:
                logger.error(f"Error killing call {unique_id}: {e}")
        
        await self.redis.delete(self.active_channels_key)
        await self.redis.delete(self.channels_hash_key)
        self.channel_map.clear()
        
        return killed
