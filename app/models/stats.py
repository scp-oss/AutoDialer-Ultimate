#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели статистики и аналитики
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Системной статистики
- Статистики по кампаниям
- Статистики по звонкам
- Статистики по контактам
- Аналитики и отчётов
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator

from app.models.common import BaseSchema


# =============================================
# Системная статистика
# =============================================
class SystemStats(BaseSchema):
    """
    Системная статистика.
    """
    # Кампании
    total_campaigns: int = Field(0, description="Всего кампаний")
    active_campaigns: int = Field(0, description="Активных кампаний")
    completed_campaigns: int = Field(0, description="Завершённых кампаний")
    paused_campaigns: int = Field(0, description="Приостановленных кампаний")
    
    # Контакты
    total_contacts: int = Field(0, description="Всего контактов")
    active_contacts: int = Field(0, description="Активных контактов")
    blacklisted_contacts: int = Field(0, description="В чёрном списке")
    new_contacts_today: int = Field(0, description="Новых сегодня")
    new_contacts_week: int = Field(0, description="Новых за неделю")
    
    # Звонки
    total_calls: int = Field(0, description="Всего звонков")
    calls_today: int = Field(0, description="Звонков сегодня")
    calls_this_hour: int = Field(0, description="Звонков за час")
    calls_this_week: int = Field(0, description="Звонков за неделю")
    calls_this_month: int = Field(0, description="Звонков за месяц")
    
    # Результаты звонков
    agreed_calls: int = Field(0, description="Согласились")
    declined_calls: int = Field(0, description="Отказались")
    busy_calls: int = Field(0, description="Занято")
    noanswer_calls: int = Field(0, description="Нет ответа")
    failed_calls: int = Field(0, description="Ошибки")
    timeout_calls: int = Field(0, description="Таймауты")
    machine_calls: int = Field(0, description="Автоответчик")
    cancelled_calls: int = Field(0, description="Отменено")
    
    # Метрики
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    avg_call_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_call_duration: int = Field(0, description="Общая длительность (сек)")
    avg_wait_time: float = Field(0.0, description="Среднее ожидание (сек)")
    
    # Входящие звонки
    incoming_calls_total: int = Field(0, description="Входящих всего")
    incoming_calls_today: int = Field(0, description="Входящих сегодня")
    
    # Аудиофайлы
    audio_files_total: int = Field(0, description="Аудиофайлов")
    audio_files_size_mb: float = Field(0.0, description="Общий размер (МБ)")
    
    # Пользователи
    users_total: int = Field(0, description="Пользователей")
    users_active: int = Field(0, description="Активных пользователей")
    users_online: int = Field(0, description="Онлайн")
    
    # API
    api_keys_total: int = Field(0, description="API ключей")
    api_requests_today: int = Field(0, description="API запросов сегодня")
    
    # Очереди
    dialer_queue_size: int = Field(0, description="Очередь дозвона")
    transcription_queue_size: int = Field(0, description="Очередь транскрибации")
    tts_queue_size: int = Field(0, description="Очередь TTS")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "total_campaigns": 25,
                "active_campaigns": 3,
                "total_contacts": 15420,
                "active_contacts": 14850,
                "total_calls": 125000,
                "calls_today": 1520,
                "agreed_calls": 8500,
                "conversion_rate": 6.8,
                "answer_rate": 45.2,
                "avg_call_duration": 42.5,
                "incoming_calls_total": 2300,
                "users_total": 12,
                "users_active": 8,
                "users_online": 3
            }
        }
    }


# =============================================
# Дневная статистика
# =============================================
class DailyStats(BaseSchema):
    """
    Дневная статистика.
    """
    date: str = Field(..., description="Дата (YYYY-MM-DD)")
    
    # Кампании
    campaigns_active: int = Field(0, description="Активных кампаний")
    campaigns_completed: int = Field(0, description="Завершено кампаний")
    
    # Контакты
    new_contacts: int = Field(0, description="Новых контактов")
    
    # Звонки
    total_calls: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    busy: int = Field(0, description="Занято")
    noanswer: int = Field(0, description="Нет ответа")
    failed: int = Field(0, description="Ошибки")
    timeout: int = Field(0, description="Таймауты")
    machine: int = Field(0, description="Автоответчик")
    
    # Метрики
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_duration: int = Field(0, description="Общая длительность (сек)")
    
    # Входящие
    incoming_calls: int = Field(0, description="Входящих звонков")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "date": "2024-01-15",
                "campaigns_active": 3,
                "new_contacts": 125,
                "total_calls": 4520,
                "agreed": 320,
                "declined": 890,
                "busy": 670,
                "noanswer": 2100,
                "conversion_rate": 7.08,
                "answer_rate": 26.8,
                "avg_duration": 38.5,
                "incoming_calls": 45
            }
        }
    }


class WeeklyStats(BaseSchema):
    """
    Недельная статистика.
    """
    week_start: str = Field(..., description="Начало недели (YYYY-MM-DD)")
    week_end: str = Field(..., description="Конец недели (YYYY-MM-DD)")
    week_number: int = Field(..., description="Номер недели")
    
    total_calls: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    
    new_contacts: int = Field(0, description="Новых контактов")
    campaigns_completed: int = Field(0, description="Завершено кампаний")


class MonthlyStats(BaseSchema):
    """
    Месячная статистика.
    """
    month: str = Field(..., description="Месяц (YYYY-MM)")
    
    total_calls: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    
    new_contacts: int = Field(0, description="Новых контактов")
    new_campaigns: int = Field(0, description="Новых кампаний")
    campaigns_completed: int = Field(0, description="Завершено кампаний")


class HourlyStats(BaseSchema):
    """
    Почасовая статистика.
    """
    hour: int = Field(..., ge=0, le=23, description="Час (0-23)")
    
    total_calls: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    answered: int = Field(0, description="Отвеченных")
    
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "hour": 10,
                "total_calls": 850,
                "agreed": 65,
                "answered": 320,
                "answer_rate": 37.6,
                "conversion_rate": 7.6,
                "avg_duration": 42.3
            }
        }
    }


class WeekdayStats(BaseSchema):
    """
    Статистика по дням недели.
    """
    weekday: int = Field(..., ge=0, le=6, description="День недели (0=ПН, 6=ВС)")
    weekday_name: str = Field(..., description="Название дня")
    
    total_calls: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    answered: int = Field(0, description="Отвеченных")
    
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "weekday": 2,
                "weekday_name": "СР",
                "total_calls": 12500,
                "agreed": 950,
                "answered": 5200,
                "answer_rate": 41.6,
                "conversion_rate": 7.6,
                "avg_duration": 44.2
            }
        }
    }


# =============================================
# Статистика по кампаниям
# =============================================
class CampaignStatsSummary(BaseSchema):
    """
    Сводка статистики по кампании.
    """
    campaign_id: int = Field(..., description="ID кампании")
    campaign_name: str = Field(..., description="Название кампании")
    status: str = Field(..., description="Статус")
    
    total_contacts: int = Field(0, description="Всего контактов")
    processed_contacts: int = Field(0, description="Обработано")
    remaining_contacts: int = Field(0, description="Осталось")
    
    total_calls: int = Field(0, description="Всего звонков")
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    busy: int = Field(0, description="Занято")
    noanswer: int = Field(0, description="Нет ответа")
    failed: int = Field(0, description="Ошибки")
    
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    
    progress_percent: float = Field(0.0, description="Прогресс (%)")
    
    started_at: Optional[datetime] = Field(None, description="Запущена")
    estimated_completion: Optional[datetime] = Field(None, description="Ожидаемое завершение")


class CampaignStatsDetail(CampaignStatsSummary):
    """
    Детальная статистика по кампании.
    """
    # По дням
    daily_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Звонки по дням")
    
    # По часам
    hourly_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Звонки по часам")
    
    # По статусам (детально)
    status_breakdown: Dict[str, int] = Field(default_factory=dict, description="Детализация по статусам")
    
    # DTMF статистика
    dtmf_stats: Dict[str, int] = Field(default_factory=dict, description="Статистика DTMF")
    
    # Причины завершения
    hangup_causes: Dict[str, int] = Field(default_factory=dict, description="Причины завершения")
    
    # Производительность
    avg_cps: float = Field(0.0, description="Средний CPS")
    peak_cps: float = Field(0.0, description="Пиковый CPS")
    total_duration: int = Field(0, description="Общая длительность (сек)")


# =============================================
# Статистика по звонкам
# =============================================
class CallStatsResponse(BaseSchema):
    """
    Статистика по звонкам.
    """
    from_date: Optional[date] = Field(None, description="С даты")
    to_date: Optional[date] = Field(None, description="По дату")
    
    total_calls: int = Field(0, description="Всего звонков")
    answered_calls: int = Field(0, description="Отвеченных")
    unique_contacts: int = Field(0, description="Уникальных контактов")
    
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    busy: int = Field(0, description="Занято")
    noanswer: int = Field(0, description="Нет ответа")
    failed: int = Field(0, description="Ошибки")
    timeout: int = Field(0, description="Таймауты")
    machine: int = Field(0, description="Автоответчик")
    cancelled: int = Field(0, description="Отменено")
    
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_duration: int = Field(0, description="Общая длительность (сек)")
    avg_wait_time: float = Field(0.0, description="Среднее ожидание (сек)")
    max_duration: int = Field(0, description="Макс. длительность (сек)")
    min_duration: int = Field(0, description="Мин. длительность (сек)")
    
    dtmf_stats: Dict[str, int] = Field(default_factory=dict, description="Статистика DTMF")
    calls_by_hour: Dict[int, int] = Field(default_factory=dict, description="Звонки по часам")
    calls_by_weekday: Dict[int, int] = Field(default_factory=dict, description="Звонки по дням недели")


class CallAnalyticsResponse(BaseSchema):
    """
    Аналитика по звонкам.
    """
    period_days: int = Field(..., description="Период в днях")
    
    daily_stats: List[DailyStats] = Field(default_factory=list, description="По дням")
    hourly_stats: List[HourlyStats] = Field(default_factory=list, description="По часам")
    weekday_stats: List[WeekdayStats] = Field(default_factory=list, description="По дням недели")
    
    top_campaigns: List[Dict[str, Any]] = Field(default_factory=list, description="Топ кампаний")
    top_phones: List[Dict[str, Any]] = Field(default_factory=list, description="Топ номеров")
    
    hangup_causes: Dict[str, int] = Field(default_factory=dict, description="Причины завершения")
    
    best_hours: List[int] = Field(default_factory=list, description="Лучшие часы")
    best_weekdays: List[int] = Field(default_factory=list, description="Лучшие дни недели")
    
    recommendations: List[str] = Field(default_factory=list, description="Рекомендации")


# =============================================
# Статистика по контактам
# =============================================
class ContactStatsResponse(BaseSchema):
    """
    Статистика по контактам.
    """
    total_contacts: int = Field(0, description="Всего контактов")
    active_contacts: int = Field(0, description="Активных")
    blacklisted_contacts: int = Field(0, description="В чёрном списке")
    
    with_calls: int = Field(0, description="С звонками")
    without_calls: int = Field(0, description="Без звонков")
    
    new_last_30_days: int = Field(0, description="Новых за 30 дней")
    
    avg_calls_per_contact: float = Field(0.0, description="Среднее звонков на контакт")
    
    by_source: Dict[str, int] = Field(default_factory=dict, description="По источникам")
    by_status: Dict[str, int] = Field(default_factory=dict, description="По статусам")
    
    top_groups: List[Dict[str, Any]] = Field(default_factory=list, description="Топ групп")
    top_tags: List[Dict[str, Any]] = Field(default_factory=list, description="Топ тегов")


# =============================================
# Статистика по входящим звонкам
# =============================================
class IncomingCallStatsResponse(BaseSchema):
    """
    Статистика по входящим звонкам.
    """
    period_days: Optional[int] = Field(None, description="Период в днях")
    from_date: Optional[datetime] = Field(None, description="С даты")
    to_date: Optional[datetime] = Field(None, description="По дату")
    
    total: int = Field(0, description="Всего звонков")
    total_duration: int = Field(0, description="Общая длительность (сек)")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_size: int = Field(0, description="Общий размер (байт)")
    
    new_count: int = Field(0, description="Новых")
    listened_count: int = Field(0, description="Прослушанных")
    archived_count: int = Field(0, description="Архивированных")
    
    transcription: Dict[str, int] = Field(default_factory=dict, description="Статусы транскрибации")
    
    daily_stats: List[Dict[str, Any]] = Field(default_factory=list, description="По дням")
    hourly_stats: List[Dict[str, Any]] = Field(default_factory=list, description="По часам")
    
    top_callers: List[Dict[str, Any]] = Field(default_factory=list, description="Топ звонящих")
    by_weekday: Dict[int, int] = Field(default_factory=dict, description="По дням недели")


# =============================================
# Полная статистика
# =============================================
class FullStatsResponse(BaseSchema):
    """
    Полная статистика системы.
    """
    system: SystemStats = Field(..., description="Системная статистика")
    daily: List[DailyStats] = Field(default_factory=list, description="Дневная статистика")
    by_campaign: List[CampaignStatsSummary] = Field(default_factory=list, description="По кампаниям")
    by_status: Dict[str, int] = Field(default_factory=dict, description="По статусам звонков")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "system": {
                    "total_campaigns": 25,
                    "active_campaigns": 3,
                    "total_calls": 125000
                },
                "daily": [],
                "by_campaign": [],
                "by_status": {
                    "agreed": 8500,
                    "declined": 12500,
                    "noanswer": 85000
                }
            }
        }
    }


# =============================================
# Данные для дашборда
# =============================================
class DashboardMetrics(BaseSchema):
    """
    Ключевые метрики для дашборда.
    """
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время")
    
    active_campaigns: int = Field(0, description="Активных кампаний")
    calls_today: int = Field(0, description="Звонков сегодня")
    agreed_week: int = Field(0, description="Согласий за неделю")
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    new_contacts: int = Field(0, description="Новых контактов за неделю")
    incoming_today: int = Field(0, description="Входящих сегодня")
    
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    
    queue_size: int = Field(0, description="Размер очереди дозвона")
    active_calls: int = Field(0, description="Активных звонков сейчас")
    current_cps: float = Field(0.0, description="Текущий CPS")


class DashboardCharts(BaseSchema):
    """
    Графики для дашборда.
    """
    calls_chart: List[Dict[str, Any]] = Field(default_factory=list, description="Звонки за неделю")
    status_distribution: Dict[str, int] = Field(default_factory=dict, description="Распределение статусов")
    hourly_activity: List[Dict[str, Any]] = Field(default_factory=list, description="Активность по часам")
    top_campaigns: List[Dict[str, Any]] = Field(default_factory=list, description="Топ кампаний")
    campaign_progress: List[Dict[str, Any]] = Field(default_factory=list, description="Прогресс кампаний")


class DashboardResponse(BaseSchema):
    """
    Полные данные для дашборда.
    """
    metrics: DashboardMetrics = Field(..., description="Метрики")
    charts: DashboardCharts = Field(..., description="Графики")
    
    recent_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Последние звонки")
    recent_incoming: List[Dict[str, Any]] = Field(default_factory=list, description="Последние входящие")
    
    system_health: Dict[str, Any] = Field(default_factory=dict, description="Здоровье системы")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "metrics": {
                    "active_campaigns": 3,
                    "calls_today": 1520,
                    "agreed_week": 2150,
                    "avg_duration": 42.5,
                    "new_contacts": 580,
                    "incoming_today": 45
                },
                "charts": {},
                "recent_calls": [],
                "recent_incoming": [],
                "system_health": {
                    "database": "healthy",
                    "redis": "healthy",
                    "ami": "healthy"
                }
            }
        }
    }


# =============================================
# Экспорт статистики
# =============================================
class StatsExportRequest(BaseSchema):
    """
    Запрос на экспорт статистики.
    """
    report_type: str = Field(..., description="Тип отчёта (calls/campaigns/contacts/incoming/system)")
    format: str = Field("csv", description="Формат (csv/json/xlsx)")
    
    from_date: Optional[date] = Field(None, description="С даты")
    to_date: Optional[date] = Field(None, description="По дату")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    
    fields: Optional[List[str]] = Field(None, description="Поля для экспорта")
    
    @field_validator('report_type')
    @classmethod
    def validate_report_type(cls, v: str) -> str:
        allowed = {"calls", "campaigns", "contacts", "incoming", "system"}
        if v not in allowed:
            raise ValueError(f"Недопустимый тип отчёта. Разрешено: {', '.join(allowed)}")
        return v


class StatsExportResponse(BaseSchema):
    """
    Ответ на экспорт статистики.
    """
    task_id: str = Field(..., description="ID задачи экспорта")
    status: str = Field("pending", description="Статус")
    report_type: str = Field(..., description="Тип отчёта")
    format: str = Field(..., description="Формат")
    expires_at: datetime = Field(..., description="Действителен до")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Системная
    "SystemStats",
    
    # Периодическая
    "DailyStats",
    "WeeklyStats",
    "MonthlyStats",
    "HourlyStats",
    "WeekdayStats",
    
    # Кампании
    "CampaignStatsSummary",
    "CampaignStatsDetail",
    
    # Звонки
    "CallStatsResponse",
    "CallAnalyticsResponse",
    
    # Контакты
    "ContactStatsResponse",
    
    # Входящие
    "IncomingCallStatsResponse",
    
    # Полная
    "FullStatsResponse",
    
    # Дашборд
    "DashboardMetrics",
    "DashboardCharts",
    "DashboardResponse",
    
    # Экспорт
    "StatsExportRequest",
    "StatsExportResponse",
]
