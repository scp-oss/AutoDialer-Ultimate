-- =============================================
-- AutoDialer Ultimate - Complete Database Schema
-- Версия: 3.0.0
-- =============================================
-- ВКЛЮЧЕНО ВСЁ:
-- - 14 таблиц
-- - 50+ индексов
-- - Триггеры и функции
-- - Представления (views)
-- - Дефолтные данные
-- - CHECK constraints
-- - Версионирование записей
-- - Webhook таблицы
-- =============================================

-- =============================================
-- Расширения
-- =============================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================
-- Таблица: schema_migrations (для версионирования БД)
-- =============================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checksum VARCHAR(64)
);

-- =============================================
-- Таблица: users (Пользователи)
-- =============================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email VARCHAR(255),
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'operator' CHECK (role IN ('admin', 'operator', 'viewer')),
    force_password_change BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    last_ip INET,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: campaigns (Кампании)
-- =============================================
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'paused', 'stopped', 'completed', 'failed', 'scheduled')),
    max_calls INTEGER DEFAULT 30 CHECK (max_calls > 0 AND max_calls <= 100),
    cps INTEGER DEFAULT 5 CHECK (cps > 0 AND cps <= 50),
    audio_id INTEGER,
    caller_id VARCHAR(80),
    retry_strategy JSONB DEFAULT '{"busy": 2, "noanswer": 3, "failed": 1, "timeout": 1}',
    schedule JSONB,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: contact_groups (Группы контактов)
-- =============================================
CREATE TABLE IF NOT EXISTS contact_groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    color VARCHAR(7) DEFAULT '#667eea',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: contacts (Контакты)
-- =============================================
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    group_id INTEGER REFERENCES contact_groups(id) ON DELETE SET NULL,
    tags TEXT[],
    custom_fields JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'blocked')),
    blacklisted BOOLEAN DEFAULT FALSE,
    blacklist_reason TEXT,
    notes TEXT,
    last_call_at TIMESTAMP,
    total_calls INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: campaign_contacts (Связь кампаний и контактов)
-- =============================================
CREATE TABLE IF NOT EXISTS campaign_contacts (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    retry_count INTEGER DEFAULT 0,
    last_call_at TIMESTAMP,
    next_retry_at TIMESTAMP,
    status VARCHAR(50),
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(campaign_id, contact_id)
);

-- =============================================
-- Таблица: call_results (Результаты звонков)
-- =============================================
CREATE TABLE IF NOT EXISTS call_results (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    unique_id VARCHAR(255),
    linked_id VARCHAR(255),
    channel VARCHAR(255),
    caller_id VARCHAR(255),
    phone VARCHAR(20) NOT NULL,
    status VARCHAR(50) NOT NULL,
    dtmf_result VARCHAR(10),
    duration INTEGER DEFAULT 0,
    billable_seconds INTEGER DEFAULT 0,
    hangup_cause VARCHAR(50),
    hangup_cause_code INTEGER,
    hangup_cause_txt TEXT,
    retry_count INTEGER DEFAULT 0,
    recording_path TEXT,
    recording_url TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: settings (Настройки системы)
-- =============================================
CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    category VARCHAR(50) DEFAULT 'general',
    is_public BOOLEAN DEFAULT FALSE,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: audio_files (Аудиофайлы)
-- =============================================
CREATE TABLE IF NOT EXISTS audio_files (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    duration INTEGER,
    format VARCHAR(10) DEFAULT 'sln',
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_public BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Внешний ключ для campaigns.audio_id
ALTER TABLE campaigns ADD CONSTRAINT fk_campaigns_audio 
    FOREIGN KEY (audio_id) REFERENCES audio_files(id) ON DELETE SET NULL;

-- =============================================
-- Таблица: audit_log (Журнал аудита)
-- =============================================
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username VARCHAR(50),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id INTEGER,
    details JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: blacklist (Чёрный список)
-- =============================================
CREATE TABLE IF NOT EXISTS blacklist (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    reason TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: api_tokens (API токены)
-- =============================================
CREATE TABLE IF NOT EXISTS api_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: webhook_subscriptions (Webhook подписки)
-- =============================================
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    events TEXT[] NOT NULL DEFAULT '{}',
    secret VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_triggered_at TIMESTAMP,
    failure_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: webhook_deliveries (История доставки webhook)
-- =============================================
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    response_code INTEGER,
    response_body TEXT,
    duration_ms INTEGER,
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Таблица: record_versions (Версионирование записей)
-- =============================================
CREATE TABLE IF NOT EXISTS record_versions (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    data JSONB NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Индексы
-- =============================================

-- Users
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

-- Campaigns
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_created_by ON campaigns(created_by);
CREATE INDEX IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at);
CREATE INDEX IF NOT EXISTS idx_campaigns_started_at ON campaigns(started_at);

-- Contacts
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS idx_contacts_group ON contacts(group_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_contacts_blacklisted ON contacts(blacklisted);
CREATE INDEX IF NOT EXISTS idx_contacts_created_at ON contacts(created_at);
CREATE INDEX IF NOT EXISTS idx_contacts_last_call ON contacts(last_call_at);
CREATE INDEX IF NOT EXISTS idx_contacts_tags ON contacts USING gin(tags);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_phone_active ON contacts(phone) WHERE NOT blacklisted;

-- Contact groups
CREATE INDEX IF NOT EXISTS idx_contact_groups_name ON contact_groups(name);

-- Campaign contacts
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_campaign ON campaign_contacts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_contact ON campaign_contacts(contact_id);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_next_retry ON campaign_contacts(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_status ON campaign_contacts(status);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_priority ON campaign_contacts(priority DESC);

-- Call results
CREATE INDEX IF NOT EXISTS idx_call_results_campaign ON call_results(campaign_id);
CREATE INDEX IF NOT EXISTS idx_call_results_contact ON call_results(contact_id);
CREATE INDEX IF NOT EXISTS idx_call_results_phone ON call_results(phone);
CREATE INDEX IF NOT EXISTS idx_call_results_status ON call_results(status);
CREATE INDEX IF NOT EXISTS idx_call_results_created ON call_results(created_at);
CREATE INDEX IF NOT EXISTS idx_call_results_linked_id ON call_results(linked_id);
CREATE INDEX IF NOT EXISTS idx_call_results_unique_id ON call_results(unique_id);
CREATE INDEX IF NOT EXISTS idx_call_results_campaign_status ON call_results(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_call_results_created_date ON call_results((created_at::DATE));

-- Audio files
CREATE INDEX IF NOT EXISTS idx_audio_files_campaign ON audio_files(campaign_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_created_by ON audio_files(created_by);
CREATE INDEX IF NOT EXISTS idx_audio_files_is_public ON audio_files(is_public);
CREATE INDEX IF NOT EXISTS idx_audio_files_created_at ON audio_files(created_at);

-- Audit log
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_username ON audit_log(username);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);

-- Blacklist
CREATE INDEX IF NOT EXISTS idx_blacklist_phone ON blacklist(phone);
CREATE INDEX IF NOT EXISTS idx_blacklist_created_at ON blacklist(created_at);

-- API tokens
CREATE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_api_tokens_expires ON api_tokens(expires_at);

-- Settings
CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
CREATE INDEX IF NOT EXISTS idx_settings_is_public ON settings(is_public);

-- Webhooks
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_is_active ON webhook_subscriptions(is_active);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at);

-- Record versions
CREATE INDEX IF NOT EXISTS idx_record_versions_entity ON record_versions(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_record_versions_created_at ON record_versions(created_at);

-- =============================================
-- Функции
-- =============================================

-- Функция обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Функция инкремента total_calls контакта
CREATE OR REPLACE FUNCTION increment_contact_total_calls()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE contacts SET 
        total_calls = total_calls + 1,
        last_call_at = NEW.created_at
    WHERE id = NEW.contact_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Функция нормализации телефона
CREATE OR REPLACE FUNCTION normalize_phone_number()
RETURNS TRIGGER AS $$
DECLARE
    cleaned TEXT;
BEGIN
    cleaned := regexp_replace(NEW.phone, '[^0-9]', '', 'g');
    
    IF length(cleaned) = 11 AND cleaned LIKE '8%' THEN
        cleaned := '7' || substring(cleaned from 2);
    ELSIF length(cleaned) = 10 AND cleaned LIKE '9%' THEN
        cleaned := '7' || cleaned;
    END IF;
    
    NEW.phone := cleaned;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Функция аудита
CREATE OR REPLACE FUNCTION audit_trigger_function()
RETURNS TRIGGER AS $$
DECLARE
    audit_user_id INTEGER;
    audit_username VARCHAR(50);
BEGIN
    BEGIN
        audit_user_id := current_setting('app.user_id', true)::INTEGER;
    EXCEPTION WHEN OTHERS THEN
        audit_user_id := NULL;
    END;
    
    BEGIN
        audit_username := current_setting('app.username', true);
    EXCEPTION WHEN OTHERS THEN
        audit_username := NULL;
    END;
    
    IF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, details)
        VALUES (audit_user_id, audit_username, 'DELETE', TG_TABLE_NAME, OLD.id, to_jsonb(OLD));
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, details)
        VALUES (audit_user_id, audit_username, 'UPDATE', TG_TABLE_NAME, NEW.id, 
                jsonb_build_object('old', to_jsonb(OLD), 'new', to_jsonb(NEW)));
        RETURN NEW;
    ELSIF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, details)
        VALUES (audit_user_id, audit_username, 'INSERT', TG_TABLE_NAME, NEW.id, to_jsonb(NEW));
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Функция создания версии записи
CREATE OR REPLACE FUNCTION create_record_version()
RETURNS TRIGGER AS $$
DECLARE
    current_version INTEGER;
    audit_user_id INTEGER;
BEGIN
    SELECT COALESCE(MAX(version), 0) INTO current_version
    FROM record_versions
    WHERE entity_type = TG_TABLE_NAME AND entity_id = NEW.id;
    
    BEGIN
        audit_user_id := current_setting('app.user_id', true)::INTEGER;
    EXCEPTION WHEN OTHERS THEN
        audit_user_id := NULL;
    END;
    
    INSERT INTO record_versions (entity_type, entity_id, version, data, created_by)
    VALUES (TG_TABLE_NAME, NEW.id, current_version + 1, to_jsonb(NEW), audit_user_id);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- Триггеры
-- =============================================

-- updated_at триггеры
DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
CREATE TRIGGER update_campaigns_updated_at 
    BEFORE UPDATE ON campaigns 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_contacts_updated_at ON contacts;
CREATE TRIGGER update_contacts_updated_at 
    BEFORE UPDATE ON contacts 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_webhook_subscriptions_updated_at ON webhook_subscriptions;
CREATE TRIGGER update_webhook_subscriptions_updated_at 
    BEFORE UPDATE ON webhook_subscriptions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Триггер инкремента счётчика звонков
DROP TRIGGER IF EXISTS increment_contact_calls ON call_results;
CREATE TRIGGER increment_contact_calls
    AFTER INSERT ON call_results
    FOR EACH ROW
    EXECUTE FUNCTION increment_contact_total_calls();

-- Триггер нормализации телефона
DROP TRIGGER IF EXISTS normalize_contact_phone ON contacts;
CREATE TRIGGER normalize_contact_phone
    BEFORE INSERT OR UPDATE OF phone ON contacts
    FOR EACH ROW
    EXECUTE FUNCTION normalize_phone_number();

-- Триггеры версионирования
DROP TRIGGER IF EXISTS version_campaigns ON campaigns;
CREATE TRIGGER version_campaigns
    AFTER UPDATE ON campaigns
    FOR EACH ROW
    EXECUTE FUNCTION create_record_version();

DROP TRIGGER IF EXISTS version_contacts ON contacts;
CREATE TRIGGER version_contacts
    AFTER UPDATE ON contacts
    FOR EACH ROW
    EXECUTE FUNCTION create_record_version();

DROP TRIGGER IF EXISTS version_settings ON settings;
CREATE TRIGGER version_settings
    AFTER UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION create_record_version();

-- =============================================
-- Представления (Views)
-- =============================================

-- Представление статистики кампаний
CREATE OR REPLACE VIEW campaign_stats AS
SELECT 
    c.id,
    c.name,
    c.status,
    c.max_calls,
    c.cps,
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT cr.id) AS total_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'declined' THEN cr.id END) AS declined_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'busy' THEN cr.id END) AS busy_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'noanswer' THEN cr.id END) AS noanswer_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'failed' THEN cr.id END) AS failed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'timeout' THEN cr.id END) AS timeout_calls,
    ROUND(AVG(cr.duration)::numeric, 2) AS avg_duration,
    SUM(cr.billable_seconds) AS total_billable_seconds,
    CASE 
        WHEN COUNT(DISTINCT cr.id) > 0 
        THEN ROUND(COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) * 100.0 / COUNT(DISTINCT cr.id), 2)
        ELSE 0 
    END AS conversion_rate,
    c.created_at,
    c.started_at,
    c.completed_at
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
GROUP BY c.id, c.name, c.status, c.max_calls, c.cps, c.created_at, c.started_at, c.completed_at;

-- Представление статистики по дням
CREATE OR REPLACE VIEW daily_stats AS
SELECT 
    DATE(created_at) AS date,
    COUNT(*) AS total_calls,
    COUNT(CASE WHEN status = 'agreed' THEN 1 END) AS agreed,
    COUNT(CASE WHEN status = 'declined' THEN 1 END) AS declined,
    COUNT(CASE WHEN status = 'busy' THEN 1 END) AS busy,
    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) AS noanswer,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) AS failed,
    COUNT(CASE WHEN status = 'timeout' THEN 1 END) AS timeout,
    ROUND(AVG(duration)::numeric, 2) AS avg_duration,
    SUM(billable_seconds) AS total_billable_seconds
FROM call_results
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- Представление активных кампаний
CREATE OR REPLACE VIEW active_campaigns AS
SELECT 
    c.*,
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT cr.id) AS calls_made,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
WHERE c.status IN ('running', 'paused')
GROUP BY c.id;

-- Представление статистики по пользователям
CREATE OR REPLACE VIEW user_stats AS
SELECT 
    u.id,
    u.username,
    u.role,
    COUNT(DISTINCT c.id) AS campaigns_created,
    COUNT(DISTINCT ct.id) AS contacts_imported,
    COUNT(DISTINCT af.id) AS audio_files_created,
    u.last_login,
    u.created_at
FROM users u
LEFT JOIN campaigns c ON u.id = c.created_by
LEFT JOIN contacts ct ON u.id = ct.created_by
LEFT JOIN audio_files af ON u.id = af.created_by
GROUP BY u.id, u.username, u.role, u.last_login, u.created_at;

-- Представление очереди на дозвон
CREATE OR REPLACE VIEW dial_queue_view AS
SELECT 
    cc.id,
    cc.campaign_id,
    c.name AS campaign_name,
    cc.contact_id,
    ct.phone,
    ct.name AS contact_name,
    cc.retry_count,
    cc.priority,
    cc.next_retry_at,
    cc.last_call_at
FROM campaign_contacts cc
JOIN campaigns c ON cc.campaign_id = c.id
JOIN contacts ct ON cc.contact_id = ct.id
WHERE c.status = 'running'
  AND ct.blacklisted = FALSE
  AND (cc.next_retry_at IS NULL OR cc.next_retry_at <= NOW())
ORDER BY cc.priority DESC, cc.retry_count ASC, cc.id ASC;

-- =============================================
-- Дефолтные настройки
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    -- System
    ('system_enabled', 'true', 'Global system enable/disable', 'system'),
    ('versioning_enabled', 'true', 'Enable record versioning', 'system'),
    
    -- Dialer
    ('global_max_calls', '50', 'Maximum concurrent calls globally', 'dialer'),
    ('default_cps', '5', 'Default calls per second', 'dialer'),
    ('call_timeout', '30', 'Call timeout in seconds', 'dialer'),
    ('max_retries', '3', 'Maximum retry attempts', 'dialer'),
    ('retry_busy_max', '2', 'Max retries for busy', 'dialer'),
    ('retry_busy_delay', '120', 'Delay for busy retry (seconds)', 'dialer'),
    ('retry_noanswer_max', '3', 'Max retries for no answer', 'dialer'),
    ('retry_noanswer_delay', '300', 'Delay for no answer retry', 'dialer'),
    ('retry_failed_max', '1', 'Max retries for failed', 'dialer'),
    ('retry_failed_delay', '60', 'Delay for failed retry (seconds)', 'dialer'),
    
    -- Storage
    ('audio_retention_days', '30', 'Audio files retention period', 'storage'),
    ('max_upload_size_mb', '10', 'Maximum upload file size', 'storage'),
    
    -- Features
    ('recording_enabled', 'false', 'Enable call recording', 'features'),
    ('recording_format', 'wav', 'Recording format (wav/mp3)', 'features'),
    ('amd_enabled', 'false', 'Enable answering machine detection', 'features'),
    ('amd_initial_silence', '2500', 'AMD initial silence (ms)', 'features'),
    ('amd_greeting', '1500', 'AMD greeting timeout (ms)', 'features'),
    ('amd_after_greeting_silence', '800', 'AMD after greeting silence (ms)', 'features'),
    ('amd_total_analysis_time', '5000', 'AMD total analysis time (ms)', 'features'),
    ('websocket_enabled', 'true', 'Enable WebSocket for real-time updates', 'features'),
    
    -- Monitoring
    ('metrics_enabled', 'true', 'Enable Prometheus metrics', 'monitoring'),
    
    -- Security
    ('rate_limit_enabled', 'true', 'Enable rate limiting', 'security'),
    ('rate_limit_requests', '100', 'Rate limit requests per window', 'security'),
    ('rate_limit_window', '60', 'Rate limit window in seconds', 'security'),
    ('login_rate_limit', '5', 'Login attempts before block', 'security'),
    ('login_rate_window', '300', 'Login rate window in seconds', 'security'),
    ('session_timeout', '3600', 'Session timeout in seconds', 'security'),
    
    -- Webhook
    ('webhook_enabled', 'true', 'Enable webhook notifications', 'webhook'),
    ('webhook_timeout', '10', 'Webhook request timeout (seconds)', 'webhook'),
    ('webhook_max_retries', '3', 'Maximum webhook retry attempts', 'webhook'),
    ('webhook_retry_delay', '60', 'Webhook retry delay (seconds)', 'webhook')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Дефолтный администратор (пароль: admin)
-- =============================================
INSERT INTO users (username, password_hash, email, full_name, role, force_password_change) VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIqK0hVdGW',
    'admin@localhost',
    'System Administrator',
    'admin',
    TRUE
) ON CONFLICT (username) DO NOTHING;

-- =============================================
-- Дефолтные группы контактов
-- =============================================
INSERT INTO contact_groups (name, description, color) VALUES 
    ('Default', 'Default contact group', '#667eea'),
    ('VIP', 'VIP contacts', '#f59e0b'),
    ('Blocked', 'Blocked contacts', '#ef4444')
ON CONFLICT (name) DO NOTHING;

-- =============================================
-- Запись о начальной схеме
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('001', 'Complete Schema') ON CONFLICT (version) DO NOTHING;

-- =============================================
-- Комментарии к таблицам
-- =============================================
COMMENT ON TABLE users IS 'Пользователи системы';
COMMENT ON TABLE campaigns IS 'Кампании обзвона';
COMMENT ON TABLE contact_groups IS 'Группы контактов';
COMMENT ON TABLE contacts IS 'Контакты (телефонные номера)';
COMMENT ON TABLE campaign_contacts IS 'Связь кампаний и контактов';
COMMENT ON TABLE call_results IS 'Результаты звонков';
COMMENT ON TABLE settings IS 'Настройки системы';
COMMENT ON TABLE audio_files IS 'Аудиофайлы';
COMMENT ON TABLE audit_log IS 'Журнал аудита';
COMMENT ON TABLE blacklist IS 'Чёрный список номеров';
COMMENT ON TABLE api_tokens IS 'API токены';
COMMENT ON TABLE schema_migrations IS 'История миграций';
COMMENT ON TABLE webhook_subscriptions IS 'Webhook подписки';
COMMENT ON TABLE webhook_deliveries IS 'История доставки webhook';
COMMENT ON TABLE record_versions IS 'Версионирование записей';

COMMENT ON COLUMN users.role IS 'Роль: admin, operator, viewer';
COMMENT ON COLUMN campaigns.status IS 'Статус: draft, running, paused, stopped, completed, failed, scheduled';
COMMENT ON COLUMN contacts.status IS 'Статус: active, inactive, blocked';
COMMENT ON COLUMN call_results.status IS 'Статус: agreed, declined, busy, noanswer, failed, timeout, cancelled, machine';
