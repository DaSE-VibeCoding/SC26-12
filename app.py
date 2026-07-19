from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

from fia.logging_config import configure_logging
from fia.web import run_server


LOGGER = logging.getLogger(__name__)


def parse_args(*, open_browser_by_default: bool = True) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="财报披露时间与关键财务指标并行分析助手")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", default=8766, type=int, help="监听端口")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="示例年度报告所在目录",
    )
    browser_group = parser.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--open-browser",
        dest="open_browser",
        action="store_true",
        help="启动后自动打开浏览器",
    )
    browser_group.add_argument(
        "--no-browser",
        dest="open_browser",
        action="store_false",
        help="启动后不自动打开浏览器",
    )
    parser.set_defaults(open_browser=open_browser_by_default)
    return parser.parse_args()


def main(*, open_browser_by_default: bool = True) -> None:
    args = parse_args(open_browser_by_default=open_browser_by_default)
    project_root = Path(__file__).resolve().parent
    log_dir = configure_logging(project_root)
    LOGGER.info(
        "应用启动：python=%s host=%s port=%s project=%s",
        sys.executable,
        args.host,
        args.port,
        project_root,
    )
    try:
        server = run_server(project_root, args.input_dir, args.host, args.port)
    except Exception:
        LOGGER.exception("本地 HTTP 服务初始化失败")
        raise
    url = f"http://{args.host}:{args.port}/"
    result_dir = project_root / ".fia_runtime" / "results"
    archive_dir = project_root / "annual_reports"
    print("FinancialReportAssistant 已启动（披露时间 + 财务指标并行分析）")
    print(f"访问地址：{url}")
    print(f"年报目录：{args.input_dir.resolve()}")
    print(f"巨潮年报归档：{archive_dir}")
    print(f"结果目录：{result_dir}")
    print(f"日志目录：{log_dir}")
    print("按 Ctrl+C 停止服务")
    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("收到 Ctrl+C，准备停止服务")
        print("\n正在停止服务……")
    except Exception:
        LOGGER.exception("HTTP 服务运行异常退出")
        raise
    finally:
        server.server_close()
        LOGGER.info("HTTP 服务已停止")


if __name__ == "__main__":
    main()
