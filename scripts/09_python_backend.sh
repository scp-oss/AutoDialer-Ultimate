#!/bin/bash
# =============================================
# AutoDialer Ultimate - Установка Python бэкенда
# Версия: 3.0.0
# =============================================
# Устанавливает Python окружение, зависимости,
# копирует бэкенд, создаёт systemd сервис
# =============================================

set -euo pipefail

# =============================================
# Цвета и логирование
# =============================================
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; NC=''
fi

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "\n${BOLD}${CYAN}▶ $*${NC}"; }

# =============================================
# Загрузка конфигурации
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

# Установка значений по умолчанию
FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
DB_NAME="${DB_NAME:-autodialer}"
DB_USER="${DB_USER:-autodialer}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_PASSWORD="${DB_PASSWORD:-}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"
JWT_SECRET="${JWT_SECRET:-}"
AMI_PASSWORD="${AMI_PASSWORD:-}"
METRICS_PASS="${METRICS_PASS:-}"
MAX_CALLS="${MAX_CALLS:-50}"
DEFAULT_CPS="${DEFAULT_CPS:-5}"
CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TTS_VOICE="${TTS_VOICE:-denis}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
LOG_FORMAT="${LOG_FORMAT:-console}"
CORS_ORIGINS="${CORS_ORIGINS:-*}"

log_info "FreePBX Extension: $FREEPBX_EXTENSION"
log_info "База данных: $DB_NAME на $DB_HOST:$DB_PORT"
log_info "Redis: $REDIS_HOST:$REDIS_PORT"
log_info "Макс. каналов: $MAX_CALLS"

# =============================================
# Проверка идемпотентности
# =============================================
MARKER_FILE="/opt/autodialer/.python_backend_installed"

check_already_installed() {
    if [ -f "$MARKER_FILE" ]; then
        log_warn "Python бэкенд уже установлен (найден $MARKER_FILE)"
        log_info "Пропускаю установку..."
        exit 0
    fi
}

# =============================================
# Проверка обязательных переменных
# =============================================
check_required_vars() {
    local missing=()
    
    [ -z "$DB_PASSWORD" ] && missing+=("DB_PASSWORD")
    [ -z "$JWT_SECRET" ] && missing+=("JWT_SECRET")
    [ -z "$AMI_PASSWORD" ] && missing+=("AMI_PASSWORD")
    [ -z "$METRICS_PASS" ] && missing+=("METRICS_PASS")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Отсутствуют обязательные переменные:"
        for var in "${missing[@]}"; do
            echo "  - $var"
        done
        log_error "Запустите install.sh для генерации секретов"
        exit 1
    fi
}

# =============================================
# Создание пользователя и директорий
# =============================================
create_user_and_dirs() {
    log_step "Создание пользователя и директорий..."
    
    # Создание пользователя
    if ! id -u autodialer &>/dev/null; then
        useradd -r -m -d /opt/autodialer -s /bin/false -c "AutoDialer Service" autodialer
        log_success "Пользователь 'autodialer' создан"
    else
        log_info "Пользователь 'autodialer' уже существует"
    fi
    
    # Создание директорий
    mkdir -p /opt/autodialer/{backend,logs,config,frontend/dist,scripts,tmp,venv,data}
    mkdir -p /opt/autodialer/logs/{access,error}
    
    # Директория для degraded queue
    mkdir -p /opt/autodialer/data
    touch /opt/autodialer/data/degraded_queue.jsonl
    
    log_success "Директории созданы"
}

# =============================================
# Настройка виртуального окружения Python
# =============================================
setup_venv() {
    log_step "Настройка виртуального окружения Python..."
    
    cd /opt/autodialer
    
    # Удаление старого venv если есть
    if [ -d "venv" ] && [ ! -f "$MARKER_FILE" ]; then
        rm -rf venv
    fi
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        log_success "Виртуальное окружение создано"
    else
        log_info "Виртуальное окружение уже существует"
    fi
    
    # Активация и обновление pip
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel -q
    
    log_success "pip обновлён"
}

# =============================================
# Установка зависимостей Python
# =============================================
install_dependencies() {
    log_step "Установка зависимостей Python..."
    
    source /opt/autodialer/venv/bin/activate
    
    # Создание requirements.txt
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

# Быстрый JSON (опционально, fallback на json)
orjson==3.10.12

# Разработка
watchfiles==1.0.4
EOF

    # Установка с повторными попытками
    for i in {1..3}; do
        if pip install -r requirements.txt -q; then
            log_success "Зависимости установлены"
            return 0
        fi
        log_warn "Попытка $i не удалась, повтор через 5 сек..."
        sleep 5
    done
    
    log_error "Не удалось установить зависимости"
    return 1
}

# =============================================
# Копирование файлов бэкенда
# =============================================
copy_backend_files() {
    log_step "Копирование файлов бэкенда..."
    
    if [ -d "$PROJECT_ROOT/backend" ]; then
        cp -r "$PROJECT_ROOT/backend/"* /opt/autodialer/backend/
        log_success "Файлы бэкенда скопированы"
    else
        log_warn "Директория backend не найдена, создаю минимальный main.py..."
        
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
        touch /opt/autodialer/backend/__init__.py
        log_warn "Создан минимальный main.py"
    fi
    
    # Проверка наличия app
    if ! grep -q "app = FastAPI" /opt/autodialer/backend/main.py; then
        log_error "main.py не содержит FastAPI приложение"
        return 1
    fi
    
    log_success "Проверка main.py пройдена"
}

# =============================================
# Создание конфигурации .env для бэкенда
# =============================================
create_backend_env() {
    log_step "Создание конфигурации бэкенда..."
    
    cat > /opt/autodialer/config/.env << EOF
# =============================================
# AutoDialer Ultimate - Конфигурация бэкенда
# Версия: 3.0.0
# =============================================

# Сервер FreePBX
FREEPBX_HOST=${FREEPBX_IP:-192.168.1.100}
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
REDIS_PASSWORD=${REDIS_PASSWORD}

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
CORS_ORIGINS=${CORS_ORIGINS}

# Логирование
LOG_LEVEL=${LOG_LEVEL}
LOG_FORMAT=${LOG_FORMAT}
LOG_FILE=/opt/autodialer/logs/autodialer.log

# Хранение
AUDIO_RETENTION_DAYS=30
MAX_UPLOAD_SIZE_MB=10

# Degraded mode
DEGRADED_QUEUE_FILE=/opt/autodialer/data/degraded_queue.jsonl

# Trusted Proxies (для X-Forwarded-For)
TRUSTED_PROXIES=${TRUSTED_PROXIES:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}
EOF

    log_success "Конфигурация бэкенда создана"
}

# =============================================
# Копирование фронтенда
# =============================================
copy_frontend() {
    log_step "Копирование файлов фронтенда..."
    
    if [ -d "$PROJECT_ROOT/frontend/dist" ] && [ -n "$(ls -A "$PROJECT_ROOT/frontend/dist" 2>/dev/null)" ]; then
        cp -r "$PROJECT_ROOT/frontend/dist/"* /opt/autodialer/frontend/dist/
        log_success "Файлы фронтенда скопированы"
    else
        log_warn "Директория frontend/dist не найдена или пуста, создаю заглушку..."
        
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
        .status { margin-top: 2rem; padding: 1rem; background: rgba(255,255,255,0.1); border-radius: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 AutoDialer Ultimate</h1>
        <p>Версия 3.0.0</p>
        <div class="status">
            <p>Бэкенд запущен</p>
            <p><small>Загрузите фронтенд в /opt/autodialer/frontend/dist/</small></p>
        </div>
    </div>
</body>
</html>
EOF
        log_warn "Создана заглушка фронтенда"
    fi
}

# =============================================
# Установка прав доступа
# =============================================
set_permissions() {
    log_step "Установка прав доступа..."
    
    chown -R autodialer:autodialer /opt/autodialer
    chmod -R 755 /opt/autodialer
    chmod 600 /opt/autodialer/config/.env
    chmod 600 /opt/autodialer/data/degraded_queue.jsonl 2>/dev/null || true
    
    log_success "Права доступа установлены"
}

# =============================================
# Создание systemd сервиса
# =============================================
create_systemd_service() {
    log_step "Создание systemd сервиса..."
    
    cat > /etc/systemd/system/autodialer.service << 'EOF'
[Unit]
Description=AutoDialer Ultimate Backend Service
Documentation=https://github.com/naumenis-code/AutoDialer-Ultimate
After=network.target network-online.target postgresql.service redis-server.service asterisk.service
Wants=network-online.target

[Service]
Type=exec
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/opt/autodialer/config/.env
Environment="PYTHONUNBUFFERED=1"
Environment="LANG=en_US.UTF-8"
Environment="LC_ALL=en_US.UTF-8"

# Ожидание зависимостей
ExecStartPre=/bin/sleep 5

# Запуск Gunicorn
ExecStart=/opt/autodialer/venv/bin/gunicorn \
    -w 4 \
    --threads 8 \
    -k uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 \
    --access-logfile /opt/autodialer/logs/access.log \
    --error-logfile /opt/autodialer/logs/error.log \
    --log-level info \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 10000 \
    --max-requests-jitter 1000 \
    --worker-connections 1000 \
    main:app

Restart=always
RestartSec=5
StartLimitInterval=60
StartLimitBurst=5

# Лимиты ресурсов
LimitNOFILE=655350
LimitNPROC=655350
MemoryMax=2G
CPUQuota=200%

# Безопасность
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadOnlyPaths=/usr /etc
ReadWritePaths=/opt/autodialer/logs /opt/autodialer/data /tmp /var/log

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    log_success "Systemd сервис создан"
}

# =============================================
# Создание вспомогательных скриптов
# =============================================
create_helper_scripts() {
    log_step "Создание вспомогательных скриптов..."
    
    # Скрипт статуса
    cat > /usr/local/bin/autodialer-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Ultimate - Статус"
echo "=============================================="
echo ""
systemctl status autodialer --no-pager -l 2>/dev/null || echo "Сервис не найден"
echo ""
echo "=============================================="
echo "Последние логи:"
echo "=============================================="
journalctl -u autodialer -n 20 --no-pager 2>/dev/null || tail -20 /opt/autodialer/logs/autodialer.log
EOF
    chmod +x /usr/local/bin/autodialer-status
    
    # Скрипт перезапуска
    cat > /usr/local/bin/autodialer-restart << 'EOF'
#!/bin/bash
systemctl restart autodialer
echo "AutoDialer перезапущен"
sleep 2
systemctl status autodialer --no-pager
EOF
    chmod +x /usr/local/bin/autodialer-restart
    
    # Скрипт логов
    cat > /usr/local/bin/autodialer-logs << 'EOF'
#!/bin/bash
journalctl -u autodialer -f
EOF
    chmod +x /usr/local/bin/autodialer-logs
    
    # Скрипт проверки всех сервисов
    cat > /usr/local/bin/autodialer-all-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Ultimate - Статус всех сервисов"
echo "=============================================="
echo ""

SERVICES=("postgresql" "redis-server" "asterisk" "autodialer" "nginx" "fail2ban")

for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo "✅ $svc: работает"
    else
        echo "❌ $svc: остановлен"
    fi
done

echo ""
echo "=============================================="
echo "Ресурсы:"
echo "=============================================="
free -h
echo ""
df -h /opt/autodialer
EOF
    chmod +x /usr/local/bin/autodialer-all-status
    
    log_success "Вспомогательные скрипты созданы"
}

# =============================================
# Запуск сервиса
# =============================================
start_service() {
    log_step "Запуск бэкенд сервиса..."
    
    systemctl enable autodialer
    systemctl restart autodialer
    
    sleep 5
    
    if systemctl is-active --quiet autodialer; then
        log_success "Бэкенд сервис запущен"
    else
        log_warn "Бэкенд сервис не запустился"
    fi
}

# =============================================
# Проверка бэкенда
# =============================================
verify_backend() {
    log_step "Проверка бэкенда..."
    
    for i in {1..10}; do
        if curl -s http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "ok"; then
            log_success "Health check пройден"
            return 0
        fi
        sleep 2
    done
    
    log_warn "Health check не пройден (сервис может ещё запускаться)"
    return 1
}

# =============================================
# Сводка
# =============================================
show_summary() {
    echo ""
    log_success "=============================================="
    log_success "Установка Python бэкенда завершена!"
    log_success "=============================================="
    echo ""
    log_info "Параметры бэкенда:"
    echo "  Пользователь:      autodialer"
    echo "  Директория:        /opt/autodialer"
    echo "  Конфигурация:      /opt/autodialer/config/.env"
    echo "  Логи:              /opt/autodialer/logs/"
    echo ""
    log_info "Параметры подключения:"
    echo "  FreePBX Extension: $FREEPBX_EXTENSION"
    echo "  База данных:       $DB_NAME на $DB_HOST:$DB_PORT"
    echo "  Redis:             $REDIS_HOST:$REDIS_PORT"
    echo ""
    log_info "Сгенерированные секреты:"
    echo "  JWT_SECRET:        ${JWT_SECRET:0:16}..."
    echo "  AMI_PASSWORD:      ${AMI_PASSWORD:0:8}..."
    echo "  METRICS_PASS:      ${METRICS_PASS:0:8}..."
    echo ""
    log_info "Эндпоинты:"
    echo "  API:               http://127.0.0.1:8000/api"
    echo "  Health:            http://127.0.0.1:8000/api/health"
    echo "  Метрики:           http://127.0.0.1:8000/metrics"
    echo "  Документация:      http://127.0.0.1:8000/docs"
    echo ""
    log_info "Вспомогательные скрипты:"
    echo "  autodialer-status       - Статус сервиса"
    echo "  autodialer-restart      - Перезапуск"
    echo "  autodialer-logs         - Логи в реальном времени"
    echo "  autodialer-all-status   - Статус всех сервисов"
    echo ""
}

# =============================================
# Главная функция
# =============================================
main() {
    check_already_installed
    check_required_vars
    
    log_step "Установка Python бэкенда..."
    
    create_user_and_dirs
    setup_venv
    install_dependencies || {
        log_error "Не удалось установить зависимости"
        exit 1
    }
    copy_backend_files
    create_backend_env
    copy_frontend
    set_permissions
    create_systemd_service
    create_helper_scripts
    start_service
    verify_backend
    
    mkdir -p /opt/autodialer
    echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$MARKER_FILE"
    
    show_summary
}

main "$@"
