-- =============================================
-- AutoDialer Ultimate - Migration 006: Record Versioning
-- Версия: 006
-- =============================================
-- Добавляет систему версионирования записей:
-- - Таблица record_versions для хранения истории изменений
-- - Триггеры для автоматического создания версий
-- - Функции для работы с версиями
-- - Представления для просмотра истории
-- =============================================

-- =============================================
-- Проверка, не применена ли уже миграция
-- =============================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '006') THEN
        RAISE NOTICE 'Migration 006 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- ТАБЛИЦА ВЕРСИОНИРОВАНИЯ
-- =============================================

-- -----------------------------------------------------------------
-- Таблица: record_versions
-- Хранит историю изменений записей
-- -----------------------------------------------------------------
CREATE TABLE record_versions (
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

COMMENT ON TABLE record_versions IS 'История версий записей (versioning)';
COMMENT ON COLUMN record_versions.entity_type IS 'Тип сущности (название таблицы)';
COMMENT ON COLUMN record_versions.entity_id IS 'ID записи в исходной таблице';
COMMENT ON COLUMN record_versions.version IS 'Номер версии (начинается с 1)';
COMMENT ON COLUMN record_versions.data IS 'Полные данные записи на момент версии (JSONB)';
COMMENT ON COLUMN record_versions.changed_fields IS 'Список изменённых полей';
COMMENT ON COLUMN record_versions.change_summary IS 'Краткое описание изменений';
COMMENT ON COLUMN record_versions.reverted_from_version IS 'ID версии, к которой сделан откат';

-- =============================================
-- ИНДЕКСЫ
-- =============================================

-- Основные индексы для быстрого поиска
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_entity ON record_versions(entity_type, entity_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_entity_type ON record_versions(entity_type);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_entity_id ON record_versions(entity_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_version ON record_versions(entity_type, entity_id, version DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_created_at ON record_versions(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_created_by ON record_versions(created_by) WHERE created_by IS NOT NULL;

-- GIN индекс для полнотекстового поиска по данным
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_data ON record_versions USING gin(data);

-- GIN индекс для поиска по изменённым полям
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_changed_fields ON record_versions USING gin(changed_fields);

-- Индекс для поиска откатов
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_reverted ON record_versions(reverted_from_version) WHERE reverted_from_version IS NOT NULL;

-- Составной индекс для пагинации истории
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_record_versions_history ON record_versions(entity_type, entity_id, version DESC, created_at DESC);

-- =============================================
-- ФУНКЦИИ
-- =============================================

-- -----------------------------------------------------------------
-- Функция: compare_jsonb_changes
-- Сравнивает две JSONB записи и возвращает список изменённых полей
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION compare_jsonb_changes(old_data JSONB, new_data JSONB)
RETURNS TEXT[] AS $$
DECLARE
    changed TEXT[];
    key TEXT;
    old_value JSONB;
    new_value JSONB;
BEGIN
    changed := ARRAY[]::TEXT[];
    
    -- Проверяем все ключи из новых данных
    FOR key IN SELECT jsonb_object_keys(new_data) LOOP
        old_value := old_data -> key;
        new_value := new_data -> key;
        
        IF old_value IS NULL OR old_value != new_value THEN
            changed := array_append(changed, key);
        END IF;
    END LOOP;
    
    -- Проверяем ключи, которые были удалены
    FOR key IN SELECT jsonb_object_keys(old_data) LOOP
        IF NOT new_data ? key THEN
            changed := array_append(changed, '~' || key);  -- Префикс ~ означает удаление
        END IF;
    END LOOP;
    
    RETURN changed;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION compare_jsonb_changes(JSONB, JSONB) IS 'Сравнение двух JSONB и возврат списка изменённых полей';

-- -----------------------------------------------------------------
-- Функция: generate_change_summary
-- Генерирует краткое описание изменений
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION generate_change_summary(old_data JSONB, new_data JSONB, changed_fields TEXT[])
RETURNS TEXT AS $$
DECLARE
    summary TEXT := '';
    field TEXT;
    old_val TEXT;
    new_val TEXT;
    field_name TEXT;
    is_deleted BOOLEAN;
BEGIN
    IF changed_fields IS NULL OR array_length(changed_fields, 1) IS NULL THEN
        RETURN 'No changes detected';
    END IF;
    
    FOREACH field IN ARRAY changed_fields LOOP
        is_deleted := field LIKE '~%';
        field_name := CASE WHEN is_deleted THEN substring(field from 2) ELSE field END;
        
        old_val := old_data ->> field_name;
        new_val := new_data ->> field_name;
        
        IF is_deleted THEN
            summary := summary || format('Deleted "%s" (was: %s); ', field_name, COALESCE(old_val, 'NULL'));
        ELSIF old_val IS NULL THEN
            summary := summary || format('Added "%s" = %s; ', field_name, COALESCE(new_val, 'NULL'));
        ELSE
            summary := summary || format('Changed "%s": %s → %s; ', field_name, 
                                         COALESCE(old_val, 'NULL'), COALESCE(new_val, 'NULL'));
        END IF;
    END LOOP;
    
    RETURN summary;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION generate_change_summary(JSONB, JSONB, TEXT[]) IS 'Генерация читаемого описания изменений';

-- -----------------------------------------------------------------
-- Функция: create_record_version
-- Создаёт новую версию записи (используется в триггерах)
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION create_record_version()
RETURNS TRIGGER AS $$
DECLARE
    current_version INTEGER;
    audit_user_id INTEGER;
    audit_username VARCHAR(50);
    audit_ip INET;
    audit_agent TEXT;
    changed_fields TEXT[];
    old_data_json JSONB;
    new_data_json JSONB;
    version_id BIGINT;
BEGIN
    -- Получаем текущую максимальную версию
    SELECT COALESCE(MAX(version), 0) INTO current_version
    FROM record_versions
    WHERE entity_type = TG_TABLE_NAME AND entity_id = NEW.id;
    
    -- Получаем контекст пользователя
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
    
    BEGIN
        audit_ip := current_setting('app.ip_address', true)::INET;
    EXCEPTION WHEN OTHERS THEN
        audit_ip := NULL;
    END;
    
    BEGIN
        audit_agent := current_setting('app.user_agent', true);
    EXCEPTION WHEN OTHERS THEN
        audit_agent := NULL;
    END;
    
    -- Преобразуем данные в JSONB
    IF TG_OP = 'UPDATE' THEN
        old_data_json := to_jsonb(OLD);
        new_data_json := to_jsonb(NEW);
        changed_fields := compare_jsonb_changes(old_data_json, new_data_json);
    ELSE
        new_data_json := to_jsonb(NEW);
        changed_fields := ARRAY[]::TEXT[];
    END IF;
    
    -- Создаём новую версию
    INSERT INTO record_versions (
        entity_type, entity_id, version, data, 
        changed_fields, change_summary,
        created_by, created_by_username, created_by_ip, created_by_agent,
        metadata
    ) VALUES (
        TG_TABLE_NAME, NEW.id, current_version + 1, new_data_json,
        changed_fields,
        CASE 
            WHEN TG_OP = 'UPDATE' THEN generate_change_summary(old_data_json, new_data_json, changed_fields)
            WHEN TG_OP = 'INSERT' THEN 'Record created'
            ELSE NULL
        END,
        audit_user_id, audit_username, audit_ip, audit_agent,
        jsonb_build_object('operation', TG_OP)
    ) RETURNING id INTO version_id;
    
    RAISE DEBUG 'Created version % for %.% (v%)', version_id, TG_TABLE_NAME, NEW.id, current_version + 1;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_record_version() IS 'Автоматическое создание версии записи при изменении';

-- -----------------------------------------------------------------
-- Функция: get_entity_version
-- Получает определённую версию записи
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_entity_version(
    p_entity_type TEXT,
    p_entity_id INTEGER,
    p_version INTEGER DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    IF p_version IS NULL THEN
        -- Возвращаем последнюю версию
        SELECT data INTO result
        FROM record_versions
        WHERE entity_type = p_entity_type AND entity_id = p_entity_id
        ORDER BY version DESC
        LIMIT 1;
    ELSE
        -- Возвращаем указанную версию
        SELECT data INTO result
        FROM record_versions
        WHERE entity_type = p_entity_type AND entity_id = p_entity_id AND version = p_version;
    END IF;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_entity_version(TEXT, INTEGER, INTEGER) IS 'Получение данных записи на определённую версию';

-- -----------------------------------------------------------------
-- Функция: get_entity_history
-- Возвращает историю изменений записи
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_entity_history(
    p_entity_type TEXT,
    p_entity_id INTEGER,
    p_limit INTEGER DEFAULT 50
) RETURNS TABLE (
    version INTEGER,
    data JSONB,
    changed_fields TEXT[],
    change_summary TEXT,
    created_by INTEGER,
    created_by_username VARCHAR,
    created_by_ip INET,
    created_at TIMESTAMP,
    reverted_from_version INTEGER,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        rv.version,
        rv.data,
        rv.changed_fields,
        rv.change_summary,
        rv.created_by,
        rv.created_by_username,
        rv.created_by_ip,
        rv.created_at,
        rv.reverted_from_version,
        rv.metadata
    FROM record_versions rv
    WHERE rv.entity_type = p_entity_type AND rv.entity_id = p_entity_id
    ORDER BY rv.version DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_entity_history(TEXT, INTEGER, INTEGER) IS 'Получение истории изменений записи';

-- -----------------------------------------------------------------
-- Функция: revert_to_version
-- Откатывает запись к указанной версии
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION revert_to_version(
    p_entity_type TEXT,
    p_entity_id INTEGER,
    p_target_version INTEGER,
    p_user_id INTEGER DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    target_data JSONB;
    current_version INTEGER;
    table_name TEXT;
    column_name TEXT;
    column_value TEXT;
    update_query TEXT;
    columns_to_update TEXT[];
    json_key TEXT;
    json_value JSONB;
    reverted BOOLEAN := FALSE;
BEGIN
    -- Проверяем существование версии
    SELECT data INTO target_data
    FROM record_versions
    WHERE entity_type = p_entity_type AND entity_id = p_entity_id AND version = p_target_version;
    
    IF target_data IS NULL THEN
        RAISE EXCEPTION 'Version % not found for %.%', p_target_version, p_entity_type, p_entity_id;
    END IF;
    
    -- Получаем текущую максимальную версию
    SELECT COALESCE(MAX(version), 0) INTO current_version
    FROM record_versions
    WHERE entity_type = p_entity_type AND entity_id = p_entity_id;
    
    table_name := quote_ident(p_entity_type);
    columns_to_update := ARRAY[]::TEXT[];
    
    -- Формируем список полей для обновления (исключаем системные)
    FOR json_key IN SELECT jsonb_object_keys(target_data) LOOP
        IF json_key NOT IN ('created_at', 'updated_at', 'created_by', 'version') THEN
            columns_to_update := array_append(columns_to_update, json_key);
        END IF;
    END LOOP;
    
    -- Устанавливаем контекст пользователя
    IF p_user_id IS NOT NULL THEN
        PERFORM set_config('app.user_id', p_user_id::TEXT, TRUE);
    END IF;
    PERFORM set_config('app.revert_version', p_target_version::TEXT, TRUE);
    
    -- Строим и выполняем UPDATE
    update_query := format('UPDATE %s SET ', table_name);
    
    FOR i IN 1..array_length(columns_to_update, 1) LOOP
        json_key := columns_to_update[i];
        json_value := target_data -> json_key;
        
        IF i > 1 THEN
            update_query := update_query || ', ';
        END IF;
        
        IF json_value IS NULL OR json_value = 'null'::JSONB THEN
            update_query := update_query || format('%I = NULL', json_key);
        ELSIF jsonb_typeof(json_value) = 'string' THEN
            update_query := update_query || format('%I = %L', json_key, json_value #>> '{}');
        ELSIF jsonb_typeof(json_value) IN ('number', 'boolean') THEN
            update_query := update_query || format('%I = %s', json_key, json_value #>> '{}');
        ELSE
            update_query := update_query || format('%I = %L::JSONB', json_key, json_value::TEXT);
        END IF;
    END LOOP;
    
    update_query := update_query || format(' WHERE id = %s', p_entity_id);
    
    EXECUTE update_query;
    GET DIAGNOSTICS reverted = ROW_COUNT;
    
    -- Сбрасываем контекст
    PERFORM set_config('app.revert_version', NULL, TRUE);
    
    RETURN reverted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION revert_to_version(TEXT, INTEGER, INTEGER, INTEGER) IS 'Откат записи к указанной версии';

-- -----------------------------------------------------------------
-- Функция: compare_versions
-- Сравнивает две версии записи
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION compare_versions(
    p_entity_type TEXT,
    p_entity_id INTEGER,
    p_version1 INTEGER,
    p_version2 INTEGER
) RETURNS JSONB AS $$
DECLARE
    data1 JSONB;
    data2 JSONB;
    diff JSONB;
BEGIN
    SELECT data INTO data1 FROM record_versions 
    WHERE entity_type = p_entity_type AND entity_id = p_entity_id AND version = p_version1;
    
    SELECT data INTO data2 FROM record_versions 
    WHERE entity_type = p_entity_type AND entity_id = p_entity_id AND version = p_version2;
    
    IF data1 IS NULL OR data2 IS NULL THEN
        RAISE EXCEPTION 'One or both versions not found';
    END IF;
    
    SELECT jsonb_object_agg(
        key,
        jsonb_build_object(
            'old', data1 -> key,
            'new', data2 -> key
        )
    ) INTO diff
    FROM jsonb_object_keys(data1 || data2) AS key
    WHERE data1 -> key IS DISTINCT FROM data2 -> key;
    
    RETURN jsonb_build_object(
        'version1', p_version1,
        'version2', p_version2,
        'differences', COALESCE(diff, '{}'::JSONB)
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION compare_versions(TEXT, INTEGER, INTEGER, INTEGER) IS 'Сравнение двух версий записи';

-- -----------------------------------------------------------------
-- Функция: cleanup_old_record_versions
-- Очистка старых версий записей
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION cleanup_old_record_versions(
    p_days INTEGER DEFAULT 90,
    p_keep_min_versions INTEGER DEFAULT 5
) RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    batch_deleted INTEGER;
BEGIN
    -- Удаляем версии старше указанного количества дней, 
    -- но сохраняем минимум p_keep_min_versions последних версий для каждой записи
    LOOP
        WITH to_delete AS (
            SELECT rv.id
            FROM record_versions rv
            WHERE rv.created_at < CURRENT_TIMESTAMP - (p_days || ' days')::INTERVAL
              AND rv.version <= (
                  SELECT MAX(rv2.version) - p_keep_min_versions
                  FROM record_versions rv2
                  WHERE rv2.entity_type = rv.entity_type AND rv2.entity_id = rv.entity_id
              )
            LIMIT 1000
        )
        DELETE FROM record_versions
        WHERE id IN (SELECT id FROM to_delete);
        
        GET DIAGNOSTICS batch_deleted = ROW_COUNT;
        deleted_count := deleted_count + batch_deleted;
        
        EXIT WHEN batch_deleted = 0;
    END LOOP;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_record_versions(INTEGER, INTEGER) IS 'Очистка старых версий записей с сохранением последних N версий';

-- =============================================
-- ТРИГГЕРЫ ВЕРСИОНИРОВАНИЯ
-- =============================================

-- -----------------------------------------------------------------
-- campaigns
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_campaigns') THEN
        CREATE TRIGGER version_campaigns
            AFTER INSERT OR UPDATE ON campaigns
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- contacts
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_contacts') THEN
        CREATE TRIGGER version_contacts
            AFTER INSERT OR UPDATE ON contacts
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- settings
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_settings') THEN
        CREATE TRIGGER version_settings
            AFTER INSERT OR UPDATE ON settings
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- users
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_users') THEN
        CREATE TRIGGER version_users
            AFTER INSERT OR UPDATE ON users
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- audio_files
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_audio_files') THEN
        CREATE TRIGGER version_audio_files
            AFTER INSERT OR UPDATE ON audio_files
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- -----------------------------------------------------------------
-- webhook_subscriptions
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'version_webhook_subscriptions') THEN
        CREATE TRIGGER version_webhook_subscriptions
            AFTER INSERT OR UPDATE ON webhook_subscriptions
            FOR EACH ROW
            EXECUTE FUNCTION create_record_version();
    END IF;
END $$;

-- =============================================
-- ПРЕДСТАВЛЕНИЯ
-- =============================================

-- -----------------------------------------------------------------
-- Представление: entity_history_summary
-- Сводка по истории изменений
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW entity_history_summary AS
SELECT 
    entity_type,
    entity_id,
    COUNT(*) AS total_versions,
    MAX(version) AS current_version,
    MIN(created_at) AS first_version_at,
    MAX(created_at) AS last_version_at,
    MAX(created_by_username) AS last_modified_by,
    array_agg(DISTINCT created_by_username) FILTER (WHERE created_by_username IS NOT NULL) AS all_modifiers
FROM record_versions
GROUP BY entity_type, entity_id;

COMMENT ON VIEW entity_history_summary IS 'Сводка по истории изменений всех записей';

-- -----------------------------------------------------------------
-- Представление: recent_changes
-- Последние изменения в системе
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW recent_changes AS
SELECT 
    rv.id,
    rv.entity_type,
    rv.entity_id,
    rv.version,
    rv.change_summary,
    rv.created_by_username AS changed_by,
    rv.created_by_ip,
    rv.created_at,
    CASE 
        WHEN rv.entity_type = 'campaigns' THEN (rv.data ->> 'name')
        WHEN rv.entity_type = 'contacts' THEN (rv.data ->> 'phone')
        WHEN rv.entity_type = 'users' THEN (rv.data ->> 'username')
        WHEN rv.entity_type = 'settings' THEN rv.entity_id::TEXT
        ELSE NULL
    END AS entity_display
FROM record_versions rv
WHERE rv.created_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
ORDER BY rv.created_at DESC
LIMIT 100;

COMMENT ON VIEW recent_changes IS 'Последние изменения в системе за 7 дней';

-- =============================================
-- НАСТРОЙКИ
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('versioning_enabled', 'true', 'Enable record versioning', 'system'),
    ('versioning_retention_days', '90', 'Record versions retention period (days)', 'system'),
    ('versioning_keep_min_versions', '5', 'Minimum versions to keep per record', 'system'),
    ('versioning_tracked_tables', 'campaigns,contacts,settings,users,audio_files,webhook_subscriptions', 'Tables with versioning enabled', 'system')
ON CONFLICT (key) DO UPDATE SET 
    value = EXCLUDED.value,
    description = EXCLUDED.description;

-- =============================================
-- ЗАПИСЬ О ПРИМЕНЕНИИ МИГРАЦИИ
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('006', 'Record Versioning');

-- =============================================
-- ВЫВОД СТАТИСТИКИ
-- =============================================
DO $$
DECLARE
    trigger_count INTEGER;
    function_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO trigger_count 
    FROM pg_trigger 
    WHERE tgname LIKE 'version_%';
    
    SELECT COUNT(*) INTO function_count
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public' 
      AND p.proname IN ('create_record_version', 'compare_jsonb_changes', 'generate_change_summary',
                        'get_entity_version', 'get_entity_history', 'revert_to_version',
                        'compare_versions', 'cleanup_old_record_versions');
    
    RAISE NOTICE 'Versioning triggers created: %', trigger_count;
    RAISE NOTICE 'Versioning functions created: %', function_count;
END $$;

-- =============================================
-- ОТКАТ (ROLLBACK)
-- =============================================
/*
DO $$
BEGIN
    -- Удаление представлений
    DROP VIEW IF EXISTS recent_changes;
    DROP VIEW IF EXISTS entity_history_summary;
    
    -- Удаление триггеров
    DROP TRIGGER IF EXISTS version_webhook_subscriptions ON webhook_subscriptions;
    DROP TRIGGER IF EXISTS version_audio_files ON audio_files;
    DROP TRIGGER IF EXISTS version_users ON users;
    DROP TRIGGER IF EXISTS version_settings ON settings;
    DROP TRIGGER IF EXISTS version_contacts ON contacts;
    DROP TRIGGER IF EXISTS version_campaigns ON campaigns;
    
    -- Удаление функций
    DROP FUNCTION IF EXISTS cleanup_old_record_versions(INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS compare_versions(TEXT, INTEGER, INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS revert_to_version(TEXT, INTEGER, INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS get_entity_history(TEXT, INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS get_entity_version(TEXT, INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS create_record_version();
    DROP FUNCTION IF EXISTS generate_change_summary(JSONB, JSONB, TEXT[]);
    DROP FUNCTION IF EXISTS compare_jsonb_changes(JSONB, JSONB);
    
    -- Удаление таблицы
    DROP TABLE IF EXISTS record_versions CASCADE;
    
    -- Удаление настроек
    DELETE FROM settings WHERE key LIKE 'versioning%';
    
    -- Удаление записи миграции
    DELETE FROM schema_migrations WHERE version = '006';
END $$;
*/
