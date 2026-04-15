#!/bin/bash
# =============================================
# Python Backend Setup
# =============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../.env"

print_step() { echo -e "\033[32m[STEP]\033[0m $1"; }
print_success() { echo -e "\033[36m[SUCCESS]\033[0m $1"; }

print_step "Creating autodialer user..."
useradd -r autodialer -s /bin/false 2>/dev/null || true

print_step "Creating directories..."
mkdir -p /opt/autodialer/{backend,logs,config,frontend/dist,scripts}
chown -R autodialer:autodialer /opt/autodialer

print_step "Setting up Python virtual environment..."
cd /opt/autodialer
python3 -m venv venv
source venv/bin/activate

print_step "Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/../backend/requirements.txt"

print_step "Copying backend files..."
cp "$SCRIPT_DIR/../backend/"*.py /opt/autodialer/backend/ 2>/dev/null || true

print_step "Creating .env configuration..."
cat > /opt/autodialer/config/.env << EOF
# Server
FREEPBX_HOST=${FREEPBX_IP}
FREEPBX_EXTENSION=291

# AMI
AMI_HOST=127.0.0.1
AMI_PORT=5038
AMI_USER=autodialer
AMI_PASSWORD=${AMI_PASSWORD}

# Database
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=autodialer
DB_USER=autodialer
DB_PASSWORD=${DB_PASSWORD}

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# JWT
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE=3600
REFRESH_TOKEN_EXPIRE=604800

# Dialer
MAX_CALLS=${MAX_CALLS:-50}
DEFAULT_CPS=${DEFAULT_CPS:-5}
CALL_TIMEOUT=30
MAX_RETRIES=3

# TTS
TTS_ENGINE=piper
TTS_MODEL=/var/lib/asterisk/sounds/tts/models/ru_RU-${TTS_VOICE:-denis}-medium.onnx
TTS_OUTPUT_DIR=/var/lib/asterisk/sounds/tts

# Metrics
METRICS_USER=admin
METRICS_PASS=${METRICS_PASS}

# CORS
CORS_ORIGINS=*

# Logging
LOG_LEVEL=INFO
LOG_FILE=/opt/autodialer/logs/autodialer.log
EOF

chown -R autodialer:autodialer /opt/autodialer/config

print_success "Python backend setup complete"
