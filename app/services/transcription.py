#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис транскрибации аудио в текст
AutoDialer Ultimate v3.0.0

Поддерживает:
- Whisper (OpenAI) - рекомендуется, высокая точность
- Vosk - легковесный, работает на CPU
- Google Speech-to-Text (опционально, через API)
- Автоматический выбор доступного движка
- Очередь для асинхронной обработки

ИСПОЛЬЗОВАНИЕ:
    from app.services.transcription import (
        TranscriptionService, get_transcription_service,
        init_transcription_service, close_transcription_service
    )
"""

import os
import json
import wave
import asyncio
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from enum import Enum

from app.core.config import settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.incoming import TranscriptionStatus, TranscriptionEngine
from prometheus_client import Counter, Histogram, Gauge


# =============================================
# Метрики
# =============================================
transcription_total = Counter(
    'autodialer_transcription_total',
    'Total transcriptions',
    ['engine', 'status']
)
transcription_duration = Histogram(
    'autodialer_transcription_duration_seconds',
    'Transcription duration',
    ['engine']
)
transcription_audio_duration = Histogram(
    'autodialer_transcription_audio_duration_seconds',
    'Transcribed audio duration',
    buckets=[10, 30, 60, 120, 180, 300, 600, 1200]
)
transcription_queue_size = Gauge(
    'autodialer_transcription_queue_size',
    'Transcription queue size'
)
transcription_active = Gauge(
    'autodialer_transcription_active',
    'Active transcription tasks'
)


# =============================================
# Исключения
# =============================================
class TranscriptionError(Exception):
    """Базовое исключение сервиса транскрибации"""
    pass


class TranscriptionEngineNotFound(TranscriptionError):
    """Движок транскрибации не найден"""
    pass


class TranscriptionFileNotFound(TranscriptionError):
    """Файл для транскрибации не найден"""
    pass


class TranscriptionFailed(TranscriptionError):
    """Ошибка транскрибации"""
    pass


# =============================================
# Сервис транскрибации
# =============================================
class TranscriptionService:
    """
    Сервис транскрибации аудио в текст.
    
    Автоматически определяет доступный движок в порядке приоритета:
    1. Whisper (если установлен)
    2. Vosk (если установлен и есть модель)
    3. Google (если настроены credentials)
    4. None (заглушка)
    
    Особенности:
    - Асинхронная обработка через очередь Redis
    - Поддержка нескольких движков
    - Автоматическая конвертация аудио при необходимости
    - Метрики Prometheus
    """
    
    def __init__(
        self,
        db_pool: Optional[ConnectionPool] = None,
        redis_client: Optional[RedisClient] = None,
        engine: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Инициализация сервиса транскрибации.
        
        Args:
            db_pool: Пул соединений с БД (для фоновой обработки)
            redis_client: Клиент Redis (для очереди)
            engine: Движок ('whisper', 'vosk', 'google', 'none')
            model: Модель для движка
        """
        self.db_pool = db_pool
        self.redis = redis_client
        
        # Определяем движок
        self.engine = self._detect_engine(engine or settings.TRANSCRIPTION_ENGINE)
        self.model = model or self._get_default_model()
        
        # Экземпляр модели
        self._model_instance = None
        self._initialized = False
        
        # Очередь для асинхронной обработки
        self._queue_task: Optional[asyncio.Task] = None
        self._running = False
        self._active_tasks = 0
        self._semaphore = asyncio.Semaphore(settings.TRANSCRIPTION_CONCURRENT)
        
        # Статистика
        self._stats = {
            'total': 0,
            'completed': 0,
            'failed': 0,
            'total_duration': 0.0
        }
        
        logger.info(f"TranscriptionService инициализирован: engine={self.engine.value}, model={self.model}")
    
    # =============================================
    # Определение движка
    # =============================================
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
        
        logger.warning("No transcription engine available, using NONE")
        return TranscriptionEngine.NONE
    
    def _get_default_model(self) -> str:
        """Получение модели по умолчанию"""
        if self.engine == TranscriptionEngine.WHISPER:
            return settings.WHISPER_MODEL
        elif self.engine == TranscriptionEngine.VOSK:
            return settings.VOSK_MODEL
        elif self.engine == TranscriptionEngine.GOOGLE:
            return settings.GOOGLE_MODEL
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
            model_path = Path(settings.VOSK_MODEL_PATH)
            return model_path.exists()
        except ImportError:
            return False
    
    def _check_google_available(self) -> bool:
        """Проверка доступности Google Speech-to-Text"""
        try:
            from google.cloud import speech
            return bool(settings.GOOGLE_APPLICATION_CREDENTIALS)
        except ImportError:
            return False
    
    # =============================================
    # Инициализация движков
    # =============================================
    def _init_whisper(self):
        """Инициализация Whisper"""
        if self._model_instance is not None:
            return
        
        try:
            import whisper
            self._model_instance = whisper.load_model(
                self.model,
                device=settings.WHISPER_DEVICE
            )
            logger.info(f"Whisper модель '{self.model}' загружена")
            self._initialized = True
        except Exception as e:
            logger.error(f"Ошибка загрузки Whisper: {e}")
            self.engine = TranscriptionEngine.NONE
    
    def _init_vosk(self):
        """Инициализация Vosk"""
        if self._model_instance is not None:
            return
        
        try:
            import vosk
            model_path = Path(settings.VOSK_MODEL_PATH)
            self._model_instance = vosk.Model(str(model_path))
            logger.info(f"Vosk модель загружена из {model_path}")
            self._initialized = True
        except Exception as e:
            logger.error(f"Ошибка загрузки Vosk: {e}")
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
    
    # =============================================
    # Транскрибация
    # =============================================
    async def transcribe(
        self,
        audio_path: str,
        language: str = "ru",
        timeout: Optional[int] = None
    ) -> Optional[str]:
        """
        Транскрибация аудиофайла в текст.
        
        Args:
            audio_path: Путь к аудиофайлу
            language: Язык аудио (по умолчанию 'ru')
            timeout: Таймаут в секундах
        
        Returns:
            Распознанный текст или None в случае ошибки
        """
        if not os.path.exists(audio_path):
            logger.error(f"Аудиофайл не найден: {audio_path}")
            raise TranscriptionFileNotFound(f"Файл не найден: {audio_path}")
        
        if self.engine == TranscriptionEngine.NONE:
            logger.warning("Нет доступного движка транскрибации")
            return ""
        
        self._ensure_initialized()
        
        start_time = datetime.utcnow()
        
        try:
            if self.engine == TranscriptionEngine.WHISPER:
                text = await self._transcribe_whisper(audio_path, language, timeout)
            elif self.engine == TranscriptionEngine.VOSK:
                text = await self._transcribe_vosk(audio_path, timeout)
            elif self.engine == TranscriptionEngine.GOOGLE:
                text = await self._transcribe_google(audio_path, language, timeout)
            else:
                text = ""
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            # Метрики
            status = "completed" if text is not None else "failed"
            transcription_total.labels(engine=self.engine.value, status=status).inc()
            transcription_duration.labels(engine=self.engine.value).observe(duration)
            
            self._stats['total'] += 1
            if text is not None:
                self._stats['completed'] += 1
            else:
                self._stats['failed'] += 1
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка транскрибации ({self.engine.value}): {e}")
            transcription_total.labels(engine=self.engine.value, status="error").inc()
            self._stats['failed'] += 1
            raise TranscriptionFailed(f"Ошибка транскрибации: {e}")
    
    async def _transcribe_whisper(
        self,
        audio_path: str,
        language: str,
        timeout: Optional[int]
    ) -> str:
        """Транскрибация через Whisper"""
        loop = asyncio.get_event_loop()
        
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._model_instance.transcribe(
                        audio_path,
                        language=language,
                        task="transcribe",
                        fp16=settings.WHISPER_FP16,
                        verbose=False
                    )
                ),
                timeout=timeout or 300
            )
            
            text = result.get("text", "").strip()
            
            # Сохраняем длительность аудио
            if "segments" in result and result["segments"]:
                audio_duration = result["segments"][-1]["end"]
                transcription_audio_duration.observe(audio_duration)
                self._stats['total_duration'] += audio_duration
            
            logger.debug(f"Whisper транскрибация: {text[:100]}...")
            return text
            
        except asyncio.TimeoutError:
            logger.error(f"Whisper транскрибация превысила таймаут {timeout}с")
            raise
        except Exception as e:
            logger.error(f"Whisper транскрибация не удалась: {e}")
            raise
    
    async def _transcribe_vosk(
        self,
        audio_path: str,
        timeout: Optional[int]
    ) -> str:
        """Транскрибация через Vosk"""
        import json
        
        try:
            wf = wave.open(audio_path, "rb")
            
            # Проверяем формат
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                logger.warning("Vosk требует mono 16-bit, конвертируем...")
                converted_path = await self._convert_audio(audio_path, 16000, 1, 16)
                if converted_path:
                    wf = wave.open(converted_path, "rb")
                else:
                    return ""
            
            import vosk
            rec = vosk.KaldiRecognizer(self._model_instance, wf.getframerate())
            rec.SetWords(False)
            rec.SetPartialWords(False)
            
            text_parts = []
            audio_duration = wf.getnframes() / wf.getframerate()
            transcription_audio_duration.observe(audio_duration)
            self._stats['total_duration'] += audio_duration
            
            loop = asyncio.get_event_loop()
            
            async def process():
                while True:
                    data = wf.readframes(4000)
                    if len(data) == 0:
                        break
                    if rec.AcceptWaveform(data):
                        result = json.loads(rec.Result())
                        part = result.get("text", "")
                        if part:
                            text_parts.append(part)
                
                final_result = json.loads(rec.FinalResult())
                final_text = final_result.get("text", "")
                if final_text:
                    text_parts.append(final_text)
                
                return " ".join(text_parts).strip()
            
            text = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: asyncio.run(process())),
                timeout=timeout or 120
            )
            
            logger.debug(f"Vosk транскрибация: {text[:100]}...")
            return text
            
        except asyncio.TimeoutError:
            logger.error(f"Vosk транскрибация превысила таймаут")
            raise
        except Exception as e:
            logger.error(f"Vosk транскрибация не удалась: {e}")
            raise
    
    async def _transcribe_google(
        self,
        audio_path: str,
        language: str,
        timeout: Optional[int]
    ) -> str:
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
            
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.recognize(config=config, audio=audio)
                ),
                timeout=timeout or 60
            )
            
            text_parts = []
            for result in response.results:
                text_parts.append(result.alternatives[0].transcript)
            
            text = " ".join(text_parts).strip()
            logger.debug(f"Google транскрибация: {text[:100]}...")
            return text
            
        except asyncio.TimeoutError:
            logger.error("Google транскрибация превысила таймаут")
            raise
        except Exception as e:
            logger.error(f"Google транскрибация не удалась: {e}")
            raise
    
    # =============================================
    # Конвертация аудио
    # =============================================
    async def _convert_audio(
        self,
        audio_path: str,
        sample_rate: int = 16000,
        channels: int = 1,
        bits: int = 16
    ) -> Optional[str]:
        """
        Конвертация аудио в нужный формат.
        
        Args:
            audio_path: Путь к исходному файлу
            sample_rate: Частота дискретизации
            channels: Количество каналов
            bits: Битность
        
        Returns:
            Путь к сконвертированному файлу или None
        """
        try:
            output_path = audio_path.replace('.wav', '_converted.wav')
            if os.path.exists(output_path):
                return output_path
            
            cmd = [
                'sox', audio_path,
                '-r', str(sample_rate),
                '-c', str(channels),
                '-b', str(bits),
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
            logger.error(f"Ошибка конвертации аудио: {e}")
            return None
    
    # =============================================
    # Асинхронная очередь
    # =============================================
    async def start_queue_processor(self):
        """Запустить обработчик очереди транскрибации"""
        if not self.redis or not self.db_pool:
            logger.warning("Redis или БД не настроены, обработчик очереди не запущен")
            return
        
        if self._running:
            return
        
        self._running = True
        self._queue_task = asyncio.create_task(self._process_transcription_queue())
        logger.info("Обработчик очереди транскрибации запущен")
    
    async def stop_queue_processor(self):
        """Остановить обработчик очереди"""
        self._running = False
        
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Обработчик очереди транскрибации остановлен")
    
    async def queue_transcription(
        self,
        call_id: int,
        audio_path: str,
        language: str = "ru"
    ) -> bool:
        """
        Добавить задачу в очередь транскрибации.
        
        Args:
            call_id: ID звонка
            audio_path: Путь к аудиофайлу
            language: Язык
        
        Returns:
            True если добавлено
        """
        if not self.redis:
            return False
        
        task = {
            "call_id": call_id,
            "audio_path": audio_path,
            "language": language,
            "queued_at": datetime.utcnow().isoformat()
        }
        
        await self.redis.rpush(REDIS_KEYS.TRANSCRIPTION_QUEUE, json.dumps(task))
        transcription_queue_size.inc()
        
        logger.info(f"Задача транскрибации добавлена в очередь: call_id={call_id}")
        return True
    
    async def _process_transcription_queue(self):
        """Фоновая обработка очереди транскрибации"""
        logger.info("Обработчик очереди транскрибации запущен")
        
        while self._running:
            try:
                # BLPOP's own (server-side) blocking timeout must stay
                # comfortably below the redis client's socket_timeout
                # (settings.REDIS_SOCKET_TIMEOUT, 5s by default) - equal
                # or larger and the client's socket read races the
                # server's graceful nil-on-timeout response, so on every
                # single idle poll (i.e. almost always, since the queue
                # is normally empty) it raised a client-side
                # TimeoutError("Timeout reading from redis:...") instead
                # of blpop() just returning None. Confirmed live: this
                # error repeated in the logs every ~11s against a real
                # Redis container.
                result = await self.redis.blpop(
                    REDIS_KEYS.TRANSCRIPTION_QUEUE,
                    timeout=max(1, settings.REDIS_SOCKET_TIMEOUT - 2)
                )
                
                if result:
                    _, task_json = result
                    task = json.loads(task_json)
                    
                    asyncio.create_task(self._process_single_task(task))
                    
                transcription_queue_size.set(
                    await self.redis.llen(REDIS_KEYS.TRANSCRIPTION_QUEUE)
                )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в обработчике очереди: {e}")
                await asyncio.sleep(1)
        
        logger.info("Обработчик очереди транскрибации остановлен")
    
    async def _process_single_task(self, task: Dict[str, Any]):
        """Обработать одну задачу транскрибации"""
        async with self._semaphore:
            call_id = task.get("call_id")
            audio_path = task.get("audio_path")
            language = task.get("language", "ru")
            
            transcription_active.inc()
            
            try:
                logger.info(f"Обработка транскрибации: call_id={call_id}")
                
                # Обновляем статус в БД
                if self.db_pool:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE incoming_calls 
                            SET transcription_status = $1 
                            WHERE id = $2
                        """, TranscriptionStatus.PROCESSING.value, call_id)
                
                # Проверяем существование файла
                if not os.path.exists(audio_path):
                    raise TranscriptionFileNotFound(f"Файл не найден: {audio_path}")
                
                # Ждём немного, чтобы файл дописался
                await asyncio.sleep(2)
                
                # Транскрибация
                text = await self.transcribe(audio_path, language)
                status = TranscriptionStatus.COMPLETED if text is not None else TranscriptionStatus.FAILED
                
                # Сохраняем результат
                if self.db_pool:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE incoming_calls 
                            SET transcription = $1, transcription_status = $2 
                            WHERE id = $3
                        """, text or "", status.value, call_id)
                        
                        # Сохраняем в Redis для быстрого доступа
                        if self.redis:
                            await self.redis.setex(
                                f"transcription:{call_id}",
                                86400,  # 24 часа
                                json.dumps({
                                    "text": text,
                                    "status": status.value,
                                    "engine": self.engine.value,
                                    "completed_at": datetime.utcnow().isoformat()
                                })
                            )
                
                logger.info(f"Транскрибация завершена: call_id={call_id}, status={status.value}")
                
            except FileNotFoundError as e:
                logger.error(f"Файл не найден для call_id={call_id}: {e}")
                if self.db_pool:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE incoming_calls 
                            SET transcription_status = $1, transcription_error = $2
                            WHERE id = $3
                        """, TranscriptionStatus.FAILED.value, str(e), call_id)
                        
            except Exception as e:
                logger.error(f"Ошибка транскрибации для call_id={call_id}: {e}")
                if self.db_pool:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE incoming_calls 
                            SET transcription_status = $1, transcription_error = $2
                            WHERE id = $3
                        """, TranscriptionStatus.FAILED.value, str(e)[:500], call_id)
            finally:
                transcription_active.dec()
    
    # =============================================
    # Информация о сервисе
    # =============================================
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о сервисе"""
        return {
            "engine": self.engine.value,
            "model": self.model,
            "initialized": self._initialized,
            "running": self._running,
            "active_tasks": self._active_tasks,
            "available_engines": {
                "whisper": self._check_whisper_available(),
                "vosk": self._check_vosk_available(),
                "google": self._check_google_available()
            },
            "settings": {
                "whisper_model": settings.WHISPER_MODEL,
                "whisper_device": settings.WHISPER_DEVICE,
                "vosk_model_path": settings.VOSK_MODEL_PATH,
                "concurrent_limit": settings.TRANSCRIPTION_CONCURRENT
            },
            "stats": self._stats,
        }

    async def get_queue_size(self) -> int:
        """Получить размер очереди транскрибации (требует await, в отличие от get_info)"""
        if not self.redis:
            return 0
        return await self.redis.llen(REDIS_KEYS.TRANSCRIPTION_QUEUE)
    
    async def get_task_status(self, call_id: int) -> Optional[Dict[str, Any]]:
        """Получить статус задачи транскрибации"""
        if not self.redis:
            return None
        
        cached = await self.redis.get(f"transcription:{call_id}")
        if cached:
            return json.loads(cached)
        
        if self.db_pool:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT transcription, transcription_status, transcription_engine, transcription_error
                    FROM incoming_calls WHERE id = $1
                """, call_id)
                
                if row:
                    return {
                        "text": row['transcription'],
                        "status": row['transcription_status'],
                        "engine": row['transcription_engine'],
                        "error": row['transcription_error']
                    }
        
        return None
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        status = "healthy" if self.engine != TranscriptionEngine.NONE else "degraded"
        
        return {
            "status": status,
            "engine": self.engine.value,
            "model": self.model,
            "initialized": self._initialized,
            "running": self._running,
            "queue_size": await self.redis.llen(REDIS_KEYS.TRANSCRIPTION_QUEUE) if self.redis else 0,
            "active_tasks": self._active_tasks
        }
    
    async def shutdown(self):
        """Корректное завершение"""
        await self.stop_queue_processor()
        self._model_instance = None
        self._initialized = False
        logger.info("TranscriptionService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_transcription_service: Optional[TranscriptionService] = None


def get_transcription_service() -> TranscriptionService:
    """Получить глобальный экземпляр TranscriptionService"""
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service


async def init_transcription_service(
    db_pool: Optional[ConnectionPool] = None,
    redis_client: Optional[RedisClient] = None
) -> TranscriptionService:
    """Инициализировать глобальный экземпляр"""
    global _transcription_service
    
    engine = settings.TRANSCRIPTION_ENGINE
    model = settings.TRANSCRIPTION_MODEL
    
    _transcription_service = TranscriptionService(
        db_pool=db_pool,
        redis_client=redis_client,
        engine=engine,
        model=model
    )
    
    if settings.TRANSCRIPTION_ENABLED and db_pool and redis_client:
        await _transcription_service.start_queue_processor()
    
    return _transcription_service


async def close_transcription_service():
    """Закрыть глобальный экземпляр"""
    global _transcription_service
    if _transcription_service:
        await _transcription_service.shutdown()
        _transcription_service = None


async def transcribe_audio(audio_path: str, language: str = "ru") -> Optional[str]:
    """Удобная функция для транскрибации аудио"""
    service = get_transcription_service()
    return await service.transcribe(audio_path, language)


async def process_transcription_queue(db_pool: ConnectionPool, redis_client: RedisClient):
    """Фоновая задача для обработки очереди (совместимость со старым кодом)"""
    service = TranscriptionService(db_pool, redis_client)
    await service.start_queue_processor()
    
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await service.stop_queue_processor()


# =============================================
# Экспорт
# =============================================
__all__ = [
    "TranscriptionService",
    "TranscriptionEngine",
    "TranscriptionStatus",
    "TranscriptionError",
    "TranscriptionEngineNotFound",
    "TranscriptionFileNotFound",
    "TranscriptionFailed",
    "get_transcription_service",
    "init_transcription_service",
    "close_transcription_service",
    "transcribe_audio",
    "process_transcription_queue",
]
