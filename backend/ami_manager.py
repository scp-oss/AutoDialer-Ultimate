#!/usr/bin/env python3
"""
AMI Manager for Asterisk
AutoDialer Ultimate v3.0.0
"""

import asyncio
import panoramisk
import time
import json
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
from cachetools import TTLCache

from logger import logger
from rate_limiter import TokenBucket, GlobalRateLimiter


class DialerManager:
    """Manages Asterisk AMI connection and call operations"""
    
    def __init__(self, db_pool, redis_client):
        self.db_pool = db_pool
        self.redis = redis_client
        
        # AMI Configuration
        ami_host = os.getenv('AMI_HOST', '127.0.0.1')
        ami_port = int(os.getenv('AMI_PORT', 5038))
        ami_user = os.getenv('AMI_USER', 'autodialer')
        ami_password = os.getenv('AMI_PASSWORD')
        
        if not ami_password:
            raise ValueError("AMI_PASSWORD not set in environment")
        
        self.manager = panoramisk.Manager(
            host=ami_host,
            port=ami_port,
            username=ami_user,
            secret=ami_password,
            ssl=False
        )
        
        # Dialer settings
        self.max_calls = int(os.getenv('MAX_CALLS', 50))
        self.caller_id = os.getenv('CALLER_ID', 'AutoDialer')
        self.call_timeout = int(os.getenv('CALL_TIMEOUT', 30))
        self.max_retries = int(os.getenv('MAX_RETRIES', 3))
        
        # Redis keys
        self.active_channels_key = "active_channels"
        self.channels_hash_key = "channels"
        self.dial_queue_key = "dial_queue"
        
        # State tracking
        self.channel_map: Dict[str, str] = {}  # unique_id -> channel
        self.call_start_times: Dict[str, datetime] = {}
        self.contact_map: Dict[str, int] = {}  # phone -> contact_id
        
        # Event deduplication
        self.processed_events = TTLCache(maxsize=100000, ttl=300)
        self.hangup_events = TTLCache(maxsize=50000, ttl=60)
        
        # Running state
        self.running = True
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        
        # Rate limiters
        self.cps_limiter = TokenBucket(rate=int(os.getenv('DEFAULT_CPS', 5)))
        self.global_limiter = GlobalRateLimiter(redis_client, "global_cps", rate=100)
        
        # Register event handlers
        self.manager.register_event('*', self.handle_ami_event)
        
        # Start background tasks
        asyncio.create_task(self.watchdog_stale_calls())
        asyncio.create_task(self.queue_worker())
        asyncio.create_task(self.reconcile_channels())
        asyncio.create_task(self.load_state_from_redis())
        asyncio.create_task(self.health_check())
    
    # =============================================
    # Connection Management
    # =============================================
    async def ensure_connected(self):
        """Ensure AMI connection with retry logic"""
        while not self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self.manager.connect()
                self.connected = True
                self.reconnect_attempts = 0
                logger.info("✅ AMI Connected successfully")
                
                # Subscribe to all events
                await self.manager.send_action(panoramisk.message.Action('Events', {'EventMask': 'on'}))
                
            except Exception as e:
                self.reconnect_attempts += 1
                wait_time = min(2 ** self.reconnect_attempts, 60)
                logger.warning(f"AMI connection failed (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}): {e}")
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
        
        if not self.connected:
            logger.error("Failed to connect to AMI after maximum attempts")
            raise Exception("AMI connection failed")
    
    async def health_check(self):
        """Periodic health check and reconnection"""
        while True:
            await asyncio.sleep(30)
            
            if not self.connected:
                logger.warning("AMI disconnected, attempting to reconnect...")
                await self.ensure_connected()
                continue
            
            try:
                # Test connection
                action = panoramisk.message.Action('Ping')
                response = await asyncio.wait_for(
                    self.manager.send_action(action),
                    timeout=5.0
                )
                if not response or response.get('response') != 'Success':
                    raise Exception("Ping failed")
            except Exception as e:
                logger.error(f"AMI health check failed: {e}")
                self.connected = False
                await self.ensure_connected()
    
    # =============================================
    # State Recovery
    # =============================================
    async def load_state_from_redis(self):
        """Restore state from Redis after restart"""
        await asyncio.sleep(2)
        
        try:
            # Load channel map
            channels = await self.redis.hgetall(self.channels_hash_key)
            self.channel_map = dict(channels)
            
            # Restore call start times (use current time for watchdog)
            for unique_id in self.channel_map:
                self.call_start_times[unique_id] = datetime.now()
            
            logger.info(f"Restored {len(self.channel_map)} channels from Redis")
            
            # Load contact map cache
            contact_keys = await self.redis.keys("contact:*")
            for key in contact_keys:
                phone = key.replace("contact:", "")
                contact_id = await self.redis.get(key)
                if contact_id:
                    self.contact_map[phone] = int(contact_id)
            
            logger.info(f"Restored {len(self.contact_map)} contacts from cache")
            
        except Exception as e:
            logger.error(f"Failed to load state from Redis: {e}")
    
    async def reconcile_channels(self):
        """Periodic reconciliation with Asterisk state"""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            
            if not self.running or not self.connected:
                continue
            
            try:
                redis_count = await self.redis.scard(self.active_channels_key)
                local_count = len(self.channel_map)
                
                # Only sync if significant mismatch
                if abs(redis_count - local_count) > max(5, redis_count * 0.1):
                    logger.warning(f"Channel mismatch: Redis={redis_count}, Local={local_count}")
                    await self._sync_channels_from_asterisk()
            except Exception as e:
                logger.error(f"Channel reconciliation error: {e}")
    
    async def _sync_channels_from_asterisk(self):
        """Full synchronization with Asterisk via CoreShowChannels"""
        try:
            action = panoramisk.message.Action('CoreShowChannels')
            response = await asyncio.wait_for(
                self.manager.send_action(action),
                timeout=10.0
            )
            
            # Clear existing state
            await self.redis.delete(self.active_channels_key)
            await self.redis.delete(self.channels_hash_key)
            old_channel_map = self.channel_map.copy()
            self.channel_map.clear()
            self.call_start_times.clear()
            
            # Parse response
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
            logger.info(f"Synced {synced_count} channels with Asterisk")
            
            # Update active calls counter
            await self.redis.set("active_calls", synced_count)
            await self.redis.expire("active_calls", 120)
            
        except Exception as e:
            logger.error(f"Channel sync failed: {e}")
    
    # =============================================
    # Phone Number Normalization
    # =============================================
    def normalize_phone(self, phone: str) -> Optional[str]:
        """Normalize phone number to international format"""
        if not phone:
            return None
        
        # Remove all non-digits
        phone = re.sub(r'[^\d]', '', phone)
        
        # Russian numbers
        if len(phone) == 11 and phone.startswith('7'):
            return phone
        elif len(phone) == 11 and phone.startswith('8'):
            return '7' + phone[1:]
        elif len(phone) == 10 and phone.startswith('9'):
            return '7' + phone
        
        # International (10+ digits)
        if len(phone) >= 10:
            return phone
        
        logger.warning(f"Invalid phone number format: {phone}")
        return None
    
    async def get_or_create_contact(self, phone: str) -> Optional[int]:
        """Get contact_id from normalized phone, with caching"""
        normalized = self.normalize_phone(phone)
        if not normalized:
            return None
        
        # Check cache
        if normalized in self.contact_map:
            return self.contact_map[normalized]
        
        # Check Redis cache
        cached = await self.redis.get(f"contact:{normalized}")
        if cached:
            contact_id = int(cached)
            self.contact_map[normalized] = contact_id
            return contact_id
        
        # Query database
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    """INSERT INTO contacts (phone) VALUES ($1) 
                       ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone 
                       RETURNING id""",
                    normalized
                )
                contact_id = result['id']
                
                # Cache in Redis (1 hour TTL)
                await self.redis.setex(f"contact:{normalized}", 3600, contact_id)
                self.contact_map[normalized] = contact_id
                
                return contact_id
        except Exception as e:
            logger.error(f"Failed to get/create contact {normalized}: {e}")
            return None
    
    # =============================================
    # Call Initiation
    # =============================================
    async def start_call(self, phone: str, campaign_id: int, retry: int = 0):
        """Queue a call for dialing"""
        normalized = self.normalize_phone(phone)
        if not normalized:
            logger.warning(f"Skipping invalid phone: {phone}")
            return
        
        # Check blacklist
        blacklisted = await self.redis.sismember("blacklist:phones", normalized)
        if blacklisted:
            logger.info(f"Skipping blacklisted number: {normalized}")
            return
        
        # Add to queue
        await self.redis.rpush(self.dial_queue_key, json.dumps({
            "phone": normalized,
            "campaign_id": campaign_id,
            "retry": retry,
            "queued_at": datetime.now().isoformat()
        }))
        
        queue_size = await self.redis.llen(self.dial_queue_key)
        logger.debug(f"Call queued: {normalized} (campaign {campaign_id}), queue size: {queue_size}")
    
    async def queue_worker(self):
        """Background worker processing the dial queue"""
        logger.info("Queue worker started")
        
        while self.running:
            try:
                # Blocking pop with timeout
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
                logger.error(f"Queue worker error: {e}")
                await asyncio.sleep(1)
        
        logger.info("Queue worker stopped")
    
    async def _start_call(self, phone: str, campaign_id: int, retry: int):
        """Internal method to initiate a call"""
        # Check running state
        if not self.running:
            logger.debug("Dialer stopped, skipping call")
            return
        
        # Check system enabled
        enabled = await self.redis.get("system_enabled") or "true"
        if enabled != "true":
            logger.debug("System disabled, skipping call")
            return
        
        # Check global CPS limit
        if not await self.global_limiter.acquire():
            # Re-queue with delay
            await asyncio.sleep(0.1)
            await self.redis.rpush(self.dial_queue_key, json.dumps({
                "phone": phone,
                "campaign_id": campaign_id,
                "retry": retry
            }))
            return
        
        # Normalize phone
        normalized = self.normalize_phone(phone)
        if not normalized:
            return
        
        # Check blacklist again (in case it was added after queueing)
        blacklisted = await self.redis.sismember("blacklist:phones", normalized)
        if blacklisted:
            logger.info(f"Skipping blacklisted number: {normalized}")
            return
        
        # Check channel limit
        active = await self.redis.scard(self.active_channels_key)
        if active >= self.max_calls:
            # Re-queue
            await self.redis.rpush(self.dial_queue_key, json.dumps({
                "phone": normalized,
                "campaign_id": campaign_id,
                "retry": retry
            }))
            logger.debug(f"Channel limit reached ({active}/{self.max_calls}), re-queued")
            return
        
        # Check if already calling this number
        for channel in self.channel_map.values():
            if normalized in channel:
                logger.debug(f"Already calling {normalized}, skipping")
                return
        
        # Prepare originate action
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
                logger.info(f"📞 Originate OK: {unique_id} -> {normalized} (campaign {campaign_id}, retry {retry})")
                
                # Update metrics
                from prometheus_client import Counter
                calls_counter = Counter('autodialer_calls_initiated', 'Calls initiated', ['campaign_id'])
                calls_counter.labels(campaign_id=str(campaign_id)).inc()
                
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                logger.error(f"Originate failed for {normalized}: {error_msg}")
                
                # Save failed result
                await self.save_call_result(campaign_id, normalized, 'failed', None, None, retry)
                
                # Schedule retry for failed originate
                if retry < 1:
                    await self.schedule_retry(campaign_id, normalized, retry + 1, 'failed')
                    
        except Exception as e:
            logger.error(f"Originate exception for {normalized}: {e}")
            await self.save_call_result(campaign_id, normalized, 'failed', None, None, retry)
    
    # =============================================
    # AMI Event Handling
    # =============================================
    async def handle_ami_event(self, manager, event):
        """Handle incoming AMI events"""
        event_name = event.name
        channel = event.get('channel', '')
        unique_id = event.get('uniqueid')
        linked_id = event.get('linkedid')
        
        # Skip if not our channel
        if channel and not channel.startswith('Local/'):
            return
        
        # Deduplicate events
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
            logger.error(f"Error handling {event_name} event: {e}", exc_info=True)
    
    async def _handle_dial_begin(self, event, channel: str, unique_id: str):
        """Handle DialBegin event"""
        if not channel.startswith('Local/'):
            return
        
        key = f"{channel}:{unique_id}"
        
        # Add to Redis
        await self.redis.sadd(self.active_channels_key, key)
        await self.redis.hset(self.channels_hash_key, unique_id, channel)
        await self.redis.expire(self.active_channels_key, 120)
        
        # Add to local map
        self.channel_map[unique_id] = channel
        
        # Update active calls counter
        active = await self.redis.scard(self.active_channels_key)
        await self.redis.set("active_calls", active)
        await self.redis.expire("active_calls", 120)
        
        logger.debug(f"DialBegin: {unique_id} on {channel}, active calls: {active}")
    
    async def _handle_dial_end(self, event, unique_id: str):
        """Handle DialEnd event"""
        dial_status = event.get('dialstatus', 'UNKNOWN')
        logger.debug(f"DialEnd: {unique_id}, status: {dial_status}")
    
    async def _handle_bridge_enter(self, event, unique_id: str, linked_id: str):
        """Handle BridgeEnter event (call answered)"""
        logger.info(f"✅ Call answered: {unique_id} (linked: {linked_id})")
        
        # Remove from watchdog (call is now active)
        if unique_id in self.call_start_times:
            del self.call_start_times[unique_id]
    
    async def _handle_hangup(self, event, channel: str, unique_id: str, linked_id: str):
        """Handle Hangup event"""
        # Deduplicate hangup events
        hangup_key = f"hangup_{unique_id}"
        if hangup_key in self.hangup_events:
            return
        self.hangup_events[hangup_key] = True
        
        # Also use Redis for distributed deduplication
        redis_hangup_key = f"hangup:{unique_id}"
        if not await self.redis.set(redis_hangup_key, "1", ex=10, nx=True):
            return
        
        cause = event.get('cause', '0')
        cause_txt = event.get('cause-txt', 'UNKNOWN')
        
        # Remove from active channels
        if unique_id in self.channel_map:
            channel = self.channel_map[unique_id]
            key = f"{channel}:{unique_id}"
            
            await self.redis.srem(self.active_channels_key, key)
            await self.redis.hdel(self.channels_hash_key, unique_id)
            del self.channel_map[unique_id]
        
        # Remove from watchdog
        if unique_id in self.call_start_times:
            del self.call_start_times[unique_id]
        
        # Update active calls counter
        active = await self.redis.scard(self.active_channels_key)
        await self.redis.set("active_calls", active)
        
        logger.info(f"📴 Hangup: {unique_id}, cause: {cause_txt} ({cause}), active calls: {active}")
    
    async def _handle_user_event(self, event, linked_id: str):
        """Handle UserEvent (custom events from dialplan)"""
        userevent = event.get('userevent')
        
        if userevent == 'DialerResult':
            status = event.get('status', 'unknown')
            campaign_id = event.get('campaign', '0')
            phone = event.get('phone', '')
            retry_count = int(event.get('retrycount', '0'))
            
            logger.info(f"🎯 DialerResult: campaign={campaign_id}, phone={phone}, status={status}, retry={retry_count}")
            
            # Save result
            await self.save_call_result(campaign_id, phone, status, linked_id, None, retry_count)
            
            # Schedule retry if needed
            if status in ['noanswer', 'busy', 'failed']:
                await self.schedule_retry(campaign_id, phone, retry_count + 1, status)
            
            # Update metrics
            from prometheus_client import Counter
            result_counter = Counter('autodialer_call_results', 'Call results', ['status', 'campaign_id'])
            result_counter.labels(status=status, campaign_id=campaign_id).inc()
            
        elif userevent == 'DialerHangup':
            channel = event.get('channel', '')
            status = event.get('status', '')
            logger.debug(f"DialerHangup: {channel}, status: {status}")
    
    async def _handle_var_set(self, event, unique_id: str):
        """Handle VarSet event (variable tracking)"""
        variable = event.get('variable', '')
        value = event.get('value', '')
        
        # Track campaign ID for the channel
        if variable == 'CAMPAIGN_ID' and unique_id:
            logger.debug(f"VarSet: {unique_id} campaign={value}")
    
    # =============================================
    # Result Handling
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
        """Save call result to database"""
        try:
            contact_id = await self.get_or_create_contact(phone)
            if not contact_id:
                logger.error(f"Failed to get/create contact for {phone}")
                return
            
            async with self.db_pool.acquire() as conn:
                # Insert call result
                await conn.execute("""
                    INSERT INTO call_results 
                    (campaign_id, contact_id, linked_id, unique_id, status, retry_count)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, int(campaign_id), contact_id, linked_id, unique_id, status, retry)
                
                # Update campaign_contacts
                await conn.execute("""
                    UPDATE campaign_contacts 
                    SET retry_count = $1, last_call_at = NOW()
                    WHERE campaign_id = $2 AND contact_id = $3
                """, retry, int(campaign_id), contact_id)
                
                logger.debug(f"Saved result: campaign={campaign_id}, phone={phone}, status={status}")
                
        except Exception as e:
            logger.error(f"Failed to save call result: {e}")
    
    async def schedule_retry(self, campaign_id: str, phone: str, retry_count: int, status: str):
        """Schedule a retry for failed call"""
        # Retry strategies by status
        strategies = {
            'busy': {'max': 2, 'delay': 120},
            'noanswer': {'max': 3, 'delay': 300},
            'failed': {'max': 1, 'delay': 60},
            'timeout': {'max': 1, 'delay': 60}
        }
        
        strategy = strategies.get(status, {'max': 1, 'delay': 60})
        
        if retry_count >= strategy['max']:
            logger.info(f"Max retries ({strategy['max']}) reached for {phone} (status: {status})")
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
            
            logger.info(f"⏰ Scheduled retry {retry_count}/{strategy['max']} for {phone} in {strategy['delay']}s")
            
        except Exception as e:
            logger.error(f"Failed to schedule retry: {e}")
    
    # =============================================
    # Watchdog & Cleanup
    # =============================================
    async def watchdog_stale_calls(self):
        """Kill calls that haven't connected within timeout"""
        logger.info("Watchdog started")
        
        while self.running:
            await asyncio.sleep(15)
            
            now = datetime.now()
            stale_timeout = timedelta(seconds=90)
            
            for unique_id, start_time in list(self.call_start_times.items()):
                if now - start_time > stale_timeout:
                    channel = self.channel_map.get(unique_id)
                    if channel:
                        logger.warning(f"⚠️ Watchdog killing stale call: {unique_id} on {channel} (age: {(now - start_time).seconds}s)")
                        
                        try:
                            action = panoramisk.message.Action('Hangup', {'Channel': channel})
                            await self.manager.send_action(action)
                        except Exception as e:
                            logger.error(f"Watchdog hangup failed for {unique_id}: {e}")
                    
                    # Clean up
                    if unique_id in self.call_start_times:
                        del self.call_start_times[unique_id]
    
    async def stop_all_calls(self) -> int:
        """Emergency stop: kill all active calls"""
        killed = 0
        
        for unique_id, channel in list(self.channel_map.items()):
            try:
                action = panoramisk.message.Action('Hangup', {'Channel': channel})
                await self.manager.send_action(action)
                killed += 1
                logger.info(f"Force killed call: {unique_id} on {channel}")
            except Exception as e:
                logger.error(f"Failed to kill call {unique_id}: {e}")
        
        # Clear all state
        await self.redis.delete(self.active_channels_key)
        await self.redis.delete(self.channels_hash_key)
        await self.redis.set("active_calls", "0")
        
        self.channel_map.clear()
        self.call_start_times.clear()
        
        logger.warning(f"Emergency stop completed, killed {killed} calls")
        return killed
    
    # =============================================
    # Status & Monitoring
    # =============================================
    def get_status(self) -> dict:
        """Get current dialer status"""
        return {
            "connected": self.connected,
            "running": self.running,
            "active_calls": len(self.channel_map),
            "max_calls": self.max_calls,
            "queue_size": 0,  # Will be filled by caller
            "cps_rate": self.cps_limiter.rate,
            "reconnect_attempts": self.reconnect_attempts
        }
    
    async def get_queue_size(self) -> int:
        """Get current queue size"""
        return await self.redis.llen(self.dial_queue_key)
    
    async def get_active_channels(self) -> list:
        """Get list of active channels"""
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
