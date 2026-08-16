#!/bin/bash
# =============================================
# AutoDialer Ultimate - Fail2ban Setup
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
# Install Fail2ban
# =============================================
print_step "Checking Fail2ban installation..."

if ! command -v fail2ban-client &> /dev/null; then
    print_info "Installing Fail2ban..."
    apt update
    apt install -y fail2ban iptables
    print_success "Fail2ban installed"
else
    FAIL2BAN_VERSION=$(fail2ban-client --version 2>&1 | head -1)
    print_success "Fail2ban already installed: $FAIL2BAN_VERSION"
fi

# =============================================
# Ensure the sshd jail's log file actually exists
# =============================================
# fail2ban-server refuses to start AT ALL if even one enabled jail's
# logpath is missing ("Have not found any log file for sshd jail" ->
# "Async configuration of server failed") - confirmed live, and it took
# down every other jail (asterisk, redis, autodialer-api, ...) with it,
# not just sshd. /var/log/auth.log only exists if rsyslog is installed
# and running; some minimal Debian images don't have it by default.
print_step "Проверка наличия /var/log/auth.log для sshd jail..."
if ! command -v rsyslogd &> /dev/null; then
    print_info "rsyslog не установлен, устанавливаю..."
    apt-get install -y rsyslog
fi
systemctl enable rsyslog --now 2>/dev/null || true
touch /var/log/auth.log
chmod 640 /var/log/auth.log
chown root:adm /var/log/auth.log 2>/dev/null || true
print_success "/var/log/auth.log готов"

# =============================================
# Create Jail Local Configuration
# =============================================
print_step "Creating jail.local configuration..."

cat > /etc/fail2ban/jail.local << 'EOF'
# =============================================
# AutoDialer Ultimate - Fail2ban Configuration
# =============================================

[DEFAULT]
# Ban time: 1 hour (3600 seconds)
bantime = 3600

# Find time window: 10 minutes
findtime = 600

# Maximum retries before ban
maxretry = 5

# Ignore localhost and private networks
ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16

# Backend for log monitoring
backend = auto

# Action on ban (only ban, no email)
action = %(action_)s

# =============================================
# SSH Protection
# =============================================
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

# =============================================
# Asterisk SIP Protection
# =============================================
[asterisk]
enabled = true
port = 5060,5061
filter = asterisk
logpath = /var/log/asterisk/security
maxretry = 3
bantime = 7200
findtime = 600

# =============================================
# Asterisk AMI Protection
# =============================================
[asterisk-ami]
enabled = true
port = 5038
filter = asterisk-ami
logpath = /var/log/asterisk/security
maxretry = 3
bantime = 3600
findtime = 600

# =============================================
# AutoDialer API Rate Limiting
# =============================================
[autodialer-api]
enabled = true
port = 80,443
filter = autodialer-api
logpath = /opt/autodialer/logs/backend/access.log
maxretry = 10
bantime = 1800
findtime = 60

# =============================================
# AutoDialer Auth Failures
# =============================================
[autodialer-auth]
enabled = true
port = 80,443
filter = autodialer-auth
logpath = /opt/autodialer/logs/autodialer.log
maxretry = 5
bantime = 3600
findtime = 300

# =============================================
# Nginx HTTP Auth
# =============================================
[nginx-http-auth]
enabled = true
port = http,https
filter = nginx-http-auth
logpath = /var/log/nginx/error.log
maxretry = 3
bantime = 1800

# =============================================
# Nginx Bad Bots
# =============================================
[nginx-badbots]
enabled = true
port = http,https
filter = nginx-badbots
logpath = /var/log/nginx/access.log
maxretry = 1
bantime = 86400

# =============================================
# Nginx Limit Req
# =============================================
[nginx-limit-req]
enabled = true
port = http,https
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 5
bantime = 600

# =============================================
# PostgreSQL Protection
# =============================================
[postgresql]
enabled = true
port = 5432
filter = postgresql
logpath = /var/log/postgresql/postgresql-*.log
maxretry = 3
bantime = 3600

# =============================================
# Recidive (Repeat Offenders)
# =============================================
[recidive]
enabled = true
filter = recidive
logpath = /var/log/fail2ban.log
action = %(action_)s
bantime = 604800
findtime = 86400
maxretry = 3
EOF

print_success "jail.local created"

# =============================================
# Create Asterisk Filter
# =============================================
print_step "Creating Asterisk filter..."

cat > /etc/fail2ban/filter.d/asterisk.conf << 'EOF'
# __prefix_line used below is defined in common.conf's [Definition], not
# ours - without pulling it in via [INCLUDES], fail2ban-server refuses to
# start at all ("Bad value substitution ... '__prefix_line' is not a
# valid option name"), taking down every other jail with it.
[INCLUDES]
before = common.conf

[Definition]
failregex = ^%(__prefix_line)s.*Registration from '[^']*' failed for '<HOST>(:\d+)?' - Wrong password$
            ^%(__prefix_line)s.*Registration from '[^']*' failed for '<HOST>(:\d+)?' - No matching peer found$
            ^%(__prefix_line)s.*Registration from '[^']*' failed for '<HOST>(:\d+)?' - Username/auth name mismatch$
            ^%(__prefix_line)s.*Registration from '[^']*' failed for '<HOST>(:\d+)?' - Device does not match ACL$
            ^%(__prefix_line)s.*Host <HOST> failed to authenticate as '[^']*'$
            ^%(__prefix_line)s.*No matching endpoint found for '[^']*' from <HOST>:\d+$
            ^%(__prefix_line)s.*Friendly scanner from <HOST>.*$
            ^%(__prefix_line)s.*SIP/2.0 \d{3} .* from <HOST>.*$
            ^%(__prefix_line)s.*SecurityEvent.*Failed to authenticate.*<HOST>.*$
ignoreregex =
EOF

print_success "asterisk.conf filter created"

# =============================================
# Create Asterisk AMI Filter
# =============================================
print_step "Creating Asterisk AMI filter..."

cat > /etc/fail2ban/filter.d/asterisk-ami.conf << 'EOF'
[INCLUDES]
before = common.conf

[Definition]
failregex = ^%(__prefix_line)s.*AMI.*Failed to authenticate user .* from <HOST>$
            ^%(__prefix_line)s.*Manager.*Failed to authenticate user .* from <HOST>$
            ^%(__prefix_line)s.*Manager.*Login failed for .* from <HOST>$
            ^%(__prefix_line)s.*HTTP Manager.*Login failed for .* from <HOST>$
ignoreregex =
EOF

print_success "asterisk-ami.conf filter created"

# =============================================
# Create AutoDialer API Filter
# =============================================
print_step "Creating AutoDialer API filter..."

cat > /etc/fail2ban/filter.d/autodialer-api.conf << 'EOF'
[Definition]
failregex = ^<HOST>.*"(GET|POST|PUT|DELETE|PATCH).*" 429 .*$
ignoreregex =
EOF

print_success "autodialer-api.conf filter created"

# =============================================
# Create AutoDialer Auth Filter
# =============================================
print_step "Creating AutoDialer Auth filter..."

cat > /etc/fail2ban/filter.d/autodialer-auth.conf << 'EOF'
[Definition]
failregex = ^.*ERROR.*Login failed for user .* from <HOST>$
            ^.*ERROR.*Invalid credentials.*<HOST>$
            ^.*WARNING.*Too many login attempts.*<HOST>$
ignoreregex =
EOF

print_success "autodialer-auth.conf filter created"

# =============================================
# Create PostgreSQL Filter
# =============================================
print_step "Creating PostgreSQL filter..."

cat > /etc/fail2ban/filter.d/postgresql.conf << 'EOF'
[INCLUDES]
before = common.conf

[Definition]
failregex = ^%(__prefix_line)s.*FATAL:.*password authentication failed for user.*HOST:\s*<HOST>.*$
            ^%(__prefix_line)s.*FATAL:.*no pg_hba.conf entry for host.*<HOST>.*$
ignoreregex =
EOF

print_success "postgresql.conf filter created"

# =============================================
# Create Nginx Bad Bots Filter
# =============================================
print_step "Creating Nginx bad bots filter..."

cat > /etc/fail2ban/filter.d/nginx-badbots.conf << 'EOF'
[Definition]
badbots = scan|bot|spider|crawl|scrape|curl|wget|python|perl|ruby|java|nmap|nikto|sqlmap|hydra|nessus

failregex = ^<HOST>.*"(GET|POST).*HTTP.*".*(?:%(badbots)s).*"$
ignoreregex =
EOF

print_success "nginx-badbots.conf filter created"

# =============================================
# Create Nginx Limit Req Filter
# =============================================
print_step "Creating Nginx limit req filter..."

cat > /etc/fail2ban/filter.d/nginx-limit-req.conf << 'EOF'
[Definition]
failregex = ^\s*\[error\] \d+#\d+: \*\d+ limiting requests, excess: [\d\.]+ by zone "[^"]+", client: <HOST>,
ignoreregex =
EOF

print_success "nginx-limit-req.conf filter created"

# =============================================
# Ensure every enabled jail's logpath actually exists
# =============================================
# fail2ban-server's config load is all-or-nothing: if even ONE enabled
# jail's logpath is missing, the ENTIRE daemon refuses to start ("Have
# not found any log file for <jail> jail" -> "Async configuration of
# server failed"), taking down every other jail with it. auth.log is
# handled above; these three are the other jails whose log file isn't
# guaranteed to exist yet at this point in the install:
#   - autodialer-api's logpath (fixed above to point at gunicorn's real
#     --access-logfile) - gunicorn only creates it once the backend has
#     actually started and logged a request.
#   - asterisk's/asterisk-ami's shared "security" logpath - Asterisk's
#     logger.conf security channel only creates the file on its first
#     write, not merely by being configured.
#   - autodialer.log (autodialer-auth jail) - created lazily by Python
#     logging on first write.
# nginx's and postgresql's log files are not touched here because those
# services already created them during their own setup scripts earlier
# in install.sh.
print_step "Проверка наличия log-файлов для всех jail fail2ban..."

mkdir -p /opt/autodialer/logs/backend
touch /opt/autodialer/logs/backend/access.log
chown autodialer:autodialer /opt/autodialer/logs/backend/access.log 2>/dev/null || true

mkdir -p /var/log/asterisk
touch /var/log/asterisk/security
chown asterisk:asterisk /var/log/asterisk/security 2>/dev/null || true

mkdir -p /opt/autodialer/logs
touch /opt/autodialer/logs/autodialer.log
chown autodialer:autodialer /opt/autodialer/logs/autodialer.log 2>/dev/null || true

print_success "Log-файлы для fail2ban готовы"

# =============================================
# Restart Fail2ban
# =============================================
print_step "Starting Fail2ban..."

systemctl enable fail2ban
systemctl restart fail2ban

if systemctl is-active --quiet fail2ban; then
    print_success "Fail2ban started"
else
    print_error "Fail2ban failed to start"
    exit 1
fi

# =============================================
# Verify Fail2ban
# =============================================
print_step "Verifying Fail2ban..."

# systemctl is-active reports the service "active" as soon as the process
# starts, before fail2ban-server has finished binding its control socket
# at /var/run/fail2ban/fail2ban.sock - a fixed `sleep 2` guessed wrong on
# a loaded box and fail2ban-client failed with "Is fail2ban running?"
# even though the service really was starting. Poll for the socket to
# actually respond instead of guessing a fixed delay.
for i in $(seq 1 15); do
    fail2ban-client ping &>/dev/null && break
    sleep 1
done
fail2ban-client ping &>/dev/null || print_error "fail2ban-client всё ещё не отвечает после 15с ожидания"

echo ""
print_info "Fail2ban Status:"
fail2ban-client status

echo ""
print_info "Active Jails:"
fail2ban-client status | grep "Jail list" | cut -d':' -f2 | tr ',' '\n' | while read jail; do
    jail=$(echo "$jail" | xargs)
    if [ -n "$jail" ]; then
        # `grep -c` counts MATCHING LINES, and "Currently banned:" is
        # always exactly one line in the output regardless of its value -
        # this always printed "banned: 1" even with zero bans. Extract the
        # actual count after the colon instead.
        status=$(fail2ban-client status "$jail" 2>/dev/null | grep "Currently banned" | awk -F':' '{print $2}' | xargs)
        echo "  ✓ $jail (banned: ${status:-0})"
    fi
done

# =============================================
# Create Helper Scripts
# =============================================
print_step "Creating helper scripts..."

# Status script
cat > /usr/local/bin/autodialer-fail2ban-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Fail2ban Status"
echo "=============================================="
echo ""

fail2ban-client status

echo ""
echo "Jail Details:"
for jail in $(fail2ban-client status | grep "Jail list" | cut -d':' -f2 | tr ',' ' '); do
    if [ -n "$jail" ]; then
        echo ""
        echo "=== $jail ==="
        fail2ban-client status "$jail"
    fi
done

echo ""
echo "Currently Banned IPs:"
fail2ban-client banned
EOF
chmod +x /usr/local/bin/autodialer-fail2ban-status

# Unban script
cat > /usr/local/bin/autodialer-fail2ban-unban << 'EOF'
#!/bin/bash
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <JAIL> <IP>"
    echo ""
    echo "Available jails:"
    fail2ban-client status | grep "Jail list" | cut -d':' -f2 | tr ',' '\n' | xargs
    exit 1
fi

JAIL="$1"
IP="$2"

fail2ban-client set "$JAIL" unbanip "$IP"
echo "Unbanned $IP from $JAIL"
EOF
chmod +x /usr/local/bin/autodialer-fail2ban-unban

# Ban script
cat > /usr/local/bin/autodialer-fail2ban-ban << 'EOF'
#!/bin/bash
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <JAIL> <IP>"
    echo ""
    echo "Available jails:"
    fail2ban-client status | grep "Jail list" | cut -d':' -f2 | tr ',' '\n' | xargs
    exit 1
fi

JAIL="$1"
IP="$2"

fail2ban-client set "$JAIL" banip "$IP"
echo "Banned $IP in $JAIL"
EOF
chmod +x /usr/local/bin/autodialer-fail2ban-ban

print_success "Helper scripts created"

# =============================================
# Summary
# =============================================
print_success "Fail2ban setup completed!"
echo ""
print_info "Active Jails:"
echo "  - sshd               : SSH protection"
echo "  - asterisk           : SIP protection"
echo "  - asterisk-ami       : AMI protection"
echo "  - autodialer-api     : API rate limiting"
echo "  - autodialer-auth    : Auth failures"
echo "  - nginx-http-auth    : Nginx auth"
echo "  - nginx-badbots      : Bad bots (24h ban)"
echo "  - nginx-limit-req    : Rate limiting"
echo "  - postgresql         : DB protection"
echo "  - recidive           : Repeat offenders (7 days)"
echo ""
print_info "Helper Scripts:"
echo "  autodialer-fail2ban-status   - View status"
echo "  autodialer-fail2ban-unban    - Unban IP"
echo "  autodialer-fail2ban-ban      - Ban IP manually"
echo ""
print_info "Useful Commands:"
echo "  fail2ban-client status                  - Overall status"
echo "  fail2ban-client status <jail>           - Jail status"
echo "  fail2ban-client set <jail> unbanip <IP> - Unban IP"
echo "  fail2ban-client set <jail> banip <IP>   - Ban IP"
echo "  fail2ban-client banned                  - List all banned IPs"
echo "  tail -f /var/log/fail2ban.log           - Watch log"
echo ""
