import json
import subprocess

import yaml

from helpers import run_full, to_audited, to_synthesised

from resynth import config
from resynth.audit import run_audit
from resynth.fsutil import sha256_text
from resynth.gates import read_gate


def test_audit_passes_clean_pipeline(ws):
    pdir = to_audited()
    gate = read_gate(pdir, "05-audit")
    assert gate["status"] == "PASS"
    report = (pdir / "output" / "AUDIT-REPORT.md").read_text(encoding="utf-8")
    assert "Traceability matrix" in report
    assert "S03-C002" in report


def test_source_drift_detected(ws):
    pdir = to_synthesised()
    target = next((pdir / "sources").glob("S02-*.md"))
    target.write_text(
        target.read_text(encoding="utf-8") + "\ndrifted content\n", encoding="utf-8"
    )
    result = run_audit("demo")
    assert not result["ok"]
    assert any("changed since intake" in r for r in result["gate"]["reasons"])


def test_dropped_claim_detected(ws):
    pdir = to_synthesised()
    extra = {
        "claim_id": "S03-C050",
        "source_id": "S03",
        "claim_text": "An extra claim added after reconciliation",
        "claim_type": "fact",
        "topic_tags": ["monitoring"],
        "supporting_quote_location": "Findings",
        "confidence_as_stated": "unstated",
        "depends_on": [],
    }
    path = pdir / "claims" / "S03-claims.jsonl"
    path.write_text(
        path.read_text(encoding="utf-8") + json.dumps(extra) + "\n", encoding="utf-8"
    )
    result = run_audit("demo")
    assert not result["ok"]
    assert any("S03-C050 dropped without an OUT_OF_SCOPE decision" in r for r in result["gate"]["reasons"])


def test_seal_hashes_and_tag(ws):
    pdir = run_full()
    seal = yaml.safe_load((pdir / "output" / "SEAL.yaml").read_text(encoding="utf-8"))
    assert seal["tag"] == "resynth-demo-v1"
    master_hash = sha256_text((pdir / "output" / "MASTER.md").read_text(encoding="utf-8"))
    assert seal["sha256"]["output/MASTER.md"] == master_hash
    tags = subprocess.run(
        ["git", "tag", "--list"],
        cwd=config.workspace_root(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "resynth-demo-v1" in tags
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=config.workspace_root(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "SEAL.yaml" not in status
