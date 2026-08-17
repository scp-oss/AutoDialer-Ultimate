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
        exit 1
    fi
    
    if [ -n "${MAKE_JOBS:-}" ]; then
        log_info "Используется MAKE_JOBS=$MAKE_JOBS (из переменной окружения)"
    elif [ "$TOTAL_RAM" -lt 4096 ]; then
        MAKE_JOBS=1
        log_warn "Мало RAM (${TOTAL_RAM}MB), компиляция в 1 поток"
    elif [ "$TOTAL_RAM" -lt 8192 ]; then
        MAKE_JOBS=2
        log_info "RAM ${TOTAL_RAM}MB, компиляция в 2 потока"
    else
        MAKE_JOBS=$(nproc)
        log_info "RAM ${TOTAL_RAM}MB, компиляция в $MAKE_JOBS потоков"
    fi
    
    export MAKE_JOBS
    
    log_success "Проверка RAM завершена (MAKE_JOBS=$MAKE_JOBS)"
}

# =============================================
# УСТАНОВКА LINUX-HEADERS ДЛЯ DEBIAN
# =============================================
install_kernel_headers() {
    log_step "Установка linux-headers для Debian..."
    
    if apt-get install -y -qq "linux-headers-$(uname -r)" 2>/dev/null; then
        log_success "Установлены linux-headers-$(uname -r)"
        return 0
    fi
    
    if apt-get install -y -qq linux-headers-amd64 2>/dev/null; then
        log_success "Установлены linux-headers-amd64"
        return 0
    fi
    
    if apt-get install -y -qq linux-headers-cloud-amd64 2>/dev/null; then
        log_success "Установлены linux-headers-cloud-amd64"
        return 0
    fi
    
    log_warn "Не удалось установить linux-headers. Компиляция может не работать."
}

# =============================================
# ПРОВЕРКА НАЛИЧИЯ БИБЛИОТЕКИ
# =============================================
check_lib() {
    local lib="$1"
    [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so" ] ||
    [ -f "/usr/lib/${lib}.so" ] ||
    [ -f "/usr/local/lib/${lib}.so" ] ||
    [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so.3" ] ||
    [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so.2" ] ||
    [ -f "/usr/lib/x86_64-linux-gnu/${lib}.so.0" ] ||
    /sbin/ldconfig -p 2>/dev/null | grep -q "$lib"
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
        build-essential gcc g++ make automake autoconf libtool pkg-config patch flex bison
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
        libpri-dev libss7-dev libopenr2-dev libnewt-dev
        wget tar gzip bzip2 xz-utils sox ffmpeg
    )
    
    for pkg in "${packages[@]}"; do
        apt-get install -y -qq "$pkg" 2>/dev/null || true
    done
    
    /sbin/ldconfig
    
    log_info "Проверка критических библиотек..."
    local critical_libs=("libssl" "libxml2" "libjansson" "libedit" "libsqlite3")
    local missing_libs=()
    
    for lib in "${critical_libs[@]}"; do
        if ! check_lib "$lib"; then
            missing_libs+=("$lib")
        fi
    done
    
    if [ ${#missing_libs[@]} -gt 0 ]; then
        log_warn "Некоторые библиотеки не найдены: ${missing_libs[*]}"
        
        for lib in "${missing_libs[@]}"; do
            case "$lib" in
                libssl)    apt-get install -y -qq libssl3 libssl-dev || true ;;
                libxml2)   apt-get install -y -qq libxml2 libxml2-dev || true ;;
                libjansson) apt-get install -y -qq libjansson4 libjansson-dev || true ;;
                libedit)   apt-get install -y -qq libedit2 libedit-dev || true ;;
                libsqlite3) apt-get install -y -qq libsqlite3-0 libsqlite3-dev || true ;;
            esac
        done
        /sbin/ldconfig
        log_warn "Продолжаем установку"
    else
        log_success "Все критические библиотеки найдены"
    fi
}

# =============================================
# СКАЧИВАНИЕ ASTERISK (БЕЗ SHA256 - АРХИВ ОБНОВЛЯЕТСЯ)
# =============================================
download_asterisk() {
    log_step "Скачивание Asterisk..."
    
    ASTERISK_VERSION="${ASTERISK_VERSION:-21}"
    ASTERISK_DOWNLOAD_URL="https://downloads.asterisk.org/pub/telephony/asterisk"
    
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
    
    log_info "Проверка целостности архива..."
    if ! tar -tzf "asterisk-${ASTERISK_VERSION}-current.tar.gz" >/dev/null 2>&1; then
        log_error "Архив повреждён"
        exit 1
    fi
    log_success "Архив цел"
    
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
        --with-ssl --with-crypto --with-srtp \
        --with-gsm --with-speex --with-opus --with-vorbis --with-ogg \
        --with-ical --with-iksemel --with-ldap --with-curl --with-libxml2 \
        --with-systemd --with-popt --with-spandsp --with-neon \
        --with-unixodbc --with-postgres \
        --prefix=/usr --sysconfdir=/etc --localstatedir=/var \
        --datarootdir=/usr/share --docdir=/usr/share/doc/asterisk \
        > "$configure_log" 2>&1; then
        
        log_error "Ошибка configure. Лог: $configure_log"
        tail -30 "$configure_log"
        exit 1
    fi
    
    log_success "Configure выполнен успешно"
    
    log_info "Настройка menuselect..."
    make menuselect.makeopts
    
    menuselect/menuselect --enable app_dial menuselect.makeopts
    menuselect/menuselect --enable app_playback menuselect.makeopts
    menuselect/menuselect --enable app_mixmonitor menuselect.makeopts
    # menuselect/menuselect --enable app_answer menuselect.makeopts
    # menuselect/menuselect --enable app_read menuselect.makeopts
    # menuselect/menuselect --enable app_verbose menuselect.makeopts
    menuselect/menuselect --enable app_userevent menuselect.makeopts
    menuselect/menuselect --enable app_stack menuselect.makeopts
    menuselect/menuselect --enable app_confbridge menuselect.makeopts
    menuselect/menuselect --enable app_amd menuselect.makeopts
    
    menuselect/menuselect --enable chan_pjsip menuselect.makeopts
    # menuselect/menuselect --disable chan_sip menuselect.makeopts
    
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
        tail -50 "$make_log"
        
        if grep -q "virtual memory exhausted" "$make_log"; then
            log_error "ОШИБКА: Недостаточно памяти (OOM)!"
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
    
    make install >/dev/null 2>&1
    make samples >/dev/null 2>&1
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

    # /var/run (он же /run) - это tmpfs, который полностью очищается при
    # КАЖДОЙ перезагрузке сервера (в отличие от простого restart сервиса).
    # Без systemd-tmpfiles.d правила /var/run/asterisk создаётся только
    # один раз здесь, при установке, и переживает лишь до первого reboot -
    # после чего Asterisk не может стартовать: "mkdir: невозможно создать
    # каталог «/var/run/asterisk»: Отказано в доступе". Подтверждено живьём
    # на тестовом сервере после реального перезапуска железа.
    mkdir -p /var/run/asterisk
    echo 'd /var/run/asterisk 0755 asterisk asterisk -' > /etc/tmpfiles.d/asterisk.conf
    systemd-tmpfiles --create /etc/tmpfiles.d/asterisk.conf 2>/dev/null || true

    chown -R asterisk:asterisk /etc/asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk /var/run/asterisk /usr/lib/asterisk
    chmod 755 /etc/asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk

    log_success "Права установлены"
}

# =============================================
# СОЗДАНИЕ ДИРЕКТОРИЙ
# =============================================
create_directories() {
    log_step "Создание дополнительных директорий..."
    
    mkdir -p /var/lib/asterisk/sounds/tts/{models,campaigns}
    mkdir -p /var/spool/asterisk/monitor
    mkdir -p /var/log/asterisk/cdr-csv /var/log/asterisk/cdr-custom
    
    chown -R asterisk:asterisk /var/lib/asterisk/sounds /var/spool/asterisk/monitor /var/log/asterisk/cdr-csv /var/log/asterisk/cdr-custom
    
    log_success "Директории созданы"
}

# =============================================
# НАСТРОЙКА SYSTEMD
# =============================================
setup_systemd() {
    log_step "Настройка systemd сервиса..."
    
    mkdir -p /etc/systemd/system/asterisk.service.d
    
    # ВНИМАНИЕ: намеренно НЕ указываем здесь User=/Group=asterisk.
    # asterisk.conf уже содержит runuser=asterisk/rungroup=asterisk -
    # это заставляет сам процесс Asterisk (запущенный systemd от root)
    # самостоятельно chown'ить /var/run/asterisk и понижать привилегии
    # через capabilities. Если ЗДЕСЬ тоже задать User=asterisk, systemd
    # стартует процесс уже НЕ от root - и тогда собственная попытка
    # Asterisk сделать chown/setuid/capset проваливается с ошибками
    # "Unable to chown run directory" / "Unable to install capabilities",
    # из-за чего control-сокет /var/run/asterisk/asterisk.ctl вообще не
    # создаётся (asterisk -r перестаёт подключаться). Подтверждено
    # живьём: с User=asterisk здесь процесс формально "active (running)",
    # но asterisk.ctl отсутствует. Один-единственный механизм понижения
    # привилегий должен использоваться - через runuser/rungroup.
    cat > /etc/systemd/system/asterisk.service.d/limits.conf << 'EOF'
[Service]
LimitNOFILE=65535
LimitMEMLOCK=infinity
LimitNPROC=65535
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
    
    if [ ! -f /usr/sbin/asterisk ]; then
        log_error "Asterisk не найден в /usr/sbin"
        return 1
    fi
    
    local asterisk_version=$(/usr/sbin/asterisk -V 2>/dev/null | head -1)
    log_success "Asterisk установлен: $asterisk_version"
    
    log_info "Проверка ключевых модулей..."
    
    /usr/sbin/asterisk -rx "module show" 2>/dev/null | grep -q "chan_pjsip" && log_success "  ✓ chan_pjsip" || log_warn "  ✗ chan_pjsip"
    /usr/sbin/asterisk -rx "module show" 2>/dev/null | grep -q "res_rtp_asterisk" && log_success "  ✓ res_rtp_asterisk" || log_warn "  ✗ res_rtp_asterisk"
    /usr/sbin/asterisk -rx "module show" 2>/dev/null | grep -q "app_dial" && log_success "  ✓ app_dial" || log_warn "  ✗ app_dial"
    [ -f /etc/asterisk/asterisk.conf ] && log_success "  ✓ Конфигурация найдена"
    
    log_success "Проверка установки завершена"
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
        journalctl -u asterisk -n 20 --no-pager 2>/dev/null || true
        return 1
    fi
    
    asterisk -rx "pjsip show version" 2>/dev/null | grep -q "PJSIP" && log_success "PJSIP работает" || log_warn "PJSIP не отвечает"
    asterisk -rx "manager show status" 2>/dev/null | grep -q "Enabled" && log_success "AMI доступен" || log_warn "AMI не настроен"
}

# =============================================
# СОЗДАНИЕ МАРКЕРА УСТАНОВКИ
# =============================================
mark_installed() {
    mkdir -p /opt/autodialer
    
    cat > "$INSTALLED_MARKER" << EOF
Asterisk installed at $(date)
Version: $(asterisk -V 2>/dev/null | head -1)
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
    echo "Версия: $(asterisk -V 2>/dev/null | head -1)"
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
    echo ""
    echo -e "${YELLOW}Следующий шаг: конфигурация Asterisk${NC}"
    echo "=============================================="
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Asterisk Installation${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.3${NC}"
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
    test_asterisk || exit 1
    mark_installed
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
