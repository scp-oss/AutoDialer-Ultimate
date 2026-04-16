// utils.js - Общие утилиты и вспомогательные функции
// Используется всеми модулями приложения

const Utils = {
    // =============================================
    // Форматирование даты и времени
    // =============================================
    
    /**
     * Форматирование даты и времени
     * @param {string|Date} dateStr - Дата
     * @param {string} format - Формат ('full', 'date', 'time', 'short')
     * @returns {string} Отформатированная дата
     */
    formatDateTime(dateStr, format = 'full') {
        if (!dateStr) return '—';
        
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return '—';
        
        const options = {
            full: {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            },
            date: {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            },
            time: {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            },
            short: {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            }
        };
        
        return date.toLocaleString('ru-RU', options[format] || options.full).replace(',', '');
    },
    
    /**
     * Форматирование даты (кратко)
     * @param {string|Date} dateStr - Дата
     * @returns {string} Дата в формате ДД.ММ.ГГГГ
     */
    formatDate(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return '—';
        
        return date.toLocaleDateString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric'
        });
    },
    
    /**
     * Форматирование времени
     * @param {string|Date} dateStr - Дата
     * @returns {string} Время в формате ЧЧ:ММ:СС
     */
    formatTime(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return '—';
        
        return date.toLocaleTimeString('ru-RU', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    },
    
    /**
     * Относительное время (например, "5 минут назад")
     * @param {string|Date} dateStr - Дата
     * @returns {string} Относительное время
     */
    formatRelativeTime(dateStr) {
        if (!dateStr) return '—';
        
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return '—';
        
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);
        
        if (diff < 60) return 'только что';
        if (diff < 3600) return `${Math.floor(diff / 60)} мин. назад`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} ч. назад`;
        if (diff < 2592000) return `${Math.floor(diff / 86400)} дн. назад`;
        
        return this.formatDate(dateStr);
    },
    
    // =============================================
    // Форматирование чисел и размеров
    // =============================================
    
    /**
     * Форматирование длительности
     * @param {number} seconds - Количество секунд
     * @returns {string} Отформатированная длительность
     */
    formatDuration(seconds) {
        if (!seconds || seconds === 0) return '0 сек';
        if (seconds < 0) return '—';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        const parts = [];
        if (hours > 0) parts.push(`${hours} ч`);
        if (minutes > 0) parts.push(`${minutes} мин`);
        if (secs > 0 || parts.length === 0) parts.push(`${secs} сек`);
        
        return parts.join(' ');
    },
    
    /**
     * Форматирование длительности в формате ММ:СС
     * @param {number} seconds - Количество секунд
     * @returns {string} Длительность в формате ММ:СС или ЧЧ:ММ:СС
     */
    formatDurationShort(seconds) {
        if (!seconds || seconds === 0) return '0:00';
        if (seconds < 0) return '—';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    },
    
    /**
     * Форматирование размера файла
     * @param {number} bytes - Размер в байтах
     * @returns {string} Отформатированный размер
     */
    formatFileSize(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let size = bytes;
        let unitIndex = 0;
        
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        
        return `${size.toFixed(unitIndex === 0 ? 0 : 2)} ${units[unitIndex]}`;
    },
    
    /**
     * Форматирование числа с разделителями тысяч
     * @param {number} num - Число
     * @returns {string} Отформатированное число
     */
    formatNumber(num) {
        if (num === null || num === undefined) return '0';
        return num.toLocaleString('ru-RU');
    },
    
    /**
     * Форматирование процентов
     * @param {number} value - Значение
     * @param {number} total - Общее количество
     * @returns {string} Процент с одним знаком после запятой
     */
    formatPercent(value, total) {
        if (!total) return '0%';
        return `${((value / total) * 100).toFixed(1)}%`;
    },
    
    // =============================================
    // Форматирование телефона и данных
    // =============================================
    
    /**
     * Форматирование номера телефона
     * @param {string} phone - Номер телефона
     * @returns {string} Отформатированный номер
     */
    formatPhoneNumber(phone) {
        if (!phone) return '—';
        
        const cleaned = phone.replace(/\D/g, '');
        
        // Российский номер (11 цифр)
        if (cleaned.length === 11 && (cleaned.startsWith('7') || cleaned.startsWith('8'))) {
            const country = cleaned[0] === '8' ? '8' : '+7';
            return `${country} (${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7, 9)}-${cleaned.slice(9, 11)}`;
        }
        
        // Международный формат
        if (cleaned.length > 11) {
            return `+${cleaned}`;
        }
        
        // Простой формат
        if (cleaned.length === 10) {
            return `(${cleaned.slice(0, 3)}) ${cleaned.slice(3, 6)}-${cleaned.slice(6, 8)}-${cleaned.slice(8, 10)}`;
        }
        
        return phone;
    },
    
    /**
     * Очистка номера телефона (только цифры)
     * @param {string} phone - Номер телефона
     * @returns {string} Только цифры
     */
    cleanPhoneNumber(phone) {
        if (!phone) return '';
        return phone.replace(/\D/g, '');
    },
    
    /**
     * Форматирование JSON для отображения
     * @param {object|string} data - Данные
     * @returns {string} Отформатированный JSON
     */
    formatJson(data) {
        try {
            const obj = typeof data === 'string' ? JSON.parse(data) : data;
            return JSON.stringify(obj, null, 2);
        } catch {
            return String(data);
        }
    },
    
    // =============================================
    // Строковые операции
    // =============================================
    
    /**
     * Экранирование HTML
     * @param {string} text - Текст
     * @returns {string} Экранированный текст
     */
    escapeHtml(text) {
        if (!text && text !== 0) return '';
        
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    },
    
    /**
     * Обрезка текста с многоточием
     * @param {string} text - Текст
     * @param {number} maxLength - Максимальная длина
     * @returns {string} Обрезанный текст
     */
    truncate(text, maxLength = 100) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength - 3) + '...';
    },
    
    /**
     * Преобразование в URL-безопасную строку (slug)
     * @param {string} text - Текст
     * @returns {string} Slug
     */
    slugify(text) {
        if (!text) return '';
        
        // Транслитерация для русского
        const ruMap = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
        };
        
        let result = text.toLowerCase();
        for (const [ru, en] of Object.entries(ruMap)) {
            result = result.replace(new RegExp(ru, 'g'), en);
        }
        
        return result
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '');
    },
    
    /**
     * Капитализация первой буквы
     * @param {string} text - Текст
     * @returns {string} Текст с заглавной первой буквой
     */
    capitalize(text) {
        if (!text) return '';
        return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
    },
    
    // =============================================
    // Работа с URL и параметрами
    // =============================================
    
    /**
     * Получение параметра из URL
     * @param {string} name - Имя параметра
     * @returns {string|null} Значение параметра
     */
    getUrlParam(name) {
        const params = new URLSearchParams(window.location.search);
        return params.get(name);
    },
    
    /**
     * Установка параметра в URL
     * @param {string} name - Имя параметра
     * @param {string} value - Значение
     */
    setUrlParam(name, value) {
        const url = new URL(window.location);
        if (value) {
            url.searchParams.set(name, value);
        } else {
            url.searchParams.delete(name);
        }
        window.history.replaceState({}, '', url);
    },
    
    /**
     * Построение строки запроса
     * @param {object} params - Объект с параметрами
     * @returns {string} Строка запроса
     */
    buildQueryString(params) {
        const parts = [];
        for (const [key, value] of Object.entries(params)) {
            if (value !== null && value !== undefined && value !== '') {
                parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
            }
        }
        return parts.length ? '?' + parts.join('&') : '';
    },
    
    // =============================================
    // Работа с DOM
    // =============================================
    
    /**
     * Создание DOM элемента
     * @param {string} tag - Тег
     * @param {object} attrs - Атрибуты
     * @param {string|Node|Array} children - Дочерние элементы
     * @returns {HTMLElement} Созданный элемент
     */
    createElement(tag, attrs = {}, children = null) {
        const el = document.createElement(tag);
        
        for (const [key, value] of Object.entries(attrs)) {
            if (key === 'class' || key === 'className') {
                el.className = value;
            } else if (key === 'style' && typeof value === 'object') {
                Object.assign(el.style, value);
            } else if (key.startsWith('on') && typeof value === 'function') {
                el.addEventListener(key.slice(2).toLowerCase(), value);
            } else {
                el.setAttribute(key, value);
            }
        }
        
        if (children) {
            if (typeof children === 'string') {
                el.textContent = children;
            } else if (Array.isArray(children)) {
                children.forEach(child => el.appendChild(child));
            } else if (children instanceof Node) {
                el.appendChild(children);
            }
        }
        
        return el;
    },
    
    /**
     * Показать элемент
     * @param {string|HTMLElement} element - Элемент или селектор
     */
    show(element) {
        const el = typeof element === 'string' ? document.querySelector(element) : element;
        if (el) el.style.display = '';
    },
    
    /**
     * Скрыть элемент
     * @param {string|HTMLElement} element - Элемент или селектор
     */
    hide(element) {
        const el = typeof element === 'string' ? document.querySelector(element) : element;
        if (el) el.style.display = 'none';
    },
    
    /**
     * Переключить видимость элемента
     * @param {string|HTMLElement} element - Элемент или селектор
     */
    toggle(element) {
        const el = typeof element === 'string' ? document.querySelector(element) : element;
        if (el) {
            el.style.display = el.style.display === 'none' ? '' : 'none';
        }
    },
    
    // =============================================
    // Работа с localStorage
    // =============================================
    
    /**
     * Сохранить в localStorage
     * @param {string} key - Ключ
     * @param {any} value - Значение
     */
    setStorage(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (e) {
            console.error('Storage set failed:', e);
        }
    },
    
    /**
     * Получить из localStorage
     * @param {string} key - Ключ
     * @param {any} defaultValue - Значение по умолчанию
     * @returns {any} Значение
     */
    getStorage(key, defaultValue = null) {
        try {
            const value = localStorage.getItem(key);
            return value ? JSON.parse(value) : defaultValue;
        } catch (e) {
            console.error('Storage get failed:', e);
            return defaultValue;
        }
    },
    
    /**
     * Удалить из localStorage
     * @param {string} key - Ключ
     */
    removeStorage(key) {
        localStorage.removeItem(key);
    },
    
    // =============================================
    // Работа с буфером обмена
    // =============================================
    
    /**
     * Копировать текст в буфер обмена
     * @param {string} text - Текст для копирования
     * @returns {Promise<boolean>} Успешно ли скопировано
     */
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // Fallback для старых браузеров
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            const success = document.execCommand('copy');
            document.body.removeChild(textarea);
            return success;
        }
    },
    
    // =============================================
    // Валидация
    // =============================================
    
    /**
     * Валидация email
     * @param {string} email - Email
     * @returns {boolean} Валиден ли email
     */
    isValidEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email);
    },
    
    /**
     * Валидация телефона
     * @param {string} phone - Телефон
     * @returns {boolean} Валиден ли телефон
     */
    isValidPhone(phone) {
        const cleaned = phone.replace(/\D/g, '');
        return cleaned.length >= 10 && cleaned.length <= 15;
    },
    
    /**
     * Валидация URL
     * @param {string} url - URL
     * @returns {boolean} Валиден ли URL
     */
    isValidUrl(url) {
        try {
            new URL(url);
            return true;
        } catch {
            return false;
        }
    },
    
    // =============================================
    // Debounce и Throttle
    // =============================================
    
    /**
     * Debounce - отложенное выполнение функции
     * @param {Function} func - Функция
     * @param {number} wait - Задержка в мс
     * @returns {Function} Обёрнутая функция
     */
    debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    /**
     * Throttle - выполнение не чаще чем раз в период
     * @param {Function} func - Функция
     * @param {number} limit - Период в мс
     * @returns {Function} Обёрнутая функция
     */
    throttle(func, limit = 300) {
        let inThrottle;
        return function executedFunction(...args) {
            if (!inThrottle) {
                func(...args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },
    
    // =============================================
    // Генерация случайных значений
    // =============================================
    
    /**
     * Генерация случайного ID
     * @param {number} length - Длина
     * @returns {string} Случайный ID
     */
    generateId(length = 8) {
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        let result = '';
        for (let i = 0; i < length; i++) {
            result += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        return result;
    },
    
    /**
     * Генерация UUID v4
     * @returns {string} UUID
     */
    generateUuid() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    },
    
    /**
     * Генерация случайного цвета
     * @returns {string} Цвет в HEX
     */
    generateColor() {
        const letters = '0123456789ABCDEF';
        let color = '#';
        for (let i = 0; i < 6; i++) {
            color += letters[Math.floor(Math.random() * 16)];
        }
        return color;
    },
    
    /**
     * Генерация случайного числа в диапазоне
     * @param {number} min - Минимум
     * @param {number} max - Максимум
     * @returns {number} Случайное число
     */
    random(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    },
    
    // =============================================
    // Работа с объектами и массивами
    // =============================================
    
    /**
     * Глубокое клонирование объекта
     * @param {object} obj - Объект
     * @returns {object} Клон
     */
    deepClone(obj) {
        if (obj === null || typeof obj !== 'object') return obj;
        if (obj instanceof Date) return new Date(obj.getTime());
        if (obj instanceof Array) return obj.map(item => this.deepClone(item));
        
        const cloned = {};
        for (const key in obj) {
            if (obj.hasOwnProperty(key)) {
                cloned[key] = this.deepClone(obj[key]);
            }
        }
        return cloned;
    },
    
    /**
     * Сравнение двух объектов
     * @param {object} obj1 - Первый объект
     * @param {object} obj2 - Второй объект
     * @returns {boolean} Равны ли объекты
     */
    isEqual(obj1, obj2) {
        return JSON.stringify(obj1) === JSON.stringify(obj2);
    },
    
    /**
     * Группировка массива по ключу
     * @param {Array} array - Массив
     * @param {string} key - Ключ
     * @returns {object} Сгруппированный объект
     */
    groupBy(array, key) {
        return array.reduce((result, item) => {
            const groupKey = item[key];
            if (!result[groupKey]) result[groupKey] = [];
            result[groupKey].push(item);
            return result;
        }, {});
    },
    
    /**
     * Удаление дубликатов из массива
     * @param {Array} array - Массив
     * @param {string} key - Ключ (опционально)
     * @returns {Array} Массив без дубликатов
     */
    unique(array, key = null) {
        if (key) {
            const seen = new Set();
            return array.filter(item => {
                const value = item[key];
                if (seen.has(value)) return false;
                seen.add(value);
                return true;
            });
        }
        return [...new Set(array)];
    },
    
    // =============================================
    // Асинхронные утилиты
    // =============================================
    
    /**
     * Задержка (sleep)
     * @param {number} ms - Миллисекунды
     * @returns {Promise} Promise
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    },
    
    /**
     * Повтор асинхронной операции с экспоненциальной задержкой
     * @param {Function} fn - Асинхронная функция
     * @param {number} maxRetries - Максимальное количество попыток
     * @param {number} baseDelay - Базовая задержка в мс
     * @returns {Promise} Результат функции
     */
    async retry(fn, maxRetries = 3, baseDelay = 1000) {
        let lastError;
        
        for (let i = 0; i < maxRetries; i++) {
            try {
                return await fn();
            } catch (error) {
                lastError = error;
                if (i < maxRetries - 1) {
                    const delay = baseDelay * Math.pow(2, i);
                    await this.sleep(delay);
                }
            }
        }
        
        throw lastError;
    },
    
    // =============================================
    // Определение устройства и браузера
    // =============================================
    
    /**
     * Проверка, является ли устройство мобильным
     * @returns {boolean} Мобильное ли устройство
     */
    isMobile() {
        return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    },
    
    /**
     * Проверка, является ли браузер Safari
     * @returns {boolean} Safari ли
     */
    isSafari() {
        return /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
    },
    
    /**
     * Получение информации о браузере
     * @returns {object} Информация о браузере
     */
    getBrowserInfo() {
        const ua = navigator.userAgent;
        let name = 'Unknown';
        let version = 'Unknown';
        
        if (ua.includes('Firefox')) {
            name = 'Firefox';
            version = ua.match(/Firefox\/(\d+)/)?.[1] || '';
        } else if (ua.includes('Edg')) {
            name = 'Edge';
            version = ua.match(/Edg\/(\d+)/)?.[1] || '';
        } else if (ua.includes('Chrome')) {
            name = 'Chrome';
            version = ua.match(/Chrome\/(\d+)/)?.[1] || '';
        } else if (ua.includes('Safari')) {
            name = 'Safari';
            version = ua.match(/Version\/(\d+)/)?.[1] || '';
        }
        
        return { name, version };
    }
};

// Экспорт глобально
window.Utils = Utils;
