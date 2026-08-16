# AutoDialer Ultimate - Asterisk image
# Runs Asterisk with our PJSIP/AMI/dialplan config so app/services/dialer.py
# can connect over AMI and originate calls through a SIP trunk registered
# to the customer's existing IP-PBX (FREEPBX_IP/FREEPBX_EXTENSION).
#
# Base is ubuntu:24.04, not debian:12-slim: Debian dropped the `asterisk`
# package from its archive entirely (bookworm's repos only carry leftover
# asterisk-core-sounds-*/asterisk-prompt-* subpackages, not the daemon
# itself - `apt-get install asterisk` has no installation candidate on
# debian:12-slim, confirmed by actually building this image). Ubuntu's
# noble/universe repo carries asterisk 1:20.6.0~dfsg+~cs6.13.40431414-2build5
# - the exact same version already validated natively (see ROADMAP.md §1.4).
FROM ubuntu:24.04

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
COPY asterisk/amd.conf /etc/asterisk/amd.conf
COPY asterisk/extensions.conf /etc/asterisk/extensions.conf
COPY asterisk/manager.conf /etc/asterisk/manager.conf.template
COPY asterisk/pjsip.conf.template /etc/asterisk/pjsip.conf.template
COPY docker/asterisk/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/spool/asterisk/monitor /var/lib/asterisk/sounds/tts /var/run/asterisk \
    && chown -R asterisk:asterisk /etc/asterisk /var/spool/asterisk /var/lib/asterisk /var/log/asterisk /var/run/asterisk

EXPOSE 5060/udp 5060/tcp 5038/tcp 10000-10100/udp

ENTRYPOINT ["/entrypoint.sh"]
