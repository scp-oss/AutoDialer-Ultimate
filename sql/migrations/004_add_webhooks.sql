-- =============================================
-- AutoDialer Ultimate - Migration 004: Webhook Tables
-- Версия: 004
-- =============================================
-- Добавляет таблицы для webhook-системы:
-- - webhook_subscriptions (подписки)
-- - webhook_deliveries (история доставки)
-- - webhook_events (типы событий)
-- =============================================

-- =============================================
-- Проверка, не применена ли уже миграция
-- =============================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '004') THEN
        RAISE NOTICE 'Migration 004 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- ТАБЛИЦЫ
-- =============================================

-- -----------------------------------------------------------------
-- Таблица: webhook_events (типы событий)
-- Справочник доступных событий webhook
-- -----------------------------------------------------------------
CREATE TABLE webhook_events (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(50) DEFAULT 'general',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE webhook_events IS 'Справочник типов событий webhook';
COMMENT ON COLUMN webhook_events.name IS 'Уникальное имя события (напр. call.started)';
COMMENT ON COLUMN webhook_events.category IS 'Категория: call, campaign, contact, system';

-- -----------------------------------------------------------------
-- Таблица: webhook_subscriptions (подписки)
-- Подписки на webhook-события
-- -----------------------------------------------------------------
CREATE TABLE webhook_subscriptions (
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

COMMENT ON TABLE webhook_subscriptions IS 'Подписки на webhook-события';
COMMENT ON COLUMN webhook_subscriptions.url IS 'URL для отправки webhook';
COMMENT ON COLUMN webhook_subscriptions.events IS 'Массив имён событий, на которые подписан webhook';
COMMENT ON COLUMN webhook_subscriptions.secret IS 'Секрет для подписи (HMAC-SHA256)';
COMMENT ON COLUMN webhook_subscriptions.headers IS 'Дополнительные HTTP-заголовки в формате JSON';
COMMENT ON COLUMN webhook_subscriptions.consecutive_failures IS 'Количество последовательных неудач (для автоматической деактивации)';

-- -----------------------------------------------------------------
-- Таблица: webhook_deliveries (история доставки)
-- Логирование всех попыток доставки webhook
-- -----------------------------------------------------------------
CREATE TABLE webhook_deliveries (
    id SERIAL PRIMARY KEY,
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

COMMENT ON TABLE webhook_deliveries IS 'История доставки webhook-событий';
COMMENT ON COLUMN webhook_deliveries.event_id IS 'Уникальный ID события (для идемпотентности)';
COMMENT ON COLUMN webhook_deliveries.payload IS 'Тело запроса в JSON';
COMMENT ON COLUMN webhook_deliveries.status IS 'Статус: pending, success, failed, retry, expired';

-- =============================================
-- ИНДЕКСЫ
-- =============================================

-- webhook_events
CREATE INDEX IF NOT EXISTS idx_webhook_events_name ON webhook_events(name);
CREATE INDEX IF NOT EXISTS idx_webhook_events_category ON webhook_events(category);
CREATE INDEX IF NOT EXISTS idx_webhook_events_is_active ON webhook_events(is_active);

-- webhook_subscriptions
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_is_active ON webhook_subscriptions(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_created_by ON webhook_subscriptions(created_by);
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_created_at ON webhook_subscriptions(created_at);
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_events ON webhook_subscriptions USING gin(events);
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_consecutive_failures ON webhook_subscriptions(consecutive_failures) WHERE consecutive_failures > 0;

-- Составной индекс для поиска активных подписок по событию
CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_active_event ON webhook_subscriptions(is_active) 
    WHERE is_active = TRUE AND array_length(events, 1) > 0;

-- webhook_deliveries
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_event_type ON webhook_deliveries(event_type);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_event_id ON webhook_deliveries(event_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at) WHERE next_retry_at IS NOT NULL;

-- Составной индекс для поиска неудачных доставок
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_failed ON webhook_deliveries(subscription_id, status) 
    WHERE status IN ('failed', 'pending', 'retry');

-- Составной индекс для поиска по подписке и статусу
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_sub_status ON webhook_deliveries(subscription_id, status);

-- =============================================
-- ДЕФОЛТНЫЕ ТИПЫ СОБЫТИЙ
-- =============================================
INSERT INTO webhook_events (name, description, category) VALUES 
    -- Call events
    ('call.started', 'Звонок начат (originate)', 'call'),
    ('call.answered', 'Абонент ответил', 'call'),
    ('call.completed', 'Звонок завершён', 'call'),
    ('call.failed', 'Звонок не удался', 'call'),
    ('call.busy', 'Абонент занят', 'call'),
    ('call.noanswer', 'Абонент не ответил', 'call'),
    ('call.dtmf', 'Получен DTMF-сигнал', 'call'),
    ('call.recording', 'Запись разговора готова', 'call'),
    
    -- Campaign events
    ('campaign.started', 'Кампания запущена', 'campaign'),
    ('campaign.paused', 'Кампания приостановлена', 'campaign'),
    ('campaign.resumed', 'Кампания возобновлена', 'campaign'),
    ('campaign.stopped', 'Кампания остановлена', 'campaign'),
    ('campaign.completed', 'Кампания завершена', 'campaign'),
    ('campaign.progress', 'Прогресс кампании обновлён', 'campaign'),
    
    -- Contact events
    ('contact.created', 'Контакт создан', 'contact'),
    ('contact.updated', 'Контакт обновлён', 'contact'),
    ('contact.deleted', 'Контакт удалён', 'contact'),
    ('contact.imported', 'Контакты импортированы', 'contact'),
    ('contact.blacklisted', 'Контакт добавлен в чёрный список', 'contact'),
    ('contact.unblacklisted', 'Контакт удалён из чёрного списка', 'contact'),
    
    -- System events
    ('system.enabled', 'Система включена', 'system'),
    ('system.disabled', 'Система выключена', 'system'),
    ('system.error', 'Системная ошибка', 'system'),
    ('system.warning', 'Системное предупреждение', 'system'),
    
    -- Audio events
    ('audio.generated', 'Аудиофайл сгенерирован (TTS)', 'audio'),
    ('audio.uploaded', 'Аудиофайл загружен', 'audio'),
    ('audio.deleted', 'Аудиофайл удалён', 'audio')
ON CONFLICT (name) DO UPDATE SET 
    description = EXCLUDED.description,
    category = EXCLUDED.category;

-- =============================================
-- ТРИГГЕРЫ
-- =============================================

-- Триггер для автоматического обновления updated_at
DROP TRIGGER IF EXISTS update_webhook_subscriptions_updated_at ON webhook_subscriptions;
CREATE TRIGGER update_webhook_subscriptions_updated_at 
    BEFORE UPDATE ON webhook_subscriptions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Триггер для автоматической деактивации после N последовательных неудач
CREATE OR REPLACE FUNCTION auto_deactivate_failed_webhooks()
RETURNS TRIGGER AS $$
BEGIN
    -- Если количество последовательных неудач >= 10, деактивируем подписку
    IF NEW.consecutive_failures >= 10 AND OLD.is_active = TRUE THEN
        NEW.is_active = FALSE;
        RAISE NOTICE 'Webhook subscription % deactivated after % consecutive failures', NEW.id, NEW.consecutive_failures;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS auto_deactivate_webhook ON webhook_subscriptions;
CREATE TRIGGER auto_deactivate_webhook
    BEFORE UPDATE OF consecutive_failures ON webhook_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION auto_deactivate_failed_webhooks();

COMMENT ON FUNCTION auto_deactivate_failed_webhooks() IS 'Автоматическая деактивация webhook после 10 последовательных неудач';

-- =============================================
-- ФУНКЦИИ
-- =============================================

-- -----------------------------------------------------------------
-- Функция получения активных подписок по событию
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_active_webhooks_for_event(event_name TEXT)
RETURNS TABLE (
    id INTEGER,
    name VARCHAR(255),
    url TEXT,
    secret VARCHAR(255),
    headers JSONB,
    timeout_seconds INTEGER,
    verify_ssl BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ws.id,
        ws.name,
        ws.url,
        ws.secret,
        ws.headers,
        ws.timeout_seconds,
        ws.verify_ssl
    FROM webhook_subscriptions ws
    WHERE ws.is_active = TRUE
      AND (ws.events @> ARRAY[event_name] OR ws.events @> ARRAY['*'])
    ORDER BY ws.id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_active_webhooks_for_event(TEXT) IS 'Получение списка активных подписок для указанного события';

-- -----------------------------------------------------------------
-- Функция создания записи о доставке
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION create_webhook_delivery(
    p_subscription_id INTEGER,
    p_event_id TEXT,
    p_event_type TEXT,
    p_payload JSONB,
    p_request_url TEXT,
    p_request_headers JSONB DEFAULT '{}',
    p_status TEXT DEFAULT 'pending'
) RETURNS INTEGER AS $$
DECLARE
    v_delivery_id INTEGER;
BEGIN
    INSERT INTO webhook_deliveries (
        subscription_id, event_id, event_type, payload, 
        request_url, request_headers, payload_size, status
    ) VALUES (
        p_subscription_id, p_event_id, p_event_type, p_payload,
        p_request_url, p_request_headers, pg_column_size(p_payload), p_status
    ) RETURNING id INTO v_delivery_id;
    
    -- Обновляем last_triggered_at у подписки
    UPDATE webhook_subscriptions 
    SET last_triggered_at = CURRENT_TIMESTAMP
    WHERE id = p_subscription_id;
    
    RETURN v_delivery_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_webhook_delivery(INTEGER, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT) IS 'Создание записи о доставке webhook';

-- -----------------------------------------------------------------
-- Функция обновления статуса доставки
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_webhook_delivery_status(
    p_delivery_id INTEGER,
    p_status TEXT,
    p_response_code INTEGER DEFAULT NULL,
    p_response_headers JSONB DEFAULT NULL,
    p_response_body TEXT DEFAULT NULL,
    p_duration_ms INTEGER DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
) RETURNS void AS $$
DECLARE
    v_subscription_id INTEGER;
    v_is_success BOOLEAN;
BEGIN
    UPDATE webhook_deliveries SET
        status = p_status,
        response_code = p_response_code,
        response_headers = p_response_headers,
        response_body = p_response_body,
        duration_ms = p_duration_ms,
        error_message = p_error_message,
        completed_at = CURRENT_TIMESTAMP
    WHERE id = p_delivery_id
    RETURNING subscription_id INTO v_subscription_id;
    
    v_is_success := p_status = 'success';
    
    -- Обновляем статистику подписки
    IF v_is_success THEN
        UPDATE webhook_subscriptions SET
            last_success_at = CURRENT_TIMESTAMP,
            success_count = success_count + 1,
            consecutive_failures = 0
        WHERE id = v_subscription_id;
    ELSE
        UPDATE webhook_subscriptions SET
            last_failure_at = CURRENT_TIMESTAMP,
            failure_count = failure_count + 1,
            consecutive_failures = consecutive_failures + 1
        WHERE id = v_subscription_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_webhook_delivery_status(INTEGER, TEXT, INTEGER, JSONB, TEXT, INTEGER, TEXT) IS 'Обновление статуса доставки webhook и статистики подписки';

-- -----------------------------------------------------------------
-- Функция планирования повторной попытки
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION schedule_webhook_retry(
    p_delivery_id INTEGER,
    p_retry_count INTEGER DEFAULT NULL
) RETURNS void AS $$
DECLARE
    v_subscription_id INTEGER;
    v_max_retries INTEGER;
    v_retry_delay INTEGER;
    v_current_retries INTEGER;
BEGIN
    -- Получаем информацию о подписке
    SELECT ws.id, ws.max_retries, ws.retry_delay_seconds, 
           COALESCE(p_retry_count, d.retry_count + 1)
    INTO v_subscription_id, v_max_retries, v_retry_delay, v_current_retries
    FROM webhook_deliveries d
    JOIN webhook_subscriptions ws ON d.subscription_id = ws.id
    WHERE d.id = p_delivery_id;
    
    -- Проверяем, не превышен ли лимит попыток
    IF v_current_retries > v_max_retries THEN
        UPDATE webhook_deliveries 
        SET status = 'expired', 
            error_message = COALESCE(error_message, '') || ' Max retries exceeded',
            completed_at = CURRENT_TIMESTAMP
        WHERE id = p_delivery_id;
        RETURN;
    END IF;
    
    -- Планируем повторную попытку
    UPDATE webhook_deliveries SET
        status = 'retry',
        retry_count = v_current_retries,
        next_retry_at = CURRENT_TIMESTAMP + (v_retry_delay * v_current_retries * INTERVAL '1 second')
    WHERE id = p_delivery_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION schedule_webhook_retry(INTEGER, INTEGER) IS 'Планирование повторной попытки доставки webhook с экспоненциальной задержкой';

-- -----------------------------------------------------------------
-- Функция очистки старых записей доставки
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION cleanup_old_webhook_deliveries(days INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM webhook_deliveries 
    WHERE created_at < CURRENT_TIMESTAMP - (days || ' days')::INTERVAL
      AND status IN ('success', 'expired');
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_webhook_deliveries(INTEGER) IS 'Очистка старых записей доставки webhook (по умолчанию 30 дней)';

-- -----------------------------------------------------------------
-- Функция реактивации webhook
-- -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION reactivate_webhook(p_subscription_id INTEGER)
RETURNS void AS $$
BEGIN
    UPDATE webhook_subscriptions SET
        is_active = TRUE,
        consecutive_failures = 0
    WHERE id = p_subscription_id;
    
    RAISE NOTICE 'Webhook subscription % reactivated', p_subscription_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION reactivate_webhook(INTEGER) IS 'Ручная реактивация отключённого webhook';

-- =============================================
-- ПРЕДСТАВЛЕНИЯ
-- =============================================

-- -----------------------------------------------------------------
-- Представление: webhook_subscription_stats
-- Статистика по подпискам
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW webhook_subscription_stats AS
SELECT 
    ws.id,
    ws.name,
    ws.url,
    ws.is_active,
    ws.created_at,
    ws.last_triggered_at,
    ws.last_success_at,
    ws.last_failure_at,
    ws.success_count,
    ws.failure_count,
    ws.consecutive_failures,
    -- Статистика доставок за последние 24 часа
    COUNT(d.id) AS deliveries_24h,
    COUNT(CASE WHEN d.status = 'success' THEN 1 END) AS success_24h,
    COUNT(CASE WHEN d.status = 'failed' THEN 1 END) AS failed_24h,
    -- Среднее время ответа
    ROUND(AVG(d.duration_ms)::numeric, 2) AS avg_response_ms
FROM webhook_subscriptions ws
LEFT JOIN webhook_deliveries d ON ws.id = d.subscription_id 
    AND d.created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
GROUP BY ws.id;

COMMENT ON VIEW webhook_subscription_stats IS 'Статистика по webhook подпискам';

-- =============================================
-- НАСТРОЙКИ
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('webhook_enabled', 'true', 'Enable webhook notifications', 'webhook'),
    ('webhook_timeout', '10', 'Webhook request timeout (seconds)', 'webhook'),
    ('webhook_max_retries', '3', 'Maximum webhook retry attempts', 'webhook'),
    ('webhook_retry_delay', '60', 'Webhook retry delay (seconds)', 'webhook'),
    ('webhook_auto_deactivate', 'true', 'Auto-deactivate after consecutive failures', 'webhook'),
    ('webhook_max_consecutive_failures', '10', 'Max consecutive failures before deactivation', 'webhook'),
    ('webhook_retention_days', '30', 'Webhook delivery retention period (days)', 'webhook'),
    ('webhook_signature_header', 'X-Webhook-Signature', 'Header name for HMAC signature', 'webhook'),
    ('webhook_event_id_header', 'X-Webhook-Event-ID', 'Header name for event ID', 'webhook'),
    ('webhook_event_type_header', 'X-Webhook-Event-Type', 'Header name for event type', 'webhook')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- ЗАПИСЬ О ПРИМЕНЕНИИ МИГРАЦИИ
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('004', 'Webhook Tables');

-- =============================================
-- ВЫВОД СТАТИСТИКИ
-- =============================================
DO $$
DECLARE
    event_count INTEGER;
    subscription_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO event_count FROM webhook_events;
    SELECT COUNT(*) INTO subscription_count FROM webhook_subscriptions;
    
    RAISE NOTICE 'Webhook events created: %', event_count;
    RAISE NOTICE 'Webhook subscriptions: %', subscription_count;
END $$;

-- =============================================
-- ОТКАТ (ROLLBACK)
-- =============================================
/*
DO $$
BEGIN
    -- Удаление представлений
    DROP VIEW IF EXISTS webhook_subscription_stats;
    
    -- Удаление функций
    DROP FUNCTION IF EXISTS reactivate_webhook(INTEGER);
    DROP FUNCTION IF EXISTS cleanup_old_webhook_deliveries(INTEGER);
    DROP FUNCTION IF EXISTS schedule_webhook_retry(INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS update_webhook_delivery_status(INTEGER, TEXT, INTEGER, JSONB, TEXT, INTEGER, TEXT);
    DROP FUNCTION IF EXISTS create_webhook_delivery(INTEGER, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT);
    DROP FUNCTION IF EXISTS get_active_webhooks_for_event(TEXT);
    DROP FUNCTION IF EXISTS auto_deactivate_failed_webhooks();
    
    -- Удаление триггеров
    DROP TRIGGER IF EXISTS auto_deactivate_webhook ON webhook_subscriptions;
    DROP TRIGGER IF EXISTS update_webhook_subscriptions_updated_at ON webhook_subscriptions;
    
    -- Удаление таблиц
    DROP TABLE IF EXISTS webhook_deliveries CASCADE;
    DROP TABLE IF EXISTS webhook_subscriptions CASCADE;
    DROP TABLE IF EXISTS webhook_events CASCADE;
    
    -- Удаление настроек
    DELETE FROM settings WHERE category = 'webhook';
    
    -- Удаление записи миграции
    DELETE FROM schema_migrations WHERE version = '004';
END $$;
*/
