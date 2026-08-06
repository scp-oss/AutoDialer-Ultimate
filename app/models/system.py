#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели системных эндпоинтов
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Статуса системы
- Health check'ов
- Управления системой (enable/disable)
- WebSocket событий
- Системной статистики
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class SystemComponentStatus(str, Enum):
    """Статус компонента системы"""
    HEALTHY = "healthy"         # Работает нормально
    DEGRADED = "degraded"       # Работает с ограничениями
    UNHEALTHY = "unhealthy"     # Не работает
    UNKNOWN = "unknown"         # Статус неизвестен
    NOT_INITIALIZED = "not_initialized"  # Не инициализирован


class SystemMode(str, Enum):
    """Режим работы системы"""
    NORMAL = "normal"           # Нормальный режим
    MAINTENANCE = "maintenance" # Обслуживание
    DEGRADED = "degraded"       # Degraded mode (Redis недоступен)
    READONLY = "readonly"       # Только чтение


class LogLevel(str, Enum):
    """Уровни логирования"""
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    AUDIT = "AUDIT"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# =============================================
# Статус компонента
# =============================================
class ComponentStatus(BaseSchema):
    """
    Статус отдельного компонента системы.
    """
    status: SystemComponentStatus = Field(..., description="Статус")
    message: Optional[str] = Field(None, description="Дополнительное сообщение")
    latency_ms: Optional[float] = Field(None, description="Задержка (мс)")
    last_check: Optional[datetime] = Field(None, description="Последняя проверка")
    error: Optional[str] = Field(None, description="Ошибка (если есть)")
    details: Dict[str, Any] = Field(default_factory=dict, description="Детали")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "message": "Connected",
                "latency_ms": 2.5,
                "last_check": "2024-01-01T00:00:00Z"
            }
        }
    }


# =============================================
# Health Check
# =============================================
class HealthCheckResponse(BaseSchema):
    """
    Ответ проверки здоровья системы.
    """
    status: SystemComponentStatus = Field(..., description="Общий статус")
    version: str = Field(..., description="Версия приложения")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время проверки")
    uptime_seconds: float = Field(..., description="Время работы (сек)")
    uptime_formatted: Optional[str] = Field(None, description="Время работы (формат)")
    
    components: Dict[str, ComponentStatus] = Field(
        default_factory=dict,
        description="Статус компонентов"
    )
    
    active_calls: int = Field(0, description="Активных звонков")
    max_calls: int = Field(0, description="Максимум звонков")
    queue_size: int = Field(0, description="Размер очереди дозвона")
    
    mode: SystemMode = Field(SystemMode.NORMAL, description="Режим работы")
    
    hostname: Optional[str] = Field(None, description="Имя хоста")
    instance_id: Optional[str] = Field(None, description="ID экземпляра")
    
    @model_validator(mode='after')
    def format_uptime(self) -> 'HealthCheckResponse':
        """Форматирование uptime"""
        if self.uptime_seconds:
            days = int(self.uptime_seconds // 86400)
            hours = int((self.uptime_seconds % 86400) // 3600)
            minutes = int((self.uptime_seconds % 3600) // 60)
            seconds = int(self.uptime_seconds % 60)
            
            parts = []
            if days > 0:
                parts.append(f"{days}д")
            if hours > 0:
                parts.append(f"{hours}ч")
            if minutes > 0:
                parts.append(f"{minutes}м")
            parts.append(f"{seconds}с")
            
            self.uptime_formatted = " ".join(parts)
        
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "version": "3.0.0",
                "timestamp": "2024-01-01T00:00:00Z",
                "uptime_seconds": 86400.0,
                "uptime_formatted": "1д 0ч 0м 0с",
                "components": {
                    "database": {
                        "status": "healthy",
                        "message": "Connected to PostgreSQL",
                        "latency_ms": 2.5
                    },
                    "redis": {
                        "status": "healthy",
                        "message": "Connected",
                        "latency_ms": 0.8
                    },
                    "ami": {
                        "status": "healthy",
                        "message": "Connected to Asterisk",
                        "latency_ms": 5.2
                    },
                    "transcription": {
                        "status": "healthy",
                        "message": "Whisper (small)",
                        "details": {"engine": "whisper", "model": "small"}
                    }
                },
                "active_calls": 12,
                "max_calls": 50,
                "queue_size": 145,
                "mode": "normal",
                "hostname": "autodialer-01",
                "instance_id": "autodialer-01:abc123"
            }
        }
    }


class LivenessResponse(BaseSchema):
    """
    Ответ liveness probe (для Kubernetes).
    """
    alive: bool = Field(True, description="Приложение живо")


class ReadinessResponse(BaseSchema):
    """
    Ответ readiness probe (для Kubernetes).
    """
    ready: bool = Field(True, description="Приложение готово принимать запросы")
    reason: Optional[str] = Field(None, description="Причина неготовности")


# =============================================
# Статус системы
# =============================================
class SystemStatusResponse(BaseSchema):
    """
    Полный статус системы.
    """
    # Общая информация
    status: SystemComponentStatus = Field(..., description="Статус системы")
    version: str = Field(..., description="Версия")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время")
    uptime_seconds: float = Field(..., description="Uptime (сек)")
    
    # Состояние
    enabled: bool = Field(..., description="Система включена")
    mode: SystemMode = Field(SystemMode.NORMAL, description="Режим")
    
    # Дозвон
    active_calls: int = Field(0, description="Активных звонков")
    max_calls: int = Field(50, description="Максимум звонков")
    queue_size: int = Field(0, description="Размер очереди")
    current_cps: float = Field(0.0, description="Текущий CPS")
    
    # Задачи
    tasks_running: int = Field(0, description="Выполняется задач")
    tasks_pending: int = Field(0, description="Ожидает задач")
    
    # Подключения
    database_connected: bool = Field(False, description="БД подключена")
    redis_connected: bool = Field(False, description="Redis подключен")
    ami_connected: bool = Field(False, description="AMI подключен")
    
    # Компоненты
    components: Dict[str, ComponentStatus] = Field(default_factory=dict, description="Статус компонентов")
    
    # Ресурсы
    memory_usage_mb: Optional[float] = Field(None, description="Использование памяти (МБ)")
    cpu_usage_percent: Optional[float] = Field(None, description="Использование CPU (%)")
    
    # Метаданные
    hostname: Optional[str] = Field(None, description="Имя хоста")
    instance_id: Optional[str] = Field(None, description="ID экземпляра")
    environment: str = Field("production", description="Окружение")


class SystemEnableResponse(BaseSchema):
    """
    Ответ на включение системы.
    """
    success: bool = Field(True, description="Успешно")
    message: str = Field("System enabled", description="Сообщение")
    enabled: bool = Field(True, description="Включена")


class SystemDisableResponse(BaseSchema):
    """
    Ответ на выключение системы (kill switch).
    """
    success: bool = Field(True, description="Успешно")
    message: str = Field("System disabled", description="Сообщение")
    enabled: bool = Field(False, description="Выключена")
    killed_calls: int = Field(0, description="Принудительно завершено звонков")
    cleared_queue: int = Field(0, description="Очищено из очереди")


# =============================================
# Системная статистика
# =============================================
class SystemStatsResponse(BaseSchema):
    """
    Системная статистика.
    """
    # Период
    from_date: Optional[datetime] = Field(None, description="С даты")
    to_date: Optional[datetime] = Field(None, description="По дату")
    
    # Кампании
    total_campaigns: int = Field(0, description="Всего кампаний")
    active_campaigns: int = Field(0, description="Активных кампаний")
    completed_campaigns: int = Field(0, description="Завершённых кампаний")
    
    # Контакты
    total_contacts: int = Field(0, description="Всего контактов")
    active_contacts: int = Field(0, description="Активных контактов")
    blacklisted_contacts: int = Field(0, description="В чёрном списке")
    
    # Звонки
    total_calls: int = Field(0, description="Всего звонков")
    calls_today: int = Field(0, description="Звонков сегодня")
    calls_this_hour: int = Field(0, description="Звонков за час")
    
    # Результаты
    agreed_calls: int = Field(0, description="Согласились")
    declined_calls: int = Field(0, description="Отказались")
    busy_calls: int = Field(0, description="Занято")
    noanswer_calls: int = Field(0, description="Нет ответа")
    failed_calls: int = Field(0, description="Ошибки")
    
    # Метрики
    conversion_rate: float = Field(0.0, description="Конверсия (%)")
    answer_rate: float = Field(0.0, description="Доля отвеченных (%)")
    avg_call_duration: float = Field(0.0, description="Средняя длительность (сек)")
    total_call_duration: int = Field(0, description="Общая длительность (сек)")
    
    # Входящие звонки
    incoming_calls_total: int = Field(0, description="Входящих звонков")
    incoming_calls_today: int = Field(0, description="Входящих сегодня")
    
    # Аудио
    audio_files_total: int = Field(0, description="Аудиофайлов")
    audio_files_size_mb: float = Field(0.0, description="Общий размер (МБ)")
    
    # Пользователи
    users_total: int = Field(0, description="Пользователей")
    users_active: int = Field(0, description="Активных пользователей")
    
    # API
    api_keys_total: int = Field(0, description="API ключей")
    api_requests_today: int = Field(0, description="API запросов сегодня")


class ResourceUsageResponse(BaseSchema):
    """
    Использование системных ресурсов.
    """
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время")
    
    # CPU
    cpu_percent: float = Field(..., description="CPU (%)")
    cpu_count: int = Field(..., description="Количество ядер")
    
    # Память
    memory_total_mb: float = Field(..., description="Всего памяти (МБ)")
    memory_used_mb: float = Field(..., description="Использовано (МБ)")
    memory_percent: float = Field(..., description="Использование памяти (%)")
    
    # Диск
    disk_total_gb: float = Field(..., description="Всего диска (ГБ)")
    disk_used_gb: float = Field(..., description="Использовано (ГБ)")
    disk_percent: float = Field(..., description="Использование диска (%)")
    
    # Сеть
    network_rx_mb: float = Field(0.0, description="Принято (МБ)")
    network_tx_mb: float = Field(0.0, description="Отправлено (МБ)")
    
    # База данных
    db_connections: int = Field(0, description="Соединений БД")
    db_pool_size: int = Field(0, description="Размер пула")
    
    # Redis
    redis_memory_mb: float = Field(0.0, description="Redis память (МБ)")
    redis_keys: int = Field(0, description="Ключей Redis")


# =============================================
# Конфигурация системы
# =============================================
class SystemConfigResponse(BaseSchema):
    """
    Конфигурация системы (только для чтения).
    """
    # Основные настройки
    version: str = Field(..., description="Версия")
    environment: str = Field(..., description="Окружение")
    debug: bool = Field(..., description="Режим отладки")
    
    # Дозвон
    max_calls: int = Field(..., description="Максимум звонков")
    default_cps: int = Field(..., description="CPS по умолчанию")
    call_timeout: int = Field(..., description="Таймаут звонка")
    max_retries: int = Field(..., description="Максимум повторов")
    
    # База данных
    database_host: str = Field(..., description="Хост БД")
    database_name: str = Field(..., description="Имя БД")
    database_pool_size: int = Field(..., description="Размер пула")
    
    # Redis
    redis_host: str = Field(..., description="Хост Redis")
    redis_sentinel_enabled: bool = Field(..., description="Sentinel включён")
    
    # AMI
    ami_host: str = Field(..., description="Хост AMI")
    freepbx_extension: str = Field(..., description="Extension FreePBX")
    
    # Транскрибация
    transcription_enabled: bool = Field(..., description="Транскрибация включена")
    transcription_engine: str = Field(..., description="Движок транскрибации")
    
    # TTS
    tts_enabled: bool = Field(..., description="TTS включён")
    tts_engine: str = Field(..., description="Движок TTS")
    
    # Логирование
    log_level: str = Field(..., description="Уровень логирования")
    log_format: str = Field(..., description="Формат логов")
    
    # Метрики
    metrics_enabled: bool = Field(..., description="Метрики включены")
    
    # CORS
    cors_origins: List[str] = Field(default_factory=list, description="CORS origins")


# =============================================
# WebSocket события
# =============================================
class WebSocketMessage(BaseSchema):
    """
    Базовое WebSocket сообщение.
    """
    type: str = Field(..., description="Тип сообщения")
    data: Dict[str, Any] = Field(..., description="Данные")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время")


class LiveCallEvent(BaseSchema):
    """
    Событие живого звонка (WebSocket).
    """
    event: str = Field(..., description="Тип события (dial_begin/answer/hangup/dtmf)")
    
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


class CampaignProgressEvent(BaseSchema):
    """
    Событие прогресса кампании (WebSocket).
    """
    campaign_id: int = Field(..., description="ID кампании")
    campaign_name: str = Field(..., description="Название")
    
    total_contacts: int = Field(..., description="Всего контактов")
    called_contacts: int = Field(..., description="Прозвонено")
    
    agreed: int = Field(0, description="Согласились")
    declined: int = Field(0, description="Отказались")
    
    progress_percent: float = Field(..., description="Прогресс (%)")
    active_calls: int = Field(0, description="Активных звонков")
    current_cps: float = Field(0.0, description="Текущий CPS")
    
    estimated_completion: Optional[datetime] = Field(None, description="Ожидаемое завершение")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время")


class SystemNotificationEvent(BaseSchema):
    """
    Системное уведомление (WebSocket).
    """
    level: str = Field(..., description="Уровень (info/warning/error/critical)")
    title: str = Field(..., description="Заголовок")
    message: str = Field(..., description="Сообщение")
    details: Optional[Dict[str, Any]] = Field(None, description="Детали")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время")


# =============================================
# Логи
# =============================================
class LogEntryResponse(BaseSchema):
    """
    Запись лога.
    """
    timestamp: datetime = Field(..., description="Время")
    level: str = Field(..., description="Уровень")
    logger: str = Field(..., description="Имя логгера")
    message: str = Field(..., description="Сообщение")
    
    correlation_id: Optional[str] = Field(None, description="Correlation ID")
    request_id: Optional[str] = Field(None, description="Request ID")
    user_id: Optional[int] = Field(None, description="User ID")
    campaign_id: Optional[int] = Field(None, description="Campaign ID")
    
    module: Optional[str] = Field(None, description="Модуль")
    function: Optional[str] = Field(None, description="Функция")
    line: Optional[int] = Field(None, description="Строка")
    
    exception: Optional[Dict[str, Any]] = Field(None, description="Исключение")


class LogsResponse(BaseSchema):
    """
    Ответ со списком логов.
    """
    items: List[LogEntryResponse] = Field(..., description="Записи лога")
    total: int = Field(..., description="Всего записей")
    page: int = Field(..., description="Страница")
    page_size: int = Field(..., description="Размер страницы")


class LogConfigUpdateRequest(BaseSchema):
    """
    Запрос на обновление конфигурации логирования.
    """
    level: Optional[LogLevel] = Field(None, description="Уровень логирования")
    format: Optional[str] = Field(None, description="Формат (console/json)")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "SystemComponentStatus",
    "SystemMode",
    "LogLevel",
    
    # Статус компонента
    "ComponentStatus",
    
    # Health Check
    "HealthCheckResponse",
    "LivenessResponse",
    "ReadinessResponse",
    
    # Статус системы
    "SystemStatusResponse",
    "SystemEnableResponse",
    "SystemDisableResponse",
    
    # Статистика
    "SystemStatsResponse",
    "ResourceUsageResponse",
    
    # Конфигурация
    "SystemConfigResponse",
    
    # WebSocket
    "WebSocketMessage",
    "LiveCallEvent",
    "CampaignProgressEvent",
    "SystemNotificationEvent",
    
    # Логи
    "LogEntryResponse",
    "LogsResponse",
    "LogConfigUpdateRequest",
]
