#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели задач и фоновых процессов
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Управления фоновыми задачами
- Отслеживания статуса задач
- Статистики выполнения
- Очередей задач
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class TaskStatus(str, Enum):
    """Статус задачи"""
    PENDING = "pending"           # Ожидает запуска
    QUEUED = "queued"             # В очереди
    RUNNING = "running"           # Выполняется
    PAUSED = "paused"             # Приостановлена
    COMPLETED = "completed"       # Успешно завершена
    FAILED = "failed"             # Завершилась с ошибкой
    CANCELLED = "cancelled"       # Отменена
    TIMEOUT = "timeout"           # Превышен таймаут
    RETRYING = "retrying"         # Повторная попытка
    ZOMBIE = "zombie"             # Зависшая (убита watchdog)


class TaskPriority(int, Enum):
    """Приоритет задачи"""
    LOWEST = 0
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class TaskType(str, Enum):
    """Тип задачи"""
    CAMPAIGN = "campaign"             # Обзвон кампании
    TTS_GENERATION = "tts_generation" # Генерация TTS
    TRANSCRIPTION = "transcription"   # Транскрибация
    IMPORT = "import"                 # Импорт данных
    EXPORT = "export"                 # Экспорт данных
    CLEANUP = "cleanup"               # Очистка
    BACKUP = "backup"                 # Резервное копирование
    REPORT = "report"                 # Генерация отчёта
    MAINTENANCE = "maintenance"       # Обслуживание
    CUSTOM = "custom"                 # Пользовательская


class TaskCategory(str, Enum):
    """Категория задачи"""
    SYSTEM = "system"           # Системные
    CAMPAIGN = "campaign"       # Кампании
    AUDIO = "audio"             # Аудио
    DATA = "data"               # Данные
    REPORT = "report"           # Отчёты
    MAINTENANCE = "maintenance" # Обслуживание
    CUSTOM = "custom"           # Пользовательские


# =============================================
# Информация о задаче
# =============================================
class TaskProgress(BaseSchema):
    """Прогресс выполнения задачи"""
    current: int = Field(0, ge=0, description="Текущее значение")
    total: int = Field(0, ge=0, description="Всего")
    percent: float = Field(0.0, ge=0, le=100, description="Процент выполнения")
    message: Optional[str] = Field(None, description="Сообщение о прогрессе")
    updated_at: Optional[datetime] = Field(None, description="Время обновления")
    
    @field_validator('percent', mode='before')
    @classmethod
    def calculate_percent(cls, v, info) -> float:
        """Автоматический расчёт процента"""
        if v is not None:
            return v
        data = info.data
        if data.get('total', 0) > 0:
            return round(data.get('current', 0) / data['total'] * 100, 2)
        return 0.0


class TaskError(BaseSchema):
    """Информация об ошибке задачи"""
    type: str = Field(..., description="Тип ошибки")
    message: str = Field(..., description="Сообщение")
    traceback: Optional[str] = Field(None, description="Трассировка")
    occurred_at: datetime = Field(default_factory=datetime.utcnow, description="Время ошибки")
    retry_count: int = Field(0, description="Номер попытки")


class TaskDependency(BaseSchema):
    """Зависимость задачи"""
    task_id: str = Field(..., description="ID задачи")
    status: TaskStatus = Field(..., description="Статус зависимости")
    required: bool = Field(True, description="Обязательная")


# =============================================
# Запросы
# =============================================
class TaskCreateRequest(BaseSchema):
    """
    Запрос на создание задачи.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название задачи")
    task_type: TaskType = Field(..., description="Тип задачи")
    category: TaskCategory = Field(TaskCategory.CUSTOM, description="Категория")
    priority: TaskPriority = Field(TaskPriority.NORMAL, description="Приоритет")
    
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Параметры")
    
    timeout: Optional[int] = Field(None, ge=0, description="Таймаут (секунд)")
    max_retries: int = Field(3, ge=0, le=10, description="Максимум повторных попыток")
    retry_delay: int = Field(60, ge=1, le=3600, description="Задержка между попытками (сек)")
    
    scheduled_at: Optional[datetime] = Field(None, description="Запланировано на")
    expires_at: Optional[datetime] = Field(None, description="Истекает")
    
    dependencies: List[str] = Field(default_factory=list, description="ID зависимых задач")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Экспорт контактов",
                "task_type": "export",
                "category": "data",
                "priority": 2,
                "parameters": {
                    "format": "csv",
                    "group_id": 1
                },
                "timeout": 300,
                "max_retries": 3,
                "tags": ["export", "contacts"]
            }
        }
    }


class TaskUpdateRequest(BaseSchema):
    """
    Запрос на обновление задачи.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название")
    priority: Optional[TaskPriority] = Field(None, description="Приоритет")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Параметры")
    timeout: Optional[int] = Field(None, ge=0, description="Таймаут")
    tags: Optional[List[str]] = Field(None, description="Теги")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Метаданные")


class TaskBulkActionRequest(BaseSchema):
    """
    Запрос на массовое действие с задачами.
    """
    task_ids: List[str] = Field(..., min_length=1, description="ID задач")
    action: str = Field(..., description="Действие (cancel/pause/resume/retry/delete)")
    
    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"cancel", "pause", "resume", "retry", "delete", "archive"}
        if v not in allowed:
            raise ValueError(f"Недопустимое действие. Разрешено: {', '.join(allowed)}")
        return v


class TaskFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию задач.
    """
    search: Optional[str] = Field(None, description="Поиск по названию, ID")
    
    status: Optional[List[TaskStatus]] = Field(None, description="Статусы")
    task_type: Optional[List[TaskType]] = Field(None, description="Типы")
    category: Optional[List[TaskCategory]] = Field(None, description="Категории")
    priority: Optional[List[TaskPriority]] = Field(None, description="Приоритеты")
    
    tags: Optional[List[str]] = Field(None, description="Теги")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    
    created_after: Optional[datetime] = Field(None, description="Создана после")
    created_before: Optional[datetime] = Field(None, description="Создана до")
    scheduled_after: Optional[datetime] = Field(None, description="Запланирована после")
    scheduled_before: Optional[datetime] = Field(None, description="Запланирована до")
    
    has_dependencies: Optional[bool] = Field(None, description="Есть зависимости")
    is_dependency: Optional[bool] = Field(None, description="Является зависимостью")
    
    sort_by: str = Field("created_at", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Ответы
# =============================================
class TaskResponse(TimestampSchema):
    """
    Ответ с информацией о задаче.
    """
    id: str = Field(..., description="ID задачи")
    name: str = Field(..., description="Название")
    task_type: TaskType = Field(..., description="Тип")
    category: TaskCategory = Field(..., description="Категория")
    status: TaskStatus = Field(..., description="Статус")
    priority: TaskPriority = Field(..., description="Приоритет")
    
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Параметры")
    
    progress: Optional[TaskProgress] = Field(None, description="Прогресс")
    result: Optional[Any] = Field(None, description="Результат")
    error: Optional[TaskError] = Field(None, description="Ошибка")
    
    timeout: Optional[int] = Field(None, description="Таймаут")
    max_retries: int = Field(3, description="Максимум попыток")
    retry_count: int = Field(0, description="Номер текущей попытки")
    
    scheduled_at: Optional[datetime] = Field(None, description="Запланирована")
    started_at: Optional[datetime] = Field(None, description="Запущена")
    completed_at: Optional[datetime] = Field(None, description="Завершена")
    expires_at: Optional[datetime] = Field(None, description="Истекает")
    
    duration: Optional[float] = Field(None, description="Длительность (сек)")
    queue_time: Optional[float] = Field(None, description="Время в очереди (сек)")
    
    dependencies: List[TaskDependency] = Field(default_factory=list, description="Зависимости")
    dependent_tasks: List[str] = Field(default_factory=list, description="Зависимые задачи")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "task_abc123def456",
                "name": "Экспорт контактов",
                "task_type": "export",
                "category": "data",
                "status": "running",
                "priority": 2,
                "progress": {
                    "current": 500,
                    "total": 1000,
                    "percent": 50.0,
                    "message": "Экспортировано 500 из 1000 контактов"
                },
                "timeout": 300,
                "max_retries": 3,
                "retry_count": 0,
                "started_at": "2024-01-01T10:00:00Z",
                "duration": 15.5,
                "created_at": "2024-01-01T09:55:00Z"
            }
        }
    }


class TaskDetailResponse(TaskResponse):
    """
    Детальный ответ о задаче.
    """
    logs: List[Dict[str, Any]] = Field(default_factory=list, description="Логи выполнения")
    events: List[Dict[str, Any]] = Field(default_factory=list, description="События")
    retry_history: List[TaskError] = Field(default_factory=list, description="История попыток")
    resource_usage: Optional[Dict[str, Any]] = Field(None, description="Использование ресурсов")


class TaskListResponse(BaseSchema):
    """
    Ответ со списком задач.
    """
    items: List[TaskResponse] = Field(..., description="Задачи")
    total: int = Field(..., description="Всего задач")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")
    
    summary: Dict[str, Any] = Field(default_factory=dict, description="Сводка")


class TaskStatsResponse(BaseSchema):
    """
    Статистика по задачам.
    """
    period_days: Optional[int] = Field(None, description="Период в днях")
    
    total: int = Field(0, description="Всего задач")
    pending: int = Field(0, description="Ожидают")
    queued: int = Field(0, description="В очереди")
    running: int = Field(0, description="Выполняются")
    completed: int = Field(0, description="Завершены")
    failed: int = Field(0, description="С ошибкой")
    cancelled: int = Field(0, description="Отменены")
    timeout: int = Field(0, description="По таймауту")
    
    avg_duration: float = Field(0.0, description="Средняя длительность (сек)")
    avg_queue_time: float = Field(0.0, description="Среднее время в очереди (сек)")
    success_rate: float = Field(0.0, description="Процент успешных (%)")
    
    by_type: Dict[str, int] = Field(default_factory=dict, description="По типам")
    by_category: Dict[str, int] = Field(default_factory=dict, description="По категориям")
    by_priority: Dict[str, int] = Field(default_factory=dict, description="По приоритетам")
    
    top_slowest: List[Dict[str, Any]] = Field(default_factory=list, description="Самые долгие")
    top_failed: List[Dict[str, Any]] = Field(default_factory=list, description="Частые ошибки")
    
    daily_stats: List[Dict[str, Any]] = Field(default_factory=list, description="По дням")


# =============================================
# Очередь задач
# =============================================
class QueueInfo(BaseSchema):
    """Информация об очереди задач"""
    name: str = Field(..., description="Название очереди")
    size: int = Field(0, description="Размер очереди")
    active: int = Field(0, description="Активных задач")
    completed: int = Field(0, description="Завершено")
    failed: int = Field(0, description="С ошибкой")
    avg_wait_time: float = Field(0.0, description="Среднее ожидание (сек)")
    throughput: float = Field(0.0, description="Пропускная способность (задач/мин)")


class QueuesStatusResponse(BaseSchema):
    """
    Статус всех очередей задач.
    """
    queues: List[QueueInfo] = Field(..., description="Очереди")
    total_pending: int = Field(0, description="Всего ожидает")
    total_active: int = Field(0, description="Всего активно")
    workers: int = Field(0, description="Количество воркеров")


class QueueTaskResponse(BaseSchema):
    """
    Задача в очереди.
    """
    task_id: str = Field(..., description="ID задачи")
    task_name: str = Field(..., description="Название задачи")
    queue_name: str = Field(..., description="Имя очереди")
    position: int = Field(..., description="Позиция в очереди")
    priority: TaskPriority = Field(..., description="Приоритет")
    queued_at: datetime = Field(..., description="Время постановки")
    estimated_start: Optional[datetime] = Field(None, description="Примерное время старта")


# =============================================
# Результат выполнения
# =============================================
class TaskResultResponse(BaseSchema):
    """
    Ответ с результатом выполнения задачи.
    """
    task_id: str = Field(..., description="ID задачи")
    status: TaskStatus = Field(..., description="Статус")
    result: Optional[Any] = Field(None, description="Результат")
    error: Optional[TaskError] = Field(None, description="Ошибка")
    duration: float = Field(..., description="Длительность (сек)")
    completed_at: datetime = Field(..., description="Завершена")


# =============================================
# Отмена/пауза
# =============================================
class TaskCancelResponse(BaseSchema):
    """
    Ответ на отмену задачи.
    """
    task_id: str = Field(..., description="ID задачи")
    cancelled: bool = Field(..., description="Отменена")
    message: str = Field(..., description="Сообщение")
    force: bool = Field(False, description="Принудительно")


class TaskPauseResponse(BaseSchema):
    """
    Ответ на паузу задачи.
    """
    task_id: str = Field(..., description="ID задачи")
    paused: bool = Field(..., description="Приостановлена")
    message: str = Field(..., description="Сообщение")


class TaskResumeResponse(BaseSchema):
    """
    Ответ на возобновление задачи.
    """
    task_id: str = Field(..., description="ID задачи")
    resumed: bool = Field(..., description="Возобновлена")
    message: str = Field(..., description="Сообщение")


class TaskRetryResponse(BaseSchema):
    """
    Ответ на повторный запуск задачи.
    """
    task_id: str = Field(..., description="ID задачи")
    new_task_id: str = Field(..., description="ID новой задачи")
    retried: bool = Field(..., description="Запущена повторно")
    message: str = Field(..., description="Сообщение")


# =============================================
# Массовые операции
# =============================================
class TaskBulkActionResponse(BaseSchema):
    """
    Ответ на массовое действие.
    """
    total: int = Field(..., description="Всего задач")
    successful: List[str] = Field(default_factory=list, description="Успешно обработаны")
    failed: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "TaskStatus",
    "TaskPriority",
    "TaskType",
    "TaskCategory",
    
    # Модели
    "TaskProgress",
    "TaskError",
    "TaskDependency",
    
    # Запросы
    "TaskCreateRequest",
    "TaskUpdateRequest",
    "TaskBulkActionRequest",
    "TaskFilterRequest",
    
    # Ответы
    "TaskResponse",
    "TaskDetailResponse",
    "TaskListResponse",
    "TaskStatsResponse",
    
    # Очередь
    "QueueInfo",
    "QueuesStatusResponse",
    "QueueTaskResponse",
    
    # Результат
    "TaskResultResponse",
    
    # Действия
    "TaskCancelResponse",
    "TaskPauseResponse",
    "TaskResumeResponse",
    "TaskRetryResponse",
    
    # Массовые
    "TaskBulkActionResponse",
]
