# app/api/auth.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Аутентификация и авторизация
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer

from app.core.dependencies import get_current_user, TokenData
from app.services.user import AuthService, get_auth_service
from app.models.auth import (
    LoginRequest, LoginResponse,
    RefreshTokenRequest, RefreshTokenResponse,
    ChangePasswordRequest, LogoutResponse,
    ForgotPasswordRequest, ForgotPasswordConfirmRequest
)

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, req: Request):
    """Вход в систему"""
    auth_service = get_auth_service()
    return await auth_service.login(request, req.client.host if req.client else None)


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh(request: RefreshTokenRequest):
    """Обновление access токена"""
    auth_service = get_auth_service()
    return await auth_service.refresh(request.refresh_token)


@router.post("/logout", response_model=LogoutResponse)
async def logout(user: TokenData = Depends(get_current_user)):
    """Выход из системы"""
    auth_service = get_auth_service()
    await auth_service.logout(user)
    return LogoutResponse()


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user: TokenData = Depends(get_current_user)
):
    """Смена пароля"""
    auth_service = get_auth_service()
    await auth_service.change_password(user.user_id, request)
    return {"status": "changed"}


@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """
    Запросить восстановление пароля по email.

    AuthService.forgot_password()/confirm_forgot_password() уже были
    полностью реализованы (генерация токена, хранение в Redis, смена
    пароля по токену), но ни разу не были подключены ни к одному
    HTTP-эндпоинту - "забыли пароль" был недостижим через API. Всегда
    возвращает {"status": "ok"} независимо от того, найден ли email, -
    сервис намеренно не раскрывает существование пользователя.
    """
    auth_service = get_auth_service()
    await auth_service.forgot_password(request)
    return {"status": "ok"}


@router.post("/reset-password")
async def reset_password(request: ForgotPasswordConfirmRequest):
    """Подтвердить восстановление пароля по токену из письма."""
    auth_service = get_auth_service()
    await auth_service.confirm_forgot_password(request)
    return {"status": "changed"}


@router.get("/me")
async def get_me(user: TokenData = Depends(get_current_user)):
    """Получить информацию о текущем пользователе"""
    from app.services.user import get_user_service
    user_service = get_user_service()
    return await user_service.get_user(user.user_id)
