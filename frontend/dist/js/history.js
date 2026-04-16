// history.js - Модуль истории звонков
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast, escapeHtml)

const HistoryModule = {
    currentPage: 1,
    pageSize: 20,
    
    // Загрузка истории
    async load(page = 1) {
        this.currentPage = page;
        
        const campaignId = document.getElementById('historyFilterCampaign')?.value;
        const status = document.getElementById('historyFilterStatus')?.value;
        const phone = document.getElementById('historyFilterPhone')?.value;
        const dateFrom = document.getElementById('historyFilterDateFrom')?.value;
        const dateTo = document.getElementById('historyFilterDateTo')?.value;
        
        let url = `${API_BASE}/history?page=${page}&page_size=${this.pageSize}`;
        if (campaignId) url += `&campaign_id=${campaignId}`;
        if (status) url += `&status=${status}`;
        if (phone) url += `&phone=${encodeURIComponent(phone)}`;
        if (dateFrom) url += `&date_from=${dateFrom}`;
        if (dateTo) url += `&date_to=${dateTo}`;
        
        try {
            const response = await authFetch(url);
            if (response.ok) {
                const data = await response.json();
                this.renderTable(data.items || data.history || []);
                this.renderPagination(data.total_pages || 1);
                this.updateStats(data.stats);
            } else {
                document.getElementById('historyTable').innerHTML = 
                    '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('History load failed:', error);
            document.getElementById('historyTable').innerHTML = 
                '<tr><td colspan="8" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    // Рендер таблицы
    renderTable(history) {
        const tbody = document.getElementById('historyTable');
        
        if (!history || history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center">Нет записей</td></tr>';
            return;
        }
        
        const statusMap = {
            'completed': 'Завершен',
            'answered': 'Отвечен',
            'no_answer': 'Нет ответа',
            'busy': 'Занято',
            'failed': 'Ошибка',
            'cancelled': 'Отменен',
            'pending': 'Ожидает',
            'ringing': 'Звонок'
        };
        
        tbody.innerHTML = history.map(call => `
            <tr data-call-id="${call.id}" class="history-row ${call.status}">
                <td>${this.formatDateTime(call.created_at)}</td>
                <td>
                    <span class="phone-number">${this.formatPhoneNumber(call.phone || call.to_number)}</span>
                    ${call.direction === 'inbound' ? '<span class="badge badge-info">Вх.</span>' : ''}
                </td>
                <td>${this.escapeHtml(call.contact_name || call.contact || '—')}</td>
                <td>${this.escapeHtml(call.campaign_name || call.campaign || '—')}</td>
                <td>
                    <span class="status-badge status-${call.status}">
                        ${statusMap[call.status] || call.status}
                    </span>
                </td>
                <td>${call.dtmf_result || '—'}</td>
                <td>${this.formatDuration(call.duration)}</td>
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
    
    // Привязка обработчиков к строкам
    attachRowEventListeners() {
        document.querySelectorAll('.history-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('a')) return;
                const id = row.dataset.callId;
                this.showCallDetails(id);
            });
        });
        
        document.querySelectorAll('.view-details').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                this.showCallDetails(id);
            });
        });
        
        document.querySelectorAll('.play-recording').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const url = btn.dataset.url;
                this.playRecording(url);
            });
        });
        
        document.querySelectorAll('.download-call').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                this.downloadCallDetails(id);
            });
        });
    },
    
    // Показать детали звонка
    async showCallDetails(callId) {
        try {
            const response = await authFetch(`${API_BASE}/history/${callId}`);
            if (!response.ok) throw new Error('Failed to load call details');
            
            const call = await response.json();
            
            const modalContent = `
                <div class="call-details">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID звонка:</td><td>${call.id}</td></tr>
                            <tr><td>Дата/время:</td><td>${this.formatDateTime(call.created_at)}</td></tr>
                            <tr><td>Номер:</td><td>${this.formatPhoneNumber(call.phone || call.to_number)}</td></tr>
                            <tr><td>Контакт:</td><td>${this.escapeHtml(call.contact_name || '—')}</td></tr>
                            <tr><td>Кампания:</td><td>${this.escapeHtml(call.campaign_name || '—')}</td></tr>
                            <tr><td>Статус:</td><td><span class="status-badge status-${call.status}">${call.status}</span></td></tr>
                            <tr><td>Длительность:</td><td>${this.formatDuration(call.duration)}</td></tr>
                            <tr><td>DTMF результат:</td><td>${call.dtmf_result || '—'}</td></tr>
                        </table>
                    </div>
                    
                    ${call.answered_at ? `
                        <div class="detail-section">
                            <h4>Временные метки</h4>
                            <table class="details-table">
                                <tr><td>Начало:</td><td>${this.formatDateTime(call.created_at)}</td></tr>
                                <tr><td>Ответ:</td><td>${this.formatDateTime(call.answered_at)}</td></tr>
                                <tr><td>Завершение:</td><td>${this.formatDateTime(call.completed_at || call.ended_at)}</td></tr>
                            </table>
                        </div>
                    ` : ''}
                    
                    ${call.recording_url ? `
                        <div class="detail-section">
                            <h4>Запись разговора</h4>
                            <audio controls src="${call.recording_url}" style="width: 100%;"></audio>
                            <br>
                            <a href="${call.recording_url}" download class="btn btn-sm btn-primary" style="margin-top: 10px;">
                                📥 Скачать запись
                            </a>
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
            
            this.showModal('Детали звонка', modalContent);
            
        } catch (error) {
            console.error('Failed to load call details:', error);
            showToast('Не удалось загрузить детали звонка', 'error');
        }
    },
    
    // Воспроизведение записи
    playRecording(url) {
        const audio = new Audio(url);
        
        const modalContent = `
            <div class="audio-player-container">
                <audio controls src="${url}" style="width: 100%;" autoplay></audio>
            </div>
        `;
        
        this.showModal('Воспроизведение записи', modalContent, {
            onClose: () => audio.pause()
        });
        
        audio.play().catch(e => {
            console.error('Audio playback failed:', e);
            showToast('Ошибка воспроизведения', 'error');
        });
    },
    
    // Скачать детали звонка
    async downloadCallDetails(callId) {
        try {
            const response = await authFetch(`${API_BASE}/history/${callId}`);
            if (!response.ok) throw new Error('Failed to load');
            
            const call = await response.json();
            
            const dataStr = JSON.stringify(call, null, 2);
            const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
            
            const linkElement = document.createElement('a');
            linkElement.setAttribute('href', dataUri);
            linkElement.setAttribute('download', `call_${callId}_${new Date().toISOString().split('T')[0]}.json`);
            linkElement.click();
            
            showToast('Детали звонка скачаны', 'success');
        } catch (error) {
            console.error('Download failed:', error);
            showToast('Не удалось скачать детали', 'error');
        }
    },
    
    // Экспорт в CSV
    async exportToCSV() {
        showToast('Подготовка экспорта...', 'info');
        
        const campaignId = document.getElementById('historyFilterCampaign')?.value;
        const status = document.getElementById('historyFilterStatus')?.value;
        const dateFrom = document.getElementById('historyFilterDateFrom')?.value;
        const dateTo = document.getElementById('historyFilterDateTo')?.value;
        
        let url = `${API_BASE}/history/export?`;
        const params = [];
        if (campaignId) params.push(`campaign_id=${campaignId}`);
        if (status) params.push(`status=${status}`);
        if (dateFrom) params.push(`date_from=${dateFrom}`);
        if (dateTo) params.push(`date_to=${dateTo}`);
        url += params.join('&');
        
        try {
            const response = await authFetch(url);
            if (response.ok) {
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = `calls_export_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(downloadUrl);
                document.body.removeChild(a);
                
                showToast('Экспорт завершен', 'success');
            } else {
                throw new Error('Export failed');
            }
        } catch (error) {
            console.error('Export failed:', error);
            
            // Fallback - клиентский экспорт
            await this.exportToCSVClientSide();
        }
    },
    
    // Клиентский экспорт в CSV (fallback)
    async exportToCSVClientSide() {
        try {
            const response = await authFetch(`${API_BASE}/history?page_size=10000`);
            if (!response.ok) throw new Error('Failed to load data');
            
            const data = await response.json();
            const calls = data.items || data.history || [];
            
            if (!calls.length) {
                showToast('Нет данных для экспорта', 'warning');
                return;
            }
            
            const headers = ['ID', 'Дата/время', 'Номер', 'Контакт', 'Кампания', 'Статус', 'DTMF', 'Длительность'];
            const rows = calls.map(call => [
                call.id,
                this.formatDateTime(call.created_at),
                call.phone || call.to_number,
                call.contact_name || '',
                call.campaign_name || '',
                call.status,
                call.dtmf_result || '',
                call.duration || 0
            ]);
            
            const csvContent = [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
            ].join('\n');
            
            const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `calls_export_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            window.URL.revokeObjectURL(url);
            
            showToast(`Экспортировано ${calls.length} записей`, 'success');
        } catch (error) {
            console.error('Client-side export failed:', error);
            showToast('Не удалось выполнить экспорт', 'error');
        }
    },
    
    // Показать статистику
    async showStatistics() {
        try {
            const response = await authFetch(`${API_BASE}/history/statistics`);
            if (!response.ok) throw new Error('Failed to load statistics');
            
            const stats = await response.json();
            
            const modalContent = `
                <div class="statistics-panel">
                    <div class="stats-grid">
                        <div class="stat-card">
                            <h4>Всего звонков</h4>
                            <div class="stat-value">${stats.total || 0}</div>
                        </div>
                        <div class="stat-card stat-success">
                            <h4>Отвечено</h4>
                            <div class="stat-value">${stats.answered || 0}</div>
                            <div class="stat-percent">${stats.answer_rate || 0}%</div>
                        </div>
                        <div class="stat-card stat-warning">
                            <h4>Нет ответа</h4>
                            <div class="stat-value">${stats.no_answer || 0}</div>
                        </div>
                        <div class="stat-card stat-danger">
                            <h4>Занято</h4>
                            <div class="stat-value">${stats.busy || 0}</div>
                        </div>
                        <div class="stat-card">
                            <h4>Ср. длительность</h4>
                            <div class="stat-value">${this.formatDuration(stats.avg_duration || 0)}</div>
                        </div>
                    </div>
                </div>
            `;
            
            this.showModal('📊 Статистика звонков', modalContent);
            
        } catch (error) {
            console.error('Failed to load statistics:', error);
            showToast('Не удалось загрузить статистику', 'error');
        }
    },
    
    // Обновление статистики в шапке
    updateStats(stats) {
        if (!stats) return;
        
        const totalEl = document.getElementById('historyTotalCalls');
        const answeredEl = document.getElementById('historyAnswered');
        const conversionEl = document.getElementById('historyConversion');
        
        if (totalEl) totalEl.textContent = stats.total || 0;
        if (answeredEl) answeredEl.textContent = stats.answered || 0;
        if (conversionEl) conversionEl.textContent = `${stats.answer_rate || 0}%`;
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
        
        // Предыдущая
        if (this.currentPage > 1) {
            html += `<button class="page-btn" data-page="${this.currentPage - 1}">←</button>`;
        } else {
            html += `<button class="page-btn" disabled>←</button>`;
        }
        
        // Страницы
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
        
        // Следующая
        if (this.currentPage < totalPages) {
            html += `<button class="page-btn" data-page="${this.currentPage + 1}">→</button>`;
        } else {
            html += `<button class="page-btn" disabled>→</button>`;
        }
        
        html += '</div>';
        
        container.innerHTML = html;
        
        // Привязка событий
        container.querySelectorAll('.page-btn[data-page]').forEach(btn => {
            btn.addEventListener('click', () => {
                const page = parseInt(btn.dataset.page);
                this.load(page);
            });
        });
    },
    
    // Сброс фильтров
    resetFilters() {
        const filterCampaign = document.getElementById('historyFilterCampaign');
        const filterStatus = document.getElementById('historyFilterStatus');
        const filterPhone = document.getElementById('historyFilterPhone');
        const filterDateFrom = document.getElementById('historyFilterDateFrom');
        const filterDateTo = document.getElementById('historyFilterDateTo');
        
        if (filterCampaign) filterCampaign.value = '';
        if (filterStatus) filterStatus.value = '';
        if (filterPhone) filterPhone.value = '';
        if (filterDateFrom) filterDateFrom.value = '';
        if (filterDateTo) filterDateTo.value = '';
        
        this.currentPage = 1;
        this.load(1);
    },
    
    // Применить фильтры
    applyFilters() {
        this.currentPage = 1;
        this.load(1);
    },
    
    // Показать модальное окно
    showModal(title, content, options = {}) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3>${title}</h3>
                    <button class="close-modal">&times;</button>
                </div>
                <div class="modal-body">
                    ${content}
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        const closeBtn = modal.querySelector('.close-modal');
        closeBtn.addEventListener('click', () => {
            if (options.onClose) options.onClose();
            modal.remove();
        });
        
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                if (options.onClose) options.onClose();
                modal.remove();
            }
        });
    },
    
    // Вспомогательные функции
    formatDateTime(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }).replace(',', '');
    },
    
    formatPhoneNumber(phone) {
        if (!phone) return '—';
        const cleaned = phone.replace(/\D/g, '');
        if (cleaned.length === 11) {
            return `+${cleaned[0]} (${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7, 9)}-${cleaned.slice(9, 11)}`;
        }
        return phone;
    },
    
    formatDuration(seconds) {
        if (!seconds || seconds === 0) return '0 сек';
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        
        const parts = [];
        if (hours > 0) parts.push(`${hours} ч`);
        if (minutes > 0) parts.push(`${minutes} мин`);
        if (secs > 0 || parts.length === 0) parts.push(`${secs} сек`);
        
        return parts.join(' ');
    },
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    
    // Инициализация модуля
    init() {
        // Обработчики фильтров
        document.getElementById('historyApplyFilters')?.addEventListener('click', () => this.applyFilters());
        document.getElementById('historyResetFilters')?.addEventListener('click', () => this.resetFilters());
        document.getElementById('historyExportCsv')?.addEventListener('click', () => this.exportToCSV());
        document.getElementById('historyShowStats')?.addEventListener('click', () => this.showStatistics());
        
        // Поиск по Enter
        document.getElementById('historyFilterPhone')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.applyFilters();
        });
        
        // Загрузка данных
        this.load(1);
    }
};

// Экспорт глобально
window.HistoryModule = HistoryModule;
