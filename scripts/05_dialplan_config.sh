#!/bin/bash
# =============================================
# AutoDialer Ultimate - Dialplan Configuration
# Version: 3.0.0
# =============================================

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[STEP]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${CYAN}[SUCCESS]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Configure Dialplan
# =============================================
print_step "Configuring Asterisk dialplan..."

cat > /etc/asterisk/extensions.conf << 'EOF'
; =============================================
; AutoDialer Ultimate - Dialplan Configuration
; Version: 3.0.0
; =============================================

[globals]
TRUNK_NAME = PJSIP/291_endpoint
CALLER_ID = AutoDialer
MAX_RETRIES = 3
CALL_TIMEOUT = 30
DTMF_TIMEOUT = 10


; =============================================
; Dialer Bridge Context
; Entry point for all outbound calls
; Called via: Local/<number>@dialer_bridge/n
; =============================================
[dialer_bridge]
exten => _X.,1,NoOp(=== AutoDialer Bridge: Calling ${EXTEN} ===)
same => n,Set(CAMPAIGN_ID=${CAMPAIGN_ID})
same => n,Set(RETRY_COUNT=${RETRY_COUNT})
same => n,Set(CALLERID(num)=${CALLER_ID})
same => n,Set(CALLERID(name)=Camp_${CAMPAIGN_ID})
same => n,Set(CHANNEL(hangup_handler_push)=hangup-handler,s,1)
same => n,Set(CDR(userfield)=campaign:${CAMPAIGN_ID})
same => n,Set(ORIGINAL_PHONE=${EXTEN})
same => n,Dial(${TRUNK_NAME}/${EXTEN},${CALL_TIMEOUT},U(sub-media^${CAMPAIGN_ID}))
same => n,Goto(sub-dial-status,s,1)


; =============================================
; Dial Status Handler
; Processes call outcomes after Dial()
; =============================================
[sub-dial-status]
exten => s,1,NoOp(=== Dial Status: ${DIALSTATUS} ===)
same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)
same => n,GotoIf($["${DIALSTATUS}"="NOANSWER"]?noanswer)
same => n,GotoIf($["${DIALSTATUS}"="CHANUNAVAIL"]?failed)
same => n,GotoIf($["${DIALSTATUS}"="CONGESTION"]?failed)
same => n,GotoIf($["${DIALSTATUS}"="CANCEL"]?failed)
same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?answered)
same => n,Hangup()

same => n(busy),NoOp(=== Call Result: BUSY ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},status=busy)
same => n,UserEvent(DialerResult,Status=busy,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},RetryCount=${RETRY_COUNT},LinkedID=${CHANNEL(linkedid)})
same => n,Return()

same => n(noanswer),NoOp(=== Call Result: NOANSWER ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},status=noanswer)
same => n,UserEvent(DialerResult,Status=noanswer,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},RetryCount=${RETRY_COUNT},LinkedID=${CHANNEL(linkedid)})
same => n,Return()

same => n(failed),NoOp(=== Call Result: FAILED (${DIALSTATUS}) ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},status=failed)
same => n,UserEvent(DialerResult,Status=failed,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},RetryCount=${RETRY_COUNT},LinkedID=${CHANNEL(linkedid)})
same => n,Return()

same => n(answered),NoOp(=== Call answered, handled by sub-media ===)
same => n,Return()


; =============================================
; Media Playback Subroutine (IVR)
; Called when call is answered
; =============================================
[sub-media]
exten => s,1,NoOp(=== Answer Detected - Campaign ${ARG1} ===)
same => n,Set(CAMPAIGN_ID=${ARG1})
same => n,Set(AUDIO_FILE=tts/main_${CAMPAIGN_ID})

; Check if custom audio exists, otherwise use default
same => n,GotoIf($[${STAT(e,${AUDIO_FILE})} = 1]?play)
same => n,Set(AUDIO_FILE=tts/default)
same => n(play),NoOp(=== Playing audio: ${AUDIO_FILE} ===)

; Answer and play
same => n,Progress()
same => n,Wait(0.3)
same => n,Answer()
same => n,Wait(0.2)
same => n,Set(TIMEOUT(digit)=${DTMF_TIMEOUT})
same => n,Set(TIMEOUT(response)=${DTMF_TIMEOUT})
same => n,Background(${AUDIO_FILE})
same => n,WaitExten(${DTMF_TIMEOUT})


; =============================================
; DTMF Handlers
; =============================================

; DTMF 1 - Agreed
exten => 1,1,NoOp(=== DTMF 1: Agreed ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},dtmf=1)
same => n,UserEvent(DialerResult,Status=agreed,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=1,LinkedID=${CHANNEL(linkedid)})
same => n,Playback(tts/thanks_${CAMPAIGN_ID})
same => n,GotoIf($[${STAT(e,tts/thanks_${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/thanks_default)
same => n(hangup),Hangup()

; DTMF 2 - Declined
exten => 2,1,NoOp(=== DTMF 2: Declined ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},dtmf=2)
same => n,UserEvent(DialerResult,Status=declined,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=2,LinkedID=${CHANNEL(linkedid)})
same => n,Playback(tts/goodbye_${CAMPAIGN_ID})
same => n,GotoIf($[${STAT(e,tts/goodbye_${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/goodbye_default)
same => n(hangup),Hangup()

; DTMF 3 - Repeat Message
exten => 3,1,NoOp(=== DTMF 3: Repeat ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},dtmf=3)
same => n,Background(${AUDIO_FILE})
same => n,WaitExten(${DTMF_TIMEOUT})

; DTMF 4 - Operator Request (optional)
exten => 4,1,NoOp(=== DTMF 4: Operator Request ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},dtmf=4)
same => n,UserEvent(DialerResult,Status=operator,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=4,LinkedID=${CHANNEL(linkedid)})
same => n,Playback(tts/operator_${CAMPAIGN_ID})
same => n,GotoIf($[${STAT(e,tts/operator_${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/operator_default)
same => n(hangup),Hangup()

; DTMF 5-9 - Custom actions
exten => 5,1,NoOp(=== DTMF 5: Custom ===)
same => n,UserEvent(DialerResult,Status=custom5,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=5,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => 6,1,NoOp(=== DTMF 6: Custom ===)
same => n,UserEvent(DialerResult,Status=custom6,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=6,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => 7,1,NoOp(=== DTMF 7: Custom ===)
same => n,UserEvent(DialerResult,Status=custom7,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=7,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => 8,1,NoOp(=== DTMF 8: Custom ===)
same => n,UserEvent(DialerResult,Status=custom8,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=8,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => 9,1,NoOp(=== DTMF 9: Custom ===)
same => n,UserEvent(DialerResult,Status=custom9,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=9,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => 0,1,NoOp(=== DTMF 0: Custom ===)
same => n,UserEvent(DialerResult,Status=custom0,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=0,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => *,1,NoOp(=== DTMF *: Custom ===)
same => n,UserEvent(DialerResult,Status=star,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=*,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

exten => #,1,NoOp(=== DTMF #: Custom ===)
same => n,UserEvent(DialerResult,Status=hash,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=#,LinkedID=${CHANNEL(linkedid)})
same => n,Hangup()

; Timeout - No DTMF received
exten => t,1,NoOp(=== DTMF Timeout ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},dtmf=timeout)
same => n,UserEvent(DialerResult,Status=timeout,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},LinkedID=${CHANNEL(linkedid)})
same => n,Playback(tts/timeout_${CAMPAIGN_ID})
same => n,GotoIf($[${STAT(e,tts/timeout_${CAMPAIGN_ID})} = 1]?hangup)
same => n,Playback(tts/timeout_default)
same => n(hangup),Hangup()

; Invalid - Invalid DTMF received
exten => i,1,NoOp(=== Invalid DTMF: ${INVALID_EXTEN} ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},dtmf=invalid)
same => n,UserEvent(DialerResult,Status=invalid_dtmf,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},DTMF=${INVALID_EXTEN},LinkedID=${CHANNEL(linkedid)})
same => n,Playback(invalid)
same => n,Background(${AUDIO_FILE})
same => n,WaitExten(${DTMF_TIMEOUT})


; =============================================
; Hangup Handler
; Called when channel hangs up
; =============================================
[hangup-handler]
exten => s,1,NoOp(=== Channel ${CHANNEL} hung up ===)
same => n,UserEvent(DialerHangup,Channel=${CHANNEL},LinkedID=${CHANNEL(linkedid)},Status=${DIALSTATUS},Duration=${CDR(duration)},BillSec=${CDR(billsec)})
same => n,Return()


; =============================================
; AMD - Answering Machine Detection (Optional)
; =============================================
[sub-amd]
exten => s,1,NoOp(=== AMD Detection ===)
same => n,AMD()
same => n,GotoIf($["${AMDSTATUS}"="MACHINE"]?machine)
same => n,GotoIf($["${AMDSTATUS}"="HUMAN"]?human)
same => n,GotoIf($["${AMDSTATUS}"="NOTSURE"]?human)
same => n,GotoIf($["${AMDSTATUS}"="HANGUP"]?hangup)
same => n,Return()

same => n(machine),NoOp(=== Answering Machine Detected ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},amd=machine)
same => n,UserEvent(DialerResult,Status=machine,Campaign=${CAMPAIGN_ID},Phone=${ORIGINAL_PHONE},LinkedID=${CHANNEL(linkedid)})
same => n,Return()

same => n(human),NoOp(=== Human Detected ===)
same => n,Set(CDR(userfield)=${CDR(userfield)},amd=human)
same => n,Return()

same => n(hangup),NoOp(=== Hangup during AMD ===)
same => n,Return()


; =============================================
; Call Recording (Optional)
; =============================================
[sub-record]
exten => s,1,NoOp(=== Starting Call Recording ===)
same => n,Set(FILENAME=${CAMPAIGN_ID}_${ORIGINAL_PHONE}_${STRFTIME(${EPOCH},,%Y%m%d_%H%M%S)})
same => n,MixMonitor(/var/spool/asterisk/monitor/${FILENAME}.wav,b)
same => n,Return()


; =============================================
; Test Extensions
; =============================================
[test]
exten => 100,1,Answer()
same => n,Echo()
same => n,Hangup()

exten => 101,1,Answer()
same => n,Playback(tts/main_1)
same => n,Hangup()

exten => 102,1,Answer()
same => n,Read(digit,beep,1,,3,5)
same => n,SayDigits(${digit})
same => n,Hangup()


; =============================================
; Default Context (Catch-all)
; =============================================
[default]
exten => _X.,1,NoOp(=== Unhandled call to ${EXTEN} ===)
same => n,Hangup()

exten => s,1,NoOp(=== Unhandled call ===)
same => n,Hangup()
EOF

print_success "Dialplan configuration created"

# =============================================
# Set Permissions
# =============================================
print_step "Setting permissions..."

chown asterisk:asterisk /etc/asterisk/extensions.conf
chmod 640 /etc/asterisk/extensions.conf

print_success "Permissions set"

# =============================================
# Reload Dialplan
# =============================================
print_step "Reloading dialplan..."

if systemctl is-active --quiet asterisk; then
    asterisk -rx "dialplan reload"
    print_success "Dialplan reloaded"
else
    print_warn "Asterisk is not running, start it to apply dialplan"
fi

# =============================================
# Verify Dialplan
# =============================================
print_step "Verifying dialplan..."

if [ -f /etc/asterisk/extensions.conf ]; then
    print_info "  ✓ extensions.conf exists"
    
    # Count contexts
    CONTEXTS=$(grep -c "^\[.*\]" /etc/asterisk/extensions.conf || true)
    print_info "  ✓ $CONTEXTS contexts found"
    
    # Check for required contexts
    REQUIRED_CONTEXTS=("dialer_bridge" "sub-dial-status" "sub-media" "hangup-handler" "sub-amd" "sub-record" "test" "default")
    for context in "${REQUIRED_CONTEXTS[@]}"; do
        if grep -q "^\[$context\]" /etc/asterisk/extensions.conf; then
            print_info "  ✓ Context [$context] found"
        else
            print_warn "  ✗ Context [$context] missing"
        fi
    done
else
    print_error "extensions.conf not found"
    exit 1
fi

# =============================================
# Show Dialplan Summary (if Asterisk is running)
# =============================================
if systemctl is-active --quiet asterisk; then
    print_step "Dialplan summary..."
    
    echo ""
    print_info "Available contexts:"
    asterisk -rx "dialplan show" 2>/dev/null | grep -E "^\[.*\]" | head -10 || true
    
    echo ""
    print_info "Dialer bridge context:"
    asterisk -rx "dialplan show dialer_bridge" 2>/dev/null | head -20 || true
fi

# =============================================
# Summary
# =============================================
print_success "Dialplan configuration completed!"
echo ""
print_info "Configuration Summary:"
echo "  Trunk: PJSIP/291_endpoint"
echo "  Call Timeout: 30 seconds"
echo "  DTMF Timeout: 10 seconds"
echo ""
print_info "Key Contexts:"
echo "  [dialer_bridge]   - Entry point for outbound calls"
echo "  [sub-dial-status] - Call outcome handler"
echo "  [sub-media]       - IVR and DTMF handling"
echo "  [hangup-handler]  - Hangup event handler"
echo "  [sub-amd]         - Answering machine detection"
echo "  [sub-record]      - Call recording"
echo "  [test]            - Test extensions (100, 101, 102)"
echo ""
print_info "DTMF Mapping:"
echo "  1 - Agreed"
echo "  2 - Declined"
echo "  3 - Repeat message"
echo "  4 - Operator request"
echo "  5-9, 0, *, # - Custom actions"
echo ""
print_info "Verification Commands:"
echo "  asterisk -rx 'dialplan show dialer_bridge'"
echo "  asterisk -rx 'dialplan show sub-media'"
echo "  asterisk -rx 'dialplan reload'"
echo ""
print_info "Test Calls:"
echo "  asterisk -rx 'channel originate Local/100@test application Echo'"
echo "  asterisk -rx 'channel originate Local/101@test application Wait 5'"
echo ""
