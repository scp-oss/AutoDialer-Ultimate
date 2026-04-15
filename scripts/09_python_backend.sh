#!/bin/bash
# =============================================
# AutoDialer Ultimate - Python Backend Setup
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
# Load Configuration
# =============================================
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
    print_info "Loaded configuration from .env"
fi

# =============================================
# Create User and Directories
# =============================================
print_step "Creating autodialer user and directories..."

# Create user if not exists
if ! id -u autodialer &>/dev/null; then
    useradd -r -m -d /opt/autodialer -s /bin/false -c "AutoDialer Service" autodialer
    print_success "User 'autodialer' created"
else
    print_info "User 'autodialer' already exists"
fi

# Create directories
mkdir -p /opt/autodialer/{backend,logs,config,frontend/dist,scripts,tmp,venv}
mkdir -p /opt/autodialer/logs/{access,error}

print_success "Directories created"

# =============================================
# Set Up Python Virtual Environment
# =============================================
print_step "Setting up Python virtual environment..."

cd /opt/autodialer

# Create virtual environment
python3 -m venv venv
print_success "Virtual environment created"

# Activate and upgrade pip
source venv/bin/activate
pip install --upgrade pip setuptools wheel
print_success "Pip upgraded"

# =============================================
# Install Python Dependencies
# =============================================
print_step "Installing Python dependencies..."

# Create requirements file
cat > /opt/autodialer/requirements.txt << 'EOF'
# AutoDialer Ultimate Requirements
# Core
fastapi==0.115.11
uvicorn[standard]==0.34.0
pydantic==2.10.6
pydantic-settings==2.7.1

# Database
asyncpg==0.30.0
sqlalchemy==2.0.36
alembic==1.14.1

# Redis
redis==5.2.1
hiredis==2.3.2

# AMI (Asterisk Manager Interface)
panoramisk==0.2.0

# Authentication
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.2.0
python-multipart==0.0.20

# HTTP & WebSocket
httpx==0.28.1
aiofiles==24.1.0
gunicorn==23.0.0

# Monitoring
prometheus-client==0.21.0

# Utilities
cachetools==5.5.0
tenacity==9.0.0
python-dateutil==2.9.0
python-dotenv==1.0.1
PyYAML==6.0.2

# Development (optional)
watchfiles==1.0.4
EOF

# Install requirements
pip install -r requirements.txt
print_success "Python dependencies installed"

# =============================================
# Copy Backend Files
# =============================================
print_step "Copying backend files..."

if [ -d "$PROJECT_ROOT/backend" ]; then
    cp -r "$PROJECT_ROOT/backend/"* /opt/autodialer/backend/
    print_success "Backend files copied"
else
    print_warn "Backend directory not found, creating skeleton..."
    
    # Create minimal main.py
    cat > /opt/autodialer/backend/main.py << 'EOF'
#!/usr/bin/env python3
"""AutoDialer Ultimate - Main Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AutoDialer Ultimate", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}

@app.get("/")
async def root():
    return {"message": "AutoDialer Ultimate API"}
EOF

    # Create __init__.py
    touch /opt/autodialer/backend/__init__.py
    
    print_warn "Created skeleton backend files"
fi

# =============================================
# Create Environment Configuration
# =============================================
print_step "Creating environment configuration..."

# Generate secrets if not set
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
AMI_PASSWORD="${AMI_PASSWORD:-$(openssl rand -hex 16)}"
METRICS_PASS="${METRICS_PASS:-$(openssl rand -hex 8)}"

# Save to .env if not exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    grep -q "^JWT_SECRET=" "$PROJECT_ROOT/.env" || echo "JWT_SECRET=$JWT_SECRET" >> "$PROJECT_ROOT/.env"
    grep -q "^AMI_PASSWORD=" "$PROJECT_ROOT/.env" || echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$PROJECT_ROOT/.env"
    grep -q "^METRICS_PASS=" "$PROJECT_ROOT/.env" || echo "METRICS_PASS=$METRICS_PASS" >> "$PROJECT_ROOT/.env"
fi

# Create .env file for backend
cat > /opt/autodialer/config/.env << EOF
# =============================================
# AutoDialer Ultimate Configuration
# =============================================

# FreePBX Server
FREEPBX_HOST=${FREEPBX_IP:-192.168.1.100}
FREEPBX_EXTENSION=291

# Asterisk AMI
AMI_HOST=127.0.0.1
AMI_PORT=5038
AMI_USER=autodialer
AMI_PASSWORD=${AMI_PASSWORD}

# Database
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=${DB_NAME:-autodialer}
DB_USER=${DB_USER:-autodialer}
DB_PASSWORD=${DB_PASSWORD}

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=${REDIS_PASSWORD:-}

# JWT
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE=3600
REFRESH_TOKEN_EXPIRE=604800

# Dialer Settings
MAX_CALLS=${MAX_CALLS:-50}
DEFAULT_CPS=${DEFAULT_CPS:-5}
CALL_TIMEOUT=30
MAX_RETRIES=3

# TTS Settings
TTS_ENGINE=piper
TTS_VOICE=${TTS_VOICE:-denis}
TTS_MODEL=/var/lib/asterisk/sounds/tts/models/ru_RU-\${TTS_VOICE}-medium.onnx
TTS_OUTPUT_DIR=/var/lib/asterisk/sounds/tts

# Metrics
METRICS_USER=admin
METRICS_PASS=${METRICS_PASS}

# CORS
CORS_ORIGINS=*

# Logging
LOG_LEVEL=${LOG_LEVEL:-INFO}
LOG_FORMAT=${LOG_FORMAT:-console}
LOG_FILE=/opt/autodialer/logs/autodialer.log

# Storage
AUDIO_RETENTION_DAYS=30
MAX_UPLOAD_SIZE_MB=10
EOF

print_success "Environment configuration created"

# =============================================
# Copy Frontend Files
# =============================================
print_step "Copying frontend files..."

if [ -d "$PROJECT_ROOT/frontend/dist" ]; then
    cp -r "$PROJECT_ROOT/frontend/dist/"* /opt/autodialer/frontend/dist/
    print_success "Frontend files copied"
else
    print_warn "Frontend dist not found, creating placeholder..."
    
    cat > /opt/autodialer/frontend/dist/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>AutoDialer Ultimate</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #0f172a; color: #f1f5f9; }
        .container { text-align: center; }
        h1 { color: #667eea; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 AutoDialer Ultimate</h1>
        <p>Version 3.0.0</p>
        <p>Backend is running. Frontend will be available soon.</p>
    </div>
</body>
</html>
EOF
    print_warn "Created placeholder frontend"
fi

# =============================================
# Set Permissions
# =============================================
print_step "Setting permissions..."

chown -R autodialer:autodialer /opt/autodialer
chmod -R 755 /opt/autodialer
chmod 600 /opt/autodialer/config/.env

print_success "Permissions set"

# =============================================
# Create Systemd Service
# =============================================
print_step "Creating systemd service..."

cat > /etc/systemd/system/autodialer.service << EOF
[Unit]
Description=AutoDialer Ultimate Backend Service
Documentation=https://github.com/naumenis-code/AutoDialer-Ultimate
After=network.target postgresql.service redis-server.service asterisk.service
Wants=network-online.target

[Service]
Type=exec
User=autodialer
Group=autodialer
WorkingDirectory=/opt/autodialer/backend
Environment="PATH=/opt/autodialer/venv/bin"
EnvironmentFile=/opt/autodialer/config/.env
ExecStart=/opt/autodialer/venv/bin/gunicorn \
    -w 4 \
    --threads 8 \
    -k uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 \
    --access-logfile /opt/autodialer/logs/access.log \
    --error-logfile /opt/autodialer/logs/error.log \
    --log-level info \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 10000 \
    --max-requests-jitter 1000 \
    main:app
Restart=always
RestartSec=5
LimitNOFILE=655350
LimitNPROC=655350
MemoryMax=2G
CPUQuota=200%
TasksMax=infinity

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
print_success "Systemd service created"

# =============================================
# Create Helper Scripts
# =============================================
print_step "Creating helper scripts..."

# Status script
cat > /usr/local/bin/autodialer-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Ultimate Status"
echo "=============================================="
echo ""
systemctl status autodialer --no-pager -l
echo ""
echo "=============================================="
echo "Recent Logs:"
echo "=============================================="
journalctl -u autodialer -n 20 --no-pager
EOF
chmod +x /usr/local/bin/autodialer-status

# Restart script
cat > /usr/local/bin/autodialer-restart << 'EOF'
#!/bin/bash
systemctl restart autodialer
echo "AutoDialer restarted"
systemctl status autodialer --no-pager
EOF
chmod +x /usr/local/bin/autodialer-restart

# Logs script
cat > /usr/local/bin/autodialer-logs << 'EOF'
#!/bin/bash
journalctl -u autodialer -f
EOF
chmod +x /usr/local/bin/autodialer-logs

print_success "Helper scripts created"

# =============================================
# Start Backend Service
# =============================================
print_step "Starting backend service..."

systemctl enable autodialer
systemctl start autodialer

# Wait for service to start
sleep 3

if systemctl is-active --quiet autodialer; then
    print_success "Backend service started"
else
    print_error "Backend service failed to start"
    systemctl status autodialer --no-pager
    exit 1
fi

# =============================================
# Verify Backend
# =============================================
print_step "Verifying backend..."

# Test health endpoint
sleep 2
if curl -s http://127.0.0.1:8000/api/health | grep -q "ok"; then
    print_success "Health check passed"
    curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool 2>/dev/null || true
else
    print_warn "Health check failed (service may still be starting)"
fi

# =============================================
# Summary
# =============================================
print_success "Python backend setup completed!"
echo ""
print_info "Backend Configuration:"
echo "  User: autodialer"
echo "  Directory: /opt/autodialer"
echo "  Config: /opt/autodialer/config/.env"
echo "  Logs: /opt/autodialer/logs/"
echo ""
print_info "Secrets Generated:"
echo "  JWT_SECRET: $JWT_SECRET"
echo "  AMI_PASSWORD: $AMI_PASSWORD"
echo "  METRICS_PASS: $METRICS_PASS"
echo ""
print_info "Endpoints:"
echo "  API: http://127.0.0.1:8000/api"
echo "  Health: http://127.0.0.1:8000/api/health"
echo "  Metrics: http://127.0.0.1:8000/metrics"
echo ""
print_info "Useful Commands:"
echo "  systemctl status autodialer"
echo "  systemctl restart autodialer"
echo "  journalctl -u autodialer -f"
echo "  autodialer-status"
echo "  autodialer-restart"
echo "  autodialer-logs"
echo ""
print_info "Next Steps:"
echo "  1. Configure Nginx (10_nginx_setup.sh)"
echo "  2. Configure Firewall (11_firewall_setup.sh)"
echo "  3. Start all services (12_start_services.sh)"
echo ""
