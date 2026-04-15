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
        audit_user_id := current_setting('app.user_id', true)::INTEGER
