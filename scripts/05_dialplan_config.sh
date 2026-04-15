#!/bin/bash
# Dialplan Configuration

set -e
source "$SCRIPT_DIR/../.env"

print_step "Configuring Dialplan..."

cp "$SCRIPT_DIR/../asterisk/extensions.conf" /etc/asterisk/

print_success "Dialplan configured"
