// audio.js - Модуль управления аудиофайлами и TTS (Piper)
// Адаптировано под реальный проект AutoDialer Ultimate

(function() {
  const container = document.getElementById('page-content');
  
  // Состояние модуля
  let currentTab = 'library';
  let audioFiles = [];
  let selectedFiles = new Set();
  let offset = 0;
  const limit = 20;
  let totalRecords = 0;
  let searchQuery = '';
  let isGenerating = false;
  
  // Доступные голоса Piper (устанавливаются в 06_tts_install.sh)
  const availableVoices = [
    { id: 'denis', name: 'Денис (мужской, русский)', lang: 'ru' },
    { id: 'irina', name: 'Ирина (женский, русский)', lang: 'ru' },
    { id: 'en_US-lessac', name: 'Lessac (женский, английский)', lang: 'en' }
  ];
  
  // Рендер страницы
  const renderAudio = async () => {
    container.innerHTML = `
      <div class="page-header">
        <h2>🎵 Управление аудио</h2>
        <div class="header-actions">
          <button class="btn btn-primary" id="upload-audio-btn">
            <span class="icon">📤</span> Загрузить файл
          </button>
          <button class="btn btn-success" id="tts-generate-btn">
            <span class="icon">🔊</span> Генерация речи (Piper)
          </button>
        </div>
      </div>
      
      <div class="tabs-container">
        <div class="tabs">
          <button class="tab ${currentTab === 'library' ? 'active' : ''}" data-tab="library">
            📚 Библиотека
          </button>
          <button class="tab ${currentTab === 'tts' ? 'active' : ''}" data-tab="tts">
            🤖 Text-to-Speech
          </button>
          <button class="tab ${currentTab === 'upload' ? 'active' : ''}" data-tab="upload">
            ⬆️ Загрузка
          </button>
        </div>
      </div>
      
      <div id="tab-content" class="tab-content"></div>
    `;
    
    await renderActiveTab();
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
        <div class="library-toolbar">
          <div class="search-box">
            <input type="text" 
                   id="search-audio" 
                   class="form-control" 
                   placeholder="🔍 Поиск по названию..."
                   value="${searchQuery}">
          </div>
          
          <div class="toolbar-actions">
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
                <th>Источник</th>
                <th>Создан</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody id="audio-tbody">
              <tr><td colspan="8" class="text-center">Загрузка...</td></tr>
            </tbody>
          </table>
        </div>
        
        <div class="pagination-container">
          <div class="pagination-info">
            Показано <span id="showing-start">${offset + 1}</span>-<span id="showing-end">${Math.min(offset + limit, totalRecords)}</span> 
            из <span id="total-records">${totalRecords}</span>
          </div>
          <div class="pagination-controls">
            <button class="btn btn-sm btn-outline" id="prev-page-btn" ${offset === 0 ? 'disabled' : ''}>
              ◀️ Назад
            </button>
            <button class="btn btn-sm btn-outline" id="next-page-btn" ${offset + limit >= totalRecords ? 'disabled' : ''}>
              Вперед ▶️
            </button>
          </div>
        </div>
      </div>
    `;
    
    await loadAudioFiles();
    attachLibraryEventListeners();
  };
  
  // Загрузка аудио файлов из API
  const loadAudioFiles = async () => {
    const tbody = document.getElementById('audio-tbody');
    tbody.innerHTML = '<tr><td colspan="8" class="text-center">Загрузка...</td></tr>';
    
    try {
      const params = new URLSearchParams({
        skip: offset,
        limit: limit
      });
      
      if (searchQuery) {
        params.append('search', searchQuery);
      }
      
      const response = await App.apiGet(`/api/audio?${params.toString()}`);
      
      // Обработка ответа (может быть массив или объект с items)
      audioFiles = Array.isArray(response) ? response : (response.items || []);
      totalRecords = response.total || audioFiles.length;
      
      // Обновление информации о пагинации
      updatePaginationInfo();
      
      if (audioFiles.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="8" class="text-center">
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
      
      // Рендер таблицы
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
              </div>
            </div>
          </td>
          <td>${formatFileType(file.mime_type)}</td>
          <td>${formatDuration(file.duration)}</td>
          <td>${formatFileSize(file.size)}</td>
          <td>
            ${file.source === 'tts' ? '<span class="badge badge-tts">TTS</span>' : '<span class="badge badge-upload">Загрузка</span>'}
          </td>
          <td>${formatDateTime(file.created_at)}</td>
          <td>
            <div class="action-buttons">
              <button class="btn btn-sm btn-outline play-audio" 
                      data-url="${file.url || file.file_path}"
                      title="Прослушать">
                ▶️
              </button>
              <button class="btn btn-sm btn-outline download-audio" 
                      data-url="${file.url || file.file_path}"
                      data-filename="${escapeHtml(file.name)}"
                      title="Скачать">
                📥
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
      
      // Привязка обработчиков к строкам
      attachFileRowEventListeners();
      
    } catch (err) {
      console.error('Ошибка загрузки аудио:', err);
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки файлов</td></tr>';
      App.showNotification('Не удалось загрузить аудиофайлы', 'error');
    }
  };
  
  // ============ ВКЛАДКА TTS ============
  const renderTTSTab = async (container) => {
    container.innerHTML = `
      <div class="tts-container">
        <div class="row">
          <div class="col-md-7">
            <div class="tts-form-panel">
              <h3>🎤 Генерация речи (Piper TTS)</h3>
              <p class="text-muted">Локальный синтезатор речи, работает офлайн</p>
              
              <form id="tts-form">
                <div class="form-group">
                  <label>Голос</label>
                  <select id="tts-voice" class="form-control" required>
                    ${availableVoices.map(v => `
                      <option value="${v.id}">${v.name}</option>
                    `).join('')}
                  </select>
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
                  <button type="submit" class="btn btn-success btn-lg" id="generate-btn">
                    🔊 Сгенерировать речь
                  </button>
                </div>
              </form>
            </div>
          </div>
          
          <div class="col-md-5">
            <div class="tts-history-panel">
              <h3>📋 Последние генерации</h3>
              <div id="tts-history-list">
                <p class="text-muted">Загрузка...</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
    
    attachTTSEventListeners();
    loadTTSHistory();
  };
  
  // Загрузка истории TTS генераций
  const loadTTSHistory = async () => {
    const container = document.getElementById('tts-history-list');
    
    try {
      const response = await App.apiGet('/api/audio?source=tts&limit=5');
      const items = Array.isArray(response) ? response : (response.items || []);
      
      if (items.length === 0) {
        container.innerHTML = '<p class="text-muted">История пуста</p>';
        return;
      }
      
      container.innerHTML = items.map(item => `
        <div class="history-item">
          <div class="history-info">
            <strong>${escapeHtml(item.name)}</strong>
            <small>${formatDateTime(item.created_at)}</small>
            ${item.tts_text ? `
              <p class="history-text">${escapeHtml(item.tts_text.substring(0, 100))}${item.tts_text.length > 100 ? '...' : ''}</p>
            ` : ''}
          </div>
          <div class="history-actions">
            <button class="btn btn-sm btn-outline play-history" data-url="${item.url || item.file_path}">▶️</button>
            <button class="btn btn-sm btn-outline use-history" data-text="${escapeHtml(item.tts_text || '')}">📋</button>
          </div>
        </div>
      `).join('');
      
      // Привязка обработчиков
      container.querySelectorAll('.play-history').forEach(btn => {
        btn.addEventListener('click', () => playAudio(btn.dataset.url));
      });
      
      container.querySelectorAll('.use-history').forEach(btn => {
        btn.addEventListener('click', () => {
          const textArea = document.getElementById('tts-text');
          if (textArea) {
            textArea.value = btn.dataset.text;
            updateCharCount();
          }
        });
      });
      
    } catch (err) {
      console.error('Ошибка загрузки истории:', err);
      container.innerHTML = '<p class="text-error">Ошибка загрузки</p>';
    }
  };
  
  // Генерация TTS
  const generateTTS = async (formData) => {
    const generateBtn = document.getElementById('generate-btn');
    const originalText = generateBtn.textContent;
    
    try {
      generateBtn.disabled = true;
      generateBtn.textContent = '⏳ Генерация...';
      
      const data = {
        text: formData.text,
        voice: formData.voice
      };
      
      if (formData.filename) {
        data.filename = formData.filename;
      }
      
      if (formData.description) {
        data.description = formData.description;
      }
      
      const response = await App.apiPost('/api/audio/generate', data);
      
      App.showNotification('Речь успешно сгенерирована!', 'success');
      
      // Показать результат
      await showTTSResult(response);
      
      // Сброс формы
      document.getElementById('tts-form').reset();
      updateCharCount();
      
    } catch (err) {
      console.error('Ошибка генерации:', err);
      App.showNotification('Ошибка генерации речи: ' + (err.message || 'Неизвестная ошибка'), 'error');
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = originalText;
    }
  };
  
  // Показать результат TTS
  const showTTSResult = async (audioFile) => {
    const modalContent = `
      <div class="tts-result">
        <h4>✅ Речь успешно сгенерирована!</h4>
        
        <div class="audio-player-container">
          <audio controls src="${audioFile.url || audioFile.file_path}" style="width: 100%;"></audio>
        </div>
        
        <div class="file-details">
          <p><strong>Название:</strong> ${escapeHtml(audioFile.name)}</p>
          <p><strong>Голос:</strong> ${getVoiceName(audioFile.tts_voice)}</p>
          <p><strong>Длительность:</strong> ${formatDuration(audioFile.duration)}</p>
          <p><strong>Размер:</strong> ${formatFileSize(audioFile.size)}</p>
        </div>
        
        ${audioFile.tts_text ? `
          <div class="text-preview">
            <h5>Текст:</h5>
            <div class="preview-content">${escapeHtml(audioFile.tts_text)}</div>
          </div>
        ` : ''}
        
        <div class="modal-actions">
          <button class="btn btn-primary" onclick="App.hideModal()">Закрыть</button>
          <button class="btn btn-success" id="use-in-campaign-btn">Использовать в кампании</button>
        </div>
      </div>
    `;
    
    App.showModal('Результат генерации', modalContent);
    
    document.getElementById('use-in-campaign-btn')?.addEventListener('click', () => {
      App.hideModal();
      window.location.hash = '#/campaigns';
    });
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
      </div>
    `;
    
    attachUploadEventListeners();
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
    // Поиск с debounce
    let searchTimeout;
    document.getElementById('search-audio')?.addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        searchQuery = e.target.value;
        offset = 0;
        loadAudioFiles();
      }, 300);
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
      updateDeleteButton();
    });
    
    // Удалить выбранные
    document.getElementById('delete-selected-btn')?.addEventListener('click', deleteSelectedFiles);
    
    // Обновить
    document.getElementById('refresh-library-btn')?.addEventListener('click', loadAudioFiles);
    
    // Пагинация
    document.getElementById('prev-page-btn')?.addEventListener('click', () => {
      if (offset >= limit) {
        offset -= limit;
        loadAudioFiles();
      }
    });
    
    document.getElementById('next-page-btn')?.addEventListener('click', () => {
      if (offset + limit < totalRecords) {
        offset += limit;
        loadAudioFiles();
      }
    });
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
        const selectAll = document.getElementById('select-all-checkbox');
        if (selectAll) selectAll.checked = allChecked;
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
      btn.addEventListener('click', (e) => {
        const url = e.currentTarget.dataset.url;
        const filename = e.currentTarget.dataset.filename;
        downloadFile(url, filename);
      });
    });
    
    // Удаление
    document.querySelectorAll('.delete-audio').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const id = parseInt(e.currentTarget.dataset.id);
        deleteFile(id);
      });
    });
  };
  
  const attachTTSEventListeners = () => {
    const textArea = document.getElementById('tts-text');
    textArea?.addEventListener('input', updateCharCount);
    
    document.getElementById('tts-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const formData = {
        voice: document.getElementById('tts-voice').value,
        text: document.getElementById('tts-text').value,
        filename: document.getElementById('tts-filename').value,
        description: document.getElementById('tts-description').value
      };
      
      await generateTTS(formData);
    });
  };
  
  const attachUploadEventListeners = () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const selectBtn = document.getElementById('select-files-btn');
    
    selectBtn?.addEventListener('click', () => fileInput.click());
    
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
  
  // Загрузка файлов
  const uploadFiles = async (files) => {
    const queueContainer = document.getElementById('upload-queue');
    const queueList = document.getElementById('queue-list');
    
    queueContainer.style.display = 'block';
    queueList.innerHTML = '';
    
    let successCount = 0;
    let errorCount = 0;
    
    for (const file of files) {
      if (file.size > 50 * 1024 * 1024) {
        App.showNotification(`Файл ${file.name} слишком большой (>50MB)`, 'error');
        errorCount++;
        continue;
      }
      
      const queueItem = document.createElement('div');
      queueItem.className = 'queue-item';
      queueItem.innerHTML = `
        <div class="queue-item-info">
          <span class="queue-filename">${escapeHtml(file.name)}</span>
          <span class="queue-size">${formatFileSize(file.size)}</span>
        </div>
        <div class="queue-progress">
          <div class="progress-bar" style="width: 0%"></div>
        </div>
        <div class="queue-status">Загрузка...</div>
      `;
      queueList.appendChild(queueItem);
      
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        const progressBar = queueItem.querySelector('.progress-bar');
        const statusEl = queueItem.querySelector('.queue-status');
        
        const response = await App.apiUpload('/api/audio/upload', formData, (progress) => {
          progressBar.style.width = `${progress}%`;
          statusEl.textContent = `Загрузка: ${progress}%`;
        });
        
        statusEl.innerHTML = '✅ Загружено';
        queueItem.classList.add('uploaded');
        successCount++;
        
      } catch (err) {
        queueItem.querySelector('.queue-status').innerHTML = '❌ Ошибка';
        queueItem.classList.add('error');
        errorCount++;
      }
    }
    
    App.showNotification(`Загружено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'error');
    
    // Скрыть очередь через 3 секунды
    setTimeout(() => {
      queueContainer.style.display = 'none';
    }, 3000);
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
    
    let successCount = 0;
    let errorCount = 0;
    
    for (const id of selectedFiles) {
      try {
        await App.apiDelete(`/api/audio/${id}`);
        successCount++;
      } catch (err) {
        errorCount++;
      }
    }
    
    App.showNotification(`Удалено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'error');
    
    selectedFiles.clear();
    await loadAudioFiles();
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
  
  // ============ УТИЛИТЫ ============
  
  const updatePaginationInfo = () => {
    const startEl = document.getElementById('showing-start');
    const endEl = document.getElementById('showing-end');
    const totalEl = document.getElementById('total-records');
    const prevBtn = document.getElementById('prev-page-btn');
    const nextBtn = document.getElementById('next-page-btn');
    
    if (startEl) startEl.textContent = totalRecords > 0 ? offset + 1 : 0;
    if (endEl) endEl.textContent = Math.min(offset + limit, totalRecords);
    if (totalEl) totalEl.textContent = totalRecords;
    
    if (prevBtn) prevBtn.disabled = offset === 0;
    if (nextBtn) nextBtn.disabled = offset + limit >= totalRecords;
  };
  
  const updateDeleteButton = () => {
    const btn = document.getElementById('delete-selected-btn');
    if (!btn) return;
    
    if (selectedFiles.size > 0) {
      btn.innerHTML = `🗑️ Удалить выбранные (${selectedFiles.size})`;
      btn.style.display = 'inline-block';
    } else {
      btn.style.display = 'none';
    }
  };
  
  const updateCharCount = () => {
    const textArea = document.getElementById('tts-text');
    const counter = document.getElementById('char-count');
    if (textArea && counter) {
      counter.textContent = textArea.value.length;
    }
  };
  
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
    return types[mimeType] || mimeType?.split('/')[1]?.toUpperCase() || 'Аудио';
  };
  
  const getFileIcon = (mimeType) => {
    if (mimeType?.includes('wav')) return '🎵';
    if (mimeType?.includes('mp3')) return '🎸';
    return '🎤';
  };
  
  const getVoiceName = (voiceId) => {
    const voice = availableVoices.find(v => v.id === voiceId);
    return voice ? voice.name : voiceId || 'Неизвестно';
  };
  
  const escapeHtml = (text) => {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  };
  
  // Экспорт
  window.AudioPage = { render: renderAudio };
})();
