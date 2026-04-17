# app/workers/cleanup.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Очистка старых аудиофайлов
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.logger import logger
from app.core.database import get_db_pool


async def cleanup_old_audio_files():
    """Очистка аудиофайлов старше N дней"""
    retention_days = settings.AUDIO_RETENTION_DAYS
    
    logger.info(f"Запуск очистки аудиофайлов старше {retention_days} дней")
    
    db_pool = get_db_pool()
    
    try:
        async with db_pool.acquire() as conn:
            # Находим старые файлы
            rows = await conn.fetch("""
                SELECT id, file_path FROM audio_files 
                WHERE created_at < NOW() - INTERVAL '1 day' * $1
                AND campaign_id IS NULL
                AND is_public = FALSE
            """, retention_days)
            
            cleaned = 0
            total_size = 0
            
            for row in rows:
                file_path = Path(row['file_path'])
                
                # Удаляем файл
                if file_path.exists():
                    try:
                        size = file_path.stat().st_size
                        file_path.unlink()
                        total_size += size
                        logger.debug(f"Файл удалён: {file_path}")
                    except Exception as e:
                        logger.error(f"Ошибка удаления файла {file_path}: {e}")
                        continue
                
                # Удаляем запись из БД
                await conn.execute(
                    "DELETE FROM audio_files WHERE id = $1",
                    row['id']
                )
                cleaned += 1
            
            if cleaned > 0:
                logger.info(f"✅ Очищено {cleaned} аудиофайлов, освобождено {total_size / (1024*1024):.2f} МБ")
            else:
                logger.debug("Нет аудиофайлов для очистки")
                
    except Exception as e:
        logger.error(f"Ошибка при очистке аудиофайлов: {e}")
