#!/usr/bin/env python3
"""
Logging Module - Structured Logging with Correlation IDs
AutoDialer Ultimate v3.0.0
"""

import logging
import sys
import os
import json
import uuid
import time
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from contextvars import ContextVar
from typing import Optional, Dict, Any, Union
from functools import wraps


# =============================================
# Correlation ID Context
# =============================================
correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
user_id_var: ContextVar[int] = ContextVar('user_id', default=0)
campaign_id_var: ContextVar[int] = ContextVar('campaign_id', default=0)


def get_correlation_id() -> str:
    """Get current correlation ID"""
    return correlation_id_var.get() or 'no-id'


def get_request_id() -> str:
    """Get current request ID"""
    return request_id_var.get() or 'no-request'


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID for current context"""
    correlation_id_var.set(correlation_id)


def set_request_id(request_id: str) -> None:
    """Set request ID for current context"""
    request_id_var.set(request_id)


def set_user_id(user_id: int) -> None:
    """Set user ID for current context"""
    user_id_var.set(user_id)


def set_campaign_id(campaign_id: int) -> None:
    """Set campaign ID for current context"""
    campaign_id_var.set(campaign_id)


def generate_correlation_id() -> str:
    """Generate a new correlation ID"""
    return uuid.uuid4().hex[:16]


def generate_request_id() -> str:
    """Generate a new request ID"""
    return f"req_{uuid.uuid4().hex[:12]}"


# =============================================
# JSON Formatter
# =============================================
class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Outputs log entries as JSON objects for easy parsing by log aggregators.
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
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }
        
        # Add stack trace if present
        if record.stack_info:
            log_entry["stack_info"] = self.formatStack(record.stack_info)
        
        # Include extra attributes
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in ['args', 'asctime', 'created', 'exc_info', 'exc_text',
                              'filename', 'funcName', 'levelname', 'levelno', 'lineno',
                              'module', 'msecs', 'message', 'msg', 'name', 'pathname',
                              'process', 'processName', 'relativeCreated', 'stack_info',
                              'thread', 'threadName', 'correlation_id', 'request_id',
                              'user_id', 'campaign_id']:
                    try:
                        json.dumps({key: value})
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        log_entry[key] = str(value)
        
        return json.dumps(log_entry, ensure_ascii=False)


# =============================================
# Console Formatter (Human Readable)
# =============================================
class ConsoleFormatter(logging.Formatter):
    """
    Human-readable console formatter with colors.
    """
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()
    
    def format(self, record: logging.LogRecord) -> str:
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Format level with color
        level = record.levelname
        if self.use_colors:
            level = f"{self.COLORS.get(level, '')}{level}{self.COLORS['RESET']}"
        
        # Build context string
        context_parts = []
        
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
        
        context = f"[{' | '.join(context_parts)}]" if context_parts else ""
        
        # Format message
        message = record.getMessage()
        
        # Base log line
        log_line = f"{timestamp} {level:8} {record.name:20} {context:30} {message}"
        
        # Add exception info
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)
        
        # Add stack info
        if record.stack_info:
            log_line += "\n" + self.formatStack(record.stack_info)
        
        return log_line


# =============================================
# Correlation Filter
# =============================================
class CorrelationFilter(logging.Filter):
    """
    Filter that adds correlation context to log records.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or ''
        record.request_id = request_id_var.get() or ''
        record.user_id = user_id_var.get() or 0
        record.campaign_id = campaign_id_var.get() or 0
        return True


# =============================================
# Logger Factory
# =============================================
class LoggerFactory:
    """Factory for creating configured loggers"""
    
    _instances: Dict[str, logging.Logger] = {}
    _initialized = False
    _log_level = logging.INFO
    _log_format = "console"  # "console" or "json"
    _log_file: Optional[str] = None
    _max_bytes = 10 * 1024 * 1024  # 10 MB
    _backup_count = 10
    
    @classmethod
    def configure(
        cls,
        level: Union[str, int] = logging.INFO,
        format_type: str = "console",
        log_file: Optional[str] = None,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 10,
        use_colors: bool = True
    ):
        """Configure the logger factory"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        
        cls._log_level = level
        cls._log_format = format_type
        cls._log_file = log_file or os.getenv('LOG_FILE', '/opt/autodialer/logs/autodialer.log')
        cls._max_bytes = max_bytes
        cls._backup_count = backup_count
        cls._use_colors = use_colors
        cls._initialized = True
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get or create a logger"""
        if name in cls._instances:
            return cls._instances[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(cls._log_level)
        logger.propagate = False
        
        # Remove existing handlers
        logger.handlers.clear()
        
        # Add correlation filter
        logger.addFilter(CorrelationFilter())
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(cls._log_level)
        
        if cls._log_format == "json":
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(ConsoleFormatter(use_colors=cls._use_colors))
        
        logger.addHandler(console_handler)
        
        # File handler (if configured)
        if cls._log_file:
            try:
                # Ensure directory exists
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
                logger.warning(f"Failed to create file handler: {e}")
        
        cls._instances[name] = logger
        return logger


# =============================================
# Structured Logger Class
# =============================================
class StructuredLogger:
    """
    Logger wrapper with structured logging support.
    
    Provides methods for logging with additional context.
    """
    
    def __init__(self, logger: logging.Logger):
        self._logger = logger
    
    def _log(self, level: int, msg: str, *args, **kwargs):
        """Internal log method with extra context"""
        extra = kwargs.pop('extra', {})
        exc_info = kwargs.pop('exc_info', None)
        stack_info = kwargs.pop('stack_info', False)
        
        # Add kwargs as extra fields
        if kwargs:
            extra.update(kwargs)
        
        self._logger.log(level, msg, *args, extra=extra, exc_info=exc_info, stack_info=stack_info)
    
    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs):
        """Log an exception with traceback"""
        self._log(logging.ERROR, msg, *args, exc_info=True, **kwargs)
    
    def with_context(self, **context) -> 'StructuredLogger':
        """Create a logger with additional context"""
        return ContextualLogger(self, context)


class ContextualLogger(StructuredLogger):
    """Logger with pre-bound context"""
    
    def __init__(self, parent: StructuredLogger, context: Dict[str, Any]):
        super().__init__(parent._logger)
        self._parent = parent
        self._context = context
    
    def _log(self, level: int, msg: str, *args, **kwargs):
        """Merge pre-bound context with call-time kwargs"""
        merged = self._context.copy()
        merged.update(kwargs)
        self._parent._log(level, msg, *args, **merged)
    
    def with_context(self, **context) -> 'ContextualLogger':
        """Add more context"""
        new_context = self._context.copy()
        new_context.update(context)
        return ContextualLogger(self._parent, new_context)


# =============================================
# Global Logger Instance
# =============================================
# Configure from environment
log_level = os.getenv('LOG_LEVEL', 'INFO')
log_format = os.getenv('LOG_FORMAT', 'console')
log_file = os.getenv('LOG_FILE', '/opt/autodialer/logs/autodialer.log')

LoggerFactory.configure(
    level=log_level,
    format_type=log_format,
    log_file=log_file
)

# Create default logger
_logger = LoggerFactory.get_logger('autodialer')
logger = StructuredLogger(_logger)


# =============================================
# Convenience Functions
# =============================================
def get_logger(name: str) -> StructuredLogger:
    """Get a named logger"""
    return StructuredLogger(LoggerFactory.get_logger(name))


def debug(msg: str, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    logger.info(msg, *args, **kwargs)


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
    """Context manager for timing operations"""
    
    def __init__(self, operation: str, logger: Optional[StructuredLogger] = None, level: int = logging.DEBUG):
        self.operation = operation
        self.logger = logger or globals()['logger']
        self.level = level
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        if exc_type:
            self.logger._log(
                self.level,
                f"{self.operation} failed after {elapsed_ms:.2f}ms",
                operation=self.operation,
                duration_ms=round(elapsed_ms, 2),
                error=str(exc_val)
            )
        else:
            self.logger._log(
                self.level,
                f"{self.operation} completed in {elapsed_ms:.2f}ms",
                operation=self.operation,
                duration_ms=round(elapsed_ms, 2)
            )


def log_time(operation: str = None, level: int = logging.DEBUG):
    """Decorator to log function execution time"""
    def decorator(func):
        op_name = operation or func.__name__
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with LogTimer(op_name, level=level):
                return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with LogTimer(op_name, level=level):
                return func(*args, **kwargs)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================
# Request Logging Middleware
# =============================================
class RequestLogger:
    """Middleware-compatible request logger"""
    
    def __init__(self, logger: Optional[StructuredLogger] = None):
        self.logger = logger or globals()['logger']
    
    async def __call__(self, request, call_next):
        # Generate request ID
        request_id = generate_request_id()
        set_request_id(request_id)
        
        # Extract correlation ID from headers or generate new
        correlation_id = request.headers.get('X-Correlation-ID', generate_correlation_id())
        set_correlation_id(correlation_id)
        
        start_time = time.perf_counter()
        
        # Log request
        self.logger.info(
            f"{request.method} {request.url.path}",
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get('User-Agent', '')
        )
        
        try:
            response = await call_next(request)
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            # Log response
            self.logger.info(
                f"{request.method} {request.url.path} -> {response.status_code}",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(elapsed_ms, 2)
            )
            
            # Add correlation headers to response
            response.headers['X-Request-ID'] = request_id
            response.headers['X-Correlation-ID'] = correlation_id
            
            return response
            
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            self.logger.error(
                f"{request.method} {request.url.path} -> ERROR",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(elapsed_ms, 2),
                exc_info=True
            )
            raise


# =============================================
# Audit Logger
# =============================================
class AuditLogger:
    """Specialized logger for audit events"""
    
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
        **kwargs
    ):
        """Log an audit event"""
        self.logger.info(
            f"AUDIT: {action}",
            audit_action=action,
            user_id=user_id,
            username=username,
            entity_type=entity_type,
            entity_id=entity_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            **kwargs
        )


# =============================================
# Error Reporting
# =============================================
def report_error(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    logger: Optional[StructuredLogger] = None
):
    """Report an error with full context"""
    log = logger or globals()['logger']
    
    error_context = {
        'error_type': type(error).__name__,
        'error_message': str(error),
        'traceback': traceback.format_exc()
    }
    
    if context:
        error_context.update(context)
    
    log.error(f"Error: {type(error).__name__}: {error}", **error_context, exc_info=True)


# =============================================
# Initialize Logging on Import
# =============================================
def init_logging(
    level: str = "INFO",
    format_type: str = "console",
    log_file: str = "/opt/autodialer/logs/autodialer.log"
):
    """Initialize logging system"""
    LoggerFactory.configure(
        level=level,
        format_type=format_type,
        log_file=log_file
    )
    
    # Recreate default logger
    global _logger, logger
    _logger = LoggerFactory.get_logger('autodialer')
    logger = StructuredLogger(_logger)
    
    logger.info(f"Logging initialized: level={level}, format={format_type}")


# Auto-initialize from environment if not already done
if not LoggerFactory._initialized:
    init_logging()
