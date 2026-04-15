#!/usr/bin/env python3
"""
Circuit Breaker Pattern Implementation
AutoDialer Ultimate v3.0.0

Provides fault tolerance for external service calls (Database, Redis, AMI, etc.)
"""

import asyncio
import time
from enum import Enum
from datetime import datetime, timedelta
from typing import Callable, Optional, Any, Dict, TypeVar, Generic
from functools import wraps
import threading

from logger import logger


# =============================================
# Circuit State Enum
# =============================================
class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"          # Normal operation, requests pass through
    OPEN = "open"              # Failing, requests are blocked
    HALF_OPEN = "half_open"    # Testing if service recovered


# =============================================
# Circuit Breaker Statistics
# =============================================
class CircuitStatistics:
    """Track circuit breaker statistics"""
    
    def __init__(self):
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.timeout_calls: int = 0
        self.rejected_calls: int = 0
        self.last_success_time: Optional[datetime] = None
        self.last_failure_time: Optional[datetime] = None
        self.last_failure_error: Optional[str] = None
        self.total_open_time: float = 0.0
        self.open_count: int = 0
        self.reset_time: Optional[datetime] = None
    
    def record_success(self):
        self.total_calls += 1
        self.successful_calls += 1
        self.last_success_time = datetime.now()
    
    def record_failure(self, error: str = None):
        self.total_calls += 1
        self.failed_calls += 1
        self.last_failure_time = datetime.now()
        self.last_failure_error = error
    
    def record_timeout(self):
        self.total_calls += 1
        self.timeout_calls += 1
        self.last_failure_time = datetime.now()
    
    def record_rejected(self):
        self.rejected_calls += 1
    
    def record_open(self):
        self.open_count += 1
        self.reset_time = datetime.now()
    
    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100
    
    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "timeout_calls": self.timeout_calls,
            "rejected_calls": self.rejected_calls,
            "success_rate": round(self.success_rate, 2),
            "failure_rate": round(self.failure_rate, 2),
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_failure_error": self.last_failure_error,
            "open_count": self.open_count
        }
    
    def reset(self):
        """Reset statistics"""
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.timeout_calls = 0
        self.rejected_calls = 0
        self.last_success_time = None
        self.last_failure_time = None
        self.last_failure_error = None
        self.open_count = 0


# =============================================
# Circuit Breaker Configuration
# =============================================
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
        half_open_timeout: float = 30.0,
        failure_window: float = 60.0,
        max_timeout: float = 300.0,
        exponential_backoff: bool = True
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_timeout = half_open_timeout
        self.failure_window = failure_window
        self.max_timeout = max_timeout
        self.exponential_backoff = exponential_backoff


# =============================================
# Circuit Breaker Exceptions
# =============================================
class CircuitBreakerError(Exception):
    """Base exception for circuit breaker"""
    pass


class CircuitOpenError(CircuitBreakerError):
    """Raised when circuit is open and request is rejected"""
    
    def __init__(self, name: str, remaining_time: float = None):
        self.name = name
        self.remaining_time = remaining_time
        message = f"Circuit '{name}' is OPEN"
        if remaining_time:
            message += f" (retry in {remaining_time:.1f}s)"
        super().__init__(message)


class CircuitTimeoutError(CircuitBreakerError):
    """Raised when request times out"""
    
    def __init__(self, name: str, timeout: float):
        self.name = name
        self.timeout = timeout
        super().__init__(f"Circuit '{name}' timed out after {timeout}s")


# =============================================
# Main Circuit Breaker Class (Async)
# =============================================
T = TypeVar('T')


class CircuitBreaker(Generic[T]):
    """
    Circuit Breaker pattern implementation for async operations.
    
    Protects external services from cascade failures.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
        timeout: float = 30.0,
        max_timeout: float = 300.0,
        exponential_backoff: bool = True,
        on_open: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_half_open: Optional[Callable] = None
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Unique name for this circuit
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open
            success_threshold: Successful calls needed to close circuit
            timeout: Request timeout in seconds
            max_timeout: Maximum recovery timeout (for exponential backoff)
            exponential_backoff: Use exponential backoff for recovery
            on_open: Callback when circuit opens
            on_close: Callback when circuit closes
            on_half_open: Callback when circuit goes half-open
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.base_recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.max_timeout = max_timeout
        self.exponential_backoff = exponential_backoff
        
        # Callbacks
        self.on_open = on_open
        self.on_close = on_close
        self.on_half_open = on_half_open
        
        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_state_change: datetime = datetime.now()
        self.open_count = 0
        
        # Locks
        self._lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        
        # Statistics
        self.stats = CircuitStatistics()
        
        # Failure timestamps for sliding window
        self._failure_timestamps: list[datetime] = []
        self._failure_window = 60.0  # 1 minute window
        
        logger.info(f"Circuit '{name}' initialized (threshold={failure_threshold}, timeout={recovery_timeout}s)")
    
    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN
    
    @property
    def recovery_remaining(self) -> float:
        """Seconds remaining until recovery attempt"""
        if not self.is_open or not self.last_failure_time:
            return 0.0
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return max(0.0, self.recovery_timeout - elapsed)
    
    def _cleanup_failure_window(self):
        """Remove failures outside the sliding window"""
        cutoff = datetime.now() - timedelta(seconds=self._failure_window)
        self._failure_timestamps = [ts for ts in self._failure_timestamps if ts > cutoff]
    
    def _calculate_recovery_timeout(self) -> int:
        """Calculate recovery timeout with optional exponential backoff"""
        if not self.exponential_backoff:
            return self.base_recovery_timeout
        
        # Exponential backoff: base * 2^open_count
        backoff = self.base_recovery_timeout * (2 ** self.open_count)
        return min(backoff, self.max_timeout)
    
    async def _transition_to_open(self, error: str = None):
        """Transition circuit to OPEN state"""
        if self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            self.open_count += 1
            self.recovery_timeout = self._calculate_recovery_timeout()
            self.last_state_change = datetime.now()
            self.stats.record_open()
            
            logger.warning(
                f"Circuit '{self.name}' OPENED after {self.failure_count} failures "
                f"(recovery timeout: {self.recovery_timeout}s, error: {error})"
            )
            
            if self.on_open:
                try:
                    self.on_open(self.name, self.failure_count)
                except Exception as e:
                    logger.error(f"on_open callback failed: {e}")
    
    async def _transition_to_half_open(self):
        """Transition circuit to HALF_OPEN state"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.last_state_change = datetime.now()
        
        logger.info(f"Circuit '{self.name}' HALF_OPEN (testing recovery)")
        
        if self.on_half_open:
            try:
                self.on_half_open(self.name)
            except Exception as e:
                logger.error(f"on_half_open callback failed: {e}")
    
    async def _transition_to_closed(self):
        """Transition circuit to CLOSED state"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self._failure_timestamps.clear()
        self.recovery_timeout = self.base_recovery_timeout
        self.last_state_change = datetime.now()
        
        logger.info(f"Circuit '{self.name}' CLOSED (recovered)")
        
        if self.on_close:
            try:
                self.on_close(self.name)
            except Exception as e:
                logger.error(f"on_close callback failed: {e}")
    
    async def _check_state(self):
        """Check and potentially transition circuit state"""
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if self.recovery_remaining <= 0:
                    await self._transition_to_half_open()
                else:
                    self.stats.record_rejected()
                    raise CircuitOpenError(self.name, self.recovery_remaining)
            
            elif self.state == CircuitState.HALF_OPEN:
                # Still in half-open, requests are allowed in limited capacity
                pass
            
            # CLOSED state - nothing to do
    
    async def _record_success(self):
        """Record a successful call"""
        async with self._lock:
            self.stats.record_success()
            
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    await self._transition_to_closed()
            
            elif self.state == CircuitState.CLOSED:
                # In closed state, reset failure count on success
                if self.failure_count > 0:
                    self.failure_count = max(0, self.failure_count - 1)
    
    async def _record_failure(self, error: str = None):
        """Record a failed call"""
        async with self._lock:
            self.stats.record_failure(error)
            self.last_failure_time = datetime.now()
            self._failure_timestamps.append(self.last_failure_time)
            self._cleanup_failure_window()
            
            if self.state == CircuitState.HALF_OPEN:
                # In half-open, a single failure re-opens the circuit
                self.failure_count = len(self._failure_timestamps)
                await self._transition_to_open(error)
            
            elif self.state == CircuitState.CLOSED:
                self.failure_count = len(self._failure_timestamps)
                if self.failure_count >= self.failure_threshold:
                    await self._transition_to_open(error)
    
    async def call(
        self,
        func: Callable[..., Any],
        *args,
        timeout: Optional[float] = None,
        **kwargs
    ) -> T:
        """
        Execute a function with circuit breaker protection.
        
        Args:
            func: Async function to call
            *args: Positional arguments
            timeout: Optional timeout override
            **kwargs: Keyword arguments
        
        Returns:
            Result of the function
        
        Raises:
            CircuitOpenError: If circuit is open
            CircuitTimeoutError: If call times out
            Original exception: If function fails
        """
        # Check circuit state
        await self._check_state()
        
        call_timeout = timeout if timeout is not None else self.timeout
        
        try:
            # Execute with timeout
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=call_timeout
                )
            else:
                # Run sync function in thread pool
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: func(*args, **kwargs)
                    ),
                    timeout=call_timeout
                )
            
            await self._record_success()
            return result
            
        except asyncio.TimeoutError:
            self.stats.record_timeout()
            await self._record_failure(f"Timeout after {call_timeout}s")
            raise CircuitTimeoutError(self.name, call_timeout)
            
        except CircuitOpenError:
            # Re-raise circuit open errors
            raise
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            await self._record_failure(error_msg)
            raise
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self._check_state()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if exc_type is None:
            await self._record_success()
        elif exc_type not in (CircuitOpenError, CircuitTimeoutError):
            error_msg = f"{exc_type.__name__}: {str(exc_val)}"
            await self._record_failure(error_msg)
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit status"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "open_count": self.open_count,
            "recovery_timeout": self.recovery_timeout,
            "recovery_remaining": round(self.recovery_remaining, 1),
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_state_change": self.last_state_change.isoformat(),
            "statistics": self.stats.to_dict()
        }
    
    def reset(self):
        """Force reset circuit to closed state"""
        async def _reset():
            async with self._lock:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self._failure_timestamps.clear()
                self.recovery_timeout = self.base_recovery_timeout
                self.last_state_change = datetime.now()
                logger.info(f"Circuit '{self.name}' manually reset to CLOSED")
        
        # Schedule reset
        asyncio.create_task(_reset())
    
    def force_open(self):
        """Force circuit to open state"""
        async def _force_open():
            async with self._lock:
                self.last_failure_time = datetime.now()
                await self._transition_to_open("Manually forced open")
        
        asyncio.create_task(_force_open())


# =============================================
# Circuit Breaker (Synchronous Version)
# =============================================
class SyncCircuitBreaker:
    """
    Synchronous circuit breaker for non-async code.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        timeout: float = 30.0
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.timeout = timeout
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self._lock = threading.Lock()
        
        self.stats = CircuitStatistics()
    
    def _check_state(self):
        """Check circuit state (synchronous)"""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self.last_failure_time:
                    elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                    if elapsed >= self.recovery_timeout:
                        self.state = CircuitState.HALF_OPEN
                    else:
                        self.stats.record_rejected()
                        raise CircuitOpenError(self.name, self.recovery_timeout - elapsed)
    
    def call(self, func: Callable, *args, timeout: Optional[float] = None, **kwargs):
        """Execute function with circuit breaker protection (sync)"""
        self._check_state()
        
        call_timeout = timeout if timeout is not None else self.timeout
        
        try:
            import signal
            
            def timeout_handler(signum, frame):
                raise CircuitTimeoutError(self.name, call_timeout)
            
            # Set timeout
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(call_timeout))
            
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            
            with self._lock:
                self.stats.record_success()
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            
            return result
            
        except CircuitTimeoutError:
            with self._lock:
                self.stats.record_timeout()
                self.failure_count += 1
                self.last_failure_time = datetime.now()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
            raise
            
        except Exception as e:
            with self._lock:
                self.stats.record_failure(str(e))
                self.failure_count += 1
                self.last_failure_time = datetime.now()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
            raise


# =============================================
# Circuit Breaker Registry
# =============================================
class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers"""
    
    def __init__(self):
        self._circuits: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()
    
    async def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        **kwargs
    ) -> CircuitBreaker:
        """Get existing circuit or create new one"""
        async with self._lock:
            if name not in self._circuits:
                self._circuits[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    **kwargs
                )
            return self._circuits[name]
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit by name"""
        return self._circuits.get(name)
    
    def list_circuits(self) -> list[str]:
        """List all circuit names"""
        return list(self._circuits.keys())
    
    def get_all_status(self) -> Dict[str, Any]:
        """Get status of all circuits"""
        return {
            name: circuit.get_status()
            for name, circuit in self._circuits.items()
        }
    
    async def reset_all(self):
        """Reset all circuits"""
        for circuit in self._circuits.values():
            circuit.reset()
    
    async def remove(self, name: str) -> bool:
        """Remove a circuit"""
        async with self._lock:
            if name in self._circuits:
                del self._circuits[name]
                return True
            return False


# =============================================
# Global Registry Instance
# =============================================
circuit_registry = CircuitBreakerRegistry()


# =============================================
# Decorator for Circuit Breaker
# =============================================
def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    timeout: float = 30.0
):
    """Decorator to wrap a function with circuit breaker"""
    def decorator(func: Callable) -> Callable:
        breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            timeout=timeout
        )
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        
        wrapper._circuit_breaker = breaker
        return wrapper
    
    return decorator


# =============================================
# Utility Functions
# =============================================
async def with_circuit_breaker(
    name: str,
    func: Callable,
    *args,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    **kwargs
) -> Any:
    """Execute a function with a temporary circuit breaker"""
    breaker = await circuit_registry.get_or_create(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout
    )
    return await breaker.call(func, *args, **kwargs)
