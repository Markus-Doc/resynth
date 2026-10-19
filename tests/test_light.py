"""Light mode: capped sources, one AI task, a short master and three gates."""

import json

import pytest
import yaml

from helpers import DEMO_SOURCES, git_init

from resynth import config, demo_operator, operator_ai, resolve
from resynth.audit import run_audit, run_seal
from resynth.errors import ResynthError
from resynth.export import run_export
from resynth.extract import run_extract, run_extract_verify
from resynth.gates import all_gates
from resynth.intake import load_sources, run_intake
from resynth.project import run_brief, run_init
from resynth.reconcile import run_reconcile
from resynth.synthesise import run_synth_verify, run_synthesise
from resynth.wizard import project_state

LIGHT_BODY = """# Master Document: quick

## Answer

Password storage should use a slow adaptive hash, and the sources agree on
the core approach [S01-C001, S02-C001].

## Key Findings

- Rotating secrets on a schedule limits exposure [S01-C003, S03-C001].

## Where Sources Disagree

The sources give different work factors for bcrypt [S01-C002, S02-C002].

## Gaps

None of the sources covers hardware security modules.

## Appendix: Source Register
"""


def to_light_extracted(project="quick"):
    run_init(project, mode="light")
    run_brief(project, "How should a small team store passwords?")
    run_intake(project, [str(p) for p in DEMO_SOURCES])
    pdir = config.project_dir(project)
    run_extract(project)
    demo_operator.write_claims(pdir)
    assert run_extract_verify(project)["ok"]
    return pdir


def test_init_records_mode(ws):
    run_init("quick", mode="light")
    run_init("thorough")
    assert config.project_mode(config.project_dir("quick")) == "light"
    assert config.project_mode(config.project_dir("thorough")) == "deep"
    assert list(all_gates(config.project_dir("quick"))) == config.LIGHT_GATE_NAMES


def test_unknown_mode_rejected(ws):
    with pytest.raises(ResynthError):
        run_init("odd", mode="medium")


def test_light_instructions_carry_the_brief(ws):
    pdir = to_light_extracted()
    text = (pdir / "claims" / "EXTRACTION-INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "How should a small team store passwords?" in text
    assert f"> {config.LIGHT_CLAIMS_PER_SOURCE} claims from any one source" in text


def test_light_skips_reconcile_and_audit(ws):
    pdir = to_light_extracted()
    with pytest.raises(ResynthError, match="not a stage of a light project"):
        run_reconcile("quick")
    assert project_state(pdir) == "synthesise"
    run_synthesise("quick")
    master = (pdir / "output" / "MASTER.md").read_text(encoding="utf-8")
    assert "## Answer" in master and "## Appendix: Claim Provenance" not in master
    with pytest.raises(ResynthError):
        run_audit("quick")


def test_light_pipeline_seals_and_exports(ws):
    pdir = to_light_extracted()
    run_synthesise("quick")
    (pdir / "output" / "MASTER.md").write_text(LIGHT_BODY, encoding="utf-8")
    result = run_synth_verify("quick")
    assert result["ok"], result["messages"]
    assert project_state(pdir) == "seal"
    git_init(config.workspace_root())
    assert run_seal("quick")["ok"]
    seal = yaml.safe_load((pdir / "output" / "SEAL.yaml").read_text(encoding="utf-8"))
    assert seal["mode"] == "light"
    assert "output/AUDIT-REPORT.md" not in seal["sha256"]
    run_export("quick")
    payload = json.loads((pdir / "output" / "MASTER.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "light"


@pytest.mark.parametrize(
    "body,reason",
    [
        (LIGHT_BODY.replace(" [S01-C001, S02-C001]", ""), "without provenance markers"),
        (LIGHT_BODY.replace("S01-C003", "S01-C099"), "S01-C099 does not exist"),
        (LIGHT_BODY.replace("## Gaps\n", "## Notes\n"), "'Gaps' missing"),
        (LIGHT_BODY.replace("hardware security modules.", "hsm. " + "word " * 1300),
         "a light master stays under"),
    ],
)
def test_light_gate_failures(ws, body, reason):
    pdir = to_light_extracted()
    run_synthesise("quick")
    (pdir / "output" / "MASTER.md").write_text(body, encoding="utf-8")
    result = run_synth_verify("quick")
    assert not result["ok"]
    assert any(reason in r for r in result["gate"]["reasons"])


def test_light_resolve_caps_and_ranks_by_citations(ws, monkeypatch):
    shared, once, twice = "https://a.test/shared", "https://a.test/once", "https://a.test/other"
    reports = ws / "incoming"
    reports.mkdir()
    (reports / "one.md").write_text(f"# One\n\nSee {once} and {shared} for detail.\n", encoding="utf-8")
    (reports / "two.md").write_text(f"# Two\n\nAlso {twice} and {shared} again.\n", encoding="utf-8")
    run_init("cap", mode="light")
    run_intake("cap", [str(reports / "one.md"), str(reports / "two.md")])
    monkeypatch.setattr(config, "LIGHT_SOURCE_CAP", 3)

    def fake_fetch(url):
        return {"body_markdown": f"# Page\n\nContent fetched from {url}.\n", "title": url,
                "source_type": "html-article", "url": url, "origin": url,
                "author_or_tool": "test", "date_authored": "2026-10-19",
                "transcript_status": "fetched"}

    monkeypatch.setitem(resolve._FETCHERS, "url", fake_fetch)
    result = resolve.run_resolve("cap")
    assert result["counts"]["fetched"] == 1 and result["counts"]["skipped"] == 2
    fetched = [fm["url"] for fm in load_sources(config.project_dir("cap")) if fm.get("resolved_from")]
    assert fetched == [shared]


def test_light_route_inherits_wired_cli(ws):
    operator_ai.config_path().write_text(
        yaml.safe_dump({"version": 2, "routes": {"extract": {"author": {"cli": "codex"}}}}),
        encoding="utf-8",
    )
    assert operator_ai.route_for(operator_ai.load(), "light")["cli"] == "codex"
