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
            const initFunc = this[tabId]?.init;
            if (initFunc) {
                await initFunc();
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
        
        document.querySelectorAll('.admin-only').forEach(el => {
            el.style.display = isAdmin ? '' : 'none';
        });

        const killSwitch = document.getElementById('killSwitchBtn');
        if (killSwitch) {
            killSwitch.style.display = isAdmin ? '' : 'none';
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

    async apiGet(endpoint) {
        const response = await this.apiFetch(endpoint);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },

    async apiPost(endpoint, data) {
        const response = await this.apiFetch(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `API error: ${response.status}`);
        }
        return response.json();
    },

    async apiPut(endpoint, data) {
        const response = await this.apiFetch(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },

    async apiPatch(endpoint, data) {
        const response = await this.apiFetch(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },

    async apiDelete(endpoint) {
        const response = await this.apiFetch(endpoint, {
            method: 'DELETE'
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
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
    validatePhone(phone) {
        const cleaned = phone.replace(/\D/g, '');
        return cleaned.length >= 10;
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
// Автоматическая инициализация
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    App.init();
    
    // Проверяем сохранённый токен
    const savedToken = localStorage.getItem('refresh_token');
    if (savedToken) {
        App.state.refreshToken = savedToken;
        App.checkAutoLogin();
    }
});
