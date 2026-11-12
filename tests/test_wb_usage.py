import json
import os
import tempfile
import unittest
from unittest.mock import patch

from printflow.wb_studio.infrastructure import usage


class UsageLogTest(unittest.TestCase):
    def test_every_request_is_one_priced_line_under_its_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "u.jsonl")
            with patch.dict(os.environ, {"PRINTFLOW_WB_USAGE_LOG": path}):
                token = usage.card.set({"job": "j1", "design": 7})
                try:
                    image = {"input_tokens_details": {"text_tokens": 200, "image_tokens": 2000, "cached_tokens": 1000},
                             "output_tokens": 100}
                    usage.record("image", "frame", "gpt-image-2.5-sunburst", image, quality="low")
                    chat = {"prompt_tokens": 3000, "completion_tokens": 500, "prompt_tokens_details": {"cached_tokens": 0}}
                    usage.record("chat", "analysis", "gpt-6.1-sol", chat)
                    usage.record("chat", "verify", "unknown-model", chat)
                    usage.record("image", "frame", "gpt-image-2.5-sunburst", None)  # nothing to account
                finally:
                    usage.card.reset(token)
            lines = [json.loads(x) for x in open(path, encoding="utf-8")]
        self.assertEqual([x["purpose"] for x in lines], ["frame", "analysis", "verify"])
        self.assertEqual(lines[0]["design"], 7)
        # 200 text x $5 + 1000 image x $8 + 1000 cached image x $2 + 100 out x $30, per 1M
        self.assertAlmostEqual(lines[0]["cost_usd"], (200 * 5 + 1000 * 8 + 1000 * 2 + 100 * 30) / 1e6)
        self.assertAlmostEqual(lines[1]["cost_usd"], (3000 * 2 + 500 * 10) / 1e6)
        self.assertIsNone(lines[2]["cost_usd"])
