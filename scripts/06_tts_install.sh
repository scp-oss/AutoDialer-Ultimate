#!/bin/bash
# Piper TTS Installation

set -e
source "$SCRIPT_DIR/../.env"

print_step "Installing Piper TTS..."

cd /tmp
wget -q https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz
tar -xzf piper_linux_x86_64.tar.gz -C /usr/local/bin/
chmod +x /usr/local/bin/piper

# Create directories
mkdir -p /var/lib/asterisk/sounds/tts/{models,campaigns}

# Download Russian voices
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx \
    -O /var/lib/asterisk/sounds/tts/models/ru_RU-denis-medium.onnx
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json \
    -O /var/lib/asterisk/sounds/tts/models/ru_RU-denis-medium.onnx.json
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx \
    -O /var/lib/asterisk/sounds/tts/models/ru_RU-irina-medium.onnx
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json \
    -O /var/lib/asterisk/sounds/tts/models/ru_RU-irina-medium.onnx.json

# Generate default audio files
VOICE="${TTS_VOICE:-denis}"
MODEL="/var/lib/asterisk/sounds/tts/models/ru_RU-${VOICE}-medium.onnx"

echo "Здравствуйте! Для подтверждения нажмите 1, для отказа нажмите 2." | \
    piper --model "$MODEL" --output_file /var/lib/asterisk/sounds/tts/main_1.wav

echo "Спасибо за подтверждение!" | \
    piper --model "$MODEL" --output_file /var/lib/asterisk/sounds/tts/thanks_1.wav

echo "Всего доброго!" | \
    piper --model "$MODEL" --output_file /var/lib/asterisk/sounds/tts/goodbye_1.wav

echo "Время ожидания истекло." | \
    piper --model "$MODEL" --output_file /var/lib/asterisk/sounds/tts/timeout_1.wav

echo "Пожалуйста, нажмите 1 для подтверждения или 2 для отказа." | \
    piper --model "$MODEL" --output_file /var/lib/asterisk/sounds/tts/default.wav

# Convert to SLN
for f in /var/lib/asterisk/sounds/tts/*.wav; do
    [ -f "$f" ] && sox "$f" -r 8000 -c 1 "${f%.wav}.sln" && rm "$f"
done

chown -R asterisk:asterisk /var/lib/asterisk/sounds/tts

print_success "Piper TTS installed"
