// blacklist.js - Полный модуль управления черным списком

class BlacklistManager {
    constructor() {
        // Основные хранилища
        this.blacklist = new Map(); // Быстрый доступ по номеру
        this.blacklistArray = []; // Для сериализации
        this.patterns = []; // Регулярные выражения для паттернов
        this.wildcards = new Map(); // Wildcard паттерны (например, 7495*)
        
        // Статистика
        this.stats = {
            totalBlocked: 0,
            autoBlocks: 0,
            manualBlocks: 0,
            temporaryBlocks: 0,
            expiredBlocks: 0
        };
        
        // Кеши и оптимизация
        this.cache = new Map();
        this.cacheSize = 1000;
        this.cacheHits = 0;
        this.cacheMisses = 0;
        
        // Настройки
        this.settings = {
            autoBlockScam: true,
            autoBlockSpam: true,
            autoBlockRobocalls: true,
            blockPrivateNumbers: false,
            blockUnknownNumbers: false,
            blockInternational: false,
            allowedCountries: ['RU', 'BY', 'KZ'],
            maxFailedAttempts: 5,
            blockDuration: 30 * 24 * 60 * 60 * 1000, // 30 дней
            notifyOnBlock: true,
            syncWithGlobal: false
        };
        
        // Глобальные черные списки (внешние API)
        this.globalBlacklists = [
            { name: 'FCC Spam List', url: '/api/blacklist/fcc', enabled: false },
            { name: 'Robocall Block List', url: '/api/blacklist/robocall', enabled: false },
            { name: 'Scam Numbers Database', url: '/api/blacklist/scam', enabled: false }
        ];
        
        // Очередь синхронизации
        this.syncQueue = [];
        this.isSyncing = false;
        
        // Подписчики на события
        this.subscribers = [];
        
        this.initialize();
    }

    // Инициализация
    async initialize() {
        try {
            // Загрузка черного списка из localStorage
            this.loadFromStorage();
            
            // Загрузка настроек
            this.loadSettings();
            
            // Загрузка статистики
            this.loadStats();
            
            // Компиляция паттернов
            this.compilePatterns();
            
            // Проверка устаревших записей
            this.cleanupExpired();
            
            // Синхронизация с глобальными списками если включено
            if (this.settings.syncWithGlobal) {
                await this.syncWithGlobalBlacklists();
            }
            
            // Запуск периодической очистки
            this.startPeriodicCleanup();
            
            console.log('BlacklistManager initialized:', {
                total: this.blacklist.size,
                patterns: this.patterns.length,
                wildcards: this.wildcards.size
            });
        } catch (error) {
            console.error('Failed to initialize BlacklistManager:', error);
        }
    }

    // Загрузка из хранилища
    loadFromStorage() {
        try {
            const stored = localStorage.getItem('blacklist');
            if (stored) {
                const data = JSON.parse(stored);
                this.blacklistArray = data;
                
                // Восстановление Map
                data.forEach(item => {
                    if (item.number) {
                        this.blacklist.set(this.normalizeNumber(item.number), item);
                    }
                });
            }
            
            // Загрузка паттернов
            const patternsStored = localStorage.getItem('blacklist_patterns');
            if (patternsStored) {
                this.patterns = JSON.parse(patternsStored);
            }
            
            // Загрузка wildcard паттернов
            const wildcardsStored = localStorage.getItem('blacklist_wildcards');
            if (wildcardsStored) {
                const wildcards = JSON.parse(wildcardsStored);
                wildcards.forEach(w => {
                    this.wildcards.set(w.prefix, w);
                });
            }
        } catch (error) {
            console.error('Failed to load blacklist from storage:', error);
        }
    }

    // Сохранение в хранилище
    saveToStorage() {
        try {
            // Сохранение основного списка
            const data = Array.from(this.blacklist.values());
            localStorage.setItem('blacklist', JSON.stringify(data));
            this.blacklistArray = data;
            
            // Сохранение паттернов
            localStorage.setItem('blacklist_patterns', JSON.stringify(this.patterns));
            
            // Сохранение wildcard паттернов
            const wildcards = Array.from(this.wildcards.values());
            localStorage.setItem('blacklist_wildcards', JSON.stringify(wildcards));
            
            this.notifySubscribers('saved', { count: this.blacklist.size });
        } catch (error) {
            console.error('Failed to save blacklist:', error);
        }
    }

    // Загрузка настроек
    loadSettings() {
        try {
            const stored = localStorage.getItem('blacklist_settings');
            if (stored) {
                this.settings = { ...this.settings, ...JSON.parse(stored) };
            }
        } catch (error) {
            console.error('Failed to load blacklist settings:', error);
        }
    }

    // Сохранение настроек
    saveSettings() {
        try {
            localStorage.setItem('blacklist_settings', JSON.stringify(this.settings));
            this.notifySubscribers('settings_updated', this.settings);
        } catch (error) {
            console.error('Failed to save blacklist settings:', error);
        }
    }

    // Загрузка статистики
    loadStats() {
        try {
            const stored = localStorage.getItem('blacklist_stats');
            if (stored) {
                this.stats = { ...this.stats, ...JSON.parse(stored) };
            }
        } catch (error) {
            console.error('Failed to load blacklist stats:', error);
        }
    }

    // Сохранение статистики
    saveStats() {
        try {
            localStorage.setItem('blacklist_stats', JSON.stringify(this.stats));
        } catch (error) {
            console.error('Failed to save blacklist stats:', error);
        }
    }

    // Добавление номера в черный список
    add(number, options = {}) {
        const {
            reason = 'manual',
            category = 'general',
            notes = '',
            duration = null, // null = навсегда
            addedBy = 'user',
            notify = true
        } = options;
        
        const normalized = this.normalizeNumber(number);
        
        // Проверка существования
        if (this.blacklist.has(normalized)) {
            return { success: false, error: 'Number already in blacklist' };
        }
        
        // Валидация номера
        if (!this.validateNumber(normalized)) {
            return { success: false, error: 'Invalid phone number' };
        }
        
        const entry = {
            id: this.generateId(),
            number: normalized,
            originalNumber: number,
            reason: reason,
            category: category,
            notes: notes,
            addedAt: new Date().toISOString(),
            addedBy: addedBy,
            expiresAt: duration ? new Date(Date.now() + duration).toISOString() : null,
            blockCount: 0,
            lastBlocked: null,
            metadata: {
                source: options.source || 'local',
                priority: options.priority || 1,
                tags: options.tags || []
            }
        };
        
        // Добавление в Map
        this.blacklist.set(normalized, entry);
        
        // Обновление статистики
        this.stats.totalBlocked++;
        if (addedBy === 'auto') {
            this.stats.autoBlocks++;
        } else {
            this.stats.manualBlocks++;
        }
        if (duration) {
            this.stats.temporaryBlocks++;
        }
        
        // Очистка кеша для этого номера
        this.cache.delete(normalized);
        
        // Сохранение
        this.saveToStorage();
        this.saveStats();
        
        // Уведомление
        if (notify && this.settings.notifyOnBlock) {
            this.showNotification(`Номер ${number} добавлен в черный список`);
        }
        
        this.notifySubscribers('added', entry);
        
        return { success: true, entry };
    }

    // Добавление нескольких номеров
    addMultiple(numbers, options = {}) {
        const results = {
            success: [],
            failed: [],
            total: numbers.length
        };
        
        numbers.forEach(number => {
            const result = this.add(number, options);
            if (result.success) {
                results.success.push(number);
            } else {
                results.failed.push({ number, error: result.error });
            }
        });
        
        return results;
    }

    // Добавление паттерна
    addPattern(pattern, options = {}) {
        const {
            description = '',
            category = 'pattern',
            isRegex = false
        } = options;
        
        const patternEntry = {
            id: this.generateId(),
            pattern: pattern,
            description: description,
            category: category,
            isRegex: isRegex,
            addedAt: new Date().toISOString(),
            matchCount: 0,
            lastMatched: null
        };
        
        // Валидация паттерна
        if (isRegex) {
            try {
                new RegExp(pattern);
            } catch (e) {
                return { success: false, error: 'Invalid regular expression' };
            }
        }
        
        this.patterns.push(patternEntry);
        this.saveToStorage();
        
        this.notifySubscribers('pattern_added', patternEntry);
        
        return { success: true, entry: patternEntry };
    }

    // Добавление wildcard паттерна
    addWildcard(prefix, options = {}) {
        const {
            description = '',
            category = 'wildcard'
        } = options;
        
        const normalized = this.normalizeNumber(prefix);
        
        if (this.wildcards.has(normalized)) {
            return { success: false, error: 'Wildcard already exists' };
        }
        
        const entry = {
            id: this.generateId(),
            prefix: normalized,
            description: description,
            category: category,
            addedAt: new Date().toISOString(),
            matchCount: 0,
            lastMatched: null
        };
        
        this.wildcards.set(normalized, entry);
        this.saveToStorage();
        
        this.notifySubscribers('wildcard_added', entry);
        
        return { success: true, entry };
    }

    // Проверка номера в черном списке
    isBlocked(number) {
        const normalized = this.normalizeNumber(number);
        
        // Проверка кеша
        if (this.cache.has(normalized)) {
            this.cacheHits++;
            return this.cache.get(normalized);
        }
        
        this.cacheMisses++;
        
        let blocked = false;
        let reason = null;
        let entry = null;
        
        // 1. Проверка точного совпадения
        if (this.blacklist.has(normalized)) {
            entry = this.blacklist.get(normalized);
            
            // Проверка срока действия
            if (this.isExpired(entry)) {
                this.remove(normalized);
            } else {
                blocked = true;
                reason = entry.reason;
                
                // Обновление счетчика
                entry.blockCount++;
                entry.lastBlocked = new Date().toISOString();
                this.blacklist.set(normalized, entry);
            }
        }
        
        // 2. Проверка wildcard паттернов
        if (!blocked) {
            for (const [prefix, wildcardEntry] of this.wildcards) {
                if (normalized.startsWith(prefix)) {
                    blocked = true;
                    reason = `Wildcard: ${prefix}*`;
                    entry = wildcardEntry;
                    wildcardEntry.matchCount++;
                    wildcardEntry.lastMatched = new Date().toISOString();
                    break;
                }
            }
        }
        
        // 3. Проверка регулярных выражений
        if (!blocked) {
            for (const pattern of this.patterns) {
                if (pattern.isRegex) {
                    const regex = new RegExp(pattern.pattern);
                    if (regex.test(normalized)) {
                        blocked = true;
                        reason = `Pattern: ${pattern.description || pattern.pattern}`;
                        entry = pattern;
                        pattern.matchCount++;
                        pattern.lastMatched = new Date().toISOString();
                        break;
                    }
                } else if (normalized.includes(pattern.pattern)) {
                    blocked = true;
                    reason = `Contains: ${pattern.description || pattern.pattern}`;
                    entry = pattern;
                    pattern.matchCount++;
                    pattern.lastMatched = new Date().toISOString();
                    break;
                }
            }
        }
        
        // 4. Проверка настроек
        if (!blocked) {
            const settingsCheck = this.checkSettingsBlock(normalized);
            if (settingsCheck.blocked) {
                blocked = true;
                reason = settingsCheck.reason;
            }
        }
        
        // Кеширование результата
        this.cache.set(normalized, blocked);
        this.limitCacheSize();
        
        // Сохранение если были обновления счетчиков
        if (entry && entry.matchCount !== undefined) {
            this.saveToStorage();
        }
        
        return blocked;
    }

    // Проверка блокировки по настройкам
    checkSettingsBlock(number) {
        // Приватные номера
        if (this.settings.blockPrivateNumbers && this.isPrivateNumber(number)) {
            return { blocked: true, reason: 'Private number' };
        }
        
        // Неизвестные номера
        if (this.settings.blockUnknownNumbers && number === 'unknown') {
            return { blocked: true, reason: 'Unknown number' };
        }
        
        // Международные номера
        if (this.settings.blockInternational && this.isInternational(number)) {
            const country = this.getCountryCode(number);
            if (!this.settings.allowedCountries.includes(country)) {
                return { blocked: true, reason: 'International (blocked)' };
            }
        }
        
        return { blocked: false };
    }

    // Получение информации о блокировке
    getBlockInfo(number) {
        const normalized = this.normalizeNumber(number);
        
        if (!this.isBlocked(normalized)) {
            return { blocked: false };
        }
        
        const entry = this.blacklist.get(normalized);
        
        return {
            blocked: true,
            number: normalized,
            reason: entry?.reason || 'Unknown',
            category: entry?.category || 'general',
            addedAt: entry?.addedAt || null,
            expiresAt: entry?.expiresAt || null,
            blockCount: entry?.blockCount || 0,
            notes: entry?.notes || ''
        };
    }

    // Удаление из черного списка
    remove(number) {
        const normalized = this.normalizeNumber(number);
        
        if (!this.blacklist.has(normalized)) {
            return false;
        }
        
        const entry = this.blacklist.get(normalized);
        this.blacklist.delete(normalized);
        
        // Очистка кеша
        this.cache.delete(normalized);
        
        // Обновление статистики
        if (entry.expiresAt) {
            this.stats.expiredBlocks++;
        }
        
        this.saveToStorage();
        this.saveStats();
        
        this.notifySubscribers('removed', { number: normalized, entry });
        
        return true;
    }

    // Удаление паттерна
    removePattern(patternId) {
        const index = this.patterns.findIndex(p => p.id === patternId);
        if (index === -1) return false;
        
        const pattern = this.patterns[index];
        this.patterns.splice(index, 1);
        
        // Очистка кеша так как паттерн мог влиять на многие номера
        this.cache.clear();
        
        this.saveToStorage();
        this.notifySubscribers('pattern_removed', pattern);
        
        return true;
    }

    // Удаление wildcard
    removeWildcard(prefix) {
        const normalized = this.normalizeNumber(prefix);
        
        if (!this.wildcards.has(normalized)) {
            return false;
        }
        
        const entry = this.wildcards.get(normalized);
        this.wildcards.delete(normalized);
        
        // Очистка кеша
        this.cache.clear();
        
        this.saveToStorage();
        this.notifySubscribers('wildcard_removed', entry);
        
        return true;
    }

    // Автоматическое добавление при множественных сбросах
    autoBlockOnFailedAttempts(number) {
        const key = `failed_attempts_${number}`;
        const attempts = (parseInt(localStorage.getItem(key)) || 0) + 1;
        
        localStorage.setItem(key, attempts);
        
        if (attempts >= this.settings.maxFailedAttempts) {
            this.add(number, {
                reason: 'Multiple failed attempts',
                category: 'auto_block',
                addedBy: 'auto',
                duration: this.settings.blockDuration,
                notes: `Auto-blocked after ${attempts} failed attempts`
            });
            
            localStorage.removeItem(key);
            return true;
        }
        
        // Автоочистка через 24 часа
        setTimeout(() => {
            localStorage.removeItem(key);
        }, 24 * 60 * 60 * 1000);
        
        return false;
    }

    // Очистка устаревших записей
    cleanupExpired() {
        const now = new Date();
        let removed = 0;
        
        for (const [number, entry] of this.blacklist) {
            if (this.isExpired(entry)) {
                this.blacklist.delete(number);
                this.cache.delete(number);
                removed++;
                this.stats.expiredBlocks++;
            }
        }
        
        if (removed > 0) {
            this.saveToStorage();
            this.saveStats();
            console.log(`Cleaned up ${removed} expired blacklist entries`);
        }
        
        return removed;
    }

    // Проверка истечения срока
    isExpired(entry) {
        if (!entry.expiresAt) return false;
        return new Date(entry.expiresAt) < new Date();
    }

    // Периодическая очистка
    startPeriodicCleanup() {
        setInterval(() => {
            this.cleanupExpired();
        }, 60 * 60 * 1000); // Каждый час
    }

    // Импорт черного списка
    importBlacklist(data, format = 'json') {
        try {
            let numbers = [];
            
            if (format === 'json') {
                const parsed = JSON.parse(data);
                numbers = parsed.map(item => item.number || item);
            } else if (format === 'csv') {
                numbers = data.split('\n')
                    .map(line => line.split(',')[0].trim())
                    .filter(num => num && !num.startsWith('#'));
            } else if (format === 'txt') {
                numbers = data.split('\n')
                    .map(line => line.trim())
                    .filter(num => num && !num.startsWith('#'));
            }
            
            const result = this.addMultiple(numbers, {
                reason: 'imported',
                source: 'import'
            });
            
            this.notifySubscribers('imported', result);
            
            return result;
        } catch (error) {
            console.error('Failed to import blacklist:', error);
            return { success: [], failed: [], error: error.message };
        }
    }

    // Экспорт черного списка
    exportBlacklist(format = 'json') {
        const data = Array.from(this.blacklist.values());
        
        if (format === 'json') {
            return JSON.stringify(data, null, 2);
        } else if (format === 'csv') {
            const headers = ['Number', 'Reason', 'Category', 'Added At', 'Expires At'];
            const rows = data.map(entry => [
                entry.number,
                entry.reason,
                entry.category,
                entry.addedAt,
                entry.expiresAt || ''
            ]);
            
            return [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
            ].join('\n');
        } else if (format === 'txt') {
            return data.map(entry => entry.number).join('\n');
        }
    }

    // Синхронизация с глобальными списками
    async syncWithGlobalBlacklists() {
        if (this.isSyncing) return;
        
        this.isSyncing = true;
        
        try {
            for (const list of this.globalBlacklists) {
                if (!list.enabled) continue;
                
                const response = await fetch(list.url);
                const data = await response.json();
                
                const result = this.addMultiple(data.numbers || data, {
                    reason: `Global: ${list.name}`,
                    source: 'global',
                    priority: 2
                });
                
                console.log(`Synced with ${list.name}:`, result);
            }
            
            this.notifySubscribers('synced', { success: true });
        } catch (error) {
            console.error('Failed to sync with global blacklists:', error);
            this.notifySubscribers('synced', { success: false, error });
        } finally {
            this.isSyncing = false;
        }
    }

    // Получение статистики
    getStatistics() {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        
        const todayBlocks = Array.from(this.blacklist.values())
            .filter(entry => new Date(entry.addedAt) >= today).length;
        
        return {
            ...this.stats,
            totalActive: this.blacklist.size,
            patternsCount: this.patterns.length,
            wildcardsCount: this.wildcards.size,
            todayBlocks: todayBlocks,
            cacheEfficiency: this.cacheHits / (this.cacheHits + this.cacheMisses) || 0,
            topCategories: this.getTopCategories(),
            topReasons: this.getTopReasons()
        };
    }

    // Топ категорий
    getTopCategories(limit = 5) {
        const categories = {};
        
        for (const entry of this.blacklist.values()) {
            categories[entry.category] = (categories[entry.category] || 0) + 1;
        }
        
        return Object.entries(categories)
            .sort((a, b) => b[1] - a[1])
            .slice(0, limit)
            .map(([name, count]) => ({ name, count }));
    }

    // Топ причин блокировки
    getTopReasons(limit = 5) {
        const reasons = {};
        
        for (const entry of this.blacklist.values()) {
            reasons[entry.reason] = (reasons[entry.reason] || 0) + 1;
        }
        
        return Object.entries(reasons)
            .sort((a, b) => b[1] - a[1])
            .slice(0, limit)
            .map(([name, count]) => ({ name, count }));
    }

    // Получение всех записей с пагинацией
    getEntries(page = 1, limit = 50, filters = {}) {
        let entries = Array.from(this.blacklist.values());
        
        // Фильтрация
        if (filters.category) {
            entries = entries.filter(e => e.category === filters.category);
        }
        if (filters.reason) {
            entries = entries.filter(e => e.reason === filters.reason);
        }
        if (filters.search) {
            const search = filters.search.toLowerCase();
            entries = entries.filter(e => 
                e.number.includes(search) || 
                e.notes?.toLowerCase().includes(search)
            );
        }
        
        // Сортировка
        entries.sort((a, b) => new Date(b.addedAt) - new Date(a.addedAt));
        
        // Пагинация
        const total = entries.length;
        const start = (page - 1) * limit;
        const end = start + limit;
        
        return {
            entries: entries.slice(start, end),
            total,
            page,
            totalPages: Math.ceil(total / limit)
        };
    }

    // Поиск по черному списку
    search(query) {
        const normalized = this.normalizeNumber(query);
        const results = [];
        
        // Поиск по точному номеру
        if (this.blacklist.has(normalized)) {
            results.push({
                type: 'exact',
                entry: this.blacklist.get(normalized)
            });
        }
        
        // Поиск по wildcard
        for (const [prefix, entry] of this.wildcards) {
            if (normalized.startsWith(prefix)) {
                results.push({
                    type: 'wildcard',
                    entry: entry
                });
            }
        }
        
        // Поиск по подстроке
        for (const entry of this.blacklist.values()) {
            if (entry.number.includes(normalized) && 
                entry.number !== normalized) {
                results.push({
                    type: 'partial',
                    entry: entry
                });
            }
        }
        
        return results;
    }

    // Проверка нескольких номеров
    checkMultiple(numbers) {
        const results = {};
        
        numbers.forEach(number => {
            results[number] = this.isBlocked(number);
        });
        
        return results;
    }

    // Очистка всего черного списка
    clearAll() {
        const count = this.blacklist.size;
        
        this.blacklist.clear();
        this.patterns = [];
        this.wildcards.clear();
        this.cache.clear();
        
        this.saveToStorage();
        
        this.notifySubscribers('cleared', { count });
        
        return count;
    }

    // Сброс статистики
    resetStats() {
        this.stats = {
            totalBlocked: this.blacklist.size,
            autoBlocks: 0,
            manualBlocks: 0,
            temporaryBlocks: 0,
            expiredBlocks: 0
        };
        
        this.saveStats();
    }

    // Валидация номера
    validateNumber(number) {
        // Базовая проверка на цифры и допустимые символы
        const cleaned = number.replace(/[\s\-\(\)\+]/g, '');
        
        // Проверка длины
        if (cleaned.length < 10 || cleaned.length > 15) {
            return false;
        }
        
        // Проверка на только цифры и +
        return /^\+?\d+$/.test(cleaned);
    }

    // Нормализация номера
    normalizeNumber(number) {
        if (!number) return '';
        
        // Удаление всех нецифровых символов кроме +
        let normalized = number.replace(/[^\d\+]/g, '');
        
        // Приведение к международному формату
        if (normalized.startsWith('8')) {
            normalized = '+7' + normalized.substring(1);
        } else if (normalized.length === 10) {
            normalized = '+7' + normalized;
        }
        
        return normalized;
    }

    // Проверка на приватный номер
    isPrivateNumber(number) {
        const privateIndicators = ['private', 'unknown', 'hidden', 'anonymous', ''];
        return privateIndicators.includes(number.toLowerCase());
    }

    // Проверка на международный номер
    isInternational(number) {
        const country = this.getCountryCode(number);
        return country && country !== 'RU';
    }

    // Получение кода страны
    getCountryCode(number) {
        const match = number.match(/^\+(\d{1,3})/);
        if (!match) return null;
        
        const code = match[1];
        const countryCodes = {
            '1': 'US',
            '7': 'RU',
            '44': 'UK',
            '49': 'DE',
            '33': 'FR',
            '39': 'IT',
            '86': 'CN',
            '81': 'JP'
        };
        
        return countryCodes[code] || code;
    }

    // Ограничение размера кеша
    limitCacheSize() {
        if (this.cache.size > this.cacheSize) {
            const entries = Array.from(this.cache.entries());
            const toDelete = entries.slice(0, Math.floor(this.cacheSize * 0.2));
            toDelete.forEach(([key]) => this.cache.delete(key));
        }
    }

    // Показ уведомления
    showNotification(message) {
        if (Notification.permission === 'granted') {
            new Notification('Черный список', {
                body: message,
                icon: '/assets/icons/blocked.png'
            });
        }
        
        // Интеграция с системой уведомлений
        if (window.notificationManager) {
            window.notificationManager.show({
                title: 'Черный список',
                message: message,
                type: 'info'
            });
        }
    }

    // Генерация ID
    generateId() {
        return 'bl_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    // Подписка на события
    subscribe(callback) {
        this.subscribers.push(callback);
    }

    // Отписка
    unsubscribe(callback) {
        this.subscribers = this.subscribers.filter(cb => cb !== callback);
    }

    // Уведомление подписчиков
    notifySubscribers(event, data) {
        this.subscribers.forEach(callback => {
            try {
                callback(event, data);
            } catch (error) {
                console.error('Error in subscriber callback:', error);
            }
        });
    }

    // Получение размера черного списка
    get size() {
        return this.blacklist.size;
    }

    // Проверка пустоты
    get isEmpty() {
        return this.blacklist.size === 0;
    }
}

// Создание глобального экземпляра
window.blacklistManager = new BlacklistManager();

// Экспорт для модульной системы
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BlacklistManager;
}

// Примеры использования:
/*
// Добавление номера
blacklistManager.add('+79161234567', {
    reason: 'Спам',
    category: 'spam',
    notes: 'Назойливая реклама'
});

// Добавление паттерна
blacklistManager.addPattern('^\\+7495\\d{7}$', {
    description: 'Все московские номера',
    isRegex: true
});

// Добавление wildcard
blacklistManager.addWildcard('+7800', {
    description: 'Бесплатные номера'
});

// Проверка номера
if (blacklistManager.isBlocked('+79161234567')) {
    console.log('Номер в черном списке');
}

// Получение информации
const info = blacklistManager.getBlockInfo('+79161234567');

// Импорт списка
blacklistManager.importBlacklist(jsonData, 'json');

// Экспорт списка
const csv = blacklistManager.exportBlacklist('csv');

// Статистика
const stats = blacklistManager.getStatistics();

// Поиск
const results = blacklistManager.search('7495');
*/
