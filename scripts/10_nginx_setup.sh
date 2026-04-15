#!/bin/bash
# Nginx Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Setting up Nginx..."

# Copy frontend
cp "$SCRIPT_DIR/../frontend/dist/index.html" /opt/autodialer/frontend/dist/

# Copy nginx config
cp "$SCRIPT_DIR/../nginx/autodialer.conf" /etc/nginx/sites-available/autodialer

ln -sf /etc/nginx/sites-available/autodialer /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl reload nginx

print_success "Nginx configured"
