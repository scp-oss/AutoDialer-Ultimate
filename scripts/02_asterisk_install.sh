#!/bin/bash
# =============================================
# AutoDialer Ultimate - Asterisk Installation
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

# =============================================
# Configuration
# =============================================
ASTERISK_VERSION="${ASTERISK_VERSION:-21}"
ASTERISK_DOWNLOAD_URL="https://downloads.asterisk.org/pub/telephony/asterisk"
INSTALL_DIR="/usr/src"
ASTERISK_USER="asterisk"
ASTERISK_GROUP="asterisk"

# Number of CPU cores for parallel build
MAKE_JOBS="${MAKE_JOBS:-$(nproc)}"

# =============================================
# Download Asterisk
# =============================================
print_step "Downloading Asterisk ${ASTERISK_VERSION}..."

cd "$INSTALL_DIR"

# Clean up old downloads
rm -f asterisk-${ASTERISK_VERSION}-current.tar.gz
rm -rf asterisk-${ASTERISK_VERSION}.*

# Download latest version
wget -q --show-progress "${ASTERISK_DOWNLOAD_URL}/asterisk-${ASTERISK_VERSION}-current.tar.gz"

if [ ! -f "asterisk-${ASTERISK_VERSION}-current.tar.gz" ]; then
    print_error "Failed to download Asterisk"
    exit 1
fi

print_success "Downloaded Asterisk ${ASTERISK_VERSION}"

# =============================================
# Extract Asterisk
# =============================================
print_step "Extracting Asterisk..."

tar -xzf "asterisk-${ASTERISK_VERSION}-current.tar.gz"
cd asterisk-${ASTERISK_VERSION}.*

ASTERISK_SRC_DIR=$(pwd)
print_info "Source directory: $ASTERISK_SRC_DIR"

# =============================================
# Install Prerequisites
# =============================================
print_step "Installing Asterisk prerequisites..."

# Run the official prerequisite script
contrib/scripts/install_prereq install

# Download MP3 support
contrib/scripts/get_mp3_source.sh || true

print_success "Prerequisites installed"

# =============================================
# Configure Asterisk
# =============================================
print_step "Configuring Asterisk build..."

./configure \
    --with-pjproject-bundled \
    --with-jansson-bundled \
    --with-ssl \
    --with-crypto \
    --with-srtp \
    --with-gsm \
    --with-speex \
    --with-opus \
    --with-vorbis \
    --with-ogg \
    --with-ical \
    --with-iksemel \
    --with-ldap \
    --with-curl \
    --with-libxml2 \
    --with-systemd \
    --with-popt \
    --with-spandsp \
    --with-neon \
    --with-netsnmp \
    --with-unixodbc \
    --with-postgres \
    --prefix=/usr \
    --sysconfdir=/etc \
    --localstatedir=/var \
    --datarootdir=/usr/share \
    --docdir=/usr/share/doc/asterisk

if [ $? -ne 0 ]; then
    print_error "Configure failed"
    exit 1
fi

print_success "Configure completed"

# =============================================
# Configure Menuselect
# =============================================
print_step "Configuring menuselect..."

make menuselect.makeopts

# Enable required modules
menuselect/menuselect --enable app_dial menuselect.makeopts
menuselect/menuselect --enable app_playback menuselect.makeopts
menuselect/menuselect --enable app_userevent menuselect.makeopts
menuselect/menuselect --enable app_read menuselect.makeopts
menuselect/menuselect --enable app_verbose menuselect.makeopts
menuselect/menuselect --enable app_answer menuselect.makeopts
menuselect/menuselect --enable app_waituntil menuselect.makeopts
menuselect/menuselect --enable app_progress menuselect.makeopts
menuselect/menuselect --enable app_mixmonitor menuselect.makeopts
menuselect/menuselect --enable app_stack menuselect.makeopts
menuselect/menuselect --enable app_echo menuselect.makeopts
menuselect/menuselect --enable app_senddtmf menuselect.makeopts
menuselect/menuselect --enable app_confbridge menuselect.makeopts
menuselect/menuselect --enable app_amd menuselect.makeopts

# Channel drivers
menuselect/menuselect --enable chan_pjsip menuselect.makeopts
menuselect/menuselect --disable chan_sip menuselect.makeopts
menuselect/menuselect --disable chan_iax2 menuselect.makeopts
menuselect/menuselect --disable chan_dahdi menuselect.makeopts
menuselect/menuselect --disable chan_skinny menuselect.makeopts
menuselect/menuselect --disable chan_unistim menuselect.makeopts
menuselect/menuselect --disable chan_mgcp menuselect.makeopts
menuselect/menuselect --disable chan_alsa menuselect.makeopts
menuselect/menuselect --disable chan_console menuselect.makeopts

# PJSIP modules
menuselect/menuselect --enable res_pjsip menuselect.makeopts
menuselect/menuselect --enable res_pjsip_authenticator_digest menuselect.makeopts
menuselect/menuselect --enable res_pjsip_endpoint_identifier_ip menuselect.makeopts
menuselect/menuselect --enable res_pjsip_endpoint_identifier_user menuselect.makeopts
menuselect/menuselect --enable res_pjsip_outbound_registration menuselect.makeopts
menuselect/menuselect --enable res_pjsip_session menuselect.makeopts
menuselect/menuselect --enable res_pjsip_logger menuselect.makeopts
menuselect/menuselect --enable res_pjsip_notify menuselect.makeopts
menuselect/menuselect --enable res_pjsip_pubsub menuselect.makeopts
menuselect/menuselect --enable res_pjsip_transport_websocket menuselect.makeopts

# RTP modules
menuselect/menuselect --enable res_rtp_asterisk menuselect.makeopts

# CDR modules
menuselect/menuselect --enable cdr_csv menuselect.makeopts
menuselect/menuselect --enable cdr_custom menuselect.makeopts
menuselect/menuselect --enable cdr_pgsql menuselect.makeopts

# CEL modules
menuselect/menuselect --enable cel_custom menuselect.makeopts

# Functions
menuselect/menuselect --enable func_callerid menuselect.makeopts
menuselect/menuselect --enable func_cdr menuselect.makeopts
menuselect/menuselect --enable func_channel menuselect.makeopts
menuselect/menuselect --enable func_strings menuselect.makeopts
menuselect/menuselect --enable func_timeout menuselect.makeopts
menuselect/menuselect --enable func_hangupcause menuselect.makeopts
menuselect/menuselect --enable func_global menuselect.makeopts
menuselect/menuselect --enable func_logic menuselect.makeopts
menuselect/menuselect --enable func_math menuselect.makeopts
menuselect/menuselect --enable func_env menuselect.makeopts
menuselect/menuselect --enable func_lock menuselect.makeopts
menuselect/menuselect --enable func_realtime menuselect.makeopts
menuselect/menuselect --enable func_sha1 menuselect.makeopts
menuselect/menuselect --enable func_shell menuselect.makeopts
menuselect/menuselect --enable func_sprintf menuselect.makeopts
menuselect/menuselect --enable func_srv menuselect.makeopts
menuselect/menuselect --enable func_uri menuselect.makeopts
menuselect/menuselect --enable func_vmcount menuselect.makeopts
menuselect/menuselect --enable func_volume menuselect.makeopts

# Format interpreters
menuselect/menuselect --enable format_wav menuselect.makeopts
menuselect/menuselect --enable format_sln menuselect.makeopts
menuselect/menuselect --enable format_gsm menuselect.makeopts
menuselect/menuselect --enable format_pcm menuselect.makeopts
menuselect/menuselect --enable format_g729 menuselect.makeopts
menuselect/menuselect --enable format_g723 menuselect.makeopts
menuselect/menuselect --enable format_ogg_vorbis menuselect.makeopts
menuselect/menuselect --enable format_mp3 menuselect.makeopts

# Resources
menuselect/menuselect --enable res_monitor menuselect.makeopts
menuselect/menuselect --enable res_agi menuselect.makeopts
menuselect/menuselect --enable res_sorcery_config menuselect.makeopts
menuselect/menuselect --enable res_sorcery_memory menuselect.makeopts
menuselect/menuselect --enable res_sorcery_astdb menuselect.makeopts
menuselect/menuselect --enable res_timing_timerfd menuselect.makeopts
menuselect/menuselect --enable res_musiconhold menuselect.makeopts
menuselect/menuselect --enable res_security_log menuselect.makeopts
menuselect/menuselect --enable res_http_websocket menuselect.makeopts
menuselect/menuselect --enable res_crypto menuselect.makeopts
menuselect/menuselect --enable res_curl menuselect.makeopts
menuselect/menuselect --enable res_odbc menuselect.makeopts
menuselect/menuselect --enable res_config_odbc menuselect.makeopts
menuselect/menuselect --enable res_config_pgsql menuselect.makeopts

# Disable unnecessary modules
menuselect/menuselect --disable pbx_dundi menuselect.makeopts
menuselect/menuselect --disable pbx_ael menuselect.makeopts
menuselect/menuselect --disable pbx_lua menuselect.makeopts
menuselect/menuselect --disable res_phoneprov menuselect.makeopts
menuselect/menuselect --disable res_ael_share menuselect.makeopts
menuselect/menuselect --disable res_adsi menuselect.makeopts
menuselect/menuselect --disable res_ari menuselect.makeopts
menuselect/menuselect --disable res_ari_applications menuselect.makeopts
menuselect/menuselect --disable res_calendar menuselect.makeopts
menuselect/menuselect --disable res_config_sqlite menuselect.makeopts
menuselect/menuselect --disable res_corosync menuselect.makeopts
menuselect/menuselect --disable res_fax menuselect.makeopts
menuselect/menuselect --disable res_hep menuselect.makeopts
menuselect/menuselect --disable res_xmpp menuselect.makeopts
menuselect/menuselect --disable codec_dahdi menuselect.makeopts

print_success "Menuselect configured"

# =============================================
# Build Asterisk
# =============================================
print_step "Building Asterisk (using ${MAKE_JOBS} jobs)..."

make -j"${MAKE_JOBS}"

if [ $? -ne 0 ]; then
    print_error "Build failed"
    exit 1
fi

print_success "Build completed"

# =============================================
# Install Asterisk
# =============================================
print_step "Installing Asterisk..."

make install

if [ $? -ne 0 ]; then
    print_error "Installation failed"
    exit 1
fi

print_success "Asterisk installed"

# =============================================
# Install Sample Configurations
# =============================================
print_step "Installing sample configurations..."

make samples

print_success "Sample configurations installed"

# =============================================
# Install Init Scripts
# =============================================
print_step "Installing init scripts..."

make config

# Create systemd service override directory
mkdir -p /etc/systemd/system/asterisk.service.d

print_success "Init scripts installed"

# =============================================
# Install Documentation
# =============================================
print_step "Installing documentation..."

make install-logrotate || true

print_success "Documentation installed"

# =============================================
# Set Permissions
# =============================================
print_step "Setting permissions..."

# Create asterisk user if not exists
if ! id -u asterisk &>/dev/null; then
    useradd -r -m -d /var/lib/asterisk -s /sbin/nologin -c "Asterisk PBX" asterisk
fi

# Set ownership
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /etc/asterisk
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/lib/asterisk
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/log/asterisk
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/spool/asterisk
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/run/asterisk
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /usr/lib/asterisk

# Set permissions
chmod 755 /etc/asterisk
chmod 755 /var/lib/asterisk
chmod 755 /var/log/asterisk
chmod 755 /var/spool/asterisk
chmod 755 /var/run/asterisk

print_success "Permissions set"

# =============================================
# Create Required Directories
# =============================================
print_step "Creating additional directories..."

mkdir -p /var/lib/asterisk/sounds/tts/{models,campaigns}
mkdir -p /var/spool/asterisk/monitor
mkdir -p /var/log/asterisk/cdr-csv
mkdir -p /var/log/asterisk/cdr-custom

chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/lib/asterisk/sounds
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/spool/asterisk/monitor
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/log/asterisk/cdr-csv
chown -R ${ASTERISK_USER}:${ASTERISK_GROUP} /var/log/asterisk/cdr-custom

print_success "Additional directories created"

# =============================================
# Verify Installation
# =============================================
print_step "Verifying installation..."

if command -v asterisk &> /dev/null; then
    ASTERISK_VERSION_INSTALLED=$(asterisk -V | head -1)
    print_success "Asterisk installed: $ASTERISK_VERSION_INSTALLED"
else
    print_error "Asterisk command not found"
    exit 1
fi

# Check key modules
print_info "Checking key modules..."
asterisk -rx "module show" 2>/dev/null | grep -E "chan_pjsip|app_dial|res_rtp_asterisk" || true

# =============================================
# Summary
# =============================================
print_success "Asterisk installation completed!"
echo ""
print_info "Installation Details:"
echo "  Version: ${ASTERISK_VERSION}"
echo "  Install Directory: /usr/lib/asterisk"
echo "  Config Directory: /etc/asterisk"
echo "  Log Directory: /var/log/asterisk"
echo "  User: ${ASTERISK_USER}"
echo ""
print_info "Next steps:"
echo "  1. Configure Asterisk (03_asterisk_config.sh)"
echo "  2. Configure PJSIP (04_pjsip_config.sh)"
echo "  3. Configure Dialplan (05_dialplan_config.sh)"
echo ""
print_info "Useful commands:"
echo "  systemctl start asterisk"
echo "  systemctl status asterisk"
echo "  asterisk -rvvv"
echo "  asterisk -rx 'core show version'"
echo "  asterisk -rx 'module show'"
echo ""

# =============================================
# Optional: Install Asterisk Sounds
# =============================================
read -p "Download and install Asterisk core sounds? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_step "Installing Asterisk core sounds..."
    
    cd "$INSTALL_DIR/asterisk-${ASTERISK_VERSION}."*
    make menuselect.makeopts
    menuselect/menuselect --enable-category MENUSELECT_CORE_SOUNDS menuselect.makeopts
    menuselect/menuselect --enable-category MENUSELECT_MOH menuselect.makeopts
    menuselect/menuselect --enable CORE-SOUNDS-EN-WAV menuselect.makeopts
    menuselect/menuselect --enable CORE-SOUNDS-EN-ULAW menuselect.makeopts
    menuselect/menuselect --enable CORE-SOUNDS-RU-WAV menuselect.makeopts
    menuselect/menuselect --enable CORE-SOUNDS-RU-ULAW menuselect.makeopts
    menuselect/menuselect --enable MOH-OPSOUND-WAV menuselect.makeopts
    
    make install
    print_success "Core sounds installed"
fi
