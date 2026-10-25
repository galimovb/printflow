from __future__ import annotations

import unittest

from support import TempDir, new_repository

from printflow.products import PRODUCTS, get_product
from printflow.products.base import Product


class ProductsInOneDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDir()
        self.repo = new_repository(self.tmp.__enter__())

    def tearDown(self) -> None:
        self.tmp.__exit__()

    def test_numbers_and_groups_are_per_product(self) -> None:
        bag = [self.repo.create({"kind": "card"}, product="shopper", numbered=True, group_size=7)[0] for _ in range(3)]
        pad = [self.repo.create({"kind": "card"}, product="mousepad", numbered=True, group_size=14)[0] for _ in range(2)]
        self.assertEqual([j.design_number for j in bag], [1, 2, 3])
        self.assertEqual([j.design_number for j in pad], [1, 2])  # свой счётчик: MSE-000001, MSE-000002
        self.assertNotEqual(bag[0].group_id, pad[0].group_id)  # группы объединения не смешиваются
        self.assertEqual([j.group_position for j in pad], [1, 2])
        self.assertEqual({j.product for j in bag} | {j.product for j in pad}, {"shopper", "mousepad"})

    def test_worker_claims_only_its_product(self) -> None:
        bag, _ = self.repo.create({"kind": "card"}, product="shopper")
        pad, _ = self.repo.create({"kind": "card"}, product="mousepad")
        self.assertEqual(self.repo.claim_next("mousepad").id, pad.id)
        self.assertIsNone(self.repo.claim_next("mousepad"))
        self.assertEqual(self.repo.claim_next("shopper").id, bag.id)
        self.assertEqual(self.repo.count_by_status("mousepad"), {"running": 1})

    def test_recover_only_own_product(self) -> None:
        self.repo.create({"kind": "card"}, product="shopper")
        self.repo.create({"kind": "card"}, product="mousepad")
        self.repo.claim_next("shopper")
        self.repo.claim_next("mousepad")
        self.assertEqual(self.repo.recover_interrupted(max_attempts=3, product="mousepad"), 1)
        self.assertEqual(self.repo.count_by_status("shopper"), {"running": 1})


class PublishDryRunsTest(unittest.TestCase):
    def test_dry_run_cards_go_to_real_publish_keeping_gallery(self) -> None:
        with TempDir() as tmp:
            repo = new_repository(tmp)
            pad, _ = repo.create({"kind": "card", "dry_run": True}, product="mousepad")
            bag, _ = repo.create({"kind": "card", "dry_run": True}, product="shopper")
            for job in (pad, bag):
                repo.claim_next(job.product)
                repo.complete(job.id, {"print": "p", "images": {"main": ["u"]}, "ozon": {"dry_run": True}})
            self.assertEqual(repo.publish_dry_runs("mousepad"), 1)
            again = repo.get(pad.id)
            self.assertEqual((again.status.value, again.payload["dry_run"]), ("pending", False))
            self.assertEqual(again.result, {"print": "p", "images": {"main": ["u"]}})  # галерея цела, Ozon — заново
            self.assertEqual(repo.get(bag.id).status.value, "done")  # другой товар не тронут
            self.assertEqual(repo.publish_dry_runs("mousepad"), 0)


class RegistryTest(unittest.TestCase):
    def test_every_product_is_complete(self) -> None:
        for name in PRODUCTS:
            product = get_product(name)
            self.assertIsInstance(product, Product)
            self.assertEqual(product.name, name)
            self.assertTrue(product.config_path.is_file(), name)
            self.assertTrue(product.article_prefix.endswith("-"))
            self.assertEqual(set(product.buckets), {"prints", "mockups", "hires"})
        prefixes = [get_product(n).article_prefix for n in PRODUCTS]
        self.assertEqual(len(prefixes), len(set(prefixes)))  # артикулы товаров не пересекаются


if __name__ == "__main__":
    unittest.main()
