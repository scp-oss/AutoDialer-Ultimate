#!/bin/bash
# =============================================
# AutoDialer Ultimate - PJSIP Configuration
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
else
    print_error ".env file not found!"
    exit 1
fi

# Check required variables
if [ -z "$FREEPBX_IP" ]; then
    print_error "FREEPBX_IP is not set in .env"
    exit 1
fi

if [ -z "$EXTENSION_PASSWORD" ]; then
    print_error "EXTENSION_PASSWORD is not set in .env"
    exit 1
fi

print_info "FreePBX Server: $FREEPBX_IP"
print_info "Extension: 291"

# =============================================
# Configure PJSIP
# =============================================
print_step "Configuring PJSIP for FreePBX registration..."

cat > /etc/asterisk/pjsip.conf << EOF
; =============================================
; PJSIP Configuration for AutoDialer Ultimate
; FreePBX Extension: 291
; =============================================

[global]
type = global
user_agent = AutoDialer-Ultimate/3.0.0
keep_alive_interval = 90
endpoint_identifier_order = ip,username,anonymous
default_realm = ${FREEPBX_IP}
max_initial_qualify = 5

; =============================================
; Transport Configuration
; =============================================
[transport-udp]
type = transport
protocol = udp
bind = 0.0.0.0
local_net = 192.168.0.0/16,10.0.0.0/8,172.16.0.0/12
external_media_address = ${FREEPBX_IP}
external_signaling_address = ${FREEPBX_IP}

; =============================================
; Authentication for Extension 291
; =============================================
[291_auth]
type = auth
auth_type = userpass
username = 291
password = ${EXTENSION_PASSWORD}
realm = ${FREEPBX_IP}

; =============================================
; Address of Record (AOR)
; =============================================
[291_aor]
type = aor
max_contacts = 1
remove_existing = yes
contact = sip:291@${FREEPBX_IP}:5060
qualify_frequency = 30
qualify_timeout = 5.0
default_expiration = 120
maximum_expiration = 3600
minimum_expiration = 60

; =============================================
; Endpoint Configuration
; =============================================
[291_endpoint]
type = endpoint
transport = transport-udp
context = dialer_bridge

; Codecs
disallow = all
allow = ulaw
allow = alaw
allow = g722

; DTMF
dtmf_mode = rfc4733

; Authentication
outbound_auth = 291_auth
aors = 291_aor

; Caller ID
callerid = AutoDialer <291>
callerid_privacy = allowed_not_screened

; Media
direct_media = no
media_encryption = no
media_use_received_transport = yes

; NAT
rewrite_contact = yes
rtp_symmetric = yes
force_rport = yes

; FreePBX specific
from_user = 291
from_domain = ${FREEPBX_IP}
outbound_proxy = sip:${FREEPBX_IP}:5060

; Timers
timers = yes
timers_sess_expires = 1800
timers_min_se = 90

; Keepalive
rtp_keepalive = 30
rtp_timeout = 30
rtp_timeout_hold = 60

; Trust
trust_id_inbound = yes
trust_id_outbound = yes

; Headers
send_pai = yes
send_rpid = yes

; ICE
ice_support = no

; Security
allow_unauthenticated_options = no

; Transport
allow_transfer = no

; Fax
fax_detect = no

; Language
language = ru

; Device state
device_state_busy_at = 1

; Call limits
max_audio_streams = 1
max_video_streams = 0

; Connected line
connected_line_method = invite

; T.38
t38_udptl = no

; =============================================
; Registration to FreePBX
; =============================================
[291_reg]
type = registration
outbound_auth = 291_auth
server_uri = sip:${FREEPBX_IP}:5060
client_uri = sip:291@${FREEPBX_IP}:5060
contact_user = 291
line = yes
endpoint = 291_endpoint
retry_interval = 60
max_retries = 10
forbidden_retry_interval = 300
fatal_retry_interval = 600
expiration = 120
auth_rejection_permanent = no
support_outbound = yes
transport = transport-udp

; =============================================
; Identify - Match incoming from FreePBX
; =============================================
[291_identify]
type = identify
endpoint = 291_endpoint
match = ${FREEPBX_IP}
match_header = From: <sip:291@${FREEPBX_IP}>

; =============================================
; System Configuration
; =============================================
[system]
type = system
timer_t1 = 500
timer_b = 32000
compact_headers = yes
threadpool_initial_size = 0
threadpool_auto_increment = 5
threadpool_idle_timeout = 60
threadpool_max_size = 50
disable_multi_domain = no
EOF

print_success "PJSIP configuration created"

# =============================================
# Create Backup Endpoint (Optional)
# =============================================
if [ -n "$BACKUP_FREEPBX_IP" ]; then
    print_step "Creating backup endpoint..."
    
    cat >> /etc/asterisk/pjsip.conf << EOF

; =============================================
; Backup FreePBX Server
; =============================================
[291_backup_aor]
type = aor
max_contacts = 1
contact = sip:291@${BACKUP_FREEPBX_IP}:5060

[291_backup_endpoint]
type = endpoint
transport = transport-udp
context = dialer_bridge
disallow = all
allow = ulaw
allow = alaw
outbound_auth = 291_auth
aors = 291_backup_aor
callerid = AutoDialer <291>
from_user = 291
from_domain = ${BACKUP_FREEPBX_IP}
outbound_proxy = sip:${BACKUP_FREEPBX_IP}:5060
EOF
    
    print_success "Backup endpoint configured"
fi

# =============================================
# Set Permissions
# =============================================
print_step "Setting permissions..."

chown asterisk:asterisk /etc/asterisk/pjsip.conf
chmod 640 /etc/asterisk/pjsip.conf

print_success "Permissions set"

# =============================================
# Configure SIP Settings (if using chan_sip as fallback)
# =============================================
print_step "Disabling chan_sip..."

cat > /etc/asterisk/sip.conf << 'EOF'
[general]
enabled = no
EOF

print_success "chan_sip disabled"

# =============================================
# Reload Asterisk Configuration
# =============================================
print_step "Reloading Asterisk configuration..."

if systemctl is-active --quiet asterisk; then
    asterisk -rx "module reload res_pjsip.so"
    asterisk -rx "module reload chan_pjsip.so"
    asterisk -rx "pjsip reload"
    print_success "PJSIP configuration reloaded"
else
    print_warn "Asterisk is not running, start it to apply configuration"
fi

# =============================================
# Verify Configuration
# =============================================
print_step "Verifying PJSIP configuration..."

# Check config syntax
if [ -f /etc/asterisk/pjsip.conf ]; then
    print_info "  ✓ pjsip.conf exists"
    
    # Count sections
    SECTIONS=$(grep -c "^\[" /etc/asterisk/pjsip.conf || true)
    print_info "  ✓ $SECTIONS configuration sections found"
else
    print_error "pjsip.conf not found"
    exit 1
fi

# Check for required sections
REQUIRED_SECTIONS=("global" "transport-udp" "291_auth" "291_aor" "291_endpoint" "291_reg" "291_identify")
for section in "${REQUIRED_SECTIONS[@]}"; do
    if grep -q "^\[$section\]" /etc/asterisk/pjsip.conf; then
        print_info "  ✓ Section [$section] found"
    else
        print_error "Section [$section] missing"
    fi
done

# =============================================
# Test Registration (if Asterisk is running)
# =============================================
if systemctl is-active --quiet asterisk; then
    print_step "Testing PJSIP registration..."
    
    sleep 2
    REGISTRATION_STATUS=$(asterisk -rx "pjsip show registrations" 2>/dev/null | grep 291 || echo "Not registered")
    
    if echo "$REGISTRATION_STATUS" | grep -q "Registered"; then
        print_success "✓ Extension 291 is REGISTERED with FreePBX"
        echo "$REGISTRATION_STATUS"
    else
        print_warn "✗ Extension 291 is NOT registered"
        print_info "Check:"
        echo "  - FreePBX IP is correct: $FREEPBX_IP"
        echo "  - Extension 291 exists in FreePBX"
        echo "  - Password matches: $EXTENSION_PASSWORD"
        echo "  - Network connectivity to FreePBX"
    fi
    
    # Show endpoints
    print_info "PJSIP Endpoints:"
    asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -E "Endpoint|291" || true
else
    print_warn "Asterisk not running, skipping registration test"
fi

# =============================================
# Summary
# =============================================
print_success "PJSIP configuration completed!"
echo ""
print_info "Configuration Summary:"
echo "  FreePBX Server: $FREEPBX_IP"
echo "  Extension: 291"
echo "  Context: dialer_bridge"
echo "  Transport: UDP"
echo "  Codecs: ulaw, alaw, g722"
echo ""
print_info "Verification Commands:"
echo "  asterisk -rx 'pjsip show registrations'"
echo "  asterisk -rx 'pjsip show endpoints'"
echo "  asterisk -rx 'pjsip show endpoint 291_endpoint'"
echo "  asterisk -rx 'pjsip show aor 291_aor'"
echo ""
print_info "Troubleshooting:"
echo "  If registration fails:"
echo "  1. Check FreePBX IP and password"
echo "  2. Verify extension 291 exists in FreePBX"
echo "  3. Check network: ping $FREEPBX_IP"
echo "  4. Check FreePBX logs for registration attempts"
echo "  5. Run: asterisk -rvvv and watch for registration messages"
echo ""
