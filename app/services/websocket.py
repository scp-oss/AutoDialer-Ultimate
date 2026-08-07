#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис WebSocket-соединений (Dashboard в реальном времени)
AutoDialer Ultimate v3.0.0

Предоставляет:
- Реестр активных WebSocket-соединений текущего процесса
- Подписку на Redis Pub/Sub каналы событий (звонки, кампании, система,
  уведомления), публикуемые dialer'ом/воркерами/другими API-процессами
- Рассылку полученных событий всем локально подключённым клиентам

Приложение может работать в нескольких процессах (несколько gunicorn/uvicorn
воркеров), поэтому WebSocket-соединение конкретного клиента "живёт" только
в одном процессе. Чтобы события, сгенерированные в другом процессе (или в
фоновом воркере), доходили до всех подключённых клиентов, используется
Redis Pub/Sub как шина: любой компонент публикует событие в канал
REDIS_KEYS.WS_CHANNELS, а каждый процесс с активным WebSocketService подписан
на этот канал и рассылает событие своим локальным соединениям.
"""

import asyncio
import json
from typing import Optional, Dict, Any, Set

from fastapi import WebSocket

from app.core.logger import logger
from app.core.redis import RedisClient, REDIS_KEYS


class WebSocketError(Exception):
    """Базовое исключение сервиса WebSocket"""
    pass


class WebSocketService:
    """
    Менеджер WebSocket-соединений дашборда с рассылкой событий через Redis Pub/Sub.

    Каналы (все — подканалы REDIS_KEYS.WS_CHANNELS):
        dashboard:events:call         — LiveCallEvent (dial_begin/answer/hangup/dtmf)
        dashboard:events:campaign     — CampaignProgressEvent
        dashboard:events:system       — SystemNotificationEvent / статус SIP
        dashboard:events:notification — уведомление пользователю
    """

    CHANNEL_PREFIX = REDIS_KEYS.WS_CHANNELS

    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client
        self._connections: Set[WebSocket] = set()
        self._connection_users: Dict[WebSocket, Optional[int]] = {}
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def channels(self) -> list:
        return [
            f"{self.CHANNEL_PREFIX}:call",
            f"{self.CHANNEL_PREFIX}:campaign",
            f"{self.CHANNEL_PREFIX}:system",
            f"{self.CHANNEL_PREFIX}:notification",
        ]

    async def start(self) -> None:
        """Подписаться на каналы событий Redis"""
        if self._started:
            return
        for channel in self.channels:
            await self.redis.subscribe(channel, self._on_redis_message)
        self._started = True
        logger.info(f"WebSocketService подписан на каналы: {self.channels}")

    async def shutdown(self) -> None:
        """Отписаться от Redis и закрыть все локальные соединения"""
        for channel in self.channels:
            try:
                await self.redis.unsubscribe(channel, self._on_redis_message)
            except Exception as e:
                logger.warning(f"Ошибка отписки от {channel}: {e}")

        async with self._lock:
            connections = list(self._connections)
            self._connections.clear()
            self._connection_users.clear()

        for ws in connections:
            try:
                await ws.close()
            except Exception:
                pass

        self._started = False
        logger.info("WebSocketService остановлен")

    async def _on_redis_message(self, channel: str, message: str) -> None:
        """Callback, вызываемый RedisClient при получении Pub/Sub сообщения"""
        await self._broadcast_local(message)

    async def connect(self, websocket: WebSocket, user_id: Optional[int] = None) -> None:
        """Зарегистрировать новое WebSocket-соединение"""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            self._connection_users[websocket] = user_id
        logger.info(f"WebSocket подключён (user_id={user_id}), всего соединений: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Убрать WebSocket-соединение из реестра"""
        async with self._lock:
            self._connections.discard(websocket)
            self._connection_users.pop(websocket, None)
        logger.info(f"WebSocket отключён, осталось соединений: {len(self._connections)}")

    async def _broadcast_local(self, payload: str) -> None:
        """Разослать сырое JSON-сообщение всем локальным соединениям"""
        async with self._lock:
            connections = list(self._connections)

        dead: list = []
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
                    self._connection_users.pop(ws, None)

    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Опубликовать событие для рассылки всем подключённым клиентам
        (во всех процессах приложения, через Redis Pub/Sub).

        event_type: "call" | "campaign" | "system" | "notification"
        """
        channel = f"{self.CHANNEL_PREFIX}:{event_type}"
        payload = {
            "type": event_type,
            "data": data,
        }
        await self.redis.publish(channel, json.dumps(payload, default=str))

    async def send_personal(self, user_id: int, message: Dict[str, Any]) -> int:
        """Отправить сообщение конкретному пользователю (во всех его соединениях в этом процессе)"""
        async with self._lock:
            targets = [ws for ws, uid in self._connection_users.items() if uid == user_id]

        sent = 0
        payload = json.dumps(message, default=str)
        for ws in targets:
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                pass
        return sent

    @property
    def active_connections(self) -> int:
        return len(self._connections)


# =============================================
# Глобальный экземпляр
# =============================================
_websocket_service: Optional[WebSocketService] = None


def get_websocket_service() -> WebSocketService:
    """Получить глобальный экземпляр WebSocketService"""
    global _websocket_service
    if _websocket_service is None:
        raise RuntimeError("WebSocketService не инициализирован")
    return _websocket_service


def set_websocket_service(service: WebSocketService) -> None:
    global _websocket_service
    _websocket_service = service


__all__ = [
    "WebSocketService",
    "WebSocketError",
    "get_websocket_service",
    "set_websocket_service",
]
