# AutoDialer Ultimate - backend image (FastAPI app in app/)
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# System dependencies:
# - libpq-dev/gcc: build asyncpg/bcrypt native extensions
# - sox, ffmpeg: audio conversion (used by app.services.audio / transcription)
# - curl: container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    sox \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements/base.txt /srv/app/requirements/base.txt
RUN pip install --no-cache-dir -r app/requirements/base.txt

# Optional TTS support (Piper). Comment out to build a smaller image without it.
COPY app/requirements/tts.txt /srv/app/requirements/tts.txt
RUN pip install --no-cache-dir -r app/requirements/tts.txt

COPY app /srv/app
COPY alembic /srv/alembic
COPY alembic.ini /srv/alembic.ini
COPY sql /srv/sql
COPY docker/backend-entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && useradd -m -u 1000 autodialer \
    && mkdir -p /opt/autodialer/logs /opt/autodialer/data \
    && chown -R autodialer:autodialer /srv /opt/autodialer
USER autodialer

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-"]
