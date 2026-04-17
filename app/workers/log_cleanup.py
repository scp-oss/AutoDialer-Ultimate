# app/workers/log_cleanup.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Очистка старых логов
"""

import os
import gzip
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.logger import logger


async def cleanup_old_logs():
    """Очистка и архивация старых логов"""
    log_dir = Path(settings.LOG_DIR)
    retention_days = 30
    
    if not log_dir.exists():
        return
    
    logger.info("Запуск очистки старых логов")
    
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    
    try:
        cleaned = 0
        archived = 0
        
        for log_file in log_dir.glob("*.log*"):
            # Пропускаем активные файлы
            if log_file.suffix == ".log":
                continue
            
            # Получаем дату модификации
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            
            if mtime < cutoff_date:
                log_file.unlink()
                cleaned += 1
        
        # Архивируем старые логи
        for log_file in log_dir.glob("*.log"):
            if log_file.stat().st_size > 10 * 1024 * 1024:  # > 10 MB
                archive_path = log_file.with_suffix(".log.gz")
                
                with open(log_file, 'rb') as f_in:
                    with gzip.open(archive_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Очищаем оригинал
                log_file.write_text("")
                archived += 1
        
        if cleaned > 0 or archived > 0:
            logger.info(f"✅ Очистка логов: удалено {cleaned}, архивировано {archived}")
            
    except Exception as e:
        logger.error(f"Ошибка при очистке логов: {e}")
