#!/bin/bash
# Logrotate Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Setting up Logrotate..."

cp "$SCRIPT_DIR/../logrotate/autodialer" /etc/logrotate.d/autodialer

# Asterisk logrotate
cat > /etc/logrotate.d/asterisk << 'EOF'
/var/log/asterisk/full
/var/log/asterisk/messages
/var/log/asterisk/security
/var/log/asterisk/queue_log {
    daily
    rotate 30
    compress
    missingok
    notifempty
    sharedscripts
    postrotate
        /usr/sbin/asterisk -rx 'logger reload' > /dev/null 2>&1 || true
    endscript
}
EOF

print_success "Logrotate configured"
