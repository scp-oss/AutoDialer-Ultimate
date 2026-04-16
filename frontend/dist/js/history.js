// history.js
(function() {
  const container = document.getElementById('page-content');
  
  // Состояние модуля
  let currentPage = 1;
  let perPage = 20;
  let totalPages = 1;
  let totalRecords = 0;
  let currentFilters = {
    campaign_id: '',
    status: '',
    from_date: '',
    to_date: '',
    phone: '',
    direction: ''
  };
  let sortField = 'created_at';
  let sortOrder = 'desc';
  
  // Инициализация при загрузке страницы
  const renderHistory = async () => {
    container.innerHTML = `
      <div class="page-header">
        <h2>📞 История звонков</h2>
        <div class="header-actions">
          <button class="btn btn-outline" id="export-csv-btn">📥 Экспорт CSV</button>
          <button class="btn btn-outline" id="stats-btn">📊 Статистика</button>
        </div>
      </div>
      
      <!-- Фильтры -->
      <div class="filters-panel">
        <div class="filter-row">
          <div class="filter-group">
            <label>Кампания</label>
            <select id="filter-campaign" class="form-control">
              <option value="">Все кампании</option>
            </select>
          </div>
          
          <div class="filter-group">
            <label>Статус</label>
            <select id="filter-status" class="form-control">
              <option value="">Все статусы</option>
              <option value="completed">Завершен</option>
              <option value="answered">Отвечен</option>
              <option value="no_answer">Нет ответа</option>
              <option value="busy">Занято</option>
              <option value="failed">Ошибка</option>
              <option value="cancelled">Отменен</option>
            </select>
          </div>
          
          <div class="filter-group">
            <label>Направление</label>
            <select id="filter-direction" class="form-control">
              <option value="">Все</option>
              <option value="outbound">Исходящие</option>
              <option value="inbound">Входящие</option>
            </select>
          </div>
        </div>
        
        <div class="filter-row">
          <div class="filter-group">
            <label>Номер телефона</label>
            <input type="text" id="filter-phone" class="form-control" placeholder="Поиск по номеру">
          </div>
          
          <div class="filter-group">
            <label>Дата с</label>
            <input type="datetime-local" id="filter-from-date" class="form-control">
          </div>
          
          <div class="filter-group">
            <label>Дата по</label>
            <input type="datetime-local" id="filter-to-date" class="form-control">
          </div>
          
          <div class="filter-group filter-actions">
            <button class="btn btn-primary" id="apply-filters-btn">🔍 Применить</button>
            <button class="btn btn-outline" id="reset-filters-btn">🔄 Сбросить</button>
          </div>
        </div>
      </div>
      
      <!-- Таблица -->
      <div class="table-container">
        <table class="table table-hover" id="history-table">
          <thead>
            <tr>
              <th class="sortable" data-sort="created_at">
                Дата/время ${getSortIcon('created_at')}
              </th>
              <th class="sortable" data-sort="phone">
                Номер ${getSortIcon('phone')}
              </th>
              <th>Контакт</th>
              <th class="sortable" data-sort="campaign_id">
                Кампания ${getSortIcon('campaign_id')}
              </th>
              <th class="sortable" data-sort="status">
                Статус ${getSortIcon('status')}
              </th>
              <th class="sortable" data-sort="duration">
                Длительность ${getSortIcon('duration')}
              </th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody id="history-tbody">
            <tr><td colspan="7" class="text-center">Загрузка...</td></tr>
          </tbody>
        </table>
      </div>
      
      <!-- Пагинация -->
      <div class="pagination-container">
        <div class="pagination-info">
          Показано <span id="showing-records">0-0</span> из <span id="total-records">0</span> записей
        </div>
        <div class="pagination-controls">
          <button class="btn btn-sm btn-outline" id="first-page" disabled>⏮️</button>
          <button class="btn btn-sm btn-outline" id="prev-page" disabled>◀️</button>
          <span class="page-indicator">
            Страница <input type="number" id="page-input" min="1" value="1" style="width: 60px;"> 
            из <span id="total-pages">1</span>
          </span>
          <button class="btn btn-sm btn-outline" id="next-page" disabled>▶️</button>
          <button class="btn btn-sm btn-outline" id="last-page" disabled>⏭️</button>
        </div>
      </div>
      
      <!-- Модальное окно для деталей звонка -->
      <div id="call-details-modal" class="modal" style="display: none;">
        <div class="modal-content">
          <div class="modal-header">
            <h3>Детали звонка</h3>
            <button class="close-modal">&times;</button>
          </div>
          <div class="modal-body" id="call-details-content">
            <!-- Динамическое содержимое -->
          </div>
        </div>
      </div>
    `;
    
    // Загрузка кампаний для фильтра
    await loadCampaignsForFilter();
    
    // Загрузка данных
    await loadHistoryData();
    
    // Привязка обработчиков событий
    attachEventListeners();
  };
  
  // Вспомогательная функция для иконок сортировки
  const getSortIcon = (field) => {
    if (sortField !== field) return '↕️';
    return sortOrder === 'asc' ? '⬆️' : '⬇️';
  };
  
  // Загрузка списка кампаний для фильтра
  const loadCampaignsForFilter = async () => {
    try {
      const campaigns = await App.apiGet('/api/campaigns');
      const select = document.getElementById('filter-campaign');
      campaigns.forEach(campaign => {
        const option = document.createElement('option');
        option.value = campaign.id;
        option.textContent = campaign.name;
        select.appendChild(option);
      });
      
      // Установка сохраненного значения
      if (currentFilters.campaign_id) {
        select.value = currentFilters.campaign_id;
      }
    } catch (err) {
      console.error('Ошибка загрузки кампаний:', err);
    }
  };
  
  // Загрузка данных истории
  const loadHistoryData = async () => {
    const tbody = document.getElementById('history-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center">Загрузка...</td></tr>';
    
    try {
      // Построение query параметров
      const params = new URLSearchParams({
        page: currentPage,
        per_page: perPage,
        sort_by: sortField,
        sort_order: sortOrder,
        ...currentFilters
      });
      
      // Удаление пустых параметров
      for (const [key, value] of params.entries()) {
        if (!value) params.delete(key);
      }
      
      const response = await App.apiGet(`/api/calls?${params.toString()}`);
      
      // Обработка ответа (может быть разная структура)
      const calls = response.items || response.calls || response;
      const pagination = response.pagination || {
        page: currentPage,
        per_page: perPage,
        total: Array.isArray(calls) ? calls.length : 0,
        pages: 1
      };
      
      totalPages = pagination.pages || Math.ceil(pagination.total / perPage) || 1;
      totalRecords = pagination.total || calls.length;
      
      // Обновление пагинации
      updatePagination();
      
      // Рендер таблицы
      if (calls.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Нет данных для отображения</td></tr>';
        return;
      }
      
      tbody.innerHTML = calls.map(call => `
        <tr data-call-id="${call.id}" class="call-row ${call.status}">
          <td>${formatDateTime(call.created_at)}</td>
          <td>
            <div class="phone-number">
              <strong>${formatPhoneNumber(call.to_number || call.phone)}</strong>
              ${call.direction === 'inbound' ? '<span class="badge badge-info">Вх.</span>' : ''}
            </div>
          </td>
          <td>${call.contact_name || call.contact || '—'}</td>
          <td>${call.campaign_name || call.campaign || '—'}</td>
          <td>
            <span class="status-badge status-${call.status}">
              ${getStatusText(call.status)}
            </span>
          </td>
          <td>${formatDuration(call.duration)}</td>
          <td>
            <div class="action-buttons">
              <button class="btn btn-sm btn-outline view-details" data-id="${call.id}" title="Подробнее">
                👁️
              </button>
              ${call.recording_url ? `
                <button class="btn btn-sm btn-outline play-recording" data-url="${call.recording_url}" title="Прослушать запись">
                  🔊
                </button>
              ` : ''}
              <button class="btn btn-sm btn-outline download-call" data-id="${call.id}" title="Скачать детали">
                📥
              </button>
            </div>
          </td>
        </tr>
      `).join('');
      
      // Привязка обработчиков к кнопкам в строках
      attachRowEventListeners();
      
    } catch (err) {
      console.error('Ошибка загрузки истории:', err);
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">Ошибка загрузки данных</td></tr>';
      App.showNotification('Не удалось загрузить историю звонков', 'error');
    }
  };
  
  // Обновление пагинации
  const updatePagination = () => {
    const startRecord = (currentPage - 1) * perPage + 1;
    const endRecord = Math.min(currentPage * perPage, totalRecords);
    
    document.getElementById('showing-records').textContent = `${startRecord}-${endRecord}`;
    document.getElementById('total-records').textContent = totalRecords;
    document.getElementById('total-pages').textContent = totalPages;
    document.getElementById('page-input').value = currentPage;
    document.getElementById('page-input').max = totalPages;
    
    // Кнопки навигации
    document.getElementById('first-page').disabled = currentPage === 1;
    document.getElementById('prev-page').disabled = currentPage === 1;
    document.getElementById('next-page').disabled = currentPage === totalPages;
    document.getElementById('last-page').disabled = currentPage === totalPages;
  };
  
  // Привязка основных обработчиков
  const attachEventListeners = () => {
    // Фильтры
    document.getElementById('apply-filters-btn').addEventListener('click', applyFilters);
    document.getElementById('reset-filters-btn').addEventListener('click', resetFilters);
    
    // Экспорт
    document.getElementById('export-csv-btn').addEventListener('click', exportToCSV);
    document.getElementById('stats-btn').addEventListener('click', showStatistics);
    
    // Сортировка
    document.querySelectorAll('.sortable').forEach(th => {
      th.addEventListener('click', (e) => {
        const field = e.currentTarget.dataset.sort;
        if (sortField === field) {
          sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
        } else {
          sortField = field;
          sortOrder = 'asc';
        }
        currentPage = 1;
        renderHistory();
      });
    });
    
    // Пагинация
    document.getElementById('first-page').addEventListener('click', () => {
      currentPage = 1;
      loadHistoryData();
    });
    
    document.getElementById('prev-page').addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        loadHistoryData();
      }
    });
    
    document.getElementById('next-page').addEventListener('click', () => {
      if (currentPage < totalPages) {
        currentPage++;
        loadHistoryData();
      }
    });
    
    document.getElementById('last-page').addEventListener('click', () => {
      currentPage = totalPages;
      loadHistoryData();
    });
    
    document.getElementById('page-input').addEventListener('change', (e) => {
      let page = parseInt(e.target.value);
      if (page < 1) page = 1;
      if (page > totalPages) page = totalPages;
      currentPage = page;
      loadHistoryData();
    });
    
    // Закрытие модального окна
    document.querySelector('.close-modal').addEventListener('click', () => {
      document.getElementById('call-details-modal').style.display = 'none';
    });
  };
  
  // Привязка обработчиков к строкам таблицы
  const attachRowEventListeners = () => {
    document.querySelectorAll('.view-details').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const callId = e.currentTarget.dataset.id;
        showCallDetails(callId);
      });
    });
    
    document.querySelectorAll('.play-recording').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const url = e.currentTarget.dataset.url;
        playRecording(url);
      });
    });
    
    document.querySelectorAll('.download-call').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const callId = e.currentTarget.dataset.id;
        downloadCallDetails(callId);
      });
    });
  };
  
  // Применение фильтров
  const applyFilters = () => {
    currentFilters = {
      campaign_id: document.getElementById('filter-campaign').value,
      status: document.getElementById('filter-status').value,
      direction: document.getElementById('filter-direction').value,
      phone: document.getElementById('filter-phone').value,
      from_date: document.getElementById('filter-from-date').value,
      to_date: document.getElementById('filter-to-date').value
    };
    
    currentPage = 1;
    loadHistoryData();
  };
  
  // Сброс фильтров
  const resetFilters = () => {
    document.getElementById('filter-campaign').value = '';
    document.getElementById('filter-status').value = '';
    document.getElementById('filter-direction').value = '';
    document.getElementById('filter-phone').value = '';
    document.getElementById('filter-from-date').value = '';
    document.getElementById('filter-to-date').value = '';
    
    currentFilters = {
      campaign_id: '',
      status: '',
      direction: '',
      phone: '',
      from_date: '',
      to_date: ''
    };
    
    currentPage = 1;
    loadHistoryData();
  };
  
  // Показать детали звонка
  const showCallDetails = async (callId) => {
    try {
      const call = await App.apiGet(`/api/calls/${callId}`);
      
      const content = document.getElementById('call-details-content');
      content.innerHTML = `
        <div class="call-details">
          <div class="detail-group">
            <h4>Основная информация</h4>
            <table class="details-table">
              <tr><td>ID звонка:</td><td>${call.id}</td></tr>
              <tr><td>Дата/время:</td><td>${formatDateTime(call.created_at)}</td></tr>
              <tr><td>Номер:</td><td>${formatPhoneNumber(call.to_number || call.phone)}</td></tr>
              <tr><td>Контакт:</td><td>${call.contact_name || '—'}</td></tr>
              <tr><td>Кампания:</td><td>${call.campaign_name || '—'}</td></tr>
              <tr><td>Статус:</td><td><span class="status-badge status-${call.status}">${getStatusText(call.status)}</span></td></tr>
              <tr><td>Длительность:</td><td>${formatDuration(call.duration)}</td></tr>
              <tr><td>Направление:</td><td>${call.direction === 'inbound' ? 'Входящий' : 'Исходящий'}</td></tr>
            </table>
          </div>
          
          ${call.answered_at ? `
            <div class="detail-group">
              <h4>Временные метки</h4>
              <table class="details-table">
                <tr><td>Начало вызова:</td><td>${formatDateTime(call.created_at)}</td></tr>
                <tr><td>Ответ:</td><td>${formatDateTime(call.answered_at)}</td></tr>
                <tr><td>Завершение:</td><td>${formatDateTime(call.completed_at || call.ended_at)}</td></tr>
                <tr><td>Ожидание ответа:</td><td>${call.answered_at ? formatDuration((new Date(call.answered_at) - new Date(call.created_at)) / 1000) : '—'}</td></tr>
              </table>
            </div>
          ` : ''}
          
          ${call.recording_url ? `
            <div class="detail-group">
              <h4>Запись разговора</h4>
              <audio controls src="${call.recording_url}" style="width: 100%;"></audio>
              <br>
              <a href="${call.recording_url}" download class="btn btn-sm btn-primary">Скачать запись</a>
            </div>
          ` : ''}
          
          ${call.variables ? `
            <div class="detail-group">
              <h4>Переменные канала</h4>
              <pre>${JSON.stringify(call.variables, null, 2)}</pre>
            </div>
          ` : ''}
          
          ${call.notes ? `
            <div class="detail-group">
              <h4>Примечания</h4>
              <p>${call.notes}</p>
            </div>
          ` : ''}
        </div>
      `;
      
      document.getElementById('call-details-modal').style.display = 'block';
      
    } catch (err) {
      console.error('Ошибка загрузки деталей звонка:', err);
      App.showNotification('Не удалось загрузить детали звонка', 'error');
    }
  };
  
  // Воспроизведение записи
  const playRecording = (url) => {
    const audioPlayer = document.createElement('audio');
    audioPlayer.src = url;
    audioPlayer.controls = true;
    audioPlayer.style.width = '100%';
    
    App.showModal('Воспроизведение записи', audioPlayer.outerHTML, null, {
      onClose: () => audioPlayer.pause()
    });
  };
  
  // Скачать детали звонка
  const downloadCallDetails = async (callId) => {
    try {
      const call = await App.apiGet(`/api/calls/${callId}`);
      
      const dataStr = JSON.stringify(call, null, 2);
      const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
      
      const exportFileDefaultName = `call_${callId}_${new Date().toISOString().split('T')[0]}.json`;
      
      const linkElement = document.createElement('a');
      linkElement.setAttribute('href', dataUri);
      linkElement.setAttribute('download', exportFileDefaultName);
      linkElement.click();
      
      App.showNotification('Детали звонка скачаны', 'success');
    } catch (err) {
      console.error('Ошибка скачивания:', err);
      App.showNotification('Не удалось скачать детали', 'error');
    }
  };
  
  // Экспорт в CSV
  const exportToCSV = async () => {
    try {
      App.showNotification('Подготовка экспорта...', 'info');
      
      const params = new URLSearchParams({
        ...currentFilters,
        export: 'csv',
        per_page: 10000 // Максимальное количество записей
      });
      
      const response = await fetch(`/api/calls/export?${params.toString()}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      });
      
      if (!response.ok) throw new Error('Ошибка экспорта');
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `calls_export_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
      App.showNotification('Экспорт завершен', 'success');
      
    } catch (err) {
      console.error('Ошибка экспорта:', err);
      
      // Альтернативный метод - создание CSV на клиенте
      try {
        await exportToCSVClientSide();
      } catch (e) {
        App.showNotification('Не удалось выполнить экспорт', 'error');
      }
    }
  };
  
  // Клиентский экспорт в CSV (fallback)
  const exportToCSVClientSide = async () => {
    const params = new URLSearchParams({
      ...currentFilters,
      per_page: 10000
    });
    
    const response = await App.apiGet(`/api/calls?${params.toString()}`);
    const calls = response.items || response.calls || response;
    
    if (!calls.length) {
      App.showNotification('Нет данных для экспорта', 'warning');
      return;
    }
    
    // Заголовки CSV
    const headers = [
      'ID', 'Дата/время', 'Номер', 'Контакт', 'Кампания', 
      'Статус', 'Длительность (сек)', 'Направление', 'Запись'
    ];
    
    // Формирование строк
    const rows = calls.map(call => [
      call.id,
      formatDateTime(call.created_at),
      call.to_number || call.phone,
      call.contact_name || '',
      call.campaign_name || '',
      getStatusText(call.status),
      call.duration || 0,
      call.direction || 'outbound',
      call.recording_url || ''
    ]);
    
    // Создание CSV
    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    ].join('\n');
    
    // Скачивание
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `calls_export_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
    
    App.showNotification(`Экспортировано ${calls.length} записей`, 'success');
  };
  
  // Показать статистику
  const showStatistics = async () => {
    try {
      const stats = await App.apiGet('/api/calls/statistics');
      
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
              <div class="stat-percent">${stats.answered_percent || 0}%</div>
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
              <h4>Средняя длительность</h4>
              <div class="stat-value">${formatDuration(stats.avg_duration || 0)}</div>
            </div>
            <div class="stat-card">
              <h4>Общая длительность</h4>
              <div class="stat-value">${formatDuration(stats.total_duration || 0)}</div>
            </div>
          </div>
          
          ${stats.by_campaign ? `
            <h4>По кампаниям</h4>
            <table class="table">
              <thead>
                <tr>
                  <th>Кампания</th>
                  <th>Всего</th>
                  <th>Отвечено</th>
                  <th>% Ответов</th>
                </tr>
              </thead>
              <tbody>
                ${stats.by_campaign.map(c => `
                  <tr>
                    <td>${c.name}</td>
                    <td>${c.total}</td>
                    <td>${c.answered}</td>
                    <td>${c.answer_rate}%</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          ` : ''}
        </div>
      `;
      
      App.showModal('📊 Статистика звонков', modalContent);
      
    } catch (err) {
      console.error('Ошибка загрузки статистики:', err);
      App.showNotification('Не удалось загрузить статистику', 'error');
    }
  };
  
  // Форматирование даты/времени
  const formatDateTime = (dateStr) => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('ru-RU', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };
  
  // Форматирование номера телефона
  const formatPhoneNumber = (phone) => {
    if (!phone) return '—';
    // Простое форматирование для российских номеров
    const cleaned = phone.replace(/\D/g, '');
    if (cleaned.length === 11) {
      return `+${cleaned[0]} (${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7, 9)}-${cleaned.slice(9, 11)}`;
    }
    return phone;
  };
  
  // Форматирование длительности
  const formatDuration = (seconds) => {
    if (!seconds || seconds === 0) return '0 сек';
    
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    const parts = [];
    if (hours > 0) parts.push(`${hours} ч`);
    if (minutes > 0) parts.push(`${minutes} мин`);
    if (secs > 0 || parts.length === 0) parts.push(`${secs} сек`);
    
    return parts.join(' ');
  };
  
  // Текст статуса
  const getStatusText = (status) => {
    const statusMap = {
      'completed': 'Завершен',
      'answered': 'Отвечен',
      'no_answer': 'Нет ответа',
      'busy': 'Занято',
      'failed': 'Ошибка',
      'cancelled': 'Отменен',
      'ringing': 'Звонок',
      'in_progress': 'В процессе'
    };
    return statusMap[status] || status;
  };
  
  // Экспорт для роутера
  window.HistoryPage = { render: renderHistory };
})();
