#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели аудита
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Аудит логов (действия пользователей)
- Фильтрации аудита
- Экспорта аудита
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class AuditAction(str, Enum):
    """Действия аудита"""
    # Аутентификация
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    TOTP_ENABLED = "totp_enabled"
    TOTP_DISABLED = "totp_disabled"
    
    # Пользователи
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_ENABLED = "user_enabled"
    USER_DISABLED = "user_disabled"
    ROLE_CHANGED = "role_changed"
    
    # Кампании
    CAMPAIGN_CREATED = "campaign_created"
    CAMPAIGN_UPDATED = "campaign_updated"
    CAMPAIGN_DELETED = "campaign_deleted"
    CAMPAIGN_STARTED = "campaign_started"
    CAMPAIGN_STOPPED = "campaign_stopped"
    CAMPAIGN_PAUSED = "campaign_paused"
    CAMPAIGN_RESUMED = "campaign_resumed"
    CAMPAIGN_CLONED = "campaign_cloned"
    
    # Контакты
    CONTACT_CREATED = "contact_created"
    CONTACT_UPDATED = "contact_updated"
    CONTACT_DELETED = "contact_deleted"
    CONTACT_IMPORTED = "contact_imported"
    CONTACT_EXPORTED = "contact_exported"
    CONTACT_BLACKLISTED = "contact_blacklisted"
    CONTACT_UNBLACKLISTED = "contact_unblacklisted"
    
    # Группы контактов
    GROUP_CREATED = "group_created"
    GROUP_UPDATED = "group_updated"
    GROUP_DELETED = "group_deleted"
    
    # Звонки
    CALL_DELETED = "call_deleted"
    CALL_RECORDING_DELETED = "call_recording_deleted"
    CALL_RECORDING_DOWNLOADED = "call_recording_downloaded"
    
    # Аудиофайлы
    AUDIO_UPLOADED = "audio_uploaded"
    AUDIO_GENERATED = "audio_generated"
    AUDIO_DELETED = "audio_deleted"
    AUDIO_CONVERTED = "audio_converted"
    
    # Чёрный список
    BLACKLIST_ADDED = "blacklist_added"
    BLACKLIST_REMOVED = "blacklist_removed"
    BLACKLIST_IMPORTED = "blacklist_imported"
    BLACKLIST_EXPORTED = "blacklist_exported"
    
    # Настройки
    SETTING_UPDATED = "setting_updated"
    SETTINGS_BULK_UPDATED = "settings_bulk_updated"
    
    # Система
    SYSTEM_ENABLED = "system_enabled"
    SYSTEM_DISABLED = "system_disabled"
    SYSTEM_CONFIG_CHANGED = "system_config_changed"
    SYSTEM_MAINTENANCE_STARTED = "system_maintenance_started"
    SYSTEM_MAINTENANCE_ENDED = "system_maintenance_ended"
    
    # API ключи
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"
    API_KEY_USED = "api_key_used"
    
    # Входящие звонки
    INCOMING_CALL_RECEIVED = "incoming_call_received"
    INCOMING_CALL_DELETED = "incoming_call_deleted"
    TRANSCRIPTION_STARTED = "transcription_started"
    TRANSCRIPTION_COMPLETED = "transcription_completed"
    
    # Webhook
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_FAILED = "webhook_failed"
    
    # Прочее
    VIEW = "view"
    EXPORT = "export"
    DOWNLOAD = "download"
    SEARCH = "search"
    OTHER = "other"


class AuditEntityType(str, Enum):
    """Типы сущностей для аудита"""
    USER = "user"
    CAMPAIGN = "campaign"
    CONTACT = "contact"
    CONTACT_GROUP = "contact_group"
    CALL = "call"
    AUDIO = "audio"
    BLACKLIST = "blacklist"
    SETTING = "setting"
    API_KEY = "api_key"
    INCOMING_CALL = "incoming_call"
    SYSTEM = "system"
    WEBHOOK = "webhook"
    REPORT = "report"
    UNKNOWN = "unknown"


class AuditSeverity(str, Enum):
    """Важность события аудита"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =============================================
# Запись аудита
# =============================================
class AuditLogResponse(TimestampSchema):
    """
    Ответ с записью аудита.
    """
    id: int = Field(..., description="ID записи")
    
    # Пользователь
    user_id: Optional[int] = Field(None, description="ID пользователя")
    username: Optional[str] = Field(None, description="Имя пользователя")
    user_role: Optional[str] = Field(None, description="Роль пользователя")
    
    # Действие
    action: AuditAction = Field(..., description="Действие")
    severity: AuditSeverity = Field(AuditSeverity.INFO, description="Важность")
    
    # Сущность
    entity_type: Optional[AuditEntityType] = Field(None, description="Тип сущности")
    entity_id: Optional[int] = Field(None, description="ID сущности")
    entity_name: Optional[str] = Field(None, description="Имя сущности")
    
    # Детали
    details: Optional[Dict[str, Any]] = Field(None, description="Детали")
    changes: Optional[Dict[str, Any]] = Field(None, description="Изменения (было/стало)")
    
    # Контекст запроса
    ip_address: Optional[str] = Field(None, description="IP адрес")
    user_agent: Optional[str] = Field(None, description="User Agent")
    request_method: Optional[str] = Field(None, description="HTTP метод")
    request_path: Optional[str] = Field(None, description="Путь запроса")
    
    # Корреляция
    correlation_id: Optional[str] = Field(None, description="Correlation ID")
    request_id: Optional[str] = Field(None, description="Request ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    
    # Результат
    status: str = Field("success", description="Статус (success/failed)")
    error_message: Optional[str] = Field(None, description="Сообщение об ошибке")
    
    # Метаданные
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "user_id": 1,
                "username": "admin",
                "user_role": "admin",
                "action": "campaign_started",
                "severity": "info",
                "entity_type": "campaign",
                "entity_id": 42,
                "entity_name": "Тестовая кампания",
                "details": {
                    "campaign_id": 42,
                    "contacts_count": 1000
                },
                "changes": {
                    "status": {"old": "draft", "new": "running"}
                },
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0...",
                "request_method": "POST",
                "request_path": "/api/campaigns/42/start",
                "correlation_id": "abc123def456",
                "request_id": "req_789ghi",
                "status": "success",
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class AuditLogDetailResponse(AuditLogResponse):
    """
    Детальный ответ с записью аудита.
    """
    # Дополнительная информация о пользователе
    user_email: Optional[str] = Field(None, description="Email пользователя")
    user_full_name: Optional[str] = Field(None, description="Полное имя")
    
    # Дополнительная информация о сущности
    entity_details: Optional[Dict[str, Any]] = Field(None, description="Детали сущности")
    
    # Связанные события
    related_events: List[AuditLogResponse] = Field(default_factory=list, description="Связанные события")
    
    # Геолокация (если доступна)
    geo_location: Optional[Dict[str, Any]] = Field(None, description="Геолокация по IP")


class AuditLogListResponse(BaseSchema):
    """
    Ответ со списком записей аудита.
    """
    items: List[AuditLogResponse] = Field(..., description="Записи")
    total: int = Field(..., description="Всего записей")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")
    
    # Сводка
    summary: Dict[str, Any] = Field(default_factory=dict, description="Сводка")


# =============================================
# Фильтры
# =============================================
class AuditLogFilter(BaseSchema):
    """
    Фильтр для аудит логов.
    """
    # Пользователь
    user_id: Optional[int] = Field(None, description="ID пользователя")
    username: Optional[str] = Field(None, description="Имя пользователя")
    user_role: Optional[str] = Field(None, description="Роль")
    
    # Действие
    action: Optional[List[AuditAction]] = Field(None, description="Действия")
    severity: Optional[List[AuditSeverity]] = Field(None, description="Важность")
    
    # Сущность
    entity_type: Optional[List[AuditEntityType]] = Field(None, description="Типы сущностей")
    entity_id: Optional[int] = Field(None, description="ID сущности")
    
    # Статус
    status: Optional[str] = Field(None, description="Статус (success/failed)")
    
    # IP и гео
    ip_address: Optional[str] = Field(None, description="IP адрес")
    
    # Корреляция
    correlation_id: Optional[str] = Field(None, description="Correlation ID")
    request_id: Optional[str] = Field(None, description="Request ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    
    # Даты
    from_date: Optional[date] = Field(None, description="С даты")
    to_date: Optional[date] = Field(None, description="По дату")
    
    # Поиск
    search: Optional[str] = Field(None, description="Поиск по деталям")
    
    # Сортировка
    sort_by: str = Field("created_at", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Статистика аудита
# =============================================
class AuditStatsResponse(BaseSchema):
    """
    Статистика аудита.
    """
    period_days: int = Field(..., description="Период в днях")
    from_date: date = Field(..., description="С даты")
    to_date: date = Field(..., description="По дату")
    
    # Общая статистика
    total_events: int = Field(0, description="Всего событий")
    success_events: int = Field(0, description="Успешных")
    failed_events: int = Field(0, description="С ошибками")
    
    # По важности
    by_severity: Dict[str, int] = Field(default_factory=dict, description="По важности")
    
    # По действиям
    top_actions: List[Dict[str, Any]] = Field(default_factory=list, description="Топ действий")
    
    # По пользователям
    top_users: List[Dict[str, Any]] = Field(default_factory=list, description="Топ пользователей")
    
    # По сущностям
    by_entity_type: Dict[str, int] = Field(default_factory=dict, description="По типам сущностей")
    
    # По IP
    top_ips: List[Dict[str, Any]] = Field(default_factory=list, description="Топ IP адресов")
    
    # По дням
    daily_events: List[Dict[str, Any]] = Field(default_factory=list, description="По дням")
    
    # По часам
    hourly_events: List[Dict[str, Any]] = Field(default_factory=list, description="По часам")


class AuditUserStatsResponse(BaseSchema):
    """
    Статистика аудита по пользователю.
    """
    user_id: int = Field(..., description="ID пользователя")
    username: str = Field(..., description="Имя пользователя")
    full_name: Optional[str] = Field(None, description="Полное имя")
    role: str = Field(..., description="Роль")
    
    # Статистика
    total_actions: int = Field(0, description="Всего действий")
    first_action: Optional[datetime] = Field(None, description="Первое действие")
    last_action: Optional[datetime] = Field(None, description="Последнее действие")
    
    # По действиям
    actions_breakdown: Dict[str, int] = Field(default_factory=dict, description="По действиям")
    
    # Сессии
    total_sessions: int = Field(0, description="Всего сессий")
    avg_session_duration: Optional[float] = Field(None, description="Средняя длительность сессии (мин)")
    
    # IP адреса
    unique_ips: int = Field(0, description="Уникальных IP")
    top_ips: List[Dict[str, Any]] = Field(default_factory=list, description="Топ IP")
    
    # Устройства
    devices: List[Dict[str, Any]] = Field(default_factory=list, description="Устройства")


class AuditEntityStatsResponse(BaseSchema):
    """
    Статистика аудита по сущности.
    """
    entity_type: AuditEntityType = Field(..., description="Тип сущности")
    entity_id: int = Field(..., description="ID сущности")
    entity_name: Optional[str] = Field(None, description="Имя сущности")
    
    # Статистика
    total_events: int = Field(0, description="Всего событий")
    
    # По действиям
    actions_breakdown: Dict[str, int] = Field(default_factory=dict, description="По действиям")
    
    # По пользователям
    users_involved: List[Dict[str, Any]] = Field(default_factory=list, description="Пользователи")
    
    # Временная шкала
    timeline: List[Dict[str, Any]] = Field(default_factory=list, description="Временная шкала")
    
    # Связанные сущности
    related_entities: List[Dict[str, Any]] = Field(default_factory=list, description="Связанные сущности")


# =============================================
# Экспорт аудита
# =============================================
class AuditExportRequest(BaseSchema):
    """
    Запрос на экспорт аудита.
    """
    filter: Optional[AuditLogFilter] = Field(None, description="Фильтр")
    format: str = Field("csv", description="Формат (csv/json/xlsx)")
    
    fields: Optional[List[str]] = Field(None, description="Поля для экспорта")
    
    include_details: bool = Field(True, description="Включать детали")
    include_changes: bool = Field(True, description="Включать изменения")
    
    max_records: int = Field(10000, ge=1, le=100000, description="Максимум записей")


class AuditExportResponse(BaseSchema):
    """
    Ответ на экспорт аудита.
    """
    task_id: str = Field(..., description="ID задачи экспорта")
    status: str = Field("pending", description="Статус")
    estimated_records: int = Field(..., description="Примерное количество записей")
    expires_at: datetime = Field(..., description="Ссылка действительна до")


class AuditExportStatusResponse(BaseSchema):
    """
    Статус задачи экспорта.
    """
    task_id: str = Field(..., description="ID задачи")
    status: str = Field(..., description="Статус (pending/processing/completed/failed)")
    progress: float = Field(0.0, description="Прогресс (%)")
    
    records_processed: int = Field(0, description="Обработано записей")
    
    download_url: Optional[str] = Field(None, description="URL для скачивания")
    error: Optional[str] = Field(None, description="Ошибка")
    
    created_at: datetime = Field(..., description="Создана")
    completed_at: Optional[datetime] = Field(None, description="Завершена")


# =============================================
# Очистка аудита
# =============================================
class AuditCleanupRequest(BaseSchema):
    """
    Запрос на очистку старых аудит логов.
    """
    older_than_days: int = Field(90, ge=30, le=365, description="Старше (дней)")
    severity: Optional[List[AuditSeverity]] = Field(None, description="Важность (только DEBUG/INFO)")
    dry_run: bool = Field(True, description="Только подсчёт")


class AuditCleanupResponse(BaseSchema):
    """
    Ответ на очистку аудита.
    """
    records_to_delete: int = Field(..., description="Записей к удалению")
    deleted: int = Field(0, description="Удалено")
    dry_run: bool = Field(..., description="Тестовый прогон")
    message: str = Field(..., description="Сообщение")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "AuditAction",
    "AuditEntityType",
    "AuditSeverity",
    
    # Записи
    "AuditLogResponse",
    "AuditLogDetailResponse",
    "AuditLogListResponse",
    
    # Фильтры
    "AuditLogFilter",
    
    # Статистика
    "AuditStatsResponse",
    "AuditUserStatsResponse",
    "AuditEntityStatsResponse",
    
    # Экспорт
    "AuditExportRequest",
    "AuditExportResponse",
    "AuditExportStatusResponse",
    
    # Очистка
    "AuditCleanupRequest",
    "AuditCleanupResponse",
]
