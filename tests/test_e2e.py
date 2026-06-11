"""End to end: the full five stage pipeline on the demo content with
simulated operator inputs, finishing sealed with every gate PASS."""

import json

import yaml

from click.testing import CliRunner

from helpers import DEMO_SOURCES, git_init, snapshot

from resynth import config, demo_operator
from resynth.audit import run_audit, run_seal
from resynth.cli import main as cli_main
from resynth.export import run_export
from resynth.extract import run_extract, run_extract_verify
from resynth.gates import all_gates
from resynth.intake import run_intake
from resynth.project import run_brief, run_init
from resynth.reconcile import run_reconcile
from resynth.synthesise import run_synth_verify, run_synthesise


def test_full_pipeline(ws):
    assert run_init("demo")["ok"]
    assert run_brief("demo", "How should passwords be stored securely?")["ok"]
    pdir = config.project_dir("demo")

    assert run_intake("demo", [str(p) for p in DEMO_SOURCES])["ok"]
    assert run_extract("demo")["ok"]
    demo_operator.write_claims(pdir)
    assert run_extract_verify("demo")["ok"]

    assert not run_reconcile("demo")["ok"], "gate must fail before decisions exist"
    demo_operator.write_decisions(pdir)
    assert run_reconcile("demo")["ok"]

    assert run_synthesise("demo")["ok"]
    assert not run_synth_verify("demo")["ok"], "scaffold alone must not pass"
    demo_operator.write_prose(pdir)
    assert run_synth_verify("demo")["ok"]

    assert run_audit("demo")["ok"]
    git_init(ws)
    seal = run_seal("demo")
    assert seal["ok"] and seal["tag"] == "resynth-demo-v1"

    assert all_gates(pdir) == {g: "PASS" for g in config.GATE_NAMES}
    assert (pdir / "output" / "SEAL.yaml").is_file()
    assert run_export("demo")["ok"]
    exported = json.loads((pdir / "output" / "MASTER.json").read_text(encoding="utf-8"))
    assert exported["format"] == "resynth-master/1"
    assert len(exported["claims"]) == 11

    runner = CliRunner()
    result = runner.invoke(cli_main, ["status", "demo", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["gates"] == {g: "PASS" for g in config.GATE_NAMES}


def test_stage_gating_blocks_out_of_order_runs(ws):
    run_init("demo")
    result = CliRunner().invoke(cli_main, ["extract", "demo", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False


def test_dry_run_writes_nothing(ws):
    run_init("demo")
    pdir = config.project_dir("demo")
    before = snapshot(pdir)
    result = CliRunner().invoke(
        cli_main,
        ["intake", "demo", "--source", str(DEMO_SOURCES[0]), "--dry-run", "--json"],
    )
    assert snapshot(pdir) == before
    assert (config.runs_dir()).is_dir(), "dry runs still produce a run log"


def test_doctor_json(ws):
    result = CliRunner().invoke(cli_main, ["doctor", "--json"])
    payload = json.loads(result.output)
    assert "checks" in payload and "python" in payload["checks"]
