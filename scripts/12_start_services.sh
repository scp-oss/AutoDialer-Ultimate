#!/bin/bash
# Start All Services

set -e
source "$SCRIPT_DIR/../.env"

print_step "Starting all services..."

# Copy systemd service
cp "$SCRIPT_DIR/../systemd/autodialer.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable asterisk postgresql redis-server autodialer nginx
systemctl restart asterisk
sleep 5
systemctl restart postgresql redis-server
sleep 2
systemctl restart autodialer nginx

print_success "All services started"
