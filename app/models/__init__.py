#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели данных (Pydantic схемы)
AutoDialer Ultimate v3.0.0

Центральный модуль, экспортирующий все Pydantic схемы для:
- Запросов/ответов API
- Валидации данных
- Сериализации/десериализации

ИСПОЛЬЗОВАНИЕ:
    from app.models import (
        CampaignCreate, CampaignResponse,
        ContactCreate, ContactResponse,
        UserCreate, UserResponse,
        PaginatedResponse, SuccessResponse
    )
"""

# =============================================
# Базовые модели
# =============================================
from app.models.common import (
    # Базовые классы
    BaseSchema,
    BaseResponse,
    TimestampSchema,
    
    # Ответы API
    SuccessResponse,
    ErrorResponse,
    PaginatedResponse,
    PaginationParams,
    
    # Статусы
    StatusResponse,
    HealthCheckResponse,
    
    # Утилиты
    model_to_dict,
    dict_to_model,
    parse_json_field,
)

# =============================================
# Модели аутентификации
# =============================================
from app.models.auth import (
    # Запросы
    LoginRequest,
    RefreshTokenRequest,
    ChangePasswordRequest,
    ResetPasswordRequest,
    ForgotPasswordRequest,
    
    # Ответы
    LoginResponse,
    TokenResponse,
    RefreshTokenResponse,
    LogoutResponse,
    
    # 2FA
    TOTPSetupResponse,
    TOTPVerifyRequest,
    TOTPVerifyResponse,
)

# =============================================
# Модели пользователей
# =============================================
from app.models.user import (
    # Запросы
    UserCreateRequest,
    UserUpdateRequest,
    UserProfileUpdateRequest,
    
    # Ответы
    UserResponse,
    UserProfileResponse,
    UserListResponse,
    
    # Роли и разрешения
    UserRole,
    Permission,
    ROLE_PERMISSIONS,
)

# =============================================
# Модели кампаний
# =============================================
from app.models.campaign import (
    # Enums
    CampaignStatus,
    ScheduleType,
    
    # Запросы
    CampaignCreateRequest,
    CampaignUpdateRequest,
    CampaignScheduleRequest,
    
    # Стратегия повторных звонков
    RetryStrategySchema,
    
    # Ответы
    CampaignResponse,
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignStatsResponse,
    CampaignProgressResponse,
    
    # Расписание
    CampaignScheduleResponse,
)

# =============================================
# Модели контактов
# =============================================
from app.models.contact import (
    # Enums
    ContactStatus,
    
    # Запросы
    ContactCreateRequest,
    ContactUpdateRequest,
    ContactBulkImportRequest,
    
    # Ответы
    ContactResponse,
    ContactDetailResponse,
    ContactListResponse,
    ContactBulkImportResponse,
    
    # Группы контактов
    ContactGroupCreateRequest,
    ContactGroupUpdateRequest,
    ContactGroupResponse,
    ContactGroupListResponse,
)

# =============================================
# Модели звонков
# =============================================
from app.models.call import (
    # Enums
    CallResultStatus,
    CallDirection,
    HangupCause,
    
    # Запросы
    CallResultCreateRequest,
    CallHistoryFilterRequest,
    
    # Ответы
    CallResultResponse,
    CallDetailResponse,
    CallHistoryResponse,
    CallListResponse,
    
    # Статистика
    CallStatsResponse,
    DailyCallStatsResponse,
)

# =============================================
# Модели аудиофайлов
# =============================================
from app.models.audio import (
    # Enums
    AudioFormat,
    AudioStatus,
    
    # Запросы
    AudioGenerateRequest,
    AudioUploadRequest,
    AudioUpdateRequest,
    
    # Ответы
    AudioResponse,
    AudioDetailResponse,
    AudioListResponse,
    AudioGenerateResponse,
    
    # TTS
    TTSVoice,
    TTSGenerateRequest,
)

# =============================================
# Модели чёрного списка
# =============================================
from app.models.blacklist import (
    # Запросы
    BlacklistAddRequest,
    BlacklistCheckRequest,
    
    # Ответы
    BlacklistResponse,
    BlacklistListResponse,
    BlacklistCheckResponse,
)

# =============================================
# Модели входящих звонков
# =============================================
from app.models.incoming import (
    # Enums
    TranscriptionStatus,
    
    # Запросы
    IncomingCallWebhookRequest,
    IncomingCallUpdateRequest,
    
    # Ответы
    IncomingCallResponse,
    IncomingCallDetailResponse,
    IncomingCallListResponse,
    IncomingCallStatsResponse,
)

# =============================================
# Модели системы
# =============================================
from app.models.system import (
    # Статус системы
    SystemStatusResponse,
    SystemEnableResponse,
    SystemDisableResponse,
    ComponentStatus,
    
    # Статистика
    SystemStatsResponse,
    
    # WebSocket
    WebSocketMessage,
    LiveCallEvent,
    CampaignProgressEvent,
)

# =============================================
# Модели настроек
# =============================================
from app.models.settings import (
    # Запросы
    SettingUpdateRequest,
    SettingsBulkUpdateRequest,
    
    # Ответы
    SettingResponse,
    SettingsListResponse,
    
    # Категории
    SettingCategory,
)

# =============================================
# Модели аудита
# =============================================
from app.models.audit import (
    # Фильтры
    AuditLogFilter,
    
    # Ответы
    AuditLogResponse,
    AuditLogListResponse,
    
    # Действия
    AuditAction,
)

# =============================================
# Модели API токенов
# =============================================
from app.models.api_token import (
    # Запросы
    ApiTokenCreateRequest,
    
    # Ответы
    ApiTokenResponse,
    ApiTokenListItem,
    ApiTokenListResponse,
)

# =============================================
# Модели статистики
# =============================================
from app.models.stats import (
    # Системная статистика
    SystemStats,
    
    # Статистика по кампаниям
    CampaignStatsSummary,
    
    # Дневная статистика
    DailyStats,
    
    # Полная статистика
    FullStatsResponse,
)

# =============================================
# Модели очередей и задач
# =============================================
from app.models.task import (
    # Enums
    TaskStatus,
    TaskPriority,
    
    # Ответы
    TaskResponse,
    TaskListResponse,
    TaskStatsResponse,
)

# =============================================
# Типы для удобства
# =============================================
from typing import Union, TypeVar, Generic, Optional, List, Dict, Any

# Дженерик для пагинированных ответов
T = TypeVar('T')

class PaginatedResponseOf(Generic[T], PaginatedResponse):
    """Типизированный пагинированный ответ"""
    items: List[T]


# =============================================
# Ре-экспорт для удобства
# =============================================
__all__ = [
    # Базовые
    "BaseSchema",
    "BaseResponse",
    "TimestampSchema",
    "SuccessResponse",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationParams",
    "StatusResponse",
    "HealthCheckResponse",
    "model_to_dict",
    "dict_to_model",
    "parse_json_field",
    
    # Аутентификация
    "LoginRequest",
    "RefreshTokenRequest",
    "ChangePasswordRequest",
    "ResetPasswordRequest",
    "ForgotPasswordRequest",
    "LoginResponse",
    "TokenResponse",
    "RefreshTokenResponse",
    "LogoutResponse",
    "TOTPSetupResponse",
    "TOTPVerifyRequest",
    "TOTPVerifyResponse",
    
    # Пользователи
    "UserCreateRequest",
    "UserUpdateRequest",
    "UserProfileUpdateRequest",
    "UserResponse",
    "UserProfileResponse",
    "UserListResponse",
    "UserRole",
    "Permission",
    "ROLE_PERMISSIONS",
    
    # Кампании
    "CampaignStatus",
    "ScheduleType",
    "CampaignCreateRequest",
    "CampaignUpdateRequest",
    "CampaignScheduleRequest",
    "RetryStrategySchema",
    "CampaignResponse",
    "CampaignDetailResponse",
    "CampaignListResponse",
    "CampaignStatsResponse",
    "CampaignProgressResponse",
    "CampaignScheduleResponse",
    
    # Контакты
    "ContactStatus",
    "ContactCreateRequest",
    "ContactUpdateRequest",
    "ContactBulkImportRequest",
    "ContactResponse",
    "ContactDetailResponse",
    "ContactListResponse",
    "ContactBulkImportResponse",
    "ContactGroupCreateRequest",
    "ContactGroupUpdateRequest",
    "ContactGroupResponse",
    "ContactGroupListResponse",
    
    # Звонки
    "CallResultStatus",
    "CallDirection",
    "HangupCause",
    "CallResultCreateRequest",
    "CallHistoryFilterRequest",
    "CallResultResponse",
    "CallDetailResponse",
    "CallHistoryResponse",
    "CallListResponse",
    "CallStatsResponse",
    "DailyCallStatsResponse",
    
    # Аудио
    "AudioFormat",
    "AudioStatus",
    "AudioGenerateRequest",
    "AudioUploadRequest",
    "AudioUpdateRequest",
    "AudioResponse",
    "AudioDetailResponse",
    "AudioListResponse",
    "AudioGenerateResponse",
    "TTSVoice",
    "TTSGenerateRequest",
    
    # Чёрный список
    "BlacklistAddRequest",
    "BlacklistCheckRequest",
    "BlacklistResponse",
    "BlacklistListResponse",
    "BlacklistCheckResponse",
    
    # Входящие звонки
    "TranscriptionStatus",
    "IncomingCallWebhookRequest",
    "IncomingCallUpdateRequest",
    "IncomingCallResponse",
    "IncomingCallDetailResponse",
    "IncomingCallListResponse",
    "IncomingCallStatsResponse",
    
    # Система
    "SystemStatusResponse",
    "SystemEnableResponse",
    "SystemDisableResponse",
    "ComponentStatus",
    "SystemStatsResponse",
    "WebSocketMessage",
    "LiveCallEvent",
    "CampaignProgressEvent",
    
    # Настройки
    "SettingUpdateRequest",
    "SettingsBulkUpdateRequest",
    "SettingResponse",
    "SettingsListResponse",
    "SettingCategory",
    
    # Аудит
    "AuditLogFilter",
    "AuditLogResponse",
    "AuditLogListResponse",
    "AuditAction",
    
    # API токены
    "ApiTokenCreateRequest",
    "ApiTokenResponse",
    "ApiTokenListItem",
    "ApiTokenListResponse",
    
    # Статистика
    "SystemStats",
    "CampaignStatsSummary",
    "DailyStats",
    "FullStatsResponse",
    
    # Задачи
    "TaskStatus",
    "TaskPriority",
    "TaskResponse",
    "TaskListResponse",
    "TaskStatsResponse",
    
    # Дженерики
    "PaginatedResponseOf",
]


# =============================================
# Функция для создания ответа с пагинацией
# =============================================
def create_paginated_response(
    items: List[Any],
    total: int,
    page: int,
    page_size: int
) -> PaginatedResponse:
    """
    Создать пагинированный ответ.
    
    Args:
        items: Список элементов
        total: Общее количество
        page: Текущая страница
        page_size: Размер страницы
    
    Returns:
        PaginatedResponse
    """
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size
    )


# =============================================
# Функция для создания успешного ответа
# =============================================
def create_success_response(
    message: str,
    data: Optional[Any] = None
) -> SuccessResponse:
    """
    Создать успешный ответ.
    
    Args:
        message: Сообщение
        data: Данные (опционально)
    
    Returns:
        SuccessResponse
    """
    return SuccessResponse(
        success=True,
        message=message,
        data=data
    )


# =============================================
# Функция для создания ответа с ошибкой
# =============================================
def create_error_response(
    error: str,
    detail: Optional[str] = None,
    code: Optional[str] = None
) -> ErrorResponse:
    """
    Создать ответ с ошибкой.
    
    Args:
        error: Краткое описание ошибки
        detail: Подробности
        code: Код ошибки
    
    Returns:
        ErrorResponse
    """
    return ErrorResponse(
        error=error,
        detail=detail,
        code=code
    )


# =============================================
# Валидаторы
# =============================================
def validate_phone(phone: str) -> str:
    """
    Нормализовать и проверить номер телефона.
    """
    import re
    
    # Удаляем все не-цифры
    phone = re.sub(r'[^\d]', '', phone)
    
    if len(phone) < 10:
        raise ValueError("Номер телефона должен содержать минимум 10 цифр")
    
    # Нормализация российских номеров
    if len(phone) == 11 and phone.startswith('8'):
        phone = '7' + phone[1:]
    elif len(phone) == 10 and phone.startswith('9'):
        phone = '7' + phone
    
    return phone


def validate_email(email: str) -> str:
    """
    Проверить email.
    """
    import re
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise ValueError("Неверный формат email")
    
    return email.lower()


def validate_password(password: str) -> str:
    """
    Проверить сложность пароля.
    """
    from app.core.security import validate_password_strength
    
    validate_password_strength(password)
    return password


# =============================================
# Конвертеры
# =============================================
def to_camel_case(snake_str: str) -> str:
    """
    Преобразовать snake_case в camelCase.
    """
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


def to_snake_case(camel_str: str) -> str:
    """
    Преобразовать camelCase в snake_case.
    """
    import re
    return re.sub(r'(?<!^)(?=[A-Z])', '_', camel_str).lower()


# =============================================
# Конфигурация Pydantic
# =============================================
from pydantic import ConfigDict

# Стандартная конфигурация для всех моделей
DEFAULT_MODEL_CONFIG = ConfigDict(
    from_attributes=True,
    populate_by_name=True,
    use_enum_values=True,
    extra="ignore",
    str_strip_whitespace=True,
    validate_default=True,
)

# Конфигурация с защитой от XSS
SECURE_MODEL_CONFIG = ConfigDict(
    **DEFAULT_MODEL_CONFIG,
    str_max_length=10000,  # Ограничение длины строк
)

# Конфигурация для ответов API (camelCase)
API_RESPONSE_CONFIG = ConfigDict(
    **DEFAULT_MODEL_CONFIG,
    alias_generator=to_camel_case,
    populate_by_name=True,
)
