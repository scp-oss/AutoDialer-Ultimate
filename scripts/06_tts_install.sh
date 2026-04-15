#!/bin/bash
# =============================================
# AutoDialer Ultimate - TTS Installation (Piper)
# Version: 3.0.0
# =============================================

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[STEP]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${CYAN}[SUCCESS]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Configuration
# =============================================
PIPER_VERSION="latest"
PIPER_DOWNLOAD_URL="https://github.com/rhasspy/piper/releases/${PIPER_VERSION}/download/piper_linux_x86_64.tar.gz"
PIPER_INSTALL_DIR="/usr/local/bin"
TTS_DIR="/var/lib/asterisk/sounds/tts"
MODELS_DIR="${TTS_DIR}/models"
CAMPAIGNS_DIR="${TTS_DIR}/campaigns"

# Voice models
VOICE_DENIS_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx"
VOICE_DENIS_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json"
VOICE_IRINA_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
VOICE_IRINA_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json"

# Default voice
DEFAULT_VOICE="${TTS_VOICE:-denis}"

# =============================================
# Install Piper TTS
# =============================================
print_step "Installing Piper TTS..."

# Download Piper
cd /tmp
print_info "Downloading Piper from $PIPER_DOWNLOAD_URL"
wget -q --show-progress "$PIPER_DOWNLOAD_URL" -O piper.tar.gz

# Extract
print_info "Extracting Piper..."
tar -xzf piper.tar.gz -C "$PIPER_INSTALL_DIR"
chmod +x "${PIPER_INSTALL_DIR}/piper"

# Clean up
rm -f piper.tar.gz

# Verify installation
if command -v piper &> /dev/null; then
    PIPER_VERSION_INSTALLED=$(piper --version 2>/dev/null || echo "unknown")
    print_success "Piper installed: $PIPER_VERSION_INSTALLED"
else
    print_error "Piper installation failed"
    exit 1
fi

# =============================================
# Create Directories
# =============================================
print_step "Creating TTS directories..."

mkdir -p "$MODELS_DIR"
mkdir -p "$CAMPAIGNS_DIR"

print_success "Directories created"

# =============================================
# Download Voice Models
# =============================================
print_step "Downloading Russian voice models..."

# Denis voice (male)
print_info "Downloading Denis voice (male)..."
wget -q --show-progress "$VOICE_DENIS_URL" -O "${MODELS_DIR}/ru_RU-denis-medium.onnx"
wget -q --show-progress "$VOICE_DENIS_JSON_URL" -O "${MODELS_DIR}/ru_RU-denis-medium.onnx.json"
print_success "Denis voice downloaded"

# Irina voice (female)
print_info "Downloading Irina voice (female)..."
wget -q --show-progress "$VOICE_IRINA_URL" -O "${MODELS_DIR}/ru_RU-irina-medium.onnx"
wget -q --show-progress "$VOICE_IRINA_JSON_URL" -O "${MODELS_DIR}/ru_RU-irina-medium.onnx.json"
print_success "Irina voice downloaded"

# =============================================
# Download English Voice (Optional)
# =============================================
print_info "Downloading English voice (optional)..."
VOICE_EN_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
VOICE_EN_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

wget -q "$VOICE_EN_URL" -O "${MODELS_DIR}/en_US-lessac-medium.onnx" 2>/dev/null || print_warn "English voice not downloaded"
wget -q "$VOICE_EN_JSON_URL" -O "${MODELS_DIR}/en_US-lessac-medium.onnx.json" 2>/dev/null || true

# =============================================
# Generate Default Audio Files
# =============================================
print_step "Generating default audio files..."

MODEL="${MODELS_DIR}/ru_RU-${DEFAULT_VOICE}-medium.onnx"

# Main message
print_info "Generating main message..."
echo "Здравствуйте! Для подтверждения нажмите 1, для отказа нажмите 2." | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/main_1.wav" --quiet

# Thanks message
print_info "Generating thanks message..."
echo "Спасибо за подтверждение! Всего доброго!" | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/thanks_1.wav" --quiet

# Goodbye message
print_info "Generating goodbye message..."
echo "Вы отказались. Всего доброго!" | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/goodbye_1.wav" --quiet

# Timeout message
print_info "Generating timeout message..."
echo "Время ожидания истекло. До свидания!" | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/timeout_1.wav" --quiet

# Default message (fallback)
print_info "Generating default message..."
echo "Пожалуйста, нажмите 1 для подтверждения или 2 для отказа." | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/default.wav" --quiet

# Operator message
print_info "Generating operator message..."
echo "Пожалуйста, ожидайте соединения с оператором." | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/operator_default.wav" --quiet

# Invalid input message
print_info "Generating invalid input message..."
echo "Неверный ввод." | \
    piper --model "$MODEL" --output_file "${TTS_DIR}/invalid.wav" --quiet

print_success "Default audio files generated"

# =============================================
# Convert WAV to SLN (Asterisk native format)
# =============================================
print_step "Converting audio files to Asterisk SLN format..."

convert_to_sln() {
    local wav_file="$1"
    local sln_file="${wav_file%.wav}.sln"
    
    if [ -f "$wav_file" ]; then
        sox "$wav_file" -r 8000 -c 1 -t raw -e signed-integer "$sln_file" 2>/dev/null || {
            print_warn "Failed to convert $(basename $wav_file)"
            return 1
        }
        rm -f "$wav_file"
        return 0
    fi
    return 1
}

converted=0
for wav in "${TTS_DIR}"/*.wav; do
    if [ -f "$wav" ]; then
        if convert_to_sln "$wav"; then
            ((converted++))
        fi
    fi
done

print_success "Converted $converted files to SLN format"

# =============================================
# Create Thanks Default
# =============================================
if [ ! -f "${TTS_DIR}/thanks_default.sln" ]; then
    ln -sf "${TTS_DIR}/thanks_1.sln" "${TTS_DIR}/thanks_default.sln"
fi

if [ ! -f "${TTS_DIR}/goodbye_default.sln" ]; then
    ln -sf "${TTS_DIR}/goodbye_1.sln" "${TTS_DIR}/goodbye_default.sln"
fi

if [ ! -f "${TTS_DIR}/timeout_default.sln" ]; then
    ln -sf "${TTS_DIR}/timeout_1.sln" "${TTS_DIR}/timeout_default.sln"
fi

# =============================================
# Set Permissions
# =============================================
print_step "Setting permissions..."

chown -R asterisk:asterisk "$TTS_DIR"
chmod -R 755 "$TTS_DIR"
chmod -R 644 "${TTS_DIR}"/*.sln 2>/dev/null || true

print_success "Permissions set"

# =============================================
# Create TTS Helper Script
# =============================================
print_step "Creating TTS helper script..."

cat > /usr/local/bin/autodialer-tts << 'EOF'
#!/bin/bash
# AutoDialer TTS Helper Script

TTS_DIR="/var/lib/asterisk/sounds/tts"
MODELS_DIR="${TTS_DIR}/models"
DEFAULT_VOICE="${TTS_VOICE:-denis}"

usage() {
    echo "Usage: $0 [options] <text>"
    echo ""
    echo "Options:"
    echo "  -o, --output FILE    Output file name (without extension)"
    echo "  -v, --voice VOICE    Voice to use (denis, irina) [default: $DEFAULT_VOICE]"
    echo "  -c, --campaign ID    Campaign ID (saves to campaigns directory)"
    echo "  -h, --help           Show this help"
    echo ""
    echo "Example:"
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

if [ -z "$TEXT" ]; then
    echo "Error: No text provided"
    usage
    exit 1
fi

if [ -z "$OUTPUT" ]; then
    OUTPUT="tts_$(date +%s)"
fi

# Determine output directory
if [ -n "$CAMPAIGN_ID" ]; then
    OUT_DIR="${TTS_DIR}/campaigns/${CAMPAIGN_ID}"
    mkdir -p "$OUT_DIR"
else
    OUT_DIR="$TTS_DIR"
fi

MODEL="${MODELS_DIR}/ru_RU-${VOICE}-medium.onnx"

if [ ! -f "$MODEL" ]; then
    echo "Error: Voice model not found: $MODEL"
    exit 1
fi

WAV_FILE="${OUT_DIR}/${OUTPUT}.wav"
SLN_FILE="${OUT_DIR}/${OUTPUT}.sln"

# Generate audio
echo "$TEXT" | piper --model "$MODEL" --output_file "$WAV_FILE" --quiet

if [ $? -ne 0 ]; then
    echo "Error: TTS generation failed"
    exit 1
fi

# Convert to SLN
sox "$WAV_FILE" -r 8000 -c 1 -t raw -e signed-integer "$SLN_FILE" 2>/dev/null
rm -f "$WAV_FILE"

# Set permissions
chown asterisk:asterisk "$SLN_FILE"
chmod 644 "$SLN_FILE"

echo "Generated: $SLN_FILE"
EOF

chmod +x /usr/local/bin/autodialer-tts
print_success "TTS helper script created: /usr/local/bin/autodialer-tts"

# =============================================
# Verify Installation
# =============================================
print_step "Verifying TTS installation..."

# Check Piper
if command -v piper &> /dev/null; then
    print_info "  ✓ Piper installed"
else
    print_error "  ✗ Piper not found"
fi

# Check models
if [ -f "${MODELS_DIR}/ru_RU-denis-medium.onnx" ]; then
    print_info "  ✓ Denis model installed"
else
    print_warn "  ✗ Denis model missing"
fi

if [ -f "${MODELS_DIR}/ru_RU-irina-medium.onnx" ]; then
    print_info "  ✓ Irina model installed"
else
    print_warn "  ✗ Irina model missing"
fi

# Check default files
DEFAULT_FILES=("main_1.sln" "thanks_1.sln" "goodbye_1.sln" "timeout_1.sln" "default.sln" "operator_default.sln" "invalid.sln")
for file in "${DEFAULT_FILES[@]}"; do
    if [ -f "${TTS_DIR}/${file}" ]; then
        print_info "  ✓ ${file}"
    else
        print_warn "  ✗ ${file} missing"
    fi
done

# Test TTS generation
print_info "Testing TTS generation..."
TEST_OUTPUT="${TTS_DIR}/test_$(date +%s)"
echo "Тест" | piper --model "$MODEL" --output_file "${TEST_OUTPUT}.wav" --quiet 2>/dev/null
if [ -f "${TEST_OUTPUT}.wav" ]; then
    print_success "  ✓ TTS test passed"
    rm -f "${TEST_OUTPUT}.wav"
else
    print_error "  ✗ TTS test failed"
fi

# =============================================
# Summary
# =============================================
print_success "TTS installation completed!"
echo ""
print_info "Installation Details:"
echo "  Piper: $(piper --version 2>/dev/null || echo 'unknown')"
echo "  Models Directory: $MODELS_DIR"
echo "  Output Directory: $TTS_DIR"
echo "  Campaigns Directory: $CAMPAIGNS_DIR"
echo "  Default Voice: $DEFAULT_VOICE"
echo ""
print_info "Available Voices:"
echo "  - denis (male)"
echo "  - irina (female)"
echo ""
print_info "Default Audio Files:"
for file in "${DEFAULT_FILES[@]}"; do
    if [ -f "${TTS_DIR}/${file}" ]; then
        size=$(du -h "${TTS_DIR}/${file}" | cut -f1)
        echo "  ${file} (${size})"
    fi
done
echo ""
print_info "Helper Script:"
echo "  /usr/local/bin/autodialer-tts"
echo ""
print_info "Usage Examples:"
echo "  # Generate custom TTS"
echo "  autodialer-tts -o welcome -v denis \"Добро пожаловать!\""
echo ""
echo "  # Generate for specific campaign"
echo "  autodialer-tts -c 5 -o campaign_msg \"Текст для кампании 5\""
echo ""
echo "  # Direct Piper usage"
echo "  echo \"Текст\" | piper --model ${MODELS_DIR}/ru_RU-denis-medium.onnx --output_file output.wav"
echo ""
