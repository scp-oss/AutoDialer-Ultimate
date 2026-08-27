// history.js - Модуль истории звонков
// Зависимости: app.js (App.apiGet, App.showModal/hideModal, App.showToast, ...)

const HistoryModule = {
    currentPage: 1,
    pageSize: 20,
    sortField: 'created_at',
    sortOrder: 'desc',
    currentCallId: null,

    // Статусы, реально возвращаемые бэкендом (CallResultStatus в
    // app/models/call.py, те же значения пишет диалплан в
    // UserEvent(DialerResult,...)). Раньше здесь были придуманные значения
    // ('completed', 'no_answer', 'cancelled' и т.п.), которых не существует
    // ни в этом enum'е, ни в диалплане - фильтр по статусу либо ничего не
    // находил, либо получал 422 от FastAPI на значении, которого нет в enum.
    // agreed/timeout переименованы под смысл "подтвердил прослушивание /
    // прослушал» вместо «согласился на предложение" - технический код
    // статуса (enum-значение "agreed"/"timeout" в БД и в диалплане) не
    // менялся, поменялась только подпись, которую видит оператор.
    STATUS_LABELS: {
        agreed: 'Подтвердил (нажал 1)',
        declined: 'Отказался',
        busy: 'Занято',
        noanswer: 'Нет ответа',
        failed: 'Ошибка',
        timeout: 'Прослушал, не подтвердил',
        announced: 'Объявление проиграно',
        canceled: 'Отменён',
        machine: 'Автоответчик',
        congestion: 'Перегрузка',
        chanunavail: 'Канал недоступен',
        unknown: 'Неизвестно'
    },

    // Инициализация вкладки (вызывается из App.switchTab через
    // App.history.init(), см. app.js)
    async init() {
        await this.loadCampaignsForFilter();
        this.setupFilterEvents();
        await this.load(1);
    },

    setupFilterEvents() {
        document.getElementById('historyRefreshBtn')
            ?.addEventListener('click', () => this.load(this.currentPage));
        document.getElementById('historyApplyFiltersBtn')
            ?.addEventListener('click', () => this.applyFilters());
        document.getElementById('historyResetFiltersBtn')
            ?.addEventListener('click', () => this.resetFilters());
        document.getElementById('historyFilterPhone')
            ?.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.applyFilters();
            });
        document.getElementById('historyDownloadDetailBtn')
            ?.addEventListener('click', () => {
                if (this.currentCallId) this.downloadCallDetails(this.currentCallId);
            });

        // Сортировка по клику на заголовок - сервер (list_calls в
        // app/api/calls.py) не принимает sort_by/sort_order как параметры
        // запроса (сервис строит ORDER BY через f-string без валидации, так
        // что открывать это поле на приём произвольного значения с фронта -
        // SQL injection), так что клик только переключает иконку и
        // перезагружает текущую страницу в стандартном порядке.
        document.querySelectorAll('.history-table .sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                this.sortOrder = (this.sortField === field && this.sortOrder === 'asc') ? 'desc' : 'asc';
                this.sortField = field;
                this.updateSortIcons();
                this.load(1);
            });
        });
    },

    updateSortIcons() {
        document.querySelectorAll('.history-table .sortable').forEach(th => {
            const icon = th.querySelector('.sort-icon');
            if (!icon) return;
            icon.textContent = th.dataset.sort === this.sortField
                ? (this.sortOrder === 'asc' ? '⬆️' : '⬇️')
                : '↕️';
        });
    },

    async loadCampaignsForFilter() {
        try {
            const data = await App.apiGet('/campaigns?limit=100');
            const campaigns = data.items || data || [];
            const select = document.getElementById('historyFilterCampaign');
            if (select) {
                select.innerHTML = '<option value="">Все обзвоны</option>' +
                    campaigns.map(c => `<option value="${c.id}">${this.escapeHtml(c.name)}</option>`).join('');
            }
        } catch (error) {
            console.error('Failed to load campaigns for filter:', error);
        }
    },

    // Загрузка истории
    async load(page = 1) {
        this.currentPage = page;

        const campaignId = document.getElementById('historyFilterCampaign')?.value;
        const status = document.getElementById('historyFilterStatus')?.value;
        const direction = document.getElementById('historyFilterDirection')?.value;
        const phone = document.getElementById('historyFilterPhone')?.value;
        const dateFrom = document.getElementById('historyFilterDateFrom')?.value;
        const dateTo = document.getElementById('historyFilterDateTo')?.value;

        // Роутер звонков в app/api/calls.py смонтирован с префиксом
        // "/calls" (см. app/api/__init__.py), а сам маршрут списка объявлен
        // как "/history" - т.е. реальный путь "/calls/history", а не
        // "/history" - раньше здесь был ровно этот несуществующий путь,
        // каждый запрос ловил 404 и история всегда показывала "Нет записей".
        let url = `/calls/history?page=${page}&page_size=${this.pageSize}`;
        if (campaignId) url += `&campaign_id=${campaignId}`;
        if (status) url += `&status=${status}`;
        if (direction) url += `&direction=${direction}`;
        if (phone) url += `&phone=${encodeURIComponent(phone)}`;
        // <input type="datetime-local"> отдаёт "YYYY-MM-DDTHH:MM", бэкенд
        // (DateRangeParams) парсит from_date/to_date строго как "YYYY-MM-DD".
        if (dateFrom) url += `&from_date=${dateFrom.slice(0, 10)}`;
        if (dateTo) url += `&to_date=${dateTo.slice(0, 10)}`;

        const tbody = document.getElementById('historyTableBody');
        try {
            const data = await App.apiGet(url);
            this.renderTable(data.items || []);
            this.renderPagination(data.total_pages || 1);
            this.updateStats(data);
        } catch (error) {
            console.error('History load failed:', error);
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        }
    },

    applyFilters() {
        this.currentPage = 1;
        this.load(1);
    },

    resetFilters() {
        const ids = ['historyFilterCampaign', 'historyFilterStatus', 'historyFilterDirection',
                      'historyFilterPhone', 'historyFilterDateFrom', 'historyFilterDateTo'];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        this.currentPage = 1;
        this.load(1);
    },

    // Рендер таблицы
    renderTable(calls) {
        const tbody = document.getElementById('historyTableBody');
        if (!tbody) return;

        if (!calls || calls.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center">Нет записей</td></tr>';
            return;
        }

        tbody.innerHTML = calls.map(call => `
            <tr data-call-id="${call.id}" class="history-row ${call.status}">
                <td>${App.formatDateTime(call.created_at)}</td>
                <td>
                    <span class="phone-number">${App.formatPhoneNumber(call.phone)}</span>
                    ${call.direction === 'inbound' ? '<span class="direction-badge inbound">Вх.</span>' : ''}
                </td>
                <td>${this.escapeHtml(call.contact_name || '—')}</td>
                <td>${this.escapeHtml(call.campaign_name || '—')}</td>
                <td>
                    <span class="status-badge status-${call.status}">
                        ${this.STATUS_LABELS[call.status] || call.status}
                    </span>
                </td>
                <td>${call.dtmf_result || '—'}</td>
                <td>${call.duration_formatted || App.formatDuration(call.duration)}</td>
                <td class="actions-cell">
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline view-details"
                                data-id="${call.id}"
                                title="Подробнее">👁️</button>
                        ${call.recording_url ? `
                            <button class="btn btn-sm btn-outline play-recording"
                                    data-url="${call.recording_url}"
                                    title="Прослушать запись">🔊</button>
                        ` : ''}
                        <button class="btn btn-sm btn-outline download-call"
                                data-id="${call.id}"
                                title="Скачать детали">📥</button>
                    </div>
                </td>
            </tr>
        `).join('');

        this.attachRowEventListeners();
    },

    attachRowEventListeners() {
        document.querySelectorAll('.history-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('a')) return;
                this.showCallDetails(row.dataset.callId);
            });
        });

        document.querySelectorAll('.view-details').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showCallDetails(btn.dataset.id);
            });
        });

        document.querySelectorAll('.play-recording').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.playRecording(btn.dataset.url);
            });
        });

        document.querySelectorAll('.download-call').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.downloadCallDetails(btn.dataset.id);
            });
        });
    },

    // Показать детали звонка
    async showCallDetails(callId) {
        this.currentCallId = callId;
        const content = document.getElementById('historyDetailContent');
        App.showModal('historyDetailModal');
        if (content) content.innerHTML = '<div class="loading">Загрузка...</div>';

        try {
            const call = await App.apiGet(`/calls/${callId}`);

            const modalContent = `
                <div class="call-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID звонка:</td><td>${call.id}</td></tr>
                            <tr><td>Дата/время:</td><td>${App.formatDateTime(call.created_at)}</td></tr>
                            <tr><td>Номер:</td><td>${App.formatPhoneNumber(call.phone)}</td></tr>
                            <tr><td>Контакт:</td><td>${this.escapeHtml(call.contact_name || '—')}</td></tr>
                            <tr><td>Обзвон:</td><td>${this.escapeHtml(call.campaign_name || '—')}</td></tr>
                            <tr><td>Статус:</td><td><span class="status-badge status-${call.status}">${this.STATUS_LABELS[call.status] || call.status}</span></td></tr>
                            <tr><td>Длительность:</td><td>${call.duration_formatted || App.formatDuration(call.duration)}</td></tr>
                            <tr><td>DTMF:</td><td>${call.dtmf_result || '—'}</td></tr>
                            <tr><td>Причина завершения:</td><td>${call.hangup_cause || '—'}</td></tr>
                            <tr><td>Попытка №:</td><td>${call.retry_count}</td></tr>
                        </table>
                    </div>

                    ${call.recording_url ? `
                        <div class="detail-section">
                            <h4>Запись разговора</h4>
                            <audio controls src="${call.recording_url}" class="audio-player"></audio>
                            <br>
                            <a href="${call.recording_url}" download class="btn btn-sm btn-primary" style="margin-top: 10px;">
                                📥 Скачать запись
                            </a>
                        </div>
                    ` : ''}

                    ${call.transcription ? `
                        <div class="detail-section">
                            <h4>Транскрипция</h4>
                            <div class="transcription-box">${this.escapeHtml(call.transcription)}</div>
                        </div>
                    ` : ''}

                    ${call.notes ? `
                        <div class="detail-section">
                            <h4>Примечания</h4>
                            <p>${this.escapeHtml(call.notes)}</p>
                        </div>
                    ` : ''}
                </div>
            `;

            if (content) content.innerHTML = modalContent;

        } catch (error) {
            console.error('Failed to load call details:', error);
            if (content) content.innerHTML = '<div class="error-message">Не удалось загрузить детали звонка</div>';
        }
    },

    closeDetailModal() {
        App.hideModal('historyDetailModal');
    },

    // Воспроизведение записи
    playRecording(url) {
        const audio = new Audio(url);
        const modalContent = `
            <div class="audio-player-container">
                <audio controls autoplay src="${url}" style="width: 100%;"></audio>
            </div>
        `;
        // Переиспользуем модалку деталей звонка под плеер, чтобы не плодить
        // ещё один динамически создаваемый modal с собственной разметкой.
        const content = document.getElementById('historyDetailContent');
        if (content) content.innerHTML = modalContent;
        App.showModal('historyDetailModal');

        audio.play().catch(e => {
            console.error('Audio playback failed:', e);
            App.showToast('Ошибка воспроизведения', 'error');
        });
    },

    // Скачать детали звонка (JSON)
    async downloadCallDetails(callId) {
        try {
            const call = await App.apiGet(`/calls/${callId}`);
            const dataStr = JSON.stringify(call, null, 2);
            const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);

            const linkElement = document.createElement('a');
            linkElement.setAttribute('href', dataUri);
            linkElement.setAttribute('download', `call_${callId}_${new Date().toISOString().split('T')[0]}.json`);
            linkElement.click();

            App.showToast('Детали звонка скачаны', 'success');
        } catch (error) {
            console.error('Download failed:', error);
            App.showToast('Не удалось скачать детали', 'error');
        }
    },

    // Экспорт в CSV - бэкенд не предоставляет отдельный эндпоинт экспорта
    // (в app/api/calls.py такого маршрута нет), поэтому строим CSV из уже
    // доступного списка звонков на клиенте, а не бьёмся в несуществующий
    // "/calls/export" на каждый клик.
    async exportToCSV() {
        App.showToast('Подготовка экспорта...', 'info');
        try {
            const data = await App.apiGet('/calls/history?page=1&page_size=10000');
            const calls = data.items || [];

            if (!calls.length) {
                App.showToast('Нет данных для экспорта', 'warning');
                return;
            }

            const headers = ['ID', 'Дата/время', 'Номер', 'Контакт', 'Обзвон', 'Статус', 'DTMF', 'Длительность'];
            const rows = calls.map(call => [
                call.id,
                App.formatDateTime(call.created_at),
                call.phone,
                call.contact_name || '',
                call.campaign_name || '',
                this.STATUS_LABELS[call.status] || call.status,
                call.dtmf_result || '',
                call.duration || 0
            ]);

            const csvContent = [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
            ].join('\n');

            const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `calls_export_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            window.URL.revokeObjectURL(url);

            App.showToast(`Экспортировано ${calls.length} записей`, 'success');
        } catch (error) {
            console.error('Export failed:', error);
            App.showToast('Не удалось выполнить экспорт', 'error');
        }
    },

    // Показать статистику - использует /api/stats/calls (см.
    // stats_router в app/api/calls.py), а не несуществующий
    // "/calls/statistics"; поля ответа - CallStatsResponse
    // (total_calls/answered_calls/noanswer/... ), не "total"/"no_answer".
    async showStatistics() {
        const content = document.getElementById('historyStatsContent');
        App.showModal('historyStatsModal');
        if (content) content.innerHTML = '<div class="loading">Загрузка статистики...</div>';

        try {
            const stats = await App.apiGet('/stats/calls');

            if (content) {
                content.innerHTML = `
                    <div class="statistics-panel">
                        <div class="stats-grid-large">
                            <div class="stat-card-large">
                                <div class="stat-value">${stats.total_calls || 0}</div>
                                <div class="stat-label">Всего звонков</div>
                            </div>
                            <div class="stat-card-large stat-success">
                                <div class="stat-value">${stats.answered_calls || 0}</div>
                                <div class="stat-label">Отвечено</div>
                            </div>
                            <div class="stat-card-large">
                                <div class="stat-value">${stats.answer_rate || 0}%</div>
                                <div class="stat-label">Дозвон</div>
                            </div>
                            <div class="stat-card-large stat-warning">
                                <div class="stat-value">${stats.noanswer || 0}</div>
                                <div class="stat-label">Нет ответа</div>
                            </div>
                            <div class="stat-card-large stat-danger">
                                <div class="stat-value">${stats.busy || 0}</div>
                                <div class="stat-label">Занято</div>
                            </div>
                            <div class="stat-card-large">
                                <div class="stat-value">${App.formatDuration(Math.round(stats.avg_duration || 0))}</div>
                                <div class="stat-label">Ср. длительность</div>
                            </div>
                            <div class="stat-card-large stat-success">
                                <div class="stat-value">${stats.agreed || 0}</div>
                                <div class="stat-label">Подтвердили прослушивание</div>
                            </div>
                            <div class="stat-card-large">
                                <div class="stat-value">${stats.machine || 0}</div>
                                <div class="stat-label">Автоответчик</div>
                            </div>
                            <div class="stat-card-large">
                                <div class="stat-value">${stats.conversion_rate || 0}%</div>
                                <div class="stat-label">Конверсия</div>
                            </div>
                        </div>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Failed to load statistics:', error);
            if (content) content.innerHTML = '<div class="error-message">Ошибка загрузки статистики</div>';
        }
    },

    // Обновление мини-статистики в шапке. CallListResponse (см.
    // app/models/call.py) не содержит поле "stats" - есть только
    // total/summary (агрегат по статусам для ТЕКУЩЕЙ страницы фильтров).
    updateStats(data) {
        const totalEl = document.getElementById('historyTotalCalls');
        const answeredEl = document.getElementById('historyAnswered');
        const conversionEl = document.getElementById('historyConversion');
        const avgDurationEl = document.getElementById('historyAvgDuration');

        const total = data.total || 0;
        const summary = data.summary || {};
        const answered = (summary.agreed || 0) + (summary.declined || 0);

        if (totalEl) totalEl.textContent = total;
        if (answeredEl) answeredEl.textContent = answered;
        if (conversionEl) conversionEl.textContent = total > 0 ? `${Math.round(answered / total * 100)}%` : '0%';

        if (avgDurationEl) {
            const durations = (data.items || []).map(c => c.duration).filter(d => d);
            const avg = durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0;
            avgDurationEl.textContent = App.formatDuration(avg);
        }
    },

    // Рендер пагинации
    renderPagination(totalPages) {
        const container = document.getElementById('historyPagination');
        if (!container) return;

        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        let html = '<div class="pagination">';

        html += this.currentPage > 1
            ? `<button class="page-btn" data-page="${this.currentPage - 1}">←</button>`
            : `<button class="page-btn" disabled>←</button>`;

        const start = Math.max(1, this.currentPage - 2);
        const end = Math.min(totalPages, this.currentPage + 2);

        if (start > 1) {
            html += `<button class="page-btn" data-page="1">1</button>`;
            if (start > 2) html += '<span class="page-dots">...</span>';
        }

        for (let i = start; i <= end; i++) {
            html += `<button class="page-btn ${i === this.currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }

        if (end < totalPages) {
            if (end < totalPages - 1) html += '<span class="page-dots">...</span>';
            html += `<button class="page-btn" data-page="${totalPages}">${totalPages}</button>`;
        }

        html += this.currentPage < totalPages
            ? `<button class="page-btn" data-page="${this.currentPage + 1}">→</button>`
            : `<button class="page-btn" disabled>→</button>`;

        html += '</div>';
        container.innerHTML = html;

        container.querySelectorAll('.page-btn[data-page]').forEach(btn => {
            btn.addEventListener('click', () => this.load(parseInt(btn.dataset.page, 10)));
        });
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Экспорт глобально
window.HistoryModule = HistoryModule;
App.history = HistoryModule;
