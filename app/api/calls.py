# app/api/calls.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
История звонков и статистика
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.dependencies import get_current_user, require_admin, TokenData, PaginationParams, DateRangeParams
from app.services import get_call_service
from app.models.call import (
    CallHistoryFilterRequest, CallListResponse, CallDetailResponse,
    CallStatsResponse, DailyCallStatsResponse, CallAnalyticsResponse,
    ActiveCallsResponse, CallResultStatus
)

router = APIRouter()
stats_router = APIRouter()


# =============================================
# История звонков
# =============================================
@router.get("/history", response_model=CallListResponse)
async def list_calls(
    pagination: PaginationParams = Depends(),
    campaign_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    status: Optional[List[CallResultStatus]] = None,
    phone: Optional[str] = None,
    date_range: DateRangeParams = Depends(),
    user: TokenData = Depends(get_current_user)
):
    """Получить историю звонков"""
    call_service = get_call_service()
    
    filter_params = CallHistoryFilterRequest(
        campaign_id=campaign_id,
        contact_id=contact_id,
        status=status,
        phone=phone,
        from_date=date_range.from_date.date() if date_range.from_date else None,
        to_date=date_range.to_date.date() if date_range.to_date else None
    )
    
    return await call_service.list_calls(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.get("/{call_id}", response_model=CallDetailResponse)
async def get_call(
    call_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить детальную информацию о звонке"""
    call_service = get_call_service()
    call = await call_service.get_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return call


@router.delete("/{call_id}")
async def delete_call(
    call_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Удалить звонок (admin only)"""
    call_service = get_call_service()
    await call_service.delete_call(call_id, admin.user_id)
    return {"status": "deleted"}


@router.get("/{call_id}/recording")
async def get_recording(
    call_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить запись звонка"""
    call_service = get_call_service()
    path = await call_service.get_recording_path(call_id)
    
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"call_{call_id}.wav"
    )


@router.delete("/{call_id}/recording")
async def delete_recording(
    call_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Удалить запись звонка (admin only)"""
    call_service = get_call_service()
    await call_service.delete_recording(call_id, admin.user_id)
    return {"status": "deleted"}


@router.get("/active", response_model=ActiveCallsResponse)
async def get_active_calls(user: TokenData = Depends(get_current_user)):
    """Получить активные звонки"""
    call_service = get_call_service()
    return await call_service.get_active_calls()


# =============================================
# Статистика
# =============================================
@stats_router.get("/calls", response_model=CallStatsResponse)
async def get_call_stats(
    campaign_id: Optional[int] = None,
    date_range: DateRangeParams = Depends(),
    user: TokenData = Depends(get_current_user)
):
    """Получить статистику звонков"""
    call_service = get_call_service()
    return await call_service.get_call_stats(
        campaign_id=campaign_id,
        from_date=date_range.from_date.date() if date_range.from_date else None,
        to_date=date_range.to_date.date() if date_range.to_date else None
    )


@stats_router.get("/calls/daily", response_model=List[DailyCallStatsResponse])
async def get_daily_stats(
    days: int = 30,
    campaign_id: Optional[int] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить дневную статистику"""
    call_service = get_call_service()
    return await call_service.get_daily_stats(days=days, campaign_id=campaign_id)


@stats_router.get("/calls/analytics", response_model=CallAnalyticsResponse)
async def get_analytics(
    days: int = 30,
    campaign_id: Optional[int] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить аналитику звонков"""
    call_service = get_call_service()
    return await call_service.get_analytics(days=days, campaign_id=campaign_id)
