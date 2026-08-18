/**
 * AutoDialer Ultimate - Incoming Calls Module
 * Version: 3.0.0
 * Входящие звонки: список, статистика, прослушивание записи, транскрибация
 */

App.incoming = {
    state: {
        calls: [],
        currentPage: 1,
        perPage: 20,
        totalPages: 1,
        totalRecords: 0,
        autoRefreshInterval: null,
        currentCallId: null,
        currentAudio: null,
        // callId -> blob: URL, so a call played twice doesn't re-fetch
        recordingUrlCache: {}
    },

    // =============================================
    // Инициализация
    // =============================================
    async init() {
        // Re-entering this tab re-renders incoming.html from scratch, but
        // this.state (on the App.incoming singleton) survives - clear any
        // interval from a previous visit before starting a fresh one, same
        // guard dashboard.js uses for its Chart.js instance.
        if (this.state.autoRefreshInterval) {
            clearInterval(this.state.autoRefreshInterval);
            this.state.autoRefreshInterval = null;
        }

        this.setupEventListeners();
        this.checkMobileView();
        window.addEventListener('resize', this._onResize || (this._onResize = () => this.checkMobileView()));
        await Promise.all([
            this.loadIncomingCalls(),
            this.loadStats()
        ]);
        this.startAutoRefresh();
    },

    checkMobileView() {
        const isMobile = window.innerWidth < 768;
        const tableContainer = document.querySelector('.incoming-table-container');
        const cardsContainer = document.getElementById('incomingCards');
        if (tableContainer) tableContainer.style.display = isMobile ? 'none' : 'block';
        if (cardsContainer) cardsContainer.style.display = isMobile ? 'block' : 'none';
    },

    setupEventListeners() {
        document.getElementById('incomingRefreshBtn')?.addEventListener('click', () => {
            this.loadIncomingCalls();
            this.loadStats();
        });

        document.getElementById('incomingSaveNotesBtn')?.addEventListener('click', () => {
            this.saveNotes();
        });
    },

    // =============================================
    // Загрузка данных
    // =============================================
    async loadIncomingCalls(page) {
        if (page) this.state.currentPage = page;

        const tbody = document.getElementById('incomingTableBody');
        const cardsContainer = document.getElementById('incomingCards');
        const loadingHtml = '<tr><td colspan="6" class="text-center"><div class="loading">Загрузка...</div></td></tr>';
        if (tbody) tbody.innerHTML = loadingHtml;

        try {
            const params = new URLSearchParams({
                page: this.state.currentPage,
                page_size: this.state.perPage
            });

            const data = await App.apiGet(`/incoming-calls/?${params.toString()}`);

            this.state.calls = data.items || [];
            this.state.totalRecords = data.total || 0;
            this.state.totalPages = data.total_pages || 1;
            this.state.currentPage = data.page || this.state.currentPage;

            this.renderTable();
            this.renderCards();
            this.renderPagination();

        } catch (error) {
            console.error('Failed to load incoming calls:', error);
            if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center text-error">Ошибка загрузки данных</td></tr>';
            if (cardsContainer) cardsContainer.innerHTML = '<div class="text-center text-error">Ошибка загрузки</div>';
            App.showToast('Не удалось загрузить входящие звонки', 'error');
        }
    },

    async loadStats() {
        try {
            const data = await App.apiGet('/incoming-calls/stats');
            this.setText('incomingTotal', data.total || 0);
            this.setText('incomingProcessed', data.completed || 0);
            this.setText('incomingProcessing', data.processing || 0);
            this.setText('incomingFailed', data.failed || 0);
        } catch (error) {
            console.error('Failed to load incoming stats:', error);
        }
    },

    // =============================================
    // Рендер таблицы (десктоп)
    // =============================================
    renderTable() {
        const tbody = document.getElementById('incomingTableBody');
        if (!tbody) return;

        if (this.state.calls.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">📞</div>
                            <p>Нет входящих звонков</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.state.calls.map(call => this.renderTableRow(call)).join('');
        this.attachRowEventListeners();
    },

    renderTableRow(call) {
        const status = call.transcription_status || 'pending';
        return `
            <tr data-call-id="${call.id}" class="incoming-row ${status}">
                <td class="date-cell">${this.formatDateTime(call.call_date || call.created_at)}</td>
                <td class="phone-cell">
                    <span class="phone-number">${this.formatPhone(call.caller_number)}</span>
                </td>
                <td class="duration-cell">${this.formatDuration(call.duration)}</td>
                <td class="text-cell">${this.getTranscriptionDisplay(call)}</td>
                <td class="audio-cell">${this.renderAudioPlayer(call)}</td>
                <td class="actions-cell">
                    <div class="action-buttons">${this.getActionButtons(call)}</div>
                </td>
            </tr>
        `;
    },

    // =============================================
    // Рендер карточек (мобильные)
    // =============================================
    renderCards() {
        const container = document.getElementById('incomingCards');
        if (!container) return;

        if (this.state.calls.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📞</div>
                    <p>Нет входящих звонков</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.state.calls.map(call => {
            const status = call.transcription_status || 'pending';
            return `
                <div class="incoming-card ${status}" data-call-id="${call.id}">
                    <div class="card-header">
                        <span class="card-date">${this.formatDateShort(call.call_date || call.created_at)}</span>
                        <span class="card-phone">📱 ${this.formatPhone(call.caller_number)}</span>
                    </div>
                    <div class="card-body">
                        <div class="card-duration">⏱️ ${this.formatDuration(call.duration)}</div>
                        <div class="card-transcription">
                            ${status === 'completed' && call.transcription ? `
                                <div class="transcription-preview">📄 "${this.escapeHtml(call.transcription)}"</div>
                            ` : `
                                <div class="transcription-status-badge ${status}">📝 ${this.getStatusText(status)}</div>
                            `}
                        </div>
                        <div class="card-audio">
                            <button class="play-pause-btn mobile" data-call-id="${call.id}">
                                ▶️ ${this.formatDuration(call.duration)}
                            </button>
                        </div>
                    </div>
                    <div class="card-footer">
                        <div class="card-actions">
                            <button class="btn btn-sm btn-outline download-call" data-id="${call.id}">⬇</button>
                            <button class="btn btn-sm btn-outline-danger delete-call" data-id="${call.id}">🗑</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        this.attachCardEventListeners();
    },

    // =============================================
    // Пагинация
    // =============================================
    renderPagination() {
        const container = document.getElementById('incomingPagination');
        if (!container) return;

        if (this.state.totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        const { currentPage, totalPages } = this.state;
        let html = '<div class="pagination">';
        html += currentPage > 1
            ? `<button class="page-btn" data-page="${currentPage - 1}">←</button>`
            : `<button class="page-btn" disabled>←</button>`;

        const start = Math.max(1, currentPage - 2);
        const end = Math.min(totalPages, currentPage + 2);

        if (start > 1) {
            html += `<button class="page-btn" data-page="1">1</button>`;
            if (start > 2) html += '<span class="page-dots">...</span>';
        }
        for (let i = start; i <= end; i++) {
            html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }
        if (end < totalPages) {
            if (end < totalPages - 1) html += '<span class="page-dots">...</span>';
            html += `<button class="page-btn" data-page="${totalPages}">${totalPages}</button>`;
        }

        html += currentPage < totalPages
            ? `<button class="page-btn" data-page="${currentPage + 1}">→</button>`
            : `<button class="page-btn" disabled>→</button>`;
        html += '</div>';

        container.innerHTML = html;
        container.querySelectorAll('.page-btn[data-page]').forEach(btn => {
            btn.addEventListener('click', () => this.loadIncomingCalls(parseInt(btn.dataset.page, 10)));
        });
    },

    // =============================================
    // Детали звонка (модалка)
    // =============================================
    showCallDetails(call) {
        this.state.currentCallId = call.id;
        const content = document.getElementById('incomingDetailContent');
        if (!content) return;

        const status = call.transcription_status || 'pending';

        content.innerHTML = `
            <div class="call-detail">
                <div class="detail-grid">
                    <div class="detail-item">
                        <span class="detail-label">📱 Номер:</span>
                        <span class="detail-value">${this.formatPhone(call.caller_number)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">📅 Дата:</span>
                        <span class="detail-value">${this.formatDateTime(call.call_date || call.created_at)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">⏱️ Длительность:</span>
                        <span class="detail-value">${this.formatDuration(call.duration)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">📁 Размер файла:</span>
                        <span class="detail-value">${this.formatFileSize(call.file_size)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">📝 Статус:</span>
                        <span class="detail-value">
                            <span class="transcription-status ${status}">${this.getStatusText(status)}</span>
                        </span>
                    </div>
                </div>

                <div class="detail-section">
                    <h4>🎵 Запись</h4>
                    <audio controls id="incomingDetailAudio" class="audio-player-full"></audio>
                </div>

                ${status === 'completed' && call.transcription ? `
                    <div class="detail-section">
                        <h4>📄 Транскрибация</h4>
                        <div class="transcription-box">${this.escapeHtml(call.transcription)}</div>
                    </div>
                ` : status === 'failed' ? `
                    <div class="detail-section">
                        <h4>📄 Транскрибация</h4>
                        <p>Расшифровка не удалась.
                            <button class="btn btn-sm btn-outline" id="incomingRetryTranscribeBtn" data-id="${call.id}">
                                🔁 Повторить
                            </button>
                        </p>
                    </div>
                ` : ''}

                <div class="detail-section">
                    <h4>📋 Заметки</h4>
                    <textarea id="incomingCallNotes" class="form-control" rows="3" placeholder="Добавьте заметку...">${this.escapeHtml(call.notes || '')}</textarea>
                </div>
            </div>
        `;

        document.getElementById('incomingRetryTranscribeBtn')?.addEventListener('click', (e) => {
            this.retryTranscription(parseInt(e.target.dataset.id, 10));
        });

        App.showModal('incomingDetailModal');

        // Плеер получает src отдельно, асинхронно - см. getRecordingBlobUrl():
        // эндпоинт защищён Bearer-токеном в заголовке, а <audio src="..."> шлёт
        // обычный GET без заголовков и всегда падает с 401.
        this.getRecordingBlobUrl(call.id).then(url => {
            const audioEl = document.getElementById('incomingDetailAudio');
            if (audioEl && this.state.currentCallId === call.id) {
                audioEl.src = url;
            }
        }).catch(error => {
            console.error('Failed to load recording:', error);
        });
    },

    closeDetailModal() {
        App.hideModal('incomingDetailModal');
        if (this.state.currentAudio) {
            this.state.currentAudio.pause();
            this.state.currentAudio = null;
        }
        this.state.currentCallId = null;
    },

    async saveNotes() {
        const callId = this.state.currentCallId;
        const notes = document.getElementById('incomingCallNotes')?.value;
        if (!callId) return;

        try {
            await App.apiPatch(`/incoming-calls/${callId}`, { notes });
            App.showToast('Заметка сохранена', 'success');
            const call = this.state.calls.find(c => c.id === callId);
            if (call) call.notes = notes;
        } catch (error) {
            console.error('Failed to save notes:', error);
            App.showToast('Ошибка сохранения заметки', 'error');
        }
    },

    async retryTranscription(callId) {
        try {
            await App.apiPost(`/incoming-calls/${callId}/transcribe`, {});
            App.showToast('Расшифровка запущена', 'info');
            await this.loadIncomingCalls();
        } catch (error) {
            console.error('Failed to retry transcription:', error);
            App.showToast('Ошибка запуска расшифровки', 'error');
        }
    },

    // =============================================
    // Действия со звонком
    // =============================================
    async downloadRecording(id) {
        // Same reason as getRecordingBlobUrl() below - a plain <a href>
        // to a Bearer-protected endpoint sends no auth header and 401s.
        try {
            const url = await this.getRecordingBlobUrl(id);
            const a = document.createElement('a');
            a.href = url;
            a.download = `incoming_${id}.wav`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } catch (error) {
            console.error('Failed to download recording:', error);
            App.showToast('Ошибка скачивания записи', 'error');
        }
    },

    async deleteCall(id) {
        if (!App.confirm('Удалить запись о звонке? Файл также будет удалён.')) return;

        try {
            await App.apiDelete(`/incoming-calls/${id}`);
            App.showToast('Запись удалена', 'success');

            this.state.calls = this.state.calls.filter(c => c.id !== id);
            this.state.totalRecords = Math.max(0, this.state.totalRecords - 1);
            this.state.totalPages = Math.ceil(this.state.totalRecords / this.state.perPage) || 1;
            if (this.state.calls.length === 0 && this.state.currentPage > 1) {
                this.state.currentPage--;
            }

            await this.loadIncomingCalls();
            await this.loadStats();
        } catch (error) {
            console.error('Failed to delete call:', error);
            App.showToast('Ошибка удаления записи', 'error');
        }
    },

    // Эндпоинт /incoming-calls/{id}/recording защищён Bearer-токеном в
    // заголовке Authorization (см. get_current_user) - обычный GET без
    // заголовков (как делает <audio src="...">/<a href="...">) на него
    // всегда падает с 401. Тянем запись авторизованным fetch'ем и отдаём
    // blob: URL, который уже можно свободно подставлять в src. Кешируем
    // по call.id, чтобы повторное воспроизведение/скачивание не тянуло
    // файл заново.
    async getRecordingBlobUrl(callId) {
        if (this.state.recordingUrlCache[callId]) {
            return this.state.recordingUrlCache[callId];
        }

        const response = await fetch(`${App.API_BASE}/incoming-calls/${callId}/recording`, {
            headers: { 'Authorization': `Bearer ${App.state.accessToken}` }
        });
        if (!response.ok) {
            throw new Error(`Recording fetch failed: ${response.status}`);
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        this.state.recordingUrlCache[callId] = url;
        return url;
    },

    async handlePlayClick(callId, button) {
        try {
            const url = await this.getRecordingBlobUrl(callId);
            this.playAudio(url, button);
        } catch (error) {
            console.error('Failed to load recording:', error);
            App.showToast('Ошибка загрузки записи', 'error');
        }
    },

    playAudio(url, button) {
        if (this.state.currentAudio && this.state.currentAudio.src === url) {
            this.state.currentAudio.pause();
            this.state.currentAudio = null;
            button.textContent = '▶️';
            return;
        }

        if (this.state.currentAudio) {
            this.state.currentAudio.pause();
            document.querySelectorAll('.play-pause-btn').forEach(btn => btn.textContent = '▶️');
        }

        const audio = new Audio(url);
        audio.play();
        button.textContent = '⏸️';

        audio.onended = () => {
            button.textContent = '▶️';
            this.state.currentAudio = null;
        };
        audio.onerror = () => {
            App.showToast('Ошибка воспроизведения', 'error');
            button.textContent = '▶️';
            this.state.currentAudio = null;
        };

        this.state.currentAudio = audio;
    },

    // =============================================
    // Автообновление (пока есть звонки в процессе расшифровки)
    // =============================================
    startAutoRefresh() {
        this.state.autoRefreshInterval = setInterval(async () => {
            const hasProcessing = this.state.calls.some(c => c.transcription_status === 'processing');
            if (hasProcessing) {
                await this.loadIncomingCalls();
                await this.loadStats();
            }
        }, 5000);
    },

    destroy() {
        if (this.state.autoRefreshInterval) {
            clearInterval(this.state.autoRefreshInterval);
            this.state.autoRefreshInterval = null;
        }
        if (this.state.currentAudio) {
            this.state.currentAudio.pause();
            this.state.currentAudio = null;
        }
    },

    // =============================================
    // Обработчики событий на строках/карточках
    // =============================================
    attachRowEventListeners() {
        document.querySelectorAll('.incoming-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('.play-pause-btn')) return;
                const id = parseInt(row.dataset.callId, 10);
                const call = this.state.calls.find(c => c.id === id);
                if (call) this.showCallDetails(call);
            });
        });

        document.querySelectorAll('#incomingTableBody .play-pause-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.handlePlayClick(parseInt(btn.dataset.callId, 10), btn);
            });
        });

        document.querySelectorAll('#incomingTableBody .download-call').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.downloadRecording(parseInt(btn.dataset.id, 10));
            });
        });

        document.querySelectorAll('#incomingTableBody .delete-call').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteCall(parseInt(btn.dataset.id, 10));
            });
        });
    },

    attachCardEventListeners() {
        document.querySelectorAll('.incoming-card').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.closest('button')) return;
                const id = parseInt(card.dataset.callId, 10);
                const call = this.state.calls.find(c => c.id === id);
                if (call) this.showCallDetails(call);
            });
        });

        document.querySelectorAll('.incoming-card .play-pause-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.handlePlayClick(parseInt(btn.dataset.callId, 10), btn);
            });
        });

        document.querySelectorAll('.incoming-card .download-call').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.downloadRecording(parseInt(btn.dataset.id, 10));
            });
        });

        document.querySelectorAll('.incoming-card .delete-call').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteCall(parseInt(btn.dataset.id, 10));
            });
        });
    },

    // =============================================
    // Утилиты
    // =============================================
    setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    },

    getTranscriptionDisplay(call) {
        const status = call.transcription_status || 'pending';
        switch (status) {
            case 'pending':
                return '<span class="transcription-status pending">⏳ ожидание</span>';
            case 'processing':
                return '<span class="transcription-status processing">⏳ обработка</span>';
            case 'completed':
                if (call.transcription) {
                    const text = call.transcription;
                    const truncated = text.length > 50 ? text.substring(0, 47) + '...' : text;
                    return `<span class="transcription-text" title="${this.escapeHtml(text)}">${this.escapeHtml(truncated)}</span>`;
                }
                return '<span class="transcription-status completed">✅ Готово</span>';
            case 'failed':
                return '<span class="transcription-status failed">❌ ошибка</span>';
            default:
                return '<span class="transcription-status">—</span>';
        }
    },

    renderAudioPlayer(call) {
        if (!call.recording_path) return '<span class="no-recording">—</span>';
        return `
            <div class="mini-audio-player">
                <button class="play-pause-btn" data-call-id="${call.id}" title="Воспроизвести">▶️</button>
                <span class="audio-duration">${this.formatDuration(call.duration)}</span>
            </div>
        `;
    },

    getActionButtons(call) {
        return `
            <button class="btn btn-sm btn-outline download-call" data-id="${call.id}" title="Скачать запись">⬇</button>
            <button class="btn btn-sm btn-outline-danger delete-call" data-id="${call.id}" title="Удалить">🗑</button>
        `;
    },

    getStatusText(status) {
        const map = {
            'pending': 'ожидание',
            'processing': 'обработка',
            'completed': 'завершено',
            'failed': 'ошибка'
        };
        return map[status] || status;
    },

    formatDateTime(dateStr) {
        if (!dateStr) return '—';
        return App.parseServerDate(dateStr).toLocaleString('ru-RU', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        }).replace(',', '');
    },

    formatDateShort(dateStr) {
        if (!dateStr) return '—';
        return App.parseServerDate(dateStr).toLocaleString('ru-RU', {
            day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
        }).replace(',', '');
    },

    formatPhone(phone) {
        return App.formatPhoneNumber(phone);
    },

    formatDuration(seconds) {
        if (!seconds) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    },

    formatFileSize(bytes) {
        if (!bytes) return '—';
        const units = ['B', 'KB', 'MB'];
        let size = bytes;
        let unitIndex = 0;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(0)} ${units[unitIndex]}`;
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};
