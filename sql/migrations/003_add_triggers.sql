-- =============================================
-- AutoDialer Ultimate - Migration 003: Triggers and Functions
-- Версия: 003
-- =============================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '003') THEN
        RAISE NOTICE 'Migration 003 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- Функция обновления updated_at
-- =============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- Функция инкремента total_calls
-- =============================================
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

-- =============================================
-- Функция нормализации телефона
-- =============================================
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

-- =============================================
-- Функция аудита
-- =============================================
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

-- =============================================
-- Триггеры updated_at
-- =============================================
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

-- =============================================
-- Триггер инкремента звонков
-- =============================================
DROP TRIGGER IF EXISTS increment_contact_calls ON call_results;
CREATE TRIGGER increment_contact_calls
    AFTER INSERT ON call_results
    FOR EACH ROW
    EXECUTE FUNCTION increment_contact_total_calls();

-- =============================================
-- Триггер нормализации телефона
-- =============================================
DROP TRIGGER IF EXISTS normalize_contact_phone ON contacts;
CREATE TRIGGER normalize_contact_phone
    BEFORE INSERT OR UPDATE OF phone ON contacts
    FOR EACH ROW
    EXECUTE FUNCTION normalize_phone_number();

-- =============================================
-- Аудит триггеры (опционально, раскомментировать при необходимости)
-- =============================================
-- DROP TRIGGER IF EXISTS audit_users ON users;
-- CREATE TRIGGER audit_users
--     AFTER INSERT OR UPDATE OR DELETE ON users
--     FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

-- DROP TRIGGER IF EXISTS audit_campaigns ON campaigns;
-- CREATE TRIGGER audit_campaigns
--     AFTER INSERT OR UPDATE OR DELETE ON campaigns
--     FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

-- =============================================
-- Дополнительные настройки
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('call_timeout', '30', 'Call timeout in seconds', 'dialer'),
    ('max_retries', '3', 'Maximum retry attempts', 'dialer'),
    ('retry_busy_max', '2', 'Max retries for busy', 'dialer'),
    ('retry_busy_delay', '120', 'Delay for busy retry (seconds)', 'dialer'),
    ('retry_noanswer_max', '3', 'Max retries for no answer', 'dialer'),
    ('retry_noanswer_delay', '300', 'Delay for no answer retry', 'dialer'),
    ('retry_failed_max', '1', 'Max retries for failed', 'dialer'),
    ('retry_failed_delay', '60', 'Delay for failed retry (seconds)', 'dialer'),
    ('audio_retention_days', '30', 'Audio files retention period', 'storage'),
    ('max_upload_size_mb', '10', 'Maximum upload file size', 'storage')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('003', 'Triggers and Functions');

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
DROP TRIGGER IF EXISTS update_contacts_updated_at ON contacts;
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
DROP TRIGGER IF EXISTS increment_contact_calls ON call_results;
DROP TRIGGER IF EXISTS normalize_contact_phone ON contacts;
DROP FUNCTION IF EXISTS update_updated_at_column();
DROP FUNCTION IF EXISTS increment_contact_total_calls();
DROP FUNCTION IF EXISTS normalize_phone_number();
DROP FUNCTION IF EXISTS audit_trigger_function();
*/
