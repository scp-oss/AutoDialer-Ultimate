#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ядро приложения AutoDialer Ultimate
Версия: 3.0.0

Центральный модуль, экспортирующий все основные компоненты:
- Конфигурация (Settings)
- Логгер (StructuredLogger)
- База данных (ConnectionPool)
- Redis (клиент и утилиты)
- Безопасность (JWT, пароли)
- Зависимости FastAPI (Depends)

ИСПОЛЬЗОВАНИЕ:
    from app.core import settings, logger, get_db_pool, get_redis_client
    from app.core import hash_password, verify_password, create_token, decode_token
    from app.core import get_current_user, require_admin
"""

# =============================================
# Конфигурация
# =============================================
from app.core.config import Settings, settings

# =============================================
# Логирование
# =============================================
from app.core.logger import (
    # Основной логгер
    logger,
    StructuredLogger,
    LoggerFactory,
    
    # Контекстные переменные
    correlation_id_var,
    request_id_var,
    user_id_var,
    campaign_id_var,
    action_id_var,
    session_id_var,
    
    # Функции контекста
    get_correlation_id,
    get_request_id,
    get_user_id,
    get_campaign_id,
    get_action_id,
    get_session_id,
    set_correlation_id,
    set_request_id,
    set_user_id,
    set_campaign_id,
    set_action_id,
    set_session_id,
    generate_correlation_id,
    generate_request_id,
    generate_session_id,
    clear_context,
    
    # Утилиты логирования
    LogTimer,
    log_time,
    LogContext,
    RequestLogger,
    AuditLogger,
    report_error,
    init_logging,
    
    # Уровни логирования
    AUDIT,
    TRACE,
    CRITICAL,
    
    # Функции-хелперы
    get_logger,
    trace,
    debug,
    info,
    audit,
    warning,
    error,
    critical,
    exception,
)

# =============================================
# База данных
# =============================================
from app.core.database import (
    # Пул соединений
    ConnectionPool,
    DatabaseConfig,
    
    # Глобальные функции
    init_database,
    close_database,
    get_db_pool,
    set_db_pool,
    
    # Удобные функции для запросов
    execute,
    fetch,
    fetchrow,
    fetchval,
    transaction,
    
    # Query Builder
    QueryBuilder,
    
    # Репозитории
    BaseRepository,
    CampaignRepository,
    ContactRepository,
    CallResultRepository,
    UserRepository,
    SettingsRepository,
    AudioFileRepository,
    
    # Миграции
    MigrationManager,
)

# =============================================
# Redis
# =============================================
from app.core.redis import (
    # Управление подключением
    init_redis,
    close_redis,
    get_redis_client,
    RedisClient,

    # Утилиты Redis
    RedisCache,
    RedisLock,
    RedisQueue,

    # Ключи Redis (константы)
    REDIS_KEYS,
)

# =============================================
# Безопасность
# =============================================
from app.core.security import (
    # Пароли
    hash_password,
    verify_password,
    check_password_strength,
    
    # JWT токены
    create_token,
    decode_token,
    create_access_token,
    create_refresh_token,
    verify_token,
    get_token_payload,
    
    # API ключи
    generate_api_key,
    hash_api_key,
    verify_api_key,
    
    # Утилиты
    generate_secure_random_string,
    constant_time_compare,
)

# =============================================
# Зависимости FastAPI
# =============================================
from app.core.dependencies import (
    # Токены и пользователи
    TokenData,
    get_current_user,
    get_current_active_user,
    require_admin,
    require_operator,
    require_viewer,
    
    # Аутентификация
    oauth2_scheme,
    verify_metrics_auth,
    verify_webhook_auth,
    
    # Утилиты
    get_db_pool as get_db_pool_dep,
    get_redis_client as get_redis_client_dep,
    get_task_registry,
    
    # Rate limiting
    check_rate_limit,
    RateLimitDep,
)

# =============================================
# Circuit Breaker (интеграция)
# =============================================
from app.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    CircuitTimeoutError,
    circuit_breaker as circuit_breaker_decorator,
    circuit_registry,
)

# Создаём предварительно настроенные Circuit Breaker'ы
def get_db_breaker():
    """Circuit Breaker для базы данных"""
    return CircuitBreaker(
        name="database",
        failure_threshold=3,
        recovery_timeout=30,
        service_type="db"
    )

def get_redis_breaker():
    """Circuit Breaker для Redis"""
    return CircuitBreaker(
        name="redis",
        failure_threshold=3,
        recovery_timeout=30,
        service_type="redis"
    )

def get_ami_breaker():
    """Circuit Breaker для AMI"""
    return CircuitBreaker(
        name="ami",
        failure_threshold=5,
        recovery_timeout=60,
        service_type="ami"
    )

# =============================================
# Метрики Prometheus
# =============================================
try:
    from prometheus_client import Counter, Gauge, Histogram, Summary
    
    # Метрики приложения
    # Метрики конкретных доменов (кампании, контакты, аудио, входящие звонки)
    # определяются в соответствующих сервисах (app/services/*.py) — здесь
    # только общеприкладные метрики, чтобы избежать коллизий имён в
    # prometheus_client.REGISTRY (Counter автоматически регистрирует и
    # компаньон-серию `<base>_created`, которая должна быть уникальной).
    active_calls_gauge = Gauge('autodialer_active_calls', 'Active calls count')
    calls_total = Counter('autodialer_calls_total', 'Total calls', ['status', 'campaign_id'])
    http_requests = Counter('autodialer_http_requests', 'HTTP requests', ['method', 'endpoint', 'status'])
    http_request_duration = Histogram('autodialer_http_request_duration_seconds', 'HTTP request duration')

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    # Заглушки для метрик
    class _DummyMetric:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
    
    active_calls_gauge = _DummyMetric()
    calls_total = _DummyMetric()
    http_requests = _DummyMetric()
    http_request_duration = _DummyMetric()

# =============================================
# Инициализация приложения
# =============================================
class AppCore:
    """
    Управление жизненным циклом ядра приложения.
    
    Использование:
        async with AppCore() as core:
            # Приложение работает
            db = core.db_pool
            redis = core.redis_client
            ...
    """
    
    def __init__(self):
        self._initialized = False
        self._start_time = None
    
    async def __aenter__(self):
        """Инициализация всех компонентов"""
        import time
        self._start_time = time.time()
        
        logger.info("=" * 60)
        logger.info(f"Инициализация ядра AutoDialer Ultimate v{settings.VERSION}")
        logger.info("=" * 60)
        
        try:
            # 1. База данных
            await init_database()
            logger.info("✅ База данных инициализирована")
            
            # 2. Redis
            await init_redis()
            logger.info("✅ Redis инициализирован")
            
            # 3. Circuit Breakers
            db_breaker = get_db_breaker()
            redis_breaker = get_redis_breaker()
            ami_breaker = get_ami_breaker()
            logger.info("✅ Circuit Breakers созданы")
            
            self._initialized = True
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации ядра: {e}")
            raise
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Корректное завершение работы"""
        import time
        
        logger.info("Завершение работы ядра приложения...")
        
        try:
            await close_redis()
            await close_database()
        except Exception as e:
            logger.error(f"Ошибка при завершении: {e}")
        
        if self._start_time:
            uptime = time.time() - self._start_time
            logger.info(f"Ядро остановлено. Uptime: {uptime:.2f} секунд")
        
        return False  # Не подавляем исключения
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    
    @property
    def db_pool(self):
        return get_db_pool()
    
    @property
    def redis_client(self):
        return get_redis_client()
    
    def health_check(self) -> dict:
        """Проверка здоровья всех компонентов"""
        status = {
            "status": "healthy",
            "version": settings.VERSION,
            "initialized": self._initialized,
            "components": {}
        }
        
        # Проверка БД
        try:
            import asyncio
            db = get_db_pool()
            if db and db.is_connected:
                status["components"]["database"] = "healthy"
            else:
                status["components"]["database"] = "not_connected"
                status["status"] = "degraded"
        except:
            status["components"]["database"] = "error"
            status["status"] = "degraded"
        
        # Проверка Redis
        try:
            redis = get_redis_client()
            # Синхронная проверка (в health check нельзя использовать await)
            status["components"]["redis"] = "connected" if redis else "not_connected"
        except:
            status["components"]["redis"] = "error"
            status["status"] = "degraded"
        
        return status


# =============================================
# Глобальные экземпляры
# =============================================
_core_instance: AppCore = None


def get_core() -> AppCore:
    """Получить экземпляр ядра приложения"""
    global _core_instance
    if _core_instance is None:
        _core_instance = AppCore()
    return _core_instance


# =============================================
# Декораторы
# =============================================
def transactional(func):
    """
    Декоратор для выполнения функции в транзакции БД.
    
    Использование:
        @transactional
        async def update_multiple_tables(conn):
            await conn.execute("UPDATE ...")
            await conn.execute("INSERT ...")
    """
    from functools import wraps
    
    @wraps(func)
    async def wrapper(*args, **kwargs):
        db_pool = get_db_pool()
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                return await func(conn, *args, **kwargs)
    
    return wrapper


def with_circuit_breaker(service: str = "default"):
    """
    Декоратор для оборачивания функции в Circuit Breaker.
    
    Использование:
        @with_circuit_breaker("database")
        async def db_query():
            ...
    """
    from app.utils.circuit_breaker import circuit_breaker as cb_decorator
    
    def decorator(func):
        breaker_name = f"{service}_{func.__name__}"
        return cb_decorator(name=breaker_name, service_type=service)(func)
    
    return decorator


def rate_limited(limit: int = 100, window: int = 60):
    """
    Декоратор для ограничения частоты вызовов.
    
    Использование:
        @rate_limited(limit=10, window=60)
        async def expensive_operation():
            ...
    """
    from functools import wraps
    from app.utils.rate_limiter import SlidingWindowRateLimiter
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            redis_client = get_redis_client()
            limiter = SlidingWindowRateLimiter(redis_client)
            key = f"rate_limit:func:{func.__module__}.{func.__name__}"
            
            result = await limiter.check(key, limit=limit, window=window)
            if not result.allowed:
                from app.utils.rate_limiter import RateLimitExceeded
                raise RateLimitExceeded(
                    f"Rate limit exceeded for {func.__name__}",
                    retry_after=result.retry_after
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def log_execution(level: str = "DEBUG", include_args: bool = False):
    """
    Декоратор для логирования выполнения функции.
    
    Использование:
        @log_execution(level="INFO", include_args=True)
        async def my_function(arg1, arg2):
            ...
    """
    from functools import wraps
    import logging
    
    log_level = getattr(logging, level.upper(), logging.DEBUG)
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__name__}"
            
            if include_args:
                logger.log(log_level, f"→ {func_name} called with args={args}, kwargs={kwargs}")
            else:
                logger.log(log_level, f"→ {func_name} called")
            
            with LogTimer(func_name, logger=logger, level=log_level):
                result = await func(*args, **kwargs)
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__name__}"
            
            if include_args:
                logger.log(log_level, f"→ {func_name} called with args={args}, kwargs={kwargs}")
            else:
                logger.log(log_level, f"→ {func_name} called")
            
            with LogTimer(func_name, logger=logger, level=log_level):
                result = func(*args, **kwargs)
            
            return result
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================
# Экспорт всего
# =============================================
__all__ = [
    # Конфигурация
    "Settings",
    "settings",
    
    # Логгер
    "logger",
    "StructuredLogger",
    "LoggerFactory",
    "LogTimer",
    "log_time",
    "LogContext",
    "RequestLogger",
    "AuditLogger",
    "report_error",
    "init_logging",
    "get_logger",
    "trace",
    "debug",
    "info",
    "audit",
    "warning",
    "error",
    "critical",
    "exception",
    
    # Контекст логирования
    "correlation_id_var",
    "request_id_var",
    "user_id_var",
    "campaign_id_var",
    "action_id_var",
    "session_id_var",
    "get_correlation_id",
    "set_correlation_id",
    "generate_correlation_id",
    "clear_context",
    
    # База данных
    "ConnectionPool",
    "DatabaseConfig",
    "init_database",
    "close_database",
    "get_db_pool",
    "execute",
    "fetch",
    "fetchrow",
    "fetchval",
    "transaction",
    "QueryBuilder",
    "BaseRepository",
    "CampaignRepository",
    "ContactRepository",
    "CallResultRepository",
    "UserRepository",
    "SettingsRepository",
    "AudioFileRepository",
    "MigrationManager",
    
    # Redis
    "init_redis",
    "close_redis",
    "get_redis_client",
    "RedisCache",
    "RedisLock",
    "RedisQueue",
    "REDIS_KEYS",
    
    # Безопасность
    "hash_password",
    "verify_password",
    "create_token",
    "decode_token",
    "create_access_token",
    "create_refresh_token",
    "generate_api_key",
    
    # Зависимости
    "TokenData",
    "get_current_user",
    "get_current_active_user",
    "require_admin",
    "require_operator",
    "oauth2_scheme",
    "verify_metrics_auth",
    "get_task_registry",
    
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    "CircuitOpenError",
    "CircuitTimeoutError",
    "get_db_breaker",
    "get_redis_breaker",
    "get_ami_breaker",
    
    # Метрики
    "active_calls_gauge",
    "calls_total",
    "http_requests",
    "http_request_duration",
    "METRICS_AVAILABLE",
    
    # Ядро приложения
    "AppCore",
    "get_core",
    
    # Декораторы
    "transactional",
    "with_circuit_breaker",
    "rate_limited",
    "log_execution",
]
