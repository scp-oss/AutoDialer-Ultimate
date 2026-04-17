# app/api/users.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление пользователями (admin only)
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import require_admin, TokenData, PaginationParams
from app.services import get_user_service
from app.models.user import (
    UserCreateRequest, UserUpdateRequest,
    UserResponse, UserListResponse,
    UserRole, UserStatus, UserFilterRequest
)

router = APIRouter()


@router.get("/", response_model=UserListResponse)
async def list_users(
    pagination: PaginationParams = Depends(),
    role: Optional[List[UserRole]] = None,
    status: Optional[List[UserStatus]] = None,
    search: Optional[str] = None,
    admin: TokenData = Depends(require_admin)
):
    """Получить список пользователей"""
    user_service = get_user_service()
    
    filter_params = UserFilterRequest(
        role=role,
        status=status,
        search=search
    )
    
    return await user_service.list_users(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.post("/", response_model=UserResponse)
async def create_user(
    request: UserCreateRequest,
    admin: TokenData = Depends(require_admin)
):
    """Создать нового пользователя"""
    user_service = get_user_service()
    return await user_service.create_user(request, admin.user_id)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Получить пользователя по ID"""
    user_service = get_user_service()
    user = await user_service.get_user(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    admin: TokenData = Depends(require_admin)
):
    """Обновить пользователя"""
    user_service = get_user_service()
    return await user_service.update_user(user_id, request, admin.user_id)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Удалить пользователя"""
    if user_id == 1:
        raise HTTPException(400, "Cannot delete default admin")
    
    user_service = get_user_service()
    await user_service.delete_user(user_id, admin.user_id)
    return {"status": "deleted"}


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    new_password: str,
    force_change: bool = True,
    admin: TokenData = Depends(require_admin)
):
    """Сбросить пароль пользователя"""
    user_service = get_user_service()
    await user_service.reset_password(user_id, new_password, force_change, admin.user_id)
    return {"status": "password_reset"}


@router.post("/{user_id}/enable")
async def enable_user(
    user_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Активировать пользователя"""
    user_service = get_user_service()
    await user_service.enable_user(user_id, admin.user_id)
    return {"status": "enabled"}


@router.post("/{user_id}/disable")
async def disable_user(
    user_id: int,
    admin: TokenData = Depends(require_admin)
):
    """Деактивировать пользователя"""
    if user_id == 1:
        raise HTTPException(400, "Cannot disable default admin")
    
    user_service = get_user_service()
    await user_service.disable_user(user_id, admin.user_id)
    return {"status": "disabled"}
