#!/bin/bash
# =============================================
# AutoDialer Ultimate - Backup Setup
# Version: 3.0.0
# Description: Резервное копирование БД + tts_audio/call_recordings
#              (ROADMAP.md §3.7)
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
# Конфигурация (совпадает с .env.example)
# =============================================
# install.sh копирует .env в /opt/autodialer/.env — это runtime-путь,
# который читают autodialer-backup/autodialer-restore при запуске из cron.
ENV_FILE="/opt/autodialer/.env"
BACKUP_DIR="${BACKUP_DIR:-/opt/autodialer/backups}"
BACKUP_RETENTION="${BACKUP_RETENTION:-30}"
AUTO_BACKUP_ENABLED="${AUTO_BACKUP_ENABLED:-false}"
BACKUP_SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"

INSTALLED_MARKER="/opt/autodialer/.backup_configured"

# =============================================
# Проверка идемпотентности
# =============================================
check_already_configured() {
    if [ -f "$INSTALLED_MARKER" ] && [ "${FORCE_REINSTALL:-false}" != "true" ]; then
        log_warn "Резервное копирование уже настроено (найден $INSTALLED_MARKER)"
        log_info "Для переустановки: FORCE_REINSTALL=true $0"
        exit 0
    fi
}

# =============================================
# Проверка зависимостей
# =============================================
check_dependencies() {
    log_step "Проверка зависимостей..."
    local missing=()
    for cmd in pg_dump pg_restore tar; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        log_error "Не найдены команды: ${missing[*]} (нужен postgresql-client)"
        exit 1
    fi
    log_success "pg_dump, pg_restore, tar найдены"
}

# =============================================
# Директория бэкапов
# =============================================
create_backup_dir() {
    log_step "Создание директории для бэкапов..."
    mkdir -p "$BACKUP_DIR"
    chown autodialer:autodialer "$BACKUP_DIR" 2>/dev/null || true
    chmod 750 "$BACKUP_DIR"
    log_success "Директория создана: $BACKUP_DIR"
}

# =============================================
# Установка скрипта резервного копирования
# =============================================
install_backup_script() {
    log_step "Установка /usr/local/bin/autodialer-backup..."

    cat > /usr/local/bin/autodialer-backup << 'SCRIPT_EOF'
#!/bin/bash
# AutoDialer Ultimate — резервное копирование БД + tts_audio/call_recordings.
# Устанавливается scripts/15_backup_setup.sh. Запускается по cron
# (см. /etc/cron.d/autodialer-backup) или вручную: autodialer-backup

set -euo pipefail

ENV_FILE="/opt/autodialer/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

DB_NAME="${DB_NAME:-autodialer}"
DB_USER="${DB_USER:-autodialer}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-/opt/autodialer/backups}"
BACKUP_RETENTION="${BACKUP_RETENTION:-30}"
TTS_DIR="${TTS_DIR:-/var/lib/asterisk/sounds/tts}"
RECORDINGS_DIR="${RECORDINGS_DIR:-/var/spool/asterisk/monitor}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_PREFIX="[autodialer-backup $TIMESTAMP]"
mkdir -p "$BACKUP_DIR"

echo "$LOG_PREFIX Старт резервного копирования в $BACKUP_DIR"

# --- База данных: pg_dump в custom-формате (нужен для pg_restore --clean) ---
DB_DUMP="$BACKUP_DIR/db_${TIMESTAMP}.dump"
if PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$DB_DUMP"; then
    echo "$LOG_PREFIX БД сохранена: $DB_DUMP ($(du -h "$DB_DUMP" | cut -f1))"
else
    echo "$LOG_PREFIX ОШИБКА: pg_dump завершился с ошибкой" >&2
    rm -f "$DB_DUMP"
    exit 1
fi

# --- tts_audio: пропускается, если каталога нет или он пуст ---
if [ -d "$TTS_DIR" ] && [ -n "$(ls -A "$TTS_DIR" 2>/dev/null)" ]; then
    TTS_ARCHIVE="$BACKUP_DIR/tts_audio_${TIMESTAMP}.tar.gz"
    tar czf "$TTS_ARCHIVE" -C "$(dirname "$TTS_DIR")" "$(basename "$TTS_DIR")"
    echo "$LOG_PREFIX tts_audio сохранён: $TTS_ARCHIVE ($(du -h "$TTS_ARCHIVE" | cut -f1))"
else
    echo "$LOG_PREFIX tts_audio ($TTS_DIR) пуст или не существует, пропуск"
fi

# --- call_recordings: то же самое ---
if [ -d "$RECORDINGS_DIR" ] && [ -n "$(ls -A "$RECORDINGS_DIR" 2>/dev/null)" ]; then
    REC_ARCHIVE="$BACKUP_DIR/call_recordings_${TIMESTAMP}.tar.gz"
    tar czf "$REC_ARCHIVE" -C "$(dirname "$RECORDINGS_DIR")" "$(basename "$RECORDINGS_DIR")"
    echo "$LOG_PREFIX call_recordings сохранены: $REC_ARCHIVE ($(du -h "$REC_ARCHIVE" | cut -f1))"
else
    echo "$LOG_PREFIX call_recordings ($RECORDINGS_DIR) пуст или не существует, пропуск"
fi

# --- Ротация: удаляем файлы бэкапов старше BACKUP_RETENTION дней ---
DELETED=$(find "$BACKUP_DIR" -maxdepth 1 \( -name "db_*.dump" -o -name "tts_audio_*.tar.gz" -o -name "call_recordings_*.tar.gz" \) -mtime "+$BACKUP_RETENTION" -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "$LOG_PREFIX Ротация: удалено $DELETED файлов старше $BACKUP_RETENTION дней"
fi

echo "$LOG_PREFIX Готово"
SCRIPT_EOF
    chmod 750 /usr/local/bin/autodialer-backup
    chown root:autodialer /usr/local/bin/autodialer-backup 2>/dev/null || true
    log_success "Установлен /usr/local/bin/autodialer-backup"
}

# =============================================
# Установка скрипта восстановления
# =============================================
install_restore_script() {
    log_step "Установка /usr/local/bin/autodialer-restore..."

    cat > /usr/local/bin/autodialer-restore << 'SCRIPT_EOF'
#!/bin/bash
# AutoDialer Ultimate — восстановление из бэкапа, созданного autodialer-backup.
# Использование: autodialer-restore <TIMESTAMP> [--yes]

set -euo pipefail

ENV_FILE="/opt/autodialer/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

DB_NAME="${DB_NAME:-autodialer}"
DB_USER="${DB_USER:-autodialer}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-/opt/autodialer/backups}"
TTS_DIR="${TTS_DIR:-/var/lib/asterisk/sounds/tts}"
RECORDINGS_DIR="${RECORDINGS_DIR:-/var/spool/asterisk/monitor}"

usage() {
    echo "Использование: autodialer-restore <TIMESTAMP> [--yes]"
    echo ""
    echo "  <TIMESTAMP>  метка времени бэкапа, например 20260810_020000"
    echo "               (совпадает с суффиксом файлов в $BACKUP_DIR)"
    echo "  --yes        не спрашивать подтверждения (для автоматизации)"
    echo ""
    echo "Доступные бэкапы БД:"
    ls -1 "$BACKUP_DIR"/db_*.dump 2>/dev/null | sed 's#.*/db_##; s#\.dump$##' || echo "  (нет)"
    exit 1
}

[ $# -ge 1 ] || usage
TIMESTAMP="$1"
ASSUME_YES=false
[ "${2:-}" = "--yes" ] && ASSUME_YES=true

DB_DUMP="$BACKUP_DIR/db_${TIMESTAMP}.dump"
TTS_ARCHIVE="$BACKUP_DIR/tts_audio_${TIMESTAMP}.tar.gz"
REC_ARCHIVE="$BACKUP_DIR/call_recordings_${TIMESTAMP}.tar.gz"

[ -f "$DB_DUMP" ] || { echo "Не найден дамп БД: $DB_DUMP" >&2; usage; }

echo "Будет восстановлено из бэкапа $TIMESTAMP:"
echo "  БД:               $DB_DUMP"
if [ -f "$TTS_ARCHIVE" ]; then echo "  tts_audio:        $TTS_ARCHIVE"; else echo "  tts_audio:        (в этом бэкапе отсутствует, пропуск)"; fi
if [ -f "$REC_ARCHIVE" ]; then echo "  call_recordings:  $REC_ARCHIVE"; else echo "  call_recordings:  (в этом бэкапе отсутствует, пропуск)"; fi
echo ""
echo "ВНИМАНИЕ: это ЗАМЕНИТ текущее содержимое БД '$DB_NAME' и указанных каталогов."

if [ "$ASSUME_YES" != "true" ]; then
    read -r -p "Продолжить? (yes/no): " CONFIRM
    [ "$CONFIRM" = "yes" ] || { echo "Отменено"; exit 1; }
fi

echo "Останавливаю backend (systemctl stop autodialer)..."
systemctl stop autodialer 2>/dev/null || echo "  (сервис autodialer не найден/не запущен, пропуск)"

echo "Восстанавливаю БД..."
PGPASSWORD="$DB_PASSWORD" pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner "$DB_DUMP"
echo "  БД восстановлена"

if [ -f "$TTS_ARCHIVE" ]; then
    echo "Восстанавливаю tts_audio..."
    tar xzf "$TTS_ARCHIVE" -C "$(dirname "$TTS_DIR")"
    echo "  tts_audio восстановлен"
fi

if [ -f "$REC_ARCHIVE" ]; then
    echo "Восстанавливаю call_recordings..."
    tar xzf "$REC_ARCHIVE" -C "$(dirname "$RECORDINGS_DIR")"
    echo "  call_recordings восстановлены"
fi

echo "Запускаю backend (systemctl start autodialer)..."
systemctl start autodialer 2>/dev/null || echo "  (сервис autodialer не найден, запустите вручную)"

echo ""
echo "Восстановление завершено. Проверьте: curl http://localhost/api/health"
SCRIPT_EOF
    chmod 750 /usr/local/bin/autodialer-restore
    chown root:autodialer /usr/local/bin/autodialer-restore 2>/dev/null || true
    log_success "Установлен /usr/local/bin/autodialer-restore"
}

# =============================================
# Расписание (cron)
# =============================================
setup_cron() {
    log_step "Настройка расписания..."
    if [ "$AUTO_BACKUP_ENABLED" = "true" ]; then
        cat > /etc/cron.d/autodialer-backup << CRON_EOF
# AutoDialer Ultimate — автоматическое резервное копирование.
# Управляется scripts/15_backup_setup.sh; расписание берётся из BACKUP_SCHEDULE в .env
$BACKUP_SCHEDULE root /usr/local/bin/autodialer-backup >> /opt/autodialer/logs/backup.log 2>&1
CRON_EOF
        chmod 644 /etc/cron.d/autodialer-backup
        log_success "Cron job установлен: $BACKUP_SCHEDULE"
    else
        rm -f /etc/cron.d/autodialer-backup
        log_warn "AUTO_BACKUP_ENABLED=false — cron job не установлен"
        log_info "Бэкапы можно запускать вручную (autodialer-backup) или своим планировщиком"
        log_info "Чтобы включить автоматически: добавьте AUTO_BACKUP_ENABLED=true в .env и перезапустите этот скрипт"
    fi
}

# =============================================
# Маркер установки
# =============================================
mark_configured() {
    mkdir -p /opt/autodialer
    cat > "$INSTALLED_MARKER" << EOF
Backup configured at $(date)
BACKUP_DIR: $BACKUP_DIR
BACKUP_RETENTION: $BACKUP_RETENTION days
AUTO_BACKUP_ENABLED: $AUTO_BACKUP_ENABLED
BACKUP_SCHEDULE: $BACKUP_SCHEDULE
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
    echo -e "${GREEN}${BOLD}✅ Резервное копирование настроено!${NC}"
    echo "=============================================="
    echo ""
    echo "Директория бэкапов: $BACKUP_DIR"
    echo "Хранение:           $BACKUP_RETENTION дней"
    echo "Автозапуск:         $AUTO_BACKUP_ENABLED $([ "$AUTO_BACKUP_ENABLED" = "true" ] && echo "($BACKUP_SCHEDULE)" || echo "(отключён)")"
    echo ""
    echo "Команды:"
    echo "  autodialer-backup                    - выполнить бэкап сейчас"
    echo "  autodialer-restore <TIMESTAMP>        - восстановить из бэкапа"
    echo "  autodialer-restore <TIMESTAMP> --yes   - без подтверждения"
    echo "  ls $BACKUP_DIR                       - список бэкапов"
    echo ""
    echo "Проверка (рекомендуется сразу после установки):"
    echo "  autodialer-backup && ls -la $BACKUP_DIR"
    echo ""
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Backup Setup${NC}"
    echo "=============================================="
    echo ""

    check_already_configured
    check_dependencies
    create_backup_dir
    install_backup_script
    install_restore_script
    setup_cron
    mark_configured
    print_summary
}

main "$@"
