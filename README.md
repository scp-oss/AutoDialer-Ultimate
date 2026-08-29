# AutoDialer Ultimate v3.0

Enterprise-grade система автоматического обзвона на базе Asterisk + FastAPI — массовый исходящий обзвон, IVR с DTMF-меню, TTS/STT, веб-панель управления и REST API.

## 📋 Содержание

- [Возможности](#-возможности)
- [Системные требования](#-системные-требования)
- [Быстрая установка](#-быстрая-установка)
- [Установка через Docker](#-альтернативная-установка-через-docker)
- [После установки](#-после-установки)
- [Архитектура](#️-архитектура)
- [Управление сервисами](#-управление-сервисами)
- [Безопасность](#-безопасность)
- [Мониторинг](#-мониторинг)
- [Документация API](#-документация-api)
- [Структура проекта](#-структура-проекта)
- [Удаление](#-удаление)
- [Решение проблем](#-решение-проблем)
- [Лицензия](#-лицензия)

## 🚀 Возможности

- **Массовый обзвон** — десятки одновременных каналов, настраиваемая скорость (CPS), в т.ч. адаптивный CPS с обратной связью по отказам
- **Интеллектуальные повторы** — отдельные стратегии и задержки для BUSY, NOANSWER, FAILED, автоответчика
- **TTS (Text-to-Speech)** — генерация голосовых сообщений через Piper (русские голоса), с очередью и ограничением параллелизма
- **STT (Speech-to-Text)** — распознавание записей звонков (Whisper/Vosk)
- **Полноценный IVR с DTMF** — 1 (согласие), 2 (отказ), 3 (повтор сообщения), 4 (запрос оператора), 0/5–9/`*`/`#` (произвольные действия кампании), таймаут и некорректный ввод — каждый исход сохраняется отдельным статусом в истории звонков
- **Входящие звонки** — приветствие, запись, транскрибация
- **Чёрный список** — с автоматической проверкой при дозвоне и импорте контактов
- **Полноценный аудит действий** — кто, когда, с какого IP и что изменил (настройки, кампании, пользователи, чёрный список), с человекочитаемой расшифровкой каждого события
- **Гибкая система настроек** — 46 параметров в 11 категориях (безопасность, дозвон, аудио, TTS, транскрибация, уведомления/SMTP, API, логирование, Asterisk), применяются из БД без правки `.env`
- **Web-интерфейс** — админ-панель (vanilla JS/HTML/CSS, без сборки)
- **REST API** — полный доступ через FastAPI, автогенерируемая документация (Swagger/ReDoc)
- **Мульти-пользовательский режим** — роли admin/operator/viewer, JWT с rotation, опциональный TOTP
- **Real-time мониторинг** — WebSocket для live-статистики звонков и кампаний
- **Отказоустойчивость** — Circuit Breaker, Rate Limiting, Graceful Shutdown, degraded-режим при недоступности AMI
- **Масштабирование** — поддержка Redis Sentinel/Cluster, несколько gunicorn-воркеров с leader election для фоновых задач

## 📋 Системные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **ОС** | Debian 12 (Bookworm) | Debian 12 |
| **CPU** | 2 vCPU | 4+ vCPU |
| **RAM** | 4 GB | 8+ GB |
| **Диск** | 20 GB | 50+ GB SSD |
| **Сеть** | Доступ к FreePBX | Стабильное соединение |

**Требования к FreePBX (Server-1):**
- Создан SIP extension (любой номер, по умолчанию 291)
- Открыты порты: 5060/udp (SIP), 10000–20000/udp (RTP)

**Порты, открываемые на сервере AutoDialer:**
- 80/tcp (HTTP), 443/tcp (HTTPS)
- 5060/udp (SIP — только от FreePBX)
- 10000–20000/udp (RTP — только от FreePBX)

## 🚀 Быстрая установка

```bash
git clone https://github.com/scp-oss/AutoDialer-Ultimate.git
cd AutoDialer-Ultimate

# Конфигурация
cp .env.example .env
nano .env  # укажите FREEPBX_IP, FREEPBX_EXTENSION, EXTENSION_PASSWORD

# Установка (интерактивная)
sudo ./install.sh

# Неинтерактивный режим / пропуск отдельных компонентов
sudo ./install.sh --force
sudo ./install.sh --skip-firewall --skip-tts
```

## 🐳 Альтернативная установка через Docker

Для быстрого развёртывания в целях тестирования/разработки. Asterisk в контейнер не входит — либо ставится отдельно через `install.sh --skip-postgres --skip-redis --skip-nginx --skip-tts`, либо используется уже существующий сервер.

| Компонент | install.sh | Docker Compose |
|---|---|---|
| Asterisk | ✅ из исходников | ❌ отдельно |
| PostgreSQL / Redis / Nginx | ✅ | ✅ (в контейнерах) |
| Изоляция | нет | полная |
| Подходит для | production | разработка / тестирование |
| Права root | нужны | не нужны |

```bash
git clone https://github.com/scp-oss/AutoDialer-Ultimate.git
cd AutoDialer-Ultimate
cp .env.example .env
nano .env
```

Ключевые переменные `.env` для Docker (Asterisk на хосте или другом сервере):

```bash
# Для локальной установки (install.sh): AMI_HOST=127.0.0.1
# Для Docker, если Asterisk на хосте:
# AMI_HOST=172.17.0.1
# AMI_HOST=host.docker.internal   # macOS/Windows
AMI_HOST=192.168.1.100
AMI_PORT=5038
AMI_USER=autodialer
AMI_PASSWORD=your_ami_password

FREEPBX_EXTENSION=291

# Оставьте пустыми — сгенерируются автоматически при первом запуске
DB_PASSWORD=
JWT_SECRET=
```

```bash
docker-compose up -d          # запуск
docker-compose ps             # статус
docker-compose logs -f backend
docker-compose down           # остановка
docker-compose down -v        # остановка с удалением данных (осторожно!)
```

## 📊 После установки

```
Веб-интерфейс:    http://<IP-сервера>/
Логин:            admin
Пароль:           см. /opt/autodialer/.admin_credentials (сменить при первом входе)

API документация: http://<IP-сервера>/docs
Health check:     http://<IP-сервера>/api/health
```

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                 Server-2: AutoDialer Ultimate                │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Nginx     │→ │  FastAPI    │→ │  Asterisk + PJSIP   │  │
│  │  :80/443    │  │  :8000      │  │       :5060 (AMI)   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                          ↓                    ↓              │
│                   ┌─────────────┐  ┌─────────────────────┐  │
│                   │ PostgreSQL  │  │       Redis         │  │
│                   │   :5432     │  │       :6379         │  │
│                   └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓ SIP (PJSIP)
┌─────────────────────────────────────────────────────────────┐
│                     Server-1: FreePBX                        │
│                    Extension: ${FREEPBX_EXTENSION}            │
└─────────────────────────────────────────────────────────────┘
                              ↓ Trunk
                        Оператор связи → Абоненты
```

FastAPI-бэкенд подключается к Asterisk по AMI (Asterisk Manager Interface) — не по SIP напрямую; сами вызовы идут через PJSIP-транк на FreePBX. Недоступность AMI при старте не блокирует веб-интерфейс: система уходит в degraded-режим и переподключается в фоне.

## 🔧 Управление сервисами

```bash
# Статус
autodialer-all-status            # все сервисы
autodialer-status                # только бэкенд
autodialer-fail2ban-status
autodialer-firewall-status
autodialer-redis-status
autodialer-logrotate-status

# Управление
autodialer-restart               # перезапуск бэкенда
autodialer-all-restart           # перезапуск всех сервисов
autodialer-logs                  # логи в реальном времени
autodialer-logrotate-force
autodialer-logs-cleanup

# Файрвол
autodialer-firewall-allow 192.168.1.100 "Офис"
autodialer-firewall-ban 192.168.1.200 3600     # временный бан
autodialer-firewall-deny 192.168.1.200          # постоянный бан

# Fail2ban
autodialer-fail2ban-unban asterisk 192.168.1.100
autodialer-fail2ban-ban asterisk 192.168.1.200

# Asterisk
asterisk -rvvv                              # консоль
asterisk -rx 'pjsip show registrations'
asterisk -rx 'pjsip show endpoints'
asterisk -rx 'core show channels'
asterisk -rx 'core reload'

# Redis
autodialer-redis-flush-queue     # экстренная очистка очереди дозвона
redis-cli --scan --pattern '*'

# TTS
autodialer-tts -o welcome -v denis "Здравствуйте! У нас есть для вас предложение."
autodialer-tts -c 5 -o campaign_5_msg "Текст для кампании 5"
```

Большинство параметров дозвона, безопасности, TTS/STT, логирования и уведомлений можно менять прямо из веб-интерфейса (вкладка «Настройки») без правки `.env` и без перезапуска — исключения (например, учётные данные AMI) явно помечены и требуют перезапуска сервиса.

## 🔐 Безопасность

| Функция | Описание |
|---|---|
| JWT | Access + Refresh токены с rotation |
| TOTP | Опциональная двухфакторная аутентификация |
| RBAC | Роли: admin, operator, viewer |
| Rate Limiting | Sliding window, отдельные лимиты для `/api/auth/*` |
| Блокировка входа | Настраиваемый лимит попыток и длительность блокировки |
| Circuit Breaker | Защита внешних сервисов (Redis, AMI, DB) |
| Аудит-лог | Полная история действий пользователей с IP/User-Agent |
| Fail2ban | Защита SIP и SSH от брутфорса |
| UFW + iptables | Файрвол с защитой от SYN flood и port scan |
| HTTPS | Let's Encrypt (автоматически при указании `DOMAIN_NAME`) |
| Security Headers | X-Frame-Options, X-Content-Type-Options, HSTS |

## 📊 Мониторинг

| Endpoint | Назначение | Доступ |
|---|---|---|
| `/metrics` | Prometheus метрики | LAN only |
| `/api/health` | Health check | Публичный |
| `/docs` | Swagger UI | Публичный |
| `/redoc` | ReDoc | Публичный |

Ключевые метрики: `autodialer_active_calls`, `autodialer_calls_total` (по статусам), `autodialer_cps`, `autodialer_http_requests`.

Логи: бэкенд — `/opt/autodialer/logs/`, Asterisk — `/var/log/asterisk/full`, Nginx — `/var/log/nginx/`, PostgreSQL — `/var/log/postgresql/`, Redis — `/var/log/redis/`.

## 📚 Документация API

Полная интерактивная документация доступна после запуска: Swagger UI — `http://<IP-сервера>/docs`, ReDoc — `http://<IP-сервера>/redoc`.

| Раздел API | Префикс |
|---|---|
| Аутентификация | `/api/auth` |
| Кампании | `/api/campaigns` |
| Контакты / группы контактов | `/api/contacts`, `/api/contact-groups` |
| Звонки и история | `/api/calls` |
| Статистика | `/api/stats` |
| Аудио / TTS | `/api/audio` |
| Чёрный список | `/api/blacklist` |
| Пользователи | `/api/users` |
| Настройки | `/api/settings` |
| Аудит-лог | `/api/audit` |
| Входящие звонки | `/api/incoming-calls` |
| Система | `/api/system` |
| WebSocket | `/api/ws` |

## 📁 Структура проекта

```
AutoDialer-Ultimate/
├── .env.example                 # Пример конфигурации
├── LICENSE                      # MIT License
├── README.md                    # Этот файл
├── ROADMAP.md                   # История разработки и технические решения
├── install.sh                   # Главный установщик
├── uninstall.sh                 # Скрипт удаления
├── docker-compose.yml, Dockerfile
├── pyproject.toml
├── alembic.ini, alembic/        # Миграции БД
├── scripts/                     # Пошаговые скрипты установки (14 шт)
├── app/                         # Python-бэкенд (FastAPI) — единственное ядро приложения
│   ├── main.py                  # Точка входа (uvicorn/gunicorn app.main:app)
│   ├── core/                    # config, logger, database, redis, security, dependencies
│   ├── models/                  # Pydantic-схемы запросов/ответов
│   ├── api/                     # REST-роутеры (по одному на домен) + WebSocket
│   ├── services/                # Бизнес-логика (кампании, дозвон, TTS, STT, настройки, аудит, ...)
│   ├── workers/                 # Фоновые asyncio-задачи (retry, транскрибация, health, очистка)
│   ├── utils/                   # AMI-хелперы, rate limiter, circuit breaker, leader election
│   └── requirements/             # base.txt, dev.txt, prod.txt, tts.txt, stt.txt
├── docker/                      # Dockerfile + entrypoint для Asterisk-образа
├── tests/                       # pytest-набор (health, security, websocket, дозвон, ...)
├── frontend/dist/                # Веб-интерфейс (vanilla JS, без сборки)
│   ├── index.html
│   ├── components/tabs/          # HTML-фрагменты вкладок
│   ├── css/style.css
│   └── js/*.js
├── asterisk/                     # Конфиги Asterisk (asterisk.conf, extensions.conf, pjsip.conf.template, ...)
├── systemd/                      # systemd-юнит бэкенда
├── nginx/                        # Nginx-конфиг
├── sql/schema.sql                # Полная схема БД (40 таблиц)
├── fail2ban/                     # Fail2ban конфиги
├── logrotate/                    # Logrotate конфиг
├── docs/                         # Документация
└── .github/workflows/            # GitHub Actions (CI)
```

## 🗑️ Удаление

```bash
sudo /opt/autodialer/uninstall.sh
```

Внимание: будут удалены все файлы в `/opt/autodialer`, база данных `autodialer` и системные сервисы.

## 🐛 Решение проблем

**Не регистрируется SIP extension**
```bash
asterisk -rx 'pjsip show registrations'
tail -f /var/log/asterisk/full | grep -i register
```
Частые причины: неверный `FREEPBX_IP`/`EXTENSION_PASSWORD` в `.env`, extension не создан на FreePBX, порт 5060 заблокирован файрволом.

**Не проигрывается аудио**
```bash
ufw status | grep 10000
ls -la /var/lib/asterisk/sounds/tts/
```

**Бэкенд не запускается**
```bash
systemctl status autodialer
journalctl -u autodialer -n 50
```

**Redis недоступен**
```bash
systemctl status redis-server
redis-cli ping
```

## 🤝 Вклад в проект

Pull requests приветствуются! Для крупных изменений сначала создайте issue для обсуждения.

## 📄 Лицензия

MIT License — см. файл [LICENSE](LICENSE).

---

⭐ Если проект оказался полезным, поставьте звезду на GitHub!
