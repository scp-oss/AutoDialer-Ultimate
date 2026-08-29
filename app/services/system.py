#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления системой
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Управления состоянием системы (enable/disable)
- Мониторинга здоровья компонентов
- Управления режимами работы (normal/maintenance/degraded)
- Сбора системной статистики
- Управления конфигурацией системы
- Управления логами
"""

import os
import json
import time
import psutil
import platform
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logger import logger, LoggerFactory, LogLevel
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.system import (
    SystemComponentStatus, SystemMode,
    ComponentStatus, HealthCheckResponse,
    SystemStatusResponse, SystemEnableResponse, SystemDisableResponse,
    SystemStatsResponse, ResourceUsageResponse, SystemConfigResponse,
    LivenessResponse, ReadinessResponse
)
from prometheus_client import Gauge, Counter, Info


# =============================================
# Метрики
# =============================================
system_info = Info('autodialer_system', 'System information')
system_uptime = Gauge('autodialer_system_uptime_seconds', 'System uptime in seconds')
system_enabled_gauge = Gauge('autodialer_system_enabled', 'System enabled status')
system_mode_gauge = Gauge('autodialer_system_mode', 'System mode', ['mode'])
memory_usage_gauge = Gauge('autodialer_memory_usage_bytes', 'Memory usage in bytes', ['type'])
cpu_usage_gauge = Gauge('autodialer_cpu_usage_percent', 'CPU usage percent')
disk_usage_gauge = Gauge('autodialer_disk_usage_bytes', 'Disk usage in bytes', ['mount', 'type'])


# =============================================
# Исключения
# =============================================
class SystemError(Exception):
    """Базовое исключение сервиса системы"""
    pass


class SystemAlreadyEnabledError(SystemError):
    """Система уже включена"""
    pass


class SystemAlreadyDisabledError(SystemError):
    """Система уже выключена"""
    pass


class ComponentUnhealthyError(SystemError):
    """Компонент нездоров"""
    pass


# =============================================
# Модели данных
# =============================================
@dataclass
class SystemState:
    """Состояние системы"""
    enabled: bool = True
    mode: SystemMode = SystemMode.NORMAL
    start_time: datetime = field(default_factory=datetime.utcnow)
    last_health_check: Optional[datetime] = None
    maintenance_reason: Optional[str] = None
    degraded_reason: Optional[str] = None


# =============================================
# Сервис системы
# =============================================
class SystemService:
    """
    Сервис управления системой.
    
    Отвечает за:
    - Включение/выключение системы (kill switch)
    - Управление режимами работы
    - Мониторинг здоровья компонентов
    - Сбор системной статистики
    - Управление конфигурацией
    """
    
    def __init__(
        self,
        db_pool: ConnectionPool,
        redis_client: RedisClient,
        dialer_manager=None,
        transcription_service=None
    ):
        self.db_pool = db_pool
        self.redis = redis_client
        self.dialer_manager = dialer_manager
        self.transcription_service = transcription_service
        
        # Состояние системы
        self._state = SystemState()
        self._state_lock = asyncio.Lock()
        
        # Кеш здоровья компонентов
        self._component_health: Dict[str, ComponentStatus] = {}
        self._last_health_check: Optional[datetime] = None
        self._health_check_interval = settings.HEALTH_CHECK_INTERVAL
        
        # Фоновые задачи
        self._health_check_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Информация о системе
        self._system_info = {
            'hostname': platform.node(),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'cpu_count': psutil.cpu_count(),
            'instance_id': os.getenv('INSTANCE_ID', f"{platform.node()}:{os.getpid()}")
        }
        
        # Устанавливаем информацию
        system_info.info({
            'version': settings.VERSION,
            'hostname': self._system_info['hostname'],
            'instance_id': self._system_info['instance_id']
        })
        
        logger.info(f"SystemService инициализирован (instance: {self._system_info['instance_id']})")
    
    # =============================================
    # Инициализация и завершение
    # =============================================
    async def start(self):
        """Запустить фоновые задачи"""
        if self._running:
            return
        
        self._running = True
        
        # Загружаем состояние из Redis
        await self._load_state()
        
        # Запускаем health check
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        # Запускаем сбор метрик
        self._metrics_task = asyncio.create_task(self._metrics_loop())
        
        logger.info("SystemService запущен")
    
    async def stop(self):
        """Остановить фоновые задачи"""
        self._running = False
        
        for task in [self._health_check_task, self._metrics_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("SystemService остановлен")
    
    async def _load_state(self):
        """Загрузить состояние из Redis"""
        try:
            enabled = await self.redis.get(REDIS_KEYS.SYSTEM_ENABLED)
            self._state.enabled = enabled != "false" if enabled else True
            
            mode = await self.redis.get("system_mode")
            if mode:
                self._state.mode = SystemMode(mode)
            
            system_enabled_gauge.set(1 if self._state.enabled else 0)
            system_mode_gauge.labels(mode=self._state.mode.value).set(1)
            
            logger.info(f"Состояние загружено: enabled={self._state.enabled}, mode={self._state.mode.value}")
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")
    
    async def _save_state(self):
        """Сохранить состояние в Redis"""
        try:
            await self.redis.set(REDIS_KEYS.SYSTEM_ENABLED, "true" if self._state.enabled else "false")
            await self.redis.set("system_mode", self._state.mode.value)
            
            system_enabled_gauge.set(1 if self._state.enabled else 0)
            system_mode_gauge.labels(mode=self._state.mode.value).set(1)
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния: {e}")
    
    # =============================================
    # Управление состоянием системы
    # =============================================
    async def enable_system(self, user_id: Optional[int] = None) -> SystemEnableResponse:
        """
        Включить систему.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            SystemEnableResponse
        """
        async with self._state_lock:
            if self._state.enabled:
                raise SystemAlreadyEnabledError("Система уже включена")
            
            # Проверяем здоровье компонентов
            health = await self.health_check()
            if health.status == SystemComponentStatus.UNHEALTHY:
                raise ComponentUnhealthyError(
                    f"Невозможно включить систему: компоненты нездоровы - {health.components}"
                )
            
            self._state.enabled = True
            self._state.mode = SystemMode.NORMAL
            self._state.maintenance_reason = None
            self._state.degraded_reason = None
            
            await self._save_state()
            
            # Включаем дозвон
            if self.dialer_manager:
                self.dialer_manager.running = True
            
            # Логируем
            await self._log_audit(user_id, 'system_enabled')
        
        logger.warning(f"Система включена пользователем {user_id}")
        
        return SystemEnableResponse(
            success=True,
            message="Система включена",
            enabled=True
        )
    
    async def disable_system(
        self,
        user_id: Optional[int] = None,
        reason: Optional[str] = None,
        force: bool = False
    ) -> SystemDisableResponse:
        """
        Выключить систему (kill switch).
        
        Args:
            user_id: ID пользователя
            reason: Причина выключения
            force: Принудительно завершить все звонки
        
        Returns:
            SystemDisableResponse
        """
        async with self._state_lock:
            if not self._state.enabled and not force:
                raise SystemAlreadyDisabledError("Система уже выключена")
            
            self._state.enabled = False
            await self._save_state()
            
            # Выключаем дозвон
            killed_calls = 0
            if self.dialer_manager:
                self.dialer_manager.running = False
                if force:
                    killed_calls = await self.dialer_manager.stop_all_calls()
            
            # Очищаем очередь
            cleared_queue = 0
            if self.redis:
                cleared_queue = await self.redis.clear_dial_queue()
            
            # Логируем
            await self._log_audit(user_id, 'system_disabled', {
                'reason': reason,
                'force': force,
                'killed_calls': killed_calls
            })
        
        logger.warning(f"Система выключена пользователем {user_id}, причина: {reason}, убито звонков: {killed_calls}")
        
        return SystemDisableResponse(
            success=True,
            message="Система выключена",
            enabled=False,
            killed_calls=killed_calls,
            cleared_queue=cleared_queue
        )
    
    async def is_system_enabled(self) -> bool:
        """Проверить, включена ли система"""
        return self._state.enabled
    
    async def set_mode(
        self,
        mode: SystemMode,
        user_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Установить режим работы системы.
        
        Args:
            mode: Режим работы
            user_id: ID пользователя
            reason: Причина
        
        Returns:
            Информация о смене режима
        """
        async with self._state_lock:
            old_mode = self._state.mode
            self._state.mode = mode
            
            if mode == SystemMode.MAINTENANCE:
                self._state.maintenance_reason = reason
            elif mode == SystemMode.DEGRADED:
                self._state.degraded_reason = reason
            else:
                self._state.maintenance_reason = None
                self._state.degraded_reason = None
            
            await self._save_state()
            
            # В режиме обслуживания выключаем дозвон
            if mode == SystemMode.MAINTENANCE and self.dialer_manager:
                self.dialer_manager.running = False
            
            await self._log_audit(user_id, 'system_mode_changed', {
                'old_mode': old_mode.value,
                'new_mode': mode.value,
                'reason': reason
            })
        
        logger.info(f"Режим системы изменён: {old_mode.value} -> {mode.value}")
        
        return {
            "success": True,
            "old_mode": old_mode.value,
            "new_mode": mode.value,
            "reason": reason
        }
    
    async def get_mode(self) -> SystemMode:
        """Получить текущий режим работы"""
        return self._state.mode
    
    # =============================================
    # Health Check
    # =============================================
    async def health_check(self) -> HealthCheckResponse:
        """
        Проверить здоровье системы и всех компонентов.
        
        Returns:
            HealthCheckResponse
        """
        components = {}
        overall_status = SystemComponentStatus.HEALTHY
        
        # Проверка БД
        try:
            start = time.monotonic()
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            latency = (time.monotonic() - start) * 1000
            
            components["database"] = ComponentStatus(
                status=SystemComponentStatus.HEALTHY,
                message="Connected",
                latency_ms=round(latency, 2),
                last_check=datetime.utcnow()
            )
        except Exception as e:
            components["database"] = ComponentStatus(
                status=SystemComponentStatus.UNHEALTHY,
                error=str(e),
                last_check=datetime.utcnow()
            )
            overall_status = SystemComponentStatus.UNHEALTHY
        
        # Проверка Redis
        try:
            start = time.monotonic()
            await self.redis.ping()
            latency = (time.monotonic() - start) * 1000
            
            components["redis"] = ComponentStatus(
                status=SystemComponentStatus.HEALTHY,
                message="Connected",
                latency_ms=round(latency, 2),
                last_check=datetime.utcnow()
            )
        except Exception as e:
            components["redis"] = ComponentStatus(
                status=SystemComponentStatus.UNHEALTHY,
                error=str(e),
                last_check=datetime.utcnow()
            )
            overall_status = SystemComponentStatus.UNHEALTHY
        
        # Проверка AMI
        if self.dialer_manager:
            if self.dialer_manager.connected:
                components["ami"] = ComponentStatus(
                    status=SystemComponentStatus.HEALTHY,
                    message="Connected",
                    last_check=datetime.utcnow()
                )
            else:
                components["ami"] = ComponentStatus(
                    status=SystemComponentStatus.UNHEALTHY,
                    message="Disconnected",
                    last_check=datetime.utcnow()
                )
                if overall_status == SystemComponentStatus.HEALTHY:
                    overall_status = SystemComponentStatus.DEGRADED
        else:
            components["ami"] = ComponentStatus(
                status=SystemComponentStatus.NOT_INITIALIZED,
                last_check=datetime.utcnow()
            )
        
        # Проверка транскрибации
        if self.transcription_service:
            try:
                info = self.transcription_service.get_info()
                if info["engine"] != "none":
                    components["transcription"] = ComponentStatus(
                        status=SystemComponentStatus.HEALTHY,
                        message=f"Engine: {info['engine']}",
                        details=info,
                        last_check=datetime.utcnow()
                    )
                else:
                    components["transcription"] = ComponentStatus(
                        status=SystemComponentStatus.DEGRADED,
                        message="No engine available",
                        last_check=datetime.utcnow()
                    )
            except Exception as e:
                components["transcription"] = ComponentStatus(
                    status=SystemComponentStatus.UNHEALTHY,
                    error=str(e),
                    last_check=datetime.utcnow()
                )
        
        # Сохраняем в кеш
        self._component_health = components
        self._last_health_check = datetime.utcnow()
        self._state.last_health_check = self._last_health_check
        
        # Определяем активные звонки
        active_calls = 0
        max_calls = settings.MAX_CALLS
        if self.dialer_manager:
            active_calls = len(self.dialer_manager.channel_map)
            max_calls = self.dialer_manager.max_calls
        
        # Размер очереди
        queue_size = await self.redis.get_queue_size() if self.redis else 0
        
        uptime = (datetime.utcnow() - self._state.start_time).total_seconds()
        system_uptime.set(uptime)
        
        return HealthCheckResponse(
            status=overall_status,
            version=settings.VERSION,
            timestamp=datetime.utcnow(),
            uptime_seconds=uptime,
            uptime_formatted=self._format_uptime(uptime),
            components={k: v for k, v in components.items()},
            active_calls=active_calls,
            max_calls=max_calls,
            queue_size=queue_size,
            mode=self._state.mode,
            hostname=self._system_info['hostname'],
            instance_id=self._system_info['instance_id']
        )
    
    async def liveness_check(self) -> LivenessResponse:
        """
        Liveness probe (для Kubernetes).
        Проверяет, живо ли приложение.
        """
        return LivenessResponse(alive=True)
    
    async def readiness_check(self) -> ReadinessResponse:
        """
        Readiness probe (для Kubernetes).
        Проверяет, готово ли приложение принимать запросы.
        """
        if not self._state.enabled:
            return ReadinessResponse(ready=False, reason="System is disabled")
        
        if self._state.mode == SystemMode.MAINTENANCE:
            return ReadinessResponse(ready=False, reason="System in maintenance mode")
        
        # Проверяем основные компоненты
        try:
            await self.db_pool.fetchval("SELECT 1")
        except Exception as e:
            return ReadinessResponse(ready=False, reason=f"Database unavailable: {e}")
        
        try:
            await self.redis.ping()
        except Exception as e:
            return ReadinessResponse(ready=False, reason=f"Redis unavailable: {e}")
        
        return ReadinessResponse(ready=True)
    
    async def _health_check_loop(self):
        """Фоновый health check"""
        while self._running:
            await asyncio.sleep(self._health_check_interval)
            
            try:
                await self.health_check()
                
                # Автоматический переход в degraded mode
                if self._state.mode == SystemMode.NORMAL:
                    unhealthy_count = sum(
                        1 for c in self._component_health.values()
                        if c.status == SystemComponentStatus.UNHEALTHY
                    )
                    if unhealthy_count > 0:
                        logger.warning(f"Обнаружены нездоровые компоненты: {unhealthy_count}")
                        # Можно автоматически перевести в degraded mode
                        # await self.set_mode(SystemMode.DEGRADED, reason="Components unhealthy")
                
            except Exception as e:
                logger.error(f"Ошибка health check: {e}")
    
    # =============================================
    # Статус системы
    # =============================================
    async def get_status(self) -> SystemStatusResponse:
        """
        Получить полный статус системы.
        
        Returns:
            SystemStatusResponse
        """
        # Базовый health check
        health = await self.health_check()
        
        # Активные звонки
        active_calls = 0
        max_calls = settings.MAX_CALLS
        current_cps = 0.0
        if self.dialer_manager:
            active_calls = len(self.dialer_manager.channel_map)
            max_calls = self.dialer_manager.max_calls
            current_cps = self.dialer_manager.cps_limiter.rate
        
        # Задачи
        tasks_running = 0
        tasks_pending = 0
        
        # Подключения
        db_connected = health.components.get("database", ComponentStatus(status=SystemComponentStatus.UNKNOWN)).status == SystemComponentStatus.HEALTHY
        redis_connected = health.components.get("redis", ComponentStatus(status=SystemComponentStatus.UNKNOWN)).status == SystemComponentStatus.HEALTHY
        ami_connected = self.dialer_manager.connected if self.dialer_manager else False
        
        # Ресурсы
        resource_usage = await self._get_resource_usage()
        
        return SystemStatusResponse(
            status=health.status,
            version=settings.VERSION,
            timestamp=datetime.utcnow(),
            uptime_seconds=health.uptime_seconds,
            enabled=self._state.enabled,
            mode=self._state.mode,
            active_calls=active_calls,
            max_calls=max_calls,
            queue_size=health.queue_size,
            current_cps=current_cps,
            tasks_running=tasks_running,
            tasks_pending=tasks_pending,
            database_connected=db_connected,
            redis_connected=redis_connected,
            ami_connected=ami_connected,
            components=health.components,
            memory_usage_mb=resource_usage.memory_used_mb,
            memory_usage_percent=resource_usage.memory_percent,
            cpu_usage_percent=resource_usage.cpu_percent,
            hostname=self._system_info['hostname'],
            instance_id=self._system_info['instance_id'],
            environment=settings.ENVIRONMENT
        )
    
    async def get_component_status(self, component: str) -> Optional[ComponentStatus]:
        """Получить статус конкретного компонента"""
        health = await self.health_check()
        return health.components.get(component)
    
    # =============================================
    # Статистика системы
    # =============================================
    async def get_system_stats(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> SystemStatsResponse:
        """
        Получить системную статистику.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            SystemStatsResponse
        """
        async with self.db_pool.acquire() as conn:
            # Базовые условия
            where_conditions = []
            params = []
            param_idx = 1
            
            if from_date:
                where_conditions.append(f"created_at >= ${param_idx}")
                params.append(from_date)
                param_idx += 1
            
            if to_date:
                where_conditions.append(f"created_at <= ${param_idx}")
                params.append(to_date)
                param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Кампании
            campaigns_stats = await conn.fetchrow(f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'running' THEN 1 END) as active,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed
                FROM campaigns
                {where_clause}
            """, *params)
            
            # Контакты
            contacts_stats = await conn.fetchrow(f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                    COUNT(CASE WHEN blacklisted = TRUE THEN 1 END) as blacklisted
                FROM contacts
                WHERE deleted_at IS NULL
            """)
            
            # Звонки
            calls_stats = await conn.fetchrow(f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END) as today,
                    COUNT(CASE WHEN EXTRACT(HOUR FROM created_at) = EXTRACT(HOUR FROM NOW()) THEN 1 END) as this_hour,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status = 'declined' THEN 1 END) as declined,
                    COUNT(CASE WHEN status = 'busy' THEN 1 END) as busy,
                    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) as noanswer,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                    AVG(duration) as avg_duration,
                    COALESCE(SUM(duration), 0) as total_duration
                FROM call_results
                {where_clause}
            """, *params)
            
            # Входящие звонки
            incoming_stats = await conn.fetchrow(f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN call_date::date = CURRENT_DATE THEN 1 END) as today
                FROM incoming_calls
                {where_clause}
            """, *params)
            
            # Аудиофайлы
            audio_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COALESCE(SUM(file_size), 0) as total_size
                FROM audio_files
                WHERE deleted_at IS NULL
            """)
            
            # Пользователи
            users_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active
                FROM users
                WHERE deleted_at IS NULL
            """)
            
            # API ключи
            api_keys_stats = await conn.fetchrow("""
                SELECT COUNT(*) as total FROM api_keys WHERE is_active = TRUE
            """)
        
        total_calls = calls_stats['total'] or 0
        agreed = calls_stats['agreed'] or 0
        answered = agreed + (calls_stats['declined'] or 0)
        
        return SystemStatsResponse(
            from_date=from_date,
            to_date=to_date,
            total_campaigns=campaigns_stats['total'] or 0,
            active_campaigns=campaigns_stats['active'] or 0,
            completed_campaigns=campaigns_stats['completed'] or 0,
            total_contacts=contacts_stats['total'] or 0,
            active_contacts=contacts_stats['active'] or 0,
            blacklisted_contacts=contacts_stats['blacklisted'] or 0,
            total_calls=total_calls,
            calls_today=calls_stats['today'] or 0,
            calls_this_hour=calls_stats['this_hour'] or 0,
            agreed_calls=agreed,
            declined_calls=calls_stats['declined'] or 0,
            busy_calls=calls_stats['busy'] or 0,
            noanswer_calls=calls_stats['noanswer'] or 0,
            failed_calls=calls_stats['failed'] or 0,
            conversion_rate=round(agreed / total_calls * 100, 2) if total_calls > 0 else 0.0,
            answer_rate=round(answered / total_calls * 100, 2) if total_calls > 0 else 0.0,
            avg_call_duration=round(calls_stats['avg_duration'] or 0, 2),
            total_call_duration=calls_stats['total_duration'] or 0,
            incoming_calls_total=incoming_stats['total'] or 0,
            incoming_calls_today=incoming_stats['today'] or 0,
            audio_files_total=audio_stats['total'] or 0,
            audio_files_size_mb=round((audio_stats['total_size'] or 0) / (1024 * 1024), 2),
            users_total=users_stats['total'] or 0,
            users_active=users_stats['active'] or 0,
            api_keys_total=api_keys_stats['total'] or 0,
            api_requests_today=0
        )
    
    async def get_resource_usage(self) -> ResourceUsageResponse:
        """Получить использование системных ресурсов"""
        return await self._get_resource_usage()
    
    async def _get_resource_usage(self) -> ResourceUsageResponse:
        """Внутренний метод получения ресурсов"""
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        
        cpu_usage_gauge.set(cpu_percent)
        
        # Память
        memory = psutil.virtual_memory()
        memory_total_mb = memory.total / (1024 * 1024)
        memory_used_mb = memory.used / (1024 * 1024)
        memory_percent = memory.percent
        
        memory_usage_gauge.labels(type='total').set(memory.total)
        memory_usage_gauge.labels(type='used').set(memory.used)
        memory_usage_gauge.labels(type='available').set(memory.available)
        
        # Диск
        disk = psutil.disk_usage('/')
        disk_total_gb = disk.total / (1024 * 1024 * 1024)
        disk_used_gb = disk.used / (1024 * 1024 * 1024)
        disk_percent = disk.percent
        
        disk_usage_gauge.labels(mount='/', type='total').set(disk.total)
        disk_usage_gauge.labels(mount='/', type='used').set(disk.used)
        disk_usage_gauge.labels(mount='/', type='free').set(disk.free)
        
        # Сеть
        net_io = psutil.net_io_counters()
        network_rx_mb = net_io.bytes_recv / (1024 * 1024)
        network_tx_mb = net_io.bytes_sent / (1024 * 1024)
        
        # База данных
        db_connections = 0
        db_pool_size = 0
        if self.db_pool and self.db_pool.pool:
            db_connections = self.db_pool.pool.get_size()
            db_pool_size = settings.DB_POOL_MAX_SIZE
        
        # Redis
        redis_memory_mb = 0
        redis_keys = 0
        if self.redis:
            try:
                info = await self.redis.client.info('memory')
                redis_memory_mb = info.get('used_memory', 0) / (1024 * 1024)
                redis_keys = info.get('keys', 0) if 'keys' in info else 0
            except:
                pass
        
        return ResourceUsageResponse(
            timestamp=datetime.utcnow(),
            cpu_percent=cpu_percent,
            cpu_count=cpu_count,
            memory_total_mb=round(memory_total_mb, 2),
            memory_used_mb=round(memory_used_mb, 2),
            memory_percent=memory_percent,
            disk_total_gb=round(disk_total_gb, 2),
            disk_used_gb=round(disk_used_gb, 2),
            disk_percent=disk_percent,
            network_rx_mb=round(network_rx_mb, 2),
            network_tx_mb=round(network_tx_mb, 2),
            db_connections=db_connections,
            db_pool_size=db_pool_size,
            redis_memory_mb=round(redis_memory_mb, 2),
            redis_keys=redis_keys
        )
    
    async def _metrics_loop(self):
        """Фоновый сбор метрик"""
        while self._running:
            await asyncio.sleep(30)
            
            try:
                # Обновляем метрики ресурсов
                await self._get_resource_usage()
                
                # Обновляем uptime
                uptime = (datetime.utcnow() - self._state.start_time).total_seconds()
                system_uptime.set(uptime)
                
                # Обновляем статус системы
                system_enabled_gauge.set(1 if self._state.enabled else 0)
                
            except Exception as e:
                logger.error(f"Ошибка сбора метрик: {e}")
    
    # =============================================
    # Конфигурация системы
    # =============================================
    async def get_config(self) -> SystemConfigResponse:
        """
        Получить конфигурацию системы (только для чтения).
        
        Returns:
            SystemConfigResponse
        """
        return SystemConfigResponse(
            version=settings.VERSION,
            environment=settings.ENVIRONMENT,
            debug=settings.DEBUG,
            max_calls=settings.MAX_CALLS,
            default_cps=settings.DEFAULT_CPS,
            call_timeout=settings.CALL_TIMEOUT,
            max_retries=settings.MAX_RETRIES,
            database_host=settings.DB_HOST,
            database_name=settings.DB_NAME,
            database_pool_size=settings.DB_POOL_MAX_SIZE,
            redis_host=settings.REDIS_HOST,
            redis_sentinel_enabled=settings.REDIS_SENTINEL_ENABLED,
            ami_host=settings.AMI_HOST,
            freepbx_extension=settings.FREEPBX_EXTENSION,
            transcription_enabled=settings.TRANSCRIPTION_ENABLED,
            transcription_engine=settings.TRANSCRIPTION_ENGINE or "auto",
            tts_enabled=settings.TTS_ENABLED,
            tts_engine=settings.TTS_ENGINE,
            log_level=settings.LOG_LEVEL,
            log_format=settings.LOG_FORMAT,
            metrics_enabled=settings.METRICS_ENABLED,
            cors_origins=settings.CORS_ORIGINS
        )
    
    # =============================================
    # Управление логами
    # =============================================
    async def get_log_level(self) -> str:
        """Получить текущий уровень логирования"""
        return settings.LOG_LEVEL
    
    async def set_log_level(self, level: LogLevel, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Установить уровень логирования.
        
        Args:
            level: Новый уровень
            user_id: ID пользователя
        
        Returns:
            Результат операции
        """
        old_level = settings.LOG_LEVEL
        
        # Обновляем настройки
        LoggerFactory.configure(level=level.value)
        
        # Сохраняем в БД
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_by)
                VALUES ('LOG_LEVEL', $1, $2)
                ON CONFLICT (key) DO UPDATE SET 
                    value = EXCLUDED.value,
                    updated_at = NOW(),
                    updated_by = EXCLUDED.updated_by
            """, level.value, user_id)
        
        await self._log_audit(user_id, 'log_level_changed', {
            'old_level': old_level,
            'new_level': level.value
        })
        
        logger.info(f"Уровень логирования изменён: {old_level} -> {level.value}")
        
        return {
            "success": True,
            "old_level": old_level,
            "new_level": level.value
        }
    
    async def restart_workers(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        "Перезагрузка сервисов" из веб-интерфейса (кнопка в модалке после
        сохранения настройки с requires_restart=True) - у settings с
        on_change (dialer.max_calls и т.п.) обновляется только ТОТ ОДИН
        воркер, который обработал конкретный HTTP PUT /settings/{key},
        остальные продолжают работать со старым значением в памяти до
        перезапуска.

        Раньше здесь слался SIGHUP gunicorn-мастеру (его штатный сигнал
        "мягкой перезагрузки" воркеров, без systemctl/sudo) - но
        подтверждено живьём, что это ненадёжно именно для этого
        приложения: если в момент SIGHUP в фоновом потоке шла
        транскрибация Whisper (self.transcription_service использует
        loop.run_in_executor - CPU-задача в ThreadPoolExecutor), процесс
        не мог полноценно завершиться - Python по умолчанию блокирует
        выход интерпретатора, пока не отработают все потоки пула. Старый
        воркер уже прошёл lifespan-shutdown (БД/Redis отключены), но сам
        процесс завис на многие минуты, продолжая при этом формально
        значиться в CGroup и получать новые запросы - "База данных не
        инициализирована" на каждый из них. Восстановилось только после
        полного systemctl restart, который жёстко убивает всё по
        таймауту сервиса независимо от зависших потоков.

        Теперь просит именно systemctl restart - через ограниченное sudo
        правило (см. scripts/02_asterisk_install.sh /
        README-инструкцию), а не пытается справиться сам через сигналы.
        """
        import subprocess

        logger.info("Перезагрузка сервиса autodialer (systemd-run --no-block systemctl restart)")

        await self._log_audit(user_id, 'workers_restart_requested', {})

        # НЕ просто "sudo systemctl restart autodialer" напрямую - этот
        # самый Python-процесс САМ является частью cgroup сервиса
        # autodialer, который мы просим перезапустить. Когда systemd
        # начинает его останавливать, он убивает ВСЕ процессы в этой
        # cgroup, включая наш воркер и, вместе с ним, ещё не завершившийся
        # дочерний sudo/systemctl - подтверждено живьём (returncode -15,
        # то есть сам процесс убит SIGTERM'ом раньше, чем успел
        # доработать). "Рубим сук, на котором сидим".
        #
        # systemd-run --no-block запускает systemctl restart как ОТДЕЛЬНЫЙ
        # transient-юнит вне cgroup текущего сервиса и не ждёт его
        # завершения - возвращается почти мгновенно, до того, как вообще
        # начнётся остановка autodialer.service, и сам restart-юнит потом
        # переживает смерть воркера, который его запустил.
        result = subprocess.run(
            [
                "/usr/bin/sudo", "-n",
                "/usr/bin/systemd-run", "--no-block",
                "/usr/bin/systemctl", "restart", "autodialer"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise SystemError(
                f"systemctl restart не удался (код {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip() or 'нет вывода'}"
            )

        return {
            "success": True,
            "message": "Отправлен сигнал перезагрузки воркерам"
        }

    # =============================================
    # Вспомогательные методы
    # =============================================
    def _format_uptime(self, seconds: float) -> str:
        """Форматирование uptime"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}д")
        if hours > 0 or days > 0:
            parts.append(f"{hours}ч")
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(f"{minutes}м")
        parts.append(f"{secs}с")
        
        return " ".join(parts)
    
    async def _log_audit(
        self,
        user_id: Optional[int],
        action: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Записать аудит"""
        if not self.db_pool:
            return

        # См. подробный комментарий в campaign.py::_log_audit() - тот же
        # фикс: снимок username/role на момент действия + IP/UA/correlation
        # из контекста запроса вместо вечного NULL.
        from app.core.logger import get_ip_address, get_user_agent, get_correlation_id, get_request_id

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log (
                        user_id, username, user_role, action, entity_type, details,
                        ip_address, user_agent, correlation_id, request_id
                    ) VALUES (
                        $1,
                        (SELECT username FROM users WHERE id = $1),
                        (SELECT role FROM users WHERE id = $1),
                        $2, $3, $4, $5, $6, $7, $8
                    )
                """, user_id, action, 'system', json.dumps(details) if details else None,
                     get_ip_address(), get_user_agent(), get_correlation_id(), get_request_id())
        except Exception as e:
            logger.error(f"Ошибка записи аудита: {e}")
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        await self.stop()
        logger.info("SystemService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_system_service: Optional[SystemService] = None


def get_system_service() -> SystemService:
    """Получить глобальный экземпляр SystemService"""
    global _system_service
    if _system_service is None:
        raise RuntimeError("SystemService не инициализирован")
    return _system_service


def set_system_service(service: SystemService) -> None:
    """Установить глобальный экземпляр SystemService"""
    global _system_service
    _system_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "SystemService",
    "SystemError",
    "SystemAlreadyEnabledError",
    "SystemAlreadyDisabledError",
    "ComponentUnhealthyError",
    "SystemState",
    "get_system_service",
    "set_system_service",
]
