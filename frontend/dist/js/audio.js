// audio.js - Модуль управления аудиофайлами и TTS
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast, escapeHtml)

const AudioModule = {
    currentTab: 'library',
    audioFiles: [],
    selectedFiles: new Set(),
    currentPage: 1,
    pageSize: 20,
    totalPages: 1,
    totalRecords: 0,
    searchQuery: '',
    
    // Доступные голоса Piper (из 06_tts_install.sh)
    voices: [
        { id: 'denis', name: 'Денис (мужской, русский)' },
        { id: 'irina', name: 'Ирина (женский, русский)' },
        { id: 'en_US-lessac', name: 'Lessac (женский, английский)' }
    ],
    
    // Инициализация модуля
    init() {
        this.render();
        this.attachEventListeners();
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('audioContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="audio-page">
                <div class="page-header">
                    <h2>🎵 Управление аудио</h2>
                    <div class="header-actions">
                        <button class="btn btn-primary" id="audioUploadBtn">
                            📤 Загрузить файл
                        </button>
                        <button class="btn btn-success" id="audioGenerateBtn">
                            🔊 Генерация речи (TTS)
                        </button>
                    </div>
                </div>
                
                <div class="tabs-container">
                    <div class="tabs">
                        <button class="tab ${this.currentTab === 'library' ? 'active' : ''}" data-tab="library">
                            📚 Библиотека
                        </button>
                        <button class="tab ${this.currentTab === 'tts' ? 'active' : ''}" data-tab="tts">
                            🤖 Text-to-Speech
                        </button>
                        <button class="tab ${this.currentTab === 'upload' ? 'active' : ''}" data-tab="upload">
                            ⬆️ Загрузка
                        </button>
                    </div>
                </div>
                
                <div id="audioTabContent" class="tab-content"></div>
            </div>
        `;
        
        this.renderActiveTab();
    },
    
    // Рендер активной вкладки
    async renderActiveTab() {
        const content = document.getElementById('audioTabContent');
        
        switch (this.currentTab) {
            case 'library':
                content.innerHTML = this.getLibraryTemplate();
                await this.loadAudioFiles();
                this.attachLibraryEvents();
                break;
            case 'tts':
                content.innerHTML = this.getTTSTemplate();
                this.attachTTSEvents();
                await this.loadTTSHistory();
                break;
            case 'upload':
                content.innerHTML = this.getUploadTemplate();
                this.attachUploadEvents();
                break;
        }
    },
    
    // ============ ШАБЛОНЫ ============
    
    getLibraryTemplate() {
        return `
            <div class="library-container">
                <div class="library-toolbar">
                    <div class="search-box">
                        <input type="text" 
                               id="audioSearch" 
                               class="form-control" 
                               placeholder="🔍 Поиск по названию..."
                               value="${this.searchQuery}">
                    </div>
                    <div class="toolbar-actions">
                        <select id="audioSortSelect" class="form-control">
                            <option value="newest">Сначала новые</option>
                            <option value="oldest">Сначала старые</option>
                            <option value="name_asc">Название (А-Я)</option>
                            <option value="name_desc">Название (Я-А)</option>
                            <option value="size_desc">Размер (по убыванию)</option>
                        </select>
                        ${this.selectedFiles.size > 0 ? `
                            <button class="btn btn-danger" id="audioDeleteSelectedBtn">
                                🗑️ Удалить выбранные (${this.selectedFiles.size})
                            </button>
                        ` : ''}
                        <button class="btn btn-outline" id="audioRefreshBtn">
                            🔄 Обновить
                        </button>
                    </div>
                </div>
                
                <div class="audio-table-container">
                    <table class="table" id="audioTable">
                        <thead>
                            <tr>
                                <th width="40">
                                    <input type="checkbox" id="audioSelectAll">
                                </th>
                                <th>Название</th>
                                <th>Тип</th>
                                <th>Длительность</th>
                                <th>Размер</th>
                                <th>Источник</th>
                                <th>Создан</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody id="audioTableBody">
                            <tr><td colspan="8" class="text-center">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                
                <div id="audioPagination" class="pagination-container"></div>
            </div>
        `;
    },
    
    getTTSTemplate() {
        return `
            <div class="tts-container">
                <div class="row">
                    <div class="col-md-7">
                        <div class="tts-form-panel">
                            <h3>🎤 Генерация речи (Piper TTS)</h3>
                            <p class="text-muted">Локальный синтезатор речи, работает офлайн</p>
                            
                            <form id="ttsForm">
                                <div class="form-group">
                                    <label>Название файла</label>
                                    <input type="text" 
                                           id="ttsName" 
                                           class="form-control" 
                                           placeholder="Например: welcome_message"
                                           required>
                                </div>
                                
                                <div class="form-group">
                                    <label>Голос</label>
                                    <select id="ttsVoice" class="form-control" required>
                                        ${this.voices.map(v => `
                                            <option value="${v.id}">${v.name}</option>
                                        `).join('')}
                                    </select>
                                </div>
                                
                                <div class="form-group">
                                    <label>Текст для озвучки</label>
                                    <textarea id="ttsText" 
                                              class="form-control" 
                                              rows="6" 
                                              placeholder="Введите текст..."
                                              maxlength="500"
                                              required></textarea>
                                    <small class="form-text">
                                        <span id="ttsCharCount">0</span>/500 символов
                                    </small>
                                </div>
                                
                                <div class="form-group">
                                    <label>Привязать к кампании (опционально)</label>
                                    <select id="ttsCampaign" class="form-control">
                                        <option value="">Нет</option>
                                    </select>
                                </div>
                                
                                <div class="form-group">
                                    <label>Описание (опционально)</label>
                                    <textarea id="ttsDescription" 
                                              class="form-control" 
                                              rows="2"
                                              placeholder="Добавьте описание..."></textarea>
                                </div>
                                
                                <div class="form-actions">
                                    <button type="submit" class="btn btn-success btn-lg" id="ttsGenerateBtn">
                                        🔊 Сгенерировать речь
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                    
                    <div class="col-md-5">
                        <div class="tts-history-panel">
                            <h3>📋 Последние генерации</h3>
                            <div id="ttsHistoryList">
                                <p class="text-muted">Загрузка...</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },
    
    getUploadTemplate() {
        return `
            <div class="upload-container">
                <div class="upload-area" id="audioDropZone">
                    <div class="upload-icon">📁</div>
                    <h3>Перетащите файлы сюда</h3>
                    <p>или</p>
                    <button class="btn btn-primary" id="audioSelectFilesBtn">Выберите файлы</button>
                    <input type="file" 
                           id="audioFileInput" 
                           multiple 
                           accept=".mp3,.wav,.ogg,.m4a,.aac,.flac"
                           style="display: none;">
                    <p class="upload-hint">
                        Поддерживаемые форматы: MP3, WAV, OGG, M4A, AAC, FLAC<br>
                        Максимальный размер: 50 МБ
                    </p>
                </div>
                
                <div class="upload-form" id="audioUploadForm" style="display: none;">
                    <h3>Загрузка файла</h3>
                    <div class="form-group">
                        <label>Название</label>
                        <input type="text" id="audioUploadName" class="form-control" required>
                    </div>
                    <div class="form-group">
                        <label>Привязать к кампании (опционально)</label>
                        <select id="audioUploadCampaign" class="form-control">
                            <option value="">Нет</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Описание (опционально)</label>
                        <textarea id="audioUploadDescription" class="form-control" rows="2"></textarea>
                    </div>
                    <div class="form-actions">
                        <button class="btn btn-primary" id="audioUploadSubmitBtn">Загрузить</button>
                        <button class="btn btn-outline" id="audioUploadCancelBtn">Отмена</button>
                    </div>
                </div>
                
                <div id="audioUploadQueue" style="display: none;">
                    <h3>Очередь загрузки</h3>
                    <div id="audioQueueList" class="queue-list"></div>
                </div>
                
                <div class="upload-tips">
                    <h4>💡 Советы</h4>
                    <ul>
                        <li>Для лучшего качества используйте WAV или FLAC</li>
                        <li>Для TTS рекомендуется моно, 16 кГц</li>
                        <li>Названия файлов должны быть информативными</li>
                    </ul>
                </div>
            </div>
        `;
    },
    
    // ============ ЗАГРУЗКА ДАННЫХ ============
    
    async loadAudioFiles() {
        const tbody = document.getElementById('audioTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Загрузка...</td></tr>';
        
        try {
            let url = `${API_BASE}/audio/?page=${this.currentPage}&page_size=${this.pageSize}`;
            if (this.searchQuery) {
                url += `&search=${encodeURIComponent(this.searchQuery)}`;
            }
            
            const response = await authFetch(url);
            if (response.ok) {
                const data = await response.json();
                this.audioFiles = data.items || data || [];
                this.totalRecords = data.total || this.audioFiles.length;
                this.totalPages = Math.ceil(this.totalRecords / this.pageSize) || 1;
                
                this.renderAudioTable();
                this.renderPagination();
                this.updateSelectAllState();
            } else {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('Audio load failed:', error);
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    renderAudioTable() {
        const tbody = document.getElementById('audioTableBody');
        
        if (this.audioFiles.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">🎵</div>
                            <p>Нет аудиофайлов</p>
                            <button class="btn btn-primary" id="audioUploadEmptyBtn">Загрузить первый файл</button>
                        </div>
                    </td>
                </tr>
            `;
            document.getElementById('audioUploadEmptyBtn')?.addEventListener('click', () => {
                this.switchTab('upload');
            });
            return;
        }
        
        tbody.innerHTML = this.audioFiles.map(file => `
            <tr data-file-id="${file.id}" class="${this.selectedFiles.has(file.id) ? 'selected' : ''}">
                <td>
                    <input type="checkbox" 
                           class="audio-checkbox" 
                           data-id="${file.id}"
                           ${this.selectedFiles.has(file.id) ? 'checked' : ''}>
                </td>
                <td>
                    <div class="file-info">
                        <div class="file-icon">${this.getFileIcon(file.mime_type || file.format)}</div>
                        <div class="file-details">
                            <strong>${this.escapeHtml(file.name)}</strong>
                            ${file.description ? `<small>${this.escapeHtml(file.description)}</small>` : ''}
                        </div>
                    </div>
                </td>
                <td>${file.format || this.getFileType(file.mime_type) || 'Аудио'}</td>
                <td>${this.formatDuration(file.duration)}</td>
                <td>${this.formatFileSize(file.file_size || file.size)}</td>
                <td>
                    ${file.source === 'tts' ? '<span class="badge badge-tts">TTS</span>' : '<span class="badge badge-upload">Загрузка</span>'}
                </td>
                <td>${this.formatDate(file.created_at)}</td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline play-audio" 
                                data-url="${file.download_url || file.file_path}"
                                title="Прослушать">▶️</button>
                        <button class="btn btn-sm btn-outline download-audio" 
                                data-url="${file.download_url || file.file_path}"
                                data-filename="${this.escapeHtml(file.name)}"
                                title="Скачать">📥</button>
                        <button class="btn btn-sm btn-outline-danger delete-audio" 
                                data-id="${file.id}"
                                title="Удалить">🗑️</button>
                    </div>
                </td>
            </tr>
        `).join('');
        
        this.attachTableRowEvents();
    },
    
    async loadTTSHistory() {
        const container = document.getElementById('ttsHistoryList');
        if (!container) return;
        
        try {
            const response = await authFetch(`${API_BASE}/audio/?source=tts&limit=5`);
            if (response.ok) {
                const data = await response.json();
                const items = data.items || data || [];
                
                if (items.length === 0) {
                    container.innerHTML = '<p class="text-muted">История пуста</p>';
                    return;
                }
                
                container.innerHTML = items.map(item => `
                    <div class="history-item">
                        <div class="history-info">
                            <strong>${this.escapeHtml(item.name)}</strong>
                            <small>${this.formatDate(item.created_at)}</small>
                            ${item.tts_text ? `
                                <p class="history-text">${this.escapeHtml(item.tts_text.substring(0, 100))}${item.tts_text.length > 100 ? '...' : ''}</p>
                            ` : ''}
                        </div>
                        <div class="history-actions">
                            <button class="btn btn-sm btn-outline play-history" data-url="${item.download_url || item.file_path}">▶️</button>
                        </div>
                    </div>
                `).join('');
                
                container.querySelectorAll('.play-history').forEach(btn => {
                    btn.addEventListener('click', () => this.playAudio(btn.dataset.url));
                });
            }
        } catch (error) {
            console.error('TTS history load failed:', error);
            container.innerHTML = '<p class="text-error">Ошибка загрузки</p>';
        }
    },
    
    async loadCampaignsForSelect() {
        try {
            const response = await authFetch(`${API_BASE}/campaigns/`);
            if (response.ok) {
                const data = await response.json();
                const campaigns = data.items || data || [];
                const options = '<option value="">Нет</option>' +
                    campaigns.map(c => `<option value="${c.id}">${this.escapeHtml(c.name)}</option>`).join('');
                
                const ttsSelect = document.getElementById('ttsCampaign');
                const uploadSelect = document.getElementById('audioUploadCampaign');
                
                if (ttsSelect) ttsSelect.innerHTML = options;
                if (uploadSelect) uploadSelect.innerHTML = options;
            }
        } catch (error) {
            console.error('Load campaigns failed:', error);
        }
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async generateAudio() {
        const name = document.getElementById('ttsName').value;
        const text = document.getElementById('ttsText').value;
        const voice = document.getElementById('ttsVoice').value;
        const campaignId = document.getElementById('ttsCampaign').value;
        const description = document.getElementById('ttsDescription').value;
        
        if (!name || !text) {
            showToast('Заполните название и текст', 'warning');
            return;
        }
        
        if (text.length > 500) {
            showToast('Текст не должен превышать 500 символов', 'warning');
            return;
        }
        
        const generateBtn = document.getElementById('ttsGenerateBtn');
        const originalText = generateBtn.textContent;
        generateBtn.disabled = true;
        generateBtn.textContent = '⏳ Генерация...';
        
        try {
            const data = { name, text, voice };
            if (campaignId) data.campaign_id = campaignId;
            if (description) data.description = description;
            
            const response = await authFetch(`${API_BASE}/audio/tts/generate`, {
                method: 'POST',
                body: JSON.stringify(data)
            });
            
            if (response.ok) {
                const result = await response.json();
                
                document.getElementById('ttsName').value = '';
                document.getElementById('ttsText').value = '';
                document.getElementById('ttsDescription').value = '';
                document.getElementById('ttsCharCount').textContent = '0';
                
                showToast('Аудио сгенерировано', 'success');
                
                // Показать результат
                this.showGeneratedAudio(result);
                
                // Обновить историю и библиотеку
                await this.loadTTSHistory();
                if (this.currentTab === 'library') {
                    await this.loadAudioFiles();
                }
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка генерации', 'error');
            }
        } catch (error) {
            console.error('Generate failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            generateBtn.disabled = false;
            generateBtn.textContent = originalText;
        }
    },
    
    showGeneratedAudio(audio) {
        const modalContent = `
            <div class="tts-result">
                <h4>✅ Речь успешно сгенерирована!</h4>
                
                <div class="audio-player-container">
                    <audio controls src="${audio.download_url || audio.file_path}" style="width: 100%;"></audio>
                </div>
                
                <div class="file-details">
                    <p><strong>Название:</strong> ${this.escapeHtml(audio.name)}</p>
                    <p><strong>Длительность:</strong> ${this.formatDuration(audio.duration)}</p>
                    <p><strong>Размер:</strong> ${this.formatFileSize(audio.file_size)}</p>
                </div>
                
                <div class="modal-actions">
                    <button class="btn btn-primary" onclick="document.querySelector('.close-modal').click()">Закрыть</button>
                    <button class="btn btn-success" id="useInCampaignBtn">Использовать в кампании</button>
                </div>
            </div>
        `;
        
        this.showModal('Результат генерации', modalContent);
        
        document.getElementById('useInCampaignBtn')?.addEventListener('click', () => {
            document.querySelector('.close-modal').click();
            // Переход к кампаниям
            if (typeof switchTab === 'function') {
                switchTab('campaigns');
            }
        });
    },
    
    async uploadFiles(files) {
        const queueContainer = document.getElementById('audioUploadQueue');
        const queueList = document.getElementById('audioQueueList');
        
        queueContainer.style.display = 'block';
        queueList.innerHTML = '';
        
        let successCount = 0;
        let errorCount = 0;
        
        for (const file of files) {
            if (file.size > 50 * 1024 * 1024) {
                showToast(`Файл ${file.name} слишком большой (>50MB)`, 'error');
                errorCount++;
                continue;
            }
            
            if (!file.name.match(/\.(mp3|wav|ogg|m4a|aac|flac)$/i)) {
                showToast(`Файл ${file.name} не поддерживается`, 'error');
                errorCount++;
                continue;
            }
            
            const queueItem = document.createElement('div');
            queueItem.className = 'queue-item';
            queueItem.innerHTML = `
                <div class="queue-item-info">
                    <span class="queue-filename">${this.escapeHtml(file.name)}</span>
                    <span class="queue-size">${this.formatFileSize(file.size)}</span>
                </div>
                <div class="queue-progress">
                    <div class="progress-bar" style="width: 0%"></div>
                </div>
                <div class="queue-status">Загрузка...</div>
            `;
            queueList.appendChild(queueItem);
            
            const formData = new FormData();
            formData.append('name', file.name.replace(/\.[^/.]+$/, ''));
            formData.append('file', file);
            
            const campaignId = document.getElementById('audioUploadCampaign')?.value;
            if (campaignId) formData.append('campaign_id', campaignId);
            
            const description = document.getElementById('audioUploadDescription')?.value;
            if (description) formData.append('description', description);
            
            try {
                const progressBar = queueItem.querySelector('.progress-bar');
                const statusEl = queueItem.querySelector('.queue-status');
                
                // Имитация прогресса
                let progress = 0;
                const progressInterval = setInterval(() => {
                    progress = Math.min(progress + 10, 90);
                    progressBar.style.width = `${progress}%`;
                    statusEl.textContent = `Загрузка: ${progress}%`;
                }, 200);
                
                const response = await authFetch(`${API_BASE}/audio/upload`, {
                    method: 'POST',
                    body: formData,
                    headers: {}
                });
                
                clearInterval(progressInterval);
                
                if (response.ok) {
                    progressBar.style.width = '100%';
                    statusEl.innerHTML = '✅ Загружено';
                    queueItem.classList.add('uploaded');
                    successCount++;
                } else {
                    throw new Error('Upload failed');
                }
            } catch (error) {
                queueItem.querySelector('.queue-status').innerHTML = '❌ Ошибка';
                queueItem.classList.add('error');
                errorCount++;
            }
        }
        
        showToast(`Загружено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'error');
        
        setTimeout(() => {
            queueContainer.style.display = 'none';
        }, 3000);
        
        if (this.currentTab === 'library') {
            await this.loadAudioFiles();
        }
    },
    
    async deleteAudio(id) {
        if (!confirm('Удалить аудиофайл?')) return;
        
        try {
            const response = await authFetch(`${API_BASE}/audio/${id}`, { method: 'DELETE' });
            
            if (response.ok) {
                this.selectedFiles.delete(id);
                showToast('Аудио удалено', 'success');
                await this.loadAudioFiles();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка удаления', 'error');
            }
        } catch (error) {
            console.error('Delete failed:', error);
            showToast('Ошибка сервера', 'error');
        }
    },
    
    async deleteSelectedFiles() {
        if (this.selectedFiles.size === 0) return;
        
        if (!confirm(`Удалить ${this.selectedFiles.size} файл(ов)?`)) return;
        
        let successCount = 0;
        let errorCount = 0;
        
        for (const id of this.selectedFiles) {
            try {
                const response = await authFetch(`${API_BASE}/audio/${id}`, { method: 'DELETE' });
                if (response.ok) {
                    successCount++;
                } else {
                    errorCount++;
                }
            } catch {
                errorCount++;
            }
        }
        
        showToast(`Удалено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'error');
        
        this.selectedFiles.clear();
        await this.loadAudioFiles();
    },
    
    playAudio(url) {
        const audio = new Audio(url);
        
        const modalContent = `
            <div class="audio-player-container">
                <audio controls src="${url}" style="width: 100%;" autoplay></audio>
            </div>
        `;
        
        this.showModal('Воспроизведение', modalContent, {
            onClose: () => audio.pause()
        });
        
        audio.play().catch(e => {
            console.error('Playback failed:', e);
            showToast('Ошибка воспроизведения', 'error');
        });
    },
    
    downloadFile(url, filename) {
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        // Переключение вкладок
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const tabName = e.currentTarget.dataset.tab;
                this.switchTab(tabName);
            });
        });
        
        // Кнопки в заголовке
        document.getElementById('audioUploadBtn')?.addEventListener('click', () => this.switchTab('upload'));
        document.getElementById('audioGenerateBtn')?.addEventListener('click', () => this.switchTab('tts'));
    },
    
    switchTab(tabName) {
        this.currentTab = tabName;
        
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
        
        this.renderActiveTab();
        
        if (tabName === 'tts' || tabName === 'upload') {
            this.loadCampaignsForSelect();
        }
    },
    
    attachLibraryEvents() {
        // Поиск с debounce
        let searchTimeout;
        document.getElementById('audioSearch')?.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.searchQuery = e.target.value;
                this.currentPage = 1;
                this.loadAudioFiles();
            }, 300);
        });
        
        // Сортировка
        document.getElementById('audioSortSelect')?.addEventListener('change', (e) => {
            this.currentPage = 1;
            this.loadAudioFiles();
        });
        
        // Выбрать все
        document.getElementById('audioSelectAll')?.addEventListener('change', (e) => {
            const checked = e.target.checked;
            document.querySelectorAll('.audio-checkbox').forEach(cb => {
                cb.checked = checked;
                const id = parseInt(cb.dataset.id);
                if (checked) {
                    this.selectedFiles.add(id);
                } else {
                    this.selectedFiles.delete(id);
                }
            });
            this.updateDeleteSelectedButton();
        });
        
        // Удалить выбранные
        document.getElementById('audioDeleteSelectedBtn')?.addEventListener('click', () => this.deleteSelectedFiles());
        
        // Обновить
        document.getElementById('audioRefreshBtn')?.addEventListener('click', () => this.loadAudioFiles());
        
        // Загрузка пустого
        document.getElementById('audioUploadEmptyBtn')?.addEventListener('click', () => this.switchTab('upload'));
    },
    
    attachTableRowEvents() {
        // Чекбоксы
        document.querySelectorAll('.audio-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const id = parseInt(e.target.dataset.id);
                if (e.target.checked) {
                    this.selectedFiles.add(id);
                } else {
                    this.selectedFiles.delete(id);
                }
                this.updateDeleteSelectedButton();
                this.updateSelectAllState();
            });
        });
        
        // Воспроизведение
        document.querySelectorAll('.play-audio').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.playAudio(btn.dataset.url);
            });
        });
        
        // Скачивание
        document.querySelectorAll('.download-audio').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.downloadFile(btn.dataset.url, btn.dataset.filename);
            });
        });
        
        // Удаление
        document.querySelectorAll('.delete-audio').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = parseInt(btn.dataset.id);
                this.deleteAudio(id);
            });
        });
    },
    
    attachTTSEvents() {
        const textArea = document.getElementById('ttsText');
        const charCount = document.getElementById('ttsCharCount');
        
        textArea?.addEventListener('input', () => {
            charCount.textContent = textArea.value.length;
        });
        
        document.getElementById('ttsForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.generateAudio();
        });
    },
    
    attachUploadEvents() {
        const dropZone = document.getElementById('audioDropZone');
        const fileInput = document.getElementById('audioFileInput');
        const selectBtn = document.getElementById('audioSelectFilesBtn');
        const uploadForm = document.getElementById('audioUploadForm');
        const cancelBtn = document.getElementById('audioUploadCancelBtn');
        const submitBtn = document.getElementById('audioUploadSubmitBtn');
        
        selectBtn?.addEventListener('click', () => fileInput.click());
        
        fileInput?.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                uploadForm.style.display = 'block';
            }
        });
        
        cancelBtn?.addEventListener('click', () => {
            uploadForm.style.display = 'none';
            fileInput.value = '';
            document.getElementById('audioUploadName').value = '';
            document.getElementById('audioUploadDescription').value = '';
        });
        
        submitBtn?.addEventListener('click', () => {
            const name = document.getElementById('audioUploadName').value;
            const files = fileInput.files;
            
            if (!name) {
                showToast('Введите название', 'warning');
                return;
            }
            
            if (files.length > 0) {
                this.uploadFiles(files);
                uploadForm.style.display = 'none';
                fileInput.value = '';
                document.getElementById('audioUploadName').value = '';
                document.getElementById('audioUploadDescription').value = '';
            }
        });
        
        // Drag & Drop
        dropZone?.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        
        dropZone?.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        });
        
        dropZone?.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                uploadForm.style.display = 'block';
                fileInput.files = files;
                
                // Автозаполнение имени
                const firstName = files[0].name.replace(/\.[^/.]+$/, '');
                document.getElementById('audioUploadName').value = firstName;
            }
        });
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    updateDeleteSelectedButton() {
        const btn = document.getElementById('audioDeleteSelectedBtn');
        if (!btn) return;
        
        if (this.selectedFiles.size > 0) {
            btn.innerHTML = `🗑️ Удалить выбранные (${this.selectedFiles.size})`;
            btn.style.display = 'inline-block';
        } else {
            btn.style.display = 'none';
        }
    },
    
    updateSelectAllState() {
        const selectAll = document.getElementById('audioSelectAll');
        if (!selectAll) return;
        
        const checkboxes = document.querySelectorAll('.audio-checkbox');
        const checkedCount = document.querySelectorAll('.audio-checkbox:checked').length;
        
        selectAll.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
        selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
    },
    
    renderPagination() {
        const container = document.getElementById('audioPagination');
        if (!container || this.totalPages <= 1) {
            if (container) container.innerHTML = '';
            return;
        }
        
        let html = '<div class="pagination">';
        
        if (this.currentPage > 1) {
            html += `<button class="page-btn" data-page="${this.currentPage - 1}">←</button>`;
        } else {
            html += `<button class="page-btn" disabled>←</button>`;
        }
        
        const start = Math.max(1, this.currentPage - 2);
        const end = Math.min(this.totalPages, this.currentPage + 2);
        
        if (start > 1) {
            html += `<button class="page-btn" data-page="1">1</button>`;
            if (start > 2) html += '<span class="page-dots">...</span>';
        }
        
        for (let i = start; i <= end; i++) {
            html += `<button class="page-btn ${i === this.currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }
        
        if (end < this.totalPages) {
            if (end < this.totalPages - 1) html += '<span class="page-dots">...</span>';
            html += `<button class="page-btn" data-page="${this.totalPages}">${this.totalPages}</button>`;
        }
        
        if (this.currentPage < this.totalPages) {
            html += `<button class="page-btn" data-page="${this.currentPage + 1}">→</button>`;
        } else {
            html += `<button class="page-btn" disabled>→</button>`;
        }
        
        html += '</div>';
        
        container.innerHTML = html;
        
        container.querySelectorAll('.page-btn[data-page]').forEach(btn => {
            btn.addEventListener('click', () => {
                this.currentPage = parseInt(btn.dataset.page);
                this.loadAudioFiles();
            });
        });
    },
    
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
        
        return modal;
    },
    
    formatDuration(seconds) {
        if (!seconds) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    },
    
    formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },
    
    formatDate(dateStr) {
        if (!dateStr) return '—';
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).replace(',', '');
    },
    
    getFileIcon(format) {
        const formatLower = (format || '').toLowerCase();
        if (formatLower.includes('wav')) return '🎵';
        if (formatLower.includes('mp3')) return '🎸';
        if (formatLower.includes('ogg')) return '🎤';
        return '🎤';
    },
    
    getFileType(mimeType) {
        if (!mimeType) return 'Аудио';
        const types = {
            'audio/mpeg': 'MP3',
            'audio/wav': 'WAV',
            'audio/ogg': 'OGG',
            'audio/mp4': 'M4A',
            'audio/aac': 'AAC',
            'audio/flac': 'FLAC'
        };
        return types[mimeType] || mimeType.split('/')[1]?.toUpperCase() || 'Аудио';
    },
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Экспорт глобально
window.AudioModule = AudioModule;
App.audio = AudioModule;
