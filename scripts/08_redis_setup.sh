#!/bin/bash
# =============================================
# AutoDialer Ultimate - Redis Setup
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
# Configuration
# =============================================
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_MAXMEMORY="${REDIS_MAXMEMORY:-256mb}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# redis-cli reads REDISCLI_AUTH automatically, so every bare `redis-cli`
# call below authenticates without needing its own -a flag. Without this,
# every verification/test call in this script (ping, SET/GET, Lua EVAL,
# CONFIG GET, INFO...) hit "NOAUTH Authentication required." once
# requirepass is set below - and since redis-cli still exits 0 on a NOAUTH
# reply, those checks were silently "passing" on the error text itself
# rather than actually verifying anything.
[ -n "$REDIS_PASSWORD" ] && export REDISCLI_AUTH="$REDIS_PASSWORD"

# =============================================
# Install Redis
# =============================================
print_step "Checking Redis installation..."

if ! command -v redis-server &> /dev/null; then
    print_info "Installing Redis..."
    apt update
    apt install -y redis-server
    print_success "Redis installed"
else
    REDIS_VERSION=$(redis-server --version | head -1)
    print_success "Redis already installed: $REDIS_VERSION"
fi

# =============================================
# Configure Redis
# =============================================
print_step "Configuring Redis..."

# Backup original config
if [ -f /etc/redis/redis.conf ] && [ ! -f /etc/redis/redis.conf.backup ]; then
    cp /etc/redis/redis.conf /etc/redis/redis.conf.backup
    print_info "Original configuration backed up"
fi

# Create Redis configuration
cat > /etc/redis/redis.conf << EOF
# =============================================
# Redis Configuration for AutoDialer Ultimate
# =============================================

# Network
bind ${REDIS_HOST}
port ${REDIS_PORT}
protected-mode yes
tcp-backlog 511
timeout 0
tcp-keepalive 300

# General
daemonize yes
supervised systemd
pidfile /var/run/redis/redis-server.pid
loglevel notice
logfile /var/log/redis/redis-server.log
databases 16
always-show-logo no

# Authentication
EOF

if [ -n "$REDIS_PASSWORD" ]; then
    echo "requirepass $REDIS_PASSWORD" >> /etc/redis/redis.conf
    print_info "Redis password configured"
else
    echo "# requirepass (not set)" >> /etc/redis/redis.conf
fi

cat >> /etc/redis/redis.conf << EOF

# Snapshotting (RDB)
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /var/lib/redis

# Append Only File (AOF)
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite yes
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
aof-load-truncated yes
aof-use-rdb-preamble yes

# Memory Management
maxmemory ${REDIS_MAXMEMORY}
maxmemory-policy allkeys-lru
maxmemory-samples 5

# Replication
# slaveof <masterip> <masterport>
# masterauth <master-password>
slave-serve-stale-data yes
slave-read-only yes
repl-diskless-sync no
repl-diskless-sync-delay 5
repl-disable-tcp-nodelay no
slave-priority 100

# Lua Scripts
lua-time-limit 5000

# Slow Log
slowlog-log-slower-than 10000
slowlog-max-len 128

# Latency Monitor
latency-monitor-threshold 0

# Event Notification
notify-keyspace-events "Ex"

# Advanced
hash-max-ziplist-entries 512
hash-max-ziplist-value 64
list-max-ziplist-size -2
list-compress-depth 0
set-max-intset-entries 512
zset-max-ziplist-entries 128
zset-max-ziplist-value 64
hll-sparse-max-bytes 3000
stream-node-max-bytes 4096
stream-node-max-entries 100
activerehashing yes
client-output-buffer-limit normal 0 0 0
client-output-buffer-limit slave 256mb 64mb 60
client-output-buffer-limit pubsub 32mb 8mb 60
hz 10
dynamic-hz yes
aof-rewrite-incremental-fsync yes
rdb-save-incremental-fsync yes

# Active Defragmentation
activedefrag no
active-defrag-ignore-bytes 100mb
active-defrag-threshold-lower 10
active-defrag-threshold-upper 100
active-defrag-cycle-min 1
active-defrag-cycle-max 25
active-defrag-max-scan-fields 1000
EOF

print_success "Redis configuration created"

# =============================================
# Configure System Limits for Redis
# =============================================
print_step "Configuring system limits for Redis..."

# Disable Transparent Huge Pages (THP)
if [ -f /sys/kernel/mm/transparent_hugepage/enabled ]; then
    echo never > /sys/kernel/mm/transparent_hugepage/enabled
    print_info "Transparent Huge Pages disabled"
fi

# Set vm.overcommit_memory
/sbin/sysctl -w vm.overcommit_memory=1
echo "vm.overcommit_memory = 1" >> /etc/sysctl.conf

# Set net.core.somaxconn
/sbin/sysctl -w net.core.somaxconn=65535

print_success "System limits configured"

# =============================================
# Create Redis Systemd Override
# =============================================
print_step "Creating systemd override for Redis..."

mkdir -p /etc/systemd/system/redis-server.service.d

cat > /etc/systemd/system/redis-server.service.d/limits.conf << 'EOF'
[Service]
LimitNOFILE=65535
LimitMEMLOCK=infinity
LimitNPROC=65535
TasksMax=infinity
EOF

systemctl daemon-reload
print_success "Systemd override created"

# =============================================
# Start and Enable Redis
# =============================================
print_step "Starting Redis..."

systemctl enable redis-server
systemctl restart redis-server

# Wait for Redis to be ready
for i in {1..10}; do
    if redis-cli ping &>/dev/null; then
        print_success "Redis is ready"
        break
    fi
    print_info "Waiting for Redis... ($i/10)"
    sleep 1
done

# =============================================
# Verify Redis Installation
# =============================================
print_step "Verifying Redis installation..."

# Check connection
if redis-cli ping &>/dev/null; then
    REDIS_RESPONSE=$(redis-cli ping)
    print_success "Redis responded: $REDIS_RESPONSE"
else
    print_error "Redis connection failed"
    exit 1
fi

# Check configuration
print_info "Redis INFO:"
redis-cli INFO server | grep -E "redis_version|redis_mode|os" || true
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human" || true
redis-cli INFO persistence | grep -E "rdb_last_save_time|aof_enabled" || true
redis-cli INFO stats | grep -E "total_connections_received|total_commands_processed" || true

# Check maxmemory
MAXMEMORY=$(redis-cli CONFIG GET maxmemory | tail -1)
if [ "$MAXMEMORY" != "0" ]; then
    print_success "Maxmemory configured: $(echo $MAXMEMORY | numfmt --to=iec)"
else
    print_warn "Maxmemory not configured"
fi

# Check persistence
if redis-cli CONFIG GET appendonly | grep -q "yes"; then
    print_success "AOF persistence enabled"
fi

if redis-cli CONFIG GET save | grep -q "900"; then
    print_success "RDB persistence enabled"
fi

# =============================================
# Test Redis Functionality
# =============================================
print_step "Testing Redis functionality..."

# Test SET/GET
TEST_KEY="autodialer:test:$(date +%s)"
TEST_VALUE="ok"
redis-cli SET "$TEST_KEY" "$TEST_VALUE" EX 10 > /dev/null
RETRIEVED=$(redis-cli GET "$TEST_KEY")
if [ "$RETRIEVED" == "$TEST_VALUE" ]; then
    print_success "SET/GET test passed"
else
    print_error "SET/GET test failed"
fi

# Test Lua scripting
LUA_RESULT=$(redis-cli EVAL "return 'hello'" 0)
if [ "$LUA_RESULT" == "hello" ]; then
    print_success "Lua scripting test passed"
else
    print_warn "Lua scripting test failed"
fi

# Clean up
redis-cli DEL "$TEST_KEY" > /dev/null 2>&1 || true

# =============================================
# Create Redis Helper Scripts
# =============================================
print_step "Creating Redis helper scripts..."

# Script to check queue status
cat > /usr/local/bin/autodialer-redis-status << 'EOF'
#!/bin/bash
# AutoDialer Redis Status Helper
[ -f /opt/autodialer/.env ] && REDISCLI_AUTH=$(grep -m1 '^REDIS_PASSWORD=' /opt/autodialer/.env | cut -d= -f2-)
export REDISCLI_AUTH

echo "=============================================="
echo "AutoDialer Redis Status"
echo "=============================================="
echo ""

echo "=== Connection Info ==="
redis-cli INFO server | grep -E "redis_version|uptime_in_seconds"
echo ""

echo "=== Memory ==="
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|mem_fragmentation_ratio"
echo ""

echo "=== Persistence ==="
redis-cli INFO persistence | grep -E "rdb_last_save_time|aof_enabled|aof_current_size"
echo ""

echo "=== Keyspace ==="
redis-cli INFO keyspace
echo ""

echo "=== AutoDialer Keys ==="
echo "Active channels: $(redis-cli SCARD active_channels 2>/dev/null || echo 0)"
echo "Dial queue size: $(redis-cli LLEN dial_queue 2>/dev/null || echo 0)"
echo "System enabled: $(redis-cli GET system_enabled 2>/dev/null || echo 'true')"
echo ""

echo "=== Slow Log ==="
redis-cli SLOWLOG GET 5 2>/dev/null || echo "No slow log entries"
EOF

chmod +x /usr/local/bin/autodialer-redis-status

# Script to flush queue (emergency)
cat > /usr/local/bin/autodialer-redis-flush-queue << 'EOF'
#!/bin/bash
# Emergency queue flush
[ -f /opt/autodialer/.env ] && REDISCLI_AUTH=$(grep -m1 '^REDIS_PASSWORD=' /opt/autodialer/.env | cut -d= -f2-)
export REDISCLI_AUTH

echo "WARNING: This will clear the dial queue!"
read -p "Are you sure? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    redis-cli DEL dial_queue
    echo "Dial queue cleared"
else
    echo "Cancelled"
fi
EOF

chmod +x /usr/local/bin/autodialer-redis-flush-queue

print_success "Helper scripts created"

# =============================================
# Summary
# =============================================
print_success "Redis setup completed!"
echo ""
print_info "Redis Configuration:"
echo "  Host: $REDIS_HOST"
echo "  Port: $REDIS_PORT"
echo "  Maxmemory: $REDIS_MAXMEMORY"
if [ -n "$REDIS_PASSWORD" ]; then
    echo "  Password: $REDIS_PASSWORD"
else
    echo "  Password: (none)"
fi
echo ""
print_info "Persistence:"
echo "  RDB: enabled"
echo "  AOF: enabled"
echo ""
print_info "Useful Commands:"
echo "  redis-cli ping                    - Test connection"
echo "  redis-cli INFO                    - Server information"
echo "  redis-cli MONITOR                 - Monitor all commands"
echo "  redis-cli --scan --pattern '*'    - List all keys"
echo "  autodialer-redis-status           - Show AutoDialer status"
echo "  autodialer-redis-flush-queue      - Emergency queue flush"
echo ""
print_info "AutoDialer Redis Keys:"
echo "  active_channels    - Set of active call channels"
echo "  dial_queue         - List of pending calls"
echo "  system_enabled     - Global system enable flag"
echo "  refresh:*          - JWT refresh tokens"
echo "  rate_limit:*       - Rate limiting counters"
echo "  leader:*           - Leader election locks"
echo ""
