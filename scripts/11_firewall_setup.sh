#!/bin/bash
# =============================================
# AutoDialer Ultimate - Firewall Setup (FIXED)
# Version: 3.0.2 (ENTERPRISE)
# Description: Безопасная настройка файрвола (ТОЛЬКО UFW)
# =============================================
# 🔥 ИСПРАВЛЕНИЯ:
# - Только UFW (никаких iptables-persistent, nftables)
# - SSH НИКОГДА не блокируется (автоопределение порта)
# - Проверка правил ДО и ПОСЛЕ включения
# - UFW default policies перед enable
# - SIP/RTP только от FreePBX (и SIP_ALLOWED_IPS)
# - Дополнительная защита в before.rules
# =============================================

set -euo pipefail

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# =============================================
# Цвета для вывода
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

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${BOLD}${CYAN}▶ $1${NC}"; }

# =============================================
# Проверка прав root
# =============================================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Требуются права root. Используйте: sudo $0"
        exit 1
    fi
}

# =============================================
# Проверка идемпотентности
# =============================================
MARKER_FILE="/opt/autodialer/.firewall_configured"

check_already_configured() {
    if [ -f "$MARKER_FILE" ] && [ "${FORCE_REINSTALL:-false}" != "true" ]; then
        log_warn "Файрвол уже настроен (найден $MARKER_FILE)"
        
        if [ "${NON_INTERACTIVE:-true}" != "true" ]; then
            read -p "Перенастроить файрвол? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "Пропускаю настройку..."
                exit 0
            fi
        else
            log_info "Пропускаю настройку..."
            exit 0
        fi
    fi
}

# =============================================
# 🔥 ОПРЕДЕЛЕНИЕ ПОРТА SSH
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
    if ! ss -tln 2>/dev/null | grep -q ":$ssh_port "; then
        # Пробуем найти реально слушаемый порт SSH
        local detected_port=$(ss -tln 2>/dev/null | grep -E ":(22|2222|22222)" | head -1 | awk '{print $4}' | cut -d':' -f2)
        if [ -n "$detected_port" ]; then
            ssh_port="$detected_port"
        fi
    fi
    
    echo "$ssh_port"
}

# =============================================
# 🔥 ОЧИСТКА КОНФЛИКТУЮЩИХ СИСТЕМ
# =============================================
cleanup_conflicting_firewalls() {
    log_step "Очистка конфликтующих файрволов..."
    
    # Отключаем nftables если активен
    if systemctl is-active --quiet nftables 2>/dev/null; then
        log_info "Отключение nftables..."
        systemctl stop nftables
        systemctl disable nftables
    fi
    
    # 🔥 Удаляем конфликтующие пакеты (главная причина проблем)
    log_info "Удаление iptables-persistent и netfilter-persistent..."
    apt-get purge -y netfilter-persistent iptables-persistent 2>/dev/null || true
    
    # Очищаем старые правила iptables (НО НЕ ТРОГАЕМ UFW)
    if command -v iptables &>/dev/null; then
        log_info "Очистка старых правил iptables..."
        iptables -F INPUT 2>/dev/null || true
        iptables -F FORWARD 2>/dev/null || true
        iptables -F OUTPUT 2>/dev/null || true
        iptables -X 2>/dev/null || true
        iptables -t nat -F 2>/dev/null || true
        iptables -t mangle -F 2>/dev/null || true
    fi
    
    log_success "Конфликтующие системы отключены"
}

# =============================================
# 🔥 УСТАНОВКА И СБРОС UFW
# =============================================
install_and_reset_ufw() {
    log_step "Установка и сброс UFW..."
    
    export DEBIAN_FRONTEND=noninteractive
    
    # Установка UFW если не установлен
    if ! command -v ufw &>/dev/null; then
        apt-get update -qq
        apt-get install -y -qq ufw
        log_success "UFW установлен"
    else
        log_info "UFW уже установлен"
    fi
    
    # Сброс к значениям по умолчанию
    log_info "Сброс UFW к значениям по умолчанию..."
    ufw --force disable
    ufw --force reset
    
    # 🔥 ЯВНО УСТАНАВЛИВАЕМ ПОЛИТИКИ ПО УМОЛЧАНИЮ
    ufw --force default deny incoming
    ufw --force default allow outgoing
    ufw --force default deny routed
    
    log_success "UFW сброшен и политики установлены"
}

# =============================================
# 🔥 БЕЗОПАСНОЕ ДОБАВЛЕНИЕ ПРАВИЛ
# =============================================
add_ufw_rules() {
    local ssh_port="$1"
    
    log_step "Добавление правил UFW..."
    
    # =============================================
    # 🔥 САМОЕ ВАЖНОЕ: SSH (ВСЕГДА ПЕРВЫМ)
    # =============================================
    ufw allow "$ssh_port/tcp" comment 'SSH'
    log_success "  ✅ SSH порт $ssh_port/tcp РАЗРЕШЁН"
    
    # Дополнительно разрешаем SSH на стандартном порту (на случай если порт не 22)
    if [ "$ssh_port" != "22" ]; then
        ufw allow 22/tcp comment 'SSH (fallback)' 2>/dev/null || true
        log_info "  ✅ SSH fallback порт 22/tcp РАЗРЕШЁН"
    fi
    
    # =============================================
    # HTTP и HTTPS
    # =============================================
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'
    log_success "  ✅ HTTP/HTTPS (80,443/tcp)"
    
    # =============================================
    # Локальные соединения
    # =============================================
    ufw allow from 127.0.0.1 comment 'Localhost IPv4'
    ufw allow from ::1 comment 'Localhost IPv6' 2>/dev/null || true
    log_success "  ✅ Localhost"
    
    # =============================================
    # Trusted Proxies (если заданы)
    # =============================================
    if [ -n "${TRUSTED_PROXIES:-}" ]; then
        IFS=',' read -ra PROXIES <<< "$TRUSTED_PROXIES"
        for proxy in "${PROXIES[@]}"; do
            proxy=$(echo "$proxy" | xargs)
            if [[ "$proxy" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$ ]] || [[ "$proxy" =~ ^[0-9a-fA-F:]+$ ]]; then
                ufw allow from "$proxy" comment "Trusted Proxy: $proxy"
                log_info "  ✅ Trusted Proxy: $proxy"
            fi
        done
    fi
    
    # =============================================
    # 🔥 SIP и RTP от FreePBX
    # =============================================
    if [ -n "${FREEPBX_IP:-}" ] && [ "$FREEPBX_IP" != "127.0.0.1" ]; then
        ufw allow from "$FREEPBX_IP" to any port 5060 proto udp comment 'SIP from FreePBX'
        ufw allow from "$FREEPBX_IP" to any port 5061 proto tcp comment 'SIP TLS from FreePBX' 2>/dev/null || true
        ufw allow from "$FREEPBX_IP" to any port 10000:20000 proto udp comment 'RTP from FreePBX'
        log_success "  ✅ SIP/RTP от $FREEPBX_IP"
    else
        log_warn "  ⚠ FREEPBX_IP не задан, SIP/RTP будут заблокированы!"
    fi
    
    # =============================================
    # Дополнительные разрешённые SIP IP (если заданы)
    # =============================================
    if [ -n "${SIP_ALLOWED_IPS:-}" ]; then
        IFS=',' read -ra SIP_IPS <<< "$SIP_ALLOWED_IPS"
        for sip_ip in "${SIP_IPS[@]}"; do
            sip_ip=$(echo "$sip_ip" | xargs)
            if [ -n "$sip_ip" ] && [ "$sip_ip" != "$FREEPBX_IP" ]; then
                ufw allow from "$sip_ip" to any port 5060 proto udp comment "SIP from $sip_ip"
                ufw allow from "$sip_ip" to any port 10000:20000 proto udp comment "RTP from $sip_ip"
                log_info "  ✅ SIP/RTP от $sip_ip"
            fi
        done
    fi
    
    # =============================================
    # PostgreSQL (только localhost)
    # =============================================
    ufw allow from 127.0.0.1 to any port 5432 proto tcp comment 'PostgreSQL (local)'
    
    # =============================================
    # Redis (только localhost)
    # =============================================
    ufw allow from 127.0.0.1 to any port 6379 proto tcp comment 'Redis (local)'
    
    # =============================================
    # Asterisk AMI (только localhost)
    # =============================================
    ufw allow from 127.0.0.1 to any port 5038 proto tcp comment 'Asterisk AMI (local)'
    
    # =============================================
    # Backend API (только localhost, проксируется через Nginx)
    # =============================================
    ufw allow from 127.0.0.1 to any port "${PORT:-8000}" proto tcp comment 'Backend API (local)'
    
    # =============================================
    # Метрики (опционально, только для мониторинга)
    # =============================================
    if [ -n "${METRICS_PORT:-}" ] && [ "${METRICS_ENABLED:-true}" = "true" ]; then
        ufw allow from 127.0.0.1 to any port "${METRICS_PORT}" proto tcp comment 'Metrics (local)'
        
        # Разрешаем из доверенных сетей
        if [ -n "${TRUSTED_PROXIES:-}" ]; then
            IFS=',' read -ra PROXIES <<< "$TRUSTED_PROXIES"
            for proxy in "${PROXIES[@]}"; do
                proxy=$(echo "$proxy" | xargs)
                if [ -n "$proxy" ]; then
                    ufw allow from "$proxy" to any port "${METRICS_PORT}" proto tcp comment "Metrics from $proxy" 2>/dev/null || true
                fi
            done
        fi
    fi
    
    # =============================================
    # ICMP (ping) - для диагностики
    # =============================================
    ufw allow proto icmp from any to any comment 'ICMP (ping)'
    
    log_success "Все правила добавлены"
}

# =============================================
# 🔥 ПРОВЕРКА ПРАВИЛ ПЕРЕД ВКЛЮЧЕНИЕМ
# =============================================
verify_ssh_rule() {
    local ssh_port="$1"
    
    log_step "Проверка правила SSH..."
    
    if ufw status | grep -q "$ssh_port/tcp.*ALLOW"; then
        log_success "✅ Правило SSH присутствует: $ssh_port/tcp ALLOW"
        return 0
    else
        log_error "❌ Правило SSH ОТСУТСТВУЕТ!"
        log_error "ЭКСТРЕННО ДОБАВЛЯЮ SSH..."
        ufw allow "$ssh_port/tcp" comment 'SSH (emergency)'
        ufw allow 22/tcp comment 'SSH fallback (emergency)'
        return 1
    fi
}

# =============================================
# 🔥 ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА В BEFORE.RULES
# =============================================
add_extra_protection() {
    log_step "Добавление дополнительной защиты в before.rules..."
    
    # Создаём резервную копию
    if [ -f /etc/ufw/before.rules ] && [ ! -f /etc/ufw/before.rules.backup ]; then
        cp /etc/ufw/before.rules /etc/ufw/before.rules.backup
    fi
    
    # Добавляем защиту в before.rules (перед COMMIT)
    local before_rules="/etc/ufw/before.rules"
    local temp_file=$(mktemp)
    
    # Копируем всё до *filter
    awk '!found && /^\*filter/ {found=1} !found {print}' "$before_rules" > "$temp_file"
    
    # Добавляем *filter и наши правила
    cat >> "$temp_file" << 'EOF'
*filter

# =============================================
# AutoDialer Ultimate - Extra Protection
# =============================================

# Защита от SYN flood
-A ufw-before-input -p tcp --syn -m limit --limit 10/s --limit-burst 20 -j ACCEPT
-A ufw-before-input -p tcp --syn -j DROP

# Защита от port scan
-A ufw-before-input -p tcp --tcp-flags ALL NONE -j DROP
-A ufw-before-input -p tcp --tcp-flags ALL ALL -j DROP
-A ufw-before-input -p tcp ! --syn -m state --state NEW -j DROP

# Блокировка невалидных пакетов
-A ufw-before-input -m state --state INVALID -j DROP

# Блокировка фрагментированных пакетов
-A ufw-before-input -f -j DROP

# Защита от smurf атак
-A ufw-before-input -p icmp -m icmp --icmp-type address-mask-request -j DROP
-A ufw-before-input -p icmp -m icmp --icmp-type timestamp-request -j DROP

# Ограничение подключений к SSH (брутфорс защита)
-A ufw-before-input -p tcp --dport 22 -m connlimit --connlimit-above 10 --connlimit-mask 32 -j DROP
-A ufw-before-input -p tcp --dport 22 -m recent --name ssh_attack --set
-A ufw-before-input -p tcp --dport 22 -m recent --name ssh_attack --rcheck --seconds 60 --hitcount 5 -j DROP

# Ограничение подключений к HTTP/HTTPS
-A ufw-before-input -p tcp --dport 80 -m connlimit --connlimit-above 100 --connlimit-mask 32 -j DROP
-A ufw-before-input -p tcp --dport 443 -m connlimit --connlimit-above 100 --connlimit-mask 32 -j DROP

EOF
    
    # Копируем остальное после *filter (пропуская уже добавленное)
    awk 'found {print}' "$before_rules" >> "$temp_file"
    
    # Заменяем оригинал
    mv "$temp_file" "$before_rules"
    chmod 640 "$before_rules"
    
    log_success "Дополнительная защита добавлена"
}

# =============================================
# 🔥 ВКЛЮЧЕНИЕ UFW (С БЕЗОПАСНОЙ ПРОВЕРКОЙ)
# =============================================
enable_ufw_safe() {
    local ssh_port="$1"
    
    log_step "Включение UFW..."
    
    # Финальная проверка перед включением
    verify_ssh_rule "$ssh_port"
    
    # Показываем правила перед включением
    log_info "Текущие правила UFW:"
    ufw status verbose | head -30
    
    echo ""
    log_warn "ВНИМАНИЕ: Сейчас будет включён UFW!"
    log_info "SSH порт $ssh_port/tcp РАЗРЕШЁН."
    
    if [ "${NON_INTERACTIVE:-true}" != "true" ]; then
        read -p "Продолжить включение UFW? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_warn "UFW НЕ включён. Вы можете включить его позже: ufw enable"
            exit 0
        fi
    fi
    
    # Включение UFW
    echo "y" | ufw enable
    
    # Проверка статуса
    sleep 2
    if ufw status | grep -q "Status: active"; then
        log_success "UFW активирован"
    else
        log_error "Не удалось активировать UFW"
        return 1
    fi
    
    # 🔥 ПОВТОРНАЯ ПРОВЕРКА SSH ПОСЛЕ ВКЛЮЧЕНИЯ
    if ! ufw status | grep -q "$ssh_port/tcp.*ALLOW"; then
        log_error "КРИТИЧЕСКАЯ ОШИБКА: SSH правило пропало после включения!"
        log_error "ЭКСТРЕННО ДОБАВЛЯЮ SSH..."
        ufw allow "$ssh_port/tcp" comment 'SSH (post-enable emergency)'
        ufw allow 22/tcp comment 'SSH fallback (post-enable emergency)'
        ufw reload
    fi
    
    log_success "UFW включён и работает"
}

# =============================================
# 🔥 ПРОВЕРКА SSH ДОСТУПА ПОСЛЕ ВКЛЮЧЕНИЯ
# =============================================
verify_ssh_access() {
    local ssh_port="$1"
    
    log_step "Проверка SSH доступа..."
    
    # Проверяем что порт всё ещё слушается
    if ss -tln 2>/dev/null | grep -q ":$ssh_port "; then
        log_success "SSH порт $ssh_port слушается"
    else
        log_warn "SSH порт $ssh_port не слушается! Проверьте sshd"
    fi
    
    # Проверяем правило в UFW
    if ufw status | grep -q "$ssh_port/tcp.*ALLOW"; then
        log_success "Правило SSH в UFW активно"
    else
        log_error "Правило SSH в UFW ОТСУТСТВУЕТ!"
        log_error "ЭКСТРЕННО ДОБАВЛЯЮ..."
        ufw allow "$ssh_port/tcp" comment 'SSH (verification emergency)'
        ufw reload
    fi
    
    log_success "Проверка SSH завершена"
}

# =============================================
# СОЗДАНИЕ ХЕЛПЕР-СКРИПТОВ
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
echo "=== SSH Rules ==="
ufw status | grep -i ssh
echo ""
echo "=== SIP Rules ==="
ufw status | grep -i sip
echo ""
echo "=== Listening Ports ==="
ss -tlnp 2>/dev/null | grep -E ":(22|80|443|5060|5432|6379|5038|8000)" | head -20
echo ""
echo "=== Active Connections ==="
ss -tunp 2>/dev/null | head -15
EOF
    chmod +x /usr/local/bin/autodialer-firewall-status
    
    # Скрипт разрешения IP
    cat > /usr/local/bin/autodialer-firewall-allow << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Использование: $0 <IP> [комментарий]"
    echo "Пример: $0 192.168.1.100 'Офисный IP'"
    exit 1
fi
IP="$1"
COMMENT="${2:-Manual allow}"
ufw allow from "$IP" comment "$COMMENT"
ufw reload
echo "✅ Разрешён $IP ($COMMENT)"
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
ufw reload
echo "🚫 Заблокирован $IP"
EOF
    chmod +x /usr/local/bin/autodialer-firewall-deny
    
    # Скрипт временной блокировки
    cat > /usr/local/bin/autodialer-firewall-ban << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Использование: $0 <IP> [секунд]"
    echo "Пример: $0 192.168.1.100 3600"
    exit 1
fi
IP="$1"
TIMEOUT="${2:-3600}"
ufw deny from "$IP" comment "Temporary ban $(date +%H:%M)"
echo "🚫 Заблокирован $IP на $TIMEOUT секунд"
(sleep "$TIMEOUT"; ufw delete deny from "$IP" 2>/dev/null; echo "✅ Разблокирован $IP") &
EOF
    chmod +x /usr/local/bin/autodialer-firewall-ban
    
    log_success "Хелпер-скрипты созданы"
}

# =============================================
# СОХРАНЕНИЕ ПРАВИЛ
# =============================================
save_rules() {
    log_step "Сохранение правил..."
    
    # UFW автоматически сохраняет свои правила
    ufw status verbose > /etc/ufw/status.txt
    
    log_success "Правила сохранены"
}

# =============================================
# ВЫВОД СВОДКИ
# =============================================
print_summary() {
    local ssh_port="$1"
    
    echo ""
    echo "=============================================="
    echo -e "${GREEN}${BOLD}✅ Настройка файрвола завершена!${NC}"
    echo "=============================================="
    echo ""
    echo "Статус UFW: $(ufw status | head -1)"
    echo ""
    echo "Открытые порты:"
    ufw status | grep -E "ALLOW" | head -20
    echo ""
    echo -e "${YELLOW}${BOLD}⚠️  ВАЖНО: SSH порт $ssh_port/tcp открыт!${NC}"
    echo ""
    echo "Дополнительная защита:"
    echo "  • SYN flood protection"
    echo "  • Port scan protection"
    echo "  • SSH brute force protection"
    echo "  • HTTP/HTTPS connection limits"
    echo ""
    echo "Хелпер-скрипты:"
    echo "  autodialer-firewall-status   - Статус файрвола"
    echo "  autodialer-firewall-allow    - Разрешить IP"
    echo "  autodialer-firewall-deny     - Заблокировать IP навсегда"
    echo "  autodialer-firewall-ban      - Временный бан IP"
    echo ""
    echo "Полезные команды:"
    echo "  ufw status verbose            - Подробный статус"
    echo "  ufw reload                    - Перезагрузить правила"
    echo "  ufw disable                   - ОТКЛЮЧИТЬ UFW (экстренно!)"
    echo ""
    echo "=============================================="
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Firewall Setup${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.2 (ENTERPRISE)${NC}"
    echo "=============================================="
    echo ""
    
    check_root
    check_already_configured
    
    # Определение порта SSH
    SSH_PORT=$(get_ssh_port)
    log_info "Обнаружен порт SSH: $SSH_PORT"
    
    # Очистка и установка
    cleanup_conflicting_firewalls
    install_and_reset_ufw
    
    # Добавление правил
    add_ufw_rules "$SSH_PORT"
    
    # Дополнительная защита
    add_extra_protection
    
    # Включение UFW
    enable_ufw_safe "$SSH_PORT"
    
    # Проверка доступа
    verify_ssh_access "$SSH_PORT"
    
    # Сохранение и скрипты
    save_rules
    create_helper_scripts
    
    # Маркер установки
    mkdir -p /opt/autodialer
    echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$MARKER_FILE"
    echo "SSH_PORT=$SSH_PORT" >> "$MARKER_FILE"
    
    # Сводка
    print_summary "$SSH_PORT"
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
