#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket API для дашборда в реальном времени
AutoDialer Ultimate v3.0.0

Единственный эндпоинт /ws/dashboard рассылает подключённым клиентам:
- статус SIP-регистрации и системы (SystemNotificationEvent)
- живые события звонков (LiveCallEvent: dial_begin/answer/hangup/dtmf)
- прогресс кампаний (CampaignProgressEvent)
- персональные уведомления пользователя (notifications)

Аутентификация: браузеры не могут отправлять заголовок Authorization при
установке WebSocket-соединения, поэтому JWT передаётся query-параметром
`token`. Соединение без валидного токена принимается в ограниченном
(anonymous) режиме — получает только публичные системные события.
"""

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.core.logger import logger
from app.core.security import decode_token
from app.services import get_websocket_service, get_system_service

router = APIRouter()


async def _resolve_user_id(token: Optional[str]) -> Optional[int]:
    """Извлечь user_id из JWT токена, переданного в query-параметре"""
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = payload.get("sub") or payload.get("user_id")
        return int(user_id) if user_id is not None else None
    except Exception as e:
        logger.debug(f"WebSocket: невалидный токен ({e}), подключение как anonymous")
        return None


@router.websocket("/dashboard")
async def dashboard_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="JWT access token"),
):
    """
    WebSocket-канал дашборда реального времени.

    Формат сообщений (JSON): {"type": "call"|"campaign"|"system"|"notification", "data": {...}}
    """
    ws_service = get_websocket_service()
    user_id = await _resolve_user_id(token)

    await ws_service.connect(websocket, user_id=user_id)

    try:
        # Начальный снимок состояния системы сразу после подключения
        try:
            system_service = get_system_service()
            status = await system_service.get_status()
            await websocket.send_json({
                "type": "system",
                "data": status.model_dump(mode="json"),
            })
        except Exception as e:
            logger.warning(f"Не удалось отправить начальный снимок статуса: {e}")

        # Держим соединение открытым; клиент может присылать ping/pong,
        # но вся полезная нагрузка идёт от сервера через Redis Pub/Sub.
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket ошибка: {e}")
    finally:
        await ws_service.disconnect(websocket)


__all__ = ["router"]
