-- =============================================
-- AutoDialer Ultimate - Migration 002: Additional Indexes
-- Версия: 002
-- =============================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '002') THEN
        RAISE NOTICE 'Migration 002 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- Индексы для users
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_created_at ON users(created_at);

-- =============================================
-- Индексы для campaigns
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_created_by ON campaigns(created_by);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_started_at ON campaigns(started_at);

-- =============================================
-- Индексы для contacts
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_group ON contacts(group_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_status ON contacts(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_blacklisted ON contacts(blacklisted);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_created_at ON contacts(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_last_call ON contacts(last_call_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_tags ON contacts USING gin(tags);

-- Уникальный индекс для активных телефонов
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_phone_active ON contacts(phone) WHERE NOT blacklisted;

-- =============================================
-- Индексы для contact_groups
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contact_groups_name ON contact_groups(name);

-- =============================================
-- Индексы для campaign_contacts
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_campaign ON campaign_contacts(campaign_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_contact ON campaign_contacts(contact_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_next_retry ON campaign_contacts(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_status ON campaign_contacts(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_priority ON campaign_contacts(priority DESC);

-- =============================================
-- Индексы для call_results
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_campaign ON call_results(campaign_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_contact ON call_results(contact_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_phone ON call_results(phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_status ON call_results(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_created ON call_results(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_linked_id ON call_results(linked_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_unique_id ON call_results(unique_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_campaign_status ON call_results(campaign_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_created_date ON call_results((created_at::DATE));

-- =============================================
-- Индексы для audio_files
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_campaign ON audio_files(campaign_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_created_by ON audio_files(created_by);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_is_public ON audio_files(is_public);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_created_at ON audio_files(created_at);

-- =============================================
-- Индексы для audit_log
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_username ON audit_log(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);

-- =============================================
-- Индексы для blacklist
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blacklist_phone ON blacklist(phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blacklist_created_at ON blacklist(created_at);

-- =============================================
-- Индексы для api_tokens
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_expires ON api_tokens(expires_at);

-- =============================================
-- Индексы для settings
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_settings_category ON settings(category);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_settings_is_public ON settings(is_public);

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('002', 'Additional Indexes');

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DROP INDEX CONCURRENTLY IF EXISTS idx_users_username;
DROP INDEX CONCURRENTLY IF EXISTS idx_users_role;
-- ... (остальные индексы)
*/
