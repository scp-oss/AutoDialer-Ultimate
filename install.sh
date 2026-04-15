#!/bin/bash
# =============================================
# AutoDialer Ultimate - Main Installer
# Version: 3.0.0
# =============================================

set -e

# =============================================
# Colors for Output
# =============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_step() { echo -e "\n${GREEN}[STEP]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${CYAN}[SUCCESS]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${BOLD}${BLUE}========================================${NC}"; echo -e "${BOLD}${BLUE}$1${NC}"; echo -e "${BOLD}${BLUE}========================================${NC}"; }

# =============================================
# Script Directory
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

cd "$SCRIPT_DIR"

# =============================================
# Check Root
# =============================================
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root: sudo ./install.sh"
    exit 1
fi

# =============================================
# Welcome Screen
# =============================================
clear
print_header "AutoDialer Ultimate v3.0.0 Installer"
echo ""
print_info "This script will install and configure AutoDialer Ultimate."
print_info "System: Debian 12 (Bookworm) recommended"
print_info "Requirements: 4GB RAM, 2 vCPU, 20GB disk"
echo ""
print_warn "IMPORTANT:"
echo "  - FreePBX server (Server-1) must be accessible"
echo "  - Extension 291 must be created on FreePBX"
echo "  - Ports 80, 443, 5060, 10000-20000 must be open"
echo ""

read -p "Continue with installation? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Installation cancelled"
    exit 1
fi

# =============================================
# Check .env File
# =============================================
print_step "Checking configuration..."

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    print_warn ".env file not found!"
    print_info "Creating .env from .env.example..."
    
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    else
        print_error ".env.example not found!"
        exit 1
    fi
    
    print_info "Please edit .env file with your configuration:"
    print_info "  nano $SCRIPT_DIR/.env"
    echo ""
    print_info "Required variables:"
    echo "  - FREEPBX_IP          : IP address of your FreePBX server"
    echo "  - EXTENSION_PASSWORD  : Password for SIP extension 291"
    echo ""
    
    read -p "Edit .env now and continue? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ${EDITOR:-nano} "$SCRIPT_DIR/.env"
    else
        print_error "Installation cancelled. Please configure .env first."
        exit 1
    fi
fi

# =============================================
# Load Configuration
# =============================================
source "$SCRIPT_DIR/.env"

# Validate required variables
if [ -z "$FREEPBX_IP" ]; then
    print_error "FREEPBX_IP is not set in .env"
    echo "Please set the IP address of your FreePBX server."
    exit 1
fi

if [ -z "$EXTENSION_PASSWORD" ]; then
    print_error "EXTENSION_PASSWORD is not set in .env"
    echo "Please set the password for SIP extension 291."
    exit 1
fi

print_success "Configuration loaded"

# =============================================
# Generate Secrets if Empty
# =============================================
print_step "Generating secrets..."

SECRETS_UPDATED=false

if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(openssl rand -hex 16)
    sed -i "s/^# DB_PASSWORD=.*/DB_PASSWORD=$DB_PASSWORD/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Generated DB_PASSWORD"
fi

if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    sed -i "s/^# JWT_SECRET=.*/JWT_SECRET=$JWT_SECRET/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Generated JWT_SECRET"
fi

if [ -z "$AMI_PASSWORD" ]; then
    AMI_PASSWORD=$(openssl rand -hex 16)
    sed -i "s/^# AMI_PASSWORD=.*/AMI_PASSWORD=$AMI_PASSWORD/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Generated AMI_PASSWORD"
fi

if [ -z "$METRICS_PASS" ]; then
    METRICS_PASS=$(openssl rand -hex 8)
    sed -i "s/^# METRICS_PASS=.*/METRICS_PASS=$METRICS_PASS/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Generated METRICS_PASS"
fi

if [ "$SECRETS_UPDATED" = true ]; then
    source "$SCRIPT_DIR/.env"
    print_success "Secrets generated and saved to .env"
fi

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

# =============================================
# Installation Summary
# =============================================
print_header "Installation Summary"
echo ""
print_info "FreePBX Server:     $FREEPBX_IP"
print_info "Extension:          291"
print_info "Domain:             ${DOMAIN_NAME:-Not configured}"
print_info "Max Calls:          $MAX_CALLS"
print_info "Default CPS:        $DEFAULT_CPS"
print_info "TTS Voice:          $TTS_VOICE"
echo ""
print_info "Installation Directory: /opt/autodialer"
print_info "Asterisk Directory:    /etc/asterisk"
echo ""

read -p "Start installation? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Installation cancelled"
    exit 1
fi

# =============================================
# Make Scripts Executable
# =============================================
print_step "Preparing installation scripts..."

if [ -d "$SCRIPT_DIR/scripts" ]; then
    chmod +x "$SCRIPT_DIR/scripts/"*.sh 2>/dev/null || true
    print_success "Scripts are executable"
else
    print_error "scripts directory not found!"
    exit 1
fi

# =============================================
# Run Installation Scripts in Order
# =============================================
INSTALLATION_START=$(date +%s)

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

FAILED_SCRIPTS=()

for script in "${SCRIPTS[@]}"; do
    script_path="$SCRIPT_DIR/scripts/$script"
    
    if [ -f "$script_path" ]; then
        print_header "Running: $script"
        
        if bash "$script_path"; then
            print_success "$script completed"
        else
            print_error "$script failed"
            FAILED_SCRIPTS+=("$script")
            
            read -p "Continue despite error? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                print_error "Installation aborted"
                exit 1
            fi
        fi
    else
        print_warn "$script not found, skipping..."
    fi
done

# =============================================
# Configure HTTPS (Optional)
# =============================================
if [ -n "$DOMAIN_NAME" ] && command -v certbot &> /dev/null; then
    print_step "Setting up HTTPS with Let's Encrypt..."
    
    read -p "Configure HTTPS for $DOMAIN_NAME? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --email "admin@$DOMAIN_NAME" 2>/dev/null || {
            print_warn "Certbot failed, HTTPS not configured"
        }
        if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
            print_success "HTTPS configured for $DOMAIN_NAME"
        fi
    fi
fi

# =============================================
# Installation Complete
# =============================================
INSTALLATION_END=$(date +%s)
INSTALLATION_TIME=$((INSTALLATION_END - INSTALLATION_START))

clear
print_header "Installation Complete!"
echo ""

if [ ${#FAILED_SCRIPTS[@]} -gt 0 ]; then
    print_warn "Some scripts failed:"
    for script in "${FAILED_SCRIPTS[@]}"; do
        echo "  - $script"
    done
    echo ""
fi

print_success "AutoDialer Ultimate has been installed!"
print_info "Installation time: ${INSTALLATION_TIME} seconds"
echo ""

# =============================================
# Server Information
# =============================================
SERVER_IP=$(hostname -I | awk '{print $1}')

print_header "Access Information"
echo ""
print_info "Web UI:       http://$SERVER_IP/"
if [ -n "$DOMAIN_NAME" ] && [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
    print_info "Web UI HTTPS: https://$DOMAIN_NAME/"
fi
print_info "API Docs:     http://$SERVER_IP/docs"
print_info "API Health:   http://$SERVER_IP/api/health"
print_info "Metrics:      http://$SERVER_IP/metrics"
echo ""

# =============================================
# Credentials
# =============================================
print_header "Credentials"
echo ""
print_info "Web UI:"
echo "  Username: admin"
echo "  Password: admin"
echo ""
print_info "AMI:"
echo "  Username: autodialer"
echo "  Password: $AMI_PASSWORD"
echo ""
print_info "Database:"
echo "  Username: $DB_USER"
echo "  Password: $DB_PASSWORD"
echo "  Database: $DB_NAME"
echo ""
print_info "Metrics:"
echo "  Username: $METRICS_USER"
echo "  Password: $METRICS_PASS"
echo ""

# =============================================
# Verification Commands
# =============================================
print_header "Verification Commands"
echo ""
print_info "Check services:"
echo "  systemctl status autodialer"
echo "  systemctl status asterisk"
echo "  systemctl status nginx"
echo ""
print_info "Check Asterisk:"
echo "  asterisk -rvvv"
echo "  asterisk -rx 'pjsip show registrations'"
echo "  asterisk -rx 'pjsip show endpoints'"
echo ""
print_info "Check logs:"
echo "  tail -f /opt/autodialer/logs/autodialer.log"
echo "  tail -f /var/log/asterisk/full"
echo "  journalctl -u autodialer -f"
echo ""

# =============================================
# Helper Scripts
# =============================================
print_header "Helper Scripts"
echo ""
print_info "Status:"
echo "  autodialer-status           - Backend status"
echo "  autodialer-all-status       - All services status"
echo "  autodialer-redis-status     - Redis status"
echo "  autodialer-firewall-status  - Firewall status"
echo "  autodialer-fail2ban-status  - Fail2ban status"
echo "  autodialer-logrotate-status - Logrotate status"
echo ""
print_info "Management:"
echo "  autodialer-restart          - Restart backend"
echo "  autodialer-all-restart      - Restart all services"
echo "  autodialer-logs             - View backend logs"
echo ""

# =============================================
# Important Notes
# =============================================
print_header "Important Notes"
echo ""
print_warn "1. CHANGE THE DEFAULT ADMIN PASSWORD!"
echo "   Login to Web UI and change password immediately."
echo ""
print_warn "2. VERIFY SIP REGISTRATION!"
echo "   asterisk -rx 'pjsip show registrations'"
echo "   Should show 'Registered' for extension 291"
echo ""
print_warn "3. CHECK FIREWALL!"
echo "   Ensure FreePBX can reach this server on ports 5060 and 10000-20000"
echo ""
print_info "4. CONFIGURE CAMPAIGNS!"
echo "   Create campaigns and import contacts via Web UI."
echo ""

# =============================================
# Configuration Files
# =============================================
print_header "Configuration Files"
echo ""
print_info "Backend:  /opt/autodialer/config/.env"
print_info "Asterisk: /etc/asterisk/"
print_info "Nginx:    /etc/nginx/sites-available/autodialer"
print_info "Systemd:  /etc/systemd/system/autodialer.service"
echo ""

# =============================================
# Support
# =============================================
print_header "Support"
echo ""
print_info "Documentation: https://github.com/naumenis-code/AutoDialer-Ultimate"
print_info "Issues:        https://github.com/naumenis-code/AutoDialer-Ultimate/issues"
echo ""

print_success "Thank you for installing AutoDialer Ultimate!"
echo "=============================================="
