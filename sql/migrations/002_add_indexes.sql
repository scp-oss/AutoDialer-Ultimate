-- =============================================
-- AutoDialer Ultimate - Migration 002: Additional Indexes
-- Версия: 002
-- =============================================
-- Добавляет все индексы для производительности
-- Использует CREATE INDEX CONCURRENTLY для избежания блокировок
-- =============================================

-- =============================================
-- Проверка, не применена ли уже миграция
-- =============================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '002') THEN
        RAISE NOTICE 'Migration 002 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- Настройка для CONCURRENTLY (требуется вне транзакции)
-- =============================================
SET statement_timeout = '300s';
SET lock_timeout = '60s';

-- =============================================
-- Индексы для users
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_created_at ON users(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_last_login ON users(last_login) WHERE last_login IS NOT NULL;

-- Составной индекс для поиска активных пользователей по роли
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_role_active ON users(role, is_active) WHERE is_active = TRUE;

-- =============================================
-- Индексы для campaigns
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_created_by ON campaigns(created_by);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_started_at ON campaigns(started_at) WHERE started_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_completed_at ON campaigns(completed_at) WHERE completed_at IS NOT NULL;

-- Составной индекс для активных кампаний
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_status_running ON campaigns(status) WHERE status IN ('running', 'paused');

-- Индекс для поиска по имени (trigram для нечёткого поиска, требует pg_trgm)
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_name_trgm ON campaigns USING gin(name gin_trgm_ops);

-- =============================================
-- Индексы для contacts
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_group ON contacts(group_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_status ON contacts(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_blacklisted ON contacts(blacklisted) WHERE blacklisted = TRUE;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_created_at ON contacts(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_last_call ON contacts(last_call_at) WHERE last_call_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_total_calls ON contacts(total_calls) WHERE total_calls > 0;

-- GIN индекс для тегов
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_tags ON contacts USING gin(tags);

-- GIN индекс для custom_fields (JSONB)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_custom_fields ON contacts USING gin(custom_fields);

-- Уникальный индекс для активных телефонов (только не заблокированные)
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_phone_active ON contacts(phone) WHERE NOT blacklisted;

-- Составной индекс для поиска по группе и статусу
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_group_status ON contacts(group_id, status) WHERE group_id IS NOT NULL;

-- =============================================
-- Индексы для contact_groups
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contact_groups_name ON contact_groups(name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contact_groups_created_by ON contact_groups(created_by);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contact_groups_created_at ON contact_groups(created_at);

-- =============================================
-- Индексы для campaign_contacts
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_campaign ON campaign_contacts(campaign_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_contact ON campaign_contacts(contact_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_next_retry ON campaign_contacts(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_status ON campaign_contacts(status) WHERE status IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_priority ON campaign_contacts(priority DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_last_call ON campaign_contacts(last_call_at) WHERE last_call_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_retry_count ON campaign_contacts(retry_count) WHERE retry_count > 0;

-- Составной индекс для очереди дозвона
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_contacts_queue ON campaign_contacts(campaign_id, next_retry_at, priority DESC, retry_count ASC) 
    WHERE next_retry_at IS NOT NULL;

-- =============================================
-- Индексы для call_results
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_campaign ON call_results(campaign_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_contact ON call_results(contact_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_phone ON call_results(phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_status ON call_results(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_created ON call_results(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_linked_id ON call_results(linked_id) WHERE linked_id IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_unique_id ON call_results(unique_id) WHERE unique_id IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_duration ON call_results(duration) WHERE duration > 0;

-- Составные индексы
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_campaign_status ON call_results(campaign_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_campaign_created ON call_results(campaign_id, created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_contact_status ON call_results(contact_id, status);

-- Индекс по дате (для daily_stats)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_created_date ON call_results((created_at::DATE));

-- Индекс для успешных звонков
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_agreed ON call_results(campaign_id) WHERE status = 'agreed';

-- GIN индекс для metadata
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_results_metadata ON call_results USING gin(metadata);

-- =============================================
-- Индексы для audio_files
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_campaign ON audio_files(campaign_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_created_by ON audio_files(created_by);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_is_public ON audio_files(is_public) WHERE is_public = TRUE;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_created_at ON audio_files(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_format ON audio_files(format);

-- Составной индекс для публичных аудио
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_public_created ON audio_files(is_public, created_at) WHERE is_public = TRUE;

-- =============================================
-- Индексы для audit_log
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_user ON audit_log(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_username ON audit_log(username) WHERE username IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id) WHERE entity_type IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_ip ON audit_log(ip_address) WHERE ip_address IS NOT NULL;

-- Составной индекс для поиска по пользователю и дате
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_user_created ON audit_log(user_id, created_at) WHERE user_id IS NOT NULL;

-- GIN индекс для details
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_details ON audit_log USING gin(details);

-- =============================================
-- Индексы для blacklist
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blacklist_phone ON blacklist(phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blacklist_created_at ON blacklist(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blacklist_created_by ON blacklist(created_by) WHERE created_by IS NOT NULL;

-- =============================================
-- Индексы для api_tokens
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_expires ON api_tokens(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_last_used ON api_tokens(last_used_at) WHERE last_used_at IS NOT NULL;

-- Составной индекс для активных токенов
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_tokens_active ON api_tokens(user_id) WHERE expires_at IS NULL OR expires_at > NOW();

-- =============================================
-- Индексы для settings
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_settings_category ON settings(category);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_settings_is_public ON settings(is_public) WHERE is_public = TRUE;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_settings_updated_at ON settings(updated_at) WHERE updated_at IS NOT NULL;

-- =============================================
-- Индексы для webhook_subscriptions
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_subscriptions_is_active ON webhook_subscriptions(is_active) WHERE is_active = TRUE;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_subscriptions_created_by ON webhook_subscriptions(created_by);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_subscriptions_created_at ON webhook_subscriptions(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_subscriptions_events ON webhook_subscriptions USING gin(events);

-- =============================================
-- Индексы для webhook_deliveries
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_event_type ON webhook_deliveries(event_type);

-- Составной индекс для поиска неудачных доставок
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_failed ON webhook_deliveries(subscription_id, status) 
    WHERE status IN ('failed', 'pending');

-- =============================================
-- Индексы для record_versions
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_entity ON record_versions(entity_type, entity_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_created_at ON record_versions(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_version ON record_versions(entity_type, entity_id, version DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_created_by ON record_versions(created_by) WHERE created_by IS NOT NULL;

-- GIN индекс для data
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_data ON record_versions USING gin(data);

-- =============================================
-- Индексы для schema_migrations
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_schema_migrations_applied_at ON schema_migrations(applied_at);

-- =============================================
-- Дополнительные настройки для полнотекстового поиска (опционально)
-- =============================================
-- Требует расширения pg_trgm
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_name_trgm ON contacts USING gin(name gin_trgm_ops);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaigns_name_trgm ON campaigns USING gin(name gin_trgm_ops);

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('002', 'Additional Indexes');

-- =============================================
-- Вывод статистики
-- =============================================
DO $$
DECLARE
    index_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO index_count FROM pg_indexes WHERE schemaname = 'public';
    RAISE NOTICE 'Total indexes in public schema: %', index_count;
END $$;

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DO $$
BEGIN
    -- Users
    DROP INDEX CONCURRENTLY IF EXISTS idx_users_role_active;
    DROP INDEX CONCURRENTLY IF EXISTS idx_users_last_login;
    DROP INDEX CONCURRENTLY IF EXISTS idx_users_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_users_is_active;
    DROP INDEX CONCURRENTLY IF EXISTS idx_users_role;
    DROP INDEX CONCURRENTLY IF EXISTS idx_users_username;
    
    -- Campaigns
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaigns_status_running;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaigns_completed_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaigns_started_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaigns_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaigns_created_by;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaigns_status;
    
    -- Contacts
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_group_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_custom_fields;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_tags;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_total_calls;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_last_call;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_blacklisted;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_group;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_phone;
    
    -- Уникальный индекс (удаляется отдельно, может потребоваться CASCADE)
    -- DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_phone_active;
    
    -- Contact groups
    DROP INDEX CONCURRENTLY IF EXISTS idx_contact_groups_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contact_groups_created_by;
    DROP INDEX CONCURRENTLY IF EXISTS idx_contact_groups_name;
    
    -- Campaign contacts
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_queue;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_retry_count;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_last_call;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_priority;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_next_retry;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_contact;
    DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_contacts_campaign;
    
    -- Call results
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_metadata;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_agreed;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_created_date;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_contact_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_campaign_created;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_campaign_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_duration;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_unique_id;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_linked_id;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_created;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_phone;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_contact;
    DROP INDEX CONCURRENTLY IF EXISTS idx_call_results_campaign;
    
    -- Audio files
    DROP INDEX CONCURRENTLY IF EXISTS idx_audio_files_public_created;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audio_files_format;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audio_files_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audio_files_is_public;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audio_files_created_by;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audio_files_campaign;
    
    -- Audit log
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_details;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_user_created;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_ip;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_created;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_entity;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_action;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_username;
    DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_user;
    
    -- Blacklist
    DROP INDEX CONCURRENTLY IF EXISTS idx_blacklist_created_by;
    DROP INDEX CONCURRENTLY IF EXISTS idx_blacklist_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_blacklist_phone;
    
    -- API tokens
    DROP INDEX CONCURRENTLY IF EXISTS idx_api_tokens_active;
    DROP INDEX CONCURRENTLY IF EXISTS idx_api_tokens_last_used;
    DROP INDEX CONCURRENTLY IF EXISTS idx_api_tokens_expires;
    DROP INDEX CONCURRENTLY IF EXISTS idx_api_tokens_user;
    DROP INDEX CONCURRENTLY IF EXISTS idx_api_tokens_token;
    
    -- Settings
    DROP INDEX CONCURRENTLY IF EXISTS idx_settings_updated_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_settings_is_public;
    DROP INDEX CONCURRENTLY IF EXISTS idx_settings_category;
    
    -- Webhooks
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_deliveries_failed;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_deliveries_event_type;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_deliveries_created;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_deliveries_status;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_deliveries_subscription;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_subscriptions_events;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_subscriptions_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_subscriptions_created_by;
    DROP INDEX CONCURRENTLY IF EXISTS idx_webhook_subscriptions_is_active;
    
    -- Record versions
    DROP INDEX CONCURRENTLY IF EXISTS idx_record_versions_data;
    DROP INDEX CONCURRENTLY IF EXISTS idx_record_versions_created_by;
    DROP INDEX CONCURRENTLY IF EXISTS idx_record_versions_version;
    DROP INDEX CONCURRENTLY IF EXISTS idx_record_versions_created_at;
    DROP INDEX CONCURRENTLY IF EXISTS idx_record_versions_entity;
    
    -- Schema migrations
    DROP INDEX CONCURRENTLY IF EXISTS idx_schema_migrations_applied_at;
    
    DELETE FROM schema_migrations WHERE version = '002';
END $$;
*/
