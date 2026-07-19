from __future__ import annotations

import json
import logging
import mimetypes
import re
import shutil
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from disclosure import SourceDataError, create_disclosure_service

from .cninfo import CninfoAnnualReportClient, CninfoDownloadError
from .parser import stable_file_id
from .service import AnalysisService


LOGGER = logging.getLogger(__name__)
FRONTEND_LOGGER = logging.getLogger("fia.frontend")
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_ARTIFACTS = {
    "normalized_financials.json",
    "pdf_highlights.json",
    "viewer_manifest.json",
}
STATIC_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}
NO_STORE_SUFFIXES = {".css", ".html", ".js", ".mjs"}


def _content_type_for(path: Path, explicit: str | None = None) -> str:
    return explicit or STATIC_MIME_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _cache_control_for(path: Path, content_type: str) -> str:
    bare_content_type = content_type.partition(";")[0].strip().lower()
    if path.suffix.lower() in NO_STORE_SUFFIXES or bare_content_type in {"application/json", "application/pdf"}:
        return "no-store"
    return "public, max-age=3600"


def example_groups(input_dir: Path) -> list[dict[str, Any]]:
    grouped: dict[str, list[Path]] = {}
    for path in sorted(input_dir.glob("*.pdf")):
        company = path.stem.split("：", 1)[0].split(":", 1)[0].strip() or "未分组"
        grouped.setdefault(company, []).append(path)
    return [
        {
            "company": company,
            "file_count": len(paths),
            "files": [path.name for path in paths],
        }
        for company, paths in sorted(grouped.items())
    ]


class FileRegistry:
    def __init__(self) -> None:
        self._files: dict[str, Path] = {}
        self._lock = threading.RLock()

    def register(self, path: Path) -> str:
        file_id = stable_file_id(path)
        with self._lock:
            self._files[file_id] = path.resolve()
        return file_id

    def get(self, file_id: str) -> Path | None:
        with self._lock:
            return self._files.get(file_id)

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"file_id": file_id, "file_name": path.name, "size": path.stat().st_size}
                for file_id, path in sorted(self._files.items(), key=lambda item: item[1].name)
            ]


class ApplicationState:
    def __init__(self, project_root: Path, input_dir: Path):
        self.project_root = project_root
        self.static_dir = project_root / "static"
        self.input_dir = input_dir.resolve()
        self.runtime_dir = project_root / ".fia_runtime"
        self.upload_dir = self.runtime_dir / "uploads"
        self.result_dir = self.runtime_dir / "results"
        self.archive_dir = project_root / "annual_reports"
        self.log_dir = project_root / "logs"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.registry = FileRegistry()
        self.service = AnalysisService(self.result_dir)
        self.cninfo = CninfoAnnualReportClient()
        self.disclosure = create_disclosure_service(project_root)
        self.analysis_lock = threading.Lock()
        for path in sorted(self.input_dir.glob("*.pdf")):
            self.registry.register(path)
        LOGGER.info(
            "应用状态初始化完成：input=%s archive=%s results=%s uploads=%s logs=%s",
            self.input_dir,
            self.archive_dir,
            self.result_dir,
            self.upload_dir,
            self.log_dir,
        )


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def create_handler(state: ApplicationState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FinancialIndicatorsAssistant/3.0"

        def log_message(self, format_string: str, *args: object) -> None:
            LOGGER.info(
                "HTTP client=%s request=%s | %s",
                self.client_address[0],
                self.requestline,
                format_string % args,
            )

        def _send_json(self, payload: Any, status: int = 200) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, message: str, status: int = 400) -> None:
            self._send_json({"error": message}, status)

        def _send_path(self, path: Path, content_type: str | None = None) -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime = _content_type_for(path, content_type)
            cache_control = _cache_control_for(path, mime)
            size = path.stat().st_size
            range_header = self.headers.get("Range")
            if range_header:
                match = re.match(r"bytes=(\d*)-(\d*)", range_header)
                if match:
                    start_text, end_text = match.groups()
                    start = int(start_text) if start_text else 0
                    end = int(end_text) if end_text else size - 1
                    end = min(end, size - 1)
                    if start <= end < size:
                        length = end - start + 1
                        self.send_response(HTTPStatus.PARTIAL_CONTENT)
                        self.send_header("Content-Type", mime)
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.send_header("Content-Length", str(length))
                        self.send_header("Cache-Control", cache_control)
                        self.end_headers()
                        try:
                            with path.open("rb") as source:
                                source.seek(start)
                                remaining = length
                                while remaining:
                                    chunk = source.read(min(1024 * 1024, remaining))
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                                    remaining -= len(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            LOGGER.info("客户端中止文件传输：path=%s client=%s", path, self.client_address[0])
                        return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            try:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                LOGGER.info("客户端中止文件传输：path=%s client=%s", path, self.client_address[0])

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2 * 1024 * 1024:
                raise ValueError("请求数据过大")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            if route == "/":
                self._send_path(state.static_dir / "index.html", "text/html; charset=utf-8")
                return
            if route == "/api/health":
                self._send_json(
                    {
                        "status": "ok",
                        "application": "FinancialReportAssistant",
                        "input_dir": str(state.input_dir),
                        "annual_report_archive": str(state.archive_dir),
                        "log_dir": str(state.log_dir),
                        "services": {
                            "financial_indicators": {"status": "ok"},
                            "disclosure_time": state.disclosure.configuration_status(),
                        },
                    }
                )
                return
            if route == "/api/files":
                self._send_json({"files": state.registry.entries()})
                return
            if route == "/api/example-groups":
                self._send_json({"groups": example_groups(state.input_dir)})
                return
            if route.startswith("/api/files/"):
                file_id = route.rsplit("/", 1)[-1]
                path = state.registry.get(file_id)
                if path is None:
                    self._send_error_json("未找到PDF文件", 404)
                    return
                self._send_path(path, "application/pdf")
                return
            if route.startswith("/api/artifacts/"):
                name = route.rsplit("/", 1)[-1]
                if name not in ALLOWED_ARTIFACTS:
                    self._send_error_json("不允许访问该文件", 403)
                    return
                self._send_path(state.result_dir / name, "application/json; charset=utf-8")
                return
            if route.startswith("/static/"):
                relative = Path(urllib.parse.unquote(route[len("/static/") :]))
                if relative.is_absolute() or ".." in relative.parts:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                self._send_path(state.static_dir / relative)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            request_id = uuid4().hex[:12]
            started = time.perf_counter()
            LOGGER.info("POST 开始 request_id=%s route=%s client=%s", request_id, route, self.client_address[0])
            try:
                if route == "/api/client-log":
                    payload = self._read_json()
                    level_name = str(payload.get("level") or "error").lower()
                    level = {
                        "info": logging.INFO,
                        "warning": logging.WARNING,
                        "error": logging.ERROR,
                    }.get(level_name, logging.ERROR)
                    message = str(payload.get("message") or "浏览器未提供错误消息")[:4000]
                    details = json.dumps(
                        payload.get("details") or {},
                        ensure_ascii=False,
                        default=str,
                    )[:12000]
                    FRONTEND_LOGGER.log(
                        level,
                        "request_id=%s client=%s message=%s details=%s",
                        request_id,
                        self.client_address[0],
                        message,
                        details,
                    )
                    self._send_json({"logged": True}, 202)
                    return
                if route == "/api/analyze-stock":
                    payload = self._read_json()
                    stock_code = payload.get("stock_code")
                    LOGGER.info("股票分析开始 request_id=%s stock_code=%s", request_id, stock_code)
                    with state.analysis_lock:
                        paths, archive_manifest = state.cninfo.fetch_and_archive(
                            stock_code,
                            state.archive_dir,
                        )
                        for path in paths:
                            state.registry.register(path)
                        result = state.service.analyze_paths(paths)
                    result["annual_report_archive"] = archive_manifest
                    LOGGER.info(
                        "股票分析完成 request_id=%s stock_code=%s files=%d cells=%s/%s elapsed=%.3fs archive=%s",
                        request_id,
                        stock_code,
                        len(paths),
                        result.get("quality", {}).get("found_cells"),
                        result.get("quality", {}).get("expected_cells"),
                        time.perf_counter() - started,
                        archive_manifest.get("archive_dir"),
                    )
                    self._send_json(result)
                    return
                if route == "/api/disclosure":
                    payload = self._read_json()
                    stock_code = payload.get("stock_code")
                    report_year = payload.get("report_year") or 2026
                    report_type = payload.get("report_type") or "Q1"
                    LOGGER.info(
                        "披露时间分析开始 request_id=%s stock_code=%s period=%s/%s",
                        request_id,
                        stock_code,
                        report_year,
                        report_type,
                    )
                    result = state.disclosure.dashboard(
                        stock_code=stock_code,
                        report_year=report_year,
                        report_type=report_type,
                    )
                    LOGGER.info(
                        "披露时间分析完成 request_id=%s stock_code=%s period=%s/%s elapsed=%.3fs",
                        request_id,
                        stock_code,
                        report_year,
                        report_type,
                        time.perf_counter() - started,
                    )
                    self._send_json(result)
                    return
                if route == "/api/upload":
                    self._handle_upload(parsed)
                    return
                if route == "/api/analyze":
                    payload = self._read_json()
                    file_ids = payload.get("file_ids") or []
                    paths = [state.registry.get(str(file_id)) for file_id in file_ids]
                    if not paths or any(path is None for path in paths):
                        self._send_error_json("请选择有效的PDF文件")
                        return
                    with state.analysis_lock:
                        result = state.service.analyze_paths(path for path in paths if path is not None)
                    self._send_json(result)
                    return
                if route == "/api/analyze-examples":
                    payload = self._read_json()
                    requested_company = str(payload.get("company") or "").strip()
                    groups = example_groups(state.input_dir)
                    if requested_company:
                        matching = next((group for group in groups if group["company"] == requested_company), None)
                        if matching is None:
                            self._send_error_json("未找到所选示例公司", 404)
                            return
                        paths = [state.input_dir / name for name in matching["files"]]
                    elif len(groups) == 1:
                        paths = [state.input_dir / name for name in groups[0]["files"]]
                    elif len(groups) > 1:
                        self._send_error_json("目录包含多家公司，请先选择示例公司")
                        return
                    else:
                        paths = []
                    if not paths:
                        self._send_error_json("目标目录没有可分析的PDF文件", 404)
                        return
                    for path in paths:
                        state.registry.register(path)
                    with state.analysis_lock:
                        result = state.service.analyze_paths(paths)
                    self._send_json(result)
                    return
            except CninfoDownloadError as exc:
                LOGGER.warning(
                    "巨潮处理失败 request_id=%s route=%s elapsed=%.3fs error=%s",
                    request_id,
                    route,
                    time.perf_counter() - started,
                    exc,
                    exc_info=True,
                )
                self._send_error_json(str(exc), 502)
                return
            except SourceDataError as exc:
                LOGGER.warning(
                    "披露时间数据源失败 request_id=%s route=%s elapsed=%.3fs error=%s",
                    request_id,
                    route,
                    time.perf_counter() - started,
                    exc,
                    exc_info=True,
                )
                self._send_error_json(str(exc), 503)
                return
            except (ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning(
                    "请求校验失败 request_id=%s route=%s elapsed=%.3fs error=%s",
                    request_id,
                    route,
                    time.perf_counter() - started,
                    exc,
                    exc_info=True,
                )
                self._send_error_json(str(exc), 400)
                return
            except Exception as exc:
                LOGGER.exception(
                    "请求处理异常 request_id=%s route=%s elapsed=%.3fs",
                    request_id,
                    route,
                    time.perf_counter() - started,
                )
                self._send_error_json(f"处理失败：{exc}", 500)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _handle_upload(self, parsed) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                self._send_error_json("上传内容为空")
                return
            if length > MAX_UPLOAD_BYTES:
                self._send_error_json("单个文件不能超过250MB", 413)
                return
            query = urllib.parse.parse_qs(parsed.query)
            original_name = urllib.parse.unquote((query.get("filename") or ["uploaded.pdf"])[0])
            safe_name = Path(original_name).name
            if not safe_name.lower().endswith(".pdf"):
                self._send_error_json("仅支持PDF文件")
                return
            destination = state.upload_dir / f"{uuid4().hex[:10]}_{safe_name}"
            remaining = length
            with destination.open("wb") as output:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    output.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                destination.unlink(missing_ok=True)
                self._send_error_json("文件上传不完整")
                return
            with destination.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    destination.unlink(missing_ok=True)
                    self._send_error_json("文件不是有效的PDF")
                    return
            file_id = state.registry.register(destination)
            self._send_json(
                {"file_id": file_id, "file_name": safe_name, "size": destination.stat().st_size},
                201,
            )

    return Handler


class LoggingThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:  # type: ignore[override]
        LOGGER.exception("HTTP 处理器未捕获异常：client=%s", client_address)


def run_server(project_root: Path, input_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    state = ApplicationState(project_root, input_dir)
    server = LoggingThreadingHTTPServer((host, port), create_handler(state))
    server.state = state  # type: ignore[attr-defined]
    LOGGER.info("HTTP 服务已绑定：host=%s port=%s", host, port)
    return server
