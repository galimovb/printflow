-- Сквозные номера дизайнов: артикул BAG-001001 (товары BAG-001001-W / -B).
-- Номер выдаётся из счётчика при постановке карточки в очередь и не переиспользуется;
-- задачи перерисовки (hires) номер не занимают. Стартовое значение — SHOPPER_FIRST_ARTICLE_NUMBER
-- (выставляет сервис migrate, счётчик только растёт).
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
ALTER TABLE jobs ADD COLUMN design_number INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS jobs_design_number ON jobs(design_number) WHERE design_number IS NOT NULL;
