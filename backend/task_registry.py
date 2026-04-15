#!/usr/bin/env python3
"""
Task Registry Module - Manage Async Tasks
AutoDialer Ultimate v3.0.0

Provides centralized management of asyncio tasks with:
- Task registration and tracking
- Graceful cancellation
- Task status monitoring
- Automatic cleanup
"""

import asyncio
import uuid
from datetime import datetime
from typing import Dict, Set, Optional, Any, Callable, Awaitable, List, Union
from dataclasses import dataclass, field
from enum import Enum

from logger import logger


# =============================================
# Task Status Enum
# =============================================
class TaskStatus(str, Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# =============================================
# Task Info
# =============================================
@dataclass
class TaskInfo:
    """Information about a registered task"""
    task_id: str
    name: str
    task: asyncio.Task
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None
    _timeout_handler: Optional[asyncio.TimerHandle] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "metadata": self.metadata,
            "timeout": self.timeout,
            "is_done": self.task.done() if self.task else False,
            "is_cancelled": self.task.cancelled() if self.task else False
        }


# =============================================
# Task Registry
# =============================================
class TaskRegistry:
    """
    Registry for managing asyncio tasks.
    
    Provides:
    - Task registration with unique IDs
    - Task cancellation (individual or all)
    - Task status tracking
    - Automatic timeout handling
    - Graceful shutdown support
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize task registry.
        
        Args:
            max_history: Maximum number of completed tasks to keep in history
        """
        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = asyncio.Lock()
        self._max_history = max_history
        self._history: List[TaskInfo] = []
        
        # Statistics
        self._stats = {
            'total_registered': 0,
            'total_completed': 0,
            'total_failed': 0,
            'total_cancelled': 0,
            'total_timeout': 0
        }
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the registry (background cleanup)"""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("TaskRegistry started")
    
    async def stop(self, grace_period: float = 5.0):
        """
        Stop the registry and cancel all tasks.
        
        Args:
            grace_period: Time to wait for tasks to complete
        """
        if not self._running:
            return
        
        self._running = False
        
        # Cancel cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all registered tasks
        await self.cancel_all(grace_period)
        
        logger.info("TaskRegistry stopped")
    
    async def _cleanup_loop(self):
        """Background task to clean up completed tasks"""
        while self._running:
            await asyncio.sleep(60)  # Run every minute
            await self._cleanup_completed()
    
    async def _cleanup_completed(self):
        """Remove old completed tasks from active registry"""
        async with self._lock:
            completed_ids = []
            
            for task_id, info in self._tasks.items():
                if info.task and info.task.done():
                    completed_ids.append(task_id)
                    
                    # Move to history
                    self._add_to_history(info)
            
            for task_id in completed_ids:
                del self._tasks[task_id]
    
    def _add_to_history(self, info: TaskInfo):
        """Add completed task to history"""
        self._history.append(info)
        
        # Trim history
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
    
    def _generate_task_id(self, prefix: str = "") -> str:
        """Generate a unique task ID"""
        return f"{prefix}{uuid.uuid4().hex[:12]}"
    
    def _create_timeout_handler(self, task_id: str, timeout: float):
        """Create a timeout handler for a task"""
        loop = asyncio.get_event_loop()
        
        def on_timeout():
            asyncio.create_task(self._handle_timeout(task_id))
        
        return loop.call_later(timeout, on_timeout)
    
    async def _handle_timeout(self, task_id: str):
        """Handle task timeout"""
        async with self._lock:
            if task_id not in self._tasks:
                return
            
            info = self._tasks[task_id]
            
            if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return
            
            logger.warning(f"Task '{info.name}' ({task_id}) timed out after {info.timeout}s")
            
            info.status = TaskStatus.TIMEOUT
            info.error = f"Timeout after {info.timeout}s"
            info.completed_at = datetime.now()
            self._stats['total_timeout'] += 1
            
            if info.task and not info.task.done():
                info.task.cancel()
    
    async def register(
        self,
        task: Union[asyncio.Task, Callable[[], Awaitable[Any]]],
        name: str = "unnamed",
        task_id: Optional[str] = None,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        start: bool = True
    ) -> str:
        """
        Register a task with the registry.
        
        Args:
            task: Asyncio Task or coroutine function
            name: Human-readable task name
            task_id: Optional custom task ID
            timeout: Optional timeout in seconds
            metadata: Optional metadata dictionary
            start: Whether to start the task immediately (if coroutine)
        
        Returns:
            Task ID
        """
        async with self._lock:
            # Generate ID
            if task_id is None:
                prefix = f"{name.replace(' ', '_')}_"
                task_id = self._generate_task_id(prefix)
            
            # Check for duplicate
            if task_id in self._tasks:
                raise ValueError(f"Task with ID '{task_id}' already exists")
            
            # Create task if coroutine function
            if not isinstance(task, asyncio.Task):
                if asyncio.iscoroutinefunction(task):
                    coro = task()
                else:
                    coro = task
                
                if start:
                    async_task = asyncio.create_task(coro)
                else:
                    async_task = asyncio.ensure_future(coro)
            else:
                async_task = task
            
            # Create info
            info = TaskInfo(
                task_id=task_id,
                name=name,
                task=async_task,
                timeout=timeout,
                metadata=metadata or {}
            )
            
            # Add callbacks
            async_task.add_done_callback(
                lambda t: asyncio.create_task(self._on_task_done(task_id, t))
            )
            
            # Set timeout handler
            if timeout:
                info._timeout_handler = self._create_timeout_handler(task_id, timeout)
            
            # Store
            self._tasks[task_id] = info
            self._stats['total_registered'] += 1
            
            logger.debug(f"Task registered: {name} ({task_id})")
            
            return task_id
    
    async def _on_task_done(self, task_id: str, task: asyncio.Task):
        """Callback when task completes"""
        async with self._lock:
            if task_id not in self._tasks:
                return
            
            info = self._tasks[task_id]
            
            # Cancel timeout handler
            if info._timeout_handler:
                info._timeout_handler.cancel()
                info._timeout_handler = None
            
            # Skip if already marked as timeout
            if info.status == TaskStatus.TIMEOUT:
                return
            
            info.completed_at = datetime.now()
            
            if task.cancelled():
                info.status = TaskStatus.CANCELLED
                self._stats['total_cancelled'] += 1
                logger.debug(f"Task cancelled: {info.name} ({task_id})")
            else:
                try:
                    exception = task.exception()
                    if exception:
                        info.status = TaskStatus.FAILED
                        info.error = str(exception)
                        self._stats['total_failed'] += 1
                        logger.error(f"Task failed: {info.name} ({task_id}) - {exception}")
                    else:
                        info.status = TaskStatus.COMPLETED
                        self._stats['total_completed'] += 1
                        logger.debug(f"Task completed: {info.name} ({task_id})")
                except asyncio.CancelledError:
                    info.status = TaskStatus.CANCELLED
                    self._stats['total_cancelled'] += 1
                except Exception as e:
                    info.status = TaskStatus.FAILED
                    info.error = str(e)
                    self._stats['total_failed'] += 1
    
    async def start_task(self, task_id: str):
        """Start a registered but not started task"""
        async with self._lock:
            if task_id not in self._tasks:
                raise ValueError(f"Task '{task_id}' not found")
            
            info = self._tasks[task_id]
            
            if info.status != TaskStatus.PENDING:
                raise ValueError(f"Task '{task_id}' already started")
            
            # Create and start task
            # Note: This assumes the task was stored as a coroutine
            # For simplicity, we don't support restarting arbitrary tasks
            
            info.status = TaskStatus.RUNNING
            info.started_at = datetime.now()
    
    async def cancel(self, task_id: str) -> bool:
        """
        Cancel a specific task.
        
        Args:
            task_id: Task ID to cancel
        
        Returns:
            True if cancelled, False if not found or already done
        """
        async with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"Task '{task_id}' not found")
                return False
            
            info = self._tasks[task_id]
            
            if info.task.done():
                logger.debug(f"Task '{info.name}' ({task_id}) already done")
                return False
            
            logger.info(f"Cancelling task: {info.name} ({task_id})")
            return info.task.cancel()
    
    async def cancel_all(self, grace_period: float = 5.0) -> int:
        """
        Cancel all registered tasks.
        
        Args:
            grace_period: Time to wait for tasks to cancel gracefully
        
        Returns:
            Number of tasks cancelled
        """
        async with self._lock:
            tasks_to_cancel = []
            
            for task_id, info in self._tasks.items():
                if info.task and not info.task.done():
                    tasks_to_cancel.append((task_id, info))
            
            if not tasks_to_cancel:
                return 0
            
            logger.info(f"Cancelling {len(tasks_to_cancel)} tasks (grace period: {grace_period}s)")
            
            # Cancel all
            for task_id, info in tasks_to_cancel:
                info.task.cancel()
            
            # Wait for cancellation
            await asyncio.wait(
                [info.task for _, info in tasks_to_cancel],
                timeout=grace_period
            )
            
            return len(tasks_to_cancel)
    
    async def cancel_by_name(self, name: str) -> int:
        """
        Cancel all tasks with a given name.
        
        Args:
            name: Task name to cancel
        
        Returns:
            Number of tasks cancelled
        """
        async with self._lock:
            cancelled = 0
            for task_id, info in list(self._tasks.items()):
                if info.name == name and info.task and not info.task.done():
                    info.task.cancel()
                    cancelled += 1
            return cancelled
    
    async def cancel_by_metadata(self, key: str, value: Any) -> int:
        """
        Cancel tasks matching metadata key-value pair.
        
        Args:
            key: Metadata key
            value: Metadata value
        
        Returns:
            Number of tasks cancelled
        """
        async with self._lock:
            cancelled = 0
            for task_id, info in list(self._tasks.items()):
                if info.metadata.get(key) == value and info.task and not info.task.done():
                    info.task.cancel()
                    cancelled += 1
            return cancelled
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task info by ID"""
        return self._tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get task status by ID"""
        info = self._tasks.get(task_id)
        return info.status if info else None
    
    def get_tasks(self, status: Optional[TaskStatus] = None) -> List[TaskInfo]:
        """
        Get all tasks, optionally filtered by status.
        
        Args:
            status: Filter by status
        
        Returns:
            List of TaskInfo objects
        """
        if status is None:
            return list(self._tasks.values())
        
        return [info for info in self._tasks.values() if info.status == status]
    
    def get_active_tasks(self) -> List[TaskInfo]:
        """Get all active (running/pending) tasks"""
        return [
            info for info in self._tasks.values()
            if info.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
        ]
    
    def get_tasks_by_name(self, name: str) -> List[TaskInfo]:
        """Get tasks by name"""
        return [info for info in self._tasks.values() if info.name == name]
    
    def get_count(self) -> int:
        """Get total number of registered tasks"""
        return len(self._tasks)
    
    def get_active_count(self) -> int:
        """Get number of active tasks"""
        return len(self.get_active_tasks())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        return {
            **self._stats,
            'active_tasks': self.get_active_count(),
            'total_tasks': len(self._tasks),
            'history_size': len(self._history)
        }
    
    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get task history"""
        history = self._history[-limit:] if limit else self._history
        return [info.to_dict() for info in history]
    
    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        Wait for a task to complete and return its result.
        
        Args:
            task_id: Task ID to wait for
            timeout: Optional timeout in seconds
        
        Returns:
            Task result
        
        Raises:
            ValueError: If task not found
            asyncio.TimeoutError: If timeout exceeded
            Exception: If task failed
        """
        info = self._tasks.get(task_id)
        if not info:
            raise ValueError(f"Task '{task_id}' not found")
        
        try:
            return await asyncio.wait_for(info.task, timeout=timeout)
        except asyncio.TimeoutError:
            info.status = TaskStatus.TIMEOUT
            info.error = f"Wait timeout after {timeout}s"
            raise
    
    async def wait_for_all(self, timeout: Optional[float] = None) -> List[Any]:
        """
        Wait for all active tasks to complete.
        
        Args:
            timeout: Optional timeout in seconds
        
        Returns:
            List of results (or exceptions)
        """
        active = self.get_active_tasks()
        if not active:
            return []
        
        tasks = [info.task for info in active]
        
        done, pending = await asyncio.wait(
            tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED
        )
        
        results = []
        for task in done:
            try:
                results.append(task.result())
            except Exception as e:
                results.append(e)
        
        return results
    
    def clear_history(self):
        """Clear task history"""
        self._history.clear()
        logger.debug("Task history cleared")
    
    def reset_stats(self):
        """Reset statistics"""
        self._stats = {
            'total_registered': 0,
            'total_completed': 0,
            'total_failed': 0,
            'total_cancelled': 0,
            'total_timeout': 0
        }
        logger.debug("Task statistics reset")


# =============================================
# Global Task Registry Instance
# =============================================
_task_registry: Optional[TaskRegistry] = None


def get_task_registry() -> TaskRegistry:
    """Get the global task registry instance"""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry()
    return _task_registry


def set_task_registry(registry: TaskRegistry):
    """Set the global task registry instance"""
    global _task_registry
    _task_registry = registry


# =============================================
# Convenience Functions
# =============================================
async def register_task(
    coro: Awaitable[Any],
    name: str = "unnamed",
    timeout: Optional[float] = None,
    **metadata
) -> str:
    """
    Register and start a coroutine as a tracked task.
    
    Args:
        coro: Coroutine to run
        name: Task name
        timeout: Optional timeout
        **metadata: Additional metadata
    
    Returns:
        Task ID
    """
    registry = get_task_registry()
    return await registry.register(coro, name=name, timeout=timeout, metadata=metadata)


async def cancel_task(task_id: str) -> bool:
    """Cancel a tracked task by ID"""
    registry = get_task_registry()
    return await registry.cancel(task_id)


async def cancel_tasks_by_campaign(campaign_id: int) -> int:
    """Cancel all tasks for a specific campaign"""
    registry = get_task_registry()
    return await registry.cancel_by_metadata("campaign_id", campaign_id)


def get_active_task_count() -> int:
    """Get number of active tasks"""
    registry = get_task_registry()
    return registry.get_active_count()


def get_task_info(task_id: str) -> Optional[Dict[str, Any]]:
    """Get task information by ID"""
    registry = get_task_registry()
    info = registry.get_task(task_id)
    return info.to_dict() if info else None


def list_active_tasks() -> List[Dict[str, Any]]:
    """List all active tasks"""
    registry = get_task_registry()
    return [info.to_dict() for info in registry.get_active_tasks()]


# =============================================
# Task Decorator
# =============================================
def tracked_task(name: str = None, timeout: float = None, auto_register: bool = True):
    """
    Decorator to automatically register a coroutine as a tracked task.
    
    Usage:
        @tracked_task(name="my_task", timeout=60)
        async def my_coroutine():
            pass
    """
    def decorator(func):
        task_name = name or func.__name__
        
        async def wrapper(*args, **kwargs):
            if auto_register:
                registry = get_task_registry()
                
                async def wrapped_coro():
                    return await func(*args, **kwargs)
                
                task_id = await registry.register(
                    wrapped_coro,
                    name=task_name,
                    timeout=timeout,
                    metadata={"function": func.__name__, "args": str(args), "kwargs": str(kwargs)}
                )
                
                info = registry.get_task(task_id)
                if info:
                    return await info.task
            else:
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator
