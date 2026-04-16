// audio.js - Модуль управления аудио для AutoDialer Ultimate
// Интеграция с FastAPI бэкендом и Asterisk

class AudioManager {
    constructor() {
        // API endpoints
        this.apiBase = '/api/audio';
        this.wsBase = null; // WebSocket для real-time аудио
        
        // Состояние
        this.audioContext = null;
        this.masterGain = null;
        this.isInitialized = false;
        this.isPlaying = false;
        
        // Аудио элементы
        this.sounds = new Map();
        this.currentSource = null;
        this.audioQueue = [];
        
        // Настройки
        this.settings = {
            volume: 0.7,
            muted: false,
            ttsVoice: 'denis', // Русские голоса Piper: denis, irina, random
            ttsSpeed: 1.0,
            autoPlay: true,
            notificationSound: true,
            ringtoneVolume: 0.5,
            playbackDevice: 'default'
        };
        
        // WebSocket соединение
        this.ws = null;
        this.wsReconnectTimer = null;
        this.wsReconnectDelay = 5000;
        
        // Кеш аудио файлов
        this.audioCache = new Map();
        this.maxCacheSize = 50;
        
        // Статистика
        this.stats = {
            ttsGenerated: 0,
            audioPlayed: 0,
            cacheHits: 0,
            cacheMisses: 0
        };
        
        // Подписчики на события
        this.subscribers = new Map();
        
        this.initialize();
    }
    
    // Инициализация
    async initialize() {
        try {
            // Загрузка настроек
            await this.loadSettings();
            
            // Инициализация Web Audio API
            await this.initAudioContext();
            
            // Подключение WebSocket
            this.connectWebSocket();
            
            // Загрузка стандартных звуков
            await this.preloadDefaultSounds();
            
            this.isInitialized = true;
            this.emit('initialized', { success: true });
            
            console.log('AudioManager initialized for AutoDialer Ultimate');
        } catch (error) {
            console.error('Failed to initialize AudioManager:', error);
            this.emit('error', { error: error.message });
        }
    }
    
    // Инициализация аудио контекста
    async initAudioContext() {
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            
            // Создание мастер-цепи
            this.masterGain = this.audioContext.createGain();
            this.masterGain.gain.value = this.settings.muted ? 0 : this.settings.volume;
            this.masterGain.connect(this.audioContext.destination);
            
            // Анализатор для визуализации
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            this.masterGain.connect(this.analyser);
            
            // Возобновление контекста при взаимодействии
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }
        } catch (error) {
            console.error('Failed to initialize audio context:', error);
            throw error;
        }
    }
    
    // Подключение WebSocket для real-time аудио
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.wsBase = `${protocol}//${window.location.host}/ws/audio`;
        
        try {
            this.ws = new WebSocket(this.wsBase);
            
            this.ws.onopen = () => {
                console.log('Audio WebSocket connected');
                this.emit('ws_connected');
                
                // Отправка информации о клиенте
                this.ws.send(JSON.stringify({
                    type: 'register',
                    clientType: 'audio',
                    capabilities: ['tts', 'playback', 'streaming']
                }));
            };
            
            this.ws.onmessage = (event) => {
                this.handleWebSocketMessage(event.data);
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.emit('ws_error', { error });
            };
            
            this.ws.onclose = () => {
                console.log('Audio WebSocket closed');
                this.emit('ws_disconnected');
                this.scheduleReconnect();
            };
        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
            this.scheduleReconnect();
        }
    }
    
    // Обработка сообщений WebSocket
    handleWebSocketMessage(data) {
        try {
            const message = JSON.parse(data);
            
            switch (message.type) {
                case 'audio_stream':
                    this.handleAudioStream(message.data);
                    break;
                    
                case 'tts_generated':
                    this.handleTTSGenerated(message.data);
                    break;
                    
                case 'playback_status':
                    this.emit('playback_status', message.data);
                    break;
                    
                case 'error':
                    console.error('WebSocket error:', message.error);
                    this.emit('error', { error: message.error });
                    break;
                    
                default:
                    console.warn('Unknown WebSocket message type:', message.type);
            }
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
        }
    }
    
    // Обработка аудио потока
    async handleAudioStream(data) {
        try {
            const { audioData, format, sampleRate } = data;
            
            // Декодирование base64
            const binaryString = atob(audioData);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            
            // Декодирование аудио
            const audioBuffer = await this.audioContext.decodeAudioData(bytes.buffer);
            
            // Воспроизведение
            this.playAudioBuffer(audioBuffer);
            
        } catch (error) {
            console.error('Failed to handle audio stream:', error);
        }
    }
    
    // Обработка сгенерированного TTS
    async handleTTSGenerated(data) {
        try {
            const { audioUrl, text, voice, campaignId } = data;
            
            // Загрузка и воспроизведение
            await this.playFromUrl(audioUrl);
            
            this.stats.ttsGenerated++;
            
            this.emit('tts_generated', {
                text,
                voice,
                campaignId,
                url: audioUrl
            });
            
        } catch (error) {
            console.error('Failed to handle TTS generated:', error);
        }
    }
    
    // Планирование переподключения
    scheduleReconnect() {
        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
        }
        
        this.wsReconnectTimer = setTimeout(() => {
            console.log('Reconnecting WebSocket...');
            this.connectWebSocket();
        }, this.wsReconnectDelay);
    }
    
    // Предзагрузка стандартных звуков
    async preloadDefaultSounds() {
        const sounds = {
            'ringtone': '/assets/sounds/ringtone.mp3',
            'busy': '/assets/sounds/busy.mp3',
            'dial': '/assets/sounds/dial.mp3',
            'hangup': '/assets/sounds/hangup.mp3',
            'notification': '/assets/sounds/notification.mp3',
            'success': '/assets/sounds/success.mp3',
            'error': '/assets/sounds/error.mp3'
        };
        
        for (const [name, url] of Object.entries(sounds)) {
            try {
                await this.loadSound(name, url);
            } catch (error) {
                console.warn(`Failed to preload sound ${name}:`, error);
            }
        }
    }
    
    // Загрузка звука
    async loadSound(name, url) {
        try {
            const response = await fetch(url);
            const arrayBuffer = await response.arrayBuffer();
            const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            
            this.sounds.set(name, audioBuffer);
            this.audioCache.set(url, audioBuffer);
            
            return audioBuffer;
        } catch (error) {
            console.error(`Failed to load sound ${name}:`, error);
            throw error;
        }
    }
    
    // Воспроизведение звука по имени
    playSound(name, options = {}) {
        const {
            volume = 1.0,
            loop = false,
            onEnd = null
        } = options;
        
        const sound = this.sounds.get(name);
        if (!sound) {
            console.warn(`Sound ${name} not found`);
            return null;
        }
        
        return this.playAudioBuffer(sound, { volume, loop, onEnd });
    }
    
    // Воспроизведение аудио буфера
    playAudioBuffer(audioBuffer, options = {}) {
        if (!this.audioContext || !this.masterGain) {
            console.error('Audio context not initialized');
            return null;
        }
        
        const {
            volume = 1.0,
            loop = false,
            onEnd = null,
            startTime = 0
        } = options;
        
        try {
            // Создание источника
            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.loop = loop;
            
            // Создание громкости
            const gainNode = this.audioContext.createGain();
            gainNode.gain.value = volume;
            
            // Подключение
            source.connect(gainNode);
            gainNode.connect(this.masterGain);
            
            // Обработка окончания
            source.onended = () => {
                this.isPlaying = false;
                this.currentSource = null;
                if (onEnd) onEnd();
                this.emit('playback_ended');
                
                // Воспроизведение следующего в очереди
                this.playNextInQueue();
            };
            
            // Запуск
            source.start(0, startTime);
            this.isPlaying = true;
            this.currentSource = source;
            
            this.stats.audioPlayed++;
            
            this.emit('playback_started', { duration: audioBuffer.duration });
            
            return {
                source,
                gainNode,
                stop: () => {
                    try {
                        source.stop();
                    } catch (e) {
                        // Игнорируем ошибку если уже остановлен
                    }
                },
                setVolume: (val) => {
                    gainNode.gain.value = val;
                }
            };
            
        } catch (error) {
            console.error('Failed to play audio buffer:', error);
            return null;
        }
    }
    
    // Воспроизведение из URL
    async playFromUrl(url, options = {}) {
        try {
            // Проверка кеша
            let audioBuffer = this.audioCache.get(url);
            
            if (audioBuffer) {
                this.stats.cacheHits++;
                return this.playAudioBuffer(audioBuffer, options);
            }
            
            this.stats.cacheMisses++;
            
            // Загрузка
            const response = await fetch(url);
            const arrayBuffer = await response.arrayBuffer();
            audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            
            // Кеширование
            this.cacheAudio(url, audioBuffer);
            
            return this.playAudioBuffer(audioBuffer, options);
            
        } catch (error) {
            console.error('Failed to play from URL:', error);
            throw error;
        }
    }
    
    // Кеширование аудио
    cacheAudio(url, audioBuffer) {
        // Ограничение размера кеша
        if (this.audioCache.size >= this.maxCacheSize) {
            const firstKey = this.audioCache.keys().next().value;
            this.audioCache.delete(firstKey);
        }
        
        this.audioCache.set(url, audioBuffer);
    }
    
    // Генерация TTS через API
    async generateTTS(text, options = {}) {
        const {
            voice = this.settings.ttsVoice,
            speed = this.settings.ttsSpeed,
            campaignId = null,
            format = 'mp3'
        } = options;
        
        try {
            const response = await fetch(`${this.apiBase}/tts/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.getAuthToken()}`
                },
                body: JSON.stringify({
                    text,
                    voice,
                    speed,
                    campaign_id: campaignId,
                    format
                })
            });
            
            if (!response.ok) {
                throw new Error(`TTS generation failed: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            this.stats.ttsGenerated++;
            
            this.emit('tts_generated', {
                text,
                voice,
                audioUrl: data.audio_url
            });
            
            return data;
            
        } catch (error) {
            console.error('Failed to generate TTS:', error);
            throw error;
        }
    }
    
    // Генерация и воспроизведение TTS
    async speak(text, options = {}) {
        try {
            const { audio_url } = await this.generateTTS(text, options);
            
            if (this.settings.autoPlay) {
                await this.playFromUrl(audio_url, options);
            }
            
            return audio_url;
            
        } catch (error) {
            console.error('Failed to speak:', error);
            throw error;
        }
    }
    
    // Воспроизведение рингтона
    playRingtone(loop = true) {
        this.stopRingtone();
        
        this.currentRingtone = this.playSound('ringtone', {
            volume: this.settings.ringtoneVolume,
            loop: loop
        });
        
        this.emit('ringtone_started');
        
        return this.currentRingtone;
    }
    
    // Остановка рингтона
    stopRingtone() {
        if (this.currentRingtone) {
            this.currentRingtone.stop();
            this.currentRingtone = null;
            this.emit('ringtone_stopped');
        }
    }
    
    // Добавление в очередь воспроизведения
    queueAudio(audioId, options = {}) {
        this.audioQueue.push({
            id: audioId,
            options
        });
        
        if (!this.isPlaying) {
            this.playNextInQueue();
        }
    }
    
    // Воспроизведение следующего в очереди
    async playNextInQueue() {
        if (this.audioQueue.length === 0 || this.isPlaying) {
            return;
        }
        
        const item = this.audioQueue.shift();
        
        try {
            await this.playFromUrl(item.id, {
                ...item.options,
                onEnd: () => {
                    this.playNextInQueue();
                    if (item.options.onEnd) {
                        item.options.onEnd();
                    }
                }
            });
        } catch (error) {
            console.error('Failed to play queued audio:', error);
            // Продолжаем со следующим
            this.playNextInQueue();
        }
    }
    
    // Очистка очереди
    clearQueue() {
        this.audioQueue = [];
        this.emit('queue_cleared');
    }
    
    // Остановка воспроизведения
    stop() {
        if (this.currentSource) {
            try {
                this.currentSource.stop();
            } catch (e) {
                // Игнорируем
            }
            this.currentSource = null;
        }
        
        this.isPlaying = false;
        this.emit('playback_stopped');
    }
    
    // Пауза
    pause() {
        if (this.audioContext && this.audioContext.state === 'running') {
            this.audioContext.suspend();
            this.emit('playback_paused');
        }
    }
    
    // Продолжить
    resume() {
        if (this.audioContext && this.audioContext.state === 'suspended') {
            this.audioContext.resume();
            this.emit('playback_resumed');
        }
    }
    
    // Установка громкости
    setVolume(value) {
        this.settings.volume = Math.max(0, Math.min(1, value));
        
        if (this.masterGain && !this.settings.muted) {
            this.masterGain.gain.value = this.settings.volume;
        }
        
        this.saveSettings();
        this.emit('volume_changed', { volume: this.settings.volume });
    }
    
    // Включение/выключение звука
    setMuted(muted) {
        this.settings.muted = muted;
        
        if (this.masterGain) {
            this.masterGain.gain.value = muted ? 0 : this.settings.volume;
        }
        
        this.saveSettings();
        this.emit('mute_changed', { muted });
    }
    
    // Получение списка доступных TTS голосов
    async getAvailableVoices() {
        try {
            const response = await fetch(`${this.apiBase}/tts/voices`, {
                headers: {
                    'Authorization': `Bearer ${this.getAuthToken()}`
                }
            });
            
            if (!response.ok) {
                throw new Error(`Failed to get voices: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data.voices;
            
        } catch (error) {
            console.error('Failed to get voices:', error);
            
            // Возвращаем список по умолчанию
            return [
                { id: 'denis', name: 'Денис (Русский)', language: 'ru-RU' },
                { id: 'irina', name: 'Ирина (Русский)', language: 'ru-RU' },
                { id: 'random', name: 'Случайный', language: 'ru-RU' }
            ];
        }
    }
    
    // Установка TTS голоса
    async setTTSVoice(voiceId) {
        this.settings.ttsVoice = voiceId;
        await this.saveSettings();
        this.emit('tts_voice_changed', { voice: voiceId });
    }
    
    // Получение визуализации аудио
    getVisualizationData() {
        if (!this.analyser) return null;
        
        const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteFrequencyData(dataArray);
        
        return {
            frequencies: Array.from(dataArray),
            average: dataArray.reduce((a, b) => a + b, 0) / dataArray.length
        };
    }
    
    // Запись аудио с микрофона
    async startRecording(options = {}) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
            
            this.mediaRecorder = new MediaRecorder(stream);
            this.recordedChunks = [];
            
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.recordedChunks.push(event.data);
                }
            };
            
            this.mediaRecorder.onstop = async () => {
                const blob = new Blob(this.recordedChunks, { type: 'audio/webm' });
                
                // Отправка на сервер
                if (options.upload) {
                    await this.uploadRecording(blob, options);
                }
                
                if (options.onComplete) {
                    options.onComplete(blob);
                }
                
                this.emit('recording_completed', { blob });
            };
            
            this.mediaRecorder.start();
            this.emit('recording_started');
            
            return true;
            
        } catch (error) {
            console.error('Failed to start recording:', error);
            this.emit('recording_error', { error: error.message });
            return false;
        }
    }
    
    // Остановка записи
    stopRecording() {
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
            this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
            this.emit('recording_stopped');
        }
    }
    
    // Загрузка записи на сервер
    async uploadRecording(blob, options = {}) {
        try {
            const formData = new FormData();
            formData.append('audio', blob, `recording_${Date.now()}.webm`);
            
            if (options.campaignId) {
                formData.append('campaign_id', options.campaignId);
            }
            
            if (options.contactId) {
                formData.append('contact_id', options.contactId);
            }
            
            const response = await fetch(`${this.apiBase}/recordings/upload`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.getAuthToken()}`
                },
                body: formData
            });
            
            if (!response.ok) {
                throw new Error(`Upload failed: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            this.emit('recording_uploaded', data);
            
            return data;
            
        } catch (error) {
            console.error('Failed to upload recording:', error);
            throw error;
        }
    }
    
    // Загрузка настроек
    async loadSettings() {
        try {
            const stored = localStorage.getItem('autodialer_audio_settings');
            if (stored) {
                this.settings = { ...this.settings, ...JSON.parse(stored) };
            }
            
            // Загрузка с сервера
            const response = await fetch(`${this.apiBase}/settings`, {
                headers: {
                    'Authorization': `Bearer ${this.getAuthToken()}`
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                this.settings = { ...this.settings, ...data };
            }
            
        } catch (error) {
            console.warn('Failed to load audio settings:', error);
        }
    }
    
    // Сохранение настроек
    async saveSettings() {
        try {
            localStorage.setItem('autodialer_audio_settings', JSON.stringify(this.settings));
            
            // Сохранение на сервере
            await fetch(`${this.apiBase}/settings`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.getAuthToken()}`
                },
                body: JSON.stringify(this.settings)
            });
            
        } catch (error) {
            console.warn('Failed to save audio settings:', error);
        }
    }
    
    // Получение токена авторизации
    getAuthToken() {
        // Получение из localStorage или из глобального состояния
        return localStorage.getItem('access_token') || '';
    }
    
    // Получение статистики
    getStatistics() {
        return {
            ...this.stats,
            cacheSize: this.audioCache.size,
            queueLength: this.audioQueue.length,
            isPlaying: this.isPlaying,
            audioContextState: this.audioContext?.state
        };
    }
    
    // Подписка на события
    on(event, callback) {
        if (!this.subscribers.has(event)) {
            this.subscribers.set(event, new Set());
        }
        this.subscribers.get(event).add(callback);
    }
    
    // Отписка от событий
    off(event, callback) {
        if (this.subscribers.has(event)) {
            this.subscribers.get(event).delete(callback);
        }
    }
    
    // Эмит события
    emit(event, data) {
        if (this.subscribers.has(event)) {
            this.subscribers.get(event).forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`Error in ${event} subscriber:`, error);
                }
            });
        }
    }
    
    // Очистка ресурсов
    destroy() {
        this.stop();
        this.stopRingtone();
        this.stopRecording();
        this.clearQueue();
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
        }
        
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        
        this.sounds.clear();
        this.audioCache.clear();
        this.subscribers.clear();
        
        this.isInitialized = false;
    }
}

// Создание глобального экземпляра
window.audioManager = new AudioManager();

// Экспорт для модульной системы
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AudioManager;
}

// Интеграция с React (если используется)
if (typeof window !== 'undefined') {
    // Экспорт для использования в React компонентах
    window.AudioManager = AudioManager;
}

/*
Примеры использования в AutoDialer Ultimate:

// В React компоненте:
import { useEffect } from 'react';

function CampaignPlayer({ campaignId, message }) {
    useEffect(() => {
        // Подписка на события
        audioManager.on('playback_started', (data) => {
            console.log('Playing:', data);
        });
        
        audioManager.on('playback_ended', () => {
            console.log('Playback ended');
        });
        
        return () => {
            audioManager.off('playback_started');
            audioManager.off('playback_ended');
        };
    }, []);
    
    const handlePlayTTS = async () => {
        try {
            // Генерация и воспроизведение TTS
            await audioManager.speak(message, {
                voice: 'denis',
                campaignId: campaignId
            });
        } catch (error) {
            console.error('TTS failed:', error);
        }
    };
    
    const handlePlayRingtone = () => {
        audioManager.playRingtone(true);
        
        // Остановить через 30 секунд
        setTimeout(() => {
            audioManager.stopRingtone();
        }, 30000);
    };
    
    const handleRecordMessage = async () => {
        await audioManager.startRecording({
            campaignId: campaignId,
            upload: true,
            onComplete: (blob) => {
                console.log('Recording completed:', blob);
            }
        });
    };
    
    return (
        <div>
            <button onClick={handlePlayTTS}>Воспроизвести TTS</button>
            <button onClick={handlePlayRingtone}>Тест рингтона</button>
            <button onClick={handleRecordMessage}>Записать сообщение</button>
            <button onClick={() => audioManager.stop()}>Стоп</button>
        </div>
    );
}

// В компоненте мониторинга звонков:
function CallMonitor() {
    const [visualization, setVisualization] = useState(null);
    
    useEffect(() => {
        const interval = setInterval(() => {
            const data = audioManager.getVisualizationData();
            setVisualization(data);
        }, 50);
        
        return () => clearInterval(interval);
    }, []);
    
    // Отображение визуализации аудио
    return (
        <canvas 
            ref={canvasRef}
            // Рисование визуализации
        />
    );
}

// Интеграция с WebSocket для real-time аудио:
audioManager.on('ws_connected', () => {
    console.log('Ready for real-time audio streaming');
});

// Получение статистики:
const stats = audioManager.getStatistics();
console.log('Audio stats:', stats);
*/
