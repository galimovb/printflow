-- Группы объединения: несколько дизайнов в одной карточке Ozon. Номер группы и место в ней
-- выдаются при постановке карточки в очередь и входят в артикул: BAG-0001-03-W
-- (группа 0001, дизайн 3 в группе, молочный). «Название модели» в Ozon — BAG-0001.
CREATE TABLE IF NOT EXISTS merge_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
ALTER TABLE jobs ADD COLUMN group_id INTEGER REFERENCES merge_groups(id);
ALTER TABLE jobs ADD COLUMN group_position INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS jobs_group_slot ON jobs(group_id, group_position) WHERE group_id IS NOT NULL;
