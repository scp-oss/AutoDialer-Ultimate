# AutoDialer Ultimate v3.0

Enterprise-grade автоматический обзвонщик на базе Asterisk + FastAPI + React.

## 🚀 Быстрая установка
```bash
git clone ttps://github.com/naumenis-code/AutoDialer-Ultimate/
cd AutoDialer-Ultimate
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
├── README.md
├── install.sh                    # Главный установочный скрипт
├── .env.example                  # Пример конфигурации
├── docker-compose.yml            # Опционально для Docker
├── scripts/
│   ├── 01_system_setup.sh        # Системные зависимости и лимиты
│   ├── 02_asterisk_install.sh    # Установка Asterisk
│   ├── 03_asterisk_config.sh     # Конфигурация Asterisk
│   ├── 04_pjsip_config.sh        # PJSIP конфигурация
│   ├── 05_dialplan_config.sh     # Dialplan
│   ├── 06_tts_install.sh         # Установка Piper TTS
│   ├── 07_postgresql_setup.sh    # Настройка PostgreSQL
│   ├── 08_redis_setup.sh         # Настройка Redis
│   ├── 09_python_backend.sh      # Установка Python и зависимостей
│   ├── 10_nginx_setup.sh         # Настройка Nginx
│   ├── 11_firewall_setup.sh      # Настройка файрвола
│   └── 12_start_services.sh      # Запуск всех сервисов
├── backend/
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
│       └── index.html
├── asterisk/
│   ├── asterisk.conf
│   ├── rtp.conf
│   ├── pjsip.conf
│   ├── extensions.conf
│   └── manager.conf
├── systemd/
│   └── autodialer.service
├── nginx/
│   └── autodialer.conf
└── sql/
    └── schema.sql
```
