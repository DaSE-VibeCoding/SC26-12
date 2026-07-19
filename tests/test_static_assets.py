from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fia.web import _cache_control_for, _content_type_for


class StaticAssetTests(unittest.TestCase):
    def test_pdfjs_modules_use_javascript_mime_and_no_cache(self) -> None:
        for name in ("pdf.mjs", "pdf.worker.mjs"):
            path = PROJECT_ROOT / "static" / "vendor" / name
            self.assertEqual(_content_type_for(path), "text/javascript; charset=utf-8")
            self.assertEqual(_cache_control_for(path, _content_type_for(path)), "no-store")

    def test_pdf_range_responses_are_not_cached(self) -> None:
        path = PROJECT_ROOT / "annual_reports" / "example.pdf"
        self.assertEqual(_cache_control_for(path, "application/pdf"), "no-store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
