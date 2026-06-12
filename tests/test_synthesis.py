from helpers import to_reconciled, to_synthesised

from resynth import demo_operator
from resynth.gates import read_gate
from resynth.synthesise import run_synth_verify, run_synthesise


def _master(pdir):
    return pdir / "output" / "MASTER.md"


def test_scaffold_generation(ws):
    pdir = to_reconciled()
    run_synthesise("demo")
    text = _master(pdir).read_text(encoding="utf-8")
    assert "## Conflicts" in text
    assert "## Gaps" in text
    assert "## Appendix: Source Register" in text
    assert "[!todo]" in text
    assert "[S01-C001, S02-C001]" in text
    assert "| Source | Title | Type | Authority | Authored | Link | Content hash |" in text
    row = next(line for line in text.splitlines() if line.startswith("| S01 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[2] == "report", "Type cell carries source_type"
    assert cells[5] == "-", "Link cell renders a dash when url is absent"


def test_full_synthesis_passes(ws):
    pdir = to_synthesised()
    assert read_gate(pdir, "04-synthesis")["status"] == "PASS"


def test_scaffold_alone_fails_verification(ws):
    to_reconciled()
    run_synthesise("demo")
    result = run_synth_verify("demo")
    assert not result["ok"]
    assert any("todo" in r for r in result["gate"]["reasons"])


def test_uncited_winning_claim_fails(ws):
    pdir = to_synthesised()
    path = _master(pdir)
    path.write_text(
        path.read_text(encoding="utf-8").replace("[S01-C004]", "[S01-C001]"),
        encoding="utf-8",
    )
    result = run_synth_verify("demo")
    assert not result["ok"]
    assert any("S01-C004" in r and "never cited" in r for r in result["gate"]["reasons"])


def test_phantom_claim_id_fails(ws):
    pdir = to_synthesised()
    path = _master(pdir)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "[S01-C004].", "[S01-C004]. A phantom statement [S09-C999]."
        ),
        encoding="utf-8",
    )
    result = run_synth_verify("demo")
    assert not result["ok"]
    assert any("S09-C999 does not exist" in r for r in result["gate"]["reasons"])


def test_empty_body_section_fails(ws):
    pdir = to_synthesised()
    path = _master(pdir)
    path.write_text(
        path.read_text(encoding="utf-8").replace(demo_operator.PROSE["Migration"], ""),
        encoding="utf-8",
    )
    result = run_synth_verify("demo")
    assert not result["ok"]
    assert any("'Migration' has no prose" in r for r in result["gate"]["reasons"])


def test_prose_without_markers_fails(ws):
    pdir = to_synthesised()
    path = _master(pdir)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            demo_operator.PROSE["Migration"],
            "Legacy hashes should be upgraded at next login.",
        ),
        encoding="utf-8",
    )
    result = run_synth_verify("demo")
    assert not result["ok"]
    assert any("without provenance markers" in r for r in result["gate"]["reasons"])


def test_missing_conflicts_section_fails(ws):
    pdir = to_synthesised()
    path = _master(pdir)
    text = path.read_text(encoding="utf-8")
    start = text.index("## Conflicts")
    end = text.index("## Gaps")
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    result = run_synth_verify("demo")
    assert not result["ok"]
    assert any("'Conflicts' missing" in r for r in result["gate"]["reasons"])


def test_existing_master_not_clobbered(ws):
    pdir = to_synthesised()
    before = _master(pdir).read_text(encoding="utf-8")
    result = run_synthesise("demo")
    assert result["events"][0]["action"] == "kept-existing"
    assert _master(pdir).read_text(encoding="utf-8") == before
    run_synthesise("demo", force=True)
    after = _master(pdir).read_text(encoding="utf-8")
    assert "[!todo]" in after
    trashed = list((pdir / "_trash").rglob("MASTER.md"))
    assert trashed, "prior master must move to _trash, never be destroyed"
