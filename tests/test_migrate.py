"""Tests for the schema v1 to v2 project upgrader."""

import pytest

from helpers import snapshot
from resynth import config
from resynth.errors import ResynthError
from resynth.fsutil import parse_frontmatter, sha256_text
from resynth.intake import FRONTMATTER_FIELDS, SCHEMA_VERSION, V2_FIELDS, register_source
from resynth.migrate import run_migrate
from resynth.project import run_init

BODY_A = "# Alpha Report\n\nArgon2id is preferred for password hashing.\n"
BODY_B = "# Beta Paper\n\nA bcrypt work factor of at least 12 is required.\n"


def write_v1(pdir, sid, origin, body, rank):
    """Handcraft a pre 0.2.0 source file with the nine v1 fields only."""
    lines = [
        f"source_id: {sid}",
        f"title: Source {sid}",
        f"origin: {origin}",
        "author_or_tool: unknown",
        "date_authored: unknown",
        "date_ingested: '2026-01-01'",
        "authority_tier: unknown",
        f"recency_rank: {rank}",
        f"sha256: {sha256_text(body)}",
    ]
    path = pdir / "sources" / f"{sid}-source.md"
    path.write_text(
        "---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8", newline="\n"
    )
    return path


def v1_project(ws, project="demo"):
    run_init(project)
    pdir = config.project_dir(project)
    write_v1(pdir, "S01", "notes/alpha-report.md", BODY_A, 1)
    write_v1(pdir, "S02", "papers/beta-paper.PDF", BODY_B, 2)
    return pdir


def test_migrate_adds_v2_fields_in_canonical_order(ws):
    pdir = v1_project(ws)
    res = run_migrate("demo")
    assert res["ok"] is True
    assert [e["action"] for e in res["events"]] == ["replaced", "replaced"]
    for fname, stype in (("S01-source.md", "report"), ("S02-source.md", "pdf")):
        fm, _body = parse_frontmatter(
            (pdir / "sources" / fname).read_text(encoding="utf-8"), fname
        )
        assert list(fm) == [*FRONTMATTER_FIELDS, *V2_FIELDS]
        assert fm["schema_version"] == SCHEMA_VERSION
        assert fm["source_type"] == stype
        assert fm["url"] is None
        assert fm["resolved_from"] is None
        assert "transcript_status" not in fm
    assert res["events"][0]["source_type"] == "report"
    assert res["events"][1]["source_type"] == "pdf"


def test_v1_values_preserved(ws):
    pdir = v1_project(ws)
    before, _ = parse_frontmatter(
        (pdir / "sources" / "S01-source.md").read_text(encoding="utf-8"), "S01"
    )
    run_migrate("demo")
    after, _ = parse_frontmatter(
        (pdir / "sources" / "S01-source.md").read_text(encoding="utf-8"), "S01"
    )
    for field in FRONTMATTER_FIELDS:
        assert after[field] == before[field]


def test_body_untouched_and_hash_still_valid(ws):
    pdir = v1_project(ws)
    res = run_migrate("demo")
    raw = (pdir / "sources" / "S01-source.md").read_bytes()
    assert raw.endswith(BODY_A.encode("utf-8"))
    _fm, body = parse_frontmatter(raw.decode("utf-8"), "S01")
    assert body == BODY_A
    gate = res["gate"]
    assert gate["status"] == "PASS"
    assert gate["warnings"] == []
    assert (pdir / "gates" / "01-intake.yaml").is_file()


def test_messages_verbatim(ws):
    v1_project(ws)
    res = run_migrate("demo")
    assert res["messages"] == [
        "S01: upgraded to schema v2 (source_type report)",
        "S02: upgraded to schema v2 (source_type pdf)",
        "Frontmatter has changed, so the existing seal no longer matches these files.",
        "The sealed git tag still pins the old state.",
        "When you are ready, re-seal with: resynth audit demo then resynth seal demo",
        "gate 01-intake: PASS",
    ]


def test_idempotent_second_run(ws):
    pdir = v1_project(ws)
    run_migrate("demo")
    sources = sorted((pdir / "sources").glob("S*.md"))
    mtimes = {f.name: f.stat().st_mtime_ns for f in sources}
    before = snapshot(pdir / "sources", pdir / "gates")
    res = run_migrate("demo")
    assert res["ok"] is True
    assert [e["action"] for e in res["events"]] == ["unchanged", "unchanged"]
    assert res["messages"] == [
        "S01: already schema v2",
        "S02: already schema v2",
        "gate 01-intake: PASS",
    ]
    assert snapshot(pdir / "sources", pdir / "gates") == before
    for f in sources:
        assert f.stat().st_mtime_ns == mtimes[f.name]


def test_dry_run_writes_nothing(ws):
    pdir = v1_project(ws)
    before = snapshot(pdir)
    res = run_migrate("demo", dry_run=True)
    assert res["ok"] is True
    assert res["gate"] is None
    assert [e["action"] for e in res["events"]] == ["dry-run", "dry-run"]
    assert snapshot(pdir) == before


def test_mixed_project_migrates_only_v1(ws):
    run_init("demo")
    pdir = config.project_dir("demo")
    write_v1(pdir, "S01", "notes/alpha-report.md", BODY_A, 1)
    register_source(pdir, BODY_B, title="Beta Paper", origin="papers/beta-paper.md")
    v2_file = next(f for f in (pdir / "sources").glob("S02*.md"))
    v2_before = v2_file.read_bytes()
    res = run_migrate("demo")
    events = {e["source"]: e["action"] for e in res["events"]}
    assert events["S01"] == "replaced"
    assert events["S02"] == "unchanged"
    assert v2_file.read_bytes() == v2_before
    fm, _ = parse_frontmatter(
        (pdir / "sources" / "S01-source.md").read_text(encoding="utf-8"), "S01"
    )
    assert fm["schema_version"] == SCHEMA_VERSION
    assert res["gate"]["status"] == "PASS"
    assert "S02: already schema v2" in res["messages"]


def test_empty_project_raises(ws):
    run_init("demo")
    with pytest.raises(ResynthError, match="no sources to migrate"):
        run_migrate("demo")
