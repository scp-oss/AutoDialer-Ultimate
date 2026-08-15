#!/bin/bash
# =============================================
# AutoDialer Ultimate - Asterisk Configuration
# Version: 3.0.0
# =============================================

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[STEP]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${CYAN}[SUCCESS]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Copy Configuration Files
# =============================================
print_step "Copying Asterisk configuration files..."

# asterisk.conf
if [ -f "$PROJECT_ROOT/asterisk/asterisk.conf" ]; then
    cp "$PROJECT_ROOT/asterisk/asterisk.conf" /etc/asterisk/
    print_success "asterisk.conf copied"
else
    print_error "asterisk.conf not found"
    exit 1
fi

# rtp.conf
if [ -f "$PROJECT_ROOT/asterisk/rtp.conf" ]; then
    cp "$PROJECT_ROOT/asterisk/rtp.conf" /etc/asterisk/
    print_success "rtp.conf copied"
else
    print_warn "rtp.conf not found, using default"
fi

# logger.conf
if [ -f "$PROJECT_ROOT/asterisk/logger.conf" ]; then
    cp "$PROJECT_ROOT/asterisk/logger.conf" /etc/asterisk/
    print_success "logger.conf copied"
fi

# cdr.conf
if [ -f "$PROJECT_ROOT/asterisk/cdr.conf" ]; then
    cp "$PROJECT_ROOT/asterisk/cdr.conf" /etc/asterisk/
    print_success "cdr.conf copied"
fi

# indications.conf
if [ -f "$PROJECT_ROOT/asterisk/indications.conf" ]; then
    cp "$PROJECT_ROOT/asterisk/indications.conf" /etc/asterisk/
    print_success "indications.conf copied"
fi

# modules.conf
if [ -f "$PROJECT_ROOT/asterisk/modules.conf" ]; then
    cp "$PROJECT_ROOT/asterisk/modules.conf" /etc/asterisk/
    print_success "modules.conf copied"
fi

# =============================================
# Configure modules.conf (Auto-load)
# =============================================
print_step "Configuring modules.conf..."

cat > /etc/asterisk/modules.conf << 'EOF'
[modules]
autoload = yes

; Core modules (required)
load => pbx_config.so
load => logger.so
load => acl.so
load => sorcery.so
load => timing.so
load => cdr.so
load => cel.so

; Applications
load => app_dial.so
load => app_playback.so
load => app_userevent.so
load => app_read.so
load => app_verbose.so
load => app_answer.so
load => app_progress.so
load => app_mixmonitor.so
load => app_stack.so
load => app_echo.so
load => app_senddtmf.so
load => app_confbridge.so
load => app_amd.so

; Channel drivers
load => chan_pjsip.so
noload => chan_sip.so
noload => chan_iax2.so
noload => chan_dahdi.so
noload => chan_skinny.so
noload => chan_unistim.so
noload => chan_mgcp.so
noload => chan_alsa.so
noload => chan_console.so

; PJSIP
load => res_pjsip.so
load => res_pjsip_authenticator_digest.so
load => res_pjsip_endpoint_identifier_ip.so
load => res_pjsip_endpoint_identifier_user.so
load => res_pjsip_outbound_registration.so
load => res_pjsip_session.so
load => res_pjsip_logger.so
load => res_pjsip_notify.so
load => res_pjsip_pubsub.so

; RTP
load => res_rtp_asterisk.so

; CDR
load => cdr_csv.so
load => cdr_custom.so

; Functions
load => func_callerid.so
load => func_cdr.so
load => func_channel.so
load => func_strings.so
load => func_timeout.so
load => func_hangupcause.so
load => func_global.so
load => func_logic.so
load => func_math.so

; Format interpreters
load => format_wav.so
load => format_sln.so
load => format_gsm.so
load => format_pcm.so

; Resources
load => res_monitor.so
load => res_agi.so
load => res_sorcery_config.so
load => res_sorcery_memory.so
load => res_sorcery_astdb.so
load => res_timing_timerfd.so
load => res_musiconhold.so
load => res_security_log.so

; Disable unnecessary
noload => pbx_dundi.so
noload => pbx_ael.so
noload => pbx_lua.so
noload => res_phoneprov.so
noload => res_ael_share.so
noload => res_adsi.so
noload => res_ari.so
noload => res_calendar.so
noload => res_config_sqlite.so
noload => res_corosync.so
noload => res_fax.so
noload => res_hep.so
noload => res_xmpp.so
noload => codec_dahdi.so
EOF

print_success "modules.conf configured"

# =============================================
# Configure asterisk.conf
# =============================================
print_step "Configuring asterisk.conf..."

cat > /etc/asterisk/asterisk.conf << 'EOF'
[directories]
astetcdir => /etc/asterisk
astmoddir => /usr/lib/asterisk/modules
astvarlibdir => /var/lib/asterisk
astdbdir => /var/lib/asterisk
astkeydir => /var/lib/asterisk
astdatadir => /var/lib/asterisk
astagidir => /var/lib/asterisk/agi-bin
astspooldir => /var/spool/asterisk
astrundir => /var/run/asterisk
astlogdir => /var/log/asterisk
astsbindir => /usr/sbin

[options]
verbose = 3
debug = 0
maxcalls = 150
maxload = 10.0
transcode_via_sln = yes
runuser = asterisk
rungroup = asterisk
languageprefix = yes
execincludes = yes
dontwarn = yes
maxfiles = 655350

[files]
astctlpermissions = 0660
astctlowner = asterisk
astctlgroup = asterisk

[compat]
pbx_realtime = 1.6
res_agi = 1.6
app_set = 1.6
EOF

print_success "asterisk.conf configured"

# =============================================
# Configure rtp.conf
# =============================================
print_step "Configuring rtp.conf..."

cat > /etc/asterisk/rtp.conf << 'EOF'
[general]
rtpstart = 10000
rtpend = 20000
rtpchecksums = no
dtmftimeout = 3000
rtp_timeout = 30
rtp_timeout_hold = 60
rtpkeepalive = 30
strictrtp = yes
icesupport = no
rtcpsend = yes
rtcpinterval = 5000
rtpstats = yes
rtpstatlog = yes
rtpstatlogfile = /var/log/asterisk/rtp_stats.log
EOF

print_success "rtp.conf configured"

# =============================================
# Configure logger.conf
# =============================================
print_step "Configuring logger.conf..."

cat > /etc/asterisk/logger.conf << 'EOF'
[general]
dateformat = %F %T.%3q
queue_log = yes
rotatetimestamp = yes

[logfiles]
full => notice,warning,error,debug,verbose,dtmf,fax,security
messages => notice,warning,error
security => security
console => notice,warning,error,verbose
debug => debug,dtmf
verbose => verbose,dtmf
dtmf => dtmf
dialer => notice,warning,error,verbose,dtmf
EOF

print_success "logger.conf configured"

# =============================================
# Configure cdr.conf
# =============================================
print_step "Configuring cdr.conf..."

cat > /etc/asterisk/cdr.conf << 'EOF'
[general]
enable = yes
unanswered = yes
endbeforehexten = no
initiatedseconds = no
batch = no
safeshutdown = yes

[csv]
usegmtime = no
loguniqueid = yes
loguserfield = yes
accountlogs = yes
newcdrcolumns = yes

[custom]
master_file = /var/log/asterisk/cdr-custom/Master.csv
usegmtime = no
loguniqueid = yes
loguserfield = yes
format => "${CDR(accountcode)}|${CDR(src)}|${CDR(dst)}|${CDR(clid)}|${CDR(channel)}|${CDR(start)}|${CDR(answer)}|${CDR(end)}|${CDR(duration)}|${CDR(billsec)}|${CDR(disposition)}|${CDR(uniqueid)}|${CDR(userfield)}|${CDR(linkedid)}"
EOF

print_success "cdr.conf configured"

# =============================================
# Configure indications.conf
# =============================================
print_step "Configuring indications.conf..."

cat > /etc/asterisk/indications.conf << 'EOF'
[general]
country = ru

[ru]
description = Russia
ringcadence = 1000,4000
dial = 425
busy = 425/330,0/330
ring = 425/1000,0/4000
congestion = 425/330,0/330
callwaiting = 425/200,0/5000
dialrecall = 425
record = 1400/500,0/15000
info = !950/330,1400/330,1800/330,0/1000
stutter = !425/100,0/100
EOF

print_success "indications.conf configured"

# =============================================
# Configure extensions.conf (Basic)
# =============================================
print_step "Creating basic extensions.conf..."

cat > /etc/asterisk/extensions.conf << 'EOF'
[globals]
TRUNK_NAME = PJSIP/291_endpoint
CALL_TIMEOUT = 30
DTMF_TIMEOUT = 10

[default]
exten => _X.,1,NoOp(Unhandled call to ${EXTEN})
same => n,Hangup()

; Placeholder for dialer_bridge context
; Will be fully configured in 05_dialplan_config.sh
[dialer_bridge]
exten => _X.,1,NoOp(Dialer bridge not yet configured)
same => n,Hangup()
EOF

print_success "Basic extensions.conf created"

# =============================================
# Configure manager.conf (AMI)
# =============================================
print_step "Configuring manager.conf..."

AMI_PASSWORD="${AMI_PASSWORD:-$(openssl rand -hex 16)}"
ADMIN_AMI_PASSWORD="${ADMIN_AMI_PASSWORD:-admin_secret_2024}"

cat > /etc/asterisk/manager.conf << EOF
[general]
enabled = yes
bindaddr = 127.0.0.1
port = 5038
timestampevents = yes
webenabled = no
debug = off

[autodialer]
secret = ${AMI_PASSWORD}
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = system,call,log,verbose,command,agent,user,dtmf,originate,cdr,reporting
write = system,call,log,verbose,command,agent,user,dtmf,originate,cdr,reporting
eventfilter=!Event: Newexten
eventfilter=!Event: VarSet
eventfilter=!Event: DTMFBegin

[admin]
secret = ${ADMIN_AMI_PASSWORD}
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = all
write = all
EOF

print_success "manager.conf configured"
print_info "AMI password: ${AMI_PASSWORD}"
print_info "AMI admin password: ${ADMIN_AMI_PASSWORD}"

# =============================================
# Configure http.conf
# =============================================
print_step "Configuring http.conf..."

cat > /etc/asterisk/http.conf << 'EOF'
[general]
enabled = yes
bindaddr = 127.0.0.1
bindport = 8088
prefix = asterisk
enablestatic = yes
sessionlimit = 100
EOF

print_success "http.conf configured"

# =============================================
# Configure acl.conf
# =============================================
print_step "Configuring acl.conf..."

cat > /etc/asterisk/acl.conf << 'EOF'
[localhost]
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1
permit = ::1

[lan]
deny = 0.0.0.0/0.0.0.0
permit = 10.0.0.0/8
permit = 172.16.0.0/12
permit = 192.168.0.0/16
EOF

print_success "acl.conf configured"

# =============================================
# Configure features.conf
# =============================================
print_step "Configuring features.conf..."

cat > /etc/asterisk/features.conf << 'EOF'
[general]
featuredigittimeout = 1000
courtesytone = beep

[applicationmap]

[featuremap]
blindxfer => #
disconnect => *
automon => *1
atxfer => *2
EOF

print_success "features.conf configured"

# =============================================
# Configure codecs.conf
# =============================================
print_step "Configuring codecs.conf..."

cat > /etc/asterisk/codecs.conf << 'EOF'
[global]
disallow = all
allow = ulaw
allow = alaw
allow = g722
allow = gsm
allow = opus
allow = speex
EOF

print_success "codecs.conf configured"

# =============================================
# Set Permissions
# =============================================
print_step "Setting permissions..."

chown -R asterisk:asterisk /etc/asterisk
chmod 640 /etc/asterisk/*.conf
chmod 640 /etc/asterisk/manager.conf  # Extra security for AMI

print_success "Permissions set"

# =============================================
# Create Systemd Override
# =============================================
print_step "Creating systemd override for Asterisk..."

cat > /etc/systemd/system/asterisk.service.d/limits.conf << 'EOF'
[Service]
LimitNOFILE=655350
LimitMEMLOCK=infinity
LimitNPROC=655350
User=asterisk
Group=asterisk
CPUQuota=200%
MemoryMax=2G
TasksMax=infinity

[Unit]
After=network-online.target
Wants=network-online.target
EOF

systemctl daemon-reload

print_success "Systemd override created"

# =============================================
# Create Sound Directories
# =============================================
print_step "Creating sound directories..."

mkdir -p /var/lib/asterisk/sounds/tts
mkdir -p /var/lib/asterisk/sounds/tts/models
mkdir -p /var/lib/asterisk/sounds/tts/campaigns
mkdir -p /var/lib/asterisk/sounds/custom

chown -R asterisk:asterisk /var/lib/asterisk/sounds

print_success "Sound directories created"

# =============================================
# Verify Configuration
# =============================================
print_step "Verifying configuration..."

# Check syntax
if asterisk -rx "core show version" &>/dev/null; then
    print_success "Asterisk is responding"
else
    print_warn "Asterisk not responding (may need to be started)"
fi

# Check config files
CONFIG_FILES=(
    "/etc/asterisk/asterisk.conf"
    "/etc/asterisk/rtp.conf"
    "/etc/asterisk/logger.conf"
    "/etc/asterisk/cdr.conf"
    "/etc/asterisk/indications.conf"
    "/etc/asterisk/manager.conf"
    "/etc/asterisk/http.conf"
    "/etc/asterisk/acl.conf"
    "/etc/asterisk/features.conf"
    "/etc/asterisk/codecs.conf"
)

for config in "${CONFIG_FILES[@]}"; do
    if [ -f "$config" ]; then
        print_info "  ✓ $(basename $config)"
    else
        print_warn "  ✗ $(basename $config) missing"
    fi
done

# =============================================
# Summary
# =============================================
print_success "Asterisk configuration completed!"
echo ""
print_info "Configuration Files:"
echo "  /etc/asterisk/asterisk.conf"
echo "  /etc/asterisk/rtp.conf"
echo "  /etc/asterisk/logger.conf"
echo "  /etc/asterisk/cdr.conf"
echo "  /etc/asterisk/indications.conf"
echo "  /etc/asterisk/manager.conf"
echo "  /etc/asterisk/modules.conf"
echo ""
print_info "AMI Credentials:"
echo "  User: autodialer"
echo "  Password: ${AMI_PASSWORD}"
echo ""
print_info "Next steps:"
echo "  1. Configure PJSIP (04_pjsip_config.sh)"
echo "  2. Configure Dialplan (05_dialplan_config.sh)"
echo "  3. Start Asterisk: systemctl start asterisk"
echo ""
print_info "Useful commands:"
echo "  systemctl status asterisk"
echo "  asterisk -rvvv"
echo "  asterisk -rx 'pjsip show endpoints'"
echo "  asterisk -rx 'manager show connected'"
echo ""
