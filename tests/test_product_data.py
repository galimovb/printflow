import unittest
from pathlib import Path
from support import TempDir
from printflow.config import product_data_dir
from printflow.scripts.source_report import report_path
from printflow.scripts.migrate_product_data import migrate

class ProductDataTest(unittest.TestCase):
    def test_all_products_use_one_custom_runtime_root(self):
        root=Path('custom-runtime')
        for name in ('shopper','mousepad','thermo'):
            self.assertEqual(product_data_dir(root,name),root/name)
            self.assertEqual(report_path(name,root),root/name/'reports/sources.csv')
        for invalid in ('../shopper','/mousepad','thermo/../../',''):
            with self.assertRaises(ValueError):product_data_dir(root,invalid)

    def test_migration_preserves_ideas_ids_reports_and_database(self):
        with TempDir() as root:
            source=root/'ideas/mousepad/cats.json';source.parent.mkdir(parents=True)
            content=b'{"ideas":[{"id":"keep-this-id","title":"cat"}]}'
            source.write_bytes(content)
            report=root/'reports/sources_shopper.csv';report.parent.mkdir();report.write_bytes(b'SKU\n123\n')
            (root/'jobs.db').write_bytes(b'working-database')
            plan=migrate(root)
            self.assertEqual(len(plan),2)
            self.assertTrue(source.exists())
            moved=migrate(root,apply=True)
            self.assertEqual(len(moved),2)
            target=root/'mousepad'/'ideas'/'cats.json'
            self.assertEqual(target.read_bytes(),content)
            self.assertEqual(report_path('shopper',root).read_bytes(),b'SKU\n123\n')
            self.assertEqual((root/'jobs.db').read_bytes(),b'working-database')
            self.assertFalse((root/'ideas').exists())
            self.assertEqual(migrate(root,apply=True),[])

    def test_conflicts_fail_before_moving_any_files(self):
        with TempDir() as root:
            for name in ('shopper','mousepad'):
                old=root/'ideas'/name/'cats.json';old.parent.mkdir(parents=True);old.write_text('old')
            conflict=root/'mousepad/ideas/cats.json';conflict.parent.mkdir(parents=True);conflict.write_text('new')
            with self.assertRaises(FileExistsError):migrate(root,apply=True)
            self.assertTrue((root/'ideas/shopper/cats.json').exists())
            self.assertEqual(conflict.read_text(),'new')


if __name__=='__main__':unittest.main()
