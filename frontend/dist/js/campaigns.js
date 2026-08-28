/**
 * AutoDialer Ultimate - Campaigns Module
 * Version: 3.0.0
 * Управление кампаниями обзвона
 */

App.campaigns = {
    // Состояние модуля
    state: {
        campaigns: [],
        currentPage: 1,
        totalPages: 1,
        pageSize: 20,
        filterStatus: '',
        searchQuery: '',
        selectedCampaign: null,
        audioFiles: [],
        contactGroups: [],
        // Группы, отмеченные при открытии формы редактирования (по
        // campaign.contact_groups) - saveCampaign() сравнивает с этим,
        // чтобы понять, реально ли пользователь сменил группу, а не
        // просто отредактировал что-то другое в той же форме.
        originalContactGroupIds: [],
        // ID кампании, чья модалка деталей сейчас открыта (для живых обновлений
        // из WebSocket-канала campaign) — null, если модалка закрыта
        viewingCampaignId: null
    },

    // =============================================
    // Инициализация
    // =============================================
    async init() {
        await this.loadCampaigns();
        await this.loadAudioForSelect();
        this.setupEventListeners();
    },

    // =============================================
    // Загрузка групп контактов для формы создания
    // =============================================
    async loadContactGroupsForSelect(selectedIds = []) {
        try {
            const data = await App.apiGet('/contact-groups/');
            this.state.contactGroups = data.items || data || [];

            const container = document.getElementById('campaignContactGroupsList');
            if (container) {
                container.innerHTML = this.state.contactGroups.length
                    ? this.state.contactGroups.map(g => `
                        <label>
                            <input type="checkbox" name="campaignContactGroupIds" value="${g.id}" ${selectedIds.includes(g.id) ? 'checked' : ''}>
                            ${this.escapeHtml(g.name)} (${g.contacts_count || 0})
                        </label>
                    `).join('')
                    : '<p class="text-muted">Нет ни одной группы контактов - создайте её на вкладке «Контакты».</p>';
            }
        } catch (error) {
            console.error('Failed to load contact groups:', error);
            const container = document.getElementById('campaignContactGroupsList');
            if (container) {
                container.innerHTML = '<p class="text-error">Ошибка загрузки групп</p>';
            }
        }
    },

    setupEventListeners() {
        // Поиск с дебаунсом
        const searchInput = document.getElementById('campaignSearch');
        if (searchInput) {
            searchInput.addEventListener('input', App.debounce(() => {
                this.state.searchQuery = searchInput.value;
                this.loadCampaigns(1);
            }, 300));
        }

        // Фильтр по статусу
        const statusFilter = document.getElementById('campaignStatusFilter');
        if (statusFilter) {
            statusFilter.addEventListener('change', () => {
                this.state.filterStatus = statusFilter.value;
                this.loadCampaigns(1);
            });
        }

        // Кнопка обновления
        const refreshBtn = document.getElementById('campaignsRefreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadCampaigns());
        }
    },

    // =============================================
    // Загрузка кампаний
    // =============================================
    async loadCampaigns(page = 1) {
        this.state.currentPage = page;
        
        const tbody = document.getElementById('campaignsTableBody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center"><div class="loading">Загрузка...</div></td></tr>';
        }
        
        try {
            let url = `/campaigns/?page=${page}&page_size=${this.state.pageSize}`;
            
            if (this.state.filterStatus) {
                url += `&status=${this.state.filterStatus}`;
            }
            if (this.state.searchQuery) {
                url += `&search=${encodeURIComponent(this.state.searchQuery)}`;
            }
            
            const data = await App.apiGet(url);
            
            this.state.campaigns = data.items || data || [];
            this.state.totalPages = data.total_pages || 1;
            
            this.renderTable();
            App.renderPagination('campaignsPagination', page, this.state.totalPages, 'App.campaigns.loadCampaigns');
            
        } catch (error) {
            console.error('Failed to load campaigns:', error);
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
            App.showToast('Ошибка загрузки обзвонов', 'error');
        }
    },

    // =============================================
    // Рендер таблицы
    // =============================================
    renderTable() {
        const tbody = document.getElementById('campaignsTableBody');
        if (!tbody) return;
        
        const campaigns = this.state.campaigns;
        
        if (!campaigns || campaigns.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">📋</div>
                            <p>Нет обзвонов</p>
                            ${App.auth.isOperator() ? `
                                <button class="btn btn-primary" onclick="App.campaigns.openCampaignModal()">
                                    Создать первый обзвон
                                </button>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = campaigns.map(c => this.campaignRowHtml(c)).join('');

        this.attachRowListeners();
    },

    // Рендер одной строки таблицы кампаний — используется и полным рендером
    // таблицы, и точечным live-обновлением конкретной строки по WebSocket-событию
    campaignRowHtml(c) {
        const progress = c.stats?.progress_percent || 0;
        // CampaignStatsResponse (app/models/campaign.py) называет это
        // processed_contacts, не called_contacts - таблица всегда
        // показывала "0/N" в прогрессе для любой кампании, независимо от
        // того, сколько реально обзвонили (видно на первом же скриншоте
        // обзвона в этом разговоре: "0/1" у уже завершённой кампании).
        const called = c.stats?.processed_contacts || 0;
        const total = c.stats?.total_contacts || 0;
        const conversion = c.stats?.conversion_rate || 0;

        return `
            <tr data-campaign-id="${c.id}" class="campaign-row ${c.status}">
                <td>${c.id}</td>
                <td>
                    <strong>${this.escapeHtml(c.name)}</strong>
                    ${c.description ? `<br><small>${this.escapeHtml(c.description)}</small>` : ''}
                </td>
                <td>
                    <span class="status-badge status-${c.status}">${this.getStatusText(c.status)}</span>
                </td>
                <td>${c.dialer_settings?.max_calls || 10}</td>
                <td>${c.dialer_settings?.cps || 1}</td>
                <td>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: 80px;">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <span class="progress-text">${called}/${total}</span>
                    </div>
                </td>
                <td>
                    <span class="${conversion > 0 ? 'text-success' : ''}">${conversion}%</span>
                </td>
                <td>${this.formatDate(c.created_at)}</td>
                <td class="actions-cell">
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline" onclick="App.campaigns.viewCampaignDetail(${c.id})" title="Просмотр">
                            👁️
                        </button>
                        ${c.status === 'draft' ? `
                            <button class="btn btn-sm btn-success" onclick="App.campaigns.startCampaign(${c.id})" title="Запустить">
                                ▶️
                            </button>
                        ` : ''}
                        ${['completed', 'stopped', 'failed'].includes(c.status) ? `
                            <button class="btn btn-sm btn-success" onclick="App.campaigns.restartCampaign(${c.id})" title="Запустить снова (обзвонит всех заново)">
                                🔁
                            </button>
                        ` : ''}
                        ${c.status === 'running' ? `
                            <button class="btn btn-sm btn-warning" onclick="App.campaigns.pauseCampaign(${c.id})" title="Пауза">
                                ⏸️
                            </button>
                            ${App.auth.isAdmin() ? `
                                <button class="btn btn-sm btn-danger" onclick="App.campaigns.stopCampaign(${c.id})" title="Остановить">
                                    ⏹️
                                </button>
                            ` : ''}
                        ` : ''}
                        ${c.status === 'paused' ? `
                            <button class="btn btn-sm btn-success" onclick="App.campaigns.resumeCampaign(${c.id})" title="Продолжить">
                                ▶️
                            </button>
                        ` : ''}
                        ${App.auth.isOperator() && c.status !== 'running' ? `
                            <button class="btn btn-sm btn-outline" onclick="App.campaigns.editCampaign(${c.id})" title="Редактировать">
                                ✏️
                            </button>
                        ` : ''}
                        ${App.auth.isAdmin() && c.status !== 'running' ? `
                            <button class="btn btn-sm btn-outline-danger" onclick="App.campaigns.deleteCampaign(${c.id})" title="Удалить">
                                🗑️
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    },

    attachRowListeners() {
        document.querySelectorAll('.campaign-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (!e.target.closest('button')) {
                    const id = row.dataset.campaignId;
                    this.viewCampaignDetail(id);
                }
            });
        });
    },

    // =============================================
    // Живые обновления по WebSocket (канал "campaign")
    // =============================================
    // progress — CampaignProgressEvent из app/models/system.py, публикуется
    // CampaignService._publish_campaign_event раз в 5 обработанных контактов
    // и при завершении/остановке/ошибке кампании (см. ROADMAP §3.4)
    handleCampaignEvent(progress) {
        if (!progress || progress.campaign_id == null) return;

        const campaignId = progress.campaign_id;
        const idx = this.state.campaigns.findIndex(c => c.id === campaignId);

        if (idx !== -1) {
            const c = this.state.campaigns[idx];
            if (progress.status) {
                c.status = progress.status;
            }
            c.stats = {
                ...(c.stats || {}),
                progress_percent: progress.progress_percent,
                called_contacts: progress.called_contacts,
                total_contacts: progress.total_contacts,
                agreed: progress.agreed,
                declined: progress.declined
            };

            const row = document.querySelector(`.campaign-row[data-campaign-id="${campaignId}"]`);
            if (row) {
                row.outerHTML = this.campaignRowHtml(c);
                const newRow = document.querySelector(`.campaign-row[data-campaign-id="${campaignId}"]`);
                if (newRow) {
                    newRow.addEventListener('click', (e) => {
                        if (!e.target.closest('button')) {
                            this.viewCampaignDetail(newRow.dataset.campaignId);
                        }
                    });
                }
            }
        }

        // Если открыта модалка деталей именно этой кампании — обновляем её тоже.
        // Живое событие не содержит полного набора полей статистики (busy/noanswer/
        // failed и т.п.), поэтому перезапрашиваем деталь через REST, а не собираем
        // модалку из неполных данных события.
        if (this.state.viewingCampaignId === campaignId) {
            this.viewCampaignDetail(campaignId);
        }
    },

    // =============================================
    // Модальное окно создания/редактирования
    // =============================================
    openCampaignModal(campaign = null) {
        const modal = document.getElementById('campaignModal');
        const title = document.getElementById('campaignModalTitle');
        const deleteBtn = document.getElementById('campaignDeleteBtn');
        
        if (!modal) return;
        
        const isEdit = !!campaign;

        // При редактировании секция групп остаётся видимой, но меняет смысл:
        // ничего не отмечено - контакты не трогаем; отмечена хотя бы одна
        // группа - при сохранении список контактов кампании полностью
        // заменяется выбранным (см. saveCampaign() -> assign-contacts,
        // replace=true). Раньше при редактировании эту секцию скрывали
        // целиком и сменить группу обзвона было вообще нельзя никак -
        // единственная кнопка "Назначить контакты" в деталях только
        // добавляла контакты поверх старых, а не заменяла группу.
        const requiredMark = document.getElementById('campaignContactsRequiredMark');
        const contactsHint = document.getElementById('campaignContactsHint');
        if (requiredMark) {
            requiredMark.style.display = isEdit ? 'none' : '';
        }
        if (contactsHint) {
            contactsHint.textContent = isEdit
                ? 'Ниже отмечена текущая группа(ы) обзвона. Смените отметку, чтобы ЗАМЕНИТЬ список контактов - остальные настройки при этом не пострадают. Ничего не меняли - список контактов не тронется.'
                : 'Нужно выбрать хотя бы одну группу - без этого обзвон нельзя сохранить';
        }

        if (isEdit) {
            title.textContent = 'Редактировать обзвон';
            deleteBtn.style.display = 'inline-block';
            
            this.state.selectedCampaign = campaign;
            
            document.getElementById('campaignId').value = campaign.id;
            document.getElementById('campaignName').value = campaign.name || '';
            document.getElementById('campaignDescription').value = campaign.description || '';
            document.getElementById('campaignMaxCalls').value = campaign.dialer_settings?.max_calls || 10;
            document.getElementById('campaignCps').value = campaign.dialer_settings?.cps || 1;
            document.getElementById('campaignCallTimeout').value = campaign.dialer_settings?.call_timeout || 90;
            document.getElementById('campaignCallerId').value = campaign.dialer_settings?.caller_id || '';
            document.getElementById('campaignAudioSelect').value = campaign.dialer_settings?.audio_id || '';
            document.getElementById('campaignDtmfEnabled').checked = campaign.dialer_settings?.dtmf_enabled !== false;
            document.getElementById('campaignDtmfTimeout').value = campaign.dialer_settings?.dtmf_timeout || 8;

            // Стратегия повторных звонков
            if (campaign.retry_strategy) {
                document.getElementById('retryBusyMax').value = campaign.retry_strategy.busy || 2;
                document.getElementById('retryBusyDelay').value = campaign.retry_strategy.busy_delay || 300;
                document.getElementById('retryNoanswerMax').value = campaign.retry_strategy.noanswer || 3;
                document.getElementById('retryNoanswerDelay').value = campaign.retry_strategy.noanswer_delay || 600;
                document.getElementById('retryFailedMax').value = campaign.retry_strategy.failed || 1;
                document.getElementById('retryFailedDelay').value = campaign.retry_strategy.failed_delay || 1800;
                document.getElementById('retryMachineMax').value = campaign.retry_strategy.machine ?? 5;
                document.getElementById('retryMachineDelay').value = campaign.retry_strategy.machine_delay || 60;
            }
            
            // Расписание
            if (campaign.schedule) {
                document.getElementById('campaignScheduleEnabled').checked = campaign.schedule.enabled || false;
                document.getElementById('scheduleStartAt').value = campaign.schedule.start_at || '';
                document.getElementById('scheduleEndAt').value = campaign.schedule.end_at || '';
                document.getElementById('scheduleType').value = campaign.schedule.schedule_type || 'once';
            }
            
        } else {
            title.textContent = 'Новый обзвон';
            deleteBtn.style.display = 'none';
            
            this.state.selectedCampaign = null;
            
            document.getElementById('campaignId').value = '';
            document.getElementById('campaignForm').reset();
            
            // Значения по умолчанию
            document.getElementById('campaignMaxCalls').value = 10;
            document.getElementById('campaignCps').value = 1;
            document.getElementById('campaignCallTimeout').value = 90;
            document.getElementById('retryBusyMax').value = 2;
            document.getElementById('retryBusyDelay').value = 300;
            document.getElementById('retryNoanswerMax').value = 3;
            document.getElementById('retryNoanswerDelay').value = 600;
            document.getElementById('retryFailedMax').value = 1;
            document.getElementById('retryFailedDelay').value = 1800;
            document.getElementById('retryMachineMax').value = 5;
            document.getElementById('retryMachineDelay').value = 60;
            document.getElementById('scheduleType').value = 'once';
        }
        
        this.loadAudioForSelect();
        // Список групп нужен и при редактировании теперь тоже - см.
        // комментарий выше про смену группы обзвона. При редактировании
        // отмечаем ТЕКУЩИЕ группы кампании (campaign.contact_groups,
        // приходит только в детальном ответе GET /campaigns/{id} - см.
        // editCampaign() ниже), чтобы было видно, откуда сейчас звонок
        // берёт контакты, а не пустой список без единой подсказки.
        // originalContactGroupIds запоминаем отдельно, чтобы saveCampaign()
        // мог сравнить и НЕ трогать campaign_contacts, если пользователь
        // ничего не менял в этом блоке - иначе любое редактирование
        // кампании (например, просто смена названия) тихо сбрасывало бы
        // прогресс/retry_count всех контактов на пустой пересбор той же
        // группы.
        const currentGroupIds = isEdit ? (campaign.contact_groups || []).map(g => g.id) : [];
        this.state.originalContactGroupIds = currentGroupIds;
        this.loadContactGroupsForSelect(currentGroupIds);
        modal.style.display = 'flex';
    },

    closeCampaignModal() {
        const modal = document.getElementById('campaignModal');
        if (modal) {
            modal.style.display = 'none';
        }
        this.state.selectedCampaign = null;
    },

    async editCampaign(id) {
        // this.state.campaigns (список, GET /campaigns/) отдаёт
        // CampaignResponse - без поля contact_groups, оно есть только в
        // CampaignDetailResponse (GET /campaigns/{id}). Без этого запроса
        // openCampaignModal() не может отметить текущую группу кампании
        // при редактировании.
        try {
            const campaign = await App.apiGet(`/campaigns/${id}`);
            this.openCampaignModal(campaign);
        } catch (error) {
            console.error('Failed to load campaign for edit:', error);
            App.showToast('Ошибка загрузки обзвона', 'error');
        }
    },

    // =============================================
    // Сохранение кампании
    // =============================================
    async saveCampaign() {
        const id = document.getElementById('campaignId')?.value;
        const name = document.getElementById('campaignName')?.value?.trim();
        const description = document.getElementById('campaignDescription')?.value?.trim();
        const maxCalls = parseInt(document.getElementById('campaignMaxCalls')?.value) || 10;
        const cps = parseInt(document.getElementById('campaignCps')?.value) || 1;
        const callTimeout = parseInt(document.getElementById('campaignCallTimeout')?.value) || 90;
        const callerId = document.getElementById('campaignCallerId')?.value?.trim();
        const audioId = document.getElementById('campaignAudioSelect')?.value;
        const dtmfEnabled = document.getElementById('campaignDtmfEnabled')?.checked ?? true;
        const dtmfTimeout = parseInt(document.getElementById('campaignDtmfTimeout')?.value) || 8;

        // Валидация
        if (!name) {
            App.showToast('Введите название обзвона', 'warning');
            return;
        }
        
        if (maxCalls < 1 || maxCalls > 100) {
            App.showToast('Количество каналов должно быть от 1 до 100', 'warning');
            return;
        }
        
        if (cps < 0.1 || cps > 50) {
            App.showToast('CPS должен быть от 0.1 до 50', 'warning');
            return;
        }

        if (callTimeout < 5 || callTimeout > 300) {
            App.showToast('Таймаут звонка должен быть от 5 до 300 секунд', 'warning');
            return;
        }

        // Группы контактов - обязательны при создании
        // (CampaignCreateRequest.validate_contacts() требует хотя бы один
        // источник). При редактировании то же поле необязательно: если
        // что-то отмечено, после сохранения формы ниже отдельным вызовом
        // ЗАМЕНЯЕМ список контактов кампании выбранным (смена группы
        // обзвона) - см. POST /campaigns/{id}/assign-contacts,
        // replace=true. Если не отмечено ничего - контакты не трогаем.
        const contactGroupIds = Array.from(
            document.querySelectorAll('input[name="campaignContactGroupIds"]:checked')
        ).map(cb => parseInt(cb.value));

        if (!id && contactGroupIds.length === 0) {
            App.showToast('Выберите хотя бы одну группу контактов', 'warning');
            return;
        }

        // Стратегия повторных звонков
        const retryStrategy = {
            busy: parseInt(document.getElementById('retryBusyMax')?.value) || 2,
            busy_delay: parseInt(document.getElementById('retryBusyDelay')?.value) || 300,
            noanswer: parseInt(document.getElementById('retryNoanswerMax')?.value) || 3,
            noanswer_delay: parseInt(document.getElementById('retryNoanswerDelay')?.value) || 600,
            failed: parseInt(document.getElementById('retryFailedMax')?.value) || 1,
            failed_delay: parseInt(document.getElementById('retryFailedDelay')?.value) || 1800,
            machine: parseInt(document.getElementById('retryMachineMax')?.value) || 5,
            machine_delay: parseInt(document.getElementById('retryMachineDelay')?.value) || 60
        };
        
        // Расписание (schedule не Optional на бэкенде — при выключенном чекбоксе
        // отправляем {enabled: false} вместо null, иначе провалится валидация)
        let schedule = { enabled: false };
        if (document.getElementById('campaignScheduleEnabled')?.checked) {
            schedule = {
                enabled: true,
                start_at: document.getElementById('scheduleStartAt')?.value || null,
                end_at: document.getElementById('scheduleEndAt')?.value || null,
                schedule_type: document.getElementById('scheduleType')?.value || 'once'
            };
        }

        // dialer_settings — вложенный объект на бэкенде (CampaignCreateRequest/
        // CampaignUpdateRequest), а не плоские поля. При редактировании сохраняем
        // остальные настройки (dial_mode, таймауты и т.п.), не выставляемые в этой форме.
        const dialerSettings = {
            ...(this.state.selectedCampaign?.dialer_settings || {}),
            max_calls: maxCalls,
            cps,
            call_timeout: callTimeout,
            caller_id: callerId || null,
            audio_id: audioId || null,
            dtmf_enabled: dtmfEnabled,
            dtmf_timeout: dtmfTimeout
        };

        const data = {
            name,
            description: description || null,
            dialer_settings: dialerSettings,
            retry_strategy: retryStrategy,
            schedule
        };

        if (!id) {
            data.contact_group_ids = contactGroupIds;
        }
        
        const submitBtn = document.querySelector('#campaignForm button[type="submit"]');
        const originalText = submitBtn?.textContent;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = '⏳ Сохранение...';
        }
        
        try {
            if (id) {
                await App.apiPatch(`/campaigns/${id}`, data);

                // Отметка группы(групп) поменялась относительно того, что
                // было отмечено при открытии формы (originalContactGroupIds,
                // выставлен в openCampaignModal() по campaign.contact_groups) -
                // значит пользователь реально хочет сменить группу обзвона,
                // заменяем контакты кампании (replace=true). Отметка НЕ
                // менялась (в т.ч. просто открыли и сохранили без правок
                // групп) - контакты не трогаем: иначе любое редактирование
                // кампании (даже просто смена названия) тихо пересобирало бы
                // campaign_contacts заново и сбрасывало retry_count/статус
                // уже обработанных контактов.
                const original = [...(this.state.originalContactGroupIds || [])].sort();
                const current = [...contactGroupIds].sort();
                const groupsChanged = original.length !== current.length
                    || original.some((v, i) => v !== current[i]);

                if (groupsChanged && contactGroupIds.length > 0) {
                    await App.apiPost(`/campaigns/${id}/assign-contacts`, {
                        group_ids: contactGroupIds,
                        contact_ids: [],
                        replace: true
                    });
                }

                App.showToast('Обзвон обновлён', 'success');
            } else {
                await App.apiPost('/campaigns/', data);
                App.showToast('Обзвон создан', 'success');
            }

            this.closeCampaignModal();
            await this.loadCampaigns(this.state.currentPage);
            
        } catch (error) {
            console.error('Failed to save campaign:', error);
            App.showToast(error.message || 'Ошибка сохранения', 'error');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        }
    },

    // =============================================
    // Управление статусом кампании
    // =============================================
    async startCampaign(id) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/start`, {});
            App.showToast('Обзвон запущен', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to start campaign:', error);
            App.showToast(error.message || 'Ошибка запуска', 'error');
        }
    },

    async restartCampaign(id) {
        if (!App.confirm('Запустить обзвон заново? Все контакты будут прозвонены ещё раз, включая тех, кто уже ответил/согласился/отказался в прошлый раз.')) {
            return;
        }
        await this.startCampaign(id);
    },

    async pauseCampaign(id) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/pause`, {});
            App.showToast('Обзвон приостановлен', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to pause campaign:', error);
            App.showToast(error.message || 'Ошибка паузы', 'error');
        }
    },

    async resumeCampaign(id) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${id}/resume`, {});
            App.showToast('Обзвон возобновлён', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to resume campaign:', error);
            App.showToast(error.message || 'Ошибка возобновления', 'error');
        }
    },

    async stopCampaign(id) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может остановить обзвон', 'error');
            return;
        }

        if (!App.confirm('Остановить обзвон? Все активные звонки будут завершены.')) {
            return;
        }

        try {
            await App.apiPost(`/campaigns/${id}/stop`, {});
            App.showToast('Обзвон остановлен', 'success');
            await this.loadCampaigns(this.state.currentPage);
        } catch (error) {
            console.error('Failed to stop campaign:', error);
            App.showToast(error.message || 'Ошибка остановки', 'error');
        }
    },

    async deleteCampaign(id) {
        if (!App.auth.isAdmin()) {
            App.showToast('Только администратор может удалить обзвон', 'error');
            return;
        }

        if (!App.confirm('Удалить обзвон? Это действие нельзя отменить.')) {
            return;
        }

        try {
            await App.apiDelete(`/campaigns/${id}`);
            App.showToast('Обзвон удалён', 'success');
            
            if (this.state.selectedCampaign?.id === id) {
                this.closeCampaignModal();
            }
            
            await this.loadCampaigns(this.state.currentPage);
            
        } catch (error) {
            console.error('Failed to delete campaign:', error);
            App.showToast(error.message || 'Ошибка удаления', 'error');
        }
    },

    // =============================================
    // Просмотр деталей кампании
    // =============================================
    async viewCampaignDetail(id) {
        try {
            const data = await App.apiGet(`/campaigns/${id}`);
            const campaign = data.campaign || data;
            const stats = data.stats || {};

            this.state.viewingCampaignId = parseInt(id);

            const modal = document.getElementById('campaignDetailModal');
            const title = document.getElementById('campaignDetailTitle');
            const content = document.getElementById('campaignDetailContent');
            
            if (!modal || !content) return;
            
            title.textContent = campaign.name;
            
            content.innerHTML = `
                <div class="campaign-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID:</td><td>${campaign.id}</td></tr>
                            <tr><td>Статус:</td><td><span class="status-badge status-${campaign.status}">${this.getStatusText(campaign.status)}</span></td></tr>
                            <tr><td>Описание:</td><td>${this.escapeHtml(campaign.description || '—')}</td></tr>
                            <tr><td>Макс. каналов:</td><td>${campaign.dialer_settings?.max_calls || 10}</td></tr>
                            <tr><td>CPS:</td><td>${campaign.dialer_settings?.cps || 1}</td></tr>
                            <tr><td>Caller ID:</td><td>${this.escapeHtml(campaign.dialer_settings?.caller_id || '—')}</td></tr>
                            <tr><td>Создана:</td><td>${App.formatDateTime(campaign.created_at)}</td></tr>
                        </table>
                    </div>
                    
                    <div class="detail-section">
                        <h4>Статистика</h4>
                        <div class="stats-grid-detail">
                            <div class="stat-item-detail">
                                <span class="stat-label">Всего звонков</span>
                                <span class="stat-value">${stats.total_calls || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Отвечено</span>
                                <span class="stat-value text-success">${stats.answered || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Согласий</span>
                                <span class="stat-value text-success">${stats.agreed || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Конверсия</span>
                                <span class="stat-value">${stats.conversion_rate || 0}%</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Занято</span>
                                <span class="stat-value text-warning">${stats.busy || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Нет ответа</span>
                                <span class="stat-value">${stats.noanswer || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Ошибок</span>
                                <span class="stat-value text-danger">${stats.failed || 0}</span>
                            </div>
                            <div class="stat-item-detail">
                                <span class="stat-label">Прогресс</span>
                                <span class="stat-value">${stats.processed_contacts || 0}/${stats.total_contacts || 0}</span>
                            </div>
                        </div>
                        <div class="progress-bar" style="margin-top: 10px;">
                            <div class="progress-fill" style="width: ${stats.progress_percent || 0}%"></div>
                        </div>
                    </div>
                    
                    ${campaign.schedule ? `
                        <div class="detail-section">
                            <h4>Расписание</h4>
                            <table class="details-table">
                                <tr><td>Активно:</td><td>${campaign.schedule.enabled ? '✅ Да' : '❌ Нет'}</td></tr>
                                <tr><td>Начало:</td><td>${campaign.schedule.start_at ? App.formatDateTime(campaign.schedule.start_at) : '—'}</td></tr>
                                <tr><td>Конец:</td><td>${campaign.schedule.end_at ? App.formatDateTime(campaign.schedule.end_at) : '—'}</td></tr>
                                <tr><td>Тип:</td><td>${campaign.schedule.schedule_type || 'once'}</td></tr>
                            </table>
                        </div>
                    ` : ''}
                    
                    ${campaign.retry_strategy ? `
                        <div class="detail-section">
                            <h4>Стратегия повторных звонков</h4>
                            <table class="details-table">
                                <tr><td>Занято:</td><td>${campaign.retry_strategy.busy || 2} попыток, задержка ${campaign.retry_strategy.busy_delay || 300}с</td></tr>
                                <tr><td>Нет ответа:</td><td>${campaign.retry_strategy.noanswer || 3} попыток, задержка ${campaign.retry_strategy.noanswer_delay || 600}с</td></tr>
                                <tr><td>Ошибка:</td><td>${campaign.retry_strategy.failed || 1} попыток, задержка ${campaign.retry_strategy.failed_delay || 1800}с</td></tr>
                            </table>
                        </div>
                    ` : ''}

                    <div class="detail-section">
                        <h4>Последние звонки</h4>
                        ${(data.recent_calls && data.recent_calls.length) ? `
                            <table class="table">
                                <thead>
                                    <tr>
                                        <th>Номер</th>
                                        <th>Контакт</th>
                                        <th>Статус</th>
                                        <th>Длит.</th>
                                        <th>Дата/время</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${data.recent_calls.map(call => `
                                        <tr>
                                            <td>${this.formatPhone(call.phone)}</td>
                                            <td>${this.escapeHtml(call.contact_name || '—')}</td>
                                            <td><span class="status-badge status-${call.status}">${this.getCallStatusText(call.status)}</span></td>
                                            <td>${App.formatDuration(call.duration)}</td>
                                            <td>${App.formatDateTime(call.created_at)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                            <small>Показаны последние ${data.recent_calls.length} - полный список со всеми номерами доступен через кнопку «Экспорт» ниже</small>
                        ` : '<p class="text-muted">Звонков ещё не было</p>'}
                    </div>
                </div>
            `;
            
            // Кнопки "Экспорт"/"Назначить контакты" в подвале этой же
            // модалки читают ID именно отсюда (см. IIFE-обёртку внизу
            // campaigns.html) - без этого атрибута dataset.campaignId был
            // всегда undefined (this.state.selectedCampaign относится к
            // ДРУГОЙ модалке - редактирования, не деталей), и "Экспорт" в
            // деталях обзвона молча ничего не делал.
            modal.dataset.campaignId = id;

            modal.style.display = 'flex';

        } catch (error) {
            console.error('Failed to load campaign detail:', error);
            App.showToast('Ошибка загрузки деталей', 'error');
        }
    },

    closeCampaignDetailModal() {
        const modal = document.getElementById('campaignDetailModal');
        if (modal) {
            modal.style.display = 'none';
        }
        this.state.viewingCampaignId = null;
    },

    // =============================================
    // Назначение контактов кампании
    // =============================================
    async openAssignContactsModal(campaignId) {
        // Кнопка в подвале модалки деталей зовёт это без аргумента -
        // берём ID из dataset, который viewCampaignDetail() всегда
        // проставляет на #campaignDetailModal перед показом. Раньше это
        // подставлялось только внешней IIFE-обёрткой в campaigns.html,
        // которая не выполняется на вкладках, отдельных от "Обзвон"
        // (например "История обзвонов" - тот же #campaignDetailModal,
        // но без этого script-тега) - там кнопка была бы сломана.
        campaignId = campaignId || document.getElementById('campaignDetailModal')?.dataset.campaignId;
        if (!campaignId) return;

        // Закрываем детали
        this.closeCampaignDetailModal();
        
        try {
            // Both endpoints return a paginated envelope
            // ({items, total, page, ...} - ContactGroupListResponse /
            // ContactListResponse on the backend), not a bare array.
            const groupsData = await App.apiGet('/contact-groups/');
            const contactsData = await App.apiGet('/contacts/?limit=10000');
            const groups = groupsData.items || groupsData || [];
            const contacts = contactsData.items || contactsData || [];

            const modal = document.getElementById('assignContactsModal');
            const content = document.getElementById('assignContactsContent');
            
            if (!modal || !content) return;
            
            content.innerHTML = `
                <div class="assign-contacts">
                    <input type="hidden" id="assignCampaignId" value="${campaignId}">
                    
                    <div class="form-group">
                        <label>Выберите группы</label>
                        <div class="checkbox-group">
                            ${groups.map(g => `
                                <label>
                                    <input type="checkbox" name="groupIds" value="${g.id}">
                                    ${this.escapeHtml(g.name)} (${g.contacts_count || 0})
                                </label>
                            `).join('')}
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label>Или выберите отдельные контакты</label>
                        <select id="contactsSelect" multiple class="form-control" style="height: 200px;">
                            ${contacts.map(c => `
                                <option value="${c.id}">${this.formatPhone(c.phone)} ${c.name ? '- ' + c.name : ''}</option>
                            `).join('')}
                        </select>
                    </div>
                    
                    <div class="form-actions">
                        <button class="btn btn-primary" onclick="App.campaigns.assignContacts()">
                            Назначить контакты
                        </button>
                    </div>
                </div>
            `;
            
            modal.style.display = 'flex';
            
        } catch (error) {
            console.error('Failed to open assign modal:', error);
            App.showToast('Ошибка загрузки', 'error');
        }
    },

    async assignContacts() {
        const campaignId = document.getElementById('assignCampaignId')?.value;
        const groupCheckboxes = document.querySelectorAll('input[name="groupIds"]:checked');
        const contactsSelect = document.getElementById('contactsSelect');
        
        const groupIds = Array.from(groupCheckboxes).map(cb => parseInt(cb.value));
        const contactIds = Array.from(contactsSelect?.selectedOptions || []).map(opt => parseInt(opt.value));
        
        if (groupIds.length === 0 && contactIds.length === 0) {
            App.showToast('Выберите группы или контакты', 'warning');
            return;
        }
        
        try {
            await App.apiPost(`/campaigns/${campaignId}/assign-contacts`, {
                group_ids: groupIds,
                contact_ids: contactIds
            });
            
            App.showToast('Контакты назначены', 'success');
            App.hideModal('assignContactsModal');
            
        } catch (error) {
            console.error('Failed to assign contacts:', error);
            App.showToast(error.message || 'Ошибка назначения', 'error');
        }
    },

    // =============================================
    // Загрузка аудио для select
    // =============================================
    async loadAudioForSelect() {
        try {
            const data = await App.apiGet('/audio/?limit=100');
            this.state.audioFiles = data.items || data || [];
            
            const select = document.getElementById('campaignAudioSelect');
            if (select) {
                const currentValue = select.value;
                select.innerHTML = '<option value="">Стандартное приветствие</option>' +
                    this.state.audioFiles.map(a => 
                        `<option value="${a.id}">${this.escapeHtml(a.name)} (${a.format || 'аудио'})</option>`
                    ).join('');
                if (currentValue) select.value = currentValue;
            }
        } catch (error) {
            console.error('Failed to load audio files:', error);
        }
    },

    // =============================================
    // Экспорт результатов кампании
    // =============================================
    async exportCampaignResults(campaignId) {
        // См. комментарий в openAssignContactsModal() выше - тот же фолбэк
        // на dataset.campaignId, чтобы кнопка "Экспорт" в подвале модалки
        // деталей работала на любой вкладке, где эта модалка открыта.
        campaignId = campaignId || document.getElementById('campaignDetailModal')?.dataset.campaignId;
        if (!campaignId) return;

        try {
            const response = await App.apiGet(`/campaigns/${campaignId}/export`);
            
            let csv = 'Номер,Контакт,Статус,Длительность (с),DTMF,Дата/время\n';

            for (const call of response.calls || []) {
                csv += `${call.phone},${call.contact_name || ''},${this.getCallStatusText(call.status)},${call.duration || 0},${call.dtmf_result || ''},${call.created_at}\n`;
            }
            
            App.downloadFile(csv, `campaign_${campaignId}_results.csv`, 'text/csv');
            App.showToast('Экспорт завершён', 'success');
            
        } catch (error) {
            console.error('Failed to export results:', error);
            App.showToast('Ошибка экспорта', 'error');
        }
    },

    // =============================================
    // Утилиты
    // =============================================
    getStatusText(status) {
        const map = {
            'draft': 'Черновик',
            'ready': 'Готов',
            'running': 'Запущена',
            'paused': 'Приостановлена',
            'stopped': 'Остановлена',
            'completed': 'Завершена',
            'failed': 'Ошибка'
        };
        return map[status] || status;
    },

    // Статус ЗВОНКА (busy/noanswer/agreed/...), не статус обзвона выше -
    // те же подписи, что и в "Истории звонков" (history.js:STATUS_LABELS),
    // переиспользуем оттуда вместо повторного дублирования того же списка.
    getCallStatusText(status) {
        return App.history?.STATUS_LABELS?.[status] || status;
    },

    formatPhone(phone) {
        return App.formatPhoneNumber(phone);
    },

    formatDate(isoString) {
        if (!isoString) return '—';
        const date = new Date(isoString);
        return date.toLocaleDateString('ru-RU');
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // =============================================
    // Очистка
    // =============================================
    destroy() {
        this.state.campaigns = [];
        this.state.selectedCampaign = null;
        this.state.viewingCampaignId = null;
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.openCampaignModal = () => App.campaigns.openCampaignModal();
window.closeCampaignModal = () => App.campaigns.closeCampaignModal();
window.saveCampaign = () => App.campaigns.saveCampaign();
window.startCampaign = (id) => App.campaigns.startCampaign(id);
window.pauseCampaign = (id) => App.campaigns.pauseCampaign(id);
window.resumeCampaign = (id) => App.campaigns.resumeCampaign(id);
window.stopCampaign = (id) => App.campaigns.stopCampaign(id);
window.deleteCampaign = (id) => App.campaigns.deleteCampaign(id);
window.viewCampaignDetail = (id) => App.campaigns.viewCampaignDetail(id);
window.closeCampaignDetailModal = () => App.campaigns.closeCampaignDetailModal();
window.editCampaign = (id) => App.campaigns.editCampaign(id);
