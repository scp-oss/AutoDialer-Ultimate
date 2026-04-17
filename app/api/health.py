# app/api/health.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Health check и метрики
"""

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.dependencies import verify_metrics_auth
from app.services import get_system_service
from app.models.system import HealthCheckResponse

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Проверка здоровья системы"""
    system_service = get_system_service()
    return await system_service.health_check()


@router.get("/health/live")
async def liveness_check():
    """Liveness probe для Kubernetes"""
    system_service = get_system_service()
    result = await system_service.liveness_check()
    return {"alive": result.alive}


@router.get("/health/ready")
async def readiness_check():
    """Readiness probe для Kubernetes"""
    system_service = get_system_service()
    result = await system_service.readiness_check()
    return {"ready": result.ready, "reason": result.reason}


@router.get("/metrics")
async def metrics(_: bool = Depends(verify_metrics_auth)):
    """Prometheus метрики"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
