#!/bin/bash
# =============================================
# AutoDialer Ultimate - Python Backend Setup (FIXED)
# Version: 3.0.1
# Description: Установка и настройка Python бэкенда с проверками
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Загрузка конфигурации
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

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
        log_warn "Python бэкенд уже установлен (найден $INSTALLED_MARKER)"
        
        if [ "${NON_INTERACTIVE:-true}" != "true" ]; then
            read -p "Переустановить бэкенд? Данные БД не будут потеряны. [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "Установка отменена"
                exit 0
            fi
        fi
        
        log_warn "Продолжение установки..."
        rm -f "$INSTALLED_MARKER"
    fi
}

# =============================================
# 🔥 ПРОВЕРКА ЗАВИСИМОСТЕЙ
# =============================================
check_dependencies() {
    log_step "Проверка зависимостей..."
    
    local missing=()
    
    # Проверка Python
    if ! command -v python3 &>/dev/null; then
        missing+=("python3")
    fi
    
    # Проверка pip
    if ! python3 -m pip --version &>/dev/null; then
        missing+=("python3-pip")
    fi
    
    # Проверка venv
    if ! python3 -m venv --help &>/dev/null; then
        missing+=("python3-venv")
    fi
    
    # Проверка PostgreSQL клиента
    if ! command -v pg_isready &>/dev/null; then
        missing+=("postgresql-client")
    fi
    
    # Проверка Redis клиента
    if ! command -v redis-cli &>/dev/null; then
        missing+=("redis-tools")
    fi
    
    # Проверка build-essential (для компиляции bcrypt)
    if ! dpkg -l build-essential &>/dev/null; then
        missing+=("build-essential")
    fi
    
    # Проверка python3-dev (заголовочные файлы)
    if ! dpkg -l python3-dev &>/dev/null; then
        missing+=("python3-dev")
    fi
    
    # Проверка libffi-dev (для bcrypt)
    if ! dpkg -l libffi-dev &>/dev/null; then
        missing+=("libffi-dev")
    fi
    
    # Проверка libssl-dev
    if ! dpkg -l libssl-dev &>/dev/null; then
        missing+=("libssl-dev")
    fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_warn "Отсутствуют зависимости: ${missing[*]}"
        log_info "Установка..."
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq "${missing[@]}"
    fi
    
    log_success "Все зависимости установлены"
}

# =============================================
# 🔥 ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПЕРЕМЕННЫХ
# =============================================
check_env_vars() {
    log_step "Проверка конфигурации..."
    
    local missing=()
    
    [ -z "${DB_PASSWORD:-}" ] && missing+=("DB_PASSWORD")
    [ -z "${JWT_SECRET:-}" ] && missing+=("JWT_SECRET")
    [ -z "${AMI_PASSWORD:-}" ] && missing+=("AMI_PASSWORD")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Отсутствуют обязательные переменные в .env:"
        for var in "${missing[@]}"; do
            echo "  - $var"
        done
        log_error "Отредактируйте .env и запустите снова"
        exit 1
    fi
    
    # Установка значений по умолчанию
    export DB_HOST="${DB_HOST:-localhost}"
    export DB_PORT="${DB_PORT:-5432}"
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    export REDIS_HOST="${REDIS_HOST:-localhost}"
    export REDIS_PORT="${REDIS_PORT:-6379}"
    export REDIS_DB="${REDIS_DB:-0}"
    export REDIS_PASSWORD="${REDIS_PASSWORD:-}"
    export WORKERS="${WORKERS:-4}"
    export HOST="${HOST:-0.0.0.0}"
    export PORT="${PORT:-8000}"
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"
    export ENVIRONMENT="${ENVIRONMENT:-production}"
    
    log_success "Конфигурация проверена"
    log_info "  DB: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    log_info "  Redis: ${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
    log_info "  Workers: $WORKERS"
}

# =============================================
# 🔥 ГЕНЕРАЦИЯ НЕДОСТАЮЩИХ СЕКРЕТОВ
# =============================================
generate_secrets() {
    log_step "Проверка секретов..."
    
    local secrets_updated=false
    
    if [ -z "${ADMIN_PASSWORD:-}" ]; then
        ADMIN_PASSWORD=$(openssl rand -base64 16 2>/dev/null || echo "Admin_$(date +%s)_$(shuf -i 1000-9999 -n 1 2>/dev/null || echo $RANDOM)")
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
    
    if [ "$secrets_updated" = true ]; then
        log_success "Секреты сгенерированы и сохранены в .env"
    else
        log_info "Все секреты уже заданы"
    fi
}

# =============================================
# КОПИРОВАНИЕ ФАЙЛОВ БЭКЕНДА
# =============================================
copy_backend_files() {
    log_step "Копирование файлов бэкенда..."
    
    mkdir -p /opt/autodialer/backend
    
    if [ -d "$PROJECT_ROOT/backend" ]; then
        cp -r "$PROJECT_ROOT/backend/"* /opt/autodialer/backend/
        log_success "Файлы скопированы из $PROJECT_ROOT/backend/"
    else
        log_error "Директория backend не найдена в $PROJECT_ROOT"
        log_error "Убедитесь, что вы клонировали репозиторий полностью"
        exit 1
    fi
    
    # Копирование .env в /opt/autodialer
    cp "$PROJECT_ROOT/.env" /opt/autodialer/.env
    chmod 600 /opt/autodialer/.env
    
    chown -R autodialer:autodialer /opt/autodialer/backend
    chmod -R 755 /opt/autodialer/backend
    
    log_success "Права установлены"
}

# =============================================
# СОЗДАНИЕ ВИРТУАЛЬНОГО ОКРУЖЕНИЯ
# =============================================
setup_virtualenv() {
    log_step "Настройка виртуального окружения..."
    
    cd /opt/autodialer/backend
    
    if [ -d "venv" ] && [ "${FORCE_REINSTALL:-false}" = "true" ]; then
        log_info "Удаление старого виртуального окружения..."
        rm -rf venv
    fi
    
    if [ ! -d "venv" ]; then
        log_info "Создание виртуального окружения..."
        python3 -m venv venv
    else
        log_info "Виртуальное окружение уже существует"
    fi
    
    source venv/bin/activate
    
    # 🔥 Обновление pip с повторными попытками
    log_info "Обновление pip..."
    for i in 1 2 3; do
        if pip install --upgrade pip setuptools wheel -q 2>/dev/null; then
            break
        fi
        log_warn "Попытка $i обновления pip не удалась"
        sleep 2
    done
    
    log_success "Виртуальное окружение готово"
    log_info "Python: $(python3 --version)"
    log_info "pip: $(pip --version)"
}

# =============================================
# 🔥 УСТАНОВКА PYTHON ЗАВИСИМОСТЕЙ (С ИСПРАВЛЕНИЯМИ)
# =============================================
install_requirements() {
    log_step "Установка Python зависимостей..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    # 🔥 Сначала устанавливаем критически важные пакеты отдельно
    log_info "Установка критических пакетов..."
    
    # Установка bcrypt отдельно (часто вызывает проблемы)
    pip install --no-cache-dir bcrypt==4.1.2 2>/dev/null || {
        log_warn "Не удалось установить bcrypt 4.1.2, пробую 4.0.1..."
        pip install --no-cache-dir bcrypt==4.0.1 2>/dev/null || {
            log_warn "Не удалось установить bcrypt, продолжаем..."
        }
    }
    
    # Установка passlib с bcrypt
    pip install --no-cache-dir "passlib[bcrypt]==1.7.4" 2>/dev/null || {
        log_warn "Не удалось установить passlib с bcrypt, пробую без..."
        pip install --no-cache-dir passlib==1.7.4 2>/dev/null
    }
    
    # 🔥 Определение файла requirements
    local req_file=""
    if [ -f "requirements/prod.txt" ]; then
        req_file="requirements/prod.txt"
        log_info "Используется $req_file"
    elif [ -f "requirements.txt" ]; then
        req_file="requirements.txt"
        log_info "Используется $req_file"
    else
        log_error "Файл requirements не найден"
        exit 1
    fi
    
    # 🔥 Установка с повторными попытками
    log_info "Установка основных зависимостей..."
    for i in 1 2 3; do
        if pip install --no-cache-dir -r "$req_file" 2>/tmp/pip-error.log; then
            log_success "Зависимости установлены"
            break
        fi
        
        if [ $i -eq 3 ]; then
            log_error "Не удалось установить зависимости после 3 попыток"
            echo ""
            echo "Последние ошибки:"
            tail -20 /tmp/pip-error.log
            exit 1
        fi
        
        log_warn "Попытка $i не удалась, повтор через 5 секунд..."
        sleep 5
    done
    
    # 🔥 Установка TTS если не отключено
    if [ "${SKIP_TTS:-false}" != "true" ] && [ -f "requirements/tts.txt" ]; then
        log_info "Установка TTS зависимостей..."
        if pip install --no-cache-dir -r requirements/tts.txt 2>/dev/null; then
            log_success "TTS зависимости установлены"
        else
            log_warn "Не удалось установить TTS зависимости"
            log_warn "TTS будет недоступен"
        fi
    fi
    
    # 🔥 Проверка установленных пакетов
    log_info "Проверка установленных пакетов..."
    pip list 2>/dev/null | grep -E "fastapi|sqlalchemy|redis|pydantic|bcrypt|celery" | while read line; do
        log_info "  $line"
    done
}

# =============================================
# 🔥 ПРОВЕРКА КРИТИЧЕСКИХ ИМПОРТОВ (С АВТОИСПРАВЛЕНИЕМ)
# =============================================
verify_imports() {
    log_step "Проверка импорта критических модулей..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    python3 << 'EOF'
import sys
import importlib
import subprocess

# Критические модули в правильном порядке
modules = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("sqlalchemy", "sqlalchemy"),
    ("asyncpg", "asyncpg"),
    ("redis.asyncio", "redis"),
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("jose", "python-jose"),
    ("passlib", "passlib"),
    ("bcrypt", "bcrypt"),
    ("celery", "celery"),
    ("httpx", "httpx"),
    ("aiohttp", "aiohttp"),
    ("panoramisk", "panoramisk"),
]

failed = []
for module, package in modules:
    try:
        importlib.import_module(module)
        print(f"✅ {module}")
    except ImportError as e:
        print(f"❌ {module}: {e}")
        failed.append((module, package))

if failed:
    print(f"\n🔥 ОШИБКА: не удалось импортировать {len(failed)} модулей")
    
    # Попытка исправить bcrypt/passlib
    bcrypt_failed = any(m[0] == "bcrypt" for m in failed)
    passlib_failed = any(m[0] == "passlib" for m in failed)
    
    if bcrypt_failed or passlib_failed:
        print("\n⚠️ Проблема с bcrypt/passlib. Пробую переустановить...")
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "bcrypt", "passlib"], check=False)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "bcrypt==4.0.1"], check=False)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "passlib==1.7.4"], check=False)
        
        # Проверяем снова
        try:
            import bcrypt
            import passlib
            print("✅ bcrypt и passlib исправлены")
        except ImportError:
            print("⚠️ Не удалось исправить bcrypt/passlib")
    
    # Показываем рекомендации
    print("\n📋 Рекомендации по исправлению:")
    for module, package in failed:
        print(f"   pip install --no-cache-dir {package}")
    
    sys.exit(1)

# Проверка версий
print("\n📦 Версии пакетов:")
packages = ["fastapi", "sqlalchemy", "redis", "pydantic", "celery"]
for pkg in packages:
    try:
        mod = importlib.import_module(pkg)
        version = getattr(mod, "__version__", "unknown")
        print(f"   {pkg}: {version}")
    except:
        pass

print("\n✅ Все критические модули импортированы успешно")
EOF
    
    if [ $? -ne 0 ]; then
        log_error "Проверка импортов не пройдена"
        return 1
    fi
    
    log_success "Проверка импортов пройдена"
    return 0
}

# =============================================
# 🔥 ОЖИДАНИЕ БАЗ ДАННЫХ
# =============================================
wait_for_databases() {
    log_step "Ожидание баз данных..."
    
    # Ожидание PostgreSQL
    log_info "Ожидание PostgreSQL (${DB_HOST}:${DB_PORT})..."
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null; then
            log_success "PostgreSQL готов"
            break
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_error "PostgreSQL не ответил за $((max_attempts * 2)) секунд"
        exit 1
    fi
    
    # Ожидание Redis
    log_info "Ожидание Redis (${REDIS_HOST}:${REDIS_PORT})..."
    attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ${REDIS_PASSWORD:+-a "$REDIS_PASSWORD"} ping &>/dev/null; then
            log_success "Redis готов"
            break
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_error "Redis не ответил за $max_attempts секунд"
        exit 1
    fi
}

# =============================================
# ИНИЦИАЛИЗАЦИЯ И ПРИМЕНЕНИЕ МИГРАЦИЙ
# =============================================
setup_database() {
    log_step "Настройка базы данных..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    # Проверка наличия Alembic
    if ! command -v alembic &>/dev/null; then
        log_warn "Alembic не найден, установка..."
        pip install alembic -q
    fi
    
    # Создание директории для миграций
    if [ ! -d "migrations/versions" ]; then
        mkdir -p migrations/versions
        touch migrations/versions/.gitkeep
    fi
    
    # Проверка инициализации Alembic
    if [ ! -f "alembic.ini" ]; then
        log_warn "alembic.ini не найден, инициализация Alembic..."
        alembic init migrations 2>/dev/null || true
    fi
    
    # 🔥 Создание начальной миграции если нет версий
    if [ -z "$(ls -A migrations/versions/*.py 2>/dev/null)" ]; then
        log_info "Создание начальной миграции..."
        alembic revision --autogenerate -m "Initial schema" 2>/dev/null || {
            log_warn "Не удалось создать автоматическую миграцию"
            log_info "Создание пустой миграции..."
            alembic revision -m "Initial schema" 2>/dev/null || true
        }
    fi
    
    # 🔥 Применение миграций с повторными попытками
    log_info "Применение миграций..."
    for i in 1 2 3; do
        if alembic upgrade head 2>/tmp/alembic-error.log; then
            log_success "Миграции применены"
            break
        fi
        
        if [ $i -eq 3 ]; then
            log_error "Не удалось применить миграции после 3 попыток"
            echo ""
            echo "Последние ошибки:"
            tail -20 /tmp/alembic-error.log
            exit 1
        fi
        
        log_warn "Попытка $i не удалась, повтор через 3 секунды..."
        sleep 3
    done
}

# =============================================
# 🔥 СОЗДАНИЕ АДМИНИСТРАТОРА (С ПРОВЕРКОЙ)
# =============================================
create_admin_user() {
    log_step "Создание пользователя admin..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    # Сохранение учётных данных
    cat > /opt/autodialer/.admin_credentials << EOF
============================================
AutoDialer Ultimate - Admin Credentials
============================================
Username: ${ADMIN_USERNAME:-admin}
Password: $ADMIN_PASSWORD
Generated: $(date)
============================================
IMPORTANT: Change this password after first login!
============================================
EOF
    chmod 600 /opt/autodialer/.admin_credentials
    
    # 🔥 Создание пользователя через Python с проверкой
    python3 << EOF
import asyncio
import sys
import os

sys.path.insert(0, '/opt/autodialer/backend')

try:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, text
    
    # Пробуем импортировать настройки
    try:
        from backend.config import settings
    except ImportError:
        # Fallback: читаем из переменных окружения
        import os
        class Settings:
            DATABASE_URL = f"postgresql+asyncpg://{os.environ.get('DB_USER', 'autodialer')}:{os.environ.get('DB_PASSWORD', '')}@{os.environ.get('DB_HOST', 'localhost')}:{os.environ.get('DB_PORT', '5432')}/{os.environ.get('DB_NAME', 'autodialer')}"
        settings = Settings()
    
    from backend.models import User
    from backend.auth import get_password_hash
    
    async def create_admin():
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as db:
            # Проверяем существование таблицы users
            try:
                await db.execute(text("SELECT 1 FROM users LIMIT 1"))
            except Exception as e:
                print(f"⚠️ Таблица users не существует: {e}")
                print("Возможно, миграции не применены.")
                return
            
            # Проверяем существует ли admin
            result = await db.execute(select(User).where(User.username == '${ADMIN_USERNAME:-admin}'))
            existing = result.scalar_one_or_none()
            
            if existing:
                print("✅ Пользователь admin уже существует")
                return
            
            # Создаём администратора
            admin = User(
                username='${ADMIN_USERNAME:-admin}',
                email='${ADMIN_EMAIL:-admin@localhost}',
                full_name='Administrator',
                hashed_password=get_password_hash('$ADMIN_PASSWORD'),
                role='admin',
                is_active=True,
                force_password_change=${FORCE_ADMIN_PASSWORD_CHANGE:-true}
            )
            db.add(admin)
            await db.commit()
            print("✅ Пользователь admin создан успешно")
        
        await engine.dispose()
    
    asyncio.run(create_admin())
except Exception as e:
    print(f"⚠️ Предупреждение: не удалось создать пользователя admin: {e}")
    print("Пользователь может быть создан позже через веб-интерфейс")
    import traceback
    traceback.print_exc()
EOF
    
    log_success "Учётные данные администратора сохранены"
}

# =============================================
# 🔥 НАСТРОЙКА SYSTEMD СЕРВИСА (С READINESS CHECKS)
# =============================================
setup_systemd() {
    log_step "Настройка systemd сервиса..."
    
    cat > /etc/systemd/system/autodialer.service << 'EOF'
[Unit]
Description=AutoDialer Ultimate Backend
Documentation=https://github.com/naumenis-code/AutoDialer-Ultimate
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=notify
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/backend/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/opt/autodialer/.env

# 🔥 Readiness checks
ExecStartPre=/bin/bash -c 'echo "Waiting for PostgreSQL..." && until pg_isready -h ${DB_HOST:-localhost} -p ${DB_PORT:-5432} -U ${DB_USER:-autodialer} 2>/dev/null; do sleep 1; done'
ExecStartPre=/bin/bash -c 'echo "Waiting for Redis..." && until redis-cli -h ${REDIS_HOST:-localhost} -p ${REDIS_PORT:-6379} ${REDIS_PASSWORD:+-a $REDIS_PASSWORD} ping 2>/dev/null | grep -q PONG; do sleep 1; done'
ExecStartPre=/bin/bash -c 'test -f /opt/autodialer/backend/main.py || (echo "Backend files missing" && exit 1)'

# 🔥 Startup с правильными параметрами
ExecStart=/opt/autodialer/backend/venv/bin/gunicorn \
    -w ${WORKERS:-4} \
    -k uvicorn.workers.UvicornWorker \
    -b ${HOST:-0.0.0.0}:${PORT:-8000} \
    --access-logfile /opt/autodialer/logs/backend/access.log \
    --error-logfile /opt/autodialer/logs/backend/error.log \
    --log-level ${LOG_LEVEL:-INFO} \
    --capture-output \
    --enable-stdio-inheritance \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --worker-connections 1000 \
    --threads 2 \
    --preload \
    backend.main:app

# 🔥 Restart policy с защитой от бесконечного цикла
Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60
TimeoutStartSec=30
TimeoutStopSec=30

# Security hardening
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/autodialer/logs /opt/autodialer/backend/uploads /opt/autodialer/recordings
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=autodialer

# Environment
Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONDONTWRITEBYTECODE=1"
Environment="PYTHONPATH=/opt/autodialer/backend"

[Install]
WantedBy=multi-user.target
EOF

    # Создание директории для логов
    mkdir -p /opt/autodialer/logs/backend
    chown -R autodialer:autodialer /opt/autodialer/logs
    
    systemctl daemon-reload
    
    log_success "Systemd сервис создан"
}

# =============================================
# НАСТРОЙКА ЛОГ-РОТАЦИИ
# =============================================
setup_logrotate() {
    log_step "Настройка ротации логов..."
    
    cat > /etc/logrotate.d/autodialer-backend << 'EOF'
/opt/autodialer/logs/backend/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 autodialer autodialer
    sharedscripts
    postrotate
        systemctl reload autodialer 2>/dev/null || true
    endscript
}

/var/log/autodialer/*.log {
    weekly
    missingok
    rotate 12
    compress
    delaycompress
    notifempty
    create 644 autodialer autodialer
}
EOF

    log_success "Ротация логов настроена"
}

# =============================================
# СОЗДАНИЕ СКРИПТОВ УПРАВЛЕНИЯ
# =============================================
create_management_scripts() {
    log_step "Создание скриптов управления..."
    
    # Статус
    cat > /usr/local/bin/autodialer-status << 'EOF'
#!/bin/bash
systemctl status autodialer --no-pager
EOF
    chmod +x /usr/local/bin/autodialer-status
    
    # Логи
    cat > /usr/local/bin/autodialer-logs << 'EOF'
#!/bin/bash
journalctl -u autodialer -f "$@"
EOF
    chmod +x /usr/local/bin/autodialer-logs
    
    # Перезапуск
    cat > /usr/local/bin/autodialer-restart << 'EOF'
#!/bin/bash
systemctl restart autodialer
echo "AutoDialer backend restarted"
EOF
    chmod +x /usr/local/bin/autodialer-restart
    
    # Проверка здоровья
    cat > /usr/local/bin/autodialer-health << 'EOF'
#!/bin/bash
curl -s http://localhost:8000/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/api/health
EOF
    chmod +x /usr/local/bin/autodialer-health
    
    log_success "Скрипты управления созданы"
}

# =============================================
# 🔥 ЗАПУСК СЕРВИСА (С ОЖИДАНИЕМ)
# =============================================
start_service() {
    log_step "Запуск сервиса..."
    
    systemctl enable autodialer
    systemctl start autodialer
    
    # Ожидание запуска
    log_info "Ожидание запуска бэкенда..."
    local max_attempts=60
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "ok"; then
            log_success "Бэкенд запущен и отвечает"
            break
        fi
        
        # Проверка на падение
        if ! systemctl is-active --quiet autodialer; then
            log_error "Сервис autodialer упал при запуске"
            log_error "Проверьте логи: journalctl -u autodialer -n 50"
            
            echo ""
            echo "Последние 30 строк лога:"
            echo "------------------------"
            journalctl -u autodialer -n 30 --no-pager 2>/dev/null || true
            exit 1
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    echo ""
    
    if [ $attempt -eq $max_attempts ]; then
        log_warn "Бэкенд не ответил за $((max_attempts * 2)) секунд"
        log_warn "Проверьте логи: journalctl -u autodialer -n 50"
        
        echo ""
        echo "Последние 30 строк лога:"
        echo "------------------------"
        journalctl -u autodialer -n 30 --no-pager 2>/dev/null || true
    fi
}

# =============================================
# 🔥 ПРОВЕРКА УСТАНОВКИ
# =============================================
verify_installation() {
    log_step "Проверка установки..."
    
    local all_ok=true
    
    # Проверка сервиса
    if systemctl is-active --quiet autodialer; then
        log_success "Сервис autodialer работает"
    else
        log_error "Сервис autodialer не запущен"
        all_ok=false
    fi
    
    # Проверка API
    if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "ok"; then
        log_success "API отвечает"
    else
        log_warn "API не отвечает"
        all_ok=false
    fi
    
    # Проверка документации
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${PORT:-8000}/docs 2>/dev/null | grep -q "200"; then
        log_success "Документация доступна"
    else
        log_warn "Документация не доступна"
    fi
    
    # Проверка подключения к БД
    if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null; then
        log_success "PostgreSQL доступен"
    else
        log_warn "PostgreSQL не доступен"
        all_ok=false
    fi
    
    # Проверка Redis
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &>/dev/null; then
        log_success "Redis доступен"
    else
        log_warn "Redis не доступен"
        all_ok=false
    fi
    
    if [ "$all_ok" = false ]; then
        log_warn "Некоторые проверки не пройдены"
        return 1
    fi
    
    log_success "Все проверки пройдены"
    return 0
}

# =============================================
# СОЗДАНИЕ МАРКЕРА УСТАНОВКИ
# =============================================
mark_installed() {
    mkdir -p /opt/autodialer
    
    cat > "$INSTALLED_MARKER" << EOF
Python backend installed at $(date)
Python version: $(python3 --version)
pip version: $(python3 -m pip --version)
Virtual environment: /opt/autodialer/backend/venv
Service: autodialer.service
Port: ${PORT:-8000}
EOF
    
    chown autodialer:autodialer "$INSTALLED_MARKER" 2>/dev/null || true
    
    log_success "Маркер установки создан: $INSTALLED_MARKER"
}

# =============================================
# ВЫВОД СВОДКИ
# =============================================
print_summary() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}${BOLD}✅ Python бэкенд установлен!${NC}"
    echo "=============================================="
    echo ""
    echo "Информация о бэкенде:"
    echo "  • Python:         $(python3 --version 2>/dev/null || echo 'неизвестно')"
    echo "  • FastAPI:        http://${HOST}:${PORT}"
    echo "  • Документация:   http://${HOST}:${PORT}/docs"
    echo "  • Health check:   http://${HOST}:${PORT}/api/health"
    echo "  • Метрики:        http://${HOST}:${METRICS_PORT:-9090}/metrics"
    echo ""
    echo "Учётные данные:"
    echo "  • Администратор:  ${ADMIN_USERNAME:-admin}"
    echo "  • Пароль:         сохранён в /opt/autodialer/.admin_credentials"
    echo ""
    echo "Управление:"
    echo "  • Статус:         autodialer-status"
    echo "  • Логи:           autodialer-logs"
    echo "  • Перезапуск:     autodialer-restart"
    echo "  • Здоровье:       autodialer-health"
    echo ""
    echo "Важные файлы:"
    echo "  • Конфиг:         /opt/autodialer/.env"
    echo "  • Логи:           /opt/autodialer/logs/backend/"
    echo "  • Системные логи: journalctl -u autodialer"
    echo ""
    echo -e "${YELLOW}Следующий шаг: настройка Nginx${NC}"
    echo "=============================================="
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Python Backend Setup${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.1 (FIXED)${NC}"
    echo "=============================================="
    echo ""
    
    # Проверки
    check_root
    check_already_installed
    check_dependencies
    check_env_vars
    generate_secrets
    
    # Установка
    copy_backend_files
    setup_virtualenv
    install_requirements
    verify_imports
    
    # Ожидание баз данных
    wait_for_databases
    
    # Настройка БД
    setup_database
    create_admin_user
    
    # Настройка сервиса
    setup_systemd
    setup_logrotate
    create_management_scripts
    
    # Запуск
    start_service
    
    # Проверка
    verify_installation
    
    # Завершение
    mark_installed
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
