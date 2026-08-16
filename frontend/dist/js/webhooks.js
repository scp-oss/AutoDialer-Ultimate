// webhooks.js - Модуль управления Webhooks (только для admin)
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast)

const WebhooksModule = {
    currentPage: 1,
    pageSize: 20,
    totalPages: 1,
    totalRecords: 0,
    webhooks: [],
    
    // Доступные события
    availableEvents: [
        { value: 'call.started', label: 'Звонок начат', category: 'calls' },
        { value: 'call.answered', label: 'Звонок отвечен', category: 'calls' },
        { value: 'call.completed', label: 'Звонок завершён', category: 'calls' },
        { value: 'call.failed', label: 'Звонок не удался', category: 'calls' },
        { value: 'call.no_answer', label: 'Нет ответа', category: 'calls' },
        { value: 'call.busy', label: 'Занято', category: 'calls' },
        { value: 'call.dtmf', label: 'DTMF нажатие', category: 'calls' },
        { value: 'campaign.started', label: 'Кампания запущена', category: 'campaigns' },
        { value: 'campaign.paused', label: 'Кампания приостановлена', category: 'campaigns' },
        { value: 'campaign.resumed', label: 'Кампания возобновлена', category: 'campaigns' },
        { value: 'campaign.stopped', label: 'Кампания остановлена', category: 'campaigns' },
        { value: 'campaign.completed', label: 'Кампания завершена', category: 'campaigns' },
        { value: 'contact.created', label: 'Контакт создан', category: 'contacts' },
        { value: 'contact.updated', label: 'Контакт обновлён', category: 'contacts' },
        { value: 'contact.deleted', label: 'Контакт удалён', category: 'contacts' },
        { value: 'blacklist.added', label: 'Добавлен в ЧС', category: 'blacklist' },
        { value: 'blacklist.removed', label: 'Удалён из ЧС', category: 'blacklist' },
        { value: 'incoming.call', label: 'Входящий звонок', category: 'incoming' },
        { value: 'transcription.completed', label: 'Транскрибация завершена', category: 'incoming' },
        { value: 'system.error', label: 'Системная ошибка', category: 'system' },
        { value: 'system.warning', label: 'Системное предупреждение', category: 'system' }
    ],
    
    // Инициализация модуля
    init() {
        // Проверка прав доступа
        if (AppState.userRole !== 'admin') {
            this.renderAccessDenied();
            return;
        }
        
        this.render();
        this.attachEventListeners();
        this.loadWebhooks();
    },
    
    // Рендер страницы при отказе в доступе
    renderAccessDenied() {
        const container = document.getElementById('webhooksContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="access-denied">
                <div class="access-denied-icon">🔒</div>
                <h2>Доступ запрещён</h2>
                <p>У вас нет прав для просмотра этой страницы.</p>
                <p>Только администраторы могут управлять Webhooks.</p>
            </div>
        `;
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('webhooksContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="webhooks-page">
                <div class="page-header">
                    <h2>🪝 Webhooks</h2>
                    <div class="header-actions">
                        <button class="btn btn-primary" id="webhookAddBtn">
                            ➕ Добавить Webhook
                        </button>
                        <button class="btn btn-outline" id="webhookRefreshBtn">
                            🔄 Обновить
                        </button>
                        <button class="btn btn-outline" id="webhookDocsBtn">
                            📚 Документация
                        </button>
                    </div>
                </div>
                
                <p class="text-muted">
                    Webhooks позволяют отправлять HTTP-запросы на ваш сервер при наступлении определённых событий.
                    Используйте для интеграции с CRM, телефонией или другими системами.
                </p>
                
                <!-- Информация о формате -->
                <div class="webhook-info-panel">
                    <div class="info-header">
                        <span>📤 Формат отправляемых данных</span>
                        <button class="btn btn-sm btn-outline" id="toggleFormatInfo">Показать пример</button>
                    </div>
                    <div id="formatExample" class="format-example" style="display: none;">
                        <pre>{
  "event": "call.completed",
  "timestamp": "2024-01-15T14:30:00Z",
  "data": {
    "call_id": 12345,
    "phone": "+79161234567",
    "status": "answered",
    "duration": 45,
    "campaign_id": 1,
    "campaign_name": "Обзвон клиентов",
    "dtmf_result": "1",
    "recording_url": "https://..."
  }
}</pre>
                        <p class="text-muted">
                            <strong>Заголовки:</strong> X-Webhook-Signature (HMAC-SHA256 подпись), X-Event-Type, X-Delivery-ID
                        </p>
                    </div>
                </div>
                
                <!-- Таблица -->
                <div class="webhooks-table-container">
                    <table class="table" id="webhooksTable">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Название</th>
                                <th>URL</th>
                                <th>События</th>
                                <th>Статус</th>
                                <th>Статистика</th>
                                <th>Последняя доставка</th>
                                <th width="120">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="webhooksTableBody">
                            <tr><td colspan="8" class="text-center">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                
                <!-- Пагинация -->
                <div id="webhooksPagination" class="pagination-container"></div>
            </div>
            
            <!-- Модальное окно добавления/редактирования -->
            <div id="webhookModal" class="modal" style="display: none;">
                <div class="modal-content modal-lg">
                    <div class="modal-header">
                        <h3 id="webhookModalTitle">Добавить Webhook</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="webhookForm">
                            <input type="hidden" id="webhookId">
                            
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Название <span class="required">*</span></label>
                                    <input type="text" 
                                           id="webhookName" 
                                           class="form-control" 
                                           placeholder="Например: Уведомления в CRM"
                                           required>
                                </div>
                                
                                <div class="form-group">
                                    <label>URL <span class="required">*</span></label>
                                    <input type="url" 
                                           id="webhookUrl" 
                                           class="form-control" 
                                           placeholder="https://your-server.com/webhook"
                                           required>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>Описание (опционально)</label>
                                <textarea id="webhookDescription" 
                                          class="form-control" 
                                          rows="2"
                                          placeholder="Для чего используется этот webhook..."></textarea>
                            </div>
                            
                            <div class="form-group">
                                <label>Секретный ключ (для подписи)</label>
                                <div class="secret-input-wrapper">
                                    <input type="password" 
                                           id="webhookSecret" 
                                           class="form-control" 
                                           placeholder="Оставьте пустым для авто-генерации">
                                    <button type="button" class="btn btn-outline generate-secret-btn" title="Сгенерировать ключ">🎲</button>
                                    <button type="button" class="btn btn-outline toggle-secret-btn" title="Показать/скрыть">👁️</button>
                                </div>
                                <small class="form-text">
                                    Используется для проверки подписи X-Webhook-Signature в заголовке запроса
                                </small>
                            </div>
                            
                            <div class="form-group">
                                <label>События <span class="required">*</span></label>
                                <div class="events-selection">
                                    <div class="events-toolbar">
                                        <button type="button" class="btn btn-sm btn-outline" id="selectAllEvents">Выбрать все</button>
                                        <button type="button" class="btn btn-sm btn-outline" id="deselectAllEvents">Снять все</button>
                                        <select id="eventCategoryFilter" class="form-control form-control-sm">
                                            <option value="">Все категории</option>
                                            <option value="calls">Звонки</option>
                                            <option value="campaigns">Кампании</option>
                                            <option value="contacts">Контакты</option>
                                            <option value="blacklist">Чёрный список</option>
                                            <option value="incoming">Входящие</option>
                                            <option value="system">Система</option>
                                        </select>
                                    </div>
                                    <div class="events-grid" id="eventsGrid"></div>
                                </div>
                            </div>
                            
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Фильтр по кампании (опционально)</label>
                                    <select id="webhookCampaignFilter" class="form-control">
                                        <option value="">Все кампании</option>
                                    </select>
                                </div>
                                
                                <div class="form-group">
                                    <label>Фильтр по статусу (опционально)</label>
                                    <select id="webhookStatusFilter" class="form-control">
                                        <option value="">Все статусы</option>
                                        <option value="answered">Отвечен</option>
                                        <option value="no_answer">Нет ответа</option>
                                        <option value="busy">Занято</option>
                                        <option value="failed">Ошибка</option>
                                    </select>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>Дополнительные заголовки (опционально)</label>
                                <div id="customHeadersContainer">
                                    <div class="custom-header-row">
                                        <input type="text" class="form-control" placeholder="Заголовок" style="flex: 1;">
                                        <input type="text" class="form-control" placeholder="Значение" style="flex: 2;">
                                        <button type="button" class="btn btn-sm btn-outline remove-header-btn" disabled>✖</button>
                                    </div>
                                </div>
                                <button type="button" class="btn btn-sm btn-outline" id="addHeaderBtn">➕ Добавить заголовок</button>
                            </div>
                            
                            <div class="form-group">
                                <label>Настройки повторных попыток</label>
                                <div class="form-row">
                                    <div class="form-group">
                                        <label>Макс. попыток</label>
                                        <input type="number" 
                                               id="webhookMaxRetries" 
                                               class="form-control" 
                                               value="3"
                                               min="0"
                                               max="10">
                                    </div>
                                    <div class="form-group">
                                        <label>Интервал (сек)</label>
                                        <input type="number" 
                                               id="webhookRetryDelay" 
                                               class="form-control" 
                                               value="60"
                                               min="10"
                                               max="3600">
                                    </div>
                                    <div class="form-group">
                                        <label>Таймаут (сек)</label>
                                        <input type="number" 
                                               id="webhookTimeout" 
                                               class="form-control" 
                                               value="10"
                                               min="1"
                                               max="60">
                                    </div>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>
                                    <input type="checkbox" id="webhookActive" checked>
                                    Webhook активен
                                </label>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="WebhooksModule.closeModal()">
                                    Отмена
                                </button>
                                <button type="button" class="btn btn-outline" id="testWebhookBtn">
                                    🧪 Тест
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    Сохранить
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно деталей -->
            <div id="webhookDetailModal" class="modal" style="display: none;">
                <div class="modal-content modal-lg">
                    <div class="modal-header">
                        <h3>Информация о Webhook</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body" id="webhookDetailContent">
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно доставок -->
            <div id="webhookDeliveriesModal" class="modal" style="display: none;">
                <div class="modal-content modal-lg">
                    <div class="modal-header">
                        <h3>История доставок</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body" id="webhookDeliveriesContent">
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно подтверждения удаления -->
            <div id="webhookDeleteModal" class="modal" style="display: none;">
                <div class="modal-content modal-sm">
                    <div class="modal-header">
                        <h3>Подтверждение удаления</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p id="webhookDeleteMessage">Вы уверены, что хотите удалить Webhook?</p>
                        
                        <div class="form-actions">
                            <button type="button" class="btn btn-outline" onclick="WebhooksModule.closeDeleteModal()">
                                Отмена
                            </button>
                            <button type="button" class="btn btn-danger" id="confirmDeleteWebhookBtn">
                                Удалить
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Рендер списка событий
        this.renderEventsGrid();
        // Загрузка кампаний для фильтра
        this.loadCampaignsForFilter();
    },
    
    // Рендер сетки событий
    renderEventsGrid(selectedEvents = []) {
        const grid = document.getElementById('eventsGrid');
        if (!grid) return;
        
        // Группировка по категориям
        const categories = {};
        this.availableEvents.forEach(event => {
            if (!categories[event.category]) {
                categories[event.category] = [];
            }
            categories[event.category].push(event);
        });
        
        const categoryNames = {
            'calls': '📞 Звонки',
            'campaigns': '📊 Кампании',
            'contacts': '👥 Контакты',
            'blacklist': '🚫 Чёрный список',
            'incoming': '📥 Входящие',
            'system': '⚙️ Система'
        };
        
        let html = '';
        Object.entries(categories).forEach(([category, events]) => {
            html += `
                <div class="event-category" data-category="${category}">
                    <h4>${categoryNames[category] || category}</h4>
                    <div class="event-list">
                        ${events.map(event => `
                            <label class="event-item">
                                <input type="checkbox" 
                                       name="webhookEvents" 
                                       value="${event.value}"
                                       ${selectedEvents.includes(event.value) ? 'checked' : ''}>
                                <span>${event.label}</span>
                            </label>
                        `).join('')}
                    </div>
                </div>
            `;
        });
        
        grid.innerHTML = html;
    },
    
    // Загрузка кампаний для фильтра
    async loadCampaignsForFilter() {
        try {
            const response = await authFetch(`${API_BASE}/campaigns/?limit=100`);
            if (response.ok) {
                const campaigns = await response.json();
                const select = document.getElementById('webhookCampaignFilter');
                if (select) {
                    const options = campaigns.map(c => 
                        `<option value="${c.id}">${this.escapeHtml(c.name)}</option>`
                    ).join('');
                    select.innerHTML = '<option value="">Все кампании</option>' + options;
                }
            }
        } catch (error) {
            console.error('Load campaigns failed:', error);
        }
    },
    
    // Загрузка webhooks
    async loadWebhooks(page = 1) {
        this.currentPage = page;
        
        const tbody = document.getElementById('webhooksTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Загрузка...</td></tr>';
        
        try {
            const response = await authFetch(`${API_BASE}/webhooks?page=${page}&page_size=${this.pageSize}`);
            if (response.ok) {
                const data = await response.json();
                this.webhooks = data.items || data || [];
                this.totalRecords = data.total || this.webhooks.length;
                this.totalPages = Math.ceil(this.totalRecords / this.pageSize) || 1;
                
                this.renderTable();
                this.renderPagination();
            } else {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('Webhooks load failed:', error);
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    // Рендер таблицы
    renderTable() {
        const tbody = document.getElementById('webhooksTableBody');
        
        if (this.webhooks.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">🪝</div>
                            <p>Нет Webhook подписок</p>
                            <button class="btn btn-primary" onclick="WebhooksModule.openModal()">
                                Добавить Webhook
                            </button>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.webhooks.map(webhook => `
            <tr data-id="${webhook.id}" class="webhook-row ${webhook.is_active ? '' : 'inactive'}">
                <td>${webhook.id}</td>
                <td>
                    <strong>${this.escapeHtml(webhook.name)}</strong>
                    ${webhook.description ? `<br><small>${this.escapeHtml(webhook.description)}</small>` : ''}
                </td>
                <td>
                    <code class="webhook-url">${this.escapeHtml(this.truncateUrl(webhook.url))}</code>
                </td>
                <td>
                    <span class="events-count">${webhook.events?.length || 0} событий</span>
                    <div class="events-preview">
                        ${this.formatEventsPreview(webhook.events)}
                    </div>
                </td>
                <td>
                    <span class="status-badge ${webhook.is_active ? 'status-active' : 'status-inactive'}">
                        ${webhook.is_active ? '✅ Активен' : '⏸️ Неактивен'}
                    </span>
                </td>
                <td>
                    <div class="stats-mini">
                        <span class="stat-success" title="Успешно">✅ ${webhook.success_count || 0}</span>
                        <span class="stat-failed" title="Ошибок">❌ ${webhook.failure_count || 0}</span>
                        <span class="stat-pending" title="В очереди">⏳ ${webhook.pending_count || 0}</span>
                    </div>
                </td>
                <td>
                    ${webhook.last_delivery_at ? this.formatDateTime(webhook.last_delivery_at) : '—'}
                    ${webhook.last_delivery_status ? this.getStatusIcon(webhook.last_delivery_status) : ''}
                </td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline view-webhook" 
                                data-id="${webhook.id}"
                                title="Подробнее">👁️</button>
                        <button class="btn btn-sm btn-outline deliveries-webhook" 
                                data-id="${webhook.id}"
                                title="История доставок">📋</button>
                        <button class="btn btn-sm btn-outline edit-webhook" 
                                data-id="${webhook.id}"
                                title="Редактировать">✏️</button>
                        <button class="btn btn-sm btn-outline test-webhook" 
                                data-id="${webhook.id}"
                                title="Тест">🧪</button>
                        <button class="btn btn-sm btn-outline-danger delete-webhook" 
                                data-id="${webhook.id}"
                                data-name="${this.escapeHtml(webhook.name)}"
                                title="Удалить">🗑️</button>
                    </div>
                </td>
            </tr>
        `).join('');
        
        this.attachTableEvents();
    },
    
    // Рендер пагинации
    renderPagination() {
        const container = document.getElementById('webhooksPagination');
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
                this.loadWebhooks(parseInt(btn.dataset.page));
            });
        });
    },
    
    // ============ МОДАЛЬНЫЕ ОКНА ============
    
    openModal(webhook = null) {
        const modal = document.getElementById('webhookModal');
        const title = document.getElementById('webhookModalTitle');
        
        this.renderEventsGrid(webhook?.events || []);
        
        if (webhook) {
            title.textContent = 'Редактировать Webhook';
            document.getElementById('webhookId').value = webhook.id;
            document.getElementById('webhookName').value = webhook.name;
            document.getElementById('webhookUrl').value = webhook.url;
            document.getElementById('webhookDescription').value = webhook.description || '';
            document.getElementById('webhookSecret').value = '';
            document.getElementById('webhookSecret').placeholder = 'Оставьте пустым, чтобы не менять';
            document.getElementById('webhookCampaignFilter').value = webhook.campaign_filter || '';
            document.getElementById('webhookStatusFilter').value = webhook.status_filter || '';
            document.getElementById('webhookMaxRetries').value = webhook.max_retries || 3;
            document.getElementById('webhookRetryDelay').value = webhook.retry_delay || 60;
            document.getElementById('webhookTimeout').value = webhook.timeout || 10;
            document.getElementById('webhookActive').checked = webhook.is_active;
            
            // Загрузка пользовательских заголовков
            this.loadCustomHeaders(webhook.headers || {});
        } else {
            title.textContent = 'Добавить Webhook';
            document.getElementById('webhookId').value = '';
            document.getElementById('webhookForm').reset();
            document.getElementById('webhookSecret').placeholder = 'Оставьте пустым для авто-генерации';
            document.getElementById('webhookMaxRetries').value = 3;
            document.getElementById('webhookRetryDelay').value = 60;
            document.getElementById('webhookTimeout').value = 10;
            document.getElementById('webhookActive').checked = true;
            
            this.loadCustomHeaders({});
        }
        
        modal.style.display = 'flex';
    },
    
    closeModal() {
        document.getElementById('webhookModal').style.display = 'none';
    },
    
    loadCustomHeaders(headers) {
        const container = document.getElementById('customHeadersContainer');
        container.innerHTML = '';
        
        Object.entries(headers).forEach(([key, value]) => {
            this.addCustomHeaderRow(key, value);
        });
        
        // Добавляем пустую строку
        this.addCustomHeaderRow('', '');
    },
    
    addCustomHeaderRow(key = '', value = '') {
        const container = document.getElementById('customHeadersContainer');
        const row = document.createElement('div');
        row.className = 'custom-header-row';
        row.innerHTML = `
            <input type="text" class="form-control" placeholder="Заголовок" value="${this.escapeHtml(key)}" style="flex: 1;">
            <input type="text" class="form-control" placeholder="Значение" value="${this.escapeHtml(value)}" style="flex: 2;">
            <button type="button" class="btn btn-sm btn-outline remove-header-btn">✖</button>
        `;
        
        row.querySelector('.remove-header-btn').addEventListener('click', () => {
            if (container.children.length > 1) {
                row.remove();
            } else {
                row.querySelectorAll('input').forEach(input => input.value = '');
            }
        });
        
        container.appendChild(row);
    },
    
    getCustomHeaders() {
        const headers = {};
        document.querySelectorAll('.custom-header-row').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const key = inputs[0].value.trim();
            const value = inputs[1].value.trim();
            if (key && value) {
                headers[key] = value;
            }
        });
        return Object.keys(headers).length > 0 ? headers : null;
    },
    
    async showDetailModal(webhookId) {
        try {
            const response = await authFetch(`${API_BASE}/webhooks/${webhookId}`);
            if (!response.ok) throw new Error('Failed to load');
            
            const webhook = await response.json();
            
            const content = document.getElementById('webhookDetailContent');
            content.innerHTML = `
                <div class="webhook-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID:</td><td>${webhook.id}</td></tr>
                            <tr><td>Название:</td><td>${this.escapeHtml(webhook.name)}</td></tr>
                            <tr><td>URL:</td><td><code>${this.escapeHtml(webhook.url)}</code></td></tr>
                            <tr><td>Описание:</td><td>${this.escapeHtml(webhook.description || '—')}</td></tr>
                            <tr><td>Статус:</td><td>${webhook.is_active ? '✅ Активен' : '⏸️ Неактивен'}</td></tr>
                        </table>
                    </div>
                    
                    <div class="detail-section">
                        <h4>События (${webhook.events?.length || 0})</h4>
                        <div class="events-list">
                            ${webhook.events?.map(e => {
                                const eventInfo = this.availableEvents.find(ev => ev.value === e);
                                return `<span class="event-tag">${eventInfo?.label || e}</span>`;
                            }).join('') || '—'}
                        </div>
                    </div>
                    
                    <div class="detail-section">
                        <h4>Статистика</h4>
                        <table class="details-table">
                            <tr><td>Успешно:</td><td>${webhook.success_count || 0}</td></tr>
                            <tr><td>Ошибок:</td><td>${webhook.failure_count || 0}</td></tr>
                            <tr><td>В очереди:</td><td>${webhook.pending_count || 0}</td></tr>
                            <tr><td>Последняя доставка:</td><td>${this.formatDateTime(webhook.last_delivery_at)}</td></tr>
                            <tr><td>Последний статус:</td><td>${webhook.last_delivery_status ? this.getStatusIcon(webhook.last_delivery_status) + ' ' + webhook.last_delivery_status : '—'}</td></tr>
                            <tr><td>Создан:</td><td>${this.formatDateTime(webhook.created_at)}</td></tr>
                        </table>
                    </div>
                </div>
            `;
            
            document.getElementById('webhookDetailModal').style.display = 'flex';
        } catch (error) {
            console.error('Load webhook detail failed:', error);
            showToast('Ошибка загрузки', 'error');
        }
    },
    
    closeDetailModal() {
        document.getElementById('webhookDetailModal').style.display = 'none';
    },
    
    async showDeliveriesModal(webhookId) {
        const modal = document.getElementById('webhookDeliveriesModal');
        const content = document.getElementById('webhookDeliveriesContent');
        
        content.innerHTML = '<p class="text-center">Загрузка...</p>';
        modal.style.display = 'flex';
        
        try {
            const response = await authFetch(`${API_BASE}/webhooks/${webhookId}/deliveries?limit=20`);
            if (!response.ok) throw new Error('Failed to load');
            
            const deliveries = await response.json();
            
            if (!deliveries || deliveries.length === 0) {
                content.innerHTML = '<p class="text-center">Нет записей о доставках</p>';
                return;
            }
            
            content.innerHTML = `
                <table class="table">
                    <thead>
                        <tr>
                            <th>Время</th>
                            <th>Событие</th>
                            <th>Статус</th>
                            <th>Код ответа</th>
                            <th>Попытка</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${deliveries.map(d => `
                            <tr>
                                <td>${this.formatDateTime(d.created_at)}</td>
                                <td>${this.escapeHtml(d.event)}</td>
                                <td>${this.getStatusIcon(d.status)} ${d.status}</td>
                                <td>${d.response_code || '—'}</td>
                                <td>${d.attempt || 1}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        } catch (error) {
            console.error('Load deliveries failed:', error);
            content.innerHTML = '<p class="text-center text-error">Ошибка загрузки</p>';
        }
    },
    
    closeDeliveriesModal() {
        document.getElementById('webhookDeliveriesModal').style.display = 'none';
    },
    
    openDeleteModal(webhookId, webhookName) {
        const modal = document.getElementById('webhookDeleteModal');
        document.getElementById('webhookDeleteMessage').textContent = 
            `Вы уверены, что хотите удалить Webhook "${webhookName}"?`;
        document.getElementById('confirmDeleteWebhookBtn').dataset.id = webhookId;
        
        modal.style.display = 'flex';
    },
    
    closeDeleteModal() {
        document.getElementById('webhookDeleteModal').style.display = 'none';
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async saveWebhook() {
        const id = document.getElementById('webhookId').value;
        const name = document.getElementById('webhookName').value;
        const url = document.getElementById('webhookUrl').value;
        const description = document.getElementById('webhookDescription').value;
        const secret = document.getElementById('webhookSecret').value;
        const campaignFilter = document.getElementById('webhookCampaignFilter').value;
        const statusFilter = document.getElementById('webhookStatusFilter').value;
        const maxRetries = parseInt(document.getElementById('webhookMaxRetries').value);
        const retryDelay = parseInt(document.getElementById('webhookRetryDelay').value);
        const timeout = parseInt(document.getElementById('webhookTimeout').value);
        const isActive = document.getElementById('webhookActive').checked;
        
        if (!name || !url) {
            showToast('Название и URL обязательны', 'warning');
            return;
        }
        
        // Сбор событий
        const events = [];
        document.querySelectorAll('input[name="webhookEvents"]:checked').forEach(cb => {
            events.push(cb.value);
        });
        
        if (events.length === 0) {
            showToast('Выберите хотя бы одно событие', 'warning');
            return;
        }
        
        const data = {
            name,
            url,
            description: description || null,
            events,
            secret: secret || null,
            campaign_filter: campaignFilter || null,
            status_filter: statusFilter || null,
            max_retries: maxRetries,
            retry_delay: retryDelay,
            timeout,
            is_active: isActive,
            headers: this.getCustomHeaders()
        };
        
        const submitBtn = document.querySelector('#webhookForm button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = '⏳ Сохранение...';
        
        try {
            const urlPath = id ? `${API_BASE}/webhooks/${id}` : `${API_BASE}/webhooks`;
            const method = id ? 'PUT' : 'POST';
            
            const response = await authFetch(urlPath, {
                method,
                body: JSON.stringify(data)
            });
            
            if (response.ok) {
                showToast(id ? 'Webhook обновлён' : 'Webhook создан', 'success');
                this.closeModal();
                await this.loadWebhooks();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка сохранения', 'error');
            }
        } catch (error) {
            console.error('Save webhook failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    },
    
    async testWebhook(webhookId = null) {
        let id = webhookId;
        let testData = null;
        
        if (!id) {
            // Тест из формы создания
            const url = document.getElementById('webhookUrl').value;
            if (!url) {
                showToast('Укажите URL для теста', 'warning');
                return;
            }
            
            testData = { url };
        }
        
        const btn = event.target;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Отправка...';
        
        try {
            const response = await authFetch(`${API_BASE}/webhooks/test`, {
                method: 'POST',
                body: JSON.stringify(id ? { webhook_id: id } : testData)
            });
            
            if (response.ok) {
                const result = await response.json();
                showToast(`Тест успешен! Код ответа: ${result.status_code}`, 'success');
            } else {
                const err = await response.json();
                showToast(`Ошибка теста: ${err.detail || 'Неизвестная ошибка'}`, 'error');
            }
        } catch (error) {
            console.error('Test webhook failed:', error);
            showToast('Ошибка отправки теста', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    },
    
    async deleteWebhook() {
        const webhookId = document.getElementById('confirmDeleteWebhookBtn').dataset.id;
        
        const btn = document.getElementById('confirmDeleteWebhookBtn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Удаление...';
        
        try {
            const response = await authFetch(`${API_BASE}/webhooks/${webhookId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                showToast('Webhook удалён', 'success');
                this.closeDeleteModal();
                await this.loadWebhooks();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка удаления', 'error');
            }
        } catch (error) {
            console.error('Delete webhook failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    },
    
    generateSecret() {
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        let secret = '';
        for (let i = 0; i < 32; i++) {
            secret += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        document.getElementById('webhookSecret').value = secret;
        showToast('Ключ сгенерирован', 'success');
    },
    
    toggleSecret() {
        const input = document.getElementById('webhookSecret');
        input.type = input.type === 'password' ? 'text' : 'password';
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    formatEventsPreview(events) {
        if (!events || events.length === 0) return '—';
        
        const preview = events.slice(0, 3).map(e => {
            const eventInfo = this.availableEvents.find(ev => ev.value === e);
            return eventInfo?.label || e;
        }).join(', ');
        
        return events.length > 3 ? preview + ` и ещё ${events.length - 3}` : preview;
    },
    
    getStatusIcon(status) {
        const icons = {
            'success': '✅',
            'failed': '❌',
            'pending': '⏳',
            'processing': '🔄'
        };
        return icons[status] || '❓';
    },
    
    truncateUrl(url) {
        if (!url) return '';
        if (url.length <= 40) return url;
        return url.substring(0, 37) + '...';
    },
    
    formatDateTime(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).replace(',', '');
    },
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        document.getElementById('webhookAddBtn')?.addEventListener('click', () => this.openModal());
        document.getElementById('webhookRefreshBtn')?.addEventListener('click', () => this.loadWebhooks());
        document.getElementById('webhookDocsBtn')?.addEventListener('click', () => window.open('/docs#/webhooks', '_blank'));
        
        document.getElementById('toggleFormatInfo')?.addEventListener('click', () => {
            const el = document.getElementById('formatExample');
            el.style.display = el.style.display === 'none' ? 'block' : 'none';
        });
        
        document.getElementById('webhookForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveWebhook();
        });
        
        document.getElementById('testWebhookBtn')?.addEventListener('click', () => this.testWebhook());
        
        document.querySelector('.generate-secret-btn')?.addEventListener('click', () => this.generateSecret());
        document.querySelector('.toggle-secret-btn')?.addEventListener('click', () => this.toggleSecret());
        
        document.getElementById('addHeaderBtn')?.addEventListener('click', () => this.addCustomHeaderRow());
        
        document.getElementById('selectAllEvents')?.addEventListener('click', () => {
            document.querySelectorAll('input[name="webhookEvents"]').forEach(cb => cb.checked = true);
        });
        
        document.getElementById('deselectAllEvents')?.addEventListener('click', () => {
            document.querySelectorAll('input[name="webhookEvents"]').forEach(cb => cb.checked = false);
        });
        
        document.getElementById('eventCategoryFilter')?.addEventListener('change', (e) => {
            const category = e.target.value;
            document.querySelectorAll('.event-category').forEach(el => {
                if (!category || el.dataset.category === category) {
                    el.style.display = 'block';
                } else {
                    el.style.display = 'none';
                }
            });
        });
        
        document.getElementById('confirmDeleteWebhookBtn')?.addEventListener('click', () => this.deleteWebhook());
        
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
    },
    
    attachTableEvents() {
        document.querySelectorAll('.view-webhook').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDetailModal(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.deliveries-webhook').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDeliveriesModal(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.edit-webhook').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                const webhook = this.webhooks.find(w => w.id == id);
                if (webhook) this.openModal(webhook);
            });
        });
        
        document.querySelectorAll('.test-webhook').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.testWebhook(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.delete-webhook').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openDeleteModal(btn.dataset.id, btn.dataset.name);
            });
        });
        
        document.querySelectorAll('.webhook-row').forEach(row => {
            row.addEventListener('click', () => {
                this.showDetailModal(row.dataset.id);
            });
        });
    }
};

// Экспорт глобально
window.WebhooksModule = WebhooksModule;
App.webhooks = WebhooksModule;
