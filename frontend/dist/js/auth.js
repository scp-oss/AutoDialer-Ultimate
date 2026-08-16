/**
 * AutoDialer Ultimate - Authentication Module
 * Version: 3.0.0
 */

App.auth = {
    // =============================================
    // Login
    // =============================================
    async login() {
        const username = document.getElementById('loginUsername')?.value;
        const password = document.getElementById('loginPassword')?.value;
        const errorDiv = document.getElementById('loginError');
        const submitBtn = document.querySelector('#loginForm button[type="submit"]');

        if (errorDiv) errorDiv.textContent = '';

        if (!username || !password) {
            if (errorDiv) errorDiv.textContent = 'Введите логин и пароль';
            return;
        }

        // Без видимого состояния загрузки клик по "Войти" не даёт никакой
        // обратной связи, пока идут /auth/login + /auth/me + загрузка
        // вкладки дашборда - выглядит так, будто кнопка не сработала.
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Вход...';
        }

        try {
            const response = await fetch(`${App.API_BASE}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            // Nginx's rate limiter (or any other infra in front of the
            // API) can reject the request before it ever reaches the
            // backend, returning an HTML error page instead of JSON -
            // response.json() then throws a confusing "Unexpected token
            // '<'" SyntaxError that masked the real cause (429 Too Many
            // Requests). Detect that case and show a clear message.
            if (response.status === 429) {
                throw new Error('Слишком много попыток входа. Подождите немного и попробуйте снова.');
            }

            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                throw new Error(`Сервер вернул неожиданный ответ (HTTP ${response.status})`);
            }

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Ошибка входа');
            }

            // Учётка с включённой 2FA возвращает 200 OK с пустыми токенами,
            // ожидая TOTP-код вторым запросом - без этой проверки пустой
            // access_token тихо сохранялся и все последующие запросы (в
            // т.ч. /auth/me) молча падали с 401 без видимой причины.
            if (!data.access_token) {
                throw new Error('Требуется код двухфакторной аутентификации');
            }

            // Сохраняем токены
            App.state.accessToken = data.access_token;
            App.state.refreshToken = data.refresh_token;
            App.state.userRole = data.role;

            localStorage.setItem('refresh_token', data.refresh_token);

            // Загружаем информацию о пользователе
            await this.loadCurrentUser();

            // Проверяем необходимость смены пароля
            if (data.force_password_change) {
                this.showPasswordChangeModal();
            } else {
                App.showApp();
            }

        } catch (error) {
            console.error('Login error:', error);
            if (errorDiv) errorDiv.textContent = error.message;
            App.showToast(error.message || 'Ошибка входа', 'error');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Войти';
            }
        }
    },

    // =============================================
    // Auto Login
    // =============================================
    async tryAutoLogin() {
        if (!App.state.refreshToken) {
            return;
        }

        try {
            // RefreshTokenRequest on the backend requires refresh_token in
            // the JSON body (app/models/auth.py) - sending it only as an
            // Authorization header (as this used to) gets no body at all,
            // so FastAPI rejects it with 422 every single time. That made
            // every page reload with a stored refresh token silently wipe
            // it and dump the user back to the login screen, even right
            // after a successful login.
            const response = await fetch(`${App.API_BASE}/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: App.state.refreshToken })
            });
            
            if (response.ok) {
                const data = await response.json();
                App.state.accessToken = data.access_token;
                await this.loadCurrentUser();
                App.showApp();
            } else {
                // Токен невалиден, очищаем
                localStorage.removeItem('refresh_token');
                App.state.refreshToken = '';
            }
        } catch (error) {
            console.error('Auto login failed:', error);
        }
    },

    // =============================================
    // Refresh Token
    // =============================================
    async refreshToken() {
        if (!App.state.refreshToken) {
            this.logout();
            return false;
        }

        try {
            const response = await fetch(`${App.API_BASE}/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: App.state.refreshToken })
            });
            
            if (response.ok) {
                const data = await response.json();
                App.state.accessToken = data.access_token;
                return true;
            } else {
                this.logout();
                return false;
            }
        } catch (error) {
            console.error('Token refresh failed:', error);
            this.logout();
            return false;
        }
    },

    // =============================================
    // Logout
    // =============================================
    async logout() {
        try {
            if (App.state.accessToken) {
                await App.apiPost('/auth/logout', {});
            }
        } catch (error) {
            // Игнорируем ошибки при логауте
        } finally {
            // Очищаем состояние
            App.state.accessToken = '';
            App.state.refreshToken = '';
            App.state.user = null;
            App.state.userRole = '';
            
            localStorage.removeItem('refresh_token');
            
            // Останавливаем периодические обновления
            App.stopPeriodicRefresh();
            
            // Показываем экран логина
            document.getElementById('appScreen').style.display = 'none';
            document.getElementById('loginScreen').style.display = 'flex';
            
            // Очищаем поля логина
            const usernameInput = document.getElementById('loginUsername');
            const passwordInput = document.getElementById('loginPassword');
            if (usernameInput) usernameInput.value = '';
            if (passwordInput) passwordInput.value = '';
        }
    },

    // =============================================
    // Load Current User
    // =============================================
    async loadCurrentUser() {
        try {
            const response = await App.apiGet('/auth/me');
            App.state.user = response;
            App.state.userRole = response.role;
        } catch (error) {
            console.error('Failed to load user:', error);
            throw error;
        }
    },

    // =============================================
    // Change Password
    // =============================================
    showPasswordChangeModal() {
        const modal = document.getElementById('passwordModal');
        if (modal) {
            modal.style.display = 'flex';
            // Очищаем поля
            document.getElementById('oldPassword').value = '';
            document.getElementById('newPassword1').value = '';
            document.getElementById('newPassword2').value = '';
            document.getElementById('passwordError').textContent = '';
        }
    },

    closePasswordModal() {
        const modal = document.getElementById('passwordModal');
        if (modal) {
            modal.style.display = 'none';
        }
    },

    async changePassword() {
        const oldPassword = document.getElementById('oldPassword')?.value;
        const newPassword1 = document.getElementById('newPassword1')?.value;
        const newPassword2 = document.getElementById('newPassword2')?.value;
        const errorDiv = document.getElementById('passwordError');
        
        // Валидация
        if (!oldPassword) {
            if (errorDiv) errorDiv.textContent = 'Введите текущий пароль';
            return;
        }
        
        if (newPassword1 !== newPassword2) {
            if (errorDiv) errorDiv.textContent = 'Пароли не совпадают';
            return;
        }
        
        if (!App.validatePassword(newPassword1)) {
            if (errorDiv) errorDiv.textContent = 'Пароль должен содержать минимум 8 символов, заглавные и строчные буквы, цифры';
            return;
        }
        
        try {
            const response = await App.apiPost('/auth/change-password', {
                old_password: oldPassword,
                new_password: newPassword1
            });
            
            App.showToast('Пароль успешно изменён', 'success');
            this.closePasswordModal();
            
            // Если это была принудительная смена, показываем приложение
            if (App.state.user?.force_password_change) {
                App.state.user.force_password_change = false;
                App.showApp();
            }
            
        } catch (error) {
            console.error('Password change error:', error);
            if (errorDiv) errorDiv.textContent = error.message || 'Ошибка смены пароля';
        }
    },

    // =============================================
    // Password Reset (Admin only)
    // =============================================
    async resetUserPassword(userId, newPassword) {
        if (!App.validatePassword(newPassword)) {
            throw new Error('Пароль не соответствует требованиям');
        }
        
        return App.apiPost('/auth/reset-password', {
            user_id: userId,
            new_password: newPassword
        });
    },

    // =============================================
    // Permissions Check
    // =============================================
    isAdmin() {
        return App.state.userRole === 'admin';
    },

    isOperator() {
        return App.state.userRole === 'operator' || App.state.userRole === 'admin';
    },

    isViewer() {
        return App.state.userRole === 'viewer';
    },

    hasPermission(permission) {
        const permissions = {
            'view_dashboard': true,
            'view_campaigns': true,
            'view_contacts': true,
            'view_history': true,
            'view_audio': true,
            'view_incoming': true,
            'manage_campaigns': this.isOperator(),
            'manage_contacts': this.isOperator(),
            'manage_audio': this.isOperator(),
            'start_campaigns': this.isOperator(),
            'stop_campaigns': this.isAdmin(),
            'delete_campaigns': this.isAdmin(),
            'manage_users': this.isAdmin(),
            'manage_settings': this.isAdmin(),
            'view_audit': this.isAdmin(),
            'manage_api_tokens': this.isAdmin(),
            'manage_webhooks': this.isAdmin(),
            'system_control': this.isAdmin()
        };
        
        return permissions[permission] ?? false;
    },

    // =============================================
    // Session Management
    // =============================================
    getSessionInfo() {
        if (!App.state.accessToken) return null;
        
        try {
            // Декодируем payload JWT (без проверки подписи)
            const token = App.state.accessToken;
            const payload = token.split('.')[1];
            const decoded = JSON.parse(atob(payload));
            
            return {
                user: decoded.sub,
                role: decoded.role,
                exp: new Date(decoded.exp * 1000),
                iat: new Date(decoded.iat * 1000)
            };
        } catch (error) {
            console.error('Failed to parse token:', error);
            return null;
        }
    },

    isSessionExpired() {
        const session = this.getSessionInfo();
        if (!session) return true;
        return session.exp < new Date();
    },

    getSessionTimeRemaining() {
        const session = this.getSessionInfo();
        if (!session) return 0;
        
        const remaining = session.exp - new Date();
        return Math.max(0, Math.floor(remaining / 1000));
    },

    // =============================================
    // UI Helpers
    // =============================================
    openPasswordModal() {
        // Закрываем профиль если открыт
        App.users?.closeProfileModal();
        this.showPasswordChangeModal();
    },

    // =============================================
    // Two-Factor Authentication (заготовка)
    // =============================================
    async setup2FA() {
        try {
            const response = await App.apiPost('/auth/2fa/setup', {});
            return response;
        } catch (error) {
            console.error('2FA setup failed:', error);
            throw error;
        }
    },

    async verify2FA(code) {
        try {
            const response = await App.apiPost('/auth/2fa/verify', { code });
            return response;
        } catch (error) {
            console.error('2FA verification failed:', error);
            throw error;
        }
    },

    async disable2FA() {
        try {
            const response = await App.apiPost('/auth/2fa/disable', {});
            return response;
        } catch (error) {
            console.error('2FA disable failed:', error);
            throw error;
        }
    }
};

// =============================================
// Экспорт глобальных функций для HTML
// =============================================
window.login = () => App.auth.login();
window.logout = () => App.auth.logout();
window.changePassword = () => App.auth.changePassword();
window.closePasswordModal = () => App.auth.closePasswordModal();
window.openPasswordModal = () => App.auth.openPasswordModal();
