* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    line-height: 1.5;
}

/* Login */
#loginScreen {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
    background: #1e293b;
    border-radius: 16px;
    padding: 2.5rem;
    width: 100%;
    max-width: 400px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

.login-card h2 {
    margin-bottom: 1.5rem;
    text-align: center;
    color: #f1f5f9;
}

.login-card input {
    width: 100%;
    padding: 0.75rem;
    margin-bottom: 1rem;
    background: #334155;
    border: 1px solid #475569;
    border-radius: 8px;
    color: #f1f5f9;
    font-size: 1rem;
}

.login-card input:focus {
    outline: none;
    border-color: #667eea;
}

.login-card button {
    width: 100%;
    padding: 0.75rem;
    background: #667eea;
    color: white;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 600;
    font-size: 1rem;
    transition: background 0.2s;
}

.login-card button:hover {
    background: #5a67d8;
}

/* App */
#appScreen {
    display: none;
}

.header {
    background: #1e293b;
    padding: 1rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #334155;
}

.header h1 {
    color: #f1f5f9;
    font-size: 1.5rem;
}

.layout {
    display: flex;
    min-height: calc(100vh - 65px);
}

.sidebar {
    width: 260px;
    background: #1e293b;
    padding: 1.5rem 0;
    border-right: 1px solid #334155;
}

.sidebar-item {
    padding: 0.75rem 1.5rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    color: #94a3b8;
    transition: all 0.2s;
}

.sidebar-item:hover {
    background: #334155;
    color: #f1f5f9;
}

.sidebar-item.active {
    background: #667eea;
    color: white;
}

.content {
    flex: 1;
    padding: 2rem;
    overflow-y: auto;
}

/* Cards */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.stat-card {
    background: #1e293b;
    border-radius: 12px;
    padding: 1.5rem;
    border: 1px solid #334155;
}

.stat-value {
    font-size: 2.5rem;
    font-weight: 700;
    color: #667eea;
}

.stat-label {
    color: #94a3b8;
    margin-top: 0.5rem;
}

.card {
    background: #1e293b;
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
    border: 1px solid #334155;
}

.card h2, .card h3 {
    color: #f1f5f9;
    margin-bottom: 1rem;
}

/* Tables */
table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid #334155;
}

th {
    font-weight: 600;
    color: #94a3b8;
}

/* Buttons */
.btn {
    padding: 0.5rem 1rem;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    font-weight: 500;
    font-size: 0.9rem;
    margin-right: 0.5rem;
    transition: all 0.2s;
}

.btn-primary {
    background: #667eea;
    color: white;
}

.btn-primary:hover {
    background: #5a67d8;
}

.btn-success {
    background: #10b981;
    color: white;
}

.btn-success:hover {
    background: #059669;
}

.btn-danger {
    background: #ef4444;
    color: white;
}

.btn-danger:hover {
    background: #dc2626;
}

.btn-outline {
    background: transparent;
    border: 1px solid #475569;
    color: #e2e8f0;
}

.btn-outline:hover {
    background: #334155;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 500;
}

.badge-running {
    background: #10b98120;
    color: #10b981;
    border: 1px solid #10b98140;
}

.badge-stopped {
    background: #ef444420;
    color: #ef4444;
    border: 1px solid #ef444440;
}

.badge-draft {
    background: #64748b20;
    color: #94a3b8;
    border: 1px solid #64748b40;
}

.badge-completed {
    background: #3b82f620;
    color: #60a5fa;
    border: 1px solid #3b82f640;
}

/* System Bar */
.system-bar {
    background: #0f172a;
    padding: 0.5rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #334155;
}

.kill-switch {
    background: #ef4444;
    color: white;
    border: none;
    padding: 0.25rem 1rem;
    border-radius: 20px;
    cursor: pointer;
    font-weight: bold;
    transition: background 0.2s;
}

.kill-switch:hover {
    background: #dc2626;
}

/* Modal */
.modal {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.7);
    justify-content: center;
    align-items: center;
    z-index: 1000;
}

.modal-content {
    background: #1e293b;
    padding: 2rem;
    border-radius: 12px;
    max-width: 500px;
    width: 90%;
}

.modal-content h3 {
    margin-bottom: 1rem;
    color: #f1f5f9;
}

.modal-content input {
    width: 100%;
    padding: 0.75rem;
    margin-bottom: 1rem;
    background: #334155;
    border: 1px solid #475569;
    border-radius: 8px;
    color: #f1f5f9;
}

/* Forms */
.form-group {
    margin-bottom: 1rem;
}

.form-group label {
    display: block;
    margin-bottom: 0.5rem;
    color: #94a3b8;
}

.form-group input,
.form-group textarea,
.form-group select {
    width: 100%;
    padding: 0.75rem;
    background: #334155;
    border: 1px solid #475569;
    border-radius: 8px;
    color: #f1f5f9;
}

/* Tab Content */
.tab-content {
    display: none;
}

.tab-content.active {
    display: block;
}

/* Progress Bar */
.progress-bar {
    width: 100%;
    height: 8px;
    background: #334155;
    border-radius: 4px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background: #10b981;
    transition: width 0.3s ease;
}

/* Utilities */
.text-success { color: #10b981; }
.text-danger { color: #ef4444; }
.text-warning { color: #f59e0b; }
.text-muted { color: #64748b; }

.mt-2 { margin-top: 0.5rem; }
.mt-4 { margin-top: 1rem; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-4 { margin-bottom: 1rem; }

.flex { display: flex; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.gap-2 { gap: 0.5rem; }
.gap-4 { gap: 1rem; }
