#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Структурированное логирование
AutoDialer Ultimate v3.0.0

Предоставляет:
- StructuredLogger с автоматическим добавлением контекста (correlation_id,
  request_id, user_id, campaign_id, action_id, session_id) в каждую запись
- Кастомные уровни логирования TRACE (5) и AUDIT (25)
- JSON и человекочитаемый (console) форматы вывода
- Ротацию файлов логов (общий и error-only)
- Утилиты: LogTimer/log_time для замера длительности, LogContext для
  временной подмены контекста, RequestLogger для HTTP-логов, AuditLogger
  для журнала аудита, report_error для унифицированного логирования ошибок

ИСПОЛЬЗОВАНИЕ:
    from app.core.logger import logger, init_logging

    init_logging(level="INFO", format_type="json", log_file="/var/log/app.log")
    logger.info("Сервис запущен", extra={"component": "startup"})
"""

import contextvars
import json
import logging
import logging.handlers
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional


# =============================================
# Кастомные уровни логирования
# =============================================
TRACE = 5
AUDIT = 25
CRITICAL = logging.CRITICAL

logging.addLevelName(TRACE, "TRACE")
logging.addLevelName(AUDIT, "AUDIT")


class LogLevel(str, Enum):
    """Уровни логирования, совпадают с settings.LOG_LEVEL"""
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    AUDIT = "AUDIT"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @property
    def numeric(self) -> int:
        return {
            "TRACE": TRACE,
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "AUDIT": AUDIT,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }[self.value]


# =============================================
# Контекстные переменные (per-async-task)
# =============================================
correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)
request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
user_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "user_id", default=None
)
campaign_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "campaign_id", default=None
)
action_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "action_id", default=None
)
session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "session_id", default=None
)


def generate_correlation_id() -> str:
    return uuid.uuid4().hex


def generate_request_id() -> str:
    return uuid.uuid4().hex


def generate_session_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> Optional[str]:
    return correlation_id_var.get()


def get_request_id() -> Optional[str]:
    return request_id_var.get()


def get_user_id() -> Optional[int]:
    return user_id_var.get()


def get_campaign_id() -> Optional[int]:
    return campaign_id_var.get()


def get_action_id() -> Optional[str]:
    return action_id_var.get()


def get_session_id() -> Optional[str]:
    return session_id_var.get()


def set_correlation_id(value: Optional[str]) -> None:
    correlation_id_var.set(value)


def set_request_id(value: Optional[str]) -> None:
    request_id_var.set(value)


def set_user_id(value: Optional[int]) -> None:
    user_id_var.set(value)


def set_campaign_id(value: Optional[int]) -> None:
    campaign_id_var.set(value)


def set_action_id(value: Optional[str]) -> None:
    action_id_var.set(value)


def set_session_id(value: Optional[str]) -> None:
    session_id_var.set(value)


def clear_context() -> None:
    """Сбросить весь контекст текущей задачи (используется в тестах / между запросами)"""
    for var in (
        correlation_id_var, request_id_var, user_id_var,
        campaign_id_var, action_id_var, session_id_var,
    ):
        var.set(None)


def _current_context() -> Dict[str, Any]:
    ctx = {
        "correlation_id": get_correlation_id(),
        "request_id": get_request_id(),
        "user_id": get_user_id(),
        "campaign_id": get_campaign_id(),
        "action_id": get_action_id(),
        "session_id": get_session_id(),
    }
    return {k: v for k, v in ctx.items() if v is not None}


# =============================================
# Форматтеры
# =============================================
class JsonFormatter(logging.Formatter):
    """JSON-форматтер для агрегаторов логов (ELK/Loki/CloudWatch)"""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        context = getattr(record, "context", None)
        if context:
            payload.update(context)

        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Человекочитаемый форматтер для разработки/консоли"""

    COLORS = {
        "TRACE": "\033[90m",
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "AUDIT": "\033[35m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[41m",
    }
    RESET = "\033[0m"

    def __init__(self, use_color: bool = True):
        super().__init__()
        self.use_color = use_color and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        color = self.COLORS.get(record.levelname, "") if self.use_color else ""
        reset = self.RESET if self.use_color else ""

        context = getattr(record, "context", None) or {}
        ctx_str = " ".join(f"{k}={v}" for k, v in context.items())

        line = f"{ts} {color}{record.levelname:<8}{reset} {record.name}: {record.getMessage()}"
        if ctx_str:
            line += f" [{ctx_str}]"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)

        return line


class ContextInjectingFilter(logging.Filter):
    """Прикрепляет текущий контекст (correlation_id и т.д.) к каждой записи"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.context = _current_context()
        return True


# =============================================
# StructuredLogger
# =============================================
class StructuredLogger:
    """
    Обёртка над stdlib logging.Logger с поддержкой структурированных полей
    и автоматическим добавлением контекста запроса.
    """

    def __init__(self, name: str = "autodialer"):
        self._logger = logging.getLogger(name)
        if not any(isinstance(f, ContextInjectingFilter) for f in self._logger.filters):
            self._logger.addFilter(ContextInjectingFilter())

    @property
    def name(self) -> str:
        return self._logger.name

    @property
    def level(self) -> int:
        return self._logger.getEffectiveLevel()

    def _log(self, level: int, msg: str, *args, extra: Optional[Dict[str, Any]] = None,
              exc_info: Any = None, **kwargs) -> None:
        record_extra = {"extra_fields": extra or {}}
        self._logger.log(level, msg, *args, exc_info=exc_info, extra=record_extra, **kwargs)

    def trace(self, msg: str, *args, **kwargs) -> None:
        self._log(TRACE, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def audit(self, msg: str, *args, **kwargs) -> None:
        self._log(AUDIT, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, exc_info: Any = True, **kwargs) -> None:
        self._log(logging.ERROR, msg, *args, exc_info=exc_info, **kwargs)


# =============================================
# LoggerFactory
# =============================================
class LoggerFactory:
    """Создаᑑт и централизованно настраивает именованные логгеры приложения"""

    _loggers: Dict[str, StructuredLogger] = {}
    _configured = False
    _current_level: str = "INFO"

    @classmethod
    def get_logger(cls, name: str = "autodialer") -> StructuredLogger:
        if name not in cls._loggers:
            cls._loggers[name] = StructuredLogger(name)
        return cls._loggers[name]

    @classmethod
    def configure(
        cls,
        level: str = "INFO",
        format_type: str = "console",
        log_file: Optional[str] = None,
        error_log_file: Optional[str] = None,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 10,
    ) -> None:
        """Настроить корневой логгер приложения (handlers, форматтеры, уровень)"""
        cls._current_level = level
        level_value = LogLevel(level).numeric if level in LogLevel.__members__ else logging.INFO

        root = logging.getLogger("autodialer")
        root.setLevel(level_value)
        root.handlers.clear()
        root.propagate = False

        formatter: logging.Formatter
        if format_type == "json":
            formatter = JsonFormatter()
        else:
            formatter = ConsoleFormatter()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        if log_file:
            try:
                path = Path(log_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.handlers.RotatingFileHandler(
                    path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
                )
                file_handler.setFormatter(JsonFormatter())
                root.addHandler(file_handler)
            except OSError:
                # Файловая система может быть недоступна для записи (например read-only
                # контейнер без смонтированного volume) — продолжаем работать через stdout
                pass

        if error_log_file:
            try:
                err_path = Path(error_log_file)
                err_path.parent.mkdir(parents=True, exist_ok=True)
                error_handler = logging.handlers.RotatingFileHandler(
                    err_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
                )
                error_handler.setFormatter(JsonFormatter())
                error_handler.setLevel(logging.ERROR)
                root.addHandler(error_handler)
            except OSError:
                pass

        # Применяем уровень ко всем уже созданным именованным логгерам
        for named_logger in cls._loggers.values():
            named_logger._logger.setLevel(level_value)

        cls._configured = True

    @classmethod
    def is_configured(cls) -> bool:
        return cls._configured


def init_logging(
    level: str = "INFO",
    format_type: str = "console",
    log_file: Optional[str] = None,
    error_log_file: Optional[str] = None,
) -> None:
    """Инициализировать логирование приложения (вызывается один раз при старте)"""
    LoggerFactory.configure(
        level=level,
        format_type=format_type,
        log_file=log_file,
        error_log_file=error_log_file,
    )


def get_logger(name: str = "autodialer") -> StructuredLogger:
    """Получить (или создать) именованный логгер"""
    return LoggerFactory.get_logger(name)


# Логгер по умолчанию для всего приложения
logger = LoggerFactory.get_logger("autodialer")


# =============================================
# Модульные функции-хелперы (используют logger по умолчанию)
# =============================================
def trace(msg: str, *args, **kwargs) -> None:
    logger.trace(msg, *args, **kwargs)


def debug(msg: str, *args, **kwargs) -> None:
    logger.debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs) -> None:
    logger.info(msg, *args, **kwargs)


def audit(msg: str, *args, **kwargs) -> None:
    logger.audit(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs) -> None:
    logger.warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs) -> None:
    logger.error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs) -> None:
    logger.critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs) -> None:
    logger.exception(msg, *args, **kwargs)


# =============================================
# Утилиты замера времени
# =============================================
class LogTimer:
    """
    Контекстный менеджер для замера и логирования длительности блока кода.

    Использование:
        with LogTimer("db_query", logger_instance=logger):
            await do_something()
    """

    def __init__(
        self,
        label: str,
        logger_instance: Optional[StructuredLogger] = None,
        level: str = "debug",
        threshold_ms: Optional[float] = None,
    ):
        self.label = label
        self.logger = logger_instance or logger
        self.level = level
        self.threshold_ms = threshold_ms
        self.duration_ms: Optional[float] = None
        self._start = 0.0

    def __enter__(self) -> "LogTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.duration_ms = (time.monotonic() - self._start) * 1000
        if self.threshold_ms is not None and self.duration_ms < self.threshold_ms:
            return
        log_fn = getattr(self.logger, self.level, self.logger.debug)
        log_fn(f"{self.label} completed", extra={"duration_ms": round(self.duration_ms, 2)})


def log_time(label: Optional[str] = None, level: str = "debug"):
    """Декоратор: логирует длительность выполнения функции (sync или async)"""

    def decorator(func: Callable) -> Callable:
        name = label or func.__qualname__

        if hasattr(func, "__call__") and _is_coroutine_function(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                with LogTimer(name, level=level):
                    return await func(*args, **kwargs)
            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with LogTimer(name, level=level):
                return func(*args, **kwargs)
        return sync_wrapper

    return decorator


def _is_coroutine_function(func: Callable) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(func)


# =============================================
# Временная подмена контекста
# =============================================
@contextmanager
def LogContext(**kwargs):
    """
    Временно установить значения контекстных переменных внутри блока `with`.

    Использование:
        with LogContext(user_id=42, campaign_id=7):
            logger.info("Обработка кампании")
    """
    setters = {
        "correlation_id": correlation_id_var,
        "request_id": request_id_var,
        "user_id": user_id_var,
        "campaign_id": campaign_id_var,
        "action_id": action_id_var,
        "session_id": session_id_var,
    }
    tokens = []
    try:
        for key, value in kwargs.items():
            var = setters.get(key)
            if var is not None:
                tokens.append((var, var.set(value)))
        yield
    finally:
        for var, token in tokens:
            var.reset(token)


# =============================================
# HTTP request/response логирование
# =============================================
class RequestLogger:
    """Логирование входящих HTTP-запросов и ответов с длительностью"""

    def __init__(self, logger_instance: Optional[StructuredLogger] = None):
        self.logger = logger_instance or logger

    def log_request(self, method: str, path: str, client_ip: Optional[str] = None) -> None:
        self.logger.info(
            f"--> {method} {path}",
            extra={"http_method": method, "http_path": path, "client_ip": client_ip},
        )

    def log_response(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        level = "info" if status_code < 500 else "error"
        getattr(self.logger, level)(
            f"<-- {method} {path} {status_code} ({duration_ms:.2f}ms)",
            extra={
                "http_method": method,
                "http_path": path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )


# =============================================
# Журнал аудита (низкоуровневый, пишет в лог-файл AUDIT-уровня)
# =============================================
class AuditLogger:
    """
    Пишет события аудита в структурированный лог (уровень AUDIT).
    Персистентность в БД обеспечивает app.services.audit.AuditService —
    этот класс отвечает только за дублирование событий в лог-поток
    (для агрегации в ELK/Loki независимо от доступности БД).
    """

    def __init__(self):
        self.logger = LoggerFactory.get_logger("autodialer.audit")

    def log(
        self,
        action: str,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.logger.audit(
            f"AUDIT {action}",
            extra={
                "action": action,
                "user_id": user_id,
                "username": username,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details or {},
            },
        )


def report_error(
    exc: BaseException,
    context: Optional[Dict[str, Any]] = None,
    logger_instance: Optional[StructuredLogger] = None,
) -> None:
    """Единая точка логирования необработанных исключений с контекстом"""
    log = logger_instance or logger
    log.error(
        f"{type(exc).__name__}: {exc}",
        extra={**(context or {}), "traceback": traceback.format_exc()},
        exc_info=exc,
    )


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Основной логгер
    "logger",
    "StructuredLogger",
    "LoggerFactory",
    "LogLevel",

    # Контекстные переменные
    "correlation_id_var",
    "request_id_var",
    "user_id_var",
    "campaign_id_var",
    "action_id_var",
    "session_id_var",

    # Функции контекста
    "get_correlation_id",
    "get_request_id",
    "get_user_id",
    "get_campaign_id",
    "get_action_id",
    "get_session_id",
    "set_correlation_id",
    "set_request_id",
    "set_user_id",
    "set_campaign_id",
    "set_action_id",
    "set_session_id",
    "generate_correlation_id",
    "generate_request_id",
    "generate_session_id",
    "clear_context",

    # Утилиты логирования
    "LogTimer",
    "log_time",
    "LogContext",
    "RequestLogger",
    "AuditLogger",
    "report_error",
    "init_logging",

    # Уровни логирования
    "AUDIT",
    "TRACE",
    "CRITICAL",

    # Функции-хелперы
    "get_logger",
    "trace",
    "debug",
    "info",
    "audit",
    "warning",
    "error",
    "critical",
    "exception",
]
