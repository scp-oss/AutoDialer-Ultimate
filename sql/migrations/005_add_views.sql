-- =============================================
-- AutoDialer Ultimate - Migration 005: Database Views
-- Версия: 005
-- =============================================
-- Добавляет все представления (views) для:
-- - Статистики кампаний
-- - Дневной статистики
-- - Активных кампаний
-- - Статистики по пользователям
-- - Очереди дозвона
-- - Дашборда
-- =============================================

-- =============================================
-- Проверка, не применена ли уже миграция
-- =============================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '005') THEN
        RAISE NOTICE 'Migration 005 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- ПРЕДСТАВЛЕНИЯ (VIEWS)
-- =============================================

-- -----------------------------------------------------------------
-- Представление: campaign_stats
-- Полная статистика по кампаниям
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW campaign_stats AS
SELECT 
    c.id,
    c.name,
    c.description,
    c.status,
    c.max_calls,
    c.cps,
    c.caller_id,
    -- Контакты
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT CASE WHEN cc.status IS NULL OR cc.status NOT IN ('completed', 'skipped') THEN cc.contact_id END) AS pending_contacts,
    -- Звонки
    COUNT(DISTINCT cr.id) AS total_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'declined' THEN cr.id END) AS declined_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'busy' THEN cr.id END) AS busy_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'noanswer' THEN cr.id END) AS noanswer_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'failed' THEN cr.id END) AS failed_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'timeout' THEN cr.id END) AS timeout_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'machine' THEN cr.id END) AS machine_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'cancelled' THEN cr.id END) AS cancelled_calls,
    -- Длительность
    ROUND(AVG(cr.duration)::numeric, 2) AS avg_duration,
    SUM(cr.duration) AS total_duration,
    SUM(cr.billable_seconds) AS total_billable_seconds,
    ROUND(AVG(cr.billable_seconds)::numeric, 2) AS avg_billable_seconds,
    -- Конверсия
    CASE 
        WHEN COUNT(DISTINCT cr.id) > 0 
        THEN ROUND(COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) * 100.0 / COUNT(DISTINCT cr.id), 2)
        ELSE 0 
    END AS conversion_rate,
    -- Прогресс
    CASE 
        WHEN COUNT(DISTINCT cc.contact_id) > 0 
        THEN ROUND(COUNT(DISTINCT cr.id) * 100.0 / COUNT(DISTINCT cc.contact_id), 2)
        ELSE 0 
    END AS progress_percent,
    -- Временные метки
    c.created_at,
    c.started_at,
    c.completed_at,
    -- Расчётное время завершения
    CASE 
        WHEN c.status = 'running' AND COUNT(DISTINCT cr.id) > 0 AND COUNT(DISTINCT cc.contact_id) > 0
        THEN NOW() + ((COUNT(DISTINCT cc.contact_id) - COUNT(DISTINCT cr.id)) * 
             (EXTRACT(EPOCH FROM (NOW() - c.started_at)) / NULLIF(COUNT(DISTINCT cr.id), 0)) * INTERVAL '1 second')
        ELSE NULL
    END AS estimated_completion,
    -- Возраст кампании
    EXTRACT(EPOCH FROM (COALESCE(c.completed_at, NOW()) - c.created_at))::INTEGER AS age_seconds,
    -- Создатель
    c.created_by,
    u.username AS created_by_name
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
LEFT JOIN users u ON c.created_by = u.id
GROUP BY c.id, c.name, c.description, c.status, c.max_calls, c.cps, c.caller_id, 
         c.created_at, c.started_at, c.completed_at, c.created_by, u.username;

COMMENT ON VIEW campaign_stats IS 'Полная статистика по кампаниям: контакты, звонки, конверсия, прогресс';

-- -----------------------------------------------------------------
-- Представление: daily_stats
-- Статистика по дням
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW daily_stats AS
SELECT 
    DATE(created_at) AS date,
    -- Общая статистика
    COUNT(*) AS total_calls,
    COUNT(DISTINCT campaign_id) AS active_campaigns,
    COUNT(DISTINCT contact_id) AS unique_contacts,
    -- Статусы
    COUNT(CASE WHEN status = 'agreed' THEN 1 END) AS agreed,
    COUNT(CASE WHEN status = 'declined' THEN 1 END) AS declined,
    COUNT(CASE WHEN status = 'busy' THEN 1 END) AS busy,
    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) AS noanswer,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) AS failed,
    COUNT(CASE WHEN status = 'timeout' THEN 1 END) AS timeout,
    COUNT(CASE WHEN status = 'machine' THEN 1 END) AS machine,
    COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled,
    -- Конверсия
    CASE 
        WHEN COUNT(*) > 0 
        THEN ROUND(COUNT(CASE WHEN status = 'agreed' THEN 1 END) * 100.0 / COUNT(*), 2)
        ELSE 0 
    END AS conversion_rate,
    -- Длительность
    ROUND(AVG(duration)::numeric, 2) AS avg_duration,
    SUM(duration) AS total_duration,
    SUM(billable_seconds) AS total_billable_seconds,
    -- DTMF статистика
    COUNT(CASE WHEN dtmf_result = '1' THEN 1 END) AS dtmf_1,
    COUNT(CASE WHEN dtmf_result = '2' THEN 1 END) AS dtmf_2,
    COUNT(CASE WHEN dtmf_result = '3' THEN 1 END) AS dtmf_3,
    COUNT(CASE WHEN dtmf_result = '4' THEN 1 END) AS dtmf_4
FROM call_results
GROUP BY DATE(created_at)
ORDER BY date DESC;

COMMENT ON VIEW daily_stats IS 'Дневная статистика звонков: количество, статусы, конверсия, длительность';

-- -----------------------------------------------------------------
-- Представление: daily_stats_by_campaign
-- Статистика по дням в разрезе кампаний
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW daily_stats_by_campaign AS
SELECT 
    DATE(cr.created_at) AS date,
    cr.campaign_id,
    c.name AS campaign_name,
    COUNT(*) AS total_calls,
    COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) AS agreed,
    ROUND(AVG(cr.duration)::numeric, 2) AS avg_duration
FROM call_results cr
LEFT JOIN campaigns c ON cr.campaign_id = c.id
GROUP BY DATE(cr.created_at), cr.campaign_id, c.name
ORDER BY date DESC, campaign_id;

COMMENT ON VIEW daily_stats_by_campaign IS 'Дневная статистика в разрезе кампаний';

-- -----------------------------------------------------------------
-- Представление: active_campaigns
-- Информация об активных кампаниях
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW active_campaigns AS
SELECT 
    c.id,
    c.name,
    c.description,
    c.status,
    c.max_calls,
    c.cps,
    c.started_at,
    -- Контакты
    COUNT(DISTINCT cc.contact_id) AS total_contacts,
    COUNT(DISTINCT cr.id) AS calls_made,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed_calls,
    -- Оставшиеся
    COUNT(DISTINCT cc.contact_id) - COUNT(DISTINCT cr.id) AS remaining_contacts,
    -- Прогресс
    CASE 
        WHEN COUNT(DISTINCT cc.contact_id) > 0 
        THEN ROUND(COUNT(DISTINCT cr.id) * 100.0 / COUNT(DISTINCT cc.contact_id), 2)
        ELSE 0 
    END AS progress_percent,
    -- Время работы
    EXTRACT(EPOCH FROM (NOW() - c.started_at))::INTEGER AS running_seconds,
    -- Скорость (звонков в час)
    CASE 
        WHEN EXTRACT(EPOCH FROM (NOW() - c.started_at)) > 0 
        THEN ROUND(COUNT(DISTINCT cr.id) * 3600.0 / EXTRACT(EPOCH FROM (NOW() - c.started_at)), 2)
        ELSE 0 
    END AS calls_per_hour,
    -- Расчётное время завершения
    CASE 
        WHEN COUNT(DISTINCT cr.id) > 0 AND COUNT(DISTINCT cc.contact_id) > 0
        THEN NOW() + ((COUNT(DISTINCT cc.contact_id) - COUNT(DISTINCT cr.id)) * 
             (EXTRACT(EPOCH FROM (NOW() - c.started_at)) / COUNT(DISTINCT cr.id)) * INTERVAL '1 second')
        ELSE NULL
    END AS estimated_completion
FROM campaigns c
LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
LEFT JOIN call_results cr ON c.id = cr.campaign_id
WHERE c.status IN ('running', 'paused')
GROUP BY c.id, c.name, c.description, c.status, c.max_calls, c.cps, c.started_at;

COMMENT ON VIEW active_campaigns IS 'Информация об активных кампаниях: прогресс, скорость, оценка завершения';

-- -----------------------------------------------------------------
-- Представление: user_stats
-- Статистика по пользователям
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW user_stats AS
SELECT 
    u.id,
    u.username,
    u.full_name,
    u.email,
    u.role,
    u.is_active,
    u.last_login,
    u.created_at,
    -- Кампании
    COUNT(DISTINCT c.id) AS campaigns_created,
    COUNT(DISTINCT CASE WHEN c.status = 'running' THEN c.id END) AS active_campaigns,
    COUNT(DISTINCT CASE WHEN c.status = 'completed' THEN c.id END) AS completed_campaigns,
    -- Контакты
    COUNT(DISTINCT ct.id) AS contacts_imported,
    -- Аудио
    COUNT(DISTINCT af.id) AS audio_files_created,
    -- Аудит
    COUNT(DISTINCT al.id) AS audit_actions,
    MAX(al.created_at) AS last_action_at,
    -- Webhook'и
    COUNT(DISTINCT ws.id) AS webhooks_created
FROM users u
LEFT JOIN campaigns c ON u.id = c.created_by
LEFT JOIN contacts ct ON u.id = ct.created_by
LEFT JOIN audio_files af ON u.id = af.created_by
LEFT JOIN audit_log al ON u.id = al.user_id
LEFT JOIN webhook_subscriptions ws ON u.id = ws.created_by
GROUP BY u.id, u.username, u.full_name, u.email, u.role, u.is_active, u.last_login, u.created_at;

COMMENT ON VIEW user_stats IS 'Статистика по пользователям: созданные кампании, контакты, аудио, действия';

-- -----------------------------------------------------------------
-- Представление: dial_queue_view
-- Очередь на дозвон
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW dial_queue_view AS
SELECT 
    cc.id,
    cc.campaign_id,
    c.name AS campaign_name,
    c.cps,
    cc.contact_id,
    ct.phone,
    ct.name AS contact_name,
    ct.tags,
    cc.retry_count,
    cc.priority,
    cc.next_retry_at,
    cc.last_call_at,
    cc.status AS contact_status,
    -- Время ожидания
    CASE 
        WHEN cc.next_retry_at IS NOT NULL AND cc.next_retry_at > NOW()
        THEN EXTRACT(EPOCH FROM (cc.next_retry_at - NOW()))::INTEGER
        ELSE 0
    END AS wait_seconds,
    -- Количество предыдущих попыток
    COUNT(DISTINCT cr.id) AS previous_attempts,
    -- Последний результат
    MAX(cr.status) AS last_result
FROM campaign_contacts cc
JOIN campaigns c ON cc.campaign_id = c.id
JOIN contacts ct ON cc.contact_id = ct.id
LEFT JOIN call_results cr ON cc.campaign_id = cr.campaign_id AND cc.contact_id = cr.contact_id
WHERE c.status = 'running'
  AND ct.blacklisted = FALSE
  AND (cc.next_retry_at IS NULL OR cc.next_retry_at <= NOW())
GROUP BY cc.id, cc.campaign_id, c.name, c.cps, cc.contact_id, ct.phone, ct.name, ct.tags,
         cc.retry_count, cc.priority, cc.next_retry_at, cc.last_call_at, cc.status
ORDER BY cc.priority DESC, cc.retry_count ASC, cc.id ASC;

COMMENT ON VIEW dial_queue_view IS 'Очередь номеров на дозвон для активных кампаний';

-- -----------------------------------------------------------------
-- Представление: dashboard_summary
-- Сводка для дашборда
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW dashboard_summary AS
SELECT 
    -- Общая статистика
    (SELECT COUNT(*) FROM campaigns) AS total_campaigns,
    (SELECT COUNT(*) FROM campaigns WHERE status = 'running') AS running_campaigns,
    (SELECT COUNT(*) FROM campaigns WHERE status = 'paused') AS paused_campaigns,
    (SELECT COUNT(*) FROM campaigns WHERE status = 'completed') AS completed_campaigns,
    -- Контакты
    (SELECT COUNT(*) FROM contacts WHERE NOT blacklisted) AS total_contacts,
    (SELECT COUNT(*) FROM contacts WHERE blacklisted = TRUE) AS blacklisted_contacts,
    -- Звонки
    (SELECT COUNT(*) FROM call_results) AS total_calls,
    (SELECT COUNT(*) FROM call_results WHERE DATE(created_at) = CURRENT_DATE) AS calls_today,
    (SELECT COUNT(*) FROM call_results WHERE status = 'agreed') AS agreed_calls,
    (SELECT COUNT(*) FROM call_results WHERE status = 'declined') AS declined_calls,
    -- Конверсия
    CASE 
        WHEN (SELECT COUNT(*) FROM call_results) > 0 
        THEN ROUND((SELECT COUNT(*) FROM call_results WHERE status = 'agreed') * 100.0 / 
                   (SELECT COUNT(*) FROM call_results), 2)
        ELSE 0 
    END AS conversion_rate,
    -- Конверсия сегодня
    CASE 
        WHEN (SELECT COUNT(*) FROM call_results WHERE DATE(created_at) = CURRENT_DATE) > 0 
        THEN ROUND((SELECT COUNT(*) FROM call_results WHERE status = 'agreed' AND DATE(created_at) = CURRENT_DATE) * 100.0 / 
                   (SELECT COUNT(*) FROM call_results WHERE DATE(created_at) = CURRENT_DATE), 2)
        ELSE 0 
    END AS conversion_rate_today,
    -- Длительность
    (SELECT ROUND(AVG(duration)::numeric, 2) FROM call_results) AS avg_duration,
    (SELECT SUM(duration) FROM call_results) AS total_duration,
    -- Пользователи
    (SELECT COUNT(*) FROM users WHERE is_active = TRUE) AS active_users,
    -- Аудио
    (SELECT COUNT(*) FROM audio_files) AS total_audio_files;

COMMENT ON VIEW dashboard_summary IS 'Сводная статистика для дашборда: кампании, контакты, звонки, конверсия';

-- -----------------------------------------------------------------
-- Представление: campaign_performance
-- Сравнение эффективности кампаний
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW campaign_performance AS
SELECT 
    c.id,
    c.name,
    c.status,
    c.max_calls,
    c.cps,
    COUNT(DISTINCT cr.id) AS total_calls,
    COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) AS agreed,
    ROUND(AVG(cr.duration)::numeric, 2) AS avg_duration,
    CASE 
        WHEN COUNT(DISTINCT cr.id) > 0 
        THEN ROUND(COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) * 100.0 / COUNT(DISTINCT cr.id), 2)
        ELSE 0 
    END AS conversion_rate,
    -- Эффективность (согласий в час)
    CASE 
        WHEN SUM(cr.duration) > 0 
        THEN ROUND(COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) * 3600.0 / SUM(cr.duration), 2)
        ELSE 0 
    END AS agreed_per_hour,
    -- Стоимость одного согласия (если есть billing)
    CASE 
        WHEN COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END) > 0 
        THEN ROUND(SUM(cr.billable_seconds)::numeric / 60.0 / COUNT(DISTINCT CASE WHEN cr.status = 'agreed' THEN cr.id END), 2)
        ELSE 0 
    END AS minutes_per_agreed
FROM campaigns c
LEFT JOIN call_results cr ON c.id = cr.campaign_id
WHERE c.status IN ('running', 'completed', 'stopped')
GROUP BY c.id, c.name, c.status, c.max_calls, c.cps
HAVING COUNT(DISTINCT cr.id) > 0
ORDER BY conversion_rate DESC;

COMMENT ON VIEW campaign_performance IS 'Сравнение эффективности кампаний: конверсия, согласий в час, минут на согласие';

-- -----------------------------------------------------------------
-- Представление: call_results_extended
-- Расширенная информация о звонках с именами
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW call_results_extended AS
SELECT 
    cr.id,
    cr.campaign_id,
    c.name AS campaign_name,
    cr.contact_id,
    ct.phone,
    ct.name AS contact_name,
    ct.tags,
    cr.unique_id,
    cr.linked_id,
    cr.channel,
    cr.caller_id,
    cr.status,
    cr.dtmf_result,
    cr.duration,
    cr.billable_seconds,
    cr.hangup_cause,
    cr.hangup_cause_code,
    cr.hangup_cause_txt,
    cr.retry_count,
    cr.recording_path,
    cr.recording_url,
    cr.metadata,
    cr.created_at,
    -- Дополнительные поля
    EXTRACT(HOUR FROM cr.created_at) AS hour_of_day,
    EXTRACT(DOW FROM cr.created_at) AS day_of_week,
    CASE 
        WHEN EXTRACT(HOUR FROM cr.created_at) BETWEEN 9 AND 12 THEN 'morning'
        WHEN EXTRACT(HOUR FROM cr.created_at) BETWEEN 12 AND 17 THEN 'afternoon'
        WHEN EXTRACT(HOUR FROM cr.created_at) BETWEEN 17 AND 21 THEN 'evening'
        ELSE 'night'
    END AS time_period
FROM call_results cr
LEFT JOIN campaigns c ON cr.campaign_id = c.id
LEFT JOIN contacts ct ON cr.contact_id = ct.id;

COMMENT ON VIEW call_results_extended IS 'Расширенная информация о звонках с именами кампаний и контактов';

-- -----------------------------------------------------------------
-- Представление: contact_call_history
-- История звонков для каждого контакта
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW contact_call_history AS
SELECT 
    ct.id AS contact_id,
    ct.phone,
    ct.name AS contact_name,
    cr.id AS call_id,
    cr.campaign_id,
    c.name AS campaign_name,
    cr.status,
    cr.dtmf_result,
    cr.duration,
    cr.created_at,
    ROW_NUMBER() OVER (PARTITION BY ct.id ORDER BY cr.created_at DESC) AS call_rank
FROM contacts ct
LEFT JOIN call_results cr ON ct.id = cr.contact_id
LEFT JOIN campaigns c ON cr.campaign_id = c.id
WHERE cr.id IS NOT NULL;

COMMENT ON VIEW contact_call_history IS 'История звонков для каждого контакта с ранжированием';

-- -----------------------------------------------------------------
-- Представление: system_health
-- Состояние системы (требует данных из Redis, заполняется бэкендом)
-- -----------------------------------------------------------------
CREATE OR REPLACE VIEW system_health AS
SELECT 
    (SELECT value FROM settings WHERE key = 'system_enabled') AS system_enabled,
    (SELECT COUNT(*) FROM campaigns WHERE status = 'running') AS active_campaigns,
    (SELECT COUNT(*) FROM call_results WHERE created_at > NOW() - INTERVAL '1 minute') AS calls_last_minute,
    (SELECT COUNT(*) FROM call_results WHERE created_at > NOW() - INTERVAL '5 minutes') AS calls_last_5_minutes,
    (SELECT COUNT(*) FROM call_results WHERE created_at > NOW() - INTERVAL '1 hour') AS calls_last_hour,
    (SELECT MAX(created_at) FROM call_results) AS last_call_at,
    (SELECT COUNT(*) FROM campaign_contacts WHERE next_retry_at <= NOW()) AS pending_retries,
    (SELECT value::INTEGER FROM settings WHERE key = 'global_max_calls') AS max_calls,
    NOW() AS checked_at;

COMMENT ON VIEW system_health IS 'Состояние системы: активные кампании, звонки за период, ожидающие повторы';

-- =============================================
-- Материализованное представление для отчётов (опционально)
-- Обновляется периодически для ускорения отчётов
-- =============================================
/*
CREATE MATERIALIZED VIEW report_campaign_summary AS
SELECT 
    c.id,
    c.name,
    c.status,
    DATE_TRUNC('hour', cr.created_at) AS hour,
    COUNT(*) AS calls,
    COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) AS agreed
FROM campaigns c
LEFT JOIN call_results cr ON c.id = cr.campaign_id
GROUP BY c.id, c.name, c.status, DATE_TRUNC('hour', cr.created_at);

CREATE UNIQUE INDEX ON report_campaign_summary (id, hour);

COMMENT ON MATERIALIZED VIEW report_campaign_summary IS 'Материализованное представление для быстрых отчётов';
*/

-- =============================================
-- Настройки
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES 
    ('dashboard_refresh_interval', '5', 'Dashboard refresh interval (seconds)', 'ui'),
    ('stats_cache_ttl', '60', 'Statistics cache TTL (seconds)', 'performance'),
    ('materialized_views_enabled', 'false', 'Enable materialized views for reports', 'performance')
ON CONFLICT (key) DO NOTHING;

-- =============================================
-- Функция обновления материализованных представлений
-- =============================================
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    -- REFRESH MATERIALIZED VIEW CONCURRENTLY report_campaign_summary;
    NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION refresh_materialized_views() IS 'Обновление всех материализованных представлений';

-- =============================================
-- Запись о применении миграции
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('005', 'Database Views');

-- =============================================
-- Вывод статистики
-- =============================================
DO $$
DECLARE
    view_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO view_count 
    FROM pg_views 
    WHERE schemaname = 'public' 
      AND viewname IN (
          'campaign_stats', 'daily_stats', 'daily_stats_by_campaign', 
          'active_campaigns', 'user_stats', 'dial_queue_view', 
          'dashboard_summary', 'campaign_performance', 
          'call_results_extended', 'contact_call_history', 'system_health'
      );
    
    RAISE NOTICE 'Views created: %', view_count;
END $$;

-- =============================================
-- Откат (ROLLBACK)
-- =============================================
/*
DO $$
BEGIN
    -- Удаление представлений
    DROP VIEW IF EXISTS system_health;
    DROP VIEW IF EXISTS contact_call_history;
    DROP VIEW IF EXISTS call_results_extended;
    DROP VIEW IF EXISTS campaign_performance;
    DROP VIEW IF EXISTS dashboard_summary;
    DROP VIEW IF EXISTS dial_queue_view;
    DROP VIEW IF EXISTS user_stats;
    DROP VIEW IF EXISTS active_campaigns;
    DROP VIEW IF EXISTS daily_stats_by_campaign;
    DROP VIEW IF EXISTS daily_stats;
    DROP VIEW IF EXISTS campaign_stats;
    
    -- Удаление материализованного представления (если создано)
    DROP MATERIALIZED VIEW IF EXISTS report_campaign_summary;
    
    -- Удаление функции
    DROP FUNCTION IF EXISTS refresh_materialized_views();
    
    -- Удаление настроек
    DELETE FROM settings WHERE key IN ('dashboard_refresh_interval', 'stats_cache_ttl', 'materialized_views_enabled');
    
    -- Удаление записи миграции
    DELETE FROM schema_migrations WHERE version = '005';
END $$;
*/
