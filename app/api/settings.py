# app/api/settings.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление настройками
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, require_admin, TokenData
from app.services import get_settings_service
from app.models.settings import (
    SettingUpdateRequest, SettingsBulkUpdateRequest,
    SettingResponse, SettingsListResponse
)

router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def get_settings(user: TokenData = Depends(get_current_user)):
    """Получить настройки (публичные для всех, все для admin)"""
    settings_service = get_settings_service()
    return await settings_service.get_settings(user.role == "admin")


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    user: TokenData = Depends(get_current_user)
):
    """Получить настройку по ключу"""
    settings_service = get_settings_service()
    setting = await settings_service.get_setting(key)
    if not setting:
        raise HTTPException(404, "Setting not found")
    
    # Проверяем доступ
    if not setting.is_public and user.role != "admin":
        raise HTTPException(403, "Access denied")
    
    return setting


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    request: SettingUpdateRequest,
    admin: TokenData = Depends(require_admin)
):
    """Обновить настройку (admin only)"""
    settings_service = get_settings_service()
    return await settings_service.update_setting(key, request.value, admin.user_id)


@router.put("/", response_model=SettingsListResponse)
async def bulk_update_settings(
    request: SettingsBulkUpdateRequest,
    admin: TokenData = Depends(require_admin)
):
    """Массовое обновление настроек (admin only)"""
    settings_service = get_settings_service()
    return await settings_service.bulk_update_settings(request.settings, admin.user_id)


@router.post("/reset")
async def reset_all_settings(admin: TokenData = Depends(require_admin)):
    """Сбросить ВСЕ настройки к значениям по умолчанию (admin only)"""
    settings_service = get_settings_service()
    return await settings_service.reset_all_settings(admin.user_id)


@router.get("/categories")
async def get_setting_categories(user: TokenData = Depends(get_current_user)):
    """Получить категории настроек"""
    settings_service = get_settings_service()
    return await settings_service.get_categories()


@router.get("/category/{category}")
async def get_settings_by_category(
    category: str,
    user: TokenData = Depends(get_current_user)
):
    """Получить настройки по категории"""
    settings_service = get_settings_service()
    return await settings_service.get_settings_by_category(
        category,
        user.role == "admin"
    )
