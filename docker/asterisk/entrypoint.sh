#!/bin/sh
set -e

# Renders manager.conf / pjsip.conf from the checked-in templates using
# environment variables (docker-compose / .env), then starts Asterisk in
# the foreground. Mirrors what scripts/04_pjsip_config.sh does for
# bare-metal installs, but driven by env vars instead of editing files
# on disk.

: "${FREEPBX_IP:?FREEPBX_IP must be set (IP of the existing SIP PBX to register to)}"
: "${FREEPBX_EXTENSION:=291}"
: "${EXTENSION_PASSWORD:?EXTENSION_PASSWORD must be set}"
: "${AMI_PASSWORD:?AMI_PASSWORD must be set}"
: "${ADMIN_AMI_PASSWORD:=admin_secret_2024}"
: "${MONITOR_AMI_PASSWORD:=monitor_secret_2024}"

export FREEPBX_IP FREEPBX_EXTENSION EXTENSION_PASSWORD AMI_PASSWORD ADMIN_AMI_PASSWORD MONITOR_AMI_PASSWORD

envsubst '${FREEPBX_IP} ${FREEPBX_EXTENSION} ${EXTENSION_PASSWORD}' \
    < /etc/asterisk/pjsip.conf.template > /etc/asterisk/pjsip.conf

envsubst '${AMI_PASSWORD} ${ADMIN_AMI_PASSWORD} ${MONITOR_AMI_PASSWORD}' \
    < /etc/asterisk/manager.conf.template > /etc/asterisk/manager.conf

# manager.conf ships with bindaddr=127.0.0.1 for bare-metal (Asterisk and
# the backend on the same host). In Docker the backend reaches Asterisk
# over the compose network under a different hostname, so AMI must listen
# on all interfaces; the container itself is not exposed outside the
# compose network unless AMI_PORT is explicitly published.
sed -i 's/^bindaddr = 127.0.0.1/bindaddr = 0.0.0.0/' /etc/asterisk/manager.conf

# AMI users are permit/deny-restricted to 127.0.0.1 by default (correct for
# bare-metal where the backend runs on the same host). In Docker the
# backend connects from a different container on the compose bridge
# network, so also permit the Docker bridge range. AMI is never published
# outside the compose network (see docker-compose.yml), so this stays
# private to the deployment.
sed -i '/^\[autodialer\]/,/^\[/ s#^permit = 127.0.0.1/255.255.255.255#permit = 127.0.0.1/255.255.255.255\npermit = 172.16.0.0/255.240.0.0#' /etc/asterisk/manager.conf

chown asterisk:asterisk /etc/asterisk/pjsip.conf /etc/asterisk/manager.conf
chmod 640 /etc/asterisk/pjsip.conf /etc/asterisk/manager.conf

exec asterisk -f -U asterisk -G asterisk -vvv
