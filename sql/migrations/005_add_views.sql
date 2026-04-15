-- =============================================
-- AutoDialer Ultimate - Migration 005: Database Views
-- Версия: 005
-- =============================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '005') THEN
        RAISE NOTICE 'Migration 005 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- Представление статистики кампаний
-- =============================================
CREATE OR REPLACE VIEW campaign_stats AS
SELECT 
    c.id,
    c.name,
    c.status,
    c.max_calls,
    c.cps,
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT cr.id) AS total_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'declined' THEN cr.id END) AS declined_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'busy' THEN cr.id END) AS busy_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'noanswer' THEN cr.id END) AS noanswer_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'failed' THEN cr.id END) AS failed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'timeout' THEN cr.id END) AS timeout_calls,
    ROUND(AVG(cr.duration)::numeric, 2) AS avg_duration,
    SUM(cr.billable_seconds) AS total_billable_seconds,
    CASE 
        WHEN COUNT(DISTINCT cr.id) > 0 
        THEN ROUND(COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) * 100.0 / COUNT(DISTINCT cr.id), 2)
        ELSE 0 
    END AS conversion_rate,
    c.created_at,
    c.started_at,
    c.completed_at
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
GROUP BY c.id, c.name, c.status, c.max_calls, c.cps, c.created_at, c.started_at, c.completed_at;

-- =============================================
-- Представление статистики по дням
-- =============================================
CREATE OR REPLACE VIEW daily_stats AS
SELECT 
    DATE(created_at) AS date,
    COUNT(*) AS total_calls,
    COUNT(CASE WHEN status = 'agreed' THEN 1 END) AS agreed,
    COUNT(CASE WHEN status = 'declined' THEN 1 END) AS declined,
    COUNT(CASE WHEN status = 'busy' THEN 1 END) AS busy,
    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) AS noanswer,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) AS failed,
    COUNT(CASE WHEN status = 'timeout' THEN 1 END) AS timeout,
    ROUND(AVG(duration)::numeric, 2) AS avg_duration,
    SUM(billable_seconds) AS total_billable_seconds
FROM call_results
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- =============================================
-- Представление активных кампаний
-- =============================================
CREATE OR REPLACE VIEW active_campaigns AS
SELECT 
    c.*,
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT cr.id) AS calls_made,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
WHERE c.status IN ('running', 'paused')
GROUP BY c.id;

-- =============================================
-- Представление статистики по пользователям
-- =============================================
CREATE OR REPLACE VIEW user_stats AS
SELECT 
    u.id,
    u.username,
    u.role,
    COUNT(DISTINCT c.id) AS campaigns_created,
    COUNT(DISTINCT cc.contact_id) AS contacts_imported,
    COUNT(DISTINCT af.id) AS audio_files_created,
    u.last_login,
    u.created_at
FROM users u
LEFT JOIN campaigns c ON u.id = c.created_by
LEFT JOIN contacts ct ON u.id = ct.created_by
LEFT JOIN campaign_contacts cc ON ct.id = cc.contact_id
LEFT JOIN audio_files af ON u.id = af.created_by
GROUP BY u.id, u.username, u.role, u.last_login, u.created_at;

-- =============================================
-- Представление очереди на дозвон
-- =============================================
CREATE OR REPLACE VIEW dial_queue_view AS
SELECT 
    cc.id,
    cc.campaign_id,
    c.name AS campaign_name,
    cc.contact_id,
    ct.phone,
    ct.name AS contact_name,
    cc.retry_count,
    cc.priority,
    cc.next_retry_at,
    cc.last_call_at
FROM campaign_contacts cc
JOIN campaigns c ON cc.campaign_id = c.id
JOIN contacts ct ON cc.contact_id = ct.id
WHERE c.status = 'running'
  AND ct.blacklisted = FALSE
  AND (cc.next_retry_at IS NULL OR cc.next_retry_at <= NOW())
ORDER BY cc.priority DESC, cc.retry_count ASC, cc.id ASC;

-- =============================================
-- Настройки
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('recording_enabled', 'false', 'Enable call recording', 'features'),
    ('recording_format', 'wav', 'Recording format (wav/mp3)', 'features'),
    ('amd_enabled', 'false', 'Enable answering machine detection', 'features'),
    ('websocket_enabled', 'true', 'Enable WebSocket for real-time updates', 'features'),
    ('metrics_enabled', 'true', 'Enable Prometheus metrics', 'monitoring')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('005', 'Database Views');

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DROP VIEW IF EXISTS dial_queue_view;
DROP VIEW IF EXISTS user_stats;
DROP VIEW IF EXISTS active_campaigns;
DROP VIEW IF EXISTS daily_stats;
DROP VIEW IF EXISTS campaign_stats;
*/
