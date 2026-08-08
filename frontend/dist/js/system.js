/**
 * AutoDialer Ultimate - System Module
 * Version: 3.0.0
 * Управление системным статусом, мониторинг, kill switch
 */

App.system = {
    // Состояние модуля
    state: {
        enabled: true,
        activeCalls: 0,
        maxCalls: 50,
        queueSize: 0,
        asteriskConnected: false,
        redisConnected: false,
        databaseConnected: false,
        cpuUsage: 0,
        memoryUsage: 0,
        uptime: 0
    },

    // WebSocket соединение
    ws: null,
    wsReconnectTimer: null,

    // =============================================
    // Инициализация
    // =============================================
    init() {
        this.refreshStatus();
        this.connectWebSocket();
        this.startPeriodicRefresh();
    },

    // =============================================
    // Получение статуса системы
    // =============================================
    async refreshStatus() {
        try {
            const data = await App.apiGet('/system/status');
            
            this.state.enabled = data.enabled;
            this.state.activeCalls = data.active_calls || 0;
            this.state.maxCalls = data.max_calls || 50;
            this.state.queueSize = data.queue_size || 0;
            this.state.asteriskConnected = data.ami_connected || false;
            this.state.redisConnected = data.redis_connected || false;
            this.state.databaseConnected = data.database_connected || false;
            this.state.cpuUsage = data.cpu_usage || 0;
            this.state.memoryUsage = data.memory_usage || 0;
            this.state.uptime = data.uptime || 0;
            
            this.updateUI();
            
        } catch (error) {
            console.error('Failed to refresh system status:', error);
            this.updateUIError();
        }
    },

    // =============================================
    // Обновление UI
    // =============================================
    updateUI() {
        // Системный статус
        const sysStatus = document.getElementById('sysStatus');
        const sysStatusIndicator = document.getElementById('sysStatusIndicator');
        
        if (sysStatus) {
            sysStatus.textContent = this.state.enabled ? 'Активна' : 'ОСТАНОВЛЕНА';
            sysStatus.style.color = this.state.enabled ? 'var(--color-success)' : 'var(--color-danger)';
        }
        
        if (sysStatusIndicator) {
            sysStatusIndicator.textContent = this.state.enabled ? '🟢' : '🔴';
        }
        
        // Каналы
        const sysChannels = document.getElementById('sysChannels');
        if (sysChannels) {
            sysChannels.textContent = `${this.state.activeCalls}/${this.state.maxCalls}`;
        }
        
        // Очередь
        const sysQueueSize = document.getElementById('sysQueueSize');
        if (sysQueueSize) {
            sysQueueSize.textContent = this.state.queueSize;
        }
        
        // Кнопка kill switch
        const killSwitch = document.getElementById('killSwitchBtn');
        if (killSwitch) {
            killSwitch.textContent = this.state.enabled ? '🛑 АВАРИЙНАЯ ОСТАНОВКА' : '🟢 ВКЛЮЧИТЬ СИСТЕМУ';
            killSwitch.style.background = this.state.enabled ? 'var(--color-danger)' : 'var(--color-success)';
        }
        
        // Статус подключений (если есть на странице)
        this.updateConnectionStatus();
    },

    updateUIError() {
        const sysStatus = document.getElementById('sysStatus');
        const sysStatusIndicator = document.getElementById('sysStatusIndicator');
        
        if (sysStatus) {
            sysStatus.textContent = 'Ошибка';
            sysStatus.style.color = 'var(--color-danger)';
        }
        if (sysStatusIndicator) {
            sysStatusIndicator.textContent = '⚠️';
        }
    },

    updateConnectionStatus() {
        const asteriskStatus = document.getElementById('asteriskStatus');
        const redisStatus = document.getElementById('redisStatus');
        const dbStatus = document.getElementById('dbStatus');
        
        if (asteriskStatus) {
            asteriskStatus.textContent = this.state.asteriskConnected ? '✅' : '❌';
            asteriskStatus.title = this.state.asteriskConnected ? 'Asterisk подключен' : 'Asterisk недоступен';
        }
        if (redisStatus) {
            redisStatus.textContent = this.state.redisConnected ? '✅' : '❌';
            redisStatus.title = this.state.redisConnected ? 'Redis подключен' : 'Redis недоступен';
        }
        if (dbStatus) {
            dbStatus.textContent = this.state.databaseConnected ? '✅' : '❌';
            dbStatus.title = this.state.databaseConnected ? 'База данных подключена' : 'База данных недоступна';
        }
    },

    // =============================================
    // Периодическое обновление
    // =============================================
    startPeriodicRefresh() {
        App.intervals.system = setInterval(() => {
            this.refreshStatus();
        }, 3000);
    },

    // =============================================
    // WebSocket для real-time обновлений
    // =============================================
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/ws/dashboard?token=${App.state.accessToken}`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('System WebSocket connected');
                if (this.wsReconnectTimer) {
                    clearTimeout(this.wsReconnectTimer);
                    this.wsReconnectTimer = null;
                }
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleWebSocketMessage(data);
                } catch (error) {
                    console.error('Failed to parse WebSocket message:', error);
                }
            };
            
            this.ws.onclose = () => {
                console.log('System WebSocket disconnected');
                this.scheduleReconnect();
            };
            
            this.ws.onerror = (error) => {
                console.error('System WebSocket error:', error);
            };
            
        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
            this.scheduleReconnect();
        }
    },

    scheduleReconnect() {
        if (this.wsReconnectTimer) return;
        
        this.wsReconnectTimer = setTimeout(() => {
            this.wsReconnectTimer = null;
            if (App.state.accessToken) {
                this.connectWebSocket();
            }
        }, 5000);
    },

    // Формат сообщений сервера (см. app/api/websocket.py):
    // {"type": "call"|"campaign"|"system"|"notification", "data": {...}}
    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'call':
                this.handleCallEvent(data.data);
                break;

            case 'system':
                this.handleSystemMessage(data.data);
                break;

            case 'notification':
                if (data.data && data.data.message) {
                    App.showToast(data.data.message, 'info');
                }
                break;

            case 'campaign':
                // Прогресс кампаний обрабатывается модулем campaigns (если подписан);
                // system.js только держит соединение и общий системный статус.
                break;
        }
    },

    handleCallEvent(call) {
        if (!call) return;

        switch (call.event) {
            case 'dial_begin':
                this.state.activeCalls++;
                this.updateUI();
                break;

            case 'hangup':
                this.state.activeCalls = Math.max(0, this.state.activeCalls - 1);
                this.updateUI();
                break;

            // 'answer' и 'dtmf' не меняют счётчик активных звонков
        }
    },

    // data либо полный снимок статуса (SystemStatusResponse — начальный снимок
    // при подключении), либо SystemNotificationEvent {level, title, message}
    // (публикуется при изменении статуса SIP/AMI и т.п.)
    handleSystemMessage(data) {
        if (!data) return;

        if ('level' in data) {
            this.handleSystemEvent(data);
            return;
        }

        this.state.enabled = data.enabled;
        this.state.activeCalls = data.active_calls || 0;
        this.state.maxCalls = data.max_calls || 50;
        this.state.queueSize = data.queue_size || 0;
        this.state.asteriskConnected = data.ami_connected || false;
        this.state.redisConnected = data.redis_connected || false;
        this.state.databaseConnected = data.database_connected || false;
        this.updateUI();
    },

    handleSystemEvent(event) {
        switch (event.level) {
            case 'warning':
                App.showToast(event.message, 'warning');
                break;
            case 'error':
            case 'critical':
                App.showToast(event.message, 'error');
                break;
            case 'info':
                App.showToast(event.message, 'info');
                break;
        }
    },

    // =============================================
    // Управление системой
    // =============================================
    async toggle() {
        const action = this.state.enabled ? 'disable' : 'enable';
        
        if (this.state.enabled) {
            if (!App.confirm('Аварийная остановка системы? Все активные звонки будут сброшены!')) {
                return;
            }
        }
        
        try {
            const response = await App.apiPost(`/system/${action}`, {});
            
            this.state.enabled = !this.state.enabled;
            this.updateUI();
            
            const message = this.state.enabled ? 'Система включена' : 'Система остановлена';
            App.showToast(message, 'success');
            
            // Обновляем статус
            await this.refreshStatus();
            
        } catch (error) {
            console.error(`Failed to ${action} system:`, error);
            App.showToast(error.message || `Ошибка ${action === 'enable' ? 'включения' : 'остановки'}`, 'error');
        }
    },

    async restart() {
        if (!App.auth.isAdmin()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        if (!App.confirm('Перезагрузить систему? Активные звонки будут сброшены!')) {
            return;
        }
        
        try {
            await App.apiPost('/system/restart', {});
            App.showToast('Система перезагружается...', 'info');
            
            // Ждём перезагрузки и обновляем статус
            setTimeout(() => this.refreshStatus(), 5000);
            
        } catch (error) {
            console.error('Failed to restart system:', error);
            App.showToast(error.message || 'Ошибка перезагрузки', 'error');
        }
    },

    async reloadConfig() {
        if (!App.auth.isAdmin()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost('/system/reload', {});
            App.showToast('Конфигурация перезагружена', 'success');
        } catch (error) {
            console.error('Failed to reload config:', error);
            App.showToast(error.message || 'Ошибка перезагрузки конфигурации', 'error');
        }
    },

    // =============================================
    // Управление Asterisk
    // =============================================
    async reloadAsteriskConfig() {
        if (!App.auth.isAdmin()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiPost('/system/asterisk/reload', {});
            App.showToast('Конфигурация Asterisk перезагружена', 'success');
        } catch (error) {
            console.error('Failed to reload Asterisk config:', error);
            App.showToast(error.message || 'Ошибка перезагрузки Asterisk', 'error');
        }
    },

    async getAsteriskChannels() {
        try {
            return await App.apiGet('/system/asterisk/channels');
        } catch (error) {
            console.error('Failed to get Asterisk channels:', error);
            return [];
        }
    },

    async getAsteriskQueues() {
        try {
            return await App.apiGet('/system/asterisk/queues');
        } catch (error) {
            console.error('Failed to get Asterisk queues:', error);
            return [];
        }
    },

    // =============================================
    // Мониторинг
    // =============================================
    async getMetrics() {
        try {
            return await App.apiGet('/system/metrics');
        } catch (error) {
            console.error('Failed to get metrics:', error);
            return null;
        }
    },

    async getHealth() {
        try {
            return await App.apiGet('/system/health');
        } catch (error) {
            console.error('Failed to get health:', error);
            return { status: 'unhealthy' };
        }
    },

    // =============================================
    // Тестовые функции
    // =============================================
    async testCall(phone) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        if (!App.validatePhone(phone)) {
            App.showToast('Неверный формат номера', 'warning');
            return;
        }
        
        try {
            const response = await App.apiPost('/system/test-call', { phone });
            App.showToast(`Тестовый звонок на ${phone} запущен`, 'success');
            return response;
        } catch (error) {
            console.error('Failed to start test call:', error);
            App.showToast(error.message || 'Ошибка запуска тестового звонка', 'error');
        }
    },

    async testAsteriskConnection() {
        try {
            const response = await App.apiPost('/system/asterisk/test', {});
            App.showToast(
                response.connected ? 'Asterisk доступен' : 'Asterisk недоступен',
                response.connected ? 'success' : 'error'
            );
            return response;
        } catch (error) {
            console.error('Failed to test Asterisk connection:', error);
            App.showToast('Ошибка проверки Asterisk', 'error');
        }
    },

    // =============================================
    // Логи системы
    // =============================================
    async getLogs(level = 'info', limit = 100) {
        try {
            return await App.apiGet(`/system/logs?level=${level}&limit=${limit}`);
        } catch (error) {
            console.error('Failed to get logs:', error);
            return [];
        }
    },

    async clearLogs() {
        if (!App.auth.isAdmin()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        if (!App.confirm('Очистить все логи системы?')) {
            return;
        }
        
        try {
            await App.apiPost('/system/logs/clear', {});
            App.showToast('Логи очищены', 'success');
        } catch (error) {
            console.error('Failed to clear logs:', error);
            App.showToast(error.message || 'Ошибка очистки логов', 'error');
        }
    },

    // =============================================
    // Информация о системе
    // =============================================
    async getSystemInfo() {
        try {
            return await App.apiGet('/system/info');
        } catch (error) {
            console.error('Failed to get system info:', error);
            return null;
        }
    },

    getUptimeFormatted() {
        const seconds = this.state.uptime;
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        
        const parts = [];
        if (days > 0) parts.push(`${days} дн`);
        if (hours > 0) parts.push(`${hours} ч`);
        if (minutes > 0) parts.push(`${minutes} мин`);
        
        return parts.length > 0 ? parts.join(' ') : 'менее минуты';
    },

    // =============================================
    // Управление очередями
    // =============================================
    async clearQueue() {
        if (!App.auth.isAdmin()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        if (!App.confirm('Очистить очередь звонков? Все ожидающие звонки будут отменены!')) {
            return;
        }
        
        try {
            await App.apiPost('/system/queue/clear', {});
            App.showToast('Очередь очищена', 'success');
            await this.refreshStatus();
        } catch (error) {
            console.error('Failed to clear queue:', error);
            App.showToast(error.message || 'Ошибка очистки очереди', 'error');
        }
    },

    async getQueueItems(limit = 50) {
        try {
            return await App.apiGet(`/system/queue?limit=${limit}`);
        } catch (error) {
            console.error('Failed to get queue items:', error);
            return [];
        }
    },

    async removeFromQueue(queueId) {
        if (!App.auth.isOperator()) {
            App.showToast('Недостаточно прав', 'error');
            return;
        }
        
        try {
            await App.apiDelete(`/system/queue/${queueId}`);
            App.showToast('Элемент удалён из очереди', 'success');
            await this.refreshStatus();
        } catch (error) {
            console.error('Failed to remove from queue:', error);
            App.showToast(error.message || 'Ошибка удаления из очереди', 'error');
        }
    },

    // =============================================
    // Очистка при уничтожении
    // =============================================
    destroy() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
            this.wsReconnectTimer = null;
        }
    }
};

// =============================================
// Экспорт глобальных функций
// =============================================
window.toggleSystem = () => App.system.toggle();
window.restartSystem = () => App.system.restart();
window.reloadConfig = () => App.system.reloadConfig();
window.clearQueue = () => App.system.clearQueue();
window.testAsteriskConnection = () => App.system.testAsteriskConnection();
