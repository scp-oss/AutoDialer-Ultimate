#!/bin/bash
# =============================================
# AutoDialer Ultimate - Logrotate Setup
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
# Install Logrotate (if not installed)
# =============================================
print_step "Checking Logrotate installation..."

if ! command -v logrotate &> /dev/null; then
    print_info "Installing Logrotate..."
    apt update
    apt install -y logrotate
    print_success "Logrotate installed"
else
    LOGROTATE_VERSION=$(logrotate --version 2>&1 | head -1)
    print_success "Logrotate already installed: $LOGROTATE_VERSION"
fi

# =============================================
# Create AutoDialer Logrotate Configuration
# =============================================
print_step "Creating AutoDialer logrotate configuration..."

cat > /etc/logrotate.d/autodialer << 'EOF'
# =============================================
# AutoDialer Ultimate - Logrotate Configuration
# =============================================

# Backend Application Logs
/opt/autodialer/logs/*.log
/opt/autodialer/logs/access/*.log
/opt/autodialer/logs/error/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    create 0640 autodialer autodialer
    dateext
    dateformat -%Y%m%d
    maxage 30
    sharedscripts
    postrotate
        systemctl reload autodialer > /dev/null 2>&1 || true
    endscript
}

# Asterisk Full Log
/var/log/asterisk/full {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk Messages Log
/var/log/asterisk/messages {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk Security Log
/var/log/asterisk/security {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk Debug Log
/var/log/asterisk/debug {
    daily
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk Verbose Log
/var/log/asterisk/verbose {
    daily
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk DTMF Log
/var/log/asterisk/dtmf {
    daily
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk Dialer Log
/var/log/asterisk/dialer {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk Queue Log
/var/log/asterisk/queue_log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}

# Asterisk CDR CSV Logs
/var/log/asterisk/cdr-csv/*.csv {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    dateext
    dateformat -%Y%m%d
}

# Asterisk CDR Custom Logs
/var/log/asterisk/cdr-custom/*.csv {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
    dateext
    dateformat -%Y%m%d
}

# Asterisk RTP Stats Log
/var/log/asterisk/rtp_stats.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 asterisk asterisk
}
EOF

print_success "AutoDialer logrotate configuration created"

# =============================================
# Create Nginx Logrotate Configuration
# =============================================
print_step "Creating Nginx logrotate configuration..."

cat > /etc/logrotate.d/nginx-autodialer << 'EOF'
# Nginx Access Log
/var/log/nginx/access.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        systemctl reload nginx > /dev/null 2>&1 || true
    endscript
}

# Nginx Error Log
/var/log/nginx/error.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        systemctl reload nginx > /dev/null 2>&1 || true
    endscript
}
EOF

print_success "Nginx logrotate configuration created"

# =============================================
# Create PostgreSQL Logrotate Configuration
# =============================================
print_step "Creating PostgreSQL logrotate configuration..."

cat > /etc/logrotate.d/postgresql-autodialer << 'EOF'
# PostgreSQL Logs
/var/log/postgresql/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 postgres postgres
    sharedscripts
    postrotate
        /usr/lib/postgresql/*/bin/pg_ctl reload -D /var/lib/postgresql/*/main > /dev/null 2>&1 || true
    endscript
}
EOF

print_success "PostgreSQL logrotate configuration created"

# =============================================
# Create Redis Logrotate Configuration
# =============================================
print_step "Creating Redis logrotate configuration..."

cat > /etc/logrotate.d/redis-autodialer << 'EOF'
# Redis Logs
/var/log/redis/redis-server.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 redis redis
    sharedscripts
    postrotate
        systemctl reload redis-server > /dev/null 2>&1 || true
    endscript
}
EOF

print_success "Redis logrotate configuration created"

# =============================================
# Create Fail2ban Logrotate Configuration
# =============================================
print_step "Creating Fail2ban logrotate configuration..."

cat > /etc/logrotate.d/fail2ban-autodialer << 'EOF'
# Fail2ban Logs
/var/log/fail2ban.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
    sharedscripts
    postrotate
        systemctl reload fail2ban > /dev/null 2>&1 || true
    endscript
}
EOF

print_success "Fail2ban logrotate configuration created"

# =============================================
# Create System Logrotate Configuration
# =============================================
print_step "Creating system logrotate configuration..."

cat > /etc/logrotate.d/system-autodialer << 'EOF'
# Auth Log
/var/log/auth.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
    sharedscripts
    postrotate
        systemctl reload rsyslog > /dev/null 2>&1 || true
    endscript
}

# Syslog
/var/log/syslog {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
    sharedscripts
    postrotate
        systemctl reload rsyslog > /dev/null 2>&1 || true
    endscript
}

# Kernel Log
/var/log/kern.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
}
EOF

print_success "System logrotate configuration created"

# =============================================
# Create Logrotate Helper Scripts
# =============================================
print_step "Creating logrotate helper scripts..."

# Status script
cat > /usr/local/bin/autodialer-logrotate-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Logrotate Status"
echo "=============================================="
echo ""

echo "=== Logrotate Configuration Files ==="
ls -la /etc/logrotate.d/ | grep -E "autodialer|nginx|postgres|redis|fail2ban|system"

echo ""
echo "=== Logrotate Status ==="
logrotate -d /etc/logrotate.conf 2>&1 | head -30

echo ""
echo "=== Log File Sizes ==="
echo ""
echo "Backend Logs:"
du -sh /opt/autodialer/logs/*.log 2>/dev/null || echo "  No logs found"

echo ""
echo "Asterisk Logs:"
du -sh /var/log/asterisk/* 2>/dev/null | head -10 || echo "  No logs found"

echo ""
echo "Nginx Logs:"
du -sh /var/log/nginx/*.log 2>/dev/null || echo "  No logs found"

echo ""
echo "Database Logs:"
du -sh /var/log/postgresql/*.log 2>/dev/null || echo "  No logs found"

echo ""
echo "System Logs:"
du -sh /var/log/syslog /var/log/auth.log 2>/dev/null || echo "  No logs found"
EOF
chmod +x /usr/local/bin/autodialer-logrotate-status

# Force rotation script
cat > /usr/local/bin/autodialer-logrotate-force << 'EOF'
#!/bin/bash
echo "Forcing log rotation..."
echo ""

echo "Rotating AutoDialer logs..."
logrotate -f /etc/logrotate.d/autodialer

echo "Rotating Nginx logs..."
logrotate -f /etc/logrotate.d/nginx-autodialer

echo "Rotating PostgreSQL logs..."
logrotate -f /etc/logrotate.d/postgresql-autodialer

echo "Rotating Redis logs..."
logrotate -f /etc/logrotate.d/redis-autodialer

echo "Rotating Fail2ban logs..."
logrotate -f /etc/logrotate.d/fail2ban-autodialer

echo ""
echo "All logs rotated!"
EOF
chmod +x /usr/local/bin/autodialer-logrotate-force

# Cleanup old logs script
cat > /usr/local/bin/autodialer-logs-cleanup << 'EOF'
#!/bin/bash
echo "Cleaning up old log archives..."
echo ""

# Remove compressed logs older than 60 days
find /opt/autodialer/logs -name "*.gz" -mtime +60 -delete 2>/dev/null
find /var/log/asterisk -name "*.gz" -mtime +60 -delete 2>/dev/null
find /var/log/nginx -name "*.gz" -mtime +60 -delete 2>/dev/null

echo "Old log archives cleaned up!"
echo ""
echo "Current disk usage:"
df -h /var/log
EOF
chmod +x /usr/local/bin/autodialer-logs-cleanup

print_success "Helper scripts created"

# =============================================
# Test Configuration
# =============================================
print_step "Testing logrotate configuration..."

# Test AutoDialer config
if logrotate -d /etc/logrotate.d/autodialer &>/dev/null; then
    print_success "AutoDialer config test passed"
else
    print_warn "AutoDialer config test failed"
fi

# Test Nginx config
if logrotate -d /etc/logrotate.d/nginx-autodialer &>/dev/null; then
    print_success "Nginx config test passed"
else
    print_warn "Nginx config test failed"
fi

# =============================================
# Add Cron Job for Logrotate (if not exists)
# =============================================
print_step "Ensuring logrotate cron job..."

# Logrotate is typically run by cron.daily
if [ ! -f /etc/cron.daily/logrotate ]; then
    cat > /etc/cron.daily/logrotate << 'EOF'
#!/bin/sh
/usr/sbin/logrotate /etc/logrotate.conf
EXITVALUE=$?
if [ $EXITVALUE != 0 ]; then
    /usr/bin/logger -t logrotate "ALERT exited abnormally with [$EXITVALUE]"
fi
exit $EXITVALUE
EOF
    chmod +x /etc/cron.daily/logrotate
    print_success "Logrotate cron job created"
else
    print_info "Logrotate cron job already exists"
fi

# =============================================
# Summary
# =============================================
print_success "Logrotate setup completed!"
echo ""
print_info "Logrotate Configuration Files:"
echo "  /etc/logrotate.d/autodialer           - Backend & Asterisk logs"
echo "  /etc/logrotate.d/nginx-autodialer     - Nginx logs"
echo "  /etc/logrotate.d/postgresql-autodialer - PostgreSQL logs"
echo "  /etc/logrotate.d/redis-autodialer     - Redis logs"
echo "  /etc/logrotate.d/fail2ban-autodialer  - Fail2ban logs"
echo "  /etc/logrotate.d/system-autodialer    - System logs"
echo ""
print_info "Log Retention:"
echo "  Backend logs:       30 days"
echo "  Asterisk logs:      7 days (3 for debug/verbose/dtmf)"
echo "  CDR logs:           30 days"
echo "  Nginx logs:         14 days"
echo "  Database logs:      7 days"
echo "  System logs:        7 days"
echo ""
print_info "Helper Scripts:"
echo "  autodialer-logrotate-status  - View status and sizes"
echo "  autodialer-logrotate-force   - Force rotation now"
echo "  autodialer-logs-cleanup      - Clean old archives"
echo ""
print_info "Useful Commands:"
echo "  logrotate -d /etc/logrotate.d/autodialer  - Test config"
echo "  logrotate -f /etc/logrotate.d/autodialer  - Force rotation"
echo "  logrotate -v /etc/logrotate.conf          - Verbose run"
echo "  du -sh /var/log/*                         - Check log sizes"
echo ""
