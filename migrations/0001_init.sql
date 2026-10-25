-- Очередь задач. number — сквозной номер задачи, из него строится артикул BAG-000001
-- (AUTOINCREMENT: номера не переиспользуются даже после удаления строк).
CREATE TABLE IF NOT EXISTS jobs (
    number INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    external_id TEXT UNIQUE,
    status TEXT NOT NULL,
    stage TEXT,
    payload TEXT NOT NULL,
    result TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
