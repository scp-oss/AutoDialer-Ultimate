// users.js - Модуль управления пользователями (только для admin)
// Зависимости: app.js (AppState, authFetch, API_BASE, showToast)

const UsersModule = {
    currentPage: 1,
    pageSize: 20,
    totalPages: 1,
    totalRecords: 0,
    searchQuery: '',
    users: [],
    
    // Инициализация модуля
    init() {
        // Проверка прав доступа
        if (AppState.userRole !== 'admin') {
            this.renderAccessDenied();
            return;
        }
        
        this.render();
        this.attachEventListeners();
        this.loadUsers();
    },
    
    // Рендер страницы при отказе в доступе
    renderAccessDenied() {
        const container = document.getElementById('usersContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="access-denied">
                <div class="access-denied-icon">🔒</div>
                <h2>Доступ запрещён</h2>
                <p>У вас нет прав для просмотра этой страницы.</p>
                <p>Только администраторы могут управлять пользователями.</p>
            </div>
        `;
    },
    
    // Рендер страницы
    render() {
        const container = document.getElementById('usersContainer');
        if (!container) return;
        
        container.innerHTML = `
            <div class="users-page">
                <div class="page-header">
                    <h2>👥 Управление пользователями</h2>
                    <div class="header-actions">
                        <button class="btn btn-primary" id="userAddBtn">
                            ➕ Добавить пользователя
                        </button>
                    </div>
                </div>
                
                <p class="text-muted">
                    Управление пользователями системы. Администраторы имеют полный доступ,
                    операторы могут управлять обзвонами и контактами, наблюдатели — только просмотр.
                </p>
                
                <!-- Панель поиска -->
                <div class="users-toolbar">
                    <div class="search-box">
                        <input type="text" 
                               id="userSearch" 
                               class="form-control" 
                               placeholder="🔍 Поиск по логину, email или имени..."
                               value="${this.searchQuery}">
                    </div>
                    <div class="toolbar-actions">
                        <select id="userRoleFilter" class="form-control">
                            <option value="">Все роли</option>
                            <option value="admin">Администраторы</option>
                            <option value="operator">Операторы</option>
                            <option value="viewer">Наблюдатели</option>
                        </select>
                        <select id="userStatusFilter" class="form-control">
                            <option value="">Все статусы</option>
                            <option value="active">Активные</option>
                            <option value="inactive">Неактивные</option>
                            <option value="locked">Заблокированные</option>
                        </select>
                        <button class="btn btn-outline" id="userRefreshBtn">
                            🔄 Обновить
                        </button>
                    </div>
                </div>
                
                <!-- Статистика -->
                <div class="users-stats">
                    <div class="stat-item">
                        <span class="stat-label">Всего пользователей:</span>
                        <span class="stat-value" id="usersTotal">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Активных:</span>
                        <span class="stat-value" id="usersActive">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Администраторов:</span>
                        <span class="stat-value" id="usersAdmins">0</span>
                    </div>
                </div>
                
                <!-- Таблица -->
                <div class="users-table-container">
                    <table class="table" id="usersTable">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Логин</th>
                                <th>Email</th>
                                <th>Полное имя</th>
                                <th>Роль</th>
                                <th>Статус</th>
                                <th>Последний вход</th>
                                <th width="120">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="usersTableBody">
                            <tr><td colspan="8" class="text-center">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                
                <!-- Пагинация -->
                <div id="usersPagination" class="pagination-container"></div>
            </div>
            
            <!-- Модальное окно добавления/редактирования -->
            <div id="userModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 id="userModalTitle">Добавить пользователя</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="userForm">
                            <input type="hidden" id="userId">
                            
                            <div class="form-group">
                                <label>Логин <span class="required">*</span></label>
                                <input type="text" 
                                       id="userUsername" 
                                       class="form-control" 
                                       placeholder="Логин"
                                       autocomplete="off"
                                       required>
                                <small class="form-text">Минимум 3 символа, только латиница и цифры</small>
                            </div>
                            
                            <div class="form-group" id="userPasswordGroup">
                                <label>Пароль <span class="required" id="passwordRequired">*</span></label>
                                <div class="password-input-wrapper">
                                    <input type="password" 
                                           id="userPassword" 
                                           class="form-control" 
                                           placeholder="Пароль"
                                           autocomplete="new-password">
                                    <button type="button" class="password-toggle" data-target="userPassword">👁️</button>
                                </div>
                                <small class="form-text">Минимум 8 символов</small>
                            </div>
                            
                            <div class="form-group">
                                <label>Email</label>
                                <input type="email" 
                                       id="userEmail" 
                                       class="form-control" 
                                       placeholder="email@example.com">
                            </div>
                            
                            <div class="form-group">
                                <label>Полное имя</label>
                                <input type="text" 
                                       id="userFullName" 
                                       class="form-control" 
                                       placeholder="Иванов Иван Иванович">
                            </div>
                            
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Роль <span class="required">*</span></label>
                                    <select id="userRole" class="form-control" required>
                                        <option value="viewer">Наблюдатель (только просмотр)</option>
                                        <option value="operator">Оператор (управление обзвонами)</option>
                                        <option value="admin">Администратор (полный доступ)</option>
                                    </select>
                                </div>
                                
                                <div class="form-group">
                                    <label>Статус</label>
                                    <select id="userStatus" class="form-control">
                                        <option value="active">Активен</option>
                                        <option value="inactive">Неактивен</option>
                                    </select>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>
                                    <input type="checkbox" id="userForcePasswordChange">
                                    Потребовать смену пароля при следующем входе
                                </label>
                            </div>
                            
                            <div class="form-group">
                                <label>Заметки (опционально)</label>
                                <textarea id="userNotes" 
                                          class="form-control" 
                                          rows="2"
                                          placeholder="Дополнительная информация..."></textarea>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="UsersModule.closeModal()">
                                    Отмена
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    Сохранить
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно смены пароля -->
            <div id="userPasswordModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Сменить пароль пользователя</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <form id="userPasswordForm">
                            <input type="hidden" id="changePasswordUserId">
                            
                            <div class="form-group">
                                <label>Пользователь</label>
                                <input type="text" 
                                       id="changePasswordUsername" 
                                       class="form-control" 
                                       readonly
                                       style="background: #f8f9fa;">
                            </div>
                            
                            <div class="form-group">
                                <label>Новый пароль <span class="required">*</span></label>
                                <div class="password-input-wrapper">
                                    <input type="password" 
                                           id="newUserPassword" 
                                           class="form-control" 
                                           placeholder="Новый пароль"
                                           required>
                                    <button type="button" class="password-toggle" data-target="newUserPassword">👁️</button>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>Подтверждение пароля <span class="required">*</span></label>
                                <div class="password-input-wrapper">
                                    <input type="password" 
                                           id="newUserPasswordConfirm" 
                                           class="form-control" 
                                           placeholder="Подтвердите пароль"
                                           required>
                                    <button type="button" class="password-toggle" data-target="newUserPasswordConfirm">👁️</button>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>
                                    <input type="checkbox" id="forcePasswordChangeAfterReset">
                                    Потребовать смену пароля при следующем входе
                                </label>
                            </div>
                            
                            <div class="form-actions">
                                <button type="button" class="btn btn-outline" onclick="UsersModule.closePasswordModal()">
                                    Отмена
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    Сменить пароль
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно подтверждения удаления -->
            <div id="userDeleteModal" class="modal" style="display: none;">
                <div class="modal-content modal-sm">
                    <div class="modal-header">
                        <h3>Подтверждение удаления</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p id="userDeleteMessage">Вы уверены, что хотите удалить пользователя?</p>
                        <p class="text-warning">⚠️ Это действие нельзя отменить!</p>
                        
                        <div class="form-actions">
                            <button type="button" class="btn btn-outline" onclick="UsersModule.closeDeleteModal()">
                                Отмена
                            </button>
                            <button type="button" class="btn btn-danger" id="confirmDeleteBtn">
                                Удалить
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Модальное окно деталей -->
            <div id="userDetailModal" class="modal" style="display: none;">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Информация о пользователе</h3>
                        <button class="close-modal">&times;</button>
                    </div>
                    <div class="modal-body" id="userDetailContent">
                    </div>
                </div>
            </div>
        `;
    },
    
    // Загрузка пользователей
    async loadUsers(page = 1) {
        this.currentPage = page;
        
        const tbody = document.getElementById('usersTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Загрузка...</td></tr>';
        
        try {
            const roleFilter = document.getElementById('userRoleFilter')?.value;
            const statusFilter = document.getElementById('userStatusFilter')?.value;
            
            let url = `${API_BASE}/users/?page=${page}&page_size=${this.pageSize}`;
            if (this.searchQuery) url += `&search=${encodeURIComponent(this.searchQuery)}`;
            if (roleFilter) url += `&role=${roleFilter}`;
            if (statusFilter) url += `&status=${statusFilter}`;
            
            const response = await authFetch(url);
            if (response.ok) {
                const data = await response.json();
                this.users = data.items || data || [];
                this.totalRecords = data.total || this.users.length;
                this.totalPages = Math.ceil(this.totalRecords / this.pageSize) || 1;
                
                this.renderTable();
                this.renderPagination();
                this.updateStats(data.stats);
            } else {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка загрузки</td></tr>';
            }
        } catch (error) {
            console.error('Users load failed:', error);
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-error">Ошибка сервера</td></tr>';
        }
    },
    
    // Рендер таблицы
    renderTable() {
        const tbody = document.getElementById('usersTableBody');
        const currentUserId = AppState.user?.id;
        
        if (this.users.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center">
                        <div class="empty-state">
                            <div class="empty-icon">👥</div>
                            <p>Нет пользователей</p>
                            <button class="btn btn-primary" onclick="UsersModule.openModal()">
                                Добавить пользователя
                            </button>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        const roleNames = {
            'admin': 'Администратор',
            'operator': 'Оператор',
            'viewer': 'Наблюдатель'
        };
        
        tbody.innerHTML = this.users.map(user => `
            <tr data-id="${user.id}" class="user-row ${user.is_active ? '' : 'inactive'}">
                <td>${user.id}</td>
                <td>
                    <strong>${this.escapeHtml(user.username)}</strong>
                    ${user.id === 1 ? '<span class="badge badge-primary" style="margin-left:5px;">root</span>' : ''}
                </td>
                <td>${this.escapeHtml(user.email || '—')}</td>
                <td>${this.escapeHtml(user.full_name || '—')}</td>
                <td>
                    <span class="role-badge role-${user.role}">
                        ${roleNames[user.role] || user.role}
                    </span>
                </td>
                <td>
                    <span class="status-badge ${user.is_active ? 'status-active' : 'status-inactive'}">
                        ${user.is_active ? '✅ Активен' : '⏸️ Неактивен'}
                    </span>
                    ${user.is_locked ? '<span class="badge badge-danger">Заблокирован</span>' : ''}
                </td>
                <td>${this.formatDateTime(user.last_login)}</td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline view-user" 
                                data-id="${user.id}"
                                title="Подробнее">👁️</button>
                        <button class="btn btn-sm btn-outline edit-user" 
                                data-id="${user.id}"
                                title="Редактировать">✏️</button>
                        <button class="btn btn-sm btn-outline change-password" 
                                data-id="${user.id}"
                                data-username="${this.escapeHtml(user.username)}"
                                title="Сменить пароль">🔑</button>
                        ${user.id !== currentUserId && user.id !== 1 ? `
                            <button class="btn btn-sm btn-outline-danger delete-user" 
                                    data-id="${user.id}"
                                    data-username="${this.escapeHtml(user.username)}"
                                    title="Удалить">🗑️</button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `).join('');
        
        this.attachTableEvents();
    },
    
    // Обновление статистики
    updateStats(stats) {
        if (!stats) return;
        
        document.getElementById('usersTotal').textContent = stats.total || this.totalRecords;
        document.getElementById('usersActive').textContent = stats.active || 0;
        document.getElementById('usersAdmins').textContent = stats.admins || 0;
    },
    
    // Рендер пагинации
    renderPagination() {
        const container = document.getElementById('usersPagination');
        if (!container) return;
        
        if (this.totalPages <= 1) {
            container.innerHTML = '';
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
                this.loadUsers(parseInt(btn.dataset.page));
            });
        });
    },
    
    // ============ МОДАЛЬНЫЕ ОКНА ============
    
    openModal(user = null) {
        const modal = document.getElementById('userModal');
        const title = document.getElementById('userModalTitle');
        const passwordGroup = document.getElementById('userPasswordGroup');
        const passwordRequired = document.getElementById('passwordRequired');
        const passwordInput = document.getElementById('userPassword');
        
        if (user) {
            title.textContent = 'Редактировать пользователя';
            document.getElementById('userId').value = user.id;
            document.getElementById('userUsername').value = user.username;
            document.getElementById('userEmail').value = user.email || '';
            document.getElementById('userFullName').value = user.full_name || '';
            document.getElementById('userRole').value = user.role;
            document.getElementById('userStatus').value = user.is_active ? 'active' : 'inactive';
            document.getElementById('userForcePasswordChange').checked = user.force_password_change || false;
            document.getElementById('userNotes').value = user.notes || '';
            
            passwordRequired.style.display = 'none';
            passwordInput.required = false;
            passwordInput.placeholder = 'Оставьте пустым, чтобы не менять';
        } else {
            title.textContent = 'Добавить пользователя';
            document.getElementById('userId').value = '';
            document.getElementById('userUsername').value = '';
            document.getElementById('userEmail').value = '';
            document.getElementById('userFullName').value = '';
            document.getElementById('userRole').value = 'viewer';
            document.getElementById('userStatus').value = 'active';
            document.getElementById('userForcePasswordChange').checked = false;
            document.getElementById('userNotes').value = '';
            
            passwordRequired.style.display = 'inline';
            passwordInput.required = true;
            passwordInput.placeholder = 'Пароль';
        }
        
        modal.style.display = 'flex';
    },
    
    closeModal() {
        document.getElementById('userModal').style.display = 'none';
    },
    
    openPasswordModal(userId, username) {
        const modal = document.getElementById('userPasswordModal');
        document.getElementById('changePasswordUserId').value = userId;
        document.getElementById('changePasswordUsername').value = username;
        document.getElementById('newUserPassword').value = '';
        document.getElementById('newUserPasswordConfirm').value = '';
        document.getElementById('forcePasswordChangeAfterReset').checked = false;
        
        modal.style.display = 'flex';
    },
    
    closePasswordModal() {
        document.getElementById('userPasswordModal').style.display = 'none';
    },
    
    openDeleteModal(userId, username) {
        const modal = document.getElementById('userDeleteModal');
        document.getElementById('userDeleteMessage').textContent = 
            `Вы уверены, что хотите удалить пользователя "${username}"?`;
        document.getElementById('confirmDeleteBtn').dataset.id = userId;
        
        modal.style.display = 'flex';
    },
    
    closeDeleteModal() {
        document.getElementById('userDeleteModal').style.display = 'none';
    },
    
    async showDetailModal(userId) {
        try {
            const response = await authFetch(`${API_BASE}/users/${userId}`);
            if (!response.ok) throw new Error('Failed to load');
            
            const user = await response.json();
            
            const roleNames = {
                'admin': 'Администратор',
                'operator': 'Оператор',
                'viewer': 'Наблюдатель'
            };
            
            const content = document.getElementById('userDetailContent');
            content.innerHTML = `
                <div class="user-detail">
                    <div class="detail-section">
                        <h4>Основная информация</h4>
                        <table class="details-table">
                            <tr><td>ID:</td><td>${user.id}</td></tr>
                            <tr><td>Логин:</td><td>${this.escapeHtml(user.username)}</td></tr>
                            <tr><td>Email:</td><td>${this.escapeHtml(user.email || '—')}</td></tr>
                            <tr><td>Полное имя:</td><td>${this.escapeHtml(user.full_name || '—')}</td></tr>
                            <tr><td>Роль:</td><td>${roleNames[user.role] || user.role}</td></tr>
                            <tr><td>Статус:</td><td>${user.is_active ? 'Активен' : 'Неактивен'}</td></tr>
                            <tr><td>Заблокирован:</td><td>${user.is_locked ? 'Да' : 'Нет'}</td></tr>
                        </table>
                    </div>
                    
                    <div class="detail-section">
                        <h4>Активность</h4>
                        <table class="details-table">
                            <tr><td>Создан:</td><td>${this.formatDateTime(user.created_at)}</td></tr>
                            <tr><td>Последний вход:</td><td>${this.formatDateTime(user.last_login)}</td></tr>
                            <tr><td>Последняя активность:</td><td>${this.formatDateTime(user.last_activity)}</td></tr>
                            <tr><td>IP последнего входа:</td><td>${user.last_ip || '—'}</td></tr>
                            <tr><td>Всего входов:</td><td>${user.login_count || 0}</td></tr>
                        </table>
                    </div>
                    
                    ${user.stats ? `
                        <div class="detail-section">
                            <h4>Статистика</h4>
                            <table class="details-table">
                                <tr><td>Обзвонов создано:</td><td>${user.stats.campaigns_created || 0}</td></tr>
                                <tr><td>Обзвонов запущено:</td><td>${user.stats.campaigns_started || 0}</td></tr>
                                <tr><td>Контактов добавлено:</td><td>${user.stats.contacts_added || 0}</td></tr>
                            </table>
                        </div>
                    ` : ''}
                    
                    ${user.notes ? `
                        <div class="detail-section">
                            <h4>Заметки</h4>
                            <p>${this.escapeHtml(user.notes)}</p>
                        </div>
                    ` : ''}
                    
                    <div class="modal-actions">
                        <button class="btn btn-primary" onclick="UsersModule.closeDetailModal(); UsersModule.openModalById(${user.id})">
                            ✏️ Редактировать
                        </button>
                    </div>
                </div>
            `;
            
            document.getElementById('userDetailModal').style.display = 'flex';
        } catch (error) {
            console.error('Load user detail failed:', error);
            showToast('Ошибка загрузки', 'error');
        }
    },
    
    closeDetailModal() {
        document.getElementById('userDetailModal').style.display = 'none';
    },
    
    async openModalById(id) {
        try {
            const response = await authFetch(`${API_BASE}/users/${id}`);
            if (response.ok) {
                const user = await response.json();
                this.closeDetailModal();
                this.openModal(user);
            }
        } catch (error) {
            console.error('Load user failed:', error);
        }
    },
    
    // ============ ДЕЙСТВИЯ ============
    
    async saveUser() {
        const id = document.getElementById('userId').value;
        const username = document.getElementById('userUsername').value;
        const password = document.getElementById('userPassword').value;
        const email = document.getElementById('userEmail').value;
        const fullName = document.getElementById('userFullName').value;
        const role = document.getElementById('userRole').value;
        const isActive = document.getElementById('userStatus').value === 'active';
        const forcePasswordChange = document.getElementById('userForcePasswordChange').checked;
        const notes = document.getElementById('userNotes').value;
        
        if (!username) {
            showToast('Введите логин', 'warning');
            return;
        }
        
        if (!id && !password) {
            showToast('Введите пароль', 'warning');
            return;
        }
        
        if (password && password.length < 8) {
            showToast('Пароль должен быть не менее 8 символов', 'warning');
            return;
        }
        
        const data = {
            username,
            email: email || null,
            full_name: fullName || null,
            role,
            is_active: isActive,
            force_password_change: forcePasswordChange,
            notes: notes || null
        };
        
        if (password) {
            data.password = password;
        }
        
        const submitBtn = document.querySelector('#userForm button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Сохранение...';
        
        try {
            const url = id ? `${API_BASE}/users/${id}` : `${API_BASE}/users/`;
            const method = id ? 'PUT' : 'POST';
            
            const response = await authFetch(url, {
                method,
                body: JSON.stringify(data)
            });
            
            if (response.ok) {
                showToast(id ? 'Пользователь обновлён' : 'Пользователь создан', 'success');
                this.closeModal();
                await this.loadUsers();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка сохранения', 'error');
            }
        } catch (error) {
            console.error('Save user failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    },
    
    async changeUserPassword() {
        const userId = document.getElementById('changePasswordUserId').value;
        const newPassword = document.getElementById('newUserPassword').value;
        const confirmPassword = document.getElementById('newUserPasswordConfirm').value;
        const forceChange = document.getElementById('forcePasswordChangeAfterReset').checked;
        
        if (!newPassword) {
            showToast('Введите новый пароль', 'warning');
            return;
        }
        
        if (newPassword.length < 8) {
            showToast('Пароль должен быть не менее 8 символов', 'warning');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            showToast('Пароли не совпадают', 'warning');
            return;
        }
        
        const submitBtn = document.querySelector('#userPasswordForm button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Смена пароля...';
        
        try {
            const response = await authFetch(`${API_BASE}/users/${userId}/password`, {
                method: 'PUT',
                body: JSON.stringify({
                    new_password: newPassword,
                    force_change: forceChange
                })
            });
            
            if (response.ok) {
                showToast('Пароль изменён', 'success');
                this.closePasswordModal();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка смены пароля', 'error');
            }
        } catch (error) {
            console.error('Change password failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    },
    
    async deleteUser() {
        const userId = document.getElementById('confirmDeleteBtn').dataset.id;
        
        const submitBtn = document.getElementById('confirmDeleteBtn');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Удаление...';
        
        try {
            const response = await authFetch(`${API_BASE}/users/${userId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                showToast('Пользователь удалён', 'success');
                this.closeDeleteModal();
                await this.loadUsers();
            } else {
                const err = await response.json();
                showToast(err.detail || 'Ошибка удаления', 'error');
            }
        } catch (error) {
            console.error('Delete user failed:', error);
            showToast('Ошибка сервера', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    },
    
    // ============ ОБРАБОТЧИКИ СОБЫТИЙ ============
    
    attachEventListeners() {
        // Кнопка добавления
        document.getElementById('userAddBtn')?.addEventListener('click', () => this.openModal());
        
        // Поиск
        let searchTimeout;
        document.getElementById('userSearch')?.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.searchQuery = e.target.value;
                this.currentPage = 1;
                this.loadUsers();
            }, 300);
        });
        
        // Фильтры
        document.getElementById('userRoleFilter')?.addEventListener('change', () => {
            this.currentPage = 1;
            this.loadUsers();
        });
        
        document.getElementById('userStatusFilter')?.addEventListener('change', () => {
            this.currentPage = 1;
            this.loadUsers();
        });
        
        // Обновление
        document.getElementById('userRefreshBtn')?.addEventListener('click', () => this.loadUsers());
        
        // Форма пользователя
        document.getElementById('userForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveUser();
        });
        
        // Форма смены пароля
        document.getElementById('userPasswordForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.changeUserPassword();
        });
        
        // Кнопка подтверждения удаления
        document.getElementById('confirmDeleteBtn')?.addEventListener('click', () => this.deleteUser());
        
        // Переключение видимости пароля
        document.querySelectorAll('.password-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.dataset.target;
                const input = document.getElementById(targetId);
                if (input) {
                    input.type = input.type === 'password' ? 'text' : 'password';
                    btn.textContent = input.type === 'password' ? '👁️' : '🙈';
                }
            });
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
    },
    
    attachTableEvents() {
        document.querySelectorAll('.view-user').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDetailModal(btn.dataset.id);
            });
        });
        
        document.querySelectorAll('.edit-user').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                const user = this.users.find(u => u.id == id);
                if (user) this.openModal(user);
            });
        });
        
        document.querySelectorAll('.change-password').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openPasswordModal(btn.dataset.id, btn.dataset.username);
            });
        });
        
        document.querySelectorAll('.delete-user').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openDeleteModal(btn.dataset.id, btn.dataset.username);
            });
        });
        
        // Клик по строке
        document.querySelectorAll('.user-row').forEach(row => {
            row.addEventListener('click', () => {
                this.showDetailModal(row.dataset.id);
            });
        });
    },
    
    // ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
    
    formatDateTime(dateStr) {
        if (!dateStr) return '—';
        // См. подробный комментарий в audit.js::formatDateTime() - тот же
        // баг: без App.parseServerDate() время показывалось на 3 часа
        // (разница UTC/Europe-Moscow) раньше реального.
        const date = App.parseServerDate(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).replace(',', '');
    },
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // Кнопка 👤 в шапке (index.html) вызывает App.users.showProfile() на
    // любой вкладке, а не только на "Пользователи" - эта функция раньше
    // не существовала вовсе, поэтому клик не делал ничего. passwordModal
    // (modals.html) грузится один раз глобально при старте приложения,
    // поэтому безопасно открывать его независимо от активной вкладки.
    showProfile() {
        App.auth.showPasswordChangeModal();
    }
};

// Экспорт глобально
window.UsersModule = UsersModule;
App.users = UsersModule;
