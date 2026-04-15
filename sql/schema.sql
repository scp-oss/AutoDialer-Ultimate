-- AutoDialer Ultimate Database Schema

CREATE DATABASE autodialer;
\c autodialer;

-- Таблицы
CREATE TABLE campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'draft',
    max_calls INTEGER DEFAULT 30,
    cps INTEGER DEFAULT 5,
    audio_id INTEGER,
    retry_strategy JSONB DEFAULT '{"busy":2,"noanswer":3,"failed":1}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(255),
    group_id INTEGER,
    blacklisted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE call_results (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    unique_id VARCHAR(255),
    linked_id VARCHAR(255),
    status VARCHAR(50),
    dtmf_result VARCHAR(10),
    duration INTEGER,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'operator')),
    force_password_change BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audio_files (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100),
    details JSONB,
    ip_address INET,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE blacklist (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы
CREATE INDEX idx_campaigns_status ON campaigns(status);
CREATE INDEX idx_contacts_phone ON contacts(phone);
CREATE INDEX idx_contacts_blacklisted ON contacts(blacklisted);
CREATE INDEX idx_call_results_campaign ON call_results(campaign_id);
CREATE INDEX idx_call_results_status ON call_results(status);
CREATE INDEX idx_call_results_created ON call_results(created_at);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_blacklist_phone ON blacklist(phone);

-- Настройки по умолчанию
INSERT INTO settings (key, value) VALUES 
    ('system_enabled', 'true'),
    ('global_max_calls', '50'),
    ('default_cps', '5')
ON CONFLICT (key) DO NOTHING;

-- Администратор по умолчанию (admin/admin)
INSERT INTO users (username, password_hash, role, force_password_change) VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIqK0hVdGW',
    'admin',
    TRUE
) ON CONFLICT (username) DO NOTHING;
