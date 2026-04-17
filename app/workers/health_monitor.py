# app/workers/health_monitor.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Мониторинг здоровья системы
"""

from app.core.logger import logger
from app.services import get_system_service


async def health_monitor():
    """Периодический мониторинг здоровья компонентов"""
    try:
        system_service = get_system_service()
        health = await system_service.health_check()
        
        if health.status != "healthy":
            logger.warning(f"Обнаружены проблемы со здоровьем: {health.status}")
            
            for component, status in health.components.items():
                if status.status != "healthy":
                    logger.warning(f"  - {component}: {status.status} - {status.error}")
                    
    except Exception as e:
        logger.error(f"Ошибка мониторинга здоровья: {e}")
