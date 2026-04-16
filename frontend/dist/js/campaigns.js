/**
 * AutoDialer Ultimate - Campaigns Module
 * Version: 3.0.0
 * Управление кампаниями обзвона
 */

App.campaigns = {
    // Состояние модуля
    state: {
        campaigns: [],
        currentPage: 1,
        totalPages: 1,
        pageSize: 20,
        filterStatus: '',
        searchQuery: '',
        selectedCampaign: null,
        audioFiles: []
    },

    // =============================================
    // Инициализация
    // =============================================
    async init() {
        await this.loadCampaigns();
        await this.loadAudioForSelect();
        this.setupEventListeners();
    },

    setupEventListeners() {
        // Поиск с дебаунсом
        const searchInput = document.getElementById('campaignSearch');
        if (searchInput) {
            searchInput.addEventListener('input', App.debounce(() => {
                this.state.searchQuery = searchInput.value;
                this.loadCampaigns(1);
            }, 300));
        }

        // Фильтр по статусу
        const statusFilter = document.getElementById('campaignStatusFilter');
        if (statusFilter) {
            statusFilter.addEventListener('change', () => {
                this.state.filterStatus = statusFilter.value;
                this.loadCampaigns(1);
            });
        }

        // Кнопка обновления
        const refreshBtn = document.getElementById('campaignsRefreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadCampaigns());
        }
    },

    // =============================================
    // Загрузка кампаний
    // =============================================
    async loadCampaigns(page = 1) {
        this.state.currentPage = page;
        
        const tbody = document.getElementById('campaignsTableBody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center"><div class="loading">Загрузка...</div></td></tr>';
        }
        
        try {
            let url = `/campaigns?page=${page}&page_size=${this.state.pageSize}`;
            
            if (this.state.filterStatus) {
                url += `&status=${this.state.filterStatus}`;
            }
            if (this.state.searchQuery) {
                url += `&search=${encodeURIComponent(this.state.searchQuery)}`;
            }
            
            const data = await App.apiGet(url);
            
            this.state.campaigns = data.items || data || [];
            this.state.totalPages = data.total_pages || 1;
            
            this.renderTable();
            App.renderPagination('campaignsPagination', page, this.state.totalPages, 'App.campaigns.loadCampaigns');
            
        } catch (error) {
            console.error('Failed to load campaigns:', error);
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
            App.showToast('Ошибка загрузки кампаний', 'error');
        }
    },

    // =============================================
    // Рендер таблицы
    // =============================================
    renderTable() {
        const tbody = document.getElementById('campaignsTableBody');
        if (!tbody) return;
        
        const campaigns = this.state.campaigns;
        
        if (!campaigns || campaigns.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">📋</div>
                            <p>Нет кампаний</p>
                            ${App.auth.isOperator() ? `
                                <button class="btn btn-primary" onclick="App.campaigns.openCampaignModal()">
                                    Создать первую кампанию
                                </button>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = campaigns.map(c => {
            const progress = c.stats?.progress_percent || 0;
            const called = c.stats?.called_contacts || 0;
            const total = c.stats?.total_contacts || 0;
            const conversion = c.stats?.conversion_rate || 0;
            
            return `
                <tr data-campaign-id="${c.id}" class="campaign-row ${c.status}">
                    <td>${c.id}</td>
                    <td>
                        <strong>${this.escapeHtml(c.name)}</strong>
                        ${c.description ? `<br><small>${this.escapeHtml(c.description)}</small>` : ''}
                    </td>
                    <td>
                        <span class="status-badge status-${c.status}">${this.getStatusText(c.status)}</span>
                    </td>
                    <td>${c.max_calls || 10}</td>
                    <td>${c.cps || 1}</td>
                    <td>
                        <div class="progress-container">
                            <div class="progress-bar" style="width: 80px;">
                                <div class="progress-fill" style="width: ${progress}%"></div>
                            </div>
                            <span class="progress-text">${called}/${total}</span>
                        </div>
                    </td>
                    <td>
                        <span class="${conversion > 0 ? 'text-success' : ''}">${conversion}%</span>
                    </td>
                    <td>${this.formatDate(c.created_at)}</td>
                    <td class="actions-cell">
                        <div class="action-buttons">
                            <button class="btn btn-sm btn-outline" onclick="App.campaigns.viewCampaignDetail(${c.id})" title="Просмотр">
                                👁️
                            </button>
                            ${c.status === 'draft' ? `
                                <button class="btn btn-sm btn-success" onclick="App.campaigns.startCampaign(${c.id})" title="Запустить">
                                    ▶️
                                </button>
                            ` : ''}
                            ${c.status === 'running' ? `
                                <button class="btn btn-sm btn-warning" onclick="App.campaigns.pauseCampaign(${c.id})" title="Пауза">
                                    ⏸️
                                </button>
                                ${App.auth.isAdmin() ? `
                                    <button class="btn btn-sm btn-danger" onclick="App.campaigns.stopCampaign(${c.id})" title="Остановить">
                                        ⏹️
                                    </button>
                                ` : ''}
                            ` : ''}
                            ${c.status === 'paused' ? `
                                <button class="btn btn-sm btn-success" onclick="App.campaigns.resumeCampaign(${c.id})" title="Продолжить">
                                    ▶️
                                </button>
                            ` : ''}
                            ${App.auth.isOperator() && c.status !== 'running' ? `
                                <button class="btn btn-sm btn-outline" onclick="App.campaigns.editCampaign(${c.id})" title="Редактировать">
                                    ✏️
                                </button>
                            ` : ''}
                            ${App.auth.isAdmin() && c.status !== 'running' ? `
                                <button class="btn btn-sm btn-outline-danger" onclick="App.campaigns.deleteCampaign(${c.id})" title="Удалить">
                                    🗑️
                                </button>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
        
        // Добавляем обработчики клика по строке
        document.querySelectorAll('.campaign-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (!e.target.closest('button')) {
                    const id = row.dataset.campaignId;
                    this.viewCampaignDetail(id);
                }
            });
        });
    },

    // =============================================
    // Модальное окно создания/редактирования
    // =============================================
    openCampaignModal(campaign = null) {
        const modal = document.getElementById('campaignModal');
        const title = document.getElementById('campaignModalTitle');
        const deleteBtn = document.getElementById('campaignDeleteBtn');
        
        if (!modal) return;
        
        const isEdit = !!campaign;
        
        if (isEdit) {
            title.textContent = 'Редактировать кампанию';
            deleteBtn.style.display = 'inline-block';
            
            this.state.selectedCampaign = campaign;
            
            document.getElementById('campaignId').value = campaign.id;
            document.getElementById('campaignName').value = campaign.name || '';
            document.getElementById('campaignDescription').value = campaign.description || '';
            document.getElementById('campaignMaxCalls').value = campaign.max_calls || 10;
            document.getElementById('campaignCps').value = campaign.cps || 1;
            document.getElementById('campaignCallerId').value = campaign.caller_id || '';
            document.getElementById('campaignAudioSelect').value = campaign.audio_id || '';
            
            // Стратегия повторных звонков
            if (campaign.retry_strategy) {
                document.getElementById('retryBusyMax').value = campaign.retry_strategy.busy || 2;
                document.getElementById('retryBusyDelay').value = campaign.retry_strategy.busy_delay || 300;
                document.getElementById('retryNoanswerMax').value = campaign.retry_strategy.noanswer || 3;
                document.getElementById('retryNoanswerDelay').value = campaign.retry_strategy.noanswer_delay || 600;
                document.getElementById('retryFailedMax').value = campaign.retry_strategy.failed || 1;
                document.getElementById('retryFailedDelay').value = campaign.retry_strategy.failed_delay || 1800;
            }
            
            // Расписание
            if (campaign.schedule) {
                document.getElementById('campaignScheduleEnabled').checked = campaign.schedule.enabled || false;
                document.getElementById('scheduleStartAt').value = campaign.schedule.start_at || '';
                document.getElementById('scheduleEndAt').value = campaign.schedule.end_at || '';
                document.getElementById('scheduleType').value = campaign.schedule.schedule_type || 'once';
            }
            
        } else {
            title.textContent = 'Новая кампания';
            deleteBtn.style.display = 'none';
            
            this.state.selectedCampaign = null;
            
            document.getElementById('campaignId').value = '';
            document.getElementById('campaignForm').reset();
            
            // Значения по умолчанию
            document.getElementById('campaignMaxCalls').value = 10;
            document.getElementById('campaignCps').value = 1;
            document.getElementById('retryBusyMax').value = 2;
            document.getElementById('retryBusyDelay').value = 300;
            document.getElementById('retryNoanswerMax').value = 3;
            document.getElementById('retryNoanswerDelay').value = 600;
            document.getElementById('retryFailedMax').value = 1;
            document.getElementById('retryFailedDelay').value = 1800;
            document.getElementById('scheduleType').value = 'once';
        }
        
        this.loadAudioForSelect();
        modal.style.display = 'flex';
    },

    closeCampaignModal() {
        const modal = document.getElementById('campaignModal');
        if (modal) {
            modal.style.display = 'none';
        }
        this.state.selectedCampaign = null;
    },

    editCampaign(id) {
        const campaign = this.state.campaigns.find(c => c.id === id);
        if (campaign) {
            this.openCampaignModal(campaign);
        }
    },

    // =============================================
    // Сохранение кампании
    // =============================================
    async saveCampaign() {
        const id = document.getElementById('campaignId')?.value;
        const name = document.getElementById('campaignName')?.value?.trim();
        const description = document.getElementById('campaignDescription')?.value?.trim();
        const maxCalls = parseInt(document.getElementById('campaignMaxCalls')?.value) || 10;
        const cps = parseInt(document.getElementById('campaignCps')?.value) || 1;
        const callerId = document.getElementById('campaignCallerId')?.value?.trim();
        const audioId = document.getElementById('campaignAudioSelect')?.value;
        
        // Валидация
        if (!name) {
            App.showToast('Введите название кампании', 'warning');
            return;
        }
        
        if (maxCalls < 1 || maxCalls > 100) {
            App.showToast('Количество каналов должно быть от 1 до 100', 'warning');
            return;
        }
        
        if (cps < 0.1 || cps > 50) {
            App.showToast('CPS должен быть от 0.1 до 50', 'warning');
            return;
        }
        
        // Стратегия повторных звонков
        const retryStrategy = {
            busy: parseInt(document.getElementById('retryBusyMax')?.value) || 2,
            busy_delay: parseInt(document.getElementById('retryBusyDelay')?.value) || 300,
            noanswer: parseInt(document.getElementById('retryNoanswerMax')?.value) || 3,
            noanswer_delay: parseInt(document.getElementById('retryNoanswerDelay')?.value) || 600,
            failed: parseInt(document.getElementById('retryFailedMax')?.value) || 1,
            failed_delay: parseInt(document.getElementById('retryFailedDelay')?.value) || 1800
        };
        
        // Расписание
        let schedule = null;
        if (document.getElementById('campaignScheduleEnabled')?.checked) {
            schedule = {
                enabled: true,
                start_at: document.getElementById('scheduleStartAt')?.value || null,
                end_at: document.getElementById('scheduleEndAt')?.value || null,
                schedule_type: document.getElementById('scheduleType')?.value || 'once'
            };
        }
        
        const data = {
            name,
            description: description || null,
            max_calls: maxCalls,
            cps,
            caller_id: callerId || null,
            audio_id: audioId || null,
            retry_strategy: retryStrategy,
            schedule
        };
        
        const submitBtn = document.querySelector('#campaignForm button[type="submit"]');
        const originalText = submitBtn?.textContent;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = '⏳ Сохранение...';
        }
        
        try {
            if (id) {
                await App.apiPut(`/campaigns/${id}`, data);
                App.showToast('Кампания обновлена', 'success');
            } else {
                await App.apiPost('/campaigns', data);
                App.showToast('Кампания создана', 'success');
            }
            
            this.closeCampaignModal();
            await this.loadCampaigns(this.state.currentPage);
            
        } catch (error) {
            console.error('Failed to save campaign:', error);
            App.showToast(error.message || 'Ошибка сохранения', 'error');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        }
    },

    // =============================================
    // Управление статусом кампании
    // =============================================
    async startCampaign(id) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/start`, {});
            App.showToast('Кампания запущена', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to start campaign:', error);
            App.showToast(error.message || 'Ошибка запуска', 'error');
        }
    },

    async pauseCampaign(id) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/pause`, {});
            App.showToast('Кампания приостановлена', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to pause campaign:', error);
            App.showToast(error.message || 'Ошибка паузы', 'error');
        }
    },

    async resumeCampaign(id) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/resume`, {});
            App.showToast('Кампания возобновлена', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to resume campaign:', error);
            App.showToast(error.message || 'Ошибка возобновления', 'error');
        }
    },

    async stopCampaign(id) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может остановить кампанию', 'error');
            return;
        }
        
        if (!App.confirm('Остановить кампанию? Все активные звонки будут завершены.')) {
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/stop`, {});
            App.showToast('Кампания остановлена', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to stop campaign:', error);
            App.showToast(error.message || 'Ошибка остановки', 'error');
        }
    },

    async deleteCampaign(id) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может удалить кампанию', 'error');
            return;
        }
        
        if (!App.confirm('Удалить кампанию? Это действие нельзя отменить.')) {
            return;
        }
        
        try {
            await App.apiDelete(`/campaigns/${id}`);
            App.showToast('Кампания удалена', 'success');
            
            if (this.state.selectedCampaign?.id === id) {
                this.closeCampaignModal();
            }
            
            await this.loadCampaigns(this.state.currentPage);
            
        } catch (error) {
            console.error('Failed to delete campaign:', error);
            App.showToast(error.message || 'Ошибка удаления', 'error');
        }
    },

    // =============================================
    // Просмотр деталей кампании
    // =============================================
    async viewCampaignDetail(id) {
        try {
            const data = await App.apiGet(`/campaigns/${id}`);
            const campaign = data.campaign || data;
            const stats = data.stats || {};
            
            const modal = document.getElementById('campaignDetailModal');
            const title = document.getElementById('campaignDetailTitle');
            const content = document.getElementById('campaignDetailContent');
            
            if (!modal || !content) return;
            
            title.textContent = campaign.name;
            
            content.innerHTML = `
                <div class="campaign-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID:</td><td>${campaign.id}</td></tr>
                            <tr><td>Статус:</td><td><span class="status-badge status-${campaign.status}">${this.getStatusText(campaign.status)}</span></td></tr>
                            <tr><td>Описание:</td><td>${this.escapeHtml(campaign.description || '—')}</td></tr>
                            <tr><td>Макс. каналов:</td><td>${campaign.max_calls || 10}</td></tr>
                            <tr><td>CPS:</td><td>${campaign.cps || 1}</td></tr>
                            <tr><td>Caller ID:</td><td>${this.escapeHtml(campaign.caller_id || '—')}</td></tr>
                            <tr><td>Создана:</td><td>${App.formatDateTime(campaign.created_at)}</td></tr>
                        </table>
                    </div>
                    
                    <div class="detail-section">
                        <h4>Статистика</h4>
                        <div class="stats-grid-detail">
                            <div class="stat-item-detail">
                                <span class="stat-label">Всего звонков</span>
                                <span class="stat-value">${stats.total_calls || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Отвечено</span>
                                <span class="stat-value text-success">${stats.answered || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Согласий</span>
                                <span class="stat-value text-success">${stats.agreed || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Конверсия</span>
                                <span class="stat-value">${stats.conversion_rate || 0}%</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Занято</span>
                                <span class="stat-value text-warning">${stats.busy || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Нет ответа</span>
                                <span class="stat-value">${stats.noanswer || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Ошибок</span>
                                <span class="stat-value text-danger">${stats.failed || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Прогресс</span>
                                <span class="stat-value">${stats.called_contacts || 0}/${stats.total_contacts || 0}</span>
                            </div>
                        </div>
                        <div class="progress-bar" style="margin-top: 10px;">
                            <div class="progress-fill" style="width: ${stats.progress_percent || 0}%"></div>
                        </div>
                    </div>
                    
                    ${campaign.schedule ? `
                        <div class="detail-section">
                            <h4>Расписание</h4>
                            <table class="details-table">
                                <tr><td>Активно:</td><td>${campaign.schedule.enabled ? '✅ Да' : '❌ Нет'}</td></tr>
                                <tr><td>Начало:</td><td>${campaign.schedule.start_at ? App.formatDateTime(campaign.schedule.start_at) : '—'}</td></tr>
                                <tr><td>Конец:</td><td>${campaign.schedule.end_at ? App.formatDateTime(campaign.schedule.end_at) : '—'}</td></tr>
                                <tr><td>Тип:</td><td>${campaign.schedule.schedule_type || 'once'}</td></tr>
                            </table>
                        </div>
                    ` : ''}
                    
                    ${campaign.retry_strategy ? `
                        <div class="detail-section">
                            <h4>Стратегия повторных звонков</h4>
                            <table class="details-table">
                                <tr><td>Занято:</td><td>${campaign.retry_strategy.busy || 2} попыток, задержка ${campaign.retry_strategy.busy_delay || 300}с</td></tr>
                                <tr><td>Нет ответа:</td><td>${campaign.retry_strategy.noanswer || 3} попыток, задержка ${campaign.retry_strategy.noanswer_delay || 600}с</td></tr>
                                <tr><td>Ошибка:</td><td>${campaign.retry_strategy.failed || 1} попыток, задержка ${campaign.retry_strategy.failed_delay || 1800}с</td></tr>
                            </table>
                        </div>
                    ` : ''}
                </div>
            `;
            
            modal.style.display = 'flex';
            
        } catch (error) {
            console.error('Failed to load campaign detail:', error);
            App.showToast('Ошибка загрузки деталей', 'error');
        }
    },

    closeCampaignDetailModal() {
        const modal = document.getElementById('campaignDetailModal');
        if (modal) {
            modal.style.display = 'none';
        }
    },

    // =============================================
    // Назначение контактов кампании
    // =============================================
    async openAssignContactsModal(campaignId) {
        // Закрываем детали
        this.closeCampaignDetailModal();
        
        try {
            const groups = await App.apiGet('/contact-groups');
            const contacts = await App.apiGet('/contacts?limit=10000');
            
            const modal = document.getElementById('assignContactsModal');
            const content = document.getElementById('assignContactsContent');
            
            if (!modal || !content) return;
            
            content.innerHTML = `
                <div class="assign-contacts">
                    <input type="hidden" id="assignCampaignId" value="${campaignId}">
                    
                    <div class="form-group">
                        <label>Выберите группы</label>
                        <div class="checkbox-group">
                            ${groups.map(g => `
                                <label>
                                    <input type="checkbox" name="groupIds" value="${g.id}">
                                    ${this.escapeHtml(g.name)} (${g.contacts_count || 0})
                                </label>
                            `).join('')}
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label>Или выберите отдельные контакты</label>
                        <select id="contactsSelect" multiple class="form-control" style="height: 200px;">
                            ${contacts.map(c => `
                                <option value="${c.id}">${this.formatPhone(c.phone)} ${c.name ? '- ' + c.name : ''}</option>
                            `).join('')}
                        </select>
                    </div>
                    
                    <div class="form-actions">
                        <button class="btn btn-primary" onclick="App.campaigns.assignContacts()">
                            Назначить контакты
                        </button>
                    </div>
                </div>
            `;
            
            modal.style.display = 'flex';
            
        } catch (error) {
            console.error('Failed to open assign modal:', error);
            App.showToast('Ошибка загрузки', 'error');
        }
    },

    async assignContacts() {
        const campaignId = document.getElementById('assignCampaignId')?.value;
        const groupCheckboxes = document.querySelectorAll('input[name="groupIds"]:checked');
        const contactsSelect = document.getElementById('contactsSelect');
        
        const groupIds = Array.from(groupCheckboxes).map(cb => parseInt(cb.value));
        const contactIds = Array.from(contactsSelect?.selectedOptions || []).map(opt => parseInt(opt.value));
        
        if (groupIds.length === 0 && contactIds.length === 0) {
            App.showToast('Выберите группы или контакты', 'warning');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${campaignId}/assign-contacts`, {
                group_ids: groupIds,
                contact_ids: contactIds
            });
            
            App.showToast('Контакты назначены', 'success');
            App.hideModal('assignContactsModal');
            
        } catch (error) {
            console.error('Failed to assign contacts:', error);
            App.showToast(error.message || 'Ошибка назначения', 'error');
        }
    },

    // =============================================
    // Загрузка аудио для select
    // =============================================
    async loadAudioForSelect() {
        try {
            const data = await App.apiGet('/audio?limit=100');
            this.state.audioFiles = data.items || data || [];
            
            const select = document.getElementById('campaignAudioSelect');
            if (select) {
                const currentValue = select.value;
                select.innerHTML = '<option value="">Стандартное приветствие</option>' +
                    this.state.audioFiles.map(a => 
                        `<option value="${a.id}">${this.escapeHtml(a.name)} (${a.format || 'аудио'})</option>`
                    ).join('');
                if (currentValue) select.value = currentValue;
            }
        } catch (error) {
            console.error('Failed to load audio files:', error);
        }
    },

    // =============================================
    // Экспорт результатов кампании
    // =============================================
    async exportCampaignResults(campaignId) {
        try {
            const response = await App.apiGet(`/campaigns/${campaignId}/export`);
            
            let csv = 'phone,contact_name,status,duration,dtmf_result,call_date\n';
            
            for (const call of response.calls || []) {
                csv += `${call.phone},${call.contact_name || ''},${call.status},${call.duration || 0},${call.dtmf_result || ''},${call.created_at}\n`;
            }
            
            App.downloadFile(csv, `campaign_${campaignId}_results.csv`, 'text/csv');
            App.showToast('Экспорт завершён', 'success');
            
        } catch (error) {
            console.error('Failed to export results:', error);
            App.showToast('Ошибка экспорта', 'error');
        }
    },

    // =============================================
    // Утилиты
    // =============================================
    getStatusText(status) {
        const map = {
            'draft': 'Черновик',
            'ready': 'Готов',
            'running': 'Запущена',
            'paused': 'Приостановлена',
            'stopped': 'Остановлена',
            'completed': 'Завершена',
            'failed': 'Ошибка'
        };
        return map[status] || status;
    },

    formatPhone(phone) {
        if (!phone) return '';
        const cleaned = phone.replace(/\D/g, '');
        if (cleaned.length === 11) {
            return `+${cleaned[0]} (${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7, 9)}-${cleaned.slice(9, 11)}`;
        }
        return phone;
    },

    formatDate(isoString) {
        if (!isoString) return '—';
        const date = new Date(isoString);
        return date.toLocaleDateString('ru-RU');
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
        this.state.campaigns = [];
        this.state.selectedCampaign = null;
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.openCampaignModal = () => App.campaigns.openCampaignModal();
window.closeCampaignModal = () => App.campaigns.closeCampaignModal();
window.saveCampaign = () => App.campaigns.saveCampaign();
window.startCampaign = (id) => App.campaigns.startCampaign(id);
window.pauseCampaign = (id) => App.campaigns.pauseCampaign(id);
window.resumeCampaign = (id) => App.campaigns.resumeCampaign(id);
window.stopCampaign = (id) => App.campaigns.stopCampaign(id);
window.deleteCampaign = (id) => App.campaigns.deleteCampaign(id);
window.viewCampaignDetail = (id) => App.campaigns.viewCampaignDetail(id);
window.closeCampaignDetailModal = () => App.campaigns.closeCampaignDetailModal();
window.editCampaign = (id) => App.campaigns.editCampaign(id);
