# WebSocket-события и диаграммы последовательности (ROADMAP.md §3.1)

Дополняет `docs/ER_DIAGRAM.md` (схема БД) и автосгенерированный `/docs`
(Swagger/OpenAPI — все REST-эндпоинты уже описаны там из коробки через
FastAPI, отдельно не дублируются здесь). Этот документ закрывает то, что
`/docs` не показывает: контракт WebSocket-событий в одном месте и как
реально выглядит поток исходящего/входящего звонка по коду, а не по ТЗ.

Построено чтением кода (`app/services/dialer.py`, `campaign.py`,
`incoming.py`, `websocket.py`, `app/api/websocket.py`,
`frontend/dist/js/system.js`), а не по памяти — там, где код и
предположение из ТЗ разошлись, ниже явно указано.

---

## 1. WebSocket-события

### 1.1 Подключение

Единственный эндпоинт: `WS /api/ws/dashboard?token=<JWT>` (`app/api/websocket.py`).

- Токен передаётся query-параметром, а не заголовком `Authorization` —
  браузерный WebSocket API не даёт установить произвольные заголовки при
  хендшейке.
- Невалидный/отсутствующий токен **не отклоняет соединение** — оно
  принимается в анонимном режиме (`user_id=None`) и получает все
  публичные события (`call`/`campaign`/`system`), кроме персональных
  `notification`, адресованных конкретному `user_id`
  (`WebSocketService.send_personal()`).
- Сразу после подключения сервер сам отправляет один снимок статуса:
  `{"type": "system", "data": <HealthCheckResponse-подобный статус>}` —
  чтобы дашборд не ждал следующего события, если система давно не меняла
  состояние.
- После этого клиент только держит соединение (`websocket.receive_text()`
  в цикле); вся полезная нагрузка идёт от сервера. Ping/pong клиента не
  обрабатывается предметно, только не даёт таймаута транспорта.

### 1.2 Общий конверт

Все сообщения — единый JSON-конверт:

```json
{"type": "call" | "campaign" | "system" | "notification", "data": {...}}
```

`data` — сериализованная (`model_dump(mode="json")` или dict вручную)
Pydantic-модель из `app/models/system.py`, кроме `notification`, у
которой ad-hoc словарь (см. ниже).

### 1.3 Транспорт: Redis Pub/Sub, не прямая рассылка

Приложение может работать в нескольких процессах (несколько
gunicorn/uvicorn воркеров) — WebSocket-соединение живёт только в одном
процессе, но событие может родиться в другом (дозвонщик, фоновый воркер).
Поэтому публикация всегда идёт в два шага:

1. Источник события (`DialerManager`, `CampaignService`,
   `NotificationService`) публикует JSON в канал Redis
   `REDIS_KEYS.WS_CHANNELS:<call|campaign|system|notification>`.
2. Каждый процесс с активным `WebSocketService` подписан на все 4 канала
   (`WebSocketService.start()`) и при получении сообщения рассылает его
   всем **своим локальным** соединениям (`_broadcast_local`).

Значит любое из событий ниже долетит до дашборда независимо от того, в
каком процессе/воркере оно было сгенерировано.

### 1.4 Справочник событий

| `type` | Модель (`app/models/system.py`) | Кто публикует | Когда |
|---|---|---|---|
| `call` | `LiveCallEvent` | `DialerManager._publish_call_event()` (`dialer.py`) | На каждое AMI-событие звонка — `dial_begin` (Originate прошёл), `answer` (BridgeEnter), `hangup`, `dtmf` |
| `campaign` | `CampaignProgressEvent` | `CampaignService._publish_campaign_event()` (`campaign.py`) | Раз в 5 обработанных контактов внутри `dial_task()`, плюс всегда при завершении/остановке/ошибке кампании |
| `system` | `SystemNotificationEvent` | `DialerManager._publish_system_event()` (`dialer.py`) | Подключение/потеря AMI (`ensure_connected()`/`health_check()`); также разово при первом подключении клиента сервер шлёт снимок статуса напрямую, не через этот канал |
| `notification` | ad-hoc `{id, user_id, type, title, message}` | `NotificationService.create()` (`notification.py`) | При создании персонального уведомления пользователю; в `WebSocketService.send_personal()` фильтруется по `user_id` **только в рамках текущего процесса** — см. оговорку ниже |

**`event` внутри `LiveCallEvent`** (поле `event`, не путать с `type`
конверта): `dial_begin` | `answer` | `hangup` | `dtmf`. Общие поля —
`unique_id`, `linked_id`, `campaign_id`, `phone`, `status` (причина
hangup), `dtmf` (нажатая цифра), `duration` (только на `hangup`, если
звонок был отвечен).

### 1.5 Как это использует фронтенд

`frontend/dist/js/system.js: handleWebSocketMessage()` — единственная
точка входа, диспетчеризует по `data.type`:

- `call` → `handleCallEvent()` — обновляет счётчик активных звонков/список
  живых звонков на дашборде.
- `system` → обновляет индикатор статуса AMI/SIP.
- `notification` → `App.showToast(data.data.message, 'info')`, если
  `data.data.message` присутствует.
- `campaign` → делегируется в `App.campaigns.handleCampaignEvent()`
  (`campaigns.js`): точечно обновляет строку таблицы кампаний, и если
  открыта модалка деталей именно этой кампании — перезапрашивает её через
  REST (`CampaignProgressEvent` не несёт полной статистики
  busy/noanswer/failed, только то, что нужно для строки таблицы).

### 1.6 Известная оговорка: `notification` и несколько процессов

`send_personal()` фильтрует локальные соединения по `user_id`, но
рассылка всё равно проходит через Redis Pub/Sub-подписку каждого
процесса на канал `...:notification` → в проде с несколькими
gunicorn/uvicorn воркерами **каждый** процесс получит сообщение из Redis
и попытается разослать его своим локальным соединениям; фактически до
пользователя долетит одна копия — та, что от процесса, где реально живёт
его WebSocket-соединение, — но остальные процессы тоже потратят цикл на
JSON-парсинг и пустой перебор `_connection_users`. Не баг (результат
корректный, лишняя работа — O(число процессов) на уведомление, не
O(число пользователей)), но стоит знать при отладке нагрузки на
`notification`-канал в многопроцессном деплое.

---

## 2. Диаграмма: исходящий звонок (кампания)

```mermaid
sequenceDiagram
    participant API as REST API (campaigns.py)
    participant Camp as CampaignService.dial_task()
    participant Dialer as DialerManager
    participant Q as Redis: dial_queue
    participant AMI as Asterisk AMI
    participant Ast as Asterisk dialplan [dialer_bridge]
    participant WS as WebSocketService (Redis Pub/Sub)
    participant FE as Дашборд (браузер)

    API->>Camp: POST /campaigns/{id}/start
    activate Camp
    loop для каждого контакта (ограничено CPS через TokenBucket)
        Camp->>Dialer: start_call(phone, campaign_id, retry)
        Dialer->>Q: RPUSH dial_queue {phone, campaign_id, retry}
        Note over Camp,Q: start_call() только ставит в очередь,<br/>самую Originate делает queue_worker()
    end

    par Фоновый обработчик очереди (queue_worker, отдельная задача)
        Q-->>Dialer: BLPOP dial_queue
        Dialer->>Dialer: _start_call(): blacklist, degraded mode,<br/>лимит каналов, CPS-лимитер, Lua-резервирование слота
        alt слот получен
            Dialer->>AMI: Originate(Local/{phone}@dialer_bridge, Setvar=CAMPAIGN_ID/RETRY_COUNT)
            AMI->>Ast: заходит в контекст dialer_bridge
            Ast-->>AMI: DialBegin
            AMI-->>Dialer: событие DialBegin
            Dialer->>WS: publish("call", {event:"dial_begin", ...})
            WS-->>FE: {"type":"call","data":{"event":"dial_begin",...}}

            alt абонент ответил
                Ast-->>AMI: BridgeEnter
                AMI-->>Dialer: событие BridgeEnter
                Dialer->>WS: publish("call", {event:"answer", ...})
                WS-->>FE: {"type":"call","data":{"event":"answer",...}}
                opt DTMF во время разговора
                    Ast-->>AMI: DTMF
                    AMI-->>Dialer: событие DTMF
                    Dialer->>WS: publish("call", {event:"dtmf", ...})
                    WS-->>FE: {"type":"call","data":{"event":"dtmf",...}}
                end
            end

            Ast-->>AMI: Hangup (cause)
            AMI-->>Dialer: событие Hangup
            Dialer->>Dialer: _save_call_result() → call_results
            alt статус busy/noanswer/failed и есть попытки в лимите
                Dialer->>Dialer: _schedule_retry() → campaign_contacts.next_retry_at
                Note over Dialer: подхватит retry_queue-воркер,<br/>см. диаграмму ниже
            end
            Dialer->>WS: publish("call", {event:"hangup", duration, ...})
            WS-->>FE: {"type":"call","data":{"event":"hangup",...}}
        else слот не получен (лимит/CPS/дубликат номера)
            Dialer->>Q: requeue (RPUSH обратно)
        end
    and Каждые 5 обработанных контактов
        Camp->>Camp: _publish_campaign_event(campaign_id)
        Camp->>WS: publish("campaign", CampaignProgressEvent)
        WS-->>FE: {"type":"campaign","data":{...}}
    end

    Camp->>Camp: все контакты обработаны → status=completed
    Camp->>WS: publish("campaign", CampaignProgressEvent) (финальный)
    WS-->>FE: {"type":"campaign","data":{...,"status":"completed"}}
    deactivate Camp
```

**Важные детали, которые легко упустить при беглом чтении ТЗ:**

- `start_call()` не звонит напрямую — это постановка в Redis-очередь
  `dial_queue`; реальный `Originate` делает отдельная фоновая задача
  `queue_worker()`. Это разделение даёт возможность троттлить исходящие
  вызовы (CPS-лимитер, лимит каналов) независимо от скорости, с которой
  `dial_task()` перебирает контакты кампании.
- Резервирование слота в `active_channels` — атомарный Lua-скрипт в
  Redis (`RESERVE_WITH_RESERVATION_LUA`), не read-then-write — иначе два
  параллельных вызова `_start_call()` могли бы одновременно пройти
  проверку лимита и превысить `max_calls`.
- `retry_queue`-воркер (см. §3.8 ROADMAP.md) не участвует в этой
  диаграмме напрямую — он отдельно, раз в 10с, вычитывает
  `campaign_contacts` с истёкшим `next_retry_at` через
  `FOR UPDATE SKIP LOCKED` и заново вызывает `dialer_service.start_call()`
  — с точки зрения диаграммы выше это просто ещё один источник, кладущий
  задачу в тот же `dial_queue`.

---

## 3. Диаграмма: входящий звонок

```mermaid
sequenceDiagram
    participant Caller as Абонент
    participant FreePBX as FreePBX (внешняя АТС клиента)
    participant API as POST /api/incoming/webhook
    participant Svc as IncomingCallService
    participant DB as Postgres: incoming_calls
    participant TS as TranscriptionService
    participant WS as WebSocketService

    Caller->>FreePBX: входящий звонок на DID
    Note over FreePBX: Запись разговора (recording) —<br/>настраивается на стороне FreePBX,<br/>это НЕ наш asterisk/extensions.conf
    FreePBX->>API: POST /webhook {caller_number, recording_path, duration, unique_id, ...}
    Note over FreePBX,API: ⚠️ Ничего в этом репозитории не настраивает<br/>сам вызов webhook — см. оговорку ниже
    API->>Svc: process_webhook(request)
    Svc->>Svc: normalize_phone(caller_number)
    Svc->>DB: SELECT ... WHERE unique_id = $1
    alt уже обработан (повторный webhook с тем же unique_id)
        Svc-->>API: {success, call_id, transcription_queued: false}
    else новый звонок
        Svc->>DB: INSERT INTO incoming_calls (...)
        Svc->>DB: найти/создать contacts по номеру
        Svc->>DB: INSERT audit_log('incoming_call_received')
        opt auto_transcribe = true (по умолчанию)
            Svc->>TS: _transcribe_call() в фоне (BackgroundTasks/asyncio.create_task)
            TS-->>DB: UPDATE incoming_calls SET transcription_status, transcript_text
        end
        Svc-->>API: {success, call_id, transcription_queued: true}
    end
```

**Важная находка при построении этой диаграммы (не задокументирована
нигде раньше):** в `asterisk/extensions.conf` этого репозитория **нет**
контекста, который принимает входящий звонок, пишет запись и сам дёргает
`POST /api/incoming/webhook` — там есть только `[sub-record]` (используется
для записи **исходящих** дозвонных звонков через `Gosub` из
`dialer_bridge`) и `[default]`/`[test]`. Это согласуется с архитектурой
из §2.4 ROADMAP.md: **наш** Asterisk — только для AMI/исходящего обзвона
и регистрируется SIP-клиентом на внешней FreePBX; входящие звонки
физически принимает FreePBX клиента, не этот Asterisk. Значит вызов
`/api/incoming/webhook` после записи звонка должен быть настроен
**на стороне FreePBX** (например, dialplan-макрос с `curl`/AGI-скриптом
после `Record()`/`MixMonitor()`) — это конфигурация внешней системы,
которой в этом репозитории нет и не может быть, но которую нужно явно
прописать в процессе внедрения у клиента. Сам эндпоинт и вся обработка
на стороне backend — рабочие и покрыты интеграционным путём (см.
`app/api/incoming.py`, `IncomingCallWebhookRequest`), просто ничего его
не вызывает автоматически без этой внешней настройки.

---

## 4. Диаграмма: очередь повторных звонков (retry)

```mermaid
sequenceDiagram
    participant Worker as retry_queue worker (каждые 10с)
    participant DB as Postgres: campaign_contacts
    participant Dialer as DialerManager.start_call()
    participant Q as Redis: dial_queue

    loop каждые 10 секунд (app/workers/retry.py)
        Worker->>DB: SELECT ... WHERE next_retry_at <= NOW() AND status='pending'<br/>FOR UPDATE SKIP LOCKED LIMIT 50
        Note over Worker,DB: SKIP LOCKED — безопасно при N репликах backend<br/>(см. ROADMAP.md §3.8), каждая берёт непересекающееся<br/>подмножество строк
        Worker->>DB: UPDATE campaign_contacts SET next_retry_at = NULL
        loop для каждой выбранной строки
            Worker->>Dialer: start_call(phone, campaign_id, retry_count)
            Dialer->>Q: RPUSH dial_queue (см. диаграмму §2)
        end
    end
```

`next_retry_at` выставляется в `DialerManager._schedule_retry()` (см.
диаграмму §2, ветка `hangup`) на основе причины: `busy` (до 2 попыток,
задержка `RETRY_BUSY_DELAY`), `noanswer` (до 3, `RETRY_NOANSWER_DELAY`),
`failed`/`timeout` (до 1, `RETRY_FAILED_DELAY`/60с) — с джиттером
(`random.expovariate`), чтобы повторные попытки по многим номерам не
били одним залпом в одну секунду.
