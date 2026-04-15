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
    audioFiles: [],
    users: [],
    settings: {}
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
    
    // Setup event listeners
    setupEventListeners();
});

function setupEventListeners() {
    // Login form
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', (e) => {
            e.preventDefault();
            login();
        });
    }
    
    // Enter key on login inputs
    const loginInputs = document.querySelectorAll('#loginUsername, #loginPassword');
    loginInputs.forEach(input => {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') login();
        });
    });
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
            AppState.refreshToken = '';
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
        // Ignore logout errors
    }
    
    localStorage.removeItem('refresh_token');
    AppState.accessToken = '';
    AppState.refreshToken = '';
    AppState.user = null;
    AppState.userRole = '';
    
    document.getElementById('appScreen').style.display = 'none';
    document.getElementById('loginScreen').style.display = 'flex';
    document.getElementById('loginUsername').value = '';
    document.getElementById('loginPassword').value = '';
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
            body: JSON.stringify({
                old_password: oldPassword,
                new_password: newPassword1
            })
        });
        
        if (response.ok) {
            closePasswordModal();
            await loadCurrentUser();
            showApp();
        } else {
            const data = await response.json();
            errorDiv.textContent = data.detail || 'Ошибка смены пароля';
        }
    } catch (error) {
        errorDiv.textContent = 'Ошибка сервера';
    }
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

function showPasswordModal() {
    document.getElementById('passwordModal').style.display = 'flex';
    document.getElementById('oldPassword').value = '';
    document.getElementById('newPassword1').value = '';
    document.getElementById('newPassword2').value = '';
}

function closePasswordModal() {
    document.getElementById('passwordModal').style.display = 'none';
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
            break;
        case 'history':
            await loadHistory();
            break;
        case 'audio':
            await loadAudio();
            break;
        case 'users':
            await loadUsers();
            break;
        case 'settings':
            await loadSettings();
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
        const response = await authFetch(`${API_BASE}/system/${action}`, {
            method: 'POST'
        });
        
        if (response.ok) {
            await refreshSystemStatus();
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

// =============================================
// Dashboard
// =============================================
async function loadDashboard() {
    await loadDashboardStats();
    await loadActiveCampaigns();
    await loadRecentCalls();
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
            
            if (campaigns.length === 0) {
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
            <td>${c.stats?.called_contacts || 0}/${c.stats?.total_contacts || 0}</td>
            <td>${c.stats?.conversion_rate || 0}%</td>
            <td class="actions">
                ${c.status === 'draft' ? `<button class="btn btn-success btn-sm" onclick="startCampaign(${c.id})" title="Запустить">▶</button>` : ''}
                ${c.status === 'running' ? `<button class="btn btn-warning btn-sm" onclick="pauseCampaign(${c.id})" title="Пауза">⏸</button>` : ''}
                ${c.status === 'paused' ? `<button class="btn btn-success btn-sm" onclick="resumeCampaign(${c.id})" title="Продолжить">▶</button>` : ''}
                ${c.status === 'running' && AppState.userRole === 'admin' ? `<button class="btn btn-danger btn-sm" onclick="stopCampaign(${c.id})" title="Остановить">⏹</button>` : ''}
                <button class="btn btn-outline btn-sm" onclick="viewCampaign(${c.id})" title="Просмотр">👁</button>
                ${AppState.userRole === 'admin' ? `<button class="btn btn-outline btn-sm" onclick="deleteCampaign(${c.id})" title="Удалить">🗑</button>` : ''}
            </td>
        </tr>
    `).join('');
}

async function startCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/start`, {
            method: 'POST'
        });
        
        if (response.ok) {
            loadCampaigns();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка запуска');
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

async function stopCampaign(id) {
    if (!confirm('Остановить кампанию?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/stop`, {
            method: 'POST'
        });
        
        if (response.ok) {
            loadCampaigns();
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

async function pauseCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/pause`, {
            method: 'POST'
        });
        
        if (response.ok) {
            loadCampaigns();
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

async function resumeCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/resume`, {
            method: 'POST'
        });
        
        if (response.ok) {
            loadCampaigns();
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

async function deleteCampaign(id) {
    if (!confirm('Удалить кампанию? Это действие нельзя отменить.')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadCampaigns();
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

function viewCampaign(id) {
    const campaign = AppState.campaigns.find(c => c.id === id);
    if (campaign) {
        alert(`Кампания: ${campaign.name}\nСтатус: ${campaign.status}\nПрогресс: ${campaign.stats?.progress_percent || 0}%`);
    }
}

function openCampaignModal() {
    document.getElementById('campaignModal').style.display = 'flex';
    loadAudioForSelect();
}

function closeCampaignModal() {
    document.getElementById('campaignModal').style.display = 'none';
    document.getElementById('campaignName').value = '';
    document.getElementById('campaignDescription').value = '';
}

async function createCampaign() {
    const name = document.getElementById('campaignName').value;
    const description = document.getElementById('campaignDescription').value;
    const maxCalls = parseInt(document.getElementById('campaignMaxCalls').value);
    const cps = parseInt(document.getElementById('campaignCps').value);
    const audioId = document.getElementById('campaignAudio').value;
    
    if (!name) {
        alert('Введите название кампании');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/campaigns`, {
            method: 'POST',
            body: JSON.stringify({
                name,
                description,
                max_calls: maxCalls,
                cps: cps,
                audio_id: audioId || null
            })
        });
        
        if (response.ok) {
            closeCampaignModal();
            loadCampaigns();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка создания');
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

// =============================================
// Contacts
// =============================================
async function loadContacts() {
    try {
        const response = await authFetch(`${API_BASE}/contacts?limit=100`);
        if (response.ok) {
            const data = await response.json();
            AppState.contacts = data.contacts || [];
            renderContactsList();
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
            <div>
                <strong>${c.phone}</strong>
                ${c.name ? ` - ${c.name}` : ''}
                ${c.email ? `<br><small>${c.email}</small>` : ''}
            </div>
            <div class="contact-tags">
                ${c.tags ? c.tags.map(t => `<span class="tag">${t}</span>`).join('') : ''}
            </div>
            <div>
                ${c.blacklisted ? '<span class="status-badge status-declined">Заблокирован</span>' : ''}
                <span class="status-badge status-${c.status}">${c.status}</span>
            </div>
        </div>
    `).join('');
}

async function importContacts() {
    const text = document.getElementById('contactsImport').value;
    const groupId = document.getElementById('contactGroupSelect').value;
    
    const phones = text.split('\n')
        .map(line => line.trim())
        .filter(line => line)
        .map(phone => ({ phone }));
    
    if (phones.length === 0) {
        alert('Введите номера телефонов');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/contacts/import`, {
            method: 'POST',
            body: JSON.stringify({
                group_id: groupId || null,
                contacts: phones
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            alert(`Импортировано: ${data.imported}\nПропущено: ${data.skipped}\nВ черном списке: ${data.blacklisted || 0}`);
            document.getElementById('contactsImport').value = '';
            loadContacts();
        }
    } catch (error) {
        alert('Ошибка импорта');
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
            renderPagination('historyPagination', page, data.total_pages, loadHistory);
        }
    } catch (error) {
        console.error('History load failed:', error);
    }
}

function renderHistoryTable(history) {
    const tbody = document.getElementById('historyTable');
    
    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Нет записей</td></tr>';
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
        </tr>
    `).join('');
}

function renderPagination(containerId, currentPage, totalPages, callback) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // Previous button
    if (currentPage > 1) {
        html += `<button onclick="${callback.name}(${currentPage - 1})">←</button>`;
    }
    
    // Page numbers
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 2) {
            html += `<button class="${i === currentPage ? 'active' : ''}" onclick="${callback.name}(${i})">${i}</button>`;
        } else if (Math.abs(i - currentPage) === 3) {
            html += '<span>...</span>';
        }
    }
    
    // Next button
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
            AppState.audioFiles = data.audio || data;
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
        alert('Заполните название и текст');
        return;
    }
    
    if (text.length > 500) {
        alert('Текст не должен превышать 500 символов');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/audio/generate`, {
            method: 'POST',
            body: JSON.stringify({
                name,
                text,
                voice,
                campaign_id: campaignId || null
            })
        });
        
        if (response.ok) {
            document.getElementById('audioName').value = '';
            document.getElementById('audioText').value = '';
            loadAudio();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка генерации');
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

async function deleteAudio(id) {
    if (!confirm('Удалить аудиофайл?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/audio/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadAudio();
        }
    } catch (error) {
        alert('Ошибка удаления');
    }
}

async function loadAudioForSelect() {
    try {
        const response = await authFetch(`${API_BASE}/audio`);
        if (response.ok) {
            const data = await response.json();
            const files = data.audio || data;
            
            const select = document.getElementById('campaignAudio');
            if (select) {
                select.innerHTML = '<option value="">По умолчанию</option>' +
                    files.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
            }
        }
    } catch (error) {
        console.error('Audio for select failed:', error);
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
            AppState.users = data.users || [];
            renderUsersTable();
        }
    } catch (error) {
        console.error('Users load failed:', error);
    }
}

function renderUsersTable() {
    const tbody = document.getElementById('usersTable');
    
    if (!AppState.users || AppState.users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Нет пользователей</td></tr>';
        return;
    }
    
    tbody.innerHTML = AppState.users.map(u => `
        <tr>
            <td>${u.id}</td>
            <td>${u.username}</td>
            <td>${u.email || '-'}</td>
            <td>${u.full_name || '-'}</td>
            <td><span class="badge badge-${u.role}">${u.role}</span></td>
            <td class="actions">
                <button class="btn btn-outline btn-sm" onclick="editUser(${u.id})" title="Редактировать">✏</button>
                ${u.id !== 1 ? `<button class="btn btn-outline btn-sm" onclick="deleteUser(${u.id})" title="Удалить">🗑</button>` : ''}
            </td>
        </tr>
    `).join('');
}

function openUserModal() {
    document.getElementById('userModal').style.display = 'flex';
    document.getElementById('newUsername').value = '';
    document.getElementById('newUserPassword').value = '';
    document.getElementById('newUserEmail').value = '';
    document.getElementById('newUserFullName').value = '';
}

function closeUserModal() {
    document.getElementById('userModal').style.display = 'none';
}

async function createUser() {
    const username = document.getElementById('newUsername').value;
    const password = document.getElementById('newUserPassword').value;
    const email = document.getElementById('newUserEmail').value;
    const fullName = document.getElementById('newUserFullName').value;
    const role = document.getElementById('newUserRole').value;
    
    if (!username || !password) {
        alert('Логин и пароль обязательны');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/users`, {
            method: 'POST',
            body: JSON.stringify({
                username,
                password,
                email: email || null,
                full_name: fullName || null,
                role
            })
        });
        
        if (response.ok) {
            closeUserModal();
            loadUsers();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка создания');
        }
    } catch (error) {
        alert('Ошибка сервера');
    }
}

async function deleteUser(id) {
    if (!confirm('Удалить пользователя?')) return;
    
    try {
        const response = await authFetch(`${API_BASE}/users/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadUsers();
        }
    } catch (error) {
        alert('Ошибка удаления');
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
            alert('Настройка сохранена');
        }
    } catch (error) {
        alert('Ошибка сохранения');
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

function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =============================================
// WebSocket Support (Optional)
// =============================================
let ws = null;
let wsReconnectTimer = null;

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        if (wsReconnectTimer) {
            clearTimeout(wsReconnectTimer);
            wsReconnectTimer = null;
        }
    };
    
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        } catch (error) {
            console.error('WebSocket message error:', error);
        }
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected');
        wsReconnectTimer = setTimeout(connectWebSocket, 5000);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'live_call':
            updateLiveCall(data.data);
            break;
        case 'campaign_progress':
            updateCampaignProgress(data.data);
            break;
        case 'system_status':
            updateSystemBar(data.data);
            break;
    }
}

function updateLiveCall(call) {
    // Update live calls display if on dashboard
    if (AppState.currentTab === 'dashboard') {
        // Implementation for live call updates
    }
}

function updateCampaignProgress(progress) {
    // Update campaign progress if viewing that campaign
    const campaign = AppState.campaigns.find(c => c.id === progress.campaign_id);
    if (campaign) {
        campaign.stats = progress;
        if (AppState.currentTab === 'campaigns') {
            renderCampaignsTable(AppState.campaigns);
        }
    }
}

// Initialize WebSocket if enabled
// connectWebSocket();
