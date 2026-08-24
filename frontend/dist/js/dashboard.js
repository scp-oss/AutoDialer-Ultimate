/**
 * AutoDialer Ultimate - Dashboard Module
 * Version: 3.0.0
 * Главная страница со статистикой и графиками
 */

App.dashboard = {
    // Состояние модуля
    state: {
        stats: {
            totalCalls: 0,
            agreed: 0,
            busy: 0,
            noanswer: 0,
            failed: 0,
            todayCalls: 0,
            conversionRate: 0,
            avgDuration: 0,
            totalDuration: 0
        },
        activeCampaigns: [],
        recentCalls: [],
        chart: null,
        chartPeriod: 'week' // day, week, month
    },

    // =============================================
    // Инициализация
    // =============================================
    async init() {
        // Re-entering this tab replaces #contentContainer's innerHTML, so
        // any previous Chart instance is bound to a canvas element that no
        // longer exists in the DOM - but this.state.chart (on the
        // App.dashboard singleton) still points at it, so loadChart()'s
        // `if (!this.state.chart)` lazy-init guard would wrongly think a
        // chart already exists and skip creating a fresh one. Destroy and
        // clear it up front so that guard re-initializes correctly.
        if (this.state.chart) {
            this.state.chart.destroy();
            this.state.chart = null;
        }

        // loadAll() -> loadChart() already lazily calls initChart() itself
        // when this.state.chart is unset - calling it again here created a
        // SECOND Chart.js instance on the same canvas on every single
        // dashboard load, which Chart.js rejects ("Canvas is already in
        // use. Chart with ID '1' must be destroyed..."), confirmed live.
        await this.loadAll();
        this.setupEventListeners();
    },

    setupEventListeners() {
        // Кнопки периода графика
        document.querySelectorAll('[data-chart-period]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.state.chartPeriod = e.target.dataset.chartPeriod;
                document.querySelectorAll('[data-chart-period]').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.loadChart();
            });
        });

        // Кнопка обновления
        const refreshBtn = document.getElementById('dashboardRefreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refresh());
        }
    },

    // =============================================
    // Загрузка данных
    // =============================================
    async loadAll() {
        try {
            // Параллельная загрузка всех данных
            await Promise.all([
                this.loadStats(),
                this.loadActiveCampaigns(),
                this.loadRecentCalls(),
                this.loadCampaignsSummary(),
                this.loadSystemWidget()
            ]);

            await this.loadChart();

        } catch (error) {
            console.error('Failed to load dashboard data:', error);
            App.showToast('Ошибка загрузки данных дашборда', 'error');
        }
    },

    async refresh() {
        await this.loadAll();
        App.showToast('Данные обновлены', 'info');
    },

    // =============================================
    // Статистика
    // =============================================
    async loadStats() {
        try {
            const data = await App.apiGet('/stats/calls');
            
            this.state.stats = {
                totalCalls: data.total_calls || 0,
                agreed: data.agreed || 0,
                busy: data.busy || 0,
                noanswer: data.noanswer || 0,
                failed: data.failed || 0,
                todayCalls: data.today_calls || 0,
                conversionRate: data.conversion_rate || 0,
                avgDuration: data.avg_duration || 0,
                totalDuration: data.total_duration || 0
            };
            
            this.renderStats();
            
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    },

    renderStats() {
        const stats = this.state.stats;
        
        // Основные карточки
        this.setText('dashTotal', this.formatNumber(stats.totalCalls));
        this.setText('dashAgreed', this.formatNumber(stats.agreed));
        this.setText('dashToday', this.formatNumber(stats.todayCalls));
        this.setText('dashConversion', `${stats.conversionRate}%`);
        
        // Дополнительные карточки (если есть)
        this.setText('dashBusy', this.formatNumber(stats.busy));
        this.setText('dashNoanswer', this.formatNumber(stats.noanswer));
        this.setText('dashFailed', this.formatNumber(stats.failed));
        this.setText('dashAvgDuration', App.formatDuration(stats.avgDuration));
        this.setText('dashTotalDuration', this.formatTotalDuration(stats.totalDuration));
        
        // Расчёт дополнительных метрик
        const answerRate = stats.totalCalls > 0 
            ? ((stats.agreed / stats.totalCalls) * 100).toFixed(1) 
            : 0;
        this.setText('dashAnswerRate', `${answerRate}%`);
    },

    // =============================================
    // Активные кампании
    // =============================================
    async loadActiveCampaigns() {
        try {
            const data = await App.apiGet('/campaigns/?status=running&limit=10');
            this.state.activeCampaigns = data.items || data || [];
            this.renderActiveCampaigns();
        } catch (error) {
            console.error('Failed to load active campaigns:', error);
            this.renderActiveCampaignsEmpty();
        }
    },

    renderActiveCampaigns() {
        const container = document.getElementById('activeCampaignsList');
        if (!container) return;
        
        const campaigns = this.state.activeCampaigns;
        
        if (!campaigns || campaigns.length === 0) {
            this.renderActiveCampaignsEmpty();
            return;
        }
        
        container.innerHTML = campaigns.map(c => {
            const progress = c.stats?.progress_percent || 0;
            const called = c.stats?.called_contacts || 0;
            const total = c.stats?.total_contacts || 0;
            const conversion = c.stats?.conversion_rate || 0;
            
            return `
                <div class="campaign-item" onclick="App.campaigns?.viewCampaignDetail(${c.id})">
                    <div class="campaign-info">
                        <div>
                            <strong>${this.escapeHtml(c.name)}</strong>
                            <span class="status-badge status-${c.status}">${this.getStatusText(c.status)}</span>
                        </div>
                        <div class="campaign-stats">
                            <span>📞 ${called}/${total}</span>
                            <span>✅ ${conversion}%</span>
                        </div>
                    </div>
                    <div class="progress-bar" style="margin-top: 8px;">
                        <div class="progress-fill" style="width: ${progress}%"></div>
                    </div>
                    <div class="campaign-actions">
                        ${c.status === 'running' ? `
                            <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); App.campaigns?.pauseCampaign(${c.id})" title="Пауза">⏸️</button>
                            <button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation(); App.campaigns?.stopCampaign(${c.id})" title="Остановить">⏹️</button>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');
    },

    renderActiveCampaignsEmpty() {
        const container = document.getElementById('activeCampaignsList');
        if (container) {
            container.innerHTML = `
                <div class="loading">
                    <p>Нет активных кампаний</p>
                    <button class="btn btn-primary btn-sm" onclick="App.switchTab('campaigns')">
                        Перейти к кампаниям
                    </button>
                </div>
            `;
        }
    },

    // =============================================
    // Последние звонки
    // =============================================
    async loadRecentCalls() {
        try {
            // /api/history doesn't exist - the endpoint is registered
            // under the /calls router as /calls/history (app/api/calls.py)
            const data = await App.apiGet('/calls/history?limit=10');
            this.state.recentCalls = data.items || data.history || data || [];
            this.renderRecentCalls();
        } catch (error) {
            console.error('Failed to load recent calls:', error);
            this.renderRecentCallsEmpty();
        }
    },

    renderRecentCalls() {
        const container = document.getElementById('recentCalls');
        if (!container) return;
        
        const calls = this.state.recentCalls;
        
        if (!calls || calls.length === 0) {
            this.renderRecentCallsEmpty();
            return;
        }
        
        container.innerHTML = calls.map(call => `
            <div class="call-item" onclick="App.history?.showCallDetails(${call.id})">
                <span class="call-time">${this.formatTime(call.created_at)}</span>
                <span class="call-phone">${this.formatPhone(call.phone || call.to_number)}</span>
                <span class="status-badge status-${call.status}">${this.getCallStatusText(call.status)}</span>
                <span class="call-campaign">${this.escapeHtml(call.campaign_name || '—')}</span>
                ${call.direction === 'inbound' ? '<span class="badge badge-info">Вх.</span>' : ''}
            </div>
        `).join('');
    },

    renderRecentCallsEmpty() {
        const container = document.getElementById('recentCalls');
        if (container) {
            container.innerHTML = '<div class="loading">Нет звонков</div>';
        }
    },

    // =============================================
    // График
    // =============================================
    initChart() {
        const canvas = document.getElementById('statsChart');
        if (!canvas) return;

        // Defensive: destroy any chart still attached before creating a
        // new one, regardless of call path.
        if (this.state.chart) {
            this.state.chart.destroy();
            this.state.chart = null;
        }

        const ctx = canvas.getContext('2d');
        
        this.state.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Всего звонков',
                        data: [],
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Согласий',
                        data: [],
                        borderColor: '#10b981',
                        backgroundColor: 'transparent',
                        tension: 0.4
                    },
                    {
                        label: 'Нет ответа',
                        data: [],
                        borderColor: '#f59e0b',
                        backgroundColor: 'transparent',
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: '#f1f5f9' }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: '#334155' }
                    },
                    y: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: '#334155' },
                        beginAtZero: true
                    }
                }
            }
        });
    },

    async loadChart() {
        if (!this.state.chart) {
            this.initChart();
        }
        
        try {
            // /api/stats/chart doesn't exist anywhere in the backend -
            // the real endpoint is /stats/calls/daily (app/api/calls.py,
            // stats_router), takes `days` (int), not `period` (string),
            // and returns a plain JSON array of DailyCallStatsResponse
            // (date/total/agreed/noanswer/... - exactly what this
            // function already reads below).
            const daysByPeriod = { day: 1, week: 7, month: 30 };
            const days = daysByPeriod[this.state.chartPeriod] || 7;
            const data = await App.apiGet(`/stats/calls/daily?days=${days}`);
            const chartData = data.daily || data || [];
            
            if (chartData.length === 0) {
                return;
            }
            
            // Сортируем по дате
            chartData.sort((a, b) => new Date(a.date) - new Date(b.date));

            const labels = chartData.map(d => this.formatChartDate(d.date));
            const totals = chartData.map(d => d.total || 0);
            const agreed = chartData.map(d => d.agreed || 0);
            const noanswer = chartData.map(d => d.noanswer || 0);

            // initChart() can silently no-op (canvas gone) if the user
            // switched away from the dashboard tab while this was in
            // flight - guard rather than crash on a null chart.
            if (!this.state.chart) return;

            this.state.chart.data.labels = labels;
            this.state.chart.data.datasets[0].data = totals;
            this.state.chart.data.datasets[1].data = agreed;
            this.state.chart.data.datasets[2].data = noanswer;
            
            this.state.chart.update();
            
        } catch (error) {
            console.error('Failed to load chart data:', error);
            this.loadMockChartData();
        }
    },

    loadMockChartData() {
        if (!this.state.chart) return;

        // Заглушка если API не отдаёт данные для графика
        const labels = [];
        const totals = [];
        const agreed = [];
        const noanswer = [];
        
        const today = new Date();
        for (let i = 6; i >= 0; i--) {
            const date = new Date(today);
            date.setDate(date.getDate() - i);
            labels.push(date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }));
            totals.push(Math.floor(Math.random() * 500) + 200);
            agreed.push(Math.floor(Math.random() * 100) + 50);
            noanswer.push(Math.floor(Math.random() * 150) + 50);
        }
        
        this.state.chart.data.labels = labels;
        this.state.chart.data.datasets[0].data = totals;
        this.state.chart.data.datasets[1].data = agreed;
        this.state.chart.data.datasets[2].data = noanswer;
        this.state.chart.update();
    },

    // =============================================
    // Быстрые действия
    // =============================================
    async quickCall() {
        const phone = prompt('Введите номер для быстрого звонка:');
        if (!phone) return;
        
        if (!App.validatePhone(phone)) {
            App.showToast('Неверный формат номера', 'warning');
            return;
        }
        
        await App.system.testCall(phone);
    },

    quickCampaign() {
        App.switchTab('campaigns');
        setTimeout(() => App.campaigns?.openCampaignModal(), 100);
    },

    quickImport() {
        App.switchTab('contacts');
        setTimeout(() => {
            const importBtn = document.querySelector('[onclick*="importContacts"]');
            if (importBtn) importBtn.click();
        }, 100);
    },

    // =============================================
    // Сводка по кампаниям
    // =============================================
    async loadCampaignsSummary() {
        try {
            const data = await App.apiGet('/campaigns/summary');
            const container = document.getElementById('campaignsSummary');
            if (container && data) {
                container.innerHTML = `
                    <div class="summary-item">
                        <span>Всего кампаний</span>
                        <strong>${data.total || 0}</strong>
                    </div>
                    <div class="summary-item">
                        <span>Активных</span>
                        <strong style="color: var(--color-success);">${data.running || 0}</strong>
                    </div>
                    <div class="summary-item">
                        <span>Завершено</span>
                        <strong>${data.completed || 0}</strong>
                    </div>
                    <div class="summary-item">
                        <span>Черновиков</span>
                        <strong style="color: var(--color-text-muted);">${data.draft || 0}</strong>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Failed to load campaigns summary:', error);
        }
    },

    // =============================================
    // Системная информация (виджет)
    // =============================================
    async loadSystemWidget() {
        try {
            // Состояние (asteriskConnected/redisConnected/databaseConnected/
            // cpuUsage/memoryUsage/uptime/version) уже приходит из
            // App.system.state, которое заполняет refreshStatus() одним
            // запросом на /system/status - отдельные вызовы getHealth()/
            // getSystemInfo() тут были лишними (и второй вообще дёргал
            // несуществующий /system/info, который всегда 404-ил).
            await App.system.refreshStatus();

            const container = document.getElementById('systemWidget');
            if (!container) return;
            
            container.innerHTML = `
                <div class="system-widget">
                    <h4>Состояние системы</h4>
                    <div class="system-status-grid">
                        <div class="status-item">
                            <span>Asterisk</span>
                            <span id="asteriskStatus">${App.system.state.asteriskConnected ? '✅' : '❌'}</span>
                        </div>
                        <div class="status-item">
                            <span>Redis</span>
                            <span id="redisStatus">${App.system.state.redisConnected ? '✅' : '❌'}</span>
                        </div>
                        <div class="status-item">
                            <span>База данных</span>
                            <span id="dbStatus">${App.system.state.databaseConnected ? '✅' : '❌'}</span>
                        </div>
                        <div class="status-item">
                            <span>Аптайм</span>
                            <span>${App.system.getUptimeFormatted()}</span>
                        </div>
                        <div class="status-item">
                            <span>CPU</span>
                            <span>${App.system.state.cpuUsage.toFixed(1)}%</span>
                        </div>
                        <div class="status-item">
                            <span>Память</span>
                            <span>${App.system.state.memoryUsage.toFixed(1)}%</span>
                        </div>
                    </div>
                    <div class="system-info">
                        <small>Версия: ${App.system.state.version || '—'}</small>
                    </div>
                </div>
            `;
        } catch (error) {
            console.error('Failed to load system widget:', error);
        }
    },

    // =============================================
    // Утилиты
    // =============================================
    setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    },

    formatNumber(num) {
        if (num === null || num === undefined) return '0';
        return num.toLocaleString('ru-RU');
    },

    formatTotalDuration(seconds) {
        if (!seconds) return '0 ч';
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (hours > 0) {
            return `${hours} ч ${minutes} мин`;
        }
        return `${minutes} мин`;
    },

    formatTime(isoString) {
        if (!isoString) return '—';
        const date = App.parseServerDate(isoString);
        return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    },

    formatPhone(phone) {
        return App.formatPhoneNumber(phone);
    },

    formatChartDate(dateStr) {
        const date = new Date(dateStr);
        if (this.state.chartPeriod === 'month') {
            return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
        } else if (this.state.chartPeriod === 'year') {
            return date.toLocaleDateString('ru-RU', { month: 'short' });
        }
        return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    },

    getStatusText(status) {
        const map = {
            'draft': 'Черновик',
            'running': 'Запущена',
            'paused': 'Приостановлена',
            'stopped': 'Остановлена',
            'completed': 'Завершена',
            'failed': 'Ошибка'
        };
        return map[status] || status;
    },

    getCallStatusText(status) {
        const map = {
            'completed': 'Завершен',
            'answered': 'Отвечен',
            'no_answer': 'Нет ответа',
            'busy': 'Занято',
            'failed': 'Ошибка',
            'cancelled': 'Отменен'
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
        if (this.state.chart) {
            this.state.chart.destroy();
            this.state.chart = null;
        }
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.quickCall = () => App.dashboard.quickCall();
window.quickCampaign = () => App.dashboard.quickCampaign();
window.quickImport = () => App.dashboard.quickImport();
