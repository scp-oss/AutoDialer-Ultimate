#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели API токенов
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Управления API ключами
- Аутентификации через API ключи
- Контроля доступа и разрешений
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema
from app.models.user import Permission


# =============================================
# Запросы
# =============================================
class ApiTokenCreateRequest(BaseSchema):
    """
    Запрос на создание API токена.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название токена")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    
    permissions: List[Permission] = Field(default_factory=list, description="Разрешения")
    
    ip_whitelist: Optional[List[str]] = Field(None, description="Белый список IP (CIDR)")
    ip_blacklist: Optional[List[str]] = Field(None, description="Чёрный список IP")
    
    rate_limit: Optional[int] = Field(None, ge=1, description="Лимит запросов в минуту")
    
    allowed_methods: Optional[List[str]] = Field(None, description="Разрешённые HTTP методы")
    allowed_paths: Optional[List[str]] = Field(None, description="Разрешённые пути (префиксы)")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Очистка названия"""
        return v.strip()
    
    @field_validator('ip_whitelist', 'ip_blacklist')
    @classmethod
    def validate_ip_list(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Валидация IP адресов"""
        if v is None:
            return v
        
        import re
        ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$')
        
        for ip in v:
            if not ip_pattern.match(ip.strip()):
                raise ValueError(f"Неверный формат IP/CIDR: {ip}")
        
        return [ip.strip() for ip in v]
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Production API Key",
                "description": "Для интеграции с CRM",
                "expires_at": "2025-12-31T23:59:59Z",
                "permissions": ["campaigns:read", "contacts:read", "calls:read"],
                "ip_whitelist": ["192.168.1.0/24", "10.0.0.1"],
                "rate_limit": 100,
                "allowed_methods": ["GET", "POST"],
                "allowed_paths": ["/api/campaigns", "/api/contacts"]
            }
        }
    }


class ApiTokenUpdateRequest(BaseSchema):
    """
    Запрос на обновление API токена.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    
    permissions: Optional[List[Permission]] = Field(None, description="Разрешения")
    
    ip_whitelist: Optional[List[str]] = Field(None, description="Белый список IP")
    ip_blacklist: Optional[List[str]] = Field(None, description="Чёрный список IP")
    
    rate_limit: Optional[int] = Field(None, ge=1, description="Лимит запросов в минуту")
    
    allowed_methods: Optional[List[str]] = Field(None, description="Разрешённые методы")
    allowed_paths: Optional[List[str]] = Field(None, description="Разрешённые пути")
    
    is_active: Optional[bool] = Field(None, description="Активен")
    
    metadata: Optional[Dict[str, Any]] = Field(None, description="Метаданные")


class ApiTokenRegenerateRequest(BaseSchema):
    """
    Запрос на перегенерацию API токена.
    """
    regenerate: bool = Field(True, description="Подтверждение перегенерации")
    keep_permissions: bool = Field(True, description="Сохранить разрешения")
    keep_restrictions: bool = Field(True, description="Сохранить ограничения")


# =============================================
# Ответы
# =============================================
class ApiTokenResponse(BaseSchema):
    """
    Ответ с созданным API токеном.
    ВНИМАНИЕ: Полный токен показывается ТОЛЬКО при создании!
    """
    id: int = Field(..., description="ID токена")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    
    token: str = Field(..., description="API токен (показывается только при создании!)")
    prefix: str = Field(..., description="Префикс токена")
    
    permissions: List[Permission] = Field(default_factory=list, description="Разрешения")
    
    ip_whitelist: Optional[List[str]] = Field(None, description="Белый список IP")
    ip_blacklist: Optional[List[str]] = Field(None, description="Чёрный список IP")
    rate_limit: Optional[int] = Field(None, description="Лимит запросов в минуту")
    
    allowed_methods: Optional[List[str]] = Field(None, description="Разрешённые методы")
    allowed_paths: Optional[List[str]] = Field(None, description="Разрешённые пути")
    
    is_active: bool = Field(True, description="Активен")
    
    created_at: datetime = Field(..., description="Дата создания")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "Production API Key",
                "description": "Для интеграции с CRM",
                "token": "ak_live_1234567890abcdef1234567890abcdef",
                "prefix": "ak_live_",
                "permissions": ["campaigns:read", "contacts:read"],
                "ip_whitelist": ["192.168.1.0/24"],
                "rate_limit": 100,
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "expires_at": "2025-12-31T23:59:59Z",
                "created_by": 1,
                "created_by_name": "admin"
            }
        }
    }


class ApiTokenListItem(BaseSchema):
    """
    Элемент списка API токенов (без секретного ключа).
    """
    id: int = Field(..., description="ID токена")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    
    prefix: str = Field(..., description="Префикс токена")
    
    permissions: List[Permission] = Field(default_factory=list, description="Разрешения")
    
    is_active: bool = Field(True, description="Активен")
    
    created_at: datetime = Field(..., description="Дата создания")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    
    last_used_at: Optional[datetime] = Field(None, description="Последнее использование")
    last_used_ip: Optional[str] = Field(None, description="Последний IP")
    
    usage_count: int = Field(0, description("Количество использований"))
    
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    @property
    def is_expired(self) -> bool:
        """Проверить, истёк ли токен"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "Production API Key",
                "description": "Для интеграции с CRM",
                "prefix": "ak_live_",
                "permissions": ["campaigns:read"],
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "expires_at": "2025-12-31T23:59:59Z",
                "last_used_at": "2024-01-15T10:30:00Z",
                "last_used_ip": "192.168.1.100",
                "usage_count": 1523,
                "created_by_name": "admin"
            }
        }
    }


class ApiTokenDetailResponse(ApiTokenListItem):
    """
    Детальный ответ об API токене.
    """
    ip_whitelist: Optional[List[str]] = Field(None, description="Белый список IP")
    ip_blacklist: Optional[List[str]] = Field(None, description="Чёрный список IP")
    rate_limit: Optional[int] = Field(None, description="Лимит запросов")
    
    allowed_methods: Optional[List[str]] = Field(None, description="Разрешённые методы")
    allowed_paths: Optional[List[str]] = Field(None, description="Разрешённые пути")
    
    usage_history: List[Dict[str, Any]] = Field(default_factory=list, description="История использования")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")


class ApiTokenListResponse(BaseSchema):
    """
    Ответ со списком API токенов.
    """
    items: List[ApiTokenListItem] = Field(..., description="Токены")
    total: int = Field(..., description="Всего токенов")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description("Всего страниц"))
    
    summary: Dict[str, Any] = Field(default_factory=dict, description="Сводка")


# =============================================
# Проверка токена
# =============================================
class ApiTokenVerifyRequest(BaseSchema):
    """
    Запрос на проверку API токена.
    """
    token: str = Field(..., description="API токен для проверки")
    path: Optional[str] = Field(None, description="Путь запроса")
    method: Optional[str] = Field(None, description("HTTP метод"))


class ApiTokenVerifyResponse(BaseSchema):
    """
    Ответ проверки API токена.
    """
    valid: bool = Field(..., description="Токен валиден")
    token_id: Optional[int] = Field(None, description="ID токена")
    user_id: Optional[int] = Field(None, description="ID пользователя")
    permissions: List[str] = Field(default_factory=list, description="Разрешения")
    
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    is_expired: bool = Field(False, description("Истёк"))
    
    rate_limit_remaining: Optional[int] = Field(None, description="Осталось запросов")
    rate_limit_reset: Optional[int] = Field(None, description("Сброс через (сек)"))
    
    errors: List[str] = Field(default_factory=list, description="Ошибки")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "valid": True,
                "token_id": 1,
                "user_id": 42,
                "permissions": ["campaigns:read", "contacts:read"],
                "expires_at": "2025-12-31T23:59:59Z",
                "is_expired": False,
                "rate_limit_remaining": 95,
                "rate_limit_reset": 30,
                "errors": []
            }
        }
    }


# =============================================
# Использование токена
# =============================================
class ApiTokenUsageEntry(BaseSchema):
    """
    Запись об использовании токена.
    """
    id: int = Field(..., description="ID записи")
    token_id: int = Field(..., description="ID токена")
    
    timestamp: datetime = Field(..., description="Время запроса")
    ip_address: Optional[str] = Field(None, description="IP адрес")
    user_agent: Optional[str] = Field(None, description="User Agent")
    
    method: str = Field(..., description="HTTP метод")
    path: str = Field(..., description="Путь запроса")
    status_code: int = Field(..., description("Код ответа"))
    
    duration_ms: int = Field(..., description("Длительность (мс)"))
    
    rate_limited: bool = Field(False, description("Был ли ограничен"))


class ApiTokenUsageResponse(BaseSchema):
    """
    Ответ с историей использования токена.
    """
    token_id: int = Field(..., description="ID токена")
    items: List[ApiTokenUsageEntry] = Field(..., description("Записи использования"))
    total: int = Field(..., description("Всего записей"))
    page: int = Field(..., description("Текущая страница"))
    page_size: int = Field(..., description("Размер страницы"))
    
    summary: Dict[str, Any] = Field(default_factory=dict, description="Сводка")


# =============================================
# Статистика токенов
# =============================================
class ApiTokenStatsResponse(BaseSchema):
    """
    Статистика по API токенам.
    """
    total_tokens: int = Field(0, description="Всего токенов")
    active_tokens: int = Field(0, description="Активных")
    expired_tokens: int = Field(0, description("Истекших"))
    revoked_tokens: int = Field(0, description("Отозванных"))
    
    total_requests: int = Field(0, description="Всего запросов")
    requests_today: int = Field(0, description("Запросов сегодня"))
    requests_this_hour: int = Field(0, description("Запросов за час"))
    
    avg_requests_per_token: float = Field(0.0, description("Среднее запросов на токен"))
    
    top_tokens: List[Dict[str, Any]] = Field(default_factory=list, description("Топ токенов по запросам"))
    top_paths: List[Dict[str, Any]] = Field(default_factory=list, description("Топ путей"))
    
    rate_limited_requests: int = Field(0, description("Ограниченных запросов"))


# =============================================
# Ротация токенов
# =============================================
class ApiTokenRotateRequest(BaseSchema):
    """
    Запрос на ротацию API токена.
    """
    rotate: bool = Field(True, description("Подтверждение ротации"))
    keep_old_active: bool = Field(False, description("Оставить старый активным"))
    old_token_expires_in: Optional[int] = Field(24, ge=1, le=168, description="Часов до истечения старого"))


class ApiTokenRotateResponse(BaseSchema):
    """
    Ответ на ротацию API токена.
    """
    old_token_id: int = Field(..., description="ID старого токена")
    new_token_id: int = Field(..., description="ID нового токена")
    new_token: str = Field(..., description="Новый API токен")
    prefix: str = Field(..., description="Префикс нового токена")
    old_token_expires_at: Optional[datetime] = Field(None, description="Старый истекает")


# =============================================
# Массовые операции
# =============================================
class ApiTokenBulkActionRequest(BaseSchema):
    """
    Запрос на массовое действие с токенами.
    """
    token_ids: List[int] = Field(..., min_length=1, description="ID токенов")
    action: str = Field(..., description="Действие (revoke/activate/deactivate)")
    
    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"revoke", "activate", "deactivate"}
        if v not in allowed:
            raise ValueError(f"Недопустимое действие. Разрешено: {', '.join(allowed)}")
        return v


class ApiTokenBulkActionResponse(BaseSchema):
    """
    Ответ на массовое действие.
    """
    total: int = Field(..., description="Всего токенов")
    successful: List[int] = Field(default_factory=list, description="Успешно обработаны")
    failed: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")


# =============================================
# Webhook токены (специальный тип)
# =============================================
class WebhookTokenCreateRequest(BaseSchema):
    """
    Запрос на создание webhook токена.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    
    webhook_url: str = Field(..., description("URL вебхука"))
    events: List[str] = Field(..., description("События для подписки"))
    
    secret: Optional[str] = Field(None, description("Секрет для подписи"))
    
    expires_at: Optional[datetime] = Field(None, description("Дата истечения"))
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")


class WebhookTokenResponse(ApiTokenResponse):
    """
    Ответ с webhook токеном.
    """
    webhook_url: str = Field(..., description("URL вебхука"))
    events: List[str] = Field(..., description("Подписан на события"))
    secret: Optional[str] = Field(None, description("Секрет для подписи (показывается только при создании!)"))


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Запросы
    "ApiTokenCreateRequest",
    "ApiTokenUpdateRequest",
    "ApiTokenRegenerateRequest",
    
    # Ответы
    "ApiTokenResponse",
    "ApiTokenListItem",
    "ApiTokenDetailResponse",
    "ApiTokenListResponse",
    
    # Проверка
    "ApiTokenVerifyRequest",
    "ApiTokenVerifyResponse",
    
    # Использование
    "ApiTokenUsageEntry",
    "ApiTokenUsageResponse",
    
    # Статистика
    "ApiTokenStatsResponse",
    
    # Ротация
    "ApiTokenRotateRequest",
    "ApiTokenRotateResponse",
    
    # Массовые операции
    "ApiTokenBulkActionRequest",
    "ApiTokenBulkActionResponse",
    
    # Webhook
    "WebhookTokenCreateRequest",
    "WebhookTokenResponse",
]
