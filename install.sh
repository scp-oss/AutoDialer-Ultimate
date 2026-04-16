#!/bin/bash
# =============================================
# AutoDialer Ultimate - Главный установщик (Оркестратор)
# Версия: 3.0.0
# GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate
# =============================================
# Этот скрипт управляет порядком установки.
# Вся логика находится в отдельных скриптах в папке scripts/
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
SKIP_DEPS="${SKIP_DEPS:-false}"
SKIP_ASTERISK="${SKIP_ASTERISK:-false}"
SKIP_POSTGRES="${SKIP_POSTGRES:-false}"
SKIP_REDIS="${SKIP_REDIS:-false}"
SKIP_NGINX="${SKIP_NGINX:-false}"
SKIP_FIREWALL="${SKIP_FIREWALL:-false}"
SKIP_TTS="${SKIP_TTS:-false}"

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --yes|-y)
                NON_INTERACTIVE=true
                export NON_INTERACTIVE
                shift
                ;;
            --skip-checks)
                SKIP_CHECKS=true
                export SKIP_CHECKS
                shift
                ;;
            --skip-deps)
                SKIP_DEPS=true
                export SKIP_DEPS
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
            --help|-h)
                echo "Использование: $0 [опции]"
                echo ""
                echo "Опции:"
                echo "  --yes, -y           Неинтерактивный режим (не задавать вопросы)"
                echo "  --skip-checks       Пропустить pre-flight проверки"
                echo "  --skip-deps         Пропустить установку системных зависимостей"
                echo "  --skip-asterisk     Пропустить установку Asterisk"
                echo "  --skip-postgres     Пропустить настройку PostgreSQL"
                echo "  --skip-redis        Пропустить настройку Redis"
                echo "  --skip-nginx        Пропустить настройку Nginx"
                echo "  --skip-firewall     Пропустить настройку файрвола"
                echo "  --skip-tts          Пропустить установку TTS"
                echo "  --help, -h          Показать эту справку"
                echo ""
                echo "Примеры:"
                echo "  sudo ./install.sh --yes"
                echo "  sudo ./install.sh --skip-firewall --skip-tts"
                exit 0
                ;;
            *)
                log_error "Неизвестная опция: $1"
                exit 1
                ;;
        esac
    done
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
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        if [ -f "$SCRIPT_DIR/.env.example" ]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            log_warn "Создан .env из примера. Отредактируйте его перед продолжением."
            log_info "Редактировать: nano $SCRIPT_DIR/.env"
            exit 1
        else
            log_error "Файл .env не найден и .env.example отсутствует"
            exit 1
        fi
    fi
    
    # Безопасная загрузка .env (без source)
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
        export "$key=$value"
    done < "$SCRIPT_DIR/.env"
    
    # Установка значений по умолчанию
    export FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
    export MAX_CALLS="${MAX_CALLS:-50}"
    export DEFAULT_CPS="${DEFAULT_CPS:-5}"
    export CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
    export MAX_RETRIES="${MAX_RETRIES:-3}"
    export TTS_VOICE="${TTS_VOICE:-denis}"
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"
    export DOMAIN_NAME="${DOMAIN_NAME:-}"
    export TRUSTED_PROXIES="${TRUSTED_PROXIES:-10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1}"
    
    log_success "Конфигурация загружена"
    log_info "  FreePBX IP:      ${FREEPBX_IP:-НЕ ЗАДАН!}"
    log_info "  Extension:        $FREEPBX_EXTENSION"
}

# =============================================
# Проверка обязательных переменных
# =============================================
check_required_vars() {
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
}

# =============================================
# Генерация секретов
# =============================================
generate_secrets() {
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
    
    if [ -z "${METRICS_PASS:-}" ]; then
        METRICS_PASS=$(openssl rand -hex 8 2>/dev/null || echo "metrics_$(date +%s)")
        echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/.env"
        export METRICS_PASS
        secrets_updated=true
        log_info "Сгенерирован METRICS_PASS"
    fi
    
    if [ "$secrets_updated" = true ]; then
        log_success "Секреты сгенерированы и сохранены в .env"
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
        log_error "Требуется минимум 4GB RAM. Обнаружено: ${TOTAL_RAM}MB"
        exit 1
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
    
    # Проверка портов
    log_info "Проверка портов..."
    for port in 80 443 5432 6379 5038 8000; do
        if ss -tln 2>/dev/null | grep -q ":$port "; then
            log_warn "  Порт $port занят"
        else
            log_info "  Порт $port свободен"
        fi
    done
    
    # Проверка Git
    if command -v git &>/dev/null; then
        log_success "Git установлен: $(git --version | head -1)"
    else
        log_info "Git не установлен (будет установлен)"
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
    if [ -f "$INSTALLED_MARKER" ]; then
        log_warn "AutoDialer уже установлен (найден $INSTALLED_MARKER)"
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Переустановить? Существующие данные могут быть потеряны. [y/N] " -n 1 -r
            echo
            [[ ! $REPLY =~ ^[Yy]$ ]] && exit 0
        fi
        log_warn "Продолжение установки..."
        rm -f "$INSTALLED_MARKER"
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
# Запуск одного скрипта
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
    
    local is_crit="false"
    if is_critical "$script"; then
        is_crit="true"
    fi
    
    log_header "Выполнение: $description"
    
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
            [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
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
    
    wait_for_service "postgresql" "127.0.0.1" "5432" 30 "PostgreSQL" || true
    wait_for_service "redis" "127.0.0.1" "6379" 30 "Redis" || true
    wait_for_service "asterisk-ami" "127.0.0.1" "5038" 30 "Asterisk AMI" || true
    wait_for_service "nginx" "127.0.0.1" "80" 30 "Nginx" || true
    
    log_info "Ожидание бэкенда..."
    for i in $(seq 1 30); do
        if curl -s http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "ok"; then
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
    
    # Проверка сервисов
    SERVICES=("postgresql" "redis-server" "asterisk" "autodialer" "nginx")
    for svc in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            log_success "$svc работает"
        else
            log_warn "$svc не запущен"
            all_ok=false
        fi
    done
    
    # Проверка API
    if curl -s http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "ok"; then
        log_success "API отвечает"
    else
        log_warn "API не отвечает"
        all_ok=false
    fi
    
    # Проверка Asterisk
    if asterisk -rx "core show version" &>/dev/null; then
        log_success "Asterisk отвечает"
    else
        log_warn "Asterisk не отвечает"
        all_ok=false
    fi
    
    # Проверка Redis
    if redis-cli ping &>/dev/null; then
        log_success "Redis отвечает"
    else
        log_warn "Redis не отвечает"
        all_ok=false
    fi
    
    if [ "$all_ok" = true ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$INSTALLED_MARKER"
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
        certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --email "admin@$DOMAIN_NAME" 2>/dev/null || {
            log_warn "Не удалось получить сертификат для $DOMAIN_NAME"
            return 1
        }
    else
        certbot --nginx -d "$DOMAIN_NAME"
    fi
    
    if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
        log_success "HTTPS настроен для $DOMAIN_NAME"
        return 0
    else
        log_warn "Сертификат не получен"
        return 1
    fi
}

# =============================================
# Создание скрипта удаления
# =============================================
create_uninstall_script() {
    cat > /opt/autodialer/uninstall.sh << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - Скрипт удаления

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${RED}⚠ ВНИМАНИЕ: Это полностью удалит AutoDialer Ultimate!${NC}"
echo "Будут удалены:"
echo "  - Все файлы в /opt/autodialer"
echo "  - База данных autodialer"
echo "  - Системные сервисы"
echo ""

read -p "Вы уверены? Введите 'yes' для подтверждения: " -r
if [ "$REPLY" != "yes" ]; then
    echo "Отмена."
    exit 0
fi

echo "Остановка сервисов..."
systemctl stop autodialer 2>/dev/null || true
systemctl disable autodialer 2>/dev/null || true

echo "Удаление базы данных..."
sudo -u postgres psql -c "DROP DATABASE IF EXISTS autodialer;" 2>/dev/null || true
sudo -u postgres psql -c "DROP USER IF EXISTS autodialer;" 2>/dev/null || true

echo "Удаление файлов..."
rm -rf /opt/autodialer
rm -f /etc/systemd/system/autodialer.service
rm -f /etc/nginx/sites-enabled/autodialer
rm -f /etc/nginx/sites-available/autodialer
rm -f /etc/logrotate.d/autodialer

echo "Очистка Redis..."
redis-cli FLUSHALL 2>/dev/null || true

systemctl daemon-reload

echo -e "${GREEN}✓ AutoDialer Ultimate удалён${NC}"
EOF
    chmod +x /opt/autodialer/uninstall.sh
    log_success "Создан скрипт удаления: /opt/autodialer/uninstall.sh"
}

# =============================================
# Основной процесс установки
# =============================================
main() {
    log_header "AutoDialer Ultimate v3.0.0 - Установка"
    log_info "GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate"
    log_info "Начало: $(date)"
    echo ""
    
    # Загрузка и проверка конфигурации
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
    echo ""
    
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Начать установку? [y/N] " -n 1 -r
        echo
        [[ ! $REPLY =~ ^[Yy]$ ]] && exit 0
    fi
    
    # =============================================
    # ЗАПУСК СКРИПТОВ УСТАНОВКИ
    # =============================================
    
    # 01. Системные зависимости и лимиты
    if [ "$SKIP_DEPS" = false ]; then
        run_script "01_system_setup.sh" "Настройка системы и установка зависимостей"
    fi
    
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
    
    # Создание скрипта удаления
    create_uninstall_script
    
    # Проверка установки
    verify_installation
    
    SERVER_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' | head -1)
    [ -z "$SERVER_IP" ] && SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$SERVER_IP" ] && SERVER_IP="127.0.0.1"
    
    log_header "УСТАНОВКА ЗАВЕРШЕНА!"
    echo ""
    log_info "Веб-интерфейс:  http://$SERVER_IP/"
    if [ -n "${DOMAIN_NAME:-}" ]; then
        log_info "Домен:          https://$DOMAIN_NAME/"
    fi
    log_info "API документация: http://$SERVER_IP/docs"
    log_info "Проверка здоровья: http://$SERVER_IP/api/health"
    log_info "Метрики:         http://$SERVER_IP/metrics"
    echo ""
    log_info "Учётные данные по умолчанию:"
    echo "  Веб-интерфейс: admin / admin"
    echo "  AMI:           autodialer / $AMI_PASSWORD"
    echo "  База данных:   $DB_USER / $DB_PASSWORD"
    echo "  Метрики:       admin / $METRICS_PASS"
    echo ""
    log_warn "ВАЖНО: Смените пароль администратора после первого входа!"
    echo ""
    log_info "Сгенерированные пароли сохранены в .env"
    log_info "Лог установки: $INSTALL_LOG"
    log_info "Бэкапы:        $BACKUP_DIR"
    echo ""
    log_info "Полезные команды:"
    echo "  autodialer-status       - Статус бэкенда"
    echo "  autodialer-all-status   - Статус всех сервисов"
    echo "  asterisk -rvvv          - Консоль Asterisk"
    echo "  /opt/autodialer/uninstall.sh - Удаление системы"
    echo ""
    log_info "GitHub: https://github.com/naumenis-code/AutoDialer-Ultimate"
    log_success "=============================================="
}

# =============================================
# Запуск
# =============================================
main "$@"
