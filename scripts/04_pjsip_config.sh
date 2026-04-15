#!/bin/bash
# =============================================
# AutoDialer Ultimate - Настройка PJSIP
# Версия: 3.0.0
# =============================================

set -e

# =============================================
# Цвета для вывода в консоль
# =============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "\n${GREEN}[ШАГ]${NC} $1"; }
print_info() { echo -e "${BLUE}[ИНФО]${NC} $1"; }
print_success() { echo -e "${CYAN}[УСПЕХ]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[ВНИМАНИЕ]${NC} $1"; }
print_error() { echo -e "${RED}[ОШИБКА]${NC} $1"; }

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Загрузка конфигурации
# =============================================
print_step "Загрузка конфигурации..."

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
    print_success "Конфигурация загружена из .env"
else
    print_error "Файл .env не найден!"
    exit 1
fi

# =============================================
# Установка значений по умолчанию
# =============================================
FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"

# =============================================
# Проверка обязательных параметров
# =============================================
if [ -z "$FREEPBX_IP" ]; then
    print_error "Параметр FREEPBX_IP не задан в .env"
    exit 1
fi

if [ -z "$EXTENSION_PASSWORD" ]; then
    print_error "Параметр EXTENSION_PASSWORD не задан в .env"
    exit 1
fi

print_info "Сервер FreePBX:    $FREEPBX_IP"
print_info "Номер Extension:   $FREEPBX_EXTENSION"

# =============================================
# Создание конфигурации PJSIP
# =============================================
print_step "Создание конфигурации PJSIP..."

cat > /etc/asterisk/pjsip.conf << EOF
; =============================================
; PJSIP Конфигурация для AutoDialer Ultimate
; Версия: 3.0.0
; Extension: ${FREEPBX_EXTENSION}
; Сервер FreePBX: ${FREEPBX_IP}
; =============================================

[global]
type = global
user_agent = AutoDialer-Ultimate/3.0.0
keep_alive_interval = 90
endpoint_identifier_order = ip,username,anonymous
default_realm = ${FREEPBX_IP}
max_initial_qualify = 5

; =============================================
; Транспорт UDP
; =============================================
[transport-udp]
type = transport
protocol = udp
bind = 0.0.0.0
local_net = 192.168.0.0/16,10.0.0.0/8,172.16.0.0/12
external_media_address = ${FREEPBX_IP}
external_signaling_address = ${FREEPBX_IP}

; =============================================
; Аутентификация для Extension ${FREEPBX_EXTENSION}
; =============================================
[${FREEPBX_EXTENSION}_auth]
type = auth
auth_type = userpass
username = ${FREEPBX_EXTENSION}
password = ${EXTENSION_PASSWORD}
realm = ${FREEPBX_IP}

; =============================================
; Address of Record (AOR)
; =============================================
[${FREEPBX_EXTENSION}_aor]
type = aor
max_contacts = 1
remove_existing = yes
contact = sip:${FREEPBX_EXTENSION}@${FREEPBX_IP}:5060
qualify_frequency = 30
qualify_timeout = 5.0
default_expiration = 120
maximum_expiration = 3600
minimum_expiration = 60

; =============================================
; Конечная точка (Endpoint)
; =============================================
[${FREEPBX_EXTENSION}_endpoint]
type = endpoint
transport = transport-udp
context = dialer_bridge

; Кодеки (приоритет: ulaw, alaw, g722)
disallow = all
allow = ulaw
allow = alaw
allow = g722

; DTMF через RFC4733 (наиболее надёжный способ)
dtmf_mode = rfc4733

; Аутентификация
outbound_auth = ${FREEPBX_EXTENSION}_auth
aors = ${FREEPBX_EXTENSION}_aor

; Caller ID
callerid = AutoDialer <${FREEPBX_EXTENSION}>
callerid_privacy = allowed_not_screened

; Медиа настройки
direct_media = no
media_encryption = no
media_use_received_transport = yes

; Настройки NAT (важно для работы за NAT)
rewrite_contact = yes
rtp_symmetric = yes
force_rport = yes

; Специфичные настройки для FreePBX
from_user = ${FREEPBX_EXTENSION}
from_domain = ${FREEPBX_IP}
outbound_proxy = sip:${FREEPBX_IP}:5060

; Таймеры сессий
timers = yes
timers_sess_expires = 1800
timers_min_se = 90

; Keepalive для RTP
rtp_keepalive = 30
rtp_timeout = 30
rtp_timeout_hold = 60

; Доверие входящим/исходящим
trust_id_inbound = yes
trust_id_outbound = yes

; Заголовки P-Asserted-Identity и Remote-Party-ID
send_pai = yes
send_rpid = yes

; Отключение ICE (не требуется)
ice_support = no

; Безопасность
allow_unauthenticated_options = no

; Запрет трансфера
allow_transfer = no

; Отключение определения факса
fax_detect = no

; Язык по умолчанию
language = ru

; Состояние устройства
device_state_busy_at = 1

; Ограничения потоков
max_audio_streams = 1
max_video_streams = 0

; Метод Connected Line
connected_line_method = invite

; Отключение T.38
t38_udptl = no

; =============================================
; Регистрация на FreePBX
; =============================================
[${FREEPBX_EXTENSION}_reg]
type = registration
outbound_auth = ${FREEPBX_EXTENSION}_auth
server_uri = sip:${FREEPBX_IP}:5060
client_uri = sip:${FREEPBX_EXTENSION}@${FREEPBX_IP}:5060
contact_user = ${FREEPBX_EXTENSION}
line = yes
endpoint = ${FREEPBX_EXTENSION}_endpoint

; Настройки повторных попыток
retry_interval = 60
max_retries = 10
forbidden_retry_interval = 300
fatal_retry_interval = 600

; Время жизни регистрации
expiration = 120

; Не считать отказ в аутентификации постоянным
auth_rejection_permanent = no

; Поддержка исходящей регистрации
support_outbound = yes

; Используемый транспорт
transport = transport-udp

; =============================================
; Идентификация входящих от FreePBX
; =============================================
[${FREEPBX_EXTENSION}_identify]
type = identify
endpoint = ${FREEPBX_EXTENSION}_endpoint
match = ${FREEPBX_IP}
match_header = From: <sip:${FREEPBX_EXTENSION}@${FREEPBX_IP}>

; =============================================
; Системные настройки
; =============================================
[system]
type = system
timer_t1 = 500
timer_b = 32000
compact_headers = yes
threadpool_initial_size = 0
threadpool_auto_increment = 5
threadpool_idle_timeout = 60
threadpool_max_size = 50
disable_multi_domain = no
EOF

print_success "Конфигурация PJSIP создана"

# =============================================
# Создание резервного endpoint (опционально)
# =============================================
if [ -n "$BACKUP_FREEPBX_IP" ]; then
    print_step "Создание резервного endpoint..."
    
    cat >> /etc/asterisk/pjsip.conf << EOF

; =============================================
; Резервный сервер FreePBX
; =============================================
[${FREEPBX_EXTENSION}_backup_aor]
type = aor
max_contacts = 1
contact = sip:${FREEPBX_EXTENSION}@${BACKUP_FREEPBX_IP}:5060

[${FREEPBX_EXTENSION}_backup_endpoint]
type = endpoint
transport = transport-udp
context = dialer_bridge
disallow = all
allow = ulaw
allow = alaw
outbound_auth = ${FREEPBX_EXTENSION}_auth
aors = ${FREEPBX_EXTENSION}_backup_aor
callerid = AutoDialer <${FREEPBX_EXTENSION}>
from_user = ${FREEPBX_EXTENSION}
from_domain = ${BACKUP_FREEPBX_IP}
outbound_proxy = sip:${BACKUP_FREEPBX_IP}:5060
EOF
    
    print_success "Резервный endpoint настроен для $BACKUP_FREEPBX_IP"
fi

# =============================================
# Установка прав доступа
# =============================================
print_step "Установка прав доступа..."

chown asterisk:asterisk /etc/asterisk/pjsip.conf
chmod 640 /etc/asterisk/pjsip.conf

print_success "Права доступа установлены"

# =============================================
# Отключение chan_sip (используем только PJSIP)
# =============================================
print_step "Отключение chan_sip..."

cat > /etc/asterisk/sip.conf << 'EOF'
[general]
enabled = no
EOF

print_success "chan_sip отключён"

# =============================================
# Перезагрузка конфигурации Asterisk
# =============================================
print_step "Перезагрузка конфигурации PJSIP..."

if systemctl is-active --quiet asterisk; then
    asterisk -rx "module reload res_pjsip.so"
    asterisk -rx "module reload chan_pjsip.so"
    asterisk -rx "pjsip reload"
    print_success "Конфигурация PJSIP перезагружена"
else
    print_warn "Asterisk не запущен, конфигурация будет применена при запуске"
fi

# =============================================
# Проверка конфигурации
# =============================================
print_step "Проверка конфигурации PJSIP..."

# Проверка наличия файла
if [ -f /etc/asterisk/pjsip.conf ]; then
    print_info "  ✓ pjsip.conf создан"
    
    # Подсчёт секций
    SECTIONS=$(grep -c "^\[" /etc/asterisk/pjsip.conf || true)
    print_info "  ✓ Найдено $SECTIONS секций конфигурации"
else
    print_error "pjsip.conf не найден!"
    exit 1
fi

# Проверка обязательных секций
REQUIRED_SECTIONS=(
    "global"
    "transport-udp"
    "${FREEPBX_EXTENSION}_auth"
    "${FREEPBX_EXTENSION}_aor"
    "${FREEPBX_EXTENSION}_endpoint"
    "${FREEPBX_EXTENSION}_reg"
    "${FREEPBX_EXTENSION}_identify"
)

print_info "Проверка обязательных секций:"
for section in "${REQUIRED_SECTIONS[@]}"; do
    if grep -q "^\[$section\]" /etc/asterisk/pjsip.conf; then
        print_info "  ✓ [$section]"
    else
        print_error "  ✗ [$section] отсутствует"
    fi
done

# =============================================
# Тестирование регистрации
# =============================================
if systemctl is-active --quiet asterisk; then
    print_step "Тестирование SIP регистрации..."
    
    sleep 3
    REGISTRATION_STATUS=$(asterisk -rx "pjsip show registrations" 2>/dev/null | grep "${FREEPBX_EXTENSION}_reg" || echo "")
    
    if echo "$REGISTRATION_STATUS" | grep -q "Registered"; then
        print_success "✓ Extension ${FREEPBX_EXTENSION} ЗАРЕГИСТРИРОВАН на FreePBX"
        echo "$REGISTRATION_STATUS"
    else
        print_warn "✗ Extension ${FREEPBX_EXTENSION} НЕ зарегистрирован"
        echo ""
        print_info "Возможные причины:"
        echo "  - Неверный IP-адрес FreePBX: $FREEPBX_IP"
        echo "  - Extension ${FREEPBX_EXTENSION} не существует на FreePBX"
        echo "  - Неверный пароль"
        echo "  - Проблемы с сетевой связностью"
        echo ""
        print_info "Проверьте:"
        echo "  1. ping $FREEPBX_IP"
        echo "  2. Настройки extension на FreePBX"
        echo "  3. Логи: tail -f /var/log/asterisk/full"
    fi
    
    # Показ конечных точек
    echo ""
    print_info "Список PJSIP endpoints:"
    asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -E "Endpoint|${FREEPBX_EXTENSION}" || true
else
    print_warn "Asterisk не запущен, пропускаю тест регистрации"
fi

# =============================================
# Сводка
# =============================================
print_step "Сводка настройки PJSIP"
echo ""
print_info "Параметры подключения:"
echo "  Сервер FreePBX:   $FREEPBX_IP"
echo "  Номер Extension:  $FREEPBX_EXTENSION"
echo "  Транспорт:        UDP"
echo "  Контекст:         dialer_bridge"
echo "  Кодеки:           ulaw, alaw, g722"
echo ""
print_info "Команды для проверки:"
echo "  asterisk -rx 'pjsip show registrations'"
echo "  asterisk -rx 'pjsip show endpoints'"
echo "  asterisk -rx 'pjsip show endpoint ${FREEPBX_EXTENSION}_endpoint'"
echo "  asterisk -rx 'pjsip show aor ${FREEPBX_EXTENSION}_aor'"
echo ""
print_info "Устранение неполадок:"
echo "  Если регистрация не проходит:"
echo "  1. Проверьте IP и пароль в .env"
echo "  2. Убедитесь, что extension ${FREEPBX_EXTENSION} создан на FreePBX"
echo "  3. Проверьте сеть: ping $FREEPBX_IP"
echo "  4. Смотрите логи: tail -f /var/log/asterisk/full"
echo ""

print_success "Настройка PJSIP завершена!"
