# AutoDialer Ultimate — статус проекта и план дальнейшей разработки

Этот документ фиксирует, что было сделано в текущей фазе работ ("Phase 1:
рабочее ядро"), какие архитектурные решения приняты и почему, и что
остаётся для полного соответствия исходному техническому заданию
(промышленная система массового SIP-обзвона с веб-интерфейсом на React,
TTS/STT, Kubernetes-манифестами и т.д.).

## Как читать этот документ

Раздел 1 — что реально работает и проверено. Раздел 2 — архитектура как
она есть сейчас. Раздел 3 — что осталось сделать, по фазам. Раздел 4 —
как развернуть и проверить систему locally.

---

## 1. Phase 1: что сделано

Исходный репозиторий представлял собой результат минимум двух независимых
генераций кода, которые никогда не сводились воедино: плоский монолит
`backend/` (на который были заведены `docker-compose.yml`/CI) и
архитектурно более зрелый модульный пакет `app/`, который не запускался
вовсе — `app.create_app()` падал на первом же импорте.

Phase 1 состояла в том, чтобы (а) выбрать `app/` как единственное ядро
(б) довести его до реально работающего состояния (в) связать с
Docker/Alembic/CI (г) добавить то, что было объявлено, но не
реализовано (WebSocket-дашборд) (д) проверить весь стек end-to-end
насколько позволяет среда выполнения.

### 1.1 Исправленные баги (по серьёзности)

Каждый пункт был найден и подтверждён через реальный запуск кода
(`python -c "import app"` → `pytest` → живой Postgres/Redis/Asterisk),
а не только чтением исходников.

**Критичные (ломали основную функциональность полностью):**

1. **AMI-команды никогда не работали.** `app/services/dialer.py` строил
   каждый AMI-запрос (подписку на события, `Originate`, `Hangup`,
   `Ping`, `CoreShowChannels`) через `panoramisk.message.Action(...)` —
   такого класса в `panoramisk` не существует. Это `AttributeError` на
   **каждый** вызов, включая инициацию звонка — то есть обзвон в принципе
   не мог позвонить ни на один номер, при этом само AMI-соединение
   устанавливалось успешно и выглядело "живым". Заменено на `ami_action()`
   — обычный dict с ключом `Action`, как того требует реальный API
   `panoramisk.Manager.send_action()`. Подтверждено вживую: запущен
   настоящий Asterisk, AMI подключился, `Ping`/`Originate`-совместимые
   вызовы формируются корректно.
2. **`app/core/logger.py` не содержал логгер.** Файл фактически содержал
   код FastAPI-зависимостей (`get_current_user`, `require_admin`, rate
   limiting) — а не `StructuredLogger`, который импортирует весь
   остальной проект (`from app.core.logger import logger`). Переименован
   в `app/core/dependencies.py` (этому соответствует и его собственный
   docstring); `app/core/logger.py` написан заново — контекстные
   переменные (correlation/request/user id), JSON/console форматтеры,
   ротация файлов, `AuditLogger`, `LogTimer`.
3. **`app/utils/ami_manager.py` — мёртвый код.** Второй, неиспользуемый
   `DialerManager` (740 строк), при этом обёрнутый в
   `try/except ImportError`, из-за чего реальный `DialerManager` из
   `app/services/dialer.py` тихо подменялся заглушкой, кидающей
   `ImportError` при любом обращении. Удалён.
4. **`init_dialer()` блокировал старт приложения на ~5.5 минут**, если
   Asterisk недоступен (10 попыток подключения с exponential backoff
   `2..60`с) — при этом сам код был обёрнут в try/except, который никогда
   не успевал сработать вовремя для отдачи `/api/health` при недоступном
   SIP. Добавлен режим `quick=True` для стартового подключения (1 попытка)
   с последующим фоновым переподключением каждые 30с — веб-интерфейс и
   REST API теперь доступны сразу, даже если SIP ещё не настроен/недоступен
   (ровно то поведение, которого требует ТЗ: статусы Online/Offline/
   Registration failed, а не падающий бэкенд).
5. **`init_services()` не связывал модульные singletons.** Каждый сервис
   регистрировался в `ServiceRegistry`, но НЕ через `set_X_service()`,
   который используют свободные функции `get_X_service()`, вызываемые
   API-роутерами напрямую — то есть каждый эндпоинт при первом же запросе
   упал бы с `RuntimeError("... не инициализирован")`. Также
   `SystemService` создавался без ссылок на `dialer_manager`/
   `transcription_service`, из-за чего статус AMI/SIP в `/api/health`
   всегда показывал `not_initialized` независимо от реального состояния.
6. **JWT-токены не проходили собственную проверку.** `create_token()`
   подписывает токен с `aud=autodialer-api`, но `decode_token()` не
   передавал `audience=` в `jwt.decode()` — python-jose при наличии `aud`
   в токене требует явно передать ожидаемую аудиторию, иначе кидает
   `Invalid audience`. Итог: **ни один** выданный токен не декодировался
   бы обратно, то есть вход в систему был бы сломан после первого же
   запроса с токеном. Исправлено, покрыто тестом.
7. **`env_prefix="AUTODIALER_"` в `Settings`** делал недействующими ВСЕ
   переменные окружения, задокументированные в `.env.example`
   (`DB_HOST`, `JWT_SECRET`, `AMI_PASSWORD` и т.д. — без префикса).
   `.env`-конфигурация не подхватывалась вообще, всё тихо уходило на
   дефолты (включая небезопасный `SECRET_KEY` по умолчанию). Убран
   префикс; `SECRET_KEY` получил `validation_alias="JWT_SECRET"` для
   соответствия документации/docker-compose/скриптам.
8. **`sql/schema.sql`: триггер версионирования падал на каждой вставке
   в `settings`.** `create_record_version()` обращается к `NEW.id`, а
   PK таблицы `settings` — `key` (VARCHAR). 17 дефолтных настроек не
   могли быть вставлены ни при `docker-entrypoint-initdb.d`, ни через
   Alembic. Триггер `version_settings` убран (settings осознанно не
   версионируется по `id`).
9. **`asterisk/pjsip.conf.template` не парсился Asterisk 20** —
   `support_outbound` (в секции `aor`/`registration`) и
   `max_initial_qualify` (в `global`) не существуют как опции PJSIP;
   Asterisk отбрасывал объекты `aor`/`global` целиком при попытке их
   создать, что в конечном итоге ломало исходящую регистрацию
   (`AOR '' not found`). Подтверждено и исправлено на **реальном**
   Asterisk 20.6 — после фикса SIP REGISTER проходит полный цикл и
   `pjsip show registrations` показывает `Registered`.

**Существенные (ломали конкретные функции):**

10. 11 моделей ответов (`CampaignResponse`, `ContactResponse`,
    `UserResponse` и т.д.) объявляли `class X(BaseSchema, TimestampSchema)`
    — `TimestampSchema` сам наследует `BaseSchema`, это ошибка порядка
    MRO, `TypeError` при импорте.
11. `app/models/task.py`, `stats.py`, `api_token.py` — систематическая
    опечатка `description("текст")` вместо `description="текст"`
    (226 строк), плюс несколько строк с несбалансированными
    скобками.
12. `app/services/dialer.py`/`call_result.py` — два Prometheus-метрики
    регистрировались под одинаковым именем (`autodialer_active_calls`,
    `autodialer_call_duration_seconds`) → `ValueError: Duplicated
    timeseries` при импорте; аналогично `app/core/__init__.py` определял
    4 неиспользуемых метрики, коллизирующих с настоящими метриками в
    сервисах (Counter `..._total` автоматически резервирует и
    сопутствующее имя `..._created`).
13. `app/workers/metrics.py` создавал новый `Gauge(...)` при **каждом**
    вызове периодической функции — упал бы на второй итерации с той же
    ошибкой дублирования. Метрики вынесены на уровень модуля.
14. `app/services/transcription.py.get_info()` — синхронный метод
    вызывал `self.redis.llen(...)` (асинхронный) без `await`, кладя
    сам объект корутины в `queue_size`; воркер падал с
    `'>' not supported between instances of 'coroutine' and 'int'`
    на каждой проверке очереди транскрибации.
15. `app/__init__.py` регистрировал `loop.add_signal_handler(SIGTERM/
    SIGINT)` без обработки исключений — падает с `RuntimeError` вне
    главного потока главного интерпретатора (в частности, в тестах
    через Starlette TestClient).
16. `app/services/dialer.py.stop_all_calls()` обращался к
    `self.channels_hash_key`, которого не существует (опечатка/пропущенная
    инициализация) — `AttributeError` при остановке обзвона.
17. `start_all_workers()`/`stop_all_workers()` никогда не вызывались из
    `app/__init__.py` — все фоновые задачи (retry queue, транскрибация,
    health monitor, log cleanup) были определены, но не запускались.

### 1.2 Структурная уборка

- Удалён дублирующий плоский `backend/` (на него ссылались Docker/CI;
  оставлен `app/` как единственное ядро; Docker/CI переключены на него).
- Удалены: битый `./MIT License` (содержал текст `.gitignore`), root
  `requirements/` (устаревшие/противоречащие зависимости — `pyttsx3`/
  `gTTS` вместо реально используемого `piper-tts`, `psycopg2-binary`
  вместо `asyncpg`), `docs/INSTALLATION.md` (описывал другой продукт,
  "AutoDialer Pro", с другим репозиторием), `setup.py` (указывал
  `find_packages(where='backend')`, объявлял `entry_points`/`scripts=[...]`
  на ~10 несуществующих файлов).
- Добавлен `pyproject.toml` (современная замена `setup.py`).
- README.md: убраны неточные упоминания React-фронтенда
  (`frontend/dist` — vanilla JS/HTML/CSS без сборки) и устаревшая
  структура каталогов.

### 1.3 Новое / реализованное с нуля

- **Alembic** (`alembic/`) поверх существующей асинхронной asyncpg-модели
  доступа к данным: `alembic/env.py` использует
  `sqlalchemy.ext.asyncio` + `asyncpg` только для управления миграциями
  (без ORM-моделей, рантайм по-прежнему работает через
  `app/core/database.py: ConnectionPool/QueryBuilder/BaseRepository`,
  см. §2.2 почему). Первая миграция `0001_initial_schema.py` применяет
  `sql/schema.sql` (23 таблицы, 90+ индексов, триггеры, функции,
  5 представлений, дефолтные данные) через собственный
  `$$...$$`-aware SQL-сплиттер (asyncpg не умеет multi-statement
  `execute()`). Проверено: `upgrade head` → `downgrade base` →
  `upgrade head` — полный цикл, идемпотентно.
- **WebSocket-дашборд** (`app/services/websocket.py` +
  `app/api/websocket.py`, эндпоинт `/api/ws/dashboard`): менеджер
  локальных соединений + подписка на Redis Pub/Sub
  (`ws_channels:{call,campaign,system,notification}`), чтобы события,
  сгенерированные в дозвонщике или в фоновом воркере (другой процесс),
  доходили до всех подключённых клиентов дашборда. Использует уже
  существовавшие, но нигде не применявшиеся Pydantic-модели
  `LiveCallEvent`/`CampaignProgressEvent`/`SystemNotificationEvent`
  (`app/models/system.py`). Проверено end-to-end тестом: клиент
  подключается, получает начальный снимок статуса, затем реальное
  сообщение, опубликованное в Redis из отдельного клиента.
- **`app/services/notification.py`** — CRUD поверх таблицы
  `notifications` + публикация в тот же WebSocket-канал.
- **Docker**: `Dockerfile` (backend, `python:3.12-slim`, entrypoint
  сначала гоняет `alembic upgrade head`), `docker/asterisk/Dockerfile` +
  `entrypoint.sh` (рендерит `pjsip.conf`/`manager.conf` из шаблонов через
  `envsubst`, поднимает Asterisk с нашим дозвонным контекстом),
  `docker-compose.yml` (postgres, redis, asterisk, backend, nginx;
  volumes для `tts_audio`/`call_recordings`, шаренные между backend/
  asterisk/nginx; healthchecks; обязательные секреты через
  `${VAR:?required}`).
- **CI** (`.github/workflows/tests.yml`): переписан на Python 3.11/3.12,
  `app/requirements/dev.txt`, реальные Postgres+Redis services,
  `alembic upgrade head` перед тестами, `ruff` (два прохода: строгий по
  `F821/F822/F823/E9` — падает сборку; полный — только предупреждение),
  `mypy` (advisory).
- **`tests/`** — новый набор (12 тестов, ранее отсутствовал): boot
  smoke-тесты, JWT/пароли (unit), health/liveness/readiness (интеграция
  с реальными Postgres+Redis, без падения при недоступном AMI),
  WebSocket (подключение + сквозная доставка через Redis Pub/Sub),
  регрессионный тест на `ami_action`.

### 1.4 Как это было проверено (важно: без Docker)

В используемой рабочей среде **демон Docker недоступен** (нет доступа к
cgroups/`/var/run/docker.sock`, `dockerd` не поднимается даже с
максимальными правами в рамках сессии) — `docker-compose up` в этой
сессии физически невозможно было запустить. Поэтому вся валидация
выполнена через **нативно установленные** PostgreSQL 16, Redis 7 и
Asterisk 20.6 (все три — через `apt`) с теми же самыми конфигами
(`sql/schema.sql` через Alembic, `asterisk/*.conf`/`pjsip.conf.template`
через тот же `envsubst`, что и в `docker/asterisk/entrypoint.sh`),
только на `127.0.0.1` вместо DNS-имён сервисов compose. Это валидирует
приложенческий код и конфигурацию с высокой достоверностью, но **сами
Dockerfile/docker-compose.yml не собирались и не поднимались буквально** —
рекомендуется первым делом прогнать `docker compose up --build` в
среде с рабочим Docker перед продакшен-деплоем.

---

## 2. Архитектура (текущее состояние)

### 2.1 Структура каталогов

```
app/
  core/          config, logger, database (asyncpg pool), redis, security, dependencies
  models/        Pydantic-схемы запросов/ответов (не ORM)
  api/           REST-роутеры (health, auth, campaigns, contacts, calls, audio,
                 blacklist, users, settings, audit, incoming, websocket) + system
  services/      бизнес-логика; один файл на домен, ServiceRegistry + get_X_service()
  workers/       фоновые asyncio-задачи (retry, transcription queue, health monitor,
                 log cleanup, metrics, reconciliation), leader election через Redis
  utils/         circuit breaker, rate limiter, leader election, task registry
alembic/         миграции (одна на сегодня: 0001_initial_schema, читает sql/schema.sql)
sql/             schema.sql (эталон схемы), migrations/ (историческая последовательность,
                 уже объединена в schema.sql), migrate.py (для bare-metal пути)
frontend/dist/   vanilla JS/HTML/CSS админ-панель (не React — см. §3.2)
asterisk/        конфиги Asterisk + pjsip.conf.template (рендерится envsubst'ом)
docker/          Dockerfile для Asterisk + entrypoint-скрипты
tests/           pytest (12 тестов, DB/Redis обязательны, AMI опционален)
install.sh, scripts/, systemd/, nginx/, fail2ban/, logrotate/  bare-metal путь развёртывания
```

### 2.2 Ключевые архитектурные решения и почему

- **Слой доступа к БД — asyncpg напрямую, не SQLAlchemy ORM**, несмотря
  на то, что ТЗ перечисляет SQLAlchemy в стеке. `app/core/database.py`
  — это готовый, полнофункциональный `ConnectionPool` + `QueryBuilder` +
  `BaseRepository` с health-check/reconnect, Circuit Breaker,
  Prometheus-метриками — уже написанный с расчётом на низкую задержку
  при сотнях одновременных запросов (важно для дозвонщика). Переписывать
  ~15 сервисов на ORM ради формального соответствия строке в ТЗ означало
  бы рискованный рефакторинг бизнес-логики без возможности его
  полноценно перепроверить в оставшееся время. Вместо этого SQLAlchemy
  используется **только** внутри Alembic (`alembic/env.py`) для
  управления миграциями — задача, для которой он и предназначен, без
  необходимости заводить ORM-модели. Если ORM обязателен по формальным
  причинам — это отдельная, крупная задача на будущую фазу (см. §3.6).
- **Фоновые задачи — свои asyncio-воркеры с leader election через Redis,
  не Celery**, хотя ТЗ говорит "Celery или аналог" (аналог — это ровно
  то, что уже было реализовано: `app/utils/leader_election.py` +
  `app/workers/__init__.py: start_all_workers()`). Один процесс, без
  отдельного брокера задач, что для дозвонщика с низкой требуемой
  задержкой между шагами кампании — разумный выбор. `celery[redis]`
  убран из зависимостей как неиспользуемый.
- **Веб-интерфейс остаётся vanilla JS**, а не переписан на React — это
  сознательный компромисс по приоритету "рабочее ядро сначала",
  выбранному в начале сессии. `frontend/dist/js/*.js` — рабочий,
  вызывает реальные `/api/*` эндпоинты (не статический макет), поэтому
  admin-panel уже пригодна к использованию, просто не на стеке из ТЗ.

### 2.3 База данных

23 таблицы (`sql/schema.sql`): `users`, `sessions`, `campaigns`,
`campaign_schedules`, `contact_groups`, `contacts`, `contact_import_jobs`,
`campaign_contacts`, `call_results`, `call_recordings`, `settings`,
`audio_files`, `tts_jobs`, `audit_log`, `blacklist`, `api_tokens`,
`webhook_events`, `webhook_subscriptions`, `webhook_deliveries`,
`record_versions`, `notifications`, `system_events`, `incoming_calls`.
5 представлений (`campaign_stats`, `daily_stats`, `active_campaigns`,
`dial_queue_view`, `dashboard_summary`). ER-диаграмма — см. §3.1
(не построена в этой фазе).

### 2.4 SIP / AMI

Система работает как SIP UA через связку **наш Asterisk (в
docker-compose/`docker/asterisk`) + AMI**: `app/services/dialer.py:
DialerManager` подключается к Asterisk по AMI (`panoramisk`), Asterisk,
в свою очередь, регистрируется как SIP-клиент на внешней АТС клиента
(`pjsip.conf`, объект `type=registration`, параметры — `FREEPBX_IP`/
`FREEPBX_EXTENSION`/`EXTENSION_PASSWORD` из веб-настроек/`.env`).
Статус (Online/Offline/Registration failed) отдаётся через
`/api/health` (поле `ami_connected` + `components.ami`) и теперь
также транслируется через WebSocket (канал `system`) при каждом
изменении статуса подключения/отключения AMI (см. §3.4).

---

## 3. Что осталось (по фазам, в порядке приоритета)

### 3.1 Документация и диаграммы
ER-диаграмма (dbdiagram.io/Mermaid из `sql/schema.sql`), полное описание
каждого REST-эндпоинта сверх автосгенерированного `/docs` (Swagger уже
работает "из коробки" через FastAPI — `/docs`, `/redoc`, `/openapi.json`),
диаграммы последовательности для потока обзвона и обработки входящего
звонка, описание всех WebSocket-событий (частично задокументированы в
`app/models/system.py`, нужно свести в отдельный документ).

### 3.2 Frontend на React/TypeScript/Vite/Tailwind/shadcn
Текущий `frontend/dist/js/*.js` рабочий и вызывает реальные эндпоинты —
можно мигрировать экран за экраном, используя его как спецификацию поведения, не
теряя функциональность в процессе.

### 3.3 Полное тестовое покрытие
Сегодня — 12 тестов (boot/security/health/websocket/dialer-regression).
Нужны: unit-тесты бизнес-логики каждого сервиса (кампании, контакты,
чёрный список, TTS/STT), интеграционные тесты полного цикла обзвона
(mock AMI), E2E (Playwright по vanilla JS UI или будущему React),
нагрузочное тестирование (Locust/k6) на CPS/конкурентные звонки согласно
целям масштабирования из ТЗ (сотни одновременных звонков, сотни тысяч
номеров).

### 3.4 SIP/AMI: живые события в WebSocket — сделано
`DialerManager` теперь публикует `LiveCallEvent` (dial_begin/answer/
hangup/dtmf) и `SystemNotificationEvent` (подключение/потеря AMI) в
Redis-каналы `ws_channels:call`/`ws_channels:system`, которые уже
рассылались `WebSocketService` подключённым клиентам — раньше эти
AMI-события двигали только внутреннюю state machine, дашборд же видел
лишь статичный снимок при подключении.

Заодно исправлен фронтенд-клиент дашборда
(`frontend/dist/js/system.js`): он стучался в несуществующий
`/api/ws/system` с придуманным форматом сообщения, которого бэкенд
никогда не отдавал. Переключён на реальный `/api/ws/dashboard` и
разобранный по факту контракт `{"type": "call"|"campaign"|"system"|
"notification", "data": {...}}` из `app/api/websocket.py`. Также
исправлено чтение `data.asterisk_connected` в `refreshStatus()` —
такого поля REST `/system/status` никогда не возвращал (реальное имя
— `ami_connected`), из-за чего индикатор Asterisk всегда показывал
"недоступен" независимо от реального статуса.

`CampaignService.start_campaign()` (`dial_task()`) теперь тоже
публикует `CampaignProgressEvent` в канал `campaign` — раз в 5
обработанных контактов, плюс всегда на завершение/остановку/ошибку
кампании — переиспользуя уже существовавший `get_campaign_progress()`.

Заодно найден и исправлен смежный баг: `_add_contacts_to_campaign()`
при добавлении контактов через `group_ids` выполнял
`conn.fetchval("SELECT COUNT(*) FROM ...")` — буквальное многоточие
вместо реального запроса, что гарантированно кидало бы синтаксическую
ошибку Postgres при каждой попытке добавить контакты в кампанию по
группам. Исправлено на разбор command-тега `INSERT N M`, который уже
возвращает `conn.execute()` (по аналогии с разбором `DELETE N` в
`remove_contacts_from_campaign`).

Живая отрисовка канала `campaign` на фронтенде также сделана:
`system.js` больше не игнорирует `campaign`-события, а передаёт их в
`App.campaigns.handleCampaignEvent()`; тот точечно обновляет строку
таблицы (`campaignRowHtml()` вынесен в переиспользуемый метод) и, если
открыта модалка деталей той же кампании (`state.viewingCampaignId`),
перезапрашивает её через REST — `CampaignProgressEvent` не несёт полного
набора статистики (busy/noanswer/failed и т.п.), поэтому модалка дорисовывается из
полного `CampaignDetailResponse`, а не из неполных
данных события.

Заодно найдены и исправлены два смежных бага, из-за которых сама
таблица кампаний показывала неверные данные независимо от WebSocket:

1. `CampaignResponse` (и, соответственно, ответ `GET /campaigns`) вообще
   не содержал `stats` — `campaigns.js` читал `c.stats?.progress_percent`
   и т.п., что всегда было `undefined`. Добавлено поле `stats` в модель
   и его заполнение в `CampaignService.list_campaigns()` (по аналогии с
   уже существовавшим по-элементном вызовом `_get_campaign_tags()`).
2. `campaigns.js` читал `c.max_calls`/`c.cps`/`campaign.caller_id`/
   `campaign.audio_id` как плоские поля — в `CampaignResponse` они вложены
   в `dialer_settings`. Хуже того, `saveCampaign()` при
   создании/редактировании кампании отправлял их бэкенду тоже плоскими
   полями верхнего уровня, а `CampaignCreateRequest`/
   `CampaignUpdateRequest` ожидают вложенный `dialer_settings` — при
   `extra="ignore"` в `BaseSchema` эти поля молча отбрасывались, и
   кампания всегда создавалась/обновлялась с настройками дозвона по
   умолчанию (max_calls=30, cps=5, без caller ID и аудио), что бы
   пользователь ни ввёл в форму. Заодно там же нашёлся баг с `schedule`:
   при выключенном чекбоксе расписания отправлялся `null`, а поле
   `schedule` в моделях запроса не `Optional` — это гарантированно
   валилось бы 422-й ошибкой валидации. Оба бага исправлены в
   `saveCampaign()`.

### 3.5 Kubernetes-манифесты
Не созданы. `docker-compose.yml` — хорошая основа: Deployment на backend
(с readinessProbe на `/api/health/ready`), StatefulSet или managed
Postgres/Redis, DaemonSet/Deployment на Asterisk с hostNetwork (SIP/RTP
плохо живут за обычным ClusterIP из-за диапазона портов RTP), PVC под
`tts_audio`/`call_recordings`, Secret под `JWT_SECRET`/`DB_PASSWORD`/
`AMI_PASSWORD`.

### 3.6 SQLAlchemy ORM (если формально обязателен)
См. §2.2 — оценка объёма: ~15 сервисов, ~25 моделей, нужен параллельный
прогон (dual-write или staged migration) чтобы не потерять корректность
на боевых данных при переключении дозвонщика под нагрузкой.

### 3.7 Резервное копирование
Не реализовано. Нужны: `pg_dump`/WAL-archiving расписание (cron/
Kubernetes CronJob), ротация бэкапов `tts_audio`/`call_recordings`
(могут быть велики, политика хранения уже частично есть в
`settings.audio_retention_days`, нужно распространить на бэкапы),
задокументированная процедура restore.

### 3.8 Стратегия масштабирования воркеров
Сегодня воркеры (`start_all_workers()`) выполняются в том же процессе,
что и API — с leader election для задач, которые не должны дублироваться.
Часть задач (`retry_queue`, `transcription_queue`, `health_monitor`) НЕ
leader-gated и при горизонтальном масштабировании backend-реплик будут
выполняться избыточно (не некорректно, но расточительно). Для вынесения
в отдельный масштабируемый Worker-деплоймент нужно либо сделать все
периодические задачи leader-gated, либо перейти на очередь задач с
конкурентным потреблением (тогда действительно понадобится Celery/
аналог с брокером, а не текущая leader-election модель).

### 3.9 Российский план нумерации — консолидация и фикс — сделано
Заказчик — из России, план набора должен быть российским (`+7`,
10 значащих цифр, мобильные коды `9XX`, домашний алиас `8` вместо `+7`).
Аудитом подтверждено, что это уже было заложено верно (`_X.` в
`asterisk/extensions.conf`/`asterisk.conf` — универсальный, без завязки
на другую страну; `pjsip.conf.template` уже `language = ru`; VOSK-модель
по умолчанию — `vosk-model-small-ru-0.22`) — но правила нормализации
(`8`→`7`, голый `9XXXXXXXXX`→`79XXXXXXXXX`, отображение
`+7 (900) 123-45-67`) были продублированы (с расхождениями) в 4 местах
бэкенда (`app/models/contact.py`, `blacklist.py`, `incoming.py`,
`app/services/dialer.py`) и в форматировании — ещё в 2
(`app/services/blacklist.py`, `app/services/call_result.py`).

Вынесены в единый `app/utils/phone.py`
(`normalize_phone`/`validate_phone_number`/`format_phone_display`), все
6+ дублей теперь импортируют/делегируют туда.

Заодно найден и исправлен реальный баг: валидатор
`CallResultCreateRequest.phone` (`app/models/call.py`) только вырезал
нецифровые символы, не приводя ведущую `8` к `7` — в отличие от всех
остальных телефонных полей в системе. Результат звонка с номером вида
`89991234567` сохранялся бы как есть, не совпадая с `contacts.phone`
(там всегда `79991234567`) при джойнах, и потенциально мог обойти
проверку чёрного списка. Исправлено на использование общего
`normalize_phone`.

`BlacklistAddRequest` заодно переведён с мягкой проверки `len(phone) >=
10` на общий `validate_phone_number()` — теперь так же отклоняет явно
некорректные коды оператора/региона (`70…`/`71…`), как и создание
контакта.

На фронтенде было 6 почти идентичных копий `formatPhone`/
`formatPhoneNumber` (`campaigns.js`, `blacklist.js`, `history.js`,
`contactGroups.js`, `dashboard.js`, `contacts.js`, плюс инлайновая в
`incoming.js`) — все переведены на делегирование к единственной
`App.formatPhoneNumber()` в `utils.js`. Заодно её ветка для голого
10-значного номера без кода страны исправлена, чтобы всегда показывать
`+7 (...)`, а не просто `(...)` без страны.

---

## 4. Быстрый старт (проверено нативно, Docker — не проверен буквально)

```bash
cp .env.example .env
# заполнить DB_PASSWORD, JWT_SECRET (32+ символов), AMI_PASSWORD,
# FREEPBX_IP/FREEPBX_EXTENSION/EXTENSION_PASSWORD

docker compose up --build -d   # postgres, redis, asterisk, backend, nginx
# backend entrypoint сам прогонит `alembic upgrade head` при старте

curl http://localhost/api/health
# {"status": "healthy", "ami_connected": true/false, ...}
```

Для локальной разработки без Docker: поднять Postgres/Redis, затем

```bash
pip install -r app/requirements/base.txt -r app/requirements/dev.txt
alembic upgrade head
uvicorn app.main:app --reload
pytest tests/ -v
```
