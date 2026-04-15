import asyncio
from typing import Dict
from logger import logger

class TaskRegistry:
    def __init__(self):
        self.tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
    
    async def register(self, task_id: str, task: asyncio.Task):
        async with self._lock:
            self.tasks[task_id] = task
            logger.debug(f"Registered task: {task_id}")
    
    async def cancel(self, task_id: str):
        async with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].cancel()
                del self.tasks[task_id]
                logger.info(f"Cancelled task: {task_id}")
    
    async def cancel_all(self):
        async with self._lock:
            for task_id, task in self.tasks.items():
                task.cancel()
                logger.info(f"Cancelled task: {task_id}")
            self.tasks.clear()
    
    def get_count(self) -> int:
        return len(self.tasks)
