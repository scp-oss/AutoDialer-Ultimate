#!/bin/bash
# =============================================
# AutoDialer Ultimate - Установка TTS (Piper)
# Версия: 3.0.0
# =============================================
# Устанавливает Piper TTS, скачивает русские голоса,
# генерирует базовые аудиофайлы и конвертирует в SLN
# =============================================

set -euo pipefail

# =============================================
# Цвета и логирование
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

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "\n${BOLD}${CYAN}▶ $*${NC}"; }

# =============================================
# Загрузка конфигурации
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

# Установка значений по умолчанию
TTS_VOICE="${TTS_VOICE:-denis}"
TTS_DIR="/var/lib/asterisk/sounds/tts"
MODELS_DIR="${TTS_DIR}/models"
PIPER_VERSION="latest"
PIPER_DOWNLOAD_URL="https://github.com/rhasspy/piper/releases/${PIPER_VERSION}/download/piper_linux_x86_64.tar.gz"

log_info "Голос по умолчанию: $TTS_VOICE"
log_info "Директория TTS: $TTS_DIR"

# =============================================
# Проверка идемпотентности
# =============================================
if command -v piper &>/dev/null && [ -f "${TTS_DIR}/main_1.sln" ]; then
    PIPER_VERSION_INSTALLED=$(piper --version 2>/dev/null || echo "unknown")
    log_warn "Piper TTS уже установлен ($PIPER_VERSION_INSTALLED)"
    log_info "Пропускаю установку..."
    exit 0
fi

# =============================================
# Установка Piper
# =============================================
install_piper() {
    log_step "Установка Piper TTS..."
    
    # Создание временной директории
    TMP_DIR=$(mktemp -d)
    cd "$TMP_DIR"
    
    # Скачивание с повторными попытками
    for i in {1..3}; do
        if wget -q --show-progress "$PIPER_DOWNLOAD_URL" -O piper.tar.gz; then
            log_success "Piper скачан"
            break
        fi
        log_warn "Попытка $i не удалась, повтор через 5 сек..."
        sleep 5
        if [ $i -eq 3 ]; then
            log_error "Не удалось скачать Piper"
            rm -rf "$TMP_DIR"
            return 1
        fi
    done
    
    # Распаковка. Архив содержит не один бинарник, а директорию piper/ с
    # самим исполняемым файлом ВМЕСТЕ с библиотеками, от которых он
    # зависит через relative rpath ($ORIGIN) - libpiper_phonemize.so*,
    # libespeak-ng.so*, libtashkeel_model.ort, espeak-ng-data/ (проверено
    # напрямую: `tar -tzf piper_linux_x86_64.tar.gz` выводит именно такую
    # структуру). Прежняя версия распаковывала архив прямо в
    # /usr/local/bin/, из-за чего там создавалась ДИРЕКТОРИЯ piper/, а не
    # исполняемый файл - `command -v piper` её не находил, и установка
    # всегда проваливалась именно на этом шаге, даже не доходя до
    # скачивания голосовых моделей ниже.
    rm -rf /opt/piper
    mkdir -p /opt/piper
    tar -xzf piper.tar.gz -C /opt/piper --strip-components=1

    # `ln -sf` does NOT replace an existing DIRECTORY at the target path
    # - it silently creates the symlink INSIDE it instead
    # (/usr/local/bin/piper/piper), leaving /usr/local/bin/piper itself
    # as a directory. Every install attempt before this fix used the old
    # buggy extraction that left exactly that kind of leftover directory
    # at /usr/local/bin/piper - confirmed live, this is why `command -v
    # piper` kept failing even after the extraction itself was fixed.
    # rm -f alone can't remove a directory either, hence -rf here.
    rm -rf /usr/local/bin/piper
    ln -sf /opt/piper/piper /usr/local/bin/piper

    # Очистка
    cd /
    rm -rf "$TMP_DIR"
    
    # Проверка установки
    if command -v piper &>/dev/null; then
        PIPER_VERSION_INSTALLED=$(piper --version 2>/dev/null || echo "unknown")
        log_success "Piper установлен: $PIPER_VERSION_INSTALLED"
    else
        log_error "Не удалось установить Piper"
        return 1
    fi
}

# =============================================
# Создание директорий
# =============================================
create_directories() {
    log_step "Создание директорий..."
    
    mkdir -p "$MODELS_DIR"
    mkdir -p "${TTS_DIR}/campaigns"
    
    log_success "Директории созданы"
}

# =============================================
# Скачивание голосовых моделей
# =============================================
download_models() {
    log_step "Скачивание голосовых моделей..."
    
    # Denis (мужской голос)
    if [ ! -f "${MODELS_DIR}/ru_RU-denis-medium.onnx" ]; then
        log_info "Скачивание Denis..."
        wget -q --show-progress \
            https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx \
            -O "${MODELS_DIR}/ru_RU-denis-medium.onnx" || log_warn "Не удалось скачать Denis"
    else
        log_info "Denis уже скачан"
    fi
    
    if [ ! -f "${MODELS_DIR}/ru_RU-denis-medium.onnx.json" ]; then
        wget -q \
            https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json \
            -O "${MODELS_DIR}/ru_RU-denis-medium.onnx.json" 2>/dev/null || true
    fi
    
    # Irina (женский голос)
    if [ ! -f "${MODELS_DIR}/ru_RU-irina-medium.onnx" ]; then
        log_info "Скачивание Irina..."
        wget -q --show-progress \
            https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx \
            -O "${MODELS_DIR}/ru_RU-irina-medium.onnx" || log_warn "Не удалось скачать Irina"
    fi
    
    if [ ! -f "${MODELS_DIR}/ru_RU-irina-medium.onnx.json" ]; then
        wget -q \
            https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json \
            -O "${MODELS_DIR}/ru_RU-irina-medium.onnx.json" 2>/dev/null || true
    fi
    
    log_success "Модели скачаны"
}

# =============================================
# Генерация базовых аудиофайлов
# =============================================
generate_default_audio() {
    log_step "Генерация базовых аудиофайлов..."
    
    MODEL="${MODELS_DIR}/ru_RU-${TTS_VOICE}-medium.onnx"
    
    if [ ! -f "$MODEL" ]; then
        log_warn "Модель $TTS_VOICE не найдена, использую denis"
        MODEL="${MODELS_DIR}/ru_RU-denis-medium.onnx"
    fi
    
    if [ ! -f "$MODEL" ]; then
        log_error "Нет доступных моделей TTS"
        return 1
    fi
    
    # Основное сообщение
    if [ ! -f "${TTS_DIR}/main_1.sln" ]; then
        log_info "Генерация main_1..."
        echo "Здравствуйте! Для подтверждения нажмите 1, для отказа нажмите 2." | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/main_1.wav" -q 2>/dev/null || true
    fi
    
    # Благодарность
    if [ ! -f "${TTS_DIR}/thanks_1.sln" ]; then
        log_info "Генерация thanks_1..."
        echo "Спасибо за подтверждение! Всего доброго!" | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/thanks_1.wav" -q 2>/dev/null || true
    fi
    
    # Отказ
    if [ ! -f "${TTS_DIR}/goodbye_1.sln" ]; then
        log_info "Генерация goodbye_1..."
        echo "Вы отказались. Всего доброго!" | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/goodbye_1.wav" -q 2>/dev/null || true
    fi
    
    # Таймаут
    if [ ! -f "${TTS_DIR}/timeout_1.sln" ]; then
        log_info "Генерация timeout_1..."
        echo "Время ожидания истекло. До свидания!" | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/timeout_1.wav" -q 2>/dev/null || true
    fi
    
    # Запасное сообщение
    if [ ! -f "${TTS_DIR}/default.sln" ]; then
        log_info "Генерация default..."
        echo "Пожалуйста, нажмите 1 для подтверждения или 2 для отказа." | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/default.wav" -q 2>/dev/null || true
    fi
    
    # Оператор
    if [ ! -f "${TTS_DIR}/operator_default.sln" ]; then
        log_info "Генерация operator_default..."
        echo "Пожалуйста, ожидайте соединения с оператором." | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/operator_default.wav" -q 2>/dev/null || true
    fi
    
    # Неверный ввод
    if [ ! -f "${TTS_DIR}/invalid.sln" ]; then
        log_info "Генерация invalid..."
        echo "Неверный ввод." | \
            piper --model "$MODEL" --output_file "${TTS_DIR}/invalid.wav" -q 2>/dev/null || true
    fi
    
    log_success "Аудиофайлы сгенерированы"
}

# =============================================
# Конвертация WAV в SLN
# =============================================
convert_to_sln() {
    log_step "Конвертация WAV в SLN..."
    
    converted=0
    for wav in "${TTS_DIR}"/*.wav; do
        if [ -f "$wav" ]; then
            sln="${wav%.wav}.sln"
            if [ ! -f "$sln" ] || [ "$wav" -nt "$sln" ]; then
                if sox "$wav" -r 8000 -c 1 -t raw -e signed-integer "$sln" 2>/dev/null; then
                    converted=$((converted + 1))
                else
                    log_warn "Не удалось конвертировать $(basename "$wav")"
                fi
            fi
            rm -f "$wav"
        fi
    done
    
    log_success "Конвертировано $converted файлов в SLN"
}

# =============================================
# Создание симлинков для fallback
# =============================================
create_symlinks() {
    log_step "Создание симлинков..."
    
    if [ -f "${TTS_DIR}/thanks_1.sln" ] && [ ! -f "${TTS_DIR}/thanks_default.sln" ]; then
        ln -sf thanks_1.sln "${TTS_DIR}/thanks_default.sln"
    fi
    
    if [ -f "${TTS_DIR}/goodbye_1.sln" ] && [ ! -f "${TTS_DIR}/goodbye_default.sln" ]; then
        ln -sf goodbye_1.sln "${TTS_DIR}/goodbye_default.sln"
    fi
    
    if [ -f "${TTS_DIR}/timeout_1.sln" ] && [ ! -f "${TTS_DIR}/timeout_default.sln" ]; then
        ln -sf timeout_1.sln "${TTS_DIR}/timeout_default.sln"
    fi
    
    log_success "Симлинки созданы"
}

# =============================================
# Установка прав
# =============================================
set_permissions() {
    log_step "Установка прав доступа..."
    
    chown -R asterisk:asterisk "$TTS_DIR" 2>/dev/null || true
    # 775, not 755: CampaignService._link_campaign_audio (app/services/
    # campaign.py) symlinks the campaign's chosen audio file into this
    # directory on every campaign start, running as the `autodialer`
    # user (systemd User=autodialer) - now a member of the `asterisk`
    # group (see install.sh's create_user()). Creating/replacing a
    # symlink needs WRITE on the *directory*, which a group-read-only
    # 755 never grants regardless of group membership.
    chmod -R 775 "$TTS_DIR"
    find "$TTS_DIR" -name "*.sln" -exec chmod 644 {} \; 2>/dev/null || true
    
    log_success "Права установлены"
}

# =============================================
# Создание хелпер-скрипта
# =============================================
create_helper_script() {
    log_step "Создание хелпер-скрипта..."
    
    cat > /usr/local/bin/autodialer-tts << 'EOF'
#!/bin/bash
# AutoDialer TTS Helper

TTS_DIR="/var/lib/asterisk/sounds/tts"
MODELS_DIR="${TTS_DIR}/models"
DEFAULT_VOICE="${TTS_VOICE:-denis}"

usage() {
    echo "Использование: $0 [опции] <текст>"
    echo ""
    echo "Опции:"
    echo "  -o, --output FILE    Имя выходного файла (без расширения)"
    echo "  -v, --voice VOICE    Голос (denis, irina) [по умолчанию: $DEFAULT_VOICE]"
    echo "  -c, --campaign ID    ID кампании (сохраняет в campaigns/ID/)"
    echo "  -h, --help           Показать справку"
    echo ""
    echo "Пример:"
    echo "  $0 -o welcome -v denis \"Здравствуйте!\""
}

OUTPUT=""
VOICE="$DEFAULT_VOICE"
CAMPAIGN_ID=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -o|--output)
            OUTPUT="$2"
            shift 2
            ;;
        -v|--voice)
            VOICE="$2"
            shift 2
            ;;
        -c|--campaign)
            CAMPAIGN_ID="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            TEXT="$1"
            shift
            ;;
    esac
done

if [ -z "${TEXT:-}" ]; then
    echo "Ошибка: Не указан текст"
    usage
    exit 1
fi

if [ -z "$OUTPUT" ]; then
    OUTPUT="tts_$(date +%s)"
fi

if [ -n "$CAMPAIGN_ID" ]; then
    OUT_DIR="${TTS_DIR}/campaigns/${CAMPAIGN_ID}"
    mkdir -p "$OUT_DIR"
else
    OUT_DIR="$TTS_DIR"
fi

MODEL="${MODELS_DIR}/ru_RU-${VOICE}-medium.onnx"

if [ ! -f "$MODEL" ]; then
    echo "Ошибка: Модель не найдена: $MODEL"
    exit 1
fi

WAV_FILE="${OUT_DIR}/${OUTPUT}.wav"
SLN_FILE="${OUT_DIR}/${OUTPUT}.sln"

echo "$TEXT" | piper --model "$MODEL" --output_file "$WAV_FILE" -q

if [ $? -ne 0 ]; then
    echo "Ошибка генерации TTS"
    exit 1
fi

sox "$WAV_FILE" -r 8000 -c 1 -t raw -e signed-integer "$SLN_FILE" 2>/dev/null
rm -f "$WAV_FILE"

chown asterisk:asterisk "$SLN_FILE" 2>/dev/null || true
chmod 644 "$SLN_FILE"

echo "Сгенерирован: $SLN_FILE"
EOF
    
    chmod +x /usr/local/bin/autodialer-tts
    log_success "Хелпер-скрипт создан: /usr/local/bin/autodialer-tts"
}

# =============================================
# Проверка установки
# =============================================
verify_installation() {
    log_step "Проверка установки..."
    
    local all_ok=true
    
    # Проверка Piper
    if command -v piper &>/dev/null; then
        log_success "✓ Piper установлен"
    else
        log_error "✗ Piper не найден"
        all_ok=false
    fi
    
    # Проверка моделей
    if [ -f "${MODELS_DIR}/ru_RU-denis-medium.onnx" ]; then
        log_success "✓ Модель Denis"
    else
        log_warn "✗ Модель Denis отсутствует"
    fi
    
    if [ -f "${MODELS_DIR}/ru_RU-irina-medium.onnx" ]; then
        log_success "✓ Модель Irina"
    else
        log_warn "✗ Модель Irina отсутствует"
    fi
    
    # Проверка аудиофайлов
    for file in main_1 thanks_1 goodbye_1 timeout_1 default; do
        if [ -f "${TTS_DIR}/${file}.sln" ]; then
            log_success "✓ ${file}.sln"
        else
            log_warn "✗ ${file}.sln отсутствует"
        fi
    done
    
    if [ "$all_ok" = true ]; then
        log_success "Проверка пройдена"
    else
        log_warn "Есть проблемы с установкой"
    fi
}

# =============================================
# Главная функция
# =============================================
main() {
    log_step "Установка Piper TTS..."
    
    install_piper || {
        log_error "Не удалось установить Piper"
        exit 1
    }
    
    create_directories
    download_models
    generate_default_audio
    convert_to_sln
    create_symlinks
    set_permissions
    create_helper_script
    verify_installation
    
    echo ""
    log_success "=============================================="
    log_success "Установка Piper TTS завершена!"
    log_success "=============================================="
    echo ""
    log_info "Доступные голоса: denis (мужской), irina (женский)"
    log_info "Голос по умолчанию: $TTS_VOICE"
    log_info "Директория: $TTS_DIR"
    log_info "Хелпер: /usr/local/bin/autodialer-tts"
    echo ""
}

main "$@"
