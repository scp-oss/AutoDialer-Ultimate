/**
 * AutoDialer Ultimate - Core Application
 * Version: 3.0.0
 */

// =============================================
// Global State
// =============================================
const App = {
    // Состояние приложения
    state: {
        accessToken: '',
        refreshToken: '',
        user: null,
        userRole: '',
        currentTab: 'dashboard',
        systemEnabled: true,
        activeCalls: 0,
        maxCalls: 50,
        queueSize: 0,
        stats: {
            totalCalls: 0,
            agreed: 0,
            busy: 0,
            noanswer: 0,
            failed: 0,
            todayCalls: 0,
            conversionRate: 0
        }
    },

    // API Base URL
    API_BASE: '/api',

    // Кэш данных
    cache: {
        campaigns: [],
        contacts: [],
        contactGroups: [],
        audioFiles: [],
        users: [],
        settings: {}
    },

    // Периодические задачи
    intervals: {
        system: null,
        dashboard: null
    },

    // =============================================
    // Инициализация
    // =============================================
    init() {
        this.setupGlobalEventListeners();
        console.log('AutoDialer Ultimate initialized');
    },

    setupGlobalEventListeners() {
        // Закрытие модальных окон по Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllModals();
            }
        });

        // Закрытие модальных окон по клику вне их
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
            }
        });
    },

    closeAllModals() {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.style.display = 'none';
        });
    },

    // =============================================
    // Управление вкладками
    // =============================================
    async switchTab(tabId) {
        // Обновляем активный пункт меню
        document.querySelectorAll('.sidebar-item').forEach(item => {
            item.classList.toggle('active', item.dataset.tab === tabId);
        });

        // Загружаем содержимое вкладки
        const container = document.getElementById('contentContainer');
        
        try {
            // Показываем загрузку
            container.innerHTML = '<div class="loading">Загрузка...</div>';
            
            // Загружаем HTML вкладки
            const response = await fetch(`components/tabs/${tabId}.html`);
            if (!response.ok) {
                throw new Error(`Failed to load tab: ${tabId}`);
            }
            
            container.innerHTML = await response.text();
            
            // Обновляем состояние
            this.state.currentTab = tabId;
            
            // Вызываем инициализацию вкладки
            // Extracting .init into a standalone reference before calling
            // it (the old `const initFunc = this[tabId]?.init; initFunc()`)
            // loses its `this` binding to the tab module (App.dashboard,
            // App.campaigns, ...), so every tab's init() saw `this` as
            // undefined and crashed on its very first `this.loadXxx()`
            // call. Call it through the module object so `this` stays
            // bound correctly.
            if (this[tabId]?.init) {
                await this[tabId].init();
            }
            
            // Останавливаем старые интервалы
            this.stopPeriodicRefresh();
            
            // Запускаем периодическое обновление для активной вкладки
            this.startPeriodicRefresh();
            
        } catch (error) {
            console.error(`Error loading tab ${tabId}:`, error);
            container.innerHTML = `<div class="error-message">Ошибка загрузки: ${error.message}</div>`;
        }
    },

    // =============================================
    // Периодическое обновление
    // =============================================
    startPeriodicRefresh() {
        // Системный статус (общий для всех)
        this.intervals.system = setInterval(() => {
            this.system?.refreshStatus();
        }, 3000);

        // Специфичные для вкладки обновления
        switch (this.state.currentTab) {
            case 'dashboard':
                this.intervals.dashboard = setInterval(() => {
                    this.dashboard?.refresh();
                }, 5000);
                break;
            case 'campaigns':
                // Кампании обновляются реже
                break;
        }
    },

    stopPeriodicRefresh() {
        if (this.intervals.system) {
            clearInterval(this.intervals.system);
            this.intervals.system = null;
        }
        if (this.intervals.dashboard) {
            clearInterval(this.intervals.dashboard);
            this.intervals.dashboard = null;
        }
    },

    // =============================================
    // Аутентификация (делегирование)
    // =============================================
    async checkAutoLogin() {
        const token = localStorage.getItem('refresh_token');
        if (token) {
            this.state.refreshToken = token;
            await this.auth.tryAutoLogin();
        }
    },

    showApp() {
        document.getElementById('loginScreen').style.display = 'none';
        document.getElementById('appScreen').style.display = 'block';
        
        this.updateUserDisplay();
        this.applyRoleBasedUI();
        
        // Загружаем дашборд по умолчанию
        this.switchTab('dashboard');
    },

    updateUserDisplay() {
        const user = this.state.user;
        if (user) {
            const userDisplay = document.getElementById('userDisplay');
            if (userDisplay) {
                userDisplay.innerHTML = `
                    <span class="badge badge-${user.role}">${user.role}</span>
                    ${user.username}
                `;
            }
        }
    },

    applyRoleBasedUI() {
        const isAdmin = this.state.userRole === 'admin';

        // .admin-only itself carries no display rule (see style.css) -
        // toggle the .hidden utility class instead of style.display, since
        // clearing an inline style can't override a CSS rule that already
        // says display:none.
        document.querySelectorAll('.admin-only').forEach(el => {
            el.classList.toggle('hidden', !isAdmin);
        });

        const killSwitch = document.getElementById('killSwitchBtn');
        if (killSwitch) {
            killSwitch.classList.toggle('hidden', !isAdmin);
        }
    },

    // =============================================
    // API Helpers
    // =============================================
    async apiFetch(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : `${this.API_BASE}${endpoint}`;
        
        if (!options.headers) {
            options.headers = {};
        }
        
        if (this.state.accessToken) {
            options.headers['Authorization'] = `Bearer ${this.state.accessToken}`;
        }
        
        if (!(options.body instanceof FormData)) {
            options.headers['Content-Type'] = options.headers['Content-Type'] || 'application/json';
        }
        
        try {
            let response = await fetch(url, options);
            
            // Обработка 401 (токен истёк)
            if (response.status === 401 && this.state.refreshToken) {
                const refreshed = await this.auth.refreshToken();
                if (refreshed) {
                    options.headers['Authorization'] = `Bearer ${this.state.accessToken}`;
                    response = await fetch(url, options);
                }
            }
            
            return response;
            
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    },

    // FastAPI's validation errors (422) return `detail` as an ARRAY of
    // {loc, msg, type} objects, not a string - `new Error(error.detail)`
    // stringified that straight to "[object Object]" (confirmed live on
    // /auth/change-password), hiding the actual problem from both the
    // user and the console. Handles the plain-string `detail` shape too
    // (used by most other endpoints, e.g. raised HTTPExceptions).
    async extractApiError(response) {
        const body = await response.json().catch(() => ({}));
        if (typeof body.detail === 'string') {
            return body.detail;
        }
        if (Array.isArray(body.detail)) {
            return body.detail
                .map(e => e.msg || JSON.stringify(e))
                .join('; ');
        }
        return `API error: ${response.status}`;
    },

    async apiGet(endpoint) {
        const response = await this.apiFetch(endpoint);
        if (!response.ok) {
            throw new Error(await this.extractApiError(response));
        }
        return response.json();
    },

    async apiPost(endpoint, data) {
        const response = await this.apiFetch(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            throw new Error(await this.extractApiError(response));
        }
        return response.json();
    },

    async apiPut(endpoint, data) {
        const response = await this.apiFetch(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            throw new Error(await this.extractApiError(response));
        }
        return response.json();
    },

    async apiPatch(endpoint, data) {
        const response = await this.apiFetch(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            throw new Error(await this.extractApiError(response));
        }
        return response.json();
    },

    async apiDelete(endpoint) {
        const response = await this.apiFetch(endpoint, {
            method: 'DELETE'
        });
        if (!response.ok) {
            throw new Error(await this.extractApiError(response));
        }
        return response.json();
    },

    // =============================================
    // UI Helpers
    // =============================================
    showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span>${message}</span>
            <button onclick="this.parentElement.remove()" style="background:none;border:none;color:white;cursor:pointer;margin-left:10px;">&times;</button>
        `;
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    },

    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.style.display = 'flex';
        }
    },

    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.style.display = 'none';
        }
    },

    confirm(message) {
        return window.confirm(message);
    },

    formatDuration(seconds) {
        if (!seconds) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    },

    formatDateTime(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        return date.toLocaleString('ru-RU');
    },

    // contacts.js/campaigns.js/dashboard.js/contactGroups.js/blacklist.js/
    // history.js/incoming.js all call App.formatPhoneNumber(), but the
    // actual implementation only ever existed on the separate `Utils`
    // namespace (utils.js, loaded before this file) - App.formatPhoneNumber
    // itself was never defined, so every one of those call sites threw
    // "App.formatPhoneNumber is not a function" the moment it ran.
    formatPhoneNumber(phone) {
        return Utils.formatPhoneNumber(phone);
    },

    formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    renderPagination(containerId, currentPage, totalPages, callback) {
        const container = document.getElementById(containerId);
        if (!container) return;
        
        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }
        
        let html = '';
        
        // Кнопка "Назад"
        if (currentPage > 1) {
            html += `<button onclick="${callback}(${currentPage - 1})">←</button>`;
        }
        
        // Номера страниц
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 2) {
                html += `<button class="${i === currentPage ? 'active' : ''}" onclick="${callback}(${i})">${i}</button>`;
            } else if (Math.abs(i - currentPage) === 3) {
                html += '<span>...</span>';
            }
        }
        
        // Кнопка "Вперёд"
        if (currentPage < totalPages) {
            html += `<button onclick="${callback}(${currentPage + 1})">→</button>`;
        }
        
        container.innerHTML = html;
    },

    // =============================================
    // Хелперы для работы с формами
    // =============================================
    getFormData(formId) {
        const form = document.getElementById(formId);
        if (!form) return {};
        
        const formData = new FormData(form);
        const data = {};
        
        for (const [key, value] of formData.entries()) {
            // Обработка checkbox
            const input = form.elements[key];
            if (input && input.type === 'checkbox') {
                data[key] = input.checked;
            } else {
                data[key] = value;
            }
        }
        
        return data;
    },

    clearForm(formId) {
        const form = document.getElementById(formId);
        if (form) {
            form.reset();
        }
    },

    setFormData(formId, data) {
        const form = document.getElementById(formId);
        if (!form) return;
        
        for (const [key, value] of Object.entries(data)) {
            const input = form.elements[key];
            if (input) {
                if (input.type === 'checkbox') {
                    input.checked = value;
                } else {
                    input.value = value ?? '';
                }
            }
        }
    },

    // =============================================
    // Валидация
    // =============================================
    // Минимум 3 цифры, не 10 - короткие внутренние добавочные АТС (3-5
    // цифр, например "291") тоже валидная цель для звонка, не только
    // мобильные номера. Держим в паре с validate_phone_number()
    // (app/utils/phone.py) - тот же минимум.
    validatePhone(phone) {
        const cleaned = phone.replace(/\D/g, '');
        return cleaned.length >= 3;
    },

    validateEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email);
    },

    validatePassword(password) {
        if (password.length < 8) return false;
        if (!/[A-Z]/.test(password)) return false;
        if (!/[a-z]/.test(password)) return false;
        if (!/\d/.test(password)) return false;
        return true;
    },

    // =============================================
    // Экспорт/Импорт
    // =============================================
    downloadFile(content, filename, contentType = 'text/plain') {
        const blob = new Blob([content], { type: contentType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },

    async readFileAsText(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = (e) => reject(e);
            reader.readAsText(file);
        });
    },

    // =============================================
    // Дебаунс и троттлинг
    // =============================================
    debounce(func, wait) {
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

    throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },

    // =============================================
    // Глубокое клонирование
    // =============================================
    deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    },

    // =============================================
    // Генерация ID
    // =============================================
    generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2);
    }
};

// =============================================
// Экспорт в глобальную область
// =============================================
window.App = App;

// =============================================
// Совместимость со старым стилем модулей
// =============================================
// apiTokens.js, audio.js, audit.js, blacklist.js, history.js,
// settings.js, users.js и webhooks.js написаны в более старом стиле и
// ссылаются на глобальные AppState/authFetch/API_BASE/showToast (см.
// комментарий "Зависимости: app.js (...)" в начале каждого из них), но
// ни один из этих четырёх глобальных идентификаторов нигде не был
// определён - каждый вызов сразу падал с ReferenceError, так что ни
// одна кнопка на этих вкладках не работала вообще (подтверждено:
// "не одна кнопка не работает на Аудио"). Остальные модули
// (campaigns.js, contacts.js, dashboard.js и т.д.) используют
// App.apiGet/apiPost/... напрямую и в этом не нуждаются - тут только
// тонкие алиасы поверх уже существующей реализации в App, без
// дублирования логики.
window.AppState = App.state;
window.API_BASE = App.API_BASE;
window.showToast = (message, type) => App.showToast(message, type);
window.authFetch = (url, options) => {
    // Every call site in the old-style modules already builds its URL
    // as `${API_BASE}/...` (API_BASE = '/api'), but App.apiFetch ALSO
    // prepends this.API_BASE to whatever it's given unless the string
    // already starts with "http" - passing an already-prefixed URL
    // straight through produced /api/api/... on every single request
    // (confirmed live: POST /api/api/audio/generate -> 405). Strip the
    // leading API_BASE here so apiFetch's own prefixing lands on a
    // plain endpoint path, same as every other (non-legacy) module.
    const endpoint = url.startsWith(App.API_BASE) ? url.slice(App.API_BASE.length) : url;
    return App.apiFetch(endpoint, options);
};

// =============================================
// Автоматическая инициализация
// =============================================
// Инициализация (App.init() + автологин) выполняется из инлайн-скрипта в
// конце index.html - там же грузятся sidebar.html/modals.html до вызова
// tryAutoLogin(). Второй, независимый DOMContentLoaded-обработчик здесь
// раньше тоже вызывал checkAutoLogin(), из-за чего автологин и, как
// следствие, вся загрузка дашборда (5 параллельных запросов) выполнялись
// ДВАЖДЫ при каждом заходе на страницу - это и приводило к 429 Too Many
// Requests от лимитера Nginx.
