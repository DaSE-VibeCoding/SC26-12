from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
_CONFIG_LOCK = threading.RLock()
_HANDLER_MARKER = "_financial_indicators_assistant_handler"


def _managed_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in logger.handlers if getattr(handler, _HANDLER_MARKER, False)]


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in _managed_handlers(logger):
        logger.removeHandler(handler)
        handler.flush()
        handler.close()


def _mark(handler: logging.Handler, log_dir: Path) -> logging.Handler:
    setattr(handler, _HANDLER_MARKER, True)
    setattr(handler, "_financial_indicators_assistant_log_dir", str(log_dir))
    return handler


def _rotating_handler(path: Path, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def configure_logging(project_root: Path) -> Path:
    """Configure bounded UTF-8 logs and return the project's log directory."""
    log_dir = Path(project_root).resolve() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with _CONFIG_LOCK:
        root_logger = logging.getLogger()
        existing = _managed_handlers(root_logger)
        if existing and all(
            getattr(handler, "_financial_indicators_assistant_log_dir", None) == str(log_dir)
            for handler in existing
        ):
            return log_dir

        _remove_managed_handlers(root_logger)
        frontend_logger = logging.getLogger("fia.frontend")
        _remove_managed_handlers(frontend_logger)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | pid=%(process)d thread=%(threadName)s | "
            "%(name)s | %(filename)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        app_handler = _mark(
            _rotating_handler(log_dir / "app.log", logging.INFO, formatter),
            log_dir,
        )
        error_handler = _mark(
            _rotating_handler(log_dir / "errors.log", logging.ERROR, formatter),
            log_dir,
        )
        console_handler = _mark(logging.StreamHandler(), log_dir)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(app_handler)
        root_logger.addHandler(error_handler)
        root_logger.addHandler(console_handler)

        frontend_handler = _mark(
            _rotating_handler(log_dir / "frontend.log", logging.INFO, formatter),
            log_dir,
        )
        frontend_logger.setLevel(logging.INFO)
        frontend_logger.addHandler(frontend_handler)
        frontend_logger.propagate = True
        logging.captureWarnings(True)
    return log_dir


def shutdown_logging() -> None:
    """Flush and close handlers managed by this application."""
    with _CONFIG_LOCK:
        frontend_logger = logging.getLogger("fia.frontend")
        _remove_managed_handlers(frontend_logger)
        _remove_managed_handlers(logging.getLogger())
