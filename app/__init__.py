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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    get_settings_service,
    get_auth_service,
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
# Обработка бизнес-исключений сервисов
# =============================================
# app/services/*.py определяет ~50 кастомных классов исключений
# (UserNotFoundError, InvalidCredentialsError, CampaignValidationError и
# т.д.), но нигде в проекте не было ни одного места, конвертирующего их в
# HTTP-ответ - ни в самих роутерах (app/api/*.py просто вызывают методы
# сервиса и возвращают результат), ни глобального exception_handler'а.
# Итог, подтверждённый живым HTTP-запросом через docker compose: ЛЮБАЯ
# бизнес-ошибка где угодно в API (неверный пароль, "не найдено",
# валидация, конфликт) долетает до FastAPI необработанной и превращается
# в голый 500 Internal Server Error вместо корректного 401/404/409/422.
# Соглашение по именам классов across всех сервисов достаточно
# единообразно, чтобы сопоставить статус по суффиксу имени класса; любое
# исключение, класс которого определён не в app.services.*, ниже не
# перехватывается и по-прежнему становится 500 - это осознанно: реальные
# непредвиденные баги (KeyError, AttributeError и т.п. из-за ошибок в
# коде) должны громко проявляться как 500, а не тихо превращаться в 400.
_ERROR_SUFFIX_STATUS: list[tuple[str, int]] = [
    ("InvalidCredentialsError", 401),
    ("InvalidTokenError", 401),
    ("TokenExpiredError", 401),
    ("AccountDisabledError", 403),
    ("AccountLockedError", 403),
    ("ReadOnlyError", 403),
    ("PermissionError", 403),
    ("NotFoundError", 404),
    ("AlreadyExistsError", 409),
    ("AlreadyRunningError", 409),
    ("AlreadyEnabledError", 409),
    ("AlreadyDisabledError", 409),
    ("AlreadyInProgressError", 409),
    ("NotRunningError", 409),
    ("DuplicateError", 409),
    ("ValidationError", 422),
]


def _service_error_status_code(exc: Exception) -> int:
    """Сопоставить кастомное исключение сервиса с HTTP-статусом по суффиксу имени класса."""
    name = type(exc).__name__
    for suffix, status_code in _ERROR_SUFFIX_STATUS:
        if name.endswith(suffix):
            return status_code
    return 400  # базовый класс ошибки конкретного домена (XError) - бизнес-правило, не баг


async def _service_error_handler(request: Request, exc: Exception):
    # Registered against the broad `Exception` type (Starlette has no way
    # to register "any exception defined under a given module prefix"),
    # so anything that isn't one of our own app.services.* error classes
    # must be re-raised here - Starlette's ServerErrorMiddleware still
    # turns it into the normal 500 response, this just adds one extra
    # frame to get there.
    from app.core.database import UniqueViolationError, ForeignKeyViolationError

    if isinstance(exc, (UniqueViolationError, ForeignKeyViolationError)):
        # ConnectionPool.acquire() already translates the raw asyncpg
        # constraint violation into one of these two - found live via
        # docker compose: creating a contact_groups row with a name that
        # already exists surfaces this and, before this handler existed,
        # became a bare 500 with no indication it was a duplicate.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    if not type(exc).__module__.startswith("app.services."):
        raise exc
    return JSONResponse(
        status_code=_service_error_status_code(exc),
        content={"detail": str(exc)},
    )


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
    
    # Настраиваем CORS.
    #
    # api.cors_origins (Настройки → API) сохраняется в БД, но НЕ применяется
    # здесь и не может быть применено даже отложенно из lifespan(), в отличие
    # от dialer.*/tts.*/transcription.* (см. шаги 5.5-5.9 в lifespan()):
    # CORSMiddleware конструируется прямо здесь, при создании самого FastAPI-
    # приложения (create_app()), ДО того как вообще существует подключение к
    # БД (оно появляется только на шаге 1 внутри lifespan()) - настройки
    # неоткуда прочитать. Более того, Starlette строит и кеширует финальный
    # стек middleware (build_middleware_stack()) на первом же ASGI-вызове,
    # которым является сам lifespan-startup - то есть даже мутация kwargs
    # у уже добавленного middleware изнутри lifespan() приходит СТРОГО
    # ПОЗЖЕ, чем стек уже собран, и не даёт эффекта. Единственный вариант
    # приложить значение из БД - полный перезапуск процесса, ПОСЛЕ того как
    # архитектура создания приложения станет асинхронной и сможет прочитать
    # БД до создания CORSMiddleware - за рамками этого фикса. Настройка
    # помечена requires_restart=True, но честно говоря не подключена вообще:
    # значение из .env (CORS_ORIGINS) остаётся единственным работающим.
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )

    # Конвертирует кастомные исключения app/services/*.py (XNotFoundError,
    # InvalidCredentialsError и т.д.) в корректные HTTP-статусы - см.
    # комментарий у _service_error_handler выше.
    _app.add_exception_handler(Exception, _service_error_handler)
    
    # Добавляем middleware
    @_app.middleware("http")
    async def app_middleware(request, call_next):
        """Главный middleware приложения"""
        import time
        import uuid
        from app.core.logger import correlation_id_var, request_id_var, ip_address_var, user_agent_var

        # Correlation ID
        corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        correlation_id_var.set(corr_id)
        request_id_var.set(req_id)

        # IP/User-Agent запроса - читаются всеми _log_audit() по сервисам
        # (app/services/campaign.py, system.py, settings.py и т.д.) через
        # эти же контекстные переменные, не как параметр функции: ни одна
        # из них никогда не получала IP на вход, поэтому в audit_log эта
        # колонка была NULL для абсолютно каждой записи, независимо от
        # того, что реально сделал человек (подтверждено живьём -
        # "IP адрес: -" на любом событии). X-Forwarded-For/X-Real-IP -
        # та же логика, что уже используется для рейт-лимита
        # (app/core/dependencies.py:625-627) - за обратным прокси
        # request.client.host был бы адресом самого nginx, а не клиента.
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("X-Real-IP") or (request.client.host if request.client else None)
        ip_address_var.set(client_ip)
        user_agent_var.set(request.headers.get("User-Agent"))

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
        
        # 3.5 asterisk.ami_host/ami_port/ami_user/ami_password (Настройки →
        # Asterisk) сохранялись в БД, но никогда не читались обратно - даже
        # DialerManager.__init__() (шаг 4 ниже) при каждом старте брал
        # исключительно settings.AMI_HOST/PORT/USER/PASSWORD из .env, а
        # panoramisk.Manager (само AMI-соединение) конструируется прямо в
        # __init__ - в отличие от dialer.max_calls и прочих настроек выше,
        # его нельзя "докрутить" уже ПОСЛЕ создания DialerManager, нужно
        # подменить settings.AMI_* ДО вызова init_dialer(). SettingsService
        # ещё не зарегистрирован глобально (это происходит на шаге 5) -
        # используем отдельный временный экземпляр только для чтения этих
        # четырёх ключей.
        #
        # Явный компромисс ради безопасности живой телефонии: подменяем
        # settings.AMI_* только если ЗНАЧЕНИЕ РЕАЛЬНО СОХРАНЕНО В БД (админ
        # хотя бы раз нажал "Сохранить" в этом разделе) - если раздел ни
        # разу не трогали, в БД просто нет строки на этот ключ и
        # get_setting_value() вернёт definition.default_value, который сам
        # равен settings.AMI_HOST и т.д. на момент импорта settings.py, то
        # есть тому же .env - поведение НЕ меняется для всех, кто никогда
        # не открывал этот раздел настроек. Если же значение в БД
        # действительно есть - расхождение всегда громко пишем в лог
        # warning'ом (не info), чтобы после рестарта было сразу видно,
        # что фактически используемые креды AMI подменены сохранённым в
        # БД значением, а не тем, что в .env на этом сервере.
        try:
            from app.services.settings import SettingsService as _SettingsServiceForAmiBootstrap
            _ami_settings_probe = _SettingsServiceForAmiBootstrap(db_pool, redis_client)
            db_ami_host = await _ami_settings_probe.get_setting_value("asterisk.ami_host")
            db_ami_port = await _ami_settings_probe.get_setting_value("asterisk.ami_port")
            db_ami_user = await _ami_settings_probe.get_setting_value("asterisk.ami_user")
            db_ami_password = await _ami_settings_probe.get_setting_value("asterisk.ami_password")
            if db_ami_host and db_ami_host != settings.AMI_HOST:
                logger.warning(f"asterisk.ami_host из БД ({db_ami_host}) отличается от .env ({settings.AMI_HOST}) - используется значение из БД")
                settings.AMI_HOST = db_ami_host
            if db_ami_port and db_ami_port != settings.AMI_PORT:
                logger.warning(f"asterisk.ami_port из БД ({db_ami_port}) отличается от .env ({settings.AMI_PORT}) - используется значение из БД")
                settings.AMI_PORT = db_ami_port
            if db_ami_user and db_ami_user != settings.AMI_USER:
                logger.warning(f"asterisk.ami_user из БД ({db_ami_user}) отличается от .env ({settings.AMI_USER}) - используется значение из БД")
                settings.AMI_USER = db_ami_user
            if db_ami_password and db_ami_password != settings.AMI_PASSWORD:
                logger.warning("asterisk.ami_password из БД отличается от .env - используется значение из БД")
                settings.AMI_PASSWORD = db_ami_password
        except Exception as e:
            logger.warning(f"Не удалось прочитать сохранённые настройки AMI из БД, использованы значения из .env: {e}")

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

        # 5.5 Применяем настройки дозвона, сохранённые в БД (SettingsService),
        # поверх статических .env-умолчаний, с которыми был сконструирован
        # DialerManager - на момент init_dialer() (шаг 4, раньше этого)
        # SettingsService ещё не существует. С WORKERS>1 (gunicorn) каждый
        # воркер поднимает СВОЙ DialerManager с СОБСТВЕННЫМ AMI-соединением
        # (app/services/dialer.py:242) и СВОИМ self.max_calls в памяти - без
        # этого шага после рестарта все воркеры снова берут MAX_CALLS из
        # .env, даже если админ через веб поменял значение в БД. Изменение
        # через веб само по себе (см. SettingsService.update_setting) живьём
        # применяется только к тому ОДНОМУ воркеру, который обработал этот
        # конкретный HTTP-запрос - остальные не узнают об изменении до
        # своего следующего рестарта, когда как раз и подхватят его отсюда.
        try:
            settings_service = get_settings_service()
            dialer_manager.max_calls = await settings_service.get_setting_value("dialer.max_calls")
            dialer_manager.caller_id = await settings_service.get_setting_value("dialer.caller_id")
            dialer_manager.call_timeout = await settings_service.get_setting_value("dialer.call_timeout")
            dialer_manager.max_retries = await settings_service.get_setting_value("dialer.max_retries")
            cps = await settings_service.get_setting_value("dialer.default_cps")
            dialer_manager.cps_limiter.update_rate(cps)
            logger.info(
                f"Настройки дозвона применены из БД: max_calls={dialer_manager.max_calls}, "
                f"cps={cps}, call_timeout={dialer_manager.call_timeout}, "
                f"max_retries={dialer_manager.max_retries}"
            )
        except Exception as e:
            logger.warning(f"Не удалось применить сохранённые настройки дозвона, использованы значения из .env: {e}")

        # 5.6 То же самое для security.max_login_attempts/block_duration -
        # LoginAttemptTracker живёт внутри AuthService, отдельным объектом
        # на каждый gunicorn-воркер (WORKERS>1), так что без этого шага
        # каждый новый воркер после рестарта опять брал бы захардкоженные
        # max_attempts=5/block_duration=300 вместо сохранённых в БД -
        # ровно та же проблема, что и с dialer_manager чуть выше.
        # Отдельный try/except, чтобы сбой здесь ни при каких условиях не
        # мог помешать уже отработавшему применению настроек дозвона.
        try:
            settings_service = get_settings_service()
            auth_service = get_auth_service()
            auth_service.login_tracker.max_attempts = await settings_service.get_setting_value("security.max_login_attempts")
            auth_service.login_tracker.block_duration = await settings_service.get_setting_value("security.block_duration")
            logger.info(
                f"Настройки блокировки входа применены из БД: "
                f"max_attempts={auth_service.login_tracker.max_attempts}, "
                f"block_duration={auth_service.login_tracker.block_duration}"
            )
        except Exception as e:
            logger.warning(f"Не удалось применить сохранённые настройки блокировки входа, использованы значения по умолчанию: {e}")

        # 5.7 dialer.adaptive_cps - раньше единственным переключателем был
        # ADAPTIVE_CPS_ENABLED из .env, читаемый только один раз в
        # DialerManager.__init__() (до того, как SettingsService вообще
        # существует) - сохранённое в БД значение этой настройки ни на что
        # не влияло, даже после рестарта. Пересоздаём/убираем
        # dialer_manager.adaptive_cps здесь теми же параметрами, что и
        # исходная конструкция в dialer.py, если сохранённое значение
        # расходится с тем, что уже решил .env.
        try:
            from app.core.config import settings as app_settings
            from app.utils.rate_limiter import AdaptiveCPSLimiter
            adaptive_enabled = await settings_service.get_setting_value("dialer.adaptive_cps")
            if adaptive_enabled and not dialer_manager.adaptive_cps:
                dialer_manager.adaptive_cps = AdaptiveCPSLimiter(
                    base_rate=app_settings.DEFAULT_CPS,
                    redis_client=dialer_manager.redis,
                    max_calls=dialer_manager.max_calls,
                    min_rate=app_settings.MIN_CPS,
                    alpha=app_settings.ADAPTIVE_CPS_ALPHA
                )
            elif not adaptive_enabled and dialer_manager.adaptive_cps:
                dialer_manager.adaptive_cps = None
            logger.info(f"dialer.adaptive_cps применён из БД: {bool(dialer_manager.adaptive_cps)}")
        except Exception as e:
            logger.warning(f"Не удалось применить dialer.adaptive_cps, оставлено значение из .env: {e}")

        # 5.8 tts.concurrent_limit - TTSService._tts_semaphore создаётся один
        # раз из settings.TTS_MAX_CONCURRENT (.env) в конструкторе, а
        # SettingsService на тот момент ещё не существует. asyncio.Semaphore
        # нельзя безопасно "докрутить" на лету - просто заменяем сам объект
        # семафора, пока ни один TTS-запрос ещё не запущен (это самое
        # начало старта приложения).
        try:
            tts_service = get_tts_service()
            tts_limit = await settings_service.get_setting_value("tts.concurrent_limit")
            if tts_limit:
                tts_service._tts_semaphore = asyncio.Semaphore(tts_limit)
                logger.info(f"tts.concurrent_limit применён из БД: {tts_limit}")
        except Exception as e:
            logger.warning(f"Не удалось применить tts.concurrent_limit, оставлено значение из .env: {e}")

        # 5.9 transcription.engine/whisper_model/concurrent_limit - та же
        # история: TranscriptionService.__init__ читает
        # settings.TRANSCRIPTION_ENGINE/WHISPER_MODEL/TRANSCRIPTION_CONCURRENT
        # (.env) один раз, до того как SettingsService существует. self.engine/
        # self.model - обычные атрибуты, читаемые заново при каждой ленивой
        # загрузке модели (см. _init_whisper()) - можно просто переставить их
        # здесь, пока транскрибация ещё ни разу не запускалась в этом воркере.
        try:
            transcription_service = get_transcription_service()
            db_engine = await settings_service.get_setting_value("transcription.engine")
            if db_engine and db_engine != "auto":
                transcription_service.engine = transcription_service._detect_engine(db_engine)
            db_whisper_model = await settings_service.get_setting_value("transcription.whisper_model")
            if db_whisper_model:
                transcription_service.model = db_whisper_model
            db_concurrent = await settings_service.get_setting_value("transcription.concurrent_limit")
            if db_concurrent:
                transcription_service._semaphore = asyncio.Semaphore(db_concurrent)
            logger.info(
                f"Настройки транскрибации применены из БД: engine={transcription_service.engine.value}, "
                f"model={transcription_service.model}"
            )
        except Exception as e:
            logger.warning(f"Не удалось применить настройки транскрибации, использованы значения из .env: {e}")

        # 5.10 logging.level/logging.format - та же история, что и с
        # dialer.*/security.* выше: init_logging() (в create_app(), ещё до
        # этого lifespan) читает settings.LOG_LEVEL/LOG_FORMAT только из
        # .env, а колбеки update_log_level/update_log_format применяют
        # изменение из веб-интерфейса только к тому воркеру, который
        # обработал запрос - остальные воркеры и любой будущий рестарт
        # снова берут значения из .env, пока не подхватят их здесь.
        try:
            from app.core.logger import LoggerFactory
            db_log_level = await settings_service.get_setting_value("logging.level")
            db_log_format = await settings_service.get_setting_value("logging.format")
            LoggerFactory.configure(
                level=db_log_level or LoggerFactory._current_level,
                format_type=db_log_format or LoggerFactory._current_format_type,
                log_file=LoggerFactory._current_log_file,
                error_log_file=LoggerFactory._current_error_log_file,
            )
            logger.info(
                f"Настройки логирования применены из БД: level={LoggerFactory._current_level}, "
                f"format={LoggerFactory._current_format_type}"
            )
        except Exception as e:
            logger.warning(f"Не удалось применить сохранённые настройки логирования, использованы значения из .env: {e}")

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
