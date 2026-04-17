#!/bin/bash
# =============================================
# AutoDialer Ultimate - Python Backend Setup (FIXED)
# Version: 3.0.2 (ENTERPRISE)
# Description: Установка и настройка Python бэкенда с проверками
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
    
    command -v python3 &>/dev/null || missing+=("python3")
    python3 -m pip --version &>/dev/null || missing+=("python3-pip")
    python3 -m venv --help &>/dev/null || missing+=("python3-venv")
    command -v pg_isready &>/dev/null || missing+=("postgresql-client")
    command -v redis-cli &>/dev/null || missing+=("redis-tools")
    dpkg -l build-essential &>/dev/null || missing+=("build-essential")
    dpkg -l python3-dev &>/dev/null || missing+=("python3-dev")
    dpkg -l libffi-dev &>/dev/null || missing+=("libffi-dev")
    dpkg -l libssl-dev &>/dev/null || missing+=("libssl-dev")
    
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
load_env() {
    if [ -f "$PROJECT_ROOT/.env" ]; then
        # Загружаем .env БЕЗ парсинга вручную
        set -a
        source "$PROJECT_ROOT/.env"
        set +a
        log_success "Конфигурация загружена из .env"
    fi
}

check_env_vars() {
    log_step "Проверка конфигурации..."
    
    # Сначала загружаем .env правильно
    load_env
    
    local missing=()
    
    [ -z "${DB_PASSWORD:-}" ] && missing+=("DB_PASSWORD")
    [ -z "${JWT_SECRET:-}" ] && missing+=("JWT_SECRET")
    [ -z "${AMI_PASSWORD:-}" ] && missing+=("AMI_PASSWORD")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Отсутствуют обязательные переменные: ${missing[*]}"
        exit 1
    fi
    
    # Установка значений по умолчанию
    export DB_HOST="${DB_HOST:-localhost}"
    export DB_PORT="${DB_PORT:-5432}"
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    export REDIS_HOST="${REDIS_HOST:-localhost}"
    export REDIS_PORT="${REDIS_PORT:-6379}"
    export WORKERS="${WORKERS:-4}"
    export HOST="${HOST:-0.0.0.0}"
    export PORT="${PORT:-8000}"
    
    log_success "Конфигурация проверена"
    log_info "  DB: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    log_info "  Redis: ${REDIS_HOST}:${REDIS_PORT}"
    log_info "  Workers: $WORKERS"
}

# =============================================
# 🔥 ГЕНЕРАЦИЯ НЕДОСТАЮЩИХ СЕКРЕТОВ
# =============================================
generate_secrets() {
    log_step "Проверка секретов..."
    
    local secrets_updated=false
    
    if [ -z "${ADMIN_PASSWORD:-}" ]; then
        ADMIN_PASSWORD=$(openssl rand -base64 16 2>/dev/null || echo "Admin_$(date +%s)_${RANDOM}")
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
    
    [ "$secrets_updated" = true ] && log_success "Секреты сгенерированы"
}

# =============================================
# КОПИРОВАНИЕ ФАЙЛОВ БЭКЕНДА
# =============================================
copy_backend_files() {
    log_step "Копирование файлов бэкенда..."
    
    mkdir -p /opt/autodialer/backend
    
    if [ -d "$PROJECT_ROOT/backend" ]; then
        cp -r "$PROJECT_ROOT/backend/"* /opt/autodialer/backend/
        log_success "Файлы скопированы"
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
# СОЗДАНИЕ ВИРТУАЛЬНОГО ОКРУЖЕНИЯ
# =============================================
setup_virtualenv() {
    log_step "Настройка виртуального окружения..."
    
    cd /opt/autodialer/backend
    
    [ -d "venv" ] && [ "${FORCE_REINSTALL:-false}" = "true" ] && rm -rf venv
    [ ! -d "venv" ] && python3 -m venv venv
    
    source venv/bin/activate
    
    for i in 1 2 3; do
        pip install --upgrade pip setuptools wheel -q 2>/dev/null && break
        sleep 2
    done
    
    log_success "Виртуальное окружение готово"
    log_info "Python: $(python3 --version)"
    log_info "pip: $(pip --version)"
}

# =============================================
# 🔥 PIP INSTALL С ПОВТОРНЫМИ ПОПЫТКАМИ
# =============================================
pip_install_with_retry() {
    local package="$1"
    local max_attempts=3
    
    for i in $(seq 1 $max_attempts); do
        if pip install --no-cache-dir $package 2>/tmp/pip-error.log; then
            return 0
        fi
        
        log_warn "pip install $package не удался (попытка $i/$max_attempts)"
        [ $i -lt $max_attempts ] && sleep 3
    done
    
    log_error "Не удалось установить: $package"
    tail -10 /tmp/pip-error.log
    return 1
}

# =============================================
# 🔥 УСТАНОВКА PYTHON ЗАВИСИМОСТЕЙ (С ИСПРАВЛЕНИЯМИ)
# =============================================
install_requirements() {
    log_step "Установка Python зависимостей..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    # =============================================
    # 🔥 КРИТИЧЕСКИ ВАЖНО: ПРАВИЛЬНЫЕ ВЕРСИИ BCRYPT И PASSLIB
    # =============================================
    log_info "Предустановка bcrypt и passlib (критически важные версии)..."
    
    # Удаляем старые версии если есть
    pip uninstall -y bcrypt passlib 2>/dev/null || true
    
    # Устанавливаем bcrypt - частые проблемы с 4.1.2, поэтому fallback на 4.0.1
    log_info "Установка bcrypt..."
    if ! pip install --no-cache-dir bcrypt==4.1.2 2>/tmp/bcrypt-error.log; then
        log_warn "bcrypt 4.1.2 не установился, пробую 4.0.1..."
        if ! pip install --no-cache-dir bcrypt==4.0.1 2>/tmp/bcrypt-error.log; then
            log_error "Не удалось установить bcrypt"
            cat /tmp/bcrypt-error.log
            exit 1
        fi
    fi
    log_success "bcrypt установлен"
    
    # Устанавливаем passlib с поддержкой bcrypt
    log_info "Установка passlib[bcrypt]..."
    if ! pip install --no-cache-dir "passlib[bcrypt]==1.7.4" 2>/tmp/passlib-error.log; then
        log_warn "passlib[bcrypt] 1.7.4 не установился, пробую passlib без bcrypt..."
        if ! pip install --no-cache-dir passlib==1.7.4 2>/tmp/passlib-error.log; then
            log_error "Не удалось установить passlib"
            cat /tmp/passlib-error.log
            exit 1
        fi
    fi
    log_success "passlib установлен"
    
    # =============================================
    # 🔥 ОСНОВНЫЕ ЗАВИСИМОСТИ
    # =============================================
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
    
    log_info "Установка основных зависимостей из $req_file..."
    if ! pip_install_with_retry "-r $req_file"; then
        log_warn "Не удалось установить с основного зеркала, пробую альтернативное..."
        pip config set global.index-url https://pypi.org/simple
        pip_install_with_retry "-r $req_file" || exit 1
    fi
    
    # =============================================
    # 🔥 TTS ЗАВИСИМОСТИ (PIPER - ТРЕБУЕТ --PREFER-BINARY)
    # =============================================
    if [ "${SKIP_TTS:-false}" != "true" ] && [ -f "requirements/tts.txt" ]; then
        log_info "Установка TTS зависимостей..."
        
        # piper-tts часто не имеет wheel, используем --prefer-binary
        log_info "Установка piper-tts (--prefer-binary)..."
        if ! pip install --prefer-binary piper-tts 2>/tmp/piper-error.log; then
            log_warn "piper-tts не установился (возможно, несовместимая архитектура)"
            log_warn "TTS будет недоступен"
        else
            log_success "piper-tts установлен"
        fi
        
        # Остальные TTS зависимости
        pip_install_with_retry "-r requirements/tts.txt" 2>/dev/null || log_warn "Некоторые TTS зависимости не установлены"
    fi
    
    log_success "Зависимости установлены"
    
    # Показываем установленные версии
    log_info "Проверка установленных пакетов:"
    pip list 2>/dev/null | grep -E "fastapi|sqlalchemy|redis|pydantic|bcrypt|passlib|celery|piper" | while read line; do
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

print("=" * 50)
print("ПРОВЕРКА ИМПОРТОВ КРИТИЧЕСКИХ МОДУЛЕЙ")
print("=" * 50)

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
    
    # 🔥 АВТОИСПРАВЛЕНИЕ BCRYPT/PASSLIB
    bcrypt_failed = any(m[0] == "bcrypt" for m in failed)
    passlib_failed = any(m[0] == "passlib" for m in failed)
    
    if bcrypt_failed or passlib_failed:
        print("\n⚠️ Проблема с bcrypt/passlib. Выполняю автоисправление...")
        print("   Переустановка bcrypt и passlib...")
        
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "bcrypt", "passlib"], 
                       check=False, capture_output=True)
        
        # Пробуем bcrypt 4.0.1 (более стабильная)
        result1 = subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "bcrypt==4.0.1"], 
                                 check=False, capture_output=True)
        if result1.returncode == 0:
            print("   ✅ bcrypt 4.0.1 установлен")
        else:
            print("   ❌ Не удалось установить bcrypt")
        
        # Passlib без bcrypt (fallback)
        result2 = subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "passlib==1.7.4"], 
                                 check=False, capture_output=True)
        if result2.returncode == 0:
            print("   ✅ passlib 1.7.4 установлен")
        else:
            print("   ❌ Не удалось установить passlib")
        
        # Проверяем снова
        print("\n   Повторная проверка:")
        try:
            import bcrypt
            print("   ✅ bcrypt импортирован")
        except ImportError:
            print("   ❌ bcrypt всё ещё не импортируется")
        
        try:
            import passlib
            print("   ✅ passlib импортирован")
        except ImportError:
            print("   ❌ passlib всё ещё не импортируется")
    
    # Показываем рекомендации для остальных
    print("\n📋 Рекомендации по исправлению:")
    for module, package in failed:
        print(f"   pip install --no-cache-dir {package}")
    
    sys.exit(1)

# Проверка версий
print("\n" + "=" * 50)
print("ВЕРСИИ УСТАНОВЛЕННЫХ ПАКЕТОВ")
print("=" * 50)
packages = ["fastapi", "sqlalchemy", "redis", "pydantic", "celery", "bcrypt", "passlib"]
for pkg in packages:
    try:
        mod = importlib.import_module(pkg)
        version = getattr(mod, "__version__", "unknown")
        print(f"   {pkg}: {version}")
    except:
        print(f"   {pkg}: не установлен")

print("\n" + "=" * 50)
print("✅ ВСЕ КРИТИЧЕСКИЕ МОДУЛИ ИМПОРТИРОВАНЫ УСПЕШНО")
print("=" * 50)
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
    
    local max_attempts=30
    local attempt=0
    
    log_info "Ожидание PostgreSQL..."
    while [ $attempt -lt $max_attempts ]; do
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null; then
            break
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    
    if [ $attempt -ge $max_attempts ]; then
        log_error "PostgreSQL не ответил за $((max_attempts * 2)) секунд"
        exit 1
    fi
    log_success "PostgreSQL готов"
    
    attempt=0
    log_info "Ожидание Redis..."
    while [ $attempt -lt $max_attempts ]; do
        if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ${REDIS_PASSWORD:+-a "$REDIS_PASSWORD"} ping &>/dev/null; then
            break
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    
    if [ $attempt -ge $max_attempts ]; then
        log_error "Redis не ответил за $max_attempts секунд"
        exit 1
    fi
    log_success "Redis готов"
}

# =============================================
# ИНИЦИАЛИЗАЦИЯ И ПРИМЕНЕНИЕ МИГРАЦИЙ
# =============================================
setup_database() {
    log_step "Настройка базы данных..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
    command -v alembic &>/dev/null || pip install alembic -q
    
    [ ! -d "migrations/versions" ] && mkdir -p migrations/versions
    [ ! -f "alembic.ini" ] && alembic init migrations 2>/dev/null || true
    
    if [ -z "$(ls -A migrations/versions/*.py 2>/dev/null)" ]; then
        log_info "Создание начальной миграции..."
        alembic revision --autogenerate -m "Initial schema" 2>/dev/null || \
            alembic revision -m "Initial schema" 2>/dev/null || true
    fi
    
    log_info "Применение миграций..."
    for i in 1 2 3; do
        if alembic upgrade head 2>/tmp/alembic-error.log; then
            break
        fi
        if [ $i -eq 3 ]; then
            log_error "Не удалось применить миграции"
            tail -20 /tmp/alembic-error.log
            exit 1
        fi
        log_warn "Попытка $i не удалась, повтор..."
        sleep 3
    done
    
    log_success "База данных настроена"
}

# =============================================
# 🔥 СОЗДАНИЕ АДМИНИСТРАТОРА
# =============================================
create_admin_user() {
    log_step "Создание пользователя admin..."
    
    cd /opt/autodialer/backend
    source venv/bin/activate
    
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
    
    python3 << EOF
import asyncio
import sys
sys.path.insert(0, '/opt/autodialer/backend')

try:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, text
    
    from backend.config import settings
    from backend.models import User
    from backend.auth import get_password_hash
    
    async def create_admin():
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as db:
            try:
                await db.execute(text("SELECT 1 FROM users LIMIT 1"))
            except Exception as e:
                print(f"⚠️ Таблица users не существует: {e}")
                return
            
            result = await db.execute(select(User).where(User.username == '${ADMIN_USERNAME:-admin}'))
            if result.scalar_one_or_none():
                print("✅ Пользователь admin уже существует")
                return
            
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
            print("✅ Пользователь admin создан")
        
        await engine.dispose()
    
    asyncio.run(create_admin())
except Exception as e:
    print(f"⚠️ Не удалось создать admin: {e}")
    import traceback
    traceback.print_exc()
EOF
    
    log_success "Учётные данные сохранены"
}

# =============================================
# 🔥 НАСТРОЙКА SYSTEMD СЕРВИСА
# =============================================
setup_systemd() {
    log_step "Настройка systemd сервиса..."
    
    cat > /etc/systemd/system/autodialer.service << EOF
[Unit]
Description=AutoDialer Ultimate Backend
After=network.target network-online.target postgresql.service redis-server.service
Wants=network-online.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=notify
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/autodialer/.env

ExecStartPre=/bin/bash -c 'until pg_isready -h \${DB_HOST:-localhost} -p \${DB_PORT:-5432} -U \${DB_USER:-autodialer} 2>/dev/null; do sleep 1; done'
ExecStartPre=/bin/bash -c 'until redis-cli -h \${REDIS_HOST:-localhost} -p \${REDIS_PORT:-6379} \${REDIS_PASSWORD:+-a \$REDIS_PASSWORD} ping 2>/dev/null | grep -q PONG; do sleep 1; done'

ExecStart=/opt/autodialer/backend/venv/bin/gunicorn \\
    -w \${WORKERS:-4} \\
    -k uvicorn.workers.UvicornWorker \\
    -b \${HOST:-0.0.0.0}:\${PORT:-8000} \\
    --access-logfile /opt/autodialer/logs/backend/access.log \\
    --error-logfile /opt/autodialer/logs/backend/error.log \\
    --log-level \${LOG_LEVEL:-INFO} \\
    --timeout 120 \\
    --graceful-timeout 30 \\
    --max-requests 1000 \\
    --max-requests-jitter 100 \\
    --worker-connections 1000 \\
    --threads 2 \\
    --preload \\
    backend.main:app

Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60
TimeoutStartSec=30
TimeoutStopSec=30

PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/autodialer/logs /opt/autodialer/backend/uploads /opt/autodialer/recordings

StandardOutput=journal
StandardError=journal
SyslogIdentifier=autodialer

Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONDONTWRITEBYTECODE=1"
Environment="PYTHONPATH=/opt/autodialer/backend"

[Install]
WantedBy=multi-user.target
EOF

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
EOF

    log_success "Ротация логов настроена"
}

# =============================================
# СОЗДАНИЕ СКРИПТОВ УПРАВЛЕНИЯ
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
echo "AutoDialer backend restarted"
EOF
    chmod +x /usr/local/bin/autodialer-restart
    
    cat > /usr/local/bin/autodialer-health << 'EOF'
#!/bin/bash
curl -s http://localhost:8000/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/api/health
EOF
    chmod +x /usr/local/bin/autodialer-health
    
    log_success "Скрипты управления созданы"
}

# =============================================
# 🔥 ЗАПУСК СЕРВИСА
# =============================================
start_service() {
    log_step "Запуск сервиса..."
    
    systemctl enable autodialer
    systemctl start autodialer
    
    log_info "Ожидание запуска бэкенда..."
    local max_attempts=60
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "ok"; then
            log_success "Бэкенд запущен и отвечает"
            break
        fi
        
        if ! systemctl is-active --quiet autodialer; then
            log_error "Сервис autodialer упал при запуске"
            journalctl -u autodialer -n 30 --no-pager 2>/dev/null || true
            exit 1
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    echo ""
    
    if [ $attempt -ge $max_attempts ]; then
        log_warn "Бэкенд не ответил за $((max_attempts * 2)) секунд"
        journalctl -u autodialer -n 30 --no-pager 2>/dev/null || true
    fi
}

# =============================================
# 🔥 ПРОВЕРКА УСТАНОВКИ
# =============================================
verify_installation() {
    log_step "Проверка установки..."
    
    local all_ok=true
    
    systemctl is-active --quiet autodialer && log_success "Сервис работает" || { log_error "Сервис не запущен"; all_ok=false; }
    curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "ok" && log_success "API отвечает" || { log_warn "API не отвечает"; all_ok=false; }
    pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null && log_success "PostgreSQL доступен" || log_warn "PostgreSQL не доступен"
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &>/dev/null && log_success "Redis доступен" || log_warn "Redis не доступен"
    
    [ "$all_ok" = true ] && log_success "Все проверки пройдены"
}

# =============================================
# СОЗДАНИЕ МАРКЕРА УСТАНОВКИ
# =============================================
mark_installed() {
    mkdir -p /opt/autodialer
    
    cat > "$INSTALLED_MARKER" << EOF
Python backend installed at $(date)
Python: $(python3 --version)
pip: $(python3 -m pip --version)
Service: autodialer.service
Port: ${PORT:-8000}
bcrypt: $(pip show bcrypt 2>/dev/null | grep Version | cut -d' ' -f2 || echo "unknown")
passlib: $(pip show passlib 2>/dev/null | grep Version | cut -d' ' -f2 || echo "unknown")
EOF
    
    chown autodialer:autodialer "$INSTALLED_MARKER" 2>/dev/null || true
    log_success "Маркер установки создан"
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
    echo "  • bcrypt:         $(pip show bcrypt 2>/dev/null | grep Version | cut -d' ' -f2 || echo 'не установлен')"
    echo "  • passlib:        $(pip show passlib 2>/dev/null | grep Version | cut -d' ' -f2 || echo 'не установлен')"
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
    echo -e "${BOLD}${BLUE}Version: 3.0.2 (ENTERPRISE)${NC}"
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
    
    wait_for_databases
    setup_database
    create_admin_user
    
    setup_systemd
    setup_logrotate
    create_management_scripts
    
    start_service
    verify_installation
    mark_installed
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
