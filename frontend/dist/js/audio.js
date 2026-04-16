// audio.js - Полный модуль управления аудио и синтезом речи

class AudioManager {
    constructor() {
        // Аудио контекст и узлы
        this.audioContext = null;
        this.masterGain = null;
        this.compressor = null;
        
        // Аудио элементы
        this.ringtones = new Map();
        this.sounds = new Map();
        this.audioFiles = new Map();
        this.currentRingtone = null;
        this.currentBackgroundMusic = null;
        
        // TTS (Text-to-Speech)
        this.synthesis = window.speechSynthesis;
        this.voices = [];
        this.currentUtterance = null;
        this.ttsEnabled = true;
        this.ttsVolume = 1.0;
        this.ttsRate = 1.0;
        this.ttsPitch = 1.0;
        this.selectedVoice = null;
        
        // Запись аудио
        this.mediaRecorder = null;
        this.recordedChunks = [];
        this.recordingStream = null;
        this.isRecording = false;
        
        // Аудио эффекты
        this.effects = new Map();
        this.filters = new Map();
        
        // Кеширование аудио
        this.audioCache = new Map();
        this.maxCacheSize = 50;
        
        // Состояние
        this.isMuted = false;
        this.isSpeakerOn = true;
        this.volume = 0.7;
        this.microphoneVolume = 1.0;
        
        // Очередь воспроизведения
        this.playQueue = [];
        this.isPlaying = false;
        
        // Статистика
        this.stats = {
            ttsCharacters: 0,
            audioPlayed: 0,
            recordingsCount: 0,
            totalRecordingTime: 0
        };
        
        this.initialize();
    }

    // Инициализация аудио системы
    async initialize() {
        try {
            // Создание аудио контекста
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            
            // Создание мастер-цепи
            this.masterGain = this.audioContext.createGain();
            this.masterGain.gain.value = this.volume;
            
            this.compressor = this.audioContext.createDynamicsCompressor();
            this.compressor.threshold.value = -24;
            this.compressor.knee.value = 30;
            this.compressor.ratio.value = 12;
            this.compressor.attack.value = 0.003;
            this.compressor.release.value = 0.25;
            
            // Подключение цепи
            this.masterGain.connect(this.compressor);
            this.compressor.connect(this.audioContext.destination);
            
            // Загрузка голосов для TTS
            await this.loadVoices();
            
            // Загрузка стандартных звуков
            await this.loadDefaultSounds();
            
            // Загрузка настроек
            this.loadSettings();
            
            // Восстановление контекста при необходимости
            this.setupAutoResume();
            
            console.log('AudioManager initialized successfully');
        } catch (error) {
            console.error('Failed to initialize AudioManager:', error);
        }
    }

    // Настройка автовозобновления аудио контекста
    setupAutoResume() {
        const resumeAudio = async () => {
            if (this.audioContext && this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }
        };
        
        document.addEventListener('click', resumeAudio, { once: true });
        document.addEventListener('touchstart', resumeAudio, { once: true });
        document.addEventListener('keydown', resumeAudio, { once: true });
    }

    // Загрузка голосов для TTS
    async loadVoices() {
        return new Promise((resolve) => {
            const voices = this.synthesis.getVoices();
            
            if (voices.length > 0) {
                this.voices = voices;
                this.selectDefaultVoice();
                resolve();
            } else {
                this.synthesis.onvoiceschanged = () => {
                    this.voices = this.synthesis.getVoices();
                    this.selectDefaultVoice();
                    resolve();
                };
            }
        });
    }

    // Выбор голоса по умолчанию
    selectDefaultVoice() {
        // Приоритет: русский женский голос
        const preferredVoices = [
            'Google русский',
            'Microsoft Irina',
            'Russian Female',
            'ru-RU'
        ];
        
        for (const preferred of preferredVoices) {
            const voice = this.voices.find(v => 
                v.name.includes(preferred) || 
                v.lang.includes('ru')
            );
            if (voice) {
                this.selectedVoice = voice;
                return;
            }
        }
        
        // Если русский не найден, берем первый доступный
        if (this.voices.length > 0) {
            this.selectedVoice = this.voices[0];
        }
    }

    // Загрузка стандартных звуков
    async loadDefaultSounds() {
        const defaultSounds = {
            'ringtone': '/assets/sounds/ringtone.mp3',
            'busy': '/assets/sounds/busy.mp3',
            'dial': '/assets/sounds/dial.mp3',
            'hangup': '/assets/sounds/hangup.mp3',
            'message': '/assets/sounds/message.mp3',
            'notification': '/assets/sounds/notification.mp3',
            'success': '/assets/sounds/success.mp3',
            'error': '/assets/sounds/error.mp3',
            'click': '/assets/sounds/click.mp3',
            'keypress': '/assets/sounds/keypress.mp3'
        };
        
        for (const [name, url] of Object.entries(defaultSounds)) {
            await this.loadSound(name, url);
        }
    }

    // Загрузка звука
    async loadSound(name, url) {
        try {
            const response = await fetch(url);
            const arrayBuffer = await response.arrayBuffer();
            const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            
            this.sounds.set(name, audioBuffer);
            return audioBuffer;
        } catch (error) {
            console.warn(`Failed to load sound ${name}:`, error);
            return null;
        }
    }

    // Воспроизведение звука
    playSound(name, options = {}) {
        const {
            volume = 1.0,
            loop = false,
            playbackRate = 1.0,
            pan = 0
        } = options;
        
        const sound = this.sounds.get(name);
        if (!sound || this.isMuted) return null;
        
        const source = this.audioContext.createBufferSource();
        source.buffer = sound;
        source.loop = loop;
        source.playbackRate.value = playbackRate;
        
        // Создание панорамирования
        const panner = this.audioContext.createStereoPanner();
        panner.pan.value = pan;
        
        // Громкость
        const gainNode = this.audioContext.createGain();
        gainNode.gain.value = volume * this.volume;
        
        // Подключение
        source.connect(panner);
        panner.connect(gainNode);
        gainNode.connect(this.masterGain);
        
        source.start();
        
        this.stats.audioPlayed++;
        
        return {
            source,
            stop: () => source.stop(),
            setVolume: (val) => gainNode.gain.value = val,
            setPan: (val) => panner.pan.value = val
        };
    }

    // Воспроизведение рингтона
    playRingtone(ringtoneName = 'ringtone', loop = true) {
        if (this.currentRingtone) {
            this.stopRingtone();
        }
        
        this.currentRingtone = this.playSound(ringtoneName, {
            volume: 0.5,
            loop: loop
        });
        
        return this.currentRingtone;
    }

    // Остановка рингтона
    stopRingtone() {
        if (this.currentRingtone) {
            this.currentRingtone.stop();
            this.currentRingtone = null;
        }
    }

    // TTS - синтез речи
    speak(text, options = {}) {
        if (!this.ttsEnabled) return null;
        
        const {
            voice = this.selectedVoice,
            volume = this.ttsVolume,
            rate = this.ttsRate,
            pitch = this.ttsPitch,
            onStart = null,
            onEnd = null,
            onError = null
        } = options;
        
        // Остановка текущего произношения
        this.stopSpeaking();
        
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.voice = voice;
        utterance.volume = this.isMuted ? 0 : volume;
        utterance.rate = rate;
        utterance.pitch = pitch;
        utterance.lang = 'ru-RU';
        
        utterance.onstart = () => {
            this.stats.ttsCharacters += text.length;
            if (onStart) onStart();
        };
        
        utterance.onend = () => {
            this.currentUtterance = null;
            if (onEnd) onEnd();
        };
        
        utterance.onerror = (error) => {
            console.error('TTS Error:', error);
            this.currentUtterance = null;
            if (onError) onError(error);
        };
        
        this.currentUtterance = utterance;
        this.synthesis.speak(utterance);
        
        return utterance;
    }

    // Остановка речи
    stopSpeaking() {
        if (this.synthesis.speaking) {
            this.synthesis.cancel();
        }
        this.currentUtterance = null;
    }

    // Пауза речи
    pauseSpeaking() {
        if (this.synthesis.speaking) {
            this.synthesis.pause();
        }
    }

    // Продолжить речь
    resumeSpeaking() {
        if (this.synthesis.paused) {
            this.synthesis.resume();
        }
    }

    // Произнести номер телефона
    speakPhoneNumber(number) {
        const digits = number.split('').join(' ');
        return this.speak(`Номер ${digits}`);
    }

    // Произнести время
    speakTime(date = new Date()) {
        const hours = date.getHours();
        const minutes = date.getMinutes();
        const timeString = `${hours} ${this.getHourWord(hours)} ${minutes} ${this.getMinuteWord(minutes)}`;
        return this.speak(timeString);
    }

    // Склонение слова "час"
    getHourWord(hours) {
        if (hours === 1 || hours === 21) return 'час';
        if ((hours >= 2 && hours <= 4) || (hours >= 22 && hours <= 23)) return 'часа';
        return 'часов';
    }

    // Склонение слова "минута"
    getMinuteWord(minutes) {
        if (minutes === 1 || minutes === 21 || minutes === 31 || minutes === 41 || minutes === 51) return 'минута';
        if ((minutes >= 2 && minutes <= 4) || 
            (minutes >= 22 && minutes <= 24) || 
            (minutes >= 32 && minutes <= 34) || 
            (minutes >= 42 && minutes <= 44) || 
            (minutes >= 52 && minutes <= 54)) return 'минуты';
        return 'минут';
    }

    // Запись аудио
    async startRecording(options = {}) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 44100,
                    channelCount: 1
                }
            });
            
            this.recordingStream = stream;
            this.recordedChunks = [];
            
            const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') 
                ? 'audio/webm;codecs=opus' 
                : 'audio/webm';
            
            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType: mimeType,
                audioBitsPerSecond: 128000
            });
            
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.recordedChunks.push(event.data);
                }
            };
            
            this.mediaRecorder.onstop = () => {
                this.processRecording(options.onComplete);
            };
            
            this.mediaRecorder.start(1000); // Сохранение чанков каждую секунду
            this.isRecording = true;
            
            const startTime = Date.now();
            this.recordingInterval = setInterval(() => {
                const duration = Math.floor((Date.now() - startTime) / 1000);
                if (options.onProgress) {
                    options.onProgress(duration);
                }
            }, 1000);
            
            return true;
        } catch (error) {
            console.error('Failed to start recording:', error);
            if (options.onError) options.onError(error);
            return false;
        }
    }

    // Остановка записи
    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            this.mediaRecorder.stop();
            this.isRecording = false;
            
            if (this.recordingStream) {
                this.recordingStream.getTracks().forEach(track => track.stop());
                this.recordingStream = null;
            }
            
            if (this.recordingInterval) {
                clearInterval(this.recordingInterval);
                this.recordingInterval = null;
            }
        }
    }

    // Обработка записи
    processRecording(callback) {
        const blob = new Blob(this.recordedChunks, { type: 'audio/webm' });
        const url = URL.createObjectURL(blob);
        
        const recording = {
            blob: blob,
            url: url,
            size: blob.size,
            duration: this.recordedChunks.length,
            timestamp: new Date().toISOString()
        };
        
        this.stats.recordingsCount++;
        this.stats.totalRecordingTime += recording.duration;
        
        if (callback) {
            callback(recording);
        }
        
        return recording;
    }

    // Воспроизведение записи
    playRecording(url) {
        const audio = new Audio(url);
        audio.volume = this.isMuted ? 0 : this.volume;
        audio.play();
        return audio;
    }

    // Сохранение записи
    saveRecording(blob, filename = null) {
        const name = filename || `recording_${Date.now()}.webm`;
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.click();
        
        URL.revokeObjectURL(url);
    }

    // Применение аудио эффектов
    createEffect(type, options = {}) {
        let effect;
        
        switch(type) {
            case 'reverb':
                effect = this.createReverb(options);
                break;
            case 'delay':
                effect = this.createDelay(options);
                break;
            case 'distortion':
                effect = this.createDistortion(options);
                break;
            case 'filter':
                effect = this.createFilter(options);
                break;
            case 'equalizer':
                effect = this.createEqualizer(options);
                break;
            default:
                throw new Error(`Unknown effect type: ${type}`);
        }
        
        const id = `effect_${Date.now()}_${Math.random()}`;
        this.effects.set(id, effect);
        
        return id;
    }

    // Создание реверберации
    createReverb(options = {}) {
        const {
            duration = 2,
            decay = 2,
            mix = 0.5
        } = options;
        
        const convolver = this.audioContext.createConvolver();
        const rate = this.audioContext.sampleRate;
        const length = rate * duration;
        const impulse = this.audioContext.createBuffer(2, length, rate);
        
        for (let channel = 0; channel < 2; channel++) {
            const channelData = impulse.getChannelData(channel);
            for (let i = 0; i < length; i++) {
                channelData[i] = (Math.random() * 2 - 1) * 
                    Math.pow(1 - i / length, decay);
            }
        }
        
        convolver.buffer = impulse;
        
        const dryGain = this.audioContext.createGain();
        const wetGain = this.audioContext.createGain();
        
        dryGain.gain.value = 1 - mix;
        wetGain.gain.value = mix;
        
        return {
            input: dryGain,
            output: wetGain,
            convolver,
            connect: (source, destination) => {
                source.connect(dryGain);
                source.connect(convolver);
                convolver.connect(wetGain);
                dryGain.connect(destination);
                wetGain.connect(destination);
            }
        };
    }

    // Создание дилея (эхо)
    createDelay(options = {}) {
        const {
            delayTime = 0.3,
            feedback = 0.3,
            mix = 0.5
        } = options;
        
        const delay = this.audioContext.createDelay();
        delay.delayTime.value = delayTime;
        
        const feedbackGain = this.audioContext.createGain();
        feedbackGain.gain.value = feedback;
        
        const dryGain = this.audioContext.createGain();
        const wetGain = this.audioContext.createGain();
        
        dryGain.gain.value = 1 - mix;
        wetGain.gain.value = mix;
        
        delay.connect(feedbackGain);
        feedbackGain.connect(delay);
        
        return {
            input: dryGain,
            output: wetGain,
            delay,
            connect: (source, destination) => {
                source.connect(dryGain);
                source.connect(delay);
                delay.connect(wetGain);
                dryGain.connect(destination);
                wetGain.connect(destination);
            }
        };
    }

    // Создание дисторшна
    createDistortion(options = {}) {
        const {
            amount = 50,
            mix = 0.5
        } = options;
        
        const distortion = this.audioContext.createWaveShaper();
        
        const makeDistortionCurve = (amount) => {
            const k = amount;
            const samples = 44100;
            const curve = new Float32Array(samples);
            const deg = Math.PI / 180;
            
            for (let i = 0; i < samples; ++i) {
                const x = i * 2 / samples - 1;
                curve[i] = (3 + k) * x * 20 * deg / (Math.PI + k * Math.abs(x));
            }
            return curve;
        };
        
        distortion.curve = makeDistortionCurve(amount);
        distortion.oversample = '4x';
        
        const dryGain = this.audioContext.createGain();
        const wetGain = this.audioContext.createGain();
        
        dryGain.gain.value = 1 - mix;
        wetGain.gain.value = mix;
        
        return {
            input: dryGain,
            output: wetGain,
            distortion,
            connect: (source, destination) => {
                source.connect(dryGain);
                source.connect(distortion);
                distortion.connect(wetGain);
                dryGain.connect(destination);
                wetGain.connect(destination);
            }
        };
    }

    // Создание фильтра
    createFilter(options = {}) {
        const {
            type = 'lowpass',
            frequency = 1000,
            Q = 1,
            gain = 0
        } = options;
        
        const filter = this.audioContext.createBiquadFilter();
        filter.type = type;
        filter.frequency.value = frequency;
        filter.Q.value = Q;
        filter.gain.value = gain;
        
        return {
            input: filter,
            output: filter,
            filter,
            connect: (source, destination) => {
                source.connect(filter);
                filter.connect(destination);
            },
            setFrequency: (freq) => filter.frequency.value = freq,
            setQ: (q) => filter.Q.value = q,
            setGain: (g) => filter.gain.value = g
        };
    }

    // Создание эквалайзера
    createEqualizer(options = {}) {
        const bands = options.bands || [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000];
        const filters = [];
        
        bands.forEach((freq, index) => {
            const filter = this.audioContext.createBiquadFilter();
            filter.type = index === 0 ? 'lowshelf' : 
                         index === bands.length - 1 ? 'highshelf' : 'peaking';
            filter.frequency.value = freq;
            filter.Q.value = 1;
            filter.gain.value = options[`band${index}`] || 0;
            filters.push(filter);
        });
        
        // Соединение фильтров последовательно
        for (let i = 0; i < filters.length - 1; i++) {
            filters[i].connect(filters[i + 1]);
        }
        
        return {
            input: filters[0],
            output: filters[filters.length - 1],
            filters,
            connect: (source, destination) => {
                source.connect(filters[0]);
                filters[filters.length - 1].connect(destination);
            },
            setBand: (index, gain) => {
                if (filters[index]) {
                    filters[index].gain.value = gain;
                }
            }
        };
    }

    // Управление громкостью
    setVolume(value) {
        this.volume = Math.max(0, Math.min(1, value));
        if (this.masterGain) {
            this.masterGain.gain.value = this.isMuted ? 0 : this.volume;
        }
        this.saveSettings();
    }

    // Включение/выключение звука
    setMuted(muted) {
        this.isMuted = muted;
        if (this.masterGain) {
            this.masterGain.gain.value = muted ? 0 : this.volume;
        }
        
        // Остановка TTS при mute
        if (muted) {
            this.stopSpeaking();
        }
        
        this.saveSettings();
    }

    // Управление громкостью микрофона
    setMicrophoneVolume(value) {
        this.microphoneVolume = Math.max(0, Math.min(2, value));
        
        if (this.recordingStream) {
            const audioTrack = this.recordingStream.getAudioTracks()[0];
            if (audioTrack && audioTrack.getCapabilities) {
                const capabilities = audioTrack.getCapabilities();
                if (capabilities.volume) {
                    audioTrack.applyConstraints({
                        volume: this.microphoneVolume
                    });
                }
            }
        }
    }

    // Настройки TTS
    setTTSEnabled(enabled) {
        this.ttsEnabled = enabled;
        if (!enabled) {
            this.stopSpeaking();
        }
        this.saveSettings();
    }

    setTTSVolume(volume) {
        this.ttsVolume = Math.max(0, Math.min(1, volume));
        this.saveSettings();
    }

    setTTSRate(rate) {
        this.ttsRate = Math.max(0.1, Math.min(10, rate));
        this.saveSettings();
    }

    setTTSPitch(pitch) {
        this.ttsPitch = Math.max(0, Math.min(2, pitch));
        this.saveSettings();
    }

    setTTSVoice(voiceName) {
        const voice = this.voices.find(v => v.name === voiceName);
        if (voice) {
            this.selectedVoice = voice;
            this.saveSettings();
        }
    }

    // Получение списка голосов
    getVoices() {
        return this.voices;
    }

    // Получение доступных языков TTS
    getAvailableLanguages() {
        const languages = new Set();
        this.voices.forEach(voice => {
            languages.add(voice.lang);
        });
        return Array.from(languages).sort();
    }

    // Предпросмотр голоса
    previewVoice(voiceName) {
        const voice = this.voices.find(v => v.name === voiceName);
        if (voice) {
            this.speak('Привет! Это тестовое сообщение для проверки голоса.', {
                voice: voice
            });
        }
    }

    // Сохранение настроек
    saveSettings() {
        const settings = {
            volume: this.volume,
            isMuted: this.isMuted,
            ttsEnabled: this.ttsEnabled,
            ttsVolume: this.ttsVolume,
            ttsRate: this.ttsRate,
            ttsPitch: this.ttsPitch,
            selectedVoice: this.selectedVoice?.name,
            microphoneVolume: this.microphoneVolume
        };
        
        localStorage.setItem('audio_settings', JSON.stringify(settings));
    }

    // Загрузка настроек
    loadSettings() {
        const settings = JSON.parse(localStorage.getItem('audio_settings') || '{}');
        
        this.volume = settings.volume ?? 0.7;
        this.isMuted = settings.isMuted ?? false;
        this.ttsEnabled = settings.ttsEnabled ?? true;
        this.ttsVolume = settings.ttsVolume ?? 1.0;
        this.ttsRate = settings.ttsRate ?? 1.0;
        this.ttsPitch = settings.ttsPitch ?? 1.0;
        this.microphoneVolume = settings.microphoneVolume ?? 1.0;
        
        if (settings.selectedVoice) {
            const voice = this.voices.find(v => v.name === settings.selectedVoice);
            if (voice) {
                this.selectedVoice = voice;
            }
        }
        
        if (this.masterGain) {
            this.masterGain.gain.value = this.isMuted ? 0 : this.volume;
        }
    }

    // Анализ аудио (для визуализации)
    createAnalyser(source) {
        const analyser = this.audioContext.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.8;
        
        source.connect(analyser);
        
        return {
            analyser,
            getFrequencyData: () => {
                const dataArray = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(dataArray);
                return dataArray;
            },
            getWaveformData: () => {
                const dataArray = new Uint8Array(analyser.fftSize);
                analyser.getByteTimeDomainData(dataArray);
                return dataArray;
            },
            getAverageVolume: () => {
                const dataArray = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(dataArray);
                return dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
            }
        };
    }

    // Визуализация аудио
    visualize(analyser, canvas, type = 'frequency') {
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;
        
        const draw = () => {
            requestAnimationFrame(draw);
            
            if (type === 'frequency') {
                const dataArray = analyser.getFrequencyData();
                ctx.fillStyle = 'rgb(0, 0, 0)';
                ctx.fillRect(0, 0, width, height);
                
                const barWidth = (width / dataArray.length) * 2.5;
                let barHeight;
                let x = 0;
                
                for (let i = 0; i < dataArray.length; i++) {
                    barHeight = (dataArray[i] / 255) * height;
                    
                    const gradient = ctx.createLinearGradient(0, height, 0, height - barHeight);
                    gradient.addColorStop(0, '#00ff00');
                    gradient.addColorStop(1, '#ff0000');
                    
                    ctx.fillStyle = gradient;
                    ctx.fillRect(x, height - barHeight, barWidth, barHeight);
                    
                    x += barWidth + 1;
                }
            } else if (type === 'waveform') {
                const dataArray = analyser.getWaveformData();
                ctx.fillStyle = 'rgb(0, 0, 0)';
                ctx.fillRect(0, 0, width, height);
                
                ctx.lineWidth = 2;
                ctx.strokeStyle = '#00ff00';
                ctx.beginPath();
                
                const sliceWidth = width / dataArray.length;
                let x = 0;
                
                for (let i = 0; i < dataArray.length; i++) {
                    const v = dataArray[i] / 128.0;
                    const y = v * height / 2;
                    
                    if (i === 0) {
                        ctx.moveTo(x, y);
                    } else {
                        ctx.lineTo(x, y);
                    }
                    
                    x += sliceWidth;
                }
                
                ctx.lineTo(width, height / 2);
                ctx.stroke();
            }
        };
        
        draw();
    }

    // Генерация тонального сигнала
    generateTone(frequency, duration, type = 'sine') {
        const oscillator = this.audioContext.createOscillator();
        const gainNode = this.audioContext.createGain();
        
        oscillator.type = type;
        oscillator.frequency.value = frequency;
        
        gainNode.gain.setValueAtTime(0.1, this.audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.00001, this.audioContext.currentTime + duration);
        
        oscillator.connect(gainNode);
        gainNode.connect(this.masterGain);
        
        oscillator.start();
        oscillator.stop(this.audioContext.currentTime + duration);
        
        return oscillator;
    }

    // DTMF тоны
    generateDTMF(digit) {
        const dtmfFrequencies = {
            '1': [697, 1209], '2': [697, 1336], '3': [697, 1477],
            '4': [770, 1209], '5': [770, 1336], '6': [770, 1477],
            '7': [852, 1209], '8': [852, 1336], '9': [852, 1477],
            '*': [941, 1209], '0': [941, 1336], '#': [941, 1477]
        };
        
        const frequencies = dtmfFrequencies[digit];
        if (!frequencies) return;
        
        frequencies.forEach(freq => {
            this.generateTone(freq, 0.1);
        });
    }

    // Тест звука
    testSound() {
        this.generateTone(440, 0.2, 'sine'); // Ля
        setTimeout(() => this.generateTone(554, 0.2, 'sine'), 200); // До#
        setTimeout(() => this.generateTone(659, 0.3, 'sine'), 400); // Ми
    }

    // Получение статистики
    getStatistics() {
        return {
            ...this.stats,
            audioContextState: this.audioContext?.state,
            voicesCount: this.voices.length,
            soundsLoaded: this.sounds.size,
            isRecording: this.isRecording
        };
    }

    // Очистка ресурсов
    cleanup() {
        this.stopSpeaking();
        this.stopRingtone();
        this.stopRecording();
        
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        
        this.sounds.clear();
        this.effects.clear();
        this.filters.clear();
        this.audioCache.clear();
    }

    // Сброс настроек
    resetSettings() {
        localStorage.removeItem('audio_settings');
        this.volume = 0.7;
        this.isMuted = false;
        this.ttsEnabled = true;
        this.ttsVolume = 1.0;
        this.ttsRate = 1.0;
        this.ttsPitch = 1.0;
        this.microphoneVolume = 1.0;
        this.selectDefaultVoice();
        
        if (this.masterGain) {
            this.masterGain.gain.value = this.volume;
        }
    }
}

// Создание глобального экземпляра
window.audioManager = new AudioManager();

// Экспорт для модульной системы
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AudioManager;
}

// Инициализация после загрузки страницы
document.addEventListener('DOMContentLoaded', () => {
    console.log('AudioManager ready');
    
    // Запрос разрешения на микрофон при необходимости
    if (window.audioManager.ttsEnabled) {
        window.audioManager.loadVoices();
    }
});

// Обработка закрытия страницы
window.addEventListener('beforeunload', () => {
    if (window.audioManager) {
        window.audioManager.cleanup();
    }
});

// Примеры использования:
/*
// Воспроизвести звук
audioManager.playSound('notification');

// Произнести текст
audioManager.speak('Здравствуйте! Это автоматический обзвон.');

// Запись разговора
await audioManager.startRecording({
    onProgress: (duration) => console.log(`Запись: ${duration}с`),
    onComplete: (recording) => {
        console.log('Запись завершена', recording);
        audioManager.saveRecording(recording.blob);
    }
});

// Настройка TTS
audioManager.setTTSRate(1.2);
audioManager.setTTSPitch(1.0);
audioManager.setTTSVolume(0.8);

// Получить список голосов
const voices = audioManager.getVoices();
console.log('Доступные голоса:', voices);

// Тест звука
audioManager.testSound();
*/
