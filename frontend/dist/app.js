// Дополнительные функции для полной версии

// =============================================
// Campaign Modal
// =============================================
function openCampaignModal() {
    document.getElementById('campaignModal').style.display = 'flex';
    loadAudioForSelect();
}

function closeCampaignModal() {
    document.getElementById('campaignModal').style.display = 'none';
    document.getElementById('campaignName').value = '';
}

async function createCampaign() {
    const name = document.getElementById('campaignName').value;
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
            body: JSON.stringify({ name, max_calls: maxCalls, cps, audio_id: audioId || null })
        });
        
        if (response.ok) {
            closeCampaignModal();
            loadCampaigns();
            if (currentTab === 'dashboard') loadDashboard();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка создания');
        }
    } catch (e) {
        alert('Ошибка сервера');
    }
}

// =============================================
// User Modal
// =============================================
function openUserModal() {
    document.getElementById('userModal').style.display = 'flex';
}

function closeUserModal() {
    document.getElementById('userModal').style.display = 'none';
    document.getElementById('newUsername').value = '';
    document.getElementById('newUserPassword').value = '';
}

async function createUser() {
    const username = document.getElementById('newUsername').value;
    const password = document.getElementById('newUserPassword').value;
    const role = document.getElementById('newUserRole').value;
    
    if (!username || !password) {
        alert('Заполните все поля');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/users`, {
            method: 'POST',
            body: JSON.stringify({ username, password, role })
        });
        
        if (response.ok) {
            closeUserModal();
            loadUsers();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка создания');
        }
    } catch (e) {
        alert('Ошибка сервера');
    }
}

// =============================================
// Contacts
// =============================================
async function loadContacts() {
    try {
        const response = await authFetch(`${API_BASE}/contacts?limit=50`);
        if (response.ok) {
            const data = await response.json();
            const container = document.getElementById('contactsList');
            
            if (data.contacts.length === 0) {
                container.innerHTML = '<div class="loading">Нет контактов</div>';
                return;
            }
            
            container.innerHTML = data.contacts.map(c => `
                <div class="contact-item">
                    <div>
                        <strong>${c.phone}</strong>
                        ${c.name ? ` - ${c.name}` : ''}
                    </div>
                    <div>
                        ${c.blacklisted ? '<span class="status-badge status-declined">Заблокирован</span>' : ''}
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Contacts load failed:', e);
    }
}

async function importContacts() {
    const text = document.getElementById('contactsImport').value;
    const phones = text.split('\n')
        .map(p => p.trim())
        .filter(p => p)
        .map(p => ({ phone: p }));
    
    if (phones.length === 0) {
        alert('Введите номера телефонов');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/contacts/import`, {
            method: 'POST',
            body: JSON.stringify({ contacts: phones })
        });
        
        if (response.ok) {
            const data = await response.json();
            alert(`Импортировано: ${data.imported}, пропущено: ${data.skipped}`);
            document.getElementById('contactsImport').value = '';
            loadContacts();
        }
    } catch (e) {
        alert('Ошибка импорта');
    }
}

// =============================================
// History
// =============================================
async function loadHistory(page = 1) {
    const campaignId = document.getElementById('historyFilterCampaign').value;
    const status = document.getElementById('historyFilterStatus').value;
    
    let url = `${API_BASE}/history?skip=${(page - 1) * 20}&limit=20`;
    if (campaignId) url += `&campaign_id=${campaignId}`;
    if (status) url += `&status=${status}`;
    
    try {
        const response = await authFetch(url);
        if (response.ok) {
            const data = await response.json();
            const tbody = document.getElementById('historyTable');
            
            if (data.history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Нет записей</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.history.map(h => `
                <tr>
                    <td>${new Date(h.created_at).toLocaleString()}</td>
                    <td>${h.phone}</td>
                    <td>${h.campaign_name || '-'}</td>
                    <td><span class="status-badge status-${h.status}">${h.status}</span></td>
                    <td>${h.dtmf_result || '-'}</td>
                </tr>
            `).join('');
            
            // Pagination
            const totalPages = Math.ceil(data.total / 20);
            renderPagination('historyPagination', page, totalPages, loadHistory);
        }
    } catch (e) {
        console.error('History load failed:', e);
    }
}

function renderPagination(containerId, currentPage, totalPages, callback) {
    const container = document.getElementById(containerId);
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    for (let i = 1; i <= totalPages; i++) {
        if (i === currentPage) {
            html += `<button class="active">${i}</button>`;
        } else if (Math.abs(i - currentPage) <= 2 || i === 1 || i === totalPages) {
            html += `<button onclick="${callback.name}(${i})">${i}</button>`;
        } else if (Math.abs(i - currentPage) === 3) {
            html += `<span>...</span>`;
        }
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
            const container = document.getElementById('audioList');
            
            if (data.length === 0) {
                container.innerHTML = '<div class="loading">Нет аудиофайлов</div>';
                return;
            }
            
            container.innerHTML = data.map(a => `
                <div class="audio-item">
                    <div>
                        <strong>${a.name}</strong>
                        ${a.campaign_name ? ` (${a.campaign_name})` : ''}
                        <div class="text-muted" style="font-size:0.8rem;">${a.created_by_name || 'system'}</div>
                    </div>
                    <div style="display:flex; gap:0.5rem; align-items:center;">
                        <audio controls src="${a.file_path.replace('/var/lib/asterisk/sounds/', '/audio/')}" style="height:30px;"></audio>
                        <button class="btn btn-outline btn-sm" onclick="deleteAudio(${a.id})">🗑</button>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Audio load failed:', e);
    }
}

async function generateAudio() {
    const name = document.getElementById('audioName').value;
    const text = document.getElementById('audioText').value;
    const voice = document.getElementById('audioVoice').value;
    
    if (!name || !text) {
        alert('Заполните название и текст');
        return;
    }
    
    try {
        const response = await authFetch(`${API_BASE}/audio/generate`, {
            method: 'POST',
            body: JSON.stringify({ name, text, voice })
        });
        
        if (response.ok) {
            document.getElementById('audioName').value = '';
            document.getElementById('audioText').value = '';
            loadAudio();
        } else {
            const data = await response.json();
            alert(data.detail || 'Ошибка генерации');
        }
    } catch (e) {
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
    } catch (e) {
        alert('Ошибка удаления');
    }
}

async function loadAudioForSelect() {
    try {
        const response = await authFetch(`${API_BASE}/audio`);
        if (response.ok) {
            const data = await response.json();
            const select = document.getElementById('campaignAudio');
            select.innerHTML = '<option value="">По умолчанию</option>' +
                data.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
        }
    } catch (e) {
        console.error('Audio for select failed:', e);
    }
}

// =============================================
// Users
// =============================================
async function loadUsers() {
    try {
        const response = await authFetch(`${API_BASE}/users`);
        if (response.ok) {
            const data = await response.json();
            const tbody = document.getElementById('usersTable');
            
            tbody.innerHTML = data.users.map(u => `
                <tr>
                    <td>${u.id}</td>
                    <td>${u.username}</td>
                    <td><span class="badge badge-${u.role}">${u.role}</span></td>
                    <td>${u.last_login ? new Date(u.last_login).toLocaleString() : '-'}</td>
                    <td>
                        ${u.id !== 1 ? `<button class="btn btn-outline btn-sm" onclick="deleteUser(${u.id})">🗑</button>` : ''}
                    </td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error('Users load failed:', e);
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
    } catch (e) {
        alert('Ошибка удаления');
    }
}

// =============================================
// Settings
// =============================================
async function loadSettings() {
    try {
        const response = await authFetch(`${API_BASE}/settings`);
        if (response.ok) {
            const data = await response.json();
            const container = document.getElementById('settingsForm');
            
            container.innerHTML = Object.entries(data).map(([key, info]) => `
                <div class="form-group">
                    <label>${key}</label>
                    <div style="display:flex; gap:0.5rem;">
                        <input type="text" value="${info.value}" id="setting_${key}" style="flex:1;">
                        <button class="btn btn-outline btn-sm" onclick="updateSetting('${key}')">Сохранить</button>
                    </div>
                    ${info.description ? `<small class="text-muted">${info.description}</small>` : ''}
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Settings load failed:', e);
    }
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
    } catch (e) {
        alert('Ошибка сохранения');
    }
}
