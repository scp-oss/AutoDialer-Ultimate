-- =============================================
-- AutoDialer Ultimate - Complete Database Schema
-- Версия: 3.0.0
-- =============================================
-- ЕДИНЫЙ ФАЙЛ ДЛЯ ЧИСТОЙ УСТАНОВКИ
-- ВКЛЮЧАЕТ:
-- - 16 таблиц (включая incoming_calls)
-- - 90+ индексов
-- - 14 триггеров
-- - 17 функций
-- - 11 представлений
-- - Дефолтные данные
-- =============================================

-- =============================================
-- РАСШИРЕНИЯ
-- =============================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================
-- ТАБЛИЦА МИГРАЦИЙ
-- =============================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checksum VARCHAR(64)
);

-- =============================================
-- 1. USERS (ПОЛЬЗОВАТЕЛИ)
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
-- 2. SESSIONS (СЕССИИ ПОЛЬЗОВАТЕЛЕЙ)
-- =============================================
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token TEXT,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 3. CAMPAIGNS (КАМПАНИИ)
-- =============================================
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'paused', 'stopped', 'completed', 'failed', 'scheduled')),
    max_calls INTEGER DEFAULT 30 CHECK (max_calls > 0 AND max_calls <= 200),
    cps INTEGER DEFAULT 5 CHECK (cps > 0 AND cps <= 100),
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
-- 4. CAMPAIGN_SCHEDULES (РАСПИСАНИЯ КАМПАНИЙ)
-- =============================================
CREATE TABLE IF NOT EXISTS campaign_schedules (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name VARCHAR(255),
    schedule_type VARCHAR(20) NOT NULL DEFAULT 'once' CHECK (schedule_type IN ('once', 'daily', 'weekly', 'monthly', 'cron')),
    cron_expression VARCHAR(100),
    days_of_week INTEGER[],
    hours INTEGER[],
    minutes INTEGER[],
    timezone VARCHAR(50) DEFAULT 'UTC',
    start_at TIMESTAMP,
    end_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 5. CONTACT_GROUPS (ГРУППЫ КОНТАКТОВ)
-- =============================================
CREATE TABLE IF NOT EXISTS contact_groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    color VARCHAR(7) DEFAULT '#667eea',
    parent_id INTEGER REFERENCES contact_groups(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 6. CONTACTS (КОНТАКТЫ)
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
    total_agreed INTEGER DEFAULT 0,
    total_declined INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_phone_active ON contacts(phone) WHERE NOT blacklisted;

-- =============================================
-- 7. CONTACT_IMPORT_JOBS (ЗАДАЧИ ИМПОРТА)
-- =============================================
CREATE TABLE IF NOT EXISTS contact_import_jobs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    group_id INTEGER REFERENCES contact_groups(id) ON DELETE SET NULL,
    file_name VARCHAR(255),
    file_size INTEGER,
    total_rows INTEGER DEFAULT 0,
    processed_rows INTEGER DEFAULT 0,
    imported_rows INTEGER DEFAULT 0,
    skipped_rows INTEGER DEFAULT 0,
    failed_rows INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 8. CAMPAIGN_CONTACTS (СВЯЗЬ КАМПАНИЙ И КОНТАКТОВ)
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
-- 9. CALL_RESULTS (РЕЗУЛЬТАТЫ ЗВОНКОВ)
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
-- 10. CALL_RECORDINGS (ЗАПИСИ РАЗГОВОРОВ)
-- =============================================
CREATE TABLE IF NOT EXISTS call_recordings (
    id SERIAL PRIMARY KEY,
    call_result_id INTEGER REFERENCES call_results(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    duration INTEGER,
    format VARCHAR(10) DEFAULT 'wav',
    transcription TEXT,
    transcription_status VARCHAR(20),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 11. SETTINGS (НАСТРОЙКИ СИСТЕМЫ)
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
-- 12. AUDIO_FILES (АУДИОФАЙЛЫ)
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

ALTER TABLE campaigns ADD CONSTRAINT fk_campaigns_audio 
    FOREIGN KEY (audio_id) REFERENCES audio_files(id) ON DELETE SET NULL;

-- =============================================
-- 13. TTS_JOBS (ЗАДАЧИ ГЕНЕРАЦИИ TTS)
-- =============================================
CREATE TABLE IF NOT EXISTS tts_jobs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    text TEXT NOT NULL,
    voice VARCHAR(50) DEFAULT 'denis',
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    audio_file_id INTEGER REFERENCES audio_files(id) ON DELETE SET NULL,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 14. AUDIT_LOG (ЖУРНАЛ АУДИТА)
-- =============================================
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
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
-- 15. BLACKLIST (ЧЁРНЫЙ СПИСОК)
-- =============================================
CREATE TABLE IF NOT EXISTS blacklist (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    reason TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 16. API_TOKENS (API ТОКЕНЫ)
-- =============================================
CREATE TABLE IF NOT EXISTS api_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    permissions TEXT[],
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 17. WEBHOOK_EVENTS (ТИПЫ СОБЫТИЙ)
-- =============================================
CREATE TABLE IF NOT EXISTS webhook_events (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(50) DEFAULT 'general',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 18. WEBHOOK_SUBSCRIPTIONS (ПОДПИСКИ)
-- =============================================
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    events TEXT[] NOT NULL DEFAULT '{}',
    secret VARCHAR(255),
    headers JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    verify_ssl BOOLEAN DEFAULT TRUE,
    timeout_seconds INTEGER DEFAULT 10,
    max_retries INTEGER DEFAULT 3,
    retry_delay_seconds INTEGER DEFAULT 60,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_triggered_at TIMESTAMP,
    last_success_at TIMESTAMP,
    last_failure_at TIMESTAMP,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 19. WEBHOOK_DELIVERIES (ИСТОРИЯ ДОСТАВКИ)
-- =============================================
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id BIGSERIAL PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    event_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    payload_size INTEGER,
    request_url TEXT NOT NULL,
    request_headers JSONB,
    request_body TEXT,
    response_code INTEGER,
    response_headers JSONB,
    response_body TEXT,
    duration_ms INTEGER,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed', 'retry', 'expired')),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMP,
    ip_address INET,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- =============================================
-- 20. RECORD_VERSIONS (ВЕРСИОНИРОВАНИЕ)
-- =============================================
CREATE TABLE IF NOT EXISTS record_versions (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    data JSONB NOT NULL,
    changed_fields TEXT[],
    change_summary TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_by_username VARCHAR(50),
    created_by_ip INET,
    created_by_agent TEXT,
    reverted_from_version INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 21. NOTIFICATIONS (УВЕДОМЛЕНИЯ)
-- =============================================
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 22. SYSTEM_EVENTS (СИСТЕМНЫЕ СОБЫТИЯ)
-- =============================================
CREATE TABLE IF NOT EXISTS system_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    source VARCHAR(100),
    message TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 23. INCOMING_CALLS (ВХОДЯЩИЕ ЗВОНКИ)
-- =============================================
CREATE TABLE IF NOT EXISTS incoming_calls (
    id SERIAL PRIMARY KEY,
    caller_number VARCHAR(20) NOT NULL,
    recording_path TEXT NOT NULL,
    transcription TEXT,
    transcription_status VARCHAR(20) DEFAULT 'pending' CHECK (transcription_status IN ('pending', 'processing', 'completed', 'failed')),
    duration INTEGER,
    file_size INTEGER,
    call_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    listened BOOLEAN DEFAULT FALSE,
    notes TEXT,
    metadata JSONB DEFAULT '{}'
);

-- =============================================
-- ИНДЕКСЫ
-- =============================================

-- Users
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);
CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login) WHERE last_login IS NOT NULL;

-- Sessions
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_is_active ON sessions(is_active) WHERE is_active = TRUE;

-- Campaigns
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_created_by ON campaigns(created_by);
CREATE INDEX IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at);
CREATE INDEX IF NOT EXISTS idx_campaigns_started_at ON campaigns(started_at) WHERE started_at IS NOT NULL;

-- Campaign schedules
CREATE INDEX IF NOT EXISTS idx_campaign_schedules_campaign ON campaign_schedules(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_schedules_is_active ON campaign_schedules(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_campaign_schedules_next_run ON campaign_schedules(next_run_at) WHERE next_run_at IS NOT NULL;

-- Contacts
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS idx_contacts_group ON contacts(group_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_contacts_blacklisted ON contacts(blacklisted) WHERE blacklisted = TRUE;
CREATE INDEX IF NOT EXISTS idx_contacts_created_at ON contacts(created_at);
CREATE INDEX IF NOT EXISTS idx_contacts_last_call ON contacts(last_call_at) WHERE last_call_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_tags ON contacts USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_contacts_custom_fields ON contacts USING gin(custom_fields);
CREATE INDEX IF NOT EXISTS idx_contacts_name_trgm ON contacts USING gin(name gin_trgm_ops);

-- Contact import jobs
CREATE INDEX IF NOT EXISTS idx_contact_import_jobs_status ON contact_import_jobs(status);
CREATE INDEX IF NOT EXISTS idx_contact_import_jobs_created_by ON contact_import_jobs(created_by);

-- Contact groups
CREATE INDEX IF NOT EXISTS idx_contact_groups_name ON contact_groups(name);
CREATE INDEX IF NOT EXISTS idx_contact_groups_parent ON contact_groups(parent_id) WHERE parent_id IS NOT NULL;

-- Campaign contacts
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_campaign ON campaign_contacts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_contact ON campaign_contacts(contact_id);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_next_retry ON campaign_contacts(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_priority ON campaign_contacts(priority DESC);

-- Call results
CREATE INDEX IF NOT EXISTS idx_call_results_campaign ON call_results(campaign_id);
CREATE INDEX IF NOT EXISTS idx_call_results_contact ON call_results(contact_id);
CREATE INDEX IF NOT EXISTS idx_call_results_phone ON call_results(phone);
CREATE INDEX IF NOT EXISTS idx_call_results_status ON call_results(status);
CREATE INDEX IF NOT EXISTS idx_call_results_created ON call_results(created_at);
CREATE INDEX IF NOT EXISTS idx_call_results_linked_id ON call_results(linked_id) WHERE linked_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_call_results_unique_id ON call_results(unique_id) WHERE unique_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_call_results_campaign_status ON call_results(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_call_results_created_date ON call_results((created_at::DATE));

-- Call recordings
CREATE INDEX IF NOT EXISTS idx_call_recordings_call_result ON call_recordings(call_result_id);

-- Audio files
CREATE INDEX IF NOT EXISTS idx_audio_files_campaign ON audio_files(campaign_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audio_files_created_by ON audio_files(created_by);
CREATE INDEX IF NOT EXISTS idx_audio_files_is_public ON audio_files(is_public) WHERE is_public = TRUE;
CREATE INDEX IF NOT EXISTS idx_audio_files_created_at ON audio_files(created_at);

-- TTS jobs
CREATE INDEX IF NOT EXISTS idx_tts_jobs_status ON tts_jobs(status);
CREATE INDEX IF NOT EXISTS idx_tts_jobs_created_by ON tts_jobs(created_by);

-- Audit log
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_details ON audit_log USING gin(details);

-- Blacklist
CREATE INDEX IF NOT EXISTS idx_blacklist_phone ON blacklist(phone);
CREATE INDEX IF NOT EXISTS idx_blacklist_created_at ON blacklist(created_at);

-- API tokens
CREATE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_api_tokens_expires ON api_tokens(expires_at) WHERE expires_at IS NOT NULL;

-- Settings
CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
CREATE INDEX IF NOT EXISTS idx_settings_is_public ON settings(is_public) WHERE is_public = TRUE;

-- Webhook events
CREATE INDEX IF NOT EXISTS idx_webhook_events_name ON webhook_events(name);
CREATE INDEX IF NOT EXISTS idx_webhook_events_category ON webhook_events(category);

-- Webhook subscriptions
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_is_active ON webhook_subscriptions(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_created_by ON webhook_subscriptions(created_by);
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_events ON webhook_subscriptions USING gin(events);

-- Webhook deliveries
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at) WHERE next_retry_at IS NOT NULL;

-- Record versions
CREATE INDEX IF NOT EXISTS idx_record_versions_entity ON record_versions(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_record_versions_version ON record_versions(entity_type, entity_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_record_versions_created_at ON record_versions(created_at);
CREATE INDEX IF NOT EXISTS idx_record_versions_data ON record_versions USING gin(data);

-- Notifications
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read) WHERE NOT is_read;
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);

-- System events
CREATE INDEX IF NOT EXISTS idx_system_events_type ON system_events(event_type);
CREATE INDEX IF NOT EXISTS idx_system_events_severity ON system_events(severity);
CREATE INDEX IF NOT EXISTS idx_system_events_created_at ON system_events(created_at);

-- Incoming calls
CREATE INDEX IF NOT EXISTS idx_incoming_calls_caller ON incoming_calls(caller_number);
CREATE INDEX IF NOT EXISTS idx_incoming_calls_date ON incoming_calls(call_date);
CREATE INDEX IF NOT EXISTS idx_incoming_calls_status ON incoming_calls(transcription_status);

-- =============================================
-- ФУНКЦИИ
-- =============================================

-- Обновление updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Инкремент счётчика звонков
CREATE OR REPLACE FUNCTION increment_contact_total_calls()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.contact_id IS NOT NULL THEN
        UPDATE contacts SET 
            total_calls = total_calls + 1,
            last_call_at = NEW.created_at,
            total_agreed = total_agreed + CASE WHEN NEW.status = 'agreed' THEN 1 ELSE 0 END,
            total_declined = total_declined + CASE WHEN NEW.status = 'declined' THEN 1 ELSE 0 END
        WHERE id = NEW.contact_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Нормализация телефона
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

-- Проверка чёрного списка
CREATE OR REPLACE FUNCTION check_blacklist()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM blacklist WHERE phone = NEW.phone) THEN
        NEW.blacklisted = TRUE;
        NEW.blacklist_reason = COALESCE(NEW.blacklist_reason, 'Number in blacklist');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Создание версии записи
CREATE OR REPLACE FUNCTION create_record_version()
RETURNS TRIGGER AS $$
DECLARE
    current_version INTEGER;
    audit_user_id INTEGER;
    audit_username VARCHAR(50);
    audit_ip INET;
    new_json JSONB;
BEGIN
    SELECT COALESCE(MAX(version), 0) INTO current_version
    FROM record_versions
    WHERE entity_type = TG_TABLE_NAME AND entity_id = NEW.id;
    
    BEGIN audit_user_id := current_setting('app.user_id', true)::INTEGER; EXCEPTION WHEN OTHERS THEN audit_user_id := NULL; END;
    BEGIN audit_username := current_setting('app.username', true); EXCEPTION WHEN OTHERS THEN audit_username := NULL; END;
    BEGIN audit_ip := current_setting('app.ip_address', true)::INET; EXCEPTION WHEN OTHERS THEN audit_ip := NULL; END;
    
    new_json := to_jsonb(NEW);
    
    INSERT INTO record_versions (entity_type, entity_id, version, data, created_by, created_by_username, created_by_ip, metadata)
    VALUES (TG_TABLE_NAME, NEW.id, current_version + 1, new_json, audit_user_id, audit_username, audit_ip,
            jsonb_build_object('operation', TG_OP));
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Очистка старых версий
CREATE OR REPLACE FUNCTION cleanup_old_record_versions(p_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM record_versions WHERE created_at < CURRENT_TIMESTAMP - (p_days || ' days')::INTERVAL;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Очистка старых сессий
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP OR is_active = FALSE;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- ТРИГГЕРЫ
-- =============================================

-- updated_at
DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
CREATE TRIGGER update_campaigns_updated_at BEFORE UPDATE ON campaigns FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
DROP TRIGGER IF EXISTS update_contacts_updated_at ON contacts;
CREATE TRIGGER update_contacts_updated_at BEFORE UPDATE ON contacts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
DROP TRIGGER IF EXISTS update_campaign_schedules_updated_at ON campaign_schedules;
CREATE TRIGGER update_campaign_schedules_updated_at BEFORE UPDATE ON campaign_schedules FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
DROP TRIGGER IF EXISTS update_webhook_subscriptions_updated_at ON webhook_subscriptions;
CREATE TRIGGER update_webhook_subscriptions_updated_at BEFORE UPDATE ON webhook_subscriptions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Инкремент звонков
DROP TRIGGER IF EXISTS increment_contact_calls ON call_results;
CREATE TRIGGER increment_contact_calls AFTER INSERT ON call_results FOR EACH ROW EXECUTE FUNCTION increment_contact_total_calls();

-- Нормализация телефона
DROP TRIGGER IF EXISTS normalize_contact_phone ON contacts;
CREATE TRIGGER normalize_contact_phone BEFORE INSERT OR UPDATE OF phone ON contacts FOR EACH ROW EXECUTE FUNCTION normalize_phone_number();

-- Чёрный список
DROP TRIGGER IF EXISTS check_contact_blacklist ON contacts;
CREATE TRIGGER check_contact_blacklist BEFORE INSERT OR UPDATE OF phone ON contacts FOR EACH ROW EXECUTE FUNCTION check_blacklist();

-- Версионирование
DROP TRIGGER IF EXISTS version_campaigns ON campaigns;
CREATE TRIGGER version_campaigns AFTER INSERT OR UPDATE ON campaigns FOR EACH ROW EXECUTE FUNCTION create_record_version();
DROP TRIGGER IF EXISTS version_contacts ON contacts;
CREATE TRIGGER version_contacts AFTER INSERT OR UPDATE ON contacts FOR EACH ROW EXECUTE FUNCTION create_record_version();
DROP TRIGGER IF EXISTS version_settings ON settings;
CREATE TRIGGER version_settings AFTER INSERT OR UPDATE ON settings FOR EACH ROW EXECUTE FUNCTION create_record_version();
DROP TRIGGER IF EXISTS version_users ON users;
CREATE TRIGGER version_users AFTER INSERT OR UPDATE ON users FOR EACH ROW EXECUTE FUNCTION create_record_version();

-- =============================================
-- ПРЕДСТАВЛЕНИЯ
-- =============================================

-- Статистика кампаний
CREATE OR REPLACE VIEW campaign_stats AS
SELECT c.id, c.name, c.status, c.max_calls, c.cps,
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT cr.id) AS total_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'declined' THEN cr.id END) AS declined_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'busy' THEN cr.id END) AS busy_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'noanswer' THEN cr.id END) AS noanswer_calls,
    ROUND(AVG(cr.duration)::numeric, 2) AS avg_duration,
    CASE WHEN COUNT(DISTINCT cr.id) > 0 
         THEN ROUND(COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) * 100.0 / COUNT(DISTINCT cr.id), 2)
         ELSE 0 END AS conversion_rate,
    c.created_at, c.started_at, c.completed_at
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
GROUP BY c.id;

-- Дневная статистика
CREATE OR REPLACE VIEW daily_stats AS
SELECT DATE(created_at) AS date,
    COUNT(*) AS total_calls,
    COUNT(CASE WHEN status = 'agreed' THEN 1 END) AS agreed,
    COUNT(CASE WHEN status = 'declined' THEN 1 END) AS declined,
    COUNT(CASE WHEN status = 'busy' THEN 1 END) AS busy,
    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) AS noanswer,
    ROUND(AVG(duration)::numeric, 2) AS avg_duration
FROM call_results
GROUP BY DATE(created_at) ORDER BY date DESC;

-- Активные кампании
CREATE OR REPLACE VIEW active_campaigns AS
SELECT c.*, COUNT(DISTINCT cc.contact_id) AS total_contacts, COUNT(DISTINCT cr.id) AS calls_made
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
WHERE c.status IN ('running', 'paused')
GROUP BY c.id;

-- Очередь дозвона
CREATE OR REPLACE VIEW dial_queue_view AS
SELECT cc.id, cc.campaign_id, c.name AS campaign_name, cc.contact_id, ct.phone, ct.name AS contact_name,
    cc.retry_count, cc.priority, cc.next_retry_at, cc.last_call_at
FROM campaign_contacts cc
JOIN campaigns c ON cc.campaign_id = c.id
JOIN contacts ct ON cc.contact_id = ct.id
WHERE c.status = 'running' AND ct.blacklisted = FALSE
  AND (cc.next_retry_at IS NULL OR cc.next_retry_at <= NOW())
ORDER BY cc.priority DESC, cc.retry_count ASC, cc.id ASC;

-- Сводка дашборда
CREATE OR REPLACE VIEW dashboard_summary AS
SELECT 
    (SELECT COUNT(*) FROM campaigns) AS total_campaigns,
    (SELECT COUNT(*) FROM campaigns WHERE status = 'running') AS running_campaigns,
    (SELECT COUNT(*) FROM contacts WHERE NOT blacklisted) AS total_contacts,
    (SELECT COUNT(*) FROM call_results) AS total_calls,
    (SELECT COUNT(*) FROM call_results WHERE DATE(created_at) = CURRENT_DATE) AS calls_today,
    (SELECT COUNT(*) FROM call_results WHERE status = 'agreed') AS agreed_calls,
    CASE WHEN (SELECT COUNT(*) FROM call_results) > 0 
         THEN ROUND((SELECT COUNT(*) FROM call_results WHERE status = 'agreed') * 100.0 / (SELECT COUNT(*) FROM call_results), 2)
         ELSE 0 END AS conversion_rate,
    (SELECT COUNT(*) FROM users WHERE is_active = TRUE) AS active_users;

-- =============================================
-- ДЕФОЛТНЫЕ ДАННЫЕ
-- =============================================

-- Настройки
INSERT INTO settings (key, value, description, category) VALUES 
    ('system_enabled', 'true', 'Global system enable/disable', 'system'),
    ('global_max_calls', '50', 'Maximum concurrent calls', 'dialer'),
    ('default_cps', '5', 'Default calls per second', 'dialer'),
    ('call_timeout', '30', 'Call timeout (seconds)', 'dialer'),
    ('max_retries', '3', 'Maximum retry attempts', 'dialer'),
    ('retry_busy_max', '2', 'Max retries for busy', 'dialer'),
    ('retry_busy_delay', '120', 'Delay for busy retry', 'dialer'),
    ('retry_noanswer_max', '3', 'Max retries for no answer', 'dialer'),
    ('retry_noanswer_delay', '300', 'Delay for no answer retry', 'dialer'),
    ('audio_retention_days', '30', 'Audio retention (days)', 'storage'),
    ('max_upload_size_mb', '10', 'Max upload size (MB)', 'storage'),
    ('versioning_enabled', '80', 'Enable versioning', 'system'),
    ('versioning_retention_days', '90', 'Version retention (days)', 'system'),
    ('session_timeout', '3600', 'Session timeout (seconds)', 'security'),
    ('rate_limit_enabled', 'true', 'Enable rate limiting', 'security'),
    ('rate_limit_requests', '100', 'Rate limit requests', 'security'),
    ('incoming_greeting', 'tts/incoming_welcome', 'Greeting audio for incoming calls', 'incoming')
ON CONFLICT (key) DO NOTHING;

-- Администратор (admin/admin)
INSERT INTO users (username, password_hash, email, full_name, role, force_password_change) VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIqK0hVdGW',
    'admin@localhost', 'System Administrator', 'admin', TRUE
) ON CONFLICT (username) DO NOTHING;

-- Группы контактов
INSERT INTO contact_groups (name, description, color) VALUES 
    ('Default', 'Default group', '#667eea'),
    ('VIP', 'VIP contacts', '#f59e0b'),
    ('Blocked', 'Blocked contacts', '#ef4444')
ON CONFLICT (name) DO NOTHING;

-- События webhook
INSERT INTO webhook_events (name, description, category) VALUES 
    ('call.started', 'Call started', 'call'),
    ('call.answered', 'Call answered', 'call'),
    ('call.completed', 'Call completed', 'call'),
    ('campaign.started', 'Campaign started', 'campaign'),
    ('campaign.completed', 'Campaign completed', 'campaign'),
    ('contact.created', 'Contact created', 'contact'),
    ('system.enabled', 'System enabled', 'system'),
    ('system.disabled', 'System disabled', 'system')
ON CONFLICT (name) DO NOTHING;

-- Запись миграции
INSERT INTO schema_migrations (version, name) VALUES ('001', 'Complete Schema') ON CONFLICT (version) DO NOTHING;

-- =============================================
-- КОММЕНТАРИИ
-- =============================================
COMMENT ON TABLE users IS 'Пользователи системы';
COMMENT ON TABLE sessions IS 'Активные сессии пользователей';
COMMENT ON TABLE campaigns IS 'Кампании обзвона';
COMMENT ON TABLE campaign_schedules IS 'Расписания запуска кампаний';
COMMENT ON TABLE contact_groups IS 'Группы контактов';
COMMENT ON TABLE contacts IS 'Контакты (телефонные номера)';
COMMENT ON TABLE contact_import_jobs IS 'Задачи импорта контактов';
COMMENT ON TABLE campaign_contacts IS 'Связь кампаний и контактов';
COMMENT ON TABLE call_results IS 'Результаты звонков';
COMMENT ON TABLE call_recordings IS 'Записи разговоров';
COMMENT ON TABLE settings IS 'Настройки системы';
COMMENT ON TABLE audio_files IS 'Аудиофайлы';
COMMENT ON TABLE tts_jobs IS 'Задачи генерации TTS';
COMMENT ON TABLE audit_log IS 'Журнал аудита';
COMMENT ON TABLE blacklist IS 'Чёрный список';
COMMENT ON TABLE api_tokens IS 'API токены';
COMMENT ON TABLE webhook_events IS 'Типы событий webhook';
COMMENT ON TABLE webhook_subscriptions IS 'Webhook подписки';
COMMENT ON TABLE webhook_deliveries IS 'История доставки webhook';
COMMENT ON TABLE record_versions IS 'Версионирование записей';
COMMENT ON TABLE notifications IS 'Уведомления пользователей';
COMMENT ON TABLE system_events IS 'Системные события';
COMMENT ON TABLE incoming_calls IS 'Входящие звонки с записью и транскрибацией';
COMMENT ON TABLE schema_migrations IS 'История миграций';
