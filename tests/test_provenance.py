"""Claim provenance: excerpt location and upstream citation extraction."""

from resynth import provenance
from resynth.provenance import SourceText, locate_claim, normalise


def _locate(body, excerpt, source_type="report", resolved=None):
    src = SourceText("S01", body, source_type)
    rec, errors, warnings = locate_claim(src, {"claim_id": "S01-C001", "source_excerpt": excerpt}, resolved)
    return rec, errors, warnings


NUMBERED = """# Report

## Findings

Bedrock routes au. profiles between Sydney and Melbourne.\\[1\\] OpenAI stores data in Australia but processes it offshore.\\[2\\]\\[3\\]

## Sources

1. [Bedrock cross-Region inference](https://aws.example.com/cris)
2. [Data controls](https://openai.example.com/your-data)
3. [AI Geek analysis](https://aigeek.example.au/residency)
"""


def test_numbered_footnotes_resolve_to_their_sentence_only():
    rec, errors, _ = _locate(NUMBERED, "processes it offshore")
    assert not errors
    assert rec["line_start"] == 5 and rec["section"] == "Findings"
    urls = [c["url"] for c in rec["citations"]]
    assert urls == ["https://openai.example.com/your-data", "https://aigeek.example.au/residency"]
    assert rec["status"] == "cited"


def test_first_sentence_gets_only_its_own_marker():
    rec, _, _ = _locate(NUMBERED, "routes au. profiles between Sydney and Melbourne")
    assert [c["marker"] for c in rec["citations"]] == ["[1]"]


MD_FOOTNOTES = """Claim with a markdown footnote.[^a] Another sentence.

[^a]: Vendor page https://vendor.example.com/page
"""


def test_markdown_footnote_definition():
    rec, _, _ = _locate(MD_FOOTNOTES, "Claim with a markdown footnote")
    assert rec["citations"][0]["url"] == "https://vendor.example.com/page"


AUTHOR_YEAR = """3.2 Refresh Scheduling

Adaptive schedules beat fixed intervals for freshness (Cho & Garcia-Molina, 2003; Azar et al.,
2018). Static intervals waste effort.

References

Azar, Y., Horvitz, E., & Lubetzky, E. (2018). Tractable near-optimal policies for crawling. PNAS.
https://doi.org/10.1073/pnas.1801519115
Cho, J., & Garcia-Molina, H. (2003). Effective page refresh policies for Web crawlers. ACM TODS.
https://doi.org/10.1145/958942.958945
"""


def test_author_year_citations_resolve_to_dois():
    rec, _, _ = _locate(AUTHOR_YEAR, "Adaptive schedules beat fixed intervals")
    assert rec["section"] == "3.2 Refresh Scheduling"
    urls = {c["marker"]: c["url"] for c in rec["citations"]}
    assert urls["Cho & Garcia-Molina, 2003"] == "https://doi.org/10.1145/958942.958945"
    assert urls["Azar et al., 2018"] == "https://doi.org/10.1073/pnas.1801519115"


def test_unknown_author_year_is_flagged_not_dropped():
    body = AUTHOR_YEAR.replace("Azar et al.,\n2018", "Nobody et al.,\n2019")
    rec, _, _ = _locate(body, "Adaptive schedules beat fixed intervals")
    missing = [c for c in rec["citations"] if c["marker"] == "Nobody et al., 2019"]
    assert missing and missing[0]["url"] is None


TOKENS = (
    "AWS separates In-Region, Geographic and Global routing. "
    "An endpoint in Sydney is not proof of inference there. "
    "citeturn5view1turn6view0 Microsoft differs.\n"
)


def test_paragraph_level_tokens_are_kept_and_marked_unresolved():
    rec, _, _ = _locate(TOKENS, "AWS separates In-Region, Geographic and Global routing")
    assert [c["marker"] for c in rec["citations"]] == ["turn5view1", "turn6view0"]
    assert all(c["scope"] == "paragraph" and c["url"] is None for c in rec["citations"])
    assert rec["status"] == "unresolved"


def test_excerpt_matches_across_token_blocks():
    rec, errors, _ = _locate(TOKENS, "proof of inference there. Microsoft differs")
    assert not errors and rec


TABLE = """| Platform | Claim | Source |
|---|---|---|
| OpenAI | Storage yes, processing no | [Data controls](https://openai.example.com/data) |
"""


def test_table_row_uses_the_whole_row():
    rec, _, _ = _locate(TABLE, "Storage yes, processing no")
    assert rec["citations"][0]["url"] == "https://openai.example.com/data"
    assert rec["citations"][0]["title"] == "Data controls"


def test_pdf_page_and_unnumbered_heading():
    body = "Intro text\n\n\fResearch Gaps\n\nThe most striking gap is vendor docs.\n"
    rec, _, _ = _locate(body, "most striking gap is vendor docs")
    assert rec["page"] == 2 and rec["section"] == "Research Gaps"


def test_video_timestamp():
    body = "## Transcript\n\n[00:01:02] Hello there.\n[00:14:32] Use Argon2id for every new system.\n"
    rec, _, _ = _locate(body, "Use Argon2id for every new system", source_type="video-transcript")
    assert rec["timestamp"] == "00:14:32"


def test_citation_fetched_as_resolved_source():
    rec, _, _ = _locate(TABLE, "Storage yes, processing no", resolved={"https://openai.example.com/data": "S04"})
    assert rec["citations"][0]["fetched_as"] == "S04"


def test_missing_and_ambiguous_excerpts():
    _, errors, _ = _locate(NUMBERED, "text that is not in the report")
    assert errors and "not found verbatim" in errors[0]
    body = "Repeated phrase here today. Repeated phrase here today."
    rec, _, warnings = _locate(body, "Repeated phrase here today")
    assert rec["occurrences"] == 2 and "occurs 2 times" in warnings[0]


def test_normalise_is_tolerant_of_copy_differences():
    assert normalise("It’s  **bold**\n and — smart") == normalise("it's bold and - SMART")
    assert normalise("model \\[1\\] text") == normalise("model text")


def test_labels():
    rec, _, _ = _locate(NUMBERED, "processes it offshore")
    assert provenance.location_label(rec) == "L5"
    label = provenance.citation_label(rec["citations"][0])
    assert label == "[[2] Data controls](https://openai.example.com/your-data)"


def test_trace_and_provenance_commands(ws):
    import json

    from click.testing import CliRunner
    from helpers import to_synthesised

    from resynth.cli import main

    to_synthesised()
    runner = CliRunner()
    out = runner.invoke(main, ["trace", "demo", "s02-c002"])
    assert out.exit_code == 0, out.output
    assert "CONFLICT G002 with S01-C002" in out.output
    assert "Location: L8-9, section What we run in production" in out.output
    assert "Cited in MASTER.md: Conflicts" in out.output
    out = runner.invoke(main, ["provenance", "demo", "--status", "uncited", "--json"])
    payload = json.loads(out.output)
    assert payload["summary"]["claims_located"] == 11 and len(payload["listed"]) == 11
    assert runner.invoke(main, ["trace", "demo", "S09-C001"]).exit_code == 1
    assert runner.invoke(main, ["check-claims", "demo", "s01"]).exit_code == 0


def test_master_appendix_traces_every_claim(ws):
    from helpers import to_synthesised

    pdir = to_synthesised()
    text = (pdir / "output" / "MASTER.md").read_text(encoding="utf-8")
    appendix = text.split("## Appendix: Claim Provenance", 1)[1]
    row = next(l for l in appendix.splitlines() if l.startswith("| S03-C002 |"))
    assert "S03 L8-9, Findings" in row
    assert '"successful credential stuffing attempts fell by 90 percent"' in row
    assert sum(1 for l in appendix.splitlines() if l.startswith("| S0")) == 11
