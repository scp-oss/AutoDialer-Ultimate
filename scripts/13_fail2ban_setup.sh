#!/bin/bash
# Fail2Ban Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Setting up Fail2Ban..."

# Copy configurations
cp "$SCRIPT_DIR/../fail2ban/jail.local" /etc/fail2ban/jail.local
cp "$SCRIPT_DIR/../fail2ban/filter.d/asterisk.conf" /etc/fail2ban/filter.d/asterisk.conf

systemctl enable fail2ban
systemctl restart fail2ban

print_success "Fail2Ban configured"
