// settings.js - Модуль настроек системы (только для admin)
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast)

const SettingsModule = {
    settings: {},
    categories: {},
    originalSettings: {},
    currentCategory: 'general',
    // Категория-кнопки кликабельны сразу после render(), но реальные данные
    // приходят асинхронно из loadSettings() - клик ДО того, как fetch
    // завершится, видел пустой this.categories[category] и навсегда
    // показывал "Нет настроек в этой категории" (ничего не перерисовывало
    // вкладку заново, когда данные наконец приходили) - подтверждено
    // живьём ("не с первого раза вкладка корректно отображается").
    settingsLoaded: false,
    
    // Инициализация модуля
    init() {
        // Проверка прав доступа
        if (AppState.userRole !== 'admin') {
            this.renderAccessDenied();
            return;
        }

        // render() ниже всегда рисует кнопку "Общие" как активную -
        // сбрасываем currentCategory здесь же, иначе при повторном заходе
        // на вкладку он мог остаться от прошлого визита (например,
        // "incoming") и разойтись с тем, что подсвечено визуально.
        this.currentCategory = 'general';
        this.settingsLoaded = false;

        this.render();
        this.attachEventListeners();
        this.loadSettings();
    },
    
    // Рендер страницы при отказе в доступе
    renderAccessDenied() {
        const container = document.getElementById('settingsContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="access-denied">
                <div class="access-denied-icon">🔒</div>
                <h2>Доступ запрещён</h2>
                <p>У вас нет прав для просмотра этой страницы.</p>
                <p>Только администраторы могут изменять настройки системы.</p>
            </div>
        `;
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('settingsContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="settings-page">
                <div class="page-header">
                    <h2>⚙️ Настройки системы</h2>
                    <div class="header-actions">
                        <button class="btn btn-outline" id="settingsRefreshBtn">
                            🔄 Обновить
                        </button>
                        <button class="btn btn-primary" id="settingsSaveAllBtn">
                            💾 Сохранить все
                        </button>
                    </div>
                </div>
                
                <p class="text-muted">
                    Глобальные настройки системы. Изменения применяются сразу после сохранения.
                    Некоторые настройки могут потребовать перезапуска сервисов.
                </p>
                
                <!-- Вкладки категорий -->
                <div class="settings-tabs">
                    <button class="settings-tab active" data-category="general">🌐 Общие</button>
                    <button class="settings-tab" data-category="asterisk">📞 Asterisk</button>
                    <button class="settings-tab" data-category="dialer">📱 Обзвон</button>
                    <button class="settings-tab" data-category="tts">🔊 TTS</button>
                    <button class="settings-tab" data-category="security">🔒 Безопасность</button>
                    <button class="settings-tab" data-category="notifications">🔔 Уведомления</button>
                    <button class="settings-tab" data-category="incoming">📞 Входящие</button>
                    <button class="settings-tab" data-category="advanced">⚡ Расширенные</button>
                </div>
                
                <!-- Контейнер настроек -->
                <div id="settingsContent" class="settings-content">
                    <div class="loading">Загрузка настроек...</div>
                </div>
            </div>
            
            <!-- Модальное окно подтверждения перезагрузки -->
            <div id="settingsRestartModal" class="modal" style="display: none;">
                <div class="modal-content modal-sm">
                    <div class="modal-header">
                        <h3>Требуется перезагрузка</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p>Некоторые настройки требуют перезагрузки сервисов для применения.</p>
                        <p>Перезагрузить сервисы сейчас?</p>
                        
                        <div class="form-actions">
                            <button type="button" class="btn btn-outline" onclick="SettingsModule.closeRestartModal()">
                                Позже
                            </button>
                            <button type="button" class="btn btn-primary" id="restartServicesBtn">
                                Перезагрузить
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно редактирования JSON -->
            <div id="settingsJsonModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Редактировать JSON</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <textarea id="settingsJsonEditor" class="json-editor" rows="15"></textarea>
                        <div class="form-actions">
                            <button type="button" class="btn btn-outline" onclick="SettingsModule.closeJsonModal()">
                                Отмена
                            </button>
                            <button type="button" class="btn btn-primary" id="saveJsonBtn">
                                Сохранить
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },
    
    // Загрузка настроек
    async loadSettings() {
        try {
            const response = await authFetch(`${API_BASE}/settings/`);
            if (response.ok) {
                const data = await response.json();
                this.settings = data;
                this.originalSettings = JSON.parse(JSON.stringify(data));
                
                // Группировка по категориям
                this.categorizeSettings();
                this.settingsLoaded = true;

                // Рендер той категории, что реально выбрана сейчас (пользователь
                // мог успеть кликнуть по другой вкладке, пока шёл запрос) -
                // не жёстко 'general'.
                this.renderCategory(this.currentCategory);
            } else {
                document.getElementById('settingsContent').innerHTML = 
                    '<div class="error-message">Ошибка загрузки настроек</div>';
            }
        } catch (error) {
            console.error('Settings load failed:', error);
            document.getElementById('settingsContent').innerHTML = 
                '<div class="error-message">Ошибка сервера</div>';
        }
    },
    
    // Группировка настроек по категориям
    categorizeSettings() {
        this.categories = {
            general: [],
            asterisk: [],
            dialer: [],
            tts: [],
            security: [],
            notifications: [],
            incoming: [],
            advanced: []
        };
        
        Object.entries(this.settings).forEach(([key, info]) => {
            const category = info.category || 'general';
            if (this.categories[category]) {
                this.categories[category].push({ key, ...info });
            } else {
                this.categories.advanced.push({ key, ...info });
            }
        });
    },
    
    // Рендер категории
    renderCategory(category) {
        const content = document.getElementById('settingsContent');
        this.currentCategory = category;

        if (!this.settingsLoaded) {
            // Настройки ещё не пришли с сервера - НЕ "Нет настроек в этой
            // категории" (это означало бы, что категория реально пуста).
            // loadSettings() перерисует this.currentCategory сам, как
            // только данные придут.
            content.innerHTML = '<div class="loading">Загрузка настроек...</div>';
            return;
        }

        const settings = this.categories[category] || [];

        if (settings.length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">⚙️</div>
                    <p>Нет настроек в этой категории</p>
                </div>
            `;
            return;
        }
        
        const categoryNames = {
            general: 'Общие настройки',
            asterisk: 'Настройки Asterisk',
            dialer: 'Настройки обзвона',
            tts: 'Настройки TTS',
            security: 'Безопасность',
            notifications: 'Уведомления',
            incoming: 'Входящие звонки',
            advanced: 'Расширенные настройки'
        };
        
        let html = `
            <div class="settings-category">
                <h3>${categoryNames[category] || category}</h3>
                <div class="settings-list">
        `;
        
        settings.forEach(setting => {
            html += this.renderSettingField(setting);
        });
        
        html += `
                </div>
                <div class="category-actions">
                    <button class="btn btn-primary save-category" data-category="${category}">
                        💾 Сохранить категорию
                    </button>
                </div>
            </div>
        `;
        
        content.innerHTML = html;
        
        // Привязка событий к полям
        this.attachSettingEvents();
    },
    
    // Рендер поля настройки
    renderSettingField(setting) {
        // ВАЖНО: data-key="${setting.key}" должен стоять РОВНО на одном
        // элементе - реальном поле ввода (input/select/checkbox), а не
        // ещё и на обёртке <div>. saveCategory()/saveAllSettings() делают
        // querySelectorAll('[data-key]') и читают .value/.checked с
        // КАЖДОГО найденного элемента - div ничего такого не имеет, так
        // что для него value получался undefined, отправлялся как
        // буквальная строка "undefined" и либо падал с 422 (числа - int()
        // не парсит "undefined"), либо ТИХО портил значение на "undefined"
        // без единой ошибки (строки/bool) - подтверждено живьём (422 на
        // все dialer.* сразу после сохранения). Раньше data-key стоял и на
        // div, и на самом поле - вторая копия сохранения на div и была
        // причиной.
        const value = setting.value;
        const type = setting.type || this.detectType(value, setting.key);
        const description = setting.description || '';

        let fieldHtml = '';
        
        switch (type) {
            case 'boolean':
                fieldHtml = `
                    <div class="setting-item setting-boolean">
                        <div class="setting-info">
                            <label>
                                <input type="checkbox" 
                                       class="setting-checkbox" 
                                       data-key="${setting.key}"
                                       ${value ? 'checked' : ''}>
                                <strong>${this.formatKey(setting.key)}</strong>
                            </label>
                            ${description ? `<small class="setting-description">${description}</small>` : ''}
                        </div>
                        <div class="setting-value">
                            <span class="value-indicator ${value ? 'enabled' : 'disabled'}">
                                ${value ? 'Включено' : 'Выключено'}
                            </span>
                        </div>
                    </div>
                `;
                break;
                
            case 'number':
                fieldHtml = `
                    <div class="setting-item setting-number">
                        <div class="setting-info">
                            <label><strong>${this.formatKey(setting.key)}</strong></label>
                            ${description ? `<small class="setting-description">${description}</small>` : ''}
                        </div>
                        <div class="setting-control">
                            <input type="number" 
                                   class="form-control setting-input" 
                                   data-key="${setting.key}"
                                   data-type="number"
                                   value="${value}"
                                   min="${setting.min || ''}"
                                   max="${setting.max || ''}"
                                   step="${setting.step || 1}">
                            ${setting.unit ? `<span class="input-unit">${setting.unit}</span>` : ''}
                        </div>
                    </div>
                `;
                break;
                
            case 'select':
                const options = setting.options || [];
                fieldHtml = `
                    <div class="setting-item setting-select">
                        <div class="setting-info">
                            <label><strong>${this.formatKey(setting.key)}</strong></label>
                            ${description ? `<small class="setting-description">${description}</small>` : ''}
                        </div>
                        <div class="setting-control">
                            <select class="form-control setting-select-input" data-key="${setting.key}">
                                ${options.map(opt => `
                                    <option value="${opt.value}" ${value === opt.value ? 'selected' : ''}>
                                        ${opt.label}
                                    </option>
                                `).join('')}
                            </select>
                        </div>
                    </div>
                `;
                break;
                
            case 'json':
                fieldHtml = `
                    <div class="setting-item setting-json">
                        <div class="setting-info">
                            <label><strong>${this.formatKey(setting.key)}</strong></label>
                            ${description ? `<small class="setting-description">${description}</small>` : ''}
                        </div>
                        <div class="setting-control">
                            <button class="btn btn-outline btn-sm edit-json" data-key="${setting.key}">
                                📝 Редактировать JSON
                            </button>
                            <div class="json-preview">
                                <code>${JSON.stringify(value).substring(0, 100)}${JSON.stringify(value).length > 100 ? '...' : ''}</code>
                            </div>
                        </div>
                    </div>
                `;
                break;
                
            default: // text, string
                fieldHtml = `
                    <div class="setting-item setting-text">
                        <div class="setting-info">
                            <label><strong>${this.formatKey(setting.key)}</strong></label>
                            ${description ? `<small class="setting-description">${description}</small>` : ''}
                        </div>
                        <div class="setting-control">
                            <input type="text" 
                                   class="form-control setting-input" 
                                   data-key="${setting.key}"
                                   data-type="text"
                                   value="${this.escapeHtml(String(value))}"
                                   placeholder="${setting.placeholder || ''}">
                            ${setting.unit ? `<span class="input-unit">${setting.unit}</span>` : ''}
                        </div>
                    </div>
                `;
                break;
        }
        
        return fieldHtml;
    },
    
    // Определение типа значения
    detectType(value, key) {
        if (typeof value === 'boolean') return 'boolean';
        if (typeof value === 'number') return 'number';
        if (key.includes('json') || key.includes('config')) return 'json';
        return 'text';
    },
    
    // Форматирование ключа
    formatKey(key) {
        // Ключи настроек - полные, с префиксом категории (см.
        // SYSTEM_SETTINGS в app/services/settings.py, например
        // "asterisk.ami_host", не просто "ami_host").
        const labels = {
            'system.name': 'Название системы',
            'dialer.max_calls': 'Максимум одновременных звонков',
            'dialer.default_cps': 'CPS по умолчанию',
            'asterisk.ami_host': 'AMI хост',
            'asterisk.ami_port': 'AMI порт',
            'asterisk.ami_user': 'AMI пользователь',
            'asterisk.ami_password': 'AMI пароль',
            'tts.default_voice': 'Голос TTS',
            'tts.speed': 'Скорость речи',
            'incoming.greeting_enabled': 'Проигрывать приветствие',
            'incoming.greeting_audio_id': 'Аудио приветствия',
            'audio.retention_days': 'Хранить записи (дней)',
            'security.session_timeout': 'Таймаут сессии (сек)',
            'security.max_login_attempts': 'Максимум попыток входа',
            'security.block_duration': 'Блокировка (сек)',
            'notifications.email_enabled': 'Email уведомления',
            'logging.level': 'Уровень логирования'
        };
        return labels[key] || key.split('.').pop().replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async saveSetting(key, value) {
        try {
            const response = await authFetch(`${API_BASE}/settings/${key}`, {
                method: 'PUT',
                // SettingUpdateRequest.value is typed str on the backend
                // (app/models/settings.py) - it stores/parses everything
                // as text internally regardless of value_type. Sending the
                // raw JS boolean/number as-is risks a 422 depending on
                // Pydantic's coercion mode; stringify explicitly instead.
                body: JSON.stringify({ value: String(value) })
            });

            if (response.ok) {
                this.settings[key].value = value;
                this.updateValueIndicator(key, value);
                
                // Проверка, требуется ли перезагрузка
                if (this.settings[key].requires_restart) {
                    this.showRestartModal();
                }
                
                return true;
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка сохранения', 'error');
                return false;
            }
        } catch (error) {
            console.error('Save setting failed:', error);
            showToast('Ошибка сервера', 'error');
            return false;
        }
    },
    
    async saveCategory(category) {
        const settings = this.categories[category] || [];
        const inputs = document.querySelectorAll(`[data-key]`);
        
        let successCount = 0;
        let errorCount = 0;
        let requiresRestart = false;
        
        for (const input of inputs) {
            const key = input.dataset.key;
            const setting = this.settings[key];
            if (!setting) continue;
            
            let value;
            if (input.type === 'checkbox') {
                value = input.checked;
            } else if (input.type === 'number') {
                value = parseFloat(input.value);
            } else if (input.tagName === 'SELECT') {
                value = input.value;
            } else {
                value = input.value;
            }
            
            // Сохраняем только изменённые
            if (JSON.stringify(value) !== JSON.stringify(this.originalSettings[key]?.value)) {
                const success = await this.saveSetting(key, value);
                if (success) {
                    successCount++;
                    this.originalSettings[key].value = value;
                    if (setting.requires_restart) requiresRestart = true;
                } else {
                    errorCount++;
                }
            }
        }
        
        if (successCount > 0) {
            showToast(`Сохранено: ${successCount}`, 'success');
            if (requiresRestart) {
                this.showRestartModal();
            }
        } else if (errorCount === 0) {
            showToast('Нет изменений для сохранения', 'info');
        }
    },
    
    async saveAllSettings() {
        const allInputs = document.querySelectorAll('[data-key]');
        let successCount = 0;
        let errorCount = 0;
        let requiresRestart = false;
        
        const submitBtn = document.getElementById('settingsSaveAllBtn');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = '⏳ Сохранение...';
        
        for (const input of allInputs) {
            const key = input.dataset.key;
            const setting = this.settings[key];
            if (!setting) continue;
            
            let value;
            if (input.type === 'checkbox') {
                value = input.checked;
            } else if (input.type === 'number') {
                value = parseFloat(input.value);
            } else if (input.tagName === 'SELECT') {
                value = input.value;
            } else {
                value = input.value;
            }
            
            if (JSON.stringify(value) !== JSON.stringify(this.originalSettings[key]?.value)) {
                const success = await this.saveSetting(key, value);
                if (success) {
                    successCount++;
                    this.originalSettings[key].value = value;
                    if (setting.requires_restart) requiresRestart = true;
                } else {
                    errorCount++;
                }
            }
        }
        
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
        
        showToast(`Сохранено: ${successCount}, ошибок: ${errorCount}`, successCount > 0 ? 'success' : 'info');
        
        if (requiresRestart) {
            this.showRestartModal();
        }
    },
    
    async restartServices() {
        const btn = document.getElementById('restartServicesBtn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Перезагрузка...';
        
        try {
            const response = await authFetch(`${API_BASE}/system/restart`, {
                method: 'POST'
            });
            
            if (response.ok) {
                showToast('Сервисы перезагружены', 'success');
                this.closeRestartModal();
            } else {
                showToast('Ошибка перезагрузки', 'error');
            }
        } catch (error) {
            console.error('Restart failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    },
    
    // Редактирование JSON
    openJsonEditor(key) {
        const setting = this.settings[key];
        if (!setting) return;
        
        const modal = document.getElementById('settingsJsonModal');
        const editor = document.getElementById('settingsJsonEditor');
        
        editor.value = JSON.stringify(setting.value, null, 2);
        editor.dataset.key = key;
        
        modal.style.display = 'flex';
    },
    
    closeJsonModal() {
        document.getElementById('settingsJsonModal').style.display = 'none';
    },
    
    async saveJson() {
        const editor = document.getElementById('settingsJsonEditor');
        const key = editor.dataset.key;
        
        try {
            const value = JSON.parse(editor.value);
            const success = await this.saveSetting(key, value);
            
            if (success) {
                this.closeJsonModal();
                // Обновить отображение
                const preview = document.querySelector(`.json-preview code`);
                if (preview) {
                    const jsonStr = JSON.stringify(value);
                    preview.textContent = jsonStr.substring(0, 100) + (jsonStr.length > 100 ? '...' : '');
                }
            }
        } catch (e) {
            showToast('Невалидный JSON', 'error');
        }
    },
    
    // Обновление индикатора значения
    updateValueIndicator(key, value) {
        const indicator = document.querySelector(`[data-key="${key}"] .value-indicator`);
        if (indicator) {
            indicator.textContent = value ? 'Включено' : 'Выключено';
            indicator.className = `value-indicator ${value ? 'enabled' : 'disabled'}`;
        }
    },
    
    // Сброс настроек
    // Подтверждение уже получено через модалку settingsResetModal
    // (см. confirmResetBtn в attachEventListeners) - лишний нативный
    // confirm() здесь показывал ВТОРОЙ, дублирующий диалог поверх уже
    // подтверждённого действия.
    async resetToDefaults() {
        try {
            const response = await authFetch(`${API_BASE}/settings/reset`, {
                method: 'POST'
            });
            
            if (response.ok) {
                showToast('Настройки сброшены', 'success');
                await this.loadSettings();
                const activeTab = document.querySelector('.settings-tab.active');
                if (activeTab) {
                    this.renderCategory(activeTab.dataset.category);
                }
            } else {
                showToast('Ошибка сброса', 'error');
            }
        } catch (error) {
            console.error('Reset failed:', error);
            showToast('Ошибка сервера', 'error');
        }
    },
    
    // Предпрослушивание приветствия
    async previewGreeting() {
        const select = document.getElementById('setting_incoming_greeting');
        if (!select) return;
        
        const greeting = select.value;
        if (!greeting) {
            showToast('Выберите приветствие', 'warning');
            return;
        }
        
        try {
            const response = await authFetch(`${API_BASE}/audio/preview?path=${encodeURIComponent(greeting)}`);
            if (response.ok) {
                const data = await response.json();
                const audio = new Audio(data.url);
                audio.play();
            }
        } catch (error) {
            console.error('Preview failed:', error);
        }
    },
    
    // ============ МОДАЛЬНЫЕ ОКНА ============
    
    showRestartModal() {
        document.getElementById('settingsRestartModal').style.display = 'flex';
    },
    
    closeRestartModal() {
        document.getElementById('settingsRestartModal').style.display = 'none';
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        // Вкладки
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                // e.currentTarget (the <button> the listener is attached to),
                // не e.target - каждая кнопка содержит дочерние <span> для
                // иконки и текста, и клик по ним (то есть почти по всей
                // видимой площади кнопки) делал e.target этим span'ом, у
                // которого нет data-category. renderCategory(undefined)
                // тихо показывал "Нет настроек в этой категории" для
                // категорий, где данные были на месте - подтверждено
                // живьём (console.warn показал category: undefined при
                // totalKeysInThisSettings: 45).
                document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
                e.currentTarget.classList.add('active');
                this.renderCategory(e.currentTarget.dataset.category);
            });
        });
        
        // Кнопки
        document.getElementById('settingsRefreshBtn')?.addEventListener('click', () => this.loadSettings());
        document.getElementById('settingsSaveAllBtn')?.addEventListener('click', () => this.saveAllSettings());
        document.getElementById('restartServicesBtn')?.addEventListener('click', () => this.restartServices());
        document.getElementById('saveJsonBtn')?.addEventListener('click', () => this.saveJson());

        // "Сбросить" - открывает модалку подтверждения; сам сброс происходит
        // по клику на confirmResetBtn внутри неё. Обе кнопки существуют в
        // settings.html и вызывают полностью реализованный resetToDefaults(),
        // но ни одна из них раньше не была привязана ни здесь, ни где-либо
        // ещё (инлайн-<script> внутри settings.html никогда не выполняется -
        // он попадает в DOM через innerHTML при переключении вкладок, а
        // браузеры не исполняют так вставленные <script>) - кнопка была
        // полностью мёртвой, подтверждено отсутствием единого обработчика
        // в коде.
        document.getElementById('settingsResetBtn')?.addEventListener('click', () => {
            App.showModal('settingsResetModal');
        });
        document.getElementById('confirmResetBtn')?.addEventListener('click', () => {
            this.resetToDefaults();
            App.hideModal('settingsResetModal');
        });
        
        // Закрытие модальных окон
        document.querySelectorAll('.close-modal').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                if (modal) modal.style.display = 'none';
            });
        });
        
        // Клик вне модального окна
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.style.display = 'none';
                }
            });
        });
        
        // Делегирование для кнопок сохранения категорий
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('save-category')) {
                const category = e.target.dataset.category;
                this.saveCategory(category);
            }
            
            if (e.target.classList.contains('edit-json')) {
                const key = e.target.dataset.key;
                this.openJsonEditor(key);
            }
        });
        
        // Делегирование для чекбоксов
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('setting-checkbox')) {
                const key = e.target.dataset.key;
                const value = e.target.checked;
                this.saveSetting(key, value);
            }
        });
    },
    
    attachSettingEvents() {
        // Автосохранение при изменении (опционально)
        const autoSaveEnabled = this.settings.auto_save_settings?.value || false;
        
        if (autoSaveEnabled) {
            document.querySelectorAll('.setting-input, .setting-select-input').forEach(input => {
                input.addEventListener('change', (e) => {
                    const key = e.target.dataset.key;
                    let value;
                    
                    if (e.target.type === 'number') {
                        value = parseFloat(e.target.value);
                    } else {
                        value = e.target.value;
                    }
                    
                    this.saveSetting(key, value);
                });
            });
        }
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Экспорт глобально
window.SettingsModule = SettingsModule;
App.settings = SettingsModule;
