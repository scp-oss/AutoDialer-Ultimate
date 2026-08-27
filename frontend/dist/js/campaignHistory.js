/**
 * AutoDialer Ultimate - Campaign History Module
 * Version: 3.0.0
 * Отдельная read-only вкладка "История обзвонов" - список прошлых (и
 * текущих) запусков обзвона без функций управления/создания (это есть
 * на вкладке "Обзвон"), с тем же drill-down в детали через уже
 * существующую App.campaigns.viewCampaignDetail() - показывает статус,
 * во сколько дозвонились до каждого номера, и т.д.
 */

App.campaignHistory = {
    state: {
        campaigns: [],
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
            tbody.innerHTML = '<tr><td colspan="8" class="text-center"><div class="loading">Загрузка...</div></td></tr>';
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

            const data = await App.apiGet(`/campaigns/?${params.toString()}`);
            this.state.campaigns = data.items || data || [];
            this.state.totalPages = data.total_pages || 1;

            this.renderTable();
            App.renderPagination('campaignHistoryPagination', page, this.state.totalPages, 'App.campaignHistory.load');

        } catch (error) {
            console.error('Failed to load campaign history:', error);
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
            App.showToast('Ошибка загрузки истории обзвонов', 'error');
        }
    },

    renderTable() {
        const tbody = document.getElementById('campaignHistoryTableBody');
        if (!tbody) return;

        const campaigns = this.state.campaigns;

        if (!campaigns || campaigns.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">🗂️</div>
                            <p>История обзвонов пока пуста</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = campaigns.map(c => this.rowHtml(c)).join('');
    },

    rowHtml(c) {
        const processed = c.stats?.processed_contacts || 0;
        const total = c.stats?.total_contacts || 0;
        const progress = c.stats?.progress_percent || 0;
        const conversion = c.stats?.conversion_rate || 0;
        const finishedAt = c.completed_at || c.stopped_at || null;

        return `
            <tr class="campaign-row" style="cursor: pointer;" onclick="App.campaigns.viewCampaignDetail(${c.id})">
                <td>${c.id}</td>
                <td>
                    <strong>${App.campaigns.escapeHtml(c.name)}</strong>
                    ${c.description ? `<br><small>${App.campaigns.escapeHtml(c.description)}</small>` : ''}
                </td>
                <td>
                    <span class="status-badge status-${c.status}">${App.campaigns.getStatusText(c.status)}</span>
                </td>
                <td>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: 80px;">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <span class="progress-text">${processed}/${total}</span>
                    </div>
                </td>
                <td>
                    <span class="${conversion > 0 ? 'text-success' : ''}">${conversion}%</span>
                </td>
                <td>${c.started_at ? App.formatDateTime(c.started_at) : '—'}</td>
                <td>${finishedAt ? App.formatDateTime(finishedAt) : '—'}</td>
                <td class="actions-cell">
                    <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); App.campaigns.viewCampaignDetail(${c.id})" title="Просмотр">
                        👁️
                    </button>
                </td>
            </tr>
        `;
    }
};
