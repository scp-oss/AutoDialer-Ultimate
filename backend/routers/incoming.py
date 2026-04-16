#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Router для входящих звонков
AutoDialer Ultimate v3.0.0

Предоставляет эндпоинты для:
- Получения списка входящих звонков
- Получения записи звонка
- Удаления записи
- Webhook для приёма уведомлений от Asterisk
- Статистики по входящим звонкам
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from logger import logger
from auth import TokenData, get_current_user, require_admin
from schemas import (
    IncomingCallResponse,
    IncomingCallDetailResponse,
    IncomingCallUpdateRequest,
    IncomingCallStatsResponse,
    IncomingCallWebhookRequest,
    PaginatedResponse,
    SuccessResponse,
    ErrorResponse
)

# =============================================
# Router
# =============================================
router = APIRouter(prefix="/api/incoming-calls", tags=["Incoming Calls"])

# Глобальные переменные (будут установлены при инициализации)
db_pool = None
redis_client = None
transcription_service = None


def init_incoming_router(pool, redis, transcription_svc):
    """Инициализация роутера зависимостями"""
    global db_pool, redis_client, transcription_service
    db_pool = pool
    redis_client = redis
    transcription_service = transcription_svc


# =============================================
# Webhook для Asterisk
# =============================================
@router.post("/webhook", response_model=SuccessResponse)
async def incoming_call_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Webhook для приёма уведомлений о входящих звонках от Asterisk.
    
    Вызывается после завершения записи входящего звонка.
    Автоматически запускает транскрибацию в фоне.
    """
    try:
        # Получаем данные из запроса
        data = await request.json()
        
        caller_number = data.get("caller_number")
        recording_path = data.get("recording_path")
        duration = data.get("duration")
        file_size = data.get("file_size")
        
        if not caller_number or not recording_path:
            return ErrorResponse(
                error="Missing required fields",
                detail="caller_number and recording_path are required"
            )
        
        # Проверяем существование файла
        if not os.path.exists(recording_path):
            logger.error(f"Recording file not found: {recording_path}")
            return ErrorResponse(
                error="File not found",
                detail=f"Recording file not found: {recording_path}"
            )
        
        # Сохраняем запись в БД
        async with db_pool.acquire() as conn:
            call_id = await conn.fetchval("""
                INSERT INTO incoming_calls 
                (caller_number, recording_path, duration, file_size, transcription_status)
                VALUES ($1, $2, $3, $4, 'pending')
                RETURNING id
            """, caller_number, recording_path, duration, file_size)
        
        logger.info(f"Incoming call {call_id} from {caller_number} saved")
        
        # Автоматически запускаем транскрибацию в фоне
        background_tasks.add_task(
            auto_transcribe,
            call_id,
            recording_path,
            data.get("language", "ru")
        )
        
        return SuccessResponse(
            success=True,
            message="Incoming call recorded",
            data={"call_id": call_id}
        )
        
    except json.JSONDecodeError:
        return ErrorResponse(error="Invalid JSON", detail="Request body must be valid JSON")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return ErrorResponse(error="Internal server error", detail=str(e))


async def auto_transcribe(call_id: int, recording_path: str, language: str = "ru"):
    """
    Автоматическая транскрибация в фоне.
    
    Args:
        call_id: ID записи в БД
        recording_path: Путь к аудиофайлу
        language: Язык аудио
    """
    try:
        # Обновляем статус
        await db_pool.execute(
            "UPDATE incoming_calls SET transcription_status = 'processing' WHERE id = $1",
            call_id
        )
        
        # Ждём немного, чтобы файл точно дописался
        await asyncio.sleep(2)
        
        # Проверяем существование файла
        if not os.path.exists(recording_path):
            raise FileNotFoundError(f"Recording file not found: {recording_path}")
        
        # Транскрибация
        text = await transcription_service.transcribe(recording_path, language)
        status = 'completed' if text is not None else 'failed'
        
        # Сохраняем результат
        await db_pool.execute("""
            UPDATE incoming_calls 
            SET transcription = $1, transcription_status = $2 
            WHERE id = $3
        """, text or "", status, call_id)
        
        logger.info(f"Auto-transcription for call {call_id} completed: {status}")
        
    except FileNotFoundError as e:
        logger.error(f"Auto-transcription file error for call {call_id}: {e}")
        await db_pool.execute(
            "UPDATE incoming_calls SET transcription_status = 'failed' WHERE id = $1",
            call_id
        )
    except Exception as e:
        logger.error(f"Auto-transcription failed for call {call_id}: {e}")
        await db_pool.execute(
            "UPDATE incoming_calls SET transcription_status = 'failed' WHERE id = $1",
            call_id
        )


# =============================================
# Ручной запуск транскрибации
# =============================================
@router.post("/{call_id}/transcribe", response_model=SuccessResponse)
async def manual_transcribe(
    call_id: int,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Ручной запуск транскрибации для существующей записи.
    
    Доступно только admin и operator.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT recording_path, transcription_status FROM incoming_calls WHERE id = $1",
            call_id
        )
        
        if not row:
            raise HTTPException(404, "Call not found")
        
        if row['transcription_status'] in ('processing', 'completed'):
            return SuccessResponse(
                success=True,
                message=f"Transcription already {row['transcription_status']}",
                data={"call_id": call_id, "status": row['transcription_status']}
            )
        
        if not os.path.exists(row['recording_path']):
            raise HTTPException(404, "Recording file not found")
    
    # Запускаем транскрибацию в фоне
    background_tasks.add_task(auto_transcribe, call_id, row['recording_path'])
    
    logger.info(f"Manual transcription started for call {call_id} by {current_user.username}")
    
    return SuccessResponse(
        success=True,
        message="Transcription started",
        data={"call_id": call_id, "status": "processing"}
    )


# =============================================
# Получение списка входящих звонков
# =============================================
@router.get("/", response_model=PaginatedResponse)
async def list_incoming_calls(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Получение списка входящих звонков с пагинацией.
    
    Query params:
        page: Номер страницы (по умолчанию 1)
        page_size: Размер страницы (по умолчанию 20, макс 100)
        status: Фильтр по статусу транскрибации (pending/processing/completed/failed)
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20
    
    offset = (page - 1) * page_size
    
    async with db_pool.acquire() as conn:
        # Строим запрос с фильтром
        query = "SELECT * FROM incoming_calls"
        count_query = "SELECT COUNT(*) FROM incoming_calls"
        params = []
        
        if status:
            query += " WHERE transcription_status = $1"
            count_query += " WHERE transcription_status = $1"
            params.append(status)
        
        query += " ORDER BY call_date DESC LIMIT $1 OFFSET $2"
        
        if status:
            params.extend([page_size, offset])
        else:
            params.extend([page_size, offset])
            if not status:
                # Для запроса без фильтра
                pass
        
        # Выполняем запросы
        if status:
            rows = await conn.fetch(query, status, page_size, offset)
            total = await conn.fetchval(count_query, status)
        else:
            rows = await conn.fetch(query, page_size, offset)
            total = await conn.fetchval(count_query)
        
        items = []
        for row in rows:
            item = dict(row)
            # Добавляем URL для скачивания
            item['recording_url'] = f"/api/incoming-calls/{row['id']}/recording"
            items.append(item)
    
    total_pages = (total + page_size - 1) // page_size
    
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# =============================================
# Получение детальной информации о звонке
# =============================================
@router.get("/{call_id}", response_model=IncomingCallDetailResponse)
async def get_incoming_call(
    call_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Получение детальной информации о входящем звонке.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM incoming_calls WHERE id = $1",
            call_id
        )
        
        if not row:
            raise HTTPException(404, "Call not found")
        
        # Отмечаем как прослушанный
        await conn.execute(
            "UPDATE incoming_calls SET listened = TRUE WHERE id = $1",
            call_id
        )
        
        item = dict(row)
        item['recording_url'] = f"/api/incoming-calls/{call_id}/recording"
        
        return IncomingCallDetailResponse(**item)


# =============================================
# Обновление информации о звонке
# =============================================
@router.patch("/{call_id}", response_model=SuccessResponse)
async def update_incoming_call(
    call_id: int,
    update_data: IncomingCallUpdateRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Обновление информации о входящем звонке (заметки, статус прослушивания).
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM incoming_calls WHERE id = $1", call_id)
        if not row:
            raise HTTPException(404, "Call not found")
        
        updates = []
        params = []
        param_idx = 1
        
        if update_data.notes is not None:
            updates.append(f"notes = ${param_idx}")
            params.append(update_data.notes)
            param_idx += 1
        
        if update_data.listened is not None:
            updates.append(f"listened = ${param_idx}")
            params.append(update_data.listened)
            param_idx += 1
        
        if updates:
            params.append(call_id)
            query = f"UPDATE incoming_calls SET {', '.join(updates)} WHERE id = ${param_idx}"
            await conn.execute(query, *params)
    
    return SuccessResponse(
        success=True,
        message="Call updated",
        data={"call_id": call_id}
    )


# =============================================
# Получение записи звонка
# =============================================
@router.get("/{call_id}/recording")
async def get_recording(
    call_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Получение аудиозаписи входящего звонка.
    
    Возвращает WAV-файл для прослушивания или скачивания.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT recording_path FROM incoming_calls WHERE id = $1",
            call_id
        )
        
        if not row:
            raise HTTPException(404, "Call not found")
        
        recording_path = row['recording_path']
        
        if not os.path.exists(recording_path):
            raise HTTPException(404, "Recording file not found")
        
        # Отмечаем как прослушанный
        await conn.execute(
            "UPDATE incoming_calls SET listened = TRUE WHERE id = $1",
            call_id
        )
        
        # Определяем media type
        if recording_path.endswith('.wav'):
            media_type = "audio/wav"
        elif recording_path.endswith('.mp3'):
            media_type = "audio/mpeg"
        else:
            media_type = "application/octet-stream"
        
        filename = f"incoming_{call_id}_{os.path.basename(recording_path)}"
        
        return FileResponse(
            recording_path,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )


# =============================================
# Удаление записи о звонке
# =============================================
@router.delete("/{call_id}", response_model=SuccessResponse)
async def delete_incoming_call(
    call_id: int,
    current_user: TokenData = Depends(require_admin)
):
    """
    Удаление записи о входящем звонке.
    
    Только для admin.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT recording_path FROM incoming_calls WHERE id = $1",
            call_id
        )
        
        if not row:
            raise HTTPException(404, "Call not found")
        
        # Удаляем файл записи
        if row['recording_path'] and os.path.exists(row['recording_path']):
            try:
                os.remove(row['recording_path'])
                logger.info(f"Recording file deleted: {row['recording_path']}")
            except Exception as e:
                logger.error(f"Failed to delete recording file: {e}")
        
        # Удаляем запись из БД
        await conn.execute("DELETE FROM incoming_calls WHERE id = $1", call_id)
    
    logger.info(f"Incoming call {call_id} deleted by {current_user.username}")
    
    return SuccessResponse(
        success=True,
        message="Call deleted",
        data={"call_id": call_id}
    )


# =============================================
# Пакетное удаление
# =============================================
@router.post("/batch-delete", response_model=SuccessResponse)
async def batch_delete_incoming_calls(
    call_ids: List[int],
    current_user: TokenData = Depends(require_admin)
):
    """
    Пакетное удаление записей о входящих звонках.
    
    Только для admin.
    """
    if not call_ids:
        return SuccessResponse(success=True, message="No calls to delete", data={"deleted": 0})
    
    deleted = 0
    async with db_pool.acquire() as conn:
        for call_id in call_ids:
            row = await conn.fetchrow(
                "SELECT recording_path FROM incoming_calls WHERE id = $1",
                call_id
            )
            
            if row:
                if row['recording_path'] and os.path.exists(row['recording_path']):
                    try:
                        os.remove(row['recording_path'])
                    except Exception:
                        pass
                
                await conn.execute("DELETE FROM incoming_calls WHERE id = $1", call_id)
                deleted += 1
    
    logger.info(f"Batch deleted {deleted} incoming calls by {current_user.username}")
    
    return SuccessResponse(
        success=True,
        message=f"Deleted {deleted} calls",
        data={"deleted": deleted}
    )


# =============================================
# Статистика по входящим звонкам
# =============================================
@router.get("/stats", response_model=IncomingCallStatsResponse)
async def get_incoming_stats(
    current_user: TokenData = Depends(get_current_user)
):
    """
    Получение статистики по входящим звонкам.
    """
    async with db_pool.acquire() as conn:
        # Общая статистика
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN transcription_status = 'pending' THEN 1 END) as pending,
                COUNT(CASE WHEN transcription_status = 'processing' THEN 1 END) as processing,
                COUNT(CASE WHEN transcription_status = 'completed' THEN 1 END) as completed,
                COUNT(CASE WHEN transcription_status = 'failed' THEN 1 END) as failed,
                AVG(duration) as avg_duration,
                SUM(duration) as total_duration
            FROM incoming_calls
        """)
        
        return IncomingCallStatsResponse(
            total=stats['total'] or 0,
            pending=stats['pending'] or 0,
            processing=stats['processing'] or 0,
            completed=stats['completed'] or 0,
            failed=stats['failed'] or 0,
            avg_duration=round(stats['avg_duration'] or 0, 2),
            total_duration=stats['total_duration'] or 0
        )


# =============================================
# Очистка старых записей (admin only)
# =============================================
@router.post("/cleanup", response_model=SuccessResponse)
async def cleanup_old_calls(
    days: int = 30,
    current_user: TokenData = Depends(require_admin)
):
    """
    Очистка старых записей о входящих звонках.
    
    Args:
        days: Удалить записи старше указанного количества дней (по умолчанию 30)
    """
    if days < 7:
        raise HTTPException(400, "Days must be at least 7")
    
    async with db_pool.acquire() as conn:
        # Получаем старые записи
        rows = await conn.fetch("""
            SELECT id, recording_path 
            FROM incoming_calls 
            WHERE call_date < NOW() - INTERVAL '1 day' * $1
        """, days)
        
        deleted = 0
        for row in rows:
            # Удаляем файл
            if row['recording_path'] and os.path.exists(row['recording_path']):
                try:
                    os.remove(row['recording_path'])
                except Exception:
                    pass
            
            # Удаляем запись
            await conn.execute("DELETE FROM incoming_calls WHERE id = $1", row['id'])
            deleted += 1
    
    logger.info(f"Cleaned up {deleted} old incoming calls (>{days} days) by {current_user.username}")
    
    return SuccessResponse(
        success=True,
        message=f"Cleaned up {deleted} calls older than {days} days",
        data={"deleted": deleted, "days": days}
    )
