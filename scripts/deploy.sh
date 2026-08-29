#!/usr/bin/env bash
# =============================================
# AutoDialer Ultimate - деплой обновлений на прод
# =============================================
#
# Репозиторий (git checkout, куда прилетает git pull) и то, что реально
# запущено, - РАЗНЫЕ директории на этом сервере:
#   - backend крутится из /opt/autodialer/backend (см.
#     scripts/09_python_backend.sh) - только app/ оттуда, не весь репозиторий
#   - frontend отдаётся nginx из /opt/autodialer/frontend/dist (см.
#     scripts/10_nginx_setup.sh) - тоже отдельная копия
# git pull в самом репозитории НИЧЕГО не меняет в том, что реально
# работает, пока эти два каталога не синхронизированы вручную - именно
# это и делает этот скрипт одной командой вместо ручного cp по списку
# делом.
#
# Использование:
#   sudo ./scripts/deploy.sh [ветка]
# Если ветка не указана - берётся текущая ветка репозитория.
#
# ПРИМЕЧАНИЕ про миграции БД: этот systemd-based деплой (в отличие от
# docker/backend-entrypoint.sh) никогда не копировал alembic.ini/alembic/
# в /opt/autodialer/backend и не гонял `alembic upgrade head` - если
# очередной коммит меняет sql/schema.sql или добавляет alembic-миграцию,
# её нужно применить к БД отдельно и вручную. Этот скрипт синхронизирует
# только код (app/ и frontend/dist/), схему БД не трогает.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Нужны права root (chown/systemctl) - запусти через sudo." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ROOT="/opt/autodialer"
SERVICE_NAME="autodialer"

cd "$REPO_DIR"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"

echo "==> Репозиторий: $REPO_DIR (ветка $BRANCH)"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "==> Синхронизация backend: app/ -> $DEPLOY_ROOT/backend/app/"
rsync -a --delete "$REPO_DIR/app/" "$DEPLOY_ROOT/backend/app/"
chown -R autodialer:autodialer "$DEPLOY_ROOT/backend/app"

echo "==> Синхронизация frontend: frontend/dist/ -> $DEPLOY_ROOT/frontend/dist/"
rsync -a --delete "$REPO_DIR/frontend/dist/" "$DEPLOY_ROOT/frontend/dist/"
chown -R www-data:www-data "$DEPLOY_ROOT/frontend/dist"

echo "==> Перезапуск $SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 1
systemctl status "$SERVICE_NAME" --no-pager -l || true

echo "==> Последние строки журнала:"
journalctl -u "$SERVICE_NAME" -n 20 --no-pager

echo "==> Готово. Не забудь Ctrl+Shift+R в браузере - фронтенд закэширован."
