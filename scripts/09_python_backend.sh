#!/bin/bash
# =============================================
# AutoDialer Ultimate - Python Backend Setup (FIXED)
# Version: 3.0.3 (ENTERPRISE)
# Description: Установка и настройка Python бэкенда (БЕЗ Alembic)
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# =============================================
# 🔥 ПРАВИЛЬНАЯ ЗАГРУЗКА .env
# =============================================
load_env() {
    if [ -f "$PROJECT_ROOT/.env" ]; then
        set -a
        source "$PROJECT_ROOT/.env"
        set +a
    fi
}

load_env

# =============================================
# Цвета для вывода
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

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${BOLD}${CYAN}▶ $1${NC}"; }

# =============================================
# Проверка прав root
# =============================================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Требуются права root. Используйте: sudo $0"
        exit 1
    fi
}

# =============================================
# Проверка идемпотентности
# =============================================
INSTALLED_MARKER="/opt/autodialer/.backend_installed"

check_already_installed() {
    if [ -f "$INSTALLED_MARKER" ] && [ "${FORCE_REINSTALL:-false}" != "true" ]; then
        log_warn "Python бэкенд уже установлен"
        exit 0
    fi
    # Bare `test && action` as the last statement of a function aborts the
    # whole script under `set -e` when the test is false (its exit code
    # becomes the function's own exit code, and check_already_installed is
    # called unguarded from main()) - the trailing `true` keeps the no-op
    # case a success. This is what silently killed a live install:
    # FORCE_REINSTALL unset -> false -> script exit code 1, zero output.
    [ "${FORCE_REINSTALL:-false}" = "true" ] && rm -f "$INSTALLED_MARKER"
    true
}

# =============================================
# Проверка зависимостей
# =============================================
check_dependencies() {
    log_step "Проверка зависимостей..."
    
    local missing=()
    
    command -v python3 &>/dev/null || missing+=("python3")
    python3 -m pip --version &>/dev/null || missing+=("python3-pip")
    python3 -m venv --help &>/dev/null || missing+=("python3-venv")
    command -v pg_isready &>/dev/null || missing+=("postgresql-client")
    command -v redis-cli &>/dev/null || missing+=("redis-tools")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_warn "Отсутствуют зависимости: ${missing[*]}"
        apt-get update -qq
        apt-get install -y -qq "${missing[@]}"
    fi
    
    log_success "Все зависимости установлены"
}

# =============================================
# Проверка конфигурации
# =============================================
check_env_vars() {
    log_step "Проверка конфигурации..."
    
    local missing=()
    
    [ -z "${DB_PASSWORD:-}" ] && missing+=("DB_PASSWORD")
    [ -z "${JWT_SECRET:-}" ] && missing+=("JWT_SECRET")
    [ -z "${AMI_PASSWORD:-}" ] && missing+=("AMI_PASSWORD")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Отсутствуют обязательные переменные: ${missing[*]}"
        exit 1
    fi
    
    export DB_HOST="${DB_HOST:-localhost}"
    export DB_PORT="${DB_PORT:-5432}"
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    export REDIS_HOST="${REDIS_HOST:-localhost}"
    export REDIS_PORT="${REDIS_PORT:-6379}"
    export REDIS_PASSWORD="${REDIS_PASSWORD:-}"
    export WORKERS="${WORKERS:-4}"
    export HOST="${HOST:-0.0.0.0}"
    export PORT="${PORT:-8000}"
    
    log_success "Конфигурация проверена"
    log_info "  DB: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    log_info "  Redis: ${REDIS_HOST}:${REDIS_PORT}"
    log_info "  Workers: $WORKERS"
}

# =============================================
# Генерация секретов
# =============================================
generate_secrets() {
    log_step "Проверка секретов..."
    
    local secrets_updated=false
    
    if [ -z "${ADMIN_PASSWORD:-}" ]; then
        ADMIN_PASSWORD=$(openssl rand -base64 16 2>/dev/null || echo "Admin_$(date +%s)")
        echo "ADMIN_PASSWORD=$ADMIN_PASSWORD" >> "$PROJECT_ROOT/.env"
        export ADMIN_PASSWORD
        secrets_updated=true
        log_info "Сгенерирован пароль администратора"
    fi
    
    if [ -z "${METRICS_PASS:-}" ]; then
        METRICS_PASS=$(openssl rand -base64 12 2>/dev/null || echo "metrics_$(date +%s)")
        echo "METRICS_PASS=$METRICS_PASS" >> "$PROJECT_ROOT/.env"
        export METRICS_PASS
        secrets_updated=true
        log_info "Сгенерирован пароль для метрик"
    fi
    
    # Same set -e trap as check_already_installed() above: ADMIN_PASSWORD
    # and METRICS_PASS are typically already set by install.sh's own
    # generate_secret() by the time this runs, so secrets_updated stays
    # false here and this bare `&&` would otherwise kill the script.
    [ "$secrets_updated" = true ] && log_success "Секреты сгенерированы"
    true
}

# =============================================
# Копирование файлов бэкенда
# =============================================
copy_backend_files() {
    log_step "Копирование файлов бэкенда..."
    
    mkdir -p /opt/autodialer/backend
    
    if [ -d "$PROJECT_ROOT/backend" ]; then
        cp -r "$PROJECT_ROOT/backend/"* /opt/autodialer/backend/
        log_success "Файлы скопированы из backend/"
    elif [ -d "$PROJECT_ROOT/app" ]; then
        # Модульная структура
        mkdir -p /opt/autodialer/backend/app
        cp -r "$PROJECT_ROOT/app/"* /opt/autodialer/backend/app/
        [ -d "$PROJECT_ROOT/utils" ] && cp -r "$PROJECT_ROOT/utils" /opt/autodialer/backend/
        [ -f "$PROJECT_ROOT/main.py" ] && cp "$PROJECT_ROOT/main.py" /opt/autodialer/backend/
        # install_requirements() below looks for requirements/prod.txt
        # relative to /opt/autodialer/backend - the real files live in
        # app/requirements/ (same ones the Docker build uses), which the
        # `cp -r app/*` above already lands one level too deep, at
        # backend/app/requirements/. Copy them to where it actually looks.
        [ -d "$PROJECT_ROOT/app/requirements" ] && cp -r "$PROJECT_ROOT/app/requirements" /opt/autodialer/backend/
        log_success "Файлы скопированы (модульная структура)"
    else
        log_error "Директория backend не найдена"
        exit 1
    fi
    
    cp "$PROJECT_ROOT/.env" /opt/autodialer/.env 2>/dev/null || true
    chmod 600 /opt/autodialer/.env 2>/dev/null || true
    
    chown -R autodialer:autodialer /opt/autodialer/backend
    chmod -R 755 /opt/autodialer/backend
}

# =============================================
# Создание виртуального окружения
# =============================================
setup_virtualenv() {
    log_step "Настройка виртуального окружения..."
    
    cd /opt/autodialer/backend
    
    [ -d "venv" ] && [ "${FORCE_REINSTALL:-false}" = "true" ] && rm -rf venv
    [ ! -d "venv" ] && python3 -m venv venv
    
    source venv/bin/activate
    
    pip install --upgrade pip setuptools wheel -q 2>/dev/null || true
    
    log_success "Виртуальное окружение готово"
    log_info "Python: $(python3 --version)"
}

# =============================================
# Установка зависимостей
# =============================================
install_requirements() {
    log_step "Установка Python зависимостей..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    # Исправляем версию panoramisk если нужно
    if [ -f "requirements/base.txt" ]; then
        sed -i 's/panoramisk.*/panoramisk>=1.4/' requirements/base.txt 2>/dev/null || true
    fi
    
    # Устанавливаем bcrypt и passlib
    log_info "Установка bcrypt и passlib..."
    pip install --no-cache-dir bcrypt==4.1.2 2>/dev/null || pip install --no-cache-dir bcrypt==4.0.1 2>/dev/null || true
    pip install --no-cache-dir "passlib[bcrypt]==1.7.4" 2>/dev/null || pip install --no-cache-dir passlib==1.7.4 2>/dev/null || true
    
    # Устанавливаем основные зависимости
    local req_file=""
    [ -f "requirements/prod.txt" ] && req_file="requirements/prod.txt"
    [ -z "$req_file" ] && [ -f "requirements.txt" ] && req_file="requirements.txt"
    
    if [ -n "$req_file" ]; then
        log_info "Установка из $req_file..."
        for i in 1 2 3; do
            if pip install -r "$req_file" 2>/dev/null; then
                log_success "Зависимости установлены"
                break
            fi
            [ $i -eq 3 ] && { log_error "Не удалось установить зависимости"; exit 1; }
            sleep 3
        done
    fi
    
    # TTS (опционально)
    if [ "${SKIP_TTS:-false}" != "true" ] && [ -f "requirements/tts.txt" ]; then
        log_info "Установка TTS..."
        pip install --prefer-binary piper-tts 2>/dev/null || true
        pip install -r requirements/tts.txt 2>/dev/null || true
    fi
    
    log_success "Зависимости установлены"
}

# =============================================
# Проверка импортов
# =============================================
verify_imports() {
    log_step "Проверка импорта модулей..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    python3 << 'EOF'
import sys
import importlib

modules = ["fastapi", "uvicorn", "sqlalchemy", "asyncpg", "redis.asyncio",
           "pydantic", "pydantic_settings", "jose", "passlib", "bcrypt",
           "httpx", "aiohttp", "panoramisk"]

failed = []
for module in modules:
    try:
        importlib.import_module(module)
        print(f"✅ {module}")
    except ImportError as e:
        print(f"❌ {module}: {e}")
        failed.append(module)

if failed:
    print(f"\n🔥 Не удалось импортировать: {', '.join(failed)}")
    sys.exit(1)

print("\n✅ Все модули импортированы")
EOF
    
    [ $? -eq 0 ] || { log_error "Проверка импортов не пройдена"; exit 1; }
    log_success "Проверка импортов пройдена"
}

# =============================================
# 🔥 НАСТРОЙКА SYSTEMD СЕРВИСА (ДО МИГРАЦИЙ)
# =============================================
setup_systemd() {
    log_step "Настройка systemd сервиса..."
    
    cat > /etc/systemd/system/autodialer.service << 'EOF'
[Unit]
Description=AutoDialer Ultimate Backend
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service
StartLimitBurst=5
StartLimitIntervalSec=60

[Service]
Type=simple
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
# systemd's own $VAR substitution in ExecStart/ExecStartPre does not
# support bash's ${VAR:-default} fallback syntax - it would pass the
# literal, unexpanded string as an argument (this is exactly what broke
# gunicorn: "-w '${WORKERS:-4}'" was passed through verbatim, not
# resolved to a number). These Environment= lines are real systemd-level
# defaults; EnvironmentFile= below is read after them, so .env silently
# overrides any of these that it actually sets.
Environment="WORKERS=4"
Environment="HOST=0.0.0.0"
Environment="PORT=8000"
Environment="DB_HOST=127.0.0.1"
Environment="DB_PORT=5432"
Environment="REDIS_HOST=127.0.0.1"
Environment="REDIS_PORT=6379"
EnvironmentFile=/opt/autodialer/.env

# -a "$REDIS_PASSWORD" matters here, not just for correctness: redis-cli
# against a password-protected server prints "NOAUTH Authentication
# required." but still exits 0, so without the password this readiness
# check silently "passes" even when Redis auth is completely broken.
ExecStartPre=/bin/bash -c 'until pg_isready -h "$DB_HOST" -p "$DB_PORT"; do sleep 1; done'
ExecStartPre=/bin/bash -c 'until redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ${REDIS_PASSWORD:+-a "$REDIS_PASSWORD"} ping 2>/dev/null | grep -q PONG; do sleep 1; done'

ExecStart=/opt/autodialer/backend/venv/bin/gunicorn \
    -w ${WORKERS} \
    -k uvicorn.workers.UvicornWorker \
    -b ${HOST}:${PORT} \
    --access-logfile /opt/autodialer/logs/backend/access.log \
    --error-logfile /opt/autodialer/logs/backend/error.log \
    --timeout 120 \
    --graceful-timeout 30 \
    backend.main:app

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # Если backend.main не найден, пробуем app.main
    if [ ! -f "/opt/autodialer/backend/backend/main.py" ] && [ -f "/opt/autodialer/backend/app/main.py" ]; then
        sed -i 's|backend.main:app|app.main:app|g' /etc/systemd/system/autodialer.service
    fi
    
    mkdir -p /opt/autodialer/logs/backend
    chown -R autodialer:autodialer /opt/autodialer/logs
    
    systemctl daemon-reload
    log_success "Systemd сервис создан"
}

# =============================================
# Ожидание баз данных
# =============================================
wait_for_databases() {
    log_step "Ожидание баз данных..."
    
    log_info "Ожидание PostgreSQL..."
    for i in $(seq 1 30); do
        pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null && break
        sleep 1
    done
    pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null || { log_error "PostgreSQL не ответил"; exit 1; }
    log_success "PostgreSQL готов"
    
    log_info "Ожидание Redis..."
    for i in $(seq 1 30); do
        redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ${REDIS_PASSWORD:+-a "$REDIS_PASSWORD"} ping &>/dev/null && break
        sleep 1
    done
    log_success "Redis готов"
}

# =============================================
# 🔥 НАСТРОЙКА БАЗЫ ДАННЫХ (ПРЯМОЙ SQL, БЕЗ ALEMBIC)
# =============================================
setup_database() {
    log_step "Настройка базы данных..."
    
    # Ищем файл схемы
    local schema_file=""
    [ -f "/opt/autodialer/sql/schema.sql" ] && schema_file="/opt/autodialer/sql/schema.sql"
    [ -z "$schema_file" ] && [ -f "$PROJECT_ROOT/sql/schema.sql" ] && schema_file="$PROJECT_ROOT/sql/schema.sql"
    [ -z "$schema_file" ] && [ -f "/opt/autodialer/backend/sql/schema.sql" ] && schema_file="/opt/autodialer/backend/sql/schema.sql"
    
    # scripts/07_postgresql_setup.sh already applies this exact schema.sql,
    # as the postgres superuser, and grants $DB_USER privileges on every
    # object it creates - it runs before this script in install.sh's
    # ALL_SCRIPTS order. Re-applying it here AS $DB_USER (not postgres)
    # doesn't create anything new - every table already exists, owned by
    # postgres - and instead spews an "ОШИБКА: нужно быть владельцем..."
    # for every ALTER TABLE/CREATE OR REPLACE FUNCTION/DROP TRIGGER/CREATE
    # VIEW statement in the file, since $DB_USER isn't the owner of any of
    # them. Skip it when 07's marker shows the schema is already in place;
    # only fall back to applying it here (e.g. someone ran with
    # --skip-postgres) when that marker is absent.
    if [ -f /opt/autodialer/.postgresql_configured ]; then
        log_info "Схема уже применена скриптом 07_postgresql_setup.sh, пропускаю повторное применение"
    elif [ -n "$schema_file" ]; then
        log_info "Применение схемы из $schema_file..."
        PGPASSWORD="${DB_PASSWORD}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$schema_file" 2>&1 | grep -v "уже существует" | grep -v "NOTICE" || true
        log_success "Схема применена"
    else
        log_warn "Файл схемы не найден, создаю базовые таблицы..."
        
        PGPASSWORD="${DB_PASSWORD}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" << 'EOSQL'
-- Базовые таблицы для AutoDialer
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email VARCHAR(255),
    full_name VARCHAR(255),
    role VARCHAR(20) DEFAULT 'operator',
    is_active BOOLEAN DEFAULT TRUE,
    force_password_change BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    max_calls INTEGER DEFAULT 30,
    cps INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active',
    blacklisted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS call_results (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER,
    contact_id INTEGER,
    status VARCHAR(50),
    duration INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS blacklist (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO settings (key, value, description) VALUES 
    ('system_enabled', 'true', 'Global system enable/disable'),
    ('global_max_calls', '50', 'Maximum concurrent calls')
ON CONFLICT (key) DO NOTHING;

-- Администратор по умолчанию (пароль: admin)
INSERT INTO users (username, password_hash, role, email, force_password_change) VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIqK0hVdGW',
    'admin',
    'admin@localhost',
    TRUE
) ON CONFLICT (username) DO NOTHING;
EOSQL
        log_success "Базовые таблицы созданы"
    fi
}

# =============================================
# Создание администратора
# =============================================
create_admin_user() {
    log_step "Создание администратора..."

    # sql/schema.sql seeds a hardcoded default admin user (username admin,
    # a bcrypt hash of the literal string "admin" baked into the SQL file
    # itself) completely independently of $ADMIN_PASSWORD. This function
    # used to only ever WRITE $ADMIN_PASSWORD to a credentials file
    # without ever setting it as the real database password - so every
    # fresh install actually logged in with the well-known default
    # admin/admin, while the install summary showed the operator a random
    # password that never worked. Hash $ADMIN_PASSWORD with the same
    # bcrypt scheme app/core/security.py uses and write it into the DB.
    local venv_python="/opt/autodialer/backend/venv/bin/python3"
    local admin_hash=""

    if [ -x "$venv_python" ]; then
        admin_hash="$(ADMIN_PASSWORD="$ADMIN_PASSWORD" "$venv_python" -c '
import os
import bcrypt
pw = os.environ["ADMIN_PASSWORD"].encode("utf-8")
print(bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8"))
' 2>/dev/null)"
    fi

    if [ -n "$admin_hash" ]; then
        if PGPASSWORD="${DB_PASSWORD}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
            -c "UPDATE users SET password_hash = '${admin_hash}', force_password_change = TRUE WHERE username = '${ADMIN_USERNAME:-admin}';" \
            >/dev/null 2>&1; then
            log_success "Пароль администратора в БД установлен из ADMIN_PASSWORD (.env)"
        else
            log_warn "Не удалось обновить пароль администратора в БД - логин admin/admin из schema.sql может ещё действовать"
        fi
    else
        log_warn "Не удалось сгенерировать хеш пароля администратора (venv/bcrypt недоступны) - логин admin/admin из schema.sql может ещё действовать"
    fi

    cat > /opt/autodialer/.admin_credentials << EOF
============================================
AutoDialer Ultimate - Admin Credentials
============================================
Username: ${ADMIN_USERNAME:-admin}
Password: ${ADMIN_PASSWORD}
Generated: $(date)
============================================
IMPORTANT: Change this password after first login!
============================================
EOF
    chmod 600 /opt/autodialer/.admin_credentials

    log_success "Учётные данные сохранены в /opt/autodialer/.admin_credentials"
}

# =============================================
# Создание скриптов управления
# =============================================
create_management_scripts() {
    log_step "Создание скриптов управления..."
    
    cat > /usr/local/bin/autodialer-status << 'EOF'
#!/bin/bash
systemctl status autodialer --no-pager
EOF
    chmod +x /usr/local/bin/autodialer-status
    
    cat > /usr/local/bin/autodialer-logs << 'EOF'
#!/bin/bash
journalctl -u autodialer -f "$@"
EOF
    chmod +x /usr/local/bin/autodialer-logs
    
    cat > /usr/local/bin/autodialer-restart << 'EOF'
#!/bin/bash
systemctl restart autodialer
echo "AutoDialer перезапущен"
EOF
    chmod +x /usr/local/bin/autodialer-restart
    
    log_success "Скрипты управления созданы"
}

# =============================================
# Запуск сервиса
# =============================================
start_service() {
    log_step "Запуск сервиса..."
    
    systemctl enable autodialer
    systemctl start autodialer
    
    # /api/health always returns HTTP 200 with a body like
    # {"status": "healthy"|"degraded"|"unhealthy"|"starting", ...} - none
    # of those values contain the substring "ok", so `grep -q "ok"` never
    # matched and this loop always ran its full 30 attempts even when the
    # backend was genuinely healthy the whole time.
    local health_re='"status"[[:space:]]*:[[:space:]]*"\(healthy\|degraded\)"'

    log_info "Ожидание бэкенда..."
    for i in $(seq 1 30); do
        curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "$health_re" && break
        sleep 2
    done

    if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "$health_re"; then
        log_success "Бэкенд запущен"
    else
        log_warn "Бэкенд не ответил, проверьте логи"
        journalctl -u autodialer -n 20 --no-pager
    fi
}

# =============================================
# Проверка установки
# =============================================
verify_installation() {
    log_step "Проверка установки..."

    systemctl is-active --quiet autodialer && log_success "Сервис работает" || log_warn "Сервис не запущен"
    curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q '"status"[[:space:]]*:[[:space:]]*"\(healthy\|degraded\)"' && log_success "API отвечает" || log_warn "API не отвечает"
}

# =============================================
# Создание маркера
# =============================================
mark_installed() {
    mkdir -p /opt/autodialer
    echo "$(date)" > "$INSTALLED_MARKER"
    log_success "Маркер установки создан"
}

# =============================================
# Вывод сводки
# =============================================
print_summary() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}${BOLD}✅ Python бэкенд установлен!${NC}"
    echo "=============================================="
    echo ""
    echo "Доступ:"
    echo "  • API:           http://${HOST}:${PORT}/api"
    echo "  • Документация:  http://${HOST}:${PORT}/docs"
    echo "  • Health check:  http://${HOST}:${PORT}/api/health"
    echo ""
    echo "Учётные данные:"
    echo "  • Администратор: ${ADMIN_USERNAME:-admin}"
    echo "  • Пароль:        сохранён в /opt/autodialer/.admin_credentials"
    echo ""
    echo "Управление:"
    echo "  • autodialer-status"
    echo "  • autodialer-logs"
    echo "  • autodialer-restart"
    echo ""
    echo "=============================================="
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ (ИСПРАВЛЕННЫЙ ПОРЯДОК)
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Python Backend Setup${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.3 (FIXED)${NC}"
    echo "=============================================="
    echo ""
    
    check_root
    check_already_installed
    check_dependencies
    check_env_vars
    generate_secrets
    
    copy_backend_files
    setup_virtualenv
    install_requirements
    verify_imports
    
    # 🔥 СЕРВИС И СКРИПТЫ ДО МИГРАЦИЙ
    setup_systemd
    create_management_scripts
    
    wait_for_databases
    setup_database
    create_admin_user
    
    start_service
    verify_installation
    mark_installed
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
