/**
 * AutoDialer Ultimate - Core Application
 */

const App = {
    // State
    state: {
        accessToken: '',
        refreshToken: '',
        user: null,
        userRole: '',
        currentTab: 'dashboard',
        systemEnabled: true,
        activeCalls: 0,
        maxCalls: 50
    },

    // API Base
    API_BASE: '/api',

    // Initialize
    init() {
        this.loadSidebar();
        this.loadModals();
        this.loadTab('dashboard');
        this.checkAutoLogin();
        this.startPeriodicRefresh();
    },

    // Load sidebar from template
    async loadSidebar() {
        const container = document.getElementById('sidebarContainer');
        const response = await fetch('components/sidebar.html');
        container.innerHTML = await response.text();
    },

    // Load modals from template
    async loadModals() {
        const container = document.getElementById('modalsContainer');
        const response = await fetch('components/modals.html');
        container.innerHTML = await response.text();
    },

    // Load tab content
    async loadTab(tabId) {
        const container = document.getElementById('contentContainer');
        const response = await fetch(`components/tabs/${tabId}.html`);
        container.innerHTML = await response.text();
        
        // Highlight active tab
        document.querySelectorAll('.sidebar-item').forEach(item => {
            item.classList.toggle('active', item.dataset.tab === tabId);
        });
        
        App.state.currentTab = tabId;
        
        // Call tab-specific init
        const initFunc = App[tabId]?.init;
        if (initFunc) initFunc();
    },

    // Switch tab
    switchTab(tabId) {
        this.loadTab(tabId);
    },

    // Check auto login
    checkAutoLogin() {
        const token = localStorage.getItem('refresh_token');
        if (token) {
            App.state.refreshToken = token;
            App.auth.refresh();
        }
    },

    // Start periodic refresh
    startPeriodicRefresh() {
        setInterval(() => {
            if (App.state.currentTab === 'dashboard') {
                App.dashboard?.refresh();
            }
            App.system.refreshStatus();
        }, 3000);
    },

    // Show app
    showApp() {
        document.getElementById('loginScreen').style.display = 'none';
        document.getElementById('appScreen').style.display = 'block';
        this.updateUserDisplay();
        this.applyRoleBasedUI();
    },

    // Update user display
    updateUserDisplay() {
        const user = App.state.user;
        if (user) {
            document.getElementById('userDisplay').innerHTML = `
                <span class="badge badge-${user.role}">${user.role}</span>
                ${user.username}
            `;
        }
    },

    // Apply role-based UI
    applyRoleBasedUI() {
        const isAdmin = App.state.userRole === 'admin';
        document.querySelectorAll('.admin-only').forEach(el => {
            el.style.display = isAdmin ? '' : 'none';
        });
    },

    // Show toast
    showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `<span>${message}</span><button onclick="this.parentElement.remove()">&times;</button>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    },

    // API fetch with auth
    async apiFetch(url, options = {}) {
        if (!options.headers) options.headers = {};
        options.headers['Authorization'] = `Bearer ${App.state.accessToken}`;
        options.headers['Content-Type'] = options.headers['Content-Type'] || 'application/json';
        
        let response = await fetch(`${App.API_BASE}${url}`, options);
        
        if (response.status === 401) {
            const refreshed = await App.auth.refresh();
            if (refreshed) {
                options.headers['Authorization'] = `Bearer ${App.state.accessToken}`;
                response = await fetch(`${App.API_BASE}${url}`, options);
            }
        }
        
        return response;
    }
};

// Export for global use
window.App = App;
