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
CALLER_ID="${CALLER_ID:-AutoDialer}"

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
same => n,Set(CAMPAIGN_ID=\${CAMPAIGN_ID})
same => n,Set(RETRY_COUNT=\${RETRY_COUNT})
same => n,Set(CALLERID(num)=\${CALLER_ID})
same => n,Set(CALLERID(name)=Camp_\${CAMPAIGN_ID})
same => n,Set(CHANNEL(hangup_handler_push)=hangup-handler,s,1)
same => n,Set(CDR(userfield)=campaign:\${CAMPAIGN_ID})
; __-префикс обязателен: [sub-media] выполняется на канале, который
; создаёт Dial() (через опцию U()), а не на этом - обычная (без __)
; переменная на этот новый канал не наследуется, и \${ORIGINAL_PHONE}
; во всех UserEvent(DialerResult,...) ниже был бы всегда пуст.
same => n,Set(__ORIGINAL_PHONE=\${EXTEN})
same => n,Dial(PJSIP/\${EXTEN}@\${TRUNK_NAME},\${CALL_TIMEOUT},U(sub-media^\${CAMPAIGN_ID}))
same => n,Goto(sub-dial-status,s,1)


; =============================================
; Обработчик статусов звонка
; Вызывается после Dial()
; =============================================
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
same => n,Return()

; Ветка "Нет ответа"
same => n(noanswer),NoOp(=== Результат: NOANSWER (Нет ответа) ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},status=noanswer)
same => n,UserEvent(DialerResult,Status: noanswer,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)})
same => n,Return()

; Ветка "Ошибка"
same => n(failed),NoOp(=== Результат: FAILED (\${DIALSTATUS}) ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},status=failed)
same => n,UserEvent(DialerResult,Status: failed,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},RetryCount: \${RETRY_COUNT},LinkedID: \${CHANNEL(linkedid)})
same => n,Return()

; Ветка "Ответил" (обрабатывается в sub-media)
same => n(answered),NoOp(=== Абонент ответил, обработка в sub-media ===)
same => n,Return()


; =============================================
; IVR - воспроизведение медиа и обработка DTMF
; Вызывается при ответе абонента
; =============================================
[sub-media]
exten => s,1,NoOp(=== Ответ абонента - Кампания \${ARG1} ===)
same => n,Set(CAMPAIGN_ID=\${ARG1})
same => n,Set(AUDIO_FILE=tts/main_\${CAMPAIGN_ID})

; Проверка наличия кастомного аудио, иначе используется default
same => n,GotoIf(\$[\${STAT(e,\${AUDIO_FILE})} = 1]?play)
same => n,Set(AUDIO_FILE=tts/default)
same => n(play),NoOp(=== Воспроизведение: \${AUDIO_FILE} ===)

; Ответ и воспроизведение
same => n,Progress()
same => n,Wait(0.3)
same => n,Answer()
same => n,Wait(0.2)

; AMD должен отработать (и дослушать) ДО того, как начнём проигрывать
; своё TTS - он различает живого человека и автоответчика по тому, что
; говорит ДАЛЬНЯЯ сторона первой, а наш же Background() заглушил бы это,
; если бы шёл одновременно. [sub-amd] сам публикует
; UserEvent(DialerResult,Status: machine,...) при вердикте MACHINE, так
; что результат уже записан к моменту возврата сюда - остаётся только
; прервать IVR и положить трубку, а не тратить питч на автоответчик.
same => n,Gosub(sub-amd,s,1)
same => n,GotoIf(\$["\${AMDSTATUS}"="MACHINE"]?amd_hangup)

same => n,Set(TIMEOUT(digit)=\${DTMF_TIMEOUT})
same => n,Set(TIMEOUT(response)=\${DTMF_TIMEOUT})
same => n,Background(\${AUDIO_FILE})
same => n,WaitExten(\${DTMF_TIMEOUT})

same => n(amd_hangup),NoOp(=== Автоответчик - питч пропущен, кладём трубку ===)
same => n,Hangup()


; =============================================
; Обработчики DTMF
; =============================================

; DTMF 1 - Согласие
exten => 1,1,NoOp(=== DTMF 1: Согласие ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=1)
same => n,UserEvent(DialerResult,Status: agreed,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 1,LinkedID: \${CHANNEL(linkedid)})
same => n,Playback(tts/thanks_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,tts/thanks_\${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/thanks_default)
same => n(hangup),Hangup()

; DTMF 2 - Отказ
exten => 2,1,NoOp(=== DTMF 2: Отказ ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=2)
same => n,UserEvent(DialerResult,Status: declined,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 2,LinkedID: \${CHANNEL(linkedid)})
same => n,Playback(tts/goodbye_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,tts/goodbye_\${CAMPAIGN_ID})} = 1]?hangup)
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
same => n,UserEvent(DialerResult,Status: operator,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 4,LinkedID: \${CHANNEL(linkedid)})
same => n,Playback(tts/operator_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,tts/operator_\${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/operator_default)
same => n(hangup),Hangup()

; DTMF 5-9, 0, *, # - Пользовательские действия
exten => 5,1,NoOp(=== DTMF 5: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom5,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 5,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => 6,1,NoOp(=== DTMF 6: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom6,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 6,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => 7,1,NoOp(=== DTMF 7: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom7,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 7,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => 8,1,NoOp(=== DTMF 8: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom8,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 8,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => 9,1,NoOp(=== DTMF 9: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom9,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 9,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => 0,1,NoOp(=== DTMF 0: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: custom0,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: 0,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => *,1,NoOp(=== DTMF *: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: star,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: *,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

exten => #,1,NoOp(=== DTMF #: Пользовательское ===)
same => n,UserEvent(DialerResult,Status: hash,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: #,LinkedID: \${CHANNEL(linkedid)})
same => n,Hangup()

; Таймаут - DTMF не получен
exten => t,1,NoOp(=== Таймаут DTMF ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=timeout)
same => n,UserEvent(DialerResult,Status: timeout,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},LinkedID: \${CHANNEL(linkedid)})
same => n,Playback(tts/timeout_\${CAMPAIGN_ID})
same => n,GotoIf(\$[\${STAT(e,tts/timeout_\${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/timeout_default)
same => n(hangup),Hangup()

; Неверный ввод
exten => i,1,NoOp(=== Неверный DTMF: \${INVALID_EXTEN} ===)
same => n,Set(CDR(userfield)=\${CDR(userfield)},dtmf=invalid)
same => n,UserEvent(DialerResult,Status: invalid_dtmf,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},DTMF: \${INVALID_EXTEN},LinkedID: \${CHANNEL(linkedid)})
same => n,Playback(invalid)
same => n,Background(\${AUDIO_FILE})
same => n,WaitExten(\${DTMF_TIMEOUT})


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
same => n,Return()


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
same => n,UserEvent(DialerResult,Status: machine,Campaign: \${CAMPAIGN_ID},Phone: \${ORIGINAL_PHONE},LinkedID: \${CHANNEL(linkedid)})
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
