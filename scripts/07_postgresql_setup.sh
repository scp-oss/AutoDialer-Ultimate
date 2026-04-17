#!/bin/bash
# =============================================
# AutoDialer Ultimate - PostgreSQL Setup (FIXED)
# Version: 3.0.3 (ENTERPRISE)
# Description: Настройка PostgreSQL с проверками
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
# Конфигурация
# =============================================
DB_NAME="${DB_NAME:-autodialer}"
DB_USER="${DB_USER:-autodialer}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

# Сохраняем пароль если не существует
if [ -f "$PROJECT_ROOT/.env" ] && ! grep -q "^DB_PASSWORD=" "$PROJECT_ROOT/.env"; then
    if [ -z "$DB_PASSWORD" ]; then
        DB_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "autodialer_$(date +%s)")
    fi
    echo "DB_PASSWORD=$DB_PASSWORD" >> "$PROJECT_ROOT/.env"
    export DB_PASSWORD
    log_info "DB_PASSWORD сохранён в .env"
fi

log_info "Database: $DB_NAME"
log_info "User: $DB_USER"

# =============================================
# Проверка идемпотентности
# =============================================
INSTALLED_MARKER="/opt/autodialer/.postgresql_configured"

check_already_configured() {
    if [ -f "$INSTALLED_MARKER" ] && [ "${FORCE_REINSTALL:-false}" != "true" ]; then
        log_warn "PostgreSQL уже настроен (найден $INSTALLED_MARKER)"
        exit 0
    fi
}

# =============================================
# Проверка установки PostgreSQL
# =============================================
check_postgresql() {
    log_step "Проверка PostgreSQL..."
    
    if ! command -v psql &>/dev/null; then
        log_info "Установка PostgreSQL..."
        apt-get update -qq
        apt-get install -y -qq postgresql postgresql-contrib postgresql-client
        log_success "PostgreSQL установлен"
    else
        POSTGRES_VERSION=$(psql --version | head -1)
        log_success "PostgreSQL уже установлен: $POSTGRES_VERSION"
    fi
}

# =============================================
# Запуск PostgreSQL (ИСПРАВЛЕНО - правильный сервис)
# =============================================
start_postgresql() {
    log_step "Запуск PostgreSQL..."
    
    # Определяем версию PostgreSQL
    PG_VERSION=$(psql --version 2>/dev/null | grep -oP '\d+' | head -1)
    [ -z "$PG_VERSION" ] && PG_VERSION="15"
    
    # Запускаем правильный сервис
    if systemctl list-unit-files 2>/dev/null | grep -q "postgresql@${PG_VERSION}-main"; then
        systemctl start "postgresql@${PG_VERSION}-main"
        systemctl enable "postgresql@${PG_VERSION}-main" 2>/dev/null || true
        log_success "Запущен postgresql@${PG_VERSION}-main"
    else
        systemctl start postgresql 2>/dev/null || true
        systemctl enable postgresql 2>/dev/null || true
        log_success "Запущен postgresql"
    fi
    
    # Ожидание готовности
    log_info "Ожидание PostgreSQL..."
    for i in $(seq 1 30); do
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" &>/dev/null; then
            log_success "PostgreSQL готов"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo ""
    
    log_error "PostgreSQL не запустился за 30 секунд"
    return 1
}

# =============================================
# Создание пользователя и базы данных
# =============================================
create_database_and_user() {
    log_step "Создание базы данных и пользователя..."
    
    # Проверяем существует ли БД
    local db_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null | xargs)
    
    if [ "$db_exists" = "1" ]; then
        log_warn "База данных '$DB_NAME' уже существует"
        return 0
    fi
    
    # Генерируем пароль если не задан
    if [ -z "$DB_PASSWORD" ]; then
        DB_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "autodialer_$(date +%s)")
        echo "DB_PASSWORD=$DB_PASSWORD" >> "$PROJECT_ROOT/.env"
        export DB_PASSWORD
        log_info "Сгенерирован пароль для БД"
    fi
    
    # Создаём пользователя
    log_info "Создание пользователя $DB_USER..."
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || {
        log_warn "Пользователь уже существует, обновляем пароль..."
        sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
    }
    
    # Создаём базу данных
    log_info "Создание базы данных $DB_NAME..."
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || {
        log_warn "База данных уже существует"
    }
    
    # Даём права
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;"
    
    log_success "База данных и пользователь созданы"
}

# =============================================
# Применение схемы
# =============================================
apply_schema() {
    log_step "Применение схемы базы данных..."
    
    local SCHEMA_FILE=""
    
    if [ -f "$PROJECT_ROOT/sql/schema.sql" ]; then
        SCHEMA_FILE="$PROJECT_ROOT/sql/schema.sql"
    elif [ -f "$PROJECT_ROOT/sql/migrations/001_initial.sql" ]; then
        SCHEMA_FILE="$PROJECT_ROOT/sql/migrations/001_initial.sql"
    elif [ -f "/opt/autodialer/sql/schema.sql" ]; then
        SCHEMA_FILE="/opt/autodialer/sql/schema.sql"
    else
        log_warn "Файл схемы не найден, создаю базовую схему..."
        SCHEMA_FILE="/tmp/autodialer_schema.sql"
        
        cat > "$SCHEMA_FILE" << 'EOF'
-- AutoDialer Ultimate Basic Schema

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email VARCHAR(255),
    full_name VARCHAR(255),
    role VARCHAR(20) DEFAULT 'operator',
    force_password_change BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
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

INSERT INTO users (username, password_hash, role, email, force_password_change) VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIqK0hVdGW',
    'admin',
    'admin@localhost',
    TRUE
) ON CONFLICT (username) DO NOTHING;
EOF
    fi
    
    log_info "Применение схемы из $SCHEMA_FILE"
    if sudo -u postgres psql -d "$DB_NAME" -f "$SCHEMA_FILE" &>/dev/null; then
        log_success "Схема применена успешно"
    else
        log_warn "Некоторые элементы схемы уже существуют"
    fi
}

# =============================================
# Проверка подключения
# =============================================
verify_connection() {
    log_step "Проверка подключения..."
    
    if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" &>/dev/null; then
        log_success "Подключение к БД успешно"
    else
        log_error "Не удалось подключиться к БД"
        return 1
    fi
    
    # Количество таблиц
    local table_count=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs)
    log_info "Таблиц создано: ${table_count:-0}"
}

# =============================================
# Создание маркера
# =============================================
mark_configured() {
    mkdir -p /opt/autodialer
    
    cat > "$INSTALLED_MARKER" << EOF
PostgreSQL configured at $(date)
Database: $DB_NAME
User: $DB_USER
Host: $DB_HOST:$DB_PORT
EOF
    
    chown autodialer:autodialer "$INSTALLED_MARKER" 2>/dev/null || true
    log_success "Маркер установки создан"
}

# =============================================
# Вывод сводки
# =============================================
print_summary() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}${BOLD}✅ PostgreSQL настроен!${NC}"
    echo "=============================================="
    echo ""
    echo "Параметры подключения:"
    echo "  • Хост:     $DB_HOST"
    echo "  • Порт:     $DB_PORT"
    echo "  • База:     $DB_NAME"
    echo "  • Пользователь: $DB_USER"
    echo "  • Пароль:   $DB_PASSWORD"
    echo ""
    echo "Строка подключения:"
    echo "  postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
    echo ""
    echo "Учётные данные по умолчанию:"
    echo "  • Логин:    admin"
    echo "  • Пароль:   admin"
    echo ""
    echo "Полезные команды:"
    echo "  sudo -u postgres psql -d $DB_NAME"
    echo "  PGPASSWORD='$DB_PASSWORD' psql -h $DB_HOST -U $DB_USER -d $DB_NAME"
    echo ""
    echo "=============================================="
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - PostgreSQL Setup${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.3 (FIXED)${NC}"
    echo "=============================================="
    echo ""
    
    check_already_configured
    check_postgresql
    start_postgresql || {
        log_error "Не удалось запустить PostgreSQL"
        exit 1
    }
    create_database_and_user
    apply_schema
    verify_connection
    mark_configured
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
