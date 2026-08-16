#!/bin/bash
# =============================================
# AutoDialer Ultimate - Промышленный установщик
# Версия: 3.0.3 (ENTERPRISE - FINAL)
# GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate
# =============================================
# ПОДДЕРЖИВАЕТ ТОЛЬКО: Debian 12 x86_64
# МИНИМАЛЬНЫЕ ТРЕБОВАНИЯ: 2GB RAM (4GB рекомендуется), 20GB Disk, 2 CPU
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
log_header() {
    echo -e "\n${BOLD}${BLUE}========================================${NC}"
    echo -e "${BOLD}${BLUE}$1${NC}"
    echo -e "${BOLD}${BLUE}========================================${NC}"
}

# =============================================
# Обработка аргументов
# =============================================
FORCE_REINSTALL="${FORCE_REINSTALL:-false}"
SKIP_CHECKS="${SKIP_CHECKS:-false}"
SKIP_SYSTEM="${SKIP_SYSTEM:-false}"
SKIP_ASTERISK="${SKIP_ASTERISK:-false}"
SKIP_POSTGRES="${SKIP_POSTGRES:-false}"
SKIP_REDIS="${SKIP_REDIS:-false}"
SKIP_BACKEND="${SKIP_BACKEND:-false}"
SKIP_NGINX="${SKIP_NGINX:-false}"
SKIP_FIREWALL="${SKIP_FIREWALL:-false}"
SKIP_TTS="${SKIP_TTS:-false}"
SKIP_FAIL2BAN="${SKIP_FAIL2BAN:-false}"
NON_INTERACTIVE="${NON_INTERACTIVE:-true}"
AUTO_SWAP="${AUTO_SWAP:-true}"
export NON_INTERACTIVE
export DEBIAN_FRONTEND=noninteractive

while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE_REINSTALL=true
            export FORCE_REINSTALL
            shift
            ;;
        --skip-checks)
            SKIP_CHECKS=true
            export SKIP_CHECKS
            shift
            ;;
        --skip-system)
            SKIP_SYSTEM=true
            export SKIP_SYSTEM
            shift
            ;;
        --skip-asterisk)
            SKIP_ASTERISK=true
            export SKIP_ASTERISK
            shift
            ;;
        --skip-postgres)
            SKIP_POSTGRES=true
            export SKIP_POSTGRES
            shift
            ;;
        --skip-redis)
            SKIP_REDIS=true
            export SKIP_REDIS
            shift
            ;;
        --skip-backend)
            SKIP_BACKEND=true
            export SKIP_BACKEND
            shift
            ;;
        --skip-nginx)
            SKIP_NGINX=true
            export SKIP_NGINX
            shift
            ;;
        --skip-firewall)
            SKIP_FIREWALL=true
            export SKIP_FIREWALL
            shift
            ;;
        --skip-tts)
            SKIP_TTS=true
            export SKIP_TTS
            shift
            ;;
        --skip-fail2ban)
            SKIP_FAIL2BAN=true
            export SKIP_FAIL2BAN
            shift
            ;;
        --no-auto-swap)
            AUTO_SWAP=false
            export AUTO_SWAP
            shift
            ;;
        --help|-h)
            cat << EOF
Использование: sudo $0 [опции]

Опции:
  --force, -f          Принудительная переустановка
  --skip-checks        Пропустить pre-flight проверки
  --skip-system        Пропустить установку системных зависимостей
  --skip-asterisk      Пропустить установку Asterisk
  --skip-postgres      Пропустить настройку PostgreSQL
  --skip-redis         Пропустить настройку Redis
  --skip-backend       Пропустить установку Python бэкенда
  --skip-nginx         Пропустить настройку Nginx
  --skip-firewall      Пропустить настройку файрвола
  --skip-tts           Пропустить установку TTS
  --skip-fail2ban      Пропустить настройку Fail2ban
  --no-auto-swap       Не создавать swap автоматически
  --help, -h           Показать справку

EOF
            exit 0
            ;;
        *)
            log_error "Неизвестная опция: $1"
            exit 1
            ;;
    esac
done

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
    fi
    exit $exit_code
}

trap cleanup_on_error ERR

# =============================================
# Проверка необходимых утилит
# =============================================
check_required_tools() {
    log_step "Проверка необходимых утилит..."
    
    local missing=()
    local required_tools=("curl" "wget" "openssl" "grep" "sed" "awk" "cut")
    
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &>/dev/null; then
            missing+=("$tool")
        fi
    done
    
    if ! command -v nc &>/dev/null; then
        log_warn "Утилита 'nc' не найдена, установка netcat-openbsd..."
        apt-get update -qq
        apt-get install -y -qq netcat-openbsd
    fi
    
    if ! command -v host &>/dev/null; then
        log_warn "Утилита 'host' не найдена, установка dnsutils..."
        apt-get update -qq
        apt-get install -y -qq dnsutils
    fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_warn "Отсутствуют утилиты: ${missing[*]}"
        apt-get update -qq
        apt-get install -y -qq "${missing[@]}" 2>/dev/null || true
    fi
    
    log_success "Все необходимые утилиты доступны"
}

# =============================================
# НАДЁЖНЫЙ APT С ПОВТОРНЫМИ ПОПЫТКАМИ
# =============================================
apt_update_with_retry() {
    local max_attempts=5
    local attempt=0
    local wait_time=5
    
    while [ $attempt -lt $max_attempts ]; do
        if apt-get update -y 2>/tmp/apt-error.log; then
            log_success "apt update выполнен успешно"
            return 0
        fi
        
        attempt=$((attempt + 1))
        
        if [ $attempt -lt $max_attempts ]; then
            log_warn "apt update не удался (попытка $attempt/$max_attempts)"
            log_info "Ожидание ${wait_time}с перед повтором..."
            sleep $wait_time
            wait_time=$((wait_time + 5))
        fi
    done
    
    log_error "apt update не удался после $max_attempts попыток"
    return 1
}

apt_install_with_retry() {
    local packages="$1"
    local max_attempts=3
    
    for i in $(seq 1 $max_attempts); do
        if apt-get install -y $packages 2>/tmp/apt-install-error.log; then
            return 0
        fi
        
        log_warn "apt install не удался (попытка $i/$max_attempts)"
        
        if [ $i -lt $max_attempts ]; then
            sleep 5
            apt_update_with_retry || true
        fi
    done
    
    log_error "Не удалось установить: $packages"
    return 1
}

# =============================================
# УМНОЕ СОЗДАНИЕ SWAP
# =============================================
setup_swap_if_needed() {
    if [ "$AUTO_SWAP" != "true" ]; then
        return 0
    fi
    
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')
    
    if [ "$TOTAL_RAM" -ge 4000 ] || [ "$SWAP_TOTAL" -ge 1024 ]; then
        return 0
    fi
    
    FREE_DISK=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
    
    if [ "${FREE_DISK:-0}" -lt 5 ]; then
        log_warn "Недостаточно места для swap (свободно: ${FREE_DISK}GB)"
        return 0
    fi
    
    local swap_size=2
    if [ "$FREE_DISK" -lt 10 ]; then
        swap_size=1
        log_info "Мало места, создаю swap 1GB"
    fi
    
    if [ ! -f /swapfile ]; then
        log_info "Создание swap файла ${swap_size}GB..."
        fallocate -l ${swap_size}G /swapfile 2>/dev/null || \
            dd if=/dev/zero of=/swapfile bs=1M count=$((swap_size * 1024)) 2>/dev/null
        
        chmod 600 /swapfile
        mkswap /swapfile 2>/dev/null
        swapon /swapfile 2>/dev/null
        
        if ! grep -q "/swapfile" /etc/fstab; then
            echo '/swapfile none swap sw 0 0' >> /etc/fstab
        fi
        
        log_success "Swap ${swap_size}GB создан"
    fi
}

# =============================================
# ЖЁСТКАЯ ПРОВЕРКА ОКРУЖЕНИЯ
# =============================================
check_environment() {
    log_step "Проверка окружения..."
    
    if [ "$EUID" -ne 0 ]; then
        log_error "Требуются права root. Используйте: sudo $0"
        exit 1
    fi
    log_success "Права root"
    
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
    
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM" -lt 2048 ]; then
        log_error "Недостаточно RAM. Требуется минимум 2GB. Обнаружено: ${TOTAL_RAM}MB"
        exit 1
    fi
    
    if [ "$TOTAL_RAM" -lt 4096 ]; then
        log_warn "Мало RAM (${TOTAL_RAM}MB). MAKE_JOBS=1"
        export MAKE_JOBS=1
    else
        export MAKE_JOBS=$(nproc)
    fi
    log_success "RAM: ${TOTAL_RAM}MB (MAKE_JOBS=${MAKE_JOBS:-auto})"
    
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
# Установка обязательных пакетов
# =============================================
install_required_packages() {
    log_step "Установка обязательных пакетов..."
    
    apt_update_with_retry
    apt_install_with_retry "ca-certificates gnupg curl wget"
    
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
    
    apt_install_with_retry "${REQUIRED_PACKAGES[*]}"
    log_success "Все пакеты установлены"
}

# =============================================
# ИСПРАВЛЕННАЯ ЗАГРУЗКА .env
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
    
    log_info "Чтение .env..."
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" | cut -d'#' -f1)
        
        if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [ -n "$value" ]; then
            export "$key=$value"
            log_info "  ✓ $key = $value"
        fi
    done < "$SCRIPT_DIR/.env"
    
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
    export FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
    export MAX_CALLS="${MAX_CALLS:-50}"
    export DEFAULT_CPS="${DEFAULT_CPS:-5.0}"
    export CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
    export MAX_RETRIES="${MAX_RETRIES:-3}"
    export TTS_VOICE="${TTS_VOICE:-denis}"
    
    REQUIRED_VARS=("FREEPBX_IP" "EXTENSION_PASSWORD")
    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var:-}" ]; then
            log_error "Отсутствует обязательная переменная: $var"
            log_error "Проверьте файл .env"
            exit 1
        fi
    done
    
    log_success "Конфигурация загружена"
    log_info "  FreePBX IP: ${FREEPBX_IP}"
    log_info "  Extension:   ${FREEPBX_EXTENSION}"
    
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
        /usr/sbin/useradd -r -s /bin/bash -m -d /opt/autodialer autodialer
        log_success "Пользователь autodialer создан"
    fi
    
    /usr/sbin/usermod -aG audio autodialer 2>/dev/null || true
    /usr/sbin/usermod -aG www-data autodialer 2>/dev/null || true
    # /var/lib/asterisk/sounds/tts is chown asterisk:asterisk, mode 755
    # (06_tts_install.sh's set_permissions) - without group membership
    # the autodialer service (runs as User=autodialer, see
    # 09_python_backend.sh's systemd unit) can read but not write there,
    # so campaign.py's per-campaign audio symlinking
    # (CampaignService._link_campaign_audio) would fail with
    # PermissionError on every campaign start.
    /usr/sbin/usermod -aG asterisk autodialer 2>/dev/null || true
    
    mkdir -p /opt/autodialer/{logs,backups,uploads,recordings}
    chown -R autodialer:autodialer /opt/autodialer
}

# =============================================
# КОПИРОВАНИЕ ВСЕХ ФАЙЛОВ ПРОЕКТА
# =============================================
copy_project_files() {
    log_step "Копирование файлов проекта..."
    
    mkdir -p /opt/autodialer
    mkdir -p /opt/autodialer/{logs,data,uploads,recordings,backups}
    mkdir -p /opt/autodialer/logs/{backend,nginx,asterisk}
    mkdir -p /opt/autodialer/frontend/dist
    mkdir -p /etc/asterisk

    # Бэкенд
    [ -d "$SCRIPT_DIR/backend" ] && cp -r "$SCRIPT_DIR/backend" /opt/autodialer/ && log_success "  ✓ backend/"
    [ -d "$SCRIPT_DIR/app" ] && cp -r "$SCRIPT_DIR/app" /opt/autodialer/ && log_success "  ✓ app/"
    [ -d "$SCRIPT_DIR/utils" ] && cp -r "$SCRIPT_DIR/utils" /opt/autodialer/ && log_success "  ✓ utils/"
    [ -d "$SCRIPT_DIR/migrations" ] && cp -r "$SCRIPT_DIR/migrations" /opt/autodialer/ && log_success "  ✓ migrations/"

    # Фронтенд
    # scripts/10_nginx_setup.sh's generated `location /` block serves from
    # `root /opt/autodialer/frontend/dist` - this used to be copied to
    # /var/www/autodialer instead, a path nothing ever pointed Nginx at,
    # so index.html never existed where Nginx looked and every request to
    # "/" 404'd even though Nginx itself was up and healthy.
    if [ -d "$SCRIPT_DIR/frontend/dist" ]; then
        cp -r "$SCRIPT_DIR/frontend/dist/"* /opt/autodialer/frontend/dist/
        log_success "  ✓ frontend/dist/"
    fi
    
    # Конфиги Asterisk
    if [ -d "$SCRIPT_DIR/asterisk" ]; then
        cp -f "$SCRIPT_DIR/asterisk/"*.conf /etc/asterisk/ 2>/dev/null || true
        log_success "  ✓ asterisk/*.conf"
    fi
    
    # SQL
    if [ -d "$SCRIPT_DIR/sql" ]; then
        mkdir -p /opt/autodialer/sql
        cp -r "$SCRIPT_DIR/sql/"* /opt/autodialer/sql/ 2>/dev/null || true
        log_success "  ✓ sql/"
    fi
    
    # Requirements (real files live under app/requirements/, same ones the
    # Docker build uses - 09_python_backend.sh's copy_backend_files() is
    # what actually installs from them, this is just a convenience copy)
    mkdir -p /opt/autodialer/requirements
    [ -d "$SCRIPT_DIR/app/requirements" ] && cp -r "$SCRIPT_DIR/app/requirements/"* /opt/autodialer/requirements/
    
    # .env
    [ -f "$SCRIPT_DIR/.env" ] && cp "$SCRIPT_DIR/.env" /opt/autodialer/.env && chmod 600 /opt/autodialer/.env
    [ -f "$SCRIPT_DIR/.env.example" ] && cp "$SCRIPT_DIR/.env.example" /opt/autodialer/
    
    # Скрипты
    if [ -d "$SCRIPT_DIR/scripts" ]; then
        mkdir -p /opt/autodialer/scripts
        cp -r "$SCRIPT_DIR/scripts/"*.sh /opt/autodialer/scripts/ 2>/dev/null || true
        chmod +x /opt/autodialer/scripts/*.sh 2>/dev/null || true
        log_success "  ✓ scripts/"
    fi
    
    # Права
    chown -R autodialer:autodialer /opt/autodialer
    chown -R www-data:www-data /opt/autodialer/frontend/dist
    chown -R asterisk:asterisk /etc/asterisk 2>/dev/null || true
    
    log_success "Копирование файлов завершено"
}

# =============================================
# ВСЕ СКРИПТЫ УСТАНОВКИ (14 штук)
# =============================================
ALL_SCRIPTS=(
    "01_system_setup.sh:Настройка системы и установка зависимостей"
    "02_asterisk_install.sh:Установка Asterisk 21"
    "03_asterisk_config.sh:Конфигурация Asterisk"
    "04_pjsip_config.sh:Настройка PJSIP"
    "05_dialplan_config.sh:Настройка Dialplan"
    "06_tts_install.sh:Установка Piper TTS"
    "07_postgresql_setup.sh:Настройка PostgreSQL"
    "08_redis_setup.sh:Настройка Redis"
    "09_python_backend.sh:Установка Python бэкенда"
    "10_nginx_setup.sh:Настройка Nginx"
    "11_firewall_setup.sh:Настройка файрвола"
    "12_start_services.sh:Запуск всех сервисов"
    "13_fail2ban_setup.sh:Настройка Fail2ban"
    "14_logrotate_setup.sh:Настройка Logrotate"
)

CRITICAL_SCRIPTS=(
    "01_system_setup.sh"
    "02_asterisk_install.sh"
    "07_postgresql_setup.sh"
    "08_redis_setup.sh"
    "09_python_backend.sh"
)

is_critical() {
    local script="$1"
    for critical in "${CRITICAL_SCRIPTS[@]}"; do
        if [[ "$script" == "$critical" ]]; then
            return 0
        fi
    done
    return 1
}

run_script() {
    local script="$1"
    local description="$2"
    
    local script_path="$SCRIPT_DIR/scripts/$script"
    
    if [ ! -f "$script_path" ]; then
        log_warn "$script не найден, пропускаю..."
        return 0
    fi
    
    log_header "Выполнение: $description"
    
    export NON_INTERACTIVE FORCE_REINSTALL SKIP_TTS MAKE_JOBS
    
    local error_log=$(mktemp)
    
    if bash "$script_path" 2>"$error_log"; then
        log_success "$script выполнен успешно"
        rm -f "$error_log"
        return 0
    else
        local exit_code=$?
        log_error "$script завершился с ошибкой (код $exit_code)"
        
        if [ -s "$error_log" ]; then
            echo ""
            echo "Последние 30 строк ошибок:"
            echo "---------------------------"
            tail -30 "$error_log"
            echo "---------------------------"
        fi
        rm -f "$error_log"
        return 1
    fi
}

run_all_scripts() {
    for script_info in "${ALL_SCRIPTS[@]}"; do
        local script="${script_info%%:*}"
        local description="${script_info##*:}"
        
        # Проверка флагов пропуска
        [[ "$script" == *"system"* ]] && [ "$SKIP_SYSTEM" = true ] && { log_warn "Пропуск $script (--skip-system)"; continue; }
        [[ "$script" == *"asterisk"* ]] && [ "$SKIP_ASTERISK" = true ] && { log_warn "Пропуск $script (--skip-asterisk)"; continue; }
        [[ "$script" == *"postgres"* ]] && [ "$SKIP_POSTGRES" = true ] && { log_warn "Пропуск $script (--skip-postgres)"; continue; }
        [[ "$script" == *"redis"* ]] && [ "$SKIP_REDIS" = true ] && { log_warn "Пропуск $script (--skip-redis)"; continue; }
        [[ "$script" == *"backend"* ]] && [ "$SKIP_BACKEND" = true ] && { log_warn "Пропуск $script (--skip-backend)"; continue; }
        [[ "$script" == *"nginx"* ]] && [ "$SKIP_NGINX" = true ] && { log_warn "Пропуск $script (--skip-nginx)"; continue; }
        [[ "$script" == *"firewall"* ]] && [ "$SKIP_FIREWALL" = true ] && { log_warn "Пропуск $script (--skip-firewall)"; continue; }
        [[ "$script" == *"tts"* ]] && [ "$SKIP_TTS" = true ] && { log_warn "Пропуск $script (--skip-tts)"; continue; }
        [[ "$script" == *"fail2ban"* ]] && [ "$SKIP_FAIL2BAN" = true ] && { log_warn "Пропуск $script (--skip-fail2ban)"; continue; }
        
        run_script "$script" "$description" || {
            if is_critical "$script"; then
                log_error "КРИТИЧЕСКАЯ ОШИБКА в $script. Установка прервана."
                exit 1
            fi
            log_warn "Некритическая ошибка в $script, продолжаем..."
        }
    done
}

# =============================================
# ОЖИДАНИЕ СЕРВИСОВ
# =============================================
wait_for_service() {
    local host="${1:-127.0.0.1}"
    local port="$2"
    local max_attempts="${3:-30}"
    local description="${4:-$host:$port}"
    
    log_info "Ожидание $description..."
    
    for i in $(seq 1 $max_attempts); do
        if timeout 2 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
            log_success "$description готов"
            return 0
        fi
        sleep 2
    done
    
    log_warn "$description не ответил за $((max_attempts * 2)) секунд"
    return 1
}

wait_for_all_services() {
    log_step "Ожидание готовности сервисов..."
    
    wait_for_service "${DB_HOST:-127.0.0.1}" "${DB_PORT:-5432}" 30 "PostgreSQL" || true
    wait_for_service "${REDIS_HOST:-127.0.0.1}" "${REDIS_PORT:-6379}" 30 "Redis" || true
    wait_for_service "127.0.0.1" "5038" 30 "Asterisk AMI" || true
    wait_for_service "127.0.0.1" "80" 30 "Nginx" || true
    
    log_info "Ожидание бэкенда..."
    for i in $(seq 1 30); do
        if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q '"status"[[:space:]]*:[[:space:]]*"\(healthy\|degraded\)"'; then
            log_success "Бэкенд готов"
            break
        fi
        sleep 2
    done
}

# =============================================
# ПРОВЕРКА УСТАНОВКИ
# =============================================
verify_installation() {
    log_step "Проверка установки..."
    
    local all_ok=true
    
    check_service_with_retry() {
        local service="$1"
        for i in $(seq 1 10); do
            if systemctl is-active --quiet "$service" 2>/dev/null; then
                return 0
            fi
            sleep 2
        done
        return 1
    }
    
    SERVICES=("postgresql" "redis-server" "asterisk" "autodialer" "nginx")
    for svc in "${SERVICES[@]}"; do
        if check_service_with_retry "$svc"; then
            log_success "$svc работает"
        else
            log_warn "$svc не запущен"
            all_ok=false
        fi
    done
    
    for i in $(seq 1 15); do
        if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q '"status"[[:space:]]*:[[:space:]]*"\(healthy\|degraded\)"'; then
            log_success "API отвечает"
            break
        fi
        if [ $i -eq 15 ]; then
            log_warn "API не отвечает"
            all_ok=false
        fi
        sleep 2
    done
    
    if [ "$all_ok" = true ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$MARKER_FILE"
        echo "Version: 3.0.3" >> "$MARKER_FILE"
        log_success "Все проверки пройдены"
        return 0
    else
        return 1
    fi
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
    
    if ! systemctl is-active --quiet nginx; then
        systemctl start nginx
        sleep 3
    fi
    
    if timeout 120 certbot --nginx -d "$DOMAIN_NAME" \
        --non-interactive \
        --agree-tos \
        --email "${ADMIN_EMAIL:-admin@$DOMAIN_NAME}" \
        --redirect \
        --quiet 2>/dev/null; then
        log_success "HTTPS настроен для $DOMAIN_NAME"
        echo "0 0 * * * root certbot renew --quiet --post-hook 'systemctl reload nginx'" > /etc/cron.d/certbot-renew
    else
        log_warn "Не удалось получить сертификат (проверьте DNS)"
    fi
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
echo "AutoDialer перезапущен"
EOF
    chmod +x /usr/local/bin/autodialer-restart
    
    cat > /usr/local/bin/autodialer-all-status << 'EOF'
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
    
    cat > /opt/autodialer/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/autodialer/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
PGPASSWORD="${DB_PASSWORD}" pg_dump -h "${DB_HOST:-localhost}" -U "${DB_USER:-autodialer}" "${DB_NAME:-autodialer}" > "$BACKUP_DIR/database.sql"
cp /opt/autodialer/.env "$BACKUP_DIR/"
echo "Бэкап создан: $BACKUP_DIR"
EOF
    chmod +x /opt/autodialer/backup.sh
    
    cat > /opt/autodialer/uninstall.sh << 'EOF'
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
# POST-INSTALL ДИАГНОСТИКА
# =============================================
post_install_diagnostics() {
    log_step "Постустановочная диагностика..."
    
    local report_file="/opt/autodialer/logs/post-install-$(date +%Y%m%d_%H%M%S).log"
    mkdir -p "$(dirname "$report_file")"
    
    {
        echo "=============================================="
        echo "AutoDialer Ultimate - Post-Install Diagnostics"
        echo "Date: $(date)"
        echo "=============================================="
        echo ""
        echo "=== SYSTEM INFO ==="
        uname -a
        cat /etc/os-release | head -3
        echo ""
        echo "=== RESOURCES ==="
        free -h
        df -h
        echo ""
        echo "=== SERVICES ==="
        for svc in postgresql redis-server asterisk autodialer nginx; do
            echo -n "$svc: "
            systemctl is-active "$svc" 2>/dev/null || echo "inactive"
        done
        echo ""
        echo "=== API HEALTH ==="
        curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | head -5 || echo "FAILED"
        echo ""
        echo "=== REDIS ==="
        redis-cli ping 2>/dev/null || echo "FAILED"
        echo ""
        echo "=== POSTGRESQL ==="
        pg_isready 2>/dev/null && echo "ready" || echo "FAILED"
        echo ""
        echo "=== ASTERISK ==="
        asterisk -rx "core show version" 2>/dev/null | head -1 || echo "FAILED"
        echo ""
        echo "=== PJSIP REGISTRATION ==="
        asterisk -rx "pjsip show registrations" 2>/dev/null | grep -E "Registered|No objects" || echo "No registrations"
        echo ""
        echo "=== BACKEND LOGS (last 50) ==="
        journalctl -u autodialer -n 50 --no-pager 2>/dev/null || echo "No logs"
    } > "$report_file"
    
    log_success "Диагностика сохранена: $report_file"
    
    echo ""
    if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q '"status"[[:space:]]*:[[:space:]]*"\(healthy\|degraded\)"'; then
        log_success "✅ API работает корректно"
    else
        log_error "❌ API НЕ РАБОТАЕТ"
        echo ""
        echo "Последние ошибки бэкенда:"
        journalctl -u autodialer -n 20 --no-pager 2>/dev/null | grep -i error || echo "Нет ошибок"
    fi
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
    echo "  • Веб-интерфейс:  ${ADMIN_USERNAME:-admin} / ${ADMIN_PASSWORD:-см. /opt/autodialer/.admin_credentials}"
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
    echo -e "${GREEN}${BOLD}✅ AutoDialer Ultimate v3.0.3 готов к работе!${NC}"
    echo "============================================================"
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=========================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate v3.0.3 - Установка${NC}"
    echo "=========================================="
    echo ""
    
    check_required_tools
    setup_swap_if_needed
    check_environment
    check_already_installed
    install_required_packages
    load_env_safe
    create_user
    copy_project_files
    run_all_scripts
    wait_for_all_services
    setup_https || true
    create_management_scripts
    verify_installation
    post_install_diagnostics
    print_summary
    
    log_success "Установка завершена: $(date)"
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
