#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели аудиофайлов и TTS
AutoDialer Ultimate v3.0.0

Предоставляет Pydantic схемы для:
- Загрузки и управления аудиофайлами
- Генерации речи (TTS)
- Конвертации аудиоформатов
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, model_validator

from app.models.common import BaseSchema, TimestampSchema


# =============================================
# Enums
# =============================================
class AudioFormat(str, Enum):
    """Формат аудиофайла"""
    SLN = "sln"       # Asterisk SLN (8kHz, 16-bit, mono)
    WAV = "wav"       # Wave
    MP3 = "mp3"       # MP3
    GSM = "gsm"       # GSM
    ULAW = "ulaw"     # μ-law
    ALAW = "alaw"     # A-law
    OGG = "ogg"       # Ogg Vorbis


class AudioStatus(str, Enum):
    """Статус аудиофайла"""
    UPLOADING = "uploading"       # Загружается
    PROCESSING = "processing"     # Обрабатывается
    READY = "ready"               # Готов к использованию
    ERROR = "error"               # Ошибка
    DELETED = "deleted"           # Удалён


class TTSVoice(str, Enum):
    """Голоса для TTS (Piper)"""
    DENIS = "denis"         # Денис (мужской, русский)
    IRINA = "irina"         # Ирина (женский, русский)
    RUSLAN = "ruslan"       # Руслан (мужской, русский)
    DARIA = "daria"         # Дарья (женский, русский)
    
    # Английские голоса
    ALAN = "alan"           # Alan (male, English)
    JENNY = "jenny"         # Jenny (female, English)
    
    # Немецкие
    THORSTEN = "thorsten"   # Thorsten (male, German)


class TTSModel(str, Enum):
    """Модели TTS"""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


# =============================================
# Метаданные аудио
# =============================================
class AudioMetadata(BaseSchema):
    """
    Метаданные аудиофайла.
    """
    duration: Optional[float] = Field(None, description="Длительность (сек)")
    sample_rate: Optional[int] = Field(None, description="Частота дискретизации (Гц)")
    channels: Optional[int] = Field(None, description="Количество каналов")
    bitrate: Optional[int] = Field(None, description="Битрейт (кбит/с)")
    codec: Optional[str] = Field(None, description="Кодек")
    file_size: Optional[int] = Field(None, description="Размер файла (байт)")
    
    # TTS метаданные
    tts_text: Optional[str] = Field(None, description="Исходный текст для TTS")
    tts_voice: Optional[TTSVoice] = Field(None, description="Голос TTS")
    tts_model: Optional[TTSModel] = Field(None, description="Модель TTS")
    tts_speed: Optional[float] = Field(None, description="Скорость речи")


# =============================================
# Запросы
# =============================================
class AudioGenerateRequest(BaseSchema):
    """
    Запрос на генерацию аудио через TTS.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название файла")
    text: str = Field(..., min_length=10, max_length=1000, description="Текст для озвучивания")
    
    voice: TTSVoice = Field(TTSVoice.DENIS, description="Голос")
    model: TTSModel = Field(TTSModel.MEDIUM, description="Модель")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Скорость речи")
    
    output_format: AudioFormat = Field(AudioFormat.SLN, description="Выходной формат")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    is_public: bool = Field(False, description="Публичный файл")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Очистка названия"""
        return v.strip()
    
    @field_validator('text')
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Очистка текста"""
        # Удаляем множественные пробелы
        import re
        v = re.sub(r'\s+', ' ', v.strip())
        
        # Проверка на недопустимые символы
        if re.search(r'[<>]', v):
            raise ValueError("Текст содержит недопустимые символы")
        
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Приветствие",
                "text": "Здравствуйте! Это компания АвтоДайлер. У нас есть для вас специальное предложение.",
                "voice": "denis",
                "model": "medium",
                "speed": 1.0,
                "output_format": "sln",
                "campaign_id": 1,
                "is_public": False,
                "description": "Основное приветствие кампании"
            }
        }
    }


class AudioUploadRequest(BaseSchema):
    """
    Запрос на загрузку аудиофайла.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Название файла")
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    is_public: bool = Field(False, description="Публичный файл")
    
    convert_to: Optional[AudioFormat] = Field(AudioFormat.SLN, description="Конвертировать в формат")
    
    tags: List[str] = Field(default_factory=list, description="Теги")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return v.strip()


class AudioUpdateRequest(BaseSchema):
    """
    Запрос на обновление аудиофайла.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название")
    description: Optional[str] = Field(None, max_length=500, description="Описание")
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    is_public: Optional[bool] = Field(None, description="Публичный файл")
    tags: Optional[List[str]] = Field(None, description="Теги")


class AudioConvertRequest(BaseSchema):
    """
    Запрос на конвертацию аудиофайла.
    """
    target_format: AudioFormat = Field(..., description="Целевой формат")
    sample_rate: Optional[int] = Field(8000, description="Частота дискретизации")
    channels: Optional[int] = Field(1, ge=1, le=2, description="Количество каналов")
    bitrate: Optional[int] = Field(None, description="Битрейт")


# =============================================
# Ответы
# =============================================
class AudioResponse(BaseSchema, TimestampSchema):
    """
    Ответ с информацией об аудиофайле.
    """
    id: int = Field(..., description="ID файла")
    name: str = Field(..., description="Название")
    description: Optional[str] = Field(None, description="Описание")
    
    file_path: str = Field(..., description="Путь к файлу")
    file_name: str = Field(..., description="Имя файла")
    
    format: AudioFormat = Field(..., description="Формат")
    status: AudioStatus = Field(AudioStatus.READY, description="Статус")
    
    file_size: Optional[int] = Field(None, description="Размер (байт)")
    file_size_human: Optional[str] = Field(None, description="Размер (человеко-читаемый)")
    
    duration: Optional[float] = Field(None, description="Длительность (сек)")
    duration_formatted: Optional[str] = Field(None, description="Длительность (ММ:СС)")
    
    metadata: AudioMetadata = Field(default_factory=AudioMetadata, description="Метаданные")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    campaign_name: Optional[str] = Field(None, description="Название кампании")
    
    is_public: bool = Field(False, description="Публичный")
    tags: List[str] = Field(default_factory=list, description="Теги")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_by_name: Optional[str] = Field(None, description="Имя создателя")
    
    download_url: Optional[str] = Field(None, description="URL для скачивания")
    stream_url: Optional[str] = Field(None, description="URL для прослушивания")
    
    usage_count: int = Field(0, description="Использований")
    last_used_at: Optional[datetime] = Field(None, description="Последнее использование")
    
    @model_validator(mode='after')
    def format_fields(self) -> 'AudioResponse':
        """Форматирование полей"""
        # Форматирование размера
        if self.file_size:
            if self.file_size < 1024:
                self.file_size_human = f"{self.file_size} B"
            elif self.file_size < 1024 * 1024:
                self.file_size_human = f"{self.file_size / 1024:.1f} KB"
            else:
                self.file_size_human = f"{self.file_size / (1024 * 1024):.2f} MB"
        
        # Форматирование длительности
        if self.duration:
            minutes = int(self.duration // 60)
            seconds = int(self.duration % 60)
            self.duration_formatted = f"{minutes:02d}:{seconds:02d}"
        
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "Приветствие",
                "description": "Основное приветствие",
                "file_path": "/var/lib/asterisk/sounds/tts/greeting.sln",
                "file_name": "greeting.sln",
                "format": "sln",
                "status": "ready",
                "file_size": 245760,
                "file_size_human": "240.0 KB",
                "duration": 15.5,
                "duration_formatted": "00:15",
                "metadata": {
                    "duration": 15.5,
                    "sample_rate": 8000,
                    "channels": 1,
                    "tts_text": "Здравствуйте! Это компания...",
                    "tts_voice": "denis"
                },
                "campaign_id": 1,
                "campaign_name": "Тестовая кампания",
                "is_public": False,
                "tags": ["приветствие", "основное"],
                "created_by": 1,
                "created_by_name": "admin",
                "download_url": "/api/audio/1/download",
                "stream_url": "/api/audio/1/stream",
                "usage_count": 42,
                "created_at": "2024-01-01T00:00:00Z"
            }
        }
    }


class AudioDetailResponse(AudioResponse):
    """
    Детальный ответ об аудиофайле.
    """
    # История использования
    usage_history: List[Dict[str, Any]] = Field(default_factory=list, description="История использования")
    
    # Связанные кампании
    related_campaigns: List[Dict[str, Any]] = Field(default_factory=list, description="Связанные кампании")
    
    # Если это TTS - оригинальные настройки
    tts_settings: Optional[Dict[str, Any]] = Field(None, description="Настройки TTS")


class AudioListResponse(BaseSchema):
    """
    Ответ со списком аудиофайлов.
    """
    items: List[AudioResponse] = Field(..., description="Аудиофайлы")
    total: int = Field(..., description="Всего файлов")
    page: int = Field(..., description="Текущая страница")
    page_size: int = Field(..., description="Размер страницы")
    total_pages: int = Field(..., description="Всего страниц")
    
    # Статистика
    total_size: int = Field(0, description="Общий размер (байт)")
    total_duration: float = Field(0.0, description="Общая длительность (сек)")


class AudioGenerateResponse(BaseSchema):
    """
    Ответ на генерацию аудио.
    """
    id: int = Field(..., description="ID созданного файла")
    name: str = Field(..., description="Название")
    file_path: str = Field(..., description="Путь к файлу")
    file_size: int = Field(..., description="Размер (байт)")
    duration: Optional[float] = Field(None, description="Длительность (сек)")
    format: AudioFormat = Field(..., description="Формат")
    
    task_id: Optional[str] = Field(None, description="ID задачи (если асинхронно)")
    status: str = Field("completed", description="Статус генерации")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "Приветствие",
                "file_path": "/var/lib/asterisk/sounds/tts/greeting.sln",
                "file_size": 245760,
                "duration": 15.5,
                "format": "sln",
                "status": "completed"
            }
        }
    }


class AudioUploadResponse(AudioGenerateResponse):
    """
    Ответ на загрузку аудио.
    """
    original_format: str = Field(..., description="Исходный формат")
    converted: bool = Field(False, description="Был ли конвертирован")


class AudioConvertResponse(BaseSchema):
    """
    Ответ на конвертацию аудио.
    """
    id: int = Field(..., description="ID нового файла")
    name: str = Field(..., description="Название")
    file_path: str = Field(..., description="Путь к файлу")
    file_size: int = Field(..., description="Размер (байт)")
    format: AudioFormat = Field(..., description="Формат")
    duration: Optional[float] = Field(None, description="Длительность (сек)")
    
    original_id: int = Field(..., description="ID исходного файла")


# =============================================
# TTS специфичные модели
# =============================================
class TTSInfoResponse(BaseSchema):
    """
    Информация о TTS сервисе.
    """
    enabled: bool = Field(..., description="TTS включён")
    engine: str = Field(..., description="Движок TTS")
    
    available_voices: List[Dict[str, Any]] = Field(default_factory=list, description="Доступные голоса")
    available_models: List[str] = Field(default_factory=list, description="Доступные модели")
    
    max_text_length: int = Field(..., description="Максимальная длина текста")
    supported_formats: List[AudioFormat] = Field(default_factory=list, description="Поддерживаемые форматы")
    
    concurrent_limit: int = Field(..., description="Лимит одновременных генераций")
    current_queue_size: int = Field(0, description="Текущий размер очереди")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "enabled": True,
                "engine": "piper",
                "available_voices": [
                    {"id": "denis", "name": "Денис", "gender": "male", "language": "ru"},
                    {"id": "irina", "name": "Ирина", "gender": "female", "language": "ru"}
                ],
                "available_models": ["tiny", "base", "small", "medium"],
                "max_text_length": 1000,
                "supported_formats": ["sln", "wav"],
                "concurrent_limit": 2,
                "current_queue_size": 0
            }
        }
    }


class TTSPreviewRequest(BaseSchema):
    """
    Запрос на предпрослушивание TTS.
    """
    text: str = Field(..., min_length=1, max_length=200, description="Текст")
    voice: TTSVoice = Field(TTSVoice.DENIS, description="Голос")
    model: TTSModel = Field(TTSModel.MEDIUM, description="Модель")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Скорость")


class TTSPreviewResponse(BaseSchema):
    """
    Ответ с предпрослушиванием TTS.
    """
    audio_url: str = Field(..., description="URL аудио для прослушивания")
    duration: float = Field(..., description="Длительность (сек)")
    expires_at: datetime = Field(..., description="Действителен до")


# =============================================
# Фильтры
# =============================================
class AudioFilterRequest(BaseSchema):
    """
    Запрос на фильтрацию аудиофайлов.
    """
    search: Optional[str] = Field(None, description="Поиск по названию")
    
    format: Optional[List[AudioFormat]] = Field(None, description="Форматы")
    status: Optional[List[AudioStatus]] = Field(None, description="Статусы")
    
    campaign_id: Optional[int] = Field(None, description="ID кампании")
    is_public: Optional[bool] = Field(None, description="Публичные")
    
    created_by: Optional[int] = Field(None, description="ID создателя")
    
    tags: Optional[List[str]] = Field(None, description="Теги (любой из)")
    
    min_duration: Optional[float] = Field(None, description="Мин. длительность")
    max_duration: Optional[float] = Field(None, description="Макс. длительность")
    
    created_after: Optional[datetime] = Field(None, description="Создан после")
    created_before: Optional[datetime] = Field(None, description="Создан до")
    
    sort_by: str = Field("created_at", description="Сортировка")
    sort_order: str = Field("DESC", description="Порядок (ASC/DESC)")


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Enums
    "AudioFormat",
    "AudioStatus",
    "TTSVoice",
    "TTSModel",
    
    # Метаданные
    "AudioMetadata",
    
    # Запросы
    "AudioGenerateRequest",
    "AudioUploadRequest",
    "AudioUpdateRequest",
    "AudioConvertRequest",
    
    # Ответы
    "AudioResponse",
    "AudioDetailResponse",
    "AudioListResponse",
    "AudioGenerateResponse",
    "AudioUploadResponse",
    "AudioConvertResponse",
    
    # TTS
    "TTSInfoResponse",
    "TTSPreviewRequest",
    "TTSPreviewResponse",
    
    # Фильтры
    "AudioFilterRequest",
]
