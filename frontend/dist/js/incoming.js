// incoming.js - Модуль управления входящими звонками

class IncomingCallManager {
    constructor() {
        this.incomingCall = null;
        this.ringtone = null;
        this.ringingTimeout = null;
        this.maxRingTime = 60000; // 60 секунд максимальное время звонка
        this.autoAnswerEnabled = false;
        this.autoAnswerDelay = 3000; // 3 секунды задержка автоответа
        this.autoAnswerTimer = null;
        this.callbacks = [];
        this.activeStream = null;
        this.sipSession = null;
        
        this.initializeRingtone();
        this.loadSettings();
    }

    // Инициализация рингтона
    initializeRingtone() {
        this.ringtone = new Audio('/assets/sounds/ringtone.mp3');
        this.ringtone.loop = true;
        this.ringtone.volume = 0.5;
    }

    // Загрузка настроек
    loadSettings() {
        const settings = JSON.parse(localStorage.getItem('incoming_settings') || '{}');
        this.autoAnswerEnabled = settings.autoAnswerEnabled || false;
        this.autoAnswerDelay = settings.autoAnswerDelay || 3000;
        this.maxRingTime = settings.maxRingTime || 60000;
        return settings;
    }

    // Сохранение настроек
    saveSettings(settings) {
        localStorage.setItem('incoming_settings', JSON.stringify(settings));
        this.loadSettings();
        this.notifySubscribers('settings_updated', settings);
    }

    // Обработка входящего звонка
    handleIncomingCall(session) {
        this.sipSession = session;
        
        const callerNumber = session.remote_identity.uri.user;
        const callerName = session.remote_identity.display_name || callerNumber;
        
        // Проверка черного списка
        if (window.blacklistManager && window.blacklistManager.isBlocked(callerNumber)) {
            this.rejectCall('blocked');
            this.logRejectedCall(callerNumber, 'blacklist');
            return;
        }

        // Поиск контакта
        const contact = window.contactsManager 
            ? window.contactsManager.findByPhone(callerNumber) 
            : null;

        // Создание объекта входящего звонка
        this.incomingCall = {
            id: this.generateCallId(),
            session: session,
            callerNumber: callerNumber,
            callerName: contact ? contact.name : callerName,
            contactId: contact ? contact.id : null,
            startTime: new Date().toISOString(),
            status: 'ringing',
            direction: 'incoming'
        };

        // Запуск рингтона
        this.startRinging();
        
        // Добавление в историю
        if (window.callHistory) {
            window.callHistory.addCallRecord({
                phoneNumber: callerNumber,
                contactName: this.incomingCall.callerName,
                startTime: this.incomingCall.startTime,
                status: 'ringing',
                direction: 'incoming',
                callType: 'incoming'
            });
        }

        // Показ уведомления
        this.showIncomingCallNotification();
        
        // Отображение модального окна входящего звонка
        this.showIncomingCallModal();
        
        // Установка таймаута на максимальное время звонка
        this.ringingTimeout = setTimeout(() => {
            if (this.incomingCall && this.incomingCall.status === 'ringing') {
                this.rejectCall('timeout');
            }
        }, this.maxRingTime);

        // Автоответ если включен
        if (this.autoAnswerEnabled) {
            this.autoAnswerTimer = setTimeout(() => {
                if (this.incomingCall && this.incomingCall.status === 'ringing') {
                    this.acceptCall();
                }
            }, this.autoAnswerDelay);
        }

        this.notifySubscribers('incoming_call', this.incomingCall);
    }

    // Запуск рингтона
    startRinging() {
        if (this.ringtone) {
            this.ringtone.play().catch(e => {
                console.warn('Не удалось воспроизвести рингтон:', e);
            });
        }
        
        // Вибрация если поддерживается
        if (navigator.vibrate) {
            navigator.vibrate([1000, 1000, 1000]);
        }
    }

    // Остановка рингтона
    stopRinging() {
        if (this.ringtone) {
            this.ringtone.pause();
            this.ringtone.currentTime = 0;
        }
        
        if (navigator.vibrate) {
            navigator.vibrate(0);
        }
        
        if (this.ringingTimeout) {
            clearTimeout(this.ringingTimeout);
            this.ringingTimeout = null;
        }
        
        if (this.autoAnswerTimer) {
            clearTimeout(this.autoAnswerTimer);
            this.autoAnswerTimer = null;
        }
    }

    // Принятие звонка
    async acceptCall() {
        if (!this.incomingCall || !this.sipSession) return;
        
        try {
            this.stopRinging();
            
            // Принятие SIP сессии
            this.sipSession.accept({
                media: {
                    audio: true,
                    video: false
                }
            });

            this.incomingCall.status = 'accepted';
            this.incomingCall.acceptTime = new Date().toISOString();
            
            // Получение медиа потока
            this.activeStream = await this.getUserMedia();
            
            // Обновление UI
            this.showActiveCallInterface();
            
            // Обновление истории
            if (window.callHistory) {
                window.callHistory.updateCallStatus(
                    this.incomingCall.id, 
                    'accepted'
                );
            }

            this.notifySubscribers('call_accepted', this.incomingCall);
            
        } catch (error) {
            console.error('Ошибка при принятии звонка:', error);
            this.rejectCall('error');
        }
    }

    // Отклонение звонка
    rejectCall(reason = 'declined') {
        if (!this.incomingCall) return;
        
        this.stopRinging();
        
        if (this.sipSession) {
            this.sipSession.reject();
        }
        
        this.incomingCall.status = reason;
        this.incomingCall.endTime = new Date().toISOString();
        
        // Логирование отклоненного звонка
        this.logRejectedCall(this.incomingCall.callerNumber, reason);
        
        // Обновление истории
        if (window.callHistory) {
            window.callHistory.updateCallStatus(
                this.incomingCall.id, 
                reason === 'declined' ? 'declined' : 'missed'
            );
        }
        
        // Закрытие модального окна
        this.hideIncomingCallModal();
        
        // Показ уведомления о пропущенном звонке
        if (reason !== 'declined') {
            this.showMissedCallNotification();
        }
        
        this.notifySubscribers('call_rejected', {
            call: this.incomingCall,
            reason: reason
        });
        
        // Очистка
        this.cleanup();
    }

    // Завершение активного звонка
    hangup() {
        if (!this.incomingCall) return;
        
        if (this.sipSession) {
            this.sipSession.terminate();
        }
        
        this.incomingCall.status = 'completed';
        this.incomingCall.endTime = new Date().toISOString();
        this.incomingCall.duration = this.calculateDuration();
        
        // Обновление истории
        if (window.callHistory) {
            window.callHistory.updateCallStatus(
                this.incomingCall.id, 
                'completed',
                this.incomingCall.duration
            );
        }
        
        // Остановка медиа
        if (this.activeStream) {
            this.activeStream.getTracks().forEach(track => track.stop());
            this.activeStream = null;
        }
        
        this.hideActiveCallInterface();
        this.notifySubscribers('call_ended', this.incomingCall);
        this.cleanup();
    }

    // Получение медиа потока
    async getUserMedia() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                },
                video: false
            });
            
            return stream;
        } catch (error) {
            console.error('Ошибка доступа к микрофону:', error);
            throw error;
        }
    }

    // Переключение микрофона
    toggleMute() {
        if (!this.activeStream) return false;
        
        const audioTrack = this.activeStream.getAudioTracks()[0];
        if (audioTrack) {
            audioTrack.enabled = !audioTrack.enabled;
            this.notifySubscribers('mute_toggled', {
                muted: !audioTrack.enabled
            });
            return !audioTrack.enabled;
        }
        return false;
    }

    // Переключение динамика
    toggleSpeaker(enabled) {
        if (!this.activeStream) return;
        
        const audioElement = document.querySelector('#remoteAudio');
        if (audioElement) {
            if (enabled) {
                audioElement.setSinkId('speaker');
            } else {
                audioElement.setSinkId('default');
            }
        }
    }

    // Отправка DTMF
    sendDTMF(digit) {
        if (this.sipSession) {
            this.sipSession.dtmf(digit);
        }
    }

    // Переадресация звонка
    async forwardCall(targetNumber) {
        if (!this.incomingCall) return;
        
        try {
            // Отправка SIP REFER
            await this.sipSession.refer(targetNumber);
            
            this.incomingCall.status = 'forwarded';
            this.incomingCall.forwardedTo = targetNumber;
            
            this.notifySubscribers('call_forwarded', {
                call: this.incomingCall,
                target: targetNumber
            });
            
            this.cleanup();
        } catch (error) {
            console.error('Ошибка переадресации:', error);
            throw error;
        }
    }

    // Показ уведомления о входящем звонке
    showIncomingCallNotification() {
        if (!this.incomingCall) return;
        
        // Браузерное уведомление
        if (Notification.permission === 'granted') {
            new Notification('Входящий звонок', {
                body: `${this.incomingCall.callerName}\n${this.incomingCall.callerNumber}`,
                icon: '/assets/icons/phone-icon.png',
                tag: 'incoming-call',
                requireInteraction: true,
                actions: [
                    { action: 'accept', title: 'Ответить' },
                    { action: 'decline', title: 'Отклонить' }
                ]
            }).onclick = (event) => {
                if (event.action === 'accept') {
                    this.acceptCall();
                } else if (event.action === 'decline') {
                    this.rejectCall('declined');
                }
            };
        }
        
        // Звуковое уведомление через TTS
        if (window.audioManager && this.incomingCall.callerName) {
            window.audioManager.speak(
                `Входящий звонок от ${this.incomingCall.callerName}`
            );
        }
    }

    // Показ модального окна входящего звонка
    showIncomingCallModal() {
        const modal = document.getElementById('incomingCallModal');
        if (!modal) return;
        
        const callerNameEl = modal.querySelector('.caller-name');
        const callerNumberEl = modal.querySelector('.caller-number');
        const contactAvatar = modal.querySelector('.contact-avatar');
        
        if (callerNameEl) {
            callerNameEl.textContent = this.incomingCall.callerName;
        }
        if (callerNumberEl) {
            callerNumberEl.textContent = this.formatPhoneNumber(this.incomingCall.callerNumber);
        }
        
        // Аватар контакта
        if (contactAvatar) {
            const initials = this.getInitials(this.incomingCall.callerName);
            contactAvatar.textContent = initials;
        }
        
        // Показ информации о контакте
        if (this.incomingCall.contactId && window.contactsManager) {
            const contact = window.contactsManager.getContact(this.incomingCall.contactId);
            if (contact) {
                const companyEl = modal.querySelector('.contact-company');
                if (companyEl && contact.company) {
                    companyEl.textContent = contact.company;
                    companyEl.style.display = 'block';
                }
            }
        }
        
        modal.style.display = 'flex';
        
        // Привязка кнопок
        const acceptBtn = modal.querySelector('.accept-call');
        const declineBtn = modal.querySelector('.decline-call');
        
        if (acceptBtn) {
            acceptBtn.onclick = () => this.acceptCall();
        }
        if (declineBtn) {
            declineBtn.onclick = () => this.rejectCall('declined');
        }
    }

    // Скрытие модального окна
    hideIncomingCallModal() {
        const modal = document.getElementById('incomingCallModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    // Показ интерфейса активного звонка
    showActiveCallInterface() {
        const activeCallModal = document.getElementById('activeCallModal');
        if (!activeCallModal) return;
        
        const callerNameEl = activeCallModal.querySelector('.caller-name');
        const callerNumberEl = activeCallModal.querySelector('.caller-number');
        const callDurationEl = activeCallModal.querySelector('.call-duration');
        
        if (callerNameEl) {
            callerNameEl.textContent = this.incomingCall.callerName;
        }
        if (callerNumberEl) {
            callerNumberEl.textContent = this.formatPhoneNumber(this.incomingCall.callerNumber);
        }
        
        // Таймер длительности
        this.startDurationTimer(callDurationEl);
        
        // Привязка кнопок управления
        this.bindCallControls(activeCallModal);
        
        // Скрываем модальное окно входящего
        this.hideIncomingCallModal();
        
        // Показываем активный звонок
        activeCallModal.style.display = 'flex';
    }

    // Скрытие интерфейса активного звонка
    hideActiveCallInterface() {
        const modal = document.getElementById('activeCallModal');
        if (modal) {
            modal.style.display = 'none';
        }
        
        if (this.durationTimer) {
            clearInterval(this.durationTimer);
            this.durationTimer = null;
        }
    }

    // Таймер длительности звонка
    startDurationTimer(element) {
        if (!element) return;
        
        const startTime = new Date(this.incomingCall.acceptTime);
        
        this.durationTimer = setInterval(() => {
            const now = new Date();
            const diff = Math.floor((now - startTime) / 1000);
            element.textContent = this.formatDuration(diff);
        }, 1000);
    }

    // Привязка контролов звонка
    bindCallControls(modal) {
        const hangupBtn = modal.querySelector('.hangup-call');
        const muteBtn = modal.querySelector('.mute-call');
        const speakerBtn = modal.querySelector('.speaker-call');
        const dtmfBtn = modal.querySelector('.dtmf-call');
        const holdBtn = modal.querySelector('.hold-call');
        const transferBtn = modal.querySelector('.transfer-call');
        
        if (hangupBtn) {
            hangupBtn.onclick = () => this.hangup();
        }
        
        if (muteBtn) {
            let isMuted = false;
            muteBtn.onclick = () => {
                isMuted = this.toggleMute();
                muteBtn.classList.toggle('active', isMuted);
            };
        }
        
        if (speakerBtn) {
            let speakerEnabled = false;
            speakerBtn.onclick = () => {
                speakerEnabled = !speakerEnabled;
                this.toggleSpeaker(speakerEnabled);
                speakerBtn.classList.toggle('active', speakerEnabled);
            };
        }
        
        if (dtmfBtn) {
            dtmfBtn.onclick = () => this.showDTMFPad();
        }
        
        if (holdBtn) {
            let isOnHold = false;
            holdBtn.onclick = () => {
                isOnHold = !isOnHold;
                this.toggleHold(isOnHold);
                holdBtn.classList.toggle('active', isOnHold);
            };
        }
        
        if (transferBtn) {
            transferBtn.onclick = () => this.showTransferDialog();
        }
    }

    // Показ DTMF клавиатуры
    showDTMFPad() {
        const dtmfPad = document.getElementById('dtmfPad');
        if (!dtmfPad) return;
        
        dtmfPad.style.display = 'grid';
        
        // Привязка кнопок DTMF
        dtmfPad.querySelectorAll('.dtmf-digit').forEach(btn => {
            btn.onclick = () => {
                this.sendDTMF(btn.dataset.digit);
            };
        });
    }

    // Перевод звонка на удержание
    toggleHold(hold) {
        if (!this.sipSession) return;
        
        if (hold) {
            this.sipSession.hold();
        } else {
            this.sipSession.unhold();
        }
    }

    // Показ диалога переадресации
    showTransferDialog() {
        const dialog = document.getElementById('transferDialog');
        if (!dialog) return;
        
        dialog.style.display = 'block';
        
        const transferInput = dialog.querySelector('#transferNumber');
        const transferBtn = dialog.querySelector('#transferBtn');
        const cancelBtn = dialog.querySelector('#cancelTransfer');
        
        if (transferBtn) {
            transferBtn.onclick = async () => {
                const targetNumber = transferInput.value;
                if (targetNumber) {
                    try {
                        await this.forwardCall(targetNumber);
                        dialog.style.display = 'none';
                    } catch (error) {
                        alert('Ошибка переадресации');
                    }
                }
            };
        }
        
        if (cancelBtn) {
            cancelBtn.onclick = () => {
                dialog.style.display = 'none';
            };
        }
    }

    // Логирование отклоненного звонка
    logRejectedCall(number, reason) {
        const rejectedCalls = JSON.parse(
            localStorage.getItem('rejected_calls') || '[]'
        );
        
        rejectedCalls.push({
            number: number,
            reason: reason,
            timestamp: new Date().toISOString()
        });
        
        // Ограничение размера лога
        if (rejectedCalls.length > 100) {
            rejectedCalls.shift();
        }
        
        localStorage.setItem('rejected_calls', JSON.stringify(rejectedCalls));
    }

    // Показ уведомления о пропущенном звонке
    showMissedCallNotification() {
        if (Notification.permission === 'granted') {
            new Notification('Пропущенный звонок', {
                body: `От: ${this.incomingCall.callerName}\n${this.incomingCall.callerNumber}`,
                icon: '/assets/icons/missed-call.png',
                tag: 'missed-call'
            });
        }
        
        // Обновление счетчика пропущенных звонков в UI
        this.updateMissedCallsCounter();
    }

    // Обновление счетчика пропущенных звонков
    updateMissedCallsCounter() {
        const counter = document.querySelector('.missed-calls-count');
        if (counter) {
            const current = parseInt(counter.textContent) || 0;
            counter.textContent = current + 1;
            counter.style.display = 'inline-block';
        }
    }

    // Расчет длительности звонка
    calculateDuration() {
        if (!this.incomingCall.acceptTime || !this.incomingCall.endTime) {
            return 0;
        }
        
        const start = new Date(this.incomingCall.acceptTime);
        const end = new Date(this.incomingCall.endTime);
        return Math.floor((end - start) / 1000);
    }

    // Форматирование номера телефона
    formatPhoneNumber(number) {
        const cleaned = number.replace(/\D/g, '');
        
        if (cleaned.length === 11) {
            return cleaned.replace(/(\d{1})(\d{3})(\d{3})(\d{2})(\d{2})/, '+$1 ($2) $3-$4-$5');
        }
        
        return number;
    }

    // Форматирование длительности
    formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }

    // Получение инициалов
    getInitials(name) {
        return name
            .split(' ')
            .map(word => word[0])
            .join('')
            .toUpperCase()
            .substring(0, 2);
    }

    // Генерация ID звонка
    generateCallId() {
        return 'call_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    // Очистка после звонка
    cleanup() {
        this.stopRinging();
        this.incomingCall = null;
        this.sipSession = null;
        
        if (this.activeStream) {
            this.activeStream.getTracks().forEach(track => track.stop());
            this.activeStream = null;
        }
        
        if (this.durationTimer) {
            clearInterval(this.durationTimer);
            this.durationTimer = null;
        }
    }

    // Подписка на события
    subscribe(callback) {
        this.callbacks.push(callback);
    }

    // Отписка
    unsubscribe(callback) {
        this.callbacks = this.callbacks.filter(cb => cb !== callback);
    }

    // Уведомление подписчиков
    notifySubscribers(event, data) {
        this.callbacks.forEach(callback => {
            try {
                callback(event, data);
            } catch (error) {
                console.error('Error in subscriber:', error);
            }
        });
    }

    // Запрос разрешения на уведомления
    async requestNotificationPermission() {
        if (Notification.permission === 'default') {
            const permission = await Notification.requestPermission();
            return permission === 'granted';
        }
        return Notification.permission === 'granted';
    }

    // Получение статистики входящих звонков
    getStatistics(period = 'today') {
        const history = window.callHistory 
            ? window.callHistory.getHistory().filter(call => call.direction === 'incoming')
            : [];
            
        const filtered = this.filterByPeriod(history, period);
        
        return {
            total: filtered.length,
            accepted: filtered.filter(c => c.status === 'completed').length,
            missed: filtered.filter(c => c.status === 'missed').length,
            declined: filtered.filter(c => c.status === 'declined').length,
            blocked: filtered.filter(c => c.status === 'blocked').length,
            averageDuration: this.calculateAverageDuration(filtered),
            totalDuration: filtered.reduce((sum, c) => sum + (c.duration || 0), 0)
        };
    }

    // Фильтрация по периоду
    filterByPeriod(history, period) {
        const now = new Date();
        let startDate = new Date();
        
        switch (period) {
            case 'today':
                startDate.setHours(0, 0, 0, 0);
                break;
            case 'week':
                startDate.setDate(now.getDate() - 7);
                break;
            case 'month':
                startDate.setMonth(now.getMonth() - 1);
                break;
        }
        
        return history.filter(call => new Date(call.startTime) >= startDate);
    }

    // Расчет средней длительности
    calculateAverageDuration(calls) {
        const completed = calls.filter(c => c.duration > 0);
        if (completed.length === 0) return 0;
        
        const total = completed.reduce((sum, c) => sum + c.duration, 0);
        return Math.round(total / completed.length);
    }
}

// Создание глобального экземпляра
window.incomingManager = new IncomingCallManager();

// Инициализация при загрузке
document.addEventListener('DOMContentLoaded', () => {
    // Запрос разрешения на уведомления
    window.incomingManager.requestNotificationPermission();
    
    // Загрузка настроек
    const settings = window.incomingManager.loadSettings();
    console.log('Incoming call manager initialized', settings);
});
