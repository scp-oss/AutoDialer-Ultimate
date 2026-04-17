# app/api/system.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление системой
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import require_admin, TokenData
from app.services import get_system_service
from app.models.system import (
    SystemStatusResponse, SystemEnableResponse, SystemDisableResponse,
    SystemConfigResponse, SystemMode
)

router = APIRouter()


@router.get("/status", response_model=SystemStatusResponse)
async def get_status(user: TokenData = Depends(require_admin)):
    """Получить статус системы"""
    system_service = get_system_service()
    return await system_service.get_status()


@router.post("/enable", response_model=SystemEnableResponse)
async def enable_system(admin: TokenData = Depends(require_admin)):
    """Включить систему"""
    system_service = get_system_service()
    return await system_service.enable_system(admin.user_id)


@router.post("/disable", response_model=SystemDisableResponse)
async def disable_system(
    reason: str = None,
    force: bool = False,
    admin: TokenData = Depends(require_admin)
):
    """Выключить систему (kill switch)"""
    system_service = get_system_service()
    return await system_service.disable_system(admin.user_id, reason, force)


@router.get("/config", response_model=SystemConfigResponse)
async def get_config(admin: TokenData = Depends(require_admin)):
    """Получить конфигурацию системы"""
    system_service = get_system_service()
    return await system_service.get_config()


@router.post("/mode")
async def set_mode(
    mode: SystemMode,
    reason: str = None,
    admin: TokenData = Depends(require_admin)
):
    """Установить режим работы системы"""
    system_service = get_system_service()
    return await system_service.set_mode(mode, admin.user_id, reason)


@router.get("/resources")
async def get_resource_usage(admin: TokenData = Depends(require_admin)):
    """Получить использование ресурсов"""
    system_service = get_system_service()
    return await system_service.get_resource_usage()
