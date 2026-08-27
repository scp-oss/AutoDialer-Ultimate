#!/bin/bash
# =============================================
# AutoDialer Ultimate - Настройка диалплана (extensions.conf)
# Версия: 3.0.0
# =============================================

set -e

# =============================================
# Цвета для вывода в консоль
# =============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "\n${GREEN}[ШАГ]${NC} $1"; }
print_info() { echo -e "${BLUE}[ИНФО]${NC} $1"; }
print_success() { echo -e "${CYAN}[УСПЕХ]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[ВНИМАНИЕ]${NC} $1"; }
print_error() { echo -e "${RED}[ОШИБКА]${NC} $1"; }

# =============================================
# Определение директорий
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Загрузка конфигурации
# =============================================
print_step "Загрузка конфигурации..."

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
    print_success "Конфигурация загружена из .env"
else
    print_error "Файл .env не найден!"
    exit 1
fi

# =============================================
# Установка значений по умолчанию
# =============================================
FREEPBX_EXTENSION="${FREEPBX_EXTENSION:-291}"
CALL_TIMEOUT="${CALL_TIMEOUT:-30}"
DTMF_TIMEOUT="${DTMF_TIMEOUT:-10}"
MAX_RETRIES="${MAX_RETRIES:-3}"
# CALLERID(num) должен быть настоящим номером/добавочным - реальные
# операторские транки отклоняют вызов (CONGESTION) при невалидном Caller
# ID Number. Раньше дефолт был текстом "AutoDialer", из-за чего звонки на
# реальные мобильные через транк проваливались, а на внутренние номера
# (не проверяющие CID) - нет, что маскировало проблему. По умолчанию
# используем сам номер extension, под который регистрируется транк.
CALLER_ID="${CALLER_ID:-$FREEPBX_EXTENSION}"

print_info "Номер Extension:   $FREEPBX_EXTENSION"
print_info "Таймаут звонка:    $CALL_TIMEOUT сек"
print_info "Таймаут DTMF:      $DTMF_TIMEOUT сек"

# =============================================
# Создание диалплана (extensions.conf)
# =============================================
print_step "Создание диалплана extensions.conf..."

cat > /etc/asterisk/extensions.conf << EOF
; =============================================
; AutoDialer Ultimate - Диалплан
; Версия: 3.0.0
; Транк: PJSIP/${FREEPBX_EXTENSION}_endpoint
; =============================================

[globals]
; =============================================
; Глобальные переменные
; =============================================
; Без префикса "PJSIP/" - Dial() ниже собирает PJSIP/<номер>@<транк>
; (правильный синтаксис chan_pjsip); "PJSIP/<транк>/<номер>" - формат
; легаси chan_sip, который chan_pjsip не поддерживает и валит каждый
; исходящий звонок с "Could not create dialog to invalid URI" даже при
; полностью рабочей регистрации/AOR - подтверждено живьём.
TRUNK_NAME = ${FREEPBX_EXTENSION}_endpoint
CALLER_ID = ${CALLER_ID}
MAX_RETRIES = ${MAX_RETRIES}
CALL_TIMEOUT = ${CALL_TIMEOUT}
DTMF_TIMEOUT = ${DTMF_TIMEOUT}


; =============================================
; Контекст dialer_bridge - точка входа для всех звонков
; Вызывается через: Local/<номер>@dialer_bridge/n
; =============================================
[dialer_bridge]
exten => _X.,1,NoOp(=== AutoDialer: Вызов \${EXTEN} ===)
; Local/\${EXTEN}@dialer_bridge/n иногда запускает этот extension
; независимо на обеих половинах пары - подтверждено живьём (двойной
; звонок абоненту). linkedid общий у обеих половин, используем как ключ
; разовой блокировки в astdb (ключ намеренно НЕ снимается в
; [hangup-handler] - см. комментарий там).
;
; ПРОВЕРКА-ЗАТЕМ-ЗАПИСЬ (GotoIf(DB_EXISTS)+Set(DB(...)=1)) сама по себе не
; атомарна - обе половины Local-канала могут выполняться параллельно, и
; обе могут проверить DB_EXISTS ДО того, как любая успеет записать ключ -
; подтверждено живьём: два "Занято" почти одновременно на один номер при
; быстром отказе. LOCK()/UNLOCK() (func_lock) делает проверку+запись
; настоящей критической секцией.
same => n,Set(DIALER_LOCK_NAME=dialer_bridge_\${CHANNEL(linkedid)})
same => n,Set(DIALER_LOCK_OK=\${LOCK(\${DIALER_LOCK_NAME})})
same => n,GotoIf(\$[\${DB_EXISTS(dialer_bridge_lock/\${CHANNEL(linkedid)})}]?duplicate,1)
same => n,Set(DB(dialer_bridge_lock/\${CHANNEL(linkedid)})=1)
same => n,Set(DIALER_UNLOCK_OK=\${UNLOCK(\${DIALER_LOCK_NAME})})
same => n,Set(CAMPAIGN_ID=\${CAMPAIGN_ID})
same => n,Set(RETRY_COUNT=\${RETRY_COUNT})
; Из Originate 'Variable' (__DTMF_ENABLED=1/0) - пусто считаем "включено".
same => n,Set(DTMF_ENABLED=\${IF(\$["\${DTMF_ENABLED}"=""]?1:\${DTMF_ENABLED})})
same => n,Set(CALLERID(num)=\${CALLER_ID})
same => n,Set(CALLERID(name)=Camp_\${CAMPAIGN_ID})
same => n,Set(CHANNEL(hangup_handler_push)=hangup-handler,s,1)
same => n,Set(CDR(userfield)=campaign:\${CAMPAIGN_ID})
; __-префикс обязателен: [sub-media] выполняется на канале, который
; создаёт Dial() (через опцию U()), а не на этом - обычная (без __)
; переменная на этот новый канал не наследуется, и \${ORIGINAL_PHONE}
; во всех UserEvent(DialerResult,...) ниже был бы всегда пуст.
same => n,Set(__ORIGINAL_PHONE=\${EXTEN})
; Приложение хранит номера с кодом "7" (79991234567), но исходящий
; маршрут FreePBX ждёт домашний формат с "8" и отвечает "484 Address
; Incomplete" на любой номер с "7" - подтверждено живьём. Меняем только
; для этого исходящего плеча.
same => n,Set(DIAL_NUMBER=\${IF(\$["\${EXTEN:0:1}"="7"]?8\${EXTEN:1}:\${EXTEN})})
same => n,Dial(PJSIP/\${DIAL_NUMBER}@\${TRUNK_NAME},\${CALL_TIMEOUT},U(sub-media^\${CAMPAIGN_ID}^\${DTMF_ENABLED}))
same => n,Goto(sub-dial-status,s,1)

exten => duplicate,1,NoOp(=== Повторный запуск dialer_bridge для linkedid \${CHANNEL(linkedid)} - пропускаем ===)
same => n,Set(DIALER_UNLOCK_OK=\${UNLOCK(\${DIALER_LOCK_NAME})})
same => n,Hangup()


; =============================================
; Обработчик статусов звонка
; Вызывается после Dial()
; =============================================
; Вызывается через Goto(sub-dial-status,s,1), а не Gosub - обычный
; переход, без кадра стека Gosub. Return() на каждой ветке логировал
; "ERROR: Return without Gosub: stack is unallocated" на каждом звонке -
; подтверждено живьём. Hangup() корректен вместо этого: на
; busy/noanswer/failed абонент не ответил, а на "answered" sub-media уже
; сам завершил канал - повторный Hangup() на уже завершённом канале
; ничего не делает.
[sub-dial-status]
exten => s,1,NoOp(=== Статус набора: \${DIALSTATUS} ===)
same => n,GotoIf(\$["\${DIALSTATUS}"="BUSY"]?busy)
same => n,GotoIf(\$["\${DIALSTATUS}"="NOANSWER"]?noanswer)
same => n,GotoIf(\$["\${DIALSTATUS}"="CHANUNAVAIL"]?failed)
same => n,GotoIf(\$["\${DIALSTATUS}"="CONGESTION"]?failed)
same => n,GotoIf(\$["\${DIALSTATUS}"="CANCEL"]?failed)
same => n,GotoIf(\$["\${DIALSTATUS}"="ANSWER"]?answered)
same => n,Hangup()

; Ветка "Занято"
same => n(busy),NoOp(=== Результат: BUSY (Занято) ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},status=busy)
same => n,UserEvent(DialerResult,Status: busy,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

; Ветка "Нет ответа"
same => n(noanswer),NoOp(=== Результат: NOANSWER (Нет ответа) ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},status=noanswer)
same => n,UserEvent(DialerResult,Status: noanswer,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

; Ветка "Ошибка"
same => n(failed),NoOp(=== Результат: FAILED (\${DIALSTATUS}) ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},status=failed)
same => n,UserEvent(DialerResult,Status: failed,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

; Ветка "Ответил" (обрабатывается в sub-media)
same => n(answered),NoOp(=== Абонент ответил, обработка в sub-media ===)
same => n,Hangup()


; =============================================
; IVR - воспроизведение медиа и обработка DTMF
; Вызывается при ответе абонента
; =============================================
[sub-media]
exten => s,1,NoOp(=== Ответ абонента - Кампания \${ARG1} ===)
same => n,Set(CAMPAIGN_ID=\${ARG1})
; ARG2 = DTMF_ENABLED (1/0), пробрасывается из [dialer_bridge].
same => n,Set(DTMF_ENABLED=\${IF(\$["\${ARG2}"=""]?1:\${ARG2})})
same => n,Set(AUDIO_FILE=tts/main_\${CAMPAIGN_ID})

; Проверка наличия кастомного аудио, иначе используется default. STAT()
; делает буквальный stat() по указанной строке - не резолвит расширения
; и не ищет в каталоге sounds, как это делает Background() - нужен полный
; абсолютный путь С расширением, иначе всегда 0 даже при существующем файле.
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/\${AUDIO_FILE}.sln)} = 1]?play)
same => n,Set(AUDIO_FILE=tts/default)
same => n(play),NoOp(=== Воспроизведение: \${AUDIO_FILE} ===)

; Ответ и воспроизведение
same => n,Progress()
same => n,Wait(0.3)
same => n,Answer()
same => n,Wait(0.2)

; U(sub-media^...) выполняется на ВЫЗЫВАЕМОМ канале ДО того, как Dial()
; вообще мог бы сбриджить его с исходным Local-каналом, а каждая ветка
; ниже завершается Hangup() прямо внутри этого Gosub - реального бриджа
; никогда не происходит, поэтому AMI-событие BridgeEnter (единственное
; место, где раньше выставлялся ctx.answered_at в dialer.py) для этих
; звонков никогда не приходит. Подтверждено живьём: длительность 0:00 на
; каждом agreed/declined звонке с реальным разговором в несколько секунд.
; Вместо того чтобы полагаться на AMI-события, считаем длительность прямо
; в диалплане (эта строка выполняется уже после реального Answer()) и
; передаём её в Python прямо в каждом UserEvent(DialerResult,...) ниже.
same => n,Set(ANSWER_EPOCH=\${EPOCH})

; AMD должен отработать (и дослушать) ДО того, как начнём проигрывать
; своё TTS - он различает живого человека и автоответчика по тому, что
; говорит ДАЛЬНЯЯ сторона первой, а наш же Background() заглушил бы это,
; если бы шёл одновременно. Раньше при вердикте MACHINE звонок сразу
; вешался вместо проигрывания питча - но вердикт строится только на
; initialSilence (2500мс) молчания после ответа, и живой человек, который
; просто не сказал "Алло" сразу, неотличим на этом этапе от автоответчика
; - подтверждено живьём (взяли трубку, промолчали - звонок обрывался до
; проигрывания сообщения). Раз звонок всё равно отвечен - теперь всегда
; проигрываем питч; AMDSTATUS по-прежнему пишется в CDR(userfield) внутри
; sub-amd для статистики, но больше не завершает звонок раньше времени.
same => n,Gosub(sub-amd,s,1)

same => n,Set(TIMEOUT(digit)=\${DTMF_TIMEOUT})
same => n,Set(TIMEOUT(response)=\${DTMF_TIMEOUT})
same => n,Background(\${AUDIO_FILE})

; DTMF-меню можно отключить на кампанию целиком - "чистое объявление".
same => n,GotoIf(\$["\${DTMF_ENABLED}"="0"]?announce_only)

; После питча кампании нужно явно объявить "нажмите 1/2/4" - раньше
; ожидалось, что эта фраза есть в самом тексте питча, но абонент, не
; услышав её, просто не понимал, что от него ждут.
; dialer.menu_prompt_audio_id (вкладка "Настройки") даёт выбрать свою
; формулировку из библиотеки аудио - симлинкается под tts/menu_prompt.sln.
; Не выбрано - используем tts/default.sln, у него уже есть подходящий
; текст ("Пожалуйста, нажмите 1 для подтверждения или 2 для отказа") и
; он гарантированно есть на любой установке.
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/tts/menu_prompt.sln)} = 1]?menu_custom)
same => n,Background(tts/default)
same => n,Goto(menu_done)
same => n(menu_custom),Background(tts/menu_prompt)
same => n(menu_done),WaitExten(\${DTMF_TIMEOUT})
same => n,Goto(s,announce_only)

same => n(announce_only),NoOp(=== DTMF отключен для кампании \${CAMPAIGN_ID} - чистое объявление ===)
same => n,UserEvent(DialerResult,Status: announced,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()


; =============================================
; Обработчики DTMF
; =============================================

; DTMF 1 - Согласие
exten => 1,1,NoOp(=== DTMF 1: Согласие ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=1)
same => n,UserEvent(DialerResult,Status: agreed,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 1,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Playback(tts/thanks_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/tts/thanks_\${CAMPAIGN_ID}.sln)} = 1]?hangup)
same => n,Playback(tts/thanks_default)
same => n(hangup),Hangup()

; DTMF 2 - Отказ
exten => 2,1,NoOp(=== DTMF 2: Отказ ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=2)
same => n,UserEvent(DialerResult,Status: declined,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 2,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Playback(tts/goodbye_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/tts/goodbye_\${CAMPAIGN_ID}.sln)} = 1]?hangup)
same => n,Playback(tts/goodbye_default)
same => n(hangup),Hangup()

; DTMF 3 - Повторить сообщение
exten => 3,1,NoOp(=== DTMF 3: Повтор ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=3)
same => n,Background(\${AUDIO_FILE})
same => n,WaitExten(\${DTMF_TIMEOUT})

; DTMF 4 - Запрос оператора
exten => 4,1,NoOp(=== DTMF 4: Запрос оператора ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=4)
same => n,UserEvent(DialerResult,Status: operator,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 4,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Playback(tts/operator_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/tts/operator_\${CAMPAIGN_ID}.sln)} = 1]?hangup)
same => n,Playback(tts/operator_default)
same => n(hangup),Hangup()

; DTMF 5-9, 0, *, # - Пользовательские действия
exten => 5,1,NoOp(=== DTMF 5: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom5,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 5,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => 6,1,NoOp(=== DTMF 6: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom6,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 6,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => 7,1,NoOp(=== DTMF 7: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom7,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 7,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => 8,1,NoOp(=== DTMF 8: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom8,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 8,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => 9,1,NoOp(=== DTMF 9: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom9,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 9,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => 0,1,NoOp(=== DTMF 0: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom0,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 0,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => *,1,NoOp(=== DTMF *: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: star,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: *,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

exten => #,1,NoOp(=== DTMF #: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: hash,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: #,LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Hangup()

; Таймаут - DTMF не получен
exten => t,1,NoOp(=== Таймаут DTMF ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=timeout)
same => n,UserEvent(DialerResult,Status: timeout,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Playback(tts/timeout_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/tts/timeout_\${CAMPAIGN_ID}.sln)} = 1]?hangup)
same => n,Playback(tts/timeout_default)
same => n(hangup),Hangup()

; Неверный ввод
exten => i,1,NoOp(=== Неверный DTMF: \${INVALID_EXTEN} ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=invalid)
same => n,UserEvent(DialerResult,Status: invalid_dtmf,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: \${INVALID_EXTEN},LinkedID: \${CHANNEL(linkedid)},Duration: \$[\${EPOCH} - \${ANSWER_EPOCH}])
same => n,Playback(invalid)
same => n,Background(\${AUDIO_FILE})
same => n,WaitExten(\${DTMF_TIMEOUT})

; Абонент мог повесить трубку, не дожидаясь WaitExten и не нажав ничего -
; тогда ни один UserEvent(DialerResult,...) выше не выполняется вовсе.
; 'h' выполняется на ЛЮБОМ завершении этого канала (включая Hangup() из
; обработчиков выше - там уже дедуплицируется на стороне Python по
; linked_id, так что повторный вызов здесь безопасен).
exten => h,1,NoOp(=== Канал завершён без ввода DTMF - кампания \${CAMPAIGN_ID} ===)
same => n,UserEvent(DialerResult,Status: unknown,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)},Duration: \${IF(\$["\${ANSWER_EPOCH}"=""]?0:\$[\${EPOCH} - \${ANSWER_EPOCH}])})


; =============================================
; Обработчик завершения звонка
; =============================================
[hangup-handler]
exten => s,1,NoOp(=== Канал \${CHANNEL} завершён ===)
; Без своего "Channel:" - у любого AMI-события (включая UserEvent) уже
; есть нативный заголовок "Channel:", который Asterisk добавляет всегда.
; Дублирующий заголовок с тем же именем заставляет panoramisk хранить
; его как список из двух одинаковых значений вместо строки, и
; \`channel.startswith(...)\` на стороне приложения падает с
; AttributeError - подтверждено живьём на Docker-сборке того же дозвона.
same => n,UserEvent(DialerHangup,LinkedID: \${CHANNEL(linkedid)},Status: \${DIALSTATUS},Duration: \${CDR(duration)},BillSec: \${CDR(billsec)})
; НЕ снимаем блокировку от дубликатов dialer_bridge здесь - вторая
; половина Local-канала не гарантированно успевает дойти до своей проверки
; DB_EXISTS до этого момента (подтверждено живьём: она может начать
; исполнять [dialer_bridge] уже ПОСЛЕ того, как первая половина полностью
; завершила разговор), и удалённый здесь ключ давал ей "0" вместо "1" -
; вторая половина уходила в повторный настоящий Dial() на тот же номер.
; linkedid уникален для каждого звонка, так что оставлять ключ навсегда
; безопасно - только растущее число записей в astdb, что лучше, чем
; повторный дозвон.
same => n,Return()


; =============================================
; Контекст incoming - обработка настоящих входящих звонков
; (PJSIP endpoint context = incoming - см. 04_pjsip_config.sh)
; =============================================
[incoming]
; PJSIP передаёт сюда реально набранный номер/extension (например "291" -
; собственный номер AutoDialer на FreePBX) как EXTEN, а не "s" - "s"
; используется только когда канал не сообщает конкретный extension.
; Без этого паттерна реальный входящий звонок отклонялся с "extension not
; found in context 'incoming'" - подтверждено живьём. _X. матчит любой
; набранный номер и просто передаёт управление в общую логику ниже.
exten => _X.,1,Goto(s,1)
exten => s,1,NoOp(=== Входящий звонок с \${CALLERID(num)} ===)
; Явный Answer() - без него MixMonitor не получает надёжного
; двустороннего аудиопотока для записи - подтверждено живьём: все .wav
; получались ровно 44 байта (пустой RIFF-заголовок) независимо от
; реальной длительности звонка. [sub-media] (исходящие, выше) всегда
; делает Answer() первым делом - здесь этого не было.
same => n,Answer()
same => n,Set(CALLER_NUM=\${CALLERID(num)})
same => n,Set(FILENAME=incoming_\${STRFTIME(\${EPOCH},,%Y%m%d_%H%M%S)}_\${CALLERID(num)})
same => n,Set(REC_START=\${EPOCH})
; Регистрация звонка в бэкенде (StopMixMonitor + POST /webhook) вынесена в
; hangup handler, а не оставлена в линейном потоке ниже - большинство
; звонящих вешают трубку задолго до Wait(30), а выполнение диалплана на
; канале обрывается сразу на хендапе (никакого "h" extension здесь нет),
; так что StopMixMonitor()/дальнейшие строки после Wait() просто никогда бы
; не выполнились для типичного короткого звонка. hangup handler гарантированно
; исполняется при любом сценарии завершения - тот же приём, что уже
; используется в [dialer_bridge] (CHANNEL(hangup_handler_push)=hangup-handler).
same => n,Set(CHANNEL(hangup_handler_push)=incoming-hangup,s,1)

; Выбор приветствия: настраивается в веб-интерфейсе (Настройки -> Входящие).
; SettingsService._apply_incoming_greeting (app/services/settings.py)
; симлинкует выбранный файл под tts/incoming_custom.sln при каждом
; сохранении настройки - тот же приём, что campaign.py использует для
; tts/main_<id>.sln (см. [sub-media] выше).
same => n,Set(GREETING_FILE=tts/incoming_custom)
; STAT() делает буквальный stat() и не ищет расширения/форматы, как это
; делает Background() - без абсолютного пути и .sln проверка никогда не
; находила реально существующий файл (подтверждено живьём).
same => n,GotoIf(\$[\${STAT(e,/var/lib/asterisk/sounds/\${GREETING_FILE}.sln)} = 1]?play_greeting)
same => n,Goto(default_greeting)

same => n(play_greeting),Background(\${GREETING_FILE})
same => n,Goto(record)

same => n(default_greeting),Background(tts/incoming_welcome)

; Запись сообщения (StopMixMonitor - в hangup handler [incoming-hangup]
; ниже, см. комментарий у CHANNEL(hangup_handler_push) выше)
; Опция "b" ("только пока канал в мосте") здесь НЕ нужна - канал в этом
; контексте никогда никуда не мостится (нет Dial()/Bridge()), так что с
; "b" MixMonitor не писал ни байта звука - подтверждено живьём (все .wav
; ровно 44 байта, пустой RIFF-заголовок).
same => n(record),Playback(beep)
same => n,MixMonitor(/var/spool/asterisk/monitor/incoming/\${FILENAME}.wav)
same => n,Wait(30)  ; Максимальная длительность записи 30 секунд

; Прощальное сообщение
same => n,Background(tts/thank_you)
same => n,Wait(1)
same => n,Hangup()


; =============================================
; Hangup handler для [incoming] - гарантированно останавливает запись и
; регистрирует звонок в бэкенде (POST /api/incoming-calls/webhook,
; auto_transcribe=True по умолчанию запускает расшифровку) независимо от
; того, чем закончился звонок - без этого файл записи оставался бы только
; на диске, без строки в БД и без возможности прослушать/расшифровать его
; через веб-интерфейс.
; =============================================
[incoming-hangup]
exten => s,1,NoOp(=== Входящий звонок \${CHANNEL} завершён - фиксируем запись ===)
; Идемпотентно: если MixMonitor уже не запущен, StopMixMonitor() ничего не делает.
same => n,StopMixMonitor()
same => n,Set(REC_DURATION=\$[\${EPOCH}-\${REC_START}])
same => n,GotoIf(\$["\${FILENAME}"=""]?done)
same => n,System(curl -s --max-time 5 -X POST http://127.0.0.1:8000/api/incoming-calls/webhook -H "Content-Type: application/json" -d '{"caller_number":"\${CALLER_NUM}","recording_path":"/var/spool/asterisk/monitor/incoming/\${FILENAME}.wav","duration":\${REC_DURATION},"unique_id":"\${UNIQUEID}","linked_id":"\${CHANNEL(linkedid)}"}' &)
same => n(done),Return()


; =============================================
; AMD - Определение автоответчика (опционально)
; =============================================
[sub-amd]
exten => s,1,NoOp(=== Определение автоответчика ===)
same => n,AMD()
same => n,GotoIf(\$["\${AMDSTATUS}"="MACHINE"]?machine)
same => n,GotoIf(\$["\${AMDSTATUS}"="HUMAN"]?human)
same => n,GotoIf(\$["\${AMDSTATUS}"="NOTSURE"]?human)
same => n,GotoIf(\$["\${AMDSTATUS}"="HANGUP"]?hangup)
same => n,Return()

same => n(machine),NoOp(=== Обнаружен автоответчик ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},amd=machine)
; Без UserEvent(DialerResult,Status: machine,...) здесь - sub-media теперь
; всё равно проигрывает питч и ждёт DTMF при любом вердикте AMD, так что
; отправка результата "machine" сразу заблокировала бы реальный
; "agreed"/"declined" через Redis-дедупликацию в
; DialerManager._handle_user_event. AMDSTATUS остаётся в CDR(userfield)
; для аудита; итоговый DialerResult теперь всегда приходит из обработчиков
; DTMF или из ветки таймаута.
same => n,Return()

same => n(human),NoOp(=== Обнаружен человек ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},amd=human)
same => n,Return()

same => n(hangup),NoOp(=== Отбой во время AMD ===)
same => n,Return()


; =============================================
; Запись разговора (опционально)
; =============================================
[sub-record]
exten => s,1,NoOp(=== Запуск записи разговора ===)
same => n,Set(FILENAME=\${CAMPAIGN_ID}_\${ORIGINAL_PHONE}_\${STRFTIME(\${EPOCH},,%Y%m%d_%H%M%S)})
same => n,MixMonitor(/var/spool/asterisk/monitor/\${FILENAME}.wav,b)
same => n,Return()


; =============================================
; Тестовые номера
; =============================================
[test]
; Эхо-тест
exten => 100,1,Answer()
same => n,Echo()
same => n,Hangup()

; Проверка воспроизведения
exten => 101,1,Answer()
same => n,Playback(tts/main_1)
same => n,Hangup()

; Проверка DTMF
exten => 102,1,Answer()
same => n,Read(digit,beep,1,,3,5)
same => n,SayDigits(\${digit})
same => n,Hangup()


; =============================================
; Контекст по умолчанию (заглушка)
; =============================================
[default]
exten => _X.,1,NoOp(=== Необработанный вызов на \${EXTEN} ===)
same => n,Hangup()

exten => s,1,NoOp(=== Необработанный вызов ===)
same => n,Hangup()
EOF

print_success "Диалплан extensions.conf создан"

# =============================================
# Установка прав доступа
# =============================================
print_step "Установка прав доступа..."

chown asterisk:asterisk /etc/asterisk/extensions.conf
chmod 640 /etc/asterisk/extensions.conf

print_success "Права доступа установлены"

# =============================================
# Перезагрузка диалплана
# =============================================
print_step "Перезагрузка диалплана..."

if systemctl is-active --quiet asterisk; then
    asterisk -rx "dialplan reload"
    print_success "Диалплан перезагружен"
else
    print_warn "Asterisk не запущен, диалплан будет применён при запуске"
fi

# =============================================
# Проверка диалплана
# =============================================
print_step "Проверка диалплана..."

if [ -f /etc/asterisk/extensions.conf ]; then
    print_info "  ✓ extensions.conf создан"
    
    # Подсчёт контекстов
    CONTEXTS=$(grep -c "^\[.*\]" /etc/asterisk/extensions.conf || true)
    print_info "  ✓ Найдено $CONTEXTS контекстов"
    
    # Проверка обязательных контекстов
    REQUIRED_CONTEXTS=(
        "dialer_bridge"
        "sub-dial-status"
        "sub-media"
        "hangup-handler"
        "sub-amd"
        "sub-record"
        "test"
        "default"
    )
    
    print_info "Проверка обязательных контекстов:"
    for context in "${REQUIRED_CONTEXTS[@]}"; do
        if grep -q "^\[$context\]" /etc/asterisk/extensions.conf; then
            print_info "  ✓ [$context]"
        else
            print_warn "  ✗ [$context] отсутствует"
        fi
    done
else
    print_error "extensions.conf не найден!"
    exit 1
fi

# =============================================
# Показ сводки диалплана
# =============================================
if systemctl is-active --quiet asterisk; then
    print_step "Сводка диалплана..."
    
    echo ""
    print_info "Доступные контексты:"
    asterisk -rx "dialplan show" 2>/dev/null | grep -E "^\[.*\]" | head -10 || true
    
    echo ""
    print_info "Контекст dialer_bridge (первые 10 строк):"
    asterisk -rx "dialplan show dialer_bridge" 2>/dev/null | head -20 || true
fi

# =============================================
# Сводка
# =============================================
print_step "Сводка настройки диалплана"
echo ""
print_info "Параметры диалплана:"
echo "  Транк:            PJSIP/${FREEPBX_EXTENSION}_endpoint"
echo "  Таймаут звонка:   $CALL_TIMEOUT сек"
echo "  Таймаут DTMF:     $DTMF_TIMEOUT сек"
echo "  Caller ID:        $CALLER_ID"
echo ""
print_info "Основные контексты:"
echo "  [dialer_bridge]   - Точка входа для исходящих звонков"
echo "  [sub-dial-status] - Обработчик статусов звонка"
echo "  [sub-media]       - IVR и обработка DTMF"
echo "  [hangup-handler]  - Обработчик завершения звонка"
echo "  [sub-amd]         - Определение автоответчика"
echo "  [sub-record]      - Запись разговоров"
echo "  [test]            - Тестовые номера (100, 101, 102)"
echo ""
print_info "Назначение DTMF:"
echo "  1 - Согласие"
echo "  2 - Отказ"
echo "  3 - Повторить сообщение"
echo "  4 - Запрос оператора"
echo "  5-9,0,*,# - Пользовательские действия"
echo ""
print_info "Команды для проверки:"
echo "  asterisk -rx 'dialplan show dialer_bridge'"
echo "  asterisk -rx 'dialplan show sub-media'"
echo "  asterisk -rx 'dialplan reload'"
echo ""
print_info "Тестовые звонки:"
echo "  asterisk -rx 'channel originate Local/100@test application Echo'"
echo "  asterisk -rx 'channel originate Local/101@test application Wait 5'"
echo ""

print_success "Настройка диалплана завершена!"
