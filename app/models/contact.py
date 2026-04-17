#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели контактов и групп контактов
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Создания и обновления контактов
- Групп контактов
- Массового импорта контактов
- Валидации номеров телефонов
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from enum import Enum
import re
from pydantic import Field, EmailStr, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class ContactStatus(str, Enum):
    """Статус контакта"""
    ACTIVE = "active"           # Активный
    INACTIVE = "inactive"       # Неактивный
    BLOCKED = "blocked"         # Заблокирован (вручную)
    BLACKLISTED = "blacklisted" # В чёрном списке
    ERROR = "error"             # Ошибка (неверный номер)


class ContactSource(str, Enum):
    """Источник контакта"""
    MANUAL = "manual"           # Добавлен вручную
    IMPORT = "import"           # Импортирован
    API = "api"                 # Через API
    WEBHOOK = "webhook"         # Через вебхук
    INCOMING_CALL = "incoming"  # Из входящего звонка


class ContactGender(str, Enum):
    """Пол контакта"""
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


# =============================================
# Валидаторы
# =============================================
def normalize_phone(phone: str) -> str:
    """
    Нормализация номера телефона.
    Приводит к международному формату.
    """
    if not phone:
        return ""
    
    # Удаляем все не-цифры
    digits = re.sub(r'[^\d]', '', phone)
    
    # Российские номера
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 11 and digits.startswith('7'):
        pass  # Уже в правильном формате
    elif len(digits) == 10 and digits.startswith('9'):
        digits = '7' + digits
    
    return digits


def validate_phone_number(phone: str) -> bool:
    """
    Проверка корректности номера телефона.
    """
    digits = normalize_phone(phone)
    
    if len(digits) < 10:
        return False
    
    # Проверка российских номеров
    if digits.startswith('7'):
        if len(digits) != 11:
            return False
        # Проверка кода оператора/региона
        if digits[1] == '0' or digits[1] == '1':
            return False
    
    # Международные номера (до 15 цифр)
    if len(digits) > 15:
        return False
    
    return True


def format_phone_display(phone: str) -> str:
    """
    Форматирование номера для отображения.
    """
    digits = normalize_phone(phone)
    
    if len(digits) == 11 and digits.startswith('7'):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    
    if len(digits) == 10:
        return f"+7 ({digits[0:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}"
    
    # Для других форматов просто добавляем +
    return f"+{digits}"


# =============================================
# Пользовательские поля
# =============================================
class CustomFieldDefinition(BaseSchema):
    """
    Определение пользовательского поля.
    """
    name: str = Field(..., description="Имя поля")
    label: str = Field(..., description="Отображаемое название")
    field_type: str = Field(..., description="Тип поля (text, number, date, select, etc.)")
    required: bool = Field(False, description="Обязательное")
    options: Optional[List[str]] = Field(None, description="Варианты для select")
    default_value: Optional[Any] = Field(None, description="Значение по умолчанию")
    order: int = Field(0, description="Порядок отображения")


# =============================================
# Запросы для контактов
# =============================================
class ContactCreateRequest(BaseSchema):
    """
    Запрос на создание контакта.
    """
    phone: str = Field(..., description="Номер телефона")
    name: Optional[str] = Field(None, max_length=255, description="Имя")
    email: Optional[EmailStr] = Field(None, description="Email")
    
    # Дополнительные телефоны
    phone2: Optional[str] = Field(None, description="Дополнительный телефон")
    phone3: Optional[str] = Field(None, description="Дополнительный телефон")
    
    # Личные данные
    gender: ContactGender = Field(ContactGender.UNKNOWN, description="Пол")
    birth_date: Optional[datetime] = Field(None, description="Дата рождения")
    company: Optional[str] = Field(None, max_length=255, description="Компания")
    position: Optional[str] = Field(None, max_length=255, description="Должность")
    
    # Адрес
    country: Optional[str] = Field(None, max_length=100, description="Страна")
    region: Optional[str] = Field(None, max_length=100, description="Регион")
    city: Optional[str] = Field(None, max_length=100, description="Город")
    address: Optional[str] = Field(None, max_length=500, description="Адрес")
    postal_code: Optional[str] = Field(None, max_length=20, description="Индекс")
    
    # Группы и теги
    group_id: Optional[int] = Field(None, description="ID группы")
    group_ids: Optional[List[int]] = Field(None, description="ID групп (несколько)")
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    # Пользовательские поля
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="Пользовательские поля")
    
    # Заметки
    notes: Optional[str] = Field(None, description="Заметки")
    
    # Источник
    source: ContactSource = Field(ContactSource.MANUAL, description="Источник")
    
    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Валидация и нормализация телефона"""
        if not v:
            raise ValueError("Номер телефона обязателен")
        
        normalized = normalize_phone(v)
        if not validate_phone_number(normalized):
            raise ValueError(f"Неверный формат номера телефона: {v}")
        
        return normalized
    
    @field_validator('phone2', 'phone3')
    @classmethod
    def validate_optional_phone(cls, v: Optional[str]) -> Optional[str]:
        if v:
            normalized = normalize_phone(v)
            if not validate_phone_number(normalized):
                raise ValueError(f"Неверный формат номера телефона: {v}")
            return normalized
        return v
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.lower().strip()
        return v
    
    @field_validator('name', 'company', 'position')
    @classmethod
    def strip_strings(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip()
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "phone": "+7 (999) 123-45-67",
                "name": "Иван Петров",
                "email": "ivan@example.com",
                "company": "ООО Ромашка",
                "position": "Директор",
                "group_id": 1,
                "tags": ["vip", "клиент"],
                "custom_fields": {
                    "inn": "1234567890",
                    "comment": "Важный клиент"
                },
                "notes": "Перезвонить после обеда"
            }
        }
    }


class ContactUpdateRequest(BaseSchema):
    """
    Запрос на обновление контакта.
    """
    name: Optional[str] = Field(None, max_length=255, description="Имя")
    email: Optional[EmailStr] = Field(None, description="Email")
    
    phone2: Optional[str] = Field(None, description="Дополнительный телефон")
    phone3: Optional[str] = Field(None, description="Дополнительный телефон")
    
    gender: Optional[ContactGender] = Field(None, description="Пол")
    birth_date: Optional[datetime] = Field(None, description="Дата рождения")
    company: Optional[str] = Field(None, max_length=255, description="Компания")
    position: Optional[str] = Field(None, max_length=255, description="Должность")
    
    country: Optional[str] = Field(None, max_length=100, description="Страна")
    region: Optional[str] = Field(None, max_length=100, description="Регион")
    city: Optional[str] = Field(None, max_length=100, description="Город")
    address: Optional[str] = Field(None, max_length=500, description="Адрес")
    postal_code: Optional[str] = Field(None, max_length=20, description="Индекс")
    
    group_id: Optional[int] = Field(None, description="ID группы")
    tags: Optional[List[str]] = Field(None, description="Теги")
    custom_fields: Optional[Dict[str, Any]] = Field(None, description="Пользовательские поля")
    notes: Optional[str] = Field(None, description="Заметки")
    status: Optional[ContactStatus] = Field(None, description="Статус")
    
    @field_validator('phone2', 'phone3')
    @classmethod
    def validate_optional_phone(cls, v: Optional[str]) -> Optional[str]:
        if v:
            normalized = normalize_phone(v)
            if not validate_phone_number(normalized):
                raise ValueError(f"Неверный формат номера телефона: {v}")
            return normalized
        return v


class ContactBulkImportRequest(BaseSchema):
    """
    Запрос на массовый импорт контактов.
    """
    group_id: Optional[int] = Field(None, description="ID группы для импорта")
    group_ids: Optional[List[int]] = Field(None, description="ID групп (распределить контакты)")
    
    contacts: List[Dict[str, str]] = Field(
        ..., 
        min_length=1, 
        max_length=50000,
        description="Список контактов"
    )
    
    skip_duplicates: bool = Field(True, description="Пропускать дубликаты")
    skip_blacklisted: bool = Field(True, description="Пропускать номера из чёрного списка")
    skip_invalid: bool = Field(True, description="Пропускать невалидные номера")
    
    update_existing: bool = Field(False, description="Обновлять существующие контакты")
    update_fields: Optional[List[str]] = Field(None, description="Поля для обновления")
    
    tags: List[str] = Field(default_factory=list, description="Теги для всех импортируемых контактов")
    source: ContactSource = Field(ContactSource.IMPORT, description="Источник")
    
    field_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Маппинг полей (имя в файле -> поле в БД)"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "group_id": 1,
                "contacts": [
                    {"phone": "79991234567", "name": "Иван", "email": "ivan@mail.ru"},
                    {"phone": "79997654321", "name": "Мария"}
                ],
                "skip_duplicates": True,
                "skip_blacklisted": True,
                "field_mapping": {
                    "phone": "phone",
                    "name": "name",
                    "email": "email"
                }
            }
        }
    }


# =============================================
# Ответы для контактов
# =============================================
class ContactResponse(BaseSchema, TimestampSchema):
    """
    Ответ с информацией о контакте.
    """
    id: int = Field(..., description="ID контакта")
    phone: str = Field(..., description="Номер телефона")
    phone_display: str = Field(..., description="Номер для отображения")
    
    name: Optional[str] = Field(None, description="Имя")
    email: Optional[str] = Field(None, description="Email")
    
    phone2: Optional[str] = Field(None, description="Дополнительный телефон")
    phone3: Optional[str] = Field(None, description="Дополнительный телефон")
    
    gender: ContactGender = Field(ContactGender.UNKNOWN, description="Пол")
    birth_date: Optional[datetime] = Field(None, description="Дата рождения")
    company: Optional[str] = Field(None, description="Компания")
    position: Optional[str] = Field(None, description="Должность")
    
    country: Optional[str] = Field(None, description="Страна")
    region: Optional[str] = Field(None, description="Регион")
    city: Optional[str] = Field(None, description="Город")
    address: Optional[str] = Field(None, description="Адрес")
    postal_code: Optional[str] = Field(None, description="Индекс")
    
    group_id: Optional[int] = Field(None, description="ID основной группы")
    group_name: Optional[str] = Field(None, description="Название группы")
    group_ids: List[int] = Field(default_factory=list, description="ID всех групп")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="Пользовательские поля")
    notes: Optional[str] = Field(None, description="Заметки")
    
    status: ContactStatus = Field(ContactStatus.ACTIVE, description="Статус")
    blacklisted: bool = Field(False, description="В чёрном списке")
    blacklist_reason: Optional[str] = Field(None, description="Причина блокировки")
    
    source: ContactSource = Field(ContactSource.MANUAL, description="Источник")
    
    # Статистика звонков
    last_call_at: Optional[datetime] = Field(None, description="Последний звонок")
    last_call_status: Optional[str] = Field(None, description="Статус последнего звонка")
    total_calls: int = Field(0, description="Всего звонков")
    successful_calls: int = Field(0, description="Успешных звонков")
    
    # DND (Do Not Disturb)
    dnd: bool = Field(False, description="Не беспокоить")
    dnd_until: Optional[datetime] = Field(None, description="Не беспокоить до")
    
    # Счётчики
    view_count: int = Field(0, description="Просмотров")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "phone": "79991234567",
                "phone_display": "+7 (999) 123-45-67",
                "name": "Иван Петров",
                "email": "ivan@example.com",
                "company": "ООО Ромашка",
                "position": "Директор",
                "group_id": 1,
                "group_name": "VIP клиенты",
                "tags": ["vip"],
                "status": "active",
                "total_calls": 3,
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class ContactDetailResponse(ContactResponse):
    """
    Детальный ответ о контакте.
    """
    recent_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Последние звонки")
    campaigns: List[Dict[str, Any]] = Field(default_factory=list, description="Кампании с участием")
    notes_history: List[Dict[str, Any]] = Field(default_factory=list, description="История заметок")


class ContactListResponse(BaseSchema):
    """
    Ответ со списком контактов.
    """
    items: List[ContactResponse] = Field(..., description="Контакты")
    total: int = Field(..., description="Всего контактов")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")


class ContactBulkImportResponse(BaseSchema):
    """
    Ответ на массовый импорт контактов.
    """
    total: int = Field(..., description="Всего в запросе")
    imported: int = Field(0, description="Импортировано")
    updated: int = Field(0, description="Обновлено")
    skipped: int = Field(0, description="Пропущено")
    duplicates: int = Field(0, description="Дубликаты")
    blacklisted: int = Field(0, description="В чёрном списке")
    invalid: int = Field(0, description="Невалидные номера")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")
    
    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 100.0
        return round((self.imported + self.updated) / self.total * 100, 2)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "total": 100,
                "imported": 85,
                "updated": 5,
                "skipped": 5,
                "duplicates": 3,
                "blacklisted": 1,
                "invalid": 1,
                "errors": [
                    {"row": 15, "phone": "123", "error": "Invalid phone number"}
                ]
            }
        }
    }


# =============================================
# Группы контактов
# =============================================
class ContactGroupCreateRequest(BaseSchema):
    """
    Запрос на создание группы контактов.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название группы")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    color: str = Field("#667eea", pattern=r'^#[0-9A-Fa-f]{6}$', description="Цвет (HEX)")
    parent_id: Optional[int] = Field(None, description="ID родительской группы")
    is_public: bool = Field(False, description="Публичная группа")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return v.strip()
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "VIP клиенты",
                "description": "Важные клиенты",
                "color": "#ff4757",
                "is_public": False
            }
        }
    }


class ContactGroupUpdateRequest(BaseSchema):
    """
    Запрос на обновление группы контактов.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$', description="Цвет")
    parent_id: Optional[int] = Field(None, description="ID родительской группы")
    is_public: Optional[bool] = Field(None, description="Публичная группа")


class ContactGroupResponse(BaseSchema, TimestampSchema):
    """
    Ответ с информацией о группе контактов.
    """
    id: int = Field(..., description="ID группы")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    color: str = Field(..., description="Цвет")
    parent_id: Optional[int] = Field(None, description="ID родительской группы")
    parent_name: Optional[str] = Field(None, description="Название родительской группы")
    is_public: bool = Field(False, description="Публичная группа")
    
    contacts_count: int = Field(0, description="Количество контактов")
    active_contacts_count: int = Field(0, description="Активных контактов")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    children: List['ContactGroupResponse'] = Field(default_factory=list, description="Дочерние группы")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "VIP клиенты",
                "description": "Важные клиенты",
                "color": "#ff4757",
                "contacts_count": 42,
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class ContactGroupListResponse(BaseSchema):
    """
    Ответ со списком групп контактов.
    """
    items: List[ContactGroupResponse] = Field(..., description="Группы")
    total: int = Field(..., description="Всего групп")
    tree: Optional[List[ContactGroupResponse]] = Field(None, description="Древовидная структура")


# =============================================
# Фильтры контактов
# =============================================
class ContactFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию контактов.
    """
    search: Optional[str] = Field(None, description="Поиск по имени, телефону, email")
    group_ids: Optional[List[int]] = Field(None, description="ID групп")
    exclude_group_ids: Optional[List[int]] = Field(None, description="Исключить группы")
    
    status: Optional[List[ContactStatus]] = Field(None, description="Статусы")
    tags: Optional[List[str]] = Field(None, description="Теги (любой из)")
    tags_all: Optional[List[str]] = Field(None, description="Теги (все)")
    
    has_calls: Optional[bool] = Field(None, description="Есть звонки")
    last_call_after: Optional[datetime] = Field(None, description="Последний звонок после")
    last_call_before: Optional[datetime] = Field(None, description="Последний звонок до")
    
    created_after: Optional[datetime] = Field(None, description="Создан после")
    created_before: Optional[datetime] = Field(None, description="Создан до")
    
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="Фильтр по пользовательским полям")
    
    sort_by: str = Field("id", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "ContactStatus",
    "ContactSource",
    "ContactGender",
    
    # Валидаторы
    "normalize_phone",
    "validate_phone_number",
    "format_phone_display",
    
    # Пользовательские поля
    "CustomFieldDefinition",
    
    # Запросы для контактов
    "ContactCreateRequest",
    "ContactUpdateRequest",
    "ContactBulkImportRequest",
    
    # Ответы для контактов
    "ContactResponse",
    "ContactDetailResponse",
    "ContactListResponse",
    "ContactBulkImportResponse",
    
    # Группы контактов
    "ContactGroupCreateRequest",
    "ContactGroupUpdateRequest",
    "ContactGroupResponse",
    "ContactGroupListResponse",
    
    # Фильтры
    "ContactFilterRequest",
]
