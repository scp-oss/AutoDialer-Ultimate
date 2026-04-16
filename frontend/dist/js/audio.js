// audio.js
(function() {
  const container = document.getElementById('page-content');
  
  // Состояние модуля
  let currentTab = 'library';
  let audioFiles = [];
  let selectedFiles = new Set();
  let currentPage = 1;
  let perPage = 20;
  let totalPages = 1;
  let searchQuery = '';
  let sortField = 'created_at';
  let sortOrder = 'desc';
  
  // TTS состояние
  let ttsProviders = [];
  let ttsVoices = [];
  let selectedProvider = '';
  let selectedVoice = '';
  let selectedLanguage = 'ru-RU';
  
  // Рендер страницы
  const renderAudio = async () => {
    container.innerHTML = `
      <div class="page-header">
        <h2>🎵 Управление аудио</h2>
        <div class="header-actions">
          <button class="btn btn-primary" id="upload-audio-btn">📤 Загрузить файл</button>
          <button class="btn btn-success" id="tts-generate-btn">🔊 Генерация речи</button>
        </div>
      </div>
      
      <!-- Вкладки -->
      <div class="tabs-container">
        <div class="tabs">
          <button class="tab ${currentTab === 'library' ? 'active' : ''}" data-tab="library">
            📚 Библиотека аудио
          </button>
          <button class="tab ${currentTab === 'tts' ? 'active' : ''}" data-tab="tts">
            🤖 Text-to-Speech
          </button>
          <button class="tab ${currentTab === 'upload' ? 'active' : ''}" data-tab="upload">
            ⬆️ Загрузка файлов
          </button>
        </div>
      </div>
      
      <div id="tab-content" class="tab-content"></div>
    `;
    
    // Загрузка провайдеров TTS
    await loadTTSProviders();
    
    // Отрисовка активной вкладки
    await renderActiveTab();
    
    // Привязка обработчиков
    attachEventListeners();
  };
  
  // Отрисовка активной вкладки
  const renderActiveTab = async () => {
    const tabContent = document.getElementById('tab-content');
    
    switch (currentTab) {
      case 'library':
        await renderLibraryTab(tabContent);
        break;
      case 'tts':
        await renderTTSTab(tabContent);
        break;
      case 'upload':
        await renderUploadTab(tabContent);
        break;
    }
  };
  
  // ============ ВКЛАДКА БИБЛИОТЕКИ ============
  const renderLibraryTab = async (container) => {
    container.innerHTML = `
      <div class="library-container">
        <!-- Панель поиска и фильтров -->
        <div class="library-toolbar">
          <div class="search-box">
            <input type="text" 
                   id="search-audio" 
                   class="form-control" 
                   placeholder="🔍 Поиск по названию..."
                   value="${searchQuery}">
          </div>
          
          <div class="toolbar-actions">
            <select id="sort-select" class="form-control">
              <option value="created_at_desc" ${sortField === 'created_at' && sortOrder === 'desc' ? 'selected' : ''}>
                📅 Сначала новые
              </option>
              <option value="created_at_asc" ${sortField === 'created_at' && sortOrder === 'asc' ? 'selected' : ''}>
                📅 Сначала старые
              </option>
              <option value="name_asc" ${sortField === 'name' && sortOrder === 'asc' ? 'selected' : ''}>
                🔤 Название (А-Я)
              </option>
              <option value="name_desc" ${sortField === 'name' && sortOrder === 'desc' ? 'selected' : ''}>
                🔤 Название (Я-А)
              </option>
              <option value="size_desc" ${sortField === 'size' && sortOrder === 'desc' ? 'selected' : ''}>
                📦 Размер (большие)
              </option>
              <option value="size_asc" ${sortField === 'size' && sortOrder === 'asc' ? 'selected' : ''}>
                📦 Размер (маленькие)
              </option>
            </select>
            
            ${selectedFiles.size > 0 ? `
              <button class="btn btn-danger" id="delete-selected-btn">
                🗑️ Удалить выбранные (${selectedFiles.size})
              </button>
            ` : ''}
            
            <button class="btn btn-outline" id="refresh-library-btn">
              🔄 Обновить
            </button>
          </div>
        </div>
        
        <!-- Таблица с файлами -->
        <div class="audio-table-container">
          <table class="table" id="audio-table">
            <thead>
              <tr>
                <th width="40">
                  <input type="checkbox" id="select-all-checkbox">
                </th>
                <th>Название</th>
                <th>Тип</th>
                <th>Длительность</th>
                <th>Размер</th>
                <th>Создан</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody id="audio-tbody">
              <tr><td colspan="7" class="text-center">Загрузка...</td></tr>
            </tbody>
          </table>
        </div>
        
        <!-- Пагинация -->
        <div class="pagination-container" id="library-pagination"></div>
      </div>
    `;
    
    await loadAudioFiles();
    attachLibraryEventListeners();
  };
  
  // Загрузка аудио файлов
  const loadAudioFiles = async () => {
    const tbody = document.getElementById('audio-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center">Загрузка...</td></tr>';
    
    try {
      const params = new URLSearchParams({
        page: currentPage,
        per_page: perPage,
        search: searchQuery,
        sort_by: sortField,
        sort_order: sortOrder
      });
      
      const response = await App.apiGet(`/api/audio?${params.toString()}`);
      
      audioFiles = response.items || response.files || response;
      const pagination = response.pagination || {
        page: currentPage,
        per_page: perPage,
        total: audioFiles.length,
        pages: Math.ceil(audioFiles.length / perPage)
      };
      
      totalPages = pagination.pages;
      
      if (audioFiles.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" class="text-center">
              <div class="empty-state">
                <div class="empty-icon">🎵</div>
                <p>Нет аудиофайлов</p>
                <button class="btn btn-primary" id="upload-empty-btn">Загрузить первый файл</button>
              </div>
            </td>
          </tr>
        `;
        document.getElementById('upload-empty-btn')?.addEventListener('click', () => {
          currentTab = 'upload';
          renderActiveTab();
        });
        return;
      }
      
      tbody.innerHTML = audioFiles.map(file => `
        <tr data-file-id="${file.id}" class="${selectedFiles.has(file.id) ? 'selected' : ''}">
          <td>
            <input type="checkbox" 
                   class="file-checkbox" 
                   data-id="${file.id}"
                   ${selectedFiles.has(file.id) ? 'checked' : ''}>
          </td>
          <td>
            <div class="file-info">
              <div class="file-icon">${getFileIcon(file.mime_type)}</div>
              <div class="file-details">
                <strong>${escapeHtml(file.name)}</strong>
                ${file.description ? `<small>${escapeHtml(file.description)}</small>` : ''}
                ${file.source === 'tts' ? '<span class="badge badge-tts">TTS</span>' : ''}
              </div>
            </div>
          </td>
          <td>${formatFileType(file.mime_type)}</td>
          <td>${formatDuration(file.duration)}</td>
          <td>${formatFileSize(file.size)}</td>
          <td>${formatDateTime(file.created_at)}</td>
          <td>
            <div class="action-buttons">
              <button class="btn btn-sm btn-outline play-audio" 
                      data-id="${file.id}" 
                      data-url="${file.url}"
                      title="Прослушать">
                ▶️
              </button>
              <button class="btn btn-sm btn-outline download-audio" 
                      data-id="${file.id}"
                      title="Скачать">
                📥
              </button>
              <button class="btn btn-sm btn-outline edit-audio" 
                      data-id="${file.id}"
                      title="Редактировать">
                ✏️
              </button>
              <button class="btn btn-sm btn-outline-danger delete-audio" 
                      data-id="${file.id}"
                      title="Удалить">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      `).join('');
      
      // Обновление пагинации
      renderPagination('library-pagination', currentPage, totalPages, (page) => {
        currentPage = page;
        loadAudioFiles();
      });
      
      // Привязка обработчиков к строкам
      attachFileRowEventListeners();
      
    } catch (err) {
      console.error('Ошибка загрузки аудио:', err);
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка загрузки файлов</td></tr>';
      App.showNotification('Не удалось загрузить аудиофайлы', 'error');
    }
  };
  
  // ============ ВКЛАДКА TTS ============
  const renderTTSTab = async (container) => {
    container.innerHTML = `
      <div class="tts-container">
        <div class="row">
          <div class="col-md-6">
            <div class="tts-form-panel">
              <h3>🎤 Генерация речи из текста</h3>
              
              <form id="tts-form">
                <div class="form-group">
                  <label>Провайдер TTS</label>
                  <select id="tts-provider" class="form-control" required>
                    <option value="">Выберите провайдера</option>
                    ${ttsProviders.map(p => `
                      <option value="${p.id}" ${selectedProvider === p.id ? 'selected' : ''}>
                        ${p.name}
                      </option>
                    `).join('')}
                  </select>
                </div>
                
                <div class="form-group">
                  <label>Язык</label>
                  <select id="tts-language" class="form-control">
                    <option value="ru-RU" ${selectedLanguage === 'ru-RU' ? 'selected' : ''}>🇷🇺 Русский</option>
                    <option value="en-US" ${selectedLanguage === 'en-US' ? 'selected' : ''}>🇺🇸 English (US)</option>
                    <option value="en-GB" ${selectedLanguage === 'en-GB' ? 'selected' : ''}>🇬🇧 English (UK)</option>
                    <option value="de-DE" ${selectedLanguage === 'de-DE' ? 'selected' : ''}>🇩🇪 Deutsch</option>
                    <option value="fr-FR" ${selectedLanguage === 'fr-FR' ? 'selected' : ''}>🇫🇷 Français</option>
                    <option value="es-ES" ${selectedLanguage === 'es-ES' ? 'selected' : ''}>🇪🇸 Español</option>
                    <option value="it-IT" ${selectedLanguage === 'it-IT' ? 'selected' : ''}>🇮🇹 Italiano</option>
                  </select>
                </div>
                
                <div class="form-group">
                  <label>Голос</label>
                  <select id="tts-voice" class="form-control" required>
                    <option value="">Сначала выберите провайдера</option>
                  </select>
                  <small class="form-text">Выберите голос из доступных</small>
                </div>
                
                <div class="form-group">
                  <label>Текст для озвучки</label>
                  <textarea id="tts-text" 
                            class="form-control" 
                            rows="6" 
                            placeholder="Введите текст..."
                            maxlength="5000"
                            required></textarea>
                  <small class="form-text">
                    <span id="char-count">0</span>/5000 символов
                  </small>
                </div>
                
                <div class="form-group">
                  <label>Настройки голоса</label>
                  <div class="voice-settings">
                    <div class="setting-item">
                      <label>Скорость</label>
                      <input type="range" 
                             id="tts-speed" 
                             min="0.5" 
                             max="2.0" 
                             step="0.1" 
                             value="1.0">
                      <span id="speed-value">1.0x</span>
                    </div>
                    
                    <div class="setting-item">
                      <label>Тон</label>
                      <input type="range" 
                             id="tts-pitch" 
                             min="-20" 
                             max="20" 
                             step="1" 
                             value="0">
                      <span id="pitch-value">0</span>
                    </div>
                    
                    <div class="setting-item">
                      <label>Громкость</label>
                      <input type="range" 
                             id="tts-volume" 
                             min="0" 
                             max="100" 
                             step="5" 
                             value="100">
                      <span id="volume-value">100%</span>
                    </div>
                  </div>
                </div>
                
                <div class="form-group">
                  <label>Название файла (опционально)</label>
                  <input type="text" 
                         id="tts-filename" 
                         class="form-control" 
                         placeholder="Оставьте пустым для авто-генерации">
                </div>
                
                <div class="form-group">
                  <label>Описание (опционально)</label>
                  <textarea id="tts-description" 
                            class="form-control" 
                            rows="2"
                            placeholder="Добавьте описание..."></textarea>
                </div>
                
                <div class="form-actions">
                  <button type="submit" class="btn btn-success btn-lg">
                    🔊 Сгенерировать речь
                  </button>
                  <button type="button" class="btn btn-outline" id="preview-tts-btn">
                    👂 Предпросмотр
                  </button>
                </div>
              </form>
            </div>
          </div>
          
          <div class="col-md-6">
            <div class="tts-history-panel">
              <h3>📋 История генераций</h3>
              <div id="tts-history-list">
                <p class="text-muted">Загрузка...</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
    
    // Загрузка голосов если провайдер уже выбран
    if (selectedProvider) {
      await loadVoices(selectedProvider);
    }
    
    attachTTSEventListeners();
    loadTTSHistory();
  };
  
  // ============ ВКЛАДКА ЗАГРУЗКИ ============
  const renderUploadTab = async (container) => {
    container.innerHTML = `
      <div class="upload-container">
        <div class="upload-area" id="drop-zone">
          <div class="upload-icon">📁</div>
          <h3>Перетащите файлы сюда</h3>
          <p>или</p>
          <button class="btn btn-primary" id="select-files-btn">Выберите файлы</button>
          <input type="file" 
                 id="file-input" 
                 multiple 
                 accept=".mp3,.wav,.ogg,.m4a,.aac,.flac"
                 style="display: none;">
          <p class="upload-hint">
            Поддерживаемые форматы: MP3, WAV, OGG, M4A, AAC, FLAC<br>
            Максимальный размер: 50 МБ
          </p>
        </div>
        
        <div id="upload-queue" style="display: none;">
          <h3>Очередь загрузки</h3>
          <div class="queue-list" id="queue-list"></div>
        </div>
        
        <div class="upload-tips">
          <h4>💡 Советы</h4>
          <ul>
            <li>Для лучшего качества используйте WAV или FLAC</li>
            <li>Для TTS рекомендуется моно, 16 кГц</li>
            <li>Названия файлов должны быть информативными</li>
            <li>Максимальная длительность: 10 минут</li>
          </ul>
        </div>
      </div>
    `;
    
    attachUploadEventListeners();
  };
  
  // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
  
  // Загрузка провайдеров TTS
  const loadTTSProviders = async () => {
    try {
      ttsProviders = await App.apiGet('/api/audio/tts/providers');
    } catch (err) {
      console.error('Ошибка загрузки провайдеров:', err);
      ttsProviders = [
        { id: 'google', name: 'Google Cloud TTS' },
        { id: 'azure', name: 'Azure Speech Services' },
        { id: 'aws', name: 'Amazon Polly' },
        { id: 'local', name: 'Локальный синтезатор' }
      ];
    }
  };
  
  // Загрузка голосов
  const loadVoices = async (providerId) => {
    try {
      const voiceSelect = document.getElementById('tts-voice');
      voiceSelect.innerHTML = '<option value="">Загрузка голосов...</option>';
      
      const response = await App.apiGet(`/api/audio/tts/voices?provider=${providerId}&language=${selectedLanguage}`);
      ttsVoices = response.voices || response;
      
      if (ttsVoices.length === 0) {
        voiceSelect.innerHTML = '<option value="">Нет доступных голосов</option>';
        return;
      }
      
      voiceSelect.innerHTML = ttsVoices.map(voice => `
        <option value="${voice.id}" ${selectedVoice === voice.id ? 'selected' : ''}>
          ${voice.name} (${voice.gender || 'нейтральный'})
        </option>
      `).join('');
      
    } catch (err) {
      console.error('Ошибка загрузки голосов:', err);
      document.getElementById('tts-voice').innerHTML = '<option value="">Ошибка загрузки</option>';
    }
  };
  
  // Загрузка истории TTS
  const loadTTSHistory = async () => {
    const container = document.getElementById('tts-history-list');
    
    try {
      const history = await App.apiGet('/api/audio?source=tts&limit=10');
      const items = history.items || history;
      
      if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-muted">История пуста</p>';
        return;
      }
      
      container.innerHTML = items.map(item => `
        <div class="history-item">
          <div class="history-info">
            <strong>${escapeHtml(item.name)}</strong>
            <small>${formatDateTime(item.created_at)}</small>
            <p class="history-text">${escapeHtml(item.text_preview || '')}</p>
          </div>
          <div class="history-actions">
            <button class="btn btn-sm btn-outline play-history" data-url="${item.url}">▶️</button>
            <button class="btn btn-sm btn-outline use-history" data-text="${escapeHtml(item.text)}">📋</button>
          </div>
        </div>
      `).join('');
      
      // Привязка обработчиков
      container.querySelectorAll('.play-history').forEach(btn => {
        btn.addEventListener('click', () => playAudio(btn.dataset.url));
      });
      
      container.querySelectorAll('.use-history').forEach(btn => {
        btn.addEventListener('click', () => {
          document.getElementById('tts-text').value = btn.dataset.text;
          updateCharCount();
        });
      });
      
    } catch (err) {
      console.error('Ошибка загрузки истории:', err);
      container.innerHTML = '<p class="text-error">Ошибка загрузки</p>';
    }
  };
  
  // Генерация TTS
  const generateTTS = async (formData) => {
    const submitBtn = document.querySelector('#tts-form button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ Генерация...';
    
    try {
      const data = {
        provider: formData.provider,
        voice: formData.voice,
        language: formData.language,
        text: formData.text,
        speed: parseFloat(formData.speed),
        pitch: parseInt(formData.pitch),
        volume: parseInt(formData.volume),
        filename: formData.filename || null,
        description: formData.description || null
      };
      
      const response = await App.apiPost('/api/audio/tts/generate', data);
      
      App.showNotification('Речь успешно сгенерирована!', 'success');
      
      // Показать результат
      showTTSResult(response);
      
      // Переключиться на библиотеку или обновить
      if (confirm('Речь сгенерирована! Перейти в библиотеку?')) {
        currentTab = 'library';
        await renderActiveTab();
      }
      
    } catch (err) {
      console.error('Ошибка генерации:', err);
      App.showNotification('Ошибка генерации речи: ' + (err.message || 'Неизвестная ошибка'), 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalText;
    }
  };
  
  // Показать результат TTS
  const showTTSResult = (audioFile) => {
    const modalContent = `
      <div class="tts-result">
        <h4>✅ Речь успешно сгенерирована!</h4>
        
        <div class="audio-player-container">
          <audio controls src="${audioFile.url}" style="width: 100%;"></audio>
        </div>
        
        <div class="file-details">
          <p><strong>Название:</strong> ${escapeHtml(audioFile.name)}</p>
          <p><strong>Длительность:</strong> ${formatDuration(audioFile.duration)}</p>
          <p><strong>Размер:</strong> ${formatFileSize(audioFile.size)}</p>
        </div>
        
        <div class="text-preview">
          <h5>Текст:</h5>
          <div class="preview-content">${escapeHtml(audioFile.text_preview || '')}</div>
        </div>
        
        <div class="modal-actions">
          <button class="btn btn-primary" onclick="App.hideModal()">Закрыть</button>
          <button class="btn btn-success" id="use-now-btn">Использовать в кампании</button>
          <button class="btn btn-outline" id="download-tts-btn">Скачать</button>
        </div>
      </div>
    `;
    
    App.showModal('Результат генерации', modalContent);
    
    document.getElementById('download-tts-btn')?.addEventListener('click', () => {
      downloadFile(audioFile.url, audioFile.name);
    });
    
    document.getElementById('use-now-btn')?.addEventListener('click', () => {
      App.hideModal();
      // Переход к созданию кампании с этим аудио
      window.location.hash = '#/campaigns/new';
      // Сохранить ID аудио в sessionStorage
      sessionStorage.setItem('selected_audio_id', audioFile.id);
    });
  };
  
  // Загрузка файлов
  const uploadFiles = async (files) => {
    const queueContainer = document.getElementById('upload-queue');
    const queueList = document.getElementById('queue-list');
    
    queueContainer.style.display = 'block';
    
    for (const file of files) {
      // Проверка размера
      if (file.size > 50 * 1024 * 1024) {
        App.showNotification(`Файл ${file.name} слишком большой (>50MB)`, 'error');
        continue;
      }
      
      const itemId = `upload-${Date.now()}-${Math.random()}`;
      
      // Добавление в очередь
      const queueItem = document.createElement('div');
      queueItem.className = 'queue-item';
      queueItem.id = itemId;
      queueItem.innerHTML = `
        <div class="queue-item-info">
          <span class="queue-filename">${escapeHtml(file.name)}</span>
          <span class="queue-size">${formatFileSize(file.size)}</span>
        </div>
        <div class="queue-progress">
          <div class="progress-bar" style="width: 0%"></div>
        </div>
        <div class="queue-status">Ожидание...</div>
      `;
      queueList.appendChild(queueItem);
      
      // Загрузка
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        const response = await App.apiUpload('/api/audio/upload', formData, (progress) => {
          const progressBar = queueItem.querySelector('.progress-bar');
          const status = queueItem.querySelector('.queue-status');
          progressBar.style.width = `${progress}%`;
          status.textContent = `Загрузка: ${progress}%`;
        });
        
        queueItem.querySelector('.queue-status').innerHTML = '✅ Загружено';
        queueItem.classList.add('uploaded');
        
        App.showNotification(`Файл ${file.name} загружен`, 'success');
        
        // Удаление из очереди через 3 секунды
        setTimeout(() => {
          queueItem.remove();
          if (queueList.children.length === 0) {
            queueContainer.style.display = 'none';
          }
        }, 3000);
        
      } catch (err) {
        queueItem.querySelector('.queue-status').innerHTML = '❌ Ошибка';
        queueItem.classList.add('error');
        App.showNotification(`Ошибка загрузки ${file.name}`, 'error');
      }
    }
  };
  
  // Воспроизведение аудио
  const playAudio = (url) => {
    const audioPlayer = document.createElement('audio');
    audioPlayer.src = url;
    audioPlayer.controls = true;
    audioPlayer.style.width = '100%';
    audioPlayer.autoplay = true;
    
    App.showModal('Воспроизведение', audioPlayer.outerHTML, null, {
      onClose: () => audioPlayer.pause()
    });
  };
  
  // Скачивание файла
  const downloadFile = (url, filename) => {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };
  
  // Удаление файла
  const deleteFile = async (id) => {
    if (!confirm('Удалить файл? Это действие нельзя отменить.')) return;
    
    try {
      await App.apiDelete(`/api/audio/${id}`);
      App.showNotification('Файл удален', 'success');
      
      selectedFiles.delete(id);
      await loadAudioFiles();
      
    } catch (err) {
      console.error('Ошибка удаления:', err);
      App.showNotification('Ошибка удаления файла', 'error');
    }
  };
  
  // Удаление выбранных файлов
  const deleteSelectedFiles = async () => {
    if (selectedFiles.size === 0) return;
    
    if (!confirm(`Удалить ${selectedFiles.size} файл(ов)?`)) return;
    
    try {
      const ids = Array.from(selectedFiles);
      await App.apiPost('/api/audio/bulk-delete', { ids });
      
      App.showNotification(`Удалено ${ids.length} файлов`, 'success');
      selectedFiles.clear();
      await loadAudioFiles();
      
    } catch (err) {
      console.error('Ошибка массового удаления:', err);
      App.showNotification('Ошибка удаления файлов', 'error');
    }
  };
  
  // Редактирование файла
  const editFile = async (id) => {
    try {
      const file = await App.apiGet(`/api/audio/${id}`);
      
      const modalContent = `
        <form id="edit-audio-form">
          <div class="form-group">
            <label>Название</label>
            <input type="text" name="name" class="form-control" value="${escapeHtml(file.name)}" required>
          </div>
          
          <div class="form-group">
            <label>Описание</label>
            <textarea name="description" class="form-control" rows="3">${escapeHtml(file.description || '')}</textarea>
          </div>
          
          <div class="form-group">
            <label>Теги (через запятую)</label>
            <input type="text" name="tags" class="form-control" value="${(file.tags || []).join(', ')}">
          </div>
          
          <div class="form-group">
            <label>
              <input type="checkbox" name="is_public" ${file.is_public ? 'checked' : ''}>
              Доступен всем пользователям
            </label>
          </div>
          
          <button type="submit" class="btn btn-primary">Сохранить</button>
        </form>
      `;
      
      App.showModal('Редактирование аудио', modalContent, async (form) => {
        const data = Object.fromEntries(new FormData(form).entries());
        data.tags = data.tags ? data.tags.split(',').map(t => t.trim()).filter(t => t) : [];
        data.is_public = form.querySelector('[name="is_public"]').checked;
        
        try {
          await App.apiPut(`/api/audio/${id}`, data);
          App.showNotification('Изменения сохранены', 'success');
          App.hideModal();
          await loadAudioFiles();
        } catch (err) {
          App.showNotification('Ошибка сохранения', 'error');
        }
      });
      
    } catch (err) {
      console.error('Ошибка загрузки файла:', err);
      App.showNotification('Ошибка загрузки данных', 'error');
    }
  };
  
  // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
  
  const attachEventListeners = () => {
    // Переключение вкладок
    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', async (e) => {
        const tabName = e.currentTarget.dataset.tab;
        currentTab = tabName;
        
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        e.currentTarget.classList.add('active');
        
        await renderActiveTab();
      });
    });
    
    // Кнопки в заголовке
    document.getElementById('upload-audio-btn')?.addEventListener('click', () => {
      currentTab = 'upload';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelector('[data-tab="upload"]').classList.add('active');
      renderActiveTab();
    });
    
    document.getElementById('tts-generate-btn')?.addEventListener('click', () => {
      currentTab = 'tts';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelector('[data-tab="tts"]').classList.add('active');
      renderActiveTab();
    });
  };
  
  const attachLibraryEventListeners = () => {
    // Поиск
    let searchTimeout;
    document.getElementById('search-audio')?.addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        searchQuery = e.target.value;
        currentPage = 1;
        loadAudioFiles();
      }, 300);
    });
    
    // Сортировка
    document.getElementById('sort-select')?.addEventListener('change', (e) => {
      const [field, order] = e.target.value.split('_');
      sortField = field;
      sortOrder = order;
      currentPage = 1;
      loadAudioFiles();
    });
    
    // Выбрать все
    document.getElementById('select-all-checkbox')?.addEventListener('change', (e) => {
      const checked = e.target.checked;
      document.querySelectorAll('.file-checkbox').forEach(cb => {
        cb.checked = checked;
        const id = parseInt(cb.dataset.id);
        if (checked) {
          selectedFiles.add(id);
        } else {
          selectedFiles.delete(id);
        }
      });
      
      // Обновить кнопку удаления
      updateDeleteButton();
    });
    
    // Удалить выбранные
    document.getElementById('delete-selected-btn')?.addEventListener('click', deleteSelectedFiles);
    
    // Обновить
    document.getElementById('refresh-library-btn')?.addEventListener('click', loadAudioFiles);
  };
  
  const attachFileRowEventListeners = () => {
    // Чекбоксы
    document.querySelectorAll('.file-checkbox').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const id = parseInt(e.target.dataset.id);
        if (e.target.checked) {
          selectedFiles.add(id);
        } else {
          selectedFiles.delete(id);
        }
        updateDeleteButton();
        
        // Обновить "выбрать все"
        const allChecked = document.querySelectorAll('.file-checkbox:checked').length === audioFiles.length;
        document.getElementById('select-all-checkbox').checked = allChecked;
      });
    });
    
    // Воспроизведение
    document.querySelectorAll('.play-audio').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const url = e.currentTarget.dataset.url;
        playAudio(url);
      });
    });
    
    // Скачивание
    document.querySelectorAll('.download-audio').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const id = e.currentTarget.dataset.id;
        const file = audioFiles.find(f => f.id == id);
        if (file) {
          downloadFile(file.url, file.name);
        }
      });
    });
    
    // Редактирование
    document.querySelectorAll('.edit-audio').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const id = e.currentTarget.dataset.id;
        editFile(id);
      });
    });
    
    // Удаление
    document.querySelectorAll('.delete-audio').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const id = e.currentTarget.dataset.id;
        deleteFile(id);
      });
    });
  };
  
  const attachTTSEventListeners = () => {
    // Выбор провайдера
    document.getElementById('tts-provider')?.addEventListener('change', async (e) => {
      selectedProvider = e.target.value;
      if (selectedProvider) {
        await loadVoices(selectedProvider);
      }
    });
    
    // Выбор языка
    document.getElementById('tts-language')?.addEventListener('change', async (e) => {
      selectedLanguage = e.target.value;
      if (selectedProvider) {
        await loadVoices(selectedProvider);
      }
    });
    
    // Выбор голоса
    document.getElementById('tts-voice')?.addEventListener('change', (e) => {
      selectedVoice = e.target.value;
    });
    
    // Подсчет символов
    const textArea = document.getElementById('tts-text');
    textArea?.addEventListener('input', updateCharCount);
    
    // Слайдеры
    document.getElementById('tts-speed')?.addEventListener('input', (e) => {
      document.getElementById('speed-value').textContent = e.target.value + 'x';
    });
    
    document.getElementById('tts-pitch')?.addEventListener('input', (e) => {
      document.getElementById('pitch-value').textContent = e.target.value;
    });
    
    document.getElementById('tts-volume')?.addEventListener('input', (e) => {
      document.getElementById('volume-value').textContent = e.target.value + '%';
    });
    
    // Отправка формы
    document.getElementById('tts-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const formData = {
        provider: document.getElementById('tts-provider').value,
        voice: document.getElementById('tts-voice').value,
        language: document.getElementById('tts-language').value,
        text: document.getElementById('tts-text').value,
        speed: document.getElementById('tts-speed').value,
        pitch: document.getElementById('tts-pitch').value,
        volume: document.getElementById('tts-volume').value,
        filename: document.getElementById('tts-filename').value,
        description: document.getElementById('tts-description').value
      };
      
      await generateTTS(formData);
    });
    
    // Предпросмотр
    document.getElementById('preview-tts-btn')?.addEventListener('click', async () => {
      const text = document.getElementById('tts-text').value;
      if (!text) {
        App.showNotification('Введите текст для предпросмотра', 'warning');
        return;
      }
      
      try {
        const response = await App.apiPost('/api/audio/tts/preview', {
          provider: selectedProvider,
          voice: selectedVoice,
          text: text.substring(0, 200) // Ограничение для предпросмотра
        });
        
        playAudio(response.url);
      } catch (err) {
        App.showNotification('Ошибка предпросмотра', 'error');
      }
    });
  };
  
  const attachUploadEventListeners = () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const selectBtn = document.getElementById('select-files-btn');
    
    // Выбор файлов
    selectBtn?.addEventListener('click', () => {
      fileInput.click();
    });
    
    fileInput?.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        uploadFiles(e.target.files);
        fileInput.value = '';
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
        uploadFiles(files);
      }
    });
  };
  
  // Обновление кнопки удаления выбранных
  const updateDeleteButton = () => {
    const btn = document.getElementById('delete-selected-btn');
    if (btn) {
      if (selectedFiles.size > 0) {
        btn.textContent = `🗑️ Удалить выбранные (${selectedFiles.size})`;
        btn.style.display = 'inline-block';
      } else {
        btn.style.display = 'none';
      }
    }
  };
  
  // Обновление счетчика символов
  const updateCharCount = () => {
    const textArea = document.getElementById('tts-text');
    const counter = document.getElementById('char-count');
    if (textArea && counter) {
      counter.textContent = textArea.value.length;
    }
  };
  
  // ============ УТИЛИТЫ ============
  
  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    
    return `${size.toFixed(1)} ${units[unitIndex]}`;
  };
  
  const formatDuration = (seconds) => {
    if (!seconds) return '0:00';
    
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };
  
  const formatDateTime = (dateStr) => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };
  
  const formatFileType = (mimeType) => {
    const types = {
      'audio/mpeg': 'MP3',
      'audio/wav': 'WAV',
      'audio/ogg': 'OGG',
      'audio/mp4': 'M4A',
      'audio/aac': 'AAC',
      'audio/flac': 'FLAC'
    };
    return types[mimeType] || mimeType?.split('/')[1]?.toUpperCase() || 'Неизвестно';
  };
  
  const getFileIcon = (mimeType) => {
    if (mimeType?.includes('wav')) return '🎵';
    if (mimeType?.includes('mp3')) return '🎸';
    return '🎤';
  };
  
  const escapeHtml = (text) => {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  };
  
  const renderPagination = (containerId, current, total, onPageChange) => {
    const container = document.getElementById(containerId);
    if (!container || total <= 1) {
      if (container) container.innerHTML = '';
      return;
    }
    
    let html = '<div class="pagination">';
    
    // Предыдущая
    html += `<button class="page-btn" ${current === 1 ? 'disabled' : ''} data-page="${current - 1}">←</button>`;
    
    // Страницы
    const start = Math.max(1, current - 2);
    const end = Math.min(total, current + 2);
    
    if (start > 1) {
      html += `<button class="page-btn" data-page="1">1</button>`;
      if (start > 2) html += '<span class="page-dots">...</span>';
    }
    
    for (let i = start; i <= end; i++) {
      html += `<button class="page-btn ${i === current ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }
    
    if (end < total) {
      if (end < total - 1) html += '<span class="page-dots">...</span>';
      html += `<button class="page-btn" data-page="${total}">${total}</button>`;
    }
    
    // Следующая
    html += `<button class="page-btn" ${current === total ? 'disabled' : ''} data-page="${current + 1}">→</button>`;
    
    html += '</div>';
    
    container.innerHTML = html;
    
    // Привязка событий
    container.querySelectorAll('.page-btn[data-page]').forEach(btn => {
      btn.addEventListener('click', () => {
        const page = parseInt(btn.dataset.page);
        if (!isNaN(page)) onPageChange(page);
      });
    });
  };
  
  // Экспорт
  window.AudioPage = { render: renderAudio };
})();
