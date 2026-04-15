#!/bin/bash
# =============================================
# AutoDialer Ultimate - Main Installer v3.0.0
# =============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

# Цвета
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

# Проверка root
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root (sudo ./install.sh)"
    exit 1
fi

# Проверка .env файла
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    print_error ".env file not found!"
    print_info "Copy .env.example to .env and configure:"
    print_info "  cp .env.example .env"
    print_info "  nano .env"
    exit 1
fi

# Загрузка конфигурации
source "$SCRIPT_DIR/.env"

# Проверка обязательных переменных
if [ -z "$FREEPBX_IP" ]; then
    print_error "FREEPBX_IP not set in .env"
    print_info "Please set the IP address of your FreePBX server"
    exit 1
fi

if [ -z "$EXTENSION_PASSWORD" ]; then
    print_error "EXTENSION_PASSWORD not set in .env"
    print_info "Please set the password for extension 291"
    exit 1
fi

# Генерация паролей если не заданы
if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(openssl rand -hex 16)
    echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/.env"
    print_info "Generated DB_PASSWORD"
fi

if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/.env"
    print_info "Generated JWT_SECRET"
fi

if [ -z "$AMI_PASSWORD" ]; then
    AMI_PASSWORD=$(openssl rand -hex 16)
    echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/.env"
    print_info "Generated AMI_PASSWORD"
fi

if [ -z "$METRICS_PASS" ]; then
    METRICS_PASS=$(openssl rand -hex 8)
    echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/.env"
    print_info "Generated METRICS_PASS"
fi

# Экспорт переменных
export FREEPBX_IP
export EXTENSION_PASSWORD
export DB_PASSWORD
export JWT_SECRET
export AMI_PASSWORD
export METRICS_PASS
export DOMAIN_NAME="${DOMAIN_NAME:-}"
export MAX_CALLS="${MAX_CALLS:-50}"
export DEFAULT_CPS="${DEFAULT_CPS:-5}"
export TTS_VOICE="${TTS_VOICE:-denis}"

print_info "=========================================="
print_info "AutoDialer Ultimate Installation"
print_info "=========================================="
print_info "FreePBX Server: $FREEPBX_IP"
print_info "Extension: 291"
print_info "Domain: ${DOMAIN_NAME:-Not configured}"
print_info "Max Calls: $MAX_CALLS"
print_info "Default CPS: $DEFAULT_CPS"
print_info "TTS Voice: $TTS_VOICE"
print_info "=========================================="

# Подтверждение установки
read -p "Continue with installation? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Installation cancelled"
    exit 1
fi

# Запуск скриптов установки по порядку
SCRIPTS=(
    "01_system_setup.sh"
    "02_asterisk_install.sh"
    "03_asterisk_config.sh"
    "04_pjsip_config.sh"
    "05_dialplan_config.sh"
    "06_tts_install.sh"
    "07_postgresql_setup.sh"
    "08_redis_setup.sh"
    "09_python_backend.sh"
    "10_nginx_setup.sh"
    "11_firewall_setup.sh"
    "12_start_services.sh"
    "13_fail2ban_setup.sh"
    "14_logrotate_setup.sh"
)

for script in "${SCRIPTS[@]}"; do
    script_path="$SCRIPT_DIR/scripts/$script"
    if [ -f "$script_path" ]; then
        print_step "Running $script"
        bash "$script_path" || {
            print_error "Failed: $script"
            exit 1
        }
    else
        print_warn "Script not found: $script (skipping)"
    fi
done

# Настройка HTTPS если указан домен
if [ -n "$DOMAIN_NAME" ]; then
    print_step "Setting up HTTPS with Certbot..."
    if command -v certbot &> /dev/null; then
        certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --email "admin@$DOMAIN_NAME" 2>/dev/null || {
            print_warn "Certbot failed, HTTPS not configured"
        }
    fi
fi

# Финальная информация
IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo "=============================================="
print_success "✅ AUTODIALER ULTIMATE INSTALLATION COMPLETE!"
echo "=============================================="
echo ""
print_info "Server IP:       $IP_ADDR"
print_info "FreePBX IP:      $FREEPBX_IP"
if [ -n "$DOMAIN_NAME" ]; then
    print_info "Domain:          $DOMAIN_NAME"
fi
echo ""
print_info "ACCESS:"
echo "  Web UI:       http://$IP_ADDR/"
if [ -n "$DOMAIN_NAME" ]; then
    echo "  Web UI HTTPS: https://$DOMAIN_NAME/"
fi
echo "  API Docs:     http://$IP_ADDR/docs"
echo "  Metrics:      http://$IP_ADDR/metrics (login: admin / $METRICS_PASS)"
echo ""
print_info "CREDENTIALS:"
echo "  Admin Login:  admin / admin"
echo "  AMI User:     autodialer / $AMI_PASSWORD"
echo "  DB User:      autodialer / $DB_PASSWORD"
echo "  Metrics:      admin / $METRICS_PASS"
echo ""
print_warn "IMPORTANT: Change admin password after first login!"
echo ""
print_info "VERIFICATION COMMANDS:"
echo "  systemctl status autodialer"
echo "  systemctl status asterisk"
echo "  asterisk -rx 'pjsip show registrations'"
echo "  tail -f /opt/autodialer/logs/autodialer.log"
echo ""
print_info "LOGS:"
echo "  Backend:  /opt/autodialer/logs/"
echo "  Asterisk: /var/log/asterisk/full"
echo ""
print_success "System is ready for production use!"
echo "=============================================="
