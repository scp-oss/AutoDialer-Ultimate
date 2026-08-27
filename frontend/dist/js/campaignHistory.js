/**
 * AutoDialer Ultimate - Campaign History Module
 * Version: 3.0.0
 * Отдельная read-only вкладка "История обзвонов" - одна строка на
 * КАЖДЫЙ запуск обзвона (GET /campaigns/runs, campaign_runs в БД), а не
 * на кампанию, так что "Запустить снова" на вкладке "Обзвон" видно как
 * отдельную запись со своим временем начала/конца и своей статистикой.
 */

App.campaignHistory = {
    state: {
        runs: [],
        currentPage: 1,
        totalPages: 1,
        pageSize: 20
    },

    async init() {
        this.setupEventListeners();
        await this.load();
    },

    setupEventListeners() {
        document.getElementById('campaignHistoryRefreshBtn')
            ?.addEventListener('click', () => this.load(this.state.currentPage));
        document.getElementById('campaignHistorySearch')
            ?.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.load(1);
            });
    },

    async load(page = 1) {
        this.state.currentPage = page;

        const tbody = document.getElementById('campaignHistoryTableBody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center"><div class="loading">Загрузка...</div></td></tr>';
        }

        try {
            const search = document.getElementById('campaignHistorySearch')?.value?.trim() || '';
            const status = document.getElementById('campaignHistoryStatusFilter')?.value || '';

            const params = new URLSearchParams({
                page: page,
                page_size: this.state.pageSize
            });
            if (search) params.set('search', search);
            if (status) params.set('status', status);

            const data = await App.apiGet(`/campaigns/runs?${params.toString()}`);
            this.state.runs = data.items || data || [];
            this.state.totalPages = data.total_pages || 1;

            this.renderTable();
            App.renderPagination('campaignHistoryPagination', page, this.state.totalPages, 'App.campaignHistory.load');

        } catch (error) {
            console.error('Failed to load campaign history:', error);
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
            App.showToast('Ошибка загрузки истории обзвонов', 'error');
        }
    },

    renderTable() {
        const tbody = document.getElementById('campaignHistoryTableBody');
        if (!tbody) return;

        const runs = this.state.runs;

        if (!runs || runs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">🗂️</div>
                            <p>Ещё не было ни одного запуска обзвона</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = runs.map(r => this.rowHtml(r)).join('');
    },

    rowHtml(r) {
        const processed = r.processed_contacts || 0;
        const total = r.total_contacts || 0;
        const progress = r.progress_percent || 0;

        return `
            <tr class="campaign-row" style="cursor: pointer;" onclick="App.campaignHistory.viewRunDetail(${r.id})">
                <td>${r.id}</td>
                <td><strong>${App.campaigns.escapeHtml(r.campaign_name)}</strong></td>
                <td>
                    <span class="status-badge status-${r.status}">${App.campaigns.getStatusText(r.status)}</span>
                </td>
                <td>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: 80px;">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <span class="progress-text">${processed}/${total}</span>
                    </div>
                </td>
                <td>${r.started_at ? App.formatDateTime(r.started_at) : '—'}</td>
                <td>${r.completed_at ? App.formatDateTime(r.completed_at) : '—'}</td>
                <td class="actions-cell">
                    <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); App.campaignHistory.viewRunDetail(${r.id})" title="Просмотр">
                        👁️
                    </button>
                </td>
            </tr>
        `;
    },

    // =============================================
    // Детали одного запуска
    // =============================================
    async viewRunDetail(id) {
        try {
            const run = await App.apiGet(`/campaigns/runs/${id}`);

            const modal = document.getElementById('runDetailModal');
            const title = document.getElementById('runDetailTitle');
            const content = document.getElementById('runDetailContent');
            if (!modal || !content) return;

            title.textContent = `${run.campaign_name} — запуск #${run.id}`;

            content.innerHTML = `
                <div class="detail-section">
                    <h4>Информация о запуске</h4>
                    <table class="details-table">
                        <tr><td>Обзвон:</td><td>${App.campaigns.escapeHtml(run.campaign_name)}</td></tr>
                        <tr><td>Статус:</td><td><span class="status-badge status-${run.status}">${App.campaigns.getStatusText(run.status)}</span></td></tr>
                        <tr><td>Запущен:</td><td>${App.formatDateTime(run.started_at)}</td></tr>
                        <tr><td>Завершён:</td><td>${run.completed_at ? App.formatDateTime(run.completed_at) : '—'}</td></tr>
                        <tr><td>Обзвонено:</td><td>${run.processed_contacts}/${run.total_contacts} (${run.progress_percent}%)</td></tr>
                    </table>
                </div>
                <div class="detail-section">
                    <h4>Звонки в этом запуске</h4>
                    ${(run.calls && run.calls.length) ? `
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>Номер</th>
                                    <th>Контакт</th>
                                    <th>Статус</th>
                                    <th>Длит.</th>
                                    <th>Дата/время</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${run.calls.map(call => `
                                    <tr>
                                        <td>${App.campaigns.formatPhone(call.phone)}</td>
                                        <td>${App.campaigns.escapeHtml(call.contact_name || '—')}</td>
                                        <td><span class="status-badge status-${call.status}">${App.campaigns.getCallStatusText(call.status)}</span></td>
                                        <td>${App.formatDuration(call.duration)}</td>
                                        <td>${App.formatDateTime(call.created_at)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    ` : '<p class="text-muted">Звонков в этом запуске пока нет</p>'}
                </div>
            `;

            modal.style.display = 'flex';

        } catch (error) {
            console.error('Failed to load run detail:', error);
            App.showToast('Ошибка загрузки деталей запуска', 'error');
        }
    },

    closeRunDetailModal() {
        const modal = document.getElementById('runDetailModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }
};
