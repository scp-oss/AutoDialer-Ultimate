#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис транскрибации аудио в текст
AutoDialer Ultimate v3.0.0

Поддерживает:
- Whisper (OpenAI) - рекомендуется, высокая точность
- Vosk - легковесный, работает на CPU
- Google Speech-to-Text (опционально, через API)

Автоматически выбирает доступный движок.
"""

import os
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum

from logger import logger


# =============================================
# Transcription Engine Enum
# =============================================
class TranscriptionEngine(str, Enum):
    """Доступные движки транскрибации"""
    WHISPER = "whisper"
    VOSK = "vosk"
    GOOGLE = "google"
    NONE = "none"


# =============================================
# Transcription Service
# =============================================
class TranscriptionService:
    """
    Сервис транскрибации аудио в текст.
    
    Автоматически определяет доступный движок в порядке приоритета:
    1. Whisper (если установлен)
    2. Vosk (если установлен и есть модель)
    3. None (заглушка)
    """
    
    def __init__(self, engine: Optional[str] = None, model: Optional[str] = None):
        """
        Инициализация сервиса транскрибации.
        
        Args:
            engine: Движок ('whisper', 'vosk', 'google', 'none')
            model: Модель для движка (для whisper: tiny/base/small/medium/large)
        """
        self.engine = self._detect_engine(engine)
        self.model = model or self._get_default_model()
        self._model_instance = None
        self._initialized = False
        
        logger.info(f"Transcription service initialized: engine={self.engine}, model={self.model}")
    
    def _detect_engine(self, requested: Optional[str]) -> TranscriptionEngine:
        """Определение доступного движка"""
        if requested == "none":
            return TranscriptionEngine.NONE
        
        if requested == "whisper" or requested is None:
            if self._check_whisper_available():
                return TranscriptionEngine.WHISPER
        
        if requested == "vosk" or requested is None:
            if self._check_vosk_available():
                return TranscriptionEngine.VOSK
        
        if requested == "google":
            if self._check_google_available():
                return TranscriptionEngine.GOOGLE
        
        logger.warning("No transcription engine available, using NONE (text will be empty)")
        return TranscriptionEngine.NONE
    
    def _get_default_model(self) -> str:
        """Получение модели по умолчанию"""
        if self.engine == TranscriptionEngine.WHISPER:
            return os.getenv('WHISPER_MODEL', 'small')
        elif self.engine == TranscriptionEngine.VOSK:
            return os.getenv('VOSK_MODEL', 'ru')
        elif self.engine == TranscriptionEngine.GOOGLE:
            return os.getenv('GOOGLE_MODEL', 'default')
        return "none"
    
    def _check_whisper_available(self) -> bool:
        """Проверка доступности Whisper"""
        try:
            import whisper
            return True
        except ImportError:
            return False
    
    def _check_vosk_available(self) -> bool:
        """Проверка доступности Vosk"""
        try:
            import vosk
            model_path = os.getenv('VOSK_MODEL_PATH', '/opt/autodialer/models/vosk-model-small-ru-0.22')
            return os.path.exists(model_path)
        except ImportError:
            return False
    
    def _check_google_available(self) -> bool:
        """Проверка доступности Google Speech-to-Text"""
        try:
            from google.cloud import speech
            return bool(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
        except ImportError:
            return False
    
    def _init_whisper(self):
        """Инициализация Whisper"""
        if self._model_instance is not None:
            return
        
        try:
            import whisper
            self._model_instance = whisper.load_model(self.model)
            logger.info(f"Whisper model '{self.model}' loaded")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            self.engine = TranscriptionEngine.NONE
    
    def _init_vosk(self):
        """Инициализация Vosk"""
        if self._model_instance is not None:
            return
        
        try:
            import vosk
            model_path = os.getenv('VOSK_MODEL_PATH', '/opt/autodialer/models/vosk-model-small-ru-0.22')
            self._model_instance = vosk.Model(model_path)
            logger.info(f"Vosk model loaded from {model_path}")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to load Vosk model: {e}")
            self.engine = TranscriptionEngine.NONE
    
    def _ensure_initialized(self):
        """Гарантировать инициализацию движка"""
        if self._initialized:
            return
        
        if self.engine == TranscriptionEngine.WHISPER:
            self._init_whisper()
        elif self.engine == TranscriptionEngine.VOSK:
            self._init_vosk()
        elif self.engine == TranscriptionEngine.NONE:
            self._initialized = True
    
    async def transcribe(self, audio_path: str, language: str = "ru") -> Optional[str]:
        """
        Транскрибация аудиофайла в текст.
        
        Args:
            audio_path: Путь к аудиофайлу
            language: Язык аудио (по умолчанию 'ru')
        
        Returns:
            Распознанный текст или None в случае ошибки
        """
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return None
        
        if self.engine == TranscriptionEngine.NONE:
            logger.warning("No transcription engine available, returning empty string")
            return ""
        
        self._ensure_initialized()
        
        if self.engine == TranscriptionEngine.WHISPER:
            return await self._transcribe_whisper(audio_path, language)
        elif self.engine == TranscriptionEngine.VOSK:
            return await self._transcribe_vosk(audio_path)
        elif self.engine == TranscriptionEngine.GOOGLE:
            return await self._transcribe_google(audio_path, language)
        
        return None
    
    async def _transcribe_whisper(self, audio_path: str, language: str) -> str:
        """Транскрибация через Whisper"""
        loop = asyncio.get_event_loop()
        
        try:
            # Выполняем в отдельном потоке, чтобы не блокировать event loop
            result = await loop.run_in_executor(
                None,
                lambda: self._model_instance.transcribe(
                    audio_path,
                    language=language,
                    task="transcribe",
                    fp16=False,  # Для CPU лучше False
                    verbose=False
                )
            )
            
            text = result.get("text", "").strip()
            logger.debug(f"Whisper transcription: {text[:100]}...")
            return text
            
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            return ""
    
    async def _transcribe_vosk(self, audio_path: str) -> str:
        """Транскрибация через Vosk"""
        import wave
        import json
        
        try:
            wf = wave.open(audio_path, "rb")
            
            # Проверяем формат
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                logger.warning(f"Vosk requires mono 16-bit audio, converting...")
                converted_path = await self._convert_audio(audio_path)
                if converted_path:
                    wf = wave.open(converted_path, "rb")
                else:
                    return ""
            
            import vosk
            rec = vosk.KaldiRecognizer(self._model_instance, wf.getframerate())
            rec.SetWords(False)
            rec.SetPartialWords(False)
            
            text_parts = []
            
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    part = result.get("text", "")
                    if part:
                        text_parts.append(part)
            
            # Финальный результат
            final_result = json.loads(rec.FinalResult())
            final_text = final_result.get("text", "")
            if final_text:
                text_parts.append(final_text)
            
            text = " ".join(text_parts).strip()
            logger.debug(f"Vosk transcription: {text[:100]}...")
            return text
            
        except Exception as e:
            logger.error(f"Vosk transcription failed: {e}")
            return ""
    
    async def _transcribe_google(self, audio_path: str, language: str) -> str:
        """Транскрибация через Google Speech-to-Text"""
        try:
            from google.cloud import speech
            
            client = speech.SpeechClient()
            
            with open(audio_path, "rb") as f:
                content = f.read()
            
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=8000,
                language_code=language,
                enable_automatic_punctuation=True,
            )
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.recognize(config=config, audio=audio)
            )
            
            text_parts = []
            for result in response.results:
                text_parts.append(result.alternatives[0].transcript)
            
            text = " ".join(text_parts).strip()
            logger.debug(f"Google transcription: {text[:100]}...")
            return text
            
        except Exception as e:
            logger.error(f"Google transcription failed: {e}")
            return ""
    
    async def _convert_audio(self, audio_path: str) -> Optional[str]:
        """Конвертация аудио в формат, подходящий для Vosk (mono, 16-bit, 16kHz)"""
        try:
            output_path = audio_path.replace('.wav', '_converted.wav')
            
            cmd = [
                'sox', audio_path,
                '-r', '16000',
                '-c', '1',
                '-b', '16',
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.wait()
            
            if process.returncode == 0 and os.path.exists(output_path):
                return output_path
            else:
                return None
                
        except Exception as e:
            logger.error(f"Audio conversion failed: {e}")
            return None
    
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о сервисе"""
        return {
            "engine": self.engine.value if self.engine else "none",
            "model": self.model,
            "initialized": self._initialized,
            "available_engines": {
                "whisper": self._check_whisper_available(),
                "vosk": self._check_vosk_available(),
                "google": self._check_google_available()
            }
        }


# =============================================
# Глобальный экземпляр
# =============================================
_transcription_service: Optional[TranscriptionService] = None


def get_transcription_service() -> TranscriptionService:
    """Получить глобальный экземпляр сервиса транскрибации"""
    global _transcription_service
    
    if _transcription_service is None:
        engine = os.getenv('TRANSCRIPTION_ENGINE')
        model = os.getenv('TRANSCRIPTION_MODEL')
        _transcription_service = TranscriptionService(engine=engine, model=model)
    
    return _transcription_service


async def transcribe_audio(audio_path: str, language: str = "ru") -> Optional[str]:
    """
    Удобная функция для транскрибации аудио.
    
    Args:
        audio_path: Путь к аудиофайлу
        language: Язык аудио
    
    Returns:
        Распознанный текст или None
    """
    service = get_transcription_service()
    return await service.transcribe(audio_path, language)


# =============================================
# Фоновая задача для обработки очереди
# =============================================
async def process_transcription_queue(db_pool, redis_client):
    """
    Фоновая обработка очереди транскрибации.
    
    Забирает задачи из Redis и обрабатывает их.
    """
    service = get_transcription_service()
    
    logger.info("Transcription queue processor started")
    
    while True:
        try:
            # Ждём задачу из очереди
            task_data = await redis_client.brpop("transcription_queue", timeout=5)
            
            if task_data:
                _, task_json = task_data
                import json
                task = json.loads(task_json)
                
                call_id = task.get("call_id")
                audio_path = task.get("audio_path")
                language = task.get("language", "ru")
                
                logger.info(f"Processing transcription for call {call_id}")
                
                # Обновляем статус в БД
                await db_pool.execute(
                    "UPDATE incoming_calls SET transcription_status = 'processing' WHERE id = $1",
                    call_id
                )
                
                # Транскрибация
                text = await service.transcribe(audio_path, language)
                status = 'completed' if text is not None else 'failed'
                
                # Сохраняем результат
                await db_pool.execute(
                    "UPDATE incoming_calls SET transcription = $1, transcription_status = $2 WHERE id = $3",
                    text, status, call_id
                )
                
                logger.info(f"Transcription completed for call {call_id}: {status}")
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Transcription queue error: {e}")
            await asyncio.sleep(1)
    
    logger.info("Transcription queue processor stopped")
