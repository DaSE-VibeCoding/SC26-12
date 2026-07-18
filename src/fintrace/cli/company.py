"""Resolve a company and persist a verifiable local run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fintrace.shared.company_resolver import normalize_company_code, resolve_company
from fintrace.shared.exceptions import FinTraceError
from fintrace.shared.file_store import append_jsonl, write_json
from fintrace.shared.paths import configured_path, ensure_runtime_directories, project_relative
from fintrace.shared.run_context import RunContext


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--company", required=True, help="Six-digit stock code, optionally suffixed"
    )
    parser.add_argument("--target-year", required=True, type=int, help="Company master target year")
    return parser


def run(company_input: str, target_year: int) -> tuple[dict[str, object], Path]:
    ensure_runtime_directories()
    company_code, _ = normalize_company_code(company_input)
    context = RunContext(feature="company", company_code=company_code)
    context.start()
    try:
        step_name = "resolve_company"
        context.start_step(step_name, {"company_code": company_input, "target_year": target_year})
        company = resolve_company(company_input, target_year)
        payload = company.model_dump(mode="json")
        company_file = context.output_dir / "company.json"
        write_json(company_file, payload)
        context.finish_step(
            step_name, {"company_file": project_relative(company_file), "company": payload}
        )

        quality = {
            "status": "passed_with_warnings" if company.company_info_fallback else "passed",
            "checks": {
                "exact_company_code_match": True,
                "company_version_available": True,
                "company_info_fallback": company.company_info_fallback,
            },
            "manual_review_required": False,
        }
        write_json(context.output_dir / "quality_report.json", quality)
        if company.company_info_fallback:
            context.warning_count += 1
        context.finish(with_warnings=company.company_info_fallback)
        append_jsonl(
            configured_path("indexes_dir") / "company_runs.jsonl",
            [
                {
                    "run_id": context.run_id,
                    "company_code": company_code,
                    "output": project_relative(company_file),
                }
            ],
        )
        return payload, context.output_dir
    except FinTraceError as exc:
        context.fail(exc.to_dict())
        raise
    except Exception as exc:
        error = {
            "code": "unexpected_error",
            "message": str(exc),
            "step": context.current_step,
        }
        context.fail(error)
        raise


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload, output_dir = run(args.company, args.target_year)
    except FinTraceError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    result = {"company": payload, "output_dir": str(output_dir)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
