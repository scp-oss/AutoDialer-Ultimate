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
    
    # Подключение к Asterisk/FreePBX (AMI) - параметры соединения, которое
    # AutoDialer открывает к серверу Asterisk/FreePBX для управления
    # звонками. Это НЕ настройка SIP-транков/провайдеров - те настраиваются
    # в самой FreePBX. Читаются AMI-клиентом только при подключении, поэтому
    # requires_restart=True: сохранение значения не переподключает AMI само
    # по себе, нужен перезапуск сервиса (см. кнопку "Перезагрузить сервисы").
    "asterisk.ami_host": SettingDefinition(
        key="asterisk.ami_host",
        value_type="string",
        default_value=app_settings.AMI_HOST,
        category=SettingCategory.ASTERISK,
        description="Хост AMI (адрес сервера Asterisk/FreePBX)",
        requires_restart=True
    ),
    "asterisk.ami_port": SettingDefinition(
        key="asterisk.ami_port",
        value_type="int",
        default_value=app_settings.AMI_PORT,
        category=SettingCategory.ASTERISK,
        description="Порт AMI",
        min_value=1,
        max_value=65535,
        requires_restart=True
    ),
    "asterisk.ami_user": SettingDefinition(
        key="asterisk.ami_user",
        value_type="string",
        default_value=app_settings.AMI_USER,
        category=SettingCategory.ASTERISK,
        description="Имя пользователя AMI (manager.conf на стороне Asterisk)",
        requires_restart=True
    ),
    "asterisk.ami_password": SettingDefinition(
        key="asterisk.ami_password",
        value_type="string",
        default_value=app_settings.AMI_PASSWORD,
        category=SettingCategory.ASTERISK,
        description="Пароль AMI",
        is_public=False,
        requires_restart=True
    ),

    # Настройки входящих звонков - приветствие, которое проигрывается перед
    # записью (см. app/api/incoming.py: GET /incoming/greeting и
    # /incoming/greeting/audio). Само проигрывание выполняет дialplan на
    # стороне FreePBX - эти настройки только говорят ему, ЧТО играть.
    # on_change="update_incoming_greeting" на обоих: раньше эти два ключа
    # писались в БД, но ничего в дialplan'е их не читало - [incoming] в
    # asterisk/asterisk.conf проверял ${GLOBAL(INCOMING_GREETING)}, который
    # никогда и нигде не устанавливался (ни здесь, ни через AMI Setvar), так
    # что выбор приветствия в веб-интерфейсе не влиял на реальный звонок на
    # свой собственный extension - только на отдельный HTTP-эндпоинт
    # /incoming/greeting(/audio), рассчитанный на то, что его дёргает
    # дialplan НА СТОРОНЕ FreePBX. on_change симлинкует выбранный файл под
    # tts/incoming_custom.sln - тем же приёмом, что campaign.py делает для
    # tts/main_<id>.sln (_link_campaign_audio) - a [incoming] теперь
    # проверяет его существование через STAT(), как и остальные контексты.
    "incoming.greeting_enabled": SettingDefinition(
        key="incoming.greeting_enabled",
        value_type="bool",
        default_value=False,
        category=SettingCategory.INCOMING,
        description="Проигрывать приветствие перед записью входящего звонка",
        on_change="update_incoming_greeting"
    ),
    # value_type="string" (not "int") on purpose: settings.js's select
    # renderer compares `value === opt.value` (strict equality) between the
    # raw setting value and the string option values built in
    # _render_metadata() below - an int value would never strict-equal a
    # string option and the dropdown would never show a selection.
    "incoming.greeting_audio_id": SettingDefinition(
        key="incoming.greeting_audio_id",
        value_type="string",
        default_value="0",
        category=SettingCategory.INCOMING,
        description="Аудио из библиотеки (вкладка «Аудио»), которое проигрывается как приветствие",
        on_change="update_incoming_greeting"
    ),

    # Настройки дозвона
    # requires_restart=True на всех пяти: с WORKERS>1 каждый gunicorn-воркер
    # держит собственный DialerManager с собственным AMI-соединением и
    # собственным self.max_calls/caller_id/... в памяти (см. комментарий в
    # app/__init__.py, lifespan, шаг 5.5). on_change применяет новое
    # значение живьём только к тому ОДНОМУ воркеру, который обработал
    # именно этот HTTP-запрос - без рестарта остальные воркеры продолжают
    # дозванивать по старому значению.
    "dialer.max_calls": SettingDefinition(
        key="dialer.max_calls",
        value_type="int",
        default_value=50,
        category=SettingCategory.DIALER,
        description="Максимальное количество одновременных звонков",
        min_value=1,
        max_value=500,
        on_change="update_dialer_max_calls",
        requires_restart=True
    ),
    "dialer.default_cps": SettingDefinition(
        key="dialer.default_cps",
        value_type="int",
        default_value=5,
        category=SettingCategory.DIALER,
        description="Звонков в секунду по умолчанию",
        min_value=1,
        max_value=100,
        on_change="update_dialer_cps",
        requires_restart=True
    ),
    "dialer.call_timeout": SettingDefinition(
        key="dialer.call_timeout",
        value_type="int",
        default_value=30,
        category=SettingCategory.DIALER,
        description="Таймаут звонка (секунд)",
        min_value=5,
        max_value=300,
        requires_restart=True
    ),
    "dialer.max_retries": SettingDefinition(
        key="dialer.max_retries",
        value_type="int",
        default_value=3,
        category=SettingCategory.DIALER,
        description="Максимальное количество повторных попыток",
        min_value=0,
        max_value=10,
        requires_restart=True
    ),
    "dialer.caller_id": SettingDefinition(
        key="dialer.caller_id",
        value_type="string",
        default_value="AutoDialer",
        category=SettingCategory.DIALER,
        description="Caller ID по умолчанию",
        requires_restart=True
    ),
    "dialer.adaptive_cps": SettingDefinition(
        key="dialer.adaptive_cps",
        value_type="bool",
        default_value=True,
        category=SettingCategory.DIALER,
        description="Использовать адаптивный CPS"
    ),
    # Фраза "нажмите 1/2/4", которую [sub-media] проигрывает после питча
    # кампании (см. комментарий у Background(tts/default) в
    # asterisk/extensions.conf) - раньше это была захардкоженная общая
    # фраза "подтвердите/откажитесь" из tts/default.sln, но пользователю
    # нужна была другая формулировка ("нажмите 1, если прослушали, 2 -
    # если нет"). on_change симлинкует выбранный файл под
    # tts/menu_prompt.sln - тем же приёмом, что incoming.greeting_audio_id
    # использует для tts/incoming_custom.sln и campaign.py для
    # tts/main_<id>.sln. Не выбрано - диалплан использует tts/default,
    # как и раньше (проверяется через STAT() тем же способом).
    "dialer.menu_prompt_audio_id": SettingDefinition(
        key="dialer.menu_prompt_audio_id",
        value_type="string",
        default_value="0",
        category=SettingCategory.DIALER,
        description="Аудио из библиотеки (вкладка «Аудио») с фразой «нажмите 1/2/4», проигрывается после питча каждой кампании с включённым DTMF-меню. Не выбрано - используется общая фраза по умолчанию.",
        on_change="update_menu_prompt"
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
            "update_incoming_greeting": self._apply_incoming_greeting,
            "update_menu_prompt": self._apply_menu_prompt,
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
                "is_readonly": definition.is_readonly,
                **await self._render_metadata(definition)
            }

        return result

    async def _render_metadata(self, definition: "SettingDefinition") -> Dict[str, Any]:
        """
        Метаданные для рендера поля во фронтенде (settings.js:
        renderSettingField() / detectType()) - раньше get_settings()/
        get_settings_by_category() отдавали только {value, description,
        category, is_public, is_readonly}, из-за чего фронт был вынужден
        угадывать тип поля по значению (detectType()), а select-настройки
        с allowed_values (voice/model/timezone и т.п.) всегда рендерились
        обычным текстовым полем без вариантов выбора.
        """
        type_map = {"bool": "boolean", "int": "number", "float": "number", "list": "json"}
        ui_type = type_map.get(definition.value_type, "text")

        options = None
        if definition.key in ("incoming.greeting_audio_id", "dialer.menu_prompt_audio_id"):
            # Список вариантов для этого поля не статичен (зависит от
            # содержимого библиотеки аудио), поэтому не хранится в
            # SettingDefinition.allowed_values, а собирается здесь.
            try:
                from app.services import get_audio_service
                audio_service = get_audio_service()
                audio_list = await audio_service.list_audio(page=1, page_size=200)
                options = [{"value": "0", "label": "— не выбрано —"}] + [
                    {"value": str(a.id), "label": a.name} for a in audio_list.items
                ]
                ui_type = "select"
            except Exception as e:
                logger.warning(f"Не удалось загрузить список аудио для {definition.key}: {e}")
        elif definition.allowed_values:
            options = [{"value": str(v), "label": str(v)} for v in definition.allowed_values]
            ui_type = "select"

        return {
            "type": ui_type,
            "min": definition.min_value,
            "max": definition.max_value,
            "options": options,
            "requires_restart": definition.requires_restart
        }
    
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
                "is_readonly": definition.is_readonly,
                **await self._render_metadata(definition)
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
            SettingCategory.ASTERISK: "Подключение к Asterisk/FreePBX (AMI)",
            SettingCategory.DIALER: "Настройки дозвона",
            SettingCategory.AUDIO: "Настройки аудиофайлов",
            SettingCategory.TTS: "Настройки синтеза речи",
            SettingCategory.TRANSCRIPTION: "Настройки транскрибации",
            SettingCategory.SECURITY: "Настройки безопасности",
            SettingCategory.NOTIFICATIONS: "Настройки уведомлений",
            SettingCategory.INCOMING: "Входящие звонки (приветствие)",
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

    async def _apply_incoming_greeting(self, value) -> None:
        """
        Симлинкует выбранное в веб-интерфейсе аудио под tts/incoming_custom.sln -
        [incoming] в asterisk/asterisk.conf проверяет наличие именно этого
        файла через STAT() (тот же приём, что campaign.py::_link_campaign_audio
        использует для tts/main_<id>.sln). value здесь не используется - оба
        ключа (greeting_enabled/greeting_audio_id) вызывают этот же колбек, а
        нужное действие зависит от актуального состояния ОБОИХ сразу, а не
        только того, который только что изменился.
        """
        from pathlib import Path

        enabled = await self.get_setting_value("incoming.greeting_enabled")
        audio_id_raw = await self.get_setting_value("incoming.greeting_audio_id")

        target = app_settings.TTS_DIR / "incoming_custom.sln"
        source: Optional[Path] = None

        try:
            audio_id = int(audio_id_raw) if audio_id_raw else None
        except (TypeError, ValueError):
            audio_id = None

        if enabled and audio_id:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT file_path FROM audio_files WHERE id = $1",
                    audio_id
                )
            if row and row['file_path']:
                candidate = Path(row['file_path'])
                if candidate.exists():
                    source = candidate
                else:
                    logger.warning(
                        f"Приветствие входящих: аудиофайл audio_id={audio_id} "
                        f"не найден на диске ({candidate})"
                    )

        try:
            if target.is_symlink() or target.exists():
                target.unlink()
            if source:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source)
                logger.info(f"Приветствие входящих звонков обновлено: {source}")
            else:
                logger.info(
                    "Приветствие входящих звонков отключено или не выбрано - "
                    "используется tts/incoming_welcome по умолчанию"
                )
        except OSError as e:
            logger.error(f"Не удалось обновить приветствие входящих звонков ({target}): {e}")

    async def _apply_menu_prompt(self, value) -> None:
        """
        Симлинкует выбранное в веб-интерфейсе аудио под tts/menu_prompt.sln -
        [sub-media] в asterisk/extensions.conf проверяет его наличие через
        STAT() и играет его вместо общей tts/default.sln после питча
        кампании, когда DTMF-меню включено (тот же приём, что
        _apply_incoming_greeting выше использует для
        tts/incoming_custom.sln).
        """
        from pathlib import Path

        audio_id_raw = value if value is not None else await self.get_setting_value("dialer.menu_prompt_audio_id")

        target = app_settings.TTS_DIR / "menu_prompt.sln"
        source: Optional[Path] = None

        try:
            audio_id = int(audio_id_raw) if audio_id_raw else None
        except (TypeError, ValueError):
            audio_id = None

        if audio_id:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT file_path FROM audio_files WHERE id = $1",
                    audio_id
                )
            if row and row['file_path']:
                candidate = Path(row['file_path'])
                if candidate.exists():
                    source = candidate
                else:
                    logger.warning(
                        f"Фраза DTMF-меню: аудиофайл audio_id={audio_id} "
                        f"не найден на диске ({candidate})"
                    )

        try:
            if target.is_symlink() or target.exists():
                target.unlink()
            if source:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source)
                logger.info(f"Фраза DTMF-меню обновлена: {source}")
            else:
                logger.info(
                    "Фраза DTMF-меню не выбрана - используется tts/default по умолчанию"
                )
        except OSError as e:
            logger.error(f"Не удалось обновить фразу DTMF-меню ({target}): {e}")

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

    async def reset_all_settings(
        self,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Сбросить ВСЕ настройки к значениям по умолчанию.

        Args:
            user_id: ID пользователя

        Returns:
            Результат сброса
        """
        reset_count = 0
        errors = []

        for key, definition in SYSTEM_SETTINGS.items():
            try:
                await self.update_setting(key, str(definition.default_value), user_id)
                reset_count += 1
            except Exception as e:
                errors.append({"key": key, "error": str(e)})

        return {
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
