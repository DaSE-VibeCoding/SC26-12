from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from fintrace.shared.company_resolver import resolve_company
from fintrace.shared.exceptions import FinTraceError
from fintrace.shared.paths import configured_path, get_project_root

app = FastAPI(title="FinTrace Local API", version="0.1.0")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _latest_run(feature: str, company_code: str) -> Path:
    index = configured_path("indexes_dir") / f"{feature}_runs.jsonl"
    records = [record for record in _jsonl(index) if record["company_code"] == company_code]
    if not records:
        raise HTTPException(404, f"No {feature} run exists for company {company_code}.")
    output = get_project_root() / records[-1]["output"]
    if output.is_file():
        output = output.parent
    if not output.is_dir():
        raise HTTPException(500, "The local run index points to a missing output directory.")
    return output


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise HTTPException(404, f"Local artifact does not exist: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage": "local_files"}


@app.get("/api/v1/companies/{company_code}")
def company(company_code: str, target_year: int = 2026) -> dict[str, Any]:
    try:
        return resolve_company(company_code, target_year).model_dump(mode="json")
    except FinTraceError as exc:
        raise HTTPException(404, exc.to_dict()) from exc


@app.get("/api/v1/companies/{company_code}/calendar")
def calendar(company_code: str) -> dict[str, Any]:
    output = _latest_run("calendar", company_code)
    return _load_json(output / "calendar_timeline.json")


@app.get("/api/v1/companies/{company_code}/financial")
def financial(company_code: str) -> dict[str, Any]:
    output = _latest_run("financial", company_code)
    with (output / "financial_facts.csv").open(encoding="utf-8-sig", newline="") as handle:
        facts = list(csv.DictReader(handle))
    return {
        "facts": facts,
        "traces": _jsonl(output / "indicator_traces.jsonl"),
        "viewer_manifest": _load_json(output / "viewer_manifest.json"),
        "quality": _load_json(output / "quality_report.json"),
    }


@app.get("/api/v1/companies/{company_code}/financial-series")
def financial_series(company_code: str) -> dict[str, Any]:
    payload = financial(company_code)
    series: dict[str, list[dict[str, Any]]] = {}
    for fact in payload["facts"]:
        series.setdefault(fact["indicator"], []).append(
            {
                "period": fact["period_label"],
                "value": fact["normalized_value"],
                "unit": fact["normalized_unit"],
                "evidence_id": fact["evidence_id"],
            }
        )
    return {"company_code": company_code, "series": series}


@app.get("/api/v1/evidence/{evidence_id}")
def evidence(evidence_id: str) -> dict[str, Any]:
    for index in reversed(_jsonl(configured_path("indexes_dir") / "financial_runs.jsonl")):
        output = get_project_root() / index["output"]
        for item in _jsonl(output / "evidence_index.jsonl"):
            if item["evidence_id"] == evidence_id:
                return item
    raise HTTPException(404, f"Evidence does not exist: {evidence_id}")


@app.get("/api/v1/traces/{trace_id}")
def trace(trace_id: str) -> dict[str, Any]:
    for index in reversed(_jsonl(configured_path("indexes_dir") / "financial_runs.jsonl")):
        output = get_project_root() / index["output"]
        for item in _jsonl(output / "indicator_traces.jsonl"):
            if item["trace_id"] == trace_id:
                item["evidence"] = [evidence(evidence_id) for evidence_id in item["inputs"]]
                return item
    raise HTTPException(404, f"Trace does not exist: {trace_id}")


@app.get("/api/v1/reports/{report_id}/pdf")
def report_pdf(report_id: str) -> FileResponse:
    for index in reversed(_jsonl(configured_path("indexes_dir") / "financial_runs.jsonl")):
        if index["report_id"] != report_id:
            continue
        manifest = _load_json(get_project_root() / index["output"] / "viewer_manifest.json")
        path = get_project_root() / manifest["report_file"]
        if path.is_file():
            return FileResponse(path, media_type="application/pdf", filename=path.name)
    raise HTTPException(404, f"Report does not exist: {report_id}")


def run() -> None:
    uvicorn.run("fintrace.api.app:app", host="127.0.0.1", port=8000, reload=False)
