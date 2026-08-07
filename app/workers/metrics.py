# app/workers/metrics.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обновление метрик
"""

from app.core.logger import logger
from app.core.redis import get_redis_client, REDIS_KEYS
from app.services import get_dialer_service, get_system_service
from app.services.dialer import active_calls_gauge, queue_size_gauge


async def update_metrics_periodically():
    """Периодическое обновление Prometheus метрик"""
    try:
        redis_client = get_redis_client()
        dialer_service = get_dialer_service()

        # Обновляем метрики активных звонков (используем уже зарегистрированные
        # в app.services.dialer гейджи — повторная регистрация с тем же именем
        # в CollectorRegistry вызывает ValueError)
        if dialer_service:
            status = await dialer_service.get_status()
            active_calls_gauge.set(status.get('active_calls', 0))
            queue_size_gauge.set(await dialer_service.get_queue_size())

        # Обновляем системные метрики
        try:
            system_service = get_system_service()
            await system_service._get_resource_usage()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Ошибка обновления метрик: {e}")
