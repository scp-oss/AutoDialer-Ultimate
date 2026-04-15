#!/bin/bash
# =============================================
# AutoDialer Ultimate - Главный установщик
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
BOLD='\033[1m'
NC='\033[0m' # No Color

# =============================================
# Функции для форматированного вывода
# =============================================
print_step() { echo -e "\n${GREEN}[ШАГ]${NC} $1"; }
print_info() { echo -e "${BLUE}[ИНФО]${NC} $1"; }
print_success() { echo -e "${CYAN}[УСПЕХ]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[ВНИМАНИЕ]${NC} $1"; }
print_error() { echo -e "${RED}[ОШИБКА]${NC} $1"; }
print_header() { 
    echo -e "\n${BOLD}${BLUE}========================================${NC}"
    echo -e "${BOLD}${BLUE}$1${NC}"
    echo -e "${BOLD}${BLUE}========================================${NC}"
}

# =============================================
# Определение директории скрипта
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR
cd "$SCRIPT_DIR"

# =============================================
# Проверка прав root
# =============================================
if [ "$EUID" -ne 0 ]; then 
    print_error "Запустите установку с правами root: sudo ./install.sh"
    exit 1
fi

# =============================================
# Приветственный экран
# =============================================
clear
print_header "Установщик AutoDialer Ultimate v3.0.0"
echo ""
print_info "Этот скрипт установит и настроит AutoDialer Ultimate."
print_info "Рекомендуемая ОС: Debian 12 (Bookworm)"
print_info "Требования: 4 ГБ RAM, 2 vCPU, 20 ГБ диска"
echo ""
print_warn "ВАЖНО:"
echo "  - Сервер FreePBX (Server-1) должен быть доступен по сети"
echo "  - На FreePBX должен быть создан SIP extension"
echo "  - Порты 80, 443, 5060, 10000-20000 должны быть открыты"
echo ""

read -p "Продолжить установку? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Установка отменена"
    exit 1
fi

# =============================================
# Проверка наличия файла .env
# =============================================
print_step "Проверка конфигурации..."

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    print_warn "Файл .env не найден!"
    print_info "Создаю .env из .env.example..."
    
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        print_success "Файл .env создан"
    else
        print_error "Файл .env.example не найден!"
        exit 1
    fi
    
    echo ""
    print_info "Необходимо отредактировать файл .env:"
    print_info "  nano $SCRIPT_DIR/.env"
    echo ""
    print_info "Обязательные параметры:"
    echo "  - FREEPBX_IP          : IP-адрес вашего сервера FreePBX"
    echo "  - FREEPBX_EXTENSION   : Номер SIP extension (по умолчанию: 291)"
    echo "  - EXTENSION_PASSWORD  : Пароль для SIP extension"
    echo ""
    
    read -p "Открыть .env для редактирования сейчас? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ${EDITOR:-nano} "$SCRIPT_DIR/.env"
    else
        print_error "Установка отменена. Сначала настройте .env"
        exit 1
    fi
fi

# =============================================
# Загрузка конфигурации из .env
# =============================================
print_step "Загрузка конфигурации..."
source "$SCRIPT_DIR/.env"

# =============================================
# Установка значений по умолчанию
# =============================================
FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
MAX_CALLS="${MAX_CALLS:-50}"
DEFAULT_CPS="${DEFAULT_CPS:-5}"
CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TTS_VOICE="${TTS_VOICE:-denis}"
DOMAIN_NAME="${DOMAIN_NAME:-}"

# =============================================
# Проверка обязательных параметров
# =============================================
if [ -z "$FREEPBX_IP" ]; then
    print_error "Параметр FREEPBX_IP не задан в .env"
    echo "Укажите IP-адрес вашего сервера FreePBX."
    exit 1
fi

if [ -z "$EXTENSION_PASSWORD" ]; then
    print_error "Параметр EXTENSION_PASSWORD не задан в .env"
    echo "Укажите пароль для SIP extension."
    exit 1
fi

print_success "Конфигурация загружена"
print_info "  FreePBX IP:      $FREEPBX_IP"
print_info "  FreePBX Extension: $FREEPBX_EXTENSION"
print_info "  Домен:           ${DOMAIN_NAME:-не настроен}"

# =============================================
# Генерация секретов (если не заданы)
# =============================================
print_step "Генерация секретов..."

SECRETS_UPDATED=false

if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(openssl rand -hex 16)
    sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PASSWORD/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Сгенерирован DB_PASSWORD"
fi

if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$JWT_SECRET/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "JWT_SECRET=$JWT_SECRET" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Сгенерирован JWT_SECRET"
fi

if [ -z "$AMI_PASSWORD" ]; then
    AMI_PASSWORD=$(openssl rand -hex 16)
    sed -i "s/^AMI_PASSWORD=.*/AMI_PASSWORD=$AMI_PASSWORD/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "AMI_PASSWORD=$AMI_PASSWORD" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Сгенерирован AMI_PASSWORD"
fi

if [ -z "$METRICS_PASS" ]; then
    METRICS_PASS=$(openssl rand -hex 8)
    sed -i "s/^METRICS_PASS=.*/METRICS_PASS=$METRICS_PASS/" "$SCRIPT_DIR/.env" 2>/dev/null || echo "METRICS_PASS=$METRICS_PASS" >> "$SCRIPT_DIR/.env"
    SECRETS_UPDATED=true
    print_info "Сгенерирован METRICS_PASS"
fi

if [ "$SECRETS_UPDATED" = true ]; then
    source "$SCRIPT_DIR/.env"
    print_success "Секреты сгенерированы и сохранены в .env"
fi

# =============================================
# Экспорт переменных для дочерних скриптов
# =============================================
export FREEPBX_IP
export FREEPBX_EXTENSION
export EXTENSION_PASSWORD
export DB_PASSWORD
export JWT_SECRET
export AMI_PASSWORD
export METRICS_PASS
export DOMAIN_NAME
export MAX_CALLS
export DEFAULT_CPS
export CALL_TIMEOUT
export MAX_RETRIES
export TTS_VOICE

# =============================================
# Сводка перед установкой
# =============================================
print_header "Сводка установки"
echo ""
print_info "Сервер FreePBX:      $FREEPBX_IP"
print_info "Номер Extension:      $FREEPBX_EXTENSION"
print_info "Домен:                ${DOMAIN_NAME:-не настроен}"
print_info "Макс. каналов:        $MAX_CALLS"
print_info "CPS по умолчанию:     $DEFAULT_CPS"
print_info "Голос TTS:            $TTS_VOICE"
echo ""
print_info "Директория установки: /opt/autodialer"
print_info "Директория Asterisk:  /etc/asterisk"
echo ""

read -p "Начать установку? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Установка отменена"
    exit 1
fi

# =============================================
# Делаем скрипты исполняемыми
# =============================================
print_step "Подготовка установочных скриптов..."

if [ -d "$SCRIPT_DIR/scripts" ]; then
    chmod +x "$SCRIPT_DIR/scripts/"*.sh 2>/dev/null || true
    print_success "Скрипты готовы к выполнению"
else
    print_error "Директория scripts не найдена!"
    exit 1
fi

# =============================================
# Запуск установочных скриптов по порядку
# =============================================
INSTALLATION_START=$(date +%s)

SCRIPTS=(
    "01_system_setup.sh:Настройка системы и установка зависимостей"
    "02_asterisk_install.sh:Установка Asterisk"
    "03_asterisk_config.sh:Конфигурация Asterisk"
    "04_pjsip_config.sh:Настройка PJSIP"
    "05_dialplan_config.sh:Настройка диалплана"
    "06_tts_install.sh:Установка TTS (Piper)"
    "07_postgresql_setup.sh:Настройка PostgreSQL"
    "08_redis_setup.sh:Настройка Redis"
    "09_python_backend.sh:Установка Python бэкенда"
    "10_nginx_setup.sh:Настройка Nginx"
    "11_firewall_setup.sh:Настройка файрвола"
    "12_start_services.sh:Запуск сервисов"
    "13_fail2ban_setup.sh:Настройка Fail2ban"
    "14_logrotate_setup.sh:Настройка ротации логов"
)

FAILED_SCRIPTS=()

for script_info in "${SCRIPTS[@]}"; do
    script="${script_info%%:*}"
    description="${script_info##*:}"
    script_path="$SCRIPT_DIR/scripts/$script"
    
    if [ -f "$script_path" ]; then
        print_header "Выполнение: $description"
        
        if bash "$script_path"; then
            print_success "$script выполнен успешно"
        else
            print_error "$script завершился с ошибкой"
            FAILED_SCRIPTS+=("$script")
            
            echo ""
            read -p "Продолжить установку несмотря на ошибку? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                print_error "Установка прервана"
                exit 1
            fi
        fi
    else
        print_warn "$script не найден, пропускаю..."
    fi
done

# =============================================
# Настройка HTTPS (опционально)
# =============================================
if [ -n "$DOMAIN_NAME" ] && command -v certbot &> /dev/null; then
    print_step "Настройка HTTPS с Let's Encrypt..."
    
    read -p "Настроить HTTPS для домена $DOMAIN_NAME? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --email "admin@$DOMAIN_NAME" 2>/dev/null || {
            print_warn "Не удалось получить сертификат, HTTPS не настроен"
        }
        if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
            print_success "HTTPS настроен для $DOMAIN_NAME"
        fi
    fi
fi

# =============================================
# Завершение установки
# =============================================
INSTALLATION_END=$(date +%s)
INSTALLATION_TIME=$((INSTALLATION_END - INSTALLATION_START))

clear
print_header "Установка завершена!"
echo ""

# =============================================
# Предупреждения об ошибках
# =============================================
if [ ${#FAILED_SCRIPTS[@]} -gt 0 ]; then
    print_warn "Некоторые скрипты завершились с ошибками:"
    for script in "${FAILED_SCRIPTS[@]}"; do
        echo "  - $script"
    done
    echo ""
fi

print_success "AutoDialer Ultimate успешно установлен!"
print_info "Время установки: ${INSTALLATION_TIME} секунд"
echo ""

# =============================================
# Информация о сервере
# =============================================
SERVER_IP=$(hostname -I | awk '{print $1}')

print_header "Информация для доступа"
echo ""
print_info "Веб-интерфейс:  http://$SERVER_IP/"
if [ -n "$DOMAIN_NAME" ] && [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
    print_info "Веб-интерфейс (HTTPS): https://$DOMAIN_NAME/"
fi
print_info "Документация API: http://$SERVER_IP/docs"
print_info "Проверка здоровья: http://$SERVER_IP/api/health"
print_info "Метрики:          http://$SERVER_IP/metrics"
echo ""

# =============================================
# Учётные данные
# =============================================
print_header "Учётные данные"
echo ""
print_info "Веб-интерфейс:"
echo "  Логин:    admin"
echo "  Пароль:   admin"
echo ""
print_info "Asterisk AMI:"
echo "  Логин:    autodialer"
echo "  Пароль:   $AMI_PASSWORD"
echo ""
print_info "База данных PostgreSQL:"
echo "  База:     $DB_NAME"
echo "  Логин:    $DB_USER"
echo "  Пароль:   $DB_PASSWORD"
echo ""
print_info "Метрики (/metrics):"
echo "  Логин:    $METRICS_USER"
echo "  Пароль:   $METRICS_PASS"
echo ""

# =============================================
# Команды для проверки
# =============================================
print_header "Команды для проверки"
echo ""
print_info "Проверка сервисов:"
echo "  systemctl status autodialer"
echo "  systemctl status asterisk"
echo "  systemctl status nginx"
echo "  systemctl status postgresql"
echo "  systemctl status redis-server"
echo ""
print_info "Проверка Asterisk:"
echo "  asterisk -rvvv"
echo "  asterisk -rx 'pjsip show registrations'"
echo "  asterisk -rx 'pjsip show endpoints'"
echo ""
print_info "Просмотр логов:"
echo "  tail -f /opt/autodialer/logs/autodialer.log"
echo "  tail -f /var/log/asterisk/full"
echo "  journalctl -u autodialer -f"
echo ""

# =============================================
# Вспомогательные скрипты
# =============================================
print_header "Вспомогательные скрипты"
echo ""
print_info "Статус:"
echo "  autodialer-status           - Статус бэкенда"
echo "  autodialer-all-status       - Статус всех сервисов"
echo "  autodialer-redis-status     - Статус Redis"
echo "  autodialer-firewall-status  - Статус файрвола"
echo "  autodialer-fail2ban-status  - Статус Fail2ban"
echo "  autodialer-logrotate-status - Статус ротации логов"
echo ""
print_info "Управление:"
echo "  autodialer-restart          - Перезапустить бэкенд"
echo "  autodialer-all-restart      - Перезапустить все сервисы"
echo "  autodialer-logs             - Просмотр логов бэкенда"
echo ""

# =============================================
# Важные замечания
# =============================================
print_header "Важные замечания"
echo ""
print_warn "1. СМЕНИТЕ ПАРОЛЬ АДМИНИСТРАТОРА!"
echo "   Войдите в веб-интерфейс и смените пароль немедленно."
echo ""
print_warn "2. ПРОВЕРЬТЕ SIP РЕГИСТРАЦИЮ!"
echo "   Выполните: asterisk -rx 'pjsip show registrations'"
echo "   Должен быть статус 'Registered' для extension $FREEPBX_EXTENSION"
echo ""
print_warn "3. ПРОВЕРЬТЕ ФАЙРВОЛ!"
echo "   Убедитесь, что FreePBX может связаться с этим сервером"
echo "   по портам 5060 (UDP) и 10000-20000 (UDP)."
echo ""
print_info "4. НАСТРОЙТЕ КАМПАНИИ!"
echo "   Создайте кампании и импортируйте контакты через веб-интерфейс."
echo ""

# =============================================
# Файлы конфигурации
# =============================================
print_header "Файлы конфигурации"
echo ""
print_info "Бэкенд:    /opt/autodialer/config/.env"
print_info "Asterisk:  /etc/asterisk/"
print_info "Nginx:     /etc/nginx/sites-available/autodialer"
print_info "Systemd:   /etc/systemd/system/autodialer.service"
echo ""

# =============================================
# Поддержка
# =============================================
print_header "Поддержка"
echo ""
print_info "Документация: https://github.com/naumenis-code/AutoDialer-Ultimate"
print_info "Баг-трекер:   https://github.com/naumenis-code/AutoDialer-Ultimate/issues"
echo ""

print_success "Спасибо за установку AutoDialer Ultimate!"
echo "=============================================="
