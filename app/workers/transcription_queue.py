# app/workers/transcription_queue.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обработка очереди транскрибации
"""

from app.core.logger import logger
from app.services import get_transcription_service


async def process_transcription_queue():
    """Обработка очереди транскрибации (вызывается периодически)"""
    # Основная логика уже в TranscriptionService._process_transcription_queue
    # Этот воркер просто проверяет, что процесс запущен
    try:
        transcription_service = get_transcription_service()
        info = transcription_service.get_info()
        
        if info.get('queue_size', 0) > 0:
            logger.debug(f"Очередь транскрибации: {info['queue_size']} задач, активно: {info.get('active_tasks', 0)}")
    except Exception as e:
        logger.error(f"Ошибка проверки очереди транскрибации: {e}")
