#!/bin/bash
# Asterisk Configuration

set -e
source "$SCRIPT_DIR/../.env"

print_step "Configuring Asterisk..."

cp "$SCRIPT_DIR/../asterisk/asterisk.conf" /etc/asterisk/
cp "$SCRIPT_DIR/../asterisk/rtp.conf" /etc/asterisk/

# Systemd limits
mkdir -p /etc/systemd/system/asterisk.service.d
cat > /etc/systemd/system/asterisk.service.d/limits.conf << EOF
[Service]
LimitNOFILE=655350
LimitMEMLOCK=infinity
LimitNPROC=655350
User=asterisk
Group=asterisk
CPUQuota=200%
[Unit]
After=network-online.target
Wants=network-online.target
EOF

systemctl daemon-reload

print_success "Asterisk configured"
