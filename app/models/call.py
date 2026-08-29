#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели звонков и результатов обзвона
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Результатов звонков (CallResult)
- Истории звонков
- Статистики звонков
- Фильтрации истории
"""

import datetime as dt
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema
from app.utils.phone import normalize_phone, format_phone_display


# =============================================
# Enums
# =============================================
class CallResultStatus(str, Enum):
    """Статус результата звонка"""
    AGREED = "agreed"           # Согласился
    DECLINED = "declined"       # Отказался
    BUSY = "busy"               # Занято
    NOANSWER = "noanswer"       # Нет ответа
    FAILED = "failed"           # Ошибка
    TIMEOUT = "timeout"         # Таймаут
    CANCELED = "canceled"       # Отменён
    MACHINE = "machine"         # Автоответчик
    CONGESTION = "congestion"   # Перегрузка сети
    CHANUNAVAIL = "chanunavail" # Канал недоступен
    UNKNOWN = "unknown"         # Неизвестно
    ANNOUNCED = "announced"     # Объявление проиграно (DTMF-меню отключено для кампании)

    # DTMF 4/5-9/0/*/# - диалплан (asterisk/extensions.conf, [sub-media])
    # шлёт эти статусы в UserEvent(DialerResult,...) уже давно, но этого
    # enum'а они никогда не покрывали - dialer.py:_save_call_result()
    # молча подменял любой status не из этого списка на FAILED, то есть
    # "абонент нажал 5" в истории неотличимо выглядело как "Ошибка".
    # Подтверждено живьём на тестовом сервере.
    OPERATOR = "operator"       # DTMF 4 - запрос оператора
    CUSTOM_0 = "custom0"        # DTMF 0 - произвольное действие кампании
    CUSTOM_5 = "custom5"        # DTMF 5 - произвольное действие кампании
    CUSTOM_6 = "custom6"        # DTMF 6 - произвольное действие кампании
    CUSTOM_7 = "custom7"        # DTMF 7 - произвольное действие кампании
    CUSTOM_8 = "custom8"        # DTMF 8 - произвольное действие кампании
    CUSTOM_9 = "custom9"        # DTMF 9 - произвольное действие кампании
    STAR = "star"               # DTMF * - произвольное действие кампании
    HASH = "hash"               # DTMF # - произвольное действие кампании
    INVALID_DTMF = "invalid_dtmf"  # Введена цифра вне обработанного диапазона


class CallDirection(str, Enum):
    """Направление звонка"""
    OUTBOUND = "outbound"   # Исходящий
    INBOUND = "inbound"     # Входящий
    INTERNAL = "internal"   # Внутренний


class HangupCause(str, Enum):
    """Причина завершения звонка (Asterisk)"""
    NORMAL_CLEARING = "16"              # Нормальное завершение
    USER_BUSY = "17"                    # Занято
    NO_ANSWER = "19"                    # Нет ответа
    NO_USER_RESPONSE = "18"             # Нет ответа пользователя
    CALL_REJECTED = "21"                # Звонок отклонён
    NUMBER_CHANGED = "22"               # Номер изменён
    DESTINATION_OUT_OF_ORDER = "27"     # Назначение недоступно
    INVALID_NUMBER_FORMAT = "28"        # Неверный формат номера
    FACILITY_REJECTED = "29"            # Услуга отклонена
    NORMAL_UNSPECIFIED = "31"           # Нормальное (без уточнения)
    NO_CIRCUIT_CHANNEL = "34"           # Нет канала
    NETWORK_OUT_OF_ORDER = "38"         # Сеть недоступна
    TEMPORARY_FAILURE = "41"            # Временная ошибка
    CONGESTION = "42"                   # Перегрузка
    BEARERCAPABILITY_NOTAVAIL = "58"    # Носитель недоступен
    SERVICE_UNAVAILABLE = "63"          # Сервис недоступен
    RECOVERY_ON_TIMER_EXPIRE = "102"    # Восстановление по таймеру
    ORIGINATOR_CANCEL = "487"           # Отмена инициатором


class DTMFResult(str, Enum):
    """Результат DTMF (нажатые клавиши)"""
    DIGIT_1 = "1"
    DIGIT_2 = "2"
    DIGIT_3 = "3"
    DIGIT_4 = "4"
    DIGIT_5 = "5"
    DIGIT_6 = "6"
    DIGIT_7 = "7"
    DIGIT_8 = "8"
    DIGIT_9 = "9"
    DIGIT_0 = "0"
    DIGIT_STAR = "*"
    DIGIT_HASH = "#"
    NO_INPUT = "no_input"
    TIMEOUT = "timeout"
    INVALID = "invalid"


# =============================================
# Запросы
# =============================================
class CallResultCreateRequest(BaseSchema):
    """
    Запрос на создание результата звонка.
    (Обычно создаётся автоматически системой)
    """
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    contact_id: Optional[int] = Field(None, description="ID контакта")
    phone: str = Field(..., description="Номер телефона")
    
    status: CallResultStatus = Field(..., description="Статус результата")
    dtmf_result: Optional[str] = Field(None, max_length=10, description="DTMF результат")
    
    duration: Optional[int] = Field(None, ge=0, description="Длительность звонка (сек)")
    billable_seconds: Optional[int] = Field(None, ge=0, description="Оплачиваемые секунды")
    
    hangup_cause: Optional[str] = Field(None, description="Причина завершения")
    hangup_cause_code: Optional[int] = Field(None, description="Код причины")
    
    retry_count: int = Field(0, ge=0, description="Номер попытки")
    
    recording_path: Optional[str] = Field(None, description="Путь к записи")
    
    unique_id: Optional[str] = Field(None, description="Unique ID Asterisk")
    linked_id: Optional[str] = Field(None, description="Linked ID Asterisk")
    channel: Optional[str] = Field(None, description="Канал")
    caller_id: Optional[str] = Field(None, description="Caller ID")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """
        Нормализация телефона (см. app.utils.phone) — важно приводить
        ведущую "8" к коду страны "7", иначе запись результата звонка
        не совпадёт с contacts.phone (там всегда 7XXXXXXXXXX) и может
        обойти проверку чёрного списка.
        """
        return normalize_phone(v)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "campaign_id": 1,
                "contact_id": 123,
                "phone": "79991234567",
                "status": "agreed",
                "dtmf_result": "1",
                "duration": 45,
                "hangup_cause": "Normal Clearing",
                "hangup_cause_code": 16,
                "retry_count": 0,
                "recording_path": "/var/spool/asterisk/monitor/2024/01/01/call_123.wav",
                "unique_id": "1704067200.123"
            }
        }
    }


class CallHistoryFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию истории звонков.
    """
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    contact_id: Optional[int] = Field(None, description="ID контакта")
    
    status: Optional[List[CallResultStatus]] = Field(None, description="Статусы")
    direction: Optional[CallDirection] = Field(None, description="Направление")
    
    phone: Optional[str] = Field(None, description="Номер телефона (поиск)")
    
    from_date: Optional[date] = Field(None, description="С даты")
    to_date: Optional[date] = Field(None, description="По дату")
    
    min_duration: Optional[int] = Field(None, ge=0, description="Мин. длительность")
    max_duration: Optional[int] = Field(None, ge=0, description="Макс. длительность")
    
    has_recording: Optional[bool] = Field(None, description="Есть запись")
    dtmf_result: Optional[str] = Field(None, description="DTMF результат")
    
    tags: Optional[List[str]] = Field(None, description="Теги")
    
    sort_by: str = Field("created_at", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Ответы
# =============================================
class CallResultResponse(TimestampSchema):
    """
    Ответ с информацией о результате звонка.
    """
    id: int = Field(..., description="ID записи")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    campaign_name: Optional[str] = Field(None, description="Название кампании")
    
    contact_id: Optional[int] = Field(None, description="ID контакта")
    contact_name: Optional[str] = Field(None, description="Имя контакта")
    phone: str = Field(..., description="Номер телефона")
    phone_display: str = Field(..., description="Номер для отображения")
    
    status: CallResultStatus = Field(..., description="Статус")
    direction: CallDirection = Field(CallDirection.OUTBOUND, description="Направление")
    
    dtmf_result: Optional[str] = Field(None, description="DTMF результат")
    dtmf_digits: Optional[List[str]] = Field(None, description="Все нажатые цифры")
    
    duration: Optional[int] = Field(None, description="Длительность (сек)")
    duration_formatted: Optional[str] = Field(None, description="Длительность (формат ММ:СС)")
    billable_seconds: Optional[int] = Field(None, description="Оплачиваемые секунды")
    
    hangup_cause: Optional[str] = Field(None, description="Причина завершения")
    hangup_cause_code: Optional[int] = Field(None, description="Код причины")
    
    retry_count: int = Field(0, description="Номер попытки")
    
    recording_path: Optional[str] = Field(None, description="Путь к записи")
    recording_url: Optional[str] = Field(None, description="URL для скачивания")
    recording_size: Optional[int] = Field(None, description="Размер записи (байт)")
    
    unique_id: Optional[str] = Field(None, description="Unique ID")
    linked_id: Optional[str] = Field(None, description="Linked ID")
    channel: Optional[str] = Field(None, description="Канал")
    caller_id: Optional[str] = Field(None, description="Caller ID")
    
    wait_time: Optional[int] = Field(None, description="Время ожидания ответа (сек)")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    tags: List[str] = Field(default_factory=list, description="Теги")
    notes: Optional[str] = Field(None, description="Заметки")
    
    @model_validator(mode='after')
    def format_fields(self) -> 'CallResultResponse':
        """Форматирование полей"""
        if self.duration:
            minutes = self.duration // 60
            seconds = self.duration % 60
            self.duration_formatted = f"{minutes:02d}:{seconds:02d}"
        
        if self.phone:
            self.phone_display = format_phone_display(self.phone)
        
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "campaign_id": 1,
                "campaign_name": "Тестовая кампания",
                "contact_id": 123,
                "contact_name": "Иван Петров",
                "phone": "79991234567",
                "phone_display": "+7 (999) 123-45-67",
                "status": "agreed",
                "direction": "outbound",
                "dtmf_result": "1",
                "duration": 45,
                "duration_formatted": "00:45",
                "hangup_cause": "Normal Clearing",
                "retry_count": 0,
                "recording_url": "/api/calls/1/recording",
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class CallDetailResponse(CallResultResponse):
    """
    Детальный ответ о звонке.
    """
    # Дополнительная информация о кампании
    campaign_status: Optional[str] = Field(None, description="Статус кампании")
    
    # Дополнительная информация о контакте
    contact_email: Optional[str] = Field(None, description="Email контакта")
    contact_company: Optional[str] = Field(None, description="Компания контакта")
    contact_tags: List[str] = Field(default_factory=list, description="Теги контакта")
    
    # Информация об операторе (если был)
    operator_id: Optional[int] = Field(None, description="ID оператора")
    operator_name: Optional[str] = Field(None, description="Имя оператора")
    
    # События звонка
    events: List[Dict[str, Any]] = Field(default_factory=list, description="События звонка")
    
    # Связанные звонки (повторы)
    related_calls: List['CallResultResponse'] = Field(default_factory=list, description="Связанные звонки")
    
    # Транскрибация (если есть)
    transcription: Optional[str] = Field(None, description="Транскрибация записи")
    transcription_status: Optional[str] = Field(None, description="Статус транскрибации")


class CallListResponse(BaseSchema):
    """
    Ответ со списком звонков.
    """
    items: List[CallResultResponse] = Field(..., description="Звонки")
    total: int = Field(..., description="Всего звонков")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")
    
    # Агрегированная статистика по результатам
    summary: Dict[str, int] = Field(default_factory=dict, description="Сводка по статусам")


class CallHistoryResponse(CallListResponse):
    """
    Ответ с историей звонков (псевдоним для CallListResponse).
    """
    pass


# =============================================
# Статистика звонков
# =============================================
class CallStatsResponse(BaseSchema):
    """
    Статистика звонков (для кампании или общая).
    """
    # Период
    from_date: Optional[date] = Field(None, description="С даты")
    to_date: Optional[date] = Field(None, description="По дату")
    
    # Общие показатели
    total_calls: int = Field(0, description="Всего звонков")
    answered_calls: int = Field(0, description="Отвеченных")
    unique_contacts: int = Field(0, description="Уникальных контактов")
    
    # Статусы
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    busy: int = Field(0, description="Занято")
    noanswer: int = Field(0, description="Нет ответа")
    failed: int = Field(0, description="Ошибки")
    timeout: int = Field(0, description="Таймауты")
    machine: int = Field(0, description="Автоответчик")
    canceled: int = Field(0, description="Отменено")
    congestion: int = Field(0, description="Перегрузка")
    
    # Метрики
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    
    # Длительность
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_duration: int = Field(0, description="Общая длительность (сек)")
    avg_wait_time: float = Field(0.0, description="Среднее ожидание (сек)")
    max_duration: int = Field(0, description="Макс. длительность (сек)")
    min_duration: int = Field(0, description="Мин. длительность (сек)")
    
    # DTMF
    dtmf_stats: Dict[str, int] = Field(default_factory=dict, description="Статистика DTMF")
    
    # По часам
    calls_by_hour: Dict[int, int] = Field(default_factory=dict, description="Звонки по часам")
    
    # По дням недели
    calls_by_weekday: Dict[int, int] = Field(default_factory=dict, description="Звонки по дням недели")


class DailyCallStatsResponse(BaseSchema):
    """
    Дневная статистика звонков.
    """
    date: dt.date = Field(..., description="Дата")
    total: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    busy: int = Field(0, description="Занято")
    noanswer: int = Field(0, description="Нет ответа")
    failed: int = Field(0, description="Ошибки")
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность")


class HourlyCallStatsResponse(BaseSchema):
    """
    Почасовая статистика звонков.
    """
    hour: int = Field(..., ge=0, le=23, description="Час")
    total: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")


# =============================================
# Аналитика
# =============================================
class CallAnalyticsResponse(BaseSchema):
    """
    Расширенная аналитика по звонкам.
    """
    period_days: int = Field(..., description="Период в днях")
    
    # Тренды
    daily_stats: List[DailyCallStatsResponse] = Field(default_factory=list, description="По дням")
    hourly_stats: List[HourlyCallStatsResponse] = Field(default_factory=list, description="По часам")
    
    # Топы
    top_campaigns: List[Dict[str, Any]] = Field(default_factory=list, description="Топ кампаний")
    top_contacts: List[Dict[str, Any]] = Field(default_factory=list, description="Топ контактов")
    top_phones: List[Dict[str, Any]] = Field(default_factory=list, description="Топ номеров")
    
    # Причины завершения
    hangup_causes: Dict[str, int] = Field(default_factory=dict, description="Причины завершения")
    
    # Эффективность по времени
    best_hours: List[int] = Field(default_factory=list, description="Лучшие часы")
    best_weekdays: List[int] = Field(default_factory=list, description="Лучшие дни недели")
    
    # Рекомендации
    recommendations: List[str] = Field(default_factory=list, description="Рекомендации")


# =============================================
# Активные звонки
# =============================================
class ActiveCallResponse(BaseSchema):
    """
    Информация об активном звонке.
    """
    unique_id: str = Field(..., description="Unique ID")
    linked_id: Optional[str] = Field(None, description="Linked ID")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    campaign_name: Optional[str] = Field(None, description="Название кампании")
    
    contact_id: Optional[int] = Field(None, description="ID контакта")
    contact_name: Optional[str] = Field(None, description="Имя контакта")
    phone: str = Field(..., description="Номер телефона")
    
    status: str = Field(..., description="Статус (dialing/ringing/answered)")
    state: str = Field(..., description="Состояние канала")
    
    channel: str = Field(..., description="Канал")
    caller_id: str = Field(..., description="Caller ID")
    
    started_at: datetime = Field(..., description="Время начала")
    duration: int = Field(0, description="Длительность (сек)")
    
    wait_time: int = Field(0, description="Время ожидания (сек)")
    
    retry_count: int = Field(0, description="Номер попытки")


class ActiveCallsResponse(BaseSchema):
    """
    Ответ со списком активных звонков.
    """
    total: int = Field(..., description="Всего активных звонков")
    calls: List[ActiveCallResponse] = Field(default_factory=list, description="Активные звонки")
    max_calls: int = Field(..., description="Максимум одновременных звонков")


# =============================================
# События звонка (для WebSocket)
# =============================================
class CallEventResponse(BaseSchema):
    """
    Событие звонка (для WebSocket).
    """
    event: str = Field(..., description="Тип события (dial_begin/dial_end/answer/hangup/dtmf)")
    
    unique_id: str = Field(..., description="Unique ID")
    linked_id: Optional[str] = Field(None, description="Linked ID")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    campaign_name: Optional[str] = Field(None, description="Название кампании")
    
    phone: Optional[str] = Field(None, description="Номер телефона")
    contact_name: Optional[str] = Field(None, description="Имя контакта")
    
    status: Optional[str] = Field(None, description="Статус")
    dtmf: Optional[str] = Field(None, description="DTMF цифра")
    
    duration: Optional[int] = Field(None, description="Длительность")
    
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время события")
    
    data: Dict[str, Any] = Field(default_factory=dict, description="Дополнительные данные")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "CallResultStatus",
    "CallDirection",
    "HangupCause",
    "DTMFResult",
    
    # Запросы
    "CallResultCreateRequest",
    "CallHistoryFilterRequest",
    
    # Ответы
    "CallResultResponse",
    "CallDetailResponse",
    "CallListResponse",
    "CallHistoryResponse",
    
    # Статистика
    "CallStatsResponse",
    "DailyCallStatsResponse",
    "HourlyCallStatsResponse",
    
    # Аналитика
    "CallAnalyticsResponse",
    
    # Активные звонки
    "ActiveCallResponse",
    "ActiveCallsResponse",
    
    # WebSocket
    "CallEventResponse",
]
