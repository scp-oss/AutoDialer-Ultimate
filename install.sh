#!/bin/bash
# AutoDialer Ultimate - Main Installer v3.0.0

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[STEP]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${CYAN}[SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root (sudo ./install.sh)"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    print_error ".env file not found! Copy .env.example to .env and configure."
    exit 1
fi

source "$SCRIPT_DIR/.env"

if [ -z "$FREEPBX_IP" ]; then
    print_error "FREEPBX_IP not set in .env"
    exit 1
fi

print_info "=========================================="
print_info "AutoDialer Ultimate Installation"
print_info "=========================================="
print_info "FreePBX Server: $FREEPBX_IP"
print_info "Domain: ${DOMAIN_NAME:-Not configured}"
print_info "=========================================="

# Генерация паролей если не заданы
if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(openssl rand -hex 16)
    echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/.env"
fi

if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/.env"
fi

if [ -z "$AMI_PASSWORD" ]; then
    AMI_PASSWORD=$(openssl rand -hex 16)
    echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/.env"
fi

if [ -z "$METRICS_PASS" ]; then
    METRICS_PASS=$(openssl rand -hex 8)
    echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/.env"
fi

export DB_PASSWORD JWT_SECRET AMI_PASSWORD METRICS_PASS

# Запуск скриптов установки
for script in "$SCRIPT_DIR"/scripts/*.sh; do
    if [ -f "$script" ] && [ -x "$script" ]; then
        print_step "Running $(basename "$script")"
        bash "$script"
    fi
done

IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo "=============================================="
print_success "✅ AUTODIALER ULTIMATE INSTALLATION COMPLETE!"
echo "=============================================="
echo ""
print_info "Server IP:       $IP_ADDR"
print_info "FreePBX IP:      $FREEPBX_IP"
echo ""
print_info "ACCESS:"
echo "  Web UI:       http://$IP_ADDR/"
echo "  API Docs:     http://$IP_ADDR/docs"
echo "  Metrics:      http://$IP_ADDR/metrics"
echo ""
print_info "CREDENTIALS:"
echo "  Admin Login:  admin / admin"
echo "  AMI User:     autodialer / $AMI_PASSWORD"
echo "  DB User:      autodialer / $DB_PASSWORD"
echo ""
print_warn "IMPORTANT: Change admin password after first login!"
echo "=============================================="
