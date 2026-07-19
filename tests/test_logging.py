from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from fia.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_logging,
    shutdown_logging,
)


class LoggingTests(unittest.TestCase):
    def test_logs_are_created_split_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            try:
                log_dir = configure_logging(project_root)
                logging.getLogger("fia.test").info("LOG_TEST_INFO")
                logging.getLogger("fia.test").error("LOG_TEST_ERROR")
                logging.getLogger("fia.frontend").error("LOG_TEST_FRONTEND")
                for logger in (logging.getLogger(), logging.getLogger("fia.frontend")):
                    for handler in logger.handlers:
                        handler.flush()

                app_text = (log_dir / "app.log").read_text(encoding="utf-8")
                error_text = (log_dir / "errors.log").read_text(encoding="utf-8")
                frontend_text = (log_dir / "frontend.log").read_text(encoding="utf-8")
                self.assertIn("LOG_TEST_INFO", app_text)
                self.assertIn("LOG_TEST_ERROR", error_text)
                self.assertNotIn("LOG_TEST_INFO", error_text)
                self.assertIn("LOG_TEST_FRONTEND", frontend_text)
                self.assertIn("test_logging.py:", app_text)

                rotating = [
                    handler
                    for handler in logging.getLogger().handlers
                    if hasattr(handler, "maxBytes")
                ]
                self.assertTrue(rotating)
                self.assertTrue(all(handler.maxBytes == LOG_MAX_BYTES for handler in rotating))
                self.assertTrue(all(handler.backupCount == LOG_BACKUP_COUNT for handler in rotating))
            finally:
                shutdown_logging()


if __name__ == "__main__":
    unittest.main(verbosity=2)
