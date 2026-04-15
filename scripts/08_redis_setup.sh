#!/bin/bash
# Redis Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Setting up Redis..."

cat > /etc/redis/redis.conf << EOF
bind 127.0.0.1
port 6379
daemonize yes
supervised systemd
pidfile /var/run/redis/redis-server.pid
loglevel notice
logfile /var/log/redis/redis-server.log
databases 16
save 900 1
save 300 10
save 60 10000
dbfilename dump.rdb
dir /var/lib/redis
maxmemory 256mb
maxmemory-policy allkeys-lru
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite yes
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
EOF

systemctl enable redis-server
systemctl restart redis-server

print_success "Redis configured"
