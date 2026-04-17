#!/bin/bash
# =============================================
# AutoDialer Ultimate - System Setup
# Version: 3.0.2 (ENTERPRISE)
# Description: Настройка системы и установка зависимостей
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
INSTALLED_MARKER="/opt/autodialer/.system_setup_done"

check_already_installed() {
    if [ -f "$INSTALLED_MARKER" ] && [ "${FORCE_REINSTALL:-false}" != "true" ]; then
        log_warn "Системные зависимости уже установлены (найден $INSTALLED_MARKER)"
        log_info "Для принудительной переустановки удалите маркер: rm -f $INSTALLED_MARKER"
        exit 0
    fi
}

# =============================================
# Проверка ОС
# =============================================
check_os() {
    log_step "Проверка операционной системы..."
    
    if [ ! -f /etc/os-release ]; then
        log_error "Не удалось определить ОС"
        exit 1
    fi
    
    source /etc/os-release
    
    if [[ "$ID" = "debian" ]] || [[ "$ID_LIKE" = *"debian"* ]]; then
        log_success "ОС: $PRETTY_NAME"
        
        if [[ "$VERSION_ID" != "12" ]]; then
            log_warn "Рекомендуется Debian 12. Обнаружена версия: $VERSION_ID"
            log_warn "Установка может работать некорректно"
        fi
    else
        log_error "Требуется Debian или Ubuntu. Обнаружено: $ID"
        exit 1
    fi
}

# =============================================
# Проверка ресурсов
# =============================================
check_resources() {
    log_step "Проверка системных ресурсов..."
    
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM" -ge 3500 ]; then
        log_success "RAM: ${TOTAL_RAM}MB"
    else
        log_warn "Рекомендуется минимум 4GB RAM. Обнаружено: ${TOTAL_RAM}MB"
        log_warn "Производительность может быть снижена"
    fi
    
    CPU_CORES=$(nproc)
    if [ "$CPU_CORES" -ge 2 ]; then
        log_success "CPU ядер: $CPU_CORES"
    else
        log_warn "Рекомендуется минимум 2 ядра CPU. Обнаружено: $CPU_CORES"
    fi
    
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
}

# =============================================
# 🔥 НАДЁЖНЫЙ APT С ПОВТОРНЫМИ ПОПЫТКАМИ
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
            
            if [ -s /tmp/apt-error.log ]; then
                tail -5 /tmp/apt-error.log
            fi
            
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
        if apt-get install -y -qq $packages 2>/tmp/apt-install-error.log; then
            return 0
        fi
        
        log_warn "apt install не удался (попытка $i/$max_attempts)"
        
        if [ $i -lt $max_attempts ]; then
            sleep 5
            apt_update_with_retry || true
        fi
    done
    
    log_error "Не удалось установить: $packages"
    tail -20 /tmp/apt-install-error.log
    return 1
}

# =============================================
# Обновление системы
# =============================================
update_system() {
    log_step "Обновление системных пакетов..."
    
    apt_update_with_retry
    
    log_info "Обновление установленных пакетов..."
    apt-get upgrade -y -qq
    
    log_success "Система обновлена"
}

# =============================================
# Установка базовых утилит
# =============================================
install_base_utils() {
    log_step "Установка базовых утилит..."
    
    local packages=(
        curl wget git
        ca-certificates gnupg lsb-release
        software-properties-common
        unzip zip
        net-tools iproute2
        dnsutils
        jq
        vim nano
        htop iotop
    )
    
    apt_install_with_retry "${packages[*]}"
    log_success "Базовые утилиты установлены"
}

# =============================================
# Установка инструментов сборки
# =============================================
install_build_tools() {
    log_step "Установка инструментов сборки..."
    
    local packages=(
        build-essential
        gcc g++ make
        cmake pkg-config
        automake autoconf libtool
        patch
    )
    
    apt_install_with_retry "${packages[*]}"
    log_success "Инструменты сборки установлены"
}

# =============================================
# Установка Python и зависимостей
# =============================================
install_python_deps() {
    log_step "Установка Python и зависимостей..."
    
    local packages=(
        python3
        python3-pip
        python3-venv
        python3-dev
        python3-setuptools
        python3-wheel
        libpq-dev
        libffi-dev
        libssl-dev
        libxml2-dev
        libxslt1-dev
        libjpeg-dev
        zlib1g-dev
    )
    
    apt_install_with_retry "${packages[*]}"
    
    log_info "Обновление pip..."
    python3 -m pip install --upgrade pip setuptools wheel -q 2>/dev/null || true
    
    log_success "Python и зависимости установлены"
}

# =============================================
# Установка аудио зависимостей
# =============================================
install_audio_deps() {
    log_step "Установка аудио зависимостей..."
    
    local packages=(
        ffmpeg
        sox
        libsox-fmt-all
        alsa-utils
        pulseaudio-utils
        libsndfile1
        libsndfile1-dev
    )
    
    apt_install_with_retry "${packages[*]}"
    
    if command -v ffmpeg &>/dev/null; then
        log_success "ffmpeg установлен: $(ffmpeg -version 2>/dev/null | head -1)"
    else
        log_warn "ffmpeg не установлен (TTS может не работать)"
    fi
    
    log_success "Аудио зависимости установлены"
}

# =============================================
# Установка клиентов БД
# =============================================
install_db_clients() {
    log_step "Установка клиентов баз данных..."
    
    apt_install_with_retry "postgresql-client redis-tools"
    
    log_success "Клиенты БД установлены"
}

# =============================================
# Установка Nginx
# =============================================
install_nginx() {
    log_step "Установка Nginx..."
    
    if command -v nginx &>/dev/null; then
        log_info "Nginx уже установлен: $(nginx -v 2>&1)"
    else
        apt_install_with_retry "nginx"
        log_success "Nginx установлен"
    fi
    
    mkdir -p /var/log/nginx
    chown -R www-data:www-data /var/log/nginx
}

# =============================================
# Установка Certbot (опционально)
# =============================================
install_certbot() {
    if [ -z "${DOMAIN_NAME:-}" ]; then
        log_info "Домен не указан, пропуск установки Certbot"
        return 0
    fi
    
    log_step "Установка Certbot для SSL..."
    
    if command -v certbot &>/dev/null; then
        log_info "Certbot уже установлен"
    else
        apt_install_with_retry "certbot python3-certbot-nginx"
        log_success "Certbot установлен"
    fi
}

# =============================================
// ... продолжение ...

# =============================================
# Создание пользователя autodialer
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
    
    log_success "Группы настроены"
}

# =============================================
# Настройка системных лимитов
# =============================================
setup_limits() {
    log_step "Настройка системных лимитов..."
    
    cat > /etc/security/limits.d/99-autodialer.conf << 'EOF'
# AutoDialer Ultimate - System Limits
autodialer soft nofile 65536
autodialer hard nofile 65536
autodialer soft nproc 32768
autodialer hard nproc 32768
autodialer soft memlock unlimited
autodialer hard memlock unlimited

root soft nofile 65536
root hard nofile 65536
EOF

    cat > /etc/sysctl.d/99-autodialer.conf << 'EOF'
# AutoDialer Ultimate - Network Optimizations
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 5

vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.overcommit_memory = 1

fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
EOF

    sysctl -p /etc/sysctl.d/99-autodialer.conf 2>/dev/null || true
    
    log_success "Системные лимиты настроены"
}

# =============================================
# Создание рабочих директорий
# =============================================
create_directories() {
    log_step "Создание рабочих директорий..."
    
    mkdir -p /opt/autodialer
    mkdir -p /opt/autodialer/{logs,backups,uploads,recordings,scripts}
    mkdir -p /opt/autodialer/logs/{nginx,backend,asterisk,celery}
    mkdir -p /opt/autodialer/backups/{db,recordings,config}
    mkdir -p /var/log/autodialer
    
    mkdir -p /var/spool/asterisk/monitor
    mkdir -p /var/lib/asterisk/sounds/tts
    
    chown -R autodialer:autodialer /opt/autodialer
    chown -R autodialer:autodialer /var/log/autodialer
    chmod 755 /opt/autodialer
    chmod 755 /opt/autodialer/{logs,backups,uploads,recordings}
    
    log_success "Рабочие директории созданы"
}

# =============================================
# Настройка swap (если мало RAM)
# =============================================
setup_swap() {
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    
    if [ "$TOTAL_RAM" -ge 4096 ]; then
        log_info "Достаточно RAM (${TOTAL_RAM}MB), swap не требуется"
        return 0
    fi
    
    log_step "Настройка swap файла..."
    
    if [ -f /swapfile ]; then
        log_info "Swap файл уже существует"
        return 0
    fi
    
    log_warn "Мало RAM (${TOTAL_RAM}MB), создаю swap файл 2GB..."
    
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 2>/dev/null
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    
    if ! grep -q "/swapfile" /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    
    echo 10 > /proc/sys/vm/swappiness
    
    log_success "Swap файл создан и активирован"
}

# =============================================
# Настройка timezone
# =============================================
setup_timezone() {
    log_step "Настройка временной зоны..."
    
    if [ -n "${TIMEZONE:-}" ]; then
        if [ -f "/usr/share/zoneinfo/$TIMEZONE" ]; then
            ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
            echo "$TIMEZONE" > /etc/timezone
            log_success "Временная зона установлена: $TIMEZONE"
        else
            log_warn "Временная зона $TIMEZONE не найдена, используется UTC"
            ln -sf /usr/share/zoneinfo/UTC /etc/localtime
            echo "UTC" > /etc/timezone
        fi
    else
        log_info "Временная зона не указана, используется UTC"
        ln -sf /usr/share/zoneinfo/UTC /etc/localtime 2>/dev/null || true
        echo "UTC" > /etc/timezone 2>/dev/null || true
    fi
    
    if command -v timedatectl &>/dev/null; then
        timedatectl set-ntp true 2>/dev/null || true
    fi
}

# =============================================
# Установка дополнительных инструментов
# =============================================
install_extra_tools() {
    log_step "Установка дополнительных инструментов..."
    
    local packages=(
        tmux screen
        tree
        ncdu
        ripgrep
        fd-find
        silversearcher-ag
    )
    
    for pkg in "${packages[@]}"; do
        apt-get install -y -qq "$pkg" 2>/dev/null || true
    done
    
    log_success "Дополнительные инструменты установлены"
}

# =============================================
# Проверка установки
# =============================================
verify_installation() {
    log_step "Проверка установки..."
    
    local all_ok=true
    
    if python3 --version &>/dev/null; then
        log_success "Python: $(python3 --version)"
    else
        log_error "Python не установлен"
        all_ok=false
    fi
    
    if python3 -m pip --version &>/dev/null; then
        log_success "pip: $(python3 -m pip --version)"
    else
        log_error "pip не установлен"
        all_ok=false
    fi
    
    if command -v ffmpeg &>/dev/null; then
        log_success "ffmpeg установлен"
    else
        log_warn "ffmpeg не установлен (TTS может не работать)"
    fi
    
    if command -v nginx &>/dev/null; then
        log_success "Nginx: $(nginx -v 2>&1)"
    else
        log_warn "Nginx не установлен"
    fi
    
    if command -v redis-cli &>/dev/null; then
        log_success "Redis клиент установлен"
    else
        log_warn "Redis клиент не установлен"
    fi
    
    if command -v psql &>/dev/null; then
        log_success "PostgreSQL клиент: $(psql --version | head -1)"
    else
        log_warn "PostgreSQL клиент не установлен"
    fi
    
    if [ "$all_ok" = false ]; then
        log_error "Некоторые проверки не пройдены"
        return 1
    fi
    
    log_success "Все проверки пройдены"
    return 0
}

# =============================================
# Создание маркера установки
# =============================================
mark_installed() {
    mkdir -p /opt/autodialer
    echo "System setup completed at $(date)" > "$INSTALLED_MARKER"
    echo "Debian version: $(lsb_release -ds 2>/dev/null || echo 'Unknown')" >> "$INSTALLED_MARKER"
    echo "Kernel: $(uname -r)" >> "$INSTALLED_MARKER"
    echo "Architecture: $(uname -m)" >> "$INSTALLED_MARKER"
    
    chown autodialer:autodialer "$INSTALLED_MARKER" 2>/dev/null || true
    
    log_success "Маркер установки создан: $INSTALLED_MARKER"
}

# =============================================
# Вывод сводки
# =============================================
print_summary() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}${BOLD}✅ Системная настройка завершена!${NC}"
    echo "=============================================="
    echo ""
    echo "Установленные компоненты:"
    echo "  • Python 3:       $(python3 --version 2>/dev/null || echo 'не установлен')"
    echo "  • pip:            $(python3 -m pip --version 2>/dev/null | cut -d' ' -f1-2 || echo 'не установлен')"
    echo "  • ffmpeg:         $(ffmpeg -version 2>/dev/null | head -1 || echo 'не установлен')"
    echo "  • Nginx:          $(nginx -v 2>&1 | cut -d'/' -f2 || echo 'не установлен')"
    echo "  • Redis client:   $(redis-cli --version 2>/dev/null | cut -d' ' -f2 || echo 'не установлен')"
    echo "  • PostgreSQL:     $(psql --version 2>/dev/null | head -1 || echo 'не установлен')"
    echo ""
    echo "Системные настройки:"
    echo "  • Лимиты файлов:  65536"
    echo "  • Swap:           $(swapon --show 2>/dev/null | grep -v NAME | wc -l) файл(ов)"
    echo "  • Timezone:       $(cat /etc/timezone 2>/dev/null || echo 'UTC')"
    echo ""
    echo "Рабочие директории:"
    echo "  • /opt/autodialer/"
    echo "  • /opt/autodialer/logs/"
    echo "  • /opt/autodialer/backups/"
    echo "  • /var/log/autodialer/"
    echo ""
    echo -e "${YELLOW}Следующий шаг: установка Asterisk${NC}"
    echo "=============================================="
}

# =============================================
# Основная функция
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - System Setup${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.2${NC}"
    echo "=============================================="
    echo ""
    
    check_root
    check_already_installed
    check_os
    check_resources
    
    update_system
    install_base_utils
    install_build_tools
    install_python_deps
    install_audio_deps
    install_db_clients
    install_nginx
    install_certbot
    install_extra_tools
    
    create_user
    setup_limits
    create_directories
    setup_swap
    setup_timezone
    
    verify_installation
    
    mark_installed
    print_summary
}

# =============================================
# Запуск
# =============================================
main "$@"
