#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис уведомлений пользователей
AutoDialer Ultimate v3.0.0

Предоставляет:
- Создание уведомлений (таблица notifications)
- Получение списка/непрочитанных уведомлений пользователя
- Отметку о прочтении
- Публикацию уведомления в Redis для доставки через WebSocket в реальном времени
"""

import json
from typing import Optional, List, Dict, Any

from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS


class NotificationError(Exception):
    """Базовое исключение сервиса уведомлений"""
    pass


class NotificationNotFoundError(NotificationError):
    """Уведомление не найдено"""
    pass


class NotificationService:
    """
    Сервис управления уведомлениями пользователей.

    Уведомления сохраняются в таблице `notifications` и одновременно
    публикуются в Redis Pub/Sub канал `REDIS_KEYS.WS_CHANNELS`, откуда
    их подхватывает WebSocketService и рассылает подключённым клиентам
    в реальном времени.
    """

    CHANNEL = f"{REDIS_KEYS.WS_CHANNELS}:notification"

    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        logger.info("NotificationService инициализирован")

    async def create(
        self,
        user_id: int,
        type: str,
        title: str,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Создать уведомление и опубликовать его для доставки в реальном времени"""
        row = await self.db_pool.fetchrow(
            """
            INSERT INTO notifications (user_id, type, title, message, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, user_id, type, title, message, is_read, read_at, metadata, created_at
            """,
            user_id, type, title, message,
            json.dumps(metadata) if metadata else "{}",
        )
        notification = dict(row)

        try:
            await self.redis.publish(
                self.CHANNEL,
                {
                    "type": "notification",
                    "data": {
                        "id": notification["id"],
                        "user_id": notification["user_id"],
                        "type": notification["type"],
                        "title": notification["title"],
                        "message": notification["message"],
                    },
                },
            )
        except Exception as e:
            # Публикация — best-effort, отсутствие подписчиков не должно ронять запрос
            logger.warning(f"Не удалось опубликовать уведомление в Redis: {e}")

        return notification

    async def list_for_user(
        self,
        user_id: int,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Получить список уведомлений пользователя"""
        query = "SELECT * FROM notifications WHERE user_id = $1"
        params: List[Any] = [user_id]

        if unread_only:
            query += " AND is_read = FALSE"

        query += " ORDER BY created_at DESC LIMIT $2 OFFSET $3"
        params.extend([limit, offset])

        rows = await self.db_pool.fetch(query, *params)
        return [dict(row) for row in rows]

    async def count_unread(self, user_id: int) -> int:
        """Количество непрочитанных уведомлений"""
        return await self.db_pool.fetchval(
            "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND is_read = FALSE",
            user_id,
        ) or 0

    async def mark_read(self, notification_id: int, user_id: int) -> bool:
        """Отметить уведомление как прочитанное"""
        result = await self.db_pool.execute(
            """
            UPDATE notifications SET is_read = TRUE, read_at = NOW()
            WHERE id = $1 AND user_id = $2
            """,
            notification_id, user_id,
        )
        if "UPDATE 1" not in result:
            raise NotificationNotFoundError(f"Уведомление {notification_id} не найдено")
        return True

    async def mark_all_read(self, user_id: int) -> int:
        """Отметить все уведомления пользователя как прочитанные"""
        result = await self.db_pool.execute(
            "UPDATE notifications SET is_read = TRUE, read_at = NOW() WHERE user_id = $1 AND is_read = FALSE",
            user_id,
        )
        import re
        match = re.search(r"UPDATE (\d+)", result)
        return int(match.group(1)) if match else 0

    async def delete(self, notification_id: int, user_id: int) -> bool:
        """Удалить уведомление"""
        result = await self.db_pool.execute(
            "DELETE FROM notifications WHERE id = $1 AND user_id = $2",
            notification_id, user_id,
        )
        if "DELETE 1" not in result:
            raise NotificationNotFoundError(f"Уведомление {notification_id} не найдено")
        return True


# =============================================
# Глобальный экземпляр
# =============================================
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Получить глобальный экземпляр NotificationService"""
    global _notification_service
    if _notification_service is None:
        raise RuntimeError("NotificationService не инициализирован")
    return _notification_service


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


__all__ = [
    "NotificationService",
    "NotificationError",
    "NotificationNotFoundError",
    "get_notification_service",
    "set_notification_service",
]
