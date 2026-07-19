from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StartupBootstrapTests(unittest.TestCase):
    def test_logging_import_does_not_load_pdf_dependencies(self) -> None:
        command = (
            "import sys; "
            "import fia.logging_config; "
            "assert 'fia.parser' not in sys.modules; "
            "assert 'pdfplumber' not in sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_public_analysis_service_remains_available_lazily(self) -> None:
        from fia import AnalysisService
        from fia.service import AnalysisService as DirectAnalysisService

        self.assertIs(AnalysisService, DirectAnalysisService)


if __name__ == "__main__":
    unittest.main(verbosity=2)
