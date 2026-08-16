/**
 * AutoDialer Ultimate - Contact Groups Module
 * Version: 3.0.0
 * Управление группами контактов
 */

App.contactGroups = {
    // Состояние модуля
    state: {
        groups: [],
        currentPage: 1,
        totalPages: 1,
        pageSize: 20,
        searchQuery: '',
        selectedGroup: null
    },

    // =============================================
    // Инициализация
    // =============================================
    async init() {
        await this.loadGroups();
        this.setupEventListeners();
    },

    setupEventListeners() {
        // Поиск с дебаунсом
        const searchInput = document.getElementById('groupSearch');
        if (searchInput) {
            searchInput.addEventListener('input', App.debounce(() => {
                this.state.searchQuery = searchInput.value;
                this.loadGroups(1);
            }, 300));
        }

        // Кнопка обновления
        const refreshBtn = document.getElementById('groupsRefreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadGroups());
        }
    },

    // =============================================
    // Загрузка групп
    // =============================================
    async loadGroups(page = 1) {
        this.state.currentPage = page;
        
        const container = document.getElementById('contactGroupsList');
        if (container) {
            container.innerHTML = '<div class="loading">Загрузка групп...</div>';
        }
        
        try {
            let url = `/contact-groups/?page=${page}&page_size=${this.state.pageSize}`;
            
            if (this.state.searchQuery) {
                url += `&search=${encodeURIComponent(this.state.searchQuery)}`;
            }
            
            const data = await App.apiGet(url);
            
            this.state.groups = data.items || data || [];
            this.state.totalPages = data.total_pages || 1;
            
            this.renderGroupsList();
            App.renderPagination('groupsPagination', page, this.state.totalPages, 'App.contactGroups.loadGroups');
            
        } catch (error) {
            console.error('Failed to load groups:', error);
            if (container) {
                container.innerHTML = '<div class="error-message">Ошибка загрузки групп</div>';
            }
            App.showToast('Ошибка загрузки групп', 'error');
        }
    },

    // =============================================
    // Рендер списка групп
    // =============================================
    renderGroupsList() {
        const container = document.getElementById('contactGroupsList');
        if (!container) return;
        
        const groups = this.state.groups;
        
        if (!groups || groups.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📁</div>
                    <p>Нет групп контактов</p>
                    ${App.auth.isOperator() ? `
                        <button class="btn btn-primary" onclick="App.contactGroups.openGroupModal()">
                            Создать первую группу
                        </button>
                    ` : ''}
                </div>
            `;
            return;
        }
        
        container.innerHTML = groups.map(group => `
            <div class="group-card" data-group-id="${group.id}">
                <div class="group-color" style="background: ${group.color || '#667eea'};"></div>
                <div class="group-content">
                    <div class="group-header">
                        <h4>${this.escapeHtml(group.name)}</h4>
                        <span class="group-count">${group.contacts_count || 0} контактов</span>
                    </div>
                    ${group.description ? `
                        <p class="group-description">${this.escapeHtml(group.description)}</p>
                    ` : ''}
                    <div class="group-footer">
                        <span class="group-date">Создана: ${App.formatDate(group.created_at)}</span>
                        <div class="group-actions">
                            <button class="btn btn-sm btn-outline" 
                                    onclick="App.contactGroups.viewGroupContacts(${group.id})"
                                    title="Просмотр контактов">
                                👁️
                            </button>
                            ${App.auth.isOperator() ? `
                                <button class="btn btn-sm btn-outline" 
                                        onclick="App.contactGroups.editGroup(${group.id})"
                                        title="Редактировать">
                                    ✏️
                                </button>
                                <button class="btn btn-sm btn-outline" 
                                        onclick="App.contactGroups.exportGroup(${group.id})"
                                        title="Экспорт">
                                    📥
                                </button>
                            ` : ''}
                            ${App.auth.isAdmin() ? `
                                <button class="btn btn-sm btn-outline-danger" 
                                        onclick="App.contactGroups.deleteGroup(${group.id})"
                                        title="Удалить">
                                    🗑️
                                </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    },

    // =============================================
    // Модальное окно создания/редактирования
    // =============================================
    openGroupModal(group = null) {
        const modal = document.getElementById('contactGroupModal');
        const title = document.getElementById('contactGroupModalTitle');
        const deleteBtn = document.getElementById('contactGroupDeleteBtn');
        
        if (!modal) return;
        
        const isEdit = !!group;
        
        if (isEdit) {
            title.textContent = 'Редактировать группу';
            deleteBtn.style.display = 'inline-block';
            
            this.state.selectedGroup = group;
            
            document.getElementById('contactGroupId').value = group.id;
            document.getElementById('contactGroupName').value = group.name || '';
            document.getElementById('contactGroupDescription').value = group.description || '';
            document.getElementById('contactGroupColor').value = group.color || '#667eea';
            
        } else {
            title.textContent = 'Новая группа';
            deleteBtn.style.display = 'none';
            
            this.state.selectedGroup = null;
            
            document.getElementById('contactGroupId').value = '';
            document.getElementById('contactGroupName').value = '';
            document.getElementById('contactGroupDescription').value = '';
            document.getElementById('contactGroupColor').value = '#667eea';
        }
        
        modal.style.display = 'flex';
    },

    closeGroupModal() {
        const modal = document.getElementById('contactGroupModal');
        if (modal) {
            modal.style.display = 'none';
        }
        this.state.selectedGroup = null;
    },

    editGroup(id) {
        const group = this.state.groups.find(g => g.id === id);
        if (group) {
            this.openGroupModal(group);
        }
    },

    // =============================================
    // Сохранение группы
    // =============================================
    async saveGroup() {
        const id = document.getElementById('contactGroupId')?.value;
        const name = document.getElementById('contactGroupName')?.value?.trim();
        const description = document.getElementById('contactGroupDescription')?.value?.trim();
        const color = document.getElementById('contactGroupColor')?.value || '#667eea';
        
        if (!name) {
            App.showToast('Введите название группы', 'warning');
            return;
        }
        
        const data = {
            name,
            description: description || null,
            color
        };
        
        const submitBtn = document.querySelector('#contactGroupForm button[type="submit"]');
        const originalText = submitBtn?.textContent;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = '⏳ Сохранение...';
        }
        
        try {
            if (id) {
                await App.apiPut(`/contact-groups/${id}`, data);
                App.showToast('Группа обновлена', 'success');
            } else {
                await App.apiPost('/contact-groups/', data);
                App.showToast('Группа создана', 'success');
            }
            
            this.closeGroupModal();
            await this.loadGroups(this.state.currentPage);
            
            // Обновляем кэш в contacts модуле
            if (App.contacts?.loadContactGroupsForSelect) {
                await App.contacts.loadContactGroupsForSelect();
            }
            
        } catch (error) {
            console.error('Failed to save group:', error);
            App.showToast(error.message || 'Ошибка сохранения', 'error');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        }
    },

    // =============================================
    // Удаление группы
    // =============================================
    async deleteGroup(id) {
        if (!id) {
            id = document.getElementById('contactGroupId')?.value;
        }
        
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может удалить группу', 'error');
            return;
        }
        
        const group = this.state.groups.find(g => g.id === id);
        const contactsCount = group?.contacts_count || 0;
        
        let message = 'Удалить группу?';
        if (contactsCount > 0) {
            message += ` В группе ${contactsCount} контактов. Они НЕ будут удалены, а останутся без группы.`;
        }
        
        if (!App.confirm(message)) return;
        
        try {
            await App.apiDelete(`/contact-groups/${id}`);
            App.showToast('Группа удалена', 'success');
            
            if (this.state.selectedGroup?.id === id) {
                this.closeGroupModal();
            }
            
            await this.loadGroups(this.state.currentPage);
            
            // Обновляем кэш в contacts модуле
            if (App.contacts?.loadContactGroupsForSelect) {
                await App.contacts.loadContactGroupsForSelect();
            }
            
        } catch (error) {
            console.error('Failed to delete group:', error);
            App.showToast(error.message || 'Ошибка удаления', 'error');
        }
    },

    // =============================================
    // Просмотр контактов группы
    // =============================================
    async viewGroupContacts(groupId) {
        const group = this.state.groups.find(g => g.id === groupId);
        if (!group) return;
        
        try {
            const data = await App.apiGet(`/contact-groups/${groupId}/contacts`);
            const contacts = data.items || data || [];
            
            const modal = document.getElementById('groupContactsModal');
            const title = document.getElementById('groupContactsTitle');
            const content = document.getElementById('groupContactsContent');
            
            if (!modal || !content) return;
            
            title.textContent = `Контакты группы "${group.name}"`;
            
            if (contacts.length === 0) {
                content.innerHTML = `
                    <div class="empty-state">
                        <p>В этой группе нет контактов</p>
                        <button class="btn btn-primary" onclick="App.switchTab('contacts'); App.hideModal('groupContactsModal');">
                            Перейти к контактам
                        </button>
                    </div>
                `;
            } else {
                content.innerHTML = `
                    <div class="group-contacts-list">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>Телефон</th>
                                    <th>Имя</th>
                                    <th>Email</th>
                                    <th>Статус</th>
                                    <th>Звонков</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${contacts.map(c => `
                                    <tr>
                                        <td>${this.formatPhone(c.phone)}</td>
                                        <td>${this.escapeHtml(c.name || '—')}</td>
                                        <td>${this.escapeHtml(c.email || '—')}</td>
                                        <td><span class="status-badge status-${c.status}">${this.getStatusText(c.status)}</span></td>
                                        <td>${c.total_calls || 0}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            }
            
            modal.style.display = 'flex';
            
        } catch (error) {
            console.error('Failed to load group contacts:', error);
            App.showToast('Ошибка загрузки контактов', 'error');
        }
    },

    closeGroupContactsModal() {
        const modal = document.getElementById('groupContactsModal');
        if (modal) {
            modal.style.display = 'none';
        }
    },

    // =============================================
    // Экспорт группы
    // =============================================
    async exportGroup(groupId) {
        const group = this.state.groups.find(g => g.id === groupId);
        if (!group) return;
        
        try {
            const data = await App.apiGet(`/contact-groups/${groupId}/export`);
            
            let csv = 'phone,name,email,status,tags,notes\n';
            
            for (const c of data.contacts || []) {
                csv += `${c.phone},${c.name || ''},${c.email || ''},${c.status},${(c.tags || []).join(';')},${(c.notes || '').replace(/\n/g, ' ')}\n`;
            }
            
            const filename = `group_${group.name.replace(/[^a-zA-Z0-9]/g, '_')}.csv`;
            App.downloadFile(csv, filename, 'text/csv');
            App.showToast('Экспорт завершён', 'success');
            
        } catch (error) {
            console.error('Failed to export group:', error);
            App.showToast('Ошибка экспорта', 'error');
        }
    },

    // =============================================
    // Массовое назначение группы
    // =============================================
    async openBatchAssignModal() {
        const modal = document.getElementById('batchAssignGroupModal');
        if (!modal) return;
        
        // Загружаем контакты без группы
        try {
            const data = await App.apiGet('/contacts/?ungrouped=true&limit=1000');
            const contacts = data.items || data || [];
            
            const content = document.getElementById('batchAssignContent');
            
            content.innerHTML = `
                <div class="batch-assign">
                    <div class="form-group">
                        <label>Выберите группу</label>
                        <select id="batchAssignGroupSelect" class="form-control">
                            <option value="">Выберите группу...</option>
                            ${this.state.groups.map(g => `
                                <option value="${g.id}">${this.escapeHtml(g.name)} (${g.contacts_count || 0})</option>
                            `).join('')}
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label>Выберите контакты</label>
                        <div class="contacts-select-list">
                            ${contacts.length === 0 ? `
                                <p class="text-muted">Нет контактов без группы</p>
                            ` : contacts.map(c => `
                                <label class="contact-select-item">
                                    <input type="checkbox" name="contactIds" value="${c.id}">
                                    <span>${this.formatPhone(c.phone)}</span>
                                    <span>${this.escapeHtml(c.name || '—')}</span>
                                </label>
                            `).join('')}
                        </div>
                    </div>
                    
                    <div class="form-actions">
                        <button class="btn btn-primary" onclick="App.contactGroups.batchAssign()">
                            Назначить
                        </button>
                    </div>
                </div>
            `;
            
            modal.style.display = 'flex';
            
        } catch (error) {
            console.error('Failed to load ungrouped contacts:', error);
            App.showToast('Ошибка загрузки контактов', 'error');
        }
    },

    async batchAssign() {
        const groupId = document.getElementById('batchAssignGroupSelect')?.value;
        const checkboxes = document.querySelectorAll('input[name="contactIds"]:checked');
        const contactIds = Array.from(checkboxes).map(cb => parseInt(cb.value));
        
        if (!groupId) {
            App.showToast('Выберите группу', 'warning');
            return;
        }
        
        if (contactIds.length === 0) {
            App.showToast('Выберите контакты', 'warning');
            return;
        }
        
        try {
            await App.apiPost('/contacts/batch-assign-group', {
                group_id: groupId,
                contact_ids: contactIds
            });
            
            App.showToast(`Группа назначена для ${contactIds.length} контактов`, 'success');
            App.hideModal('batchAssignGroupModal');
            await this.loadGroups(this.state.currentPage);
            
        } catch (error) {
            console.error('Failed to batch assign:', error);
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    closeBatchAssignModal() {
        App.hideModal('batchAssignGroupModal');
    },

    // =============================================
    // Импорт групп
    // =============================================
    async importGroups() {
        const fileInput = document.getElementById('groupsImportFile');
        const file = fileInput?.files[0];
        
        if (!file) {
            App.showToast('Выберите файл', 'warning');
            return;
        }
        
        try {
            const text = await App.readFileAsText(file);
            const lines = text.split('\n').filter(l => l.trim());
            
            const groups = [];
            for (const line of lines) {
                const parts = line.split(',').map(p => p.trim());
                if (parts[0]) {
                    groups.push({
                        name: parts[0],
                        description: parts[1] || '',
                        color: parts[2] || '#667eea'
                    });
                }
            }
            
            if (groups.length === 0) {
                App.showToast('Нет данных для импорта', 'warning');
                return;
            }
            
            const response = await App.apiPost('/contact-groups/import', { groups });
            
            App.showToast(`Импортировано: ${response.imported}, пропущено: ${response.skipped}`, 'success');
            
            fileInput.value = '';
            await this.loadGroups(1);
            
        } catch (error) {
            console.error('Failed to import groups:', error);
            App.showToast(error.message || 'Ошибка импорта', 'error');
        }
    },

    // =============================================
    // Утилиты
    // =============================================
    formatPhone(phone) {
        return App.formatPhoneNumber(phone);
    },

    getStatusText(status) {
        const map = {
            'active': 'Активен',
            'inactive': 'Неактивен',
            'blocked': 'Заблокирован'
        };
        return map[status] || status;
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // =============================================
    // Очистка
    // =============================================
    destroy() {
        this.state.groups = [];
        this.state.selectedGroup = null;
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.openGroupModal = () => App.contactGroups.openGroupModal();
window.closeGroupModal = () => App.contactGroups.closeGroupModal();
window.saveGroup = () => App.contactGroups.saveGroup();
window.editGroup = (id) => App.contactGroups.editGroup(id);
window.deleteGroup = (id) => App.contactGroups.deleteGroup(id);
window.viewGroupContacts = (id) => App.contactGroups.viewGroupContacts(id);
window.closeGroupContactsModal = () => App.contactGroups.closeGroupContactsModal();
window.exportGroup = (id) => App.contactGroups.exportGroup(id);
window.openBatchAssignModal = () => App.contactGroups.openBatchAssignModal();
window.closeBatchAssignModal = () => App.contactGroups.closeBatchAssignModal();
window.importGroups = () => App.contactGroups.importGroups();
