"""命令行启动入口：运行 ``python start_app.py``。"""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
from pathlib import Path

from fia.logging_config import configure_logging


REQUIRED_MODULES = ("pdfplumber", "pypdf")
LOGGER = logging.getLogger(__name__)


def dependencies_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in REQUIRED_MODULES)


def local_environment_matches_project(venv_dir: Path) -> bool:
    """Return whether generated environment files record the current location."""
    config_path = venv_dir / "pyvenv.cfg"
    activation_path = venv_dir / "Scripts" / "activate.bat"
    if not config_path.is_file() or not activation_path.is_file():
        return False
    try:
        config_text = config_path.read_text(encoding="utf-8")
        activation_text = activation_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    command = next(
        (line.partition("=")[2].strip() for line in config_text.splitlines() if line.startswith("command =")),
        "",
    )
    expected_path = str(venv_dir.resolve()).casefold()
    return expected_path in command.casefold() and expected_path in activation_text.casefold()


def prepare_local_environment() -> None:
    """创建或修复项目内虚拟环境，并使用它重新启动当前脚本。"""
    project_root = Path(__file__).resolve().parent
    venv_dir = project_root / ".venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    running_in_local_environment = Path(sys.executable).resolve() == venv_python.resolve()

    if running_in_local_environment:
        if not local_environment_matches_project(venv_dir):
            raise RuntimeError("本地运行环境来自其他目录，请使用系统 Python 重新运行 start_app.py。")
        if dependencies_available():
            LOGGER.info("复用项目虚拟环境：%s", venv_dir)
            return
        raise RuntimeError("本地运行环境依赖不完整，请使用系统 Python 重新运行 start_app.py。")

    if not venv_python.exists():
        LOGGER.info("创建项目虚拟环境：%s", venv_dir)
        print("首次启动：正在创建本地 Python 运行环境……", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    elif not local_environment_matches_project(venv_dir):
        LOGGER.warning("检测到复制自其他目录的虚拟环境，准备重建：%s", venv_dir)
        print("检测到从其他目录复制的本地运行环境，正在为当前项目重新创建……", flush=True)
        subprocess.run(
            [sys.executable, "-m", "venv", "--clear", str(venv_dir)],
            check=True,
        )

    dependency_check = subprocess.run(
        [str(venv_python), "-c", "import pdfplumber, pypdf"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if dependency_check.returncode != 0:
        LOGGER.info("项目依赖不完整，开始安装 requirements.txt")
        print("首次启动：正在安装 PDF 解析依赖……", flush=True)
        subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(project_root / "requirements.txt"),
            ],
            check=True,
        )

    os.execv(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


def run() -> None:
    project_root = Path(__file__).resolve().parent
    log_dir = configure_logging(project_root)
    LOGGER.info("启动器开始运行：python=%s project=%s logs=%s", sys.executable, project_root, log_dir)
    prepare_local_environment()
    from app import main

    # CMD 启动成功后默认自动打开看板；如需关闭，可追加 --no-browser。
    main(open_browser_by_default=True)


if __name__ == "__main__":
    try:
        run()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        LOGGER.exception("启动失败")
        print(f"启动失败：{exc}", file=sys.stderr)
        print("请检查网络连接及 requirements.txt 后重试。", file=sys.stderr)
        raise SystemExit(1) from exc
