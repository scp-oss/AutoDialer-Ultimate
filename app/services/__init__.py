#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервисы бизнес-логики
AutoDialer Ultimate v3.0.0

Центральный модуль, экспортирующий все сервисы приложения:
- DialerService (управление дозвоном)
- CampaignService (управление кампаниями)
- ContactService (управление контактами)
- CallService (управление звонками)
- AudioService (управление аудиофайлами и TTS)
- TranscriptionService (транскрибация)
- SystemService (управление системой)
- BlacklistService (чёрный список)
- UserService (управление пользователями)
- SettingsService (управление настройками)
- AuditService (аудит)
- StatsService (статистика)
- IncomingCallService (входящие звонки)

ИСПОЛЬЗОВАНИЕ:
    from app.services import (
        CampaignService, ContactService, DialerService,
        get_campaign_service, get_contact_service
    )
"""

from typing import Optional, Dict, Any
from app.core.logger import logger


# =============================================
# Сервис дозвона (Dialer)
# =============================================
from app.services.dialer import (
    DialerService,
    DialerManager,
    CallState,
    init_dialer,
    close_dialer,
    get_dialer_service,
    get_dialer_manager,
)


# =============================================
# Сервис кампаний
# =============================================
from app.services.campaign import (
    CampaignService,
    CampaignError,
    get_campaign_service,
)


# =============================================
# Сервис контактов
# =============================================
from app.services.contact import (
    ContactService,
    ContactGroupService,
    ContactError,
    get_contact_service,
    get_contact_group_service,
)


# =============================================
# Сервис звонков
# =============================================
from app.services.call import (
    CallService,
    CallError,
    get_call_service,
)


# =============================================
# Сервис аудио и TTS
# =============================================
from app.services.audio import (
    AudioService,
    TTSService,
    AudioError,
    get_audio_service,
    get_tts_service,
)


# =============================================
# Сервис транскрибации
# =============================================
from app.services.transcription import (
    TranscriptionService,
    TranscriptionEngine,
    TranscriptionError,
    get_transcription_service,
    init_transcription_service,
)


# =============================================
# Сервис системы
# =============================================
from app.services.system import (
    SystemService,
    SystemError,
    get_system_service,
)


# =============================================
# Сервис чёрного списка
# =============================================
from app.services.blacklist import (
    BlacklistService,
    BlacklistError,
    get_blacklist_service,
)


# =============================================
# Сервис пользователей
# =============================================
from app.services.user import (
    UserService,
    AuthService,
    UserError,
    get_user_service,
    get_auth_service,
)


# =============================================
# Сервис настроек
# =============================================
from app.services.settings import (
    SettingsService,
    SettingsError,
    get_settings_service,
)


# =============================================
# Сервис аудита
# =============================================
from app.services.audit import (
    AuditService,
    AuditError,
    get_audit_service,
)


# =============================================
# Сервис статистики
# =============================================
from app.services.stats import (
    StatsService,
    StatsError,
    get_stats_service,
)


# =============================================
# Сервис входящих звонков
# =============================================
from app.services.incoming import (
    IncomingCallService,
    IncomingCallError,
    get_incoming_call_service,
)


# =============================================
# Сервис WebSocket
# =============================================
from app.services.websocket import (
    WebSocketService,
    WebSocketError,
    get_websocket_service,
)


# =============================================
# Сервис уведомлений
# =============================================
from app.services.notification import (
    NotificationService,
    NotificationError,
    get_notification_service,
)


# =============================================
# Реестр сервисов (Service Locator)
# =============================================
class ServiceRegistry:
    """
    Реестр сервисов (Service Locator pattern).
    
    Позволяет централизованно управлять всеми сервисами приложения.
    
    Использование:
        registry = ServiceRegistry()
        registry.register("campaign", CampaignService(db_pool, redis_client))
        
        campaign_service = registry.get("campaign")
    """
    
    _instance: Optional['ServiceRegistry'] = None
    _services: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._services = {}
        return cls._instance
    
    def register(self, name: str, service: Any) -> None:
        """Зарегистрировать сервис"""
        self._services[name] = service
        logger.debug(f"Сервис зарегистрирован: {name}")
    
    def get(self, name: str) -> Optional[Any]:
        """Получить сервис по имени"""
        return self._services.get(name)
    
    def get_or_raise(self, name: str) -> Any:
        """Получить сервис или выбросить исключение"""
        service = self._services.get(name)
        if service is None:
            raise ValueError(f"Сервис '{name}' не зарегистрирован")
        return service
    
    def unregister(self, name: str) -> None:
        """Удалить сервис из реестра"""
        if name in self._services:
            del self._services[name]
            logger.debug(f"Сервис удалён: {name}")
    
    def list_services(self) -> list:
        """Список зарегистрированных сервисов"""
        return list(self._services.keys())
    
    def clear(self) -> None:
        """Очистить реестр"""
        self._services.clear()
        logger.debug("Реестр сервисов очищен")
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья всех сервисов"""
        results = {}
        
        for name, service in self._services.items():
            if hasattr(service, 'health_check'):
                try:
                    results[name] = await service.health_check()
                except Exception as e:
                    results[name] = {"status": "unhealthy", "error": str(e)}
            else:
                results[name] = {"status": "unknown"}
        
        return results
    
    async def shutdown_all(self) -> None:
        """Корректное завершение всех сервисов"""
        for name, service in self._services.items():
            if hasattr(service, 'shutdown'):
                try:
                    await service.shutdown()
                    logger.debug(f"Сервис остановлен: {name}")
                except Exception as e:
                    logger.error(f"Ошибка при остановке сервиса {name}: {e}")


# =============================================
# Глобальный реестр сервисов
# =============================================
service_registry = ServiceRegistry()


# =============================================
# Инициализация всех сервисов
# =============================================
async def init_services(
    db_pool,
    redis_client,
    dialer_manager=None,
    transcription_service=None
) -> ServiceRegistry:
    """
    Инициализировать все сервисы приложения.
    
    Args:
        db_pool: Пул соединений с БД
        redis_client: Клиент Redis
        dialer_manager: Менеджер дозвона (опционально)
        transcription_service: Сервис транскрибации (опционально)
    
    Returns:
        ServiceRegistry с зарегистрированными сервисами
    """
    logger.info("Инициализация сервисов...")
    
    # Базовые сервисы
    service_registry.register("system", SystemService(db_pool, redis_client))
    service_registry.register("settings", SettingsService(db_pool, redis_client))
    
    # Сервисы пользователей и аутентификации
    service_registry.register("user", UserService(db_pool, redis_client))
    service_registry.register("auth", AuthService(db_pool, redis_client))
    
    # Сервисы кампаний и контактов
    service_registry.register("campaign", CampaignService(db_pool, redis_client, dialer_manager))
    service_registry.register("contact", ContactService(db_pool, redis_client))
    service_registry.register("contact_group", ContactGroupService(db_pool, redis_client))
    
    # Сервисы звонков
    service_registry.register("call", CallService(db_pool, redis_client))
    
    # Сервисы аудио и TTS
    service_registry.register("audio", AudioService(db_pool, redis_client))
    service_registry.register("tts", TTSService(db_pool, redis_client))
    
    # Сервис чёрного списка
    service_registry.register("blacklist", BlacklistService(db_pool, redis_client))
    
    # Сервис входящих звонков
    service_registry.register(
        "incoming_call",
        IncomingCallService(db_pool, redis_client, transcription_service)
    )
    
    # Сервисы аудита и статистики
    service_registry.register("audit", AuditService(db_pool))
    service_registry.register("stats", StatsService(db_pool, redis_client))
    
    # Сервисы WebSocket и уведомлений
    service_registry.register("websocket", WebSocketService(redis_client))
    service_registry.register("notification", NotificationService(db_pool, redis_client))
    
    # Если есть dialer_manager, регистрируем DialerService
    if dialer_manager:
        service_registry.register("dialer", DialerService(dialer_manager))
    
    logger.info(f"Инициализировано {len(service_registry.list_services())} сервисов")
    
    return service_registry


async def shutdown_services() -> None:
    """Корректно завершить все сервисы"""
    logger.info("Завершение сервисов...")
    await service_registry.shutdown_all()
    service_registry.clear()
    logger.info("Все сервисы остановлены")


# =============================================
# Удобные функции для получения сервисов
# =============================================
def get_service(name: str) -> Any:
    """Получить сервис по имени"""
    return service_registry.get_or_raise(name)


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Реестр
    "ServiceRegistry",
    "service_registry",
    "init_services",
    "shutdown_services",
    "get_service",
    
    # Dialer
    "DialerService",
    "DialerManager",
    "CallState",
    "init_dialer",
    "close_dialer",
    "get_dialer_service",
    "get_dialer_manager",
    
    # Campaign
    "CampaignService",
    "CampaignError",
    "get_campaign_service",
    
    # Contact
    "ContactService",
    "ContactGroupService",
    "ContactError",
    "get_contact_service",
    "get_contact_group_service",
    
    # Call
    "CallService",
    "CallError",
    "get_call_service",
    
    # Audio & TTS
    "AudioService",
    "TTSService",
    "AudioError",
    "get_audio_service",
    "get_tts_service",
    
    # Transcription
    "TranscriptionService",
    "TranscriptionEngine",
    "TranscriptionError",
    "get_transcription_service",
    "init_transcription_service",
    
    # System
    "SystemService",
    "SystemError",
    "get_system_service",
    
    # Blacklist
    "BlacklistService",
    "BlacklistError",
    "get_blacklist_service",
    
    # User & Auth
    "UserService",
    "AuthService",
    "UserError",
    "get_user_service",
    "get_auth_service",
    
    # Settings
    "SettingsService",
    "SettingsError",
    "get_settings_service",
    
    # Audit
    "AuditService",
    "AuditError",
    "get_audit_service",
    
    # Stats
    "StatsService",
    "StatsError",
    "get_stats_service",
    
    # Incoming Call
    "IncomingCallService",
    "IncomingCallError",
    "get_incoming_call_service",
    
    # WebSocket
    "WebSocketService",
    "WebSocketError",
    "get_websocket_service",
    
    # Notification
    "NotificationService",
    "NotificationError",
    "get_notification_service",
]
