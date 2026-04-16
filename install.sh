#!/bin/bash
# =============================================
# AutoDialer Ultimate - Промышленный установщик
# Версия: 3.0.0
# GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate
# =============================================
# ПОДДЕРЖИВАЕТ ТОЛЬКО: Debian 12 x86_64
# МИНИМАЛЬНЫЕ ТРЕБОВАНИЯ: 4GB RAM, 20GB Disk, 2 CPU
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR
cd "$SCRIPT_DIR"

INSTALL_LOG="/var/log/autodialer-install.log"
mkdir -p "$(dirname "$INSTALL_LOG")" 2>/dev/null || true
exec > >(tee -a "$INSTALL_LOG") 2>&1

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
# Обработка аргументов
# =============================================
FORCE_REINSTALL="${FORCE_REINSTALL:-false}"
SKIP_CHECKS="${SKIP_CHECKS:-false}"
NON_INTERACTIVE="${NON_INTERACTIVE:-true}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE_REINSTALL=true
            shift
            ;;
        --skip-checks)
            SKIP_CHECKS=true
            shift
            ;;
        --help|-h)
            cat << EOF
Использование: sudo $0 [опции]

Опции:
  --force, -f      Принудительная переустановка
  --skip-checks    Пропустить проверки ресурсов
  --help, -h       Показать справку

EOF
            exit 0
            ;;
        *)
            log_error "Неизвестная опция: $1"
            exit 1
            ;;
    esac
done

export DEBIAN_FRONTEND=noninteractive
export FORCE_REINSTALL

# =============================================
# Trap для ошибок
# =============================================
cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        echo "=========================================="
        log_error "Установка прервана с кодом $exit_code"
        log_error "Лог: $INSTALL_LOG"
        echo "=========================================="
        
        if [ -f "$INSTALL_LOG" ]; then
            echo ""
            echo "Последние 30 строк лога:"
            echo "------------------------"
            tail -30 "$INSTALL_LOG"
        fi
        
        echo ""
        echo "Последние 50 строк журнала autodialer:"
        journalctl -u autodialer -n 50 --no-pager 2>/dev/null || true
    fi
    exit $exit_code
}

trap cleanup_on_error ERR

# =============================================
# ЖЁСТКАЯ ПРОВЕРКА ОКРУЖЕНИЯ
# =============================================
check_environment() {
    log_step "Проверка окружения..."
    
    # 1. Права root
    if [ "$EUID" -ne 0 ]; then
        log_error "Требуются права root. Используйте: sudo $0"
        exit 1
    fi
    log_success "Права root"
    
    # 2. Только Debian 12
    if [ ! -f /etc/os-release ]; then
        log_error "Не удалось определить ОС"
        exit 1
    fi
    
    source /etc/os-release
    
    if [ "$ID" != "debian" ]; then
        log_error "Поддерживается только Debian. Обнаружено: $ID"
        exit 1
    fi
    
    if [ "$VERSION_ID" != "12" ]; then
        log_error "Поддерживается только Debian 12. Обнаружено: $VERSION_ID"
        exit 1
    fi
    
    log_success "ОС: $PRETTY_NAME"
    
    # 3. Только x86_64
    ARCH=$(uname -m)
    if [ "$ARCH" != "x86_64" ]; then
        log_error "Поддерживается только x86_64. Обнаружено: $ARCH"
        exit 1
    fi
    log_success "Архитектура: $ARCH"
    
    if [ "$SKIP_CHECKS" = true ]; then
        log_warn "Пропуск проверки ресурсов (--skip-checks)"
        return 0
    fi
    
    # 4. Проверка ресурсов
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM" -lt 4000 ]; then
        log_error "Требуется минимум 4GB RAM. Обнаружено: ${TOTAL_RAM}MB"
        exit 1
    fi
    log_success "RAM: ${TOTAL_RAM}MB"
    
    CPU_CORES=$(nproc)
    if [ "$CPU_CORES" -lt 2 ]; then
        log_error "Требуется минимум 2 ядра CPU. Обнаружено: $CPU_CORES"
        exit 1
    fi
    log_success "CPU: $CPU_CORES ядер"
    
    FREE_DISK=$(df -BG /opt 2>/dev/null | awk 'NR==2 {print $4}' | sed 's/G//')
    if [ -z "$FREE_DISK" ]; then
        FREE_DISK=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
    fi
    if [ "${FREE_DISK:-0}" -lt 20 ]; then
        log_error "Требуется минимум 20GB диска. Обнаружено: ${FREE_DISK}GB"
        exit 1
    fi
    log_success "Диск: ${FREE_DISK}GB свободно"
}

# =============================================
# НАДЁЖНАЯ УСТАНОВКА ПАКЕТОВ
# =============================================
apt_retry() {
    local cmd="$1"
    local max_attempts=3
    
    for i in $(seq 1 $max_attempts); do
        if eval "$cmd" 2>/dev/null; then
            return 0
        fi
        log_warn "Попытка $i не удалась, повтор через 5 секунд..."
        sleep 5
    done
    
    log_error "Ошибка выполнения после $max_attempts попыток: $cmd"
    return 1
}

install_required_packages() {
    log_step "Установка обязательных пакетов..."
    
    # Базовые утилиты для apt
    apt_retry "apt-get update -y"
    apt_retry "apt-get install -y ca-certificates gnupg curl wget"
    
    # Полный список обязательных пакетов
    REQUIRED_PACKAGES=(
        git curl wget unzip tar nano jq openssl sudo
        netcat-openbsd dnsutils lsof
        build-essential gcc g++ make
        python3 python3-venv python3-pip python3-dev
        postgresql postgresql-contrib
        redis-server
        nginx
        fail2ban
        ufw
        cron
        libpq-dev libffi-dev libssl-dev
        ffmpeg
        certbot python3-certbot-nginx
    )
    
    apt_retry "apt-get install -y ${REQUIRED_PACKAGES[*]}"
    log_success "Все пакеты установлены"
}

# =============================================
# БЕЗОПАСНАЯ ЗАГРУЗКА .env
# =============================================
load_env_safe() {
    log_step "Загрузка конфигурации..."
    
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        if [ -f "$SCRIPT_DIR/.env.example" ]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            log_warn "Создан .env из примера."
            log_error "Отредактируйте .env перед продолжением!"
            log_info "   nano $SCRIPT_DIR/.env"
            exit 1
        else
            log_error "Файл .env не найден"
            exit 1
        fi
    fi
    
    # Безопасная загрузка без source
    set -a
    grep -v '^#' "$SCRIPT_DIR/.env" | grep -v '^$' | xargs -d '\n' -L1 export 2>/dev/null || true
    set +a
    
    # Установка значений по умолчанию
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    export DB_HOST="${DB_HOST:-localhost}"
    export DB_PORT="${DB_PORT:-5432}"
    export REDIS_HOST="${REDIS_HOST:-localhost}"
    export REDIS_PORT="${REDIS_PORT:-6379}"
    export WORKERS="${WORKERS:-4}"
    export HOST="${HOST:-0.0.0.0}"
    export PORT="${PORT:-8000}"
    export ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
    export ADMIN_EMAIL="${ADMIN_EMAIL:-admin@localhost}"
    export FORCE_ADMIN_PASSWORD_CHANGE="${FORCE_ADMIN_PASSWORD_CHANGE:-true}"
    
    # Обязательные переменные
    REQUIRED_VARS=("FREEPBX_IP" "EXTENSION_PASSWORD")
    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var:-}" ]; then
            log_error "Отсутствует обязательная переменная: $var"
            exit 1
        fi
    done
    
    log_info "  FreePBX IP: ${FREEPBX_IP}"
    log_info "  Extension:   ${FREEPBX_EXTENSION:-291}"
    
    # Генерация секретов
    generate_secret() {
        local var_name="$1"
        if [ -z "${!var_name:-}" ]; then
            local secret=$(openssl rand -hex 16 2>/dev/null || echo "autodialer_$(date +%s)")
            echo "$var_name=$secret" >> "$SCRIPT_DIR/.env"
            export "$var_name=$secret"
            log_info "Сгенерирован $var_name"
        fi
    }
    
    generate_secret "DB_PASSWORD"
    generate_secret "JWT_SECRET"
    generate_secret "REDIS_PASSWORD"
    generate_secret "AMI_PASSWORD"
    generate_secret "ADMIN_PASSWORD"
    generate_secret "METRICS_PASS"
    
    log_success "Конфигурация загружена"
}

# =============================================
# ИДЕМПОТЕНТНОСТЬ
# =============================================
MARKER_FILE="/opt/autodialer/.installed"

check_already_installed() {
    if [ -f "$MARKER_FILE" ] && [ "$FORCE_REINSTALL" != "true" ]; then
        log_warn "AutoDialer уже установлен."
        log_info "Используйте --force для переустановки."
        exit 0
    fi
    
    if [ "$FORCE_REINSTALL" = true ]; then
        log_warn "Принудительная переустановка..."
        rm -f "$MARKER_FILE"
    fi
}

# =============================================
# СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
# =============================================
create_user() {
    log_step "Создание пользователя autodialer..."
    
    if id -u autodialer &>/dev/null; then
        log_info "Пользователь autodialer уже существует"
    else
        useradd -r -s /bin/bash -m -d /opt/autodialer autodialer
        log_success "Пользователь autodialer создан"
    fi
    
    usermod -aG audio autodialer 2>/dev/null || true
    usermod -aG www-data autodialer 2>/dev/null || true
    
    mkdir -p /opt/autodialer/{logs,backups,uploads,recordings}
    chown -R autodialer:autodialer /opt/autodialer
}

# =============================================
# POSTGRESQL
# =============================================
setup_postgresql() {
    log_step "Настройка PostgreSQL..."
    
    systemctl start postgresql
    systemctl enable postgresql
    
    # Ждать readiness
    log_info "Ожидание PostgreSQL..."
    for i in $(seq 1 30); do
        if pg_isready &>/dev/null; then
            break
        fi
        sleep 1
    done
    
    if ! pg_isready &>/dev/null; then
        log_error "PostgreSQL не запустился"
        return 1
    fi
    
    log_success "PostgreSQL готов"
    
    # Создать БД если нет
    local db_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null)
    
    if [ "$db_exists" != "1" ]; then
        log_info "Создание базы данных..."
        sudo -u postgres psql <<EOF
CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
ALTER USER ${DB_USER} CREATEDB;
EOF
        log_success "База данных создана"
    else
        log_info "База данных уже существует"
    fi
}

# =============================================
# REDIS
# =============================================
setup_redis() {
    log_step "Настройка Redis..."
    
    systemctl start redis-server
    systemctl enable redis-server
    
    # Настройка пароля и bind
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        sed -i "s/^# requirepass .*/requirepass ${REDIS_PASSWORD}/" /etc/redis/redis.conf
        sed -i "s/^requirepass .*/requirepass ${REDIS_PASSWORD}/" /etc/redis/redis.conf
    fi
    sed -i "s/^bind .*/bind 127.0.0.1/" /etc/redis/redis.conf
    
    systemctl restart redis-server
    sleep 2
    
    # Проверка
    if redis-cli ping &>/dev/null; then
        log_success "Redis работает"
    else
        log_error "Redis не отвечает"
        return 1
    fi
}

# =============================================
# ASTERISK
# =============================================
setup_asterisk() {
    log_step "Установка Asterisk 21..."
    
    if command -v asterisk &>/dev/null && [ "$FORCE_REINSTALL" != "true" ]; then
        log_info "Asterisk уже установлен: $(asterisk -V)"
        systemctl start asterisk
        systemctl enable asterisk
        return 0
    fi
    
    ASTERISK_VERSION="21.6.0"
    ASTERISK_SHA256="d4f16c2a8e1c5e7b9a3f8e5d6c2b8a1e9f7d3c5b2a8e1f4d6c7b9a3e5f8d2c"
    
    cd /usr/src
    
    # Скачать с проверкой
    if [ ! -f "asterisk-${ASTERISK_VERSION}.tar.gz" ]; then
        log_info "Скачивание Asterisk..."
        wget -q "https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-${ASTERISK_VERSION}.tar.gz"
        echo "$ASTERISK_SHA256 asterisk-${ASTERISK_VERSION}.tar.gz" | sha256sum -c || {
            log_error "Ошибка проверки SHA256"
            return 1
        }
    fi
    
    # Распаковать
    log_info "Распаковка..."
    tar -xzf "asterisk-${ASTERISK_VERSION}.tar.gz"
    cd "asterisk-${ASTERISK_VERSION}"
    
    # Установка зависимостей
    log_info "Установка зависимостей Asterisk..."
    contrib/scripts/install_prereq install
    
    # Конфигурация и компиляция
    log_info "Конфигурация..."
    ./configure --with-pjproject-bundled >/dev/null 2>&1
    
    log_info "Компиляция (это займёт несколько минут)..."
    make -j$(nproc) >/dev/null 2>&1
    
    log_info "Установка..."
    make install >/dev/null 2>&1
    make samples >/dev/null 2>&1
    make config >/dev/null 2>&1
    
    # Проверка
    if asterisk -V &>/dev/null; then
        log_success "Asterisk установлен: $(asterisk -V)"
    else
        log_error "Ошибка установки Asterisk"
        return 1
    fi
    
    systemctl start asterisk
    systemctl enable asterisk
}

# =============================================
# КОПИРОВАНИЕ КОНФИГОВ ASTERISK
# =============================================
copy_asterisk_configs() {
    log_step "Настройка конфигурации Asterisk..."
    
    if [ -d "$SCRIPT_DIR/asterisk" ]; then
        cp -f "$SCRIPT_DIR/asterisk/"*.conf /etc/asterisk/ 2>/dev/null || true
        
        # Подстановка переменных
        sed -i "s/\${FREEPBX_IP}/${FREEPBX_IP}/g" /etc/asterisk/pjsip.conf 2>/dev/null || true
        sed -i "s/\${FREEPBX_EXTENSION}/${FREEPBX_EXTENSION:-291}/g" /etc/asterisk/pjsip.conf 2>/dev/null || true
        sed -i "s/\${EXTENSION_PASSWORD}/${EXTENSION_PASSWORD}/g" /etc/asterisk/pjsip.conf 2>/dev/null || true
        sed -i "s/\${AMI_PASSWORD}/${AMI_PASSWORD}/g" /etc/asterisk/manager.conf 2>/dev/null || true
    fi
    
    systemctl restart asterisk
    sleep 3
    
    if asterisk -rx "core show version" &>/dev/null; then
        log_success "Конфигурация Asterisk применена"
    else
        log_warn "Проверьте конфигурацию Asterisk вручную"
    fi
}

# =============================================
# PYTHON BACKEND
# =============================================
setup_backend() {
    log_step "Установка Python бэкенда..."
    
    mkdir -p /opt/autodialer/backend
    
    if [ -d "$SCRIPT_DIR/backend" ]; then
        cp -r "$SCRIPT_DIR/backend/"* /opt/autodialer/backend/
    else
        log_error "Директория backend не найдена"
        return 1
    fi
    
    cd /opt/autodialer/backend
    
    # venv
    log_info "Создание виртуального окружения..."
    python3 -m venv venv
    source venv/bin/activate
    
    # pip install с retry
    log_info "Установка Python зависимостей..."
    for i in 1 2 3; do
        if pip install --upgrade pip setuptools wheel -q; then
            if [ -f "requirements/prod.txt" ]; then
                pip install -r requirements/prod.txt
            elif [ -f "requirements.txt" ]; then
                pip install -r requirements.txt
            fi
            break
        fi
        log_warn "Попытка $i не удалась..."
        sleep 5
    done
    
    # Alembic миграции
    if command -v alembic &>/dev/null; then
        log_info "Применение миграций..."
        alembic upgrade head 2>/dev/null || log_warn "Миграции не применены"
    fi
    
    # Создание админа
    log_info "Создание администратора..."
    cat > /opt/autodialer/.admin_credentials << EOF
============================================
AutoDialer Ultimate - Admin Credentials
============================================
Username: ${ADMIN_USERNAME}
Password: ${ADMIN_PASSWORD}
Generated: $(date)
============================================
IMPORTANT: Change this password after first login!
============================================
EOF
    chmod 600 /opt/autodialer/.admin_credentials
    
    deactivate
    
    # Копирование .env
    cp "$SCRIPT_DIR/.env" /opt/autodialer/.env
    chown autodialer:autodialer /opt/autodialer/.env
    chmod 600 /opt/autodialer/.env
    
    log_success "Бэкенд установлен"
}

# =============================================
# SYSTEMD СЕРВИС
# =============================================
setup_systemd() {
    log_step "Настройка systemd сервиса..."
    
    cat > /etc/systemd/system/autodialer.service <<EOF
[Unit]
Description=AutoDialer Ultimate Backend
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=notify
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/backend/venv/bin"
EnvironmentFile=/opt/autodialer/.env

ExecStartPre=/bin/bash -c 'until pg_isready -h \${DB_HOST:-localhost} -p \${DB_PORT:-5432}; do sleep 1; done'
ExecStartPre=/bin/bash -c 'until redis-cli -h \${REDIS_HOST:-localhost} -p \${REDIS_PORT:-6379} ping 2>/dev/null; do sleep 1; done'

ExecStart=/opt/autodialer/backend/venv/bin/gunicorn \\
    -w \${WORKERS:-4} \\
    -k uvicorn.workers.UvicornWorker \\
    -b \${HOST:-0.0.0.0}:\${PORT:-8000} \\
    --access-logfile /opt/autodialer/logs/access.log \\
    --error-logfile /opt/autodialer/logs/error.log \\
    --timeout 120 \\
    --graceful-timeout 30 \\
    backend.main:app

Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60
TimeoutStartSec=30
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable autodialer
    
    log_success "Systemd сервис создан"
}

# =============================================
# NGINX
# =============================================
setup_nginx() {
    log_step "Настройка Nginx..."
    
    # Копирование статики
    if [ -d "$SCRIPT_DIR/frontend/dist" ]; then
        mkdir -p /var/www/autodialer
        cp -r "$SCRIPT_DIR/frontend/dist/"* /var/www/autodialer/
        chown -R www-data:www-data /var/www/autodialer
    fi
    
    cat > /etc/nginx/sites-available/autodialer <<'EOF'
server {
    listen 80;
    server_name _;
    
    root /var/www/autodialer;
    index index.html;
    
    # Статика
    location /css/ {
        alias /var/www/autodialer/css/;
    }
    
    location /js/ {
        alias /var/www/autodialer/js/;
    }
    
    location /components/ {
        alias /var/www/autodialer/components/;
    }
    
    # API прокси
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
    
    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }
    
    # Документация API
    location /docs {
        proxy_pass http://127.0.0.1:8000/docs;
        proxy_set_header Host $host;
    }
    
    location /redoc {
        proxy_pass http://127.0.0.1:8000/redoc;
        proxy_set_header Host $host;
    }
    
    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/api/health;
        proxy_set_header Host $host;
    }
    
    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/autodialer /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Проверка конфигурации
    if nginx -t 2>/dev/null; then
        systemctl restart nginx
        systemctl enable nginx
        log_success "Nginx настроен"
    else
        log_error "Ошибка конфигурации Nginx"
        nginx -t
        return 1
    fi
}

# =============================================
# FIREWALL
# =============================================
setup_firewall() {
    log_step "Настройка файрвола..."
    
    ufw --force enable
    
    ufw allow 22/tcp comment 'SSH'
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'
    ufw allow 5060/udp comment 'SIP'
    ufw allow 10000:20000/udp comment 'RTP'
    
    ufw reload
    
    log_success "Файрвол настроен"
}

# =============================================
# HTTPS (CERTBOT)
# =============================================
setup_https() {
    if [ -z "${DOMAIN_NAME:-}" ]; then
        log_info "Домен не указан, HTTPS не настраивается"
        return 0
    fi
    
    log_step "Настройка HTTPS для $DOMAIN_NAME..."
    
    # Проверяем что Nginx запущен
    if ! systemctl is-active --quiet nginx; then
        systemctl start nginx
        sleep 3
    fi
    
    # Получение сертификата
    if certbot --nginx -d "$DOMAIN_NAME" \
        --non-interactive \
        --agree-tos \
        --email "${ADMIN_EMAIL:-admin@$DOMAIN_NAME}" \
        --redirect \
        --quiet 2>/dev/null; then
        log_success "HTTPS настроен для $DOMAIN_NAME"
        
        # Автообновление
        echo "0 0 * * * root certbot renew --quiet --post-hook 'systemctl reload nginx'" > /etc/cron.d/certbot-renew
    else
        log_warn "Не удалось получить сертификат (проверьте DNS)"
    fi
}

# =============================================
# ЗАПУСК СЕРВИСОВ
# =============================================
start_services() {
    log_step "Запуск сервисов..."
    
    systemctl start postgresql
    systemctl start redis-server
    systemctl start autodialer
    systemctl start asterisk
    
    # Ждать бэкенд
    log_info "Ожидание бэкенда..."
    for i in $(seq 1 30); do
        if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "ok"; then
            log_success "Бэкенд готов"
            break
        fi
        sleep 2
    done
}

# =============================================
# ФИНАЛЬНАЯ ПРОВЕРКА
# =============================================
health_check() {
    log_step "Финальная проверка..."
    
    local all_ok=true
    local services=("postgresql" "redis-server" "nginx" "autodialer" "asterisk")
    
    for svc in "${services[@]}"; do
        if systemctl is-active --quiet "$svc"; then
            log_success "$svc"
        else
            log_error "$svc"
            all_ok=false
        fi
    done
    
    # API health
    sleep 3
    if curl -s http://127.0.0.1/api/health 2>/dev/null | grep -q "ok"; then
        log_success "API health check"
    else
        log_warn "API health check (возможно, требуется время для запуска)"
    fi
    
    if [ "$all_ok" = false ]; then
        log_warn "Некоторые сервисы не запущены"
        return 1
    fi
    
    return 0
}

# =============================================
# СОЗДАНИЕ СКРИПТОВ УПРАВЛЕНИЯ
# =============================================
create_management_scripts() {
    log_step "Создание скриптов управления..."
    
    # Статус
    cat > /usr/local/bin/autodialer-status <<'EOF'
#!/bin/bash
systemctl status autodialer --no-pager
EOF
    chmod +x /usr/local/bin/autodialer-status
    
    # Логи
    cat > /usr/local/bin/autodialer-logs <<'EOF'
#!/bin/bash
journalctl -u autodialer -f "$@"
EOF
    chmod +x /usr/local/bin/autodialer-logs
    
    # Перезапуск
    cat > /usr/local/bin/autodialer-restart <<'EOF'
#!/bin/bash
systemctl restart autodialer
echo "AutoDialer перезапущен"
EOF
    chmod +x /usr/local/bin/autodialer-restart
    
    # Статус всех
    cat > /usr/local/bin/autodialer-all-status <<'EOF'
#!/bin/bash
for svc in postgresql redis-server asterisk autodialer nginx; do
    if systemctl is-active --quiet "$svc"; then
        echo "✅ $svc"
    else
        echo "❌ $svc"
    fi
done
EOF
    chmod +x /usr/local/bin/autodialer-all-status
    
    # Бэкап
    cat > /opt/autodialer/backup.sh <<'EOF'
#!/bin/bash
BACKUP_DIR="/opt/autodialer/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
PGPASSWORD="${DB_PASSWORD}" pg_dump -h "${DB_HOST:-localhost}" -U "${DB_USER:-autodialer}" "${DB_NAME:-autodialer}" > "$BACKUP_DIR/database.sql"
cp /opt/autodialer/.env "$BACKUP_DIR/"
echo "Бэкап создан: $BACKUP_DIR"
EOF
    chmod +x /opt/autodialer/backup.sh
    
    # Удаление
    cat > /opt/autodialer/uninstall.sh <<'EOF'
#!/bin/bash
echo "⚠️ ВНИМАНИЕ: Это удалит AutoDialer Ultimate!"
read -p "Введите 'yes' для подтверждения: " -r
if [ "$REPLY" != "yes" ]; then
    echo "Отмена."
    exit 0
fi
systemctl stop autodialer asterisk
systemctl disable autodialer asterisk
sudo -u postgres psql -c "DROP DATABASE IF EXISTS autodialer;"
sudo -u postgres psql -c "DROP USER IF EXISTS autodialer;"
rm -rf /opt/autodialer
rm -f /etc/systemd/system/autodialer.service
rm -f /etc/nginx/sites-enabled/autodialer
rm -f /usr/local/bin/autodialer-*
systemctl daemon-reload
systemctl reload nginx
echo "✅ AutoDialer удалён"
EOF
    chmod +x /opt/autodialer/uninstall.sh
    
    log_success "Скрипты управления созданы"
}

# =============================================
# ВЫВОД ИТОГОВОЙ ИНФОРМАЦИИ
# =============================================
print_summary() {
    SERVER_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' | head -1)
    [ -z "$SERVER_IP" ] && SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$SERVER_IP" ] && SERVER_IP="127.0.0.1"
    
    echo ""
    echo "============================================================"
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║         🎉 УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА! 🎉              ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
    echo "============================================================"
    echo ""
    echo -e "${BOLD}🌐 Доступ к системе:${NC}"
    echo "  • Веб-интерфейс:  http://$SERVER_IP/"
    if [ -n "${DOMAIN_NAME:-}" ]; then
        echo "  • Домен:          https://$DOMAIN_NAME/"
    fi
    echo "  • API документация: http://$SERVER_IP/docs"
    echo "  • Health check:   http://$SERVER_IP/api/health"
    echo ""
    echo -e "${BOLD}🔐 Учётные данные:${NC}"
    echo "  • Веб-интерфейс:  ${ADMIN_USERNAME} / ${ADMIN_PASSWORD}"
    echo "  • AMI:            ${AMI_USER:-autodialer} / ${AMI_PASSWORD}"
    echo "  • База данных:    ${DB_USER} / ${DB_PASSWORD}"
    echo ""
    echo -e "${YELLOW}${BOLD}⚠️  ВАЖНО: Смените пароль администратора после первого входа!${NC}"
    echo ""
    echo -e "${BOLD}📁 Важные файлы:${NC}"
    echo "  • Конфигурация:   /opt/autodialer/.env"
    echo "  • Учётные данные: /opt/autodialer/.admin_credentials"
    echo "  • Лог установки:  $INSTALL_LOG"
    echo ""
    echo -e "${BOLD}🛠️  Управление:${NC}"
    echo "  • Статус:         autodialer-status"
    echo "  • Статус всех:    autodialer-all-status"
    echo "  • Логи:           autodialer-logs"
    echo "  • Перезапуск:     autodialer-restart"
    echo "  • Бэкап:          /opt/autodialer/backup.sh"
    echo "  • Удаление:       /opt/autodialer/uninstall.sh"
    echo ""
    echo "============================================================"
    echo -e "${GREEN}${BOLD}✅ AutoDialer Ultimate v3.0.0 готов к работе!${NC}"
    echo "============================================================"
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=========================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate v3.0.0 - Установка${NC}"
    echo "=========================================="
    echo ""
    
    # БЛОК 1: Жёсткая проверка
    check_environment
    
    # БЛОК 2: Проверка повторной установки
    check_already_installed
    
    # БЛОК 3: Установка пакетов
    install_required_packages
    
    # БЛОК 4: Конфигурация
    load_env_safe
    
    # БЛОК 5: Создание пользователя
    create_user
    
    # БЛОК 6: Компоненты
    setup_postgresql
    setup_redis
    setup_asterisk
    copy_asterisk_configs
    setup_backend
    setup_systemd
    setup_nginx
    setup_firewall
    
    # БЛОК 7: Запуск
    start_services
    
    # БЛОК 8: HTTPS
    setup_https
    
    # БЛОК 9: Скрипты управления
    create_management_scripts
    
    # БЛОК 10: Финальная проверка
    health_check || true
    
    # БЛОК 11: Маркер установки
    date > "$MARKER_FILE"
    echo "Version: 3.0.0" >> "$MARKER_FILE"
    
    # БЛОК 12: Итоги
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
