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
# -i/--itemize-changes печатает ровно одну строку на каждый реально
# скопированный/удалённый файл и молчит, если различий нет - по пустому
# выводу узнаём, изменилось ли что-то, и решаем, нужен ли рестарт.
# Раньше скрипт рестартовал сервис безусловно на каждый запуск, даже когда
# git говорил "уже актуально" - на живом дозвоне это лишний раз рвёт все
# активные звонки без всякой причины.
# --no-owner --no-group: обычный rsync -a копирует ещё и владельца/группу
# С ИСТОЧНИКА (репозиторий, принадлежит root), а строкой ниже мы сами
# выставляем autodialer:autodialer НА ПРИЁМНИКЕ - без этих флагов rsync на
# каждом запуске видел расхождение владельца (root в источнике vs
# autodialer в приёмнике от прошлого запуска), считал файл "изменившимся"
# и откатывал владельца на root, а chown ниже тут же возвращал его
# обратно - вечная перетасовка, ложно определявшаяся как реальное
# изменение кода и запускавшая рестарт на пустом месте (подтверждено
# живьём). --exclude='__pycache__': .pyc-кэш не из репозитория и не
# должен быть предметом deploy - без исключения его создание/устаревание
# между запусками тоже могло ложно засчитаться как изменение.
backend_changes="$(rsync -a --no-owner --no-group --delete --exclude='__pycache__' -i "$REPO_DIR/app/" "$DEPLOY_ROOT/backend/app/")"
if [ -n "$backend_changes" ]; then
    echo "$backend_changes"
fi
chown -R autodialer:autodialer "$DEPLOY_ROOT/backend/app"

echo "==> Синхронизация frontend: frontend/dist/ -> $DEPLOY_ROOT/frontend/dist/"
frontend_changes="$(rsync -a --no-owner --no-group --delete -i "$REPO_DIR/frontend/dist/" "$DEPLOY_ROOT/frontend/dist/")"
if [ -n "$frontend_changes" ]; then
    echo "$frontend_changes"
fi
chown -R www-data:www-data "$DEPLOY_ROOT/frontend/dist"

if [ -n "$backend_changes" ]; then
    echo "==> Backend изменился - перезапуск $SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME" --no-pager -l || true
    echo "==> Последние строки журнала:"
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager
else
    echo "==> Backend не менялся - рестарт $SERVICE_NAME пропущен (активные звонки не тронуты)"
fi

if [ -n "$frontend_changes" ]; then
    echo "==> Фронтенд обновлён - сделай Ctrl+Shift+R в браузере, рестарт сервиса для этого не нужен"
else
    echo "==> Фронтенд не менялся"
fi

echo "==> Готово."
