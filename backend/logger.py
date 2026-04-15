#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging Module - Структурированное логирование с Correlation ID
AutoDialer Ultimate v3.0.0

ВКЛЮЧЕНЫ ВСЕ ИСПРАВЛЕНИЯ:
- Structured JSON logging (orjson)
- CRITICAL уровень для важных событий
- Correlation ID и Request ID
- Контекстные переменные (user_id, campaign_id)
- Ротация логов
- Цветной консольный вывод
- Таймеры для замера производительности
- Аудит логирование
"""

import logging
import sys
import os
import time
import uuid
import json
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from contextvars import ContextVar
from typing import Optional, Dict, Any, Union, Callable
from functools import wraps

# =============================================
# Попытка импорта быстрого JSON
# =============================================
try:
    import orjson
    
    def fast_json_dumps(obj: Any) -> str:
        """Быстрая сериализация через orjson."""
        return orjson.dumps(obj).decode('utf-8')
    
    def fast_json_loads(s: str) -> Any:
        """Быстрая десериализация через orjson."""
        return orjson.loads(s)
    
    USE_ORJSON = True
except ImportError:
    def fast_json_dumps(obj: Any) -> str:
        """Сериализация через стандартный json."""
        return json.dumps(obj, ensure_ascii=False, default=str)
    
    def fast_json_loads(s: str) -> Any:
        """Десериализация через стандартный json."""
        return json.loads(s)
    
    USE_ORJSON = False


# =============================================
# Контекстные переменные для трассировки
# =============================================
correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
user_id_var: ContextVar[int] = ContextVar('user_id', default=0)
campaign_id_var: ContextVar[int] = ContextVar('campaign_id', default=0)
action_id_var: ContextVar[str] = ContextVar('action_id', default='')
session_id_var: ContextVar[str] = ContextVar('session_id', default='')


# =============================================
# Функции для работы с контекстом
# =============================================
def get_correlation_id() -> str:
    """Получить текущий Correlation ID."""
    return correlation_id_var.get() or 'no-id'


def get_request_id() -> str:
    """Получить текущий Request ID."""
    return request_id_var.get() or 'no-request'


def get_user_id() -> int:
    """Получить текущий User ID."""
    return user_id_var.get() or 0


def get_campaign_id() -> int:
    """Получить текущий Campaign ID."""
    return campaign_id_var.get() or 0


def get_action_id() -> str:
    """Получить текущий Action ID."""
    return action_id_var.get() or ''


def get_session_id() -> str:
    """Получить текущий Session ID."""
    return session_id_var.get() or ''


def set_correlation_id(correlation_id: str) -> None:
    """Установить Correlation ID."""
    correlation_id_var.set(correlation_id)


def set_request_id(request_id: str) -> None:
    """Установить Request ID."""
    request_id_var.set(request_id)


def set_user_id(user_id: int) -> None:
    """Установить User ID."""
    user_id_var.set(user_id)


def set_campaign_id(campaign_id: int) -> None:
    """Установить Campaign ID."""
    campaign_id_var.set(campaign_id)


def set_action_id(action_id: str) -> None:
    """Установить Action ID."""
    action_id_var.set(action_id)


def set_session_id(session_id: str) -> None:
    """Установить Session ID."""
    session_id_var.set(session_id)


def generate_correlation_id() -> str:
    """Сгенерировать новый Correlation ID."""
    return uuid.uuid4().hex[:16]


def generate_request_id() -> str:
    """Сгенерировать новый Request ID."""
    return f"req_{uuid.uuid4().hex[:12]}"


def generate_session_id() -> str:
    """Сгенерировать новый Session ID."""
    return f"sess_{uuid.uuid4().hex[:16]}"


def clear_context():
    """Очистить все контекстные переменные."""
    correlation_id_var.set('')
    request_id_var.set('')
    user_id_var.set(0)
    campaign_id_var.set(0)
    action_id_var.set('')
    session_id_var.set('')


# =============================================
# Дополнительные уровни логирования
# =============================================
# Добавляем уровень CRITICAL (выше ERROR)
CRITICAL = 50  # Уже есть в logging, но явно определяем
AUDIT = 25  # Между INFO и WARNING
TRACE = 5   # Ниже DEBUG

logging.addLevelName(AUDIT, "AUDIT")
logging.addLevelName(TRACE, "TRACE")


def audit(self, message, *args, **kwargs):
    """Логирование аудит-событий."""
    if self.isEnabledFor(AUDIT):
        self._log(AUDIT, message, args, **kwargs)


def trace(self, message, *args, **kwargs):
    """Трассировочное логирование."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


logging.Logger.audit = audit
logging.Logger.trace = trace


# =============================================
# JSON Formatter
# =============================================
class JSONFormatter(logging.Formatter):
    """
    JSON форматтер для структурированного логирования.
    
    Выводит записи в JSON для парсинга лог-агрегаторами (ELK, Loki).
    """
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "correlation_id": getattr(record, 'correlation_id', ''),
            "request_id": getattr(record, 'request_id', ''),
            "user_id": getattr(record, 'user_id', 0),
            "campaign_id": getattr(record, 'campaign_id', 0),
            "action_id": getattr(record, 'action_id', ''),
            "session_id": getattr(record, 'session_id', ''),
            "process": record.process,
            "thread": record.thread,
        }
        
        # Исключение
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }
        
        # Stack trace
        if record.stack_info:
            log_entry["stack_info"] = self.formatStack(record.stack_info)
        
        # Структурированные данные (если есть)
        if hasattr(record, 'structured_data'):
            log_entry.update(record.structured_data)
        
        # Дополнительные атрибуты
        if self.include_extra:
            exclude_keys = {
                'args', 'asctime', 'created', 'exc_info', 'exc_text',
                'filename', 'funcName', 'levelname', 'levelno', 'lineno',
                'module', 'msecs', 'message', 'msg', 'name', 'pathname',
                'process', 'processName', 'relativeCreated', 'stack_info',
                'thread', 'threadName', 'correlation_id', 'request_id',
                'user_id', 'campaign_id', 'action_id', 'session_id',
                'structured_data'
            }
            
            for key, value in record.__dict__.items():
                if key not in exclude_keys and not key.startswith('_'):
                    try:
                        fast_json_dumps({key: value})
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        log_entry[key] = str(value)
        
        return fast_json_dumps(log_entry)


# =============================================
# Console Formatter (Human Readable)
# =============================================
class ConsoleFormatter(logging.Formatter):
    """
    Человеко-читаемый форматтер с цветами для консоли.
    """
    
    # ANSI цвета
    COLORS = {
        'TRACE': '\033[35m',     # Magenta
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'AUDIT': '\033[34m',     # Blue
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[41m',  # Red background
        'RESET': '\033[0m'       # Reset
    }
    
    def __init__(self, use_colors: bool = True, show_context: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()
        self.show_context = show_context
    
    def format(self, record: logging.LogRecord) -> str:
        # Время
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Уровень с цветом
        level = record.levelname
        if self.use_colors:
            level = f"{self.COLORS.get(level, '')}{level:8}{self.COLORS['RESET']}"
        else:
            level = f"{level:8}"
        
        # Контекст
        context_parts = []
        
        if self.show_context:
            corr_id = getattr(record, 'correlation_id', '')
            if corr_id:
                context_parts.append(f"corr={corr_id[:8]}")
            
            req_id = getattr(record, 'request_id', '')
            if req_id:
                context_parts.append(f"req={req_id}")
            
            user_id = getattr(record, 'user_id', 0)
            if user_id:
                context_parts.append(f"user={user_id}")
            
            campaign_id = getattr(record, 'campaign_id', 0)
            if campaign_id:
                context_parts.append(f"camp={campaign_id}")
            
            action_id = getattr(record, 'action_id', '')
            if action_id:
                context_parts.append(f"act={action_id[:8]}")
        
        context = f"[{' | '.join(context_parts)}]" if context_parts else ""
        
        # Имя логгера
        logger_name = record.name
        
        # Сообщение
        message = record.getMessage()
        
        # Основная строка
        log_line = f"{timestamp} {level} {logger_name:20} {context:40} {message}"
        
        # Исключение
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)
        
        # Stack trace
        if record.stack_info:
            log_line += "\n" + self.formatStack(record.stack_info)
        
        return log_line


# =============================================
# Correlation Filter
# =============================================
class CorrelationFilter(logging.Filter):
    """
    Фильтр, добавляющий контекст корреляции в записи лога.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or ''
        record.request_id = request_id_var.get() or ''
        record.user_id = user_id_var.get() or 0
        record.campaign_id = campaign_id_var.get() or 0
        record.action_id = action_id_var.get() or ''
        record.session_id = session_id_var.get() or ''
        return True


# =============================================
# Logger Factory
# =============================================
class LoggerFactory:
    """Фабрика для создания настроенных логгеров."""
    
    _instances: Dict[str, logging.Logger] = {}
    _initialized = False
    _log_level = logging.INFO
    _log_format = "console"  # "console" или "json"
    _log_file: Optional[str] = None
    _error_log_file: Optional[str] = None
    _max_bytes = 10 * 1024 * 1024  # 10 MB
    _backup_count = 10
    _use_colors = True
    _show_context = True
    
    @classmethod
    def configure(
        cls,
        level: Union[str, int] = logging.INFO,
        format_type: str = "console",
        log_file: Optional[str] = None,
        error_log_file: Optional[str] = None,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 10,
        use_colors: bool = True,
        show_context: bool = True
    ):
        """
        Конфигурация фабрики логгеров.
        
        Args:
            level: Уровень логирования
            format_type: "console" или "json"
            log_file: Путь к основному файлу лога
            error_log_file: Путь к файлу ошибок
            max_bytes: Максимальный размер файла
            backup_count: Количество ротаций
            use_colors: Использовать цвета в консоли
            show_context: Показывать контекст в логах
        """
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        
        cls._log_level = level
        cls._log_format = format_type
        cls._log_file = log_file or os.getenv('LOG_FILE', '/opt/autodialer/logs/autodialer.log')
        cls._error_log_file = error_log_file or os.getenv('ERROR_LOG_FILE', '/opt/autodialer/logs/error.log')
        cls._max_bytes = max_bytes
        cls._backup_count = backup_count
        cls._use_colors = use_colors
        cls._show_context = show_context
        cls._initialized = True
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Получить или создать логгер."""
        if name in cls._instances:
            return cls._instances[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(cls._log_level)
        logger.propagate = False
        
        # Удаляем существующие хендлеры
        logger.handlers.clear()
        
        # Добавляем фильтр корреляции
        logger.addFilter(CorrelationFilter())
        
        # Консольный хендлер
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(cls._log_level)
        
        if cls._log_format == "json":
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(ConsoleFormatter(
                use_colors=cls._use_colors,
                show_context=cls._show_context
            ))
        
        logger.addHandler(console_handler)
        
        # Файловый хендлер для всех логов
        if cls._log_file:
            try:
                log_dir = os.path.dirname(cls._log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                
                file_handler = RotatingFileHandler(
                    cls._log_file,
                    maxBytes=cls._max_bytes,
                    backupCount=cls._backup_count
                )
                file_handler.setLevel(logging.DEBUG)
                
                if cls._log_format == "json":
                    file_handler.setFormatter(JSONFormatter())
                else:
                    file_handler.setFormatter(ConsoleFormatter(use_colors=False))
                
                logger.addHandler(file_handler)
            except Exception as e:
                logger.warning(f"Не удалось создать файловый хендлер: {e}")
        
        # Файловый хендлер только для ошибок
        if cls._error_log_file:
            try:
                log_dir = os.path.dirname(cls._error_log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                
                error_handler = RotatingFileHandler(
                    cls._error_log_file,
                    maxBytes=cls._max_bytes,
                    backupCount=cls._backup_count
                )
                error_handler.setLevel(logging.WARNING)
                
                if cls._log_format == "json":
                    error_handler.setFormatter(JSONFormatter())
                else:
                    error_handler.setFormatter(ConsoleFormatter(use_colors=False))
                
                logger.addHandler(error_handler)
            except Exception as e:
                logger.warning(f"Не удалось создать хендлер ошибок: {e}")
        
        cls._instances[name] = logger
        return logger


# =============================================
# Structured Logger Class
# =============================================
class StructuredLogger:
    """
    Обёртка над логгером с поддержкой структурированного логирования.
    """
    
    def __init__(self, logger: logging.Logger):
        self._logger = logger
    
    def _log(self, level: int, msg: str, *args, **kwargs):
        """Внутренний метод логирования с дополнительным контекстом."""
        structured_data = kwargs.pop('structured_data', None)
        exc_info = kwargs.pop('exc_info', None)
        stack_info = kwargs.pop('stack_info', False)
        
        extra = {}
        if structured_data:
            extra['structured_data'] = structured_data
        
        # Добавляем kwargs как extra поля
        if kwargs:
            extra.update(kwargs)
        
        self._logger.log(level, msg, *args, extra=extra, exc_info=exc_info, stack_info=stack_info)
    
    def trace(self, msg: str, *args, **kwargs):
        """Трассировочное логирование."""
        self._log(TRACE, msg, *args, **kwargs)
    
    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)
    
    def audit(self, msg: str, *args, **kwargs):
        """Аудит логирование."""
        self._log(AUDIT, msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        """Критическое логирование."""
        self._log(CRITICAL, msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs):
        """Логирование исключения с трейсбеком."""
        self._log(logging.ERROR, msg, *args, exc_info=True, **kwargs)
    
    def with_context(self, **context) -> 'StructuredLogger':
        """Создать логгер с дополнительным контекстом."""
        return ContextualLogger(self, context)
    
    def bind(self, **context) -> 'StructuredLogger':
        """Алиас для with_context."""
        return self.with_context(**context)


class ContextualLogger(StructuredLogger):
    """Логгер с предустановленным контекстом."""
    
    def __init__(self, parent: StructuredLogger, context: Dict[str, Any]):
        super().__init__(parent._logger)
        self._parent = parent
        self._context = context
    
    def _log(self, level: int, msg: str, *args, **kwargs):
        """Объединение предустановленного контекста с переданным."""
        structured_data = self._context.copy()
        
        if 'structured_data' in kwargs:
            structured_data.update(kwargs.pop('structured_data'))
        
        if kwargs:
            structured_data.update(kwargs)
        
        self._parent._log(level, msg, *args, structured_data=structured_data)
    
    def with_context(self, **context) -> 'ContextualLogger':
        """Добавить ещё контекста."""
        new_context = self._context.copy()
        new_context.update(context)
        return ContextualLogger(self._parent, new_context)
    
    def bind(self, **context) -> 'ContextualLogger':
        """Алиас для with_context."""
        return self.with_context(**context)


# =============================================
# Глобальный экземпляр логгера
# =============================================
# Конфигурация из переменных окружения
_log_level = os.getenv('LOG_LEVEL', 'INFO')
_log_format = os.getenv('LOG_FORMAT', 'console')
_log_file = os.getenv('LOG_FILE', '/opt/autodialer/logs/autodialer.log')
_error_log_file = os.getenv('ERROR_LOG_FILE', '/opt/autodialer/logs/error.log')

LoggerFactory.configure(
    level=_log_level,
    format_type=_log_format,
    log_file=_log_file,
    error_log_file=_error_log_file
)

# Создание логгера по умолчанию
_logger = LoggerFactory.get_logger('autodialer')
logger = StructuredLogger(_logger)


# =============================================
# Convenience Functions
# =============================================
def get_logger(name: str) -> StructuredLogger:
    """Получить именованный логгер."""
    return StructuredLogger(LoggerFactory.get_logger(name))


def trace(msg: str, *args, **kwargs):
    logger.trace(msg, *args, **kwargs)


def debug(msg: str, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    logger.info(msg, *args, **kwargs)


def audit(msg: str, *args, **kwargs):
    logger.audit(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    logger.error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    logger.critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    logger.exception(msg, *args, **kwargs)


# =============================================
# Performance Logging
# =============================================
class LogTimer:
    """Контекстный менеджер для замера времени выполнения."""
    
    def __init__(
        self,
        operation: str,
        logger: Optional[StructuredLogger] = None,
        level: int = logging.DEBUG,
        log_success: bool = True,
        log_failure: bool = True
    ):
        self.operation = operation
        self.logger = logger or globals()['logger']
        self.level = level
        self.log_success = log_success
        self.log_failure = log_failure
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        
        if exc_type and self.log_failure:
            self.logger._log(
                self.level,
                f"{self.operation} failed after {elapsed_ms:.2f}ms",
                structured_data={
                    "operation": self.operation,
                    "duration_ms": round(elapsed_ms, 2),
                    "error": str(exc_val),
                    "error_type": exc_type.__name__
                }
            )
        elif not exc_type and self.log_success:
            self.logger._log(
                self.level,
                f"{self.operation} completed in {elapsed_ms:.2f}ms",
                structured_data={
                    "operation": self.operation,
                    "duration_ms": round(elapsed_ms, 2)
                }
            )


def log_time(
    operation: str = None,
    level: int = logging.DEBUG,
    log_success: bool = True,
    log_failure: bool = True
):
    """
    Декоратор для логирования времени выполнения функции.
    
    Usage:
        @log_time("my_operation")
        async def my_function():
            pass
    """
    def decorator(func):
        op_name = operation or func.__name__
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with LogTimer(op_name, level=level, log_success=log_success, log_failure=log_failure):
                return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with LogTimer(op_name, level=level, log_success=log_success, log_failure=log_failure):
                return func(*args, **kwargs)
        
        if hasattr(func, '__await__'):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================
# Request Logging Middleware (для FastAPI)
# =============================================
class RequestLogger:
    """Middleware для логирования HTTP запросов."""
    
    def __init__(
        self,
        logger: Optional[StructuredLogger] = None,
        log_request_body: bool = False,
        log_response_body: bool = False,
        max_body_length: int = 1000
    ):
        self.logger = logger or globals()['logger']
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_length = max_body_length
    
    async def __call__(self, request, call_next):
        # Генерация ID
        request_id = generate_request_id()
        correlation_id = request.headers.get('X-Correlation-ID', generate_correlation_id())
        
        set_request_id(request_id)
        set_correlation_id(correlation_id)
        
        start_time = time.perf_counter()
        
        # Логирование запроса
        log_data = {
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params) if request.query_params else None,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get('User-Agent', ''),
            "request_id": request_id
        }
        
        self.logger.info(
            f"{request.method} {request.url.path}",
            structured_data={"http_request": log_data}
        )
        
        try:
            response = await call_next(request)
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            # Логирование ответа
            log_data = {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
                "request_id": request_id
            }
            
            level = logging.INFO
            if response.status_code >= 500:
                level = logging.ERROR
            elif response.status_code >= 400:
                level = logging.WARNING
            
            self.logger._log(
                level,
                f"{request.method} {request.url.path} -> {response.status_code}",
                structured_data={"http_response": log_data}
            )
            
            # Добавляем заголовки
            response.headers['X-Request-ID'] = request_id
            response.headers['X-Correlation-ID'] = correlation_id
            
            return response
            
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            self.logger.error(
                f"{request.method} {request.url.path} -> ERROR",
                structured_data={
                    "http_error": {
                        "method": request.method,
                        "path": request.url.path,
                        "error": str(e),
                        "duration_ms": round(elapsed_ms, 2),
                        "request_id": request_id
                    }
                },
                exc_info=True
            )
            raise


# =============================================
# Audit Logger
# =============================================
class AuditLogger:
    """Специализированный логгер для аудит-событий."""
    
    def __init__(self, logger: Optional[StructuredLogger] = None):
        self.logger = logger or get_logger('audit')
    
    def log(
        self,
        action: str,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs
    ):
        """Записать аудит-событие."""
        audit_data = {
            "action": action,
            "user_id": user_id or get_user_id(),
            "username": username,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details or {},
            "ip_address": ip_address,
            "user_agent": user_agent,
            "correlation_id": get_correlation_id(),
            "session_id": get_session_id(),
            **kwargs
        }
        
        self.logger.audit(
            f"AUDIT: {action}",
            structured_data={"audit": audit_data}
        )


# =============================================
# Error Reporting
# =============================================
def report_error(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    logger: Optional[StructuredLogger] = None,
    level: int = logging.ERROR
):
    """
    Детальный репорт ошибки с полным контекстом.
    
    Args:
        error: Исключение
        context: Дополнительный контекст
        logger: Логгер (по умолчанию глобальный)
        level: Уровень логирования
    """
    log = logger or globals()['logger']
    
    error_context = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "traceback": traceback.format_exc(),
        "correlation_id": get_correlation_id(),
        "request_id": get_request_id(),
        "user_id": get_user_id(),
        "campaign_id": get_campaign_id()
    }
    
    if context:
        error_context.update(context)
    
    log._log(
        level,
        f"Error: {type(error).__name__}: {error}",
        structured_data={"error_report": error_context},
        exc_info=True
    )


# =============================================
# Инициализация логирования
# =============================================
def init_logging(
    level: str = "INFO",
    format_type: str = "console",
    log_file: str = "/opt/autodialer/logs/autodialer.log",
    error_log_file: str = "/opt/autodialer/logs/error.log"
):
    """Инициализация системы логирования."""
    LoggerFactory.configure(
        level=level,
        format_type=format_type,
        log_file=log_file,
        error_log_file=error_log_file
    )
    
    global _logger, logger
    _logger = LoggerFactory.get_logger('autodialer')
    logger = StructuredLogger(_logger)
    
    logger.info(
        "Logging initialized",
        structured_data={
            "log_init": {
                "level": level,
                "format": format_type,
                "orjson_available": USE_ORJSON
            }
        }
    )


# =============================================
# Контекстный менеджер для логирования
# =============================================
class LogContext:
    """
    Контекстный менеджер для временной установки контекста логирования.
    
    Usage:
        with LogContext(user_id=123, campaign_id=456):
            logger.info("Внутри контекста")
    """
    
    def __init__(self, **context):
        self.context = context
        self._saved = {}
    
    def __enter__(self):
        if 'correlation_id' in self.context:
            self._saved['correlation_id'] = correlation_id_var.get()
            correlation_id_var.set(self.context['correlation_id'])
        
        if 'request_id' in self.context:
            self._saved['request_id'] = request_id_var.get()
            request_id_var.set(self.context['request_id'])
        
        if 'user_id' in self.context:
            self._saved['user_id'] = user_id_var.get()
            user_id_var.set(self.context['user_id'])
        
        if 'campaign_id' in self.context:
            self._saved['campaign_id'] = campaign_id_var.get()
            campaign_id_var.set(self.context['campaign_id'])
        
        if 'action_id' in self.context:
            self._saved['action_id'] = action_id_var.get()
            action_id_var.set(self.context['action_id'])
        
        if 'session_id' in self.context:
            self._saved['session_id'] = session_id_var.get()
            session_id_var.set(self.context['session_id'])
        
        return self
    
    def __exit__(self, *args):
        for key, value in self._saved.items():
            if key == 'correlation_id':
                correlation_id_var.set(value)
            elif key == 'request_id':
                request_id_var.set(value)
            elif key == 'user_id':
                user_id_var.set(value)
            elif key == 'campaign_id':
                campaign_id_var.set(value)
            elif key == 'action_id':
                action_id_var.set(value)
            elif key == 'session_id':
                session_id_var.set(value)


# =============================================
# Авто-инициализация
# =============================================
if not LoggerFactory._initialized:
    init_logging()
