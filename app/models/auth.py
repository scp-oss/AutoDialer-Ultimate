#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели аутентификации и авторизации
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Входа в систему (login)
- Обновления токенов (refresh)
- Смены/восстановления пароля
- Двухфакторной аутентификации (2FA/TOTP)
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import Field, EmailStr, field_validator, model_validator
import re

from app.models.common import BaseSchema, BaseResponse


# =============================================
# Запросы аутентификации
# =============================================
class LoginRequest(BaseSchema):
    """
    Запрос на вход в систему.
    
    Пример:
        {
            "username": "admin",
            "password": "SecurePass123",
            "remember_me": true
        }
    """
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=50,
        description="Имя пользователя или email"
    )
    password: str = Field(
        ..., 
        min_length=1,
        description="Пароль"
    )
    remember_me: bool = Field(
        False, 
        description="Запомнить меня (увеличивает время жизни refresh токена)"
    )
    totp_code: Optional[str] = Field(
        None,
        min_length=6,
        max_length=6,
        pattern=r'^\d{6}$',
        description="Код двухфакторной аутентификации (если включена)"
    )
    
    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Очистка имени пользователя"""
        return v.strip().lower()
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "admin",
                "password": "SecurePass123",
                "remember_me": True
            }
        }
    }


class RefreshTokenRequest(BaseSchema):
    """
    Запрос на обновление access токена.
    """
    refresh_token: str = Field(
        ..., 
        min_length=1,
        description="Refresh токен"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            }
        }
    }


class ChangePasswordRequest(BaseSchema):
    """
    Запрос на смену пароля (когда пользователь знает старый пароль).
    """
    old_password: str = Field(
        ..., 
        min_length=1,
        description="Текущий пароль"
    )
    new_password: str = Field(
        ..., 
        min_length=8,
        description="Новый пароль"
    )
    confirm_password: str = Field(
        ..., 
        min_length=8,
        description="Подтверждение нового пароля"
    )
    
    @field_validator('new_password')
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
        
        if errors:
            raise ValueError("; ".join(errors))
        
        return v
    
    @model_validator(mode='after')
    def validate_passwords_match(self) -> 'ChangePasswordRequest':
        """Проверка совпадения паролей"""
        if self.new_password != self.confirm_password:
            raise ValueError("Новый пароль и подтверждение не совпадают")
        if self.old_password == self.new_password:
            raise ValueError("Новый пароль должен отличаться от старого")
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "old_password": "OldPass123",
                "new_password": "NewSecurePass456",
                "confirm_password": "NewSecurePass456"
            }
        }
    }


class ResetPasswordRequest(BaseSchema):
    """
    Запрос на сброс пароля (администратором).
    """
    user_id: int = Field(..., gt=0, description="ID пользователя")
    new_password: str = Field(..., min_length=8, description="Новый пароль")
    force_change: bool = Field(True, description="Потребовать смену пароля при следующем входе")
    
    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        errors = []
        if len(v) < 8:
            errors.append("Минимальная длина пароля - 8 символов")
        if not re.search(r'[A-ZА-Я]', v):
            errors.append("Пароль должен содержать хотя бы одну заглавную букву")
        if not re.search(r'[a-zа-я]', v):
            errors.append("Пароль должен содержать хотя бы одну строчную букву")
        if not re.search(r'\d', v):
            errors.append("Пароль должен содержать хотя бы одну цифру")
        if errors:
            raise ValueError("; ".join(errors))
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": 5,
                "new_password": "NewSecurePass456",
                "force_change": True
            }
        }
    }


class ForgotPasswordRequest(BaseSchema):
    """
    Запрос на восстановление пароля (по email).
    """
    email: EmailStr = Field(..., description="Email пользователя")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "user@example.com"
            }
        }
    }


class ForgotPasswordConfirmRequest(BaseSchema):
    """
    Подтверждение восстановления пароля (по токену из email).
    """
    token: str = Field(..., description="Токен восстановления")
    new_password: str = Field(..., min_length=8, description="Новый пароль")
    confirm_password: str = Field(..., min_length=8, description="Подтверждение пароля")
    
    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        errors = []
        if len(v) < 8:
            errors.append("Минимальная длина пароля - 8 символов")
        if not re.search(r'[A-ZА-Я]', v):
            errors.append("Пароль должен содержать хотя бы одну заглавную букву")
        if not re.search(r'[a-zа-я]', v):
            errors.append("Пароль должен содержать хотя бы одну строчную букву")
        if not re.search(r'\d', v):
            errors.append("Пароль должен содержать хотя бы одну цифру")
        if errors:
            raise ValueError("; ".join(errors))
        return v
    
    @model_validator(mode='after')
    def validate_passwords_match(self) -> 'ForgotPasswordConfirmRequest':
        if self.new_password != self.confirm_password:
            raise ValueError("Пароли не совпадают")
        return self


# =============================================
# Ответы аутентификации
# =============================================
class LoginResponse(BaseResponse):
    """
    Ответ при успешном входе.
    """
    access_token: str = Field(..., description="Access токен (JWT)")
    refresh_token: str = Field(..., description="Refresh токен")
    token_type: str = Field("bearer", description="Тип токена")
    role: str = Field(..., description="Роль пользователя")
    force_password_change: bool = Field(False, description="Требуется смена пароля")
    user_id: int = Field(..., description="ID пользователя")
    username: str = Field(..., description="Имя пользователя")
    full_name: Optional[str] = Field(None, description="Полное имя")
    email: Optional[str] = Field(None, description="Email")
    permissions: List[str] = Field(default_factory=list, description="Разрешения")
    expires_in: int = Field(3600, description="Время жизни access токена в секундах")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "role": "admin",
                "force_password_change": False,
                "user_id": 1,
                "username": "admin",
                "full_name": "Administrator",
                "email": "admin@example.com",
                "permissions": ["campaigns:read", "campaigns:write", "users:manage"],
                "expires_in": 3600
            }
        }
    }


class TokenResponse(BaseResponse):
    """
    Ответ с токенами (упрощённая версия).
    """
    access_token: str = Field(..., description="Access токен")
    refresh_token: str = Field(..., description="Refresh токен")
    token_type: str = Field("bearer", description="Тип токена")
    role: str = Field(..., description="Роль")
    force_password_change: bool = Field(False, description="Требуется смена пароля")
    expires_in: int = Field(3600, description="Время жизни в секундах")


class RefreshTokenResponse(BaseResponse):
    """
    Ответ при обновлении токена.
    """
    access_token: str = Field(..., description="Новый access токен")
    token_type: str = Field("bearer", description="Тип токена")
    expires_in: int = Field(3600, description="Время жизни в секундах")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600
            }
        }
    }


class LogoutResponse(BaseResponse):
    """
    Ответ при выходе из системы.
    """
    success: bool = Field(True, description="Успешность")
    message: str = Field("Logged out successfully", description="Сообщение")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Logged out successfully"
            }
        }
    }


# =============================================
# Двухфакторная аутентификация (2FA / TOTP)
# =============================================
class TOTPSetupResponse(BaseResponse):
    """
    Ответ при настройке 2FA (TOTP).
    """
    secret: str = Field(..., description="Секретный ключ (base32)")
    uri: str = Field(..., description="URI для QR-кода")
    qr_code_data_url: Optional[str] = Field(None, description="Data URL с QR-кодом (base64)")
    recovery_codes: List[str] = Field(default_factory=list, description="Коды восстановления")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "secret": "JBSWY3DPEHPK3PXP",
                "uri": "otpauth://totp/AutoDialer:admin?secret=JBSWY3DPEHPK3PXP&issuer=AutoDialer",
                "qr_code_data_url": "data:image/png;base64,iVBORw0KGgoAAA...",
                "recovery_codes": ["ABCD-EFGH-IJKL", "MNOP-QRST-UVWX"]
            }
        }
    }


class TOTPVerifyRequest(BaseSchema):
    """
    Запрос на проверку TOTP кода.
    """
    code: str = Field(
        ..., 
        min_length=6, 
        max_length=6, 
        pattern=r'^\d{6}$',
        description="6-значный код из приложения"
    )
    recovery_code: Optional[str] = Field(
        None,
        description="Код восстановления (если нет доступа к приложению)"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": "123456"
            }
        }
    }


class TOTPVerifyResponse(BaseResponse):
    """
    Ответ при проверке TOTP кода.
    """
    verified: bool = Field(..., description="Код верный")
    message: str = Field(..., description="Сообщение")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "verified": True,
                "message": "2FA enabled successfully"
            }
        }
    }


class TOTPStatusResponse(BaseResponse):
    """
    Статус 2FA для пользователя.
    """
    enabled: bool = Field(..., description="Включена ли 2FA")
    setup_completed: bool = Field(..., description="Завершена ли настройка")
    backup_codes_remaining: Optional[int] = Field(None, description="Осталось кодов восстановления")
    last_used_at: Optional[datetime] = Field(None, description="Последнее использование")


class TOTPDisableRequest(BaseSchema):
    """
    Запрос на отключение 2FA.
    """
    password: str = Field(..., description="Текущий пароль для подтверждения")
    code: Optional[str] = Field(None, description="TOTP код (если есть доступ)")
    recovery_code: Optional[str] = Field(None, description="Или код восстановления")
    
    @model_validator(mode='after')
    def validate_code_or_recovery(self) -> 'TOTPDisableRequest':
        if not self.code and not self.recovery_code:
            raise ValueError("Необходимо указать code или recovery_code")
        return self


# =============================================
# API Ключи
# =============================================
class ApiKeyCreateRequest(BaseSchema):
    """
    Запрос на создание API ключа.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название ключа")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    permissions: List[str] = Field(default_factory=list, description="Разрешения")
    ip_whitelist: Optional[List[str]] = Field(None, description="Белый список IP")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Production API Key",
                "expires_at": "2025-12-31T23:59:59Z",
                "permissions": ["campaigns:read", "contacts:read"],
                "ip_whitelist": ["192.168.1.0/24"]
            }
        }
    }


class ApiKeyResponse(BaseResponse):
    """
    Ответ с созданным API ключом (показывается только один раз!).
    """
    id: int = Field(..., description="ID ключа")
    name: str = Field(..., description="Название")
    key: str = Field(..., description="API ключ (показывается только при создании!)")
    prefix: str = Field(..., description="Префикс для идентификации")
    created_at: datetime = Field(..., description="Дата создания")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    permissions: List[str] = Field(default_factory=list, description="Разрешения")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "Production API Key",
                "key": "ak_live_1234567890abcdef1234567890abcdef",
                "prefix": "ak_live_",
                "created_at": "2024-01-01T00:00:00Z",
                "expires_at": "2025-12-31T23:59:59Z",
                "permissions": ["campaigns:read", "contacts:read"]
            }
        }
    }


class ApiKeyListItem(BaseSchema):
    """
    Элемент списка API ключей (без самого ключа).
    """
    id: int = Field(..., description="ID ключа")
    name: str = Field(..., description="Название")
    prefix: str = Field(..., description="Префикс")
    created_at: datetime = Field(..., description="Дата создания")
    last_used_at: Optional[datetime] = Field(None, description="Последнее использование")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    is_active: bool = Field(True, description="Активен ли")
    permissions: List[str] = Field(default_factory=list, description="Разрешения")
    
    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at


class ApiKeyListResponse(BaseResponse):
    """
    Ответ со списком API ключей.
    """
    items: List[ApiKeyListItem] = Field(..., description="Ключи")
    total: int = Field(..., description="Всего ключей")


# =============================================
# Сессии
# =============================================
class SessionInfo(BaseSchema):
    """
    Информация об активной сессии.
    """
    session_id: str = Field(..., description="ID сессии")
    ip_address: Optional[str] = Field(None, description="IP адрес")
    user_agent: Optional[str] = Field(None, description="User Agent")
    created_at: datetime = Field(..., description="Создана")
    last_activity: datetime = Field(..., description="Последняя активность")
    is_current: bool = Field(False, description="Текущая сессия")


class SessionsListResponse(BaseResponse):
    """
    Ответ со списком активных сессий.
    """
    sessions: List[SessionInfo] = Field(..., description="Сессии")
    total: int = Field(..., description="Всего сессий")


# =============================================
# OAuth (опционально)
# =============================================
class OAuthProvider(str):
    """OAuth провайдеры"""
    GOOGLE = "google"
    GITHUB = "github"
    YANDEX = "yandex"
    VK = "vk"


class OAuthLoginRequest(BaseSchema):
    """
    Запрос на вход через OAuth.
    """
    provider: str = Field(..., description="Провайдер (google, github, etc.)")
    code: str = Field(..., description="Код авторизации от провайдера")
    redirect_uri: str = Field(..., description="Redirect URI")
    state: Optional[str] = Field(None, description="State для CSRF защиты")


class OAuthLinkRequest(BaseSchema):
    """
    Привязка OAuth к существующему аккаунту.
    """
    provider: str = Field(..., description="Провайдер")
    code: str = Field(..., description="Код авторизации")
    redirect_uri: str = Field(..., description="Redirect URI")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Запросы
    "LoginRequest",
    "RefreshTokenRequest",
    "ChangePasswordRequest",
    "ResetPasswordRequest",
    "ForgotPasswordRequest",
    "ForgotPasswordConfirmRequest",
    
    # Ответы
    "LoginResponse",
    "TokenResponse",
    "RefreshTokenResponse",
    "LogoutResponse",
    
    # 2FA / TOTP
    "TOTPSetupResponse",
    "TOTPVerifyRequest",
    "TOTPVerifyResponse",
    "TOTPStatusResponse",
    "TOTPDisableRequest",
    
    # API Ключи
    "ApiKeyCreateRequest",
    "ApiKeyResponse",
    "ApiKeyListItem",
    "ApiKeyListResponse",
    
    # Сессии
    "SessionInfo",
    "SessionsListResponse",
    
    # OAuth
    "OAuthProvider",
    "OAuthLoginRequest",
    "OAuthLinkRequest",
]
