#!/bin/bash
# =============================================
# System Setup & Dependencies
# =============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../.env" 2>/dev/null || true

print_step() { echo -e "\033[32m[STEP]\033[0m $1"; }
print_info() { echo -e "\033[34m[INFO]\033[0m $1"; }
print_success() { echo -e "\033[36m[SUCCESS]\033[0m $1"; }

print_step "Updating system packages..."
apt update && apt upgrade -y

print_step "Installing base packages..."
apt install -y \
    curl wget git gnupg lsb-release ca-certificates software-properties-common \
    build-essential libssl-dev libncurses5-dev libnewt-dev libxml2-dev \
    linux-headers-$(uname -r) libsqlite3-dev uuid-dev libjansson-dev \
    libedit-dev pkg-config autoconf automake libtool libtool-bin \
    python3 python3-pip python3-venv python3-dev \
    redis-server postgresql postgresql-contrib \
    nginx ufw fail2ban sox iptables-persistent net-tools \
    libcap2-bin certbot python3-certbot-nginx

print_step "Configuring system limits..."
cat >> /etc/security/limits.conf << 'EOF'
* soft nofile 655350
* hard nofile 655350
* soft nproc 655350
* hard nproc 655350
root soft nofile 655350
root hard nofile 655350
asterisk soft nofile 655350
asterisk hard nofile 655350
autodialer soft nofile 655350
autodialer hard nofile 655350
EOF

print_step "Configuring sysctl..."
cat >> /etc/sysctl.conf << 'EOF'
fs.file-max = 2097152
fs.nr_open = 2097152
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 10
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
EOF

sysctl -p

print_success "System setup complete"
