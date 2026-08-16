# app/workers/retry.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обработка очереди повторных звонков
"""

import asyncio
from datetime import datetime

from app.core.logger import logger
from app.core.database import get_db_pool
from app.services import get_dialer_service

# dialer_service.start_call() was observed live to hang indefinitely (not
# raise, not time out on its own - just never return) when called from
# this specific background-worker task context, stuck on its very first
# Redis command (confirmed by instrumenting start_call() directly: it
# never got past `await self.redis.is_blacklisted(...)`, and even a bare
# `await self.redis.client.ping()` wrapped in its own asyncio.wait_for
# never fired). Ruled out: holding the asyncpg connection open across the
# call (restructured to release it first - hang persisted), a shared
# circuit breaker (set_circuit_breaker() is never actually called
# anywhere in the app, so both the DB pool's and Redis client's circuit
# breakers are always None - dead code, not in play). The process runs
# under uvloop (confirmed installed and active), which is a known source
# of hard-to-diagnose interactions between asyncpg and redis.asyncio in
# background-task contexts; full root-causing would need task-level
# introspection tooling (e.g. py-spy with asyncio task awareness) not
# available in this sandbox - py-spy's plain thread dump only shows the
# idle event loop's epoll wait, not which suspended task is stuck.
# Wrapping in a timeout is a defensive fix that stands on its own merit
# regardless of the exact cause: no periodic worker should be able to
# wedge itself forever on one unresponsive external call, and every other
# AMI action call in this codebase already uses this same pattern (see
# app/services/dialer.py's Ping/CoreShowChannels calls).
START_CALL_TIMEOUT = 15


async def process_retry_queue():
    """Обработка запланированных повторных звонков"""
    db_pool = get_db_pool()
    dialer_service = get_dialer_service()

    if not dialer_service:
        logger.debug("Dialer не инициализирован, пропуск обработки повторов")
        return
    
    try:
        # Получаем и claim'им контакты для повтора - соединение с БД
        # держим ТОЛЬКО на время этого блока и явно освобождаем (закрывая
        # `async with`) до того, как обращаемся к Redis/AMI через
        # dialer_service.start_call() ниже. Раньше соединение оставалось
        # открытым на весь цикл, включая размещение звонков - подтверждено
        # живьём: dialer_service.start_call() зависал навсегда (не падал,
        # не логировал ошибку - просто никогда не возвращался) на первом
        # же обращении к Redis, если вызывался, пока это соединение с БД
        # ещё держалось открытым.
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("""
                    SELECT
                        cc.id,
                        cc.campaign_id,
                        c.phone,
                        cc.retry_count
                    FROM campaign_contacts cc
                    JOIN contacts c ON cc.contact_id = c.id
                    WHERE cc.next_retry_at IS NOT NULL
                    AND cc.next_retry_at <= NOW()
                    AND cc.status = 'pending'
                    AND NOT c.blacklisted
                    LIMIT 50
                    FOR UPDATE SKIP LOCKED
                """)

                if not rows:
                    return

                # campaign_contacts не имеет колонки updated_at (только
                # created_at, см. sql/schema.sql) - `SET ... updated_at =
                # NOW()` падало с `column "updated_at" of relation
                # "campaign_contacts" does not exist` на КАЖДОЙ попытке
                # повтора, то есть очередь повторных звонков не
                # обрабатывала ни одного контакта ни разу за всю историю
                # проекта. Подтверждено живьём.
                ids = [row['id'] for row in rows]
                await conn.execute("""
                    UPDATE campaign_contacts
                    SET next_retry_at = NULL
                    WHERE id = ANY($1)
                """, ids)

        # Запускаем звонки - соединение с БД уже освобождено выше.
        for row in rows:
            try:
                await asyncio.wait_for(
                    dialer_service.start_call(
                        row['phone'],
                        row['campaign_id'],
                        row['retry_count']
                    ),
                    timeout=START_CALL_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Повторный звонок для {row['phone']} завис "
                    f"(> {START_CALL_TIMEOUT}с) - пропущен, попробуем в следующем цикле"
                )
            except Exception as e:
                logger.error(f"Ошибка запуска повторного звонка: {e}")

        logger.debug(f"Обработано {len(rows)} повторных звонков")

    except Exception as e:
        logger.error(f"Ошибка в обработчике повторов: {e}")
