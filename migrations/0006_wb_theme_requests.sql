-- Темы WB, поставленные из интерфейса. Парсит их программа на компьютере (Chrome, которому доверяет WB):
-- она забирает заявку waiting → parsing и отдаёт найденные карточки в очередь (queued) или сообщает empty/failed.
CREATE TABLE IF NOT EXISTS wb_theme_requests (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL,
    theme TEXT NOT NULL,
    count INTEGER NOT NULL,
    search INTEGER NOT NULL,
    algorithm TEXT NOT NULL,
    colors TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',
    campaign_id TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS wb_theme_requests_status ON wb_theme_requests(status, number);
-- Последний сигнал от программы-парсера: интерфейс показывает, запущена ли она.
CREATE TABLE IF NOT EXISTS wb_parser_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seen_at TEXT NOT NULL,
    current TEXT
);
-- Прогресс темы и список уже искавшихся тем читаются из jobs по выражениям: без индексов это полный проход базы.
CREATE INDEX IF NOT EXISTS jobs_wb_campaign ON jobs(json_extract(payload, '$.campaign_id')) WHERE product = 'tee_wb';
CREATE INDEX IF NOT EXISTS jobs_wb_kind ON jobs(json_extract(payload, '$.kind')) WHERE product = 'tee_wb';
