#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления аудиофайлами и TTS
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Загрузки аудиофайлов
- Генерации аудио через TTS (Piper)
- Конвертации аудиоформатов
- Управления аудиофайлами
"""

import os
import re
import json
import uuid
import asyncio
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, BinaryIO
from dataclasses import dataclass

from app.core.config import settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient
from app.models.audio import (
    AudioFormat, AudioStatus, TTSVoice, TTSModel,
    AudioGenerateRequest, AudioUploadRequest, AudioUpdateRequest,
    AudioResponse, AudioDetailResponse, AudioListResponse,
    AudioGenerateResponse, AudioUploadResponse, AudioConvertResponse,
    TTSInfoResponse, TTSPreviewRequest, TTSPreviewResponse,
    AudioFilterRequest, AudioMetadata
)
from prometheus_client import Counter, Histogram, Gauge


# =============================================
# Метрики
# =============================================
audio_generated_counter = Counter(
    'autodialer_audio_generated_total',
    'Total audio files generated',
    ['voice', 'format']
)
audio_uploaded_counter = Counter(
    'autodialer_audio_uploaded_total',
    'Total audio files uploaded',
    ['format']
)
audio_converted_counter = Counter(
    'autodialer_audio_converted_total',
    'Total audio files converted',
    ['from_format', 'to_format']
)
audio_deleted_counter = Counter(
    'autodialer_audio_deleted_total',
    'Total audio files deleted'
)
tts_generation_duration = Histogram(
    'autodialer_tts_generation_duration_seconds',
    'TTS generation duration',
    ['voice', 'model']
)
tts_queue_size = Gauge(
    'autodialer_tts_queue_size',
    'TTS queue size'
)


# =============================================
# Исключения
# =============================================
class AudioError(Exception):
    """Базовое исключение сервиса аудио"""
    pass


class AudioNotFoundError(AudioError):
    """Аудиофайл не найден"""
    pass


class AudioValidationError(AudioError):
    """Ошибка валидации аудиофайла"""
    pass


class TTSGenerationError(AudioError):
    """Ошибка генерации TTS"""
    pass


class AudioConversionError(AudioError):
    """Ошибка конвертации аудио"""
    pass


class AudioUploadError(AudioError):
    """Ошибка загрузки аудио"""
    pass


# =============================================
# Модели данных
# =============================================
@dataclass
class AudioFileInfo:
    """Информация об аудиофайле"""
    path: Path
    format: AudioFormat
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    file_size: Optional[int] = None
    bitrate: Optional[int] = None


# =============================================
# Сервис аудио
# =============================================
class AudioService:
    """
    Сервис управления аудиофайлами.
    
    Отвечает за:
    - Загрузку аудиофайлов
    - Конвертацию форматов
    - CRUD операции с аудиофайлами
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        # Очередь конвертации
        self._conversion_queue: asyncio.Queue = asyncio.Queue()
        self._conversion_task: Optional[asyncio.Task] = None
        
        # Базовые директории
        self.audio_dir = Path(settings.TTS_DIR)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("AudioService инициализирован")
    
    # =============================================
    # Загрузка аудио
    # =============================================
    async def upload_audio(
        self,
        file: BinaryIO,
        filename: str,
        request: AudioUploadRequest,
        user_id: Optional[int] = None
    ) -> AudioUploadResponse:
        """
        Загрузить аудиофайл.
        
        Args:
            file: Файловый объект
            filename: Имя файла
            request: Параметры загрузки
            user_id: ID пользователя
        
        Returns:
            Информация о загруженном файле
        """
        # Проверяем формат
        original_format = self._get_format_from_filename(filename)
        if original_format not in [AudioFormat.WAV, AudioFormat.MP3]:
            raise AudioValidationError(f"Неподдерживаемый формат: {original_format}")
        
        # Проверяем размер
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > settings.AUDIO_MAX_SIZE:
            max_mb = settings.AUDIO_MAX_SIZE // (1024 * 1024)
            raise AudioValidationError(f"Файл слишком большой. Максимальный размер: {max_mb} МБ")
        
        # Генерируем имя файла
        safe_name = re.sub(r'[^\w\-\.]', '_', request.name)
        base_filename = f"upload_{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:8]}"
        
        # Сохраняем оригинальный файл
        original_path = self.audio_dir / f"{base_filename}.{original_format.value}"
        
        with open(original_path, 'wb') as f:
            while chunk := file.read(64 * 1024):
                f.write(chunk)
        
        logger.info(f"Файл сохранён: {original_path}")
        
        # Определяем целевой формат
        target_format = request.convert_to or AudioFormat.SLN
        converted = False
        final_path = original_path
        
        if target_format != original_format:
            # Конвертируем
            final_path = await self._convert_audio(
                original_path,
                original_format,
                target_format
            )
            converted = True
            
            # Удаляем оригинал если сконвертирован
            if original_path != final_path:
                original_path.unlink()
        
        # Получаем метаданные
        metadata = await self._get_audio_metadata(final_path, target_format)
        
        # Сохраняем в БД
        async with self.db_pool.acquire() as conn:
            audio_id = await conn.fetchval("""
                INSERT INTO audio_files (
                    name, description, file_path, file_name,
                    format, status, file_size, duration,
                    sample_rate, channels, bitrate,
                    campaign_id, is_public,
                    created_by, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8,
                    $9, $10, $11,
                    $12, $13,
                    $14, NOW(), NOW()
                )
                RETURNING id
            """,
                request.name,
                request.description,
                str(final_path),
                final_path.name,
                target_format.value,
                AudioStatus.READY.value,
                metadata.file_size,
                metadata.duration,
                metadata.sample_rate,
                metadata.channels,
                metadata.bitrate,
                request.campaign_id,
                request.is_public,
                user_id
            )
            
            # Добавляем теги
            if request.tags:
                await self._add_audio_tags(conn, audio_id, request.tags)
            
            # Получаем созданный файл
            audio = await self._get_audio_by_id(conn, audio_id)
        
        audio_uploaded_counter.labels(format=original_format.value).inc()
        logger.info(f"Аудио загружено: {request.name} (ID: {audio_id})")
        
        return AudioUploadResponse(
            id=audio_id,
            name=request.name,
            file_path=str(final_path),
            file_size=metadata.file_size or 0,
            duration=metadata.duration,
            format=target_format,
            original_format=original_format.value,
            converted=converted,
            status="completed"
        )
    
    # =============================================
    # Конвертация аудио
    # =============================================
    async def convert_audio(
        self,
        audio_id: int,
        target_format: AudioFormat,
        user_id: Optional[int] = None
    ) -> AudioConvertResponse:
        """Конвертировать аудиофайл в другой формат"""
        async with self.db_pool.acquire() as conn:
            audio = await conn.fetchrow(
                "SELECT * FROM audio_files WHERE id = $1",
                audio_id
            )
            if not audio:
                raise AudioNotFoundError(f"Аудиофайл {audio_id} не найден")
            
            source_path = Path(audio['file_path'])
            if not source_path.exists():
                raise AudioNotFoundError(f"Файл не найден: {source_path}")
            
            source_format = AudioFormat(audio['format'])
            
            if source_format == target_format:
                raise AudioValidationError(f"Файл уже в формате {target_format.value}")
        
        # Конвертируем
        target_path = await self._convert_audio(
            source_path,
            source_format,
            target_format
        )
        
        # Получаем метаданные
        metadata = await self._get_audio_metadata(target_path, target_format)
        
        # Сохраняем в БД
        async with self.db_pool.acquire() as conn:
            new_audio_id = await conn.fetchval("""
                INSERT INTO audio_files (
                    name, description, file_path, file_name,
                    format, status, file_size, duration,
                    sample_rate, channels, bitrate,
                    campaign_id, is_public, converted_from_id,
                    created_by, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8,
                    $9, $10, $11,
                    $12, $13, $14,
                    $15, NOW(), NOW()
                )
                RETURNING id
            """,
                f"{audio['name']} ({target_format.value})",
                audio['description'],
                str(target_path),
                target_path.name,
                target_format.value,
                AudioStatus.READY.value,
                metadata.file_size,
                metadata.duration,
                metadata.sample_rate,
                metadata.channels,
                metadata.bitrate,
                audio['campaign_id'],
                audio['is_public'],
                audio_id,
                user_id
            )
            
            new_audio = await self._get_audio_by_id(conn, new_audio_id)
        
        audio_converted_counter.labels(
            from_format=source_format.value,
            to_format=target_format.value
        ).inc()
        
        logger.info(f"Аудио конвертировано: {audio_id} -> {new_audio_id} ({target_format.value})")
        
        return AudioConvertResponse(
            id=new_audio_id,
            name=new_audio.name,
            file_path=str(target_path),
            file_size=metadata.file_size or 0,
            format=target_format,
            duration=metadata.duration,
            original_id=audio_id
        )
    
    async def _convert_audio(
        self,
        source_path: Path,
        source_format: AudioFormat,
        target_format: AudioFormat
    ) -> Path:
        """Внутренний метод конвертации аудио"""
        target_path = source_path.with_suffix(f".{target_format.value}")
        
        # Настройки для разных форматов
        if target_format == AudioFormat.SLN:
            # SLN: 8kHz, mono, 16-bit
            cmd = [
                'sox', str(source_path),
                '-r', '8000',
                '-c', '1',
                '-b', '16',
                '-t', 'raw',
                str(target_path)
            ]
        elif target_format == AudioFormat.WAV:
            cmd = [
                'sox', str(source_path),
                '-r', '8000',
                '-c', '1',
                str(target_path)
            ]
        elif target_format == AudioFormat.MP3:
            cmd = [
                'ffmpeg', '-i', str(source_path),
                '-acodec', 'libmp3lame',
                '-ab', '64k',
                '-ar', '8000',
                '-ac', '1',
                '-y',
                str(target_path)
            ]
        else:
            raise AudioConversionError(f"Неподдерживаемый целевой формат: {target_format}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='ignore')[:500]
                raise AudioConversionError(f"Ошибка конвертации: {error_msg}")
            
            if not target_path.exists():
                raise AudioConversionError("Файл не был создан")
            
            logger.info(f"Конвертация завершена: {source_path} -> {target_path}")
            
            return target_path
            
        except FileNotFoundError as e:
            raise AudioConversionError(f"Не найден инструмент конвертации: {e}")
        except Exception as e:
            raise AudioConversionError(f"Ошибка конвертации: {e}")
    
    # =============================================
    # CRUD операции
    # =============================================
    async def get_audio(self, audio_id: int) -> Optional[AudioDetailResponse]:
        """Получить аудиофайл по ID"""
        async with self.db_pool.acquire() as conn:
            audio = await self._get_audio_by_id(conn, audio_id)
            if not audio:
                return None
            
            # Получаем дополнительные данные
            usage_history = await self._get_usage_history(conn, audio_id)
            related_campaigns = await self._get_related_campaigns(conn, audio)
            
            # Увеличиваем счётчик просмотров
            await conn.execute(
                "UPDATE audio_files SET view_count = view_count + 1 WHERE id = $1",
                audio_id
            )
            
            return AudioDetailResponse(
                **audio.model_dump(),
                usage_history=usage_history,
                related_campaigns=related_campaigns,
                tts_settings=None  # Будет заполнено если это TTS
            )
    
    async def update_audio(
        self,
        audio_id: int,
        request: AudioUpdateRequest,
        user_id: Optional[int] = None
    ) -> AudioResponse:
        """Обновить аудиофайл"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM audio_files WHERE id = $1",
                audio_id
            )
            if not existing:
                raise AudioNotFoundError(f"Аудиофайл {audio_id} не найден")
            
            updates = []
            params = []
            param_idx = 1
            
            if request.name is not None:
                updates.append(f"name = ${param_idx}")
                params.append(request.name)
                param_idx += 1
            
            if request.description is not None:
                updates.append(f"description = ${param_idx}")
                params.append(request.description)
                param_idx += 1
            
            if request.campaign_id is not None:
                updates.append(f"campaign_id = ${param_idx}")
                params.append(request.campaign_id)
                param_idx += 1
            
            if request.is_public is not None:
                updates.append(f"is_public = ${param_idx}")
                params.append(request.is_public)
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(audio_id)
                query = f"""
                    UPDATE audio_files 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            # Обновляем теги
            if request.tags is not None:
                await self._update_audio_tags(conn, audio_id, request.tags)
            
            audio = await self._get_audio_by_id(conn, audio_id)
        
        logger.info(f"Аудио {audio_id} обновлено")
        return audio
    
    async def delete_audio(self, audio_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить аудиофайл"""
        async with self.db_pool.acquire() as conn:
            audio = await conn.fetchrow(
                "SELECT file_path, campaign_id FROM audio_files WHERE id = $1",
                audio_id
            )
            if not audio:
                raise AudioNotFoundError(f"Аудиофайл {audio_id} не найден")
            
            # Проверяем использование в кампаниях
            if audio['campaign_id']:
                campaign = await conn.fetchrow(
                    "SELECT id, name FROM campaigns WHERE audio_id = $1 AND status = 'running'",
                    audio_id
                )
                if campaign:
                    raise AudioError(
                        f"Нельзя удалить аудиофайл, используемый в запущенной кампании '{campaign['name']}'"
                    )
            
            # Удаляем файл
            file_path = Path(audio['file_path'])
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.warning(f"Не удалось удалить файл {file_path}: {e}")
            
            # Удаляем из БД
            await conn.execute("DELETE FROM audio_tags WHERE audio_id = $1", audio_id)
            await conn.execute("DELETE FROM audio_usage WHERE audio_id = $1", audio_id)
            await conn.execute("DELETE FROM audio_files WHERE id = $1", audio_id)
        
        audio_deleted_counter.inc()
        logger.info(f"Аудио {audio_id} удалено")
        
        return True
    
    async def list_audio(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_params: Optional[AudioFilterRequest] = None
    ) -> AudioListResponse:
        """Получить список аудиофайлов с фильтрацией"""
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            where_conditions.append("a.deleted_at IS NULL")
            
            if filter_params:
                if filter_params.search:
                    where_conditions.append(f"""
                        (a.name ILIKE ${param_idx} OR a.description ILIKE ${param_idx})
                    """)
                    params.append(f"%{filter_params.search}%")
                    param_idx += 1
                
                if filter_params.format:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.format))])
                    where_conditions.append(f"a.format IN ({placeholders})")
                    params.extend([f.value for f in filter_params.format])
                    param_idx += len(filter_params.format)
                
                if filter_params.status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.status))])
                    where_conditions.append(f"a.status IN ({placeholders})")
                    params.extend([s.value for s in filter_params.status])
                    param_idx += len(filter_params.status)
                
                if filter_params.campaign_id is not None:
                    where_conditions.append(f"a.campaign_id = ${param_idx}")
                    params.append(filter_params.campaign_id)
                    param_idx += 1
                
                if filter_params.is_public is not None:
                    where_conditions.append(f"a.is_public = ${param_idx}")
                    params.append(filter_params.is_public)
                    param_idx += 1
                
                if filter_params.created_by is not None:
                    where_conditions.append(f"a.created_by = ${param_idx}")
                    params.append(filter_params.created_by)
                    param_idx += 1
                
                if filter_params.tags:
                    where_conditions.append(f"""
                        a.id IN (
                            SELECT audio_id FROM audio_tags 
                            WHERE tag = ANY(${param_idx})
                        )
                    """)
                    params.append(filter_params.tags)
                    param_idx += 1
                
                if filter_params.min_duration is not None:
                    where_conditions.append(f"a.duration >= ${param_idx}")
                    params.append(filter_params.min_duration)
                    param_idx += 1
                
                if filter_params.max_duration is not None:
                    where_conditions.append(f"a.duration <= ${param_idx}")
                    params.append(filter_params.max_duration)
                    param_idx += 1
                
                if filter_params.created_after:
                    where_conditions.append(f"a.created_at >= ${param_idx}")
                    params.append(filter_params.created_after)
                    param_idx += 1
                
                if filter_params.created_before:
                    where_conditions.append(f"a.created_at <= ${param_idx}")
                    params.append(filter_params.created_before)
                    param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions)
            
            # Общее количество
            count_query = f"""
                SELECT COUNT(*) FROM audio_files a
                {where_clause}
            """
            total = await conn.fetchval(count_query, *params)
            
            # Статистика
            stats_query = f"""
                SELECT 
                    COALESCE(SUM(a.file_size), 0) as total_size,
                    COALESCE(SUM(a.duration), 0) as total_duration
                FROM audio_files a
                {where_clause}
            """
            stats = await conn.fetchrow(stats_query, *params)
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "created_at"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные
            query = f"""
                SELECT 
                    a.*,
                    u.username as created_by_name,
                    c.name as campaign_name
                FROM audio_files a
                LEFT JOIN users u ON a.created_by = u.id
                LEFT JOIN campaigns c ON a.campaign_id = c.id
                {where_clause}
                ORDER BY a.{sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = []
            for row in rows:
                tags = await self._get_audio_tags(conn, row['id'])
                metadata = AudioMetadata(
                    duration=row['duration'],
                    sample_rate=row['sample_rate'],
                    channels=row['channels'],
                    bitrate=row['bitrate'],
                    file_size=row['file_size']
                )
                
                item = AudioResponse(
                    id=row['id'],
                    name=row['name'],
                    description=row['description'],
                    file_path=row['file_path'],
                    file_name=row['file_name'],
                    format=AudioFormat(row['format']),
                    status=AudioStatus(row['status']),
                    file_size=row['file_size'],
                    file_size_human=None,
                    duration=row['duration'],
                    duration_formatted=None,
                    metadata=metadata,
                    campaign_id=row['campaign_id'],
                    campaign_name=row['campaign_name'],
                    is_public=row['is_public'],
                    tags=tags,
                    created_by=row['created_by'],
                    created_by_name=row['created_by_name'],
                    download_url=f"/api/audio/{row['id']}/download",
                    stream_url=f"/api/audio/{row['id']}/stream",
                    usage_count=row['usage_count'] or 0,
                    last_used_at=row['last_used_at'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
                items.append(item)
            
            return AudioListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size,
                total_size=stats['total_size'] or 0,
                total_duration=stats['total_duration'] or 0.0
            )
    
    async def get_audio_file_path(self, audio_id: int) -> Path:
        """Получить путь к аудиофайлу"""
        async with self.db_pool.acquire() as conn:
            path = await conn.fetchval(
                "SELECT file_path FROM audio_files WHERE id = $1",
                audio_id
            )
            if not path:
                raise AudioNotFoundError(f"Аудиофайл {audio_id} не найден")
            
            file_path = Path(path)
            if not file_path.exists():
                raise AudioNotFoundError(f"Файл не найден: {file_path}")
            
            # Обновляем статистику использования
            await conn.execute("""
                UPDATE audio_files 
                SET usage_count = usage_count + 1, last_used_at = NOW()
                WHERE id = $1
            """, audio_id)
            
            return file_path
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    def _get_format_from_filename(self, filename: str) -> AudioFormat:
        """Определить формат по расширению файла"""
        ext = Path(filename).suffix.lower()
        
        format_map = {
            '.wav': AudioFormat.WAV,
            '.mp3': AudioFormat.MP3,
            '.sln': AudioFormat.SLN,
            '.gsm': AudioFormat.GSM,
            '.ulaw': AudioFormat.ULAW,
            '.alaw': AudioFormat.ALAW,
            '.ogg': AudioFormat.OGG,
        }
        
        return format_map.get(ext, AudioFormat.WAV)
    
    async def _get_audio_metadata(
        self,
        file_path: Path,
        format: AudioFormat
    ) -> AudioFileInfo:
        """Получить метаданные аудиофайла"""
        info = AudioFileInfo(
            path=file_path,
            format=format,
            file_size=file_path.stat().st_size if file_path.exists() else None
        )
        
        # Получаем длительность через sox
        try:
            cmd = ['soxi', '-D', str(file_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            
            if process.returncode == 0:
                info.duration = float(stdout.decode().strip())
        except Exception:
            pass
        
        # Получаем sample rate
        try:
            cmd = ['soxi', '-r', str(file_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            
            if process.returncode == 0:
                info.sample_rate = int(stdout.decode().strip())
        except Exception:
            pass
        
        # Получаем количество каналов
        try:
            cmd = ['soxi', '-c', str(file_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            
            if process.returncode == 0:
                info.channels = int(stdout.decode().strip())
        except Exception:
            pass
        
        # Битрейт
        if info.duration and info.file_size:
            info.bitrate = int((info.file_size * 8) / info.duration / 1000)
        
        return info
    
    async def _get_audio_by_id(self, conn, audio_id: int) -> Optional[AudioResponse]:
        """Получить аудио по ID (внутренний метод)"""
        row = await conn.fetchrow("""
            SELECT 
                a.*,
                u.username as created_by_name,
                c.name as campaign_name
            FROM audio_files a
            LEFT JOIN users u ON a.created_by = u.id
            LEFT JOIN campaigns c ON a.campaign_id = c.id
            WHERE a.id = $1 AND a.deleted_at IS NULL
        """, audio_id)
        
        if not row:
            return None
        
        tags = await self._get_audio_tags(conn, audio_id)
        metadata = AudioMetadata(
            duration=row['duration'],
            sample_rate=row['sample_rate'],
            channels=row['channels'],
            bitrate=row['bitrate'],
            file_size=row['file_size']
        )
        
        return AudioResponse(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            file_path=row['file_path'],
            file_name=row['file_name'],
            format=AudioFormat(row['format']),
            status=AudioStatus(row['status']),
            file_size=row['file_size'],
            file_size_human=None,
            duration=row['duration'],
            duration_formatted=None,
            metadata=metadata,
            campaign_id=row['campaign_id'],
            campaign_name=row['campaign_name'],
            is_public=row['is_public'],
            tags=tags,
            created_by=row['created_by'],
            created_by_name=row['created_by_name'],
            download_url=f"/api/audio/{row['id']}/download",
            stream_url=f"/api/audio/{row['id']}/stream",
            usage_count=row['usage_count'] or 0,
            last_used_at=row['last_used_at'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    async def _get_audio_tags(self, conn, audio_id: int) -> List[str]:
        rows = await conn.fetch(
            "SELECT tag FROM audio_tags WHERE audio_id = $1",
            audio_id
        )
        return [row['tag'] for row in rows]
    
    async def _add_audio_tags(self, conn, audio_id: int, tags: List[str]) -> None:
        for tag in tags:
            await conn.execute("""
                INSERT INTO audio_tags (audio_id, tag)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, audio_id, tag)
    
    async def _update_audio_tags(self, conn, audio_id: int, tags: List[str]) -> None:
        await conn.execute("DELETE FROM audio_tags WHERE audio_id = $1", audio_id)
        await self._add_audio_tags(conn, audio_id, tags)
    
    async def _get_usage_history(self, conn, audio_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT * FROM audio_usage
            WHERE audio_id = $1
            ORDER BY used_at DESC
            LIMIT 50
        """, audio_id)
        return [dict(row) for row in rows]
    
    async def _get_related_campaigns(self, conn, audio: AudioResponse) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id, name, status
            FROM campaigns
            WHERE audio_id = $1
            ORDER BY created_at DESC
        """, audio.id)
        return [dict(row) for row in rows]
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            # Проверяем доступность sox
            sox_available = False
            try:
                process = await asyncio.create_subprocess_exec(
                    'sox', '--version',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                sox_available = process.returncode == 0
            except:
                pass
            
            return {
                "status": "healthy",
                "sox_available": sox_available,
                "audio_dir": str(self.audio_dir),
                "audio_dir_exists": self.audio_dir.exists()
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        if self._conversion_task and not self._conversion_task.done():
            self._conversion_task.cancel()
            try:
                await self._conversion_task
            except asyncio.CancelledError:
                pass
        logger.info("AudioService остановлен")


# =============================================
# Сервис TTS (Text-to-Speech)
# =============================================
class TTSService:
    """
    Сервис генерации речи (TTS) через Piper.
    
    Отвечает за:
    - Генерацию аудио из текста
    - Управление очередью генерации
    - Предпрослушивание
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        # Очередь TTS
        self._tts_queue: asyncio.Queue = asyncio.Queue()
        self._tts_task: Optional[asyncio.Task] = None
        self._tts_semaphore = asyncio.Semaphore(settings.TTS_MAX_CONCURRENT)
        
        # Директории
        self.tts_dir = Path(settings.TTS_DIR)
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = Path(settings.PIPER_MODEL_DIR)
        
        # Статистика
        self._stats = {
            'generated': 0,
            'failed': 0,
            'total_duration': 0.0
        }
        
        logger.info("TTSService инициализирован")
    
    async def start(self):
        """Запустить фоновую обработку очереди"""
        if not self._tts_task or self._tts_task.done():
            self._tts_task = asyncio.create_task(self._process_tts_queue())
            logger.info("Обработчик очереди TTS запущен")
    
    async def generate_audio(
        self,
        request: AudioGenerateRequest,
        user_id: Optional[int] = None,
        background: bool = False
    ) -> AudioGenerateResponse:
        """
        Сгенерировать аудио через TTS.
        
        Args:
            request: Параметры генерации
            user_id: ID пользователя
            background: Выполнять в фоне (вернуть task_id)
        
        Returns:
            Информация о сгенерированном файле или задаче
        """
        if background:
            # Добавляем в очередь
            task_id = str(uuid.uuid4())
            await self._tts_queue.put({
                'task_id': task_id,
                'request': request,
                'user_id': user_id
            })
            
            tts_queue_size.set(self._tts_queue.qsize())
            
            return AudioGenerateResponse(
                id=0,
                name=request.name,
                file_path="",
                file_size=0,
                duration=None,
                format=request.output_format,
                task_id=task_id,
                status="queued"
            )
        
        # Синхронная генерация
        return await self._generate_audio_sync(request, user_id)
    
    async def _generate_audio_sync(
        self,
        request: AudioGenerateRequest,
        user_id: Optional[int] = None
    ) -> AudioGenerateResponse:
        """Синхронная генерация аудио"""
        start_time = datetime.utcnow()
        
        async with self._tts_semaphore:
            try:
                # Генерируем имя файла
                safe_name = re.sub(r'[^\w\-]', '_', request.name)
                base_filename = f"tts_{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:8]}"
                
                # Путь к модели
                model_path = self._get_model_path(request.voice, request.model)
                if not model_path.exists():
                    raise TTSGenerationError(f"Модель не найдена: {model_path}")
                
                # Генерируем WAV
                wav_path = self.tts_dir / f"{base_filename}.wav"
                await self._run_piper(request.text, model_path, wav_path, request.speed)
                
                # Конвертируем в целевой формат если нужно
                final_path = wav_path
                if request.output_format != AudioFormat.WAV:
                    audio_service = AudioService(self.db_pool, self.redis)
                    final_path = await audio_service._convert_audio(
                        wav_path,
                        AudioFormat.WAV,
                        request.output_format
                    )
                    wav_path.unlink()  # Удаляем промежуточный WAV
                
                # Получаем метаданные
                audio_service = AudioService(self.db_pool, self.redis)
                metadata = await audio_service._get_audio_metadata(final_path, request.output_format)
                
                # Сохраняем в БД
                async with self.db_pool.acquire() as conn:
                    audio_id = await conn.fetchval("""
                        INSERT INTO audio_files (
                            name, description, file_path, file_name,
                            format, status, file_size, duration,
                            sample_rate, channels,
                            campaign_id, is_public,
                            tts_text, tts_voice, tts_model, tts_speed,
                            created_by, created_at, updated_at
                        ) VALUES (
                            $1, $2, $3, $4,
                            $5, $6, $7, $8,
                            $9, $10,
                            $11, $12,
                            $13, $14, $15, $16,
                            $17, NOW(), NOW()
                        )
                        RETURNING id
                    """,
                        request.name,
                        request.description,
                        str(final_path),
                        final_path.name,
                        request.output_format.value,
                        AudioStatus.READY.value,
                        metadata.file_size,
                        metadata.duration,
                        metadata.sample_rate,
                        metadata.channels,
                        request.campaign_id,
                        request.is_public,
                        request.text,
                        request.voice.value,
                        request.model.value,
                        request.speed,
                        user_id
                    )
                    
                    if request.tags:
                        await audio_service._add_audio_tags(conn, audio_id, request.tags)
                
                generation_time = (datetime.utcnow() - start_time).total_seconds()
                
                # Метрики
                audio_generated_counter.labels(
                    voice=request.voice.value,
                    format=request.output_format.value
                ).inc()
                tts_generation_duration.labels(
                    voice=request.voice.value,
                    model=request.model.value
                ).observe(generation_time)
                
                self._stats['generated'] += 1
                self._stats['total_duration'] += metadata.duration or 0
                
                logger.info(f"TTS сгенерирован: {request.name} ({metadata.duration:.1f}с, {generation_time:.1f}с)")
                
                return AudioGenerateResponse(
                    id=audio_id,
                    name=request.name,
                    file_path=str(final_path),
                    file_size=metadata.file_size or 0,
                    duration=metadata.duration,
                    format=request.output_format,
                    status="completed"
                )
                
            except Exception as e:
                self._stats['failed'] += 1
                logger.error(f"Ошибка генерации TTS: {e}")
                raise TTSGenerationError(f"Ошибка генерации TTS: {e}")
    
    async def _process_tts_queue(self):
        """Фоновая обработка очереди TTS"""
        while True:
            try:
                task_data = await self._tts_queue.get()
                
                request = task_data['request']
                user_id = task_data['user_id']
                task_id = task_data['task_id']
                
                try:
                    result = await self._generate_audio_sync(request, user_id)
                    
                    # Сохраняем результат в Redis
                    await self.redis.setex(
                        f"tts_result:{task_id}",
                        3600,
                        json.dumps({
                            'status': 'completed',
                            'audio_id': result.id,
                            'file_path': result.file_path,
                            'duration': result.duration
                        })
                    )
                except Exception as e:
                    await self.redis.setex(
                        f"tts_result:{task_id}",
                        3600,
                        json.dumps({
                            'status': 'failed',
                            'error': str(e)
                        })
                    )
                finally:
                    self._tts_queue.task_done()
                    tts_queue_size.set(self._tts_queue.qsize())
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в обработчике очереди TTS: {e}")
                await asyncio.sleep(1)
    
    async def _run_piper(
        self,
        text: str,
        model_path: Path,
        output_path: Path,
        speed: float
    ) -> None:
        """Запустить Piper для генерации речи"""
        # Piper параметры
        cmd = [
            'piper',
            '--model', str(model_path),
            '--output_file', str(output_path),
            '--length_scale', str(1.0 / speed),  # Инвертируем для piper
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate(input=text.encode('utf-8'))
            
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='ignore')[:500]
                raise TTSGenerationError(f"Piper error: {error_msg}")
            
            if not output_path.exists():
                raise TTSGenerationError("Файл не был создан")
                
        except FileNotFoundError:
            raise TTSGenerationError("Piper не установлен. Установите: pip install piper-tts")
        except Exception as e:
            raise TTSGenerationError(f"Ошибка Piper: {e}")
    
    def _get_model_path(self, voice: TTSVoice, model: TTSModel) -> Path:
        """Получить путь к модели Piper"""
        # Формат имени модели: ru_RU-{voice}-{model}.onnx
        voice_map = {
            TTSVoice.DENIS: 'denis',
            TTSVoice.IRINA: 'irina',
            TTSVoice.RUSLAN: 'ruslan',
            TTSVoice.DARIA: 'daria',
            TTSVoice.ALAN: 'alan',
            TTSVoice.JENNY: 'jenny',
            TTSVoice.THORSTEN: 'thorsten',
        }
        
        voice_name = voice_map.get(voice, 'denis')
        
        # Определяем язык
        if voice in [TTSVoice.DENIS, TTSVoice.IRINA, TTSVoice.RUSLAN, TTSVoice.DARIA]:
            lang = 'ru_RU'
        elif voice == TTSVoice.THORSTEN:
            lang = 'de_DE'
        else:
            lang = 'en_US'
        
        model_name = f"{lang}-{voice_name}-{model.value}.onnx"
        return self.models_dir / model_name
    
    async def preview_tts(self, request: TTSPreviewRequest) -> TTSPreviewResponse:
        """Предпрослушивание TTS"""
        # Генерируем временный файл
        temp_id = uuid.uuid4().hex
        temp_path = self.tts_dir / f"preview_{temp_id}.wav"
        
        model_path = self._get_model_path(request.voice, request.model)
        await self._run_piper(request.text, model_path, temp_path, request.speed)
        
        # Получаем длительность
        audio_service = AudioService(self.db_pool, self.redis)
        metadata = await audio_service._get_audio_metadata(temp_path, AudioFormat.WAV)
        
        # Сохраняем в Redis для доступа по URL
        await self.redis.setex(
            f"tts_preview:{temp_id}",
            300,  # 5 минут
            json.dumps({
                'path': str(temp_path),
                'expires': (datetime.utcnow().timestamp() + 300)
            })
        )
        
        return TTSPreviewResponse(
            audio_url=f"/api/audio/preview/{temp_id}",
            duration=metadata.duration or 0.0,
            expires_at=datetime.utcnow() + timedelta(seconds=300)
        )
    
    async def get_tts_info(self) -> TTSInfoResponse:
        """Получить информацию о TTS сервисе"""
        # Проверяем доступные модели
        available_voices = []
        for voice in TTSVoice:
            for model in TTSModel:
                model_path = self._get_model_path(voice, model)
                if model_path.exists():
                    available_voices.append({
                        'id': voice.value,
                        'name': voice.value.capitalize(),
                        'gender': 'male' if voice in [TTSVoice.DENIS, TTSVoice.RUSLAN, TTSVoice.ALAN, TTSVoice.THORSTEN] else 'female',
                        'language': 'ru' if voice in [TTSVoice.DENIS, TTSVoice.IRINA, TTSVoice.RUSLAN, TTSVoice.DARIA] else 'en',
                        'models': [m.value for m in TTSModel if self._get_model_path(voice, m).exists()]
                    })
        
        # Убираем дубликаты голосов
        unique_voices = {}
        for voice_info in available_voices:
            if voice_info['id'] not in unique_voices:
                unique_voices[voice_info['id']] = voice_info
            else:
                unique_voices[voice_info['id']]['models'].extend(voice_info['models'])
        
        return TTSInfoResponse(
            enabled=True,
            engine='piper',
            available_voices=list(unique_voices.values()),
            available_models=[m.value for m in TTSModel],
            max_text_length=settings.TTS_MAX_TEXT_LENGTH,
            supported_formats=[AudioFormat.WAV, AudioFormat.SLN],
            concurrent_limit=settings.TTS_MAX_CONCURRENT,
            current_queue_size=self._tts_queue.qsize()
        )
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Получить статус задачи TTS"""
        result = await self.redis.get(f"tts_result:{task_id}")
        if result:
            return json.loads(result)
        return {'status': 'queued' if task_id in str(self._tts_queue) else 'unknown'}
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            piper_available = False
            try:
                process = await asyncio.create_subprocess_exec(
                    'piper', '--help',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                piper_available = process.returncode == 0
            except:
                pass
            
            return {
                "status": "healthy",
                "piper_available": piper_available,
                "models_dir": str(self.models_dir),
                "models_dir_exists": self.models_dir.exists(),
                "queue_size": self._tts_queue.qsize(),
                "stats": self._stats
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
            try:
                await self._tts_task
            except asyncio.CancelledError:
                pass
        logger.info("TTSService остановлен")


# =============================================
# Глобальные экземпляры
# =============================================
_audio_service: Optional[AudioService] = None
_tts_service: Optional[TTSService] = None


def get_audio_service() -> AudioService:
    """Получить глобальный экземпляр AudioService"""
    global _audio_service
    if _audio_service is None:
        raise RuntimeError("AudioService не инициализирован")
    return _audio_service


def get_tts_service() -> TTSService:
    """Получить глобальный экземпляр TTSService"""
    global _tts_service
    if _tts_service is None:
        raise RuntimeError("TTSService не инициализирован")
    return _tts_service


def set_audio_service(service: AudioService) -> None:
    """Установить глобальный экземпляр AudioService"""
    global _audio_service
    _audio_service = service


def set_tts_service(service: TTSService) -> None:
    """Установить глобальный экземпляр TTSService"""
    global _tts_service
    _tts_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "AudioService",
    "TTSService",
    "AudioError",
    "AudioNotFoundError",
    "AudioValidationError",
    "TTSGenerationError",
    "AudioConversionError",
    "AudioUploadError",
    "get_audio_service",
    "get_tts_service",
    "set_audio_service",
    "set_tts_service",
]
