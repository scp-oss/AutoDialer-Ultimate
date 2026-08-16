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


# NOTE: there used to be a catch-all `@api_router.get("/{path:path}")`
# handler here meant to give unmatched /api/* requests a nicer JSON 404
# body. It caused two confirmed bugs instead of fixing anything:
#   1. It returned the error body via a plain Pydantic model with no
#      explicit status_code, so FastAPI sent it back as a bare 200 OK -
#      every genuinely-missing endpoint "succeeded" with an error payload
#      disguised as data.
#   2. Because a `{path:path}` converter matches literally any path, it
#      gave Starlette's router a FULL match before it ever got a chance
#      to fall back to its own redirect-slash handling for a real
#      sub-router route missing only a trailing slash. Confirmed live:
#      GET /api/audio (no trailing slash, exactly what the frontend
#      sends) was swallowed by this handler and returned 200 with a
#      "Not Found" body instead of either 307-redirecting to the real
#      /api/audio/ or being genuinely absent - the frontend then tried
#      to treat that error object as a list and crashed with
#      "X.map is not a function".
# Removing it restores FastAPI/Starlette's own default behavior: a
# proper 404 for paths that really don't exist, and a correct redirect
# for real routes reached without their trailing slash.


# =============================================
# Экспорт
# =============================================
__all__ = [
    "api_router",
]
