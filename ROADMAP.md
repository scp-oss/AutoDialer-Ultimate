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
k8s/             Kubernetes-манифесты (черновик, не проверен на кластере — см. §3.5)
tests/           pytest (91 тест; 86 — чистые unit-тесты без внешних зависимостей,
                 5 — интеграционные, требуют Postgres+Redis; AMI опционален)
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

29 таблиц (`sql/schema.sql`): `users`, `sessions`, `campaigns`,
`campaign_schedules`, `contact_groups`, `contacts`, `contact_import_jobs`,
`contact_group_members`, `contact_tags`, `contact_notes_history`,
`campaign_contacts`, `call_results`, `call_recordings`, `settings`,
`audio_files`, `tts_jobs`, `audit_log`, `blacklist`, `blacklist_tags`,
`blacklist_history`, `api_tokens`, `webhook_events`,
`webhook_subscriptions`, `webhook_deliveries`, `record_versions`,
`notifications`, `system_events`, `incoming_calls`. Было 24 —
`blacklist_tags`/`blacklist_history` добавлены при фиксе `blacklist`,
`contact_group_members`/`contact_tags`/`contact_notes_history` — при
фиксе `contacts` (см. §3.0). 5 представлений (`campaign_stats`,
`daily_stats`, `active_campaigns`, `dial_queue_view`, `dashboard_summary`).
ER-диаграмма — `docs/ER_DIAGRAM.md` (см. §3.1) — **устарела после этого
раунда**, не отражает новые колонки/таблицы `blacklist`/`contacts`, регенерация не
входила в объём текущего раунда.

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

### 3.0 Критично: расхождение схемы БД и сервисного слоя — блокирует часть API
Найдено при написании юнит-тестов для `BlacklistService` (см. §3.3): моки
БД в юнит-тестах не проверяют реальные имена колонок, поэтому баг
вскрылся только когда сервис был прогнан против настоящего Postgres.

**Баг №1 (исправлен, широко распространён): `request.<enum>.value` при
`use_enum_values=True`.** `app/models/common.py: BaseSchema.model_config`
задаёт `use_enum_values=True` для вообще всех Pydantic-моделей проекта —
это значит, что поле-enum после валидации хранит **строку** (`request.reason
== "spam"`), а не объект enum. Написанный ранее код сервисов почти
везде обращался к этим полям как к enum-объектам: `request.reason.value`,
`filter_params.status]` в списковых включениях `[s.value for s in
filter_params.status]` и т.п. — рабочий с реальным enum, но кидающий
`AttributeError: 'str' object has no attribute 'value'` на голой строке.
Итог: `BlacklistService.add_to_blacklist()`/`bulk_add_to_blacklist()`
падали на **каждой** попытке добавить новый номер (до записи в БД —
`.value` вычислялся прямо в аргументах `INSERT`), `export_to_csv()` падал
при непустом списке. То же самое обнаружилось (grep по всем
`app/services/*.py` + точечная проверка каждого случая, живая ли это
enum-переменная или поле pydantic-модели) в: `app/services/audio.py`
(генерация TTS), `app/services/audit.py` (экспорт в CSV/JSON),
`app/services/call_result.py` (сохранение результата звонка — **самый
частый** путь записи в системе), `app/services/campaign.py` (создание/
обновление кампании), `app/services/contact.py` (создание/обновление
контакта, импорт), `app/services/incoming.py` (обновление входящего
звонка), `app/services/user.py` (создание/обновление пользователя,
кастомные разрешения). Исправлено везде одинаково: убран `.value` там,
где значение уже строка (поле pydantic-модели), оставлен там, где это
действительно объект enum (например, `CampaignStatus.RUNNING.value` —
прямое обращение к члену класса enum, не поле модели, не тронуто).
Регрессия зафиксирована тестами (`tests/test_blacklist_service.py`,
15 тестов, все через реальные `BlacklistAddRequest`/`BlacklistBulkAddRequest`
— то есть проходят валидацию `use_enum_values=True` так же, как в проде).

**Баг №2 (исправлен): `is_expired` — `None` вместо `False`.**
`app/services/blacklist.py: _get_blacklist_by_id()`/`list_blacklist()`
вычисляли `is_expired=row['expires_at'] and row['expires_at'] <
datetime.utcnow()` — при `expires_at IS NULL` (подавляющее большинство
записей: постоянная блокировка без срока) `and` возвращает `None`
(короткое замыкание), а не `False`, что валится на Pydantic-поле
`is_expired: bool`. Исправлено оборачиванием в `bool(...)`.

**Баг №3 (исправлен для `blacklist`, для остальных таблиц — только
задокументирован, это отдельная крупная задача): `sql/schema.sql`
годами не синхронизировался с сервисным слоем.** `blacklist` в
`sql/schema.sql` был определён 5 колонками (`id, phone, reason,
created_by, created_at`), а `app/services/blacklist.py` (~1100 строк)
вокруг этой таблицы реализует статус (active/expired/removed), срок
действия, источник, теги, историю, CSV-экспорт, массовые операции — то
есть **каждая** операция чёрного списка падала бы с
`asyncpg.exceptions.UndefinedColumnError` на базе, собранной из
актуального `sql/schema.sql`. Исправлено:
- `sql/schema.sql`: добавлены недостающие колонки `blacklist`
  (`reason_details, status, expires_at, source, notes,
  times_called_before, updated_at, removed_at, removed_by,
  removed_reason`) и две таблицы, которых не было вообще, хотя сервис их
  читает/пишет напрямую — `blacklist_tags` (активно используется) и
  `blacklist_history` (сервис только читает через `_get_entry_history`;
  ничего в неё пока не пишет — таблица создана, чтобы `SELECT` не падал,
  наполнение не реализовано и это отдельная задача на будущее).
- Заодно исправлен триггер `check_blacklist()`: раньше помечал
  `contacts.blacklisted = TRUE` при наличии **любой** записи с этим
  номером в `blacklist`, включая мягко удалённые (`status = 'removed'`)
  — теперь корректно проверяет `status = 'active'`.
- Новая идемпотентная Alembic-миграция `alembic/versions/
  0002_blacklist_schema_fix.py` (`ALTER TABLE ... ADD COLUMN IF NOT
  EXISTS` + `CREATE TABLE IF NOT EXISTS`) — доводит базы, уже
  развёрнутые на `0001`, до актуальной схемы без потери данных.
- **Проверено вживую**: поднят нативный Postgres, накачена `0001` →
  `0002`, выполнен полный цикл `add_to_blacklist` → `check_phone` →
  `export_to_csv` → `list_blacklist` → `get_stats` →
  `remove_phone_from_blacklist` → повторный `check_phone` (корректно
  `False` после удаления — это же подтверждает и фикс триггера) — ни
  одной ошибки на реальной БД.

**Баг №4 (исправлен для `contacts`/`contact_groups`, продолжение работы
по Багу №3): та же схемная просадка на `contacts`.** `sql/schema.sql`
знал только про 18 базовых колонок `contacts` и одиночный `group_id`
(один-к-одному), а `app/services/contact.py` (`ContactService` +
`ContactGroupService`, ~1400 строк) реализует расширенную анкету
контакта, мягкое удаление, DND, счётчик просмотров и полноценное
многие-ко-многим контакт↔группа с тегами и историей заметок — вживую
подтверждено падением `create_contact()` на `INSERT` с
`UndefinedColumnError: column "phone2" does not exist`. Исправлено:
- `sql/schema.sql`: `contacts` дополнен колонками `phone2, phone3,
  gender, birth_date, company, position, country, region, city, address,
  postal_code, source, last_call_status, successful_calls, dnd,
  dnd_until, view_count, deleted_at`; `status` CHECK расширен до всех 5
  значений `ContactStatus` (было только 3 — `blacklisted`/`error`
  раньше даже не проходили бы constraint); `contact_groups` дополнен
  `is_public`/`updated_at`. Добавлены три таблицы, которых не было
  вообще: `contact_group_members` (многие-ко-многим, с `is_primary` —
  `contacts.group_id` остаётся для обратной совместимости как основная
  группа), `contact_tags`, `contact_notes_history` (сервис пока только
  читает её через `_get_contact_notes_history`, наполнение — будущая
  задача, как и `blacklist_history`).
- Новая идемпотентная миграция `alembic/versions/
  0003_contacts_schema_fix.py`.
- **Побочная находка при живой проверке через `alembic upgrade head` (а
  не прямой прогон `sql/schema.sql` через `psql`, как раньше) — баг в
  самом `0001_initial_schema.py`.** Его `_split_sql_statements()` бил
  `sql/schema.sql` на отдельные операторы по каждому `;` вне `$$...$$`,
  но не считал `-- ...`-комментарии и `'...'`-строковые литералы
  непрозрачными зонами — а описательный комментарий перед
  `blacklist_history` (добавленный в прошлом раунде) и мой новый перед
  `contact_notes_history` оба содержат `;` внутри обычного русского
  предложения ("... читает эту таблицу; наполнение — будущая задача").
  Результат: `CREATE TABLE contact_notes_history (...)` резалось пополам
  прямо на слове "наполнение", `alembic upgrade head` падал с
  `PostgresSyntaxError`. Это относится и к уже существовавшему
  комментарию перед `blacklist_history` — вероятно, `0002` в прошлом
  раунде проверялась только через прямой `psql -f sql/schema.sql`
  (не ломается — `psql` понимает SQL-комментарии нативно) и
  инкрементальный путь `0001→0002` без предварительного fresh-`0001`,
  либо этот текст комментария появился уже после последней живой
  проверки `alembic upgrade head`; в любом случае сам факт, что баг был
  тут и не пойман — напоминание, что "проверено вживую" должно всегда
  включать **fresh `alembic upgrade head` с нуля**, а не только
  прямой `psql -f schema.sql`. Исправлено: `_split_sql_statements()`
  теперь также трактует `-- до конца строки` и `'...'` как
  непрозрачные — проверено юнит-проверкой (186 операторов, ни один не
  начинается с "хвоста" разрезанного комментария) и полным `alembic
  upgrade head` с нуля (`0001→0002→0003`).
- **Проверено вживую**: `alembic upgrade head` с нуля, затем полный цикл
  через `ContactService`/`ContactGroupService` — `create_group` →
  `create_contact` (все новые поля) → `get_contact` → `update_contact` →
  `list_contacts` → `blacklist_contact`/`unblacklist_contact` →
  `delete_contact`/`restore_contact` → `list_groups`/`get_group_tree` →
  `export_contacts` (CSV+JSON) → `bulk_import_contacts` — ни одной
  ошибки.

**Баг №5 (исправлен для `campaigns`/`call_results`, продолжение работы по
Багу №3): та же схемная просадка + два новых класса живых багов,
обнаруженных только при полном прогоне `CampaignService`/
`CallResultService`.** `campaigns` не хватало `priority, dial_mode,
call_timeout, answer_timeout, caller_id_number, paused_at, stopped_at,
metadata` (все — часть `DialerSettingsSchema`/`CampaignPriority`,
которые `CampaignService.create_campaign()`/`update_campaign()` пишут
напрямую); таблицы `campaign_tags` не было вообще. `call_results` не
хватало `direction, dtmf_digits, wait_time, recording_size, tags, notes`;
таблиц `call_tags`/`call_events`/`call_transcriptions` не было вообще.
`campaign_contacts` не хватало `last_call_status`. Вживую подтверждено:
`CampaignService.get_campaign()` падал на `cr.wait_time does not exist`
внутри JOIN на `call_results` при подсчёте статистики кампании — то есть
баг в `call_results` ломал не только сам `call_result.py`, но и просмотр
любой кампании. Исправлено (`sql/schema.sql` + новая идемпотентная
миграция `alembic/versions/0004_campaigns_call_results_schema_fix.py`).

При живом прогоне `CallResultService.save_call_result()`/`get_call_stats()`
найдены и исправлены два независимых бага в самом `app/services/
call_result.py`, не связанных со схемой:

- `_update_contact_stats()`/`_update_campaign_progress()` переиспользовали
  `$1` и как обычное присвоение колонке (`last_call_status = $1`), и
  внутри `CASE WHEN $1 IN ('agreed', 'declined') THEN ...` — asyncpg
  выводит для одного и того же `$1` два разных типа (`character varying`
  из колонки, `text` из сравнения со строковыми литералами) и кидает
  `AmbiguousParameterError: inconsistent types deduced for parameter $1`
  на **каждый** вызов `save_call_result()`, у которого есть `contact_id`
  или `campaign_id` (то есть почти всегда). Исправлено явным приведением
  `$1::VARCHAR` в обеих `CASE`-ветках.
- `_get_dtmf_stats()` безусловно приклеивал `{where_clause} AND
  dtmf_result IS NOT NULL` — когда вызывающий код (`get_call_stats()` без
  фильтров) не передаёт условий, `where_clause` — пустая строка, и запрос
  превращается в `FROM call_results  AND dtmf_result IS NOT NULL` без
  `WHERE`, что гарантированно `PostgresSyntaxError` на любом
  вызове статистики без фильтра по кампании/периоду (самый частый
  случай — дашборд без фильтров). Соседний `_get_hangup_causes()` этой
  ошибки не содержит: там `where_conditions` всегда стартует с
  обязательного условия по `days`, так что `where_clause` никогда не
  пуст — сверено отдельно, чтобы не чинить то, что не сломано. Исправлено
  условной сборкой `WHERE .../ AND ...` в зависимости от того, пуст ли
  `where_clause`.

**Проверено вживую**: `alembic upgrade head` с нуля (`0001→0002→0003→
0004`), затем `CampaignService` — `create_campaign` (полный
`dialer_settings` + `priority` + теги) → `get_campaign` → `update_campaign`
→ `list_campaigns` (с фильтром по `priority`) → `delete_campaign`; и
`CallResultService` — `save_call_result` → `get_call` →
`get_call_by_unique_id` → `list_calls` (с фильтром по `direction`) →
`get_call_stats` → `get_daily_stats`/`get_analytics` → `delete_call` — ни
одной ошибки после фиксов. Регрессия проверена повторным прогоном
`tests/test_blacklist_service.py` и смоук-теста `contacts` — 96/96
`pytest` по-прежнему проходит.

**Баг №6 (исправлен для `users`/`user_permissions`/`api_keys`, продолжение
работы по Багу №3): та же схемная просадка + широкая роль/статус
CHECK-просадка + один живой баг типа asyncpg↔Pydantic.** `sql/schema.sql`
знал только про 13 базовых колонок `users` и не имел `user_permissions`/
`api_keys` вообще — `UserService`/`AuthService` (~1840 строк) реализуют
расширенный профиль (телефон/отдел/должность/аватар/настройки/
уведомления), мягкое удаление, 2FA (TOTP), кастомные разрешения поверх
роли и API-ключи. Вживую подтверждено падением `create_user()` на
`INSERT` с `UndefinedColumnError: column "phone" does not exist`.
Дополнительно: `role` CHECK-constraint допускал только 3 из 6 значений
`UserRole` (`admin`/`operator`/`viewer`) — `manager`/`api`/`auditor`
были бы отвергнуты Postgres на любом `create_user()`/`update_user()` с
такой ролью. Исправлено:
- `sql/schema.sql`: `users` дополнен колонками `phone, department,
  position, status, created_by, avatar_url, preferences, notifications,
  totp_secret, totp_enabled, totp_recovery_codes, totp_last_used,
  deleted_at, login_count, metadata`; `role` CHECK расширен до всех 6
  значений `UserRole`; добавлен `status` CHECK (`active`/`inactive`/
  `blocked`/`pending`, по `UserStatus`). Добавлены две таблицы, которых
  не было вообще: `user_permissions` (кастомные разрешения поверх
  `ROLE_PERMISSIONS`), `api_keys` (API-ключи, `create_api_key`/
  `list_api_keys`/`revoke_api_key`/`verify_api_key`).
- Новая идемпотентная миграция `alembic/versions/
  0005_users_schema_fix.py`.
- При живом прогоне `UserService.disable_user()`/`enable_user()` (то есть
  любой путь, перечитывающий пользователя после того, как в него хоть
  раз писался `last_ip` через `login()`) найден и исправлен реальный баг
  в `app/services/user.py`, не связанный со схемой: `users.last_ip` —
  колонка типа `INET`, asyncpg возвращает такие колонки как
  `ipaddress.IPv4Address`/`IPv6Address`, а не `str`; `UserResponse.last_ip`
  типизирован как `Optional[str]` — прямая передача `row['last_ip']` в
  конструктор кидала `pydantic.ValidationError: Input should be a valid
  string`. Ломалось не при создании пользователя (там `last_ip` ещё
  `NULL`), а на первом же перечитывании профиля после логина — то есть в
  проде это проявилось бы на дашборде управления пользователями сразу
  после первого входа любого пользователя. Исправлено в обоих местах,
  строящих `UserResponse` из строки БД (`_get_user_by_id()`,
  `list_users()`): `str(row['last_ip']) if row['last_ip'] else None`.
- **Проверено вживую**: `alembic upgrade head` с нуля (`0001→0002→0003→
  0004→0005`), затем полный цикл через `UserService`/`AuthService` —
  `create_user` (роль `manager` + кастомное разрешение) → `get_user` →
  `update_user` → `update_profile` → `list_users` → `login` →
  `change_password` → `setup_totp`/`verify_totp` (реальный TOTP-код,
  вычисленный вручную по тому же алгоритму, что и
  `TOTPManager.verify_totp()`) → `create_api_key`/`list_api_keys`/
  `verify_api_key`/`revoke_api_key` → `disable_user`/`enable_user` →
  `delete_user`/`restore_user` — ни одной ошибки после фиксов.
  Регрессия проверена повторным прогоном `pytest` — 96/96 по-прежнему
  проходит.

**Баг №7 (исправлен для `audio_files`/`audio_tags`/`audio_usage`,
продолжение работы по Багу №3): та же схемная просадка + тип-мисматч +
рецидив Бага №1 в новом месте.** `sql/schema.sql` не хватало у
`audio_files` колонок `file_name, status, sample_rate, channels,
bitrate, converted_from_id, tts_text, tts_voice, tts_model, tts_speed,
updated_at, view_count, usage_count, last_used_at, deleted_at` — все
пишутся/читаются `AudioService`/`TTSService` (`upload_audio`,
`convert_audio`, `generate_audio`, увеличение `view_count` в
`get_audio()`, `usage_count`/`last_used_at` в `get_audio_file_path()`).
Таблиц `audio_tags`/`audio_usage` не было вообще — любой вызов
`_add_audio_tags()`/`_get_audio_tags()`/`_get_usage_history()` падал бы с
`UndefinedTableError`. Отдельно найден тип-мисматч: `duration` был
объявлен `INTEGER`, а `AudioMetadata.duration`/`AudioResponse.duration` —
`float` (`soxi -D` возвращает дробные секунды, например `15.5`) —
вставка нецелой длительности в `INTEGER`-колонку кидала бы asyncpg
`DataError` почти на каждой загрузке/генерации TTS. Исправлено:
- `sql/schema.sql`: `audio_files` дополнен перечисленными колонками,
  `duration` расширен до `DOUBLE PRECISION`; добавлены `audio_tags`
  (многие-ко-многим тег↔аудио) и `audio_usage` (сервис пока только
  читает её через `_get_usage_history`, наполнение — будущая задача, как
  и `blacklist_history`/`contact_notes_history` ранее).
- Новая идемпотентная миграция `alembic/versions/
  0006_audio_schema_fix.py`.
- При живом прогоне `AudioService.upload_audio()` найден и исправлен
  рецидив Бага №1 в новом месте, в двух независимых точках: `app/models/
  audio.py: AudioUploadRequest.convert_to` типизирован как
  `Optional[AudioFormat]` со значением по умолчанию `AudioFormat.SLN`, но
  `use_enum_values=True` на `BaseSchema` нормализует **даже значение по
  умолчанию** в голую строку `'sln'` при создании модели — то есть
  `request.convert_to` никогда не является `AudioFormat`-объектом, даже
  когда клиент вообще не передавал `convert_to`. `_convert_audio()`
  падал на `target_format.value` (`AttributeError: 'str' object has no
  attribute 'value'`) при построении пути результата; после фикса того
  же вызова `upload_audio()` упал на том же `.value` уровнем выше — в
  собственном `INSERT`, где брался `target_format.value` до нормализации.
  Оба места теперь приводят значение через `AudioFormat(x)` перед
  использованием `.value`.
- **Проверено вживую**: `alembic upgrade head` с нуля (`0001→0002→0003→
  0004→0005→0006`), затем `AudioService` — `upload_audio` (WAV→SLN
  конвертация при загрузке) → `get_audio` (счётчик `view_count`) →
  `update_audio` (теги) → `list_audio` → `convert_audio` (SLN→WAV) →
  `get_audio_file_path` (`usage_count`/`last_used_at`) → `delete_audio` —
  ни одной ошибки после фиксов. Смоук-тест ограничен путями, не
  требующими `ffmpeg`/`piper` (недоступны в этой среде) — конвертация в
  MP3 и генерация TTS не проверялись живьём в этом раунде, только
  статически. Регрессия проверена повторным прогоном `pytest` — 96/96
  по-прежнему проходит.

**Баг №8 (исправлен для `audit_log`, продолжение работы по Багу №3): та
же схемная просадка + рецидив Бага №6 (INET→str) в новом месте + сломанный
SQL-запрос статистики.** `sql/schema.sql` не хватало у `audit_log`
колонок `user_role, severity, entity_name, changes, request_method,
request_path, correlation_id, request_id, session_id, status,
error_message, metadata` — все пишутся `AuditService.log()`/`log_batch()`
напрямую в `INSERT`, то есть **любое** аудируемое действие в системе
падало бы с `UndefinedColumnError`. Исправлено:
- `sql/schema.sql`: `audit_log` дополнен перечисленными колонками
  (`severity` — с CHECK по `AuditSeverity`); добавлены индексы по
  `correlation_id`, `severity`, `(entity_type, entity_id)`, `session_id`
  под соответствующие запросы (`get_audit_log`'s related-events lookup,
  фильтрация по важности, `get_entity_stats`, подсчёт уникальных сессий).
- Новая идемпотентная миграция `alembic/versions/
  0007_audit_log_schema_fix.py`.
- При живом прогоне найден и исправлен рецидив Бага №6 в новом месте:
  `audit_log.ip_address` — тоже `INET`, asyncpg возвращает
  `ipaddress.IPv4Address`/`IPv6Address`, а не `str`;
  `AuditLogResponse.ip_address: Optional[str]` кидал бы
  `pydantic.ValidationError` на первой же записи с непустым IP (то есть
  почти всегда — контекст запроса обычно включает IP). Исправлено в
  `get_audit_log()` и `_row_to_response()` тем же паттерном:
  `str(row['ip_address']) if row['ip_address'] else None`.
- Отдельно найден и исправлен настоящий баг в `get_user_stats()`, не
  связанный со схемой: запрос длительности сессий одновременно делал
  `GROUP BY session_id` и вычислял `AVG(EXTRACT(...MAX(created_at) -
  MIN(created_at)...))` — вложенные агрегатные функции внутри `AVG()` при
  активном `GROUP BY` того же уровня, что Postgres прямо запрещает:
  `GroupingError: aggregate function calls cannot be nested`. Падало на
  **каждый** вызов `get_user_stats()` (просмотр статистики пользователя),
  а не только когда у пользователя были сессии — ошибка возникает на
  этапе planning запроса, до выполнения. Исправлено переписыванием на
  подзапрос: сперва длительность на сессию через `GROUP BY session_id`,
  затем `COUNT(*)`/`AVG(...)` уже над результатом подзапроса без
  вложенности.
- **Проверено вживую**: `alembic upgrade head` с нуля (`0001→0002→0003→
  0004→0005→0006→0007`), затем `AuditService` — `log`/`log_batch` (с
  общим `correlation_id`/`session_id`) → `get_audit_log` (проверка типа
  `ip_address` после конверсии, связанные события по `correlation_id`) →
  `list_audit_logs` (фильтр по `severity`/`status`/`correlation_id`) →
  `get_audit_by_entity`/`get_audit_by_user` → `get_stats`/
  `get_user_stats`/`get_entity_stats` → `export_to_csv`/`export_to_json`
  → `cleanup_old_logs` (dry run) → `health_check` — ни одной ошибки после
  фиксов. Регрессия проверена повторным прогоном `pytest` — 96/96
  по-прежнему проходит.

**Не исправлено, только задокументировано.** Та же проверка (сравнение
колонок в `INSERT INTO` сервисов с реальным списком колонок в
`sql/schema.sql`, статический скрипт по всем `app/services/*.py`) для
оставшихся таблиц — колонки, которые сервис ожидает в `INSERT`, а
`sql/schema.sql` их не определяет, плюс таблицы, которых нет вообще:

- `incoming_calls` (`app/services/incoming.py`): `caller_name,
  called_number, recording_format, unique_id, linked_id, language,
  status, created_at, updated_at`; таблиц нет: `incoming_call_tags`,
  `incoming_call_events`
- `settings` (`app/services/settings.py`): `created_at`

Практически это значит: обработка входящего звонка, вероятно, всё ещё
падает на любом окружении, где база создаётся из актуального
`sql/schema.sql` (создание пользователя, TTS-аудио и запись аудита, ранее
в этом же списке, исправлены Багами №6-№8 выше). Статический список
может быть неточным (проверялись только `INSERT INTO`, не
`UPDATE`/`SELECT`/представления/триггеры), а живой прогон, как показали
Баги №5-№8, иногда вскрывает дополнительные баги самого сервисного кода,
не только схемы — перед исправлением каждой таблицы её нужно
перепроверить так же, как
`blacklist`/`contacts`/`campaigns`/`call_results`/`users`/`audio_files`/
`audit_log`:
**fresh `alembic upgrade head` с нуля** (не просто `psql -f
sql/schema.sql` — см. находку про `0001` выше) плюс живой прогон
сервиса. **Это самая приоритетная задача проекта на сегодняшний день**
— важнее React-фронтенда и SQLAlchemy ORM, потому что без неё часть
REST API нерабочая независимо
от остального прогресса.

### 3.1 Документация и диаграммы
ER-диаграмма — сделано: `docs/ER_DIAGRAM.md` (Mermaid, все 24 таблицы
`sql/schema.sql`), с заметками о нетривиальных связях (двунаправленный FK
`campaigns`↔`audio_files`, полиморфные `record_versions`/`audit_log` без
прямого FK на версионируемую сущность, `settings` с непервичным `id`,
двойная нормализация телефона на уровне API и SQL-триггера).

WebSocket-события и диаграммы последовательности — сделано:
`docs/EVENTS_AND_FLOWS.md`. Свод всех 4 типов WebSocket-событий
(`call`/`campaign`/`system`/`notification` — модель, источник публикации,
когда публикуется, как потребляется на фронтенде) в одну таблицу вместо
разрозненных докстрингов по файлам; диаграммы последовательности
(Mermaid) для исходящего звонка кампании (от `dial_task()` через
Redis-очередь `dial_queue` и AMI `Originate` до `LiveCallEvent` на
дашборде), входящего звонка (webhook `/api/incoming/webhook`) и очереди
повторных звонков (`retry_queue`-воркер).

Построено чтением кода, а не по памяти/ТЗ — при этом найдена и
задокументирована реальная нестыковка: `asterisk/extensions.conf` этого
репозитория не содержит контекста, который принимает входящий звонок и
вызывает `/api/incoming/webhook` после записи — там только `[sub-record]`
(для **исходящих** звонков через `Gosub` из `dialer_bridge`). Согласуется
с архитектурой из §2.4 (наш Asterisk — только AMI/исходящий обзвон,
входящие звонки принимает внешняя FreePBX клиента), но означает, что
вызов webhook должен быть настроен отдельно на стороне FreePBX
(dialplan-макрос с `curl`/AGI после записи) — это конфигурация внешней
системы, отсутствующая (и не могущая присутствовать) в этом репозитории,
и её нужно явно прописать в процессе внедрения у клиента. Сам эндпоинт и
обработка на backend рабочие, просто ничего не вызывает их автоматически
без этой внешней настройки.

Ещё нужно: полное описание каждого REST-эндпоинта сверх автосгенерированного
`/docs` (Swagger уже работает "из коробки" через FastAPI — `/docs`, `/redoc`,
`/openapi.json`) — само по себе покрывает контракт запросов/ответов,
осталось разве что дополнить его бизнес-контекстом там, где имя
эндпоинта не самоочевидно.

### 3.2 Frontend на React/TypeScript/Vite/Tailwind/shadcn
Текущий `frontend/dist/js/*.js` рабочий и вызывает реальные эндпоинты —
можно мигрировать экран за экраном, используя его как спецификацию поведения, не
теряя функциональность в процессе.

### 3.3 Полное тестовое покрытие
Было 12 тестов (boot/security/health/websocket/dialer-regression). Добавлены
`tests/test_phone.py` (21 тест на `app/utils/phone.py` — нормализация,
валидация, форматирование российских номеров) и
`tests/test_model_validators.py` (26 тестов на `field_validator`/
`model_validator` в `UserCreateRequest`, `ContactCreateRequest`,
`BlacklistAddRequest` — чистая валидация Pydantic-схем, без БД/Redis).
Заодно найден и исправлен баг: `UserCreateRequest.validate_password_strength`
обещал в докстринге проверку "пароль не совпадает с username" через
`model_validator`, но такого валидатора нигде не было — пароль, равный
имени пользователя или содержащий его, проходил валидацию. Добавлен
недостающий `model_validator`.

Добавлены `tests/test_circuit_breaker.py` (10 тестов) и
`tests/test_rate_limiter.py` (12 тестов) — юнит-тесты на
`app/utils/circuit_breaker.py: CircuitBreaker` и
`app/utils/rate_limiter.py: TokenBucket`. Оба — чисто in-memory
asyncio-примитивы без БД/Redis, но это как раз та бизнес-критичная логика,
о которой просит эта секция: `CircuitBreaker` — единственная защита от
каскадных сбоев при обращении к AMI/БД/Redis по всему проекту, `TokenBucket`
— CPS-лимитер, которым буквально ограничивается скорость обзвона
(`CampaignService.dial_task()`, см. `docs/EVENTS_AND_FLOWS.md` §2). У обоих
до этого не было ни одного теста.

Заодно найден и исправлен реальный баг в `CircuitBreaker._record_success()`:
в состоянии CLOSED успешный вызов уменьшал поле `failure_count`, но не
убирал соответствующую запись из `_failure_timestamps` (внутреннего
скользящего окна, из которого `_record_failure()` всегда пересчитывает
`failure_count = len(_failure_timestamps)`). В результате "восстановление"
после успехов было косметическим: `get_status()`/`failure_count` могли
показывать 0 после нескольких успешных вызовов, но следующий же провал
пересчитывал `failure_count` из непочищенного списка и отбрасывал счётчик
сразу к прежнему (до "восстановления") значению — вплоть до немедленного
размыкания цепи там, где по показанному состоянию это выглядело бы
неожиданным. Исправлено: успех в CLOSED теперь убирает и запись из
`_failure_timestamps`, синхронизируя её с `failure_count`. Воспроизведено
и проверено до/после фикса (`CircuitBreaker(failure_threshold=5)`: 3
провала → `failure_count=3`; 3 успеха → `failure_count=0`,
`len(_failure_timestamps)` тоже 0 после фикса, было 3 до; следующий провал
→ `failure_count=1`, было 4). Регрессионный тест —
`test_recovery_after_successes_is_not_undone_by_next_failure`.

Добавлен `tests/test_blacklist_service.py` (15 тестов) — первый в проекте
пример юнит-тестов сервиса, которому для работы нужны БД/Redis, но здесь
оба замоканы (лёгкие `FakeConnection`/`FakePool`/`FakeRedis`, реализующие
только тот интерфейс, которым пользуется `BlacklistService`: `fetchrow/
fetchval/fetch/execute` и `add_to_blacklist/remove_from_blacklist/
is_blacklisted`) — так что тесты быстрые и не требуют инфраструктуры, но
проверяют реальную ветвление сервиса: невалидный номер, уже активная
запись, реактивация мягко удалённой, `check_phone` с коротким замыканием
на промахе Redis, парсинг command-тега `UPDATE N` в `cleanup_expired()`,
массовое добавление. Именно при написании этих тестов (сначала через
моки, потом — обязательной проверкой вживую против настоящего Postgres,
раз мок не проверяет реальные имена колонок) нашлись три бага, подробно
описанные в новой секции §3.0 выше: широко распространённый
`request.<enum>.value` при `use_enum_values=True` (задел 8 сервисов, не
только `blacklist`), `is_expired` вычислялся как `None` вместо `False`, и
`sql/schema.sql` для `blacklist` не совпадал с тем, что читает/пишет
`BlacklistService` (не хватало 10 колонок и 2 таблиц целиком) — все три
исправлены, покрыты регрессионными тестами и/или новой Alembic-миграцией
`0002_blacklist_schema_fix.py`.

Сейчас — 91 тест, из них 86 не требует БД/Redis и проходит в любом
окружении (было 76/71 до этого раунда).

Ещё нужны: unit-тесты бизнес-логики сервисов, которым для проверки
реально нужны БД/Redis (кампании, TTS/STT — по образцу
`tests/test_blacklist_service.py`), интеграционные тесты полного цикла
обзвона (mock AMI), E2E (Playwright по vanilla JS UI или будущему React),
нагрузочное тестирование (Locust/k6) на CPS/конкурентные звонки согласно
целям масштабирования из ТЗ (сотни одновременных звонков, сотни тысяч
номеров). Приоритетнее всего этого — §3.0: без живого прогона сервисов
против реальной БД (что и раскрыло все три бага выше) юнит-тесты на
моках дают ложное чувство полноты покрытия.

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

### 3.5 Kubernetes-манифесты — сделано (черновик, не проверено на кластере)
`k8s/` — Namespace, ConfigMap/Secret-шаблон (`02-secret.example.yaml`,
реальный `02-secret.yaml` — в `.gitignore`), StatefulSet для Postgres/Redis,
Deployment для Asterisk (`hostNetwork: true` — SIP/RTP не проходят через
обычный ClusterIP из-за диапазона UDP-портов 10000-10100, плюс отдельный
`Service` для AMI на порт 5038, чтобы backend доставал до него по
кластерному DNS, а не по IP узла), Deployment backend (readinessProbe на
`/api/health/ready`, livenessProbe на `/api/health/live`, init-контейнер
`alembic upgrade head`), Deployment nginx, PVC под `tts_audio`/
`call_recordings` (`ReadWriteMany` — том монтируют одновременно три
ворклоада, большинство StorageClass по умолчанию это не поддерживают).

Как и с Docker (см. §1.4), в среде этой сессии не было ни Kubernetes-
кластера, ни его эмуляции — манифесты валидированы только на синтаксис
YAML и сверены построчно с `docker-compose.yml`/`Dockerfile`/
`.env.example`, но ни разу не применялись `kubectl apply`. `k8s/README.md`
честно перечисляет, что нужно сделать перед реальным деплоем: собрать и
запушить три образа (ни один пока не существует ни в каком реестре), вшить
`frontend/dist` в образы на этапе сборки (в K8s нет host bind-mount, которым
пользуется `docker-compose.yml`), выбрать RWX-совместимый StorageClass,
закрепить под Asterisk конкретный узел.

### 3.6 SQLAlchemy ORM (если формально обязателен)
См. §2.2 — оценка объёма: ~15 сервисов, ~25 моделей, нужен параллельный
прогон (dual-write или staged migration) чтобы не потерять корректность
на боевых данных при переключении дозвонщика под нагрузкой.

### 3.7 Резервное копирование — сделано (bare-metal + Kubernetes; для docker-compose — вручную по образцу)
Реализовано для обоих путей развёртывания, упомянутых в ТЗ:

- **Bare-metal**: `scripts/15_backup_setup.sh` (по образцу существующих
  `scripts/07_postgresql_setup.sh`/`14_logrotate_setup.sh` — тот же стиль
  логирования, идемпотентности через маркер-файл, чтения `.env`)
  устанавливает `/usr/local/bin/autodialer-backup` (запускается по cron,
  расписание — `BACKUP_SCHEDULE` из `.env`, по умолчанию выключено —
  `AUTO_BACKUP_ENABLED=false`, эти переменные уже были в
  `.env.example`, но нигде не читались) и
  `/usr/local/bin/autodialer-restore <TIMESTAMP> [--yes]`.
  `autodialer-backup` делает `pg_dump -Fc` (custom-формат — нужен для
  `pg_restore --clean`), архивирует `tts_audio`/`call_recordings` через
  `tar` (пропускает, если каталог пуст/не существует), затем ротирует
  файлы бэкапов старше `BACKUP_RETENTION` дней (по умолчанию 30 —
  отдельная настройка от `settings.audio_retention_days`, та относится к
  самим аудиофайлам системы, не к их бэкапам). `autodialer-restore`
  восстанавливает БД и оба каталога из конкретного бэкапа, с
  подтверждением (`yes`/`no`, если не передан `--yes`), останавливая и
  перезапуская `autodialer.service` вокруг восстановления БД.

  **Проверено вживую в этой сессии** (в отличие от большей части
  Kubernetes/Docker-путей, см. §1.4): поднят нативный Postgres 16,
  выполнен `autodialer-backup`, затем данные в БД и оба каталога
  намеренно испорчены (удалена строка настройки, удалены файлы),
  `autodialer-restore <TS> --yes` восстановил всё побайтово (сверено
  напрямую через `psql`/`diff`-сравнение содержимого файлов). Отдельно
  проверена ротация: файл с `mtime` 40 дней назад корректно удалён при
  `BACKUP_RETENTION=30`, свежие — нет. Единственный найденный при
  тестировании нюанс (не баг, а ожидаемое поведение `tar x`): восстановление
  каталога не удаляет файлы, появившиеся в нём после бэкапа и отсутствующие
  в архиве — как `rsync` без `--delete`. Для `tts_audio`/`call_recordings`
  это не проблема (лишний файл не мешает), но стоит иметь в виду.

- **Kubernetes**: `k8s/50-backup-cronjob.yaml` — два `CronJob`
  (`media-backup` запускается на 15 минут позже `postgres-backup`, чтобы
  не претендовать одновременно на один и тот же PVC) пишут в отдельный
  `backup-storage` PVC (`ReadWriteOnce`) по той же логике, что и
  bare-metal скрипт (`pg_dump -Fc` + `tar` + ротация по `mtime`).
  Восстановление сознательно НЕ автоматизировано как `Job` — только
  задокументированная в комментариях файла процедура (`kubectl cp` +
  `pg_restore`/`tar x` через одноразовый под), по той же причине, что и
  `autodialer-restore` требует ручного подтверждения: восстановление —
  разрушительная операция, для которой автоматический безусловный запуск
  скорее опасен, чем полезен. Как и остальной `k8s/` (см. §3.5), **не
  применялось на реальном кластере** — только синтаксическая проверка
  YAML и extraction+`sh -n` проверка встроенных shell-команд. Честно
  задокументировано, что PVC-бэкап — это защита от случайного удаления/
  плохой миграции, а не полноценный disaster recovery (бэкап и данные на
  одном и том же storage backend); шаг с копированием вовне кластера
  (rclone/`aws s3 sync` и т.п.) не реализован.

- **docker-compose**: отдельного скрипта не заводилось — `docker-compose.yml`
  даёт прямой доступ к контейнеру Postgres, поэтому та же логика
  переносится однострочно: `docker compose exec -T postgres pg_dump -U
  $DB_USER -Fc $DB_NAME > backup.dump` из обычного cron на хосте (плюс
  `tar` volume-директорий `tts_audio`/`call_recordings`, которые в
  docker-compose и так смонтированы с хоста — см. `docker-compose.yml`).
  Не показалось оправданным дублировать почти идентичный скрипт в третий
  раз ради одного `docker compose exec` — `scripts/15_backup_setup.sh`
  можно использовать как образец логики ротации/восстановления один в
  один.

### 3.8 Стратегия масштабирования воркеров — аудит: заявленная проблема не подтвердилась
Воркеры (`start_all_workers()`) выполняются в том же процессе, что и API,
с leader election (`app/utils/leader_election.py`) для задач, которые не
должны дублироваться. Эта секция раньше утверждала, что `retry_queue`,
`transcription_queue` и `health_monitor` не leader-gated и потому будут
выполняться избыточно при горизонтальном масштабировании backend
(`replicas: 2+`). Аудит кода показал, что для всех трёх (и заодно
`metrics`) отсутствие leader election — не проблема, а корректный дизайн:

- `process_retry_queue` (`app/workers/retry.py`) забирает строки через
  `SELECT ... FOR UPDATE SKIP LOCKED` внутри транзакции — стандартный
  Postgres-паттерн безопасной конкурентной очереди: при N репликах каждая
  берёт непересекающееся подмножество строк, дублирования повторных
  звонков не происходит.
- Воркер `process_transcription_queue` из `worker_configs`
  (`app/workers/transcription_queue.py`) саму транскрибацию не делает —
  он раз в 5с проверяет размер очереди и пишет debug-лог. Реальная
  обработка — в `TranscriptionService._process_transcription_queue()`
  (`app/services/transcription.py`), которая читает задачи через
  `redis.blpop()` (атомарная операция — каждую задачу заберёт ровно один
  consumer), тоже безопасно при любом числе реплик.
- `health_monitor` и `update_metrics_periodically` не трогают разделяемое
  состояние — каждый отражает здоровье/метрики своего собственного
  процесса. Их не нужно (и не следует) leader-gate'ить: в
  Prometheus-модели каждая реплика обязана публиковать свои метрики
  независимо, иначе `/metrics` пустых реплик будет вводить в заблуждение.

Итого настоящих кандидатов на leader election изначально было верно
определено три: `cleanup_audio`, `log_cleanup`, `asterisk_reconciliation`
(синхронизация каналов с единственным инстансом Asterisk — гонка при
нескольких репликах) — все три уже leader-gated (`requires_leader=True`
в `worker_configs`, `app/workers/__init__.py`). Больше переносить нечего;
специального Worker-деплоймента или перехода на Celery для этого не
требуется.

Единственная реальная оговорка на будущее: если появится новая
периодическая задача с побочными эффектами на разделяемый ресурс (ещё
одна очередь без `SKIP LOCKED`/атомарного `BLPOP`), её надо либо сделать
leader-gated, либо явно спроектировать под конкурентных потребителей —
проверять это для каждой новой задачи отдельно, а не по умолчанию считать
дублирование воркеров проблемой.

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
