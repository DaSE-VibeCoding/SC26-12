from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


LOGGER = logging.getLogger(__name__)
CNINFO_SEARCH_PAGE_URL = (
    "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
)
CNINFO_STOCK_LIST_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_PDF_BASE_URL = "https://static.cninfo.com.cn/"
REPORT_YEARS = (2021, 2022, 2023, 2024, 2025)
QUERY_START_DATE = date(2021, 1, 1)
QUERY_END_DATE = date(2026, 6, 30)
ANNUAL_REPORT_CATEGORY = "category_ndbg_szsh"
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_PDF_BYTES = 300 * 1024 * 1024
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

_ANNUAL_REPORT_RE = re.compile(
    r"(?P<year>20\d{2})年年度报告(?P<corrected>（更正后）)?$",
    re.IGNORECASE,
)
_EXCLUDED_TITLE_MARKERS = ("半年度报告", "摘要", "英文", "英语", "english")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class CninfoDownloadError(RuntimeError):
    """巨潮检索、筛选或下载无法得到可信五年年报时抛出。"""


def normalize_stock_code(value: Any) -> str:
    code = "" if value is None else str(value).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("股票代码必须是 6 位数字")
    return code


def clean_announcement_title(value: Any) -> str:
    return _HTML_TAG_RE.sub("", str(value or "")).strip()


def is_full_annual_report(title: str, years: tuple[int, ...] = REPORT_YEARS) -> bool:
    normalized = clean_announcement_title(title)
    lowered = normalized.lower()
    match = _ANNUAL_REPORT_RE.search(normalized)
    return bool(
        match
        and int(match.group("year")) in years
        and not any(marker in lowered for marker in _EXCLUDED_TITLE_MARKERS)
    )


def _safe_component(value: str) -> str:
    cleaned = _INVALID_PATH_CHARS_RE.sub("_", value).strip(" ._")
    return cleaned[:80] or "未知公司"


def _exchange_parameters(stock_code: str, org_id: str) -> tuple[str, str]:
    if org_id.startswith("gfbj") or stock_code.startswith(("4", "8", "92")):
        return "third", "neeq"
    if stock_code.startswith(("5", "6", "9")):
        return "sse", "sse"
    return "szse", "szse"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CninfoAnnualReportClient:
    """使用巨潮官网当前公告查询接口检索并归档完整年度报告。"""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.timeout = timeout
        self._opener = opener or request.urlopen

    @staticmethod
    def _headers(*, accept: str = "application/json, text/plain, */*") -> dict[str, str]:
        return {
            "Accept": accept,
            "Origin": "https://www.cninfo.com.cn",
            "Referer": CNINFO_SEARCH_PAGE_URL,
            "User-Agent": "Mozilla/5.0 FinancialIndicatorsAssistant/3.0",
        }

    def _read_response(self, req: request.Request, maximum: int) -> bytes:
        try:
            with self._opener(req, timeout=self.timeout) as response:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > maximum:
                    raise CninfoDownloadError("巨潮响应超过允许大小，已停止读取")
                payload = response.read(maximum + 1)
        except CninfoDownloadError:
            raise
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise CninfoDownloadError(f"巨潮请求失败：{type(exc).__name__}: {exc}") from exc
        if len(payload) > maximum:
            raise CninfoDownloadError("巨潮响应超过允许大小，已停止读取")
        return payload

    def _request_json(self, req: request.Request) -> dict[str, Any]:
        raw = self._read_response(req, MAX_JSON_BYTES)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CninfoDownloadError("巨潮返回内容不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise CninfoDownloadError("巨潮返回结构发生变化：预期为 JSON 对象")
        return payload

    def _resolve_stock(self, stock_code: str) -> dict[str, str]:
        req = request.Request(CNINFO_STOCK_LIST_URL, headers=self._headers(), method="GET")
        payload = self._request_json(req)
        for item in payload.get("stockList") or []:
            if isinstance(item, dict) and str(item.get("code") or "").zfill(6) == stock_code:
                org_id = str(item.get("orgId") or "")
                if org_id:
                    return {
                        "stock_code": stock_code,
                        "company_name": str(item.get("zwjc") or f"股票{stock_code}"),
                        "org_id": org_id,
                    }
        raise CninfoDownloadError(f"巨潮股票清单中未找到代码：{stock_code}")

    def query_annual_reports(
        self,
        stock_code: Any,
        years: tuple[int, ...] = REPORT_YEARS,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        code = normalize_stock_code(stock_code)
        LOGGER.info("巨潮年报查询开始：stock_code=%s years=%s", code, list(years))
        stock = self._resolve_stock(code)
        column, plate = _exchange_parameters(code, stock["org_id"])
        LOGGER.info(
            "巨潮股票解析完成：stock_code=%s company=%s org_id=%s column=%s plate=%s",
            code,
            stock["company_name"],
            stock["org_id"],
            column,
            plate,
        )
        start_date = QUERY_START_DATE
        end_date = QUERY_END_DATE
        candidates: list[dict[str, Any]] = []
        raw_page_counts: list[int] = []

        for page_number in range(1, 101):
            parameters = {
                "pageNum": page_number,
                "pageSize": 30,
                "column": column,
                "tabName": "fulltext",
                "stock": f"{code},{stock['org_id']}",
                "searchkey": "",
                "secid": "",
                "plate": plate,
                "category": ANNUAL_REPORT_CATEGORY,
                "trade": "",
                "seDate": f"{start_date.isoformat()}~{end_date.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            body = parse.urlencode(parameters).encode("utf-8")
            headers = {
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            }
            req = request.Request(CNINFO_QUERY_URL, data=body, headers=headers, method="POST")
            payload = self._request_json(req)
            page_items = payload.get("announcements") or []
            if not isinstance(page_items, list):
                raise CninfoDownloadError("巨潮公告查询结构发生变化：announcements 不是列表")
            candidates.extend(item for item in page_items if isinstance(item, dict))
            raw_page_counts.append(len(page_items))
            if not payload.get("hasMore"):
                break
        else:  # pragma: no cover - defensive pagination boundary
            raise CninfoDownloadError("巨潮公告分页超过 100 页，已停止查询")

        normalized: list[dict[str, Any]] = []
        excluded_titles: list[str] = []
        for item in candidates:
            title = clean_announcement_title(item.get("announcementTitle"))
            if str(item.get("secCode") or "").zfill(6) != code or not is_full_annual_report(title, years):
                excluded_titles.append(title)
                continue
            match = _ANNUAL_REPORT_RE.search(title)
            relative_url = str(item.get("adjunctUrl") or "").lstrip("/")
            timestamp = item.get("announcementTime")
            if match is None or not relative_url or not isinstance(timestamp, (int, float)):
                raise CninfoDownloadError(f"巨潮完整年报记录缺少年份、时间或下载地址：{title}")
            published = datetime.fromtimestamp(timestamp / 1000, tz=CHINA_TZ)
            normalized.append(
                {
                    "announcement_id": str(item.get("announcementId") or ""),
                    "stock_code": code,
                    "company_name": str(item.get("secName") or stock["company_name"]),
                    "title": title,
                    "report_year": int(match.group("year")),
                    "published_at": published.isoformat(timespec="seconds"),
                    "source_url": parse.urljoin(CNINFO_PDF_BASE_URL, relative_url),
                    "is_correction": bool(match.group("corrected")),
                    # 保留旧字段，避免既有清单读取方因字段消失而出错。
                    "is_revision": bool(match.group("corrected")),
                }
            )

        selected: list[dict[str, Any]] = []
        for year in years:
            options = [item for item in normalized if item["report_year"] == year]
            if not options:
                continue
            selected.append(
                max(
                    options,
                    key=lambda item: (
                        item["is_correction"],
                        item["published_at"],
                        item["announcement_id"],
                    ),
                )
            )
        selected.sort(key=lambda item: item["report_year"])
        audit = {
            "source_site": "巨潮资讯网",
            "source_page": CNINFO_SEARCH_PAGE_URL,
            "stock_code": code,
            "company_name": stock["company_name"],
            "org_id": stock["org_id"],
            "query_keyword": "",
            "query_category": "年报",
            "query_category_code": ANNUAL_REPORT_CATEGORY,
            "allowed_title_suffixes": ["YYYY年年度报告", "YYYY年年度报告（更正后）"],
            "same_year_preference": "更正后优先，其次取发布时间较晚者",
            "query_date_range": f"{start_date.isoformat()}~{end_date.isoformat()}",
            "candidate_count": len(candidates),
            "full_report_candidate_count": len(normalized),
            "selected_count": len(selected),
            "excluded_titles": [title for title in excluded_titles if title],
            "page_item_counts": raw_page_counts,
        }
        LOGGER.info(
            "巨潮年报筛选完成：stock_code=%s raw=%d full=%d selected_years=%s excluded=%d",
            code,
            len(candidates),
            len(normalized),
            [item["report_year"] for item in selected],
            len(excluded_titles),
        )
        return selected, audit

    @staticmethod
    def _cached_report_is_current(
        target: Path,
        previous: dict[str, Any] | None,
        source_url: str,
    ) -> bool:
        if not previous or previous.get("source_url") != source_url or not target.is_file():
            return False
        if target.stat().st_size != int(previous.get("size_bytes") or -1):
            return False
        try:
            with target.open("rb") as handle:
                return handle.read(5) == b"%PDF-"
        except OSError:
            return False

    def _download_pdf(self, source_url: str, target: Path) -> tuple[int, str]:
        parsed_url = parse.urlparse(source_url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "static.cninfo.com.cn":
            raise CninfoDownloadError(f"拒绝非巨潮官方 PDF 地址：{source_url}")
        req = request.Request(
            source_url,
            headers=self._headers(accept="application/pdf,application/octet-stream;q=0.9,*/*;q=0.8"),
            method="GET",
        )
        LOGGER.info("巨潮 PDF 下载开始：target=%s source=%s", target, source_url)
        descriptor, temporary = tempfile.mkstemp(prefix=".annual-report-", suffix=".part", dir=target.parent)
        total = 0
        digest = hashlib.sha256()
        try:
            try:
                with self._opener(req, timeout=max(self.timeout, 90.0)) as response, os.fdopen(
                    descriptor, "wb"
                ) as output:
                    declared = response.headers.get("Content-Length")
                    if declared and int(declared) > MAX_PDF_BYTES:
                        raise CninfoDownloadError("单份年报超过 300MB，已停止下载")
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_PDF_BYTES:
                            raise CninfoDownloadError("单份年报超过 300MB，已停止下载")
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            except (error.URLError, TimeoutError, OSError, ValueError) as exc:
                raise CninfoDownloadError(f"年报下载失败：{type(exc).__name__}: {exc}") from exc
            temporary_path = Path(temporary)
            with temporary_path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise CninfoDownloadError("巨潮下载内容不是有效 PDF")
            os.replace(temporary, target)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        LOGGER.info("巨潮 PDF 下载完成：target=%s bytes=%d sha256=%s", target, total, digest.hexdigest())
        return total, digest.hexdigest()

    def fetch_and_archive(
        self,
        stock_code: Any,
        archive_root: Path,
        years: tuple[int, ...] = REPORT_YEARS,
    ) -> tuple[list[Path], dict[str, Any]]:
        reports, audit = self.query_annual_reports(stock_code, years)
        by_year = {item["report_year"]: item for item in reports}
        missing = [year for year in years if year not in by_year]
        if missing:
            missing_text = "、".join(str(year) for year in missing)
            raise CninfoDownloadError(
                f"巨潮未找到以下完整中文版年度报告：{missing_text}。"
                "已排除半年度报告、摘要和英文版，未使用不完整文件继续分析。"
            )

        code = normalize_stock_code(stock_code)
        company_name = reports[-1]["company_name"] or audit["company_name"]
        company_component = _safe_component(company_name)
        archive_dir = Path(archive_root).resolve() / f"{code}_{company_component}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        LOGGER.info("年报归档开始：stock_code=%s company=%s archive=%s", code, company_name, archive_dir)
        manifest_path = archive_dir / "download_manifest.json"
        previous_reports: dict[int, dict[str, Any]] = {}
        if manifest_path.is_file():
            try:
                previous_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                previous_reports = {
                    int(item["report_year"]): item
                    for item in previous_payload.get("reports") or []
                    if isinstance(item, dict) and str(item.get("report_year", "")).isdigit()
                }
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError):
                previous_reports = {}

        paths: list[Path] = []
        archived_reports: list[dict[str, Any]] = []
        for report in reports:
            year = int(report["report_year"])
            target = archive_dir / f"{code}_{company_component}_{year}年年度报告.pdf"
            previous = previous_reports.get(year)
            reused = self._cached_report_is_current(target, previous, report["source_url"])
            if reused:
                size_bytes = target.stat().st_size
                sha256 = str(previous.get("sha256") or _sha256_file(target))
                LOGGER.info("复用已校验年报：year=%d file=%s bytes=%d", year, target, size_bytes)
            else:
                size_bytes, sha256 = self._download_pdf(report["source_url"], target)
            paths.append(target)
            archived_reports.append(
                {
                    **report,
                    "archive_file": target.name,
                    "local_path": str(target),
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                    "reused": reused,
                }
            )

        manifest = {
            "schema_version": "1.0",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_site": "巨潮资讯网",
            "source_page": CNINFO_SEARCH_PAGE_URL,
            "stock_code": code,
            "company_name": company_name,
            "years": list(years),
            "archive_dir": str(archive_dir),
            "reports": archived_reports,
            "query_audit": audit,
        }
        _atomic_write_json(manifest_path, manifest)
        LOGGER.info(
            "年报归档完成：stock_code=%s files=%d downloaded=%d reused=%d manifest=%s",
            code,
            len(archived_reports),
            sum(not item["reused"] for item in archived_reports),
            sum(bool(item["reused"]) for item in archived_reports),
            manifest_path,
        )
        return paths, manifest
