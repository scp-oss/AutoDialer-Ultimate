#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели входящих звонков
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Входящих звонков
- Webhook уведомлений от Asterisk
- Транскрибации записей
- Статистики входящих звонков
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema
from app.utils.phone import normalize_phone, format_phone_display


# =============================================
# Enums
# =============================================
class TranscriptionStatus(str, Enum):
    """Статус транскрибации"""
    PENDING = "pending"         # Ожидает обработки
    PROCESSING = "processing"   # Обрабатывается
    COMPLETED = "completed"     # Завершена
    FAILED = "failed"           # Ошибка
    SKIPPED = "skipped"         # Пропущена (например, слишком короткая запись)


class IncomingCallStatus(str, Enum):
    """Статус входящего звонка"""
    NEW = "new"                 # Новый
    LISTENED = "listened"       # Прослушан
    ARCHIVED = "archived"       # Архивирован
    DELETED = "deleted"         # Удалён


class TranscriptionEngine(str, Enum):
    """Движок транскрибации"""
    WHISPER = "whisper"
    VOSK = "vosk"
    GOOGLE = "google"
    NONE = "none"


# =============================================
# Валидаторы
# =============================================
# normalize_phone / format_phone_display — см. app.utils.phone
# (единственный источник правил российского плана нумерации,
# импортированы выше).


# =============================================
# Webhook запросы
# =============================================
class IncomingCallWebhookRequest(BaseSchema):
    """
    Webhook запрос от Asterisk о входящем звонке.
    """
    caller_number: str = Field(..., description="Номер звонящего")
    caller_name: Optional[str] = Field(None, description="Имя звонящего (Caller ID Name)")
    
    called_number: Optional[str] = Field(None, description="Вызванный номер (DID)")
    
    recording_path: str = Field(..., description="Путь к файлу записи")
    recording_format: str = Field("wav", description="Формат записи")
    
    duration: Optional[int] = Field(None, ge=0, description="Длительность (сек)")
    file_size: Optional[int] = Field(None, ge=0, description="Размер файла (байт)")
    
    unique_id: Optional[str] = Field(None, description="Unique ID Asterisk")
    linked_id: Optional[str] = Field(None, description="Linked ID")
    
    language: str = Field("ru", description="Язык для транскрибации")
    auto_transcribe: bool = Field(True, description="Автоматически запустить транскрибацию")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @field_validator('caller_number')
    @classmethod
    def validate_caller_number(cls, v: str) -> str:
        """Нормализация номера"""
        return normalize_phone(v)
    
    @field_validator('called_number')
    @classmethod
    def validate_called_number(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return normalize_phone(v)
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "caller_number": "+79991234567",
                "caller_name": "Иван Петров",
                "called_number": "+74951234567",
                "recording_path": "/var/spool/asterisk/monitor/2024/01/01/incoming_1704067200.123.wav",
                "recording_format": "wav",
                "duration": 45,
                "file_size": 720000,
                "unique_id": "1704067200.123",
                "language": "ru",
                "auto_transcribe": True
            }
        }
    }


class IncomingCallWebhookResponse(BaseSchema):
    """
    Ответ на webhook.
    """
    success: bool = Field(True, description="Успешно")
    message: str = Field(..., description="Сообщение")
    call_id: Optional[int] = Field(None, description="ID созданной записи")
    transcription_queued: bool = Field(False, description="Транскрибация в очереди")


# =============================================
# Запросы
# =============================================
class IncomingCallUpdateRequest(BaseSchema):
    """
    Запрос на обновление записи о входящем звонке.
    """
    notes: Optional[str] = Field(None, description="Заметки")
    listened: Optional[bool] = Field(None, description="Прослушан")
    status: Optional[IncomingCallStatus] = Field(None, description="Статус")
    
    tags: Optional[List[str]] = Field(None, description="Теги")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Метаданные")
    
    @field_validator('notes')
    @classmethod
    def validate_notes(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip()
        return v


class IncomingCallTranscribeRequest(BaseSchema):
    """
    Запрос на запуск транскрибации.
    """
    language: str = Field("ru", description="Язык")
    engine: Optional[TranscriptionEngine] = Field(None, description="Движок (авто если не указан)")
    force: bool = Field(False, description="Принудительно (даже если уже была)")


# =============================================
# Ответы
# =============================================
class IncomingCallResponse(TimestampSchema):
    """
    Ответ с информацией о входящем звонке.
    """
    id: int = Field(..., description="ID записи")
    
    caller_number: str = Field(..., description="Номер звонящего")
    caller_number_display: str = Field(..., description="Номер для отображения")
    caller_name: Optional[str] = Field(None, description="Имя звонящего")
    
    called_number: Optional[str] = Field(None, description="Вызванный номер")
    called_number_display: Optional[str] = Field(None, description="Вызванный номер для отображения")
    
    call_date: datetime = Field(..., description="Дата и время звонка")
    
    duration: Optional[int] = Field(None, description="Длительность (сек)")
    duration_formatted: Optional[str] = Field(None, description="Длительность (ММ:СС)")
    
    file_size: Optional[int] = Field(None, description="Размер файла (байт)")
    file_size_human: Optional[str] = Field(None, description="Размер (человеко-читаемый)")
    
    recording_path: str = Field(..., description="Путь к записи")
    recording_url: Optional[str] = Field(None, description="URL для прослушивания")
    recording_format: str = Field("wav", description="Формат записи")
    
    transcription: Optional[str] = Field(None, description="Текст транскрибации")
    transcription_status: TranscriptionStatus = Field(TranscriptionStatus.PENDING, description="Статус транскрибации")
    transcription_engine: Optional[str] = Field(None, description="Использованный движок")
    transcription_error: Optional[str] = Field(None, description="Ошибка транскрибации")
    
    language: str = Field("ru", description="Язык")
    
    listened: bool = Field(False, description="Прослушан")
    listened_at: Optional[datetime] = Field(None, description="Дата прослушивания")
    listened_by: Optional[int] = Field(None, description="ID прослушавшего")
    listened_by_name: Optional[str] = Field(None, description="Имя прослушавшего")
    
    status: IncomingCallStatus = Field(IncomingCallStatus.NEW, description="Статус")
    
    notes: Optional[str] = Field(None, description="Заметки")
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    # Связанные данные
    contact_id: Optional[int] = Field(None, description="ID контакта (если найден)")
    contact_name: Optional[str] = Field(None, description="Имя контакта")
    
    unique_id: Optional[str] = Field(None, description="Unique ID")
    linked_id: Optional[str] = Field(None, description="Linked ID")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @model_validator(mode='after')
    def format_fields(self) -> 'IncomingCallResponse':
        """Форматирование полей"""
        # Форматирование номера
        self.caller_number_display = format_phone_display(self.caller_number)
        if self.called_number:
            self.called_number_display = format_phone_display(self.called_number)
        
        # Форматирование длительности
        if self.duration:
            minutes = self.duration // 60
            seconds = self.duration % 60
            self.duration_formatted = f"{minutes:02d}:{seconds:02d}"
        
        # Форматирование размера
        if self.file_size:
            if self.file_size < 1024:
                self.file_size_human = f"{self.file_size} B"
            elif self.file_size < 1024 * 1024:
                self.file_size_human = f"{self.file_size / 1024:.1f} KB"
            else:
                self.file_size_human = f"{self.file_size / (1024 * 1024):.2f} MB"
        
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "caller_number": "79991234567",
                "caller_number_display": "+7 (999) 123-45-67",
                "caller_name": "Иван Петров",
                "called_number": "74951234567",
                "called_number_display": "+7 (495) 123-45-67",
                "call_date": "2024-01-01T10:30:00Z",
                "duration": 45,
                "duration_formatted": "00:45",
                "file_size": 720000,
                "file_size_human": "703.1 KB",
                "recording_path": "/var/spool/asterisk/monitor/2024/01/01/incoming_1704067200.123.wav",
                "recording_url": "/api/incoming-calls/1/recording",
                "transcription": "Здравствуйте, меня зовут Иван, я хотел бы узнать...",
                "transcription_status": "completed",
                "transcription_engine": "whisper",
                "language": "ru",
                "listened": True,
                "listened_at": "2024-01-01T11:00:00Z",
                "listened_by": 1,
                "listened_by_name": "admin",
                "status": "listened",
                "notes": "Клиент интересуется тарифом Premium",
                "tags": ["важный", "перезвонить"],
                "contact_id": 42,
                "contact_name": "Иван Петров",
                "created_at": "2024-01-01T10:30:00Z"
            }
        }
    }


class IncomingCallDetailResponse(IncomingCallResponse):
    """
    Детальный ответ о входящем звонке.
    """
    # Полная транскрибация с таймкодами
    transcription_segments: Optional[List[Dict[str, Any]]] = Field(None, description="Сегменты транскрибации")
    
    # История прослушиваний
    listen_history: List[Dict[str, Any]] = Field(default_factory=list, description="История прослушиваний")
    
    # Связанные звонки (от этого же номера)
    related_calls: List['IncomingCallResponse'] = Field(default_factory=list, description="Связанные звонки")
    
    # Информация о контакте
    contact_details: Optional[Dict[str, Any]] = Field(None, description="Детали контакта")
    
    # Аналитика
    sentiment: Optional[str] = Field(None, description="Тональность (positive/neutral/negative)")
    keywords: List[str] = Field(default_factory=list, description="Ключевые слова")
    summary: Optional[str] = Field(None, description="Краткое содержание")


class IncomingCallListResponse(BaseSchema):
    """
    Ответ со списком входящих звонков.
    """
    items: List[IncomingCallResponse] = Field(..., description="Звонки")
    total: int = Field(..., description="Всего звонков")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")
    
    # Статистика по списку
    summary: Dict[str, Any] = Field(default_factory=dict, description="Сводка")


# =============================================
# Статистика
# =============================================
class IncomingCallStatsResponse(BaseSchema):
    """
    Статистика входящих звонков.
    """
    period_days: Optional[int] = Field(None, description="Период в днях")
    from_date: Optional[datetime] = Field(None, description="С даты")
    to_date: Optional[datetime] = Field(None, description="По дату")
    
    # Общая статистика
    total: int = Field(0, description="Всего звонков")
    total_duration: int = Field(0, description="Общая длительность (сек)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_size: int = Field(0, description="Общий размер (байт)")
    
    # По статусам
    new_count: int = Field(0, description="Новых")
    listened_count: int = Field(0, description="Прослушанных")
    archived_count: int = Field(0, description="Архивированных")
    
    # Транскрибация
    transcription: Dict[str, int] = Field(default_factory=dict, description="Статусы транскрибации")
    
    # По дням
    daily_stats: List[Dict[str, Any]] = Field(default_factory=list, description="По дням")
    
    # По часам
    hourly_stats: List[Dict[str, Any]] = Field(default_factory=list, description="По часам")
    
    # Топ номеров
    top_callers: List[Dict[str, Any]] = Field(default_factory=list, description="Топ звонящих")
    
    # По дням недели
    by_weekday: Dict[int, int] = Field(default_factory=dict, description="По дням недели")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "period_days": 30,
                "total": 156,
                "total_duration": 7020,
                "avg_duration": 45.0,
                "total_size": 112320000,
                "new_count": 23,
                "listened_count": 120,
                "archived_count": 13,
                "transcription": {
                    "pending": 5,
                    "processing": 2,
                    "completed": 140,
                    "failed": 9
                },
                "top_callers": [
                    {"number": "79991234567", "calls": 12, "total_duration": 540}
                ]
            }
        }
    }


# =============================================
# Транскрибация
# =============================================
class TranscriptionTaskResponse(BaseSchema):
    """
    Информация о задаче транскрибации.
    """
    call_id: int = Field(..., description="ID звонка")
    status: TranscriptionStatus = Field(..., description="Статус")
    progress: float = Field(0.0, description="Прогресс (%)")
    
    started_at: Optional[datetime] = Field(None, description="Начата")
    completed_at: Optional[datetime] = Field(None, description="Завершена")
    
    engine: Optional[str] = Field(None, description="Движок")
    language: str = Field("ru", description="Язык")
    
    error: Optional[str] = Field(None, description="Ошибка")
    
    queue_position: Optional[int] = Field(None, description="Позиция в очереди")
    estimated_time: Optional[int] = Field(None, description="Примерное время (сек)")


class TranscriptionInfoResponse(BaseSchema):
    """
    Информация о сервисе транскрибации.
    """
    enabled: bool = Field(..., description="Включена")
    engine: str = Field(..., description="Текущий движок")
    model: Optional[str] = Field(None, description="Модель")
    
    available_engines: List[str] = Field(default_factory=list, description="Доступные движки")
    
    queue_size: int = Field(0, description="Размер очереди")
    active_tasks: int = Field(0, description="Активных задач")
    
    supported_languages: List[str] = Field(default_factory=list, description="Поддерживаемые языки")
    max_duration: int = Field(300, description="Макс. длительность (сек)")
    max_file_size: int = Field(25 * 1024 * 1024, description="Макс. размер файла (байт)")


# =============================================
# Фильтры
# =============================================
class IncomingCallFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию входящих звонков.
    """
    search: Optional[str] = Field(None, description="Поиск по номеру, имени, транскрибации")
    
    caller_number: Optional[str] = Field(None, description="Номер звонящего")
    called_number: Optional[str] = Field(None, description="Вызванный номер")
    
    status: Optional[List[IncomingCallStatus]] = Field(None, description="Статусы")
    transcription_status: Optional[List[TranscriptionStatus]] = Field(None, description="Статусы транскрибации")
    
    listened: Optional[bool] = Field(None, description="Прослушан")
    
    tags: Optional[List[str]] = Field(None, description="Теги")
    
    min_duration: Optional[int] = Field(None, ge=0, description="Мин. длительность")
    max_duration: Optional[int] = Field(None, ge=0, description="Макс. длительность")
    
    from_date: Optional[datetime] = Field(None, description="С даты")
    to_date: Optional[datetime] = Field(None, description="По дату")
    
    has_transcription: Optional[bool] = Field(None, description="Есть транскрибация")
    has_contact: Optional[bool] = Field(None, description="Привязан к контакту")
    
    sort_by: str = Field("call_date", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")
    
    @field_validator('caller_number', 'called_number')
    @classmethod
    def normalize_phone_filter(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return normalize_phone(v)
        return v


# =============================================
# Массовые операции
# =============================================
class IncomingCallBulkActionRequest(BaseSchema):
    """
    Запрос на массовое действие.
    """
    call_ids: List[int] = Field(..., min_length=1, description="ID звонков")
    action: str = Field(..., description="Действие (mark_listened/archive/delete/transcribe)")
    
    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"mark_listened", "archive", "delete", "transcribe"}
        if v not in allowed:
            raise ValueError(f"Недопустимое действие. Разрешено: {', '.join(allowed)}")
        return v


class IncomingCallBulkActionResponse(BaseSchema):
    """
    Ответ на массовое действие.
    """
    total: int = Field(..., description="Всего")
    successful: int = Field(0, description="Успешно")
    failed: int = Field(0, description="Ошибок")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "TranscriptionStatus",
    "IncomingCallStatus",
    "TranscriptionEngine",
    
    # Валидаторы
    "normalize_phone",
    "format_phone_display",
    
    # Webhook
    "IncomingCallWebhookRequest",
    "IncomingCallWebhookResponse",
    
    # Запросы
    "IncomingCallUpdateRequest",
    "IncomingCallTranscribeRequest",
    
    # Ответы
    "IncomingCallResponse",
    "IncomingCallDetailResponse",
    "IncomingCallListResponse",
    
    # Статистика
    "IncomingCallStatsResponse",
    
    # Транскрибация
    "TranscriptionTaskResponse",
    "TranscriptionInfoResponse",
    
    # Фильтры
    "IncomingCallFilterRequest",
    
    # Массовые операции
    "IncomingCallBulkActionRequest",
    "IncomingCallBulkActionResponse",
]
