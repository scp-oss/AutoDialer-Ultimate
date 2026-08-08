#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели кампаний
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Создания и обновления кампаний
- Стратегий повторных звонков
- Расписания кампаний
- Статистики кампаний
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class CampaignStatus(str, Enum):
    """Статус кампании"""
    DRAFT = "draft"           # Черновик
    SCHEDULED = "scheduled"   # Запланирована
    RUNNING = "running"       # Выполняется
    PAUSED = "paused"         # Приостановлена
    STOPPED = "stopped"       # Остановлена
    COMPLETED = "completed"   # Завершена
    FAILED = "failed"         # Ошибка
    CANCELLED = "cancelled"   # Отменена


class ScheduleType(str, Enum):
    """Тип расписания"""
    ONCE = "once"             # Однократно
    DAILY = "daily"           # Ежедневно
    WEEKLY = "weekly"         # Еженедельно
    MONTHLY = "monthly"       # Ежемесячно
    CRON = "cron"             # CRON выражение


class CampaignPriority(str, Enum):
    """Приоритет кампании"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DialMode(str, Enum):
    """Режим дозвона"""
    PREDICTIVE = "predictive"   # Предиктивный (адаптивный CPS)
    PROGRESSIVE = "progressive" # Прогрессивный (фиксированный CPS)
    PREVIEW = "preview"         # Предварительный просмотр
    POWER = "power"             # Мощный (максимальный CPS)


# =============================================
# Стратегия повторных звонков
# =============================================
class RetryStrategySchema(BaseSchema):
    """
    Стратегия повторных звонков при разных статусах.
    """
    busy: int = Field(2, ge=0, le=10, description="Максимум повторов при 'занято'")
    busy_delay: int = Field(120, ge=30, le=3600, description="Задержка при 'занято' (сек)")
    
    noanswer: int = Field(3, ge=0, le=10, description="Максимум повторов при 'нет ответа'")
    noanswer_delay: int = Field(300, ge=60, le=7200, description="Задержка при 'нет ответа' (сек)")
    
    failed: int = Field(1, ge=0, le=5, description="Максимум повторов при 'ошибка'")
    failed_delay: int = Field(60, ge=30, le=1800, description="Задержка при 'ошибка' (сек)")
    
    timeout: int = Field(1, ge=0, le=5, description="Максимум повторов при 'таймаут'")
    timeout_delay: int = Field(60, ge=30, le=1800, description="Задержка при 'таймаут' (сек)")
    
    machine: int = Field(1, ge=0, le=3, description="Максимум повторов при 'автоответчик'")
    machine_delay: int = Field(3600, ge=1800, le=86400, description="Задержка при 'автоответчик' (сек)")
    
    # Глобальные настройки
    max_total_retries: int = Field(5, ge=0, le=20, description="Общий максимум повторов")
    retry_interval_multiplier: float = Field(2.0, ge=1.0, le=5.0, description="Множитель интервала")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "busy": 2,
                "busy_delay": 120,
                "noanswer": 3,
                "noanswer_delay": 300,
                "failed": 1,
                "failed_delay": 60,
                "timeout": 1,
                "timeout_delay": 60,
                "machine": 1,
                "machine_delay": 3600,
                "max_total_retries": 5,
                "retry_interval_multiplier": 2.0
            }
        }
    }


# =============================================
# Расписание кампании
# =============================================
class CampaignScheduleSchema(BaseSchema):
    """
    Расписание запуска кампании.
    """
    enabled: bool = Field(True, description="Включено ли расписание")
    schedule_type: ScheduleType = Field(ScheduleType.ONCE, description="Тип расписания")
    
    # Даты
    start_at: Optional[datetime] = Field(None, description="Дата начала")
    end_at: Optional[datetime] = Field(None, description="Дата окончания")
    
    # Часовой пояс
    timezone: str = Field("UTC", description="Часовой пояс")
    
    # CRON выражение
    cron_expression: Optional[str] = Field(
        None, 
        description="CRON выражение (например: '0 9-18 * * 1-5')"
    )
    
    # Дни недели (0 = ПН, 6 = ВС)
    days_of_week: Optional[List[int]] = Field(
        None, 
        description="Дни недели (0-6, где 0=ПН, 6=ВС)"
    )
    
    # Часы (0-23)
    hours: Optional[List[int]] = Field(
        None, 
        description="Часы для запуска (0-23)"
    )
    
    # Минуты (0-59)
    minutes: Optional[List[int]] = Field(
        None, 
        description="Минуты для запуска (0-59)"
    )
    
    # Рабочие дни
    working_days_only: bool = Field(False, description="Только в рабочие дни")
    exclude_holidays: bool = Field(False, description="Исключить праздники")
    holidays_calendar: Optional[str] = Field(None, description="Календарь праздников (код страны)")
    
    @field_validator('days_of_week')
    @classmethod
    def validate_days_of_week(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for day in v:
                if day < 0 or day > 6:
                    raise ValueError("Дни недели должны быть от 0 до 6")
        return v
    
    @field_validator('hours')
    @classmethod
    def validate_hours(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for hour in v:
                if hour < 0 or hour > 23:
                    raise ValueError("Часы должны быть от 0 до 23")
        return v
    
    @field_validator('minutes')
    @classmethod
    def validate_minutes(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for minute in v:
                if minute < 0 or minute > 59:
                    raise ValueError("Минуты должны быть от 0 до 59")
        return v
    
    @model_validator(mode='after')
    def validate_dates(self) -> 'CampaignScheduleSchema':
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValueError("start_at не может быть позже end_at")
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "enabled": True,
                "schedule_type": "daily",
                "start_at": "2024-01-01T09:00:00Z",
                "end_at": "2024-01-31T18:00:00Z",
                "timezone": "Europe/Moscow",
                "days_of_week": [0, 1, 2, 3, 4],
                "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17],
                "working_days_only": True
            }
        }
    }


# =============================================
# Настройки дозвона
# =============================================
class DialerSettingsSchema(BaseSchema):
    """
    Настройки дозвона для кампании.
    """
    max_calls: int = Field(30, ge=1, le=500, description="Максимум одновременных звонков")
    cps: int = Field(5, ge=1, le=100, description="Звонков в секунду (CPS)")
    dial_mode: DialMode = Field(DialMode.PREDICTIVE, description="Режим дозвона")
    
    call_timeout: int = Field(30, ge=5, le=300, description="Таймаут звонка (сек)")
    answer_timeout: int = Field(60, ge=10, le=600, description="Таймаут ожидания ответа (сек)")
    
    caller_id: Optional[str] = Field(None, max_length=80, description="Caller ID")
    caller_id_number: Optional[str] = Field(None, max_length=20, description="Номер Caller ID")
    
    audio_id: Optional[int] = Field(None, description="ID аудиофайла")
    audio_name: Optional[str] = Field(None, description="Название аудиофайла")
    
    # DTMF настройки
    dtmf_timeout: int = Field(5, ge=1, le=30, description="Таймаут ожидания DTMF (сек)")
    dtmf_interdigit_timeout: int = Field(3, ge=1, le=10, description="Таймаут между цифрами (сек)")
    
    # Запись звонков
    record_calls: bool = Field(False, description="Записывать звонки")
    record_format: str = Field("wav", description="Формат записи")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "max_calls": 30,
                "cps": 5,
                "dial_mode": "predictive",
                "call_timeout": 30,
                "answer_timeout": 60,
                "caller_id": "AutoDialer Campaign",
                "record_calls": True
            }
        }
    }


# =============================================
# Запросы
# =============================================
class CampaignCreateRequest(BaseSchema):
    """
    Запрос на создание кампании.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название кампании")
    description: Optional[str] = Field(None, max_length=1000, description="Описание")
    
    # Приоритет и статус
    priority: CampaignPriority = Field(CampaignPriority.NORMAL, description="Приоритет")
    
    # Настройки дозвона
    dialer_settings: DialerSettingsSchema = Field(
        default_factory=DialerSettingsSchema,
        description="Настройки дозвона"
    )
    
    # Стратегия повторов
    retry_strategy: RetryStrategySchema = Field(
        default_factory=RetryStrategySchema,
        description="Стратегия повторных звонков"
    )
    
    # Расписание
    schedule: CampaignScheduleSchema = Field(
        default_factory=CampaignScheduleSchema,
        description="Расписание"
    )
    
    # Контакты
    contact_group_ids: Optional[List[int]] = Field(None, description="ID групп контактов")
    contact_ids: Optional[List[int]] = Field(None, description="ID отдельных контактов")
    contact_filter: Optional[Dict[str, Any]] = Field(None, description="Фильтр контактов")
    
    # Ограничения
    max_contacts: Optional[int] = Field(None, ge=1, description="Максимум контактов для обзвона")
    max_duration_hours: Optional[float] = Field(None, ge=0.1, description="Максимальная длительность (часы)")
    
    # Теги и метаданные
    tags: List[str] = Field(default_factory=list, description="Теги")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Очистка названия"""
        return v.strip()
    
    @model_validator(mode='after')
    def validate_contacts(self) -> 'CampaignCreateRequest':
        if not self.contact_group_ids and not self.contact_ids and not self.contact_filter:
            raise ValueError("Необходимо указать хотя бы один источник контактов")
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Тестовая кампания",
                "description": "Обзвон клиентов по базе",
                "priority": "normal",
                "dialer_settings": {
                    "max_calls": 30,
                    "cps": 5,
                    "dial_mode": "predictive",
                    "caller_id": "AutoDialer"
                },
                "contact_group_ids": [1, 2],
                "max_contacts": 1000
            }
        }
    }


class CampaignUpdateRequest(BaseSchema):
    """
    Запрос на обновление кампании.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название")
    description: Optional[str] = Field(None, max_length=1000, description="Описание")
    priority: Optional[CampaignPriority] = Field(None, description="Приоритет")
    
    dialer_settings: Optional[DialerSettingsSchema] = Field(None, description="Настройки дозвона")
    retry_strategy: Optional[RetryStrategySchema] = Field(None, description="Стратегия повторов")
    schedule: Optional[CampaignScheduleSchema] = Field(None, description="Расписание")
    
    tags: Optional[List[str]] = Field(None, description="Теги")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Метаданные")


class CampaignStartRequest(BaseSchema):
    """
    Запрос на запуск кампании.
    """
    force: bool = Field(False, description="Принудительный запуск (игнорировать расписание)")
    limit_contacts: Optional[int] = Field(None, ge=1, description="Ограничить количество контактов")


class CampaignStopRequest(BaseSchema):
    """
    Запрос на остановку кампании.
    """
    reason: Optional[str] = Field(None, description="Причина остановки")
    force: bool = Field(False, description="Принудительная остановка")


# =============================================
# Ответы
# =============================================
class CampaignResponse(TimestampSchema):
    """
    Ответ с информацией о кампании.
    """
    id: int = Field(..., description="ID кампании")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    status: CampaignStatus = Field(CampaignStatus.DRAFT, description="Статус")
    priority: CampaignPriority = Field(CampaignPriority.NORMAL, description="Приоритет")
    
    # Настройки
    dialer_settings: DialerSettingsSchema = Field(..., description="Настройки дозвона")
    retry_strategy: RetryStrategySchema = Field(..., description="Стратегия повторов")
    schedule: CampaignScheduleSchema = Field(..., description="Расписание")
    
    # Аудио
    audio_id: Optional[int] = Field(None, description="ID аудиофайла")
    audio_name: Optional[str] = Field(None, description="Название аудиофайла")
    
    # Создатель
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    # Даты
    started_at: Optional[datetime] = Field(None, description="Дата запуска")
    paused_at: Optional[datetime] = Field(None, description="Дата паузы")
    stopped_at: Optional[datetime] = Field(None, description="Дата остановки")
    completed_at: Optional[datetime] = Field(None, description="Дата завершения")
    
    # Теги и метаданные
    tags: List[str] = Field(default_factory=list, description="Теги")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")

    # Статистика (заполняется в списке кампаний; в CampaignDetailResponse
    # переопределяется собственным полем ниже)
    stats: Optional["CampaignStatsResponse"] = Field(None, description="Статистика кампании")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "Тестовая кампания",
                "description": "Обзвон клиентов",
                "status": "draft",
                "priority": "normal",
                "dialer_settings": {
                    "max_calls": 30,
                    "cps": 5
                },
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class CampaignStatsResponse(BaseSchema):
    """
    Статистика кампании.
    """
    # Контакты
    total_contacts: int = Field(0, description="Всего контактов")
    processed_contacts: int = Field(0, description="Обработано контактов")
    remaining_contacts: int = Field(0, description="Осталось контактов")
    skipped_contacts: int = Field(0, description="Пропущено контактов")
    
    # Звонки
    total_calls: int = Field(0, description="Всего звонков")
    answered_calls: int = Field(0, description="Отвеченных звонков")
    
    # Статусы
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    busy: int = Field(0, description="Занято")
    noanswer: int = Field(0, description="Нет ответа")
    failed: int = Field(0, description="Ошибки")
    timeout: int = Field(0, description="Таймауты")
    machine: int = Field(0, description="Автоответчик")
    cancelled: int = Field(0, description="Отменено")
    
    # Метрики
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    
    # Длительность
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_duration: int = Field(0, description="Общая длительность (сек)")
    avg_wait_time: float = Field(0.0, description="Среднее время ожидания (сек)")
    
    # Прогресс
    progress_percent: float = Field(0.0, ge=0, le=100, description="Прогресс (%)")
    estimated_completion: Optional[datetime] = Field(None, description="Ожидаемое завершение")
    
    # Производительность
    current_cps: float = Field(0.0, description="Текущий CPS")
    avg_cps: float = Field(0.0, description="Средний CPS")
    peak_cps: float = Field(0.0, description="Пиковый CPS")


class CampaignDetailResponse(CampaignResponse):
    """
    Детальный ответ о кампании (со статистикой).
    """
    stats: Optional[CampaignStatsResponse] = Field(None, description="Статистика")
    contact_groups: List[Dict[str, Any]] = Field(default_factory=list, description="Группы контактов")
    recent_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Последние звонки")


class CampaignListResponse(BaseSchema):
    """
    Ответ со списком кампаний.
    """
    items: List[CampaignResponse] = Field(..., description="Кампании")
    total: int = Field(..., description="Всего кампаний")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")


class CampaignProgressResponse(BaseSchema):
    """
    Ответ с прогрессом кампании (для WebSocket).
    """
    campaign_id: int = Field(..., description="ID кампании")
    campaign_name: str = Field(..., description="Название")
    status: CampaignStatus = Field(..., description="Статус")
    
    total_contacts: int = Field(..., description="Всего контактов")
    called_contacts: int = Field(..., description="Прозвонено")
    
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    
    progress_percent: float = Field(..., description="Прогресс (%)")
    active_calls: int = Field(0, description="Активных звонков")
    current_cps: float = Field(0.0, description="Текущий CPS")
    
    estimated_completion: Optional[datetime] = Field(None, description="Ожидаемое завершение")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время обновления")


class CampaignScheduleResponse(BaseSchema):
    """
    Ответ с информацией о следующем запуске по расписанию.
    """
    campaign_id: int = Field(..., description="ID кампании")
    next_run_at: Optional[datetime] = Field(None, description="Следующий запуск")
    last_run_at: Optional[datetime] = Field(None, description="Последний запуск")
    is_active: bool = Field(..., description="Активно ли расписание")
    schedule: CampaignScheduleSchema = Field(..., description="Настройки расписания")


# =============================================
# Массовые операции
# =============================================
class CampaignBulkActionRequest(BaseSchema):
    """
    Запрос на массовое действие с кампаниями.
    """
    campaign_ids: List[int] = Field(..., min_length=1, description="ID кампаний")
    action: str = Field(..., description="Действие (start/stop/pause/resume/delete)")
    
    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"start", "stop", "pause", "resume", "delete", "archive"}
        if v not in allowed:
            raise ValueError(f"Недопустимое действие. Разрешено: {', '.join(allowed)}")
        return v


class CampaignBulkActionResponse(BaseSchema):
    """
    Ответ на массовое действие.
    """
    total: int = Field(..., description="Всего кампаний")
    successful: List[int] = Field(default_factory=list, description="Успешно обработаны")
    failed: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "CampaignStatus",
    "ScheduleType",
    "CampaignPriority",
    "DialMode",
    
    # Схемы
    "RetryStrategySchema",
    "CampaignScheduleSchema",
    "DialerSettingsSchema",
    
    # Запросы
    "CampaignCreateRequest",
    "CampaignUpdateRequest",
    "CampaignStartRequest",
    "CampaignStopRequest",
    
    # Ответы
    "CampaignResponse",
    "CampaignStatsResponse",
    "CampaignDetailResponse",
    "CampaignListResponse",
    "CampaignProgressResponse",
    "CampaignScheduleResponse",
    
    # Массовые операции
    "CampaignBulkActionRequest",
    "CampaignBulkActionResponse",
]
