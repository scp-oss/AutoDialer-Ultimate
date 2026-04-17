#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Базовые модели данных
AutoDialer Ultimate v3.0.0

Предоставляет базовые классы Pydantic для всех моделей:
- BaseSchema (базовая схема)
- TimestampSchema (схема с временными метками)
- SuccessResponse / ErrorResponse
- PaginatedResponse
- и другие общие модели
"""

from datetime import datetime
from typing import Optional, List, Any, Dict, Union, TypeVar, Generic
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


# =============================================
# Типы
# =============================================
T = TypeVar('T')


# =============================================
# Базовые схемы
# =============================================
class BaseSchema(BaseModel):
    """
    Базовая схема с общей конфигурацией.
    
    Все модели должны наследоваться от этого класса.
    """
    
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
        str_strip_whitespace=True,
        validate_default=True,
        ser_json_timedelta='iso8601',
        ser_json_bytes='base64',
    )


class TimestampSchema(BaseSchema):
    """
    Схема с полями created_at и updated_at.
    """
    created_at: Optional[datetime] = Field(None, description="Дата создания")
    updated_at: Optional[datetime] = Field(None, description="Дата обновления")


class SoftDeleteSchema(TimestampSchema):
    """
    Схема с поддержкой мягкого удаления.
    """
    deleted_at: Optional[datetime] = Field(None, description="Дата удаления")
    is_deleted: bool = Field(False, description="Удалена ли запись")


class BaseResponse(BaseSchema):
    """
    Базовый класс для всех ответов API.
    """
    pass


# =============================================
# Ответы API
# =============================================
class SuccessResponse(BaseResponse):
    """
    Успешный ответ API.
    
    Пример:
        {
            "success": true,
            "message": "Операция выполнена успешно",
            "data": {"id": 123}
        }
    """
    success: bool = Field(True, description="Признак успешности")
    message: str = Field(..., description="Сообщение")
    data: Optional[Any] = Field(None, description="Данные ответа")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Операция выполнена успешно",
                "data": {"id": 123}
            }
        }
    )


class ErrorResponse(BaseResponse):
    """
    Ответ с ошибкой API.
    
    Пример:
        {
            "error": "Not Found",
            "detail": "Campaign with id 123 not found",
            "code": "CAMPAIGN_NOT_FOUND",
            "timestamp": "2024-01-01T00:00:00Z"
        }
    """
    error: str = Field(..., description="Краткое описание ошибки")
    detail: Optional[str] = Field(None, description="Подробности ошибки")
    code: Optional[str] = Field(None, description="Код ошибки")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время ошибки")
    path: Optional[str] = Field(None, description="Путь запроса")
    method: Optional[str] = Field(None, description="HTTP метод")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "Not Found",
                "detail": "Campaign with id 123 not found",
                "code": "CAMPAIGN_NOT_FOUND",
                "timestamp": "2024-01-01T00:00:00Z"
            }
        }
    )


class ValidationErrorResponse(BaseResponse):
    """
    Ответ с ошибками валидации.
    """
    error: str = Field("Validation Error", description="Тип ошибки")
    detail: str = Field("Request validation failed", description="Описание")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Список ошибок валидации")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "Validation Error",
                "detail": "Request validation failed",
                "errors": [
                    {
                        "loc": ["body", "name"],
                        "msg": "field required",
                        "type": "value_error.missing"
                    }
                ]
            }
        }
    )


# =============================================
# Пагинация
# =============================================
class PaginationParams(BaseModel):
    """
    Параметры пагинации для запросов.
    
    Использование в FastAPI:
        @router.get("/items")
        async def get_items(pagination: PaginationParams = Depends()):
            ...
    """
    page: int = Field(1, ge=1, description="Номер страницы")
    page_size: int = Field(20, ge=1, le=100, description="Размер страницы")
    
    @property
    def offset(self) -> int:
        """Вычислить offset для SQL запроса"""
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        """Alias для page_size"""
        return self.page_size
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "page": 1,
                "page_size": 20
            }
        }
    )


class PaginatedResponse(BaseResponse, Generic[T]):
    """
    Пагинированный ответ API.
    
    Пример:
        {
            "items": [...],
            "total": 100,
            "page": 1,
            "page_size": 20,
            "total_pages": 5,
            "has_next": true,
            "has_prev": false
        }
    """
    items: List[T] = Field(..., description="Элементы на текущей странице")
    total: int = Field(..., ge=0, description="Общее количество элементов")
    page: int = Field(..., ge=1, description="Текущая страница")
    page_size: int = Field(..., ge=1, description="Размер страницы")
    total_pages: int = Field(..., ge=0, description="Всего страниц")
    
    @property
    def has_next(self) -> bool:
        """Есть ли следующая страница"""
        return self.page < self.total_pages
    
    @property
    def has_prev(self) -> bool:
        """Есть ли предыдущая страница"""
        return self.page > 1
    
    @property
    def next_page(self) -> Optional[int]:
        """Номер следующей страницы"""
        return self.page + 1 if self.has_next else None
    
    @property
    def prev_page(self) -> Optional[int]:
        """Номер предыдущей страницы"""
        return self.page - 1 if self.has_prev else None
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int
    ) -> "PaginatedResponse[T]":
        """
        Создать пагинированный ответ.
        
        Args:
            items: Элементы
            total: Общее количество
            page: Текущая страница
            page_size: Размер страницы
        
        Returns:
            PaginatedResponse
        """
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if page_size > 0 else 0
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь с дополнительными полями"""
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_prev": self.has_prev,
            "next_page": self.next_page,
            "prev_page": self.prev_page,
        }
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [{"id": 1, "name": "Item 1"}],
                "total": 100,
                "page": 1,
                "page_size": 20,
                "total_pages": 5
            }
        }
    )


class CursorPaginatedResponse(BaseResponse, Generic[T]):
    """
    Пагинированный ответ с использованием курсора.
    
    Используется для больших наборов данных.
    """
    items: List[T] = Field(..., description="Элементы")
    next_cursor: Optional[str] = Field(None, description="Курсор для следующей страницы")
    prev_cursor: Optional[str] = Field(None, description="Курсор для предыдущей страницы")
    has_more: bool = Field(..., description="Есть ли ещё элементы")
    total: Optional[int] = Field(None, description="Общее количество (опционально)")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        next_cursor: Optional[str] = None,
        prev_cursor: Optional[str] = None,
        has_more: bool = False,
        total: Optional[int] = None
    ) -> "CursorPaginatedResponse[T]":
        return cls(
            items=items,
            next_cursor=next_cursor,
            prev_cursor=prev_cursor,
            has_more=has_more,
            total=total
        )


# =============================================
# Статусы
# =============================================
class StatusResponse(BaseResponse):
    """
    Ответ со статусом.
    """
    status: str = Field(..., description="Статус")
    message: Optional[str] = Field(None, description="Сообщение")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "message": "Service is running"
            }
        }
    )


class HealthCheckResponse(BaseResponse):
    """
    Ответ проверки здоровья.
    """
    status: str = Field(..., description="Общий статус (healthy/degraded/unhealthy)")
    version: str = Field(..., description="Версия приложения")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время проверки")
    uptime_seconds: float = Field(..., description="Время работы в секундах")
    components: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Статус компонентов")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "version": "3.0.0",
                "timestamp": "2024-01-01T00:00:00Z",
                "uptime_seconds": 86400.0,
                "components": {
                    "database": {"status": "healthy"},
                    "redis": {"status": "healthy"},
                    "ami": {"status": "healthy"}
                }
            }
        }
    )


class ComponentStatus(BaseModel):
    """
    Статус отдельного компонента.
    """
    status: str = Field(..., description="Статус (healthy/unhealthy/degraded)")
    message: Optional[str] = Field(None, description="Дополнительное сообщение")
    latency_ms: Optional[float] = Field(None, description="Задержка в миллисекундах")
    last_check: Optional[datetime] = Field(None, description="Время последней проверки")
    error: Optional[str] = Field(None, description="Ошибка (если есть)")


# =============================================
# Метаданные
# =============================================
class MetaResponse(BaseResponse):
    """
    Ответ с метаданными.
    """
    meta: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    data: Any = Field(..., description="Данные")


class BulkOperationResponse(BaseResponse):
    """
    Ответ массовой операции.
    """
    total: int = Field(..., description="Всего обработано")
    successful: int = Field(..., description="Успешно")
    failed: int = Field(..., description="С ошибками")
    skipped: int = Field(0, description="Пропущено")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки")
    details: Optional[Dict[str, Any]] = Field(None, description="Детали")
    
    @property
    def success_rate(self) -> float:
        """Процент успешных операций"""
        if self.total == 0:
            return 100.0
        return round(self.successful / self.total * 100, 2)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total": 100,
                "successful": 95,
                "failed": 3,
                "skipped": 2,
                "errors": [
                    {"item": 5, "error": "Duplicate phone number"}
                ],
                "details": {"imported": 95}
            }
        }
    )


class IdResponse(BaseResponse):
    """
    Ответ с ID созданной/обновлённой записи.
    """
    id: Union[int, str] = Field(..., description="ID записи")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"id": 123}
        }
    )


class CountResponse(BaseResponse):
    """
    Ответ с количеством.
    """
    count: int = Field(..., ge=0, description="Количество")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"count": 42}
        }
    )


class ExistsResponse(BaseResponse):
    """
    Ответ с проверкой существования.
    """
    exists: bool = Field(..., description="Существует ли")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"exists": True}
        }
    )


# =============================================
# Фильтры и поиск
# =============================================
class SearchParams(BaseModel):
    """
    Параметры поиска.
    """
    query: Optional[str] = Field(None, description="Поисковый запрос", min_length=1)
    fields: Optional[List[str]] = Field(None, description="Поля для поиска")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "test",
                "fields": ["name", "description"]
            }
        }
    )


class FilterParams(BaseModel):
    """
    Параметры фильтрации.
    """
    filters: Dict[str, Any] = Field(default_factory=dict, description="Фильтры")
    
    def has_filter(self, name: str) -> bool:
        """Проверить наличие фильтра"""
        return name in self.filters
    
    def get_filter(self, name: str, default: Any = None) -> Any:
        """Получить значение фильтра"""
        return self.filters.get(name, default)


class DateRangeParams(BaseModel):
    """
    Параметры диапазона дат.
    """
    from_date: Optional[datetime] = Field(None, description="Дата начала")
    to_date: Optional[datetime] = Field(None, description="Дата окончания")
    
    def validate(self) -> None:
        """Проверить корректность диапазона"""
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date cannot be after to_date")
    
    @property
    def is_valid(self) -> bool:
        """Проверить, задан ли диапазон"""
        return self.from_date is not None or self.to_date is not None


class SortParams(BaseModel):
    """
    Параметры сортировки.
    """
    sort_by: str = Field("id", description="Поле для сортировки")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)", pattern="^(ASC|DESC)$")
    
    @property
    def order_clause(self) -> str:
        """SQL ORDER BY clause"""
        return f"{self.sort_by} {self.sort_order.upper()}"
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sort_by": "created_at",
                "sort_order": "DESC"
            }
        }
    )


# =============================================
# Утилиты
# =============================================
def model_to_dict(model: BaseModel, exclude_none: bool = True, by_alias: bool = False) -> Dict[str, Any]:
    """
    Преобразовать Pydantic модель в словарь.
    
    Args:
        model: Pydantic модель
        exclude_none: Исключить None значения
        by_alias: Использовать алиасы полей
    
    Returns:
        Словарь с данными
    """
    return model.model_dump(exclude_none=exclude_none, by_alias=by_alias)


def dict_to_model(data: Dict[str, Any], model_class: type[BaseModel]) -> BaseModel:
    """
    Преобразовать словарь в Pydantic модель.
    
    Args:
        data: Словарь с данными
        model_class: Класс модели
    
    Returns:
        Экземпляр модели
    """
    return model_class.model_validate(data)


def parse_json_field(value: Union[str, Dict, List, None]) -> Any:
    """
    Распарсить JSON поле из БД.
    
    Args:
        value: Значение из БД (строка JSON или уже объект)
    
    Returns:
        Распарсенный объект
    """
    if value is None:
        return None
    
    if isinstance(value, (dict, list)):
        return value
    
    if isinstance(value, str):
        import json
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    
    return value


def to_camel_case_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Преобразовать ключи словаря из snake_case в camelCase.
    """
    result = {}
    for key, value in data.items():
        camel_key = to_camel(key)
        if isinstance(value, dict):
            result[camel_key] = to_camel_case_dict(value)
        elif isinstance(value, list):
            result[camel_key] = [
                to_camel_case_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[camel_key] = value
    return result


def to_snake_case_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Преобразовать ключи словаря из camelCase в snake_case.
    """
    import re
    
    def camel_to_snake(name: str) -> str:
        return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    
    result = {}
    for key, value in data.items():
        snake_key = camel_to_snake(key)
        if isinstance(value, dict):
            result[snake_key] = to_snake_case_dict(value)
        elif isinstance(value, list):
            result[snake_key] = [
                to_snake_case_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[snake_key] = value
    return result


# =============================================
# Конфигурация для API с camelCase
# =============================================
class CamelCaseModel(BaseModel):
    """
    Модель с автоматическим преобразованием в camelCase для API.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Базовые
    "BaseSchema",
    "TimestampSchema",
    "SoftDeleteSchema",
    "BaseResponse",
    
    # Ответы
    "SuccessResponse",
    "ErrorResponse",
    "ValidationErrorResponse",
    
    # Пагинация
    "PaginationParams",
    "PaginatedResponse",
    "CursorPaginatedResponse",
    
    # Статусы
    "StatusResponse",
    "HealthCheckResponse",
    "ComponentStatus",
    
    # Метаданные
    "MetaResponse",
    "BulkOperationResponse",
    "IdResponse",
    "CountResponse",
    "ExistsResponse",
    
    # Фильтры
    "SearchParams",
    "FilterParams",
    "DateRangeParams",
    "SortParams",
    
    # Утилиты
    "model_to_dict",
    "dict_to_model",
    "parse_json_field",
    "to_camel_case_dict",
    "to_snake_case_dict",
    
    # CamelCase
    "CamelCaseModel",
]
