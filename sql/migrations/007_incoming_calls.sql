-- =============================================
-- AutoDialer Ultimate - Migration 007: Incoming Calls
-- Версия: 007
-- =============================================
-- Добавляет функциональность входящих звонков:
-- - Таблица incoming_calls для хранения записей
-- - Настройка incoming_greeting для приветствия
-- =============================================

-- =============================================
-- Проверка, не применена ли уже миграция
-- =============================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '007') THEN
        RAISE NOTICE 'Migration 007 already applied, skipping...';
        RETURN;
    END IF;
END $$;

-- =============================================
-- ТАБЛИЦА INCOMING_CALLS
-- =============================================
CREATE TABLE incoming_calls (
    id SERIAL PRIMARY KEY,
    caller_number VARCHAR(20) NOT NULL,
    recording_path TEXT NOT NULL,
    transcription TEXT,
    transcription_status VARCHAR(20) DEFAULT 'pending' CHECK (transcription_status IN ('pending', 'processing', 'completed', 'failed')),
    duration INTEGER,
    file_size INTEGER,
    call_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    listened BOOLEAN DEFAULT FALSE,
    notes TEXT,
    metadata JSONB DEFAULT '{}'
);

COMMENT ON TABLE incoming_calls IS 'Входящие звонки с записью и транскрибацией';
COMMENT ON COLUMN incoming_calls.caller_number IS 'Номер звонящего';
COMMENT ON COLUMN incoming_calls.recording_path IS 'Путь к аудиозаписи';
COMMENT ON COLUMN incoming_calls.transcription IS 'Распознанный текст';
COMMENT ON COLUMN incoming_calls.transcription_status IS 'Статус транскрибации: pending, processing, completed, failed';
COMMENT ON COLUMN incoming_calls.duration IS 'Длительность записи в секундах';
COMMENT ON COLUMN incoming_calls.file_size IS 'Размер файла в байтах';
COMMENT ON COLUMN incoming_calls.call_date IS 'Дата и время звонка';
COMMENT ON COLUMN incoming_calls.listened IS 'Прослушана ли запись';
COMMENT ON COLUMN incoming_calls.notes IS 'Заметки оператора';
COMMENT ON COLUMN incoming_calls.metadata IS 'Дополнительные метаданные';

-- =============================================
-- ИНДЕКСЫ ДЛЯ INCOMING_CALLS
-- =============================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incoming_calls_caller ON incoming_calls(caller_number);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incoming_calls_date ON incoming_calls(call_date);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incoming_calls_status ON incoming_calls(transcription_status);

-- =============================================
-- НАСТРОЙКА INCOMING_GREETING
-- =============================================
INSERT INTO settings (key, value, description, category) VALUES (
    'incoming_greeting',
    'tts/incoming_welcome',
    'Аудиофайл приветствия для входящих звонков',
    'incoming'
) ON CONFLICT (key) DO NOTHING;

-- =============================================
-- ФУНКЦИЯ ДЛЯ АВТОМАТИЧЕСКОЙ ТРАНСКРИБАЦИИ (заготовка)
-- =============================================
CREATE OR REPLACE FUNCTION process_incoming_call_transcription()
RETURNS TRIGGER AS $$
BEGIN
    -- Эта функция будет вызываться из Python-бэкенда
    -- Здесь только заглушка для будущей реализации
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION process_incoming_call_transcription() IS 'Заглушка для автоматической транскрибации (вызывается из бэкенда)';

-- =============================================
-- ТРИГГЕР ДЛЯ АВТОМАТИЧЕСКОГО ОБНОВЛЕНИЯ (опционально)
-- =============================================
-- DROP TRIGGER IF EXISTS trigger_incoming_call_created ON incoming_calls;
-- CREATE TRIGGER trigger_incoming_call_created
--     AFTER INSERT ON incoming_calls
--     FOR EACH ROW
--     EXECUTE FUNCTION process_incoming_call_transcription();

-- =============================================
-- ЗАПИСЬ О ПРИМЕНЕНИИ МИГРАЦИИ
-- =============================================
INSERT INTO schema_migrations (version, name) VALUES ('007', 'Incoming Calls');

-- =============================================
-- ВЫВОД СТАТИСТИКИ
-- =============================================
DO $$
BEGIN
    RAISE NOTICE 'Migration 007 applied: incoming_calls table created';
    RAISE NOTICE '  - Table: incoming_calls';
    RAISE NOTICE '  - Indexes: 3';
    RAISE NOTICE '  - Setting: incoming_greeting';
END $$;

-- =============================================
-- ОТКАТ (ROLLBACK)
-- =============================================
/*
DO $$
BEGIN
    -- Удаление триггера (если был создан)
    DROP TRIGGER IF EXISTS trigger_incoming_call_created ON incoming_calls;
    
    -- Удаление функции
    DROP FUNCTION IF EXISTS process_incoming_call_transcription();
    
    -- Удаление таблицы
    DROP TABLE IF EXISTS incoming_calls CASCADE;
    
    -- Удаление настройки
    DELETE FROM settings WHERE key = 'incoming_greeting';
    
    -- Удаление записи миграции
    DELETE FROM schema_migrations WHERE version = '007';
    
    RAISE NOTICE 'Migration 007 rolled back';
END $$;
*/
