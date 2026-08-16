#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конфигурация приложения AutoDialer Ultimate
Версия: 3.0.0

Централизованное управление всеми настройками через Pydantic Settings.
Поддерживает загрузку из .env файла и переменных окружения.

ИСПОЛЬЗОВАНИЕ:
    from app.core.config import settings
    
    db_host = settings.DB_HOST
    max_calls = settings.MAX_CALLS
"""

import os
import json
from typing import List, Optional, Dict, Any, Union, Literal, Annotated
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode
from datetime import timedelta


# =============================================
# Вспомогательные функции
# =============================================
def parse_cors_origins(v: Union[str, List[str]]) -> List[str]:
    """Парсинг CORS origins из строки или списка"""
    if isinstance(v, str):
        if v == "*":
            return ["*"]
        return [origin.strip() for origin in v.split(",") if origin.strip()]
    return v


def parse_redis_url(url: str) -> Dict[str, Any]:
    """Парсинг Redis URL в компоненты"""
    if not url:
        return {}
    
    # redis://user:pass@host:port/db
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 6379,
            "password": parsed.password or None,
            "db": int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
            "username": parsed.username or None,
        }
    except:
        return {}


def parse_db_url(url: str) -> Dict[str, Any]:
    """Парсинг PostgreSQL URL в компоненты"""
    if not url:
        return {}
    
    # postgresql://user:pass@host:port/dbname
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "database": parsed.path.lstrip("/") if parsed.path else "",
            "user": parsed.username or "",
            "password": parsed.password or "",
        }
    except:
        return {}


# =============================================
# Основной класс настроек
# =============================================
class Settings(BaseSettings):
    """
    Настройки приложения AutoDialer Ultimate.
    
    Загружаются из .env файла и переменных окружения.
    Префикс для переменных: AUTODIALER_ (опционально)
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Без префикса: имена полей ниже (DB_HOST, REDIS_HOST, AMI_PASSWORD,
        # JWT_SECRET и т.д.) - это и есть имена переменных окружения,
        # как задокументировано в .env.example и используется в
        # docker-compose.yml / install.sh / scripts/*.sh.
        case_sensitive=True,
        extra="ignore",
        validate_default=True,
    )
    
    # =============================================
    # Приложение
    # =============================================
    VERSION: str = Field("3.0.0", description="Версия приложения")
    DEBUG: bool = Field(False, description="Режим отладки")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        "production", 
        description="Окружение"
    )
    APP_NAME: str = Field("AutoDialer Ultimate", description="Название приложения")
    APP_HOST: str = Field("0.0.0.0", description="Хост для прослушивания")
    APP_PORT: int = Field(8000, ge=1, le=65535, description="Порт")
    WORKERS: int = Field(4, ge=1, le=32, description="Количество воркеров")
    
    # Пути
    BASE_DIR: Path = Field(default_factory=lambda: Path("/opt/autodialer"))
    STATIC_DIR: Path = Field(default_factory=lambda: Path("/opt/autodialer/frontend/dist"))
    LOG_DIR: Path = Field(default_factory=lambda: Path("/opt/autodialer/logs"))
    DATA_DIR: Path = Field(default_factory=lambda: Path("/opt/autodialer/data"))
    TTS_DIR: Path = Field(default_factory=lambda: Path("/var/lib/asterisk/sounds/tts"))
    RECORDINGS_DIR: Path = Field(default_factory=lambda: Path("/var/spool/asterisk/monitor"))
    
    # =============================================
    # База данных PostgreSQL
    # =============================================
    DATABASE_URL: Optional[str] = Field(None, description="URL подключения к БД")
    
    DB_HOST: str = Field("127.0.0.1", description="Хост PostgreSQL")
    DB_PORT: int = Field(5432, ge=1, le=65535, description="Порт PostgreSQL")
    DB_NAME: str = Field("autodialer", description="Имя базы данных")
    DB_USER: str = Field("autodialer", description="Пользователь БД")
    DB_PASSWORD: str = Field("", description="Пароль БД")
    
    # Пул соединений
    DB_POOL_MIN_SIZE: int = Field(5, ge=1, le=100, description="Мин. размер пула")
    DB_POOL_MAX_SIZE: int = Field(50, ge=1, le=500, description="Макс. размер пула")
    DB_MAX_QUERIES: int = Field(50000, ge=0, description="Макс. запросов на соединение")
    DB_MAX_INACTIVE_LIFETIME: int = Field(300, ge=0, description="Время жизни неактивного соединения (сек)")
    DB_COMMAND_TIMEOUT: int = Field(60, ge=1, description="Таймаут команды (сек)")
    DB_STATEMENT_CACHE_SIZE: int = Field(100, ge=0, description="Размер кеша prepared statements")
    
    # Репликация (опционально)
    DB_REPLICA_HOST: Optional[str] = Field(None, description="Хост реплики")
    DB_REPLICA_PORT: Optional[int] = Field(5432, description="Порт реплики")
    DB_REPLICA_NAME: Optional[str] = Field(None, description="Имя БД реплики")
    DB_REPLICA_USER: Optional[str] = Field(None, description="Пользователь реплики")
    DB_REPLICA_PASSWORD: Optional[str] = Field(None, description="Пароль реплики")
    
    # =============================================
    # Redis
    # =============================================
    REDIS_URL: Optional[str] = Field(None, description="URL подключения к Redis")
    
    REDIS_HOST: str = Field("localhost", description="Хост Redis")
    REDIS_PORT: int = Field(6379, ge=1, le=65535, description="Порт Redis")
    REDIS_PASSWORD: Optional[str] = Field(None, description="Пароль Redis")
    REDIS_DB: int = Field(0, ge=0, le=15, description="Номер БД Redis")
    REDIS_USERNAME: Optional[str] = Field(None, description="Имя пользователя Redis 6+")
    
    # Redis Sentinel
    REDIS_SENTINEL_ENABLED: bool = Field(False, description="Использовать Redis Sentinel")
    REDIS_SENTINEL_MASTER: str = Field("mymaster", description="Имя мастера Sentinel")
    REDIS_SENTINEL_NODES: str = Field("", description="Узлы Sentinel (host:port,host:port)")
    
    # Пул соединений Redis
    REDIS_MAX_CONNECTIONS: int = Field(50, ge=1, description="Макс. соединений Redis")
    REDIS_SOCKET_TIMEOUT: int = Field(5, ge=1, description="Таймаут сокета (сек)")
    REDIS_SOCKET_CONNECT_TIMEOUT: int = Field(5, ge=1, description="Таймаут подключения (сек)")
    REDIS_RETRY_ON_TIMEOUT: bool = Field(True, description="Повторять при таймауте")
    REDIS_HEALTH_CHECK_INTERVAL: int = Field(30, ge=0, description="Интервал проверки здоровья (сек)")
    
    # =============================================
    # Asterisk AMI
    # =============================================
    AMI_HOST: str = Field("127.0.0.1", description="Хост AMI")
    AMI_PORT: int = Field(5038, ge=1, le=65535, description="Порт AMI")
    AMI_USER: str = Field("autodialer", description="Пользователь AMI")
    AMI_PASSWORD: str = Field("", description="Пароль AMI")
    AMI_SSL: bool = Field(False, description="Использовать SSL/TLS")
    AMI_SSL_VERIFY: bool = Field(False, description="Проверять SSL сертификат")
    
    # FreePBX интеграция
    FREEPBX_ENABLED: bool = Field(True, description="Интеграция с FreePBX")
    FREEPBX_EXTENSION: str = Field("291", description="Extension для дозвона")
    FREEPBX_CONTEXT: str = Field("from-internal", description="Контекст FreePBX")
    FREEPBX_TRUNK: str = Field("", description="Транк для исходящих (если не Local/)")
    
    # =============================================
    # Дозвон (Dialer)
    # =============================================
    MAX_CALLS: int = Field(50, ge=1, le=500, description="Макс. одновременных звонков")
    DEFAULT_CPS: int = Field(5, ge=1, le=100, description="Calls per second по умолчанию")
    MAX_CPS: int = Field(50, ge=1, le=200, description="Максимальный CPS")
    MIN_CPS: float = Field(0.5, ge=0.1, le=10, description="Минимальный CPS")
    
    CALL_TIMEOUT: int = Field(30, ge=5, le=300, description="Таймаут звонка (сек)")
    CALLER_ID: str = Field("AutoDialer", description="Caller ID по умолчанию")
    CALLER_ID_NUMBER: str = Field("", description="Номер Caller ID")
    
    MAX_RETRIES: int = Field(3, ge=0, le=10, description="Макс. повторных попыток")
    
    # Стратегии повторных звонков
    RETRY_BUSY_DELAY: int = Field(120, ge=30, le=3600, description="Задержка при busy (сек)")
    RETRY_NOANSWER_DELAY: int = Field(300, ge=60, le=7200, description="Задержка при noanswer (сек)")
    RETRY_FAILED_DELAY: int = Field(60, ge=30, le=1800, description="Задержка при failed (сек)")
    
    # Адаптивный CPS
    ADAPTIVE_CPS_ENABLED: bool = Field(True, description="Включить адаптивный CPS")
    ADAPTIVE_CPS_ALPHA: float = Field(0.3, ge=0.1, le=1.0, description="Коэффициент сглаживания EMA")
    ADAPTIVE_CPS_SUCCESS_ALPHA: float = Field(0.1, ge=0.05, le=0.5, description="Коэфф. успешности")
    
    # Degraded mode
    DEGRADED_MODE_ENABLED: bool = Field(True, description="Включить degraded mode при потере Redis")
    DEGRADED_QUEUE_FILE: Path = Field(
        default_factory=lambda: Path("/opt/autodialer/data/degraded_queue.jsonl")
    )
    DEGRADED_QUEUE_MAX_SIZE: int = Field(500, ge=10, le=10000, description="Макс. размер локальной очереди")
    DEGRADED_QUEUE_MAX_AGE: int = Field(300, ge=60, le=3600, description="Макс. возраст записи (сек)")
    DEGRADED_RECOVERY_CPS: int = Field(5, ge=1, le=20, description="CPS при восстановлении")
    
    # =============================================
    # Транскрибация
    # =============================================
    TRANSCRIPTION_ENABLED: bool = Field(True, description="Включить транскрибацию")
    TRANSCRIPTION_ENGINE: Literal["whisper", "vosk", "google", "none"] = Field(
        "none", 
        description="Движок транскрибации"
    )
    TRANSCRIPTION_MODEL: Optional[str] = Field(None, description="Модель транскрибации")
    
    # Whisper
    WHISPER_MODEL: Literal["tiny", "base", "small", "medium", "large"] = Field(
        "small", 
        description="Модель Whisper"
    )
    WHISPER_LANGUAGE: str = Field("ru", description="Язык по умолчанию")
    WHISPER_FP16: bool = Field(False, description="Использовать FP16 (только GPU)")
    WHISPER_DEVICE: Literal["cpu", "cuda"] = Field("cpu", description="Устройство")
    
    # Vosk
    VOSK_MODEL: str = Field("ru", description="Модель Vosk")
    VOSK_MODEL_PATH: Path = Field(
        default_factory=lambda: Path("/opt/autodialer/models/vosk-model-small-ru-0.22")
    )
    VOSK_SAMPLE_RATE: int = Field(16000, description="Частота дискретизации")
    
    # Google Speech-to-Text
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = Field(None, description="Путь к JSON ключу Google")
    GOOGLE_MODEL: str = Field("default", description="Модель Google STT")
    
    # Очередь транскрибации
    TRANSCRIPTION_QUEUE_SIZE: int = Field(1000, description="Макс. размер очереди")
    TRANSCRIPTION_CONCURRENT: int = Field(1, ge=1, le=4, description="Одновременных транскрибаций")
    
    # =============================================
    # TTS (Text-to-Speech)
    # =============================================
    TTS_ENABLED: bool = Field(True, description="Включить TTS")
    TTS_ENGINE: Literal["piper", "none"] = Field("piper", description="Движок TTS")
    TTS_MAX_CONCURRENT: int = Field(2, ge=1, le=10, description="Макс. одновременных генераций")
    TTS_TIMEOUT: int = Field(30, ge=10, le=120, description="Таймаут генерации (сек)")
    TTS_MAX_TEXT_LENGTH: int = Field(500, ge=50, le=2000, description="Макс. длина текста")
    
    # Piper
    PIPER_MODEL_DIR: Path = Field(
        default_factory=lambda: Path("/var/lib/asterisk/sounds/tts/models")
    )
    PIPER_VOICES: Annotated[List[str], NoDecode] = Field(["denis", "irina"], description="Доступные голоса")
    PIPER_DEFAULT_VOICE: str = Field("denis", description="Голос по умолчанию")
    PIPER_SPEED: float = Field(1.0, ge=0.5, le=2.0, description="Скорость речи")
    
    # Аудио файлы
    AUDIO_MAX_SIZE: int = Field(10 * 1024 * 1024, description="Макс. размер файла (байт)")
    AUDIO_ALLOWED_FORMATS: Annotated[List[str], NoDecode] = Field([".wav", ".mp3"], description="Разрешённые форматы")
    AUDIO_RETENTION_DAYS: int = Field(30, ge=7, le=365, description="Дней хранения аудио")
    AUDIO_CONVERT_FORMAT: str = Field("sln", description="Формат для конвертации")
    AUDIO_SAMPLE_RATE: int = Field(8000, description="Частота дискретизации")
    
    # =============================================
    # Безопасность
    # =============================================
    SECRET_KEY: str = Field(
        "change-me-in-production-please-use-strong-secret-key",
        description="Секретный ключ для JWT",
        min_length=32,
        validation_alias="JWT_SECRET",
    )
    ALGORITHM: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        "HS256", 
        description="Алгоритм JWT"
    )
    
    # JWT токены
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60, ge=1, description="Время жизни access токена (мин)")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, ge=1, le=365, description="Время жизни refresh токена (дней)")
    API_TOKEN_EXPIRE_DAYS: int = Field(365, ge=1, le=3650, description="Время жизни API токена (дней)")
    
    # Пароли
    PASSWORD_MIN_LENGTH: int = Field(8, ge=6, description="Мин. длина пароля")
    PASSWORD_REQUIRE_UPPER: bool = Field(True, description="Требовать заглавные буквы")
    PASSWORD_REQUIRE_LOWER: bool = Field(True, description="Требовать строчные буквы")
    PASSWORD_REQUIRE_DIGIT: bool = Field(True, description="Требовать цифры")
    PASSWORD_REQUIRE_SPECIAL: bool = Field(False, description="Требовать спецсимволы")
    BCRYPT_ROUNDS: int = Field(12, ge=4, le=31, description="Раундов bcrypt")
    
    # Rate limiting
    RATE_LIMIT_ENABLED: bool = Field(True, description="Включить rate limiting")
    RATE_LIMIT_GLOBAL: int = Field(200, description="Глобальный лимит запросов в минуту")
    RATE_LIMIT_AUTH: int = Field(10, description="Лимит для /auth/* в минуту")
    RATE_LIMIT_API: int = Field(100, description="Лимит для /api/* в минуту")
    
    # CORS
    CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["*"],
        description="Разрешённые origins для CORS"
    )
    CORS_ALLOW_CREDENTIALS: bool = Field(True, description="Разрешить credentials")
    CORS_ALLOW_METHODS: List[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешённые методы"
    )
    CORS_ALLOW_HEADERS: List[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешённые заголовки"
    )
    
    # Trusted proxies
    TRUSTED_PROXIES: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        description="Доверенные прокси"
    )

    # =============================================
    # Email (SMTP)
    # =============================================
    # Отсутствие SMTP_HOST - валидное состояние "email не настроен", а не
    # ошибка конфигурации: письма (приветственное, восстановление пароля)
    # логируются, но не отправляются, по аналогии с тем, как STT
    # намеренно необязателен для установки (app/requirements/stt.txt).
    SMTP_HOST: Optional[str] = Field(None, description="Адрес SMTP-сервера")
    SMTP_PORT: int = Field(587, ge=1, le=65535, description="Порт SMTP-сервера")
    SMTP_USER: Optional[str] = Field(None, description="Пользователь SMTP")
    SMTP_PASSWORD: Optional[str] = Field(None, description="Пароль SMTP")
    SMTP_USE_TLS: bool = Field(True, description="STARTTLS для SMTP")
    SMTP_FROM_EMAIL: str = Field("noreply@autodialer.local", description="Адрес отправителя")
    SMTP_FROM_NAME: str = Field("AutoDialer Ultimate", description="Имя отправителя")
    SMTP_TIMEOUT: int = Field(10, ge=1, le=60, description="Таймаут соединения с SMTP (сек)")
    APP_BASE_URL: str = Field(
        "http://localhost:8000",
        description="Базовый URL приложения для ссылок в письмах (сброс пароля и т.п.)"
    )

    # =============================================
    # Логирование
    # =============================================
    LOG_LEVEL: Literal["TRACE", "DEBUG", "INFO", "AUDIT", "WARNING", "ERROR", "CRITICAL"] = Field(
        "INFO", 
        description="Уровень логирования"
    )
    LOG_FORMAT: Literal["console", "json"] = Field("console", description="Формат логов")
    LOG_FILE: Path = Field(
        default_factory=lambda: Path("/opt/autodialer/logs/autodialer.log")
    )
    LOG_ERROR_FILE: Path = Field(
        default_factory=lambda: Path("/opt/autodialer/logs/error.log")
    )
    LOG_AUDIT_FILE: Optional[Path] = Field(None, description="Файл для аудит логов")
    LOG_MAX_BYTES: int = Field(10 * 1024 * 1024, description="Макс. размер файла (байт)")
    LOG_BACKUP_COUNT: int = Field(10, ge=1, description="Количество файлов ротации")
    LOG_USE_COLORS: bool = Field(True, description="Использовать цвета в консоли")
    LOG_SHOW_CONTEXT: bool = Field(True, description="Показывать контекст")
    LOG_INCLUDE_BODY: bool = Field(False, description="Логировать тело запросов")
    LOG_MAX_BODY_LENGTH: int = Field(1000, description="Макс. длина тела в логах")
    
    # Sentry (опционально)
    SENTRY_DSN: Optional[str] = Field(None, description="DSN для Sentry")
    SENTRY_ENVIRONMENT: str = Field("production", description="Окружение в Sentry")
    SENTRY_TRACES_SAMPLE_RATE: float = Field(0.1, ge=0, le=1, description="Частота трассировки")
    
    # =============================================
    # Мониторинг и метрики
    # =============================================
    METRICS_ENABLED: bool = Field(True, description="Включить Prometheus метрики")
    METRICS_PORT: int = Field(9090, ge=1, le=65535, description="Порт для метрик")
    METRICS_PATH: str = Field("/metrics", description="Путь для метрик")
    
    # Health checks
    HEALTH_CHECK_INTERVAL: int = Field(30, ge=5, description="Интервал проверки здоровья (сек)")
    HEALTH_CHECK_TIMEOUT: int = Field(5, ge=1, description="Таймаут проверки (сек)")
    
    # OpenTelemetry
    OTEL_ENABLED: bool = Field(False, description="Включить OpenTelemetry")
    OTEL_EXPORTER_ENDPOINT: str = Field("http://localhost:4317", description="Эндпоинт OTLP")
    OTEL_SERVICE_NAME: str = Field("autodialer", description="Имя сервиса")
    
    # =============================================
    # Фоновые задачи
    # =============================================
    WORKER_CLEANUP_INTERVAL: int = Field(86400, ge=3600, description="Интервал очистки (сек)")
    WORKER_RETRY_INTERVAL: int = Field(10, ge=1, description="Интервал обработки повторов (сек)")
    WORKER_METRICS_INTERVAL: int = Field(15, ge=5, description="Интервал обновления метрик (сек)")
    WORKER_WATCHDOG_INTERVAL: int = Field(30, ge=10, description="Интервал watchdog (сек)")
    
    # =============================================
    # WebSocket
    # =============================================
    WEBSOCKET_ENABLED: bool = Field(True, description="Включить WebSocket")
    WEBSOCKET_PATH: str = Field("/ws", description="Путь WebSocket")
    WEBSOCKET_PING_INTERVAL: int = Field(30, ge=5, description="Интервал ping (сек)")
    WEBSOCKET_PING_TIMEOUT: int = Field(10, ge=1, description="Таймаут ping (сек)")
    
    # =============================================
    # Валидаторы
    # =============================================
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins_validator(cls, v: Union[str, List[str]]) -> List[str]:
        return parse_cors_origins(v)
    
    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v
    
    @field_validator("PIPER_VOICES", mode="before")
    @classmethod
    def parse_piper_voices(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [voice.strip() for voice in v.split(",") if voice.strip()]
        return v
    
    @field_validator("AUDIO_ALLOWED_FORMATS", mode="before")
    @classmethod
    def parse_audio_formats(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [fmt.strip() for fmt in v.split(",") if fmt.strip()]
        return v
    
    @model_validator(mode="after")
    def validate_database(self) -> "Settings":
        """Применение DATABASE_URL если задан"""
        if self.DATABASE_URL:
            db_config = parse_db_url(self.DATABASE_URL)
            if db_config.get("host"):
                self.DB_HOST = db_config["host"]
            if db_config.get("port"):
                self.DB_PORT = db_config["port"]
            if db_config.get("database"):
                self.DB_NAME = db_config["database"]
            if db_config.get("user"):
                self.DB_USER = db_config["user"]
            if db_config.get("password"):
                self.DB_PASSWORD = db_config["password"]
        return self
    
    @model_validator(mode="after")
    def validate_redis(self) -> "Settings":
        """Применение REDIS_URL если задан"""
        if self.REDIS_URL:
            redis_config = parse_redis_url(self.REDIS_URL)
            if redis_config.get("host"):
                self.REDIS_HOST = redis_config["host"]
            if redis_config.get("port"):
                self.REDIS_PORT = redis_config["port"]
            if redis_config.get("password"):
                self.REDIS_PASSWORD = redis_config["password"]
            if redis_config.get("db") is not None:
                self.REDIS_DB = redis_config["db"]
            if redis_config.get("username"):
                self.REDIS_USERNAME = redis_config["username"]
        return self
    
    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        """Проверка секретного ключа в production"""
        if self.ENVIRONMENT == "production" and self.SECRET_KEY == "change-me-in-production-please-use-strong-secret-key":
            import warnings
            warnings.warn(
                "⚠️ ВНИМАНИЕ: Используется SECRET_KEY по умолчанию в production! "
                "Установите JWT_SECRET в .env файле.",
                RuntimeWarning
            )
        return self
    
    @model_validator(mode="after")
    def create_directories(self) -> "Settings":
        """Создание необходимых директорий"""
        dirs_to_create = [
            self.LOG_DIR,
            self.DATA_DIR,
            self.TTS_DIR,
        ]
        
        for dir_path in dirs_to_create:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass  # Игнорируем ошибки создания при валидации
        
        return self
    
    # =============================================
    # Вычисляемые свойства
    # =============================================
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"
    
    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT == "staging"
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def SMTP_ENABLED(self) -> bool:
        """Email считается настроенным, если задан SMTP_HOST - без него
        письма (welcome, восстановление пароля) логируются, но не
        отправляются, а не падают с ошибкой конфигурации."""
        return bool(self.SMTP_HOST)

    @property
    def redis_url(self) -> str:
        """Полный URL для Redis"""
        auth = ""
        if self.REDIS_PASSWORD:
            if self.REDIS_USERNAME:
                auth = f"{self.REDIS_USERNAME}:{self.REDIS_PASSWORD}@"
            else:
                auth = f":{self.REDIS_PASSWORD}@"
        
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    @property
    def database_url(self) -> str:
        """Полный URL для PostgreSQL"""
        auth = f"{self.DB_USER}:{self.DB_PASSWORD}" if self.DB_PASSWORD else self.DB_USER
        return f"postgresql://{auth}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def database_pool_config(self) -> Dict[str, Any]:
        """Конфигурация для asyncpg пула"""
        return {
            "min_size": self.DB_POOL_MIN_SIZE,
            "max_size": self.DB_POOL_MAX_SIZE,
            "max_queries": self.DB_MAX_QUERIES,
            "max_inactive_connection_lifetime": self.DB_MAX_INACTIVE_LIFETIME,
            "command_timeout": self.DB_COMMAND_TIMEOUT,
            "statement_cache_size": self.DB_STATEMENT_CACHE_SIZE,
        }
    
    @property
    def access_token_expires(self) -> timedelta:
        return timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    @property
    def refresh_token_expires(self) -> timedelta:
        return timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)
    
    @property
    def ami_config(self) -> Dict[str, Any]:
        """Конфигурация для AMI подключения"""
        return {
            "host": self.AMI_HOST,
            "port": self.AMI_PORT,
            "username": self.AMI_USER,
            "secret": self.AMI_PASSWORD,
            "ssl": self.AMI_SSL,
        }
    
    @property
    def dialer_config(self) -> Dict[str, Any]:
        """Конфигурация дозвона"""
        return {
            "max_calls": self.MAX_CALLS,
            "caller_id": self.CALLER_ID,
            "call_timeout": self.CALL_TIMEOUT,
            "max_retries": self.MAX_RETRIES,
            "default_cps": self.DEFAULT_CPS,
            "freepbx_extension": self.FREEPBX_EXTENSION,
        }
    
    @property
    def retry_strategy_config(self) -> Dict[str, Any]:
        """Конфигурация стратегии повторных звонков"""
        return {
            "busy": {"max": 2, "delay": self.RETRY_BUSY_DELAY},
            "noanswer": {"max": 3, "delay": self.RETRY_NOANSWER_DELAY},
            "failed": {"max": 1, "delay": self.RETRY_FAILED_DELAY},
            "timeout": {"max": 1, "delay": 60},
        }
    
    def model_dump_safe(self, hide_secrets: bool = True) -> Dict[str, Any]:
        """
        Безопасный дамп настроек (без секретов).
        
        Args:
            hide_secrets: Скрыть секретные поля
        
        Returns:
            Словарь с настройками
        """
        data = self.model_dump()
        
        if hide_secrets:
            secret_fields = [
                "DB_PASSWORD", "REDIS_PASSWORD", "AMI_PASSWORD",
                "SECRET_KEY", "SENTRY_DSN", "GOOGLE_APPLICATION_CREDENTIALS"
            ]
            for field in secret_fields:
                if field in data and data[field]:
                    data[field] = "***HIDDEN***"
        
        return data
    
    def print_config(self, hide_secrets: bool = True):
        """Вывод конфигурации в лог"""
        import json
        config_dict = self.model_dump_safe(hide_secrets)
        return json.dumps(config_dict, indent=2, default=str)


# =============================================
# Создание глобального экземпляра
# =============================================
settings = Settings()


# =============================================
# Экспорт
# =============================================
__all__ = [
    "Settings",
    "settings",
    "parse_cors_origins",
    "parse_redis_url",
    "parse_db_url",
]
