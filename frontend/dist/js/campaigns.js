/**
 * AutoDialer Ultimate - Campaigns Module
 * Version: 3.0.0
 */

App.campaigns = {
    // Состояние модуля
    state: {
        campaigns: [],
        currentPage: 1,
        totalPages: 1,
        selectedCampaign: null,
        filterStatus: ''
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
        // Обработчик для переключения расписания
        const scheduleCheckbox = document.getElementById('campaignScheduleEnabled');
        const scheduleOptions = document.getElementById('campaignScheduleOptions');
        if (scheduleCheckbox && scheduleOptions) {
            scheduleCheckbox.addEventListener('change', (e) => {
                scheduleOptions.style.display = e.target.checked ? 'block' : 'none';
            });
        }
    },

    // =============================================
    // Загрузка кампаний
    // =============================================
    async loadCampaigns(page = 1) {
        this.state.currentPage = page;
        
        try {
            const url = `/campaigns?page=${page}&page_size=20${this.state.filterStatus ? `&status=${this.state.filterStatus}` : ''}`;
            const data = await App.apiGet(url);
            
            this.state.campaigns = data.items || data;
            this.state.totalPages = data.total_pages || 1;
            
            this.renderCampaignsTable();
            App.renderPagination('campaignsPagination', page, this.state.totalPages, 'App.campaigns.loadCampaigns');
            
        } catch (error) {
            console.error('Failed to load campaigns:', error);
            App.showToast('Ошибка загрузки кампаний', 'error');
        }
    },

    renderCampaignsTable() {
        const tbody = document.getElementById('campaignsTable');
        if (!tbody) return;
        
        const campaigns = this.state.campaigns;
        
        if (!campaigns || campaigns.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center">Нет кампаний</td></tr>';
            return;
        }
        
        const statusMap = {
            'draft': 'Черновик',
            'running': 'Запущена',
            'paused': 'Приостановлена',
            'stopped': 'Остановлена',
            'completed': 'Завершена',
            'failed': 'Ошибка',
            'scheduled': 'Запланирована'
        };
        
        tbody.innerHTML = campaigns.map(c => `
            <tr>
                <td>${c.id}</td>
                <td>${c.name}</td>
                <td><span class="status-badge status-${c.status}">${statusMap[c.status] || c.status}</span></td>
                <td>${c.max_calls}</td>
                <td>${c.cps}</td>
                <td>
                    <div class="progress-bar" style="width:80px;">
                        <div class="progress-fill" style="width:${c.stats?.progress_percent || 0}%"></div>
                    </div>
                    ${c.stats?.called_contacts || 0}/${c.stats?.total_contacts || 0}
                </td>
                <td>${c.stats?.conversion_rate || 0}%</td>
                <td class="actions">
                    <button class="btn btn-outline btn-sm" onclick="App.campaigns.viewCampaign(${c.id})" title="Просмотр">👁</button>
                    ${c.status === 'draft' ? `<button class="btn btn-success btn-sm" onclick="App.campaigns.startCampaign(${c.id})" title="Запустить">▶</button>` : ''}
                    ${c.status === 'running' ? `<button class="btn btn-warning btn-sm" onclick="App.campaigns.pauseCampaign(${c.id})" title="Пауза">⏸</button>` : ''}
                    ${c.status === 'paused' ? `<button class="btn btn-success btn-sm" onclick="App.campaigns.resumeCampaign(${c.id})" title="Продолжить">▶</button>` : ''}
                    ${c.status === 'running' && App.auth.isAdmin() ? `<button class="btn btn-danger btn-sm" onclick="App.campaigns.stopCampaign(${c.id})" title="Остановить">⏹</button>` : ''}
                    ${App.auth.isAdmin() && c.status !== 'running' ? `<button class="btn btn-outline btn-sm" onclick="App.campaigns.deleteCampaign(${c.id})" title="Удалить">🗑</button>` : ''}
                </td>
            </tr>
        `).join('');
    },

    // =============================================
    // Фильтрация
    // =============================================
    filterByStatus(status) {
        this.state.filterStatus = status;
        this.loadCampaigns(1);
    },

    // =============================================
    // Действия с кампанией
    // =============================================
    async startCampaign(id) {
        if (!App.auth.hasPermission('start_campaigns')) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/start`, {});
            App.showToast('Кампания запущена', 'success');
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка запуска', 'error');
        }
    },

    async pauseCampaign(id) {
        try {
            await App.apiPost(`/campaigns/${id}/pause`, {});
            App.showToast('Кампания приостановлена', 'success');
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    async resumeCampaign(id) {
        try {
            await App.apiPost(`/campaigns/${id}/resume`, {});
            App.showToast('Кампания возобновлена', 'success');
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    async stopCampaign(id) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может останавливать кампании', 'error');
            return;
        }
        
        if (!App.confirm('Остановить кампанию? Все активные звонки будут прерваны.')) {
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/stop`, {});
            App.showToast('Кампания остановлена', 'success');
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка', 'error');
        }
    },

    async deleteCampaign(id) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может удалять кампании', 'error');
            return;
        }
        
        if (!App.confirm('Удалить кампанию? Это действие нельзя отменить.')) {
            return;
        }
        
        try {
            await App.apiDelete(`/campaigns/${id}`);
            App.showToast('Кампания удалена', 'success');
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка удаления', 'error');
        }
    },

    // =============================================
    // Просмотр кампании
    // =============================================
    async viewCampaign(id) {
        try {
            const data = await App.apiGet(`/campaigns/${id}`);
            this.state.selectedCampaign = data.campaign;
            
            this.showCampaignDetailModal(data);
            
        } catch (error) {
            console.error('Failed to load campaign detail:', error);
            App.showToast('Ошибка загрузки', 'error');
        }
    },

    showCampaignDetailModal(data) {
        const campaign = data.campaign;
        const stats = data.stats || {};
        
        document.getElementById('campaignDetailTitle').textContent = campaign.name;
        
        // Статистика
        document.getElementById('campaignDetailStats').innerHTML = `
            <div class="stats-grid" style="grid-template-columns: repeat(4, 1fr);">
                <div class="stat-card"><div class="stat-value">${stats.total_contacts || 0}</div><div>Контактов</div></div>
                <div class="stat-card"><div class="stat-value">${stats.total_calls || 0}</div><div>Звонков</div></div>
                <div class="stat-card"><div class="stat-value">${stats.agreed || 0}</div><div>Согласий</div></div>
                <div class="stat-card"><div class="stat-value">${stats.conversion_rate || 0}%</div><div>Конверсия</div></div>
                <div class="stat-card"><div class="stat-value">${stats.busy || 0}</div><div>Занято</div></div>
                <div class="stat-card"><div class="stat-value">${stats.noanswer || 0}</div><div>Нет ответа</div></div>
                <div class="stat-card"><div class="stat-value">${stats.failed || 0}</div><div>Ошибок</div></div>
                <div class="stat-card"><div class="stat-value">${stats.avg_duration || 0}с</div><div>Ср. длит.</div></div>
            </div>
        `;
        
        // Информация о расписании
        const schedule = campaign.schedule;
        document.getElementById('campaignScheduleInfo').innerHTML = schedule && schedule.enabled
            ? `<p>Тип: ${schedule.schedule_type || 'однократно'}</p>
               ${schedule.start_at ? `<p>Начало: ${App.formatDateTime(schedule.start_at)}</p>` : ''}
               ${schedule.end_at ? `<p>Окончание: ${App.formatDateTime(schedule.end_at)}</p>` : ''}`
            : '<p>Расписание не настроено</p>';
        
        // Информация о retry стратегии
        const retry = campaign.retry_strategy;
        if (retry) {
            document.getElementById('campaignRetryInfo').innerHTML = `
                <p>BUSY: ${retry.busy || 2} попыток, задержка ${retry.busy_delay || 120}с</p>
                <p>NOANSWER: ${retry.noanswer || 3} попыток, задержка ${retry.noanswer_delay || 300}с</p>
                <p>FAILED: ${retry.failed || 1} попыток, задержка ${retry.failed_delay || 60}с</p>
            `;
        }
        
        App.showModal('campaignDetailModal');
    },

    closeCampaignDetailModal() {
        App.hideModal('campaignDetailModal');
        this.state.selectedCampaign = null;
    },

    // =============================================
    // Создание кампании
    // =============================================
    openCampaignModal() {
        // Очищаем форму
        document.getElementById('campaignNameInput').value = '';
        document.getElementById('campaignDescription').value = '';
        document.getElementById('campaignMaxCalls').value = '30';
        document.getElementById('campaignCps').value = '5';
        document.getElementById('campaignCallerId').value = '';
        document.getElementById('campaignScheduleEnabled').checked = false;
        document.getElementById('campaignScheduleOptions').style.display = 'none';
        
        // Сбрасываем retry стратегию
        document.getElementById('retryBusyMax').value = '2';
        document.getElementById('retryBusyDelay').value = '120';
        document.getElementById('retryNoanswerMax').value = '3';
        document.getElementById('retryNoanswerDelay').value = '300';
        document.getElementById('retryFailedMax').value = '1';
        document.getElementById('retryFailedDelay').value = '60';
        
        this.loadAudioForSelect();
        App.showModal('campaignModal');
    },

    closeCampaignModal() {
        App.hideModal('campaignModal');
    },

    async createCampaign() {
        const name = document.getElementById('campaignNameInput').value;
        const description = document.getElementById('campaignDescription').value;
        const maxCalls = parseInt(document.getElementById('campaignMaxCalls').value) || 30;
        const cps = parseInt(document.getElementById('campaignCps').value) || 5;
        const audioId = document.getElementById('campaignAudioSelect').value;
        const callerId = document.getElementById('campaignCallerId').value;
        
        if (!name) {
            App.showToast('Введите название кампании', 'warning');
            return;
        }
        
        const data = {
            name,
            description: description || null,
            max_calls: maxCalls,
            cps: cps,
            audio_id: audioId || null,
            caller_id: callerId || null
        };
        
        // Расписание
        if (document.getElementById('campaignScheduleEnabled').checked) {
            data.schedule = {
                enabled: true,
                schedule_type: document.getElementById('scheduleType').value,
                start_at: document.getElementById('scheduleStartAt').value || null,
                end_at: document.getElementById('scheduleEndAt').value || null
            };
        }
        
        // Retry стратегия
        data.retry_strategy = {
            busy: parseInt(document.getElementById('retryBusyMax').value) || 2,
            busy_delay: parseInt(document.getElementById('retryBusyDelay').value) || 120,
            noanswer: parseInt(document.getElementById('retryNoanswerMax').value) || 3,
            noanswer_delay: parseInt(document.getElementById('retryNoanswerDelay').value) || 300,
            failed: parseInt(document.getElementById('retryFailedMax').value) || 1,
            failed_delay: parseInt(document.getElementById('retryFailedDelay').value) || 60
        };
        
        try {
            await App.apiPost('/campaigns', data);
            App.showToast('Кампания создана', 'success');
            this.closeCampaignModal();
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка создания', 'error');
        }
    },

    // =============================================
    // Редактирование кампании
    // =============================================
    async editCampaign(id) {
        try {
            const data = await App.apiGet(`/campaigns/${id}`);
            const campaign = data.campaign;
            
            // Заполняем форму
            document.getElementById('editCampaignId').value = campaign.id;
            document.getElementById('editCampaignName').value = campaign.name;
            document.getElementById('editCampaignDescription').value = campaign.description || '';
            document.getElementById('editCampaignMaxCalls').value = campaign.max_calls;
            document.getElementById('editCampaignCps').value = campaign.cps;
            document.getElementById('editCampaignCallerId').value = campaign.caller_id || '';
            
            await this.loadAudioForSelect('editCampaignAudio');
            document.getElementById('editCampaignAudio').value = campaign.audio_id || '';
            
            // Расписание
            if (campaign.schedule?.enabled) {
                document.getElementById('editScheduleEnabled').checked = true;
                document.getElementById('editScheduleOptions').style.display = 'block';
                document.getElementById('editScheduleType').value = campaign.schedule.schedule_type || 'once';
                document.getElementById('editScheduleStartAt').value = campaign.schedule.start_at?.slice(0, 16) || '';
                document.getElementById('editScheduleEndAt').value = campaign.schedule.end_at?.slice(0, 16) || '';
            }
            
            // Retry стратегия
            const retry = campaign.retry_strategy || {};
            document.getElementById('editRetryBusyMax').value = retry.busy || 2;
            document.getElementById('editRetryBusyDelay').value = retry.busy_delay || 120;
            document.getElementById('editRetryNoanswerMax').value = retry.noanswer || 3;
            document.getElementById('editRetryNoanswerDelay').value = retry.noanswer_delay || 300;
            document.getElementById('editRetryFailedMax').value = retry.failed || 1;
            document.getElementById('editRetryFailedDelay').value = retry.failed_delay || 60;
            
            App.showModal('editCampaignModal');
            
        } catch (error) {
            console.error('Failed to load campaign for edit:', error);
            App.showToast('Ошибка загрузки', 'error');
        }
    },

    closeEditCampaignModal() {
        App.hideModal('editCampaignModal');
    },

    async updateCampaign() {
        const id = document.getElementById('editCampaignId').value;
        const name = document.getElementById('editCampaignName').value;
        const description = document.getElementById('editCampaignDescription').value;
        const maxCalls = parseInt(document.getElementById('editCampaignMaxCalls').value) || 30;
        const cps = parseInt(document.getElementById('editCampaignCps').value) || 5;
        const audioId = document.getElementById('editCampaignAudio').value;
        const callerId = document.getElementById('editCampaignCallerId').value;
        
        if (!name) {
            App.showToast('Введите название кампании', 'warning');
            return;
        }
        
        const data = {
            name,
            description: description || null,
            max_calls: maxCalls,
            cps: cps,
            audio_id: audioId || null,
            caller_id: callerId || null
        };
        
        // Расписание
        if (document.getElementById('editScheduleEnabled').checked) {
            data.schedule = {
                enabled: true,
                schedule_type: document.getElementById('editScheduleType').value,
                start_at: document.getElementById('editScheduleStartAt').value || null,
                end_at: document.getElementById('editScheduleEndAt').value || null
            };
        } else {
            data.schedule = { enabled: false };
        }
        
        // Retry стратегия
        data.retry_strategy = {
            busy: parseInt(document.getElementById('editRetryBusyMax').value) || 2,
            busy_delay: parseInt(document.getElementById('editRetryBusyDelay').value) || 120,
            noanswer: parseInt(document.getElementById('editRetryNoanswerMax').value) || 3,
            noanswer_delay: parseInt(document.getElementById('editRetryNoanswerDelay').value) || 300,
            failed: parseInt(document.getElementById('editRetryFailedMax').value) || 1,
            failed_delay: parseInt(document.getElementById('editRetryFailedDelay').value) || 60
        };
        
        try {
            await App.apiPatch(`/campaigns/${id}`, data);
            App.showToast('Кампания обновлена', 'success');
            this.closeEditCampaignModal();
            this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            App.showToast(error.message || 'Ошибка обновления', 'error');
        }
    },

    // =============================================
    // Загрузка аудио для select
    // =============================================
    async loadAudioForSelect(selectId = 'campaignAudioSelect') {
        try {
            const data = await App.apiGet('/audio');
            const files = data.items || data;
            
            const select = document.getElementById(selectId);
            if (select) {
                select.innerHTML = '<option value="">Стандартное приветствие</option>' +
                    files.filter(f => f.format === 'sln' || f.file_path?.endsWith('.sln'))
                        .map(f => `<option value="${f.id}">${f.name}</option>`)
                        .join('');
            }
            
            // Также обновляем select в модалке редактирования
            const editSelect = document.getElementById('editCampaignAudio');
            if (editSelect) {
                editSelect.innerHTML = '<option value="">Стандартное приветствие</option>' +
                    files.filter(f => f.format === 'sln' || f.file_path?.endsWith('.sln'))
                        .map(f => `<option value="${f.id}">${f.name}</option>`)
                        .join('');
            }
            
        } catch (error) {
            console.error('Failed to load audio for select:', error);
        }
    },

    // =============================================
    // Назначение контактов кампании
    // =============================================
    async assignContacts(campaignId, contactIds) {
        try {
            await App.apiPost(`/campaigns/${campaignId}/contacts`, {
                contact_ids: contactIds
            });
            App.showToast(`Назначено ${contactIds.length} контактов`, 'success');
        } catch (error) {
            App.showToast(error.message || 'Ошибка назначения', 'error');
        }
    },

    async assignContactGroups(campaignId, groupIds) {
        try {
            await App.apiPost(`/campaigns/${campaignId}/contact-groups`, {
                group_ids: groupIds
            });
            App.showToast(`Назначены группы контактов`, 'success');
        } catch (error) {
            App.showToast(error.message || 'Ошибка назначения', 'error');
        }
    },

    // =============================================
    // Экспорт/Импорт
    // =============================================
    async exportCampaigns() {
        try {
            const data = await App.apiGet('/campaigns/export');
            App.downloadFile(JSON.stringify(data, null, 2), 'campaigns.json', 'application/json');
        } catch (error) {
            App.showToast('Ошибка экспорта', 'error');
        }
    },

    // =============================================
    // Статистика
    // =============================================
    async loadCampaignStats(campaignId) {
        try {
            return await App.apiGet(`/campaigns/${campaignId}/stats`);
        } catch (error) {
            console.error('Failed to load campaign stats:', error);
            return null;
        }
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.openCampaignModal = () => App.campaigns.openCampaignModal();
window.closeCampaignModal = () => App.campaigns.closeCampaignModal();
window.createCampaign = () => App.campaigns.createCampaign();
window.closeCampaignDetailModal = () => App.campaigns.closeCampaignDetailModal();
