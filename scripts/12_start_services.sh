#!/bin/bash
# =============================================
# AutoDialer Ultimate - Start Services (FIXED)
# Version: 3.0.2 (ENTERPRISE)
# Description: Запуск всех сервисов с проверкой готовности
# =============================================
# 🔥 ИСПРАВЛЕНИЯ:
# - Убраны sleep, добавлены реальные проверки готовности
# - Правильный порядок запуска (БД → Redis → Asterisk → Backend → Nginx)
# - Проверка API перед запуском Nginx
# - Защита от падения бэкенда из-за неготовности БД
# - systemctl daemon-reload перед запуском
# - Проверка PJSIP регистрации
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
# Конфигурация
# =============================================
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-autodialer}"
DB_NAME="${DB_NAME:-autodialer}"

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

BACKEND_PORT="${PORT:-8000}"

MAX_WAIT_DB="${MAX_WAIT_DB:-60}"
MAX_WAIT_REDIS="${MAX_WAIT_REDIS:-30}"
MAX_WAIT_BACKEND="${MAX_WAIT_BACKEND:-120}"
MAX_WAIT_ASTERISK="${MAX_WAIT_ASTERISK:-30}"

# =============================================
# 🔥 ФУНКЦИИ ОЖИДАНИЯ ГОТОВНОСТИ
# =============================================

# Ожидание PostgreSQL (полная проверка)
wait_for_postgresql() {
    local max_attempts=$((MAX_WAIT_DB / 2))
    local attempt=0
    
    log_info "Ожидание PostgreSQL (${DB_HOST}:${DB_PORT})..."
    
    while [ $attempt -lt $max_attempts ]; do
        # 1. Проверка pg_isready
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" &>/dev/null; then
            # 2. Проверка подключения и запроса
            if PGPASSWORD="${DB_PASSWORD:-}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" &>/dev/null; then
                # 3. Проверка наличия таблиц (schema check)
                local table_count=$(PGPASSWORD="${DB_PASSWORD:-}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs)
                
                if [ "${table_count:-0}" -gt 0 ]; then
                    log_success "PostgreSQL готов (таблиц: $table_count)"
                    return 0
                else
                    log_info "PostgreSQL запущен, но schema не найдена (попытка $attempt)"
                fi
            fi
        fi
        
        # Показываем прогресс каждые 10 секунд
        if [ $((attempt % 5)) -eq 0 ] && [ $attempt -gt 0 ]; then
            log_info "  Всё ещё ожидаю PostgreSQL... (${attempt}s)"
        fi
        
        attempt=$((attempt + 1))
        sleep 2
    done
    
    log_error "PostgreSQL не ответил за ${MAX_WAIT_DB} секунд"
    log_error "Проверьте: systemctl status postgresql"
    return 1
}

# Ожидание Redis (с паролем и SET/GET)
redis_ping() {
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" ping 2>/dev/null
    else
        redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null
    fi
}

wait_for_redis() {
    local max_attempts=$MAX_WAIT_REDIS
    local attempt=0
    
    log_info "Ожидание Redis (${REDIS_HOST}:${REDIS_PORT})..."
    
    while [ $attempt -lt $max_attempts ]; do
        if redis_ping | grep -q "PONG"; then
            # Дополнительная проверка SET/GET
            local test_key="autodialer:health:$(date +%s)"
            
            if [ -n "${REDIS_PASSWORD:-}" ]; then
                redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" SET "$test_key" "ok" EX 10 >/dev/null 2>&1 && \
                redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" GET "$test_key" 2>/dev/null | grep -q "ok"
            else
                redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SET "$test_key" "ok" EX 10 >/dev/null 2>&1 && \
                redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" GET "$test_key" 2>/dev/null | grep -q "ok"
            fi
            
            if [ $? -eq 0 ]; then
                log_success "Redis готов"
                return 0
            fi
        fi
        
        if [ $((attempt % 5)) -eq 0 ] && [ $attempt -gt 0 ]; then
            log_info "  Всё ещё ожидаю Redis... (${attempt}s)"
        fi
        
        attempt=$((attempt + 1))
        sleep 1
    done
    
    log_error "Redis не ответил за ${MAX_WAIT_REDIS} секунд"
    log_error "Проверьте: systemctl status redis-server"
    return 1
}

# Ожидание Asterisk (проверка AMI)
wait_for_asterisk() {
    local max_attempts=$((MAX_WAIT_ASTERISK / 2))
    local attempt=0
    
    log_info "Ожидание Asterisk..."
    
    while [ $attempt -lt $max_attempts ]; do
        # Проверка что процесс запущен
        if asterisk -rx "core show version" &>/dev/null; then
            # Проверка AMI
            if asterisk -rx "manager show status" 2>/dev/null | grep -q "Enabled"; then
                log_success "Asterisk готов и AMI доступен"
                return 0
            fi
        fi
        
        if [ $((attempt % 5)) -eq 0 ] && [ $attempt -gt 0 ]; then
            log_info "  Всё ещё ожидаю Asterisk... (${attempt}s)"
        fi
        
        attempt=$((attempt + 1))
        sleep 2
    done
    
    log_warn "Asterisk не ответил за ${MAX_WAIT_ASTERISK} секунд"
    log_warn "Проверьте: systemctl status asterisk"
    return 1
}

# Ожидание бэкенда (проверка /api/health)
wait_for_backend() {
    local max_attempts=$((MAX_WAIT_BACKEND / 2))
    local attempt=0
    
    log_info "Ожидание бэкенда (http://127.0.0.1:${BACKEND_PORT})..."
    
    while [ $attempt -lt $max_attempts ]; do
        # Проверка health endpoint. /api/health всегда возвращает HTTP 200 и
        # JSON вида {"status": "healthy"|"degraded"|"unhealthy"|"starting", ...}
        # - подстроки "ok" в этих значениях нет, поэтому раньше проверка
        # `grep -q "ok"` никогда не срабатывала, даже когда бэкенд был
        # полностью здоров (подтверждено вручную через curl).
        local health_body
        health_body="$(curl -s --max-time 3 "http://127.0.0.1:${BACKEND_PORT}/api/health" 2>/dev/null)"
        if echo "$health_body" | grep -q '"status"[[:space:]]*:[[:space:]]*"\(healthy\|degraded\)"'; then
            log_success "Бэкенд готов и отвечает"
            return 0
        fi
        
        # Проверка что процесс не упал
        if ! systemctl is-active --quiet autodialer 2>/dev/null; then
            log_error "Сервис autodialer упал при запуске!"
            log_error "Проверьте логи: journalctl -u autodialer -n 50"
            
            echo ""
            echo "Последние 30 строк лога:"
            echo "------------------------"
            journalctl -u autodialer -n 30 --no-pager 2>/dev/null || true
            return 1
        fi
        
        # Показываем прогресс
        if [ $((attempt % 5)) -eq 0 ] && [ $attempt -gt 0 ]; then
            log_info "  Всё ещё ожидаю бэкенд... ($((attempt * 2))s)"
            
            # Каждые 30 секунд показываем статус
            if [ $((attempt % 15)) -eq 0 ]; then
                systemctl status autodialer --no-pager -l 2>/dev/null | head -10 || true
            fi
        fi
        
        attempt=$((attempt + 1))
        sleep 2
    done
    
    log_error "Бэкенд не ответил за ${MAX_WAIT_BACKEND} секунд"
    log_error "Проверьте логи: journalctl -u autodialer -n 50"
    
    echo ""
    echo "Последние 30 строк лога:"
    echo "------------------------"
    journalctl -u autodialer -n 30 --no-pager 2>/dev/null || true
    
    return 1
}

# Ожидание Nginx
wait_for_nginx() {
    local max_attempts=10
    local attempt=0
    
    log_info "Ожидание Nginx..."
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s --max-time 3 "http://127.0.0.1/" 2>/dev/null | grep -q "AutoDialer\|autodialer\|<!DOCTYPE"; then
            log_success "Nginx готов и отвечает"
            return 0
        fi
        
        attempt=$((attempt + 1))
        sleep 1
    done
    
    log_warn "Nginx не ответил, но продолжаем..."
    return 0
}

# =============================================
# 🔥 ОСТАНОВКА ВСЕХ СЕРВИСОВ (для чистого старта)
# =============================================
stop_all_services() {
    log_step "Остановка всех сервисов для чистого старта..."
    
    local services=("autodialer" "nginx" "asterisk" "redis-server" "postgresql")
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet "$service" 2>/dev/null; then
            log_info "Остановка $service..."
            systemctl stop "$service" || true
        fi
    done
    
    # Ожидание полной остановки
    sleep 3
    
    log_success "Все сервисы остановлены"
}

# =============================================
# 🔥 ЗАПУСК СЕРВИСОВ В ПРАВИЛЬНОМ ПОРЯДКЕ
# =============================================
start_services_ordered() {
    log_step "Запуск сервисов в правильном порядке..."
    
    # 🔥 ОБЯЗАТЕЛЬНЫЙ DAEMON-RELOAD
    log_info "Выполнение systemctl daemon-reload..."
    systemctl daemon-reload
    
    # 1. PostgreSQL (САМЫЙ ВАЖНЫЙ - ПЕРВЫМ)
    log_info "1. Запуск PostgreSQL..."
    systemctl start postgresql
    systemctl enable postgresql 2>/dev/null || true
    
    if ! wait_for_postgresql; then
        log_error "Не удалось запустить PostgreSQL"
        return 1
    fi
    
    # 2. Redis
    log_info "2. Запуск Redis..."
    systemctl start redis-server
    systemctl enable redis-server 2>/dev/null || true
    
    if ! wait_for_redis; then
        log_error "Не удалось запустить Redis"
        return 1
    fi
    
    # 3. Asterisk
    log_info "3. Запуск Asterisk..."
    systemctl start asterisk
    systemctl enable asterisk 2>/dev/null || true
    
    wait_for_asterisk || log_warn "Asterisk не готов, но продолжаем..."
    
    # 4. AutoDialer Backend (зависит от БД и Redis)
    log_info "4. Запуск AutoDialer Backend..."
    systemctl start autodialer
    systemctl enable autodialer 2>/dev/null || true
    
    # Даём бэкенду немного времени на инициализацию
    sleep 2
    
    if ! wait_for_backend; then
        log_error "Не удалось запустить бэкенд"
        
        # Пытаемся перезапустить ещё раз
        log_warn "Попытка перезапуска бэкенда..."
        systemctl restart autodialer
        sleep 5
        
        if ! wait_for_backend; then
            log_error "Бэкенд не запускается после перезапуска"
            return 1
        fi
    fi
    
    # 5. Nginx (после бэкенда)
    log_info "5. Запуск Nginx..."
    systemctl start nginx
    systemctl enable nginx 2>/dev/null || true
    
    wait_for_nginx
    
    # 6. Дополнительные сервисы
    log_info "6. Запуск дополнительных сервисов..."
    systemctl start fail2ban 2>/dev/null || true
    systemctl enable fail2ban 2>/dev/null || true
    
    log_success "Все сервисы запущены"
    return 0
}

# =============================================
# 🔥 ПРОВЕРКА СТАТУСА ВСЕХ СЕРВИСОВ
# =============================================
verify_all_services() {
    log_step "Проверка статуса всех сервисов..."
    
    echo ""
    printf "%-20s %-15s %s\n" "СЕРВИС" "СТАТУС" "ДЕТАЛИ"
    echo "─────────────────────────────────────────────────"
    
    local all_ok=true
    local services=(
        "postgresql:PostgreSQL"
        "redis-server:Redis"
        "asterisk:Asterisk"
        "autodialer:Backend"
        "nginx:Nginx"
        "fail2ban:Fail2ban"
    )
    
    for svc_info in "${services[@]}"; do
        local svc="${svc_info%%:*}"
        local name="${svc_info##*:}"
        
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            local status="● АКТИВЕН"
            local details=""
            
            case "$svc" in
                postgresql)
                    details="$(pg_isready -h "$DB_HOST" -p "$DB_PORT" 2>/dev/null && echo "ready" || echo "not ready")"
                    ;;
                redis-server)
                    details="$(redis_ping 2>/dev/null || echo "no response")"
                    ;;
                asterisk)
                    details="$(asterisk -rx "core show version" 2>/dev/null | head -1 | cut -d' ' -f1-2 || echo "no response")"
                    ;;
                autodialer)
                    details="$(curl -s http://127.0.0.1:${BACKEND_PORT}/api/health 2>/dev/null | grep -o '"status":"[^"]*"' | cut -d'"' -f4 || echo "no response")"
                    ;;
                nginx)
                    details="HTTP $(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ 2>/dev/null || echo "000")"
                    ;;
            esac
            
            printf "${GREEN}%-20s %-15s${NC} %s\n" "$name" "$status" "$details"
        else
            printf "${RED}%-20s %-15s${NC} %s\n" "$name" "○ ОСТАНОВЛЕН" "-"
            all_ok=false
        fi
    done
    
    echo "─────────────────────────────────────────────────"
    
    if [ "$all_ok" = true ]; then
        log_success "Все сервисы работают"
        return 0
    else
        log_warn "Некоторые сервисы не запущены"
        return 1
    fi
}

# =============================================
# 🔥 ПРОВЕРКА СЕТЕВЫХ ПОРТОВ
# =============================================
check_network_ports() {
    log_step "Проверка сетевых портов..."
    
    echo ""
    echo "Слушаемые порты:"
    echo "─────────────────────────────────────────────────"
    
    local ports=(
        "5432:PostgreSQL"
        "6379:Redis"
        "5060:SIP"
        "5038:AMI"
        "${BACKEND_PORT}:Backend"
        "80:HTTP"
        "443:HTTPS"
    )
    
    for port_info in "${ports[@]}"; do
        local port="${port_info%%:*}"
        local name="${port_info##*:}"
        
        if ss -tlnp 2>/dev/null | grep -q ":$port "; then
            printf "  ${GREEN}✅ %-6s${NC} %s\n" "$port" "$name"
        else
            printf "  ${YELLOW}⚠️ %-6s${NC} %s (не слушается)\n" "$port" "$name"
        fi
    done
    
    echo "─────────────────────────────────────────────────"
}

# =============================================
# 🔥 ПРОВЕРКА API ЭНДПОИНТОВ
# =============================================
check_api_endpoints() {
    log_step "Проверка API эндпоинтов..."
    
    echo ""
    local endpoints=(
        "/api/health:Health"
        "/docs:Swagger"
    )
    
    for ep_info in "${endpoints[@]}"; do
        local ep="${ep_info%%:*}"
        local name="${ep_info##*:}"
        
        local code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${BACKEND_PORT}${ep}" 2>/dev/null)
        
        case "$code" in
            200)
                printf "  ${GREEN}✅ %3s${NC} %s (%s)\n" "$code" "$ep" "$name"
                ;;
            401|403)
                printf "  ${BLUE}🔒 %3s${NC} %s (%s) - требуется авторизация\n" "$code" "$ep" "$name"
                ;;
            404)
                printf "  ${YELLOW}⚠️ %3s${NC} %s (%s) - не найдено\n" "$code" "$ep" "$name"
                ;;
            *)
                printf "  ${RED}❌ %3s${NC} %s (%s)\n" "$code" "$ep" "$name"
                ;;
        esac
    done
    
    echo ""
}

# =============================================
# 🔥 ПРОВЕРКА PJSIP РЕГИСТРАЦИИ
# =============================================
check_pjsip_registration() {
    log_step "Проверка PJSIP регистрации..."
    
    if ! systemctl is-active --quiet asterisk; then
        log_warn "Asterisk не запущен, пропускаю проверку PJSIP"
        return 0
    fi
    
    echo ""
    local reg_status=$(asterisk -rx "pjsip show registrations" 2>/dev/null)
    
    if echo "$reg_status" | grep -q "Registered"; then
        log_success "PJSIP зарегистрирован на FreePBX"
        echo "$reg_status" | grep "Registered" | head -3
    else
        log_warn "PJSIP НЕ зарегистрирован"
        log_info "Проверьте настройки FREEPBX_IP и EXTENSION_PASSWORD в .env"
        echo "$reg_status" | head -5
    fi
    echo ""
}

# =============================================
# СОЗДАНИЕ СКРИПТА СТАТУСА
# =============================================
create_status_script() {
    log_step "Создание скрипта статуса..."
    
    cat > /usr/local/bin/autodialer-all-status << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - All Services Status

echo "=============================================="
echo "AutoDialer Ultimate - Service Status"
echo "=============================================="
echo ""

SERVICES="postgresql redis-server asterisk autodialer nginx fail2ban"

for svc in $SERVICES; do
    if systemctl is-active --quiet $svc; then
        echo "✅ $svc: running"
    else
        echo "❌ $svc: stopped"
    fi
done

echo ""
echo "=============================================="
echo "Resource Usage"
echo "=============================================="

echo ""
echo "CPU:"
top -bn1 | head -5

echo ""
echo "Memory:"
free -h

echo ""
echo "Disk:"
df -h / /opt/autodialer

echo ""
echo "=============================================="
echo "Network Ports"
echo "=============================================="
ss -tlnp 2>/dev/null | grep -E ":(22|80|443|5060|5432|6379|5038|8000)" || echo "No ports found"

echo ""
echo "=============================================="
echo "PJSIP Registration"
echo "=============================================="
asterisk -rx "pjsip show registrations" 2>/dev/null | grep -E "Registered|No objects" || echo "No registrations"
EOF
    chmod +x /usr/local/bin/autodialer-all-status
    
    log_success "Скрипт статуса создан: /usr/local/bin/autodialer-all-status"
}

# =============================================
# СОЗДАНИЕ СКРИПТА ПЕРЕЗАПУСКА
# =============================================
create_restart_script() {
    log_step "Создание скрипта перезапуска..."
    
    cat > /usr/local/bin/autodialer-all-restart << 'EOF'
#!/bin/bash
# AutoDialer Ultimate - Restart All Services

echo "Перезапуск всех сервисов AutoDialer..."

SERVICES="postgresql redis-server asterisk autodialer nginx"

for svc in $SERVICES; do
    echo "Перезапуск $svc..."
    systemctl restart $svc
    sleep 2
done

echo "Все сервисы перезапущены!"
autodialer-all-status
EOF
    chmod +x /usr/local/bin/autodialer-all-restart
    
    log_success "Скрипт перезапуска создан: /usr/local/bin/autodialer-all-restart"
}

# =============================================
# ВЫВОД ИТОГОВОЙ СВОДКИ
# =============================================
print_summary() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN}${BOLD}✅ ВСЕ СЕРВИСЫ ЗАПУЩЕНЫ!${NC}"
    echo "============================================================"
    echo ""
    echo "Доступные URL:"
    echo "  • Веб-интерфейс:  http://$(hostname -I | awk '{print $1}')/"
    echo "  • API:            http://$(hostname -I | awk '{print $1}'):${BACKEND_PORT}/api"
    echo "  • Документация:   http://$(hostname -I | awk '{print $1}'):${BACKEND_PORT}/docs"
    echo "  • Health check:   http://$(hostname -I | awk '{print $1}'):${BACKEND_PORT}/api/health"
    echo ""
    echo "Управление сервисами:"
    echo "  • Статус всех:    autodialer-all-status"
    echo "  • Перезапуск:     autodialer-all-restart"
    echo "  • Логи бэкенда:   journalctl -u autodialer -f"
    echo "  • Логи Asterisk:  tail -f /var/log/asterisk/full"
    echo "  • Консоль Asterisk: asterisk -rvvv"
    echo ""
    echo "============================================================"
}

# =============================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================
main() {
    echo ""
    echo "=============================================="
    echo -e "${BOLD}${BLUE}AutoDialer Ultimate - Start Services${NC}"
    echo -e "${BOLD}${BLUE}Version: 3.0.2 (ENTERPRISE)${NC}"
    echo "=============================================="
    echo ""
    
    # Остановка для чистого старта
    stop_all_services
    
    # Запуск в правильном порядке
    if ! start_services_ordered; then
        log_error "Не удалось запустить все сервисы"
        verify_all_services
        exit 1
    fi
    
    # Проверки
    verify_all_services
    check_network_ports
    check_api_endpoints
    check_pjsip_registration
    
    # Создание скриптов
    create_status_script
    create_restart_script
    
    # Сводка
    print_summary
}

# =============================================
# ЗАПУСК
# =============================================
main "$@"
