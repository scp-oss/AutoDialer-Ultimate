#!/bin/bash
# System Setup & Dependencies

set -e
source "$SCRIPT_DIR/../.env"

print_step "System setup..."

# Update system
apt update && apt upgrade -y

# Install base packages
apt install -y curl wget git gnupg lsb-release ca-certificates software-properties-common \
    build-essential libssl-dev libncurses5-dev libnewt-dev libxml2-dev \
    linux-headers-$(uname -r) libsqlite3-dev uuid-dev libjansson-dev \
    libedit-dev pkg-config autoconf automake libtool libtool-bin \
    python3 python3-pip python3-venv python3-dev \
    redis-server postgresql postgresql-contrib \
    nginx ufw fail2ban sox iptables-persistent net-tools \
    libcap2-bin

# System limits
cat >> /etc/security/limits.conf << EOF
* soft nofile 655350
* hard nofile 655350
asterisk soft nofile 655350
asterisk hard nofile 655350
autodialer soft nofile 655350
autodialer hard nofile 655350
EOF

# Sysctl tuning
cat >> /etc/sysctl.conf << EOF
fs.file-max = 2097152
net.core.somaxconn = 65535
net.ipv4.tcp_fin_timeout = 10
net.ipv4.tcp_tw_reuse = 1
vm.swappiness = 10
EOF

sysctl -p

print_success "System setup complete"
