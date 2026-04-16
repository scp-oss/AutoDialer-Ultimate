// incoming.js - Модуль входящих звонков с автотранскрибацией
// Адаптировано под реальный проект AutoDialer Ultimate

(function() {
  const container = document.getElementById('page-content');
  
  // Состояние модуля
  let incomingCalls = [];
  let currentPage = 1;
  let perPage = 20;
  let totalPages = 1;
  let totalRecords = 0;
  let autoRefreshInterval = null;
  let processingCalls = new Set();
  
  // Рендер страницы
  const renderIncoming = async () => {
    container.innerHTML = `
      <div class="page-header">
        <h2>📞 Входящие звонки</h2>
        <div class="header-actions">
          <button class="btn btn-outline" id="refresh-btn" title="Обновить">
            🔄 Обновить
          </button>
        </div>
      </div>
      
      <!-- Таблица -->
      <div class="incoming-table-container">
        <table class="table incoming-table" id="incoming-table">
          <thead>
            <tr>
              <th>Дата/Время</th>
              <th>Номер</th>
              <th>Длит.</th>
              <th>Текст</th>
              <th>Запись</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody id="incoming-tbody">
            <tr><td colspan="6" class="text-center">Загрузка...</td></tr>
          </tbody>
        </table>
      </div>
      
      <!-- Мобильные карточки -->
      <div class="incoming-cards" id="incoming-cards" style="display: none;"></div>
      
      <!-- Пагинация -->
      <div class="pagination-container">
        <div class="pagination-info">
          Показано <span id="showing-start">0</span>-<span id="showing-end">0</span> 
          из <span id="total-records">0</span>
        </div>
        <div class="pagination-controls">
          <button class="btn btn-sm btn-outline" id="first-page" disabled>⏮️</button>
          <button class="btn btn-sm btn-outline" id="prev-page" disabled>◀️</button>
          <span class="page-indicator">
            Стр. <span id="current-page">1</span> из <span id="total-pages">1</span>
          </span>
          <button class="btn btn-sm btn-outline" id="next-page" disabled>▶️</button>
          <button class="btn btn-sm btn-outline" id="last-page" disabled>⏭️</button>
        </div>
      </div>
      
      <!-- Модальное окно для деталей -->
      <div id="call-details-modal" class="modal" style="display: none;">
        <div class="modal-content modal-lg">
          <div class="modal-header">
            <h3>Детали входящего звонка</h3>
            <button class="close-modal">&times;</button>
          </div>
          <div class="modal-body" id="call-details-content"></div>
        </div>
      </div>
    `;
    
    // Проверка мобильного устройства
    checkMobileView();
    window.addEventListener('resize', checkMobileView);
    
    // Загрузка данных
    await loadIncomingCalls();
    
    // Привязка обработчиков
    attachEventListeners();
    
    // Запуск автообновления для отслеживания статусов
    startAutoRefresh();
  };
  
  // Проверка мобильного вида
  const checkMobileView = () => {
    const isMobile = window.innerWidth < 768;
    document.querySelector('.incoming-table-container').style.display = isMobile ? 'none' : 'block';
    document.getElementById('incoming-cards').style.display = isMobile ? 'block' : 'none';
    
    if (isMobile) {
      renderMobileCards();
    }
  };
  
  // Загрузка входящих звонков
  const loadIncomingCalls = async () => {
    const tbody = document.getElementById('incoming-tbody');
    const cardsContainer = document.getElementById('incoming-cards');
    
    const loadingHtml = '<tr><td colspan="6" class="text-center">Загрузка...</td></tr>';
    if (tbody) tbody.innerHTML = loadingHtml;
    if (cardsContainer) cardsContainer.innerHTML = '<div class="text-center">Загрузка...</div>';
    
    try {
      const params = new URLSearchParams({
        skip: (currentPage - 1) * perPage,
        limit: perPage
      });
      
      const response = await App.apiGet(`/api/incoming-calls?${params.toString()}`);
      
      incomingCalls = response.items || response.calls || [];
      totalRecords = response.total || incomingCalls.length;
      totalPages = Math.ceil(totalRecords / perPage) || 1;
      
      // Обновление пагинации
      updatePagination();
      
      if (incomingCalls.length === 0) {
        const emptyHtml = `
          <tr>
            <td colspan="6" class="text-center">
              <div class="empty-state">
                <div class="empty-icon">📞</div>
                <p>Нет входящих звонков</p>
              </div>
            </td>
          </tr>
        `;
        if (tbody) tbody.innerHTML = emptyHtml;
        if (cardsContainer) {
          cardsContainer.innerHTML = `
            <div class="empty-state">
              <div class="empty-icon">📞</div>
              <p>Нет входящих звонков</p>
            </div>
          `;
        }
        return;
      }
      
      // Рендер таблицы
      if (tbody) {
        tbody.innerHTML = incomingCalls.map(call => renderTableRow(call)).join('');
      }
      
      // Рендер мобильных карточек
      renderMobileCards();
      
      // Привязка обработчиков к строкам
      attachRowEventListeners();
      
    } catch (err) {
      console.error('Ошибка загрузки входящих звонков:', err);
      const errorHtml = '<tr><td colspan="6" class="text-center text-error">Ошибка загрузки данных</td></tr>';
      if (tbody) tbody.innerHTML = errorHtml;
      if (cardsContainer) cardsContainer.innerHTML = '<div class="text-center text-error">Ошибка загрузки</div>';
      App.showNotification('Не удалось загрузить входящие звонки', 'error');
    }
  };
  
  // Рендер строки таблицы
  const renderTableRow = (call) => {
    const status = call.transcription_status || 'pending';
    const hasTranscription = status === 'completed' && call.transcription;
    
    return `
      <tr data-call-id="${call.id}" class="incoming-row ${status}">
        <td class="date-cell">${formatDateTime(call.call_date || call.created_at)}</td>
        <td class="phone-cell">
          <span class="phone-number">${formatPhoneNumber(call.caller_number)}</span>
        </td>
        <td class="duration-cell">${formatDuration(call.duration)}</td>
        <td class="text-cell">
          ${getTranscriptionDisplay(call)}
        </td>
        <td class="audio-cell">
          ${renderAudioPlayer(call)}
        </td>
        <td class="actions-cell">
          <div class="action-buttons">
            ${getActionButtons(call)}
          </div>
        </td>
      </tr>
    `;
  };
  
  // Отображение транскрибации
  const getTranscriptionDisplay = (call) => {
    const status = call.transcription_status || 'pending';
    
    switch (status) {
      case 'pending':
        return '<span class="transcription-status pending">⏳ pending</span>';
      case 'processing':
        processingCalls.add(call.id);
        return '<span class="transcription-status processing">⏳ processing</span>';
      case 'completed':
        processingCalls.delete(call.id);
        if (call.transcription) {
          const text = call.transcription;
          const truncated = text.length > 50 ? text.substring(0, 47) + '...' : text;
          return `<span class="transcription-text" title="${escapeHtml(text)}">${escapeHtml(truncated)}</span>`;
        }
        return '<span class="transcription-status completed">✅ Готово</span>';
      case 'failed':
        processingCalls.delete(call.id);
        return '<span class="transcription-status failed">❌ failed</span>';
      default:
        return '<span class="transcription-status">—</span>';
    }
  };
  
  // Рендер аудиоплеера
  const renderAudioPlayer = (call) => {
    if (!call.recording_path && !call.recording_url) {
      return '<span class="no-recording">—</span>';
    }
    
    const audioUrl = call.recording_url || `/api/incoming-calls/${call.id}/recording`;
    const duration = formatDuration(call.duration);
    
    return `
      <div class="mini-audio-player">
        <button class="play-pause-btn" data-audio-url="${audioUrl}" title="Воспроизвести">▶️</button>
        <span class="audio-duration">${duration}</span>
      </div>
    `;
  };
  
  // Кнопки действий
  const getActionButtons = (call) => {
    const status = call.transcription_status || 'pending';
    const buttons = [];
    
    // Кнопка скачивания (всегда)
    buttons.push(`
      <button class="btn btn-sm btn-outline download-call" 
              data-id="${call.id}" 
              title="Скачать запись">
        ⬇
      </button>
    `);
    
    // Кнопка удаления (всегда)
    buttons.push(`
      <button class="btn btn-sm btn-outline-danger delete-call" 
              data-id="${call.id}" 
              title="Удалить">
        🗑
      </button>
    `);
    
    return buttons.join('');
  };
  
  // Рендер мобильных карточек
  const renderMobileCards = () => {
    const container = document.getElementById('incoming-cards');
    if (!container) return;
    
    if (incomingCalls.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📞</div>
          <p>Нет входящих звонков</p>
        </div>
      `;
      return;
    }
    
    container.innerHTML = incomingCalls.map(call => {
      const status = call.transcription_status || 'pending';
      const hasTranscription = status === 'completed' && call.transcription;
      
      return `
        <div class="incoming-card" data-call-id="${call.id}">
          <div class="card-header">
            <span class="card-date">${formatDateShort(call.call_date || call.created_at)}</span>
            <span class="card-phone">📱 ${formatPhoneNumber(call.caller_number)}</span>
          </div>
          
          <div class="card-body">
            <div class="card-duration">⏱️ ${formatDuration(call.duration)}</div>
            
            <div class="card-transcription">
              ${status === 'completed' && call.transcription ? `
                <div class="transcription-preview">
                  📄 "${escapeHtml(call.transcription)}"
                </div>
              ` : `
                <div class="transcription-status-badge ${status}">
                  📝 Статус: ${getStatusText(status)}
                </div>
              `}
            </div>
            
            <div class="card-audio">
              <button class="play-pause-btn mobile" data-audio-url="${call.recording_url || `/api/incoming-calls/${call.id}/recording`}">
                ▶️ ${formatDuration(call.duration)}
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
    
    // Привязка обработчиков
    attachCardEventListeners();
  };
  
  // Обновление пагинации
  const updatePagination = () => {
    const startRecord = (currentPage - 1) * perPage + 1;
    const endRecord = Math.min(currentPage * perPage, totalRecords);
    
    document.getElementById('showing-start').textContent = totalRecords > 0 ? startRecord : 0;
    document.getElementById('showing-end').textContent = endRecord;
    document.getElementById('total-records').textContent = totalRecords;
    document.getElementById('current-page').textContent = currentPage;
    document.getElementById('total-pages').textContent = totalPages;
    
    document.getElementById('first-page').disabled = currentPage === 1;
    document.getElementById('prev-page').disabled = currentPage === 1;
    document.getElementById('next-page').disabled = currentPage === totalPages;
    document.getElementById('last-page').disabled = currentPage === totalPages;
  };
  
  // Показать детали звонка
  const showCallDetails = (call) => {
    const modal = document.getElementById('call-details-modal');
    const content = document.getElementById('call-details-content');
    
    const status = call.transcription_status || 'pending';
    const audioUrl = call.recording_url || `/api/incoming-calls/${call.id}/recording`;
    
    content.innerHTML = `
      <div class="call-details">
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">📱 Номер:</span>
            <span class="detail-value">${formatPhoneNumber(call.caller_number)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">📅 Дата:</span>
            <span class="detail-value">${formatDateTime(call.call_date || call.created_at)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">⏱️ Длительность:</span>
            <span class="detail-value">${formatDuration(call.duration)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">📁 Размер файла:</span>
            <span class="detail-value">${formatFileSize(call.file_size)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">📝 Статус:</span>
            <span class="detail-value">
              <span class="status-badge ${status}">${getStatusText(status)}</span>
            </span>
          </div>
        </div>
        
        <div class="detail-section">
          <h4>🎵 Запись</h4>
          <audio controls src="${audioUrl}" style="width: 100%;"></audio>
        </div>
        
        ${status === 'completed' && call.transcription ? `
          <div class="detail-section">
            <h4>📄 Транскрибация</h4>
            <div class="transcription-box">${escapeHtml(call.transcription)}</div>
          </div>
        ` : ''}
        
        <div class="detail-section">
          <h4>📋 Заметки</h4>
          <textarea id="call-notes" class="form-control" rows="3" placeholder="Добавьте заметку...">${escapeHtml(call.notes || '')}</textarea>
        </div>
        
        <div class="modal-actions">
          <button class="btn btn-primary" id="save-notes-btn" data-id="${call.id}">💾 Сохранить</button>
          <button class="btn btn-outline" id="copy-transcription-btn" data-text="${escapeHtml(call.transcription || '')}">📋 Копировать текст</button>
        </div>
      </div>
    `;
    
    modal.style.display = 'block';
    
    // Обработчики в модальном окне
    document.getElementById('save-notes-btn')?.addEventListener('click', async (e) => {
      const id = e.target.dataset.id;
      const notes = document.getElementById('call-notes').value;
      await saveNotes(id, notes);
    });
    
    document.getElementById('copy-transcription-btn')?.addEventListener('click', (e) => {
      const text = e.target.dataset.text;
      navigator.clipboard?.writeText(text).then(() => {
        App.showNotification('Текст скопирован', 'success');
      });
    });
  };
  
  // Сохранение заметок
  const saveNotes = async (id, notes) => {
    try {
      await App.apiPut(`/api/incoming-calls/${id}/notes`, { notes });
      App.showNotification('Заметка сохранена', 'success');
      
      // Обновить локальные данные
      const call = incomingCalls.find(c => c.id == id);
      if (call) call.notes = notes;
      
    } catch (err) {
      console.error('Ошибка сохранения заметки:', err);
      App.showNotification('Ошибка сохранения заметки', 'error');
    }
  };
  
  // Скачивание записи
  const downloadRecording = (id) => {
    const url = `/api/incoming-calls/${id}/recording?download=true`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `incoming_${id}.wav`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    
    App.showNotification('Скачивание началось', 'info');
  };
  
  // Удаление записи
  const deleteCall = async (id) => {
    if (!confirm('Удалить запись о звонке? Файл также будет удален.')) return;
    
    try {
      await App.apiDelete(`/api/incoming-calls/${id}`);
      App.showNotification('Запись удалена', 'success');
      
      // Удалить из локального массива
      incomingCalls = incomingCalls.filter(c => c.id != id);
      totalRecords--;
      totalPages = Math.ceil(totalRecords / perPage) || 1;
      
      if (incomingCalls.length === 0 && currentPage > 1) {
        currentPage--;
      }
      
      await loadIncomingCalls();
      
    } catch (err) {
      console.error('Ошибка удаления:', err);
      App.showNotification('Ошибка удаления записи', 'error');
    }
  };
  
  // Воспроизведение аудио
  const playAudio = (url, button) => {
    // Если уже играет - остановить
    if (window.currentAudio && window.currentAudio.src === url) {
      window.currentAudio.pause();
      window.currentAudio = null;
      button.textContent = '▶️';
      return;
    }
    
    // Остановить предыдущее
    if (window.currentAudio) {
      window.currentAudio.pause();
      document.querySelectorAll('.play-pause-btn').forEach(btn => btn.textContent = '▶️');
    }
    
    const audio = new Audio(url);
    audio.play();
    button.textContent = '⏸️';
    
    audio.onended = () => {
      button.textContent = '▶️';
      window.currentAudio = null;
    };
    
    audio.onerror = () => {
      App.showNotification('Ошибка воспроизведения', 'error');
      button.textContent = '▶️';
      window.currentAudio = null;
    };
    
    window.currentAudio = audio;
  };
  
  // Автообновление для отслеживания статусов транскрибации
  const startAutoRefresh = () => {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
    }
    
    autoRefreshInterval = setInterval(async () => {
      // Проверяем, есть ли звонки в статусе processing
      const processingIds = incomingCalls
        .filter(c => c.transcription_status === 'processing')
        .map(c => c.id);
      
      if (processingIds.length > 0) {
        // Тихий рефреш
        await loadIncomingCalls();
      }
    }, 5000); // Проверка каждые 5 секунд
  };
  
  // Остановка автообновления при уходе со страницы
  const stopAutoRefresh = () => {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
    }
  };
  
  // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
  
  const attachEventListeners = () => {
    // Обновление
    document.getElementById('refresh-btn')?.addEventListener('click', loadIncomingCalls);
    
    // Пагинация
    document.getElementById('first-page')?.addEventListener('click', () => {
      currentPage = 1;
      loadIncomingCalls();
    });
    
    document.getElementById('prev-page')?.addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        loadIncomingCalls();
      }
    });
    
    document.getElementById('next-page')?.addEventListener('click', () => {
      if (currentPage < totalPages) {
        currentPage++;
        loadIncomingCalls();
      }
    });
    
    document.getElementById('last-page')?.addEventListener('click', () => {
      currentPage = totalPages;
      loadIncomingCalls();
    });
    
    // Закрытие модального окна
    document.querySelector('.close-modal')?.addEventListener('click', () => {
      document.getElementById('call-details-modal').style.display = 'none';
    });
    
    // Клик вне модального окна
    window.addEventListener('click', (e) => {
      const modal = document.getElementById('call-details-modal');
      if (e.target === modal) {
        modal.style.display = 'none';
      }
    });
  };
  
  const attachRowEventListeners = () => {
    // Клик по строке - показать детали
    document.querySelectorAll('.incoming-row').forEach(row => {
      row.addEventListener('click', (e) => {
        // Игнорируем клики по кнопкам
        if (e.target.closest('button') || e.target.closest('.play-pause-btn')) {
          return;
        }
        
        const id = parseInt(row.dataset.callId);
        const call = incomingCalls.find(c => c.id === id);
        if (call) {
          showCallDetails(call);
        }
      });
    });
    
    // Кнопки воспроизведения
    document.querySelectorAll('.play-pause-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.audioUrl;
        playAudio(url, btn);
      });
    });
    
    // Кнопки скачивания
    document.querySelectorAll('.download-call').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        downloadRecording(id);
      });
    });
    
    // Кнопки удаления
    document.querySelectorAll('.delete-call').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        deleteCall(id);
      });
    });
  };
  
  const attachCardEventListeners = () => {
    // Клик по карточке
    document.querySelectorAll('.incoming-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        
        const id = parseInt(card.dataset.callId);
        const call = incomingCalls.find(c => c.id === id);
        if (call) {
          showCallDetails(call);
        }
      });
    });
    
    // Кнопки в карточках
    document.querySelectorAll('.incoming-card .play-pause-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.audioUrl;
        playAudio(url, btn);
      });
    });
    
    document.querySelectorAll('.incoming-card .download-call').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        downloadRecording(id);
      });
    });
    
    document.querySelectorAll('.incoming-card .delete-call').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        deleteCall(id);
      });
    });
  };
  
  // ============ УТИЛИТЫ ============
  
  const formatDateTime = (dateStr) => {
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
  };
  
  const formatDateShort = (dateStr) => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    }).replace(',', '');
  };
  
  const formatPhoneNumber = (phone) => {
    if (!phone) return '—';
    const cleaned = phone.replace(/\D/g, '');
    if (cleaned.length === 11) {
      return `+${cleaned[0]} ${cleaned.slice(1, 4)} ${cleaned.slice(4, 7)}-${cleaned.slice(7, 9)}-${cleaned.slice(9, 11)}`;
    }
    return phone;
  };
  
  const formatDuration = (seconds) => {
    if (!seconds) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };
  
  const formatFileSize = (bytes) => {
    if (!bytes) return '—';
    const units = ['B', 'KB', 'MB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(0)} ${units[unitIndex]}`;
  };
  
  const getStatusText = (status) => {
    const statusMap = {
      'pending': 'ожидание',
      'processing': 'обработка',
      'completed': 'завершено',
      'failed': 'ошибка'
    };
    return statusMap[status] || status;
  };
  
  const escapeHtml = (text) => {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  };
  
  // Очистка при уходе со страницы
  const cleanup = () => {
    stopAutoRefresh();
    if (window.currentAudio) {
      window.currentAudio.pause();
      window.currentAudio = null;
    }
  };
  
  // Экспорт
  window.IncomingPage = { 
    render: renderIncoming,
    cleanup: cleanup
  };
})();
