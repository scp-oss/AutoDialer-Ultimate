# AutoDialer Ultimate - Asterisk image
# Runs Asterisk with our PJSIP/AMI/dialplan config so app/services/dialer.py
# can connect over AMI and originate calls through a SIP trunk registered
# to the customer's existing IP-PBX (FREEPBX_IP/FREEPBX_EXTENSION).
FROM debian:12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    asterisk \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY asterisk/asterisk.conf /etc/asterisk/asterisk.conf
COPY asterisk/modules.conf /etc/asterisk/modules.conf
COPY asterisk/logger.conf /etc/asterisk/logger.conf
COPY asterisk/cdr.conf /etc/asterisk/cdr.conf
COPY asterisk/rtp.conf /etc/asterisk/rtp.conf
COPY asterisk/indications.conf /etc/asterisk/indications.conf
COPY asterisk/extensions.conf /etc/asterisk/extensions.conf
COPY asterisk/manager.conf /etc/asterisk/manager.conf.template
COPY asterisk/pjsip.conf.template /etc/asterisk/pjsip.conf.template
COPY docker/asterisk/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/spool/asterisk/monitor /var/lib/asterisk/sounds/tts \
    && chown -R asterisk:asterisk /etc/asterisk /var/spool/asterisk /var/lib/asterisk /var/log/asterisk /var/run/asterisk

EXPOSE 5060/udp 5060/tcp 5038/tcp 10000-10100/udp

ENTRYPOINT ["/entrypoint.sh"]
