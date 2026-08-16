// apiTokens.js - Модуль управления API токенами (только для admin)
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast)

const ApiTokensModule = {
    currentPage: 1,
    pageSize: 20,
    totalPages: 1,
    totalRecords: 0,
    tokens: [],
    
    // Инициализация модуля
    init() {
        // Проверка прав доступа
        if (AppState.userRole !== 'admin') {
            this.renderAccessDenied();
            return;
        }
        
        this.render();
        this.attachEventListeners();
        this.loadTokens();
    },
    
    // Рендер страницы при отказе в доступе
    renderAccessDenied() {
        const container = document.getElementById('apiTokensContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="access-denied">
                <div class="access-denied-icon">🔒</div>
                <h2>Доступ запрещён</h2>
                <p>У вас нет прав для просмотра этой страницы.</p>
                <p>Только администраторы могут управлять API токенами.</p>
            </div>
        `;
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('apiTokensContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="apitokens-page">
                <div class="page-header">
                    <h2>🔑 API токены</h2>
                    <div class="header-actions">
                        <button class="btn btn-primary" id="tokenCreateBtn">
                            ➕ Создать токен
                        </button>
                        <button class="btn btn-outline" id="tokenRefreshBtn">
                            🔄 Обновить
                        </button>
                    </div>
                </div>
                
                <p class="text-muted">
                    API токены используются для доступа к REST API системы.
                    Храните токены в безопасности и не передавайте третьим лицам.
                </p>
                
                <!-- Информация о API -->
                <div class="api-info-panel">
                    <div class="info-item">
                        <span class="info-label">📚 Документация API:</span>
                        <a href="/docs" target="_blank" class="info-link">Swagger UI</a>
                        <span class="info-separator">|</span>
                        <a href="/redoc" target="_blank" class="info-link">ReDoc</a>
                    </div>
                    <div class="info-item">
                        <span class="info-label">🔗 Базовый URL:</span>
                        <code id="apiBaseUrl">${window.location.origin}/api</code>
                        <button class="btn btn-sm btn-outline copy-btn" data-copy="${window.location.origin}/api" title="Копировать URL">📋</button>
                    </div>
                    <div class="info-item">
                        <span class="info-label">📖 Пример использования:</span>
                        <code>curl -H "Authorization: Bearer YOUR_TOKEN" ${window.location.origin}/api/campaigns</code>
                    </div>
                </div>
                
                <!-- Таблица -->
                <div class="apitokens-table-container">
                    <table class="table" id="apiTokensTable">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Название</th>
                                <th>Токен</th>
                                <th>Создан</th>
                                <th>Истекает</th>
                                <th>Последнее использование</th>
                                <th>Использований</th>
                                <th width="100">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="apiTokensTableBody">
                            <tr><td colspan="8" class="text-center">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                
                <!-- Пагинация -->
                <div id="apiTokensPagination" class="pagination-container"></div>
            </div>
            
            <!-- Модальное окно создания токена -->
            <div id="tokenCreateModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Создать API токен</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="tokenCreateForm">
                            <div class="form-group">
                                <label>Название токена <span class="required">*</span></label>
                                <input type="text" 
                                       id="tokenName" 
                                       class="form-control" 
                                       placeholder="Например: Интеграция с CRM"
                                       required>
                                <small class="form-text">Описательное название, чтобы помнить для чего токен</small>
                            </div>
                            
                            <div class="form-group">
                                <label>Описание (опционально)</label>
                                <textarea id="tokenDescription" 
                                          class="form-control" 
                                          rows="2"
                                          placeholder="Дополнительная информация..."></textarea>
                            </div>
                            
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Срок действия</label>
                                    <select id="tokenExpires" class="form-control">
                                        <option value="">Никогда</option>
                                        <option value="30">30 дней</option>
                                        <option value="60">60 дней</option>
                                        <option value="90">90 дней</option>
                                        <option value="180">180 дней</option>
                                        <option value="365">365 дней</option>
                                    </select>
                                </div>
                                
                                <div class="form-group">
                                    <label>Или до даты</label>
                                    <input type="date" 
                                           id="tokenExpiresAt" 
                                           class="form-control"
                                           min="${new Date().toISOString().split('T')[0]}">
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>Разрешения (опционально)</label>
                                <div class="permissions-grid">
                                    <label><input type="checkbox" name="permission" value="campaigns:read"> Чтение кампаний</label>
                                    <label><input type="checkbox" name="permission" value="campaigns:write"> Управление кампаниями</label>
                                    <label><input type="checkbox" name="permission" value="contacts:read"> Чтение контактов</label>
                                    <label><input type="checkbox" name="permission" value="contacts:write"> Управление контактами</label>
                                    <label><input type="checkbox" name="permission" value="history:read"> Чтение истории</label>
                                    <label><input type="checkbox" name="permission" value="audio:read"> Чтение аудио</label>
                                    <label><input type="checkbox" name="permission" value="audio:write"> Управление аудио</label>
                                    <label><input type="checkbox" name="permission" value="blacklist:read"> Чтение ЧС</label>
                                    <label><input type="checkbox" name="permission" value="blacklist:write"> Управление ЧС</label>
                                    <label><input type="checkbox" name="permission" value="incoming:read"> Входящие звонки</label>
                                </div>
                                <small class="form-text">Если ничего не выбрано — токен имеет те же права, что и создатель</small>
                            </div>
                            
                            <div class="form-group">
                                <label>IP ограничения (опционально)</label>
                                <input type="text" 
                                       id="tokenAllowedIps" 
                                       class="form-control" 
                                       placeholder="192.168.1.0/24, 10.0.0.1">
                                <small class="form-text">Список IP адресов или подсетей через запятую</small>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="ApiTokensModule.closeCreateModal()">
                                    Отмена
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    Создать токен
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно с созданным токеном -->
            <div id="tokenCreatedModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>✅ Токен создан</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="token-created-info">
                            <div class="warning-box">
                                <strong>⚠️ Внимание!</strong>
                                <p>Токен показан только один раз. Сохраните его в безопасном месте!</p>
                            </div>
                            
                            <div class="form-group">
                                <label>Ваш API токен:</label>
                                <div class="token-display">
                                    <code id="newTokenValue" class="token-value"></code>
                                    <button class="btn btn-outline copy-token-btn" title="Копировать токен">📋</button>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>Пример использования:</label>
                                <pre id="tokenExample" class="code-example"></pre>
                                <button class="btn btn-sm btn-outline copy-example-btn" title="Копировать пример">📋 Копировать</button>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-primary" onclick="ApiTokensModule.closeCreatedModal()">
                                    Я сохранил токен
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно деталей токена -->
            <div id="tokenDetailModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Информация о токене</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body" id="tokenDetailContent">
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно подтверждения удаления -->
            <div id="tokenDeleteModal" class="modal" style="display: none;">
                <div class="modal-content modal-sm">
                    <div class="modal-header">
                        <h3>Подтверждение удаления</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p id="tokenDeleteMessage">Вы уверены, что хотите отозвать токен?</p>
                        <p class="text-warning">⚠️ Приложения, использующие этот токен, потеряют доступ!</p>
                        
                        <div class="form-actions">
                            <button type="button" class="btn btn-outline" onclick="ApiTokensModule.closeDeleteModal()">
                                Отмена
                            </button>
                            <button type="button" class="btn btn-danger" id="confirmDeleteTokenBtn">
                                Отозвать токен
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Привязка кнопок копирования
        this.attachCopyButtons();
    },
    
    // Загрузка токенов
    async loadTokens(page = 1) {
        this.currentPage = page;
        
        const tbody = document.getElementById('apiTokensTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Загрузка...</td></tr>';
        
        try {
            const response = await authFetch(`${API_BASE}/tokens?page=${page}&page_size=${this.pageSize}`);
            if (response.ok) {
                const data = await response.json();
                this.tokens = data.items || data || [];
                this.totalRecords = data.total || this.tokens.length;
                this.totalPages = Math.ceil(this.totalRecords / this.pageSize) || 1;
                
                this.renderTable();
                this.renderPagination();
            } else {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('Tokens load failed:', error);
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    // Рендер таблицы
    renderTable() {
        const tbody = document.getElementById('apiTokensTableBody');
        
        if (this.tokens.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">🔑</div>
                            <p>Нет API токенов</p>
                            <button class="btn btn-primary" onclick="ApiTokensModule.openCreateModal()">
                                Создать первый токен
                            </button>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.tokens.map(token => `
            <tr data-id="${token.id}" class="token-row ${token.is_active ? '' : 'inactive'}">
                <td>${token.id}</td>
                <td>
                    <strong>${this.escapeHtml(token.name)}</strong>
                    ${token.description ? `<br><small>${this.escapeHtml(token.description)}</small>` : ''}
                </td>
                <td>
                    <code class="token-preview">${token.token_preview || '****' + (token.token_suffix || '')}</code>
                    ${token.token_preview ? `
                        <button class="btn btn-sm btn-outline copy-token-preview" 
                                data-token="${token.token_preview}"
                                title="Копировать">📋</button>
                    ` : ''}
                </td>
                <td>${this.formatDate(token.created_at)}</td>
                <td>
                    ${token.expires_at ? this.formatDate(token.expires_at) : '<span class="never-expires">Никогда</span>'}
                    ${this.isExpired(token.expires_at) ? '<span class="badge badge-danger">Истёк</span>' : ''}
                </td>
                <td>${token.last_used_at ? this.formatDateTime(token.last_used_at) : '—'}</td>
                <td>${token.use_count || 0}</td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline view-token" 
                                data-id="${token.id}"
                                title="Подробнее">👁️</button>
                        <button class="btn btn-sm btn-outline-danger revoke-token" 
                                data-id="${token.id}"
                                data-name="${this.escapeHtml(token.name)}"
                                title="Отозвать">🗑️</button>
                    </div>
                </td>
            </tr>
        `).join('');
        
        this.attachTableEvents();
    },
    
    // Рендер пагинации
    renderPagination() {
        const container = document.getElementById('apiTokensPagination');
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
                this.loadTokens(parseInt(btn.dataset.page));
            });
        });
    },
    
    // ============ МОДАЛЬНЫЕ ОКНА ============
    
    openCreateModal() {
        const modal = document.getElementById('tokenCreateModal');
        if (modal) {
            document.getElementById('tokenCreateForm').reset();
            modal.style.display = 'flex';
        }
    },
    
    closeCreateModal() {
        document.getElementById('tokenCreateModal').style.display = 'none';
    },
    
    openCreatedModal(token, tokenValue) {
        const modal = document.getElementById('tokenCreatedModal');
        const tokenEl = document.getElementById('newTokenValue');
        const exampleEl = document.getElementById('tokenExample');
        
        tokenEl.textContent = tokenValue;
        tokenEl.dataset.token = tokenValue;
        
        const example = `curl -H "Authorization: Bearer ${tokenValue}" ${window.location.origin}/api/campaigns`;
        exampleEl.textContent = example;
        exampleEl.dataset.example = example;
        
        modal.style.display = 'flex';
        
        // Привязка кнопок копирования
        modal.querySelector('.copy-token-btn').addEventListener('click', () => {
            this.copyToClipboard(tokenValue);
            showToast('Токен скопирован', 'success');
        });
        
        modal.querySelector('.copy-example-btn').addEventListener('click', () => {
            this.copyToClipboard(example);
            showToast('Пример скопирован', 'success');
        });
    },
    
    closeCreatedModal() {
        document.getElementById('tokenCreatedModal').style.display = 'none';
        this.loadTokens();
    },
    
    async showDetailModal(tokenId) {
        try {
            const response = await authFetch(`${API_BASE}/tokens/${tokenId}`);
            if (!response.ok) throw new Error('Failed to load');
            
            const token = await response.json();
            
            const content = document.getElementById('tokenDetailContent');
            content.innerHTML = `
                <div class="token-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID:</td><td>${token.id}</td></tr>
                            <tr><td>Название:</td><td>${this.escapeHtml(token.name)}</td></tr>
                            <tr><td>Описание:</td><td>${this.escapeHtml(token.description || '—')}</td></tr>
                            <tr><td>Статус:</td><td>${token.is_active ? '✅ Активен' : '❌ Отозван'}</td></tr>
                        </table>
                    </div>
                    
                    <div class="detail-section">
                        <h4>Сроки действия</h4>
                        <table class="details-table">
                            <tr><td>Создан:</td><td>${this.formatDateTime(token.created_at)}</td></tr>
                            <tr><td>Истекает:</td><td>${token.expires_at ? this.formatDateTime(token.expires_at) : 'Никогда'}</td></tr>
                            <tr><td>Последнее использование:</td><td>${token.last_used_at ? this.formatDateTime(token.last_used_at) : '—'}</td></tr>
                            <tr><td>Всего использований:</td><td>${token.use_count || 0}</td></tr>
                        </table>
                    </div>
                    
                    ${token.permissions && token.permissions.length > 0 ? `
                        <div class="detail-section">
                            <h4>Разрешения</h4>
                            <ul>
                                ${token.permissions.map(p => `<li>${this.escapeHtml(p)}</li>`).join('')}
                            </ul>
                        </div>
                    ` : ''}
                    
                    ${token.allowed_ips ? `
                        <div class="detail-section">
                            <h4>IP ограничения</h4>
                            <p><code>${this.escapeHtml(token.allowed_ips)}</code></p>
                        </div>
                    ` : ''}
                    
                    ${token.last_ip ? `
                        <div class="detail-section">
                            <h4>Последний IP</h4>
                            <p><code>${this.escapeHtml(token.last_ip)}</code></p>
                        </div>
                    ` : ''}
                </div>
            `;
            
            document.getElementById('tokenDetailModal').style.display = 'flex';
        } catch (error) {
            console.error('Load token detail failed:', error);
            showToast('Ошибка загрузки', 'error');
        }
    },
    
    closeDetailModal() {
        document.getElementById('tokenDetailModal').style.display = 'none';
    },
    
    openDeleteModal(tokenId, tokenName) {
        const modal = document.getElementById('tokenDeleteModal');
        document.getElementById('tokenDeleteMessage').textContent = 
            `Вы уверены, что хотите отозвать токен "${tokenName}"?`;
        document.getElementById('confirmDeleteTokenBtn').dataset.id = tokenId;
        
        modal.style.display = 'flex';
    },
    
    closeDeleteModal() {
        document.getElementById('tokenDeleteModal').style.display = 'none';
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async createToken() {
        const name = document.getElementById('tokenName').value;
        const description = document.getElementById('tokenDescription').value;
        const expiresSelect = document.getElementById('tokenExpires').value;
        const expiresAt = document.getElementById('tokenExpiresAt').value;
        const allowedIps = document.getElementById('tokenAllowedIps').value;
        
        if (!name) {
            showToast('Введите название токена', 'warning');
            return;
        }
        
        // Сбор разрешений
        const permissions = [];
        document.querySelectorAll('input[name="permission"]:checked').forEach(cb => {
            permissions.push(cb.value);
        });
        
        // Определение срока действия
        let expiresAtValue = null;
        if (expiresAt) {
            expiresAtValue = new Date(expiresAt).toISOString();
        } else if (expiresSelect) {
            const days = parseInt(expiresSelect);
            const date = new Date();
            date.setDate(date.getDate() + days);
            expiresAtValue = date.toISOString();
        }
        
        const data = {
            name,
            description: description || null,
            expires_at: expiresAtValue,
            permissions: permissions.length > 0 ? permissions : null,
            allowed_ips: allowedIps || null
        };
        
        const submitBtn = document.querySelector('#tokenCreateForm button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = '⏳ Создание...';
        
        try {
            const response = await authFetch(`${API_BASE}/tokens`, {
                method: 'POST',
                body: JSON.stringify(data)
            });
            
            if (response.ok) {
                const result = await response.json();
                
                this.closeCreateModal();
                this.openCreatedModal(result, result.token);
                
                showToast('Токен создан', 'success');
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка создания', 'error');
            }
        } catch (error) {
            console.error('Create token failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    },
    
    async revokeToken() {
        const tokenId = document.getElementById('confirmDeleteTokenBtn').dataset.id;
        
        const btn = document.getElementById('confirmDeleteTokenBtn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Отзыв...';
        
        try {
            const response = await authFetch(`${API_BASE}/tokens/${tokenId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                showToast('Токен отозван', 'success');
                this.closeDeleteModal();
                await this.loadTokens();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка отзыва', 'error');
            }
        } catch (error) {
            console.error('Revoke token failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    attachCopyButtons() {
        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const text = btn.dataset.copy;
                this.copyToClipboard(text);
                showToast('URL скопирован', 'success');
            });
        });
    },
    
    attachTableEvents() {
        document.querySelectorAll('.view-token').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDetailModal(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.revoke-token').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openDeleteModal(btn.dataset.id, btn.dataset.name);
            });
        });
        
        document.querySelectorAll('.copy-token-preview').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.copyToClipboard(btn.dataset.token);
                showToast('Токен скопирован', 'success');
            });
        });
        
        document.querySelectorAll('.token-row').forEach(row => {
            row.addEventListener('click', () => {
                this.showDetailModal(row.dataset.id);
            });
        });
    },
    
    copyToClipboard(text) {
        navigator.clipboard?.writeText(text).catch(() => {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        });
    },
    
    isExpired(expiresAt) {
        if (!expiresAt) return false;
        return new Date(expiresAt) < new Date();
    },
    
    formatDate(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        return date.toLocaleDateString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric'
        });
    },
    
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
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        document.getElementById('tokenCreateBtn')?.addEventListener('click', () => this.openCreateModal());
        document.getElementById('tokenRefreshBtn')?.addEventListener('click', () => this.loadTokens());
        
        document.getElementById('tokenCreateForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.createToken();
        });
        
        document.getElementById('confirmDeleteTokenBtn')?.addEventListener('click', () => this.revokeToken());
        
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
        
        // Обработчик выбора срока действия
        document.getElementById('tokenExpires')?.addEventListener('change', (e) => {
            const dateInput = document.getElementById('tokenExpiresAt');
            if (e.target.value) {
                dateInput.value = '';
                dateInput.disabled = true;
            } else {
                dateInput.disabled = false;
            }
        });
        
        document.getElementById('tokenExpiresAt')?.addEventListener('change', (e) => {
            const select = document.getElementById('tokenExpires');
            if (e.target.value) {
                select.value = '';
            }
        });
    }
};

// Экспорт глобально
window.ApiTokensModule = ApiTokensModule;
App.apiTokens = ApiTokensModule;
