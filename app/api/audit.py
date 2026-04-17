# app/api/audit.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Аудит логов (admin only)
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import io

from app.core.dependencies import require_admin, TokenData, PaginationParams, DateRangeParams
from app.services import get_audit_service
from app.models.audit import (
    AuditLogFilter, AuditLogResponse, AuditLogListResponse,
    AuditStatsResponse, AuditAction, AuditSeverity,
    AuditExportRequest, AuditExportResponse
)

router = APIRouter()


@router.get("/", response_model=AuditLogListResponse)
async def list_audit_logs(
    pagination: PaginationParams = Depends(),
    user_id: Optional[int] = None,
    action: Optional[List[AuditAction]] = None,
    severity: Optional[List[AuditSeverity]] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    date_range: DateRangeParams = Depends(),
    search: Optional[str] = None,
    admin: TokenData = Depends(require_admin)
):
    """Получить аудит логи"""
    audit_service = get_audit_service()
    
    filter_params = AuditLogFilter(
        user_id=user_id,
        action=action,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        from_date=date_range.from_date.date() if date_range.from_date else None,
        to_date=date_range.to_date.date() if date_range.to_date else None,
        search=search
    )
    
    return await audit_service.list_audit_logs(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.get("/{log_id}", response_model=AuditLogResponse)
async def get_audit_log(
    log_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Получить запись аудита по ID"""
    audit_service = get_audit_service()
    log = await audit_service.get_audit_log(log_id)
    if not log:
        raise HTTPException(404, "Audit log not found")
    return log


@router.get("/stats", response_model=AuditStatsResponse)
async def get_audit_stats(
    days: int = 30,
    admin: TokenData = Depends(require_admin)
):
    """Получить статистику аудита"""
    audit_service = get_audit_service()
    return await audit_service.get_stats(days=days)


@router.get("/user/{user_id}")
async def get_user_audit_stats(
    user_id: int,
    days: int = 30,
    admin: TokenData = Depends(require_admin)
):
    """Получить статистику аудита по пользователю"""
    audit_service = get_audit_service()
    return await audit_service.get_user_stats(user_id, days=days)


@router.post("/export")
async def export_audit_logs(
    request: AuditExportRequest,
    admin: TokenData = Depends(require_admin)
):
    """Экспортировать аудит логи"""
    audit_service = get_audit_service()
    
    if request.format == "csv":
        content = await audit_service.export_to_csv(request.filter, request.max_records)
    elif request.format == "json":
        content = await audit_service.export_to_json(request.filter, request.max_records)
    else:
        raise HTTPException(400, f"Unsupported format: {request.format}")
    
    filename = f"audit_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{request.format}"
    media_type = "text/csv" if request.format == "csv" else "application/json"
    
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/cleanup")
async def cleanup_old_logs(
    older_than_days: int = 90,
    dry_run: bool = True,
    admin: TokenData = Depends(require_admin)
):
    """Очистить старые аудит логи"""
    if older_than_days < 30:
        raise HTTPException(400, "older_than_days must be at least 30")
    
    audit_service = get_audit_service()
    return await audit_service.cleanup_old_logs(older_than_days, dry_run, admin.user_id)
