# app/api/campaigns.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление кампаниями
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from app.core.dependencies import get_current_user, require_admin, TokenData, PaginationParams
from app.services import get_campaign_service
from app.models.campaign import (
    CampaignCreateRequest, CampaignUpdateRequest,
    CampaignResponse, CampaignDetailResponse, CampaignListResponse,
    CampaignStatsResponse, CampaignProgressResponse,
    CampaignStatus, CampaignPriority
)

router = APIRouter()


@router.get("/", response_model=CampaignListResponse)
async def list_campaigns(
    pagination: PaginationParams = Depends(),
    status: Optional[List[CampaignStatus]] = None,
    priority: Optional[List[CampaignPriority]] = None,
    search: Optional[str] = None,
    tags: Optional[List[str]] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить список кампаний"""
    campaign_service = get_campaign_service()
    return await campaign_service.list_campaigns(
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        priority=priority,
        search=search,
        tags=tags
    )


@router.post("/", response_model=dict)
async def create_campaign(
    request: CampaignCreateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Создать новую кампанию"""
    campaign_service = get_campaign_service()
    campaign_id = await campaign_service.create_campaign(request, user.user_id)
    return {"campaign_id": campaign_id}


@router.get("/summary")
async def get_campaigns_summary(
    user: TokenData = Depends(get_current_user)
):
    """
    Сводка по количеству кампаний в каждом статусе (для дашборда).
    Должен стоять ДО /{campaign_id} - иначе "summary" пытается
    распарситься как campaign_id:int и падает с 422 (тот же порядок
    роутов, что уже пофикшен в contacts.py/incoming.py).
    """
    campaign_service = get_campaign_service()
    return await campaign_service.get_summary()


@router.get("/active")
async def get_active_campaigns(user: TokenData = Depends(get_current_user)):
    """
    Получить активные кампании. Была зарегистрирована ПОСЛЕ /{campaign_id}
    (см. ниже) - каждый вызов /campaigns/active падал с тем же 422, пытаясь
    распарсить "active" как campaign_id:int. Никогда не работала, поэтому
    никто не заметил - тот же класс бага, что и /summary выше.
    """
    campaign_service = get_campaign_service()
    return await campaign_service.get_active_campaigns()


@router.get("/runs")
async def list_campaign_runs(
    pagination: PaginationParams = Depends(),
    campaign_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: TokenData = Depends(get_current_user)
):
    """
    Список запусков обзвонов для вкладки "История обзвонов" - одна
    строка на каждый прогон (нажатие "Запустить"/"Запустить снова"),
    а не на кампанию. Должен стоять ДО /{campaign_id} - тот же класс
    бага, что и /summary/​/active выше ("runs" иначе пытается
    распарситься как campaign_id:int и падает с 422).
    """
    campaign_service = get_campaign_service()
    return await campaign_service.list_campaign_runs(
        page=pagination.page,
        page_size=pagination.page_size,
        campaign_id=campaign_id,
        status=status,
        search=search
    )


@router.get("/runs/{run_id}")
async def get_campaign_run(
    run_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Детали одного запуска (для drill-down из "Истории обзвонов")"""
    campaign_service = get_campaign_service()
    run = await campaign_service.get_campaign_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign(
    campaign_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить кампанию по ID"""
    campaign_service = get_campaign_service()
    campaign = await campaign_service.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return campaign


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    request: CampaignUpdateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Обновить кампанию"""
    campaign_service = get_campaign_service()
    await campaign_service.update_campaign(campaign_id, request, user.user_id)
    return {"status": "updated"}


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Удалить кампанию (admin only)"""
    campaign_service = get_campaign_service()
    await campaign_service.delete_campaign(campaign_id, admin.user_id)
    return {"status": "deleted"}


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    user: TokenData = Depends(get_current_user)
):
    """Запустить кампанию"""
    campaign_service = get_campaign_service()
    return await campaign_service.start_campaign(campaign_id, user.user_id)


@router.post("/{campaign_id}/stop")
async def stop_campaign(
    campaign_id: int,
    reason: Optional[str] = None,
    user: TokenData = Depends(get_current_user)
):
    """Остановить кампанию"""
    campaign_service = get_campaign_service()
    await campaign_service.stop_campaign(campaign_id, user.user_id, reason)
    return {"status": "stopped"}


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Приостановить кампанию"""
    campaign_service = get_campaign_service()
    await campaign_service.pause_campaign(campaign_id, user.user_id)
    return {"status": "paused"}


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Возобновить кампанию"""
    campaign_service = get_campaign_service()
    return await campaign_service.resume_campaign(campaign_id, user.user_id)


@router.get("/{campaign_id}/stats", response_model=CampaignStatsResponse)
async def get_campaign_stats(
    campaign_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить статистику кампании"""
    campaign_service = get_campaign_service()
    stats = await campaign_service.get_campaign_stats(campaign_id)
    if not stats:
        raise HTTPException(404, "Campaign not found")
    return stats


@router.get("/{campaign_id}/progress", response_model=CampaignProgressResponse)
async def get_campaign_progress(
    campaign_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить прогресс кампании"""
    campaign_service = get_campaign_service()
    progress = await campaign_service.get_campaign_progress(campaign_id)
    if not progress:
        raise HTTPException(404, "Campaign not found")
    return progress
