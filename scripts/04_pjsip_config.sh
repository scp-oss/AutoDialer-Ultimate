#!/bin/bash
# PJSIP Configuration

set -e
source "$SCRIPT_DIR/../.env"

print_step "Configuring PJSIP..."

# Replace variables in template
sed -e "s/\${FREEPBX_IP}/${FREEPBX_IP}/g" \
    -e "s/\${EXTENSION_PASSWORD}/${EXTENSION_PASSWORD}/g" \
    "$SCRIPT_DIR/../asterisk/pjsip.conf.template" > /etc/asterisk/pjsip.conf

print_success "PJSIP configured"
