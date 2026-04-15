#!/bin/bash
# =============================================
# AutoDialer Ultimate - Настройка файрвола (UFW + iptables)
# Версия: 3.0.0
# =============================================
# Безопасная настройка файрвола:
# - НЕ блокирует SSH (автоопределение порта)
# - Разрешает только необходимые порты
# - SIP/RTP только от FreePBX
# - Trusted Proxies для X-Forwarded-For
# - Защита от SYN flood, port scan, invalid packets
# - Rate limiting на HTTP/HTTPS
# =============================================

set -euo pipefail

# =============================================
# Цвета и логирование
# =============================================
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; NC=''
fi

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "\n${BOLD}${CYAN}▶ $*${NC}"; }

# =============================================
# Загрузка конфигурации
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

FREEPBX_IP="${FREEPBX_IP:-}"
DOMAIN_NAME="${DOMAIN_NAME:-}"
TRUSTED_PROXIES="${TRUSTED_PROXIES:-10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1,::1}"

log_info "FreePBX IP: ${FREEPBX_IP:-не задан}"
log_info "Trusted Proxies: $TRUSTED_PROXIES"

# =============================================
# Проверка прав root
# =============================================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Требуются права root"
        exit 1
    fi
}

# =============================================
# Проверка идемпотентности
# =============================================
MARKER_FILE="/opt/autodialer/.firewall_configured"

check_already_configured() {
    if [ -f "$MARKER_FILE" ]; then
        log_warn "Файрвол уже настроен (найден $MARKER_FILE)"
        log_info "Пропускаю настройку..."
        exit 0
    fi
}

# =============================================
# Определение порта SSH
# =============================================
get_ssh_port() {
    local ssh_port
    
    # Пробуем получить из конфига
    ssh_port=$(grep -E "^Port\s+" /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}' | head -1)
    
    # Если не найден, используем 22
    if [ -z "$ssh_port" ]; then
        ssh_port="22"
    fi
    
    # Проверяем, слушает ли кто-то этот порт
    if ! ss -tln | grep -q ":$ssh_port "; then
        # Если нет, пробуем найти реально слушаемый порт SSH
        ssh_port=$(ss -tln | grep -E ":22\s" | head -1 | awk '{print $4}' | cut -d':' -f2)
        if [ -z "$ssh_port" ]; then
            ssh_port="22"
            log_warn "Не удалось определить порт SSH, использую 22"
        fi
    fi
    
    echo "$ssh_port"
}

# =============================================
# Установка UFW
# =============================================
install_ufw() {
    log_step "Установка UFW..."
    
    if command -v ufw &>/dev/null; then
        log_info "UFW уже установлен"
        return 0
    fi
    
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ufw iptables-persistent netfilter-persistent
    
    log_success "UFW установлен"
}

# =============================================
# Сброс UFW к defaults
# =============================================
reset_ufw() {
    log_step "Сброс UFW к значениям по умолчанию..."
    
    ufw --force disable
    ufw --force reset
    
    ufw default deny incoming
    ufw default allow outgoing
    ufw default deny routed
    
    log_success "UFW сброшен"
}

# =============================================
# Настройка правил UFW
# =============================================
configure_ufw_rules() {
    log_step "Настройка правил UFW..."
    
    local ssh_port="$1"
    
    # SSH (САМОЕ ВАЖНОЕ - не блокировать!)
    ufw allow "$ssh_port/tcp" comment 'SSH'
    log_info "  ✓ SSH порт $ssh_port/tcp"
    
    # HTTP и HTTPS
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'
    log_info "  ✓ HTTP/HTTPS (80,443/tcp)"
    
    # Локальные соединения
    ufw allow from 127.0.0.1 comment 'Localhost IPv4'
    ufw allow from ::1 comment 'Localhost IPv6' 2>/dev/null || true
    log_info "  ✓ Localhost"
    
    # Внутренние сети (только если есть TRUSTED_PROXIES)
    IFS=',' read -ra PROXIES <<< "$TRUSTED_PROXIES"
    for proxy in "${PROXIES[@]}"; do
        proxy=$(echo "$proxy" | xargs)
        if [[ "$proxy" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]] || [[ "$proxy" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            ufw allow from "$proxy" comment "Trusted Proxy: $proxy"
            log_info "  ✓ Trusted Proxy: $proxy"
        fi
    done
    
    # SIP от FreePBX
    if [ -n "$FREEPBX_IP" ] && [ "$FREEPBX_IP" != "127.0.0.1" ]; then
        ufw allow from "$FREEPBX_IP" to any port 5060 proto udp comment 'SIP from FreePBX'
        ufw allow from "$FREEPBX_IP" to any port 5061 proto tcp comment 'SIP TLS from FreePBX' 2>/dev/null || true
        log_info "  ✓ SIP от $FREEPBX_IP"
    else
        log_warn "  ⚠ FREEPBX_IP не задан, SIP будет заблокирован!"
    fi
    
    # RTP от FreePBX
    if [ -n "$FREEPBX_IP" ] && [ "$FREEPBX_IP" != "127.0.0.1" ]; then
        ufw allow from "$FREEPBX_IP" to any port 10000:20000 proto udp comment 'RTP from FreePBX'
        log_info "  ✓ RTP от $FREEPBX_IP"
    else
        log_warn "  ⚠ FREEPBX_IP не задан, RTP будет заблокирован!"
    fi
    
    # PostgreSQL (только localhost)
    ufw allow from 127.0.0.1 to any port 5432 proto tcp comment 'PostgreSQL (local)'
    
    # Redis (только localhost)
    ufw allow from 127.0.0.1 to any port 6379 proto tcp comment 'Redis (local)'
    
    # Asterisk AMI (только localhost)
    ufw allow from 127.0.0.1 to any port 5038 proto tcp comment 'Asterisk AMI (local)'
    
    # Backend API (только localhost, проксируется через Nginx)
    ufw allow from 127.0.0.1 to any port 8000 proto tcp comment 'Backend API (local)'
    
    # ICMP (ping) - опционально, для диагностики
    ufw allow proto icmp comment 'ICMP (ping)'
    log_info "  ✓ ICMP (ping)"
    
    log_success "Правила UFW настроены"
}

# =============================================
# Дополнительные правила iptables (защита от атак)
# =============================================
configure_iptables_protection() {
    log_step "Настройка дополнительной защиты iptables..."
    
    # Защита от SYN flood
    iptables -A INPUT -p tcp --syn -m limit --limit 10/s --limit-burst 20 -j ACCEPT 2>/dev/null || true
    iptables -A INPUT -p tcp --syn -j DROP 2>/dev/null || true
    log_info "  ✓ SYN flood protection"
    
    # Защита от port scan
    iptables -A INPUT -p tcp --tcp-flags ALL NONE -j DROP 2>/dev/null || true
    iptables -A INPUT -p tcp --tcp-flags ALL ALL -j DROP 2>/dev/null || true
    iptables -A INPUT -p tcp ! --syn -m state --state NEW -j DROP 2>/dev/null || true
    log_info "  ✓ Port scan protection"
    
    # Блокировка невалидных пакетов
    iptables -A INPUT -m state --state INVALID -j DROP 2>/dev/null || true
    iptables -A FORWARD -m state --state INVALID -j DROP 2>/dev/null || true
    iptables -A OUTPUT -m state --state INVALID -j DROP 2>/dev/null || true
    log_info "  ✓ Invalid packet protection"
    
    # Блокировка фрагментированных пакетов
    iptables -A INPUT -f -j DROP 2>/dev/null || true
    log_info "  ✓ Fragment protection"
    
    # Защита от smurf атак
    iptables -A INPUT -p icmp -m icmp --icmp-type address-mask-request -j DROP 2>/dev/null || true
    iptables -A INPUT -p icmp -m icmp --icmp-type timestamp-request -j DROP 2>/dev/null || true
    log_info "  ✓ Smurf protection"
    
    # Ограничение подключений к SSH (brute force protection)
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m connlimit --connlimit-above 10 --connlimit-mask 32 -j DROP 2>/dev/null || true
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m recent --name ssh_attack --set 2>/dev/null || true
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m recent --name ssh_attack --rcheck --seconds 60 --hitcount 5 -j DROP 2>/dev/null || true
    log_info "  ✓ SSH brute force protection"
    
    # Ограничение подключений к HTTP/HTTPS
    iptables -A INPUT -p tcp --dport 80 -m connlimit --connlimit-above 100 --connlimit-mask 32 -j DROP 2>/dev/null || true
    iptables -A INPUT -p tcp --dport 443 -m connlimit --connlimit-above 100 --connlimit-mask 32 -j DROP 2>/dev/null || true
    log_info "  ✓ HTTP/HTTPS connection limit"
    
    # SIP flood protection (только если есть FREEPBX_IP)
    if [ -n "$FREEPBX_IP" ] && [ "$FREEPBX_IP" != "127.0.0.1" ]; then
        # Разрешаем только от FreePBX
        iptables -A INPUT -p udp --dport 5060 ! -s "$FREEPBX_IP" -j DROP 2>/dev/null || true
        iptables -A INPUT -p udp --dport 10000:20000 ! -s "$FREEPBX_IP" -j DROP 2>/dev/null || true
        log_info "  ✓ SIP/RTP restricted to $FREEPBX_IP"
    fi
    
    log_success "Дополнительная защита iptables настроена"
}

# =============================================
# Включение UFW
# =============================================
enable_ufw() {
    log_step "Включение UFW..."
    
    echo "y" | ufw enable
    
    if ufw status | grep -q "Status: active"; then
        log_success "UFW активирован"
    else
        log_error "Не удалось активировать UFW"
        return 1
    fi
}

# =============================================
# Проверка SSH доступа
# =============================================
verify_ssh_access() {
    log_step "Проверка SSH доступа..."
    
    local ssh_port="$1"
    
    # Проверяем, что правило SSH добавлено в UFW
    if ufw status | grep -q "$ssh_port/tcp.*ALLOW"; then
        log_success "Правило SSH в UFW присутствует"
    else
        log_error "Правило SSH ОТСУТСТВУЕТ в UFW! Экстренно добавляю..."
        ufw allow "$ssh_port/tcp" comment 'SSH (emergency)'
    fi
    
    # Проверяем iptables
    if iptables -L INPUT -n | grep -q "dpt:$ssh_port"; then
        log_success "Правило SSH в iptables присутствует"
    fi
}

# =============================================
# Сохранение правил iptables
# =============================================
save_iptables() {
    log_step "Сохранение правил iptables..."
    
    if command -v netfilter-persistent &>/dev/null; then
        netfilter-persistent save
        log_success "Правила сохранены через netfilter-persistent"
    elif command -v iptables-save &>/dev/null; then
        mkdir -p /etc/iptables
        iptables-save > /etc/iptables/rules.v4
        ip6tables-save > /etc/iptables/rules.v6 2>/dev/null || true
        log_success "Правила сохранены в /etc/iptables/"
    else
        log_warn "Не удалось сохранить правила (установите iptables-persistent)"
    fi
}

# =============================================
# Создание хелпер-скриптов
# =============================================
create_helper_scripts() {
    log_step "Создание хелпер-скриптов..."
    
    # Скрипт статуса
    cat > /usr/local/bin/autodialer-firewall-status << 'EOF'
#!/bin/bash
echo "=============================================="
echo "AutoDialer Firewall Status"
echo "=============================================="
echo ""
echo "=== UFW Status ==="
ufw status verbose
echo ""
echo "=== iptables INPUT Rules ==="
iptables -L INPUT -n -v --line-numbers 2>/dev/null | head -30
echo ""
echo "=== Active Connections ==="
ss -tunp 2>/dev/null | head -20
echo ""
echo "=== Recent SSH Attacks ==="
iptables -L INPUT -n 2>/dev/null | grep -i ssh || echo "No SSH rules"
EOF
    chmod +x /usr/local/bin/autodialer-firewall-status
    
    # Скрипт разрешения IP
    cat > /usr/local/bin/autodialer-firewall-allow << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Использование: $0 <IP> [комментарий]"
    exit 1
fi
IP="$1"
COMMENT="${2:-Manual allow}"
ufw allow from "$IP" comment "$COMMENT"
echo "Разрешён $IP ($COMMENT)"
ufw reload
EOF
    chmod +x /usr/local/bin/autodialer-firewall-allow
    
    # Скрипт блокировки IP
    cat > /usr/local/bin/autodialer-firewall-deny << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Использование: $0 <IP>"
    exit 1
fi
IP="$1"
ufw deny from "$IP"
echo "Заблокирован $IP"
ufw reload
EOF
    chmod +x /usr/local/bin/autodialer-firewall-deny
    
    # Скрипт временной блокировки IP (через iptables)
    cat > /usr/local/bin/autodialer-firewall-ban << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Использование: $0 <IP> [секунд]"
    exit 1
fi
IP="$1"
TIMEOUT="${2:-3600}"
iptables -A INPUT -s "$IP" -j DROP
echo "Заблокирован $IP на $TIMEOUT секунд (iptables)"
# Автоматическое удаление через timeout
(sleep "$TIMEOUT"; iptables -D INPUT -s "$IP" -j DROP 2>/dev/null; echo "Разблокирован $IP") &
EOF
    chmod +x /usr/local/bin/autodialer-firewall-ban
    
    log_success "Хелпер-скрипты созданы"
}

# =============================================
# Показ итогов
# =============================================
show_summary() {
    local ssh_port="$1"
    
    echo ""
    log_success "=============================================="
    log_success "Настройка файрвола завершена!"
    log_success "=============================================="
    echo ""
    log_info "Статус UFW: $(ufw status | head -1)"
    echo ""
    log_info "Открытые порты (UFW):"
    ufw status | grep -E "ALLOW" | head -20
    echo ""
    log_info "Дополнительная защита iptables:"
    echo "  ✓ SYN flood protection"
    echo "  ✓ Port scan protection"
    echo "  ✓ Invalid packet filtering"
    echo "  ✓ SSH brute force protection"
    echo "  ✓ HTTP/HTTPS connection limits"
    echo ""
    log_warn "ВАЖНО: SSH порт $ssh_port/tcp открыт. НЕ закрывайте его!"
    echo ""
    log_info "Хелпер-скрипты:"
    echo "  autodialer-firewall-status  - Статус файрвола"
    echo "  autodialer-firewall-allow    - Разрешить IP (UFW)"
    echo "  autodialer-firewall-deny     - Заблокировать IP (UFW)"
    echo "  autodialer-firewall-ban      - Временный бан IP (iptables)"
    echo ""
    log_info "Полезные команды:"
    echo "  ufw status verbose            - Подробный статус UFW"
    echo "  iptables -L INPUT -n -v       - Правила iptables"
    echo "  ufw disable                   - ОТКЛЮЧИТЬ UFW (только экстренно!)"
    echo ""
}

# =============================================
# Главная функция
# =============================================
main() {
    check_root
    check_already_configured
    
    log_step "Настройка файрвола и защиты..."
    
    SSH_PORT=$(get_ssh_port)
    log_info "Обнаружен порт SSH: $SSH_PORT"
    
    install_ufw
    reset_ufw
    configure_ufw_rules "$SSH_PORT"
    configure_iptables_protection
    enable_ufw
    verify_ssh_access "$SSH_PORT"
    save_iptables
    create_helper_scripts
    
    mkdir -p /opt/autodialer
    echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$MARKER_FILE"
    
    show_summary "$SSH_PORT"
}

main "$@"
