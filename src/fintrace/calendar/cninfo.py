from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from fintrace.shared.exceptions import FinTraceError

CNINFO_PDF_BASE_URL = "https://static.cninfo.com.cn/"
CNINFO_HOME_URL = "https://www.cninfo.com.cn/new/index.jsp"
ANNUAL_REPORT_PATTERN = re.compile(
    r"(?P<year>20\d{2})年年度报告(?:[（(](?:修订版|修订稿|更新后)[）)])?$"
)
EXCLUDED_TITLE_MARKERS = ("摘要", "半年度", "英文", "english")
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class CninfoQueryError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="cninfo_query_error", **kwargs)


def _headers(source_url: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.cninfo.com.cn",
        "Referer": source_url,
        "User-Agent": "Mozilla/5.0 FinTrace/0.1",
    }


def _exchange_parameters(company_code: str) -> tuple[str, str]:
    if company_code.startswith(("5", "6", "9")):
        return "sse", "sse"
    return "szse", "szse"


def _request_json(
    client: httpx.Client, method: str, url: str, **kwargs: Any
) -> dict[str, Any]:
    try:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CninfoQueryError(
            f"Cninfo request failed: {exc}",
            step="query_cninfo_annual_reports",
            details={"url": url},
        ) from exc
    if not isinstance(payload, dict):
        raise CninfoQueryError(
            "Cninfo returned an unexpected response.",
            step="query_cninfo_annual_reports",
            details={"url": url},
        )
    return payload


def is_full_annual_report(title: str) -> bool:
    normalized = re.sub(r"<[^>]+>", "", title).strip()
    lowered = normalized.lower()
    return bool(ANNUAL_REPORT_PATTERN.search(normalized)) and not any(
        marker in lowered for marker in EXCLUDED_TITLE_MARKERS
    )


def _normalize_announcement(item: dict[str, Any]) -> dict[str, Any]:
    title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or "")).strip()
    match = ANNUAL_REPORT_PATTERN.search(title)
    timestamp = item.get("announcementTime")
    if not match or not isinstance(timestamp, (int, float)):
        raise CninfoQueryError(
            "Cninfo announcement is missing its report year or publication time.",
            step="normalize_cninfo_results",
            details={"announcement": item},
        )
    published_at = datetime.fromtimestamp(timestamp / 1000, tz=CHINA_TZ)
    relative_url = str(item.get("adjunctUrl") or "").lstrip("/")
    return {
        "announcement_id": str(item.get("announcementId") or ""),
        "company_code": str(item.get("secCode") or "").zfill(6),
        "company_name": str(item.get("secName") or ""),
        "announcement_title": title,
        "report_year": int(match.group("year")),
        "report_period": date(int(match.group("year")), 12, 31).isoformat(),
        "published_at": published_at.isoformat(),
        "event_date": published_at.date().isoformat(),
        "source_url": f"{CNINFO_PDF_BASE_URL}{relative_url}" if relative_url else None,
    }


def query_annual_reports(
    company_code: str,
    publication_year: int,
    *,
    client: httpx.Client | None = None,
    source_url: str = CNINFO_HOME_URL,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock_list_url = urljoin(source_url, "/new/data/szse_stock.json")
    query_url = urljoin(source_url, "/new/hisAnnouncement/query")
    owned_client = client is None
    active_client = client or httpx.Client(
        headers=_headers(source_url), timeout=30.0, follow_redirects=True
    )
    raw_pages: list[dict[str, Any]] = []
    try:
        payload = _request_json(active_client, "GET", stock_list_url)
        org_id = next(
            (
                str(stock["orgId"])
                for stock in payload.get("stockList") or []
                if str(stock.get("code", "")).zfill(6) == company_code and stock.get("orgId")
            ),
            None,
        )
        if org_id is None:
            raise CninfoQueryError(
                f"Stock code was not found in Cninfo: {company_code}",
                step="resolve_cninfo_stock",
                details={"company_code": company_code},
            )
        column, plate = _exchange_parameters(company_code)
        page = 1
        while True:
            payload = _request_json(
                active_client,
                "POST",
                query_url,
                data={
                    "pageNum": page,
                    "pageSize": 30,
                    "column": column,
                    "tabName": "fulltext",
                    "stock": f"{company_code},{org_id}",
                    "searchkey": "",
                    "secid": "",
                    "plate": plate,
                    "category": "category_ndbg_szsh",
                    "trade": "",
                    "seDate": f"{publication_year}-01-01~{publication_year}-12-31",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                },
            )
            raw_pages.append(payload)
            if not payload.get("hasMore"):
                break
            page += 1
            if page > 100:
                raise CninfoQueryError(
                    "Cninfo pagination exceeded the safety limit.",
                    step="query_cninfo_annual_reports",
                )
    finally:
        if owned_client:
            active_client.close()

    candidates = [item for page_data in raw_pages for item in page_data.get("announcements") or []]
    selected = [
        _normalize_announcement(item)
        for item in candidates
        if str(item.get("secCode") or "").zfill(6) == company_code
        and is_full_annual_report(str(item.get("announcementTitle") or ""))
    ]
    selected.sort(key=lambda item: (item["published_at"], item["announcement_id"]))
    audit = {
        "source_site": "巨潮资讯网",
        "source_url": source_url,
        "company_code": company_code,
        "publication_year": publication_year,
        "org_id": org_id,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "excluded_titles": [
            str(item.get("announcementTitle") or "")
            for item in candidates
            if not is_full_annual_report(str(item.get("announcementTitle") or ""))
        ],
        "raw_pages": raw_pages,
    }
    return selected, audit
