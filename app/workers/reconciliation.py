# app/workers/reconciliation.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронизация с Asterisk
"""

from app.core.logger import logger
from app.services import get_dialer_service


async def reconcile_with_asterisk():
    """Периодическая сверка состояния с Asterisk"""
    try:
        dialer_service = get_dialer_service()
        
        if dialer_service and dialer_service.manager:
            manager = dialer_service.manager
            if hasattr(manager, '_sync_channels_from_asterisk'):
                await manager._sync_channels_from_asterisk()
                logger.debug("Синхронизация с Asterisk выполнена")
                
    except Exception as e:
        logger.error(f"Ошибка синхронизации с Asterisk: {e}")
