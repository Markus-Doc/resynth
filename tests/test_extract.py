import json

import pytest

from helpers import make_project, to_extracted

from resynth.extract import run_extract, run_extract_verify, validate_claim
from resynth.gates import read_gate

VALID = {
    "claim_id": "S01-C001",
    "source_id": "S01",
    "claim_text": "Argon2id is preferred",
    "claim_type": "recommendation",
    "topic_tags": ["hashing-algorithms"],
    "supporting_quote_location": "Hashing algorithms",
    "confidence_as_stated": "high",
    "depends_on": [],
}


def test_valid_claim_passes():
    assert validate_claim(dict(VALID), "S01") == []


@pytest.mark.parametrize(
    "field,value,fragment",
    [
        ("claim_id", "C001", "format"),
        ("claim_id", "S02-C001", "does not belong"),
        ("source_id", "S02", "does not match"),
        ("claim_text", "", "non-empty"),
        ("claim_type", "opinion", "claim_type"),
        ("topic_tags", [], "topic_tags"),
        ("topic_tags", "tag", "topic_tags"),
        ("supporting_quote_location", "", "non-empty"),
        ("supporting_quote_location", "x" * 300, "too long"),
        ("confidence_as_stated", "certain", "confidence_as_stated"),
        ("depends_on", ["bogus"], "depends_on"),
        ("depends_on", "S01-C002", "depends_on"),
    ],
)
def test_field_violations_fail(field, value, fragment):
    claim = dict(VALID)
    claim[field] = value
    errors = validate_claim(claim, "S01")
    assert errors, f"expected violation for {field}={value!r}"
    assert any(fragment in e for e in errors)


def test_missing_and_unknown_fields_fail():
    claim = dict(VALID)
    del claim["claim_text"]
    claim["extra"] = 1
    errors = validate_claim(claim, "S01")
    assert any("missing field claim_text" in e for e in errors)
    assert any("unknown field extra" in e for e in errors)


@pytest.mark.parametrize(
    "locator",
    [
        {"url": "https://example.com/talk"},
        {"page": 12},
        {"timestamp": "00:14:32"},
        {"timestamp": "4:05"},
        {"anchor": "section-slug"},
        {"url": "https://example.com/talk", "page": 3, "timestamp": "1:02:03", "anchor": "intro"},
    ],
)
def test_valid_source_locator_accepted(locator):
    claim = dict(VALID)
    claim["source_locator"] = locator
    assert validate_claim(claim, "S01") == []


def test_claim_without_locator_still_valid():
    claim = dict(VALID)
    assert "source_locator" not in claim
    assert validate_claim(claim, "S01") == []


@pytest.mark.parametrize(
    "locator,fragment",
    [
        ({"chapter": 3}, "unknown source_locator key chapter"),
        ({}, "at least one of url, page, timestamp, anchor"),
        ("page 12", "source_locator must be an object"),
        ({"timestamp": "12m30s"}, "H:MM or HH:MM:SS"),
        ({"timestamp": "1:2:03"}, "H:MM or HH:MM:SS"),
        ({"page": 0}, "positive integer"),
        ({"page": -4}, "positive integer"),
        ({"page": "12"}, "positive integer"),
        ({"url": ""}, "source_locator.url"),
    ],
)
def test_bad_source_locator_rejected(locator, fragment):
    claim = dict(VALID)
    claim["source_locator"] = locator
    errors = validate_claim(claim, "S01")
    assert errors, f"expected violation for source_locator={locator!r}"
    assert any(fragment in e for e in errors)


def test_workspace_generation(ws):
    pdir = make_project()
    run_extract("demo")
    for sid in ("S01", "S02", "S03"):
        assert (pdir / "claims" / f"{sid}-claims.jsonl").is_file()
    assert (pdir / "claims" / "EXTRACTION-INSTRUCTIONS.md").is_file()


def test_extract_verify_passes_demo_claims(ws):
    pdir = to_extracted()
    gate = read_gate(pdir, "02-extract")
    assert gate["status"] == "PASS"


def test_dangling_depends_on_fails_gate(ws):
    pdir = to_extracted()
    path = pdir / "claims" / "S03-claims.jsonl"
    claim = dict(VALID)
    claim.update(claim_id="S03-C099", source_id="S03", depends_on=["S03-C900"])
    path.write_text(
        path.read_text(encoding="utf-8") + json.dumps(claim) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("demo")
    assert not result["ok"]
    assert any("dangling depends_on" in r for r in result["gate"]["reasons"])


def test_duplicate_claim_id_fails_gate(ws):
    pdir = to_extracted()
    path = pdir / "claims" / "S01-claims.jsonl"
    text = path.read_text(encoding="utf-8")
    dup = next(l for l in text.splitlines() if l.strip().startswith("{"))
    path.write_text(text + dup + "\n", encoding="utf-8")
    result = run_extract_verify("demo")
    assert not result["ok"]
    assert any("duplicate claim_id" in r for r in result["gate"]["reasons"])


def test_coverage_heuristic_warns(ws, tmp_path):
    from resynth import config
    from resynth.intake import run_intake
    from resynth.project import run_init

    run_init("cov")
    big = tmp_path / "big.md"
    big.write_text("# Big source\n\n" + ("substantial content here " * 120), encoding="utf-8")
    run_intake("cov", [str(big)])
    run_extract("cov")
    pdir = config.project_dir("cov")
    (pdir / "claims" / "S01-claims.jsonl").write_text(
        json.dumps(VALID) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("cov")
    assert result["ok"]
    assert any("coverage" in w for w in result["gate"]["warnings"])


VIDEO_URL = "https://example.com/talks/argon2"


def _video_project(project="vid"):
    """A project with one handcrafted schema v2 video-transcript source."""
    from resynth import config
    from resynth.fsutil import sha256_text
    from resynth.intake import check_intake_gate
    from resynth.project import run_init

    run_init(project)
    pdir = config.project_dir(project)
    body = "# Argon2 conference talk\n\nThe speaker recommends Argon2id throughout.\n"
    frontmatter = (
        "---\n"
        "source_id: S01\n"
        "title: Argon2 conference talk\n"
        "origin: test\n"
        "author_or_tool: unknown\n"
        "date_authored: unknown\n"
        "date_ingested: '2026-06-12'\n"
        "authority_tier: unknown\n"
        "recency_rank: 1\n"
        f"sha256: {sha256_text(body)}\n"
        "schema_version: 2\n"
        "source_type: video-transcript\n"
        f"url: {VIDEO_URL}\n"
        "resolved_from: null\n"
        "transcript_status: fetched\n"
        "---\n"
    )
    (pdir / "sources" / "S01-argon2-conference-talk.md").write_text(
        frontmatter + body, encoding="utf-8"
    )
    check_intake_gate(pdir)
    run_extract(project)
    return pdir


def test_verify_warns_video_claim_without_timestamp(ws):
    pdir = _video_project()
    (pdir / "claims" / "S01-claims.jsonl").write_text(
        json.dumps(VALID) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("vid")
    assert result["ok"]
    assert any(
        "S01-C001: video source claim without a timestamp locator" in w
        for w in result["gate"]["warnings"]
    )


def test_verify_warns_locator_url_mismatch(ws):
    pdir = _video_project()
    claim = dict(VALID)
    claim["source_locator"] = {"timestamp": "00:14:32", "url": "https://elsewhere.example.com"}
    (pdir / "claims" / "S01-claims.jsonl").write_text(
        json.dumps(claim) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("vid")
    assert result["ok"]
    warnings = result["gate"]["warnings"]
    assert any("S01-C001: locator url does not match the source url" in w for w in warnings)
    assert not any("without a timestamp" in w for w in warnings)


def test_verify_no_url_warning_when_locator_url_matches(ws):
    pdir = _video_project()
    claim = dict(VALID)
    claim["source_locator"] = {"timestamp": "00:14:32", "url": VIDEO_URL}
    (pdir / "claims" / "S01-claims.jsonl").write_text(
        json.dumps(claim) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("vid")
    assert result["ok"]
    assert not any("locator url" in w for w in result["gate"]["warnings"])
