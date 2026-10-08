from helpers import (
    make_project,
    run_full,
    to_audited,
    to_extracted,
    to_reconciled,
    to_synthesised,
)

from resynth.project import run_brief, run_init
from resynth import config
from resynth.wizard import project_state


def test_state_progression(ws):
    run_init("demo")
    pdir = config.project_dir("demo")
    assert project_state(pdir) == "brief"
    run_brief("demo", "How should passwords be stored?")
    assert project_state(pdir) == "intake"


def test_state_after_intake(ws):
    pdir = make_project()
    run_brief("demo", "topic")
    assert project_state(pdir) == "extract"


def test_state_through_pipeline(ws):
    pdir = to_extracted()
    run_brief("demo", "topic")
    assert project_state(pdir) == "reconcile"


def test_state_synthesise_and_beyond(ws):
    pdir = to_reconciled()
    run_brief("demo", "topic")
    assert project_state(pdir) == "synthesise"
    pdir = config.project_dir("demo")


def test_state_audit_seal_done(ws):
    pdir = to_synthesised()
    run_brief("demo", "topic")
    assert project_state(pdir) == "audit"


def test_state_done_after_seal(ws):
    pdir = run_full()
    run_brief("demo", "topic")
    assert project_state(pdir) == "done"


def test_cli_version_and_new_commands(ws):
    from click.testing import CliRunner

    from resynth import __version__
    from resynth.cli import main

    runner = CliRunner()
    res = runner.invoke(main, ["--version"])
    assert res.exit_code == 0
    assert f"resynth, version {__version__}" in res.output
    assert "bye" not in res.output
    for cmd in ("resolve", "migrate"):
        res = runner.invoke(main, [cmd, "--help"])
        assert res.exit_code == 0, res.output


def _fake_extractor(calls, fail=()):
    """A stand-in AI CLI: writes the demo claims for the source named in the
    prompt, or fails for sources listed in fail."""
    import json
    import re

    from resynth import demo_operator, operator_ai

    def run_task(cfg, prompt, cwd, on_line=None, *, mode="write", should_stop=None):
        sid = re.search(r"ids (S\d{2})-C001", prompt).group(1)
        calls.append((sid, prompt))
        if sid in fail:
            return operator_ai.TaskResult(1, "boom")
        pdir = config.project_dir("demo")
        lines = [json.dumps({"source_id": sid, "depends_on": [], **c}) for c in demo_operator.CLAIMS[sid]]
        (pdir / "claims" / f"{sid}-claims.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return operator_ai.TaskResult(0, "done")

    return run_task


def _extract_route():
    from resynth import operator_ai, wizard

    return wizard._author_route(operator_ai.load(), "extract")


def test_extraction_runs_one_task_per_source_seeded_first(ws, monkeypatch):
    from resynth import wizard
    from resynth.extract import run_extract, run_extract_verify

    make_project()
    run_extract("demo")
    calls = []
    monkeypatch.setattr("resynth.operator_ai.run_task", _fake_extractor(calls))
    assert wizard._delegate_extract("demo", ws, _extract_route(), []) == "ok"
    assert [sid for sid, _ in calls][0] == "S01"
    assert sorted(sid for sid, _ in calls) == ["S01", "S02", "S03"]
    seed_prompt = calls[0][1]
    assert "sources/S01-" in seed_prompt and "S02" not in seed_prompt
    assert "-m resynth check-claims demo S01" in seed_prompt
    later = dict(calls)["S02"]
    assert "Prefer these topic tags" in later and "hashing-algorithms" in later
    assert run_extract_verify("demo")["ok"]


def test_extraction_retry_reruns_only_failing_sources(ws, monkeypatch):
    from resynth import wizard
    from resynth.extract import run_extract, run_extract_verify

    make_project()
    run_extract("demo")
    calls = []
    monkeypatch.setattr("resynth.operator_ai.run_task", _fake_extractor(calls, fail={"S02"}))
    assert wizard._delegate_extract("demo", ws, _extract_route(), []) == "ok"
    result = run_extract_verify("demo")
    assert not result["ok"]
    calls.clear()
    monkeypatch.setattr("resynth.operator_ai.run_task", _fake_extractor(calls))
    feedback = result["gate"]["reasons"]
    assert wizard._delegate_extract("demo", ws, _extract_route(), feedback) == "ok"
    assert [sid for sid, _ in calls] == ["S02"]
    assert run_extract_verify("demo")["ok"]


def test_extraction_with_nothing_left_runs_no_task(ws, monkeypatch):
    from resynth import wizard

    to_extracted()
    calls = []
    monkeypatch.setattr("resynth.operator_ai.run_task", _fake_extractor(calls))
    assert wizard._delegate_extract("demo", ws, _extract_route(), []) == "ok"
    assert calls == []


def test_delegated_prompts_carry_self_checks():
    import sys

    from resynth import wizard

    check = wizard._check_command("reconcile", project="p")
    assert check == f'"{sys.executable}" -m resynth reconcile p --fill-unique --json'
    prompt, _ = wizard._build_prompt("synthesise", {"cli": "claude"}, [], "", project="p",
                                     check=wizard._check_command("synthesise", project="p"))
    assert "synth-verify p --json" in prompt and "work from MASTER.md alone" in prompt
