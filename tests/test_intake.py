import pytest

from helpers import DEMO_SOURCES, make_project

from resynth.errors import ResynthError
from resynth.fsutil import parse_frontmatter, sha256_text
from resynth.gates import read_gate
from resynth.intake import FRONTMATTER_FIELDS, run_intake


def test_frontmatter_generation(ws):
    pdir = make_project()
    files = sorted((pdir / "sources").glob("S*.md"))
    assert len(files) == 3
    fm, body = parse_frontmatter(files[0].read_text(encoding="utf-8"), files[0].name)
    for field in FRONTMATTER_FIELDS:
        assert field in fm and fm[field] not in (None, "")
    assert fm["source_id"] == "S01"
    assert fm["title"] == "Password Storage Guidance, Standards Review"
    assert fm["sha256"] == sha256_text(body)


def test_intake_gate_passes_with_verified_hashes(ws):
    pdir = make_project()
    gate = read_gate(pdir, "01-intake")
    assert gate["status"] == "PASS"
    assert gate["reasons"] == []


def test_hash_verification_detects_tamper(ws):
    pdir = make_project()
    target = next((pdir / "sources").glob("S01-*.md"))
    target.write_text(
        target.read_text(encoding="utf-8") + "\ntampered line\n", encoding="utf-8"
    )
    from resynth.intake import check_intake_gate

    gate = check_intake_gate(pdir)
    assert gate["status"] == "FAIL"
    assert any("sha256" in r for r in gate["reasons"])


def test_duplicate_source_rejected(ws):
    pdir = make_project()
    result = run_intake("demo", [str(DEMO_SOURCES[0])])
    actions = [e["action"] for e in result["events"]]
    assert actions == ["rejected-duplicate"]
    assert len(list((pdir / "sources").glob("S*.md"))) == 3


def test_unsupported_format_rejected(ws, tmp_path):
    make_project()
    bad = tmp_path / "data.csv"
    bad.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(ResynthError, match="unsupported source format"):
        run_intake("demo", [str(bad)])


def test_missing_source_file(ws):
    make_project()
    with pytest.raises(ResynthError, match="not found"):
        run_intake("demo", ["nope.md"])
