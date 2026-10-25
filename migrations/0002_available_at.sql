-- Отложенный повтор упавшей задачи: воркер не берёт её раньше available_at.
ALTER TABLE jobs ADD COLUMN available_at TEXT;
