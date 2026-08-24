// blacklist.js - Модуль управления чёрным списком
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast)

const BlacklistModule = {
    currentPage: 1,
    pageSize: 20,
    totalPages: 1,
    totalRecords: 0,
    searchQuery: '',
    blacklistItems: [],
    
    // Инициализация модуля
    init() {
        this.render();
        this.attachEventListeners();
        this.loadBlacklist();
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('blacklistContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="blacklist-page">
                <div class="page-header">
                    <h2>🚫 Чёрный список</h2>
                    <div class="header-actions">
                        <button class="btn btn-primary" id="blacklistAddBtn">
                            ➕ Добавить номер
                        </button>
                        <button class="btn btn-outline" id="blacklistImportBtn">
                            📤 Импорт
                        </button>
                        <button class="btn btn-outline" id="blacklistExportBtn">
                            📥 Экспорт
                        </button>
                    </div>
                </div>
                
                <p class="text-muted">
                    Номера в чёрном списке не будут обзваниваться ни в одном обзвоне.
                    При импорте контактов номера из чёрного списка автоматически пропускаются.
                </p>
                
                <!-- Панель поиска и фильтров -->
                <div class="blacklist-toolbar">
                    <div class="search-box">
                        <input type="text" 
                               id="blacklistSearch" 
                               class="form-control" 
                               placeholder="🔍 Поиск по номеру или причине..."
                               value="${this.searchQuery}">
                    </div>
                    <div class="toolbar-actions">
                        <button class="btn btn-outline" id="blacklistRefreshBtn">
                            🔄 Обновить
                        </button>
                        <button class="btn btn-danger" id="blacklistClearAllBtn" title="Очистить весь список">
                            🗑️ Очистить всё
                        </button>
                    </div>
                </div>
                
                <!-- Статистика -->
                <div class="blacklist-stats">
                    <div class="stat-item">
                        <span class="stat-label">Всего номеров:</span>
                        <span class="stat-value" id="blacklistTotal">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Добавлено сегодня:</span>
                        <span class="stat-value" id="blacklistToday">0</span>
                    </div>
                </div>
                
                <!-- Таблица -->
                <div class="blacklist-table-container">
                    <table class="table" id="blacklistTable">
                        <thead>
                            <tr>
                                <th width="40">
                                    <input type="checkbox" id="blacklistSelectAll">
                                </th>
                                <th>Номер телефона</th>
                                <th>Причина</th>
                                <th>Дата добавления</th>
                                <th>Добавил</th>
                                <th>Источник</th>
                                <th width="100">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="blacklistTableBody">
                            <tr><td colspan="7" class="text-center">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                
                <!-- Пагинация -->
                <div id="blacklistPagination" class="pagination-container"></div>
            </div>
            
            <!-- Модальное окно добавления -->
            <div id="blacklistAddModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Добавить номер в чёрный список</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="blacklistAddForm">
                            <div class="form-group">
                                <label>Номер телефона <span class="required">*</span></label>
                                <input type="text" 
                                       id="blacklistPhone" 
                                       class="form-control" 
                                       placeholder="Например: +79161234567"
                                       required>
                                <small class="form-text">Можно указать несколько номеров через запятую или с новой строки</small>
                            </div>
                            
                            <div class="form-group">
                                <label>Причина (опционально)</label>
                                <select id="blacklistReasonSelect" class="form-control">
                                    <option value="">Выберите причину или введите свою</option>
                                    <option value="Жалоба на спам">Жалоба на спам</option>
                                    <option value="Отказ от обзвона">Отказ от обзвона</option>
                                    <option value="Неверный номер">Неверный номер</option>
                                    <option value="Автоответчик">Автоответчик</option>
                                    <option value="Нецелевой">Нецелевой</option>
                                    <option value="Дубликат">Дубликат</option>
                                </select>
                            </div>
                            
                            <div class="form-group">
                                <label>Или введите свою причину</label>
                                <input type="text" 
                                       id="blacklistReasonCustom" 
                                       class="form-control" 
                                       placeholder="Своя причина">
                            </div>
                            
                            <div class="form-group">
                                <label>Заметки (опционально)</label>
                                <textarea id="blacklistNotes" 
                                          class="form-control" 
                                          rows="2"
                                          placeholder="Дополнительные заметки..."></textarea>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="BlacklistModule.closeAddModal()">
                                    Отмена
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    Добавить
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно импорта -->
            <div id="blacklistImportModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Импорт номеров в чёрный список</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="blacklistImportForm">
                            <div class="form-group">
                                <label>Список номеров</label>
                                <textarea id="blacklistImportText" 
                                          class="form-control" 
                                          rows="10"
                                          placeholder="Введите номера (по одному на строку или через запятую)..."
                                          required></textarea>
                                <small class="form-text">
                                    <span id="blacklistImportCount">0</span> номеров
                                </small>
                            </div>
                            
                            <div class="form-group">
                                <label>Причина для всех (опционально)</label>
                                <input type="text" 
                                       id="blacklistImportReason" 
                                       class="form-control" 
                                       placeholder="Причина добавления">
                            </div>
                            
                            <div class="form-group">
                                <label>
                                    <input type="checkbox" id="blacklistImportSkipDuplicates" checked>
                                    Пропускать дубликаты
                                </label>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="BlacklistModule.closeImportModal()">
                                    Отмена
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    Импортировать
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно редактирования -->
            <div id="blacklistEditModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Редактировать запись</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="blacklistEditForm">
                            <input type="hidden" id="blacklistEditId">
                            <input type="hidden" id="blacklistEditPhone">
                            
                            <div class="form-group">
                                <label>Номер телефона</label>
                                <input type="text" 
                                       id="blacklistEditPhoneDisplay" 
                                       class="form-control" 
                                       readonly
                                       style="background: #f8f9fa;">
                            </div>
                            
                            <div class="form-group">
                                <label>Причина</label>
                                <input type="text" 
                                       id="blacklistEditReason" 
                                       class="form-control" 
                                       placeholder="Причина">
                            </div>
                            
                            <div class="form-group">
                                <label>Заметки</label>
                                <textarea id="blacklistEditNotes" 
                                          class="form-control" 
                                          rows="3"
                                          placeholder="Заметки..."></textarea>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="BlacklistModule.closeEditModal()">
                                    Отмена
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
            <div id="blacklistDetailModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Детали записи</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body" id="blacklistDetailContent">
                    </div>
                </div>
            </div>
        `;
    },
    
    // Загрузка чёрного списка
    async loadBlacklist(page = 1) {
        this.currentPage = page;
        
        const tbody = document.getElementById('blacklistTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Загрузка...</td></tr>';
        
        try {
            let url = `${API_BASE}/blacklist/?page=${page}&page_size=${this.pageSize}`;
            if (this.searchQuery) {
                url += `&search=${encodeURIComponent(this.searchQuery)}`;
            }
            
            const response = await authFetch(url);
            if (response.ok) {
                const data = await response.json();
                this.blacklistItems = data.items || data || [];
                this.totalRecords = data.total || this.blacklistItems.length;
                this.totalPages = Math.ceil(this.totalRecords / this.pageSize) || 1;
                
                this.renderTable();
                this.renderPagination();
                this.updateStats(data.stats);
            } else {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('Blacklist load failed:', error);
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    // Рендер таблицы
    renderTable() {
        const tbody = document.getElementById('blacklistTableBody');
        
        if (this.blacklistItems.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">🚫</div>
                            <p>Чёрный список пуст</p>
                            <button class="btn btn-primary" onclick="BlacklistModule.openAddModal()">
                                Добавить номер
                            </button>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.blacklistItems.map(item => `
            <tr data-id="${item.id}" class="blacklist-row">
                <td>
                    <input type="checkbox" class="blacklist-checkbox" data-id="${item.id}">
                </td>
                <td>
                    <span class="phone-number">${this.formatPhoneNumber(item.phone)}</span>
                    ${item.is_blocked !== false ? '<span class="badge badge-danger">Заблокирован</span>' : ''}
                </td>
                <td>${this.escapeHtml(item.reason || '—')}</td>
                <td>${this.formatDateTime(item.created_at)}</td>
                <td>${this.escapeHtml(item.created_by_name || item.created_by || 'system')}</td>
                <td>
                    <span class="source-badge source-${item.source || 'manual'}">
                        ${this.getSourceName(item.source)}
                    </span>
                </td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline view-detail" 
                                data-id="${item.id}"
                                title="Подробнее">👁️</button>
                        <button class="btn btn-sm btn-outline edit-item" 
                                data-id="${item.id}"
                                title="Редактировать">✏️</button>
                        <button class="btn btn-sm btn-outline-danger remove-item" 
                                data-phone="${this.escapeHtml(item.phone)}"
                                data-id="${item.id}"
                                title="Удалить">🗑️</button>
                    </div>
                </td>
            </tr>
        `).join('');
        
        this.attachTableEvents();
    },
    
    // Обновление статистики
    updateStats(stats) {
        if (!stats) return;
        
        document.getElementById('blacklistTotal').textContent = stats.total || this.totalRecords;
        document.getElementById('blacklistToday').textContent = stats.today || 0;
    },
    
    // Рендер пагинации
    renderPagination() {
        const container = document.getElementById('blacklistPagination');
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
                this.loadBlacklist(parseInt(btn.dataset.page));
            });
        });
    },
    
    // ============ МОДАЛЬНЫЕ ОКНА ============
    
    openAddModal() {
        const modal = document.getElementById('blacklistAddModal');
        if (modal) {
            modal.style.display = 'flex';
            document.getElementById('blacklistPhone').value = '';
            document.getElementById('blacklistReasonSelect').value = '';
            document.getElementById('blacklistReasonCustom').value = '';
            document.getElementById('blacklistNotes').value = '';
        }
    },
    
    closeAddModal() {
        const modal = document.getElementById('blacklistAddModal');
        if (modal) modal.style.display = 'none';
    },
    
    openImportModal() {
        const modal = document.getElementById('blacklistImportModal');
        if (modal) {
            modal.style.display = 'flex';
            document.getElementById('blacklistImportText').value = '';
            document.getElementById('blacklistImportReason').value = '';
            document.getElementById('blacklistImportCount').textContent = '0';
        }
    },
    
    closeImportModal() {
        const modal = document.getElementById('blacklistImportModal');
        if (modal) modal.style.display = 'none';
    },
    
    openEditModal(item) {
        const modal = document.getElementById('blacklistEditModal');
        if (modal) {
            document.getElementById('blacklistEditId').value = item.id;
            document.getElementById('blacklistEditPhone').value = item.phone;
            document.getElementById('blacklistEditPhoneDisplay').value = this.formatPhoneNumber(item.phone);
            document.getElementById('blacklistEditReason').value = item.reason || '';
            document.getElementById('blacklistEditNotes').value = item.notes || '';
            modal.style.display = 'flex';
        }
    },
    
    closeEditModal() {
        const modal = document.getElementById('blacklistEditModal');
        if (modal) modal.style.display = 'none';
    },
    
    async showDetailModal(id) {
        try {
            const response = await authFetch(`${API_BASE}/blacklist/${id}`);
            if (!response.ok) throw new Error('Failed to load');
            
            const item = await response.json();
            
            const content = document.getElementById('blacklistDetailContent');
            content.innerHTML = `
                <div class="detail-section">
                    <h4>Основная информация</h4>
                    <table class="details-table">
                        <tr><td>Номер:</td><td>${this.formatPhoneNumber(item.phone)}</td></tr>
                        <tr><td>Причина:</td><td>${this.escapeHtml(item.reason || '—')}</td></tr>
                        <tr><td>Добавлен:</td><td>${this.formatDateTime(item.created_at)}</td></tr>
                        <tr><td>Добавил:</td><td>${this.escapeHtml(item.created_by_name || 'system')}</td></tr>
                        <tr><td>Источник:</td><td>${this.getSourceName(item.source)}</td></tr>
                        <tr><td>Статус:</td><td>${item.is_blocked !== false ? '🚫 Заблокирован' : '✅ Активен'}</td></tr>
                    </table>
                </div>
                
                ${item.notes ? `
                    <div class="detail-section">
                        <h4>Заметки</h4>
                        <p>${this.escapeHtml(item.notes)}</p>
                    </div>
                ` : ''}
                
                ${item.stats ? `
                    <div class="detail-section">
                        <h4>Статистика</h4>
                        <table class="details-table">
                            <tr><td>Попыток обзвона:</td><td>${item.stats.attempts || 0}</td></tr>
                            <tr><td>Последняя попытка:</td><td>${this.formatDateTime(item.stats.last_attempt)}</td></tr>
                        </table>
                    </div>
                ` : ''}
            `;
            
            document.getElementById('blacklistDetailModal').style.display = 'flex';
        } catch (error) {
            console.error('Load detail failed:', error);
            showToast('Ошибка загрузки', 'error');
        }
    },
    
    closeDetailModal() {
        const modal = document.getElementById('blacklistDetailModal');
        if (modal) modal.style.display = 'none';
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async addToBlacklist() {
        const phoneInput = document.getElementById('blacklistPhone');
        const reasonSelect = document.getElementById('blacklistReasonSelect');
        const reasonCustom = document.getElementById('blacklistReasonCustom');
        const notes = document.getElementById('blacklistNotes');
        
        const phones = phoneInput.value
            .split(/[,\n]/)
            .map(p => p.trim())
            .filter(p => p);
        
        if (phones.length === 0) {
            showToast('Введите номер телефона', 'warning');
            return;
        }
        
        const reason = reasonCustom.value || reasonSelect.value || null;
        
        const submitBtn = document.querySelector('#blacklistAddForm button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Добавление...';
        
        let successCount = 0;
        let errorCount = 0;
        
        for (const phone of phones) {
            try {
                const data = { phone };
                if (reason) data.reason = reason;
                if (notes.value) data.notes = notes.value;
                
                const response = await authFetch(`${API_BASE}/blacklist/`, {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    successCount++;
                } else {
                    errorCount++;
                }
            } catch {
                errorCount++;
            }
        }
        
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
        
        showToast(`Добавлено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'error');
        
        if (successCount > 0) {
            this.closeAddModal();
            await this.loadBlacklist();
        }
    },
    
    async importBlacklist() {
        const text = document.getElementById('blacklistImportText').value;
        const reason = document.getElementById('blacklistImportReason').value;
        const skipDuplicates = document.getElementById('blacklistImportSkipDuplicates').checked;
        
        const phones = text
            .split(/[,\n]/)
            .map(p => p.trim())
            .filter(p => p);
        
        if (phones.length === 0) {
            showToast('Введите номера телефонов', 'warning');
            return;
        }
        
        const submitBtn = document.querySelector('#blacklistImportForm button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Импорт...';
        
        try {
            const response = await authFetch(`${API_BASE}/blacklist/import`, {
                method: 'POST',
                body: JSON.stringify({
                    phones,
                    reason: reason || null,
                    skip_duplicates: skipDuplicates
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                showToast(`Импортировано: ${data.imported}, пропущено: ${data.skipped}`, 'success');
                this.closeImportModal();
                await this.loadBlacklist();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка импорта', 'error');
            }
        } catch (error) {
            console.error('Import failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    },
    
    async removeFromBlacklist(phone, id = null) {
        const identifier = id || phone;
        
        if (!confirm(`Удалить ${phone} из чёрного списка?`)) return;
        
        try {
            const response = await authFetch(`${API_BASE}/blacklist/${encodeURIComponent(identifier)}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                showToast('Номер удалён из чёрного списка', 'success');
                await this.loadBlacklist();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка удаления', 'error');
            }
        } catch (error) {
            console.error('Remove failed:', error);
            showToast('Ошибка сервера', 'error');
        }
    },
    
    async removeSelected() {
        const selected = Array.from(document.querySelectorAll('.blacklist-checkbox:checked'))
            .map(cb => ({
                id: cb.dataset.id,
                phone: cb.closest('tr').querySelector('.phone-number')?.textContent || ''
            }));
        
        if (selected.length === 0) {
            showToast('Выберите номера для удаления', 'warning');
            return;
        }
        
        if (!confirm(`Удалить ${selected.length} номер(ов) из чёрного списка?`)) return;
        
        let successCount = 0;
        let errorCount = 0;
        
        for (const item of selected) {
            try {
                const response = await authFetch(`${API_BASE}/blacklist/${item.id}`, {
                    method: 'DELETE'
                });
                if (response.ok) {
                    successCount++;
                } else {
                    errorCount++;
                }
            } catch {
                errorCount++;
            }
        }
        
        showToast(`Удалено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'error');
        await this.loadBlacklist();
    },
    
    async clearAll() {
        if (!confirm('ВНИМАНИЕ! Вы уверены, что хотите очистить ВЕСЬ чёрный список? Это действие нельзя отменить!')) return;
        
        if (!confirm('Подтвердите ещё раз: удалить ВСЕ номера из чёрного списка?')) return;
        
        try {
            const response = await authFetch(`${API_BASE}/blacklist/clear`, {
                method: 'POST'
            });
            
            if (response.ok) {
                const data = await response.json();
                showToast(`Удалено ${data.deleted} номеров`, 'success');
                await this.loadBlacklist();
            } else {
                showToast('Ошибка очистки', 'error');
            }
        } catch (error) {
            console.error('Clear all failed:', error);
            showToast('Ошибка сервера', 'error');
        }
    },
    
    async updateItem() {
        const id = document.getElementById('blacklistEditId').value;
        const reason = document.getElementById('blacklistEditReason').value;
        const notes = document.getElementById('blacklistEditNotes').value;
        
        try {
            const response = await authFetch(`${API_BASE}/blacklist/${id}`, {
                method: 'PUT',
                body: JSON.stringify({ reason: reason || null, notes: notes || null })
            });
            
            if (response.ok) {
                showToast('Запись обновлена', 'success');
                this.closeEditModal();
                await this.loadBlacklist();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка обновления', 'error');
            }
        } catch (error) {
            console.error('Update failed:', error);
            showToast('Ошибка сервера', 'error');
        }
    },
    
    async exportBlacklist() {
        showToast('Подготовка экспорта...', 'info');
        
        try {
            const response = await authFetch(`${API_BASE}/blacklist/export`);
            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `blacklist_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                showToast('Экспорт завершен', 'success');
            } else {
                // Fallback - клиентский экспорт
                await this.exportToCSVClientSide();
            }
        } catch (error) {
            console.error('Export failed:', error);
            await this.exportToCSVClientSide();
        }
    },
    
    async exportToCSVClientSide() {
        try {
            const response = await authFetch(`${API_BASE}/blacklist/?page_size=10000`);
            if (!response.ok) throw new Error('Failed to load');
            
            const data = await response.json();
            const items = data.items || data || [];
            
            if (!items.length) {
                showToast('Нет данных для экспорта', 'warning');
                return;
            }
            
            const headers = ['Номер', 'Причина', 'Дата добавления', 'Добавил', 'Источник', 'Заметки'];
            const rows = items.map(item => [
                item.phone,
                item.reason || '',
                this.formatDateTime(item.created_at),
                item.created_by_name || 'system',
                this.getSourceName(item.source),
                item.notes || ''
            ]);
            
            const csvContent = [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
            ].join('\n');
            
            const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `blacklist_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            window.URL.revokeObjectURL(url);
            
            showToast(`Экспортировано ${items.length} записей`, 'success');
        } catch (error) {
            console.error('Client-side export failed:', error);
            showToast('Не удалось выполнить экспорт', 'error');
        }
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        // Кнопки в заголовке
        document.getElementById('blacklistAddBtn')?.addEventListener('click', () => this.openAddModal());
        document.getElementById('blacklistImportBtn')?.addEventListener('click', () => this.openImportModal());
        document.getElementById('blacklistExportBtn')?.addEventListener('click', () => this.exportBlacklist());
        document.getElementById('blacklistRefreshBtn')?.addEventListener('click', () => this.loadBlacklist());
        document.getElementById('blacklistClearAllBtn')?.addEventListener('click', () => this.clearAll());
        
        // Поиск
        let searchTimeout;
        document.getElementById('blacklistSearch')?.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.searchQuery = e.target.value;
                this.currentPage = 1;
                this.loadBlacklist();
            }, 300);
        });
        
        // Выбрать все
        document.getElementById('blacklistSelectAll')?.addEventListener('change', (e) => {
            document.querySelectorAll('.blacklist-checkbox').forEach(cb => {
                cb.checked = e.target.checked;
            });
        });
        
        // Форма добавления
        document.getElementById('blacklistAddForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.addToBlacklist();
        });
        
        // Форма импорта
        document.getElementById('blacklistImportForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.importBlacklist();
        });
        
        // Форма редактирования
        document.getElementById('blacklistEditForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.updateItem();
        });
        
        // Подсчёт номеров при импорте
        document.getElementById('blacklistImportText')?.addEventListener('input', (e) => {
            const phones = e.target.value
                .split(/[,\n]/)
                .map(p => p.trim())
                .filter(p => p);
            document.getElementById('blacklistImportCount').textContent = phones.length;
        });
        
        // Закрытие модальных окон
        document.querySelectorAll('.close-modal').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                if (modal) modal.style.display = 'none';
            });
        });
        
        // Клик вне модального окна
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.style.display = 'none';
                }
            });
        });
        
        // Кнопка удаления выбранных (добавляется динамически)
        this.addDeleteSelectedButton();
    },
    
    attachTableEvents() {
        document.querySelectorAll('.view-detail').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDetailModal(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.edit-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                const item = this.blacklistItems.find(i => i.id == id);
                if (item) this.openEditModal(item);
            });
        });
        
        document.querySelectorAll('.remove-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.removeFromBlacklist(btn.dataset.phone, btn.dataset.id);
            });
        });
        
        // Клик по строке
        document.querySelectorAll('.blacklist-row').forEach(row => {
            row.addEventListener('click', () => {
                const id = row.dataset.id;
                this.showDetailModal(id);
            });
        });
    },
    
    addDeleteSelectedButton() {
        const toolbar = document.querySelector('.blacklist-toolbar .toolbar-actions');
        if (!toolbar) return;
        
        const existingBtn = document.getElementById('blacklistDeleteSelectedBtn');
        if (existingBtn) existingBtn.remove();
        
        const btn = document.createElement('button');
        btn.id = 'blacklistDeleteSelectedBtn';
        btn.className = 'btn btn-danger';
        btn.innerHTML = '🗑️ Удалить выбранные';
        btn.style.display = 'none';
        btn.addEventListener('click', () => this.removeSelected());
        
        toolbar.insertBefore(btn, document.getElementById('blacklistClearAllBtn'));
        
        // Обновление видимости при изменении выбора
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('blacklist-checkbox') || e.target.id === 'blacklistSelectAll') {
                const selectedCount = document.querySelectorAll('.blacklist-checkbox:checked').length;
                btn.style.display = selectedCount > 0 ? 'inline-block' : 'none';
                btn.innerHTML = `🗑️ Удалить выбранные (${selectedCount})`;
            }
        });
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    formatPhoneNumber(phone) {
        return App.formatPhoneNumber(phone);
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
    
    getSourceName(source) {
        const sources = {
            'manual': 'Вручную',
            'import': 'Импорт',
            'campaign': 'Обзвон',
            'api': 'API',
            'system': 'Система'
        };
        return sources[source] || source || 'Вручную';
    },
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Экспорт глобально
window.BlacklistModule = BlacklistModule;
App.blacklist = BlacklistModule;
