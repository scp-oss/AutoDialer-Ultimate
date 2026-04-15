# AutoDialer Ultimate v3.0

Enterprise-grade автоматический обзвонщик на базе Asterisk + FastAPI + React.

## 🚀 Быстрая установка
```bash
# Клонирование
git clone https://github.com/naumenis-code/AutoDialer-Ultimate/
cd autodialer-ultimate

# Настройка
cp .env.example .env
nano .env  # Укажите FREEPBX_IP и пароли

# Установка
sudo ./install.sh
```

📋 Системные требования
```bash
Debian 12 (Bookworm)
Минимум 4GB RAM, 2 vCPU
Доступ к FreePBX серверу (Server-1)
Открытые порты: 80, 443, 5060/udp, 10000-20000/udp
```
🏗️ Архитектура
```bash
[Server-2: AutoDialer]
        ↓ SIP (PJSIP)
[Server-1: FreePBX]
        ↓ Trunk
[Оператор связи]
        ↓
[Абоненты]
```
🔐 Безопасность
```bash
JWT с refresh token rotation
RBAC (admin/operator)
Rate limiting (sliding window)
Circuit breaker для внешних сервисов
Fail2ban для SIP
HTTPS через Let's Encrypt
```
📊 Мониторинг
```bash
/metrics - Prometheus endpoint
/api/health - Health check
Логи: /opt/autodialer/logs/
```
📁 СТРУКТУРА GitHub РЕПОЗИТОРИЯ
```bash
autodialer-ultimate/
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── install.sh
├── docker-compose.yml
├── scripts/
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
│   └── 12_start_services.sh
├── backend/
│   ├── __init__.py
│   ├── requirements.txt
│   ├── main.py
│   ├── logger.py
│   ├── auth.py
│   ├── circuit_breaker.py
│   ├── rate_limiter.py
│   ├── leader_election.py
│   ├── task_registry.py
│   └── ami_manager.py
├── frontend/
│   └── dist/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── asterisk/
│   ├── asterisk.conf
│   ├── rtp.conf
│   ├── pjsip.conf.template
│   ├── extensions.conf
│   └── manager.conf.template
├── systemd/
│   └── autodialer.service
├── nginx/
│   └── autodialer.conf
├── sql/
│   └── schema.sql
├── logrotate/
│   └── autodialer
└── docs/
    ├── INSTALL.md
    ├── CONFIGURATION.md
    ├── API.md
    └── FAQ.md
```
🛠️ Helper Scripts
Скрипт	Назначение
``bash
autodialer-fail2ban-status	Статус всех jail
autodialer-fail2ban-unban	Разбанить IP
autodialer-fail2ban-ban	        Забанить IP вручную
``
