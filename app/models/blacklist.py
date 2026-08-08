#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели чёрного списка
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Управления чёрным списком номеров
- Проверки номеров
- Массового импорта в чёрный список
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema
from app.utils.phone import normalize_phone, validate_phone_number, format_phone_display


# =============================================
# Enums
# =============================================
class BlacklistSource(str, Enum):
    """Источник добавления в чёрный список"""
    MANUAL = "manual"           # Вручную
    IMPORT = "import"           # Импорт
    API = "api"                 # Через API
    AUTO = "auto"               # Автоматически (после N неудачных звонков)
    COMPLAINT = "complaint"     # Жалоба абонента
    BOUNCE = "bounce"           # Несуществующий номер


class BlacklistReason(str, Enum):
    """Причина блокировки"""
    SPAM = "spam"                       # Спам
    WRONG_NUMBER = "wrong_number"       # Неверный номер
    NOT_INTERESTED = "not_interested"   # Не заинтересован
    COMPLAINT = "complaint"             # Жалоба
    DO_NOT_CALL = "do_not_call"         # Просьба не звонить
    INVALID_NUMBER = "invalid_number"   # Невалидный номер
    BOUNCE = "bounce"                   # Не существует
    NO_ANSWER = "no_answer"             # Никогда не отвечает
    OTHER = "other"                     # Другое


class BlacklistStatus(str, Enum):
    """Статус записи в чёрном списке"""
    ACTIVE = "active"           # Активна
    EXPIRED = "expired"         # Истекла
    REMOVED = "removed"         # Удалена


# =============================================
# Валидаторы
# =============================================
# normalize_phone / validate_phone_number / format_phone_display — см.
# app.utils.phone (единственный источник правил российского плана
# нумерации, импортированы выше).


# =============================================
# Запросы
# =============================================
class BlacklistAddRequest(BaseSchema):
    """
    Запрос на добавление номера в чёрный список.
    """
    phone: str = Field(..., description="Номер телефона")
    reason: BlacklistReason = Field(BlacklistReason.OTHER, description="Причина")
    reason_details: Optional[str] = Field(None, max_length=500, description="Детали причины")
    
    expires_at: Optional[datetime] = Field(None, description="Дата истечения (если временно)")
    
    source: BlacklistSource = Field(BlacklistSource.MANUAL, description="Источник")
    
    notes: Optional[str] = Field(None, max_length=500, description="Заметки")
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Валидация и нормализация номера"""
        if not v:
            raise ValueError("Номер телефона обязателен")
        
        normalized = normalize_phone(v)
        if not validate_phone_number(normalized):
            raise ValueError(f"Неверный формат номера: {v}")

        return normalized
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "phone": "+79991234567",
                "reason": "do_not_call",
                "reason_details": "Клиент попросил не звонить",
                "source": "manual",
                "notes": "Перезвонить через месяц",
                "tags": ["vip"]
            }
        }
    }


class BlacklistCheckRequest(BaseSchema):
    """
    Запрос на проверку номера в чёрном списке.
    """
    phones: List[str] = Field(..., min_length=1, max_length=1000, description="Номера для проверки")
    
    @field_validator('phones')
    @classmethod
    def validate_phones(cls, v: List[str]) -> List[str]:
        """Нормализация всех номеров"""
        return [normalize_phone(phone) for phone in v if phone]


class BlacklistRemoveRequest(BaseSchema):
    """
    Запрос на удаление из чёрного списка.
    """
    reason: Optional[str] = Field(None, max_length=500, description="Причина удаления")
    permanent: bool = Field(True, description="Перманентное удаление")


class BlacklistBulkAddRequest(BaseSchema):
    """
    Запрос на массовое добавление в чёрный список.
    """
    phones: List[str] = Field(..., min_length=1, max_length=10000, description="Номера")
    reason: BlacklistReason = Field(BlacklistReason.OTHER, description="Причина")
    reason_details: Optional[str] = Field(None, description="Детали")
    
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    source: BlacklistSource = Field(BlacklistSource.IMPORT, description="Источник")
    
    skip_existing: bool = Field(True, description="Пропускать существующие")
    skip_invalid: bool = Field(True, description="Пропускать невалидные")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    @field_validator('phones')
    @classmethod
    def normalize_phones(cls, v: List[str]) -> List[str]:
        """Нормализация номеров"""
        normalized = []
        for phone in v:
            if phone:
                norm = normalize_phone(phone)
                if norm:
                    normalized.append(norm)
        return normalized


# =============================================
# Ответы
# =============================================
class BlacklistResponse(TimestampSchema):
    """
    Ответ с информацией о записи в чёрном списке.
    """
    id: int = Field(..., description="ID записи")
    phone: str = Field(..., description="Номер телефона")
    phone_display: str = Field(..., description="Номер для отображения")
    
    reason: BlacklistReason = Field(..., description="Причина")
    reason_details: Optional[str] = Field(None, description="Детали причины")
    
    status: BlacklistStatus = Field(BlacklistStatus.ACTIVE, description="Статус")
    
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    is_expired: bool = Field(False, description="Истекла ли")
    
    source: BlacklistSource = Field(..., description="Источник")
    
    notes: Optional[str] = Field(None, description="Заметки")
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    removed_at: Optional[datetime] = Field(None, description="Дата удаления")
    removed_by: Optional[int] = Field(None, description="ID удалившего")
    removed_reason: Optional[str] = Field(None, description="Причина удаления")
    
    # Статистика
    times_called_before: int = Field(0, description="Звонков до блокировки")
    
    @model_validator(mode='after')
    def format_fields(self) -> 'BlacklistResponse':
        """Форматирование полей"""
        # Форматирование номера
        self.phone_display = format_phone_display(self.phone)
        
        # Проверка истечения
        if self.expires_at and self.status == BlacklistStatus.ACTIVE:
            self.is_expired = datetime.utcnow() > self.expires_at
        
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "phone": "79991234567",
                "phone_display": "+7 (999) 123-45-67",
                "reason": "do_not_call",
                "reason_details": "Клиент попросил не звонить",
                "status": "active",
                "source": "manual",
                "notes": "Перезвонить через месяц",
                "tags": ["vip"],
                "created_by": 1,
                "created_by_name": "admin",
                "times_called_before": 3,
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class BlacklistDetailResponse(BlacklistResponse):
    """
    Детальный ответ о записи в чёрном списке.
    """
    # История изменений
    history: List[Dict[str, Any]] = Field(default_factory=list, description="История изменений")
    
    # Связанные контакты
    contacts: List[Dict[str, Any]] = Field(default_factory=list, description="Связанные контакты")
    
    # История звонков до блокировки
    calls_before: List[Dict[str, Any]] = Field(default_factory=list, description="Звонки до блокировки")


class BlacklistListResponse(BaseSchema):
    """
    Ответ со списком записей чёрного списка.
    """
    items: List[BlacklistResponse] = Field(..., description="Записи")
    total: int = Field(..., description="Всего записей")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")
    
    # Статистика
    active_count: int = Field(0, description="Активных")
    expired_count: int = Field(0, description="Истекших")
    removed_count: int = Field(0, description="Удалённых")


class BlacklistCheckResponse(BaseSchema):
    """
    Ответ на проверку номера в чёрном списке.
    """
    phone: str = Field(..., description="Номер")
    is_blacklisted: bool = Field(..., description="В чёрном списке")
    
    record: Optional[BlacklistResponse] = Field(None, description="Запись (если есть)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "phone": "79991234567",
                "is_blacklisted": True,
                "record": {
                    "id": 1,
                    "reason": "do_not_call",
                    "status": "active"
                }
            }
        }
    }


class BlacklistBulkCheckResponse(BaseSchema):
    """
    Ответ на массовую проверку номеров.
    """
    results: List[BlacklistCheckResponse] = Field(..., description="Результаты проверки")
    
    total: int = Field(..., description="Всего проверено")
    blacklisted: int = Field(..., description="В чёрном списке")
    clean: int = Field(..., description="Чистых")
    
    @property
    def blacklisted_percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.blacklisted / self.total * 100, 2)


class BlacklistBulkAddResponse(BaseSchema):
    """
    Ответ на массовое добавление в чёрный список.
    """
    total: int = Field(..., description="Всего в запросе")
    added: int = Field(0, description="Добавлено")
    skipped: int = Field(0, description="Пропущено (уже существуют)")
    invalid: int = Field(0, description="Невалидные номера")
    
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")
    
    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 100.0
        return round(self.added / self.total * 100, 2)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "total": 100,
                "added": 85,
                "skipped": 10,
                "invalid": 5,
                "errors": [
                    {"phone": "123", "error": "Invalid phone number"}
                ]
            }
        }
    }


class BlacklistRemoveResponse(BaseSchema):
    """
    Ответ на удаление из чёрного списка.
    """
    success: bool = Field(True, description="Успешно")
    message: str = Field(..., description="Сообщение")
    phone: str = Field(..., description="Номер")
    removed: bool = Field(True, description="Удалена")


class BlacklistBulkRemoveResponse(BaseSchema):
    """
    Ответ на массовое удаление из чёрного списка.
    """
    total: int = Field(..., description="Всего")
    removed: int = Field(0, description="Удалено")
    not_found: int = Field(0, description="Не найдено")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")


# =============================================
# Статистика
# =============================================
class BlacklistStatsResponse(BaseSchema):
    """
    Статистика чёрного списка.
    """
    total_records: int = Field(0, description="Всего записей")
    active_records: int = Field(0, description="Активных")
    expired_records: int = Field(0, description="Истекших")
    removed_records: int = Field(0, description="Удалённых")
    
    # По причинам
    by_reason: Dict[str, int] = Field(default_factory=dict, description="По причинам")
    
    # По источникам
    by_source: Dict[str, int] = Field(default_factory=dict, description="По источникам")
    
    # По времени
    added_today: int = Field(0, description="Добавлено сегодня")
    added_this_week: int = Field(0, description="Добавлено за неделю")
    added_this_month: int = Field(0, description="Добавлено за месяц")
    
    removed_today: int = Field(0, description="Удалено сегодня")
    
    # Топ причин
    top_reasons: List[Dict[str, Any]] = Field(default_factory=list, description="Топ причин")


# =============================================
# Фильтры
# =============================================
class BlacklistFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию чёрного списка.
    """
    search: Optional[str] = Field(None, description="Поиск по номеру")
    
    reason: Optional[List[BlacklistReason]] = Field(None, description="Причины")
    status: Optional[List[BlacklistStatus]] = Field(None, description="Статусы")
    source: Optional[List[BlacklistSource]] = Field(None, description="Источники")
    
    tags: Optional[List[str]] = Field(None, description="Теги")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    
    created_after: Optional[datetime] = Field(None, description="Создана после")
    created_before: Optional[datetime] = Field(None, description="Создана до")
    
    expires_before: Optional[datetime] = Field(None, description="Истекает до")
    expires_after: Optional[datetime] = Field(None, description="Истекает после")
    
    include_expired: bool = Field(True, description="Включать истекшие")
    include_removed: bool = Field(False, description="Включать удалённые")
    
    sort_by: str = Field("created_at", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "BlacklistSource",
    "BlacklistReason",
    "BlacklistStatus",
    
    # Валидаторы
    "normalize_phone",
    
    # Запросы
    "BlacklistAddRequest",
    "BlacklistCheckRequest",
    "BlacklistRemoveRequest",
    "BlacklistBulkAddRequest",
    
    # Ответы
    "BlacklistResponse",
    "BlacklistDetailResponse",
    "BlacklistListResponse",
    "BlacklistCheckResponse",
    "BlacklistBulkCheckResponse",
    "BlacklistBulkAddResponse",
    "BlacklistRemoveResponse",
    "BlacklistBulkRemoveResponse",
    
    # Статистика
    "BlacklistStatsResponse",
    
    # Фильтры
    "BlacklistFilterRequest",
]
