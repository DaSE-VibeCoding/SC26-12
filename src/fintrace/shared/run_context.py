"""Run and step lifecycle stored entirely under the local data directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from fintrace.shared.file_store import write_json
from fintrace.shared.paths import get_output_dir, get_processed_dir, project_relative


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_run_id(now: datetime | None = None) -> str:
    timestamp = (now or utc_now()).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}_{uuid4().hex[:8]}"


@dataclass(slots=True)
class RunContext:
    feature: str
    company_code: str
    run_id: str = field(default_factory=new_run_id)
    status: RunStatus = RunStatus.PENDING
    current_step: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    warning_count: int = 0
    error_count: int = 0

    @property
    def processed_dir(self) -> Path:
        return get_processed_dir(self.feature, self.company_code, self.run_id)

    @property
    def output_dir(self) -> Path:
        return get_output_dir(self.feature, self.company_code, self.run_id)

    def start(self) -> None:
        self.status = RunStatus.RUNNING
        self.started_at = utc_now()
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.save()

    def start_step(self, step_name: str, inputs: dict[str, object]) -> Path:
        self.current_step = step_name
        step_dir = get_processed_dir(self.feature, self.company_code, self.run_id, step_name)
        step_dir.mkdir(parents=True, exist_ok=True)
        write_json(step_dir / "input_manifest.json", inputs)
        write_json(
            step_dir / "step_log.json",
            {"step": step_name, "status": RunStatus.RUNNING, "started_at": utc_now()},
        )
        self.save()
        return step_dir

    def finish_step(self, step_name: str, outputs: dict[str, object]) -> None:
        step_dir = get_processed_dir(self.feature, self.company_code, self.run_id, step_name)
        write_json(step_dir / "output_manifest.json", outputs)
        write_json(
            step_dir / "step_log.json",
            {"step": step_name, "status": RunStatus.COMPLETED, "finished_at": utc_now()},
        )

    def finish(self, with_warnings: bool = False) -> None:
        self.status = RunStatus.COMPLETED_WITH_WARNINGS if with_warnings else RunStatus.COMPLETED
        self.finished_at = utc_now()
        self.current_step = None
        self.save()

    def fail(self, error: dict[str, object]) -> None:
        self.status = RunStatus.FAILED
        self.finished_at = utc_now()
        self.error_count += 1
        write_json(self.output_dir / "error.json", error)
        self.save()

    def save(self) -> None:
        payload = asdict(self)
        payload["output_directory"] = project_relative(self.output_dir)
        write_json(self.output_dir / "run_log.json", payload)
