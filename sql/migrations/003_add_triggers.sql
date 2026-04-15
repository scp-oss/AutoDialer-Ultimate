-- =============================================
-- AutoDialer Ultimate - Migration 003: Triggers and Functions
-- Версия: 003
-- =============================================
-- Добавляет все триггеры и функции:
-- - updated_at триггеры
-- - нормализация телефона
-- - инкремент счётчика звонков
-- - аудит (опционально)
-- - версионирование записей
-- =============================================

-- =============================================
-- Проверка, не применена ли уже миграция
-- =============================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '003') THEN
        RAISE NOTICE 'Migration 003 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- ФУНКЦИИ
-- =============================================

-- -----------------------------------------------------------------
-- Функция обновления updated_at
-- Используется в триггерах для автоматического обновления timestamp
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_updated_at_column() IS 'Автоматическое обновление поля updated_at при изменении записи';

-- -----------------------------------------------------------------
-- Функция инкремента total_calls контакта
-- Увеличивает счётчик звонков при добавлении нового call_result
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION increment_contact_total_calls()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.contact_id IS NOT NULL THEN
        UPDATE contacts SET 
            total_calls = total_calls + 1,
            last_call_at = NEW.created_at
        WHERE id = NEW.contact_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION increment_contact_total_calls() IS 'Увеличивает счётчик звонков контакта при добавлении результата';

-- -----------------------------------------------------------------
-- Функция нормализации телефона
-- Приводит телефон к единому формату: 7XXXXXXXXXX
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION normalize_phone_number()
RETURNS TRIGGER AS $$
DECLARE
    cleaned TEXT;
BEGIN
    -- Удаляем все нецифровые символы
    cleaned := regexp_replace(NEW.phone, '[^0-9]', '', 'g');
    
    -- Нормализация российских номеров
    IF length(cleaned) = 11 AND cleaned LIKE '8%' THEN
        cleaned := '7' || substring(cleaned from 2);
    ELSIF length(cleaned) = 10 AND cleaned LIKE '9%' THEN
        cleaned := '7' || cleaned;
    ELSIF length(cleaned) = 11 AND cleaned LIKE '7%' THEN
        -- Уже в правильном формате
        cleaned := cleaned;
    ELSIF length(cleaned) >= 10 THEN
        -- Международный формат, оставляем как есть
        cleaned := cleaned;
    END IF;
    
    -- Проверяем, не заблокирован ли номер
    IF EXISTS (SELECT 1 FROM blacklist WHERE phone = cleaned) THEN
        NEW.blacklisted = TRUE;
        NEW.blacklist_reason = COALESCE(NEW.blacklist_reason, 'Auto-blocked by blacklist');
    END IF;
    
    NEW.phone := cleaned;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION normalize_phone_number() IS 'Нормализация номера телефона и проверка чёрного списка';

-- -----------------------------------------------------------------
-- Функция проверки чёрного списка при вставке/обновлении
-- -----------------------------------------------------------------
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

COMMENT ON FUNCTION check_blacklist() IS 'Проверка номера в чёрном списке при вставке/обновлении';

-- -----------------------------------------------------------------
-- Функция аудита
-- Логирует все изменения в таблицах
-- Требует установки переменных сессии: app.user_id, app.username
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION audit_trigger_function()
RETURNS TRIGGER AS $$
DECLARE
    audit_user_id INTEGER;
    audit_username VARCHAR(50);
    audit_ip INET;
    audit_agent TEXT;
BEGIN
    -- Получаем user_id из контекста сессии
    BEGIN
        audit_user_id := current_setting('app.user_id', true)::INTEGER;
    EXCEPTION WHEN OTHERS THEN
        audit_user_id := NULL;
    END;
    
    -- Получаем username из контекста сессии
    BEGIN
        audit_username := current_setting('app.username', true);
    EXCEPTION WHEN OTHERS THEN
        audit_username := NULL;
    END;
    
    -- Получаем IP из контекста сессии
    BEGIN
        audit_ip := current_setting('app.ip_address', true)::INET;
    EXCEPTION WHEN OTHERS THEN
        audit_ip := NULL;
    END;
    
    -- Получаем User-Agent из контекста сессии
    BEGIN
        audit_agent := current_setting('app.user_agent', true);
    EXCEPTION WHEN OTHERS THEN
        audit_agent := NULL;
    END;
    
    IF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, details, ip_address, user_agent)
        VALUES (audit_user_id, audit_username, 'DELETE', TG_TABLE_NAME, OLD.id, to_jsonb(OLD), audit_ip, audit_agent);
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, details, ip_address, user_agent)
        VALUES (audit_user_id, audit_username, 'UPDATE', TG_TABLE_NAME, NEW.id, 
                jsonb_build_object('old', to_jsonb(OLD), 'new', to_jsonb(NEW)), audit_ip, audit_agent);
        RETURN NEW;
    ELSIF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, details, ip_address, user_agent)
        VALUES (audit_user_id, audit_username, 'INSERT', TG_TABLE_NAME, NEW.id, to_jsonb(NEW), audit_ip, audit_agent);
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION audit_trigger_function() IS 'Логирование всех операций (INSERT/UPDATE/DELETE) в audit_log';

-- -----------------------------------------------------------------
-- Функция создания версии записи
-- Сохраняет копию записи при каждом обновлении
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION create_record_version()
RETURNS TRIGGER AS $$
DECLARE
    current_version INTEGER;
    audit_user_id INTEGER;
BEGIN
    -- Получаем текущую максимальную версию
    SELECT COALESCE(MAX(version), 0) INTO current_version
    FROM record_versions
    WHERE entity_type = TG_TABLE_NAME AND entity_id = NEW.id;
    
    -- Получаем user_id из контекста
    BEGIN
        audit_user_id := current_setting('app.user_id', true)::INTEGER;
    EXCEPTION WHEN OTHERS THEN
        audit_user_id := NULL;
    END;
    
    -- Создаём новую версию
    INSERT INTO record_versions (entity_type, entity_id, version, data, created_by)
    VALUES (TG_TABLE_NAME, NEW.id, current_version + 1, to_jsonb(NEW), audit_user_id);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_record_version() IS 'Создание версии записи при обновлении';

-- -----------------------------------------------------------------
-- Функция проверки статуса кампании при запуске
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION check_campaign_start()
RETURNS TRIGGER AS $$
BEGIN
    -- Проверяем, что кампания не запущена, если система отключена
    IF NEW.status = 'running' THEN
        IF EXISTS (SELECT 1 FROM settings WHERE key = 'system_enabled' AND value = 'false') THEN
            RAISE EXCEPTION 'Cannot start campaign: system is disabled';
        END IF;
        
        -- Устанавливаем время запуска
        NEW.started_at = COALESCE(NEW.started_at, CURRENT_TIMESTAMP);
    END IF;
    
    -- При завершении устанавливаем время
    IF NEW.status IN ('completed', 'stopped', 'failed') AND OLD.status = 'running' THEN
        NEW.completed_at = CURRENT_TIMESTAMP;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_campaign_start() IS 'Проверка возможности запуска кампании и установка временных меток';

-- -----------------------------------------------------------------
-- Функция очистки устаревших записей аудита
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION cleanup_old_audit_logs(days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM audit_log 
    WHERE created_at < CURRENT_TIMESTAMP - (days || ' days')::INTERVAL;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_audit_logs(INTEGER) IS 'Очистка устаревших записей аудита (по умолчанию 90 дней)';

-- -----------------------------------------------------------------
-- Функция очистки старых версий записей
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION cleanup_old_record_versions(days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM record_versions 
    WHERE created_at < CURRENT_TIMESTAMP - (days || ' days')::INTERVAL;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_record_versions(INTEGER) IS 'Очистка старых версий записей (по умолчанию 90 дней)';

-- =============================================
-- ТРИГГЕРЫ
-- =============================================

-- -----------------------------------------------------------------
-- updated_at триггеры
-- -----------------------------------------------------------------
DO $$
BEGIN
    -- campaigns
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_campaigns_updated_at') THEN
        CREATE TRIGGER update_campaigns_updated_at 
            BEFORE UPDATE ON campaigns 
            FOR EACH ROW 
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
    
    -- contacts
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_contacts_updated_at') THEN
        CREATE TRIGGER update_contacts_updated_at 
            BEFORE UPDATE ON contacts 
            FOR EACH ROW 
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
    
    -- users
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_users_updated_at') THEN
        CREATE TRIGGER update_users_updated_at 
            BEFORE UPDATE ON users 
            FOR EACH ROW 
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
    
    -- webhook_subscriptions
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_webhook_subscriptions_updated_at') THEN
        CREATE TRIGGER update_webhook_subscriptions_updated_at 
            BEFORE UPDATE ON webhook_subscriptions 
            FOR EACH ROW 
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- Триггер инкремента счётчика звонков
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'increment_contact_calls') THEN
        CREATE TRIGGER increment_contact_calls
            AFTER INSERT ON call_results
            FOR EACH ROW
            EXECUTE FUNCTION increment_contact_total_calls();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- Триггер нормализации телефона
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'normalize_contact_phone') THEN
        CREATE TRIGGER normalize_contact_phone
            BEFORE INSERT OR UPDATE OF phone ON contacts
            FOR EACH ROW
            EXECUTE FUNCTION normalize_phone_number();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- Триггер проверки чёрного списка
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'check_contact_blacklist') THEN
        CREATE TRIGGER check_contact_blacklist
            BEFORE INSERT OR UPDATE OF phone ON contacts
            FOR EACH ROW
            EXECUTE FUNCTION check_blacklist();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- Триггеры версионирования
-- -----------------------------------------------------------------
DO $$
BEGIN
    -- campaigns
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_campaigns') THEN
        CREATE TRIGGER version_campaigns
            AFTER UPDATE ON campaigns
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
    
    -- contacts
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_contacts') THEN
        CREATE TRIGGER version_contacts
            AFTER UPDATE ON contacts
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
    
    -- settings
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_settings') THEN
        CREATE TRIGGER version_settings
            AFTER UPDATE ON settings
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
    
    -- users
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_users') THEN
        CREATE TRIGGER version_users
            AFTER UPDATE ON users
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- Триггер проверки запуска кампании
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'check_campaign_start_trigger') THEN
        CREATE TRIGGER check_campaign_start_trigger
            BEFORE UPDATE OF status ON campaigns
            FOR EACH ROW
            WHEN (OLD.status IS DISTINCT FROM NEW.status)
            EXECUTE FUNCTION check_campaign_start();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- Аудит триггеры (опционально, раскомментировать при необходимости)
-- -----------------------------------------------------------------
/*
DO $$
BEGIN
    -- Аудит пользователей
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_users') THEN
        CREATE TRIGGER audit_users
            AFTER INSERT OR UPDATE OR DELETE ON users
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();
    END IF;
    
    -- Аудит кампаний
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_campaigns') THEN
        CREATE TRIGGER audit_campaigns
            AFTER INSERT OR UPDATE OR DELETE ON campaigns
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();
    END IF;
    
    -- Аудит контактов
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_contacts') THEN
        CREATE TRIGGER audit_contacts
            AFTER INSERT OR UPDATE OR DELETE ON contacts
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();
    END IF;
    
    -- Аудит настроек
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_settings') THEN
        CREATE TRIGGER audit_settings
            AFTER UPDATE ON settings
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();
    END IF;
    
    -- Аудит API токенов
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_api_tokens') THEN
        CREATE TRIGGER audit_api_tokens
            AFTER INSERT OR DELETE ON api_tokens
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();
    END IF;
END $$;
*/

-- =============================================
-- Дополнительные настройки
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('audit_enabled', 'false', 'Enable audit logging for all tables', 'audit'),
    ('audit_retention_days', '90', 'Audit log retention period (days)', 'audit'),
    ('versioning_enabled', 'true', 'Enable record versioning', 'system'),
    ('versioning_retention_days', '90', 'Record versions retention period (days)', 'system')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Создание расширения для cron-задач (pg_cron)
-- =============================================
-- CREATE EXTENSION IF NOT EXISTS pg_cron;

-- =============================================
-- Планирование очистки старых записей (требует pg_cron)
-- =============================================
/*
SELECT cron.schedule(
    'cleanup-audit-logs',
    '0 3 * * *',  -- Каждый день в 3:00
    $$SELECT cleanup_old_audit_logs(
        (SELECT value::INTEGER FROM settings WHERE key = 'audit_retention_days')
    )$$
);

SELECT cron.schedule(
    'cleanup-record-versions',
    '0 4 * * *',  -- Каждый день в 4:00
    $$SELECT cleanup_old_record_versions(
        (SELECT value::INTEGER FROM settings WHERE key = 'versioning_retention_days')
    )$$
);
*/

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('003', 'Triggers and Functions');

-- =============================================
-- Вывод статистики
-- =============================================
DO $$
DECLARE
    func_count INTEGER;
    trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO func_count 
    FROM pg_proc p 
    JOIN pg_namespace n ON p.pronamespace = n.oid 
    WHERE n.nspname = 'public' AND p.proname LIKE '%autodialer%' 
       OR p.proname IN ('update_updated_at_column', 'increment_contact_total_calls', 
                        'normalize_phone_number', 'check_blacklist', 'audit_trigger_function',
                        'create_record_version', 'check_campaign_start',
                        'cleanup_old_audit_logs', 'cleanup_old_record_versions');
    
    SELECT COUNT(*) INTO trigger_count FROM pg_trigger WHERE tgisinternal = false;
    
    RAISE NOTICE 'Functions created: %', func_count;
    RAISE NOTICE 'Triggers created: %', trigger_count;
END $$;

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DO $$
BEGIN
    -- Удаление триггеров
    DROP TRIGGER IF EXISTS check_campaign_start_trigger ON campaigns;
    DROP TRIGGER IF EXISTS version_users ON users;
    DROP TRIGGER IF EXISTS version_settings ON settings;
    DROP TRIGGER IF EXISTS version_contacts ON contacts;
    DROP TRIGGER IF EXISTS version_campaigns ON campaigns;
    DROP TRIGGER IF EXISTS check_contact_blacklist ON contacts;
    DROP TRIGGER IF EXISTS normalize_contact_phone ON contacts;
    DROP TRIGGER IF EXISTS increment_contact_calls ON call_results;
    DROP TRIGGER IF EXISTS update_webhook_subscriptions_updated_at ON webhook_subscriptions;
    DROP TRIGGER IF EXISTS update_users_updated_at ON users;
    DROP TRIGGER IF EXISTS update_contacts_updated_at ON contacts;
    DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
    
    -- Аудит триггеры (если были созданы)
    DROP TRIGGER IF EXISTS audit_api_tokens ON api_tokens;
    DROP TRIGGER IF EXISTS audit_settings ON settings;
    DROP TRIGGER IF EXISTS audit_contacts ON contacts;
    DROP TRIGGER IF EXISTS audit_campaigns ON campaigns;
    DROP TRIGGER IF EXISTS audit_users ON users;
    
    -- Удаление функций
    DROP FUNCTION IF EXISTS cleanup_old_record_versions(INTEGER);
    DROP FUNCTION IF EXISTS cleanup_old_audit_logs(INTEGER);
    DROP FUNCTION IF EXISTS check_campaign_start();
    DROP FUNCTION IF EXISTS create_record_version();
    DROP FUNCTION IF EXISTS audit_trigger_function();
    DROP FUNCTION IF EXISTS check_blacklist();
    DROP FUNCTION IF EXISTS normalize_phone_number();
    DROP FUNCTION IF EXISTS increment_contact_total_calls();
    DROP FUNCTION IF EXISTS update_updated_at_column();
    
    -- Удаление настроек
    DELETE FROM settings WHERE key IN ('audit_enabled', 'audit_retention_days', 'versioning_enabled', 'versioning_retention_days');
    
    -- Удаление записи миграции
    DELETE FROM schema_migrations WHERE version = '003';
END $$;
*/
