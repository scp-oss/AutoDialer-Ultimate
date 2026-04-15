#!/bin/bash
# Python Backend Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Setting up Python backend..."

# Create user
useradd -r autodialer -s /bin/false || true

# Create directories
mkdir -p /opt/autodialer/{backend,logs,config,frontend/dist}
chown -R autodialer:autodialer /opt/autodialer

# Create virtual environment
cd /opt/autodialer
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r "$SCRIPT_DIR/../backend/requirements.txt"

# Copy backend files
cp "$SCRIPT_DIR/../backend/"*.py /opt/autodialer/backend/

# Generate secrets
if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/../.env"
fi

if [ -z "$AMI_PASSWORD" ]; then
    AMI_PASSWORD=$(openssl rand -hex 16)
    echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/../.env"
fi

if [ -z "$METRICS_PASS" ]; then
    METRICS_PASS=$(openssl rand -hex 8)
    echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/../.env"
fi

# Create .env file
cat > /opt/autodialer/config/.env << EOF
FREEPBX_HOST=${FREEPBX_IP}
FREEPBX_EXTENSION=291

AMI_HOST=127.0.0.1
AMI_PORT=5038
AMI_USER=autodialer
AMI_PASSWORD=${AMI_PASSWORD}

DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=autodialer
DB_USER=autodialer
DB_PASSWORD=${DB_PASSWORD}

REDIS_HOST=127.0.0.1
REDIS_PORT=6379

JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE=3600
REFRESH_TOKEN_EXPIRE=604800

MAX_CALLS=${MAX_CALLS:-50}
DEFAULT_CPS=${DEFAULT_CPS:-5}
CALL_TIMEOUT=${CALL_TIMEOUT:-30}
MAX_RETRIES=${MAX_RETRIES:-3}

TTS_ENGINE=piper
TTS_MODEL=/var/lib/asterisk/sounds/tts/models/ru_RU-${TTS_VOICE:-denis}-medium.onnx
TTS_OUTPUT_DIR=/var/lib/asterisk/sounds/tts

METRICS_USER=${METRICS_USER:-admin}
METRICS_PASS=${METRICS_PASS}

CORS_ORIGINS=*

LOG_LEVEL=INFO
LOG_FILE=/opt/autodialer/logs/autodialer.log
EOF

chown -R autodialer:autodialer /opt/autodialer

print_success "Python backend configured"
