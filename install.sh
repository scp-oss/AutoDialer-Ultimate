#!/bin/bash
# =============================================
# AutoDialer Ultimate - Главный установщик
# Версия: 3.0.0
# GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate
# =============================================
# Установка на "голое железо" (Debian 12)
# Все компоненты устанавливаются напрямую в систему
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR
cd "$SCRIPT_DIR"

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

# =============================================
# Функции логирования
# =============================================
INSTALL_LOG="${INSTALL_LOG:-/var/log/autodialer-install.log}"
mkdir -p "$(dirname "$INSTALL_LOG")" 2>/dev/null || true
exec > >(tee -a "$INSTALL_LOG") 2>&1

log() { echo -e "${2:-}[$(date '+%H:%M:%S')]${NC} $1"; }
log_info() { log "$1" "${BLUE}[INFO]"; }
log_success() { log "$1" "${GREEN}[OK]"; }
log_warn() { log "$1" "${YELLOW}[WARN]"; }
log_error() { log "$1" "${RED}[ERROR]"; }
log_step() { echo -e "\n${BOLD}${CYAN}▶ $1${NC}"; }
log_header() {
    echo -e "\n${BOLD}${BLUE}========================================${NC}"
    echo -e "${BOLD}${BLUE}$1${NC}"
    echo -e "${BOLD}${BLUE}========================================${NC}"
}

# =============================================
# Trap для обработки ошибок
# =============================================
cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "=============================================="
        log_error "Установка прервана с кодом $exit_code"
        log_error "Проверьте лог: $INSTALL_LOG"
        log_error "=============================================="
    fi
    exit $exit_code
}

trap cleanup_on_error EXIT

# =============================================
# Обработка аргументов командной строки
# =============================================
NON_INTERACTIVE="${NON_INTERACTIVE:-false}"
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
FORCE_REINSTALL="${FORCE_REINSTALL:-false}"

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --yes|-y)
                NON_INTERACTIVE=true
                export NON_INTERACTIVE
                shift
                ;;
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
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Неизвестная опция: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

show_help() {
    cat << EOF
Использование: sudo $0 [опции]

Опции:
  --yes, -y              Неинтерактивный режим (не задавать вопросы)
  --force, -f            Принудительная переустановка
  --skip-checks          Пропустить pre-flight проверки
  --skip-system          Пропустить установку системных зависимостей
  --skip-asterisk        Пропустить установку Asterisk
  --skip-postgres        Пропустить настройку PostgreSQL
  --skip-redis           Пропустить настройку Redis
  --skip-backend         Пропустить установку Python бэкенда
  --skip-nginx           Пропустить настройку Nginx
  --skip-firewall        Пропустить настройку файрвола
  --skip-tts             Пропустить установку TTS
  --skip-fail2ban        Пропустить настройку Fail2ban
  --help, -h             Показать эту справку

Примеры:
  sudo ./install.sh --yes
  sudo ./install.sh --skip-firewall --skip-tts
  sudo ./install.sh --force --skip-checks

EOF
}

parse_args "$@"

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
# Загрузка конфигурации из .env
# =============================================
load_env() {
    log_step "Загрузка конфигурации..."
    
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        if [ -f "$SCRIPT_DIR/.env.example" ]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            log_warn "Создан .env из примера."
            log_error "Отредактируйте .env перед продолжением!"
            log_info "Редактировать: nano $SCRIPT_DIR/.env"
            exit 1
        else
            log_error "Файл .env не найден и .env.example отсутствует"
            exit 1
        fi
    fi
    
    # Безопасная загрузка .env
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
    
    # Установка значений по умолчанию
    export FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
    export MAX_CALLS="${MAX_CALLS:-50}"
    export DEFAULT_CPS="${DEFAULT_CPS:-5.0}"
    export CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
    export MAX_RETRIES="${MAX_RETRIES:-3}"
    export TTS_VOICE="${TTS_VOICE:-denis}"
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    export DB_HOST="${DB_HOST:-localhost}"
    export DB_PORT="${DB_PORT:-5432}"
    export REDIS_HOST="${REDIS_HOST:-localhost}"
    export REDIS_PORT="${REDIS_PORT:-6379}"
    export WORKERS="${WORKERS:-4}"
    export PORT="${PORT:-8000}"
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"
    export ENVIRONMENT="${ENVIRONMENT:-production}"
    export DOMAIN_NAME="${DOMAIN_NAME:-}"
    export TRUSTED_PROXIES="${TRUSTED_PROXIES:-10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1}"
    export TIMEZONE="${TIMEZONE:-UTC}"
    export ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
    export ADMIN_EMAIL="${ADMIN_EMAIL:-admin@localhost}"
    export FORCE_ADMIN_PASSWORD_CHANGE="${FORCE_ADMIN_PASSWORD_CHANGE:-true}"
    
    log_success "Конфигурация загружена"
    log_info "  FreePBX IP:      ${FREEPBX_IP:-НЕ ЗАДАН!}"
    log_info "  Extension:        $FREEPBX_EXTENSION"
    log_info "  Макс. каналов:    $MAX_CALLS"
    log_info "  CPS по умолчанию: $DEFAULT_CPS"
    log_info "  Домен:            ${DOMAIN_NAME:-не настроен}"
}

# =============================================
# Проверка обязательных переменных
# =============================================
check_required_vars() {
    log_step "Проверка обязательных переменных..."
    
    local missing=()
    
    [ -z "${FREEPBX_IP:-}" ] && missing+=("FREEPBX_IP")
    [ -z "${EXTENSION_PASSWORD:-}" ] && missing+=("EXTENSION_PASSWORD")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Отсутствуют обязательные переменные в .env:"
        for var in "${missing[@]}"; do
            echo "  - $var"
        done
        log_error "Отредактируйте .env и запустите установку снова."
        exit 1
    fi
    
    log_success "Все обязательные переменные заданы"
}

# =============================================
# Генерация секретов
# =============================================
generate_secrets() {
    log_step "Проверка секретов..."
    
    local secrets_updated=false
    
    if [ -z "${DB_PASSWORD:-}" ]; then
        DB_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "autodialer_pass_$(date +%s)")
        echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/.env"
        export DB_PASSWORD
        secrets_updated=true
        log_info "Сгенерирован DB_PASSWORD"
    fi
    
    if [ -z "${JWT_SECRET:-}" ]; then
        JWT_SECRET=$(openssl rand -hex 32 2>/dev/null || echo "jwt_secret_$(date +%s)")
        echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/.env"
        export JWT_SECRET
        secrets_updated=true
        log_info "Сгенерирован JWT_SECRET"
    fi
    
    if [ -z "${AMI_PASSWORD:-}" ]; then
        AMI_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "ami_pass_$(date +%s)")
        echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/.env"
        export AMI_PASSWORD
        secrets_updated=true
        log_info "Сгенерирован AMI_PASSWORD"
    fi
    
    if [ -z "${REDIS_PASSWORD:-}" ]; then
        REDIS_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "redis_pass_$(date +%s)")
        echo "REDIS_PASSWORD=$REDIS_PASSWORD" >> "$SCRIPT_DIR/.env"
        export REDIS_PASSWORD
        secrets_updated=true
        log_info "Сгенерирован REDIS_PASSWORD"
    fi
    
    if [ "$secrets_updated" = true ]; then
        log_success "Секреты сгенерированы и сохранены в .env"
    else
        log_info "Все секреты уже заданы"
    fi
}

# =============================================
# Pre-flight проверки
# =============================================
preflight_checks() {
    log_step "Pre-flight проверки..."
    
    # Проверка прав root
    check_root
    log_success "Права root: OK"
    
    # Проверка ОС
    if [ -f /etc/os-release ]; then
        source /etc/os-release
        if [[ "$ID" = "debian" ]] || [[ "$ID_LIKE" = *"debian"* ]]; then
            log_success "ОС: $PRETTY_NAME"
            if [[ "$VERSION_ID" != "12" ]]; then
                log_warn "Рекомендуется Debian 12. Обнаружено: $VERSION_ID"
            fi
        else
            log_warn "Рекомендуется Debian. Обнаружено: $ID"
        fi
    fi
    
    # Проверка архитектуры
    ARCH=$(uname -m)
    if [[ "$ARCH" == "x86_64" ]]; then
        log_success "Архитектура: $ARCH"
    else
        log_error "Требуется x86_64. Обнаружено: $ARCH"
        exit 1
    fi
    
    # Проверка RAM
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM" -ge 3500 ]; then
        log_success "RAM: ${TOTAL_RAM}MB"
    else
        log_warn "Рекомендуется минимум 4GB RAM. Обнаружено: ${TOTAL_RAM}MB"
    fi
    
    # Проверка диска
    FREE_DISK=$(df -BG /opt 2>/dev/null | awk 'NR==2 {print $4}' | sed 's/G//')
    if [ -z "$FREE_DISK" ]; then
        FREE_DISK=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
    fi
    if [ "${FREE_DISK:-0}" -ge 20 ]; then
        log_success "Свободное место: ${FREE_DISK}GB"
    else
        log_error "Требуется минимум 20GB. Обнаружено: ${FREE_DISK}GB"
        exit 1
    fi
    
    # Проверка подключения к FreePBX
    if [ -n "${FREEPBX_IP:-}" ] && [ "$FREEPBX_IP" != "127.0.0.1" ]; then
        log_info "Проверка подключения к FreePBX ($FREEPBX_IP)..."
        if timeout 3 ping -c 1 "$FREEPBX_IP" &>/dev/null; then
            log_success "FreePBX доступен"
        else
            log_warn "FreePBX не отвечает на ping. Проверьте сеть."
        fi
    fi
    
    # Проверка DNS (если указан домен)
    if [ -n "${DOMAIN_NAME:-}" ]; then
        log_info "Проверка DNS для $DOMAIN_NAME..."
        if host "$DOMAIN_NAME" &>/dev/null; then
            log_success "DNS для $DOMAIN_NAME разрешается"
        else
            log_warn "DNS для $DOMAIN_NAME не разрешается"
        fi
    fi
    
    log_success "Pre-flight проверки завершены"
}

# =============================================
# Проверка идемпотентности
# =============================================
INSTALLED_MARKER="/opt/autodialer/.installed"

check_already_installed() {
    if [ -f "$INSTALLED_MARKER" ] && [ "$FORCE_REINSTALL" != "true" ]; then
        log_warn "AutoDialer уже установлен (найден $INSTALLED_MARKER)"
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Переустановить? Существующие данные могут быть потеряны. [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "Установка отменена"
                exit 0
            fi
        fi
        log_warn "Продолжение установки..."
    fi
}

# =============================================
# Создание бэкапов
# =============================================
BACKUP_DIR="/opt/autodialer/backup/$(date +%Y%m%d_%H%M%S)"

backup_existing() {
    local path="$1"
    if [ -e "$path" ]; then
        mkdir -p "$BACKUP_DIR"
        cp -r "$path" "$BACKUP_DIR/" 2>/dev/null || true
        log_info "Создан бэкап: $path -> $BACKUP_DIR/"
    fi
}

# =============================================
# Подготовка скриптов
# =============================================
prepare_scripts() {
    log_step "Подготовка скриптов..."
    
    if [ -d "$SCRIPT_DIR/scripts" ]; then
        chmod +x "$SCRIPT_DIR/scripts/"*.sh 2>/dev/null || true
        log_success "Скрипты готовы"
    else
        log_error "Директория scripts не найдена!"
        log_info "Убедитесь, что вы клонировали репозиторий полностью:"
        log_info "  git clone https://github.com/naumenis-code/AutoDialer-Ultimate.git"
        exit 1
    fi
}

# =============================================
# Запуск скрипта
# =============================================
CRITICAL_SCRIPTS=(
    "01_system_setup.sh"
    "02_asterisk_install.sh"
    "07_postgresql_setup.sh"
    "08_redis_setup.sh"
    "09_python_backend.sh"
    "12_start_services.sh"
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
    
    # Проверка флагов пропуска
    if [[ "$script" == *"system"* ]] && [ "$SKIP_SYSTEM" = true ]; then
        log_warn "Пропуск $script (--skip-system)"
        return 0
    fi
    if [[ "$script" == *"asterisk"* ]] && [ "$SKIP_ASTERISK" = true ]; then
        log_warn "Пропуск $script (--skip-asterisk)"
        return 0
    fi
    if [[ "$script" == *"postgres"* ]] && [ "$SKIP_POSTGRES" = true ]; then
        log_warn "Пропуск $script (--skip-postgres)"
        return 0
    fi
    if [[ "$script" == *"redis"* ]] && [ "$SKIP_REDIS" = true ]; then
        log_warn "Пропуск $script (--skip-redis)"
        return 0
    fi
    if [[ "$script" == *"backend"* ]] && [ "$SKIP_BACKEND" = true ]; then
        log_warn "Пропуск $script (--skip-backend)"
        return 0
    fi
    if [[ "$script" == *"nginx"* ]] && [ "$SKIP_NGINX" = true ]; then
        log_warn "Пропуск $script (--skip-nginx)"
        return 0
    fi
    if [[ "$script" == *"firewall"* ]] && [ "$SKIP_FIREWALL" = true ]; then
        log_warn "Пропуск $script (--skip-firewall)"
        return 0
    fi
    if [[ "$script" == *"tts"* ]] && [ "$SKIP_TTS" = true ]; then
        log_warn "Пропуск $script (--skip-tts)"
        return 0
    fi
    if [[ "$script" == *"fail2ban"* ]] && [ "$SKIP_FAIL2BAN" = true ]; then
        log_warn "Пропуск $script (--skip-fail2ban)"
        return 0
    fi
    
    local is_crit="false"
    if is_critical "$script"; then
        is_crit="true"
    fi
    
    log_header "Выполнение: $description"
    
    # Передаём переменные окружения
    export NON_INTERACTIVE
    export FORCE_REINSTALL
    export SKIP_TTS
    
    if bash "$script_path"; then
        log_success "$script выполнен успешно"
        return 0
    else
        local exit_code=$?
        log_error "$script завершился с ошибкой (код $exit_code)"
        
        if [ "$is_crit" = "true" ]; then
            log_error "КРИТИЧЕСКАЯ ОШИБКА. Установка прервана."
            exit 1
        fi
        
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Продолжить установку? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
        
        return 1
    fi
}

# =============================================
# Ожидание сервисов
# =============================================
wait_for_service() {
    local service="$1"
    local host="${2:-127.0.0.1}"
    local port="$3"
    local max_attempts="${4:-30}"
    local description="${5:-$service}"
    
    log_info "Ожидание $description ($host:$port)..."
    
    for i in $(seq 1 $max_attempts); do
        if nc -z "$host" "$port" 2>/dev/null; then
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
    
    wait_for_service "postgresql" "${DB_HOST:-127.0.0.1}" "${DB_PORT:-5432}" 30 "PostgreSQL" || true
    wait_for_service "redis" "${REDIS_HOST:-127.0.0.1}" "${REDIS_PORT:-6379}" 30 "Redis" || true
    wait_for_service "asterisk-ami" "127.0.0.1" "5038" 30 "Asterisk AMI" || true
    wait_for_service "nginx" "127.0.0.1" "80" 30 "Nginx" || true
    
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
# Проверка установки
# =============================================
verify_installation() {
    log_step "Проверка установки..."
    
    local all_ok=true
    
    SERVICES=("postgresql" "redis-server" "asterisk" "autodialer" "nginx")
    for svc in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            log_success "$svc работает"
        else
            log_warn "$svc не запущен"
            all_ok=false
        fi
    done
    
    if curl -s http://127.0.0.1:${PORT:-8000}/api/health 2>/dev/null | grep -q "ok"; then
        log_success "API отвечает"
    else
        log_warn "API не отвечает"
        all_ok=false
    fi
    
    if command -v asterisk &>/dev/null && asterisk -rx "core show version" &>/dev/null; then
        log_success "Asterisk отвечает"
    else
        log_warn "Asterisk не отвечает"
        all_ok=false
    fi
    
    if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null; then
        log_success "Redis отвечает"
    else
        log_warn "Redis не отвечает"
        all_ok=false
    fi
    
    if [ "$all_ok" = true ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$INSTALLED_MARKER"
        echo "Version: 3.0.0" >> "$INSTALLED_MARKER"
        log_success "Все проверки пройдены"
        return 0
    else
        return 1
    fi
}

# =============================================
# Настройка HTTPS (Certbot)
# =============================================
setup_https() {
    if [ -z "${DOMAIN_NAME:-}" ]; then
        return 0
    fi
    
    if ! command -v certbot &>/dev/null; then
        log_info "Установка Certbot..."
        apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
    fi
    
    log_step "Настройка HTTPS для $DOMAIN_NAME..."
    
    if [ "$NON_INTERACTIVE" = true ]; then
        certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --email "${ADMIN_EMAIL:-admin@$DOMAIN_NAME}" 2>/dev/null || {
            log_warn "Не удалось получить сертификат для $DOMAIN_NAME"
            return 1
        }
    else
        certbot --nginx -d "$DOMAIN_NAME"
    fi
    
    if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
        log_success "HTTPS настроен для $DOMAIN_NAME"
        
        # Настройка автообновления
        echo "0 0 * * * root certbot renew --quiet --post-hook 'systemctl reload nginx'" > /etc/cron.d/certbot-renew
    else
        log_warn "Сертификат не получен"
    fi
}

# =============================================
# Создание скрипта удаления
# =============================================
create_uninstall_script() {
    log_step "Создание скрипта удаления..."
    
    cat > /opt/autodialer/uninstall.sh << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - Скрипт удаления

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║  ⚠ ВНИМАНИЕ: Это полностью удалит AutoDialer Ultimate!   ║${NC}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Будут удалены:"
echo "  • Все файлы в /opt/autodialer"
echo "  • База данных autodialer"
echo "  • Системные сервисы"
echo "  • Конфигурации Nginx"
echo ""

read -p "Вы уверены? Введите 'yes' для подтверждения: " -r
if [ "$REPLY" != "yes" ]; then
    echo -e "${GREEN}Отмена.${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}Остановка сервисов...${NC}"
systemctl stop autodialer 2>/dev/null || true
systemctl stop asterisk 2>/dev/null || true
systemctl disable autodialer 2>/dev/null || true
systemctl disable asterisk 2>/dev/null || true

echo -e "${YELLOW}Удаление базы данных...${NC}"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS autodialer;" 2>/dev/null || true
sudo -u postgres psql -c "DROP USER IF EXISTS autodialer;" 2>/dev/null || true

echo -e "${YELLOW}Удаление файлов...${NC}"
rm -rf /opt/autodialer
rm -f /etc/systemd/system/autodialer.service
rm -f /etc/systemd/system/asterisk.service.d/limits.conf
rm -f /etc/nginx/sites-enabled/autodialer
rm -f /etc/nginx/sites-available/autodialer
rm -f /etc/logrotate.d/autodialer*
rm -f /etc/security/limits.d/99-autodialer.conf
rm -f /etc/sysctl.d/99-autodialer.conf
rm -f /usr/local/bin/autodialer-*

echo -e "${YELLOW}Очистка Redis...${NC}"
redis-cli FLUSHALL 2>/dev/null || true

systemctl daemon-reload
systemctl reload nginx 2>/dev/null || true

echo ""
echo -e "${GREEN}${BOLD}✅ AutoDialer Ultimate удалён${NC}"
echo ""
EOF
    chmod +x /opt/autodialer/uninstall.sh
    
    log_success "Скрипт удаления создан: /opt/autodialer/uninstall.sh"
}

# =============================================
# Создание скрипта бэкапа
# =============================================
create_backup_script() {
    log_step "Создание скрипта резервного копирования..."
    
    cat > /opt/autodialer/backup.sh << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - Скрипт резервного копирования

BACKUP_DIR="/opt/autodialer/backups/$(date +%Y%m%d_%H%M%S)"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

echo "Создание резервной копии..."

# База данных
echo "  • База данных..."
PGPASSWORD="${DB_PASSWORD}" pg_dump -h "${DB_HOST:-localhost}" -U "${DB_USER:-autodialer}" "${DB_NAME:-autodialer}" > "$BACKUP_DIR/database.sql"

# Конфигурация
echo "  • Конфигурация..."
cp /opt/autodialer/.env "$BACKUP_DIR/"
cp -r /etc/asterisk "$BACKUP_DIR/asterisk" 2>/dev/null || true
cp -r /etc/nginx/sites-available "$BACKUP_DIR/nginx" 2>/dev/null || true

# Записи звонков (опционально)
if [ "${BACKUP_RECORDINGS:-false}" = "true" ]; then
    echo "  • Записи звонков..."
    tar -czf "$BACKUP_DIR/recordings.tar.gz" -C /opt/autodialer recordings/ 2>/dev/null || true
fi

echo "Резервная копия создана: $BACKUP_DIR"

# Удаление старых бэкапов
echo "Очистка старых бэкапов (старше $RETENTION_DAYS дней)..."
find /opt/autodialer/backups -maxdepth 1 -type d -name "20*" -mtime +$RETENTION_DAYS -exec rm -rf {} \; 2>/dev/null || true

echo "Готово."
EOF
    chmod +x /opt/autodialer/backup.sh
    
    log_success "Скрипт резервного копирования создан: /opt/autodialer/backup.sh"
}

# =============================================
# Создание скрипта восстановления
# =============================================
create_restore_script() {
    log_step "Создание скрипта восстановления..."
    
    cat > /opt/autodialer/restore.sh << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - Скрипт восстановления

if [ -z "$1" ]; then
    echo "Использование: $0 <путь_к_бэкапу>"
    echo "Доступные бэкапы:"
    ls -d /opt/autodialer/backups/20* 2>/dev/null || echo "  Нет доступных бэкапов"
    exit 1
fi

BACKUP_PATH="$1"

if [ ! -d "$BACKUP_PATH" ]; then
    echo "Ошибка: директория $BACKUP_PATH не найдена"
    exit 1
fi

echo "Восстановление из $BACKUP_PATH..."

# Остановка сервисов
systemctl stop autodialer

# Восстановление базы данных
if [ -f "$BACKUP_PATH/database.sql" ]; then
    echo "Восстановление базы данных..."
    PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-autodialer}" -d "${DB_NAME:-autodialer}" < "$BACKUP_PATH/database.sql"
fi

# Восстановление конфигурации
if [ -f "$BACKUP_PATH/.env" ]; then
    cp "$BACKUP_PATH/.env" /opt/autodialer/.env
fi

# Запуск сервисов
systemctl start autodialer

echo "Восстановление завершено."
EOF
    chmod +x /opt/autodialer/restore.sh
    
    log_success "Скрипт восстановления создан: /opt/autodialer/restore.sh"
}

# =============================================
# Вывод финальной информации
# =============================================
print_final_info() {
    SERVER_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' | head -1)
    [ -z "$SERVER_IP" ] && SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$SERVER_IP" ] && SERVER_IP="127.0.0.1"
    
    echo ""
    echo "============================================================"
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║                                                          ║${NC}"
    echo -e "${GREEN}${BOLD}║         🎉 УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА! 🎉              ║${NC}"
    echo -e "${GREEN}${BOLD}║                                                          ║${NC}"
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
    echo "  • Метрики:        http://$SERVER_IP:${METRICS_PORT:-9090}/metrics"
    echo ""
    echo -e "${BOLD}🔐 Учётные данные:${NC}"
    echo "  • Веб-интерфейс:  ${ADMIN_USERNAME:-admin} / $(cat /opt/autodialer/.admin_credentials 2>/dev/null | grep "Password" | cut -d' ' -f2 || echo 'см. /opt/autodialer/.admin_credentials')"
    echo "  • AMI:            ${AMI_USER:-autodialer} / $AMI_PASSWORD"
    echo "  • База данных:    $DB_USER / $DB_PASSWORD"
    echo "  • Redis:          ${REDIS_PASSWORD:+с паролем}"
    echo "  • Метрики:        admin / $METRICS_PASS"
    echo ""
    echo -e "${YELLOW}${BOLD}⚠️  ВАЖНО: Смените пароль администратора после первого входа!${NC}"
    echo ""
    echo -e "${BOLD}📁 Важные файлы:${NC}"
    echo "  • Конфигурация:   /opt/autodialer/.env"
    echo "  • Учётные данные: /opt/autodialer/.admin_credentials"
    echo "  • Лог установки:  $INSTALL_LOG"
    echo "  • Бэкапы:         $BACKUP_DIR"
    echo ""
    echo -e "${BOLD}🛠️  Управление:${NC}"
    echo "  • Статус:         autodialer-status"
    echo "  • Статус всех:    autodialer-all-status"
    echo "  • Логи:           autodialer-logs"
    echo "  • Перезапуск:     autodialer-restart"
    echo "  • Консоль Asterisk: asterisk -rvvv"
    echo "  • Бэкап:          /opt/autodialer/backup.sh"
    echo "  • Восстановление: /opt/autodialer/restore.sh"
    echo "  • Удаление:       /opt/autodialer/uninstall.sh"
    echo ""
    echo -e "${BLUE}📚 Документация:${NC}"
    echo "  • GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate"
    echo ""
    echo "============================================================"
    echo -e "${GREEN}${BOLD}✅ AutoDialer Ultimate v3.0.0 готов к работе!${NC}"
    echo "============================================================"
}

# =============================================
# Основной процесс установки
# =============================================
main() {
    log_header "AutoDialer Ultimate v3.0.0 - Установка"
    log_info "GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate"
    log_info "Начало: $(date)"
    
    # Загрузка конфигурации
    load_env
    check_required_vars
    generate_secrets
    
    # Pre-flight проверки
    if [ "$SKIP_CHECKS" = false ]; then
        preflight_checks
    fi
    
    # Проверка идемпотентности
    check_already_installed
    
    # Создание бэкапов важных файлов
    backup_existing "/etc/asterisk"
    backup_existing "/etc/nginx/sites-available/autodialer"
    backup_existing "/opt/autodialer/.env"
    
    # Подготовка скриптов
    prepare_scripts
    
    # Сводка перед установкой
    log_header "Параметры установки"
    log_info "FreePBX IP:      $FREEPBX_IP"
    log_info "Extension:        $FREEPBX_EXTENSION"
    log_info "Макс. каналов:    $MAX_CALLS"
    log_info "CPS по умолчанию: $DEFAULT_CPS"
    log_info "Голос TTS:        $TTS_VOICE"
    log_info "Домен:            ${DOMAIN_NAME:-не настроен}"
    log_info "Рабочих процессов: $WORKERS"
    echo ""
    
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Начать установку? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Установка отменена"
            exit 0
        fi
    fi
    
    # =============================================
    # ЗАПУСК СКРИПТОВ УСТАНОВКИ
    # =============================================
    
    # 01. Системные зависимости
    run_script "01_system_setup.sh" "Настройка системы и установка зависимостей"
    
    # 02. Установка Asterisk
    run_script "02_asterisk_install.sh" "Установка Asterisk 21"
    
    # 03. Конфигурация Asterisk
    run_script "03_asterisk_config.sh" "Конфигурация Asterisk"
    
    # 04. Настройка PJSIP
    run_script "04_pjsip_config.sh" "Настройка PJSIP"
    
    # 05. Настройка Dialplan
    run_script "05_dialplan_config.sh" "Настройка Dialplan"
    
    # 06. Установка TTS (Piper)
    run_script "06_tts_install.sh" "Установка Piper TTS"
    
    # 07. Настройка PostgreSQL
    run_script "07_postgresql_setup.sh" "Настройка PostgreSQL"
    
    # 08. Настройка Redis
    run_script "08_redis_setup.sh" "Настройка Redis"
    
    # 09. Установка Python бэкенда
    run_script "09_python_backend.sh" "Установка Python бэкенда"
    
    # 10. Настройка Nginx
    run_script "10_nginx_setup.sh" "Настройка Nginx"
    
    # 11. Настройка файрвола
    run_script "11_firewall_setup.sh" "Настройка файрвола"
    
    # 12. Запуск сервисов
    run_script "12_start_services.sh" "Запуск всех сервисов"
    
    # 13. Настройка Fail2ban
    run_script "13_fail2ban_setup.sh" "Настройка Fail2ban"
    
    # 14. Настройка ротации логов
    run_script "14_logrotate_setup.sh" "Настройка Logrotate"
    
    # =============================================
    # ЗАВЕРШЕНИЕ
    # =============================================
    
    # Ожидание сервисов
    wait_for_all_services
    
    # Настройка HTTPS
    setup_https || true
    
    # Создание скриптов управления
    create_uninstall_script
    create_backup_script
    create_restore_script
    
    # Проверка установки
    verify_installation
    
    # Финальная информация
    print_final_info
    
    log_success "Установка завершена: $(date)"
}

# =============================================
# Запуск
# =============================================
main "$@"
