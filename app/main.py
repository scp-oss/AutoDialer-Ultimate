#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoDialer Ultimate - Точка входа приложения
Версия: 3.0.0

Минимальный файл для запуска FastAPI приложения.
Вся логика инициализации вынесена в app/__init__.py.

Запуск:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    
    или
    
    python -m app.main
"""

import os
import sys
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Загружаем переменные окружения из .env файла
from dotenv import load_dotenv
env_file = ROOT_DIR / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Импортируем приложение
from app import create_app, __version__, logger

# Создаём экземпляр приложения
app = create_app()


# =============================================
# Точка входа для прямого запуска
# =============================================
if __name__ == "__main__":
    import uvicorn
    from app.core.config import settings
    
    logger.info(f"Запуск AutoDialer Ultimate v{__version__}")
    logger.info(f"Окружение: {settings.ENVIRONMENT}")
    logger.info(f"Адрес: http://{settings.APP_HOST}:{settings.APP_PORT}")
    logger.info(f"Документация: http://{settings.APP_HOST}:{settings.APP_PORT}/docs")
    
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS if not settings.DEBUG else 1,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=settings.DEBUG,
    )
