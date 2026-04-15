#!/usr/bin/env python3
"""
Leader Election Module - Distributed Locking and Leadership
AutoDialer Ultimate v3.0.0

Provides distributed leader election using Redis for coordinating
background tasks across multiple instances.
"""

import asyncio
import socket
import uuid
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, Dict, Set
from contextlib import asynccontextmanager

from logger import logger


# =============================================
# Leader Election Configuration
# =============================================
class LeaderConfig:
    """Configuration for leader election"""
    
    def __init__(
        self,
        lock_key: str,
        ttl: int = 30,
        renew_interval: int = 10,
        retry_interval: int = 5,
        max_retries: int = 10
    ):
        self.lock_key = lock_key
        self.ttl = ttl
        self.renew_interval = renew_interval
        self.retry_interval = retry_interval
        self.max_retries = max_retries


# =============================================
# Leader Election Exception
# =============================================
class LeaderElectionError(Exception):
    """Base exception for leader election"""
    pass


class NotLeaderError(LeaderElectionError):
    """Raised when operation requires leadership"""
    pass


class LockAcquisitionError(LeaderElectionError):
    """Raised when lock cannot be acquired"""
    pass


# =============================================
# Leader Election Base Class
# =============================================
class LeaderElection:
    """
    Distributed leader election using Redis SET NX.
    
    Ensures only one instance performs leader-only tasks.
    """
    
    def __init__(
        self,
        redis_client,
        lock_key: str,
        ttl: int = 30,
        instance_id: Optional[str] = None,
        on_leader_start: Optional[Callable] = None,
        on_leader_stop: Optional[Callable] = None
    ):
        """
        Initialize leader election.
        
        Args:
            redis_client: Redis client instance
            lock_key: Unique key for the lock
            ttl: Lock TTL in seconds
            instance_id: Unique instance identifier (auto-generated if None)
            on_leader_start: Callback when leadership is acquired
            on_leader_stop: Callback when leadership is lost
        """
        self.redis = redis_client
        self.lock_key = f"leader:{lock_key}"
        self.ttl = ttl
        self.instance_id = instance_id or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        
        # Callbacks
        self.on_leader_start = on_leader_start
        self.on_leader_stop = on_leader_stop
        
        # State
        self.is_leader = False
        self._renew_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._running = False
        
        # Statistics
        self._stats = {
            'acquire_attempts': 0,
            'acquire_successes': 0,
            'acquire_failures': 0,
            'renew_attempts': 0,
            'renew_successes': 0,
            'renew_failures': 0,
            'leadership_lost_count': 0,
            'total_leadership_time': 0.0,
            'last_acquired': None,
            'last_lost': None
        }
        
        logger.info(f"LeaderElection initialized: {self.lock_key} (instance: {self.instance_id}, ttl: {ttl}s)")
    
    @property
    def leader_id(self) -> Optional[str]:
        """Get current leader's instance ID"""
        return self.instance_id if self.is_leader else None
    
    async def try_acquire(self) -> bool:
        """
        Try to acquire leadership.
        
        Returns:
            True if leadership acquired, False otherwise
        """
        async with self._lock:
            if self.is_leader:
                return True
            
            self._stats['acquire_attempts'] += 1
            
            try:
                # Try to set lock with NX (only if not exists)
                acquired = await self.redis.set(
                    self.lock_key,
                    self.instance_id,
                    ex=self.ttl,
                    nx=True
                )
                
                if acquired:
                    self.is_leader = True
                    self._stats['acquire_successes'] += 1
                    self._stats['last_acquired'] = datetime.now()
                    
                    logger.info(f"✅ Leadership acquired: {self.lock_key} by {self.instance_id}")
                    
                    # Start renewal task
                    self._running = True
                    self._renew_task = asyncio.create_task(self._renew_loop())
                    
                    # Call callback
                    if self.on_leader_start:
                        try:
                            await self.on_leader_start()
                        except Exception as e:
                            logger.error(f"on_leader_start callback failed: {e}")
                    
                    return True
                else:
                    self._stats['acquire_failures'] += 1
                    
                    # Check who is the current leader
                    current_leader = await self.redis.get(self.lock_key)
                    logger.debug(f"Leadership not acquired, current leader: {current_leader}")
                    return False
                    
            except Exception as e:
                self._stats['acquire_failures'] += 1
                logger.error(f"Failed to acquire leadership: {e}")
                return False
    
    async def _renew_loop(self):
        """Background task to renew leadership"""
        renew_interval = max(1, self.ttl // 3)  # Renew at 1/3 of TTL
        
        while self._running and self.is_leader:
            await asyncio.sleep(renew_interval)
            
            if not self.is_leader:
                break
            
            success = await self._renew()
            if not success:
                logger.error(f"Failed to renew leadership, stepping down")
                await self._step_down()
                break
    
    async def _renew(self) -> bool:
        """Renew the leadership lock"""
        self._stats['renew_attempts'] += 1
        
        try:
            # Use Lua script to ensure we only renew our own lock
            lua_script = """
                local current = redis.call('GET', KEYS[1])
                if current == ARGV[1] then
                    return redis.call('EXPIRE', KEYS[1], ARGV[2])
                end
                return 0
            """
            
            result = await self.redis.eval(
                lua_script,
                1,
                self.lock_key,
                self.instance_id,
                self.ttl
            )
            
            if result:
                self._stats['renew_successes'] += 1
                logger.debug(f"Leadership renewed: {self.lock_key}")
                return True
            else:
                self._stats['renew_failures'] += 1
                logger.warning(f"Failed to renew leadership (lock held by someone else)")
                return False
                
        except Exception as e:
            self._stats['renew_failures'] += 1
            logger.error(f"Renewal error: {e}")
            return False
    
    async def _step_down(self):
        """Voluntarily step down from leadership"""
        async with self._lock:
            if not self.is_leader:
                return
            
            logger.info(f"Stepping down from leadership: {self.lock_key}")
            
            self._running = False
            self.is_leader = False
            self._stats['leadership_lost_count'] += 1
            self._stats['last_lost'] = datetime.now()
            
            if self._stats['last_acquired']:
                delta = (datetime.now() - self._stats['last_acquired']).total_seconds()
                self._stats['total_leadership_time'] += delta
            
            # Cancel renewal task
            if self._renew_task and not self._renew_task.done():
                self._renew_task.cancel()
                try:
                    await self._renew_task
                except asyncio.CancelledError:
                    pass
                self._renew_task = None
            
            # Release lock if we still hold it
            await self._release_lock()
            
            # Call callback
            if self.on_leader_stop:
                try:
                    await self.on_leader_stop()
                except Exception as e:
                    logger.error(f"on_leader_stop callback failed: {e}")
    
    async def _release_lock(self):
        """Release the lock if we hold it"""
        try:
            lua_script = """
                local current = redis.call('GET', KEYS[1])
                if current == ARGV[1] then
                    return redis.call('DEL', KEYS[1])
                end
                return 0
            """
            
            await self.redis.eval(
                lua_script,
                1,
                self.lock_key,
                self.instance_id
            )
            logger.debug(f"Lock released: {self.lock_key}")
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
    
    async def release(self):
        """Release leadership (alias for step_down)"""
        await self._step_down()
    
    async def wait_for_leadership(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until leadership is acquired.
        
        Args:
            timeout: Maximum time to wait in seconds
        
        Returns:
            True if leadership acquired, False on timeout
        """
        start_time = datetime.now()
        
        while True:
            if await self.try_acquire():
                return True
            
            if timeout:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= timeout:
                    return False
            
            await asyncio.sleep(1)
    
    def require_leader(self):
        """Decorator to require leadership for a function"""
        def decorator(func: Callable) -> Callable:
            async def wrapper(*args, **kwargs):
                if not self.is_leader:
                    raise NotLeaderError(f"Operation requires leadership: {self.lock_key}")
                return await func(*args, **kwargs)
            return wrapper
        return decorator
    
    async def get_current_leader(self) -> Optional[str]:
        """Get the current leader's instance ID"""
        return await self.redis.get(self.lock_key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get leadership statistics"""
        stats = self._stats.copy()
        stats['is_leader'] = self.is_leader
        stats['instance_id'] = self.instance_id
        stats['lock_key'] = self.lock_key
        stats['ttl'] = self.ttl
        
        if self._stats['last_acquired']:
            stats['last_acquired'] = self._stats['last_acquired'].isoformat()
        if self._stats['last_lost']:
            stats['last_lost'] = self._stats['last_lost'].isoformat()
        
        return stats


# =============================================
# Leader Election with Health Check
# =============================================
class HealthCheckingLeaderElection(LeaderElection):
    """
    Leader election with additional health checking.
    
    Performs periodic health checks and steps down if unhealthy.
    """
    
    def __init__(
        self,
        redis_client,
        lock_key: str,
        ttl: int = 30,
        instance_id: Optional[str] = None,
        health_check: Optional[Callable[[], bool]] = None,
        health_check_interval: int = 10,
        on_leader_start: Optional[Callable] = None,
        on_leader_stop: Optional[Callable] = None
    ):
        super().__init__(
            redis_client, lock_key, ttl, instance_id,
            on_leader_start, on_leader_stop
        )
        self.health_check = health_check
        self.health_check_interval = health_check_interval
        self._health_check_task: Optional[asyncio.Task] = None
        self._healthy = True
    
    async def try_acquire(self) -> bool:
        """Try to acquire leadership with health check"""
        acquired = await super().try_acquire()
        
        if acquired and self.health_check:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        return acquired
    
    async def _health_check_loop(self):
        """Background health checking"""
        while self._running and self.is_leader:
            await asyncio.sleep(self.health_check_interval)
            
            if self.health_check:
                try:
                    healthy = await self.health_check() if asyncio.iscoroutinefunction(self.health_check) else self.health_check()
                    
                    if not healthy and self._healthy:
                        self._healthy = False
                        logger.warning(f"Instance became unhealthy, stepping down")
                        await self._step_down()
                    elif healthy and not self._healthy:
                        self._healthy = True
                        logger.info(f"Instance became healthy again")
                        
                except Exception as e:
                    logger.error(f"Health check failed: {e}")
    
    async def _step_down(self):
        """Step down and stop health check"""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
        
        await super()._step_down()


# =============================================
# Leader Election Registry
# =============================================
class LeaderElectionRegistry:
    """Registry for managing multiple leader elections"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self._elections: Dict[str, LeaderElection] = {}
        self._lock = asyncio.Lock()
    
    async def create(
        self,
        name: str,
        ttl: int = 30,
        instance_id: Optional[str] = None,
        **kwargs
    ) -> LeaderElection:
        """Create or get a leader election instance"""
        async with self._lock:
            if name not in self._elections:
                self._elections[name] = LeaderElection(
                    self.redis,
                    lock_key=name,
                    ttl=ttl,
                    instance_id=instance_id,
                    **kwargs
                )
            return self._elections[name]
    
    def get(self, name: str) -> Optional[LeaderElection]:
        """Get a leader election instance by name"""
        return self._elections.get(name)
    
    async def try_acquire_all(self) -> Dict[str, bool]:
        """Try to acquire all registered elections"""
        results = {}
        for name, election in self._elections.items():
            results[name] = await election.try_acquire()
        return results
    
    async def release_all(self):
        """Release all elections"""
        for election in self._elections.values():
            await election.release()
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all elections"""
        return {
            name: election.get_stats()
            for name, election in self._elections.items()
        }
    
    async def remove(self, name: str) -> bool:
        """Remove an election from registry"""
        async with self._lock:
            if name in self._elections:
                election = self._elections[name]
                if election.is_leader:
                    await election.release()
                del self._elections[name]
                return True
            return False


# =============================================
# Leader-Only Task Runner
# =============================================
class LeaderTaskRunner:
    """
    Run tasks only when instance is the leader.
    
    Automatically starts/stops tasks based on leadership status.
    """
    
    def __init__(self, election: LeaderElection):
        self.election = election
        self._tasks: Set[asyncio.Task] = set()
        self._task_factories: Dict[str, Callable] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    def add_task(self, name: str, factory: Callable[[], asyncio.Task]):
        """Add a task to run when leader"""
        self._task_factories[name] = factory
    
    async def start(self):
        """Start monitoring leadership and running tasks"""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"LeaderTaskRunner started for {self.election.lock_key}")
    
    async def stop(self):
        """Stop monitoring and all tasks"""
        self._running = False
        
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        await self._stop_all_tasks()
        logger.info(f"LeaderTaskRunner stopped for {self.election.lock_key}")
    
    async def _monitor_loop(self):
        """Monitor leadership status and start/stop tasks"""
        was_leader = False
        
        while self._running:
            is_leader = self.election.is_leader
            
            if is_leader and not was_leader:
                logger.info(f"Became leader, starting tasks")
                await self._start_all_tasks()
            elif not is_leader and was_leader:
                logger.info(f"Lost leadership, stopping tasks")
                await self._stop_all_tasks()
            
            was_leader = is_leader
            await asyncio.sleep(5)
    
    async def _start_all_tasks(self):
        """Start all registered tasks"""
        for name, factory in self._task_factories.items():
            try:
                task = factory()
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                logger.info(f"Started leader task: {name}")
            except Exception as e:
                logger.error(f"Failed to start task {name}: {e}")
    
    async def _stop_all_tasks(self):
        """Stop all running tasks"""
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error stopping task: {e}")
        self._tasks.clear()


# =============================================
# Context Manager for Leadership
# =============================================
@asynccontextmanager
async def leader_context(
    redis_client,
    lock_key: str,
    ttl: int = 30,
    instance_id: Optional[str] = None,
    wait_timeout: Optional[float] = None
):
    """
    Context manager for temporary leadership.
    
    Usage:
        async with leader_context(redis, "my-task") as is_leader:
            if is_leader:
                # Perform leader-only work
                pass
    """
    election = LeaderElection(redis_client, lock_key, ttl, instance_id)
    
    acquired = False
    try:
        if wait_timeout:
            acquired = await election.wait_for_leadership(wait_timeout)
        else:
            acquired = await election.try_acquire()
        
        yield acquired
        
    finally:
        if acquired:
            await election.release()


# =============================================
# Utility Functions
# =============================================
async def run_as_leader(
    redis_client,
    lock_key: str,
    func: Callable,
    *args,
    ttl: int = 30,
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    **kwargs
) -> Any:
    """
    Run a function only if this instance is the leader.
    
    Args:
        redis_client: Redis client
        lock_key: Lock key
        func: Function to run
        ttl: Lock TTL
        wait: Whether to wait for leadership
        wait_timeout: Max wait time
    
    Returns:
        Result of function, or None if not leader
    """
    election = LeaderElection(redis_client, lock_key, ttl)
    
    try:
        if wait:
            acquired = await election.wait_for_leadership(wait_timeout)
        else:
            acquired = await election.try_acquire()
        
        if acquired:
            return await func(*args, **kwargs)
        else:
            logger.debug(f"Not leader, skipping execution: {lock_key}")
            return None
            
    finally:
        if election.is_leader:
            await election.release()


async def get_or_create_leader(
    redis_client,
    lock_key: str,
    ttl: int = 30,
    instance_id: Optional[str] = None
) -> LeaderElection:
    """Get or create a singleton leader election for a key"""
    # Simple singleton cache
    if not hasattr(get_or_create_leader, '_cache'):
        get_or_create_leader._cache = {}
    
    if lock_key not in get_or_create_leader._cache:
        get_or_create_leader._cache[lock_key] = LeaderElection(
            redis_client, lock_key, ttl, instance_id
        )
    
    return get_or_create_leader._cache[lock_key]
