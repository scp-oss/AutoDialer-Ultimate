#!/bin/bash
# Asterisk 21 Installation

set -e
source "$SCRIPT_DIR/../.env"

print_step "Installing Asterisk 21 from source..."

cd /usr/src

# Download
wget -q https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-21-current.tar.gz
tar -xzf asterisk-21-current.tar.gz
cd asterisk-21.*

# Install prerequisites
contrib/scripts/install_prereq install
contrib/scripts/get_mp3_source.sh

# Configure
./configure --with-pjproject-bundled --with-jansson-bundled --with-ssl

# Select modules
make menuselect.makeopts
menuselect/menuselect --enable app_dial \
                      --enable app_playback \
                      --enable app_userevent \
                      --enable app_read \
                      --enable app_verbose \
                      --enable app_answer \
                      --enable app_waituntil \
                      --enable app_progress \
                      --enable app_mixmonitor \
                      --enable chan_pjsip \
                      --enable res_pjsip \
                      --enable res_pjsip_outbound_registration \
                      --enable res_pjsip_session \
                      --enable res_rtp_asterisk \
                      --enable res_monitor \
                      --enable cdr_csv \
                      --enable cdr_custom \
                      --enable func_callerid \
                      --enable func_cdr \
                      --enable func_channel \
                      --enable func_strings \
                      --enable func_timeout \
                      --enable func_hangupcause \
                      --enable func_global \
                      menuselect.makeopts

# Build and install
make -j$(nproc)
make install
make samples
make config

# Create asterisk user
useradd -m asterisk -s /sbin/nologin || true
chown -R asterisk:asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk /etc/asterisk
mkdir -p /var/run/asterisk
chown -R asterisk:asterisk /var/run/asterisk

print_success "Asterisk 21 installed"
