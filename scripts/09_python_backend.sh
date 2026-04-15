#!/bin/bash
# =============================================
# AutoDialer Ultimate - Установка Python бэкенда
# Версия: 3.0.0
# =============================================

set -e

# =============================================
# Цвета для вывода в консоль
# =============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "\n${GREEN}[ШАГ]${NC} $1"; }
print_info() { echo -e "${BLUE}[ИНФО]${NC} $1"; }
print_success() { echo -e "${CYAN}[УСПЕХ]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[ВНИМАНИЕ]${NC} $1"; }
print_error() { echo -e "${RED}[ОШИБКА]${NC} $1"; }

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Загрузка конфигурации
# =============================================
print_step "Загрузка конфигурации..."

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
    print_success "Конфигурация загружена из .env"
else
    print_error "Файл .env не найден!"
    exit 1
fi

# =============================================
# Установка значений по умолчанию
# =============================================
FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
DB_NAME="${DB_NAME:-autodialer}"
DB_USER="${DB_USER:-autodialer}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
MAX_CALLS="${MAX_CALLS:-50}"
DEFAULT_CPS="${DEFAULT_CPS:-5}"
CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TTS_VOICE="${TTS_VOICE:-denis}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
LOG_FORMAT="${LOG_FORMAT:-console}"

print_info "FreePBX Extension: $FREEPBX_EXTENSION"
print_info "База данных:       $DB_NAME на $DB_HOST:$DB_PORT"
print_info "Redis:             $REDIS_HOST:$REDIS_PORT"
print_info "Макс. каналов:     $MAX_CALLS"

# =============================================
# Создание пользователя и директорий
# =============================================
print_step "Создание пользователя autodialer и директорий..."

# Создание пользователя, если не существует
if ! id -u autodialer &>/dev/null; then
    useradd -r -m -d /opt/autodialer -s /bin/false -c "AutoDialer Service" autodialer
    print_success "Пользователь 'autodialer' создан"
else
    print_info "Пользователь 'autodialer' уже существует"
fi

# Создание директорий
mkdir -p /opt/autodialer/{backend,logs,config,frontend/dist,scripts,tmp,venv}
mkdir -p /opt/autodialer/logs/{access,error}

print_success "Директории созданы"

# =============================================
# Настройка виртуального окружения Python
# =============================================
print_step "Настройка виртуального окружения Python..."

cd /opt/autodialer

# Создание виртуального окружения
python3 -m venv venv
print_success "Виртуальное окружение создано"

# Активация и обновление pip
source venv/bin/activate
pip install --upgrade pip setuptools wheel
print_success "pip обновлён"

# =============================================
# Установка зависимостей Python
# =============================================
print_step "Установка зависимостей Python..."

# Создание файла requirements.txt
cat > /opt/autodialer/requirements.txt << 'EOF'
# =============================================
# AutoDialer Ultimate - Зависимости Python
# =============================================

# Ядро
fastapi==0.115.11
uvicorn[standard]==0.34.0
pydantic==2.10.6
pydantic-settings==2.7.1

# База данных
asyncpg==0.30.0
sqlalchemy==2.0.36
alembic==1.14.1

# Redis
redis==5.2.1
hiredis==2.3.2

# AMI (Asterisk Manager Interface)
panoramisk==0.2.0

# Аутентификация
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.2.0
python-multipart==0.0.20

# HTTP и WebSocket
httpx==0.28.1
aiofiles==24.1.0
gunicorn==23.0.0

# Мониторинг
prometheus-client==0.21.0

# Утилиты
cachetools==5.5.0
tenacity==9.0.0
python-dateutil==2.9.0
python-dotenv==1.0.1
PyYAML==6.0.2

# Разработка (опционально)
watchfiles==1.0.4
EOF

# Установка зависимостей
pip install -r requirements.txt
print_success "Зависимости Python установлены"

# =============================================
# Копирование файлов бэкенда
# =============================================
print_step "Копирование файлов бэкенда..."

if [ -d "$PROJECT_ROOT/backend" ]; then
    cp -r "$PROJECT_ROOT/backend/"* /opt/autodialer/backend/
    print_success "Файлы бэкенда скопированы"
else
    print_warn "Директория backend не найдена, создаю заглушку..."
    
    # Создание минимального main.py
    cat > /opt/autodialer/backend/main.py << 'EOF'
#!/usr/bin/env python3
"""AutoDialer Ultimate - Основное приложение"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AutoDialer Ultimate", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}

@app.get("/")
async def root():
    return {"message": "AutoDialer Ultimate API"}
EOF

    # Создание __init__.py
    touch /opt/autodialer/backend/__init__.py
    
    print_warn "Созданы заглушки файлов бэкенда"
fi

# =============================================
# Создание файла конфигурации .env для бэкенда
# =============================================
print_step "Создание конфигурации бэкенда..."

# Генерация секретов, если не заданы
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
AMI_PASSWORD="${AMI_PASSWORD:-$(openssl rand -hex 16)}"
METRICS_PASS="${METRICS_PASS:-$(openssl rand -hex 8)}"

# Сохранение секретов в основной .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    grep -q "^JWT_SECRET=" "$PROJECT_ROOT/.env" || echo "JWT_SECRET=$JWT_SECRET" >> "$PROJECT_ROOT/.env"
    grep -q "^AMI_PASSWORD=" "$PROJECT_ROOT/.env" || echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$PROJECT_ROOT/.env"
    grep -q "^METRICS_PASS=" "$PROJECT_ROOT/.env" || echo "METRICS_PASS=$METRICS_PASS" >> "$PROJECT_ROOT/.env"
fi

# Создание .env для бэкенда
cat > /opt/autodialer/config/.env << EOF
# =============================================
# AutoDialer Ultimate - Конфигурация бэкенда
# Версия: 3.0.0
# =============================================

# Сервер FreePBX
FREEPBX_HOST=${FREEPBX_IP}
FREEPBX_EXTENSION=${FREEPBX_EXTENSION}

# Asterisk AMI
AMI_HOST=127.0.0.1
AMI_PORT=5038
AMI_USER=autodialer
AMI_PASSWORD=${AMI_PASSWORD}

# База данных PostgreSQL
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT}
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}

# Redis
REDIS_HOST=${REDIS_HOST}
REDIS_PORT=${REDIS_PORT}
REDIS_PASSWORD=${REDIS_PASSWORD:-}

# JWT аутентификация
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE=3600
REFRESH_TOKEN_EXPIRE=604800

# Настройки дозвона
MAX_CALLS=${MAX_CALLS}
DEFAULT_CPS=${DEFAULT_CPS}
CALL_TIMEOUT=${CALL_TIMEOUT}
MAX_RETRIES=${MAX_RETRIES}
CALLER_ID=${CALLER_ID:-AutoDialer}

# Настройки TTS
TTS_ENGINE=piper
TTS_VOICE=${TTS_VOICE}
TTS_MODEL=/var/lib/asterisk/sounds/tts/models/ru_RU-\${TTS_VOICE}-medium.onnx
TTS_OUTPUT_DIR=/var/lib/asterisk/sounds/tts

# Метрики
METRICS_USER=admin
METRICS_PASS=${METRICS_PASS}

# CORS
CORS_ORIGINS=*

# Логирование
LOG_LEVEL=${LOG_LEVEL}
LOG_FORMAT=${LOG_FORMAT}
LOG_FILE=/opt/autodialer/logs/autodialer.log

# Хранение
AUDIO_RETENTION_DAYS=30
MAX_UPLOAD_SIZE_MB=10
EOF

print_success "Конфигурация бэкенда создана"

# =============================================
# Копирование файлов фронтенда
# =============================================
print_step "Копирование файлов фронтенда..."

if [ -d "$PROJECT_ROOT/frontend/dist" ]; then
    cp -r "$PROJECT_ROOT/frontend/dist/"* /opt/autodialer/frontend/dist/
    print_success "Файлы фронтенда скопированы"
else
    print_warn "Директория frontend/dist не найдена, создаю заглушку..."
    
    cat > /opt/autodialer/frontend/dist/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>AutoDialer Ultimate</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .container { text-align: center; }
        h1 { font-size: 3rem; margin-bottom: 1rem; }
        p { font-size: 1.2rem; opacity: 0.9; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 AutoDialer Ultimate</h1>
        <p>Версия 3.0.0</p>
        <p>Бэкенд запущен. Фронтенд будет доступен после полной установки.</p>
    </div>
</body>
</html>
EOF
    print_warn "Создана заглушка фронтенда"
fi

# =============================================
# Установка прав доступа
# =============================================
print_step "Установка прав доступа..."

chown -R autodialer:autodialer /opt/autodialer
chmod -R 755 /opt/autodialer
chmod 600 /opt/autodialer/config/.env

print_success "Права доступа установлены"

# =============================================
# Создание systemd сервиса
# =============================================
print_step "Создание systemd сервиса..."

cat > /etc/systemd/system/autodialer.service << EOF
[Unit]
Description=AutoDialer Ultimate Backend Service
Documentation=https://github.com/naumenis-code/AutoDialer-Ultimate
After=network.target postgresql.service redis-server.service asterisk.service
Wants=network-online.target

[Service]
Type=exec
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/venv/bin"
EnvironmentFile=/opt/autodialer/config/.env
ExecStart=/opt/autodialer/venv/bin/gunicorn \\
    -w 4 \\
    --threads 8 \\
    -k uvicorn.workers.UvicornWorker \\
    --bind 127.0.0.1:8000 \\
    --access-logfile /opt/autodialer/logs/access.log \\
    --error-logfile /opt/autodialer/logs/error.log \\
    --log-level info \\
    --timeout 120 \\
    --graceful-timeout 30 \\
    --max-requests 10000 \\
    --max-requests-jitter 1000 \\
    main:app
Restart=always
RestartSec=5
LimitNOFILE=655350
LimitNPROC=655350
MemoryMax=2G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
print_success "Systemd сервис создан"

# =============================================
# Создание вспомогательных скриптов
# =============================================
print_step "Создание вспомогательных скриптов..."

# Скрипт статуса
cat > /usr/local/bin/autodialer-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Ultimate - Статус"
echo "=============================================="
echo ""
systemctl status autodialer --no-pager -l
echo ""
echo "=============================================="
echo "Последние логи:"
echo "=============================================="
journalctl -u autodialer -n 20 --no-pager
EOF
chmod +x /usr/local/bin/autodialer-status

# Скрипт перезапуска
cat > /usr/local/bin/autodialer-restart << 'EOF'
#!/bin/bash
systemctl restart autodialer
echo "AutoDialer перезапущен"
systemctl status autodialer --no-pager
EOF
chmod +x /usr/local/bin/autodialer-restart

# Скрипт просмотра логов
cat > /usr/local/bin/autodialer-logs << 'EOF'
#!/bin/bash
journalctl -u autodialer -f
EOF
chmod +x /usr/local/bin/autodialer-logs

print_success "Вспомогательные скрипты созданы"

# =============================================
# Запуск сервиса
# =============================================
print_step "Запуск бэкенд сервиса..."

systemctl enable autodialer
systemctl start autodialer

# Ожидание запуска
sleep 3

if systemctl is-active --quiet autodialer; then
    print_success "Бэкенд сервис запущен"
else
    print_error "Бэкенд сервис не запустился"
    systemctl status autodialer --no-pager
    exit 1
fi

# =============================================
# Проверка бэкенда
# =============================================
print_step "Проверка бэкенда..."

sleep 2
if curl -s http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "ok"; then
    print_success "Health check пройден"
    echo ""
    curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool 2>/dev/null || true
else
    print_warn "Health check не пройден (сервис может ещё запускаться)"
fi

# =============================================
# Сводка
# =============================================
print_step "Сводка установки Python бэкенда"
echo ""
print_info "Параметры бэкенда:"
echo "  Пользователь:      autodialer"
echo "  Директория:        /opt/autodialer"
echo "  Конфигурация:      /opt/autodialer/config/.env"
echo "  Логи:              /opt/autodialer/logs/"
echo ""
print_info "Параметры подключения:"
echo "  FreePBX Host:      $FREEPBX_IP"
echo "  FreePBX Extension: $FREEPBX_EXTENSION"
echo "  База данных:       $DB_NAME на $DB_HOST:$DB_PORT"
echo "  Redis:             $REDIS_HOST:$REDIS_PORT"
echo ""
print_info "Сгенерированные секреты:"
echo "  JWT_SECRET:        $JWT_SECRET"
echo "  AMI_PASSWORD:      $AMI_PASSWORD"
echo "  METRICS_PASS:      $METRICS_PASS"
echo ""
print_info "Эндпоинты:"
echo "  API:               http://127.0.0.1:8000/api"
echo "  Health:            http://127.0.0.1:8000/api/health"
echo "  Метрики:           http://127.0.0.1:8000/metrics"
echo "  Документация:      http://127.0.0.1:8000/docs"
echo ""
print_info "Вспомогательные скрипты:"
echo "  autodialer-status   - Статус сервиса и логи"
echo "  autodialer-restart  - Перезапуск сервиса"
echo "  autodialer-logs     - Просмотр логов в реальном времени"
echo ""
print_info "Полезные команды:"
echo "  systemctl status autodialer"
echo "  systemctl restart autodialer"
echo "  journalctl -u autodialer -f"
echo ""

print_success "Установка Python бэкенда завершена!"
