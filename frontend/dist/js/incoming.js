/**
 * Incoming Calls Module
 */

App.incoming = {
    currentPage: 1,
    selectedCalls: new Set(),
    currentCallId: null,

    // Initialize
    init() {
        this.loadStats();
        this.loadCalls(1);
        this.setupEventListeners();
    },

    setupEventListeners() {
        document.getElementById('selectAllIncoming')?.addEventListener('change', (e) => {
            this.toggleSelectAll(e.target.checked);
        });
    },

    // Load statistics
    async loadStats() {
        try {
            const response = await App.apiFetch('/incoming-calls/stats');
            if (response.ok) {
                const stats = await response.json();
                document.getElementById('incomingTotal').textContent = stats.total || 0;
                document.getElementById('incomingCompleted').textContent = stats.completed || 0;
                document.getElementById('incomingProcessing').textContent = stats.processing || 0;
                document.getElementById('incomingPending').textContent = stats.pending || 0;
            }
        } catch (error) {
            console.error('Stats load failed:', error);
        }
    },

    // Load calls list
    async loadCalls(page = 1) {
        this.currentPage = page;
        const status = document.getElementById('incomingFilterStatus')?.value || '';
        
        try {
            const url = `/incoming-calls?page=${page}&page_size=20${status ? `&status=${status}` : ''}`;
            const response = await App.apiFetch(url);
            
            if (response.ok) {
                const data = await response.json();
                this.renderTable(data.items);
                this.renderPagination(data.total_pages);
                this.selectedCalls.clear();
                this.updateBatchButtons();
            }
        } catch (error) {
            console.error('Calls load failed:', error);
        }
    },

    // Render table
    renderTable(calls) {
        const tbody = document.getElementById('incomingCallsTable');
        
        if (!calls || calls.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">Нет входящих звонков</td></tr>';
            return;
        }
        
        tbody.innerHTML = calls.map(call => `
            <tr>
                <td><input type="checkbox" value="${call.id}" onchange="App.incoming.toggleSelect(${call.id})"></td>
                <td>${new Date(call.call_date).toLocaleString()}</td>
                <td>${call.caller_number}</td>
                <td>${call.duration ? App.utils.formatDuration(call.duration) : '-'}</td>
                <td>
                    ${call.transcription_status === 'completed' 
                        ? `<span class="transcription-preview">${(call.transcription || '').substring(0, 50)}...</span>`
                        : `<span class="status-badge status-${call.transcription_status}">${call.transcription_status}</span>`}
                </td>
                <td>
                    <audio controls src="${App.API_BASE}/incoming-calls/${call.id}/recording" style="width: 150px; height: 30px;"></audio>
                </td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="App.incoming.showDetail(${call.id})">👁</button>
                    <button class="btn btn-outline btn-sm" onclick="App.incoming.download(${call.id})">⬇</button>
                    ${call.transcription_status !== 'completed' 
                        ? `<button class="btn btn-outline btn-sm" onclick="App.incoming.retryTranscription(${call.id})">📝</button>`
                        : ''}
                    <button class="btn btn-outline btn-sm admin-only" onclick="App.incoming.delete(${call.id})">🗑</button>
                </td>
            </tr>
        `).join('');
    },

    // Render pagination
    renderPagination(totalPages) {
        const container = document.getElementById('incomingPagination');
        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }
        
        let html = '';
        if (this.currentPage > 1) {
            html += `<button onclick="App.incoming.loadCalls(${this.currentPage - 1})">←</button>`;
        }
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || Math.abs(i - this.currentPage) <= 2) {
                html += `<button class="${i === this.currentPage ? 'active' : ''}" onclick="App.incoming.loadCalls(${i})">${i}</button>`;
            } else if (Math.abs(i - this.currentPage) === 3) {
                html += '<span>...</span>';
            }
        }
        if (this.currentPage < totalPages) {
            html += `<button onclick="App.incoming.loadCalls(${this.currentPage + 1})">→</button>`;
        }
        container.innerHTML = html;
    },

    // Toggle select
    toggleSelect(id) {
        if (this.selectedCalls.has(id)) {
            this.selectedCalls.delete(id);
        } else {
            this.selectedCalls.add(id);
        }
        this.updateBatchButtons();
    },

    // Toggle select all
    toggleSelectAll(checked) {
        const checkboxes = document.querySelectorAll('#incomingCallsTable input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = checked;
            if (checked) {
                this.selectedCalls.add(parseInt(cb.value));
            } else {
                this.selectedCalls.clear();
            }
        });
        this.updateBatchButtons();
    },

    // Update batch buttons
    updateBatchButtons() {
        const count = this.selectedCalls.size;
        document.getElementById('batchDeleteBtn').style.display = count > 0 ? 'inline-block' : 'none';
        document.getElementById('batchTranscribeBtn').style.display = count > 0 ? 'inline-block' : 'none';
    },

    // Show detail
    async showDetail(id) {
        this.currentCallId = id;
        
        try {
            const response = await App.apiFetch(`/incoming-calls/${id}`);
            if (response.ok) {
                const call = await response.json();
                
                document.getElementById('detailCallerNumber').textContent = call.caller_number;
                document.getElementById('detailCallDate').textContent = new Date(call.call_date).toLocaleString();
                document.getElementById('detailDuration').textContent = App.utils.formatDuration(call.duration);
                document.getElementById('detailTranscriptionStatus').textContent = call.transcription_status;
                
                const audio = document.getElementById('detailAudioPlayer');
                audio.src = `${App.API_BASE}/incoming-calls/${id}/recording`;
                
                document.getElementById('detailDownloadLink').href = `${App.API_BASE}/incoming-calls/${id}/recording`;
                document.getElementById('detailDownloadLink').download = `incoming_${call.caller_number}.wav`;
                
                document.getElementById('detailTranscription').textContent = call.transcription || 'Нет текста';
                document.getElementById('detailNotes').value = call.notes || '';
                
                document.getElementById('detailRetryBtn').style.display = 
                    call.transcription_status !== 'completed' ? 'inline-block' : 'none';
                
                document.getElementById('incomingDetailModal').style.display = 'flex';
            }
        } catch (error) {
            App.showToast('Ошибка загрузки', 'error');
        }
    },

    // Close detail modal
    closeDetail() {
        document.getElementById('incomingDetailModal').style.display = 'none';
        this.currentCallId = null;
    },

    // Save notes
    async saveNotes() {
        if (!this.currentCallId) return;
        
        const notes = document.getElementById('detailNotes').value;
        
        try {
            const response = await App.apiFetch(`/incoming-calls/${this.currentCallId}`, {
                method: 'PATCH',
                body: JSON.stringify({ notes })
            });
            
            if (response.ok) {
                App.showToast('Заметка сохранена', 'success');
                this.closeDetail();
                this.loadCalls(this.currentPage);
            }
        } catch (error) {
            App.showToast('Ошибка сохранения', 'error');
        }
    },

    // Copy transcription
    copyTranscription() {
        const text = document.getElementById('detailTranscription').textContent;
        navigator.clipboard?.writeText(text);
        App.showToast('Текст скопирован', 'info');
    },

    // Retry transcription
    async retryTranscription(id = null) {
        const callId = id || this.currentCallId;
        if (!callId) return;
        
        try {
            await App.apiFetch(`/incoming-calls/${callId}/transcribe`, { method: 'POST' });
            App.showToast('Транскрибация запущена', 'info');
            setTimeout(() => this.loadCalls(this.currentPage), 3000);
        } catch (error) {
            App.showToast('Ошибка', 'error');
        }
    },

    // Download
    download(id) {
        window.open(`${App.API_BASE}/incoming-calls/${id}/recording`, '_blank');
    },

    // Delete single
    async delete(id) {
        if (!confirm('Удалить запись о звонке?')) return;
        
        try {
            await App.apiFetch(`/incoming-calls/${id}`, { method: 'DELETE' });
            App.showToast('Удалено', 'success');
            this.loadCalls(this.currentPage);
            this.loadStats();
        } catch (error) {
            App.showToast('Ошибка удаления', 'error');
        }
    },

    // Delete from detail
    deleteFromDetail() {
        if (this.currentCallId) {
            this.delete(this.currentCallId);
            this.closeDetail();
        }
    },

    // Batch delete
    async batchDelete() {
        if (this.selectedCalls.size === 0) return;
        if (!confirm(`Удалить ${this.selectedCalls.size} записей?`)) return;
        
        try {
            await App.apiFetch('/incoming-calls/batch-delete', {
                method: 'POST',
                body: JSON.stringify({ call_ids: Array.from(this.selectedCalls) })
            });
            App.showToast('Удалено', 'success');
            this.loadCalls(this.currentPage);
            this.loadStats();
        } catch (error) {
            App.showToast('Ошибка', 'error');
        }
    },

    // Batch transcribe
    async batchTranscribe() {
        if (this.selectedCalls.size === 0) return;
        
        for (const id of this.selectedCalls) {
            await App.apiFetch(`/incoming-calls/${id}/transcribe`, { method: 'POST' });
        }
        App.showToast(`Запущена транскрибация ${this.selectedCalls.size} записей`, 'info');
        setTimeout(() => this.loadCalls(this.currentPage), 3000);
    }
};
