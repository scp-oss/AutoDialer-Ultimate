#!/bin/bash
# =============================================
# AutoDialer Ultimate - Firewall Setup (UFW + iptables)
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

FREEPBX_IP="${FREEPBX_IP:-}"
SERVER_IP=$(hostname -I | awk '{print $1}')

# =============================================
# Install UFW
# =============================================
print_step "Checking UFW installation..."

if ! command -v ufw &> /dev/null; then
    print_info "Installing UFW..."
    apt update
    apt install -y ufw iptables-persistent
    print_success "UFW installed"
else
    print_success "UFW already installed"
fi

# =============================================
# Reset UFW to Defaults
# =============================================
print_step "Resetting UFW to defaults..."

ufw --force disable
ufw --force reset

print_success "UFW reset"

# =============================================
# Set Default Policies
# =============================================
print_step "Setting default policies..."

ufw default deny incoming
ufw default allow outgoing
ufw default deny routed

print_success "Default policies set (deny incoming, allow outgoing)"

# =============================================
# Allow Essential Services
# =============================================
print_step "Configuring firewall rules..."

# SSH (always allow)
ufw allow 22/tcp comment 'SSH'
print_info "  ✓ SSH (22/tcp)"

# HTTP/HTTPS
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
print_info "  ✓ HTTP/HTTPS (80,443/tcp)"

# SIP (restricted to FreePBX)
if [ -n "$FREEPBX_IP" ]; then
    ufw allow proto udp from "$FREEPBX_IP" to any port 5060 comment 'SIP from FreePBX'
    ufw allow proto tcp from "$FREEPBX_IP" to any port 5061 comment 'SIP TLS from FreePBX'
    print_info "  ✓ SIP from FreePBX ($FREEPBX_IP)"
else
    ufw allow 5060/udp comment 'SIP'
    print_warn "  ⚠ SIP allowed from anywhere (set FREEPBX_IP to restrict)"
fi

# RTP (restricted to FreePBX)
if [ -n "$FREEPBX_IP" ]; then
    ufw allow proto udp from "$FREEPBX_IP" to any port 10000:20000 comment 'RTP from FreePBX'
    print_info "  ✓ RTP from FreePBX ($FREEPBX_IP)"
else
    ufw allow 10000:20000/udp comment 'RTP'
    print_warn "  ⚠ RTP allowed from anywhere (set FREEPBX_IP to restrict)"
fi

# Allow localhost (required for internal services)
ufw allow from 127.0.0.1 comment 'Localhost'
ufw allow from ::1 comment 'Localhost IPv6'
print_info "  ✓ Localhost"

# Allow internal networks (optional)
read -p "Allow internal networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ufw allow from 10.0.0.0/8 comment 'Private network 10/8'
    ufw allow from 172.16.0.0/12 comment 'Private network 172.16/12'
    ufw allow from 192.168.0.0/16 comment 'Private network 192.168/16'
    print_info "  ✓ Internal networks allowed"
fi

# ICMP (ping) - optional
read -p "Allow ICMP (ping)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ufw allow proto icmp comment 'ICMP (ping)'
    print_info "  ✓ ICMP allowed"
fi

print_success "Firewall rules configured"

# =============================================
# Additional iptables Rules
# =============================================
print_step "Adding additional iptables rules..."

# Protection against common attacks
iptables -A INPUT -p tcp --tcp-flags ALL NONE -j DROP
iptables -A INPUT -p tcp --tcp-flags ALL ALL -j DROP
iptables -A INPUT -p tcp ! --syn -m state --state NEW -j DROP
iptables -A INPUT -f -j DROP

# Limit connections
iptables -A INPUT -p tcp --dport 80 -m connlimit --connlimit-above 100 --connlimit-mask 32 -j DROP
iptables -A INPUT -p tcp --dport 443 -m connlimit --connlimit-above 100 --connlimit-mask 32 -j DROP
iptables -A INPUT -p tcp --dport 22 -m connlimit --connlimit-above 10 --connlimit-mask 32 -j DROP

# Protect against port scans
iptables -A INPUT -p tcp -m recent --name portscan --set -j DROP
iptables -A FORWARD -p tcp -m recent --name portscan --set -j DROP

# Block invalid packets
iptables -A INPUT -m state --state INVALID -j DROP
iptables -A FORWARD -m state --state INVALID -j DROP
iptables -A OUTPUT -m state --state INVALID -j DROP

# SIP flood protection
if [ -n "$FREEPBX_IP" ]; then
    iptables -A INPUT -p udp --dport 5060 ! -s "$FREEPBX_IP" -j DROP
    iptables -A INPUT -p udp --dport 10000:20000 ! -s "$FREEPBX_IP" -j DROP
fi

print_success "Additional iptables rules added"

# =============================================
# Save iptables Rules
# =============================================
print_step "Saving iptables rules..."

# Save rules for persistence
if command -v netfilter-persistent &> /dev/null; then
    netfilter-persistent save
    print_success "Rules saved with netfilter-persistent"
elif command -v iptables-save &> /dev/null; then
    iptables-save > /etc/iptables/rules.v4
    ip6tables-save > /etc/iptables/rules.v6 2>/dev/null || true
    print_success "Rules saved to /etc/iptables/"
else
    print_warn "Could not save rules persistently"
fi

# =============================================
# Enable UFW
# =============================================
print_step "Enabling UFW..."

ufw --force enable

if ufw status | grep -q "Status: active"; then
    print_success "UFW is active"
else
    print_error "UFW failed to activate"
    exit 1
fi

# =============================================
# Verify Firewall
# =============================================
print_step "Verifying firewall configuration..."

echo ""
print_info "UFW Status:"
ufw status verbose | head -30

echo ""
print_info "Active iptables rules (first 20):"
iptables -L -n -v | head -20

# =============================================
# Create Firewall Helper Scripts
# =============================================
print_step "Creating firewall helper scripts..."

# Status script
cat > /usr/local/bin/autodialer-firewall-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Firewall Status"
echo "=============================================="
echo ""
echo "=== UFW Status ==="
ufw status verbose
echo ""
echo "=== iptables Rules (INPUT chain) ==="
iptables -L INPUT -n -v --line-numbers | head -30
echo ""
echo "=== Active Connections ==="
ss -tunp | head -20
EOF
chmod +x /usr/local/bin/autodialer-firewall-status

# Allow IP script
cat > /usr/local/bin/autodialer-firewall-allow << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: $0 <IP_ADDRESS> [comment]"
    exit 1
fi

IP="$1"
COMMENT="${2:-Manual allow}"

ufw allow from "$IP" comment "$COMMENT"
echo "Allowed $IP ($COMMENT)"
ufw reload
EOF
chmod +x /usr/local/bin/autodialer-firewall-allow

# Deny IP script
cat > /usr/local/bin/autodialer-firewall-deny << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: $0 <IP_ADDRESS>"
    exit 1
fi

IP="$1"

ufw deny from "$IP"
echo "Blocked $IP"
ufw reload
EOF
chmod +x /usr/local/bin/autodialer-firewall-deny

print_success "Helper scripts created"

# =============================================
# Summary
# =============================================
print_success "Firewall setup completed!"
echo ""
print_info "Firewall Configuration:"
echo "  Status: $(ufw status | head -1)"
echo "  Default incoming: deny"
echo "  Default outgoing: allow"
echo ""
print_info "Allowed Ports:"
echo "  - 22/tcp (SSH)"
echo "  - 80/tcp (HTTP)"
echo "  - 443/tcp (HTTPS)"
if [ -n "$FREEPBX_IP" ]; then
    echo "  - 5060/udp (SIP from $FREEPBX_IP)"
    echo "  - 10000:20000/udp (RTP from $FREEPBX_IP)"
else
    echo "  - 5060/udp (SIP - unrestricted)"
    echo "  - 10000:20000/udp (RTP - unrestricted)"
fi
echo ""
print_info "Helper Scripts:"
echo "  autodialer-firewall-status  - View firewall status"
echo "  autodialer-firewall-allow    - Allow an IP"
echo "  autodialer-firewall-deny     - Block an IP"
echo ""
print_info "Useful Commands:"
echo "  ufw status                    - Show firewall status"
echo "  ufw status verbose            - Detailed status"
echo "  ufw allow <port>              - Allow port"
echo "  ufw deny <port>               - Deny port"
echo "  ufw delete <rule>             - Delete rule"
echo "  ufw reload                    - Reload rules"
echo "  ufw disable                   - Disable firewall (emergency)"
echo ""
print_warn "IMPORTANT:"
echo "  - SSH (22) is open. Do not close it!"
echo "  - SIP/RTP restricted to FreePBX: $FREEPBX_IP"
echo "  - Review rules with: ufw status verbose"
echo ""
