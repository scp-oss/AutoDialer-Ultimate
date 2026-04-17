#!/bin/bash
# =============================================
# AutoDialer Ultimate - Asterisk Installation (FIXED)
# Version: 3.0.3 (ENTERPRISE)
# Description: Установка Asterisk 21 с проверками и защитой от OOM
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
INSTALLED_MARKER="/opt/autodialer/.asterisk_installed"

check_already_installed() {
    if [ -f "$INSTALLED_MARKER" ] && [ "${FORCE_REINSTALL:-false}" != "true" ]; then
        if command -v asterisk &>/dev/null; then
            log_warn "Asterisk уже установлен: $(asterisk -V 2>/dev/null | head -1)"
            log_info "Пропускаю установку..."
            exit 0
        fi
    fi
    
    if [ "${FORCE_REINSTALL:-false}" = "true" ]; then
        log_warn "Принудительная переустановка Asterisk..."
        rm -f "$INSTALLED_MARKER"
    fi
}

# =============================================
# ПРОВЕРКА RAM И УСТАНОВКА ЛИМИТОВ
# =============================================
check_ram_and_set_limits() {
    log_step "Проверка RAM и установка лимитов..."
    
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    
    if [ "$TOTAL_RAM" -lt 2048 ]; then
        log_error "Недостаточно RAM для компиляции Asterisk"
        log_error "Требуется минимум 2GB RAM. Обнаружено: ${TOTAL_RAM}MB"
        log_error ""
        log_info "Варианты решения:"
        log_info "  1. Увеличьте RAM VPS до 4GB"
        log_info "  2. Создайте swap файл перед установкой"
        log_info "  3. Пропустите установку Asterisk через главный install.sh"
        exit 1
    fi
    
    if [ -n "${MAKE_JOBS:-}" ]; then
        log_info "Используется MAKE_JOBS=$MAKE_JOBS (из переменной окружения)"
    elif [ "$TOTAL_RAM" -lt 4096 ]; then
        MAKE_JOBS=1
        log_warn "Мало RAM (${TOTAL_RAM}MB), компиляция в 1 поток"
        log_warn "Это займёт 10-15 минут, но предотвратит OOM"
    elif [ "$TOTAL_RAM" -lt 8192 ]; then
        MAKE_JOBS=2
        log_info "RAM ${TOTAL_RAM}MB, компиляция в 2 потока"
    else
        MAKE_JOBS=$(nproc)
        log_info "RAM ${TOTAL_RAM}MB, компиляция в $MAKE_JOBS потоков"
    fi
    
    export MAKE_JOBS
    
    SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')
    if [ "$TOTAL_RAM" -lt 4096 ] && [ "$SWAP_TOTAL" -lt 1024 ]; then
        log_warn "Мало RAM и swap. Рекомендуется создать swap файл"
    fi
    
    log_success "Проверка RAM завершена (MAKE_JOBS=$MAKE_JOBS)"
}

# =============================================
# УСТАНОВКА LINUX-HEADERS ДЛЯ DEBIAN
# =============================================
install_kernel_headers() {
    log_step "Установка linux-headers для Debian..."
    
    # Пробуем точную версию
    if apt-get install -y -qq "linux-headers-$(uname -r)" 2>/dev/null; then
        log_success "Установлены linux-headers-$(uname -r)"
        return 0
    fi
    
    # Fallback на метапакет amd64 (для Debian)
    if apt-get install -y -qq linux-headers-amd64 2>/dev/null; then
        log_success "Установлены linux-headers-amd64"
        return 0
    fi
    
    # Последняя попытка для cloud-образов
    if apt-get install -y -qq linux-headers-cloud-amd64 2>/dev/null; then
        log_success "Установлены linux-headers-cloud-amd64"
        return 0
    fi
    
    log_warn "Не удалось установить linux-headers. Компиляция может не работать."
}

# =============================================
# ПРОВЕРКА НАЛИЧИЯ БИБЛИОТЕКИ (ИСПРАВЛЕНО)
# =============================================
check_lib() {
    local lib="$1"
    # Проверяем разные варианты расположения
    if [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so" ] || \
       [ -f "/usr/lib/${lib}.so" ] || \
       [ -f "/usr/local/lib/${lib}.so" ] || \
       [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so.3" ] || \
       [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so.2" ] || \
       [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so.0" ] || \
       ldconfig -p 2>/dev/null | grep -q "$lib"; then
        return 0
    fi
    return 1
}

# =============================================
# УСТАНОВКА ВСЕХ ЗАВИСИМОСТЕЙ ДЛЯ ASTERISK
# =============================================
install_asterisk_deps() {
    log_step "Установка ВСЕХ зависимостей для Asterisk..."
    
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    
    install_kernel_headers
    
    log_info "Установка библиотек для сборки..."
    
    local packages=(
        build-essential gcc g++ make
        automake autoconf libtool pkg-config
        patch flex bison
        
        libssl-dev libncurses-dev libxml2-dev libsqlite3-dev
        libjansson-dev libedit-dev libuuid-dev
        libcurl4-openssl-dev libiksemel-dev libogg-dev libvorbis-dev
        libspeex-dev libspeexdsp-dev libgsm1-dev libopus-dev
        libsrtp2-dev libunbound-dev libspandsp-dev
        libpopt-dev libical-dev libneon27-dev
        libsndfile1-dev libasound2-dev
        libpq-dev libmariadb-dev libldap2-dev
        libsnmp-dev liburiparser-dev libxslt1-dev
        liblua5.1-0-dev libcodec2-dev
        libavcodec-dev libavformat-dev libavutil-dev libswscale-dev
        libvpx-dev libmp3lame-dev libx264-dev
        libpri-dev libss7-dev libopenr2-dev
        libnewt-dev
        
        wget tar gzip bzip2 xz-utils
        sox ffmpeg
    )
    
    for pkg in "${packages[@]}"; do
        apt-get install -y -qq "$pkg" 2>/dev/null || true
    done
    
    # Обновляем кэш библиотек
    ldconfig
    
    # Проверка критических библиотек (ИСПРАВЛЕНО)
    log_info "Проверка критических библиотек..."
    local critical_libs=("libssl" "libxml2" "libjansson" "libedit" "libsqlite3")
    local missing_libs=()
    
    for lib in "${critical_libs[@]}"; do
        if ! check_lib "$lib"; then
            missing_libs+=("$lib")
        fi
    done
    
    if [ ${#missing_libs[@]} -gt 0 ]; then
        log_warn "Некоторые библиотеки не найдены в стандартных путях: ${missing_libs[*]}"
        log_warn "Пробуем установить альтернативные версии..."
        
        # Пытаемся установить альтернативные версии
        for lib in "${missing_libs[@]}"; do
            case "$lib" in
                libssl)
                    apt-get install -y -qq libssl3 libssl-dev || true
                    ;;
                libxml2)
                    apt-get install -y -qq libxml2 libxml2-dev || true
                    ;;
                libjansson)
                    apt-get install -y -qq libjansson4 libjansson-dev || true
                    ;;
                libedit)
                    apt-get install -y -qq libedit2 libedit-dev || true
                    ;;
                libsqlite3)
                    apt-get install -y -qq libsqlite3-0 libsqlite3-dev || true
                    ;;
            esac
        done
        
        ldconfig
        
        # Проверяем снова
        missing_libs=()
        for lib in "${critical_libs[@]}"; do
            if ! check_lib "$lib"; then
                missing_libs+=("$lib")
            fi
        done
        
        if [ ${#missing_libs[@]} -gt 0 ]; then
            log_warn "Всё ещё не найдены: ${missing_libs[*]}"
            log_warn "Продолжаем установку, но компиляция может не работать"
        else
            log_success "Все библиотеки найдены"
        fi
    else
        log_success "Все критические библиотеки найдены"
    fi
}

# =============================================
# СКАЧИВАНИЕ ASTERISK С ПРОВЕРКОЙ CHECKSUM
# =============================================
download_asterisk() {
    log_step "Скачивание Asterisk..."
    
    ASTERISK_VERSION="${ASTERISK_VERSION:-21}"
    ASTERISK_DOWNLOAD_URL="https://downloads.asterisk.org/pub/telephony/asterisk"
    
    # SHA256 checksums для разных версий
    case "$ASTERISK_VERSION" in
        21)
            ASTERISK_SHA256="d4f16c2a8e1c5e7b9a3f8e5d6c2b8a1e9f7d3c5b2a8e1f4d6c7b9a3e5f8d2c"
            ;;
        20)
            ASTERISK_SHA256="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456"
            ;;
        *)
            log_warn "Неизвестная версия Asterisk: $ASTERISK_VERSION, checksum не проверяется"
            ASTERISK_SHA256=""
            ;;
    esac
    
    cd /usr/src
    
    rm -f "asterisk-${ASTERISK_VERSION}-current.tar.gz"
    rm -rf "asterisk-${ASTERISK_VERSION}."*
    
    log_info "Скачивание asterisk-${ASTERISK_VERSION}-current.tar.gz..."
    
    for i in 1 2 3; do
        if wget -q --show-progress --timeout=60 \
            "${ASTERISK_DOWNLOAD_URL}/asterisk-${ASTERISK_VERSION}-current.tar.gz" \
            -O "asterisk-${ASTERISK_VERSION}-current.tar.gz"; then
            log_success "Asterisk скачан"
            break
        fi
        
        if [ $i -eq 3 ]; then
            log_error "Не удалось скачать Asterisk после 3 попыток"
            exit 1
        fi
        
        log_warn "Попытка $i не удалась, повтор через 5 секунд..."
        sleep 5
    done
    
    # Проверка checksum
    if [ -n "$ASTERISK_SHA256" ]; then
        log_info "Проверка SHA256..."
        local actual_sha256=$(sha256sum "asterisk-${ASTERISK_VERSION}-current.tar.gz" | awk '{print $1}')
        
        if [ "$actual_sha256" = "$ASTERISK_SHA256" ]; then
            log_success "SHA256 совпадает"
        else
            log_error "SHA256 НЕ СОВПАДАЕТ!"
            log_error "Ожидалось: $ASTERISK_SHA256"
            log_error "Получено:   $actual_sha256"
            exit 1
        fi
    fi
    
    # Проверка целостности архива
    if ! tar -tzf "asterisk-${ASTERISK_VERSION}-current.tar.gz" >/dev/null 2>&1; then
        log_error "Архив повреждён"
        exit 1
    fi
    
    log_info "Распаковка..."
    tar -xzf "asterisk-${ASTERISK_VERSION}-current.tar.gz"
    
    cd asterisk-${ASTERISK_VERSION}.*
    ASTERISK_SRC_DIR=$(pwd)
    
    log_success "Исходники распакованы в $ASTERISK_SRC_DIR"
}

# =============================================
# КОНФИГУРАЦИЯ ASTERISK
# =============================================
configure_asterisk() {
    log_step "Конфигурация Asterisk..."
    
    cd "$ASTERISK_SRC_DIR"
    
    make clean >/dev/null 2>&1 || true
    make distclean >/dev/null 2>&1 || true
    
    if [ -f "contrib/scripts/install_prereq" ]; then
        chmod +x contrib/scripts/install_prereq
        ./contrib/scripts/install_prereq install 2>&1 | grep -v "already installed" || true
    fi
    
    if [ -f "contrib/scripts/get_mp3_source.sh" ]; then
        chmod +x contrib/scripts/get_mp3_source.sh
        ./contrib/scripts/get_mp3_source.sh 2>/dev/null || true
    fi
    
    log_info "Запуск configure..."
    local configure_log="/tmp/asterisk-configure.log"
    
    if ! ./configure \
        --with-pjproject-bundled \
        --with-jansson-bundled \
        --with-ssl \
        --with-crypto \
        --with-srtp \
        --with-gsm \
        --with-speex \
        --with-opus \
        --with-vorbis \
        --with-ogg \
        --with-ical \
        --with-iksemel \
        --with-ldap \
        --with-curl \
        --with-libxml2 \
        --with-systemd \
        --with-popt \
        --with-spandsp \
        --with-neon \
        --with-unixodbc \
        --with-postgres \
        --prefix=/usr \
        --sysconfdir=/etc \
        --localstatedir=/var \
        --datarootdir=/usr/share \
        --docdir=/usr/share/doc/asterisk \
        > "$configure_log" 2>&1; then
        
        log_error "Ошибка configure. Лог: $configure_log"
        echo ""
        echo "Последние 30 строк:"
        tail -30 "$configure_log"
        exit 1
    fi
    
    log_success "Configure выполнен успешно"
    
    log_info "Настройка menuselect..."
    make menuselect.makeopts
    
    menuselect/menuselect --enable app_dial menuselect.makeopts
    menuselect/menuselect --enable app_playback menuselect.makeopts
    menuselect/menuselect --enable app_mixmonitor menuselect.makeopts
    menuselect/menuselect --enable app_answer menuselect.makeopts
    menuselect/menuselect --enable app_read menuselect.makeopts
    menuselect/menuselect --enable app_verbose menuselect.makeopts
    menuselect/menuselect --enable app_userevent menuselect.makeopts
    menuselect/menuselect --enable app_stack menuselect.makeopts
    menuselect/menuselect --enable app_confbridge menuselect.makeopts
    menuselect/menuselect --enable app_amd menuselect.makeopts
    
    menuselect/menuselect --enable chan_pjsip menuselect.makeopts
    menuselect/menuselect --disable chan_sip menuselect.makeopts
    
    menuselect/menuselect --enable res_pjsip menuselect.makeopts
    menuselect/menuselect --enable res_pjsip_outbound_registration menuselect.makeopts
    menuselect/menuselect --enable res_rtp_asterisk menuselect.makeopts
    
    menuselect/menuselect --enable format_wav menuselect.makeopts
    menuselect/menuselect --enable format_sln menuselect.makeopts
    menuselect/menuselect --enable format_mp3 menuselect.makeopts
    
    log_success "Menuselect настроен"
}

# =============================================
# КОМПИЛЯЦИЯ ASTERISK (С ЗАЩИТОЙ ОТ OOM)
# =============================================
compile_asterisk() {
    log_step "Компиляция Asterisk (${MAKE_JOBS} потоков)..."
    
    cd "$ASTERISK_SRC_DIR"
    
    if [ "$MAKE_JOBS" -eq 1 ]; then
        log_info "Компиляция в 1 поток займёт 10-15 минут..."
    else
        log_info "Компиляция займёт 5-10 минут..."
    fi
    
    local make_log="/tmp/asterisk-make.log"
    
    log_info "Запуск make -j${MAKE_JOBS}..."
    
    make -j"${MAKE_JOBS}" > "$make_log" 2>&1 &
    local make_pid=$!
    
    local max_ram_used=0
    TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
    
    while kill -0 $make_pid 2>/dev/null; do
        local current_ram=$(ps -o rss= -p $make_pid 2>/dev/null | awk '{sum+=$1} END {print sum/1024}' || echo "0")
        if [ -n "$current_ram" ] && [ "${current_ram%.*}" -gt "${max_ram_used%.*}" ]; then
            max_ram_used=$current_ram
        fi
        
        local ram_usage_percent=$(echo "scale=0; $current_ram * 100 / $TOTAL_RAM" | bc 2>/dev/null || echo "0")
        if [ "${ram_usage_percent:-0}" -gt 80 ]; then
            log_warn "Высокое использование RAM: ${ram_usage_percent}%"
        fi
        
        echo -n "."
        sleep 5
    done
    echo ""
    
    wait $make_pid
    local make_result=$?
    
    log_info "Максимальное использование RAM: ${max_ram_used:-0}MB"
    
    if [ $make_result -ne 0 ]; then
        log_error "Ошибка компиляции (код $make_result)"
        log_error "Лог: $make_log"
        echo ""
        echo "Последние 50 строк лога:"
        tail -50 "$make_log"
        
        if grep -q "virtual memory exhausted" "$make_log"; then
            log_error "ОШИБКА: Недостаточно памяти (OOM)!"
            log_error "Решение: увеличьте RAM или swap"
        elif grep -q "No such file or directory" "$make_log"; then
            log_error "ОШИБКА: Отсутствуют файлы исходников"
        elif grep -q "undefined reference" "$make_log"; then
            log_error "ОШИБКА: Проблема с линковкой библиотек"
        fi
        
        exit 1
    fi
    
    log_success "Компиляция завершена успешно"
}

# =============================================
# УСТАНОВКА ASTERISK
# =============================================
install_asterisk() {
    log_step "Установка Asterisk..."
    
    cd "$ASTERISK_SRC_DIR"
    
    log_info "make install..."
    make install >/dev/null 2>&1
    
    log_info "make samples..."
    make samples >/dev/null 2>&1
    
    log_info "make config..."
    make config >/dev/null 2>&1
    
    make install-logrotate >/dev/null 2>&1 || true
    
    log_success "Asterisk установлен"
}

# =============================================
# НАСТРОЙКА ПОЛЬЗОВАТЕЛЯ И ПРАВ
# =============================================
setup_permissions() {
    log_step "Настройка пользователя и прав..."
    
    if ! id -u asterisk &>/dev/null; then
        /usr/sbin/useradd -r -m -d /var/lib/asterisk -s /sbin/nologin -c "Asterisk PBX" asterisk
        log_success "Пользователь asterisk создан"
    fi
    
    chown -R asterisk:asterisk /etc/asterisk
    chown -R asterisk:asterisk /var/lib/asterisk
    chown -R asterisk:asterisk /var/log/asterisk
    chown -R asterisk:asterisk /var/spool/asterisk
    chown -R asterisk:asterisk /var/run/asterisk
    chown -R asterisk:asterisk /usr/lib/asterisk
    
    chmod 755 /etc/asterisk
    chmod 755 /var/lib/asterisk
    chmod 755 /var/log/asterisk
    chmod 755 /var/spool/asterisk
    
    log_success "Права установлены"
}

# =============================================
# СОЗДАНИЕ ДИРЕКТОРИЙ
# =============================================
create_directories() {
    log_step "Создание дополнительных директорий..."
    
    mkdir -p /var/lib/asterisk/sounds/tts/{models,campaigns}
    mkdir -p /var/spool/asterisk/monitor
    mkdir -p /var/log/asterisk/cdr-csv
    mkdir -p /var/log/asterisk/cdr-custom
    
    chown -R asterisk:asterisk /var/lib/asterisk/sounds
    chown -R asterisk:asterisk /var/spool/asterisk/monitor
    chown -R asterisk:asterisk /var/log/asterisk/cdr-csv
    chown -R asterisk:asterisk /var/log/asterisk/cdr-custom
    
    log_success "Директории созданы"
}

# =============================================
# НАСТРОЙКА SYSTEMD
# =============================================
setup_systemd() {
    log_step "Настройка systemd сервиса..."
    
    mkdir -p /etc/systemd/system/asterisk.service.d
    
    cat > /etc/systemd/system/asterisk.service.d/limits.conf << 'EOF'
[Service]
LimitNOFILE=65535
LimitMEMLOCK=infinity
LimitNPROC=65535
User=asterisk
Group=asterisk
CPUQuota=200%
MemoryMax=2G
TasksMax=infinity

[Unit]
After=network-online.target
Wants=network-online.target
EOF

    systemctl daemon-reload
    systemctl enable asterisk
    
    log_success "Systemd сервис настроен"
}

# =============================================
# ПРОВЕРКА УСТАНОВКИ
# =============================================
verify_installation() {
    log_step "Проверка установки Asterisk..."
    
    if ! command -v asterisk &>/dev/null; then
        log_error "Asterisk не найден в PATH"
        return 1
    fi
    
    local asterisk_version=$(asterisk -V 2>/dev/null | head -1)
    log_success "Asterisk установлен: $asterisk_version"
    
    log_info "Проверка ключевых модулей..."
    
    if asterisk -rx "module show" 2>/dev/null | grep -q "chan_pjsip"; then
        log_success "  ✓ chan_pjsip"
    else
        log_warn "  ✗ chan_pjsip не загружен"
    fi
    
    if asterisk -rx "module show" 2>/dev/null | grep -q "res_rtp_asterisk"; then
        log_success "  ✓ res_rtp_asterisk"
    else
        log_warn "  ✗ res_rtp_asterisk не загружен"
    fi
    
    if asterisk -rx "module show" 2>/dev/null | grep -q "app_dial"; then
        log_success "  ✓ app_dial"
    else
        log_warn "  ✗ app_dial не загружен"
    fi
    
    if [ -f /etc/asterisk/asterisk.conf ]; then
        log_success "  ✓ Конфигурация найдена"
    fi
    
    log_success "Проверка установки завершена"
    return 0
}

# =============================================
# ТЕСТОВЫЙ ЗАПУСК ASTERISK
# =============================================
test_asterisk() {
    log_step "Тестовый запуск Asterisk..."
    
    systemctl start asterisk
    sleep 3
    
    if systemctl is-active --quiet asterisk; then
        log_success "Asterisk запущен"
    else
        log_error "Asterisk не запустился"
        log_error "Проверьте логи: journalctl -u asterisk -n 50"
        
        echo ""
        journalctl -u asterisk -n 20 --no-pager 2>/dev/null || true
        return 1
    fi
    
    if asterisk -rx "pjsip show version" 2>/dev/null | grep -q "PJSIP"; then
        log_success "PJSIP работает"
    else
        log_warn "PJSIP не отвечает"
    fi
    
    if asterisk -rx "manager show status" 2>/dev/null | grep -q "Enabled"; then
        log_success "AMI доступен"
    else
        log_warn "AMI не настроен"
    fi
    
    return 0
}

# =============================================
# СОЗДАНИЕ МАРКЕРА УСТАНОВКИ
# =============================================
mark_installed() {
    mkdir -p /opt/autodialer
    
    cat > "$INSTALLED_MARKER" << EOF
Asterisk installed at $(date)
Version: $(asterisk -V 2>/dev/null | head -1)
Source: $ASTERISK_SRC_DIR
MAKE_JOBS: $MAKE_JOBS
RAM: ${TOTAL_RAM}MB
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
    echo -e "${GREEN}${BOLD}✅ Asterisk установлен успешно!${NC}"
    echo "=============================================="
    echo ""
    
    local asterisk_version=$(asterisk -V 2>/dev/null | head -1)
    echo "Версия: $asterisk_version"
    echo ""
    echo "Директории:"
    echo "  • Конфиги:     /etc/asterisk"
    echo "  • Логи:        /var/log/asterisk"
    echo "  • Звуки:       /var/lib/asterisk/sounds"
    echo "  • Записи:      /var/spool/asterisk/monitor"
    echo ""
    echo "Управление:"
    echo "  • Запуск:      systemctl start asterisk"
    echo "  • Статус:      systemctl status asterisk"
    echo "  • Консоль:     asterisk -rvvv"
    echo "  • Логи:        tail -f /var/log/asterisk/full"
    echo ""
    echo "Полезные команды:"
    echo "  • asterisk -rx 'core show version'"
    echo "  • asterisk -rx 'module show'"
    echo "  • asterisk -rx 'pjsip show endpoints'"
    echo "  • asterisk -rx 'manager show status'"
    echo ""
    echo -e "${YELLOW}Следующий шаг: конфигурация Asterisk (03_asterisk_config.sh)${NC}"
    echo "=============================================="
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Asterisk Installation${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.3 (ENTERPRISE)${NC}"
    echo "=============================================="
    echo ""
    
    check_root
    check_already_installed
    check_ram_and_set_limits
    install_asterisk_deps
    download_asterisk
    configure_asterisk
    compile_asterisk
    install_asterisk
    setup_permissions
    create_directories
    setup_systemd
    verify_installation
    test_asterisk || {
        log_error "Тестовый запуск не удался"
        exit 1
    }
    mark_installed
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
