"""Disclosure-time analysis service used by the combined application."""

from __future__ import annotations

import os
from pathlib import Path

from .domain import ValidationError
from .sources import IndustryPeerResolver, SourceDataError
from .storage import DisclosureService


def create_disclosure_service(project_root: Path) -> DisclosureService:
    """Create the disclosure service with paths portable across installations."""

    disclosure_root = project_root / "disclosure"
    lookup_root = Path(
        os.environ.get("DISCLOSURE_LOOKUP_ROOT", str(project_root.parent / "lookupfiles"))
    )
    data_file = Path(
        os.environ.get(
            "DISCLOSURE_DATA_FILE",
            str(disclosure_root / "data" / "disclosure_db.json"),
        )
    )
    history_file = Path(
        os.environ.get(
            "DISCLOSURE_HISTORY_FILE",
            str(lookup_root / "DisclosureTime" / "DisclosureTime_History.xlsx"),
        )
    )
    industry_file = Path(
        os.environ.get(
            "DISCLOSURE_INDUSTRY_FILE",
            str(lookup_root / "STK_LISTEDCOINFOANL_20200101_20251231.xlsx"),
        )
    )
    total_assets_file = Path(
        os.environ.get(
            "DISCLOSURE_TOTAL_ASSETS_FILE",
            str(disclosure_root / "data" / "peer_total_assets.json"),
        )
    )
    offline = os.environ.get("DISCLOSURE_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return DisclosureService(
        data_file=data_file,
        history_file=history_file,
        allow_network=not offline,
        peer_resolver=IndustryPeerResolver(industry_file, total_assets_file),
    )


__all__ = [
    "DisclosureService",
    "SourceDataError",
    "ValidationError",
    "create_disclosure_service",
]
