#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели пользователей
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Создания и обновления пользователей
- Управления ролями и разрешениями
- Профилей пользователей
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, EmailStr, field_validator, model_validator
import re

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class UserRole(str, Enum):
    """Роль пользователя"""
    ADMIN = "admin"           # Администратор (полный доступ)
    MANAGER = "manager"       # Менеджер (управление кампаниями и контактами)
    OPERATOR = "operator"     # Оператор (только запуск/остановка кампаний)
    VIEWER = "viewer"         # Наблюдатель (только просмотр)
    API = "api"               # API доступ (только через API ключи)
    AUDITOR = "auditor"       # Аудитор (просмотр логов и статистики)


class UserStatus(str, Enum):
    """Статус пользователя"""
    ACTIVE = "active"         # Активен
    INACTIVE = "inactive"     # Неактивен
    BLOCKED = "blocked"       # Заблокирован
    PENDING = "pending"       # Ожидает подтверждения


class Permission(str, Enum):
    """Разрешения"""
    # Кампании
    CAMPAIGNS_READ = "campaigns:read"
    CAMPAIGNS_CREATE = "campaigns:create"
    CAMPAIGNS_UPDATE = "campaigns:update"
    CAMPAIGNS_DELETE = "campaigns:delete"
    CAMPAIGNS_START = "campaigns:start"
    CAMPAIGNS_STOP = "campaigns:stop"
    CAMPAIGNS_MANAGE = "campaigns:manage"  # Все права на кампании
    
    # Контакты
    CONTACTS_READ = "contacts:read"
    CONTACTS_CREATE = "contacts:create"
    CONTACTS_UPDATE = "contacts:update"
    CONTACTS_DELETE = "contacts:delete"
    CONTACTS_IMPORT = "contacts:import"
    CONTACTS_EXPORT = "contacts:export"
    CONTACTS_MANAGE = "contacts:manage"
    
    # Группы контактов
    GROUPS_READ = "groups:read"
    GROUPS_CREATE = "groups:create"
    GROUPS_UPDATE = "groups:update"
    GROUPS_DELETE = "groups:delete"
    GROUPS_MANAGE = "groups:manage"
    
    # Звонки
    CALLS_READ = "calls:read"
    CALLS_HISTORY = "calls:history"
    CALLS_RECORDINGS = "calls:recordings"
    CALLS_DELETE = "calls:delete"
    
    # Аудиофайлы
    AUDIO_READ = "audio:read"
    AUDIO_UPLOAD = "audio:upload"
    AUDIO_GENERATE = "audio:generate"
    AUDIO_DELETE = "audio:delete"
    AUDIO_MANAGE = "audio:manage"
    
    # Чёрный список
    BLACKLIST_READ = "blacklist:read"
    BLACKLIST_ADD = "blacklist:add"
    BLACKLIST_REMOVE = "blacklist:remove"
    BLACKLIST_MANAGE = "blacklist:manage"
    
    # Пользователи
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    USERS_MANAGE = "users:manage"
    
    # Настройки
    SETTINGS_READ = "settings:read"
    SETTINGS_UPDATE = "settings:update"
    SETTINGS_MANAGE = "settings:manage"
    
    # Система
    SYSTEM_STATUS = "system:status"
    SYSTEM_ENABLE = "system:enable"
    SYSTEM_DISABLE = "system:disable"
    SYSTEM_MANAGE = "system:manage"
    
    # Аудит
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    
    # Статистика
    STATS_READ = "stats:read"
    STATS_EXPORT = "stats:export"
    
    # API ключи
    API_KEYS_READ = "api_keys:read"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_REVOKE = "api_keys:revoke"
    API_KEYS_MANAGE = "api_keys:manage"
    
    # Входящие звонки
    INCOMING_READ = "incoming:read"
    INCOMING_MANAGE = "incoming:manage"
    INCOMING_DELETE = "incoming:delete"


# =============================================
# Роли и разрешения по умолчанию
# =============================================
ROLE_PERMISSIONS: Dict[UserRole, List[Permission]] = {
    UserRole.ADMIN: [
        # Админ имеет все разрешения
        Permission.CAMPAIGNS_MANAGE,
        Permission.CONTACTS_MANAGE,
        Permission.GROUPS_MANAGE,
        Permission.CALLS_READ,
        Permission.CALLS_HISTORY,
        Permission.CALLS_RECORDINGS,
        Permission.CALLS_DELETE,
        Permission.AUDIO_MANAGE,
        Permission.BLACKLIST_MANAGE,
        Permission.USERS_MANAGE,
        Permission.SETTINGS_MANAGE,
        Permission.SYSTEM_MANAGE,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
        Permission.STATS_READ,
        Permission.STATS_EXPORT,
        Permission.API_KEYS_MANAGE,
        Permission.INCOMING_MANAGE,
    ],
    UserRole.MANAGER: [
        Permission.CAMPAIGNS_MANAGE,
        Permission.CONTACTS_MANAGE,
        Permission.GROUPS_MANAGE,
        Permission.CALLS_READ,
        Permission.CALLS_HISTORY,
        Permission.CALLS_RECORDINGS,
        Permission.AUDIO_MANAGE,
        Permission.BLACKLIST_MANAGE,
        Permission.STATS_READ,
        Permission.STATS_EXPORT,
        Permission.INCOMING_READ,
        Permission.INCOMING_MANAGE,
    ],
    UserRole.OPERATOR: [
        Permission.CAMPAIGNS_READ,
        Permission.CAMPAIGNS_START,
        Permission.CAMPAIGNS_STOP,
        Permission.CONTACTS_READ,
        Permission.CALLS_READ,
        Permission.CALLS_HISTORY,
        Permission.AUDIO_READ,
        Permission.BLACKLIST_READ,
        Permission.STATS_READ,
        Permission.INCOMING_READ,
    ],
    UserRole.VIEWER: [
        Permission.CAMPAIGNS_READ,
        Permission.CONTACTS_READ,
        Permission.CALLS_READ,
        Permission.CALLS_HISTORY,
        Permission.AUDIO_READ,
        Permission.STATS_READ,
        Permission.INCOMING_READ,
    ],
    UserRole.AUDITOR: [
        Permission.CAMPAIGNS_READ,
        Permission.CONTACTS_READ,
        Permission.CALLS_READ,
        Permission.CALLS_HISTORY,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
        Permission.STATS_READ,
        Permission.STATS_EXPORT,
        Permission.INCOMING_READ,
    ],
    UserRole.API: [
        Permission.CAMPAIGNS_READ,
        Permission.CAMPAIGNS_START,
        Permission.CONTACTS_READ,
        Permission.CONTACTS_CREATE,
        Permission.CALLS_READ,
        Permission.STATS_READ,
    ],
}


# =============================================
# Запросы
# =============================================
class UserCreateRequest(BaseSchema):
    """
    Запрос на создание пользователя.
    """
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=50, 
        pattern=r'^[a-zA-Z0-9_-]+$',
        description="Имя пользователя"
    )
    password: str = Field(..., min_length=8, description="Пароль")
    
    email: Optional[EmailStr] = Field(None, description="Email")
    full_name: Optional[str] = Field(None, max_length=255, description="Полное имя")
    
    role: UserRole = Field(UserRole.VIEWER, description="Роль")
    custom_permissions: List[Permission] = Field(default_factory=list, description="Дополнительные разрешения")
    
    phone: Optional[str] = Field(None, description="Телефон")
    department: Optional[str] = Field(None, max_length=100, description="Отдел")
    position: Optional[str] = Field(None, max_length=100, description="Должность")
    
    force_password_change: bool = Field(True, description="Потребовать смену пароля при первом входе")
    send_welcome_email: bool = Field(False, description="Отправить приветственное письмо")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Валидация имени пользователя"""
        v = v.strip().lower()
        
        # Запрещённые имена
        forbidden = {'admin', 'administrator', 'root', 'system', 'autodialer', 'noreply'}
        if v in forbidden:
            raise ValueError(f"Имя пользователя '{v}' зарезервировано")
        
        return v
    
    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Проверка сложности пароля"""
        errors = []
        
        if len(v) < 8:
            errors.append("Минимальная длина пароля - 8 символов")
        if not re.search(r'[A-ZА-Я]', v):
            errors.append("Пароль должен содержать хотя бы одну заглавную букву")
        if not re.search(r'[a-zа-я]', v):
            errors.append("Пароль должен содержать хотя бы одну строчную букву")
        if not re.search(r'\d', v):
            errors.append("Пароль должен содержать хотя бы одну цифру")
        
        # Проверка на совпадение с username (если уже задан)
        # Будет выполнена в model_validator
        
        if errors:
            raise ValueError("; ".join(errors))
        
        return v
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.lower().strip()
        return v
    
    @field_validator('full_name')
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip()
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "ivanov",
                "password": "SecurePass123",
                "email": "ivanov@example.com",
                "full_name": "Иван Иванов",
                "role": "operator",
                "phone": "+79991234567",
                "department": "Продажи",
                "position": "Менеджер",
                "force_password_change": True
            }
        }
    }


class UserUpdateRequest(BaseSchema):
    """
    Запрос на обновление пользователя.
    """
    email: Optional[EmailStr] = Field(None, description="Email")
    full_name: Optional[str] = Field(None, max_length=255, description="Полное имя")
    
    role: Optional[UserRole] = Field(None, description="Роль")
    custom_permissions: Optional[List[Permission]] = Field(None, description="Дополнительные разрешения")
    
    phone: Optional[str] = Field(None, description="Телефон")
    department: Optional[str] = Field(None, max_length=100, description="Отдел")
    position: Optional[str] = Field(None, max_length=100, description="Должность")
    
    status: Optional[UserStatus] = Field(None, description="Статус")
    
    force_password_change: Optional[bool] = Field(None, description="Потребовать смену пароля")
    
    metadata: Optional[Dict[str, Any]] = Field(None, description="Метаданные")
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.lower().strip()
        return v


class UserProfileUpdateRequest(BaseSchema):
    """
    Запрос на обновление своего профиля.
    """
    email: Optional[EmailStr] = Field(None, description="Email")
    full_name: Optional[str] = Field(None, max_length=255, description="Полное имя")
    phone: Optional[str] = Field(None, description="Телефон")
    
    avatar_url: Optional[str] = Field(None, description="URL аватара")
    
    preferences: Dict[str, Any] = Field(default_factory=dict, description="Настройки")
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.lower().strip()
        return v


# =============================================
# Ответы
# =============================================
class UserResponse(BaseSchema, TimestampSchema):
    """
    Ответ с информацией о пользователе.
    """
    id: int = Field(..., description="ID пользователя")
    username: str = Field(..., description="Имя пользователя")
    
    email: Optional[str] = Field(None, description="Email")
    full_name: Optional[str] = Field(None, description="Полное имя")
    
    role: UserRole = Field(..., description="Роль")
    custom_permissions: List[Permission] = Field(default_factory=list, description="Дополнительные разрешения")
    
    # Вычисляемые разрешения (роль + custom)
    permissions: List[Permission] = Field(default_factory=list, description="Все разрешения")
    
    phone: Optional[str] = Field(None, description="Телефон")
    department: Optional[str] = Field(None, description="Отдел")
    position: Optional[str] = Field(None, description="Должность")
    
    avatar_url: Optional[str] = Field(None, description="URL аватара")
    
    status: UserStatus = Field(UserStatus.ACTIVE, description="Статус")
    force_password_change: bool = Field(False, description="Требуется смена пароля")
    
    last_login: Optional[datetime] = Field(None, description="Последний вход")
    last_ip: Optional[str] = Field(None, description="Последний IP")
    
    login_count: int = Field(0, description="Количество входов")
    
    # 2FA
    totp_enabled: bool = Field(False, description="2FA включена")
    
    # Статистика
    campaigns_created: int = Field(0, description="Создано кампаний")
    calls_made: int = Field(0, description="Совершено звонков")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @model_validator(mode='after')
    def compute_permissions(self) -> 'UserResponse':
        """Вычисление всех разрешений"""
        base_permissions = ROLE_PERMISSIONS.get(self.role, [])
        all_permissions = set(base_permissions) | set(self.custom_permissions)
        
        # Если есть MANAGE разрешение, добавляем все дочерние
        expanded = set()
        for perm in all_permissions:
            expanded.add(perm)
            if perm == Permission.CAMPAIGNS_MANAGE:
                expanded.update([p for p in Permission if p.value.startswith("campaigns:")])
            elif perm == Permission.CONTACTS_MANAGE:
                expanded.update([p for p in Permission if p.value.startswith("contacts:")])
            elif perm == Permission.USERS_MANAGE:
                expanded.update([p for p in Permission if p.value.startswith("users:")])
            elif perm == Permission.SYSTEM_MANAGE:
                expanded.update([p for p in Permission if p.value.startswith("system:")])
        
        self.permissions = list(expanded)
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "username": "admin",
                "email": "admin@example.com",
                "full_name": "Администратор",
                "role": "admin",
                "permissions": ["campaigns:manage", "contacts:manage", "users:manage"],
                "status": "active",
                "force_password_change": False,
                "last_login": "2024-01-01T10:00:00Z",
                "totp_enabled": True,
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class UserProfileResponse(UserResponse):
    """
    Ответ с профилем текущего пользователя.
    """
    preferences: Dict[str, Any] = Field(default_factory=dict, description="Настройки")
    notifications: Dict[str, bool] = Field(default_factory=dict, description="Настройки уведомлений")
    
    # API ключи (только информация, без самих ключей)
    api_keys_count: int = Field(0, description="Количество API ключей")
    active_sessions_count: int = Field(0, description="Активных сессий")
    
    # Лимиты
    limits: Dict[str, Any] = Field(default_factory=dict, description="Лимиты пользователя")


class UserListResponse(BaseSchema):
    """
    Ответ со списком пользователей.
    """
    items: List[UserResponse] = Field(..., description="Пользователи")
    total: int = Field(..., description="Всего пользователей")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")


class UserSummaryResponse(BaseSchema):
    """
    Краткая информация о пользователе.
    """
    id: int = Field(..., description="ID")
    username: str = Field(..., description="Имя пользователя")
    full_name: Optional[str] = Field(None, description="Полное имя")
    role: UserRole = Field(..., description="Роль")
    status: UserStatus = Field(..., description="Статус")


# =============================================
# Уведомления
# =============================================
class NotificationPreferences(BaseSchema):
    """
    Настройки уведомлений пользователя.
    """
    email_notifications: bool = Field(True, description="Email уведомления")
    
    campaign_started: bool = Field(True, description="Кампания запущена")
    campaign_completed: bool = Field(True, description="Кампания завершена")
    campaign_failed: bool = Field(True, description="Ошибка кампании")
    
    call_failed: bool = Field(False, description="Ошибка звонка")
    
    system_alerts: bool = Field(True, description="Системные оповещения")
    security_alerts: bool = Field(True, description="Оповещения безопасности")
    
    daily_report: bool = Field(True, description="Ежедневный отчёт")
    weekly_report: bool = Field(True, description="Еженедельный отчёт")
    
    notify_emails: List[str] = Field(default_factory=list, description="Дополнительные email для уведомлений")


# =============================================
# Фильтры
# =============================================
class UserFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию пользователей.
    """
    search: Optional[str] = Field(None, description="Поиск по имени, email")
    
    role: Optional[List[UserRole]] = Field(None, description="Роли")
    status: Optional[List[UserStatus]] = Field(None, description="Статусы")
    
    has_totp: Optional[bool] = Field(None, description="Включена 2FA")
    force_password_change: Optional[bool] = Field(None, description="Требуется смена пароля")
    
    created_after: Optional[datetime] = Field(None, description="Создан после")
    created_before: Optional[datetime] = Field(None, description="Создан до")
    
    last_login_after: Optional[datetime] = Field(None, description="Последний вход после")
    last_login_before: Optional[datetime] = Field(None, description="Последний вход до")
    
    department: Optional[str] = Field(None, description="Отдел")
    
    sort_by: str = Field("id", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "UserRole",
    "UserStatus",
    "Permission",
    
    # Разрешения ролей
    "ROLE_PERMISSIONS",
    
    # Запросы
    "UserCreateRequest",
    "UserUpdateRequest",
    "UserProfileUpdateRequest",
    
    # Ответы
    "UserResponse",
    "UserProfileResponse",
    "UserListResponse",
    "UserSummaryResponse",
    
    # Уведомления
    "NotificationPreferences",
    
    # Фильтры
    "UserFilterRequest",
]
