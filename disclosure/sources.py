"""真实数据源适配器：历史 Excel 与巨潮资讯网官方接口。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .domain import (
    REPORT_META,
    YEARS,
    ValidationError,
    business_key,
    market_for_stock,
    normalize_iso_date,
    normalize_stock_code,
    normalize_year,
    period_to_year_type,
)


XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXPECTED_HEADERS = (
    "Scode",
    "Coname",
    "Date",
    "FrstAppt",
    "FrstChgDt",
    "ScndChgDt",
    "ThirdChgDt",
    "ActlDt",
)
DATE_FIELDS = (
    "first_reservation_date",
    "first_change_date",
    "second_change_date",
    "third_change_date",
    "actual_disclosure_date",
)

CNINFO_PAGE_URL = "https://www.cninfo.com.cn/new/commonUrl?url=data/yuyuepilu"
CNINFO_BASE_URL = "https://www.cninfo.com.cn/new/information"
CNINFO_MARKETS = ("szmb", "szcn", "shmb", "shkcp")


class SourceDataError(RuntimeError):
    """数据源不可用、结构变化或返回不可信时抛出。"""


def _q(tag: str) -> str:
    return f"{{{XML_NS}}}{tag}"


def _column_index(reference: str) -> int:
    letters = "".join(ch for ch in reference if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value - 1


class HistoryWorkbook:
    """用 Python 标准库流式读取权威历史工作簿。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock = threading.RLock()
        self._loaded = False
        self._records: dict[str, dict[str, Any]] = {}
        self._companies: dict[str, str] = {}
        self._max_period: str | None = None
        self._audit: dict[str, Any] = {}

    @staticmethod
    def _shared_strings(archive: ZipFile) -> list[str]:
        try:
            stream = archive.open("xl/sharedStrings.xml")
        except KeyError as exc:
            raise SourceDataError("历史 Excel 缺少 xl/sharedStrings.xml") from exc
        strings: list[str] = []
        with stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag == _q("si"):
                    strings.append("".join(node.text or "" for node in element.iter(_q("t"))))
                    element.clear()
        return strings

    @staticmethod
    def _cell_text(cell: ET.Element, shared: list[str]) -> str:
        cell_type = cell.attrib.get("t")
        value_node = cell.find(_q("v"))
        raw = "" if value_node is None or value_node.text is None else value_node.text
        if cell_type == "s" and raw:
            try:
                return shared[int(raw)]
            except (ValueError, IndexError) as exc:
                raise SourceDataError("历史 Excel 的共享字符串索引无效") from exc
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.iter(_q("t")))
        return raw

    def _load(self) -> None:
        if not self.path.is_file():
            raise SourceDataError(f"找不到历史 Excel：{self.path}")

        started = time.perf_counter()
        source_rows = 0
        skipped_invalid_period = 0
        skipped_invalid_date = 0
        headers: tuple[str, ...] | None = None
        records: dict[str, dict[str, Any]] = {}
        companies: dict[str, str] = {}
        max_period: str | None = None

        try:
            with ZipFile(self.path) as archive:
                shared = self._shared_strings(archive)
                try:
                    sheet_stream = archive.open("xl/worksheets/sheet1.xml")
                except KeyError as exc:
                    raise SourceDataError("历史 Excel 缺少第一个工作表") from exc

                with sheet_stream:
                    for _, row in ET.iterparse(sheet_stream, events=("end",)):
                        if row.tag != _q("row"):
                            continue
                        row_number = int(row.attrib.get("r", "0") or 0)
                        values = [""] * 8
                        for cell in row.findall(_q("c")):
                            index = _column_index(cell.attrib.get("r", ""))
                            if 0 <= index < len(values):
                                values[index] = self._cell_text(cell, shared).strip()

                        if row_number == 1:
                            headers = tuple(values)
                        elif row_number >= 3:
                            source_rows += 1
                            code, name, period, *date_values = values
                            if not (
                                len(period) == 10
                                and period[:4].isdigit()
                                and period[4] == "-"
                                and period[7] == "-"
                            ):
                                skipped_invalid_period += 1
                                row.clear()
                                continue
                            try:
                                year, kind = period_to_year_type(period)
                            except ValidationError:
                                if period[:4].isdigit() and int(period[:4]) in YEARS:
                                    skipped_invalid_period += 1
                                row.clear()
                                continue
                            try:
                                code = normalize_stock_code(code)
                                normalized_dates = [
                                    normalize_iso_date(value, field)
                                    for field, value in zip(DATE_FIELDS, date_values, strict=True)
                                ]
                            except ValidationError:
                                skipped_invalid_date += 1
                                row.clear()
                                continue

                            record: dict[str, Any] = {
                                "stock_code": code,
                                "company_name": name or f"股票 {code}",
                                "short_name": name or f"股票 {code}",
                                "report_year": year,
                                "report_type": kind,
                                **dict(zip(DATE_FIELDS, normalized_dates, strict=True)),
                                "source_type": "HISTORY_XLSX",
                                "source_url": None,
                                "source_file": str(self.path),
                                "source_row_number": row_number,
                                "source_period": period,
                                "source_modified_at": datetime.fromtimestamp(
                                    self.path.stat().st_mtime
                                ).astimezone().isoformat(timespec="seconds"),
                            }
                            key = business_key(record)
                            if key in records:
                                raise SourceDataError(f"历史 Excel 存在重复业务键：{key}")
                            records[key] = record
                            companies[code] = record["company_name"]
                            max_period = period if max_period is None or period > max_period else max_period
                        row.clear()
        except (BadZipFile, ET.ParseError, OSError) as exc:
            raise SourceDataError(f"无法解析历史 Excel：{self.path}") from exc

        if headers != EXPECTED_HEADERS:
            raise SourceDataError(
                "历史 Excel 表头与预期不一致；为防止列错位，已停止导入。"
                f"实际表头：{headers}"
            )
        if not records:
            raise SourceDataError("历史 Excel 中没有找到 2022—2026 的有效记录")

        self._records = records
        self._companies = companies
        self._max_period = max_period
        self._audit = {
            "source_file": str(self.path),
            "source_size_bytes": self.path.stat().st_size,
            "source_rows": source_rows,
            "scope_records": len(records),
            "scope_companies": len(companies),
            "skipped_invalid_period_rows": skipped_invalid_period,
            "skipped_invalid_date_rows": skipped_invalid_date,
            "duplicate_business_keys": 0,
            "latest_period": max_period,
            "loaded_seconds": round(time.perf_counter() - started, 3),
        }
        self._loaded = True

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self._load()

    @property
    def max_period(self) -> str:
        self.ensure_loaded()
        if self._max_period is None:  # pragma: no cover - protected by _load
            raise SourceDataError("历史 Excel 没有有效报告期")
        return self._max_period

    @property
    def audit(self) -> dict[str, Any]:
        self.ensure_loaded()
        return dict(self._audit)

    def company_name(self, stock_code: str) -> str | None:
        self.ensure_loaded()
        return self._companies.get(normalize_stock_code(stock_code))

    def records_for_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        self.ensure_loaded()
        wanted = set(codes)
        return [dict(item) for item in self._records.values() if item["stock_code"] in wanted]

    def all_records(self) -> list[dict[str, Any]]:
        """返回范围内全部记录的副本，供完整性审计使用。"""

        self.ensure_loaded()
        return [dict(item) for item in self._records.values()]

    def record(self, stock_code: str, year: int, kind: str) -> dict[str, Any] | None:
        self.ensure_loaded()
        item = self._records.get(f"{stock_code}|{year}|{kind}")
        return None if item is None else dict(item)


class IndustryPeerResolver:
    """按行业代码和总资产，为目标公司自动选择五家同行。"""

    EXPECTED_INDUSTRY_HEADERS = (
        "Symbol",
        "ShortName",
        "EndDate",
        "ListedCoID",
        "SecurityID",
        "IndustryName",
        "IndustryCode",
    )

    def __init__(self, industry_file: str | Path, total_assets_file: str | Path):
        self.industry_file = Path(industry_file).resolve()
        self.total_assets_file = Path(total_assets_file).resolve()
        self._lock = threading.RLock()
        self._loaded = False
        self._snapshots: dict[int, dict[str, dict[str, str]]] = {}
        self._assets: dict[str, dict[int, Decimal]] = {}
        self._asset_metadata: dict[str, Any] = {}
        self._audit: dict[str, Any] = {}

    def configuration_status(self) -> dict[str, Any]:
        return {
            "industry_file": str(self.industry_file),
            "industry_file_exists": self.industry_file.is_file(),
            "total_assets_file": str(self.total_assets_file),
            "total_assets_file_exists": self.total_assets_file.is_file(),
        }

    def _load_industries(self) -> tuple[dict[int, dict[str, dict[str, str]]], dict[str, Any]]:
        if not self.industry_file.is_file():
            raise SourceDataError(f"找不到上市公司行业 Excel：{self.industry_file}")

        snapshots: dict[int, dict[str, dict[str, str]]] = {}
        headers: tuple[str, ...] | None = None
        source_rows = 0
        skipped_rows = 0
        try:
            with ZipFile(self.industry_file) as archive:
                shared = HistoryWorkbook._shared_strings(archive)
                with archive.open("xl/worksheets/sheet1.xml") as sheet_stream:
                    for _, row in ET.iterparse(sheet_stream, events=("end",)):
                        if row.tag != _q("row"):
                            continue
                        row_number = int(row.attrib.get("r", "0") or 0)
                        values = [""] * len(self.EXPECTED_INDUSTRY_HEADERS)
                        for cell in row.findall(_q("c")):
                            index = _column_index(cell.attrib.get("r", ""))
                            if 0 <= index < len(values):
                                values[index] = HistoryWorkbook._cell_text(cell, shared).strip()

                        if row_number == 1:
                            headers = tuple(values)
                        elif row_number >= 4:
                            source_rows += 1
                            code, short_name, end_date, _, _, industry_name, industry_code = values
                            if not (
                                len(end_date) >= 4
                                and end_date[:4].isdigit()
                                and industry_code
                            ):
                                skipped_rows += 1
                                row.clear()
                                continue
                            try:
                                code = normalize_stock_code(code)
                            except ValidationError:
                                skipped_rows += 1
                                row.clear()
                                continue
                            year = int(end_date[:4])
                            by_code = snapshots.setdefault(year, {})
                            if code in by_code:
                                raise SourceDataError(f"行业 Excel 存在重复股票代码/年度：{code} / {year}")
                            by_code[code] = {
                                "stock_code": code,
                                "short_name": short_name or f"股票 {code}",
                                "industry_name": industry_name,
                                "industry_code": industry_code,
                            }
                        row.clear()
        except (BadZipFile, ET.ParseError, KeyError, OSError) as exc:
            raise SourceDataError(f"无法解析上市公司行业 Excel：{self.industry_file}") from exc

        if headers != self.EXPECTED_INDUSTRY_HEADERS:
            raise SourceDataError(
                "上市公司行业 Excel 前七列表头与预期不一致；为防止列错位，已停止导入。"
                f"实际表头：{headers}"
            )
        if not snapshots:
            raise SourceDataError("上市公司行业 Excel 没有可用的 IndustryCode 记录")
        return snapshots, {
            "source_file": str(self.industry_file),
            "source_size_bytes": self.industry_file.stat().st_size,
            "source_rows": source_rows,
            "valid_records": sum(len(items) for items in snapshots.values()),
            "skipped_rows": skipped_rows,
            "year_min": min(snapshots),
            "year_max": max(snapshots),
        }

    def _load_total_assets(self) -> tuple[dict[str, dict[int, Decimal]], dict[str, Any]]:
        if not self.total_assets_file.is_file():
            raise SourceDataError(f"找不到总资产数据：{self.total_assets_file}")
        try:
            payload = json.loads(self.total_assets_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceDataError(f"无法读取总资产数据：{self.total_assets_file}") from exc
        if (
            payload.get("schema_version") != 1
            or payload.get("metric") != "TotalAsset"
            or payload.get("unit") != "元"
            or not isinstance(payload.get("assets_by_code"), dict)
        ):
            raise SourceDataError("总资产数据结构或计量单位不符合预期")

        assets: dict[str, dict[int, Decimal]] = {}
        for raw_code, raw_values in payload["assets_by_code"].items():
            if not isinstance(raw_values, dict):
                raise SourceDataError(f"总资产公司记录不是对象：{raw_code}")
            try:
                code = normalize_stock_code(raw_code)
            except ValidationError as exc:
                raise SourceDataError(f"总资产数据包含无效股票代码：{raw_code}") from exc
            yearly: dict[int, Decimal] = {}
            for raw_year, raw_value in raw_values.items():
                try:
                    year = int(raw_year)
                    value = Decimal(str(raw_value))
                except (ValueError, InvalidOperation) as exc:
                    raise SourceDataError(f"总资产数据无法解析：{code} / {raw_year}") from exc
                if value > 0:
                    yearly[year] = value
            if yearly:
                assets[code] = yearly
        if not assets:
            raise SourceDataError("总资产数据没有有效记录")
        metadata = {key: value for key, value in payload.items() if key != "assets_by_code"}
        metadata["data_file"] = str(self.total_assets_file)
        return assets, metadata

    def _load(self) -> None:
        started = time.perf_counter()
        snapshots, industry_audit = self._load_industries()
        assets, asset_metadata = self._load_total_assets()
        self._snapshots = snapshots
        self._assets = assets
        self._asset_metadata = asset_metadata
        self._audit = {
            "industry": industry_audit,
            "total_assets": dict(asset_metadata),
            "loaded_seconds": round(time.perf_counter() - started, 3),
        }
        self._loaded = True

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self._load()

    @property
    def audit(self) -> dict[str, Any]:
        self.ensure_loaded()
        return {
            "industry": dict(self._audit["industry"]),
            "total_assets": dict(self._audit["total_assets"]),
            "loaded_seconds": self._audit["loaded_seconds"],
        }

    def _latest_asset(self, code: str, maximum_year: int) -> tuple[int, Decimal] | None:
        values = self._assets.get(code, {})
        years = [year for year in values if year <= maximum_year]
        if not years:
            return None
        year = max(years)
        return year, values[year]

    def resolve(self, stock_code: Any, report_year: Any, limit: int = 5) -> dict[str, Any]:
        code = normalize_stock_code(stock_code)
        year = normalize_year(report_year)
        self.ensure_loaded()

        snapshot_year = next(
            (
                candidate_year
                for candidate_year in sorted(self._snapshots, reverse=True)
                if candidate_year <= year and code in self._snapshots[candidate_year]
            ),
            None,
        )
        common = {
            "method": "same_industry_top_total_assets",
            "target_code": code,
            "requested_report_year": year,
            "required_peer_count": limit,
            "industry_source_file": str(self.industry_file),
            "total_assets_data_file": str(self.total_assets_file),
            "total_assets_source_file": self._asset_metadata.get("source_file"),
            "total_assets_unit": self._asset_metadata.get("unit", "元"),
        }
        if snapshot_year is None:
            return {
                **common,
                "automatic_status": "target_not_found",
                "automatic_reason": "行业 Excel 中未找到目标公司的可用 IndustryCode，未自动指定同行。",
                "peer_codes": [],
                "selected_peers": [],
                "candidate_company_count": 0,
                "rankable_company_count": 0,
            }

        target = self._snapshots[snapshot_year][code]
        candidates = [
            item
            for item_code, item in self._snapshots[snapshot_year].items()
            if item_code != code and item["industry_code"] == target["industry_code"]
        ]
        asset_year_ceiling = min(year, int(self._asset_metadata["year_max"]))
        ranked: list[dict[str, Any]] = []
        for candidate in candidates:
            asset = self._latest_asset(candidate["stock_code"], asset_year_ceiling)
            if asset is None:
                continue
            asset_year, total_assets = asset
            ranked.append(
                {
                    **candidate,
                    "asset_year": asset_year,
                    "total_assets": format(total_assets, "f"),
                }
            )
        ranked.sort(key=lambda item: (-Decimal(item["total_assets"]), item["stock_code"]))
        selected = ranked[:limit] if len(ranked) >= limit else []
        status = "resolved" if selected else "insufficient_candidates"
        reason = (
            f"按 {snapshot_year} 年 IndustryCode={target['industry_code']} 匹配同行，"
            f"并按不晚于 {asset_year_ceiling} 年的最新总资产降序选择前 {limit} 家。"
            if selected
            else (
                f"{snapshot_year} 年 IndustryCode={target['industry_code']} 下共有 {len(candidates)} 家其他公司，"
                f"其中仅 {len(ranked)} 家具有可用总资产，少于 {limit} 家，未自动指定同行。"
            )
        )
        return {
            **common,
            "automatic_status": status,
            "automatic_reason": reason,
            "industry_code": target["industry_code"],
            "industry_name": target["industry_name"],
            "industry_year": snapshot_year,
            "asset_year_ceiling": asset_year_ceiling,
            "candidate_company_count": len(candidates),
            "rankable_company_count": len(ranked),
            "peer_codes": [item["stock_code"] for item in selected],
            "selected_peers": selected,
        }


class RawResponseCache:
    """把每次巨潮响应原样保存到本地，供复核与追溯。"""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(
        self,
        endpoint: str,
        parameters: dict[str, Any],
        response_text: str | None,
        error_message: str | None = None,
    ) -> Path:
        received_at = datetime.now().astimezone().isoformat(timespec="microseconds")
        digest = hashlib.sha256(
            json.dumps(parameters, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        safe_time = received_at.replace(":", "-").replace("+", "_")
        filename = f"{safe_time}_{endpoint}_{digest}.json"
        target = self.directory / filename
        payload = {
            "received_at": received_at,
            "source": "CNINFO_OFFICIAL",
            "url": f"{CNINFO_BASE_URL}/{endpoint}",
            "request_parameters": parameters,
            "success": error_message is None,
            "error": error_message,
            "response_text": response_text,
        }
        with self._lock:
            descriptor, temporary = tempfile.mkstemp(prefix=".cninfo-", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
        return target


class CninfoClient:
    """巨潮预约披露官方页面所使用接口的最小只读客户端。"""

    def __init__(self, raw_cache_dir: str | Path, timeout: float = 15.0):
        self.raw_cache = RawResponseCache(raw_cache_dir)
        self.timeout = timeout

    def _post_json(self, endpoint: str, parameters: dict[str, Any]) -> tuple[Any, Path]:
        body = parse.urlencode(parameters).encode("utf-8")
        req = request.Request(
            f"{CNINFO_BASE_URL}/{endpoint}",
            data=body,
            method="POST",
            headers={
                "User-Agent": "Mozilla/5.0 DisclosureTimeAssistant/3.0",
                "Referer": CNINFO_PAGE_URL,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response_text: str | None = None
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                response_text = response.read().decode("utf-8")
            cache_file = self.raw_cache.save(endpoint, parameters, response_text)
            return json.loads(response_text), cache_file
        except (error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            cache_file = self.raw_cache.save(endpoint, parameters, response_text, message)
            raise SourceDataError(f"巨潮接口 {endpoint} 请求失败；原始记录：{cache_file}") from exc

    def get_sections(self, rows: int = 20) -> tuple[list[dict[str, str]], str]:
        payload, cache_file = self._post_json("getSelectData", {"rows": rows})
        if not isinstance(payload, list):
            raise SourceDataError("巨潮报告期接口结构发生变化：预期为列表")
        sections: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            period = str(item.get("value0", ""))
            title = str(item.get("value1", ""))
            try:
                period_to_year_type(period)
            except ValidationError:
                continue
            sections.append({"period": period, "title": title})
        if not sections:
            raise SourceDataError("巨潮报告期接口没有返回 2022—2026 的有效报告期")
        return sections, str(cache_file)

    def fetch_record(self, period: str, stock_code: str) -> dict[str, Any] | None:
        year, kind = period_to_year_type(period)
        code = normalize_stock_code(stock_code)
        preferred_market = market_for_stock(code)
        markets = (
            [preferred_market, *[item for item in CNINFO_MARKETS if item != preferred_market]]
            if preferred_market
            else list(CNINFO_MARKETS)
        )
        item: dict[str, Any] | None = None
        cache_file: Path | None = None
        matched_market: str | None = None
        for market in markets:
            parameters = {
                "sectionTime": period,
                "firstTime": "",
                "lastTime": "",
                "market": market,
                "stockCode": code,
                "isDesc": "false",
            }
            payload, current_cache_file = self._post_json("getPrbookInfo", parameters)
            if not isinstance(payload, dict):
                raise SourceDataError("巨潮预约披露接口结构发生变化：预期为对象")
            raw_records = payload.get("prbookinfos")
            if raw_records is None and int(payload.get("totalRows") or 0) == 0:
                continue
            if not isinstance(raw_records, list):
                raise SourceDataError("巨潮预约披露接口结构发生变化：prbookinfos 不是列表或空值")
            matches = [
                candidate
                for candidate in raw_records
                if isinstance(candidate, dict)
                and str(candidate.get("seccode", "")).zfill(6) == code
                and str(candidate.get("f001d_0102", "")) == period
            ]
            if len(matches) > 1:
                raise SourceDataError(f"巨潮返回重复记录：{code} / {period} / {market}")
            if matches:
                item = matches[0]
                cache_file = current_cache_file
                matched_market = market
                break
        if item is None or cache_file is None or matched_market is None:
            return None

        try:
            dates = {
                "first_reservation_date": normalize_iso_date(item.get("f002d_0102"), "首次预约日期"),
                "first_change_date": normalize_iso_date(item.get("f003d_0102"), "第一次变更日期"),
                "second_change_date": normalize_iso_date(item.get("f004d_0102"), "第二次变更日期"),
                "third_change_date": normalize_iso_date(item.get("f005d_0102"), "第三次变更日期"),
                "actual_disclosure_date": normalize_iso_date(item.get("f006d_0102"), "实际披露日期"),
            }
        except ValidationError as exc:
            raise SourceDataError(f"巨潮返回了无法识别的日期：{code} / {period}") from exc

        return {
            "stock_code": code,
            "company_name": str(item.get("secname") or f"股票 {code}"),
            "short_name": str(item.get("secname") or f"股票 {code}"),
            "report_year": year,
            "report_type": kind,
            **dates,
            "source_type": "CNINFO_OFFICIAL",
            "source_url": CNINFO_PAGE_URL,
            "source_endpoint": f"{CNINFO_BASE_URL}/getPrbookInfo",
            "source_file": None,
            "source_period": period,
            "source_market": matched_market,
            "source_org_id": item.get("orgId"),
            "raw_cache_file": str(cache_file),
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
