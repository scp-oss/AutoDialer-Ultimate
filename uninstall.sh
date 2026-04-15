#!/bin/bash
# uninstall.sh - Полное удаление AutoDialer Ultimate

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${RED}⚠ ВНИМАНИЕ: Это полностью удалит AutoDialer Ultimate!${NC}"
echo "Будут удалены:"
echo "  - Все файлы в /opt/autodialer"
echo "  - База данных autodialer"
echo "  - Системные сервисы"
echo ""

read -p "Вы уверены? Введите 'yes' для подтверждения: " -r
if [ "$REPLY" != "yes" ]; then
    echo "Отмена."
    exit 0
fi

echo "Остановка сервисов..."
systemctl stop autodialer 2>/dev/null || true
systemctl disable autodialer 2>/dev/null || true

echo "Удаление базы данных..."
sudo -u postgres psql -c "DROP DATABASE IF EXISTS autodialer;" 2>/dev/null || true
sudo -u postgres psql -c "DROP USER IF EXISTS autodialer;" 2>/dev/null || true

echo "Удаление файлов..."
rm -rf /opt/autodialer
rm -f /etc/systemd/system/autodialer.service
rm -f /etc/nginx/sites-enabled/autodialer
rm -f /etc/nginx/sites-available/autodialer
rm -f /etc/logrotate.d/autodialer

echo "Очистка Redis..."
redis-cli FLUSHALL 2>/dev/null || true

systemctl daemon-reload

echo -e "${GREEN}✓ AutoDialer Ultimate удалён${NC}"
