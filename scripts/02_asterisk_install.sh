#!/bin/bash
# =============================================
# AutoDialer Ultimate - Asterisk Installation (FIXED)
# Version: 3.0.1
# Description: Установка Asterisk 21 с проверками и защитой от OOM
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Загрузка конфигурации
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
// ... previous code continues ...

# =============================================
# 🔥 ПРОВЕРКА RAM И УСТАНОВКА ЛИМИТОВ
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
        log_info "  2. Создайте swap файл перед установкой:"
        log_info "     fallocate -l 2G /swapfile"
        log_info "     chmod 600 /swapfile"
        log_info "     mkswap /swapfile"
        log_info "     swapon /swapfile"
        log_info "  3. Пропустите установку Asterisk через главный install.sh"
        exit 1
    fi
    
    # 🔥 Определение количества потоков компиляции
    if [ -n "${MAKE_JOBS:-}" ]; then
        # Используем переданное значение
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
    
    # 🔥 Проверка и создание swap если нужно
    SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')
    if [ "$TOTAL_RAM" -lt 4096 ] && [ "$SWAP_TOTAL" -lt 1024 ]; then
        log_warn "Мало RAM и swap. Рекомендуется создать swap файл:"
        log_warn "  fallocate -l 2G /swapfile"
        log_warn "  chmod 600 /swapfile"
        log_warn "  mkswap /swapfile"
        log_warn "  swapon /swapfile"
        
        if [ "${NON_INTERACTIVE:-true}" != "true" ]; then
            read -p "Создать swap файл 2GB сейчас? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                log_info "Создание swap файла..."
                fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 2>/dev/null
                chmod 600 /swapfile
                mkswap /swapfile
                swapon /swapfile
                echo '/swapfile none swap sw 0 0' >> /etc/fstab
                log_success "Swap файл создан"
            fi
        fi
    fi
    
    log_success "Проверка RAM завершена (MAKE_JOBS=$MAKE_JOBS)"
}

# =============================================
// ... previous code continues ...

# =============================================
# 🔥 УСТАНОВКА ВСЕХ ЗАВИСИМОСТЕЙ ДЛЯ ASTERISK
# =============================================
install_asterisk_deps() {
    log_step "Установка ВСЕХ зависимостей для Asterisk..."
    
    export DEBIAN_FRONTEND=noninteractive
    
    # 🔥 Обновление списка пакетов
    apt-get update -qq
    
    # 🔥 Установка linux-headers
    log_info "Установка linux-headers..."
    apt-get install -y -qq linux-headers-$(uname -r) 2>/dev/null || {
        log_warn "Не удалось установить linux-headers-$(uname -r)"
        log_info "Пробую linux-headers-generic..."
        apt-get install -y -qq linux-headers-generic 2>/dev/null || {
            log_warn "linux-headers не установлены. Компиляция может не работать."
        }
    }
    
    # 🔥 ПОЛНЫЙ СПИСОК ЗАВИСИМОСТЕЙ (проверено на Debian 12)
    log_info "Установка библиотек для сборки..."
    
    local packages=(
        # Инструменты сборки
        build-essential gcc g++ make
        automake autoconf libtool pkg-config
        patch flex bison
        
        # Библиотеки
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
        libnewt-dev libsqlite0-dev
        
        # Утилиты
        wget tar gzip bzip2 xz-utils
        sox ffmpeg
    )
    
    for pkg in "${packages[@]}"; do
        apt-get install -y -qq "$pkg" 2>/dev/null || {
            log_warn "Не удалось установить $pkg"
        }
    done
    
    # 🔥 Проверка критических библиотек
    log_info "Проверка критических библиотек..."
    local critical_libs=("libssl" "libxml2" "libjansson" "libedit" "libsqlite3")
    local missing_libs=()
    
    for lib in "${critical_libs[@]}"; do
        if ! ldconfig -p 2>/dev/null | grep -q "$lib"; then
            missing_libs+=("$lib")
        fi
    done
    
    if [ ${#missing_libs[@]} -gt 0 ]; then
        log_error "Отсутствуют критические библиотеки: ${missing_libs[*]}"
        log_error "Попробуйте установить вручную:"
        log_error "  apt-get install -y libssl-dev libxml2-dev libjansson-dev libedit-dev libsqlite3-dev"
        exit 1
    fi
    
    log_success "Все зависимости установлены"
}

# =============================================
// ... previous code continues ...

# =============================================
# СКАЧИВАНИЕ ASTERISK С ПРОВЕРКОЙ
# =============================================
download_asterisk() {
    log_step "Скачивание Asterisk..."
    
    ASTERISK_VERSION="${ASTERISK_VERSION:-21}"
    ASTERISK_DOWNLOAD_URL="https://downloads.asterisk.org/pub/telephony/asterisk"
    
    cd /usr/src
    
    # 🔥 Очистка старых файлов
    rm -f "asterisk-${ASTERISK_VERSION}-current.tar.gz"
    rm -rf "asterisk-${ASTERISK_VERSION}."*
    
    # 🔥 Скачивание с повторными попытками
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
    
    # 🔥 Проверка целостности архива
    if ! tar -tzf "asterisk-${ASTERISK_VERSION}-current.tar.gz" >/dev/null 2>&1; then
        log_error "Архив повреждён"
        exit 1
    fi
    
    log_success "Архив проверен"
    
    # 🔥 Распаковка
    log_info "Распаковка..."
    tar -xzf "asterisk-${ASTERISK_VERSION}-current.tar.gz"
    
    cd asterisk-${ASTERISK_VERSION}.*
    ASTERISK_SRC_DIR=$(pwd)
    
    log_success "Исходники распакованы в $ASTERISK_SRC_DIR"
}

# =============================================
// ... previous code continues ...

# =============================================
# КОНФИГУРАЦИЯ ASTERISK
# =============================================
configure_asterisk() {
    log_step "Конфигурация Asterisk..."
    
    cd "$ASTERISK_SRC_DIR"
    
    # 🔥 Очистка перед конфигурацией
    make clean >/dev/null 2>&1 || true
    make distclean >/dev/null 2>&1 || true
    
    # 🔥 Установка зависимостей через install_prereq
    log_info "Запуск install_prereq..."
    if [ -f "contrib/scripts/install_prereq" ]; then
        chmod +x contrib/scripts/install_prereq
        ./contrib/scripts/install_prereq install 2>&1 | grep -v "already installed" || true
    fi
    
    # 🔥 Скачивание MP3 поддержки
    if [ -f "contrib/scripts/get_mp3_source.sh" ]; then
        chmod +x contrib/scripts/get_mp3_source.sh
        ./contrib/scripts/get_mp3_source.sh 2>/dev/null || true
    fi
    
    # 🔥 Запуск configure с полным набором опций
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
        echo "-------------------"
        tail -30 "$configure_log"
        exit 1
    fi
    
    log_success "Configure выполнен успешно"
    
    # 🔥 Настройка menuselect
    log_info "Настройка menuselect..."
    make menuselect.makeopts
    
    # Включаем необходимые модули
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

// ... previous code continues ...

# =============================================
# 🔥 КОМПИЛЯЦИЯ ASTERISK (С ЗАЩИТОЙ ОТ OOM)
# =============================================
compile_asterisk() {
    log_step "Компиляция Asterisk (${MAKE_JOBS} потоков)..."
    
    cd "$ASTERISK_SRC_DIR"
    
    # 🔥 Оценка времени компиляции
    if [ "$MAKE_JOBS" -eq 1 ]; then
        log_info "Компиляция в 1 поток займёт 10-15 минут..."
    else
        log_info "Компиляция займёт 5-10 минут..."
    fi
    
    local make_log="/tmp/asterisk-make.log"
    
    # 🔥 Запуск компиляции с мониторингом памяти
    log_info "Запуск make -j${MAKE_JOBS}..."
    
    # Фоновая компиляция
    make -j"${MAKE_JOBS}" > "$make_log" 2>&1 &
    local make_pid=$!
    
    # Мониторинг памяти во время компиляции
    local max_ram_used=0
    while kill -0 $make_pid 2>/dev/null; do
        local current_ram=$(ps -o rss= -p $make_pid 2>/dev/null | awk '{sum+=$1} END {print sum/1024}' || echo "0")
        if [ -n "$current_ram" ] && [ "${current_ram%.*}" -gt "${max_ram_used%.*}" ]; then
            max_ram_used=$current_ram
        fi
        
        # 🔥 Проверка на OOM (если процесс использует > 80% RAM)
        local ram_usage_percent=$(echo "scale=0; $current_ram * 100 / $TOTAL_RAM" | bc 2>/dev/null || echo "0")
        if [ "${ram_usage_percent:-0}" -gt 80 ]; then
            log_warn "Высокое использование RAM: ${ram_usage_percent}%"
            log_warn "Если произойдёт OOM, перезапустите с --skip-asterisk"
        fi
        
        # Прогресс-индикатор
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
        echo "------------------------"
        tail -50 "$make_log"
        echo "------------------------"
        
        # 🔥 Анализ ошибки
        if grep -q "virtual memory exhausted" "$make_log"; then
            log_error "ОШИБКА: Недостаточно памяти (OOM)!"
            log_error ""
            log_info "Решение:"
            log_info "  1. Увеличьте RAM или swap"
            log_info "  2. Установите MAKE_JOBS=1 перед запуском"
            log_info "  3. Пропустите Asterisk: --skip-asterisk"
        elif grep -q "No such file or directory" "$make_log"; then
            log_error "ОШИБКА: Отсутствуют файлы исходников"
        elif grep -q "undefined reference" "$make_log"; then
            log_error "ОШИБКА: Проблема с линковкой библиотек"
        fi
        
        exit 1
    fi
    
    log_success "Компиляция завершена успешно"
}

// ... previous code continues ...

# =============================================
# УСТАНОВКА ASTERISK
# =============================================
install_asterisk() {
    log_step "Установка Asterisk..."
    
    cd "$ASTERISK_SRC_DIR"
    
    # Установка
    log_info "make install..."
    make install >/dev/null 2>&1
    
    # Установка конфигов
    log_info "make samples..."
    make samples >/dev/null 2>&1
    
    # Установка init скриптов
    log_info "make config..."
    make config >/dev/null 2>&1
    
    # Установка logrotate
    make install-logrotate >/dev/null 2>&1 || true
    
    log_success "Asterisk установлен"
}

# =============================================
// ... previous code continues ...

# =============================================
# НАСТРОЙКА ПОЛЬЗОВАТЕЛЯ И ПРАВ
# =============================================
setup_permissions() {
    log_step "Настройка пользователя и прав..."
    
    # Создание пользователя asterisk если не существует
    if ! id -u asterisk &>/dev/null; then
        useradd -r -m -d /var/lib/asterisk -s /sbin/nologin -c "Asterisk PBX" asterisk
        log_success "Пользователь asterisk создан"
    fi
    
    # Установка прав
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
// ... previous code continues ...

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
// ... previous code continues ...

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
// ... previous code continues ...

# =============================================
# ПРОВЕРКА УСТАНОВКИ
# =============================================
verify_installation() {
    log_step "Проверка установки Asterisk..."
    
    # Проверка бинарника
    if ! command -v asterisk &>/dev/null; then
        log_error "Asterisk не найден в PATH"
        return 1
    fi
    
    # Проверка версии
    local asterisk_version=$(asterisk -V 2>/dev/null | head -1)
    log_success "Asterisk установлен: $asterisk_version"
    
    # Проверка модулей
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
    
    # Проверка конфигурации
    if [ -f /etc/asterisk/asterisk.conf ]; then
        log_success "  ✓ Конфигурация найдена"
    fi
    
    log_success "Проверка установки завершена"
    return 0
}

// ... previous code continues ...

# =============================================
# 🔥 ТЕСТОВЫЙ ЗАПУСК ASTERISK
# =============================================
test_asterisk() {
    log_step "Тестовый запуск Asterisk..."
    
    # Запуск сервиса
    systemctl start asterisk
    sleep 3
    
    # Проверка статуса
    if systemctl is-active --quiet asterisk; then
        log_success "Asterisk запущен"
    else
        log_error "Asterisk не запустился"
        log_error "Проверьте логи: journalctl -u asterisk -n 50"
        
        # Показываем ошибки
        echo ""
        journalctl -u asterisk -n 20 --no-pager 2>/dev/null || true
        return 1
    fi
    
    # Проверка PJSIP
    if asterisk -rx "pjsip show version" 2>/dev/null | grep -q "PJSIP"; then
        log_success "PJSIP работает"
    else
        log_warn "PJSIP не отвечает"
    fi
    
    # Проверка AMI
    if asterisk -rx "manager show status" 2>/dev/null | grep -q "Enabled"; then
        log_success "AMI доступен"
    else
        log_warn "AMI не настроен"
    fi
    
    return 0
}

// ... previous code continues ...

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

// ... previous code continues ...

# =============================================
// ... continue with final parts of the script ...

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

// ... previous code continues ...

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Asterisk Installation${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.1 (FIXED)${NC}"
    echo "=============================================="
    echo ""
    
    # Проверки
    check_root
    check_already_installed
    check_ram_and_set_limits
    
    # Установка
    install_asterisk_deps
    download_asterisk
    configure_asterisk
    compile_asterisk
    install_asterisk
    
    # Настройка
    setup_permissions
    create_directories
    setup_systemd
    
    # Проверка
    verify_installation
    test_asterisk || {
        log_error "Тестовый запуск не удался"
        log_error "Проверьте логи и исправьте ошибки"
        exit 1
    }
    
    # Завершение
    mark_installed
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
