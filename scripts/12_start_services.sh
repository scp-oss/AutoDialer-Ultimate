#!/bin/bash
# =============================================
# AutoDialer Ultimate - Start All Services
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
# Service List
# =============================================
SERVICES=(
    "postgresql"
    "redis-server"
    "asterisk"
    "autodialer"
    "nginx"
    "fail2ban"
    "prometheus"
    "grafana-server"
)

# =============================================
# Stop Services (Clean Start)
# =============================================
print_step "Stopping all services for clean start..."

for service in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$service" 2>/dev/null; then
        print_info "Stopping $service..."
        systemctl stop "$service" || true
    fi
done

print_success "All services stopped"

# Wait for services to fully stop
sleep 3

# =============================================
# Start Services in Order
# =============================================
print_step "Starting services in order..."

# 1. PostgreSQL (database first)
print_info "Starting PostgreSQL..."
systemctl start postgresql
for i in {1..10}; do
    if systemctl is-active --quiet postgresql; then
        print_success "  ✓ PostgreSQL started"
        break
    fi
    sleep 1
done

# 2. Redis (cache)
print_info "Starting Redis..."
systemctl start redis-server
for i in {1..5}; do
    if systemctl is-active --quiet redis-server; then
        print_success "  ✓ Redis started"
        break
    fi
    sleep 1
done

# 3. Asterisk (telephony)
print_info "Starting Asterisk..."
systemctl start asterisk
sleep 3
if systemctl is-active --quiet asterisk; then
    print_success "  ✓ Asterisk started"
else
    print_warn "  ⚠ Asterisk failed to start"
fi

# 4. AutoDialer Backend
print_info "Starting AutoDialer backend..."
systemctl start autodialer
sleep 3
if systemctl is-active --quiet autodialer; then
    print_success "  ✓ AutoDialer backend started"
else
    print_warn "  ⚠ AutoDialer backend failed to start"
fi

# 5. Nginx (web server)
print_info "Starting Nginx..."
systemctl start nginx
if systemctl is-active --quiet nginx; then
    print_success "  ✓ Nginx started"
else
    print_warn "  ⚠ Nginx failed to start"
fi

# 6. Fail2ban (security)
print_info "Starting Fail2ban..."
systemctl start fail2ban
if systemctl is-active --quiet fail2ban; then
    print_success "  ✓ Fail2ban started"
fi

# 7. Monitoring (optional)
if systemctl list-unit-files | grep -q prometheus; then
    print_info "Starting Prometheus..."
    systemctl start prometheus 2>/dev/null || true
fi

if systemctl list-unit-files | grep -q grafana-server; then
    print_info "Starting Grafana..."
    systemctl start grafana-server 2>/dev/null || true
fi

print_success "All services started"

# =============================================
# Enable Services on Boot
# =============================================
print_step "Enabling services on boot..."

for service in "${SERVICES[@]}"; do
    if systemctl list-unit-files | grep -q "^${service}.service"; then
        systemctl enable "$service" 2>/dev/null || true
        print_info "  ✓ $service enabled"
    fi
done

print_success "Services enabled on boot"

# =============================================
# Verify Services
# =============================================
print_step "Verifying services..."

echo ""
print_info "Service Status:"
echo "─────────────────────────────────────────────────"
printf "%-20s %-15s %s\n" "SERVICE" "STATUS" "INFO"
echo "─────────────────────────────────────────────────"

# Check PostgreSQL
if systemctl is-active --quiet postgresql; then
    VERSION=$(sudo -u postgres psql -t -c "SELECT version();" 2>/dev/null | cut -d' ' -f1-3 | head -1 || echo "unknown")
    printf "%-20s \033[32m%-15s\033[0m %s\n" "postgresql" "● ACTIVE" "$VERSION"
else
    printf "%-20s \033[31m%-15s\033[0m %s\n" "postgresql" "○ INACTIVE" "-"
fi

# Check Redis
if systemctl is-active --quiet redis-server; then
    REDIS_PONG=$(redis-cli ping 2>/dev/null || echo "no response")
    printf "%-20s \033[32m%-15s\033[0m %s\n" "redis-server" "● ACTIVE" "$REDIS_PONG"
else
    printf "%-20s \033[31m%-15s\033[0m %s\n" "redis-server" "○ INACTIVE" "-"
fi

# Check Asterisk
if systemctl is-active --quiet asterisk; then
    AST_VERSION=$(asterisk -rx "core show version" 2>/dev/null | head -1 || echo "unknown")
    REG_STATUS=$(asterisk -rx "pjsip show registrations" 2>/dev/null | grep -c "Registered" || echo "0")
    printf "%-20s \033[32m%-15s\033[0m %s, %s registrations\n" "asterisk" "● ACTIVE" "$AST_VERSION" "$REG_STATUS"
else
    printf "%-20s \033[31m%-15s\033[0m %s\n" "asterisk" "○ INACTIVE" "-"
fi

# Check AutoDialer
if systemctl is-active --quiet autodialer; then
    HEALTH=$(curl -s http://127.0.0.1:8000/api/health 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "no response")
    printf "%-20s \033[32m%-15s\033[0m %s\n" "autodialer" "● ACTIVE" "$HEALTH"
else
    printf "%-20s \033[31m%-15s\033[0m %s\n" "autodialer" "○ INACTIVE" "-"
fi

# Check Nginx
if systemctl is-active --quiet nginx; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ 2>/dev/null || echo "000")
    printf "%-20s \033[32m%-15s\033[0m %s\n" "nginx" "● ACTIVE" "HTTP $HTTP_CODE"
else
    printf "%-20s \033[31m%-15s\033[0m %s\n" "nginx" "○ INACTIVE" "-"
fi

# Check Fail2ban
if systemctl is-active --quiet fail2ban; then
    JAILS=$(fail2ban-client status 2>/dev/null | grep "Jail list" | cut -d':' -f2 | xargs || echo "none")
    printf "%-20s \033[32m%-15s\033[0m %s\n" "fail2ban" "● ACTIVE" "jails: $JAILS"
else
    printf "%-20s \033[31m%-15s\033[0m %s\n" "fail2ban" "○ INACTIVE" "-"
fi

echo "─────────────────────────────────────────────────"

# =============================================
# Network Ports Check
# =============================================
print_step "Checking network ports..."

echo ""
print_info "Listening Ports:"
echo "─────────────────────────────────────────────────"
ss -tlnp 2>/dev/null | grep -E ":(22|80|443|5432|6379|5038|8000|8088|9090|3000)" | while read line; do
    echo "$line"
done || echo "No ports found"
echo "─────────────────────────────────────────────────"

# =============================================
# Detailed Asterisk Check
# =============================================
if systemctl is-active --quiet asterisk; then
    print_step "Detailed Asterisk check..."
    
    echo ""
    print_info "PJSIP Registration:"
    asterisk -rx "pjsip show registrations" 2>/dev/null | grep -v "No objects found" || echo "  No registrations"
    
    echo ""
    print_info "Active Channels:"
    asterisk -rx "core show channels" 2>/dev/null | head -5 || echo "  No active channels"
fi

# =============================================
# Detailed Backend Check
# =============================================
if systemctl is-active --quiet autodialer; then
    echo ""
    print_info "Backend Health:"
    curl -s http://127.0.0.1:8000/api/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  Health check failed"
fi

# =============================================
# Create Status Script
# =============================================
print_step "Creating status script..."

cat > /usr/local/bin/autodialer-all-status << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - All Services Status

echo "=============================================="
echo "AutoDialer Ultimate - Service Status"
echo "=============================================="
echo ""

SERVICES="postgresql redis-server asterisk autodialer nginx fail2ban"

for svc in $SERVICES; do
    if systemctl is-active --quiet $svc; then
        echo "✅ $svc: running"
    else
        echo "❌ $svc: stopped"
    fi
done

echo ""
echo "=============================================="
echo "Resource Usage"
echo "=============================================="

echo ""
echo "CPU:"
top -bn1 | head -5

echo ""
echo "Memory:"
free -h

echo ""
echo "Disk:"
df -h / /opt/autodialer /var/lib/postgresql /var/lib/redis 2>/dev/null

echo ""
echo "=============================================="
echo "Recent Errors"
echo "=============================================="

echo ""
echo "AutoDialer Errors:"
journalctl -u autodialer -n 5 --no-pager 2>/dev/null | grep -i error || echo "  No recent errors"

echo ""
echo "Asterisk Errors:"
tail -5 /var/log/asterisk/full 2>/dev/null | grep -i error || echo "  No recent errors"
EOF

chmod +x /usr/local/bin/autodialer-all-status
print_success "Status script created: /usr/local/bin/autodialer-all-status"

# =============================================
# Create Restart All Script
# =============================================
cat > /usr/local/bin/autodialer-all-restart << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - Restart All Services

echo "Restarting all AutoDialer services..."

SERVICES="postgresql redis-server asterisk autodialer nginx"

for svc in $SERVICES; do
    echo "Restarting $svc..."
    systemctl restart $svc
    sleep 2
done

echo "All services restarted!"
systemctl status postgresql redis-server asterisk autodialer nginx --no-pager -l
EOF

chmod +x /usr/local/bin/autodialer-all-restart
print_success "Restart script created: /usr/local/bin/autodialer-all-restart"

# =============================================
# Final Summary
# =============================================
print_success "All services started and verified!"
echo ""
print_info "Service URLs:"
echo "  Web UI:       http://$SERVER_IP/"
echo "  API Docs:     http://$SERVER_IP/docs"
echo "  API Health:   http://$SERVER_IP/api/health"
echo "  Metrics:      http://$SERVER_IP/metrics"
echo ""
print_info "Credentials:"
echo "  Admin:        admin / admin"
echo "  AMI:          autodialer / $AMI_PASSWORD"
echo "  Database:     $DB_USER / $DB_PASSWORD"
echo ""
print_info "Useful Commands:"
echo "  autodialer-all-status    - Check all services"
echo "  autodialer-all-restart   - Restart all services"
echo "  autodialer-status        - Backend status"
echo "  autodialer-logs          - Backend logs"
echo "  asterisk -rvvv           - Asterisk console"
echo ""
print_warn "IMPORTANT:"
echo "  1. Change admin password on first login"
echo "  2. Check PJSIP registration: asterisk -rx 'pjsip show registrations'"
echo "  3. Monitor logs: journalctl -u autodialer -f"
echo "  4. Verify FreePBX connectivity: ping $FREEPBX_IP"
echo ""
print_success "AutoDialer Ultimate is ready!"
echo "=============================================="
