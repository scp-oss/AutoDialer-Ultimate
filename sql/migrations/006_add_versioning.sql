-- =============================================
-- AutoDialer Ultimate - Migration 006: Record Versioning
-- Версия: 006
-- =============================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '006') THEN
        RAISE NOTICE 'Migration 006 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- Таблица версионирования записей
-- =============================================
CREATE TABLE record_versions (
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
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_entity ON record_versions(entity_type, entity_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_created_at ON record_versions(created_at);

-- =============================================
-- Функция создания версии при обновлении
-- =============================================
CREATE OR REPLACE FUNCTION create_record_version()
RETURNS TRIGGER AS $$
DECLARE
    current_version INTEGER;
    audit_user_id INTEGER;
BEGIN
    -- Получаем текущую версию
    SELECT COALESCE(MAX(version), 0) INTO current_version
    FROM record_versions
    WHERE entity_type = TG_TABLE_NAME AND entity_id = NEW.id;
    
    -- Получаем user_id из контекста
    BEGIN
        audit_user_id := current_setting('app.user_id', true)::INTEGER;
    EXCEPTION WHEN OTHERS THEN
        audit_user_id := NULL;
    END;
    
    -- Создаем новую версию
    INSERT INTO record_versions (entity_type, entity_id, version, data, created_by)
    VALUES (TG_TABLE_NAME, NEW.id, current_version + 1, to_jsonb(NEW), audit_user_id);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- Триггеры версионирования для важных таблиц
-- =============================================
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
-- Настройки
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('versioning_enabled', 'true', 'Enable record versioning', 'system'),
    ('rate_limit_enabled', 'true', 'Enable rate limiting', 'security'),
    ('rate_limit_requests', '100', 'Rate limit requests per window', 'security'),
    ('rate_limit_window', '60', 'Rate limit window in seconds', '60'),
    ('login_rate_limit', '5', 'Login attempts before block', 'security'),
    ('login_rate_window', '300', 'Login rate window in seconds', 'security'),
    ('session_timeout', '3600', 'Session timeout in seconds', 'security')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('006', 'Record Versioning');

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DROP TRIGGER IF EXISTS version_campaigns ON campaigns;
DROP TRIGGER IF EXISTS version_contacts ON contacts;
DROP TRIGGER IF EXISTS version_settings ON settings;
DROP FUNCTION IF EXISTS create_record_version();
DROP TABLE IF EXISTS record_versions CASCADE;
*/
