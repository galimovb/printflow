-- Одна база на все товары (шопперы, коврики…): у задач и групп объединения — товар.
-- Всё, что было до общей базы, — шопперы. Номер дизайна уникален в пределах товара (BAG-000001 и MSE-000001),
-- счётчик номеров — свой у каждого товара: design:<товар>.
ALTER TABLE jobs ADD COLUMN product TEXT NOT NULL DEFAULT 'shopper';
ALTER TABLE merge_groups ADD COLUMN product TEXT NOT NULL DEFAULT 'shopper';
DROP INDEX IF EXISTS jobs_design_number;
CREATE UNIQUE INDEX IF NOT EXISTS jobs_product_design_number ON jobs(product, design_number) WHERE design_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_product_status ON jobs(product, status, number);
UPDATE counters SET name = 'design:shopper' WHERE name = 'design';
