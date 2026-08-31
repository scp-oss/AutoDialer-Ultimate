/**
 * AutoDialer Ultimate - Contacts Module
 * Version: 3.0.0
 */

App.contacts = {
    // Состояние модуля
    state: {
        contacts: [],
        currentPage: 1,
        totalPages: 1,
        searchQuery: '',
        selectedContact: null,
        filterGroupId: ''
    },

    // =============================================
    // Инициализация
    // =============================================
    async init() {
        await this.loadContacts();
        await this.loadContactGroupsForSelect();
        this.setupEventListeners();
    },

    setupEventListeners() {
        // Поиск с дебаунсом
        const searchInput = document.getElementById('contactSearch');
        if (searchInput) {
            searchInput.addEventListener('input', App.debounce(() => {
                this.state.searchQuery = searchInput.value;
                this.loadContacts(1);
            }, 300));
        }
    },

    // =============================================
    // Загрузка контактов
    // =============================================
    async loadContacts(page = 1) {
        this.state.currentPage = page;
        
        try {
            let url = `/contacts/?page=${page}&page_size=20`;
            
            if (this.state.searchQuery) {
                url += `&search=${encodeURIComponent(this.state.searchQuery)}`;
            }
            if (this.state.filterGroupId) {
                url += `&group_id=${this.state.filterGroupId}`;
            }
            
            const data = await App.apiGet(url);
            
            this.state.contacts = data.items || data.contacts || [];
            this.state.totalPages = data.total_pages || 1;
            
            this.renderContactsList();
            App.renderPagination('contactsPagination', page, this.state.totalPages, 'App.contacts.loadContacts');
            
        } catch (error) {
            console.error('Failed to load contacts:', error);
            App.showToast('Ошибка загрузки контактов', 'error');
        }
    },

    renderContactsList() {
        const container = document.getElementById('contactsList');
        if (!container) return;
        
        const contacts = this.state.contacts;
        
        if (!contacts || contacts.length === 0) {
            container.innerHTML = '<div class="loading">Нет контактов</div>';
            return;
        }
        
        container.innerHTML = contacts.map(c => `
            <div class="contact-item">
                <div class="contact-info">
                    <strong>${this.formatPhone(c.phone)}</strong>
                    ${c.name ? ` - ${c.name}` : ''}
                    ${c.email ? `<br><small>${c.email}</small>` : ''}
                    ${c.group_name ? `<br><small class="text-muted">Группа: ${c.group_name}</small>` : ''}
                    <div class="contact-tags">
                        ${c.tags ? c.tags.map(t => `<span class="tag">${t}</span>`).join('') : ''}
                    </div>
                    ${c.notes ? `<br><small class="text-muted">${c.notes.substring(0, 50)}...</small>` : ''}
                </div>
                <div class="contact-stats">
                    <span class="stat-badge">📞 ${c.total_calls || 0}</span>
                    <span class="stat-badge">✅ ${c.total_agreed || 0}</span>
                </div>
                <div class="contact-actions">
                    ${c.blacklisted ? '<span class="status-badge status-declined" title="В чёрном списке">🚫</span>' : ''}
                    <span class="status-badge status-${c.status}">${this.getStatusText(c.status)}</span>
                    <button class="btn btn-outline btn-sm" onclick="App.contacts.editContact(${c.id})" title="Редактировать">✏️</button>
                    <button class="btn btn-outline btn-sm" onclick="App.contacts.callContact('${c.phone}')" title="Позвонить">📞</button>
                    ${App.auth.isOperator() ? `<button class="btn btn-outline btn-sm" onclick="App.contacts.deleteContact(${c.id})" title="Удалить">🗑️</button>` : ''}
                </div>
            </div>
        `).join('');
    },

    formatPhone(phone) {
        return App.formatPhoneNumber(phone);
    },

    getStatusText(status) {
        const statusMap = {
            'active': 'Активен',
            'inactive': 'Неактивен',
            'blocked': 'Заблокирован'
        };
        return statusMap[status] || status;
    },

    // =============================================
    // Фильтрация
    // =============================================
    filterByGroup(groupId) {
        this.state.filterGroupId = groupId;
        this.loadContacts(1);
    },

    clearFilters() {
        this.state.searchQuery = '';
        this.state.filterGroupId = '';
        const searchInput = document.getElementById('contactSearch');
        if (searchInput) searchInput.value = '';
        this.loadContacts(1);
    },

    // =============================================
    // CRUD операции
    // =============================================
    openContactModal(contactId = null) {
        const modal = document.getElementById('contactModal');
        const title = document.getElementById('contactModalTitle');
        const deleteBtn = document.getElementById('contactDeleteBtn');
        
        if (contactId) {
            title.textContent = 'Редактировать контакт';
            deleteBtn.style.display = 'inline-block';
            
            const contact = this.state.contacts.find(c => c.id === contactId);
            if (contact) {
                this.state.selectedContact = contact;
                document.getElementById('contactId').value = contact.id;
                document.getElementById('contactPhone').value = contact.phone || '';
                document.getElementById('contactName').value = contact.name || '';
                document.getElementById('contactEmail').value = contact.email || '';
                document.getElementById('contactGroup').value = contact.group_id || '';
                document.getElementById('contactTags').value = contact.tags ? contact.tags.join(', ') : '';
                document.getElementById('contactNotes').value = contact.notes || '';
                document.getElementById('contactStatus').value = contact.status || 'active';
            }
        } else {
            title.textContent = 'Новый контакт';
            deleteBtn.style.display = 'none';
            this.state.selectedContact = null;
            document.getElementById('contactId').value = '';
            document.getElementById('contactPhone').value = '';
            document.getElementById('contactName').value = '';
            document.getElementById('contactEmail').value = '';
            document.getElementById('contactGroup').value = '';
            document.getElementById('contactTags').value = '';
            document.getElementById('contactNotes').value = '';
            document.getElementById('contactStatus').value = 'active';
        }
        
        this.loadContactGroupsForSelect();
        modal.style.display = 'flex';
    },

    closeContactModal() {
        document.getElementById('contactModal').style.display = 'none';
        this.state.selectedContact = null;
    },

    editContact(id) {
        this.openContactModal(id);
    },

    async saveContact() {
        const id = document.getElementById('contactId').value;
        const phone = document.getElementById('contactPhone').value.trim();
        const name = document.getElementById('contactName').value.trim();
        const email = document.getElementById('contactEmail').value.trim();
        const groupId = document.getElementById('contactGroup').value;
        const tagsInput = document.getElementById('contactTags').value.trim();
        const notes = document.getElementById('contactNotes').value.trim();
        const status = document.getElementById('contactStatus').value;
        
        // Валидация
        if (!phone) {
            App.showToast('Введите номер телефона', 'warning');
            return;
        }
        
        if (!App.validatePhone(phone)) {
            App.showToast('Неверный формат телефона', 'warning');
            return;
        }
        
        if (email && !App.validateEmail(email)) {
            App.showToast('Неверный формат email', 'warning');
            return;
        }
        
        const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];
        
        const data = {
            phone,
            name: name || null,
            email: email || null,
            group_id: groupId || null,
            tags,
            notes: notes || null,
            status
        };
        
        try {
            if (id) {
                await App.apiPatch(`/contacts/${id}`, data);
                App.showToast('Контакт обновлён', 'success');
            } else {
                await App.apiPost('/contacts/', data);
                App.showToast('Контакт создан', 'success');
            }
            
            this.closeContactModal();
            this.loadContacts(this.state.currentPage);
            
        } catch (error) {
            App.showToast(error.message || 'Ошибка сохранения', 'error');
        }
    },

    async deleteContact(id) {
        if (!id) {
            id = document.getElementById('contactId')?.value;
        }
        
        if (!id) return;
        
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        if (!App.confirm('Удалить контакт?')) return;
        
        try {
            await App.apiDelete(`/contacts/${id}`);
            App.showToast('Контакт удалён', 'success');
            
            if (this.state.selectedContact) {
                this.closeContactModal();
            }
            
            this.loadContacts(this.state.currentPage);
            
        } catch (error) {
            App.showToast(error.message || 'Ошибка удаления', 'error');
        }
    },

    // =============================================
    // Импорт контактов
    // =============================================
    async importContacts() {
        const textarea = document.getElementById('contactsImport');
        const groupSelect = document.getElementById('contactGroupSelect');
        
        if (!textarea) return;
        
        const text = textarea.value.trim();
        if (!text) {
            App.showToast('Введите номера телефонов', 'warning');
            return;
        }
        
        const lines = text.split('\n').filter(line => line.trim());
        const contacts = lines.map(line => {
            const parts = line.split(',').map(p => p.trim());
            return {
                phone: parts[0] || '',
                name: parts[1] || ''
            };
        }).filter(c => c.phone);
        
        if (contacts.length === 0) {
            App.showToast('Не найдено валидных номеров', 'warning');
            return;
        }
        
        const groupId = groupSelect?.value || null;
        
        try {
            const response = await App.apiPost('/contacts/import', {
                group_id: groupId,
                contacts: contacts
            });
            
            App.showToast(
                `Импортировано: ${response.imported}, пропущено: ${response.skipped}`,
                'success'
            );
            
            textarea.value = '';
            this.loadContacts(1);
            this.loadContactGroupsForSelect(); // Обновляем счётчики групп
            
        } catch (error) {
            App.showToast(error.message || 'Ошибка импорта', 'error');
        }
    },

    // Разбор CSV в массив строк (каждая строка - массив ячеек), с
    // поддержкой кавычек ("..." с запятыми/переносами строк/
    // экранированными "" внутри) - простой split(',')/split('\n') ломался
    // бы на любом значении вроде company="Иванов, Петров и Ко". Тот же
    // формат, что отдаёт GET /contacts/export (utf-8-sig, запятая).
    _parseCsv(text) {
        // utf-8-sig BOM, который сам же экспорт и добавляет
        if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);

        const rows = [];
        let row = [];
        let field = '';
        let inQuotes = false;

        for (let i = 0; i < text.length; i++) {
            const ch = text[i];
            if (inQuotes) {
                if (ch === '"') {
                    if (text[i + 1] === '"') { field += '"'; i++; }
                    else { inQuotes = false; }
                } else {
                    field += ch;
                }
            } else if (ch === '"') {
                inQuotes = true;
            } else if (ch === ',') {
                row.push(field); field = '';
            } else if (ch === '\r') {
                // пропускаем, \n ниже завершит строку
            } else if (ch === '\n') {
                row.push(field); field = '';
                rows.push(row); row = [];
            } else {
                field += ch;
            }
        }
        if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }

        return rows.filter(r => r.length > 1 || (r.length === 1 && r[0].trim() !== ''));
    },

    // Заголовки могут быть на русском (как в подсказке под полем загрузки)
    // или английском (как в файле, который отдаёт сам экспорт) - сводим
    // оба варианта к именам полей, которые реально читает бэкенд
    // (ContactService._create_contact_from_import/_update_contact_from_import
    // в app/services/contact.py: phone/name/email/company).
    _csvHeaderAliases: {
        phone: 'phone', номер: 'phone', телефон: 'phone',
        name: 'name', имя: 'name', фио: 'name',
        email: 'email', почта: 'email',
        company: 'company', компания: 'company', организация: 'company',
    },

    // =============================================
    // Импорт контактов из CSV-файла
    // =============================================
    async importFromCsvFile() {
        const fileInput = document.getElementById('contactsImportFile');
        const file = fileInput?.files?.[0];
        if (!file) {
            App.showToast('Выберите CSV-файл', 'warning');
            return;
        }

        let text;
        try {
            text = await App.readFileAsText(file);
        } catch (error) {
            App.showToast('Не удалось прочитать файл', 'error');
            return;
        }

        const rows = this._parseCsv(text);
        if (rows.length < 2) {
            App.showToast('Файл пуст или содержит только заголовок', 'warning');
            return;
        }

        const header = rows[0].map(h => h.trim().toLowerCase());
        const fieldNames = header.map(h => this._csvHeaderAliases[h] || null);

        if (!fieldNames.includes('phone')) {
            App.showToast('В файле нет колонки с номером телефона (phone/номер/телефон)', 'error');
            return;
        }

        const contacts = rows.slice(1).map(cells => {
            const contact = {};
            fieldNames.forEach((field, idx) => {
                if (field && cells[idx] !== undefined && cells[idx] !== '') {
                    contact[field] = cells[idx];
                }
            });
            return contact;
        }).filter(c => c.phone);

        if (contacts.length === 0) {
            App.showToast('Не найдено ни одной строки с номером телефона', 'warning');
            return;
        }

        const groupSelect = document.getElementById('contactGroupSelect');
        const updateExisting = document.getElementById('contactsCsvUpdateExisting')?.checked || false;

        try {
            const response = await App.apiPost('/contacts/import', {
                group_id: groupSelect?.value || null,
                contacts: contacts,
                update_existing: updateExisting,
                skip_duplicates: !updateExisting,
            });

            App.showToast(
                `Импортировано: ${response.imported}, обновлено: ${response.updated}, ` +
                `пропущено: ${response.skipped + response.duplicates + response.invalid}`,
                'success'
            );

            fileInput.value = '';
            this.loadContacts(1);
            this.loadContactGroupsForSelect();

        } catch (error) {
            App.showToast(error.message || 'Ошибка импорта файла', 'error');
        }
    },

    // =============================================
    // Экспорт контактов
    // =============================================
    async exportContacts() {
        try {
            // GET /contacts/export возвращает не JSON, а готовый CSV-файл
            // (StreamingResponse, media_type=text/csv) - App.apiGet() всегда
            // делает response.json(), что на CSV-тексте валится с
            // SyntaxError ещё до того, как этот код вообще успевал что-то
            // собрать сам. Экспорт был полностью нерабочим - любое нажатие
            // сразу показывало "Ошибка экспорта". Бэкенд уже формирует
            // корректный CSV (с UTF-8 BOM для Excel) - здесь просто
            // забираем его как текст и отдаём на скачивание как есть,
            // вместо повторной (и менее полной) пересборки на клиенте.
            const response = await App.apiFetch('/contacts/export?format=csv');
            if (!response.ok) {
                throw new Error(await App.extractApiError(response));
            }
            const csv = await response.text();

            App.downloadFile(csv, 'contacts.csv', 'text/csv');
            App.showToast('Экспорт завершён', 'success');

        } catch (error) {
            App.showToast(error.message || 'Ошибка экспорта', 'error');
        }
    },

    // =============================================
    // Загрузка групп для select
    // =============================================
    async loadContactGroupsForSelect() {
        try {
            const data = await App.apiGet('/contact-groups/');
            const groups = data.items || data;
            
            const selects = ['contactGroupSelect', 'contactGroup'];
            selects.forEach(id => {
                const select = document.getElementById(id);
                if (select) {
                    const currentValue = select.value;
                    select.innerHTML = '<option value="">Без группы</option>' +
                        groups.map(g => `<option value="${g.id}">${g.name} (${g.contacts_count || 0})</option>`).join('');
                    if (currentValue) select.value = currentValue;
                }
            });
            
            // Сохраняем в кэш
            App.cache.contactGroups = groups;
            
        } catch (error) {
            console.error('Failed to load contact groups:', error);
        }
    },

    // =============================================
    // Действия с контактом
    // =============================================
    async callContact(phone) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        // Открываем модалку быстрого звонка
        const campaignId = prompt('Введите ID обзвона для звонка (или оставьте пустым для тестового):');

        try {
            if (campaignId) {
                await App.apiPost(`/campaigns/${campaignId}/call`, { phone });
                App.showToast(`Звонок на ${phone} запущен в обзвоне ${campaignId}`, 'success');
            } else {
                // Тестовый звонок
                await App.apiPost('/system/test-call', { phone });
                App.showToast(`Тестовый звонок на ${phone} запущен`, 'success');
            }
        } catch (error) {
            App.showToast(error.message || 'Ошибка запуска звонка', 'error');
        }
    },

    async addToBlacklist(phone, reason = '') {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost('/blacklist/', { phone, reason });
            App.showToast(`Номер ${phone} добавлен в чёрный список`, 'success');
            this.loadContacts(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    // =============================================
    // Массовые операции
    // =============================================
    async batchDelete(contactIds) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может выполнять массовое удаление', 'error');
            return;
        }
        
        if (!App.confirm(`Удалить ${contactIds.length} контактов?`)) return;
        
        try {
            await App.apiPost('/contacts/batch-delete', { contact_ids: contactIds });
            App.showToast(`Удалено ${contactIds.length} контактов`, 'success');
            this.loadContacts(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    async batchAssignGroup(contactIds, groupId) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost('/contacts/batch-assign-group', { contact_ids: contactIds, group_id: groupId });
            App.showToast(`Назначена группа для ${contactIds.length} контактов`, 'success');
            this.loadContacts(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    // =============================================
    // История звонков контакта
    // =============================================
    async viewContactHistory(contactId) {
        try {
            const data = await App.apiGet(`/contacts/${contactId}/history`);
            
            let html = '<div class="contact-history">';
            html += '<h4>История звонков</h4>';
            
            if (!data.history || data.history.length === 0) {
                html += '<p>Нет истории звонков</p>';
            } else {
                html += '<table class="table"><thead><tr><th>Дата</th><th>Обзвон</th><th>Статус</th><th>DTMF</th><th>Длит.</th></tr></thead><tbody>';
                
                for (const call of data.history) {
                    html += `<tr>
                        <td>${App.formatDateTime(call.created_at)}</td>
                        <td>${call.campaign_name || '-'}</td>
                        <td><span class="status-badge status-${call.status}">${call.status}</span></td>
                        <td>${call.dtmf_result || '-'}</td>
                        <td>${App.formatDuration(call.duration)}</td>
                    </tr>`;
                }
                
                html += '</tbody></table>';
            }
            
            html += '</div>';
            
            // Показываем в модальном окне
            document.getElementById('contactHistoryContent').innerHTML = html;
            App.showModal('contactHistoryModal');
            
        } catch (error) {
            console.error('Failed to load contact history:', error);
            App.showToast('Ошибка загрузки истории', 'error');
        }
    },

    closeContactHistoryModal() {
        App.hideModal('contactHistoryModal');
    },

    // =============================================
    // Поиск дубликатов
    // =============================================
    async findDuplicates() {
        try {
            const data = await App.apiGet('/contacts/duplicates');
            
            if (!data.duplicates || data.duplicates.length === 0) {
                App.showToast('Дубликаты не найдены', 'info');
                return;
            }
            
            let html = '<div class="duplicates-list">';
            html += `<h4>Найдено ${data.duplicates.length} дубликатов</h4>`;
            
            for (const dup of data.duplicates) {
                html += `<div class="duplicate-group">`;
                html += `<strong>Телефон: ${dup.phone}</strong>`;
                html += '<ul>';
                for (const contact of dup.contacts) {
                    html += `<li>ID ${contact.id}: ${contact.name || 'Без имени'} (${contact.status})</li>`;
                }
                html += '</ul>';
                html += `<button class="btn btn-sm btn-outline" onclick="App.contacts.mergeDuplicates('${dup.phone}')">Объединить</button>`;
                html += '</div>';
            }
            
            html += '</div>';
            
            document.getElementById('duplicatesContent').innerHTML = html;
            App.showModal('duplicatesModal');
            
        } catch (error) {
            console.error('Failed to find duplicates:', error);
            App.showToast('Ошибка поиска дубликатов', 'error');
        }
    },

    async mergeDuplicates(phone) {
        if (!App.confirm('Объединить дубликаты для этого номера?')) return;
        
        try {
            await App.apiPost('/contacts/merge', { phone });
            App.showToast('Дубликаты объединены', 'success');
            App.hideModal('duplicatesModal');
            this.loadContacts(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка объединения', 'error');
        }
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.openContactModal = () => App.contacts.openContactModal();
window.closeContactModal = () => App.contacts.closeContactModal();
window.saveContact = () => App.contacts.saveContact();
window.deleteContact = (id) => App.contacts.deleteContact(id);
window.importContacts = () => App.contacts.importContacts();
window.exportContacts = () => App.contacts.exportContacts();
window.searchContacts = () => App.contacts.loadContacts(1);
window.viewContactHistory = (id) => App.contacts.viewContactHistory(id);
window.closeContactHistoryModal = () => App.contacts.closeContactHistoryModal();
