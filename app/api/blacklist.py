# app/api/blacklist.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление чёрным списком
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, require_admin, TokenData, PaginationParams
from app.services import get_blacklist_service
from app.models.blacklist import (
    BlacklistAddRequest, BlacklistBulkAddRequest,
    BlacklistResponse, BlacklistListResponse,
    BlacklistCheckRequest, BlacklistCheckResponse,
    BlacklistBulkCheckResponse, BlacklistStatsResponse,
    BlacklistReason, BlacklistStatus, BlacklistFilterRequest
)

router = APIRouter()


@router.get("/", response_model=BlacklistListResponse)
async def list_blacklist(
    pagination: PaginationParams = Depends(),
    reason: Optional[List[BlacklistReason]] = None,
    status: Optional[List[BlacklistStatus]] = None,
    search: Optional[str] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить список номеров в чёрном списке"""
    blacklist_service = get_blacklist_service()
    
    filter_params = BlacklistFilterRequest(
        reason=reason,
        status=status,
        search=search
    )
    
    return await blacklist_service.list_blacklist(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.post("/", response_model=BlacklistResponse)
async def add_to_blacklist(
    request: BlacklistAddRequest,
    user: TokenData = Depends(get_current_user)
):
    """Добавить номер в чёрный список"""
    blacklist_service = get_blacklist_service()
    return await blacklist_service.add_to_blacklist(request, user.user_id)


@router.post("/check", response_model=BlacklistBulkCheckResponse)
async def check_blacklist(
    request: BlacklistCheckRequest,
    user: TokenData = Depends(get_current_user)
):
    """Проверить номера в чёрном списке"""
    blacklist_service = get_blacklist_service()
    return await blacklist_service.check_blacklist(request.phones)


@router.get("/check/{phone}", response_model=BlacklistCheckResponse)
async def check_single_phone(
    phone: str,
    user: TokenData = Depends(get_current_user)
):
    """Проверить один номер в чёрном списке"""
    blacklist_service = get_blacklist_service()
    result = await blacklist_service.check_blacklist([phone])
    return result.results[0] if result.results else None


@router.get("/{blacklist_id}", response_model=BlacklistResponse)
async def get_blacklist_entry(
    blacklist_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить запись чёрного списка по ID"""
    blacklist_service = get_blacklist_service()
    entry = await blacklist_service.get_blacklist_entry(blacklist_id)
    if not entry:
        raise HTTPException(404, "Blacklist entry not found")
    return entry


@router.delete("/{blacklist_id}")
async def remove_from_blacklist(
    blacklist_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Удалить номер из чёрного списка"""
    blacklist_service = get_blacklist_service()
    await blacklist_service.remove_from_blacklist(blacklist_id, user.user_id)
    return {"status": "removed"}


@router.delete("/phone/{phone}")
async def remove_phone_from_blacklist(
    phone: str,
    admin: TokenData = Depends(require_admin)
):
    """Удалить номер из чёрного списка по номеру (admin only)"""
    blacklist_service = get_blacklist_service()
    await blacklist_service.remove_phone_from_blacklist(phone, admin.user_id)
    return {"status": "removed"}


@router.post("/bulk")
async def bulk_add_to_blacklist(
    request: BlacklistBulkAddRequest,
    user: TokenData = Depends(get_current_user)
):
    """Массовое добавление в чёрный список"""
    blacklist_service = get_blacklist_service()
    return await blacklist_service.bulk_add_to_blacklist(request, user.user_id)


@router.get("/stats", response_model=BlacklistStatsResponse)
async def get_blacklist_stats(user: TokenData = Depends(get_current_user)):
    """Получить статистику чёрного списка"""
    blacklist_service = get_blacklist_service()
    return await blacklist_service.get_stats()


@router.post("/cleanup")
async def cleanup_expired(
    admin: TokenData = Depends(require_admin)
):
    """Очистить истекшие записи (admin only)"""
    blacklist_service = get_blacklist_service()
    cleaned = await blacklist_service.cleanup_expired()
    return {"cleaned": cleaned}
