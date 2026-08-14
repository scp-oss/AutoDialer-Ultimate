#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления настройками
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Получения и обновления настроек
- Управления категориями настроек
- Валидации значений
- Кеширования настроек
- Применения настроек к компонентам системы
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field

from app.core.config import settings as app_settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient
from app.models.settings import (
    SettingCategory,
    SettingUpdateRequest, SettingsBulkUpdateRequest,
    SettingResponse, SettingsListResponse
)
from prometheus_client import Counter


# =============================================
# Метрики
# =============================================
settings_updated_counter = Counter(
    'autodialer_settings_updated_total',
    'Total settings updated',
    ['key']
)


# =============================================
# Исключения
# =============================================
class SettingsError(Exception):
    """Базовое исключение сервиса настроек"""
    pass


class SettingNotFoundError(SettingsError):
    """Настройка не найдена"""
    pass


class SettingValidationError(SettingsError):
    """Ошибка валидации значения настройки"""
    pass


class SettingReadOnlyError(SettingsError):
    """Попытка изменить настройку только для чтения"""
    pass


# =============================================
# Определения настроек
# =============================================
@dataclass
class SettingDefinition:
    """Определение настройки"""
    key: str
    value_type: str = "string"
    default_value: Any = None
    category: SettingCategory = SettingCategory.GENERAL
    description: str = ""
    is_public: bool = False
    is_readonly: bool = False
    validation_regex: Optional[str] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    allowed_values: Optional[List[Any]] = None
    requires_restart: bool = False
    on_change: Optional[str] = None  # callback функция
    tags: List[str] = field(default_factory=list)


# Предопределённые настройки системы
SYSTEM_SETTINGS: Dict[str, SettingDefinition] = {
    # Общие настройки
    "system.name": SettingDefinition(
        key="system.name",
        value_type="string",
        default_value="AutoDialer Ultimate",
        category=SettingCategory.GENERAL,
        description="Название системы",
        is_public=True
    ),
    "system.timezone": SettingDefinition(
        key="system.timezone",
        value_type="string",
        default_value="UTC",
        category=SettingCategory.GENERAL,
        description="Часовой пояс",
        allowed_values=["UTC", "Europe/Moscow", "Europe/London", "America/New_York"]
    ),
    "system.language": SettingDefinition(
        key="system.language",
        value_type="string",
        default_value="ru",
        category=SettingCategory.GENERAL,
        description="Язык интерфейса",
        allowed_values=["ru", "en"]
    ),
    
    # Настройки дозвона
    "dialer.max_calls": SettingDefinition(
        key="dialer.max_calls",
        value_type="int",
        default_value=50,
        category=SettingCategory.DIALER,
        description="Максимальное количество одновременных звонков",
        min_value=1,
        max_value=500,
        on_change="update_dialer_max_calls"
    ),
    "dialer.default_cps": SettingDefinition(
        key="dialer.default_cps",
        value_type="int",
        default_value=5,
        category=SettingCategory.DIALER,
        description="Звонков в секунду по умолчанию",
        min_value=1,
        max_value=100,
        on_change="update_dialer_cps"
    ),
    "dialer.call_timeout": SettingDefinition(
        key="dialer.call_timeout",
        value_type="int",
        default_value=30,
        category=SettingCategory.DIALER,
        description="Таймаут звонка (секунд)",
        min_value=5,
        max_value=300
    ),
    "dialer.max_retries": SettingDefinition(
        key="dialer.max_retries",
        value_type="int",
        default_value=3,
        category=SettingCategory.DIALER,
        description="Максимальное количество повторных попыток",
        min_value=0,
        max_value=10
    ),
    "dialer.caller_id": SettingDefinition(
        key="dialer.caller_id",
        value_type="string",
        default_value="AutoDialer",
        category=SettingCategory.DIALER,
        description="Caller ID по умолчанию"
    ),
    "dialer.adaptive_cps": SettingDefinition(
        key="dialer.adaptive_cps",
        value_type="bool",
        default_value=True,
        category=SettingCategory.DIALER,
        description="Использовать адаптивный CPS"
    ),
    
    # Настройки аудио
    "audio.max_size_mb": SettingDefinition(
        key="audio.max_size_mb",
        value_type="int",
        default_value=10,
        category=SettingCategory.AUDIO,
        description="Максимальный размер аудиофайла (МБ)",
        min_value=1,
        max_value=100
    ),
    "audio.retention_days": SettingDefinition(
        key="audio.retention_days",
        value_type="int",
        default_value=30,
        category=SettingCategory.AUDIO,
        description="Дней хранения аудиофайлов",
        min_value=7,
        max_value=365
    ),
    "audio.allowed_formats": SettingDefinition(
        key="audio.allowed_formats",
        value_type="list",
        default_value=["wav", "mp3", "sln"],
        category=SettingCategory.AUDIO,
        description="Разрешённые форматы аудио"
    ),
    
    # Настройки TTS
    "tts.enabled": SettingDefinition(
        key="tts.enabled",
        value_type="bool",
        default_value=True,
        category=SettingCategory.TTS,
        description="Включить TTS"
    ),
    "tts.default_voice": SettingDefinition(
        key="tts.default_voice",
        value_type="string",
        default_value="denis",
        category=SettingCategory.TTS,
        description="Голос TTS по умолчанию",
        allowed_values=["denis", "irina", "ruslan", "daria"]
    ),
    "tts.default_model": SettingDefinition(
        key="tts.default_model",
        value_type="string",
        default_value="medium",
        category=SettingCategory.TTS,
        description="Модель TTS по умолчанию",
        allowed_values=["tiny", "base", "small", "medium", "large"]
    ),
    "tts.speed": SettingDefinition(
        key="tts.speed",
        value_type="float",
        default_value=1.0,
        category=SettingCategory.TTS,
        description="Скорость речи",
        min_value=0.5,
        max_value=2.0
    ),
    "tts.concurrent_limit": SettingDefinition(
        key="tts.concurrent_limit",
        value_type="int",
        default_value=2,
        category=SettingCategory.TTS,
        description="Максимум одновременных генераций TTS",
        min_value=1,
        max_value=10
    ),
    
    # Настройки транскрибации
    "transcription.enabled": SettingDefinition(
        key="transcription.enabled",
        value_type="bool",
        default_value=True,
        category=SettingCategory.TRANSCRIPTION,
        description="Включить транскрибацию"
    ),
    "transcription.engine": SettingDefinition(
        key="transcription.engine",
        value_type="string",
        default_value="auto",
        category=SettingCategory.TRANSCRIPTION,
        description="Движок транскрибации",
        allowed_values=["auto", "whisper", "vosk", "google", "none"]
    ),
    "transcription.whisper_model": SettingDefinition(
        key="transcription.whisper_model",
        value_type="string",
        default_value="small",
        category=SettingCategory.TRANSCRIPTION,
        description="Модель Whisper",
        allowed_values=["tiny", "base", "small", "medium", "large"]
    ),
    "transcription.language": SettingDefinition(
        key="transcription.language",
        value_type="string",
        default_value="ru",
        category=SettingCategory.TRANSCRIPTION,
        description="Язык транскрибации по умолчанию"
    ),
    "transcription.concurrent_limit": SettingDefinition(
        key="transcription.concurrent_limit",
        value_type="int",
        default_value=1,
        category=SettingCategory.TRANSCRIPTION,
        description="Максимум одновременных транскрибаций",
        min_value=1,
        max_value=4
    ),
    
    # Настройки безопасности
    "security.password_min_length": SettingDefinition(
        key="security.password_min_length",
        value_type="int",
        default_value=8,
        category=SettingCategory.SECURITY,
        description="Минимальная длина пароля",
        min_value=6,
        max_value=32,
        is_readonly=True
    ),
    "security.session_timeout": SettingDefinition(
        key="security.session_timeout",
        value_type="int",
        default_value=3600,
        category=SettingCategory.SECURITY,
        description="Таймаут сессии (секунд)",
        min_value=300,
        max_value=86400
    ),
    "security.max_login_attempts": SettingDefinition(
        key="security.max_login_attempts",
        value_type="int",
        default_value=5,
        category=SettingCategory.SECURITY,
        description="Максимум попыток входа",
        min_value=3,
        max_value=10
    ),
    "security.block_duration": SettingDefinition(
        key="security.block_duration",
        value_type="int",
        default_value=300,
        category=SettingCategory.SECURITY,
        description="Длительность блокировки (секунд)",
        min_value=60,
        max_value=3600
    ),
    "security.totp_enabled": SettingDefinition(
        key="security.totp_enabled",
        value_type="bool",
        default_value=False,
        category=SettingCategory.SECURITY,
        description="Разрешить двухфакторную аутентификацию"
    ),
    
    # Настройки уведомлений
    "notifications.email_enabled": SettingDefinition(
        key="notifications.email_enabled",
        value_type="bool",
        default_value=False,
        category=SettingCategory.NOTIFICATIONS,
        description="Включить email уведомления"
    ),
    "notifications.smtp_host": SettingDefinition(
        key="notifications.smtp_host",
        value_type="string",
        default_value="",
        category=SettingCategory.NOTIFICATIONS,
        description="SMTP хост"
    ),
    "notifications.smtp_port": SettingDefinition(
        key="notifications.smtp_port",
        value_type="int",
        default_value=587,
        category=SettingCategory.NOTIFICATIONS,
        min_value=1,
        max_value=65535
    ),
    "notifications.smtp_username": SettingDefinition(
        key="notifications.smtp_username",
        value_type="string",
        default_value="",
        category=SettingCategory.NOTIFICATIONS
    ),
    "notifications.smtp_password": SettingDefinition(
        key="notifications.smtp_password",
        value_type="string",
        default_value="",
        category=SettingCategory.NOTIFICATIONS,
        is_public=False
    ),
    "notifications.from_email": SettingDefinition(
        key="notifications.from_email",
        value_type="string",
        default_value="noreply@autodialer.local",
        category=SettingCategory.NOTIFICATIONS
    ),
    
    # Настройки API
    "api.rate_limit_enabled": SettingDefinition(
        key="api.rate_limit_enabled",
        value_type="bool",
        default_value=True,
        category=SettingCategory.API,
        description="Включить ограничение частоты запросов"
    ),
    "api.rate_limit_requests": SettingDefinition(
        key="api.rate_limit_requests",
        value_type="int",
        default_value=100,
        category=SettingCategory.API,
        description="Максимум запросов в минуту",
        min_value=10,
        max_value=1000
    ),
    "api.cors_origins": SettingDefinition(
        key="api.cors_origins",
        value_type="list",
        default_value=["*"],
        category=SettingCategory.API,
        description="Разрешённые CORS origins"
    ),
    
    # Настройки логирования
    "logging.level": SettingDefinition(
        key="logging.level",
        value_type="string",
        default_value="INFO",
        category=SettingCategory.LOGGING,
        description="Уровень логирования",
        allowed_values=["TRACE", "DEBUG", "INFO", "AUDIT", "WARNING", "ERROR", "CRITICAL"],
        on_change="update_log_level"
    ),
    "logging.format": SettingDefinition(
        key="logging.format",
        value_type="string",
        default_value="console",
        category=SettingCategory.LOGGING,
        description="Формат логов",
        allowed_values=["console", "json"]
    ),
    "logging.retention_days": SettingDefinition(
        key="logging.retention_days",
        value_type="int",
        default_value=30,
        category=SettingCategory.LOGGING,
        description="Дней хранения логов",
        min_value=7,
        max_value=365
    ),
}


# =============================================
# Сервис настроек
# =============================================
class SettingsService:
    """
    Сервис управления настройками.
    
    Отвечает за:
    - Получение и обновление настроек
    - Валидацию значений
    - Кеширование
    - Применение изменений
    """
    
    def __init__(
        self,
        db_pool: ConnectionPool,
        redis_client: RedisClient,
        dialer_manager=None,
        system_service=None
    ):
        self.db_pool = db_pool
        self.redis = redis_client
        self.dialer_manager = dialer_manager
        self.system_service = system_service
        
        # Кеш настроек
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 300  # 5 минут
        
        # Колбеки для применения изменений
        self._change_callbacks = {
            "update_dialer_max_calls": self._apply_dialer_max_calls,
            "update_dialer_cps": self._apply_dialer_cps,
            "update_log_level": self._apply_log_level,
        }
        
        logger.info("SettingsService инициализирован")
    
    # =============================================
    # Получение настроек
    # =============================================
    async def get_settings(self, include_private: bool = False) -> Dict[str, Any]:
        """
        Получить все настройки.
        
        Args:
            include_private: Включать приватные настройки
        
        Returns:
            Словарь настроек
        """
        result = {}
        
        for key, definition in SYSTEM_SETTINGS.items():
            if not include_private and not definition.is_public:
                continue
            
            value = await self.get_setting_value(key)
            result[key] = {
                "value": value,
                "description": definition.description,
                "category": definition.category.value,
                "is_public": definition.is_public,
                "is_readonly": definition.is_readonly
            }
        
        return result
    
    async def get_setting_value(self, key: str) -> Any:
        """
        Получить значение настройки.
        
        Args:
            key: Ключ настройки
        
        Returns:
            Значение настройки
        """
        # Проверяем кеш
        cache_key = f"setting:{key}"
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)
        
        definition = SYSTEM_SETTINGS.get(key)
        if not definition:
            raise SettingNotFoundError(f"Настройка {key} не найдена")
        
        # Получаем из БД
        async with self.db_pool.acquire() as conn:
            db_value = await conn.fetchval("""
                SELECT value FROM settings WHERE key = $1
            """, key)
        
        if db_value is not None:
            value = self._parse_value(db_value, definition.value_type)
        else:
            value = definition.default_value
        
        # Кешируем
        await self.redis.setex(cache_key, self._cache_ttl, json.dumps(value))
        
        return value
    
    async def get_setting(self, key: str) -> SettingResponse:
        """
        Получить настройку с метаданными.
        
        Args:
            key: Ключ настройки
        
        Returns:
            SettingResponse
        """
        definition = SYSTEM_SETTINGS.get(key)
        if not definition:
            raise SettingNotFoundError(f"Настройка {key} не найдена")
        
        value = await self.get_setting_value(key)
        
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT s.updated_at, s.updated_by, u.username as updated_by_name
                FROM settings s
                LEFT JOIN users u ON s.updated_by = u.id
                WHERE s.key = $1
            """, key)
        
        return SettingResponse(
            key=key,
            value=str(value),
            description=definition.description,
            category=definition.category.value,
            updated_at=row['updated_at'] if row else None,
            updated_by=row['updated_by_name'] if row else None
        )
    
    async def get_settings_by_category(
        self,
        category: str,
        include_private: bool = False
    ) -> Dict[str, Any]:
        """
        Получить настройки по категории.
        
        Args:
            category: Категория
            include_private: Включать приватные
        
        Returns:
            Словарь настроек
        """
        result = {}
        
        for key, definition in SYSTEM_SETTINGS.items():
            if definition.category.value != category:
                continue
            
            if not include_private and not definition.is_public:
                continue
            
            value = await self.get_setting_value(key)
            result[key] = {
                "value": value,
                "description": definition.description,
                "is_public": definition.is_public,
                "is_readonly": definition.is_readonly
            }
        
        return result
    
    async def get_categories(self) -> List[Dict[str, Any]]:
        """Получить список категорий"""
        categories = {}
        
        for definition in SYSTEM_SETTINGS.values():
            cat = definition.category.value
            if cat not in categories:
                categories[cat] = {
                    "name": cat,
                    "description": self._get_category_description(definition.category),
                    "count": 0
                }
            categories[cat]["count"] += 1
        
        return list(categories.values())
    
    # =============================================
    # Обновление настроек
    # =============================================
    async def update_setting(
        self,
        key: str,
        value: str,
        user_id: Optional[int] = None
    ) -> SettingResponse:
        """
        Обновить настройку.
        
        Args:
            key: Ключ настройки
            value: Новое значение
            user_id: ID пользователя
        
        Returns:
            Обновлённая настройка
        """
        definition = SYSTEM_SETTINGS.get(key)
        if not definition:
            raise SettingNotFoundError(f"Настройка {key} не найдена")
        
        if definition.is_readonly:
            raise SettingReadOnlyError(f"Настройка {key} только для чтения")
        
        # Валидируем значение
        parsed_value = self._validate_and_parse(value, definition)
        
        # Сохраняем в БД
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_by, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
            """, key, str(parsed_value), user_id)
            
            # Логируем
            await self._log_audit(conn, user_id, 'setting_updated', 'setting', None, {
                'key': key,
                'value': str(parsed_value)
            })
        
        # Инвалидируем кеш
        await self.redis.delete(f"setting:{key}")
        
        # Применяем изменения если нужно
        if definition.on_change and definition.on_change in self._change_callbacks:
            try:
                await self._change_callbacks[definition.on_change](parsed_value)
            except Exception as e:
                logger.error(f"Ошибка применения настройки {key}: {e}")
        
        settings_updated_counter.labels(key=key).inc()
        
        logger.info(f"Настройка {key} обновлена: {value}")
        
        return await self.get_setting(key)
    
    async def bulk_update_settings(
        self,
        settings: Dict[str, str],
        user_id: Optional[int] = None
    ) -> SettingsListResponse:
        """
        Массовое обновление настроек.
        
        Args:
            settings: Словарь ключ-значение
            user_id: ID пользователя
        
        Returns:
            Список обновлённых настроек
        """
        updated = []
        errors = []
        
        for key, value in settings.items():
            try:
                result = await self.update_setting(key, value, user_id)
                updated.append(result)
            except Exception as e:
                errors.append({"key": key, "error": str(e)})
        
        logger.info(f"Массовое обновление настроек: {len(updated)} обновлено, {len(errors)} ошибок")
        
        return SettingsListResponse(
            items=updated,
            total=len(updated),
            errors=errors
        )
    
    # =============================================
    # Валидация
    # =============================================
    def _validate_and_parse(self, value: str, definition: SettingDefinition) -> Any:
        """
        Валидировать и распарсить значение.
        
        Args:
            value: Строковое значение
            definition: Определение настройки
        
        Returns:
            Распарсенное значение
        """
        try:
            if definition.value_type == "string":
                parsed = value
                if definition.allowed_values and parsed not in definition.allowed_values:
                    raise SettingValidationError(
                        f"Значение должно быть одним из: {', '.join(map(str, definition.allowed_values))}"
                    )
                
            elif definition.value_type == "int":
                parsed = int(value)
                if definition.min_value is not None and parsed < definition.min_value:
                    raise SettingValidationError(f"Значение должно быть не менее {definition.min_value}")
                if definition.max_value is not None and parsed > definition.max_value:
                    raise SettingValidationError(f"Значение должно быть не более {definition.max_value}")
                
            elif definition.value_type == "float":
                parsed = float(value)
                if definition.min_value is not None and parsed < definition.min_value:
                    raise SettingValidationError(f"Значение должно быть не менее {definition.min_value}")
                if definition.max_value is not None and parsed > definition.max_value:
                    raise SettingValidationError(f"Значение должно быть не более {definition.max_value}")
                
            elif definition.value_type == "bool":
                parsed = value.lower() in ("true", "1", "yes", "on")
                
            elif definition.value_type == "list":
                parsed = json.loads(value) if value.startswith("[") else [v.strip() for v in value.split(",")]
                if not isinstance(parsed, list):
                    raise SettingValidationError("Значение должно быть списком")
                
            else:
                parsed = value
            
            # Проверка регулярным выражением
            if definition.validation_regex:
                import re
                if not re.match(definition.validation_regex, str(parsed)):
                    raise SettingValidationError("Значение не соответствует формату")
            
            return parsed
            
        except ValueError as e:
            raise SettingValidationError(f"Неверный формат значения: {e}")
    
    def _parse_value(self, value: str, value_type: str) -> Any:
        """Распарсить значение из БД"""
        try:
            if value_type == "int":
                return int(value)
            elif value_type == "float":
                return float(value)
            elif value_type == "bool":
                return value.lower() in ("true", "1", "yes", "on")
            elif value_type == "list":
                return json.loads(value) if value.startswith("[") else []
            else:
                return value
        except (ValueError, json.JSONDecodeError):
            return value
    
    def _get_category_description(self, category: SettingCategory) -> str:
        """Получить описание категории"""
        descriptions = {
            SettingCategory.GENERAL: "Общие настройки системы",
            SettingCategory.DIALER: "Настройки дозвона",
            SettingCategory.AUDIO: "Настройки аудиофайлов",
            SettingCategory.TTS: "Настройки синтеза речи",
            SettingCategory.TRANSCRIPTION: "Настройки транскрибации",
            SettingCategory.SECURITY: "Настройки безопасности",
            SettingCategory.NOTIFICATIONS: "Настройки уведомлений",
            SettingCategory.API: "Настройки API",
            SettingCategory.LOGGING: "Настройки логирования",
        }
        return descriptions.get(category, "")
    
    # =============================================
    # Применение изменений
    # =============================================
    async def _apply_dialer_max_calls(self, value: int) -> None:
        """Применить изменение max_calls"""
        if self.dialer_manager:
            self.dialer_manager.max_calls = value
            logger.info(f"Dialer max_calls обновлён: {value}")
    
    async def _apply_dialer_cps(self, value: int) -> None:
        """Применить изменение CPS"""
        if self.dialer_manager:
            self.dialer_manager.cps_limiter.update_rate(value)
            logger.info(f"Dialer CPS обновлён: {value}")
    
    async def _apply_log_level(self, value: str) -> None:
        """Применить изменение уровня логирования"""
        if self.system_service:
            from app.models.system import LogLevel
            await self.system_service.set_log_level(LogLevel(value))
    
    # =============================================
    # Экспорт/Импорт
    # =============================================
    async def export_settings(self) -> Dict[str, Any]:
        """Экспортировать все настройки"""
        settings = {}
        
        for key in SYSTEM_SETTINGS.keys():
            value = await self.get_setting_value(key)
            settings[key] = value
        
        return {
            "version": app_settings.VERSION,
            "exported_at": datetime.utcnow().isoformat(),
            "settings": settings
        }
    
    async def import_settings(
        self,
        data: Dict[str, Any],
        user_id: Optional[int] = None,
        overwrite: bool = True
    ) -> Dict[str, Any]:
        """
        Импортировать настройки.
        
        Args:
            data: Данные для импорта
            user_id: ID пользователя
            overwrite: Перезаписывать существующие
        
        Returns:
            Результат импорта
        """
        settings = data.get("settings", {})
        
        imported = 0
        skipped = 0
        errors = []
        
        for key, value in settings.items():
            if key not in SYSTEM_SETTINGS:
                skipped += 1
                continue
            
            try:
                if overwrite:
                    await self.update_setting(key, str(value), user_id)
                    imported += 1
                else:
                    # Проверяем существование
                    existing = await self.get_setting_value(key)
                    definition = SYSTEM_SETTINGS[key]
                    if existing == definition.default_value:
                        await self.update_setting(key, str(value), user_id)
                        imported += 1
                    else:
                        skipped += 1
            except Exception as e:
                errors.append({"key": key, "error": str(e)})
        
        logger.info(f"Импорт настроек: {imported} импортировано, {skipped} пропущено")
        
        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors
        }
    
    # =============================================
    # Сброс настроек
    # =============================================
    async def reset_setting(
        self,
        key: str,
        user_id: Optional[int] = None
    ) -> SettingResponse:
        """
        Сбросить настройку к значению по умолчанию.
        
        Args:
            key: Ключ настройки
            user_id: ID пользователя
        
        Returns:
            Обновлённая настройка
        """
        definition = SYSTEM_SETTINGS.get(key)
        if not definition:
            raise SettingNotFoundError(f"Настройка {key} не найдена")
        
        return await self.update_setting(key, str(definition.default_value), user_id)
    
    async def reset_category(
        self,
        category: str,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Сбросить все настройки категории.
        
        Args:
            category: Категория
            user_id: ID пользователя
        
        Returns:
            Результат сброса
        """
        reset_count = 0
        errors = []
        
        for key, definition in SYSTEM_SETTINGS.items():
            if definition.category.value != category:
                continue
            
            try:
                await self.update_setting(key, str(definition.default_value), user_id)
                reset_count += 1
            except Exception as e:
                errors.append({"key": key, "error": str(e)})
        
        return {
            "category": category,
            "reset": reset_count,
            "errors": errors
        }
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _log_audit(
        self,
        conn,
        user_id: Optional[int],
        action: str,
        entity_type: str,
        entity_id: Optional[int],
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Записать аудит"""
        import json
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, action, entity_type, entity_id, json.dumps(details) if details else None)
    
    # =============================================
    # Инициализация
    # =============================================
    async def initialize_defaults(self) -> int:
        """
        Инициализировать настройки значениями по умолчанию.
        Вызывается при первом запуске.
        
        Returns:
            Количество созданных настроек
        """
        created = 0
        
        async with self.db_pool.acquire() as conn:
            for key, definition in SYSTEM_SETTINGS.items():
                existing = await conn.fetchval("""
                    SELECT 1 FROM settings WHERE key = $1
                """, key)
                
                if not existing:
                    await conn.execute("""
                        INSERT INTO settings (key, value, created_at, updated_at)
                        VALUES ($1, $2, NOW(), NOW())
                    """, key, str(definition.default_value))
                    created += 1
        
        if created > 0:
            logger.info(f"Инициализировано {created} настроек по умолчанию")
        
        return created
    
    async def reload_cache(self) -> None:
        """Перезагрузить кеш настроек"""
        pattern = "setting:*"
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break
        
        logger.info("Кеш настроек очищен")
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            return {
                "status": "healthy",
                "settings_count": len(SYSTEM_SETTINGS)
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        logger.info("SettingsService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_settings_service: Optional[SettingsService] = None


def get_settings_service() -> SettingsService:
    """Получить глобальный экземпляр SettingsService"""
    global _settings_service
    if _settings_service is None:
        raise RuntimeError("SettingsService не инициализирован")
    return _settings_service


def set_settings_service(service: SettingsService) -> None:
    """Установить глобальный экземпляр SettingsService"""
    global _settings_service
    _settings_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "SettingsService",
    "SettingsError",
    "SettingNotFoundError",
    "SettingValidationError",
    "SettingReadOnlyError",
    "SettingDefinition",
    "SYSTEM_SETTINGS",
    "get_settings_service",
    "set_settings_service",
]
