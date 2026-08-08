#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoDialer Ultimate - Основной пакет приложения
Версия: 3.0.0

Центральный модуль приложения, экспортирующий:
- Версию приложения
- Основные настройки
- Ядро приложения (core)
- Модели данных (models)
- Сервисы бизнес-логики (services)
- API роутеры (api)

ИСПОЛЬЗОВАНИЕ:
    from app import create_app, settings, logger
    from app.models import CampaignCreate, ContactResponse
    from app.services import get_campaign_service
"""

import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# =============================================
# Версия
# =============================================
__version__ = "3.0.0"
__author__ = "AutoDialer Team"
__description__ = "Enterprise-grade auto dialer system with advanced features"


# =============================================
# Импорт ядра
# =============================================
from app.core import (
    # Конфигурация
    settings,
    Settings,
    
    # Логирование
    logger,
    StructuredLogger,
    LoggerFactory,
    init_logging,
    get_logger,
    
    # База данных
    ConnectionPool,
    init_database,
    close_database,
    get_db_pool,
    
    # Redis
    init_redis,
    close_redis,
    get_redis_client,
    RedisClient,
    
    # Безопасность
    hash_password,
    verify_password,
    create_token,
    decode_token,
    
    # Зависимости
    get_current_user,
    require_admin,
    TokenData,
    
    # Circuit Breaker
    CircuitBreaker,
    get_db_breaker,
    get_redis_breaker,
    
    # Метрики
    active_calls_gauge,
    calls_total,
    http_requests,
    METRICS_AVAILABLE,
    
    # Декораторы
    transactional,
    rate_limited,
    log_execution,
)


# =============================================
# Импорт моделей
# =============================================
from app.models import (
    # Базовые
    BaseSchema,
    BaseResponse,
    TimestampSchema,
    SuccessResponse,
    ErrorResponse,
    PaginatedResponse,
    PaginationParams,
    
    # Аутентификация
    LoginRequest,
    LoginResponse,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    
    # Пользователи
    UserCreateRequest,
    UserResponse,
    UserRole,
    Permission,
    
    # Кампании
    CampaignCreateRequest,
    CampaignResponse,
    CampaignStatus,
    RetryStrategySchema,
    
    # Контакты
    ContactCreateRequest,
    ContactResponse,
    ContactStatus,
    
    # Звонки
    CallResultResponse,
    CallResultStatus,
    
    # Аудио
    AudioResponse,
    AudioGenerateRequest,
    
    # Система
    SystemStatusResponse,
    HealthCheckResponse,
)


# =============================================
# Импорт сервисов
# =============================================
from app.services import (
    # Реестр сервисов
    ServiceRegistry,
    service_registry,
    init_services,
    shutdown_services,
    
    # Сервисы
    DialerService,
    DialerManager,
    CampaignService,
    ContactService,
    ContactGroupService,
    CallResultService,
    AudioService,
    TTSService,
    TranscriptionService,
    SystemService,
    
    # Функции получения сервисов
    get_dialer_service,
    get_campaign_service,
    get_contact_service,
    get_call_service,
    get_audio_service,
    get_tts_service,
    get_transcription_service,
    get_system_service,
)


# =============================================
# Импорт API
# =============================================
from app.api import api_router


# =============================================
# Глобальные переменные приложения
# =============================================
_app: Optional[FastAPI] = None
_app_state: Dict[str, Any] = {
    'initialized': False,
    'start_time': None,
    'db_pool': None,
    'redis_client': None,
    'dialer_manager': None,
    'transcription_service': None,
}


# =============================================
# Создание приложения
# =============================================
def create_app() -> FastAPI:
    """
    Создать и настроить экземпляр FastAPI приложения.
    
    Returns:
        Настроенный экземпляр FastAPI
    """
    global _app
    
    # Настраиваем логирование
    init_logging(
        level=settings.LOG_LEVEL,
        format_type=settings.LOG_FORMAT,
        log_file=str(settings.LOG_FILE),
        error_log_file=str(settings.LOG_ERROR_FILE)
    )
    
    # Создаём приложение
    _app = FastAPI(
        title="AutoDialer Ultimate API",
        version=__version__,
        description=__description__,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )
    
    # Настраиваем CORS
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )
    
    # Добавляем middleware
    @_app.middleware("http")
    async def app_middleware(request, call_next):
        """Главный middleware приложения"""
        import time
        import uuid
        from app.core.logger import correlation_id_var, request_id_var
        
        # Correlation ID
        corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        correlation_id_var.set(corr_id)
        request_id_var.set(req_id)
        
        start_time = time.monotonic()
        
        response = await call_next(request)
        
        # Добавляем заголовки
        response.headers["X-Correlation-ID"] = corr_id
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Response-Time"] = f"{(time.monotonic() - start_time)*1000:.2f}ms"
        
        # Метрики
        if METRICS_AVAILABLE:
            http_requests.labels(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code
            ).inc()
        
        return response
    
    # Подключаем API роутер
    _app.include_router(api_router)
    
    # Подключаем статику (фронтенд)
    static_dir = settings.STATIC_DIR
    if static_dir.exists():
        _app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    
    # Health check реализован в app.api.health (роутер /api/health,
    # /api/health/live, /api/health/ready) — единственный источник истины,
    # чтобы не дублировать OpenAPI operation id.

    # Метрики Prometheus
    if settings.METRICS_ENABLED:
        @_app.get(settings.METRICS_PATH, tags=["Metrics"])
        async def metrics():
            """Prometheus метрики"""
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
            from fastapi.responses import Response
            
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST
            )
    
    logger.info(f"Приложение создано: v{__version__}")
    
    return _app


# =============================================
# Lifespan (управление жизненным циклом)
# =============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.
    
    Выполняется при старте и завершении приложения.
    """
    import time
    import signal
    from datetime import datetime
    
    # =============================================
    # Startup
    # =============================================
    logger.info("=" * 60)
    logger.info(f"Запуск AutoDialer Ultimate v{__version__}...")
    logger.info("=" * 60)
    
    start_time = time.time()
    _app_state['start_time'] = start_time
    
    try:
        # 1. Инициализация базы данных
        logger.info("Инициализация базы данных...")
        db_pool = await init_database()
        _app_state['db_pool'] = db_pool
        logger.info("✅ База данных подключена")
        
        # 2. Инициализация Redis
        logger.info("Инициализация Redis...")
        redis_client = await init_redis()
        _app_state['redis_client'] = redis_client
        logger.info("✅ Redis подключен")
        
        # 3. Инициализация транскрибации
        from app.services.transcription import init_transcription_service
        logger.info("Инициализация сервиса транскрибации...")
        transcription_service = await init_transcription_service(db_pool, redis_client)
        _app_state['transcription_service'] = transcription_service
        logger.info(f"✅ Транскрибация: {transcription_service.get_info()['engine']}")
        
        # 4. Инициализация дозвона (AMI)
        from app.services.dialer import init_dialer
        from app.services.call_result import CallResultService
        
        logger.info("Инициализация сервиса дозвона...")
        call_result_service = CallResultService(db_pool, redis_client)
        dialer_manager = await init_dialer(db_pool, redis_client, call_result_service)
        _app_state['dialer_manager'] = dialer_manager
        logger.info("✅ AMI подключен")
        
        # 5. Инициализация всех сервисов
        logger.info("Инициализация сервисов...")
        await init_services(
            db_pool=db_pool,
            redis_client=redis_client,
            dialer_manager=dialer_manager,
            transcription_service=transcription_service
        )
        logger.info(f"✅ Инициализировано {len(service_registry.list_services())} сервисов")
        
        # 6. Запуск системного сервиса
        system_service = get_system_service()
        await system_service.start()

        # 6.5 Запуск фоновых воркеров (retry queue, транскрибация, health
        # monitor, очистка и т.д.) — без этого вызова app/workers/*.py
        # никогда не выполняются несмотря на регистрацию в create_app()
        from app.workers import start_all_workers
        await start_all_workers()

        # 7. Регистрация обработчиков сигналов (доп. к graceful shutdown,
        # который uvicorn/gunicorn уже выполняют через ASGI lifespan).
        # add_signal_handler требует основного потока основного интерпретатора
        # и падает в тестовом окружении (Starlette TestClient гоняет lifespan
        # в отдельном потоке) - это не должно ронять старт приложения.
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(shutdown_handler(s))
                )
        except (NotImplementedError, RuntimeError) as e:
            logger.debug(f"Регистрация обработчиков сигналов пропущена: {e}")
        
        _app_state['initialized'] = True
        
        # Информация о запуске
        logger.info("=" * 60)
        logger.info(f"✅ AutoDialer Ultimate v{__version__} готов к работе!")
        logger.info(f"   Адрес: http://{settings.APP_HOST}:{settings.APP_PORT}")
        logger.info(f"   Документация: http://{settings.APP_HOST}:{settings.APP_PORT}/docs")
        logger.info(f"   Время запуска: {(time.time() - start_time):.2f}с")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске: {e}")
        raise
    
    yield
    
    # =============================================
    # Shutdown
    # =============================================
    logger.info("=" * 60)
    logger.info("Завершение работы AutoDialer Ultimate...")
    logger.info("=" * 60)
    
    await shutdown_handler()
    
    logger.info("✅ Завершение работы завершено")


async def shutdown_handler(sig=None):
    """
    Обработчик graceful shutdown.
    
    Args:
        sig: Сигнал (опционально)
    """
    if sig:
        logger.info(f"Получен сигнал: {sig.name}")
    
    try:
        # 0. Останавливаем фоновые воркеры
        try:
            from app.workers import stop_all_workers
            await stop_all_workers()
        except Exception as e:
            logger.warning(f"Ошибка остановки воркеров: {e}")

        # 1. Останавливаем системный сервис
        try:
            system_service = get_system_service()
            await system_service.stop()
        except Exception as e:
            logger.warning(f"Ошибка остановки SystemService: {e}")

        # 2. Отключаем систему
        if _app_state.get('redis_client'):
            await _app_state['redis_client'].set(REDIS_KEYS.SYSTEM_ENABLED, "false")
        
        # 3. Останавливаем все сервисы
        try:
            await shutdown_services()
        except Exception as e:
            logger.warning(f"Ошибка остановки сервисов: {e}")
        
        # 4. Останавливаем дозвон
        if _app_state.get('dialer_manager'):
            from app.services.dialer import close_dialer
            await close_dialer()
            logger.info("✅ Dialer остановлен")
        
        # 5. Останавливаем транскрибацию
        if _app_state.get('transcription_service'):
            from app.services.transcription import close_transcription_service
            await close_transcription_service()
            logger.info("✅ Transcription остановлен")
        
        # 6. Закрываем Redis
        if _app_state.get('redis_client'):
            await close_redis()
            logger.info("✅ Redis отключен")
        
        # 7. Закрываем базу данных
        if _app_state.get('db_pool'):
            await close_database()
            logger.info("✅ База данных отключена")
        
        _app_state['initialized'] = False
        
    except Exception as e:
        logger.error(f"❌ Ошибка при завершении: {e}")


# =============================================
# Получение приложения
# =============================================
def get_app() -> FastAPI:
    """
    Получить экземпляр приложения.
    Создаёт приложение если оно ещё не создано.
    
    Returns:
        Экземпляр FastAPI
    """
    global _app
    
    if _app is None:
        _app = create_app()
    
    return _app


def get_app_state() -> Dict[str, Any]:
    """
    Получить состояние приложения.
    
    Returns:
        Словарь с состоянием
    """
    return _app_state.copy()


# =============================================
# Утилиты
# =============================================
def is_initialized() -> bool:
    """Проверить, инициализировано ли приложение"""
    return _app_state.get('initialized', False)


def get_uptime() -> Optional[float]:
    """Получить время работы приложения в секундах"""
    import time
    
    start_time = _app_state.get('start_time')
    if start_time:
        return time.time() - start_time
    return None


# =============================================
# Импорт для корректной работы
# =============================================
from datetime import datetime
from app.core.redis import REDIS_KEYS


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Версия
    "__version__",
    "__author__",
    "__description__",
    
    # Приложение
    "create_app",
    "get_app",
    "get_app_state",
    "is_initialized",
    "get_uptime",
    "shutdown_handler",
    
    # Ядро
    "settings",
    "logger",
    "get_db_pool",
    "get_redis_client",
    
    # Модели (выборочно)
    "BaseSchema",
    "SuccessResponse",
    "ErrorResponse",
    "PaginatedResponse",
    
    # Сервисы (выборочно)
    "service_registry",
    "get_campaign_service",
    "get_contact_service",
    "get_dialer_service",
    "get_system_service",
    
    # API
    "api_router",
]
