"""Read-only provenance views: trace one claim back to where it came from,
or summarise how well a whole project's claims trace to cited evidence."""

from __future__ import annotations

from . import config
from . import provenance
from .errors import ResynthError
from .extract import CLAIM_ID_RE, load_all_claims
from .intake import load_sources
from .reconcile import load_decisions
from .synthesise import cited_locations


def run_trace(project: str, claim_id: str) -> dict:
    pdir = config.project_dir(project)
    claim_id = claim_id.strip().upper()
    if not CLAIM_ID_RE.match(claim_id):
        raise ResynthError(f"'{claim_id}' is not a claim id, expected the S01-C001 form")
    claims = {c["claim_id"]: c for c in load_all_claims(pdir)}
    if claim_id not in claims:
        raise ResynthError(f"claim {claim_id} not found in project {project}")
    claim = claims[claim_id]
    source = next((fm for fm in load_sources(pdir) if fm["source_id"] == claim["source_id"]), None)
    decision = next((d for d in load_decisions(pdir) if claim_id in d.get("claim_ids", [])), None)
    record = provenance.load(pdir).get(claim_id)
    where_cited = cited_locations(pdir).get(claim_id)

    lines = [f"{claim_id}: {claim['claim_text']}"]
    if decision:
        others = [c for c in decision["claim_ids"] if c != claim_id]
        lines.append(f"Decision: {decision['decision']} {decision['group_id']}"
                     + (f" with {', '.join(others)}" if others else ""))
    if source:
        lines.append(f"Source: {source['source_id']} {source['title']} (original file {source['origin']})")
    if record:
        loc = provenance.location_label(record)
        lines.append(f"Location: {loc}" + (f", section {record['section']}" if record.get("section") else ""))
        lines.append(f'Excerpt: "{record["source_excerpt"]}"')
        if record["citations"]:
            lines.append("Evidence the source cites there:")
            lines += [f"  - {provenance.citation_label(c, markdown=False)}" for c in record["citations"]]
        else:
            lines.append("Evidence the source cites there: none, the statement is the source's own analysis")
    else:
        lines.append(f"Location: not verified, the claim has no source_excerpt ({claim['supporting_quote_location']})")
    lines.append(f"Cited in MASTER.md: {where_cited}" if where_cited else "Cited in MASTER.md: no")
    return {
        "ok": True,
        "claim": claim,
        "decision": decision,
        "source": {k: v for k, v in (source or {}).items() if not k.startswith("_")},
        "provenance": record,
        "cited_in": where_cited,
        "messages": lines,
    }


def run_provenance_report(project: str, status: str | None = None) -> dict:
    """Summary of the project's provenance index, optionally listing every
    claim with a given evidence status (cited, unresolved, uncited)."""
    pdir = config.project_dir(project)
    records = provenance.load(pdir)
    if not records:
        raise ResynthError(f"no provenance index yet, run resynth extract-verify {project}")
    claims = {c["claim_id"] for c in load_all_claims(pdir)}
    summary = provenance.summary(records)
    summary["claims_total"] = len(claims)
    summary["claims_not_located"] = sorted(claims - set(records))
    lines = [
        f"{summary['claims_located']} of {len(claims)} claims located verbatim in their source",
        f"cited (resolvable link or DOI): {summary['cited']}",
        f"unresolved (marker with no recoverable link): {summary['unresolved']}",
        f"uncited (the source cites nothing at that passage): {summary['uncited']}",
    ]
    if summary["claims_not_located"]:
        lines.append("not located: " + ", ".join(summary["claims_not_located"]))
    listed = []
    if status:
        listed = [r for r in sorted(records.values(), key=lambda r: r["claim_id"]) if r["status"] == status]
        lines.append(f"{status} claims:")
        lines += [f"  {r['claim_id']} {r['source_id']} {provenance.location_label(r)}" for r in listed]
    return {"ok": True, "summary": summary, "listed": [r["claim_id"] for r in listed], "messages": lines}
