#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления входящими звонками
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Обработки webhook от Asterisk
- Управления записями входящих звонков
- Транскрибации записей
- Статистики входящих звонков
- Очистки старых записей
"""

import os
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import BackgroundTasks

from app.core.config import settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.incoming import (
    TranscriptionStatus, IncomingCallStatus, TranscriptionEngine,
    IncomingCallWebhookRequest, IncomingCallWebhookResponse,
    IncomingCallUpdateRequest, IncomingCallTranscribeRequest,
    IncomingCallResponse, IncomingCallDetailResponse, IncomingCallListResponse,
    IncomingCallStatsResponse, IncomingCallFilterRequest,
    IncomingCallBulkActionRequest, IncomingCallBulkActionResponse,
    TranscriptionTaskResponse, TranscriptionInfoResponse,
    normalize_phone, format_phone_display
)
from app.services.transcription import TranscriptionService, get_transcription_service
from prometheus_client import Counter, Gauge, Histogram


# =============================================
# Метрики
# =============================================
incoming_calls_total = Counter(
    'autodialer_incoming_calls_total',
    'Total incoming calls',
    ['status']
)
incoming_calls_duration = Histogram(
    'autodialer_incoming_calls_duration_seconds',
    'Incoming call duration',
    buckets=[10, 30, 60, 120, 180, 300, 600, 1200, 1800]
)
incoming_recordings_size = Gauge(
    'autodialer_incoming_recordings_size_bytes',
    'Total size of incoming recordings'
)
transcription_tasks_gauge = Gauge(
    'autodialer_transcription_tasks',
    'Transcription tasks in queue'
)


# =============================================
# Исключения
# =============================================
class IncomingCallError(Exception):
    """Базовое исключение сервиса входящих звонков"""
    pass


class IncomingCallNotFoundError(IncomingCallError):
    """Звонок не найден"""
    pass


class RecordingNotFoundError(IncomingCallError):
    """Запись не найдена"""
    pass


class TranscriptionAlreadyInProgressError(IncomingCallError):
    """Транскрибация уже выполняется"""
    pass


# =============================================
# Сервис входящих звонков
# =============================================
class IncomingCallService:
    """
    Сервис управления входящими звонками.
    
    Отвечает за:
    - Обработку webhook от Asterisk
    - Управление записями
    - Запуск транскрибации
    - Статистику
    - Очистку старых записей
    """
    
    def __init__(
        self,
        db_pool: ConnectionPool,
        redis_client: RedisClient,
        transcription_service: Optional[TranscriptionService] = None
    ):
        self.db_pool = db_pool
        self.redis = redis_client
        self.transcription_service = transcription_service or get_transcription_service()
        
        # Директория для записей
        self.recordings_dir = Path(settings.RECORDINGS_DIR)
        
        logger.info("IncomingCallService инициализирован")
    
    # =============================================
    # Обработка Webhook
    # =============================================
    async def process_webhook(
        self,
        request: IncomingCallWebhookRequest,
        background_tasks: Optional[BackgroundTasks] = None
    ) -> IncomingCallWebhookResponse:
        """
        Обработать webhook от Asterisk.
        
        Args:
            request: Данные webhook
            background_tasks: Фоновые задачи FastAPI
        
        Returns:
            Ответ на webhook
        """
        # Проверяем обязательные поля
        if not request.caller_number:
            raise IncomingCallError("caller_number is required")
        
        if not request.recording_path:
            raise IncomingCallError("recording_path is required")
        
        # Нормализуем номер
        caller_number = normalize_phone(request.caller_number)
        
        # Проверяем существование файла
        recording_path = Path(request.recording_path)
        if not recording_path.exists():
            logger.error(f"Файл записи не найден: {recording_path}")
            raise RecordingNotFoundError(f"Recording file not found: {recording_path}")
        
        # Получаем размер файла
        file_size = request.file_size or recording_path.stat().st_size
        
        async with self.db_pool.acquire() as conn:
            # Проверяем, не существует ли уже запись с таким unique_id
            if request.unique_id:
                existing = await conn.fetchval("""
                    SELECT id FROM incoming_calls WHERE unique_id = $1
                """, request.unique_id)
                
                if existing:
                    logger.info(f"Звонок с unique_id {request.unique_id} уже существует")
                    return IncomingCallWebhookResponse(
                        success=True,
                        message="Call already processed",
                        call_id=existing,
                        transcription_queued=False
                    )
            
            # Создаём запись
            call_id = await conn.fetchval("""
                INSERT INTO incoming_calls (
                    caller_number, caller_name,
                    called_number,
                    recording_path, recording_format,
                    duration, file_size,
                    unique_id, linked_id,
                    language,
                    status, transcription_status,
                    call_date, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NOW(), NOW()
                )
                RETURNING id
            """,
                caller_number,
                request.caller_name,
                normalize_phone(request.called_number) if request.called_number else None,
                str(recording_path),
                request.recording_format,
                request.duration,
                file_size,
                request.unique_id,
                request.linked_id,
                request.language or "ru",
                IncomingCallStatus.NEW.value,
                TranscriptionStatus.PENDING.value
            )
            
            # Сохраняем метаданные
            if request.metadata:
                await conn.execute("""
                    UPDATE incoming_calls SET metadata = $1 WHERE id = $2
                """, json.dumps(request.metadata), call_id)
            
            # Находим или создаём контакт
            contact_id = await self._find_or_create_contact(conn, caller_number, request.caller_name)
            if contact_id:
                await conn.execute("""
                    UPDATE incoming_calls SET contact_id = $1 WHERE id = $2
                """, contact_id, call_id)
            
            # Логируем
            await self._log_audit(conn, None, 'incoming_call_received', 'incoming_call', call_id, {
                'caller_number': caller_number,
                'duration': request.duration
            })
        
        # Метрики
        incoming_calls_total.labels(status='received').inc()
        if request.duration:
            incoming_calls_duration.observe(request.duration)
        if file_size:
            incoming_recordings_size.inc(file_size)
        
        logger.info(f"Входящий звонок сохранён: {caller_number} (ID: {call_id})")
        
        # Запускаем транскрибацию в фоне
        transcription_queued = False
        if request.auto_transcribe and self.transcription_service:
            if background_tasks:
                background_tasks.add_task(
                    self._transcribe_call,
                    call_id,
                    str(recording_path),
                    request.language or "ru"
                )
            else:
                asyncio.create_task(
                    self._transcribe_call(
                        call_id,
                        str(recording_path),
                        request.language or "ru"
                    )
                )
            transcription_queued = True
        
        return IncomingCallWebhookResponse(
            success=True,
            message="Incoming call recorded",
            call_id=call_id,
            transcription_queued=transcription_queued
        )
    
    async def _transcribe_call(self, call_id: int, recording_path: str, language: str):
        """
        Фоновая транскрибация звонка.
        
        Args:
            call_id: ID звонка
            recording_path: Путь к записи
            language: Язык
        """
        try:
            # Ждём немного, чтобы файл дописался
            await asyncio.sleep(2)
            
            # Проверяем существование файла
            if not os.path.exists(recording_path):
                raise RecordingNotFoundError(f"Recording file not found: {recording_path}")
            
            # Обновляем статус
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE incoming_calls 
                    SET transcription_status = $1, updated_at = NOW()
                    WHERE id = $2
                """, TranscriptionStatus.PROCESSING.value, call_id)
            
            # Транскрибация
            text = await self.transcription_service.transcribe(recording_path, language)
            status = TranscriptionStatus.COMPLETED if text is not None else TranscriptionStatus.FAILED
            engine = self.transcription_service.engine.value if self.transcription_service.engine else None
            
            # Сохраняем результат
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE incoming_calls 
                    SET transcription = $1, 
                        transcription_status = $2,
                        transcription_engine = $3,
                        updated_at = NOW()
                    WHERE id = $4
                """, text or "", status.value, engine, call_id)
                
                # Сохраняем в Redis для быстрого доступа
                await self.redis.setex(
                    f"transcription:{call_id}",
                    86400,  # 24 часа
                    json.dumps({
                        "text": text,
                        "status": status.value,
                        "engine": engine,
                        "completed_at": datetime.utcnow().isoformat()
                    })
                )
            
            logger.info(f"Транскрибация завершена для звонка {call_id}: {status.value}")
            
        except Exception as e:
            logger.error(f"Ошибка транскрибации звонка {call_id}: {e}")
            
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE incoming_calls 
                    SET transcription_status = $1, 
                        transcription_error = $2,
                        updated_at = NOW()
                    WHERE id = $3
                """, TranscriptionStatus.FAILED.value, str(e)[:500], call_id)
    
    # =============================================
    # CRUD операции
    # =============================================
    async def get_incoming_call(self, call_id: int) -> Optional[IncomingCallDetailResponse]:
        """Получить входящий звонок по ID"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    ic.*,
                    c.name as contact_name,
                    COALESCE(u.full_name, u.username) as listened_by_name
                FROM incoming_calls ic
                LEFT JOIN contacts c ON ic.contact_id = c.id
                LEFT JOIN users u ON ic.listened_by = u.id
                WHERE ic.id = $1
            """, call_id)
            
            if not row:
                return None
            
            # Получаем теги
            tags = await self._get_call_tags(conn, call_id)
            
            # Получаем историю прослушиваний
            listen_history = await self._get_listen_history(conn, call_id)
            
            # Получаем связанные звонки
            related_calls = await self._get_related_calls(conn, row['caller_number'], call_id)
            
            # Получаем сегменты транскрибации если есть
            transcription_segments = await self._get_transcription_segments(conn, call_id)
            
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            
            return IncomingCallDetailResponse(
                id=row['id'],
                caller_number=row['caller_number'],
                caller_number_display=format_phone_display(row['caller_number']),
                caller_name=row['caller_name'],
                called_number=row['called_number'],
                called_number_display=format_phone_display(row['called_number']) if row['called_number'] else None,
                call_date=row['call_date'],
                duration=row['duration'],
                duration_formatted=self._format_duration(row['duration']),
                file_size=row['file_size'],
                file_size_human=self._format_file_size(row['file_size']),
                recording_path=row['recording_path'],
                recording_url=f"/api/incoming-calls/{row['id']}/recording",
                recording_format=row['recording_format'] or "wav",
                transcription=row['transcription'],
                transcription_status=TranscriptionStatus(row['transcription_status']) if row['transcription_status'] else TranscriptionStatus.PENDING,
                transcription_engine=row['transcription_engine'],
                transcription_error=row['transcription_error'],
                language=row['language'] or "ru",
                listened=row['listened'],
                listened_at=row['listened_at'],
                listened_by=row['listened_by'],
                listened_by_name=row['listened_by_name'],
                status=IncomingCallStatus(row['status']) if row['status'] else IncomingCallStatus.NEW,
                notes=row['notes'],
                tags=tags,
                contact_id=row['contact_id'],
                contact_name=row['contact_name'],
                unique_id=row['unique_id'],
                linked_id=row['linked_id'],
                metadata=metadata,
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                transcription_segments=transcription_segments,
                listen_history=listen_history,
                related_calls=related_calls,
                contact_details=None,
                sentiment=None,
                keywords=[],
                summary=None
            )
    
    async def list_incoming_calls(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_params: Optional[IncomingCallFilterRequest] = None
    ) -> IncomingCallListResponse:
        """
        Получить список входящих звонков с фильтрацией.
        
        Args:
            page: Номер страницы
            page_size: Размер страницы
            filter_params: Параметры фильтрации
        
        Returns:
            Список звонков
        """
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            if filter_params:
                if filter_params.search:
                    where_conditions.append(f"""
                        (ic.caller_number LIKE ${param_idx} 
                         OR ic.caller_name ILIKE ${param_idx}
                         OR ic.transcription ILIKE ${param_idx})
                    """)
                    params.append(f"%{filter_params.search}%")
                    param_idx += 1
                
                if filter_params.caller_number:
                    where_conditions.append(f"ic.caller_number = ${param_idx}")
                    params.append(normalize_phone(filter_params.caller_number))
                    param_idx += 1
                
                if filter_params.called_number:
                    where_conditions.append(f"ic.called_number = ${param_idx}")
                    params.append(normalize_phone(filter_params.called_number))
                    param_idx += 1
                
                if filter_params.status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.status))])
                    where_conditions.append(f"ic.status IN ({placeholders})")
                    params.extend(list(filter_params.status))
                    param_idx += len(filter_params.status)

                if filter_params.transcription_status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.transcription_status))])
                    where_conditions.append(f"ic.transcription_status IN ({placeholders})")
                    params.extend(list(filter_params.transcription_status))
                    param_idx += len(filter_params.transcription_status)
                
                if filter_params.listened is not None:
                    where_conditions.append(f"ic.listened = ${param_idx}")
                    params.append(filter_params.listened)
                    param_idx += 1
                
                if filter_params.tags:
                    where_conditions.append(f"""
                        ic.id IN (
                            SELECT incoming_call_id FROM incoming_call_tags 
                            WHERE tag = ANY(${param_idx})
                        )
                    """)
                    params.append(filter_params.tags)
                    param_idx += 1
                
                if filter_params.min_duration is not None:
                    where_conditions.append(f"ic.duration >= ${param_idx}")
                    params.append(filter_params.min_duration)
                    param_idx += 1
                
                if filter_params.max_duration is not None:
                    where_conditions.append(f"ic.duration <= ${param_idx}")
                    params.append(filter_params.max_duration)
                    param_idx += 1
                
                if filter_params.from_date:
                    where_conditions.append(f"ic.call_date >= ${param_idx}")
                    params.append(filter_params.from_date)
                    param_idx += 1
                
                if filter_params.to_date:
                    where_conditions.append(f"ic.call_date <= ${param_idx}")
                    params.append(filter_params.to_date)
                    param_idx += 1
                
                if filter_params.has_transcription is not None:
                    if filter_params.has_transcription:
                        where_conditions.append("ic.transcription IS NOT NULL AND ic.transcription != ''")
                    else:
                        where_conditions.append("(ic.transcription IS NULL OR ic.transcription = '')")
                
                if filter_params.has_contact is not None:
                    if filter_params.has_contact:
                        where_conditions.append("ic.contact_id IS NOT NULL")
                    else:
                        where_conditions.append("ic.contact_id IS NULL")
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Общее количество
            count_query = f"SELECT COUNT(*) FROM incoming_calls ic {where_clause}"
            total = await conn.fetchval(count_query, *params)
            
            # Сводка
            summary = await self._get_list_summary(conn, where_clause, params)
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "call_date"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные
            query = f"""
                SELECT
                    ic.*,
                    c.name as contact_name,
                    COALESCE(u.full_name, u.username) as listened_by_name
                FROM incoming_calls ic
                LEFT JOIN contacts c ON ic.contact_id = c.id
                LEFT JOIN users u ON ic.listened_by = u.id
                {where_clause}
                ORDER BY ic.{sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = []
            for row in rows:
                tags = await self._get_call_tags(conn, row['id'])
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
                
                items.append(IncomingCallResponse(
                    id=row['id'],
                    caller_number=row['caller_number'],
                    caller_number_display=format_phone_display(row['caller_number']),
                    caller_name=row['caller_name'],
                    called_number=row['called_number'],
                    called_number_display=format_phone_display(row['called_number']) if row['called_number'] else None,
                    call_date=row['call_date'],
                    duration=row['duration'],
                    duration_formatted=self._format_duration(row['duration']),
                    file_size=row['file_size'],
                    file_size_human=self._format_file_size(row['file_size']),
                    recording_path=row['recording_path'],
                    recording_url=f"/api/incoming-calls/{row['id']}/recording",
                    recording_format=row['recording_format'] or "wav",
                    transcription=row['transcription'],
                    transcription_status=TranscriptionStatus(row['transcription_status']) if row['transcription_status'] else TranscriptionStatus.PENDING,
                    transcription_engine=row['transcription_engine'],
                    transcription_error=row['transcription_error'],
                    language=row['language'] or "ru",
                    listened=row['listened'],
                    listened_at=row['listened_at'],
                    listened_by=row['listened_by'],
                    listened_by_name=row['listened_by_name'],
                    status=IncomingCallStatus(row['status']) if row['status'] else IncomingCallStatus.NEW,
                    notes=row['notes'],
                    tags=tags,
                    contact_id=row['contact_id'],
                    contact_name=row['contact_name'],
                    unique_id=row['unique_id'],
                    linked_id=row['linked_id'],
                    metadata=metadata,
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                ))
            
            return IncomingCallListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size,
                summary=summary
            )
    
    async def update_incoming_call(
        self,
        call_id: int,
        request: IncomingCallUpdateRequest,
        user_id: Optional[int] = None
    ) -> bool:
        """
        Обновить входящий звонок.
        
        Args:
            call_id: ID звонка
            request: Данные для обновления
            user_id: ID пользователя
        
        Returns:
            True если обновлён
        """
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id FROM incoming_calls WHERE id = $1
            """, call_id)
            
            if not existing:
                raise IncomingCallNotFoundError(f"Звонок {call_id} не найден")
            
            updates = []
            params = []
            param_idx = 1
            
            if request.notes is not None:
                updates.append(f"notes = ${param_idx}")
                params.append(request.notes)
                param_idx += 1
            
            if request.listened is not None:
                updates.append(f"listened = ${param_idx}")
                if request.listened:
                    updates.append(f"listened_at = NOW()")
                    updates.append(f"listened_by = ${param_idx + 1}")
                    params.extend([request.listened, user_id])
                    param_idx += 2
                else:
                    params.append(request.listened)
                    param_idx += 1
            
            if request.status is not None:
                updates.append(f"status = ${param_idx}")
                params.append(request.status)
                param_idx += 1
            
            if request.tags is not None:
                await self._update_call_tags(conn, call_id, request.tags)
            
            if request.metadata is not None:
                updates.append(f"metadata = ${param_idx}")
                params.append(json.dumps(request.metadata))
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(call_id)
                query = f"""
                    UPDATE incoming_calls 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            await self._log_audit(conn, user_id, 'incoming_call_updated', 'incoming_call', call_id)
        
        logger.info(f"Входящий звонок {call_id} обновлён")
        return True
    
    async def mark_listened(self, call_id: int, user_id: Optional[int] = None) -> bool:
        """
        Отметить звонок как прослушанный.
        
        Args:
            call_id: ID звонка
            user_id: ID пользователя
        
        Returns:
            True если отмечен
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE incoming_calls 
                SET listened = TRUE, 
                    listened_at = NOW(),
                    listened_by = $1,
                    status = $2,
                    updated_at = NOW()
                WHERE id = $3 AND listened = FALSE
            """, user_id, IncomingCallStatus.LISTENED.value, call_id)
        
        return True
    
    async def delete_incoming_call(
        self,
        call_id: int,
        user_id: Optional[int] = None,
        delete_recording: bool = True
    ) -> bool:
        """
        Удалить входящий звонок.
        
        Args:
            call_id: ID звонка
            user_id: ID пользователя
            delete_recording: Удалить файл записи
        
        Returns:
            True если удалён
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT recording_path, file_size FROM incoming_calls WHERE id = $1
            """, call_id)
            
            if not row:
                raise IncomingCallNotFoundError(f"Звонок {call_id} не найден")
            
            # Удаляем файл
            if delete_recording and row['recording_path']:
                recording_path = Path(row['recording_path'])
                if recording_path.exists():
                    try:
                        recording_path.unlink()
                        logger.info(f"Файл записи удалён: {recording_path}")
                    except Exception as e:
                        logger.error(f"Ошибка удаления файла {recording_path}: {e}")
                
                # Обновляем метрику размера
                if row['file_size']:
                    incoming_recordings_size.dec(row['file_size'])
            
            # Удаляем связанные данные
            await conn.execute("DELETE FROM incoming_call_tags WHERE incoming_call_id = $1", call_id)
            await conn.execute("DELETE FROM incoming_call_events WHERE incoming_call_id = $1", call_id)
            
            # Удаляем запись
            await conn.execute("DELETE FROM incoming_calls WHERE id = $1", call_id)
            
            await self._log_audit(conn, user_id, 'incoming_call_deleted', 'incoming_call', call_id)
        
        incoming_calls_total.labels(status='deleted').inc()
        logger.info(f"Входящий звонок {call_id} удалён")
        
        return True
    
    # =============================================
    # Транскрибация
    # =============================================
    async def start_transcription(
        self,
        call_id: int,
        language: str = "ru",
        background_tasks: Optional[BackgroundTasks] = None
    ) -> Dict[str, Any]:
        """
        Запустить транскрибацию звонка.
        
        Args:
            call_id: ID звонка
            language: Язык
            background_tasks: Фоновые задачи
        
        Returns:
            Статус запуска
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT recording_path, transcription_status, updated_at FROM incoming_calls WHERE id = $1
            """, call_id)

            if not row:
                raise IncomingCallNotFoundError(f"Звонок {call_id} не найден")

            # "processing" зависает навсегда, если воркер, который его
            # обрабатывал, умер до финального UPDATE (например, backend
            # убило OOM killer'ом посреди транскрибации - подтверждено
            # живьём) - ничто и никогда не переводит такую запись в
            # failed/completed самостоятельно. Блокируем повтор только
            # если задача реально может быть ещё активна (обновлялась
            # недавно) - иначе разрешаем, иначе застрявшую запись было
            # бы вообще невозможно когда-либо повторить.
            processing_age = (datetime.utcnow() - row['updated_at']).total_seconds()
            if row['transcription_status'] == TranscriptionStatus.PROCESSING.value and processing_age < 300:
                raise TranscriptionAlreadyInProgressError("Транскрибация уже выполняется")
            
            if not os.path.exists(row['recording_path']):
                raise RecordingNotFoundError(f"Файл записи не найден: {row['recording_path']}")
            
            # Обновляем статус
            await conn.execute("""
                UPDATE incoming_calls 
                SET transcription_status = $1, updated_at = NOW()
                WHERE id = $2
            """, TranscriptionStatus.PENDING.value, call_id)
        
        # Запускаем транскрибацию
        if background_tasks:
            background_tasks.add_task(
                self._transcribe_call,
                call_id,
                row['recording_path'],
                language
            )
        else:
            asyncio.create_task(
                self._transcribe_call(
                    call_id,
                    row['recording_path'],
                    language
                )
            )
        
        logger.info(f"Транскрибация запущена для звонка {call_id}")
        
        return {
            "call_id": call_id,
            "status": "started",
            "language": language
        }
    
    async def get_transcription_status(self, call_id: int) -> Optional[TranscriptionTaskResponse]:
        """
        Получить статус транскрибации.
        
        Args:
            call_id: ID звонка
        
        Returns:
            Статус задачи
        """
        # Проверяем Redis сначала
        cached = await self.redis.get(f"transcription:{call_id}")
        if cached:
            data = json.loads(cached)
            return TranscriptionTaskResponse(
                call_id=call_id,
                status=TranscriptionStatus(data['status']),
                progress=100.0 if data['status'] == 'completed' else 0.0,
                completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
                engine=data.get('engine'),
                error=data.get('error')
            )
        
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    transcription_status,
                    transcription_engine,
                    transcription_error,
                    updated_at
                FROM incoming_calls 
                WHERE id = $1
            """, call_id)
            
            if not row:
                return None
            
            return TranscriptionTaskResponse(
                call_id=call_id,
                status=TranscriptionStatus(row['transcription_status']) if row['transcription_status'] else TranscriptionStatus.PENDING,
                progress=100.0 if row['transcription_status'] == 'completed' else 0.0,
                completed_at=row['updated_at'] if row['transcription_status'] == 'completed' else None,
                engine=row['transcription_engine'],
                error=row['transcription_error']
            )
    
    async def get_transcription_info(self) -> TranscriptionInfoResponse:
        """
        Получить информацию о сервисе транскрибации.
        
        Returns:
            Информация о сервисе
        """
        info = self.transcription_service.get_info()
        
        queue_size = await self.redis.llen(REDIS_KEYS.TRANSCRIPTION_QUEUE)
        
        return TranscriptionInfoResponse(
            enabled=info['engine'] != 'none',
            engine=info['engine'],
            model=info.get('model'),
            available_engines=list(info['available_engines'].keys()),
            queue_size=queue_size,
            active_tasks=info.get('active_tasks', 0),
            supported_languages=["ru", "en"],
            max_duration=300,
            max_file_size=25 * 1024 * 1024
        )
    
    # =============================================
    # Запись звонка
    # =============================================
    async def get_recording_path(self, call_id: int) -> Path:
        """
        Получить путь к записи звонка.
        
        Args:
            call_id: ID звонка
        
        Returns:
            Путь к файлу
        """
        async with self.db_pool.acquire() as conn:
            path = await conn.fetchval("""
                SELECT recording_path FROM incoming_calls WHERE id = $1
            """, call_id)
            
            if not path:
                raise RecordingNotFoundError(f"Запись для звонка {call_id} не найдена")
            
            recording_path = Path(path)
            if not recording_path.exists():
                raise RecordingNotFoundError(f"Файл записи не найден: {recording_path}")
            
            return recording_path
    
    # =============================================
    # Массовые операции
    # =============================================
    async def batch_action(
        self,
        request: IncomingCallBulkActionRequest,
        user_id: Optional[int] = None
    ) -> IncomingCallBulkActionResponse:
        """
        Выполнить массовое действие.
        
        Args:
            request: Запрос с действием
            user_id: ID пользователя
        
        Returns:
            Результат операции
        """
        result = IncomingCallBulkActionResponse(
            total=len(request.call_ids),
            successful=0,
            failed=0,
            errors=[]
        )
        
        for call_id in request.call_ids:
            try:
                if request.action == "mark_listened":
                    await self.mark_listened(call_id, user_id)
                elif request.action == "archive":
                    await self.update_incoming_call(
                        call_id,
                        IncomingCallUpdateRequest(status=IncomingCallStatus.ARCHIVED),
                        user_id
                    )
                elif request.action == "delete":
                    await self.delete_incoming_call(call_id, user_id)
                elif request.action == "transcribe":
                    await self.start_transcription(call_id)
                
                result.successful += 1
                
            except Exception as e:
                result.failed += 1
                result.errors.append({"call_id": call_id, "error": str(e)})
        
        logger.info(f"Массовое действие '{request.action}': {result.successful} успешно, {result.failed} ошибок")
        
        return result
    
    async def batch_delete(
        self,
        call_ids: List[int],
        user_id: Optional[int] = None
    ) -> int:
        """
        Массовое удаление звонков.
        
        Args:
            call_ids: Список ID
            user_id: ID пользователя
        
        Returns:
            Количество удалённых
        """
        deleted = 0
        
        for call_id in call_ids:
            try:
                await self.delete_incoming_call(call_id, user_id)
                deleted += 1
            except Exception as e:
                logger.error(f"Ошибка удаления звонка {call_id}: {e}")
        
        return deleted
    
    # =============================================
    # Статистика
    # =============================================
    async def get_stats(self, days: int = 30) -> IncomingCallStatsResponse:
        """
        Получить статистику входящих звонков.
        
        Args:
            days: Период в днях
        
        Returns:
            Статистика
        """
        from app.services.stats import StatsService
        stats_service = StatsService(self.db_pool, self.redis)
        return await stats_service.get_incoming_stats(days)
    
    # =============================================
    # Очистка старых записей
    # =============================================
    async def cleanup_old_calls(
        self,
        days: int = 30,
        user_id: Optional[int] = None
    ) -> int:
        """
        Очистить старые записи входящих звонков.
        
        Args:
            days: Старше N дней
            user_id: ID пользователя
        
        Returns:
            Количество удалённых
        """
        if days < 7:
            raise IncomingCallError("Days must be at least 7")
        
        async with self.db_pool.acquire() as conn:
            # Получаем старые записи
            rows = await conn.fetch("""
                SELECT id, recording_path, file_size
                FROM incoming_calls 
                WHERE call_date < NOW() - INTERVAL '1 day' * $1
            """, days)
            
            deleted = 0
            total_size = 0
            
            for row in rows:
                try:
                    # Удаляем файл
                    if row['recording_path']:
                        recording_path = Path(row['recording_path'])
                        if recording_path.exists():
                            recording_path.unlink()
                            if row['file_size']:
                                total_size += row['file_size']
                    
                    # Удаляем связанные данные
                    await conn.execute("DELETE FROM incoming_call_tags WHERE incoming_call_id = $1", row['id'])
                    
                    # Удаляем запись
                    await conn.execute("DELETE FROM incoming_calls WHERE id = $1", row['id'])
                    
                    deleted += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка очистки звонка {row['id']}: {e}")
            
            if deleted > 0:
                incoming_recordings_size.dec(total_size)
                
                await self._log_audit(conn, user_id, 'incoming_calls_cleanup', 'system', None, {
                    'deleted': deleted,
                    'older_than_days': days,
                    'freed_space': total_size
                })
        
        logger.info(f"Очищено {deleted} старых входящих звонков (>{days} дней)")
        
        return deleted
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _find_or_create_contact(
        self,
        conn,
        phone: str,
        name: Optional[str] = None
    ) -> Optional[int]:
        """Найти или создать контакт"""
        # Ищем существующий
        contact_id = await conn.fetchval("""
            SELECT id FROM contacts WHERE phone = $1
        """, phone)
        
        if contact_id:
            return contact_id
        
        # Создаём новый
        contact_id = await conn.fetchval("""
            INSERT INTO contacts (phone, name, source, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, NOW(), NOW())
            RETURNING id
        """, phone, name, 'incoming', 'active')
        
        return contact_id
    
    async def _get_call_tags(self, conn, call_id: int) -> List[str]:
        rows = await conn.fetch("""
            SELECT tag FROM incoming_call_tags WHERE incoming_call_id = $1
        """, call_id)
        return [row['tag'] for row in rows]
    
    async def _update_call_tags(self, conn, call_id: int, tags: List[str]) -> None:
        await conn.execute("DELETE FROM incoming_call_tags WHERE incoming_call_id = $1", call_id)
        for tag in tags:
            await conn.execute("""
                INSERT INTO incoming_call_tags (incoming_call_id, tag)
                VALUES ($1, $2)
            """, call_id, tag)
    
    async def _get_listen_history(self, conn, call_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT * FROM incoming_call_events 
            WHERE incoming_call_id = $1 AND event_type = 'listened'
            ORDER BY created_at DESC
        """, call_id)
        return [dict(row) for row in rows]
    
    async def _get_related_calls(
        self,
        conn,
        caller_number: str,
        exclude_id: int,
        limit: int = 10
    ) -> List[IncomingCallResponse]:
        rows = await conn.fetch("""
            SELECT id FROM incoming_calls 
            WHERE caller_number = $1 AND id != $2
            ORDER BY call_date DESC
            LIMIT $3
        """, caller_number, exclude_id, limit)
        
        related = []
        for row in rows:
            call = await self.get_incoming_call(row['id'])
            if call:
                related.append(call)
        
        return related
    
    async def _get_transcription_segments(self, conn, call_id: int) -> Optional[List[Dict[str, Any]]]:
        row = await conn.fetchrow("""
            SELECT transcription_segments FROM incoming_calls WHERE id = $1
        """, call_id)
        
        if row and row['transcription_segments']:
            return json.loads(row['transcription_segments'])
        return None
    
    async def _get_list_summary(
        self,
        conn,
        where_clause: str,
        params: List
    ) -> Dict[str, Any]:
        """Получить сводку по списку"""
        summary = {}
        
        # По статусам
        status_rows = await conn.fetch(f"""
            SELECT status, COUNT(*) as count
            FROM incoming_calls ic
            {where_clause}
            GROUP BY status
        """, *params)
        summary['by_status'] = {row['status']: row['count'] for row in status_rows}
        
        # По статусам транскрибации
        trans_rows = await conn.fetch(f"""
            SELECT transcription_status, COUNT(*) as count
            FROM incoming_calls ic
            {where_clause}
            GROUP BY transcription_status
        """, *params)
        summary['by_transcription'] = {row['transcription_status']: row['count'] for row in trans_rows}
        
        # Общая длительность
        total_duration = await conn.fetchval(f"""
            SELECT COALESCE(SUM(duration), 0) FROM incoming_calls ic {where_clause}
        """, *params)
        summary['total_duration'] = total_duration
        
        return summary
    
    def _format_duration(self, duration: Optional[int]) -> Optional[str]:
        """Форматирование длительности"""
        if duration is None:
            return None
        
        minutes = duration // 60
        seconds = duration % 60
        return f"{minutes:02d}:{seconds:02d}"
    
    def _format_file_size(self, size: Optional[int]) -> Optional[str]:
        """Форматирование размера файла"""
        if size is None:
            return None
        
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.2f} MB"
    
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
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, action, entity_type, entity_id, json.dumps(details) if details else None)
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            # Получаем количество записей
            count = await self.db_pool.fetchval("SELECT COUNT(*) FROM incoming_calls")
            
            return {
                "status": "healthy",
                "total_calls": count or 0,
                "recordings_dir": str(self.recordings_dir),
                "recordings_dir_exists": self.recordings_dir.exists()
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        logger.info("IncomingCallService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_incoming_call_service: Optional[IncomingCallService] = None


def get_incoming_call_service() -> IncomingCallService:
    """Получить глобальный экземпляр IncomingCallService"""
    global _incoming_call_service
    if _incoming_call_service is None:
        raise RuntimeError("IncomingCallService не инициализирован")
    return _incoming_call_service


def set_incoming_call_service(service: IncomingCallService) -> None:
    """Установить глобальный экземпляр IncomingCallService"""
    global _incoming_call_service
    _incoming_call_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "IncomingCallService",
    "IncomingCallError",
    "IncomingCallNotFoundError",
    "RecordingNotFoundError",
    "TranscriptionAlreadyInProgressError",
    "get_incoming_call_service",
    "set_incoming_call_service",
]
