#!/bin/bash
# Firewall Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Configuring firewall..."

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 5060/udp comment 'SIP'
ufw allow 10000:20000/udp comment 'RTP'
ufw --force enable

# Restrict SIP/RTP to FreePBX only
iptables -A INPUT -p udp --dport 5060 ! -s ${FREEPBX_IP} -j DROP
iptables -A INPUT -p udp --dport 10000:20000 ! -s ${FREEPBX_IP} -j DROP
netfilter-persistent save

print_success "Firewall configured"
