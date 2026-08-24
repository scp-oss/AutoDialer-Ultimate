# app/api/system.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление системой
"""

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.dependencies import require_admin, require_operator, TokenData
from app.services import get_system_service, get_dialer_service
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


@router.post("/restart")
async def restart_services(admin: TokenData = Depends(require_admin)):
    """
    Перезагрузка воркеров backend'а (кнопка в модалке "Требуется
    перезагрузка" в Настройках). Фронтенд (settings.js restartServices())
    уже дёргал этот маршрут, но его не существовало вообще - 405 Method
    Not Allowed на каждый клик, подтверждено живьём.
    """
    system_service = get_system_service()
    return await system_service.restart_workers(admin.user_id)


@router.post("/test-call")
async def test_call(
    phone: str = Body(..., embed=True),
    user: TokenData = Depends(require_operator)
):
    """
    Тестовый звонок (кнопка "Быстрый звонок" на дашборде).

    Фронтенд (dashboard.js quickCall() -> system.js testCall()) уже вызывал
    этот маршрут, но его не существовало вообще - кнопка была полностью
    подключена на фронтенде и мертва на бэкенде (тот же паттерн, что
    API-токены/Webhooks). Ставит звонок в ту же очередь, что и обычные
    кампании (campaign_id=0 - существующее соглашение "без кампании", см.
    _save_call_result), поэтому идёт по тому же пути AMI Originate ->
    dialer_bridge, что и реальные звонки - это и есть смысл теста.
    """
    dialer_service = get_dialer_service()
    if not dialer_service:
        raise HTTPException(503, "Dialer недоступен")
    await dialer_service.start_call(phone, campaign_id=0)
    return {"status": "queued", "phone": phone}
