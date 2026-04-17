# app/api/audio.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление аудиофайлами и TTS
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from app.core.dependencies import get_current_user, require_admin, TokenData, PaginationParams
from app.services import get_audio_service, get_tts_service
from app.models.audio import (
    AudioGenerateRequest, AudioUploadRequest, AudioUpdateRequest,
    AudioResponse, AudioListResponse, AudioGenerateResponse,
    TTSInfoResponse, TTSPreviewRequest, TTSPreviewResponse,
    AudioFormat, AudioFilterRequest
)

router = APIRouter()


# =============================================
# Аудиофайлы
# =============================================
@router.get("/", response_model=AudioListResponse)
async def list_audio(
    pagination: PaginationParams = Depends(),
    format: Optional[List[AudioFormat]] = None,
    campaign_id: Optional[int] = None,
    is_public: Optional[bool] = None,
    search: Optional[str] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить список аудиофайлов"""
    audio_service = get_audio_service()
    
    filter_params = AudioFilterRequest(
        format=format,
        campaign_id=campaign_id,
        is_public=is_public,
        search=search
    )
    
    return await audio_service.list_audio(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.get("/{audio_id}", response_model=AudioResponse)
async def get_audio(
    audio_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить аудиофайл по ID"""
    audio_service = get_audio_service()
    audio = await audio_service.get_audio(audio_id)
    if not audio:
        raise HTTPException(404, "Audio not found")
    return audio


@router.patch("/{audio_id}", response_model=AudioResponse)
async def update_audio(
    audio_id: int,
    request: AudioUpdateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Обновить аудиофайл"""
    audio_service = get_audio_service()
    return await audio_service.update_audio(audio_id, request, user.user_id)


@router.delete("/{audio_id}")
async def delete_audio(
    audio_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Удалить аудиофайл"""
    audio_service = get_audio_service()
    await audio_service.delete_audio(audio_id, user.user_id)
    return {"status": "deleted"}


@router.get("/{audio_id}/download")
async def download_audio(
    audio_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Скачать аудиофайл"""
    audio_service = get_audio_service()
    path = await audio_service.get_audio_file_path(audio_id)
    
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"audio_{audio_id}{path.suffix}"
    )


@router.get("/{audio_id}/stream")
async def stream_audio(
    audio_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Потоковое воспроизведение аудио"""
    audio_service = get_audio_service()
    path = await audio_service.get_audio_file_path(audio_id)
    
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Content-Disposition": "inline"}
    )


@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    campaign_id: Optional[int] = Form(None),
    is_public: bool = Form(False),
    convert_to: Optional[AudioFormat] = Form(None),
    user: TokenData = Depends(get_current_user)
):
    """Загрузить аудиофайл"""
    audio_service = get_audio_service()
    
    request = AudioUploadRequest(
        name=name,
        description=description,
        campaign_id=campaign_id,
        is_public=is_public,
        convert_to=convert_to
    )
    
    return await audio_service.upload_audio(file.file, file.filename, request, user.user_id)


@router.post("/convert/{audio_id}")
async def convert_audio(
    audio_id: int,
    target_format: AudioFormat,
    user: TokenData = Depends(get_current_user)
):
    """Конвертировать аудио в другой формат"""
    audio_service = get_audio_service()
    return await audio_service.convert_audio(audio_id, target_format, user.user_id)


# =============================================
# TTS (Text-to-Speech)
# =============================================
@router.get("/tts/info", response_model=TTSInfoResponse)
async def get_tts_info(user: TokenData = Depends(get_current_user)):
    """Получить информацию о TTS"""
    tts_service = get_tts_service()
    return await tts_service.get_tts_info()


@router.post("/tts/generate", response_model=AudioGenerateResponse)
async def generate_tts(
    request: AudioGenerateRequest,
    background: bool = False,
    user: TokenData = Depends(get_current_user)
):
    """Сгенерировать аудио через TTS"""
    tts_service = get_tts_service()
    return await tts_service.generate_audio(request, user.user_id, background)


@router.post("/tts/preview", response_model=TTSPreviewResponse)
async def preview_tts(
    request: TTSPreviewRequest,
    user: TokenData = Depends(get_current_user)
):
    """Предпрослушивание TTS"""
    tts_service = get_tts_service()
    return await tts_service.preview_tts(request)


@router.get("/tts/task/{task_id}")
async def get_tts_task_status(
    task_id: str,
    user: TokenData = Depends(get_current_user)
):
    """Получить статус задачи TTS"""
    tts_service = get_tts_service()
    return await tts_service.get_task_status(task_id)


@router.get("/preview/{preview_id}")
async def stream_preview(
    preview_id: str,
    user: TokenData = Depends(get_current_user)
):
    """Потоковое воспроизведение предпрослушивания TTS"""
    from app.core.redis import get_redis_client
    import json
    from pathlib import Path
    
    redis_client = get_redis_client()
    data = await redis_client.get(f"tts_preview:{preview_id}")
    
    if not data:
        raise HTTPException(404, "Preview not found or expired")
    
    preview = json.loads(data)
    path = Path(preview['path'])
    
    if not path.exists():
        raise HTTPException(404, "Preview file not found")
    
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Content-Disposition": "inline"}
    )
