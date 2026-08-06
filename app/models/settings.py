#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели настроек
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Управления настройками системы
- Категорий настроек
- Валидации значений
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class SettingCategory(str, Enum):
    """Категории настроек"""
    GENERAL = "general"           # Общие настройки
    DIALER = "dialer"             # Настройки дозвона
    AUDIO = "audio"               # Настройки аудио
    TTS = "tts"                   # Настройки TTS
    TRANSCRIPTION = "transcription"  # Настройки транскрибации
    SECURITY = "security"         # Настройки безопасности
    NOTIFICATIONS = "notifications"  # Настройки уведомлений
    API = "api"                   # Настройки API
    LOGGING = "logging"           # Настройки логирования
    ADVANCED = "advanced"         # Расширенные настройки


class SettingValueType(str, Enum):
    """Типы значений настроек"""
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"
    DICT = "dict"
    JSON = "json"


# =============================================
# Запросы
# =============================================
class SettingUpdateRequest(BaseSchema):
    """
    Запрос на обновление настройки.
    """
    value: str = Field(..., description="Новое значение")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "value": "50"
            }
        }
    }


class SettingsBulkUpdateRequest(BaseSchema):
    """
    Запрос на массовое обновление настроек.
    """
    settings: Dict[str, str] = Field(
        ..., 
        description="Словарь ключ-значение"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "settings": {
                    "dialer.max_calls": "50",
                    "dialer.default_cps": "5",
                    "audio.retention_days": "30"
                }
            }
        }
    }


class SettingResetRequest(BaseSchema):
    """
    Запрос на сброс настроек.
    """
    keys: Optional[List[str]] = Field(None, description="Ключи для сброса (если None - все)")
    category: Optional[SettingCategory] = Field(None, description="Категория для сброса")


# =============================================
# Ответы
# =============================================
class SettingResponse(BaseSchema):
    """
    Ответ с информацией о настройке.
    """
    key: str = Field(..., description="Ключ настройки")
    value: str = Field(..., description="Значение")
    description: Optional[str] = Field(None, description="Описание")
    category: str = Field(..., description="Категория")
    value_type: str = Field("string", description="Тип значения")
    default_value: Optional[str] = Field(None, description="Значение по умолчанию")
    is_public: bool = Field(True, description="Публичная")
    is_readonly: bool = Field(False, description="Только для чтения")
    allowed_values: Optional[List[str]] = Field(None, description="Разрешённые значения")
    min_value: Optional[float] = Field(None, description="Минимальное значение")
    max_value: Optional[float] = Field(None, description="Максимальное значение")
    requires_restart: bool = Field(False, description="Требует перезапуска")
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    updated_at: Optional[datetime] = Field(None, description="Дата обновления")
    updated_by: Optional[str] = Field(None, description="Кем обновлено")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "key": "dialer.max_calls",
                "value": "50",
                "description": "Максимальное количество одновременных звонков",
                "category": "dialer",
                "value_type": "int",
                "default_value": "30",
                "is_public": True,
                "is_readonly": False,
                "min_value": 1,
                "max_value": 500,
                "requires_restart": False,
                "tags": ["dialer", "performance"],
                "updated_at": "2024-01-01T00:00:00Z",
                "updated_by": "admin"
            }
        }
    }


class SettingDetailResponse(SettingResponse):
    """
    Детальный ответ о настройке с историей изменений.
    """
    history: List[Dict[str, Any]] = Field(default_factory=list, description="История изменений")
    usage_info: Optional[Dict[str, Any]] = Field(None, description="Информация об использовании")


class SettingsListResponse(BaseSchema):
    """
    Ответ со списком настроек.
    """
    items: List[SettingResponse] = Field(..., description="Настройки")
    total: int = Field(..., description="Всего настроек")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")


class SettingsByCategoryResponse(BaseSchema):
    """
    Ответ с настройками по категориям.
    """
    categories: Dict[str, List[SettingResponse]] = Field(..., description="Настройки по категориям")
    total_categories: int = Field(..., description="Всего категорий")
    total_settings: int = Field(..., description="Всего настроек")


class SettingCategoryInfo(BaseSchema):
    """
    Информация о категории настроек.
    """
    name: str = Field(..., description="Ключ категории")
    display_name: str = Field(..., description="Отображаемое имя")
    description: Optional[str] = Field(None, description="Описание")
    icon: Optional[str] = Field(None, description="Иконка")
    order: int = Field(0, description="Порядок отображения")
    settings_count: int = Field(0, description="Количество настроек")


class SettingsCategoriesResponse(BaseSchema):
    """
    Ответ со списком категорий.
    """
    items: List[SettingCategoryInfo] = Field(..., description="Категории")


# =============================================
# Экспорт/Импорт
# =============================================
class SettingsExportResponse(BaseSchema):
    """
    Ответ с экспортированными настройками.
    """
    version: str = Field(..., description="Версия приложения")
    exported_at: datetime = Field(..., description="Дата экспорта")
    settings: Dict[str, Any] = Field(..., description="Настройки")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "version": "3.0.0",
                "exported_at": "2024-01-01T00:00:00Z",
                "settings": {
                    "dialer.max_calls": 50,
                    "dialer.default_cps": 5
                }
            }
        }
    }


class SettingsImportRequest(BaseSchema):
    """
    Запрос на импорт настроек.
    """
    settings: Dict[str, Any] = Field(..., description="Настройки для импорта")
    overwrite: bool = Field(True, description="Перезаписывать существующие")
    skip_errors: bool = Field(True, description="Пропускать ошибки")
    validate_only: bool = Field(False, description="Только валидация")


class SettingsImportResponse(BaseSchema):
    """
    Ответ на импорт настроек.
    """
    imported: int = Field(0, description="Импортировано")
    skipped: int = Field(0, description="Пропущено")
    failed: int = Field(0, description="Ошибок")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "imported": 25,
                "skipped": 3,
                "failed": 1,
                "errors": [
                    {"key": "invalid.setting", "error": "Setting not found"}
                ]
            }
        }
    }


# =============================================
# Валидация
# =============================================
class SettingValidationRequest(BaseSchema):
    """
    Запрос на валидацию значения настройки.
    """
    key: str = Field(..., description="Ключ настройки")
    value: str = Field(..., description="Значение для проверки")


class SettingValidationResponse(BaseSchema):
    """
    Ответ валидации значения.
    """
    valid: bool = Field(..., description="Валидно")
    parsed_value: Optional[Any] = Field(None, description="Распарсенное значение")
    errors: List[str] = Field(default_factory=list, description="Ошибки")
    warnings: List[str] = Field(default_factory=list, description="Предупреждения")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "valid": True,
                "parsed_value": 50,
                "errors": [],
                "warnings": ["Значение 50 выше рекомендуемого (30)"]
            }
        }
    }


# =============================================
# Определение настройки
# =============================================
class SettingDefinitionResponse(BaseSchema):
    """
    Полное определение настройки (метаданные).
    """
    key: str = Field(..., description="Ключ")
    display_name: str = Field(..., description="Отображаемое имя")
    description: Optional[str] = Field(None, description="Описание")
    category: SettingCategory = Field(..., description="Категория")
    value_type: SettingValueType = Field(..., description="Тип значения")
    default_value: Any = Field(..., description="Значение по умолчанию")
    current_value: Any = Field(..., description="Текущее значение")
    
    is_public: bool = Field(True, description="Публичная")
    is_readonly: bool = Field(False, description="Только для чтения")
    is_advanced: bool = Field(False, description="Расширенная")
    requires_restart: bool = Field(False, description="Требует перезапуска")
    
    validation: Optional[Dict[str, Any]] = Field(None, description="Правила валидации")
    options: Optional[List[Dict[str, Any]]] = Field(None, description="Варианты выбора")
    
    ui_component: str = Field("input", description="Компонент UI")
    ui_props: Dict[str, Any] = Field(default_factory=dict, description="Свойства UI")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    order: int = Field(0, description="Порядок")


class SettingDefinitionsResponse(BaseSchema):
    """
    Ответ со всеми определениями настроек.
    """
    items: List[SettingDefinitionResponse] = Field(..., description="Определения")
    total: int = Field(..., description="Всего")


# =============================================
# История изменений
# =============================================
class SettingHistoryEntry(BaseSchema):
    """
    Запись истории изменений настройки.
    """
    id: int = Field(..., description="ID записи")
    key: str = Field(..., description="Ключ настройки")
    old_value: Optional[str] = Field(None, description="Старое значение")
    new_value: str = Field(..., description="Новое значение")
    changed_by: Optional[int] = Field(None, description="ID изменившего")
    changed_by_name: Optional[str] = Field(None, description="Имя изменившего")
    changed_at: datetime = Field(..., description="Дата изменения")
    reason: Optional[str] = Field(None, description="Причина изменения")
    ip_address: Optional[str] = Field(None, description="IP адрес")


class SettingHistoryResponse(BaseSchema):
    """
    Ответ с историей изменений настройки.
    """
    key: str = Field(..., description="Ключ настройки")
    items: List[SettingHistoryEntry] = Field(..., description="История")
    total: int = Field(..., description="Всего записей")


# =============================================
# Группы настроек (Profiles)
# =============================================
class SettingsProfileCreate(BaseSchema):
    """
    Запрос на создание профиля настроек.
    """
    name: str = Field(..., min_length=1, max_length=100, description="Название профиля")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Настройки")
    is_default: bool = Field(False, description="Профиль по умолчанию")


class SettingsProfileUpdate(BaseSchema):
    """
    Запрос на обновление профиля настроек.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Название")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    settings: Optional[Dict[str, Any]] = Field(None, description="Настройки")
    is_default: Optional[bool] = Field(None, description="Профиль по умолчанию")


class SettingsProfileResponse(TimestampSchema):
    """
    Ответ с информацией о профиле настроек.
    """
    id: int = Field(..., description="ID профиля")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    settings: Dict[str, Any] = Field(..., description="Настройки")
    is_default: bool = Field(False, description="По умолчанию")
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    settings_count: int = Field(0, description="Количество настроек")


class SettingsProfileListResponse(BaseSchema):
    """
    Ответ со списком профилей.
    """
    items: List[SettingsProfileResponse] = Field(..., description="Профили")
    total: int = Field(..., description="Всего профилей")


# =============================================
# Применение профиля
# =============================================
class ApplyProfileRequest(BaseSchema):
    """
    Запрос на применение профиля настроек.
    """
    profile_id: int = Field(..., description="ID профиля")
    overwrite: bool = Field(True, description="Перезаписать существующие")
    dry_run: bool = Field(False, description="Только предпросмотр")


class ApplyProfileResponse(BaseSchema):
    """
    Ответ на применение профиля.
    """
    profile_id: int = Field(..., description="ID профиля")
    profile_name: str = Field(..., description="Название профиля")
    applied: int = Field(0, description="Применено настроек")
    skipped: int = Field(0, description="Пропущено")
    changes: List[Dict[str, Any]] = Field(default_factory=list, description="Изменения")
    dry_run: bool = Field(False, description="Предпросмотр")


# =============================================
# Предопределённые настройки
# =============================================
class PredefinedSettingOption(BaseSchema):
    """Вариант значения для настройки"""
    value: str = Field(..., description="Значение")
    label: str = Field(..., description="Отображаемое имя")
    description: Optional[str] = Field(None, description="Описание")


class PredefinedSetting(BaseSchema):
    """Предопределённая настройка"""
    key: str = Field(..., description="Ключ")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    category: SettingCategory = Field(..., description="Категория")
    value_type: SettingValueType = Field(..., description="Тип")
    default_value: Any = Field(..., description="По умолчанию")
    options: Optional[List[PredefinedSettingOption]] = Field(None, description="Варианты")
    min_value: Optional[float] = Field(None, description="Мин.")
    max_value: Optional[float] = Field(None, description="Макс.")
    placeholder: Optional[str] = Field(None, description="Placeholder")
    help_text: Optional[str] = Field(None, description="Подсказка")


class PredefinedSettingsResponse(BaseSchema):
    """Ответ со списком предопределённых настроек"""
    items: List[PredefinedSetting] = Field(..., description="Настройки")
    total: int = Field(..., description="Всего")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "SettingCategory",
    "SettingValueType",
    
    # Запросы
    "SettingUpdateRequest",
    "SettingsBulkUpdateRequest",
    "SettingResetRequest",
    
    # Ответы
    "SettingResponse",
    "SettingDetailResponse",
    "SettingsListResponse",
    "SettingsByCategoryResponse",
    "SettingCategoryInfo",
    "SettingsCategoriesResponse",
    
    # Экспорт/Импорт
    "SettingsExportResponse",
    "SettingsImportRequest",
    "SettingsImportResponse",
    
    # Валидация
    "SettingValidationRequest",
    "SettingValidationResponse",
    
    # Определения
    "SettingDefinitionResponse",
    "SettingDefinitionsResponse",
    
    # История
    "SettingHistoryEntry",
    "SettingHistoryResponse",
    
    # Профили
    "SettingsProfileCreate",
    "SettingsProfileUpdate",
    "SettingsProfileResponse",
    "SettingsProfileListResponse",
    "ApplyProfileRequest",
    "ApplyProfileResponse",
    
    # Предопределённые
    "PredefinedSettingOption",
    "PredefinedSetting",
    "PredefinedSettingsResponse",
]
