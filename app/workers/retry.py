# app/workers/retry.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обработка очереди повторных звонков
"""

from datetime import datetime

from app.core.logger import logger
from app.core.database import get_db_pool
from app.services import get_dialer_service


async def process_retry_queue():
    """Обработка запланированных повторных звонков"""
    db_pool = get_db_pool()
    dialer_service = get_dialer_service()
    
    if not dialer_service:
        logger.debug("Dialer не инициализирован, пропуск обработки повторов")
        return
    
    try:
        async with db_pool.acquire() as conn:
            # Получаем контакты для повтора
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
                
                # Обновляем записи
                ids = [row['id'] for row in rows]
                await conn.execute("""
                    UPDATE campaign_contacts 
                    SET next_retry_at = NULL, updated_at = NOW()
                    WHERE id = ANY($1)
                """, ids)
            
            # Запускаем звонки (вне транзакции)
            for row in rows:
                try:
                    await dialer_service.start_call(
                        row['phone'],
                        row['campaign_id'],
                        row['retry_count']
                    )
                except Exception as e:
                    logger.error(f"Ошибка запуска повторного звонка: {e}")
            
            if rows:
                logger.debug(f"Обработано {len(rows)} повторных звонков")
                
    except Exception as e:
        logger.error(f"Ошибка в обработчике повторов: {e}")
