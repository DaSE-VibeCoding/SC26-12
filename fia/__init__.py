"""Financial indicator extraction and evidence viewer package.

Keep package initialization dependency-free so ``start_app.py`` can configure
logging before the project virtual environment and PDF libraries are loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .service import AnalysisService

__all__ = ["AnalysisService"]


def __getattr__(name: str) -> Any:
    if name == "AnalysisService":
        from .service import AnalysisService

        return AnalysisService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
