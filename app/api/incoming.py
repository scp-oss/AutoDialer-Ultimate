# app/api/incoming.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Входящие звонки
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse

from app.core.dependencies import get_current_user, require_admin, TokenData, PaginationParams
from app.services import get_incoming_call_service, get_settings_service, get_audio_service
from app.models.incoming import (
    IncomingCallWebhookRequest, IncomingCallUpdateRequest,
    IncomingCallResponse, IncomingCallDetailResponse, IncomingCallListResponse,
    IncomingCallStatsResponse, IncomingCallFilterRequest,
    TranscriptionStatus
)

router = APIRouter()


@router.post("/webhook")
async def incoming_call_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Webhook для приёма уведомлений от Asterisk"""
    data = await request.json()

    webhook_request = IncomingCallWebhookRequest(**data)
    incoming_service = get_incoming_call_service()

    return await incoming_service.process_webhook(webhook_request, background_tasks)


# =============================================
# Приветствие для входящих (dialplan на стороне FreePBX)
# =============================================
# Без авторизации - как и /webhook выше, эти маршруты вызывает не браузер,
# а dialplan/AGI на стороне Asterisk/FreePBX (Answer -> запрос сюда, узнать
# что играть -> Playback -> Record -> POST /webhook как раньше). Отдаваемое
# аудио не приватные данные (это просто голосовое приветствие), так что тот
# же уровень доверия по сетевому расположению, что и у /webhook, достаточен.
@router.get("/greeting")
async def get_incoming_greeting_config():
    """
    Узнать, включено ли приветствие и какой ID аудио сейчас выбран
    (настраивается в веб-интерфейсе: Настройки -> Входящие).
    """
    settings_service = get_settings_service()
    enabled = await settings_service.get_setting_value("incoming.greeting_enabled")
    audio_id = await settings_service.get_setting_value("incoming.greeting_audio_id")
    return {"enabled": bool(enabled), "audio_id": audio_id or None}


@router.get("/greeting/audio")
async def download_incoming_greeting_audio():
    """
    Скачать текущий аудиофайл приветствия. Дialplan должен сохранить его
    локально на сервере Asterisk и проиграть через Playback() - Asterisk не
    умеет проигрывать звук напрямую по URL.
    """
    settings_service = get_settings_service()
    enabled = await settings_service.get_setting_value("incoming.greeting_enabled")
    audio_id = await settings_service.get_setting_value("incoming.greeting_audio_id")

    if not enabled or not audio_id:
        raise HTTPException(404, "Greeting is not configured or disabled")

    audio_service = get_audio_service()
    path = await audio_service.get_playable_audio_path(int(audio_id))

    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"greeting{path.suffix}"
    )


@router.get("/", response_model=IncomingCallListResponse)
async def list_incoming_calls(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = None,
    transcription_status: Optional[TranscriptionStatus] = None,
    listened: Optional[bool] = None,
    search: Optional[str] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить список входящих звонков"""
    incoming_service = get_incoming_call_service()
    
    filter_params = IncomingCallFilterRequest(
        status=status,
        transcription_status=[transcription_status] if transcription_status else None,
        listened=listened,
        search=search
    )
    
    return await incoming_service.list_incoming_calls(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.get("/stats", response_model=IncomingCallStatsResponse)
async def get_incoming_stats(
    days: Optional[int] = 30,
    user: TokenData = Depends(get_current_user)
):
    """Получить статистику входящих звонков"""
    incoming_service = get_incoming_call_service()
    return await incoming_service.get_stats(days=days)


# NOTE: /stats must be registered before /{call_id} - same
# FastAPI/Starlette route-ordering pitfall fixed elsewhere in contacts.py:
# a literal "stats" would otherwise get parsed as call_id:int and 422.
@router.get("/{call_id}", response_model=IncomingCallDetailResponse)
async def get_incoming_call(
    call_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить входящий звонок по ID"""
    incoming_service = get_incoming_call_service()
    call = await incoming_service.get_incoming_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    
    # Отмечаем как прослушанный
    await incoming_service.mark_listened(call_id, user.user_id)
    
    return call


@router.patch("/{call_id}")
async def update_incoming_call(
    call_id: int,
    request: IncomingCallUpdateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Обновить входящий звонок"""
    incoming_service = get_incoming_call_service()
    await incoming_service.update_incoming_call(call_id, request, user.user_id)
    return {"status": "updated"}


@router.delete("/{call_id}")
async def delete_incoming_call(
    call_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Удалить входящий звонок (admin only)"""
    incoming_service = get_incoming_call_service()
    await incoming_service.delete_incoming_call(call_id, admin.user_id)
    return {"status": "deleted"}


@router.get("/{call_id}/recording")
async def get_recording(
    call_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить запись входящего звонка"""
    incoming_service = get_incoming_call_service()
    path = await incoming_service.get_recording_path(call_id)
    
    # Отмечаем как прослушанный
    await incoming_service.mark_listened(call_id, user.user_id)
    
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"incoming_{call_id}.wav"
    )


@router.post("/{call_id}/transcribe")
async def transcribe_incoming_call(
    call_id: int,
    background_tasks: BackgroundTasks,
    language: str = "ru",
    user: TokenData = Depends(get_current_user)
):
    """Запустить транскрибацию входящего звонка"""
    incoming_service = get_incoming_call_service()
    return await incoming_service.start_transcription(call_id, language, background_tasks)


@router.post("/batch-delete")
async def batch_delete_incoming_calls(
    call_ids: list[int],
    admin: TokenData = Depends(require_admin)
):
    """Массовое удаление входящих звонков (admin only)"""
    incoming_service = get_incoming_call_service()
    deleted = await incoming_service.batch_delete(call_ids, admin.user_id)
    return {"deleted": deleted}


@router.post("/cleanup")
async def cleanup_old_calls(
    days: int = 30,
    admin: TokenData = Depends(require_admin)
):
    """Очистить старые входящие звонки (admin only)"""
    if days < 7:
        raise HTTPException(400, "Days must be at least 7")
    
    incoming_service = get_incoming_call_service()
    cleaned = await incoming_service.cleanup_old_calls(days, admin.user_id)
    return {"cleaned": cleaned, "days": days}
