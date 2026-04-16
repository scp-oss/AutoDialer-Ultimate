// audit.js - Модуль аудита (журнал событий, только для admin)
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast)

const AuditModule = {
    currentPage: 1,
    pageSize: 25,
    totalPages: 1,
    totalRecords: 0,
    auditLogs: [],
    
    // Фильтры
    filters: {
        action: '',
        username: '',
        dateFrom: '',
        dateTo: '',
        ipAddress: ''
    },
    
    // Инициализация модуля
    init() {
        // Проверка прав доступа
        if (AppState.userRole !== 'admin') {
            this.renderAccessDenied();
            return;
        }
        
        this.render();
        this.attachEventListeners();
        this.loadActions(); // загрузка списка действий для фильтра
        this.loadAuditLog();
    },
    
    // Рендер страницы при отказе в доступе
    renderAccessDenied() {
        const container = document.getElementById('auditContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="access-denied">
                <div class="access-denied-icon">🔒</div>
                <h2>Доступ запрещён</h2>
                <p>У вас нет прав для просмотра этой страницы.</p>
                <p>Только администраторы могут просматривать журнал аудита.</p>
            </div>
        `;
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('auditContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="audit-page">
                <div class="page-header">
                    <h2>📋 Журнал аудита</h2>
                    <div class="header-actions">
                        <button class="btn btn-outline" id="auditRefreshBtn">
                            🔄 Обновить
                        </button>
                        <button class="btn btn-outline" id="auditExportBtn">
                            📥 Экспорт
                        </button>
                        <button class="btn btn-danger" id="auditClearBtn">
                            🗑️ Очистить старые
                        </button>
                    </div>
                </div>
                
                <p class="text-muted">
                    Журнал всех действий пользователей и системных событий.
                    Записи хранятся ${this.settings?.audit_retention_days || 90} дней.
                </p>
                
                <!-- Панель фильтров -->
                <div class="audit-filters">
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Действие</label>
                            <select id="auditFilterAction" class="form-control">
                                <option value="">Все действия</option>
                            </select>
                        </div>
                        
                        <div class="filter-group">
                            <label>Пользователь</label>
                            <input type="text" 
                                   id="auditFilterUsername" 
                                   class="form-control" 
                                   placeholder="Логин пользователя"
                                   value="${this.filters.username}">
                        </div>
                        
                        <div class="filter-group">
                            <label>IP адрес</label>
                            <input type="text" 
                                   id="auditFilterIp" 
                                   class="form-control" 
                                   placeholder="IP адрес"
                                   value="${this.filters.ipAddress}">
                        </div>
                    </div>
                    
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Дата с</label>
                            <input type="datetime-local" 
                                   id="auditFilterDateFrom" 
                                   class="form-control"
                                   value="${this.filters.dateFrom}">
                        </div>
                        
                        <div class="filter-group">
                            <label>Дата по</label>
                            <input type="datetime-local" 
                                   id="auditFilterDateTo" 
                                   class="form-control"
                                   value="${this.filters.dateTo}">
                        </div>
                        
                        <div class="filter-group filter-actions">
                            <button class="btn btn-primary" id="auditApplyFiltersBtn">
                                🔍 Применить
                            </button>
                            <button class="btn btn-outline" id="auditResetFiltersBtn">
                                🔄 Сбросить
                            </button>
                        </div>
                    </div>
                </div>
                
                <!-- Статистика -->
                <div class="audit-stats">
                    <div class="stat-item">
                        <span class="stat-label">Всего записей:</span>
                        <span class="stat-value" id="auditTotalRecords">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">За сегодня:</span>
                        <span class="stat-value" id="auditTodayRecords">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Уникальных пользователей:</span>
                        <span class="stat-value" id="auditUniqueUsers">0</span>
                    </div>
                </div>
                
                <!-- Таблица -->
                <div class="audit-table-container">
                    <table class="table" id="auditTable">
                        <thead>
                            <tr>
                                <th width="180">Дата/Время</th>
                                <th width="120">Пользователь</th>
                                <th width="150">Действие</th>
                                <th>Детали</th>
                                <th width="120">IP адрес</th>
                                <th width="100">User Agent</th>
                                <th width="60"></th>
                            </tr>
                        </thead>
                        <tbody id="auditTableBody">
                            <tr><td colspan="7" class="text-center">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                
                <!-- Пагинация -->
                <div id="auditPagination" class="pagination-container"></div>
            </div>
            
            <!-- Модальное окно деталей -->
            <div id="auditDetailModal" class="modal" style="display: none;">
                <div class="modal-content modal-lg">
                    <div class="modal-header">
                        <h3>Детали события</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body" id="auditDetailContent">
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно очистки -->
            <div id="auditClearModal" class="modal" style="display: none;">
                <div class="modal-content modal-sm">
                    <div class="modal-header">
                        <h3>Очистка журнала</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p>Удалить записи старше:</p>
                        <select id="auditClearDays" class="form-control">
                            <option value="30">30 дней</option>
                            <option value="60">60 дней</option>
                            <option value="90" selected>90 дней</option>
                            <option value="180">180 дней</option>
                            <option value="365">365 дней</option>
                        </select>
                        
                        <p class="text-warning" style="margin-top: 15px;">
                            ⚠️ Это действие нельзя отменить!
                        </p>
                        
                        <div class="form-actions">
                            <button type="button" class="btn btn-outline" onclick="AuditModule.closeClearModal()">
                                Отмена
                            </button>
                            <button type="button" class="btn btn-danger" id="auditConfirmClearBtn">
                                Очистить
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },
    
    // Загрузка списка действий для фильтра
    async loadActions() {
        try {
            const response = await authFetch(`${API_BASE}/audit/actions`);
            if (response.ok) {
                const actions = await response.json();
                const select = document.getElementById('auditFilterAction');
                if (select) {
                    actions.forEach(action => {
                        const option = document.createElement('option');
                        option.value = action;
                        option.textContent = this.formatActionName(action);
                        if (this.filters.action === action) {
                            option.selected = true;
                        }
                        select.appendChild(option);
                    });
                }
            }
        } catch (error) {
            console.error('Load actions failed:', error);
        }
    },
    
    // Загрузка журнала аудита
    async loadAuditLog(page = 1) {
        this.currentPage = page;
        
        const tbody = document.getElementById('auditTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Загрузка...</td></tr>';
        
        try {
            let url = `${API_BASE}/audit?page=${page}&page_size=${this.pageSize}`;
            
            if (this.filters.action) url += `&action=${encodeURIComponent(this.filters.action)}`;
            if (this.filters.username) url += `&username=${encodeURIComponent(this.filters.username)}`;
            if (this.filters.ipAddress) url += `&ip_address=${encodeURIComponent(this.filters.ipAddress)}`;
            if (this.filters.dateFrom) url += `&date_from=${this.filters.dateFrom}`;
            if (this.filters.dateTo) url += `&date_to=${this.filters.dateTo}`;
            
            const response = await authFetch(url);
            if (response.ok) {
                const data = await response.json();
                this.auditLogs = data.items || data || [];
                this.totalRecords = data.total || this.auditLogs.length;
                this.totalPages = Math.ceil(this.totalRecords / this.pageSize) || 1;
                
                this.renderTable();
                this.renderPagination();
                this.updateStats(data.stats);
            } else {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('Audit load failed:', error);
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    // Рендер таблицы
    renderTable() {
        const tbody = document.getElementById('auditTableBody');
        
        if (this.auditLogs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">📋</div>
                            <p>Нет записей в журнале</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.auditLogs.map(log => `
            <tr data-id="${log.id}" class="audit-row" data-action="${log.action}">
                <td>${this.formatDateTime(log.created_at)}</td>
                <td>
                    <span class="username">${this.escapeHtml(log.username || 'system')}</span>
                    ${log.user_id ? `<small class="user-id">ID: ${log.user_id}</small>` : ''}
                </td>
                <td>
                    <span class="action-badge action-${this.getActionClass(log.action)}">
                        ${this.formatActionName(log.action)}
                    </span>
                </td>
                <td>
                    <div class="details-preview">
                        ${this.formatDetails(log.details, log.action)}
                    </div>
                </td>
                <td>
                    ${log.ip_address ? `
                        <span class="ip-address">${this.escapeHtml(log.ip_address)}</span>
                    ` : '—'}
                </td>
                <td>
                    ${log.user_agent ? this.getBrowserIcon(log.user_agent) : '—'}
                </td>
                <td>
                    <button class="btn btn-sm btn-outline view-detail" data-id="${log.id}" title="Подробнее">
                        👁️
                    </button>
                </td>
            </tr>
        `).join('');
        
        this.attachTableEvents();
    },
    
    // Обновление статистики
    updateStats(stats) {
        if (!stats) return;
        
        document.getElementById('auditTotalRecords').textContent = stats.total || this.totalRecords;
        document.getElementById('auditTodayRecords').textContent = stats.today || 0;
        document.getElementById('auditUniqueUsers').textContent = stats.unique_users || 0;
    },
    
    // Рендер пагинации
    renderPagination() {
        const container = document.getElementById('auditPagination');
        if (!container) return;
        
        if (this.totalPages <= 1) {
            container.innerHTML = '';
            return;
        }
        
        let html = '<div class="pagination">';
        
        if (this.currentPage > 1) {
            html += `<button class="page-btn" data-page="${this.currentPage - 1}">←</button>`;
        } else {
            html += `<button class="page-btn" disabled>←</button>`;
        }
        
        const start = Math.max(1, this.currentPage - 2);
        const end = Math.min(this.totalPages, this.currentPage + 2);
        
        if (start > 1) {
            html += `<button class="page-btn" data-page="1">1</button>`;
            if (start > 2) html += '<span class="page-dots">...</span>';
        }
        
        for (let i = start; i <= end; i++) {
            html += `<button class="page-btn ${i === this.currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }
        
        if (end < this.totalPages) {
            if (end < this.totalPages - 1) html += '<span class="page-dots">...</span>';
            html += `<button class="page-btn" data-page="${this.totalPages}">${this.totalPages}</button>`;
        }
        
        if (this.currentPage < this.totalPages) {
            html += `<button class="page-btn" data-page="${this.currentPage + 1}">→</button>`;
        } else {
            html += `<button class="page-btn" disabled>→</button>`;
        }
        
        html += '</div>';
        
        container.innerHTML = html;
        
        container.querySelectorAll('.page-btn[data-page]').forEach(btn => {
            btn.addEventListener('click', () => {
                this.loadAuditLog(parseInt(btn.dataset.page));
            });
        });
    },
    
    // ============ ФОРМАТИРОВАНИЕ ============
    
    formatDateTime(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }).replace(',', '');
    },
    
    formatActionName(action) {
        const actions = {
            'login': 'Вход в систему',
            'logout': 'Выход из системы',
            'login_failed': 'Неудачный вход',
            'password_change': 'Смена пароля',
            'user_create': 'Создание пользователя',
            'user_update': 'Обновление пользователя',
            'user_delete': 'Удаление пользователя',
            'campaign_create': 'Создание кампании',
            'campaign_start': 'Запуск кампании',
            'campaign_stop': 'Остановка кампании',
            'campaign_pause': 'Пауза кампании',
            'campaign_resume': 'Возобновление кампании',
            'campaign_delete': 'Удаление кампании',
            'contact_create': 'Создание контакта',
            'contact_update': 'Обновление контакта',
            'contact_delete': 'Удаление контакта',
            'contact_import': 'Импорт контактов',
            'blacklist_add': 'Добавление в ЧС',
            'blacklist_remove': 'Удаление из ЧС',
            'blacklist_import': 'Импорт в ЧС',
            'audio_upload': 'Загрузка аудио',
            'audio_generate': 'Генерация TTS',
            'audio_delete': 'Удаление аудио',
            'settings_update': 'Изменение настроек',
            'system_start': 'Запуск системы',
            'system_stop': 'Остановка системы',
            'system_restart': 'Перезагрузка системы',
            'api_token_create': 'Создание API токена',
            'api_token_delete': 'Удаление API токена',
            'webhook_create': 'Создание Webhook',
            'webhook_update': 'Обновление Webhook',
            'webhook_delete': 'Удаление Webhook',
            'incoming_call': 'Входящий звонок',
            'transcription': 'Транскрибация'
        };
        return actions[action] || action.replace(/_/g, ' ');
    },
    
    getActionClass(action) {
        if (action.includes('create') || action.includes('upload') || action.includes('generate')) return 'create';
        if (action.includes('update') || action.includes('change') || action.includes('start') || action.includes('resume')) return 'update';
        if (action.includes('delete') || action.includes('remove') || action.includes('stop')) return 'delete';
        if (action.includes('login') || action.includes('logout')) return 'auth';
        if (action.includes('failed') || action.includes('error')) return 'error';
        return 'default';
    },
    
    formatDetails(details, action) {
        if (!details) return '—';
        
        try {
            const obj = typeof details === 'string' ? JSON.parse(details) : details;
            
            // Форматирование в зависимости от типа действия
            if (action === 'login' || action === 'login_failed') {
                return `Пользователь: ${obj.username || '—'}`;
            }
            
            if (action.includes('campaign')) {
                return `Кампания: ${obj.campaign_name || obj.campaign_id || '—'}`;
            }
            
            if (action.includes('user')) {
                return `Пользователь: ${obj.target_username || obj.user_id || '—'}`;
            }
            
            if (action.includes('contact')) {
                return `Контакт: ${obj.phone || obj.contact_id || '—'}`;
            }
            
            if (action.includes('blacklist')) {
                return `Номер: ${obj.phone || '—'}`;
            }
            
            if (action.includes('audio')) {
                return `Файл: ${obj.filename || obj.audio_id || '—'}`;
            }
            
            if (action.includes('settings')) {
                return `Настройка: ${obj.key || '—'}`;
            }
            
            // Общее форматирование
            const preview = JSON.stringify(obj);
            return preview.length > 100 ? preview.substring(0, 97) + '...' : preview;
            
        } catch {
            return String(details).substring(0, 100);
        }
    },
    
    getBrowserIcon(userAgent) {
        if (!userAgent) return '—';
        
        const ua = userAgent.toLowerCase();
        if (ua.includes('chrome') && !ua.includes('edg')) return '🌐 Chrome';
        if (ua.includes('firefox')) return '🦊 Firefox';
        if (ua.includes('safari') && !ua.includes('chrome')) return '🧭 Safari';
        if (ua.includes('edg')) return '📘 Edge';
        if (ua.includes('opera')) return '🎭 Opera';
        
        return '🌐';
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async showDetailModal(logId) {
        try {
            const response = await authFetch(`${API_BASE}/audit/${logId}`);
            if (!response.ok) throw new Error('Failed to load');
            
            const log = await response.json();
            
            let detailsHtml = '';
            if (log.details) {
                try {
                    const obj = typeof log.details === 'string' ? JSON.parse(log.details) : log.details;
                    detailsHtml = `<pre>${JSON.stringify(obj, null, 2)}</pre>`;
                } catch {
                    detailsHtml = `<p>${this.escapeHtml(String(log.details))}</p>`;
                }
            }
            
            const content = document.getElementById('auditDetailContent');
            content.innerHTML = `
                <div class="audit-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID:</td><td>${log.id}</td></tr>
                            <tr><td>Дата/Время:</td><td>${this.formatDateTime(log.created_at)}</td></tr>
                            <tr><td>Действие:</td><td>${this.formatActionName(log.action)}</td></tr>
                            <tr><td>Пользователь:</td><td>${this.escapeHtml(log.username || 'system')} (ID: ${log.user_id || '—'})</td></tr>
                            <tr><td>IP адрес:</td><td>${this.escapeHtml(log.ip_address || '—')}</td></tr>
                            <tr><td>User Agent:</td><td>${this.escapeHtml(log.user_agent || '—')}</td></tr>
                        </table>
                    </div>
                    
                    ${log.details ? `
                        <div class="detail-section">
                            <h4>Детали</h4>
                            ${detailsHtml}
                        </div>
                    ` : ''}
                    
                    ${log.before_state ? `
                        <div class="detail-section">
                            <h4>Состояние до</h4>
                            <pre>${JSON.stringify(log.before_state, null, 2)}</pre>
                        </div>
                    ` : ''}
                    
                    ${log.after_state ? `
                        <div class="detail-section">
                            <h4>Состояние после</h4>
                            <pre>${JSON.stringify(log.after_state, null, 2)}</pre>
                        </div>
                    ` : ''}
                </div>
            `;
            
            document.getElementById('auditDetailModal').style.display = 'flex';
        } catch (error) {
            console.error('Load detail failed:', error);
            showToast('Ошибка загрузки', 'error');
        }
    },
    
    closeDetailModal() {
        document.getElementById('auditDetailModal').style.display = 'none';
    },
    
    openClearModal() {
        document.getElementById('auditClearModal').style.display = 'flex';
    },
    
    closeClearModal() {
        document.getElementById('auditClearModal').style.display = 'none';
    },
    
    async clearOldLogs() {
        const days = document.getElementById('auditClearDays').value;
        
        const btn = document.getElementById('auditConfirmClearBtn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Очистка...';
        
        try {
            const response = await authFetch(`${API_BASE}/audit/clear`, {
                method: 'POST',
                body: JSON.stringify({ older_than_days: parseInt(days) })
            });
            
            if (response.ok) {
                const data = await response.json();
                showToast(`Удалено ${data.deleted} записей`, 'success');
                this.closeClearModal();
                await this.loadAuditLog();
            } else {
                showToast('Ошибка очистки', 'error');
            }
        } catch (error) {
            console.error('Clear failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    },
    
    async exportAudit() {
        showToast('Подготовка экспорта...', 'info');
        
        try {
            let url = `${API_BASE}/audit/export?`;
            const params = [];
            if (this.filters.action) params.push(`action=${encodeURIComponent(this.filters.action)}`);
            if (this.filters.username) params.push(`username=${encodeURIComponent(this.filters.username)}`);
            if (this.filters.dateFrom) params.push(`date_from=${this.filters.dateFrom}`);
            if (this.filters.dateTo) params.push(`date_to=${this.filters.dateTo}`);
            url += params.join('&');
            
            const response = await authFetch(url);
            if (response.ok) {
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = `audit_export_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(downloadUrl);
                document.body.removeChild(a);
                
                showToast('Экспорт завершен', 'success');
            } else {
                await this.exportToCSVClientSide();
            }
        } catch (error) {
            console.error('Export failed:', error);
            await this.exportToCSVClientSide();
        }
    },
    
    async exportToCSVClientSide() {
        try {
            const response = await authFetch(`${API_BASE}/audit?page_size=10000`);
            if (!response.ok) throw new Error('Failed to load');
            
            const data = await response.json();
            const logs = data.items || data || [];
            
            if (!logs.length) {
                showToast('Нет данных для экспорта', 'warning');
                return;
            }
            
            const headers = ['ID', 'Дата/Время', 'Пользователь', 'Действие', 'Детали', 'IP адрес'];
            const rows = logs.map(log => [
                log.id,
                this.formatDateTime(log.created_at),
                log.username || 'system',
                this.formatActionName(log.action),
                this.formatDetails(log.details, log.action).replace(/,/g, ';'),
                log.ip_address || ''
            ]);
            
            const csvContent = [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
            ].join('\n');
            
            const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `audit_export_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            window.URL.revokeObjectURL(url);
            
            showToast(`Экспортировано ${logs.length} записей`, 'success');
        } catch (error) {
            console.error('Client-side export failed:', error);
            showToast('Не удалось выполнить экспорт', 'error');
        }
    },
    
    applyFilters() {
        this.filters = {
            action: document.getElementById('auditFilterAction')?.value || '',
            username: document.getElementById('auditFilterUsername')?.value || '',
            ipAddress: document.getElementById('auditFilterIp')?.value || '',
            dateFrom: document.getElementById('auditFilterDateFrom')?.value || '',
            dateTo: document.getElementById('auditFilterDateTo')?.value || ''
        };
        
        this.currentPage = 1;
        this.loadAuditLog();
    },
    
    resetFilters() {
        document.getElementById('auditFilterAction').value = '';
        document.getElementById('auditFilterUsername').value = '';
        document.getElementById('auditFilterIp').value = '';
        document.getElementById('auditFilterDateFrom').value = '';
        document.getElementById('auditFilterDateTo').value = '';
        
        this.filters = {
            action: '',
            username: '',
            ipAddress: '',
            dateFrom: '',
            dateTo: ''
        };
        
        this.currentPage = 1;
        this.loadAuditLog();
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        document.getElementById('auditRefreshBtn')?.addEventListener('click', () => this.loadAuditLog());
        document.getElementById('auditExportBtn')?.addEventListener('click', () => this.exportAudit());
        document.getElementById('auditClearBtn')?.addEventListener('click', () => this.openClearModal());
        
        document.getElementById('auditApplyFiltersBtn')?.addEventListener('click', () => this.applyFilters());
        document.getElementById('auditResetFiltersBtn')?.addEventListener('click', () => this.resetFilters());
        
        document.getElementById('auditConfirmClearBtn')?.addEventListener('click', () => this.clearOldLogs());
        
        document.querySelectorAll('.close-modal').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                if (modal) modal.style.display = 'none';
            });
        });
        
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.style.display = 'none';
                }
            });
        });
        
        // Поиск по Enter
        document.getElementById('auditFilterUsername')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.applyFilters();
        });
    },
    
    attachTableEvents() {
        document.querySelectorAll('.view-detail').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDetailModal(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.audit-row').forEach(row => {
            row.addEventListener('click', () => {
                this.showDetailModal(row.dataset.id);
            });
        });
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Экспорт глобально
window.AuditModule = AuditModule;
