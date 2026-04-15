#!/bin/bash
# =============================================
# AutoDialer Ultimate - Главный установщик
# Версия: 3.0.0
# =============================================
# Исправления:
# - Fail-fast на критических ошибках
# - Pre-flight проверки (ОС, RAM, порты)
# - Ожидание сервисов (wait-for)
# - Идемпотентность
# - Логирование всей установки
# - Неинтерактивный режим
# - Безопасная загрузка .env
# - Trap для отката
# =============================================

set -euo pipefail  # Строгий режим: ошибка = выход, незаданные переменные = ошибка

# =============================================
# Конфигурация
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LOG="/var/log/autodialer-install.log"
INSTALLED_MARKER="/opt/autodialer/.installed"
NON_INTERACTIVE=false
SKIP_CHECKS=false

# Критические скрипты (падение любого = остановка установки)
CRITICAL_SCRIPTS=(
    "01_system_setup.sh"
    "02_asterisk_install.sh"
    "07_postgresql_setup.sh"
    "08_redis_setup.sh"
    "09_python_backend.sh"
)

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
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$INSTALL_LOG"
}

log_info() { log "INFO" "$@"; }
log_success() { echo -e "${GREEN}✓${NC} $*" | tee -a "$INSTALL_LOG"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $*" | tee -a "$INSTALL_LOG"; }
log_error() { echo -e "${RED}✗${NC} $*" | tee -a "$INSTALL_LOG"; }
log_step() { echo -e "\n${BOLD}${BLUE}▶${NC} ${BOLD}$*${NC}" | tee -a "$INSTALL_LOG"; }
log_header() {
    echo -e "\n${BOLD}${BLUE}========================================${NC}" | tee -a "$INSTALL_LOG"
    echo -e "${BOLD}${BLUE}$*${NC}" | tee -a "$INSTALL_LOG"
    echo -e "${BOLD}${BLUE}========================================${NC}" | tee -a "$INSTALL_LOG"
}

# =============================================
# Обработка ошибок и trap
# =============================================
cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Установка прервана с кодом $exit_code"
        log_error "Проверьте лог: $INSTALL_LOG"
        log_info "Для отката изменений выполните: $SCRIPT_DIR/uninstall.sh"
    fi
    exit $exit_code
}

trap cleanup_on_error EXIT

# =============================================
# Обработка аргументов командной строки
# =============================================
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --yes|-y)
                NON_INTERACTIVE=true
                shift
                ;;
            --skip-checks)
                SKIP_CHECKS=true
                shift
                ;;
            --help|-h)
                echo "Использование: $0 [опции]"
                echo ""
                echo "Опции:"
                echo "  --yes, -y        Неинтерактивный режим (не задавать вопросы)"
                echo "  --skip-checks    Пропустить pre-flight проверки"
                echo "  --help, -h       Показать эту справку"
                exit 0
                ;;
            *)
                log_error "Неизвестная опция: $1"
                exit 1
                ;;
        esac
    done
}

# =============================================
# Pre-flight проверки
# =============================================
preflight_checks() {
    log_step "Pre-flight проверки..."
    
    # Проверка ОС
    if [ ! -f /etc/os-release ]; then
        log_error "Не удалось определить ОС"
        exit 1
    fi
    source /etc/os-release
    if [[ "$ID" != "debian" ]] && [[ "$ID_LIKE" != *"debian"* ]]; then
        log_error "Требуется Debian 12. Обнаружено: $PRETTY_NAME"
        exit 1
    fi
    if [[ "$VERSION_ID" != "12" ]]; then
        log_warn "Рекомендуется Debian 12. Обнаружено: $VERSION_ID"
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Продолжить? [y/N] " -n 1 -r
            echo
            [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
        fi
    fi
    log_success "ОС: $PRETTY_NAME"
    
    # Проверка архитектуры
    ARCH=$(uname -m)
    if [[ "$ARCH" != "x86_64" ]]; then
        log_error "Требуется x86_64 архитектура. Обнаружено: $ARCH"
        exit 1
    fi
    log_success "Архитектура: $ARCH"
    
    # Проверка RAM
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM" -lt 3500 ]; then
        log_error "Требуется минимум 4GB RAM. Обнаружено: ${TOTAL_RAM}MB"
        exit 1
    fi
    log_success "RAM: ${TOTAL_RAM}MB"
    
    # Проверка свободного места
    FREE_DISK=$(df -BG /opt 2>/dev/null | awk 'NR==2 {print $4}' | sed 's/G//' || echo "0")
    if [ "${FREE_DISK:-0}" -lt 20 ]; then
        log_error "Требуется минимум 20GB свободного места в /opt. Обнаружено: ${FREE_DISK}GB"
        exit 1
    fi
    log_success "Свободное место в /opt: ${FREE_DISK}GB"
    
    # Проверка портов
    log_info "Проверка портов..."
    PORTS=("80" "443" "5038" "5432" "6379" "8000")
    for port in "${PORTS[@]}"; do
        if ss -tuln | grep -q ":$port "; then
            log_warn "Порт $port уже занят"
        else
            log_info "  Порт $port свободен"
        fi
    done
    
    # Проверка прав root
    if [ "$EUID" -ne 0 ]; then
        log_error "Установка требует прав root. Используйте: sudo $0"
        exit 1
    fi
    
    log_success "Pre-flight проверки завершены"
}

# =============================================
# Безопасная загрузка .env
# =============================================
load_env_safe() {
    log_step "Загрузка конфигурации..."
    
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        if [ -f "$SCRIPT_DIR/.env.example" ]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            log_warn "Создан .env из примера. Отредактируйте его перед продолжением."
        else
            log_error "Файл .env не найден"
            exit 1
        fi
    fi
    
    # Безопасная загрузка: читаем построчно, игнорируем комментарии и пустые строки
    while IFS='=' read -r key value; do
        # Пропускаем комментарии и пустые строки
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        
        # Удаляем пробелы и кавычки
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
        
        # Безопасно экспортируем
        export "$key=$value"
    done < "$SCRIPT_DIR/.env"
    
    # Проверка обязательных переменных
    REQUIRED_VARS=("FREEPBX_IP" "EXTENSION_PASSWORD")
    MISSING_VARS=()
    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var:-}" ]; then
            MISSING_VARS+=("$var")
        fi
    done
    
    if [ ${#MISSING_VARS[@]} -gt 0 ]; then
        log_error "Отсутствуют обязательные переменные в .env:"
        for var in "${MISSING_VARS[@]}"; do
            echo "  - $var"
        done
        exit 1
    fi
    
    # Установка значений по умолчанию
    export FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
    export MAX_CALLS="${MAX_CALLS:-50}"
    export DEFAULT_CPS="${DEFAULT_CPS:-5}"
    export TTS_VOICE="${TTS_VOICE:-denis}"
    export DB_NAME="${DB_NAME:-autodialer}"
    export DB_USER="${DB_USER:-autodialer}"
    
    log_success "Конфигурация загружена"
    log_info "  FREEPBX_IP: $FREEPBX_IP"
    log_info "  FREEPBX_EXTENSION: $FREEPBX_EXTENSION"
}

# =============================================
# Генерация секретов
# =============================================
generate_secrets() {
    log_step "Генерация секретов..."
    
    SECRETS_UPDATED=false
    
    if [ -z "${DB_PASSWORD:-}" ]; then
        DB_PASSWORD=$(openssl rand -hex 16)
        echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/.env"
        export DB_PASSWORD
        SECRETS_UPDATED=true
        log_info "Сгенерирован DB_PASSWORD"
    fi
    
    if [ -z "${JWT_SECRET:-}" ]; then
        JWT_SECRET=$(openssl rand -hex 32)
        echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/.env"
        export JWT_SECRET
        SECRETS_UPDATED=true
        log_info "Сгенерирован JWT_SECRET"
    fi
    
    if [ -z "${AMI_PASSWORD:-}" ]; then
        AMI_PASSWORD=$(openssl rand -hex 16)
        echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/.env"
        export AMI_PASSWORD
        SECRETS_UPDATED=true
        log_info "Сгенерирован AMI_PASSWORD"
    fi
    
    if [ -z "${METRICS_PASS:-}" ]; then
        METRICS_PASS=$(openssl rand -hex 8)
        echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/.env"
        export METRICS_PASS
        SECRETS_UPDATED=true
        log_info "Сгенерирован METRICS_PASS"
    fi
    
    if [ "$SECRETS_UPDATED" = true ]; then
        log_success "Секреты сгенерированы"
    else
        log_info "Секреты уже заданы"
    fi
}

# =============================================
# Проверка идемпотентности
# =============================================
check_already_installed() {
    if [ -f "$INSTALLED_MARKER" ]; then
        log_warn "AutoDialer уже установлен (найден $INSTALLED_MARKER)"
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Переустановить? Существующие данные могут быть потеряны. [y/N] " -n 1 -r
            echo
            [[ ! $REPLY =~ ^[Yy]$ ]] && exit 0
        fi
        log_warn "Продолжение установки..."
    fi
}

# =============================================
# Ожидание сервиса
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
    
    log_error "$description не ответил за $((max_attempts * 2)) секунд"
    return 1
}

# =============================================
# Проверка критичности скрипта
# =============================================
is_critical_script() {
    local script="$1"
    for critical in "${CRITICAL_SCRIPTS[@]}"; do
        if [[ "$script" == "$critical" ]]; then
            return 0
        fi
    done
    return 1
}

# =============================================
# Запуск скриптов установки
# =============================================
run_installation_scripts() {
    log_step "Запуск скриптов установки..."
    
    local SCRIPTS=(
        "01_system_setup.sh:Настройка системы и установка зависимостей"
        "02_asterisk_install.sh:Установка Asterisk"
        "03_asterisk_config.sh:Конфигурация Asterisk"
        "04_pjsip_config.sh:Настройка PJSIP"
        "05_dialplan_config.sh:Настройка диалплана"
        "06_tts_install.sh:Установка TTS (Piper)"
        "07_postgresql_setup.sh:Настройка PostgreSQL"
        "08_redis_setup.sh:Настройка Redis"
        "09_python_backend.sh:Установка Python бэкенда"
        "10_nginx_setup.sh:Настройка Nginx"
        "11_firewall_setup.sh:Настройка файрвола"
        "12_start_services.sh:Запуск сервисов"
        "13_fail2ban_setup.sh:Настройка Fail2ban"
        "14_logrotate_setup.sh:Настройка ротации логов"
    )
    
    local FAILED_SCRIPTS=()
    local CRITICAL_FAILED=false
    
    for script_info in "${SCRIPTS[@]}"; do
        local script="${script_info%%:*}"
        local description="${script_info##*:}"
        local script_path="$SCRIPT_DIR/scripts/$script"
        
        log_header "Выполнение: $description"
        
        if [ ! -f "$script_path" ]; then
            log_warn "$script не найден, пропускаю"
            continue
        fi
        
        if bash "$script_path" 2>&1 | tee -a "$INSTALL_LOG"; then
            log_success "$script выполнен успешно"
        else
            local exit_code=$?
            log_error "$script завершился с ошибкой (код $exit_code)"
            FAILED_SCRIPTS+=("$script")
            
            if is_critical_script "$script"; then
                CRITICAL_FAILED=true
                log_error "КРИТИЧЕСКАЯ ОШИБКА: $script не выполнен"
                break
            fi
            
            if [ "$NON_INTERACTIVE" = false ]; then
                read -p "Продолжить установку? [y/N] " -n 1 -r
                echo
                [[ ! $REPLY =~ ^[Yy]$ ]] && break
            fi
        fi
    done
    
    if [ "$CRITICAL_FAILED" = true ]; then
        log_error "Установка прервана из-за критической ошибки"
        return 1
    fi
    
    if [ ${#FAILED_SCRIPTS[@]} -gt 0 ]; then
        log_warn "Некоторые скрипты завершились с ошибками:"
        for script in "${FAILED_SCRIPTS[@]}"; do
            echo "  - $script"
        done
    fi
    
    return 0
}

# =============================================
# Ожидание всех сервисов
# =============================================
wait_for_all_services() {
    log_step "Ожидание готовности сервисов..."
    
    wait_for_service "postgresql" "127.0.0.1" "5432" 30 "PostgreSQL" || log_warn "PostgreSQL не отвечает"
    wait_for_service "redis" "127.0.0.1" "6379" 30 "Redis" || log_warn "Redis не отвечает"
    wait_for_service "asterisk-ami" "127.0.0.1" "5038" 30 "Asterisk AMI" || log_warn "Asterisk AMI не отвечает"
    wait_for_service "nginx" "127.0.0.1" "80" 30 "Nginx" || log_warn "Nginx не отвечает"
    
    # Ждём бэкенд
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
    
    local ALL_OK=true
    
    # Проверка сервисов
    SERVICES=("postgresql" "redis-server" "asterisk" "autodialer" "nginx")
    for svc in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            log_success "$svc работает"
        else
            log_warn "$svc не запущен"
            ALL_OK=false
        fi
    done
    
    # Проверка API
    if curl -s http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "ok"; then
        log_success "API отвечает"
    else
        log_warn "API не отвечает"
        ALL_OK=false
    fi
    
    if [ "$ALL_OK" = true ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$INSTALLED_MARKER"
        log_success "Установка успешно завершена!"
    else
        log_warn "Установка завершена с предупреждениями"
    fi
}

# =============================================
# Показ итоговой информации
# =============================================
show_summary() {
    local SERVER_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' | head -1)
    [ -z "$SERVER_IP" ] && SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    
    log_header "Установка завершена!"
    echo ""
    log_info "Веб-интерфейс:  http://$SERVER_IP/"
    log_info "Документация API: http://$SERVER_IP/docs"
    log_info "Проверка здоровья: http://$SERVER_IP/api/health"
    log_info "Метрики:          http://$SERVER_IP/metrics"
    echo ""
    log_info "Учётные данные по умолчанию:"
    echo "  Логин:    admin"
    echo "  Пароль:   admin"
    echo ""
    log_info "Сгенерированные пароли сохранены в .env"
    echo ""
    log_warn "ВАЖНО: Смените пароль администратора после первого входа!"
    echo ""
    log_info "Лог установки: $INSTALL_LOG"
    log_info "Для проверки статуса: autodialer-all-status"
}

# =============================================
# Главная функция
# =============================================
main() {
    parse_args "$@"
    
    # Настройка логирования
    mkdir -p "$(dirname "$INSTALL_LOG")"
    exec > >(tee -a "$INSTALL_LOG") 2>&1
    
    log_header "AutoDialer Ultimate v3.0.0 - Установка"
    log_info "Начало установки: $(date)"
    log_info "Режим: $([ "$NON_INTERACTIVE" = true ] && echo "неинтерактивный" || echo "интерактивный")"
    
    # Pre-flight проверки
    if [ "$SKIP_CHECKS" = false ]; then
        preflight_checks
    fi
    
    # Проверка идемпотентности
    check_already_installed
    
    # Загрузка конфигурации
    load_env_safe
    
    # Генерация секретов
    generate_secrets
    
    # Подтверждение установки
    log_header "Параметры установки"
    log_info "FreePBX IP:      $FREEPBX_IP"
    log_info "Extension:        $FREEPBX_EXTENSION"
    log_info "Макс. каналов:    $MAX_CALLS"
    log_info "CPS по умолчанию: $DEFAULT_CPS"
    log_info "Голос TTS:        $TTS_VOICE"
    echo ""
    
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Начать установку? [y/N] " -n 1 -r
        echo
        [[ ! $REPLY =~ ^[Yy]$ ]] && exit 0
    fi
    
    # Делаем скрипты исполняемыми
    chmod +x "$SCRIPT_DIR/scripts/"*.sh 2>/dev/null || true
    
    # Запуск установки
    if ! run_installation_scripts; then
        log_error "Установка прервана"
        exit 1
    fi
    
    # Ожидание сервисов
    wait_for_all_services
    
    # Проверка установки
    verify_installation
    
    # Показ итогов
    show_summary
    
    log_info "Установка завершена: $(date)"
}

# =============================================
# Запуск
# =============================================
main "$@"
