-- =============================================
-- AutoDialer Ultimate - Migration 004: Webhook Tables
-- Версия: 004
-- =============================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '004') THEN
        RAISE NOTICE 'Migration 004 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- Таблица: webhook_subscriptions
-- =============================================
CREATE TABLE webhook_subscriptions (
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
-- Таблица: webhook_deliveries
-- =============================================
CREATE TABLE webhook_deliveries (
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
-- Индексы
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_subscriptions_is_active ON webhook_subscriptions(is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at);

-- =============================================
-- Триггер updated_at
-- =============================================
DROP TRIGGER IF EXISTS update_webhook_subscriptions_updated_at ON webhook_subscriptions;
CREATE TRIGGER update_webhook_subscriptions_updated_at 
    BEFORE UPDATE ON webhook_subscriptions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- Настройки webhook
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('webhook_enabled', 'true', 'Enable webhook notifications', 'webhook'),
    ('webhook_timeout', '10', 'Webhook request timeout (seconds)', 'webhook'),
    ('webhook_max_retries', '3', 'Maximum webhook retry attempts', 'webhook'),
    ('webhook_retry_delay', '60', 'Webhook retry delay (seconds)', 'webhook')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('004', 'Webhook Tables');

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DROP TABLE IF EXISTS webhook_deliveries CASCADE;
DROP TABLE IF EXISTS webhook_subscriptions CASCADE;
*/
