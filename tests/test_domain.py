from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from printflow.domain.models import (
    CardSpec,
    Job,
    JobStatus,
    article_from_offer,
    article_pattern,
    design_article,
    design_merge_group,
    format_article,
)


class ArticleTest(unittest.TestCase):
    def test_articles(self) -> None:
        self.assertEqual(format_article("BAG-", 7), "BAG-000007")
        self.assertTrue(article_pattern("BAG-").match("BAG-000007"))
        self.assertFalse(article_pattern("BAG-").match("TEE-000007"))
        self.assertEqual(article_from_offer("BAG-000007-W", "BAG-"), "BAG-000007")
        self.assertEqual(article_from_offer("bag-000007", "BAG-"), "BAG-000007")
        self.assertIsNone(article_from_offer("TEE-000007-W-XL", "BAG-"))
        # новый формат: группа-место-цвет
        self.assertTrue(article_pattern("BAG-").match("BAG-0001-03"))
        self.assertEqual(article_from_offer("BAG-0001-03-W", "BAG-"), "BAG-0001-03")
        self.assertEqual(article_from_offer("bag-0012-07-b", "BAG-"), "BAG-0012-07")

    def test_design_article_and_group(self) -> None:
        current = Job(id="c", number=1010, status=JobStatus.PENDING, payload={},
                      design_number=1005, group_id=2, group_position=4)
        first_group = Job(id="a", number=1003, status=JobStatus.PENDING, payload={}, group_id=1, group_position=3)
        legacy = Job(id="b", number=467, status=JobStatus.PENDING, payload={})
        # сейчас: сквозной артикул, модель отличается видом
        self.assertEqual(design_article("BAG-", current), "BAG-001005")
        group = design_merge_group("BAG-", current, 7)
        self.assertEqual((group.key, group.position, group.size), ("BAG-000002", 4, 7))
        # уже выложенные форматы не меняются
        self.assertEqual(design_article("BAG-", first_group), "BAG-0001-03")
        self.assertEqual(design_merge_group("BAG-", first_group, 7).key, "BAG-0001")
        self.assertEqual(design_article("BAG-", legacy), "BAG-000467")
        self.assertEqual(design_merge_group("BAG-", legacy, 7).key, "BAG-000467")


class CardSpecTest(unittest.TestCase):
    def test_payload_roundtrip_keeps_old_format(self) -> None:
        spec = CardSpec(theme="кот", product_name="Сумка-шоппер с принтом", colors=("black",), dry_run=True)
        payload = spec.to_payload()
        self.assertEqual(payload["kind"], "card")
        self.assertEqual(CardSpec.from_payload(payload), spec)
        old = {"kind": "card", "theme": "кот", "design_label": "Кот", "colors": ["white", "black"],
               "upload_to_ozon": True, "dry_run": False}  # задача, поставленная до рефакторинга
        self.assertEqual(CardSpec.from_payload(old), CardSpec(theme="кот"))  # старое design_label игнорируется


class SettingsTest(unittest.TestCase):
    def test_layering_and_whitelist(self) -> None:
        import printflow.config as config

        full = config.read_env()  # все ключи боевого окружения — дальше подменяем только проверяемые
        own_keys = {"OPENAI_API_KEY", "S3_ACCESS_KEY", "SHOPPER_OZON_API_KEY", "MOUSEPAD_OZON_API_KEY"}
        saved = {k: os.environ.pop(k, None) for k in own_keys}
        old = config.ROOT, config.PACKAGE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            root, own = Path(tmp), Path(tmp) / "printflow"
            own.mkdir()
            rest = "".join(f"{k}={v}\n" for k, v in full.items() if k not in own_keys and "\n" not in v)
            (root / ".env").write_text("OPENAI_API_KEY=tee-openai\nS3_ACCESS_KEY=tee-s3\nOZON_API_KEY=tee-ozon\n",
                                       encoding="utf-8")
            (own / ".env").write_text(rest + "OPENAI_API_KEY=own-openai\nSHOPPER_OZON_API_KEY=bag-ozon\n"
                                      "MOUSEPAD_OZON_API_KEY=pad-ozon\n", encoding="utf-8")
            config.ROOT, config.PACKAGE_DIR = root, own
            try:
                shopper = config.load_product_settings("SHOPPER")
                mousepad = config.load_product_settings("MOUSEPAD")
                app = config.load_app_settings()
            finally:
                config.ROOT, config.PACKAGE_DIR = old
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
        self.assertEqual(shopper.openai.api_key, "own-openai")  # своё перекрывает футболочное
        self.assertEqual(app.s3.access_key, "tee-s3")  # общее берётся у футболок
        self.assertEqual(shopper.ozon.api_key, "bag-ozon")  # кабинет — только свой
        self.assertEqual(mousepad.ozon.api_key, "pad-ozon")  # у каждого товара свой кабинет

    def test_no_defaults(self) -> None:
        """Значений по умолчанию нет: без ключа — ошибка со списком всех недостающих."""
        import printflow.config as config

        env = config.read_env()
        del env["SHOPPER_WORKERS"], env["OPENAI_TEXT_MODEL"]
        with self.assertRaises(config.MissingSettings) as ctx:
            config.load_product_settings("SHOPPER", env)
        self.assertIn("SHOPPER_WORKERS", str(ctx.exception))
        self.assertIn("OPENAI_TEXT_MODEL", str(ctx.exception))
        env["MOUSEPAD_OZON_CERTIFICATE_ID"] = ""  # пусто — «не привязывать», это не пропуск
        env["SHOPPER_WORKERS"], env["OPENAI_TEXT_MODEL"] = "2", "m"
        self.assertIsNone(config.load_product_settings("MOUSEPAD", env).ozon.certificate_id)


if __name__ == "__main__":
    unittest.main()
