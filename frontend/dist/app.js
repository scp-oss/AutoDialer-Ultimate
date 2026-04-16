/**
 * AutoDialer Ultimate - Frontend Application
 * Version: 3.0.0
 * Enterprise-grade auto dialer system
 */

// =============================================
// Global State
// =============================================
const AppState = {
    accessToken: '',
    refreshToken: '',
    user: null,
    userRole: '',
    forcePasswordChange: false,
    currentTab: 'dashboard',
    systemEnabled: true,
    activeCalls: 0,
    maxCalls: 50,
    stats: {
        totalCalls: 0,
        agreed: 0,
        busy: 0,
        noanswer: 0,
        failed: 0,
        todayCalls: 0,
        conversionRate: 0
    },
    campaigns: [],
    contacts: [],
    contactGroups: [],
    audioFiles: [],
    users: [],
    settings: {},
    chart: null
};

const API_BASE = '/api';

// =============================================
// Initialization
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    const savedRefreshToken = localStorage.getItem('refresh_token');
    if (savedRefreshToken) {
        AppState.refreshToken = savedRefreshToken;
        tryAutoLogin();
    }
    setupEventListeners();
});

function setupEventListeners() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', (e) => {
            e.preventDefault();
            login();
        });
    }
}

// =============================================
// Authentication
// =============================================
async function tryAutoLogin() {
    try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${AppState.refreshToken}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            AppState.accessToken = data.access_token;
            await loadCurrentUser();
            showApp();
        } else {
            localStorage.removeItem('refresh_token');
        }
    } catch (error) {
        console.error('Auto login failed:', error);
    }
}

async function login() {
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    const errorDiv = document.getElementById('loginError');
    
    if (!username || !password) {
        errorDiv.textContent = 'Введите логин и пароль';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Ошибка входа');
        }
        
        AppState.accessToken = data.access_token;
        AppState.refreshToken = data.refresh_token;
        AppState.userRole = data.role;
        AppState.forcePasswordChange = data.force_password_change;
        
        localStorage.setItem('refresh_token', AppState.refreshToken);
        
        if (AppState.forcePasswordChange) {
            showPasswordModal();
        } else {
            await loadCurrentUser();
            showApp();
        }
    } catch (error) {
        errorDiv.textContent = error.message;
    }
}

async function logout() {
    try {
        await authFetch(`${API_BASE}/auth/logout`, { method: 'POST' });
    } catch (error) {
        // Ignore
    }
    
    localStorage.removeItem('refresh_token');
    AppState.accessToken = '';
    AppState.refreshToken = '';
    AppState.user = null;
    AppState.userRole = '';
    
    document.getElementById('appScreen').style.display = 'none';
    document.getElementById('loginScreen').style.display = 'flex';
}

async function changePassword() {
    const oldPassword = document.getElementById('oldPassword').value;
    const newPassword1 = document.getElementById('newPassword1').value;
    const newPassword2 = document.getElementById('newPassword2').value;
    const errorDiv = document.getElementById('passwordError');
    
    if (newPassword1 !== newPassword2) {
        errorDiv.textContent = 'Пароли не совпадают';
        return;
    }
    
    if (newPassword1.length < 8) {
        errorDiv.textContent = 'Пароль должен быть не менее 8 символов';
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/auth/change-password`, {
            method: 'POST',
            body: JSON.stringify({ old_password: oldPassword, new_password: newPassword1 })
        });
        
        if (response.ok) {
            closePasswordModal();
            showToast('Пароль успешно изменён', 'success');
        } else {
            const data = await response.json();
            errorDiv.textContent = data.detail || 'Ошибка смены пароля';
        }
    } catch (error) {
        errorDiv.textContent = 'Ошибка сервера';
    }
}

function showPasswordModal() {
    document.getElementById('passwordModal').style.display = 'flex';
}

function closePasswordModal() {
    document.getElementById('passwordModal').style.display = 'none';
}

function openPasswordModal() {
    closeProfileModal();
    showPasswordModal();
}

// =============================================
// API Helpers
// =============================================
async function authFetch(url, options = {}) {
    if (!options.headers) {
        options.headers = {};
    }
    options.headers['Authorization'] = `Bearer ${AppState.accessToken}`;
    options.headers['Content-Type'] = options.headers['Content-Type'] || 'application/json';
    
    let response = await fetch(url, options);
    
    if (response.status === 401) {
        const refreshed = await refreshAccessToken();
        if (refreshed) {
            options.headers['Authorization'] = `Bearer ${AppState.accessToken}`;
            response = await fetch(url, options);
        }
    }
    
    return response;
}

async function refreshAccessToken() {
    if (!AppState.refreshToken) {
        logout();
        return false;
    }
    
    try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${AppState.refreshToken}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            AppState.accessToken = data.access_token;
            return true;
        }
    } catch (error) {
        console.error('Token refresh failed:', error);
    }
    
    logout();
    return false;
}

async function loadCurrentUser() {
    try {
        const response = await authFetch(`${API_BASE}/auth/me`);
        if (response.ok) {
            AppState.user = await response.json();
            AppState.userRole = AppState.user.role;
        }
    } catch (error) {
        console.error('Failed to load user:', error);
    }
}

// =============================================
// UI Functions
// =============================================
function showApp() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('appScreen').style.display = 'block';
    
    updateUserDisplay();
    applyRoleBasedUI();
    
    switchTab('dashboard');
    startPeriodicRefresh();
}

function updateUserDisplay() {
    const userDisplay = document.getElementById('userDisplay');
    if (userDisplay && AppState.user) {
        userDisplay.innerHTML = `
            <span class="badge badge-${AppState.user.role}">${AppState.user.role}</span>
            ${AppState.user.username}
        `;
    }
}

function applyRoleBasedUI() {
    const isAdmin = AppState.userRole === 'admin';
    
    document.querySelectorAll('.admin-only').forEach(el => {
        el.style.display = isAdmin ? '' : 'none';
    });
    
    const killSwitch = document.getElementById('killSwitchBtn');
    if (killSwitch) {
        killSwitch.style.display = isAdmin ? '' : 'none';
    }
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
    
    document.getElementById(tabId).classList.add('active');
    document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');
    
    AppState.currentTab = tabId;
    loadTabContent(tabId);
}

async function loadTabContent(tabId) {
    switch (tabId) {
        case 'dashboard':
            await loadDashboard();
            break;
        case 'campaigns':
            await loadCampaigns();
            break;
        case 'contacts':
            await loadContacts();
            await loadContactGroupsForSelect();
            break;
        case 'contactGroups':
            await loadContactGroups();
            break;
        case 'history':
            await loadHistory();
            await loadCampaignsForFilter();
            break;
        case 'audio':
            await loadAudio();
            await loadCampaignsForAudioSelect();
            break;
        case 'blacklist':
            await loadBlacklist();
            break;
        case 'users':
            await loadUsers();
            break;
        case 'settings':
            await loadSettings();
            break;
        case 'audit':
            await loadAuditLog();
            break;
        case 'apiTokens':
            await loadApiTokens();
            break;
        case 'webhooks':
            await loadWebhooks();
            break;
    }
}

function startPeriodicRefresh() {
    setInterval(async () => {
        await refreshSystemStatus();
        if (AppState.currentTab === 'dashboard') {
            await loadDashboardStats();
        }
    }, 3000);
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()" style="background:none;border:none;color:white;cursor:pointer;margin-left:10px;">&times;</button>
    `;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

// =============================================
// Profile
// =============================================
function showUserProfile() {
    if (AppState.user) {
        document.getElementById('profileUsername').textContent = AppState.user.username;
        document.getElementById('profileEmail').textContent = AppState.user.email || '-';
        document.getElementById('profileFullName').textContent = AppState.user.full_name || '-';
        document.getElementById('profileRole').textContent = AppState.user.role;
        document.getElementById('profileLastLogin').textContent = AppState.user.last_login ? new Date(AppState.user.last_login).toLocaleString() : '-';
        document.getElementById('profileModal').style.display = 'flex';
    }
}

function closeProfileModal() {
    document.getElementById('profileModal').style.display = 'none';
}

// =============================================
// System Status
// =============================================
async function refreshSystemStatus() {
    try {
        const response = await authFetch(`${API_BASE}/system/status`);
        if (response.ok) {
            const data = await response.json();
            AppState.systemEnabled = data.enabled;
            AppState.activeCalls = data.active_calls;
            AppState.maxCalls = data.max_calls;
            
            updateSystemBar(data);
        }
    } catch (error) {
        console.error('Status refresh failed:', error);
    }
}

function updateSystemBar(data) {
    const sysStatus = document.getElementById('sysStatus');
    const sysChannels = document.getElementById('sysChannels');
    const killSwitch = document.getElementById('killSwitchBtn');
    
    if (sysStatus) {
        sysStatus.textContent = data.enabled ? 'Активна' : 'ОСТАНОВЛЕНА';
        sysStatus.style.color = data.enabled ? '#10b981' : '#ef4444';
    }
    
    if (sysChannels) {
        sysChannels.textContent = `${data.active_calls}/${data.max_calls}`;
    }
    
    if (killSwitch) {
        killSwitch.textContent = data.enabled ? '🛑 АВАРИЙНАЯ ОСТАНОВКА' : '🟢 ВКЛЮЧИТЬ СИСТЕМУ';
    }
}

async function toggleSystem() {
    const action = AppState.systemEnabled ? 'disable' : 'enable';
    
    if (AppState.systemEnabled) {
        if (!confirm('Аварийная остановка системы? Все активные звонки будут сброшены!')) {
            return;
        }
    }
    
    try {
        const response = await authFetch(`${API_BASE}/system/${action}`, { method: 'POST' });
        
        if (response.ok) {
            await refreshSystemStatus();
            showToast(`Система ${AppState.systemEnabled ? 'включена' : 'остановлена'}`, 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

// =============================================
// Dashboard
// =============================================
async function loadDashboard() {
    await loadDashboardStats();
    await loadActiveCampaigns();
    await loadRecentCalls();
    await loadChart();
}

async function loadDashboardStats() {
    try {
        const response = await authFetch(`${API_BASE}/stats`);
        if (response.ok) {
            const data = await response.json();
            AppState.stats = data;
            
            document.getElementById('dashTotal').textContent = data.total_calls || 0;
            document.getElementById('dashAgreed').textContent = data.agreed || 0;
            document.getElementById('dashToday').textContent = data.today_calls || 0;
            document.getElementById('dashConversion').textContent = `${data.conversion_rate || 0}%`;
            document.getElementById('dashBusy').textContent = data.busy || 0;
            document.getElementById('dashNoanswer').textContent = data.noanswer || 0;
        }
    } catch (error) {
        console.error('Stats load failed:', error);
    }
}

async function loadActiveCampaigns() {
    try {
        const response = await authFetch(`${API_BASE}/campaigns?status=running`);
        if (response.ok) {
            const campaigns = await response.json();
            const container = document.getElementById('activeCampaignsList');
            
            if (!campaigns || campaigns.length === 0) {
                container.innerHTML = '<div class="loading">Нет активных кампаний</div>';
                return;
            }
            
            container.innerHTML = campaigns.map(c => `
                <div class="campaign-item">
                    <div>
                        <strong>${c.name}</strong>
                        <span class="status-badge status-${c.status}">${c.status}</span>
                    </div>
                    <div class="progress-bar" style="width:200px;">
                        <div class="progress-fill" style="width:${c.stats?.progress_percent || 0}%"></div>
                    </div>
                    <div>${c.stats?.called_contacts || 0}/${c.stats?.total_contacts || 0}</div>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Active campaigns load failed:', error);
    }
}

async function loadRecentCalls() {
    try {
        const response = await authFetch(`${API_BASE}/history?limit=5`);
        if (response.ok) {
            const data = await response.json();
            const container = document.getElementById('recentCalls');
            
            if (!data.history || data.history.length === 0) {
                container.innerHTML = '<div class="loading">Нет звонков</div>';
                return;
            }
            
            container.innerHTML = data.history.map(c => `
                <div class="call-item">
                    <span>${new Date(c.created_at).toLocaleTimeString()}</span>
                    <span>${c.phone}</span>
                    <span class="status-badge status-${c.status}">${c.status}</span>
                    <span>${c.campaign_name || '-'}</span>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Recent calls load failed:', error);
    }
}

async function loadChart() {
    try {
        const response = await authFetch(`${API_BASE}/stats`);
        if (response.ok) {
            const data = await response.json();
            
            const ctx = document.getElementById('statsChart')?.getContext('2d');
            if (!ctx) return;
            
            if (AppState.chart) {
                AppState.chart.destroy();
            }
            
            const daily = data.daily || [];
            
            AppState.chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: daily.map(d => d.date).reverse(),
                    datasets: [{
                        label: 'Всего звонков',
                        data: daily.map(d => d.total).reverse(),
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        fill: true
                    }, {
                        label: 'Согласий',
                        data: daily.map(d => d.agreed).reverse(),
                        borderColor: '#10b981',
                        backgroundColor: 'transparent'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            labels: { color: '#f1f5f9' }
                        }
                    },
                    scales: {
                        x: { ticks: { color: '#94a3b8' } },
                        y: { ticks: { color: '#94a3b8' } }
                    }
                }
            });
        }
    } catch (error) {
        console.error('Chart load failed:', error);
    }
}

// =============================================
// Campaigns
// =============================================
async function loadCampaigns() {
    try {
        const response = await authFetch(`${API_BASE}/campaigns`);
        if (response.ok) {
            const campaigns = await response.json();
            AppState.campaigns = campaigns;
            renderCampaignsTable(campaigns);
        }
    } catch (error) {
        console.error('Campaigns load failed:', error);
    }
}

function renderCampaignsTable(campaigns) {
    const tbody = document.getElementById('campaignsTable');
    
    if (!campaigns || campaigns.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Нет кампаний</td></tr>';
        return;
    }
    
    const statusMap = {
        'draft': 'Черновик',
        'running': 'Запущена',
        'paused': 'Приостановлена',
        'stopped': 'Остановлена',
        'completed': 'Завершена',
        'failed': 'Ошибка'
    };
    
    tbody.innerHTML = campaigns.map(c => `
        <tr>
            <td>${c.id}</td>
            <td>${c.name}</td>
            <td><span class="status-badge status-${c.status}">${statusMap[c.status] || c.status}</span></td>
            <td>${c.max_calls}</td>
            <td>${c.cps}</td>
            <td>
                <div class="progress-bar" style="width:80px;">
                    <div class="progress-fill" style="width:${c.stats?.progress_percent || 0}%"></div>
                </div>
                ${c.stats?.called_contacts || 0}/${c.stats?.total_contacts || 0}
            </td>
            <td>${c.stats?.conversion_rate || 0}%</td>
            <td class="actions">
                <button class="btn btn-outline btn-sm" onclick="viewCampaignDetail(${c.id})" title="Просмотр">👁</button>
                ${c.status === 'draft' ? `<button class="btn btn-success btn-sm" onclick="startCampaign(${c.id})" title="Запустить">▶</button>` : ''}
                ${c.status === 'running' ? `<button class="btn btn-warning btn-sm" onclick="pauseCampaign(${c.id})" title="Пауза">⏸</button>` : ''}
                ${c.status === 'paused' ? `<button class="btn btn-success btn-sm" onclick="resumeCampaign(${c.id})" title="Продолжить">▶</button>` : ''}
                ${c.status === 'running' && AppState.userRole === 'admin' ? `<button class="btn btn-danger btn-sm" onclick="stopCampaign(${c.id})" title="Остановить">⏹</button>` : ''}
                ${AppState.userRole === 'admin' && c.status !== 'running' ? `<button class="btn btn-outline btn-sm" onclick="deleteCampaign(${c.id})" title="Удалить">🗑</button>` : ''}
            </td>
        </tr>
    `).join('');
}

async function startCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/start`, { method: 'POST' });
        
        if (response.ok) {
            loadCampaigns();
            showToast('Кампания запущена', 'success');
        } else {
            const data = await response.json();
            showToast(data.detail || 'Ошибка запуска', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function stopCampaign(id) {
    if (!confirm('Остановить кампанию?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/stop`, { method: 'POST' });
        
        if (response.ok) {
            loadCampaigns();
            showToast('Кампания остановлена', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function pauseCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/pause`, { method: 'POST' });
        
        if (response.ok) {
            loadCampaigns();
            showToast('Кампания приостановлена', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function resumeCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/resume`, { method: 'POST' });
        
        if (response.ok) {
            loadCampaigns();
            showToast('Кампания возобновлена', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function deleteCampaign(id) {
    if (!confirm('Удалить кампанию? Это действие нельзя отменить.')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            loadCampaigns();
            showToast('Кампания удалена', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function viewCampaignDetail(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}`);
        if (response.ok) {
            const data = await response.json();
            const campaign = data.campaign;
            const stats = data.stats;
            
            document.getElementById('campaignDetailTitle').textContent = campaign.name;
            
            document.getElementById('campaignDetailStats').innerHTML = `
                <div class="stats-grid">
                    <div class="stat-card"><div class="stat-value">${stats.total_calls || 0}</div><div>Звонков</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.agreed || 0}</div><div>Согласий</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.busy || 0}</div><div>Занято</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.noanswer || 0}</div><div>Нет ответа</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.conversion_rate || 0}%</div><div>Конверсия</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.avg_duration || 0}с</div><div>Ср. длит.</div></div>
                </div>
            `;
            
            document.getElementById('campaignScheduleInfo').innerHTML = campaign.schedule 
                ? `<p>Расписание: ${JSON.stringify(campaign.schedule)}</p>`
                : '<p>Расписание не настроено</p>';
            
            document.getElementById('campaignDetailModal').style.display = 'flex';
        }
    } catch (error) {
        console.error('Campaign detail failed:', error);
    }
}

function closeCampaignDetailModal() {
    document.getElementById('campaignDetailModal').style.display = 'none';
}

function openCampaignModal() {
    document.getElementById('campaignModal').style.display = 'flex';
    loadAudioForSelect();
}

function closeCampaignModal() {
    document.getElementById('campaignModal').style.display = 'none';
    document.getElementById('campaignNameInput').value = '';
    document.getElementById('campaignDescription').value = '';
}

async function createCampaign() {
    const name = document.getElementById('campaignNameInput').value;
    const description = document.getElementById('campaignDescription').value;
    const maxCalls = parseInt(document.getElementById('campaignMaxCalls').value);
    const cps = parseInt(document.getElementById('campaignCps').value);
    const audioId = document.getElementById('campaignAudioSelect').value;
    const callerId = document.getElementById('campaignCallerId').value;
    
    if (!name) {
        showToast('Введите название кампании', 'warning');
        return;
    }
    
    const data = { name, description, max_calls: maxCalls, cps, audio_id: audioId || null, caller_id: callerId || null };
    
    // Schedule
    if (document.getElementById('campaignScheduleEnabled').checked) {
        data.schedule = {
            enabled: true,
            start_at: document.getElementById('scheduleStartAt').value || null,
            end_at: document.getElementById('scheduleEndAt').value || null,
            schedule_type: document.getElementById('scheduleType').value
        };
    }
    
    // Retry strategy
    data.retry_strategy = {
        busy: parseInt(document.getElementById('retryBusyMax').value),
        busy_delay: parseInt(document.getElementById('retryBusyDelay').value),
        noanswer: parseInt(document.getElementById('retryNoanswerMax').value),
        noanswer_delay: parseInt(document.getElementById('retryNoanswerDelay').value),
        failed: parseInt(document.getElementById('retryFailedMax').value),
        failed_delay: parseInt(document.getElementById('retryFailedDelay').value)
    };
    
    try {
        const response = await authFetch(`${API_BASE}/campaigns`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            closeCampaignModal();
            loadCampaigns();
            showToast('Кампания создана', 'success');
        } else {
            const err = await response.json();
            showToast(err.detail || 'Ошибка создания', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function loadCampaignsForFilter() {
    try {
        const response = await authFetch(`${API_BASE}/campaigns`);
        if (response.ok) {
            const campaigns = await response.json();
            const select = document.getElementById('historyFilterCampaign');
            if (select) {
                select.innerHTML = '<option value="">Все кампании</option>' +
                    campaigns.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
            }
        }
    } catch (error) {
        console.error('Load campaigns for filter failed:', error);
    }
}

async function loadCampaignsForAudioSelect() {
    try {
        const response = await authFetch(`${API_BASE}/campaigns`);
        if (response.ok) {
            const campaigns = await response.json();
            const selectAudio = document.getElementById('audioCampaign');
            const selectUpload = document.getElementById('audioUploadCampaign');
            const selectCampaign = document.getElementById('campaignAudioSelect');
            
            const options = '<option value="">Нет</option>' +
                campaigns.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
            
            if (selectAudio) selectAudio.innerHTML = options;
            if (selectUpload) selectUpload.innerHTML = options;
            if (selectCampaign) selectCampaign.innerHTML = '<option value="">Стандартное приветствие</option>' + 
                campaigns.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
        }
    } catch (error) {
        console.error('Load campaigns for audio failed:', error);
    }
}

// =============================================
// Contacts
// =============================================
async function loadContacts(page = 1) {
    const search = document.getElementById('contactSearch')?.value || '';
    
    try {
        const response = await authFetch(`${API_BASE}/contacts?page=${page}&page_size=20&search=${encodeURIComponent(search)}`);
        if (response.ok) {
            const data = await response.json();
            AppState.contacts = data.items || [];
            renderContactsList();
            renderPagination('contactsPagination', page, data.total_pages || 1, loadContacts);
        }
    } catch (error) {
        console.error('Contacts load failed:', error);
    }
}

function renderContactsList() {
    const container = document.getElementById('contactsList');
    
    if (AppState.contacts.length === 0) {
        container.innerHTML = '<div class="loading">Нет контактов</div>';
        return;
    }
    
    container.innerHTML = AppState.contacts.map(c => `
        <div class="contact-item">
            <div class="contact-info">
                <strong>${c.phone}</strong>
                ${c.name ? ` - ${c.name}` : ''}
                ${c.email ? `<br><small>${c.email}</small>` : ''}
                <div class="contact-tags">
                    ${c.tags ? c.tags.map(t => `<span class="tag">${t}</span>`).join('') : ''}
                </div>
            </div>
            <div class="contact-actions">
                ${c.blacklisted ? '<span class="status-badge status-declined">Заблокирован</span>' : ''}
                <button class="btn btn-outline btn-sm" onclick="editContact(${c.id})" title="Редактировать">✏</button>
                <button class="btn btn-outline btn-sm" onclick="deleteContact(${c.id})" title="Удалить">🗑</button>
            </div>
        </div>
    `).join('');
}

function searchContacts() {
    loadContacts(1);
}

function openContactModal(contactId = null) {
    const modal = document.getElementById('contactModal');
    const title = document.getElementById('contactModalTitle');
    const deleteBtn = document.getElementById('contactDeleteBtn');
    
    if (contactId) {
        title.textContent = 'Редактировать контакт';
        deleteBtn.style.display = 'inline-block';
        
        const contact = AppState.contacts.find(c => c.id === contactId);
        if (contact) {
            document.getElementById('contactId').value = contact.id;
            document.getElementById('contactPhone').value = contact.phone;
            document.getElementById('contactName').value = contact.name || '';
            document.getElementById('contactEmail').value = contact.email || '';
            document.getElementById('contactGroup').value = contact.group_id || '';
            document.getElementById('contactTags').value = contact.tags ? contact.tags.join(', ') : '';
            document.getElementById('contactNotes').value = contact.notes || '';
        }
    } else {
        title.textContent = 'Новый контакт';
        deleteBtn.style.display = 'none';
        document.getElementById('contactId').value = '';
        document.getElementById('contactPhone').value = '';
        document.getElementById('contactName').value = '';
        document.getElementById('contactEmail').value = '';
        document.getElementById('contactGroup').value = '';
        document.getElementById('contactTags').value = '';
        document.getElementById('contactNotes').value = '';
    }
    
    loadContactGroupsForSelect();
    modal.style.display = 'flex';
}

function closeContactModal() {
    document.getElementById('contactModal').style.display = 'none';
}

function editContact(id) {
    openContactModal(id);
}

async function saveContact() {
    const id = document.getElementById('contactId').value;
    const phone = document.getElementById('contactPhone').value;
    const name = document.getElementById('contactName').value;
    const email = document.getElementById('contactEmail').value;
    const groupId = document.getElementById('contactGroup').value;
    const tags = document.getElementById('contactTags').value.split(',').map(t => t.trim()).filter(t => t);
    const notes = document.getElementById('contactNotes').value;
    
    if (!phone) {
        showToast('Введите номер телефона', 'warning');
        return;
    }
    
    const data = { phone, name, email, group_id: groupId || null, tags, notes };
    
    try {
        const url = id ? `${API_BASE}/contacts/${id}` : `${API_BASE}/contacts`;
        const method = id ? 'PUT' : 'POST';
        
        const response = await authFetch(url, { method, body: JSON.stringify(data) });
        
        if (response.ok) {
            closeContactModal();
            loadContacts();
            showToast(id ? 'Контакт обновлён' : 'Контакт создан', 'success');
        } else {
            const err = await response.json();
            showToast(err.detail || 'Ошибка сохранения', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function deleteContact(id) {
    if (!id) {
        id = document.getElementById('contactId').value;
    }
    if (!confirm('Удалить контакт?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/contacts/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            closeContactModal();
            loadContacts();
            showToast('Контакт удалён', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function importContacts() {
    const text = document.getElementById('contactsImport').value;
    const groupId = document.getElementById('contactGroupSelect').value;
    
    const phones = text.split('\n')
        .map(line => line.trim())
        .filter(line => line)
        .map(phone => ({ phone }));
    
    if (phones.length === 0) {
        showToast('Введите номера телефонов', 'warning');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/contacts/import`, {
            method: 'POST',
            body: JSON.stringify({ group_id: groupId || null, contacts: phones })
        });
        
        if (response.ok) {
            const data = await response.json();
            document.getElementById('contactsImport').value = '';
            loadContacts();
            showToast(`Импортировано: ${data.imported}, пропущено: ${data.skipped}`, 'success');
        }
    } catch (error) {
        showToast('Ошибка импорта', 'error');
    }
}

// =============================================
// Contact Groups
// =============================================
async function loadContactGroups() {
    try {
        const response = await authFetch(`${API_BASE}/contact-groups`);
        if (response.ok) {
            const data = await response.json();
            AppState.contactGroups = data.items || data;
            renderContactGroupsList();
        }
    } catch (error) {
        console.error('Contact groups load failed:', error);
    }
}

function renderContactGroupsList() {
    const container = document.getElementById('contactGroupsList');
    
    if (!AppState.contactGroups || AppState.contactGroups.length === 0) {
        container.innerHTML = '<div class="loading">Нет групп</div>';
        return;
    }
    
    container.innerHTML = AppState.contactGroups.map(g => `
        <div class="group-item">
            <div class="group-color" style="background: ${g.color}; width: 20px; height: 20px; border-radius: 4px; margin-right: 10px;"></div>
            <div class="group-info">
                <strong>${g.name}</strong>
                ${g.description ? `<br><small>${g.description}</small>` : ''}
                <span class="group-count">(${g.contacts_count || 0})</span>
            </div>
            <div class="group-actions">
                <button class="btn btn-outline btn-sm" onclick="editContactGroup(${g.id})">✏</button>
                <button class="btn btn-outline btn-sm" onclick="deleteContactGroup(${g.id})">🗑</button>
            </div>
        </div>
    `).join('');
}

async function loadContactGroupsForSelect() {
    try {
        const response = await authFetch(`${API_BASE}/contact-groups`);
        if (response.ok) {
            const groups = await response.json();
            const items = groups.items || groups;
            
            const selects = ['contactGroupSelect', 'contactGroup'];
            selects.forEach(id => {
                const select = document.getElementById(id);
                if (select) {
                    select.innerHTML = '<option value="">Без группы</option>' +
                        items.map(g => `<option value="${g.id}">${g.name}</option>`).join('');
                }
            });
        }
    } catch (error) {
        console.error('Load groups for select failed:', error);
    }
}

function openContactGroupModal(groupId = null) {
    const modal = document.getElementById('contactGroupModal');
    const title = document.getElementById('contactGroupModalTitle');
    const deleteBtn = document.getElementById('contactGroupDeleteBtn');
    
    if (groupId) {
        title.textContent = 'Редактировать группу';
        deleteBtn.style.display = 'inline-block';
        
        const group = AppState.contactGroups.find(g => g.id === groupId);
        if (group) {
            document.getElementById('contactGroupId').value = group.id;
            document.getElementById('contactGroupName').value = group.name;
            document.getElementById('contactGroupDescription').value = group.description || '';
            document.getElementById('contactGroupColor').value = group.color || '#667eea';
        }
    } else {
        title.textContent = 'Новая группа';
        deleteBtn.style.display = 'none';
        document.getElementById('contactGroupId').value = '';
        document.getElementById('contactGroupName').value = '';
        document.getElementById('contactGroupDescription').value = '';
        document.getElementById('contactGroupColor').value = '#667eea';
    }
    
    modal.style.display = 'flex';
}

function closeContactGroupModal() {
    document.getElementById('contactGroupModal').style.display = 'none';
}

function editContactGroup(id) {
    openContactGroupModal(id);
}

async function saveContactGroup() {
    const id = document.getElementById('contactGroupId').value;
    const name = document.getElementById('contactGroupName').value;
    const description = document.getElementById('contactGroupDescription').value;
    const color = document.getElementById('contactGroupColor').value;
    
    if (!name) {
        showToast('Введите название группы', 'warning');
        return;
    }
    
    const data = { name, description, color };
    
    try {
        const url = id ? `${API_BASE}/contact-groups/${id}` : `${API_BASE}/contact-groups`;
        const method = id ? 'PUT' : 'POST';
        
        const response = await authFetch(url, { method, body: JSON.stringify(data) });
        
        if (response.ok) {
            closeContactGroupModal();
            loadContactGroups();
            showToast(id ? 'Группа обновлена' : 'Группа создана', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function deleteContactGroup(id) {
    if (!id) {
        id = document.getElementById('contactGroupId').value;
    }
    if (!confirm('Удалить группу? Контакты не будут удалены.')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/contact-groups/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            closeContactGroupModal();
            loadContactGroups();
            showToast('Группа удалена', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

// =============================================
// History
// =============================================
async function loadHistory(page = 1) {
    const campaignId = document.getElementById('historyFilterCampaign')?.value;
    const status = document.getElementById('historyFilterStatus')?.value;
    
    let url = `${API_BASE}/history?page=${page}&page_size=20`;
    if (campaignId) url += `&campaign_id=${campaignId}`;
    if (status) url += `&status=${status}`;
    
    try {
        const response = await authFetch(url);
        if (response.ok) {
            const data = await response.json();
            renderHistoryTable(data.items || []);
            renderPagination('historyPagination', page, data.total_pages || 1, loadHistory);
        }
    } catch (error) {
        console.error('History load failed:', error);
    }
}

function renderHistoryTable(history) {
    const tbody = document.getElementById('historyTable');
    
    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Нет записей</td></tr>';
        return;
    }
    
    tbody.innerHTML = history.map(h => `
        <tr>
            <td>${new Date(h.created_at).toLocaleString()}</td>
            <td>${h.phone}</td>
            <td>${h.contact_name || '-'}</td>
            <td>${h.campaign_name || '-'}</td>
            <td><span class="status-badge status-${h.status}">${h.status}</span></td>
            <td>${h.dtmf_result || '-'}</td>
            <td>
                ${h.recording_url ? `<button class="btn btn-outline btn-sm" onclick="playRecording('${h.recording_url}')">▶</button>` : '-'}
            </td>
        </tr>
    `).join('');
}

function playRecording(url) {
    const audio = new Audio(url);
    audio.play();
}

function renderPagination(containerId, currentPage, totalPages, callback) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    if (currentPage > 1) {
        html += `<button onclick="${callback.name}(${currentPage - 1})">←</button>`;
    }
    
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 2) {
            html += `<button class="${i === currentPage ? 'active' : ''}" onclick="${callback.name}(${i})">${i}</button>`;
        } else if (Math.abs(i - currentPage) === 3) {
            html += '<span>...</span>';
        }
    }
    
    if (currentPage < totalPages) {
        html += `<button onclick="${callback.name}(${currentPage + 1})">→</button>`;
    }
    
    container.innerHTML = html;
}

// =============================================
// Audio
// =============================================
async function loadAudio() {
    try {
        const response = await authFetch(`${API_BASE}/audio`);
        if (response.ok) {
            const data = await response.json();
            AppState.audioFiles = data.items || data;
            renderAudioList();
        }
    } catch (error) {
        console.error('Audio load failed:', error);
    }
}

function renderAudioList() {
    const container = document.getElementById('audioList');
    
    if (!AppState.audioFiles || AppState.audioFiles.length === 0) {
        container.innerHTML = '<div class="loading">Нет аудиофайлов</div>';
        return;
    }
    
    container.innerHTML = AppState.audioFiles.map(a => `
        <div class="audio-item">
            <div class="audio-info">
                <strong>${a.name}</strong>
                ${a.description ? `<br><small>${a.description}</small>` : ''}
                <div class="audio-meta">
                    <span>${a.format}</span>
                    ${a.duration ? `<span>${Math.round(a.duration)}с</span>` : ''}
                    <span>${formatFileSize(a.file_size)}</span>
                </div>
            </div>
            <div class="audio-controls">
                <audio controls src="${a.download_url || a.file_path}"></audio>
                <button class="btn btn-outline btn-sm" onclick="deleteAudio(${a.id})" title="Удалить">🗑</button>
            </div>
        </div>
    `).join('');
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

async function generateAudio() {
    const name = document.getElementById('audioName').value;
    const text = document.getElementById('audioText').value;
    const voice = document.getElementById('audioVoice').value;
    const campaignId = document.getElementById('audioCampaign')?.value;
    
    if (!name || !text) {
        showToast('Заполните название и текст', 'warning');
        return;
    }
    
    if (text.length > 500) {
        showToast('Текст не должен превышать 500 символов', 'warning');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/audio/generate`, {
            method: 'POST',
            body: JSON.stringify({ name, text, voice, campaign_id: campaignId || null })
        });
        
        if (response.ok) {
            document.getElementById('audioName').value = '';
            document.getElementById('audioText').value = '';
            loadAudio();
            showToast('Аудио сгенерировано', 'success');
        } else {
            const data = await response.json();
            showToast(data.detail || 'Ошибка генерации', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function uploadAudio() {
    const name = document.getElementById('audioUploadName').value;
    const fileInput = document.getElementById('audioUploadFile');
    const campaignId = document.getElementById('audioUploadCampaign')?.value;
    
    if (!name || !fileInput.files[0]) {
        showToast('Заполните название и выберите файл', 'warning');
        return;
    }
    
    const file = fileInput.files[0];
    if (!file.name.match(/\.(wav|mp3)$/i)) {
        showToast('Поддерживаются только WAV и MP3', 'warning');
        return;
    }
    
    const formData = new FormData();
    formData.append('name', name);
    formData.append('file', file);
    if (campaignId) formData.append('campaign_id', campaignId);
    
    try {
        const response = await authFetch(`${API_BASE}/audio/upload`, {
            method: 'POST',
            body: formData,
            headers: {} // Let browser set Content-Type
        });
        
        if (response.ok) {
            document.getElementById('audioUploadName').value = '';
            fileInput.value = '';
            loadAudio();
            showToast('Аудио загружено', 'success');
        } else {
            const data = await response.json();
            showToast(data.detail || 'Ошибка загрузки', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function deleteAudio(id) {
    if (!confirm('Удалить аудиофайл?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/audio/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            loadAudio();
            showToast('Аудио удалено', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function loadAudioForSelect() {
    try {
        const response = await authFetch(`${API_BASE}/audio`);
        if (response.ok) {
            const data = await response.json();
            const files = data.items || data;
            
            const select = document.getElementById('campaignAudioSelect');
            if (select) {
                select.innerHTML = '<option value="">Стандартное приветствие</option>' +
                    files.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
            }
        }
    } catch (error) {
        console.error('Audio for select failed:', error);
    }
}

// =============================================
// Blacklist
// =============================================
async function loadBlacklist() {
    try {
        const response = await authFetch(`${API_BASE}/blacklist`);
        if (response.ok) {
            const data = await response.json();
            renderBlacklistTable(data.items || data);
        }
    } catch (error) {
        console.error('Blacklist load failed:', error);
    }
}

function renderBlacklistTable(items) {
    const tbody = document.getElementById('blacklistTable');
    
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Чёрный список пуст</td></tr>';
        return;
    }
    
    tbody.innerHTML = items.map(b => `
        <tr>
            <td>${b.phone}</td>
            <td>${b.reason || '-'}</td>
            <td>${new Date(b.created_at).toLocaleString()}</td>
            <td>${b.created_by_name || 'system'}</td>
            <td>
                <button class="btn btn-outline btn-sm" onclick="removeFromBlacklist('${b.phone}')">🗑</button>
            </td>
        </tr>
    `).join('');
}

function openBlacklistModal() {
    document.getElementById('blacklistModal').style.display = 'flex';
}

function closeBlacklistModal() {
    document.getElementById('blacklistModal').style.display = 'none';
    document.getElementById('blacklistPhone').value = '';
    document.getElementById('blacklistReason').value = '';
}

async function addToBlacklist() {
    const phone = document.getElementById('blacklistPhone').value;
    const reason = document.getElementById('blacklistReason').value;
    
    if (!phone) {
        showToast('Введите номер телефона', 'warning');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/blacklist`, {
            method: 'POST',
            body: JSON.stringify({ phone, reason })
        });
        
        if (response.ok) {
            closeBlacklistModal();
            loadBlacklist();
            showToast('Номер добавлен в чёрный список', 'success');
        } else {
            const data = await response.json();
            showToast(data.detail || 'Ошибка', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function removeFromBlacklist(phone) {
    if (!confirm(`Удалить ${phone} из чёрного списка?`)) return;
    
    try {
        const response = await authFetch(`${API_BASE}/blacklist/${encodeURIComponent(phone)}`, { method: 'DELETE' });
        
        if (response.ok) {
            loadBlacklist();
            showToast('Номер удалён из чёрного списка', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

// =============================================
// Users (Admin Only)
// =============================================
async function loadUsers() {
    if (AppState.userRole !== 'admin') return;
    
    try {
        const response = await authFetch(`${API_BASE}/users`);
        if (response.ok) {
            const data = await response.json();
            AppState.users = data.items || data;
            renderUsersTable();
        }
    } catch (error) {
        console.error('Users load failed:', error);
    }
}

function renderUsersTable() {
    const tbody = document.getElementById('usersTable');
    
    if (!AppState.users || AppState.users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Нет пользователей</td></tr>';
        return;
    }
    
    tbody.innerHTML = AppState.users.map(u => `
        <tr>
            <td>${u.id}</td>
            <td>${u.username}</td>
            <td>${u.email || '-'}</td>
            <td>${u.full_name || '-'}</td>
            <td><span class="badge badge-${u.role}">${u.role}</span></td>
            <td>${u.is_active ? '✅' : '❌'}</td>
            <td>
                ${u.id !== 1 ? `<button class="btn btn-outline btn-sm" onclick="deleteUser(${u.id})">🗑</button>` : ''}
            </td>
        </tr>
    `).join('');
}

function openUserModal() {
    document.getElementById('userModal').style.display = 'flex';
}

function closeUserModal() {
    document.getElementById('userModal').style.display = 'none';
    document.getElementById('newUsername').value = '';
    document.getElementById('newUserPassword').value = '';
    document.getElementById('newUserEmail').value = '';
    document.getElementById('newUserFullName').value = '';
}

async function createUser() {
    const username = document.getElementById('newUsername').value;
    const password = document.getElementById('newUserPassword').value;
    const email = document.getElementById('newUserEmail').value;
    const fullName = document.getElementById('newUserFullName').value;
    const role = document.getElementById('newUserRole').value;
    
    if (!username || !password) {
        showToast('Логин и пароль обязательны', 'warning');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/users`, {
            method: 'POST',
            body: JSON.stringify({ username, password, email: email || null, full_name: fullName || null, role })
        });
        
        if (response.ok) {
            closeUserModal();
            loadUsers();
            showToast('Пользователь создан', 'success');
        } else {
            const data = await response.json();
            showToast(data.detail || 'Ошибка создания', 'error');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function deleteUser(id) {
    if (!confirm('Удалить пользователя?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/users/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            loadUsers();
            showToast('Пользователь удалён', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

// =============================================
// Settings (Admin Only)
// =============================================
async function loadSettings() {
    if (AppState.userRole !== 'admin') return;
    
    try {
        const response = await authFetch(`${API_BASE}/settings`);
        if (response.ok) {
            const data = await response.json();
            AppState.settings = data;
            renderSettingsForm();
        }
    } catch (error) {
        console.error('Settings load failed:', error);
    }
}

function renderSettingsForm() {
    const container = document.getElementById('settingsForm');
    
    const categories = {};
    Object.entries(AppState.settings).forEach(([key, info]) => {
        const category = info.category || 'general';
        if (!categories[category]) categories[category] = [];
        categories[category].push({ key, ...info });
    });
    
    let html = '';
    Object.entries(categories).forEach(([category, settings]) => {
        html += `<h4>${category}</h4>`;
        settings.forEach(s => {
            html += `
                <div class="form-group">
                    <label>${s.key}</label>
                    <div class="setting-control">
                        <input type="text" id="setting_${s.key}" value="${s.value}" style="flex:1;">
                        <button class="btn btn-outline btn-sm" onclick="updateSetting('${s.key}')">Сохранить</button>
                    </div>
                    ${s.description ? `<small class="text-muted">${s.description}</small>` : ''}
                </div>
            `;
        });
    });
    
    container.innerHTML = html;
}

async function updateSetting(key) {
    const input = document.getElementById(`setting_${key}`);
    const value = input.value;
    
    try {
        const response = await authFetch(`${API_BASE}/settings/${key}`, {
            method: 'PUT',
            body: JSON.stringify({ value })
        });
        
        if (response.ok) {
            showToast('Настройка сохранена', 'success');
        }
    } catch (error) {
        showToast('Ошибка сохранения', 'error');
    }
}

// =============================================
// Audit Log (Admin Only)
// =============================================
async function loadAuditLog(page = 1) {
    const action = document.getElementById('auditFilterAction')?.value;
    
    let url = `${API_BASE}/audit?page=${page}&page_size=20`;
    if (action) url += `&action=${action}`;
    
    try {
        const response = await authFetch(url);
        if (response.ok) {
            const data = await response.json();
            renderAuditTable(data.items || []);
            renderPagination('auditPagination', page, data.total_pages || 1, loadAuditLog);
        }
    } catch (error) {
        console.error('Audit load failed:', error);
    }
}

function renderAuditTable(items) {
    const tbody = document.getElementById('auditTable');
    
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Нет записей</td></tr>';
        return;
    }
    
    tbody.innerHTML = items.map(a => `
        <tr>
            <td>${new Date(a.created_at).toLocaleString()}</td>
            <td>${a.username || 'system'}</td>
            <td>${a.action}</td>
            <td>${a.ip_address || '-'}</td>
            <td>${JSON.stringify(a.details).substring(0, 50)}</td>
        </tr>
    `).join('');
}

// =============================================
// API Tokens (Admin Only)
// =============================================
async function loadApiTokens() {
    try {
        const response = await authFetch(`${API_BASE}/tokens`);
        if (response.ok) {
            const data = await response.json();
            renderApiTokensTable(data.items || data);
        }
    } catch (error) {
        console.error('API tokens load failed:', error);
    }
}

function renderApiTokensTable(tokens) {
    const tbody = document.getElementById('apiTokensTable');
    
    if (!tokens || tokens.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Нет токенов</td></tr>';
        return;
    }
    
    tbody.innerHTML = tokens.map(t => `
        <tr>
            <td>${t.name}</td>
            <td><code>${t.token ? t.token.substring(0, 8) + '...' : '****'}</code></td>
            <td>${new Date(t.created_at).toLocaleString()}</td>
            <td>${t.expires_at ? new Date(t.expires_at).toLocaleString() : 'Никогда'}</td>
            <td>${t.last_used_at ? new Date(t.last_used_at).toLocaleString() : '-'}</td>
            <td>
                <button class="btn btn-outline btn-sm" onclick="deleteApiToken(${t.id})">🗑</button>
            </td>
        </tr>
    `).join('');
}

function openApiTokenModal() {
    document.getElementById('apiTokenModal').style.display = 'flex';
    document.getElementById('newTokenDisplay').style.display = 'none';
    document.getElementById('apiTokenCreateBtn').style.display = 'block';
}

function closeApiTokenModal() {
    document.getElementById('apiTokenModal').style.display = 'none';
    document.getElementById('apiTokenName').value = '';
    document.getElementById('apiTokenExpires').value = '';
}

async function createApiToken() {
    const name = document.getElementById('apiTokenName').value;
    const expires = document.getElementById('apiTokenExpires').value;
    
    if (!name) {
        showToast('Введите название', 'warning');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/tokens`, {
            method: 'POST',
            body: JSON.stringify({ name, expires_at: expires || null })
        });
        
        if (response.ok) {
            const data = await response.json();
            document.getElementById('newTokenValue').textContent = data.token;
            document.getElementById('newTokenDisplay').style.display = 'block';
            document.getElementById('apiTokenCreateBtn').style.display = 'none';
            loadApiTokens();
            showToast('Токен создан', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

function copyToken() {
    const token = document.getElementById('newTokenValue').textContent;
    navigator.clipboard?.writeText(token);
    showToast('Токен скопирован', 'info');
}

async function deleteApiToken(id) {
    if (!confirm('Удалить токен?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/tokens/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            loadApiTokens();
            showToast('Токен удалён', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

// =============================================
// Webhooks (Admin Only)
// =============================================
async function loadWebhooks() {
    try {
        const response = await authFetch(`${API_BASE}/webhooks`);
        if (response.ok) {
            const data = await response.json();
            renderWebhooksTable(data.items || data);
        }
    } catch (error) {
        console.error('Webhooks load failed:', error);
    }
}

function renderWebhooksTable(webhooks) {
    const tbody = document.getElementById('webhooksTable');
    
    if (!webhooks || webhooks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Нет подписок</td></tr>';
        return;
    }
    
    tbody.innerHTML = webhooks.map(w => `
        <tr>
            <td>${w.name}</td>
            <td>${w.url}</td>
            <td>${w.events ? w.events.join(', ') : '*'}</td>
            <td>${w.is_active ? '✅' : '❌'}</td>
            <td>${w.success_count || 0}/${w.failure_count || 0}</td>
            <td>
                <button class="btn btn-outline btn-sm" onclick="editWebhook(${w.id})">✏</button>
                <button class="btn btn-outline btn-sm" onclick="deleteWebhook(${w.id})">🗑</button>
            </td>
        </tr>
    `).join('');
}

function openWebhookModal(webhookId = null) {
    const modal = document.getElementById('webhookModal');
    const title = document.getElementById('webhookModalTitle');
    const deleteBtn = document.getElementById('webhookDeleteBtn');
    
    if (webhookId) {
        title.textContent = 'Редактировать Webhook';
        deleteBtn.style.display = 'inline-block';
        // Load webhook data
    } else {
        title.textContent = 'Добавить Webhook';
        deleteBtn.style.display = 'none';
        document.getElementById('webhookId').value = '';
        document.getElementById('webhookName').value = '';
        document.getElementById('webhookUrl').value = '';
        document.getElementById('webhookSecret').value = '';
        document.getElementById('webhookActive').checked = true;
        document.querySelectorAll('#webhookEvents input[type=checkbox]').forEach(cb => cb.checked = false);
    }
    
    modal.style.display = 'flex';
}

function closeWebhookModal() {
    document.getElementById('webhookModal').style.display = 'none';
}

function editWebhook(id) {
    openWebhookModal(id);
}

async function saveWebhook() {
    const id = document.getElementById('webhookId').value;
    const name = document.getElementById('webhookName').value;
    const url = document.getElementById('webhookUrl').value;
    const secret = document.getElementById('webhookSecret').value;
    const isActive = document.getElementById('webhookActive').checked;
    
    const events = [];
    document.querySelectorAll('#webhookEvents input[type=checkbox]:checked').forEach(cb => {
        events.push(cb.value);
    });
    
    if (!name || !url) {
        showToast('Название и URL обязательны', 'warning');
        return;
    }
    
    const data = { name, url, events, secret: secret || null, is_active: isActive };
    
    try {
        const urlPath = id ? `${API_BASE}/webhooks/${id}` : `${API_BASE}/webhooks`;
        const method = id ? 'PUT' : 'POST';
        
        const response = await authFetch(urlPath, { method, body: JSON.stringify(data) });
        
        if (response.ok) {
            closeWebhookModal();
            loadWebhooks();
            showToast(id ? 'Webhook обновлён' : 'Webhook создан', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

async function deleteWebhook(id) {
    if (!id) {
        id = document.getElementById('webhookId').value;
    }
    if (!confirm('Удалить Webhook?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/webhooks/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            closeWebhookModal();
            loadWebhooks();
            showToast('Webhook удалён', 'success');
        }
    } catch (error) {
        showToast('Ошибка сервера', 'error');
    }
}

// =============================================
// Utility Functions
// =============================================
function formatDuration(seconds) {
    if (!seconds) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
