"""真实来源记录存储，以及看板聚合服务。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from .domain import (
    REPORT_META,
    REPORT_TYPES,
    YEARS,
    ValidationError,
    business_key,
    enrich_record,
    missing_record,
    normalize_iso_date,
    normalize_report_type,
    normalize_stock_code,
    normalize_year,
    report_period,
    report_window,
)
from .sources import (
    CNINFO_PAGE_URL,
    CninfoClient,
    HistoryWorkbook,
    IndustryPeerResolver,
    SourceDataError,
)


SCHEMA_VERSION = 2
ALLOWED_STORED_SOURCES = {"CNINFO_OFFICIAL"}


class JsonDocumentStore:
    """只保存已核验来源的增量记录；历史 Excel 不复制进该文件。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write_unlocked(self._empty_database())

    @staticmethod
    def _empty_database() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "data_policy": "REAL_SOURCES_ONLY",
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "records": [],
        }

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取真实数据缓存：{self.path}") from exc
        if data.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(
                "数据文件版本不兼容。旧演示库必须先改名为 disclosure_db.demo.json，"
                "不能被真实数据模式读取。"
            )
        if data.get("data_policy") != "REAL_SOURCES_ONLY" or not isinstance(data.get("records"), list):
            raise RuntimeError("真实数据缓存结构不完整，已停止读取")
        if any(item.get("source_type") not in ALLOWED_STORED_SOURCES for item in data["records"]):
            raise RuntimeError("真实数据缓存中发现非官方来源记录，已停止读取")
        return data

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.stem}-", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def all_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._read_unlocked()["records"]]

    def get(self, stock_code: str, year: int, kind: str) -> dict[str, Any] | None:
        key = f"{stock_code}|{year}|{kind}"
        with self._lock:
            for item in self._read_unlocked()["records"]:
                if business_key(item) == key:
                    return dict(item)
        return None

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate_record(record)
        with self._lock:
            data = self._read_unlocked()
            key = business_key(normalized)
            by_key = {business_key(item): index for index, item in enumerate(data["records"])}
            if key in by_key:
                data["records"][by_key[key]] = normalized
            else:
                data["records"].append(normalized)
            data["records"].sort(
                key=lambda item: (item["stock_code"], item["report_year"], item["report_type"])
            )
            self._write_unlocked(data)
        return normalized

    @staticmethod
    def _validate_record(record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValidationError("记录必须是 JSON 对象")
        result = dict(record)
        result["stock_code"] = normalize_stock_code(result.get("stock_code"))
        result["report_year"] = normalize_year(result.get("report_year"))
        result["report_type"] = normalize_report_type(result.get("report_type"))
        for field in (
            "first_reservation_date",
            "first_change_date",
            "second_change_date",
            "third_change_date",
            "actual_disclosure_date",
        ):
            result[field] = normalize_iso_date(result.get(field), field)

        source_type = result.get("source_type")
        if source_type not in ALLOWED_STORED_SOURCES:
            raise ValidationError("只允许写入 CNINFO_OFFICIAL 来源；DEMO 数据被永久禁用")
        source_url = str(result.get("source_url") or "")
        if source_url != CNINFO_PAGE_URL:
            raise ValidationError("巨潮记录缺少已核验的官方来源网址")
        if not result.get("raw_cache_file"):
            raise ValidationError("巨潮记录缺少原始响应缓存文件，拒绝写入")
        if result.get("source_period") != report_period(result["report_year"], result["report_type"]):
            raise ValidationError("巨潮记录的报告期与年度/类型不一致")
        if not result.get("fetched_at"):
            raise ValidationError("巨潮记录缺少抓取时间")
        result.setdefault("company_name", f"股票 {result['stock_code']}")
        result.setdefault("short_name", result["company_name"])
        return result


class DisclosureService:
    """按“Excel 历史优先、巨潮仅补最新缺口”生成看板。"""

    def __init__(
        self,
        data_file: str | Path,
        history_file: str | Path,
        *,
        allow_network: bool = True,
        cninfo_client: CninfoClient | None = None,
        peer_resolver: IndustryPeerResolver,
    ):
        self.store = JsonDocumentStore(data_file)
        self.history = HistoryWorkbook(history_file)
        self.peer_resolver = peer_resolver
        self.allow_network = allow_network
        raw_dir = Path(data_file).resolve().parent / "raw" / "cninfo"
        self.cninfo = cninfo_client or CninfoClient(raw_dir)

    def configuration_status(self) -> dict[str, Any]:
        return {
            "mode": "REAL_SOURCES_ONLY",
            "database_file": str(self.store.path),
            "history_file": str(self.history.path),
            "history_file_exists": self.history.path.is_file(),
            "network_enabled": self.allow_network,
            "demo_generation_enabled": False,
            **self.peer_resolver.configuration_status(),
        }

    @staticmethod
    def _cache_is_fresh(record: dict[str, Any], now: datetime) -> bool:
        if record.get("actual_disclosure_date"):
            return True
        try:
            fetched = datetime.fromisoformat(str(record.get("fetched_at")))
        except (TypeError, ValueError):
            return False
        if fetched.tzinfo is None:
            fetched = fetched.astimezone()
        return now - fetched < timedelta(hours=12)

    def _refresh_official(
        self,
        target_code: str,
        peer_codes: list[str],
        selected_period: str,
    ) -> dict[str, Any]:
        status: dict[str, Any] = {
            "status": "not_needed",
            "queried_records": 0,
            "updated_records": 0,
            "not_found_records": 0,
            "errors": [],
            "sections_cache_file": None,
        }
        if not self.allow_network:
            status.update({"status": "disabled", "errors": ["网络抓取已禁用，使用现有缓存"]})
            return status

        try:
            sections, sections_cache = self.cninfo.get_sections(rows=20)
        except SourceDataError as exc:
            status.update({"status": "failed", "errors": [str(exc)]})
            return status

        status["sections_cache_file"] = sections_cache
        available_periods = {item["period"] for item in sections}
        incremental_periods = sorted(
            period for period in available_periods if period > self.history.max_period
        )
        tasks: list[tuple[str, str]] = [(period, target_code) for period in incremental_periods]
        if selected_period in incremental_periods:
            tasks.extend((selected_period, code) for code in peer_codes)

        now = datetime.now().astimezone()
        pending: list[tuple[str, str]] = []
        for period, code in tasks:
            year, kind = int(period[:4]), next(
                key for key, meta in REPORT_META.items() if meta["period_suffix"] == period[5:]
            )
            cached = self.store.get(code, year, kind)
            if cached is None or not self._cache_is_fresh(cached, now):
                pending.append((period, code))

        if not pending:
            status["status"] = "cache_current" if tasks else "not_needed"
            return status

        status["status"] = "completed"
        status["queried_records"] = len(pending)
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as executor:
            futures = {
                executor.submit(self.cninfo.fetch_record, period, code): (period, code)
                for period, code in pending
            }
            for future in as_completed(futures):
                period, code = futures[future]
                try:
                    record = future.result()
                    if record is None:
                        status["not_found_records"] += 1
                    else:
                        self.store.upsert(record)
                        status["updated_records"] += 1
                except (SourceDataError, ValidationError, RuntimeError) as exc:
                    status["errors"].append(f"{code} / {period}：{exc}")
        if status["errors"]:
            status["status"] = "partial" if status["updated_records"] else "failed"
        return status

    def _combined_records(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        combined = {
            business_key(item): item for item in self.history.records_for_codes(codes)
        }
        for item in self.store.all_records():
            if item["stock_code"] not in codes:
                continue
            period = report_period(item["report_year"], item["report_type"])
            if period <= self.history.max_period:
                continue
            combined[business_key(item)] = item
        return combined

    def dashboard(
        self,
        stock_code: Any,
        report_year: Any,
        report_type: Any,
    ) -> dict[str, Any]:
        code = normalize_stock_code(stock_code)
        year = normalize_year(report_year)
        kind = normalize_report_type(report_type)
        peer_resolution = self.peer_resolver.resolve(code, year)
        peers = peer_resolution["peer_codes"]
        selected_period = report_period(year, kind)

        self.history.ensure_loaded()
        official_status = self._refresh_official(code, peers, selected_period)
        codes = [code, *peers]
        records = self._combined_records(codes)

        names: dict[str, str] = {}
        for item in records.values():
            names[item["stock_code"]] = item["company_name"]
        for item_code in codes:
            names.setdefault(
                item_code,
                self.history.company_name(item_code) or f"股票 {item_code}",
            )

        rows: list[dict[str, Any]] = []
        for item_code in codes:
            item = records.get(f"{item_code}|{year}|{kind}")
            enriched = (
                missing_record(item_code, names[item_code], year, kind)
                if item is None
                else enrich_record(item)
            )
            enriched["is_target"] = item_code == code
            rows.append(enriched)
        rows.sort(key=lambda item: (not item["is_target"], item["display_date"] or "9999-12-31"))

        target = next(item for item in rows if item["is_target"])
        dated = sorted(
            (item for item in rows if item["display_date"]), key=lambda item: item["display_date"]
        )
        target_rank = next(
            (index + 1 for index, item in enumerate(dated) if item["stock_code"] == code), None
        )
        median_date: str | None = None
        median_delta_days: int | None = None
        if dated:
            ordinals = [date.fromisoformat(item["display_date"]).toordinal() for item in dated]
            median_ordinal = round(median(ordinals))
            median_date = date.fromordinal(median_ordinal).isoformat()
            if target["display_date"]:
                median_delta_days = (
                    date.fromisoformat(target["display_date"]).toordinal() - median_ordinal
                )

        history_payload: list[dict[str, Any]] = []
        for history_year in YEARS:
            period_records: dict[str, Any] = {}
            for history_kind in REPORT_TYPES:
                item = records.get(f"{code}|{history_year}|{history_kind}")
                period_records[history_kind] = (
                    missing_record(code, names[code], history_year, history_kind)
                    if item is None
                    else enrich_record(item)
                )
            history_payload.append({"report_year": history_year, "records": period_records})

        start, end = report_window(year, kind)
        return {
            "target_company": {
                "stock_code": code,
                "company_name": names[code],
                "short_name": names[code],
            },
            "filters": {"report_year": year, "report_type": kind},
            "report_meta": REPORT_META[kind],
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "rows": rows,
            "history": history_payload,
            "metrics": {
                "target_rank": target_rank,
                "company_count": len(dated),
                "median_date": median_date,
                "median_delta_days": median_delta_days,
                "reservation_change_count": target["reservation_change_count"],
            },
            "peer_resolution": peer_resolution,
            "data_source": {
                "mode": "REAL_SOURCES_ONLY",
                "notice": "Excel 覆盖其最新报告期；之后的缺口仅由巨潮官方接口补充。抓取失败时显示暂无数据。",
                "history": self.history.audit,
                "peer_selection": self.peer_resolver.audit,
                "official_refresh": official_status,
                "database_file": str(self.store.path),
                "official_page_url": CNINFO_PAGE_URL,
                "demo_generation_enabled": False,
            },
        }
