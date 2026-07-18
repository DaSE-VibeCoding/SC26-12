import json

from fintrace.shared.run_context import RunContext, RunStatus


def test_run_context_persists_step_manifests() -> None:
    context = RunContext(feature="test", company_code="600519")
    context.start()
    context.start_step("example", {"input": 1})
    context.finish_step("example", {"output": 2})
    context.finish()

    run_log = json.loads((context.output_dir / "run_log.json").read_text(encoding="utf-8"))
    step_dir = context.processed_dir / "example"
    assert run_log["status"] == RunStatus.COMPLETED
    assert (step_dir / "input_manifest.json").is_file()
    assert (step_dir / "output_manifest.json").is_file()
    assert (step_dir / "step_log.json").is_file()
