// AutoDialer Ultimate Frontend Application

// Global state
let accessToken = '';
let refreshToken = '';
let userRole = '';
let username = '';
let forceChange = false;
let currentTab = 'dashboard';

const API_BASE = '/api';

// =============================================
// Initialization
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    const savedRefreshToken = localStorage.getItem('refresh_token');
    if (savedRefreshToken) {
        refreshToken = savedRefreshToken;
        tryAutoLogin();
    }
});

async function tryAutoLogin() {
    try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${refreshToken}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            accessToken = data.access_token;
            await loadUserInfo();
            showApp();
        } else {
            localStorage.removeItem('refresh_token');
        }
    } catch (e) {
        console.error('Auto login failed:', e);
    }
}

// =============================================
// Authentication
// =============================================
async function login() {
    const usernameInput = document.getElementById('loginUsername');
    const passwordInput = document.getElementById('loginPassword');
    const errorDiv = document.getElementById('loginError');
    
    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: usernameInput.value,
                password: passwordInput.value
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Login failed');
        }
        
        accessToken = data.access_token;
        refreshToken = data.refresh_token;
        userRole = data.role;
        forceChange = data.force_password_change;
        
        localStorage.setItem('refresh_token', refreshToken);
        
        if (forceChange) {
            showPasswordModal();
        } else {
            await loadUserInfo();
            showApp();
        }
    } catch (e) {
        errorDiv.textContent = e.message;
    }
}

async function logout() {
    try {
        await authFetch(`${API_BASE}/auth/logout`, { method: 'POST' });
    } catch (e) {
        // Ignore
    }
    
    localStorage.removeItem('refresh_token');
    accessToken = '';
    refreshToken = '';
    
    document.getElementById('appScreen').style.display = 'none';
    document.getElementById('loginScreen').style.display = 'flex';
}

async function changePassword() {
    const oldPass = document.getElementById('oldPassword').value;
    const newPass1 = document.getElementById('newPassword1').value;
    const newPass2 = document.getElementById('newPassword2').value;
    const errorDiv = document.getElementById('passwordError');
    
    if (newPass1 !== newPass2) {
        errorDiv.textContent = 'Пароли не совпадают';
        return;
    }
    
    if (newPass1.length < 6) {
        errorDiv.textContent = 'Пароль должен быть не менее 6 символов';
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/auth/change-password`, {
            method: 'POST',
            body: JSON.stringify({
                old_password: oldPass,
                new_password: newPass1
            })
        });
        
        if (response.ok) {
            closePasswordModal();
            await loadUserInfo();
            showApp();
        } else {
            const data = await response.json();
            errorDiv.textContent = data.detail || 'Ошибка смены пароля';
        }
    } catch (e) {
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
    options.headers['Authorization'] = `Bearer ${accessToken}`;
    options.headers['Content-Type'] = options.headers['Content-Type'] || 'application/json';
    
    let response = await fetch(url, options);
    
    if (response.status === 401) {
        const refreshed = await refreshAccessToken();
        if (refreshed) {
            options.headers['Authorization'] = `Bearer ${accessToken}`;
            response = await fetch(url, options);
        }
    }
    
    return response;
}

async function refreshAccessToken() {
    try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${refreshToken}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            accessToken = data.access_token;
            return true;
        }
    } catch (e) {
        console.error('Token refresh failed:', e);
    }
    
    logout();
    return false;
}

async function loadUserInfo() {
    try {
        const response = await authFetch(`${API_BASE}/auth/me`);
        if (response.ok) {
            const data = await response.json();
            username = data.username;
            userRole = data.role;
        }
    } catch (e) {
        console.error('Failed to load user info:', e);
    }
}

// =============================================
// UI Functions
// =============================================
function showApp() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('appScreen').style.display = 'block';
    
    document.getElementById('userDisplay').innerHTML = `
        <span class="badge badge-${userRole}">${userRole}</span> ${username}
    `;
    
    if (userRole !== 'admin') {
        document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
        const killSwitch = document.getElementById('killSwitchBtn');
        if (killSwitch) killSwitch.style.display = 'none';
    }
    
    switchTab('dashboard');
    startPeriodicRefresh();
}

function showPasswordModal() {
    document.getElementById('passwordModal').style.display = 'flex';
}

function closePasswordModal() {
    document.getElementById('passwordModal').style.display = 'none';
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
    
    document.getElementById(tabId).classList.add('active');
    document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');
    
    currentTab = tabId;
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
        if (currentTab === 'dashboard') {
            await loadDashboard();
        }
    }, 3000);
}

// =============================================
// Data Loading
// =============================================
async function refreshSystemStatus() {
    try {
        const response = await authFetch(`${API_BASE}/system/status`);
        if (response.ok) {
            const data = await response.json();
            document.getElementById('sysStatus').textContent = data.enabled ? 'Активна' : 'ОСТАНОВЛЕНА';
            document.getElementById('sysChannels').textContent = `${data.active_calls}/${data.max_calls}`;
            
            const killSwitch = document.getElementById('killSwitchBtn');
            if (killSwitch) {
                killSwitch.textContent = data.enabled ? '🛑 АВАРИЙНАЯ ОСТАНОВКА' : '🟢 ВКЛЮЧИТЬ';
            }
        }
    } catch (e) {
        console.error('Status refresh failed:', e);
    }
}

async function loadDashboard() {
    try {
        const response = await authFetch(`${API_BASE}/stats`);
        if (response.ok) {
            const data = await response.json();
            document.getElementById('dashTotal').textContent = data.total_calls || 0;
            document.getElementById('dashAgreed').textContent = data.agreed || 0;
            document.getElementById('dashToday').textContent = data.today_calls || 0;
            document.getElementById('dashConversion').textContent = `${data.conversion_rate || 0}%`;
        }
    } catch (e) {
        console.error('Dashboard load failed:', e);
    }
}

async function loadCampaigns() {
    try {
        const response = await authFetch(`${API_BASE}/campaigns`);
        if (response.ok) {
            const data = await response.json();
            const tbody = document.getElementById('campaignsTable');
            
            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Нет кампаний</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.map(c => `
                <tr>
                    <td>${c.id}</td>
                    <td>${c.name}</td>
                    <td><span class="badge badge-${c.status}">${c.status}</span></td>
                    <td>${c.max_calls}</td>
                    <td>${c.cps}</td>
                    <td>
                        ${c.status === 'draft' ? 
                            `<button class="btn btn-success" onclick="startCampaign(${c.id})">▶</button>` : ''}
                        ${c.status === 'running' && userRole === 'admin' ? 
                            `<button class="btn btn-danger" onclick="stopCampaign(${c.id})">⏹</button>` : ''}
                    </td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error('Campaigns load failed:', e);
    }
}

async function loadContacts() {
    // Implementation
}

async function loadHistory() {
    // Implementation
}

async function loadAudio() {
    // Implementation
}

async function loadUsers() {
    // Implementation
}

async function loadSettings() {
    // Implementation
}

// =============================================
// Actions
// =============================================
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
    } catch (e) {
        alert('Ошибка сервера');
    }
}

async function stopCampaign(id) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns/${id}/stop`, {
            method: 'POST'
        });
        if (response.ok) {
            loadCampaigns();
        }
    } catch (e) {
        alert('Ошибка сервера');
    }
}

async function toggleSystem() {
    try {
        const statusResponse = await authFetch(`${API_BASE}/system/status`);
        const statusData = await statusResponse.json();
        
        if (statusData.enabled) {
            if (!confirm('Аварийная остановка системы? Все активные звонки будут сброшены!')) {
                return;
            }
            await authFetch(`${API_BASE}/system/disable`, { method: 'POST' });
        } else {
            await authFetch(`${API_BASE}/system/enable`, { method: 'POST' });
        }
        
        await refreshSystemStatus();
    } catch (e) {
        alert('Ошибка сервера');
    }
}

function openCampaignModal() {
    const name = prompt('Название кампании:');
    if (name) {
        createCampaign(name);
    }
}

async function createCampaign(name) {
    try {
        const response = await authFetch(`${API_BASE}/campaigns`, {
            method: 'POST',
            body: JSON.stringify({ name, max_calls: 30, cps: 5 })
        });
        if (response.ok) {
            loadCampaigns();
        }
    } catch (e) {
        alert('Ошибка создания');
    }
}
