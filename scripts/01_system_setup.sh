#!/bin/bash
# =============================================
# AutoDialer Ultimate - System Setup Script
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

# =============================================
# System Update
# =============================================
print_step "Updating system packages..."
apt update && apt upgrade -y

# =============================================
# Install Base Dependencies
# =============================================
print_step "Installing base dependencies..."
apt install -y \
    curl \
    wget \
    git \
    gnupg \
    lsb-release \
    ca-certificates \
    software-properties-common \
    apt-transport-https \
    build-essential \
    pkg-config \
    autoconf \
    automake \
    libtool \
    libtool-bin \
    cmake \
    make \
    gcc \
    g++ \
    unzip \
    tar \
    bzip2 \
    xz-utils \
    net-tools \
    iproute2 \
    dnsutils \
    htop \
    iotop \
    vim \
    nano \
    less \
    jq \
    tree

# =============================================
# Install Development Libraries
# =============================================
print_step "Installing development libraries..."
apt install -y \
    libssl-dev \
    libncurses5-dev \
    libnewt-dev \
    libxml2-dev \
    linux-headers-$(uname -r) \
    libsqlite3-dev \
    uuid-dev \
    libjansson-dev \
    libedit-dev \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    libcurl4-openssl-dev \
    libspeex-dev \
    libspeexdsp-dev \
    libgsm1-dev \
    libopus-dev \
    libvorbis-dev \
    libogg-dev \
    libspandsp-dev \
    libical-dev \
    libneon27-dev \
    libiksemel-dev \
    libpopt-dev \
    libcap2-bin \
    libsystemd-dev \
    liburiparser-dev \
    libxslt1-dev \
    libpq-dev \
    libmariadb-dev \
    libmariadb-dev-compat \
    libsnmp-dev \
    libvpb-dev \
    libpri-dev \
    libss7-dev \
    libopenr2-dev \
    libresample1-dev \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libavfilter-dev \
    libsrtp2-dev \
    libpjproject-dev

# =============================================
# Install Python and Tools
# =============================================
print_step "Installing Python and tools..."
apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-setuptools \
    python3-wheel \
    virtualenv

# Update pip
pip3 install --upgrade pip setuptools wheel

# =============================================
# Install Database and Cache
# =============================================
print_step "Installing PostgreSQL and Redis..."
apt install -y \
    postgresql \
    postgresql-contrib \
    postgresql-client \
    redis-server

# =============================================
# Install Web Server
# =============================================
print_step "Installing Nginx..."
apt install -y \
    nginx \
    nginx-extras

# =============================================
# Install Security Tools
# =============================================
print_step "Installing security tools..."
apt install -y \
    ufw \
    fail2ban \
    iptables-persistent \
    openssl \
    certbot \
    python3-certbot-nginx

# =============================================
# Install Audio Processing Tools
# =============================================
print_step "Installing audio processing tools..."
apt install -y \
    sox \
    libsox-fmt-all \
    ffmpeg \
    lame \
    flac \
    vorbis-tools

# =============================================
# Install Monitoring Tools
# =============================================
print_step "Installing monitoring tools..."
apt install -y \
    prometheus \
    prometheus-node-exporter \
    grafana

# =============================================
# System Limits Configuration
# =============================================
print_step "Configuring system limits..."

cat >> /etc/security/limits.conf << 'EOF'
# AutoDialer Ultimate Limits
* soft nofile 655350
* hard nofile 655350
* soft nproc 655350
* hard nproc 655350
root soft nofile 655350
root hard nofile 655350
asterisk soft nofile 655350
asterisk hard nofile 655350
asterisk soft nproc 655350
asterisk hard nproc 655350
autodialer soft nofile 655350
autodialer hard nofile 655350
postgres soft nofile 65535
postgres hard nofile 65535
redis soft nofile 65535
redis hard nofile 65535
nginx soft nofile 65535
nginx hard nofile 65535
EOF

# =============================================
# Sysctl Configuration
# =============================================
print_step "Configuring sysctl parameters..."

cat >> /etc/sysctl.conf << 'EOF'
# AutoDialer Ultimate Network Tuning
fs.file-max = 2097152
fs.nr_open = 2097152
fs.inotify.max_user_watches = 524288

# Network
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.core.rmem_default = 8388608
net.core.wmem_default = 8388608
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 10
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_tw_recycle = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_window_scaling = 1
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.udp_rmem_min = 8192
net.ipv4.udp_wmem_min = 8192

# Memory
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 500
vm.overcommit_memory = 1
vm.max_map_count = 262144

# Kernel
kernel.pid_max = 4194304
kernel.threads-max = 2097152
kernel.sched_autogroup_enabled = 1
kernel.sched_migration_cost_ns = 5000000
kernel.sched_latency_ns = 18000000
kernel.sched_min_granularity_ns = 3000000
kernel.sched_wakeup_granularity_ns = 4000000
EOF

# Apply sysctl settings
sysctl -p || true

# =============================================
# Create Required Users and Groups
# =============================================
print_step "Creating system users and groups..."

# Create asterisk user if not exists
if ! id -u asterisk &>/dev/null; then
    useradd -r -m -d /var/lib/asterisk -s /sbin/nologin -c "Asterisk PBX" asterisk
    print_info "Created asterisk user"
fi

# Create autodialer user if not exists
if ! id -u autodialer &>/dev/null; then
    useradd -r -m -d /opt/autodialer -s /bin/false -c "AutoDialer Service" autodialer
    print_info "Created autodialer user"
fi

# Add users to groups
usermod -a -G audio asterisk || true
usermod -a -G asterisk autodialer || true

# =============================================
# Create Required Directories
# =============================================
print_step "Creating required directories..."

mkdir -p /opt/autodialer/{backend,logs,config,frontend/dist,scripts,tmp}
mkdir -p /var/lib/asterisk/sounds/tts/{models,campaigns}
mkdir -p /var/log/asterisk
mkdir -p /var/spool/asterisk/{monitor,voicemail}
mkdir -p /var/run/asterisk

# Set permissions
chown -R asterisk:asterisk /var/lib/asterisk
chown -R asterisk:asterisk /var/log/asterisk
chown -R asterisk:asterisk /var/spool/asterisk
chown -R asterisk:asterisk /var/run/asterisk
chown -R autodialer:autodialer /opt/autodialer

# =============================================
# Configure Timezone and Locale
# =============================================
print_step "Configuring timezone and locale..."

# Set timezone (configurable via environment)
TIMEZONE="${TIMEZONE:-UTC}"
timedatectl set-timezone "$TIMEZONE" || true

# Generate locales
locale-gen en_US.UTF-8 ru_RU.UTF-8 || true
update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 || true

# =============================================
# Enable and Start Services
# =============================================
print_step "Enabling and starting services..."

systemctl enable postgresql || true
systemctl enable redis-server || true
systemctl enable nginx || true
systemctl enable fail2ban || true
systemctl enable prometheus || true
systemctl enable prometheus-node-exporter || true

systemctl start postgresql || true
systemctl start redis-server || true

# =============================================
# Firewall Configuration (UFW)
# =============================================
print_step "Configuring firewall..."

# Default policies
ufw default deny incoming
ufw default allow outgoing

# Allow SSH
ufw allow 22/tcp comment 'SSH'

# Allow HTTP/HTTPS
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

# Allow SIP (will be restricted later)
ufw allow 5060/udp comment 'SIP'
ufw allow 5061/tcp comment 'SIP TLS'

# Allow RTP
ufw allow 10000:20000/udp comment 'RTP'

# Allow PostgreSQL (localhost only - already restricted)
# ufw allow from 127.0.0.1 to any port 5432

# Allow Redis (localhost only)
# ufw allow from 127.0.0.1 to any port 6379

# Allow Prometheus/Grafana (internal network only)
# ufw allow from 10.0.0.0/8 to any port 9090
# ufw allow from 10.0.0.0/8 to any port 3000

# Enable firewall
ufw --force enable

# =============================================
# Systemd Overrides
# =============================================
print_step "Creating systemd override directories..."

mkdir -p /etc/systemd/system/asterisk.service.d
mkdir -p /etc/systemd/system/autodialer.service.d
mkdir -p /etc/systemd/system/nginx.service.d
mkdir -p /etc/systemd/system/postgresql.service.d
mkdir -p /etc/systemd/system/redis-server.service.d

# =============================================
# Logrotate Base Configuration
# =============================================
print_step "Configuring logrotate..."

cat > /etc/logrotate.d/autodialer-base << 'EOF'
/opt/autodialer/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 autodialer autodialer
}
EOF

# =============================================
# MOTD
# =============================================
print_step "Creating MOTD..."

cat > /etc/motd << 'EOF'
=============================================
     AutoDialer Ultimate Server
=============================================
Welcome to AutoDialer Ultimate!

Important paths:
  /opt/autodialer    - Application files
  /etc/asterisk      - Asterisk configuration
  /var/log/asterisk  - Asterisk logs

Useful commands:
  systemctl status autodialer
  systemctl status asterisk
  asterisk -rvvv

Documentation:
  /opt/autodialer/docs/
=============================================
EOF

# =============================================
# Cleanup
# =============================================
print_step "Cleaning up..."
apt autoremove -y
apt clean

# =============================================
# Summary
# =============================================
print_success "System setup completed!"
echo ""
print_info "System Information:"
echo "  Hostname: $(hostname)"
echo "  IP Address: $(hostname -I | awk '{print $1}')"
echo "  OS: $(lsb_release -ds)"
echo "  Kernel: $(uname -r)"
echo "  CPU: $(nproc) cores"
echo "  Memory: $(free -h | awk '/^Mem:/ {print $2}')"
echo ""
print_info "Installed Services:"
echo "  PostgreSQL: $(postgres --version 2>/dev/null || echo 'not installed')"
echo "  Redis: $(redis-server --version | head -1)"
echo "  Nginx: $(nginx -v 2>&1 | cut -d'/' -f2)"
echo "  Python: $(python3 --version)"
echo ""
print_info "Next steps:"
echo "  1. Run 02_asterisk_install.sh"
echo "  2. Run 03_asterisk_config.sh"
echo ""
