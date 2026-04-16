# AutoDialer Ultimate v3.0

Enterprise-grade автоматический обзвонщик на базе Asterisk + FastAPI + React.

## 📋 Содержание

- [Возможности](#-возможности)
- [Системные требования](#-системные-требования)
- [Быстрая установка](#-быстрая-установка)
- [Архитектура](#️-архитектура)
- [После установки](#-после-установки)
- [Безопасность](#-безопасность)
- [Мониторинг](#-мониторинг)
- [Документация API](#-документация-api)
- [Структура проекта](#-структура-проекта)
- [Удаление](#-удаление)
- [Лицензия](#-лицензия)

## 🚀 Возможности

- **Массовый обзвон** — до 50+ одновременных каналов
- **Гибкий CPS** — настраиваемая скорость дозвона (calls per second)
- **Интеллектуальные повторы** — настраиваемые стратегии для BUSY, NOANSWER, FAILED
- **TTS (Text-to-Speech)** — генерация голосовых сообщений через Piper (русские голоса)
- **IVR с DTMF** — обработка нажатий клавиш (1-согласие, 2-отказ, 3-повтор, 4-оператор)
- **Web-интерфейс** — современная админ-панель на React
- **REST API** — полный доступ через FastAPI
- **Мульти-пользовательский режим** — роли admin/operator/viewer
- **Real-time мониторинг** — WebSocket для live-статистики
- **Отказоустойчивость** — Circuit Breaker, Rate Limiting, Graceful Shutdown
- **Масштабирование** — поддержка Redis Sentinel/Cluster, горизонтальное масштабирование

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
- Открыты порты: 5060/udp (SIP), 10000-20000/udp (RTP)

**Порты, открываемые на сервере AutoDialer:**
- 80/tcp (HTTP)
- 443/tcp (HTTPS)
- 5060/udp (SIP — только от FreePBX)
- 10000-20000/udp (RTP — только от FreePBX)

## 🚀 Быстрая установка
```bash
# Клонирование репозитория
git clone https://github.com/naumenis-code/AutoDialer-Ultimate.git
cd AutoDialer-Ultimate

# Копирование и настройка конфигурации
cp .env.example .env
nano .env  # Укажите FREEPBX_IP, FREEPBX_EXTENSION, EXTENSION_PASSWORD

# Запуск установки
sudo ./install.sh

# Неинтерактивный режим
sudo ./install.sh --yes

# Пропустить определённые компоненты
sudo ./install.sh --skip-firewall --skip-tts
```
После установки:
```bash
Веб-интерфейс: http://<IP-сервера>/
Логин: admin / Пароль: admin (смените при первом входе!)
```
🏗️ Архитектура
```bash
┌─────────────────────────────────────────────────────────────┐
│                    Server-2: AutoDialer Ultimate            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Nginx     │→ │  FastAPI    │→ │    Asterisk + PJSIP │  │
│  │   :80/443   │  │  :8000      │  │         :5060       │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                          ↓                    ↓             │
│                   ┌─────────────┐  ┌─────────────────────┐  │
│                   │ PostgreSQL  │  │       Redis         │  │
│                   │   :5432     │  │       :6379         │  │
│                   └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓ SIP (PJSIP)
┌─────────────────────────────────────────────────────────────┐
│                    Server-1: FreePBX                        │
│                      Extension: ${FREEPBX_EXTENSION}        │
└─────────────────────────────────────────────────────────────┘
                              ↓ Trunk
┌─────────────────────────────────────────────────────────────┐
│                    Оператор связи                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
                        Абоненты
```
📊 После установки
Проверка статуса
```bash
# Статус всех сервисов
autodialer-all-status

# Статус бэкенда
autodialer-status

# Статус Fail2ban
autodialer-fail2ban-status

# Статус файрвола
autodialer-firewall-status

# Статус Redis
autodialer-redis-status

# Статус ротации логов
autodialer-logrotate-status
```
Управление сервисами
```bash
# Перезапуск бэкенда
autodialer-restart

# Перезапуск всех сервисов
autodialer-all-restart

# Просмотр логов в реальном времени
autodialer-logs

# Принудительная ротация логов
autodialer-logrotate-force

# Очистка старых логов
autodialer-logs-cleanup
```
Управление файрволом
```bash
# Разрешить IP
autodialer-firewall-allow 192.168.1.100 "Офис"

# Заблокировать IP (временно)
autodialer-firewall-ban 192.168.1.200 3600

# Заблокировать IP (навсегда)
autodialer-firewall-deny 192.168.1.200
```
Управление Fail2ban
```bash
# Разбанить IP
autodialer-fail2ban-unban asterisk 192.168.1.100

# Забанить IP вручную
autodialer-fail2ban-ban asterisk 192.168.1.200
```
Полезные команды Asterisk
```bash
# Консоль Asterisk
asterisk -rvvv

# Проверка SIP регистрации
asterisk -rx 'pjsip show registrations'

# Проверка PJSIP endpoints
asterisk -rx 'pjsip show endpoints'

# Проверка активных каналов
asterisk -rx 'core show channels'

# Проверка версии
asterisk -rx 'core show version'

# Перезагрузка конфигурации
asterisk -rx 'core reload'
```
Управление Redis
```bash
# Проверка статуса очередей
autodialer-redis-status

# Экстренная очистка очереди дозвона
autodialer-redis-flush-queue

# Подключение к Redis CLI
redis-cli

# Просмотр ключей
redis-cli --scan --pattern '*'
```
Генерация TTS
```bash
# Генерация аудиофайла
autodialer-tts -o welcome -v denis "Здравствуйте! У нас есть для вас предложение."

# Генерация для конкретной кампании
autodialer-tts -c 5 -o campaign_5_msg "Текст для кампании 5"
```
🔐 Безопасность
```bash
Функция                	                Описание
JWT                        Access + Refresh токены с rotation
RBAC                       Роли: admin, operator, viewer
Rate Limiting              Sliding window, защита от DDoS
Circuit Breaker            Защита внешних сервисов (Redis, AMI, DB)
Fail2ban                   Защита SIP и SSH от брутфорса
UFW + iptables             Файрвол с защитой от SYN flood и port scan
HTTPS                      Lets Encrypt (автоматически при указании DOMAIN_NAME)
Security Headers           X-Frame-Options, X-Content-Type, HSTS
```
📊 Мониторинг
```bash
Endpoint	            Назначение	                  Доступ
/metrics	         Prometheus метрики              LAN only
/api/health	         Health check	                 Публичный
/docs	                 Swagger UI	                 Публичный
/redoc	                 ReDoc                         Публичный
```


Метрики Prometheus:
```bash
autodialer_active_calls — активные звонки
autodialer_calls_total — всего звонков (по статусам)
autodialer_cps — calls per second
autodialer_http_requests — HTTP запросы
```
Логи:
```bash
Бэкенд: /opt/autodialer/logs/autodialer.log
Asterisk: /var/log/asterisk/full
Nginx: /var/log/nginx/access.log, /var/log/nginx/error.log
PostgreSQL: /var/log/postgresql/
Redis: /var/log/redis/
```
📚 Документация API
```bash
После запуска документация доступна по адресам:
Swagger UI: http://<IP-сервера>/docs
ReDoc: http://<IP-сервера>/redoc
```
Основные эндпоинты:
```bash
Метод	Путь	Назначение
POST	/api/auth/login	Вход в систему
POST	/api/auth/refresh	Обновление токена
GET	/api/campaigns	Список кампаний
POST	/api/campaigns	Создание кампании
POST	/api/campaigns/{id}/start	Запуск кампании
POST	/api/campaigns/{id}/stop	Остановка кампании
GET	/api/contacts	Список контактов
POST	/api/contacts/import	Импорт контактов
GET	/api/stats	Статистика
GET	/api/history	История звонков
POST	/api/audio/generate	Генерация TTS
GET	/api/system/status	Статус системы
POST	/api/system/disable	Аварийная остановка
```
📁 Структура проекта
```bash
autodialer-ultimate/
├── .env.example                    # Пример конфигурации
├── .gitignore                      # Игнорируемые файлы
├── LICENSE                         # MIT License
├── README.md                       # Этот файл
├── install.sh                      # Главный установщик
├── uninstall.sh                    # Скрипт удаления
├── docker-compose.yml              # Docker Compose
├── Dockerfile.backend              # Dockerfile бэкенда
├── setup.py                        # Установка Python пакета
├── scripts/                        # Скрипты установки (14 шт)
│   ├── 01_system_setup.sh
│   ├── 02_asterisk_install.sh
│   ├── 03_asterisk_config.sh
│   ├── 04_pjsip_config.sh
│   ├── 05_dialplan_config.sh
│   ├── 06_tts_install.sh
│   ├── 07_postgresql_setup.sh
│   ├── 08_redis_setup.sh
│   ├── 09_python_backend.sh
│   ├── 10_nginx_setup.sh
│   ├── 11_firewall_setup.sh
│   ├── 12_start_services.sh
│   ├── 13_fail2ban_setup.sh
│   └── 14_logrotate_setup.sh
├── backend/                        # Python бэкенд (13 файлов)
│   ├── __init__.py
│   ├── requirements.txt
│   ├── main.py
│   ├── logger.py
│   ├── auth.py
│   ├── models.py
│   ├── schemas.py
│   ├── database.py
│   ├── circuit_breaker.py
│   ├── rate_limiter.py
│   ├── leader_election.py
│   ├── task_registry.py
│   └── ami_manager.py
├── frontend/dist/                  # React фронтенд (собранный)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── asterisk/                       # Конфиги Asterisk (9 файлов)
│   ├── asterisk.conf
│   ├── rtp.conf
│   ├── pjsip.conf.template
│   ├── extensions.conf
│   ├── manager.conf.template
│   ├── logger.conf
│   ├── cdr.conf
│   ├── indications.conf
│   └── modules.conf
├── systemd/                        # Systemd сервисы
│   ├── autodialer.service
│   └── asterisk.service.d/
│       └── limits.conf
├── nginx/                          # Nginx конфиг
│   └── autodialer.conf
├── sql/                            # База данных
│   ├── schema.sql                  # Полная схема (23 таблицы)
│   └── migrations/                 # Миграции (6 файлов)
│       ├── 001_initial.sql
│       ├── 002_add_indexes.sql
│       ├── 003_add_triggers.sql
│       ├── 004_add_webhooks.sql
│       ├── 005_add_views.sql
│       └── 006_add_versioning.sql
├── fail2ban/                       # Fail2ban конфиги
│   ├── jail.local
│   └── filter.d/
│       └── asterisk.conf
├── logrotate/                      # Logrotate конфиг
│   └── autodialer
├── docs/                           # Документация
│   ├── INSTALL.md
│   ├── CONFIGURATION.md
│   ├── API.md
│   └── FAQ.md
├── .github/workflows/              # GitHub Actions
│   └── tests.yml
└── requirements/                   # Dev зависимости
    └── dev.txt
```
🔧 Удаление
```bash
bash
# Полное удаление системы
sudo /opt/autodialer/uninstall.sh
Внимание: Будут удалены все файлы в /opt/autodialer, база данных autodialer, системные сервисы.
```

🐛 Решение проблем
```bash
1. Не регистрируется SIP extension
bash
# Проверить статус регистрации
asterisk -rx 'pjsip show registrations'
```
# Проверить логи
```bash
tail -f /var/log/asterisk/full | grep -i register
Возможные причины:
Неверный FREEPBX_IP в .env
Неверный EXTENSION_PASSWORD
Extension не создан на FreePBX
Блокировка порта 5060 файрволом
```
2. Не проигрывается аудио / нет звука
```bash
bash
# Проверить RTP порты
ufw status | grep 10000
# Проверить наличие аудиофайлов
ls -la /var/lib/asterisk/sounds/tts/
```
3. Бэкенд не запускается
```bash
bash
# Проверить статус
systemctl status autodialer

# Проверить логи
journalctl -u autodialer -n 50
```
4. Redis недоступен
```bash
bash
# Проверить статус
systemctl status redis-server

# Проверить подключение
redis-cli ping
```
🤝 Вклад в проект
```bash
Pull requests приветствуются! Для крупных изменений, пожалуйста, сначала создайте issue для обсуждения.
```
📄 Лицензия
```bash
MIT License — см. файл LICENSE
```
👤 Автор
```bash
Илья — naumenis-code
```
⭐ Если проект оказался полезным, поставьте звезду на GitHub!
