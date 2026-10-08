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
        json.dumps(dict(VALID, source_excerpt="substantial content here substantial content")) + "\n",
        encoding="utf-8",
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


VIDEO_EXCERPT = "The speaker recommends Argon2id throughout"


def test_verify_warns_video_claim_without_timestamp(ws):
    pdir = _video_project()
    (pdir / "claims" / "S01-claims.jsonl").write_text(
        json.dumps(dict(VALID, source_excerpt=VIDEO_EXCERPT)) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("vid")
    assert result["ok"]
    assert any(
        "S01-C001: video source claim without a timestamp locator" in w
        for w in result["gate"]["warnings"]
    )


def test_verify_warns_locator_url_mismatch(ws):
    pdir = _video_project()
    claim = dict(VALID, source_excerpt=VIDEO_EXCERPT)
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
    claim = dict(VALID, source_excerpt=VIDEO_EXCERPT)
    claim["source_locator"] = {"timestamp": "00:14:32", "url": VIDEO_URL}
    (pdir / "claims" / "S01-claims.jsonl").write_text(
        json.dumps(claim) + "\n", encoding="utf-8"
    )
    result = run_extract_verify("vid")
    assert result["ok"]
    assert not any("locator url" in w for w in result["gate"]["warnings"])


def _rewrite_first_claim(pdir, **changes):
    path = pdir / "claims" / "S01-claims.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("{"))
    claim = json.loads(lines[i])
    for key, value in changes.items():
        if value is None:
            claim.pop(key, None)
        else:
            claim[key] = value
    lines[i] = json.dumps(claim)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_excerpt_not_in_source_fails_gate(ws):
    pdir = to_extracted()
    _rewrite_first_claim(pdir, source_excerpt="bcrypt is banned in every framework reviewed")
    result = run_extract_verify("demo")
    assert not result["ok"]
    assert any("S01-C001: source_excerpt not found verbatim in S01" in r for r in result["gate"]["reasons"])


def test_excerpt_tolerates_wrapping_case_and_quote_style(ws):
    pdir = to_extracted()
    _rewrite_first_claim(pdir, source_excerpt="IDENTIFIES   Argon2id as the preferred algorithm   FOR password hashing")
    assert run_extract_verify("demo")["ok"]


def test_missing_excerpt_fails_unless_policy_relaxed(ws):
    pdir = to_extracted()
    _rewrite_first_claim(pdir, source_excerpt=None)
    result = run_extract_verify("demo")
    assert not result["ok"]
    assert any("S01-C001: missing source_excerpt" in r for r in result["gate"]["reasons"])
    rules = pdir / "merge-rules.yaml"
    rules.write_text(rules.read_text(encoding="utf-8").replace(
        "require_source_excerpt: true", "require_source_excerpt: false"), encoding="utf-8")
    result = run_extract_verify("demo")
    assert result["ok"]
    assert any("missing source_excerpt" in w for w in result["gate"]["warnings"])


def test_short_excerpt_rejected():
    errors = validate_claim(dict(VALID, source_excerpt="Argon2id"), "S01")
    assert any("at least" in e for e in errors)


def test_passing_gate_writes_provenance(ws):
    from resynth import provenance

    pdir = to_extracted()
    records = provenance.load(pdir)
    assert len(records) == 11
    rec = records["S02-C002"]
    assert rec["section"] == "What we run in production"
    assert rec["line_start"] == 8 and rec["status"] == "uncited"


def test_check_source_claims_is_read_only(ws):
    from resynth.extract import check_source_claims

    pdir = to_extracted()
    before = (pdir / "gates" / "02-extract.yaml").read_bytes()
    assert check_source_claims("demo", "S02")["ok"]
    _rewrite_first_claim(pdir, source_excerpt="not present anywhere in the source text")
    result = check_source_claims("demo", "S01")
    assert not result["ok"]
    assert any("not found verbatim" in p for p in result["problems"])
    assert (pdir / "gates" / "02-extract.yaml").read_bytes() == before
