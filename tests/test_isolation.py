"""Ядро не патчится и server.config не загружается: из server.* разрешены только три модуля."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_CORE = {"server", "server.prompts", "server.print_generation", "server.print_raster"}


class IsolationTest(unittest.TestCase):
    def test_core_config_never_imported(self) -> None:
        modules = [
            "printflow.__main__", "printflow.container", "printflow.migrations.__main__",
            "printflow.scripts.from_xlsx", "printflow.scripts.ozon_prepare_card",
            "printflow.products.shopper.scripts.preview_gallery",
            "printflow.products.shopper.scripts.generate_blanks",
            "printflow.products.shopper.infrastructure.print_generator",
        ]
        code = (
            f"import sys, {', '.join(modules)};"
            "print(' '.join(sorted(m for m in sys.modules if m == 'server' or m.startswith('server.'))))"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(set(out.stdout.split()), ALLOWED_CORE)


if __name__ == "__main__":
    unittest.main()
