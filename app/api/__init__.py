#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API роутеры FastAPI
AutoDialer Ultimate v3.0.0

Центральный модуль, объединяющий все API роутеры:
- health - проверка здоровья и метрики
- auth - аутентификация и авторизация
- system - управление системой
- campaigns - управление кампаниями
- contacts - управление контактами
- calls - история звонков и статистика
- audio - управление аудиофайлами и TTS
- blacklist - управление чёрным списком
- users - управление пользователями (admin)
- settings - управление настройками (admin)
- audit - аудит логов (admin)
- incoming - входящие звонки
- websocket - WebSocket соединения
"""

from fastapi import APIRouter

# =============================================
# Главный роутер API
# =============================================
api_router = APIRouter(prefix="/api")


# =============================================
# Импорт и подключение роутеров
# =============================================

# Health & Metrics (без префикса /api)
from app.api import health
api_router.include_router(health.router, tags=["Health"])

# Аутентификация
from app.api import auth
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Система
from app.api import system
api_router.include_router(system.router, prefix="/system", tags=["System"])

# Кампании
from app.api import campaigns
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["Campaigns"])

# Контакты
from app.api import contacts
api_router.include_router(contacts.router, prefix="/contacts", tags=["Contacts"])

# Группы контактов
from app.api import contact_groups
api_router.include_router(contact_groups.router, prefix="/contact-groups", tags=["Contact Groups"])

# Звонки (история и статистика)
from app.api import calls
api_router.include_router(calls.router, prefix="/calls", tags=["Calls"])
api_router.include_router(calls.stats_router, prefix="/stats", tags=["Statistics"])

# Аудиофайлы и TTS
from app.api import audio
api_router.include_router(audio.router, prefix="/audio", tags=["Audio"])

# Чёрный список
from app.api import blacklist
api_router.include_router(blacklist.router, prefix="/blacklist", tags=["Blacklist"])

# Пользователи (admin only)
from app.api import users
api_router.include_router(users.router, prefix="/users", tags=["Users"])

# Настройки
from app.api import settings as settings_router
api_router.include_router(settings_router.router, prefix="/settings", tags=["Settings"])

# Аудит (admin only)
from app.api import audit
api_router.include_router(audit.router, prefix="/audit", tags=["Audit"])

# Входящие звонки
from app.api import incoming
api_router.include_router(incoming.router, prefix="/incoming-calls", tags=["Incoming Calls"])

# WebSocket (дашборд в реальном времени)
from app.api import websocket
api_router.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])


# =============================================
# Корневой эндпоинт API
# =============================================
@api_router.get("/", tags=["Root"])
async def api_root():
    """
    Корневой эндпоинт API.
    
    Returns:
        Информация об API
    """
    from app import __version__
    from datetime import datetime
    
    return {
        "name": "AutoDialer Ultimate API",
        "version": __version__,
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "health": "/api/health",
            "auth": "/api/auth",
            "system": "/api/system",
            "campaigns": "/api/campaigns",
            "contacts": "/api/contacts",
            "calls": "/api/calls",
            "stats": "/api/stats",
            "audio": "/api/audio",
            "blacklist": "/api/blacklist",
            "users": "/api/users",
            "settings": "/api/settings",
            "audit": "/api/audit",
            "incoming": "/api/incoming-calls",
        },
        "docs": "/docs",
        "redoc": "/redoc",
    }


# =============================================
# Обработчик 404 для API
# =============================================
@api_router.get("/{path:path}", include_in_schema=False)
async def api_not_found(path: str):
    """
    Обработчик несуществующих API эндпоинтов.
    """
    from app.models.common import ErrorResponse
    
    return ErrorResponse(
        error="Not Found",
        detail=f"API endpoint '/api/{path}' not found",
        code="API_ENDPOINT_NOT_FOUND"
    )


# =============================================
# Экспорт
# =============================================
__all__ = [
    "api_router",
]
