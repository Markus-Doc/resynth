"""Stage 4: SYNTHESIS. Generates the master document scaffold and
verifies the operator's prose against the reconciliation record.

MASTER.md has two parts. The body, up to the Gaps section, is operator
prose. The appendices (source register and claim provenance) are generated
by RESYNTH and refreshed on every synthesise and synth-verify, so they always
match the sources, claims and provenance index on disk."""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import config
from . import provenance
from .extract import load_all_claims
from .fsutil import safe_write
from .gates import require_previous, write_gate
from .intake import load_sources
from .reconcile import load_decisions, merge_rules

CITE_RE = re.compile(r"S\d{2}-C\d{3}")
APPENDIX_MARK = "## Appendix: Source Register"
APPENDICES = {"Appendix: Source Register", "Appendix: Claim Provenance"}
SPECIAL_SECTIONS = {"Conflicts", "Gaps"} | APPENDICES


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(config.templates_dir())),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def section_title(tag: str) -> str:
    return " ".join(w.capitalize() for w in tag.split("-"))


def winning_claims(decisions: list[dict]) -> dict[str, str]:
    """Map of claim_id to group_id for every claim that must be cited."""
    winners = {}
    for d in decisions:
        if d["decision"] in {"CORROBORATED", "UNIQUE"}:
            for cid in d["claim_ids"]:
                winners[cid] = d["group_id"]
        elif d["decision"] == "SUPERSEDED":
            winners[d["winner"]] = d["group_id"]
    return winners


def _plan(pdir: Path) -> dict:
    claims = {c["claim_id"]: c for c in load_all_claims(pdir)}
    decisions = load_decisions(pdir)
    rules = merge_rules(pdir)
    winners = winning_claims(decisions)
    conflicts = [d for d in decisions if d["decision"] == "CONFLICT"]
    ordering = list(rules.get("section_order") or [])
    tags_in_play = sorted({t for cid in winners for t in claims[cid]["topic_tags"]})
    for tag in tags_in_play:
        if tag not in ordering:
            ordering.append(tag)
    sections: dict[str, list[str]] = {}
    for cid in sorted(winners):
        tag = next(t for t in ordering if t in claims[cid]["topic_tags"])
        sections.setdefault(tag, []).append(cid)
    section_list = [
        {"tag": tag, "title": section_title(tag), "claim_ids": sections[tag]}
        for tag in ordering
        if tag in sections
    ]
    return {
        "claims": claims,
        "decisions": decisions,
        "rules": rules,
        "winners": winners,
        "conflicts": conflicts,
        "sections": section_list,
    }


def _claim_briefs(plan: dict) -> dict[str, dict]:
    """Claim text plus decision context, so the scaffold alone is enough to
    write each section without opening the claims index or decision log."""
    briefs = {}
    for d in plan["decisions"]:
        for cid in d["claim_ids"]:
            others = [c for c in d["claim_ids"] if c != cid] if d["decision"] != "UNIQUE" else []
            briefs[cid] = {
                "claim_text": plan["claims"][cid]["claim_text"],
                "decision": d["decision"],
                "partners": others,
            }
    return briefs


def _source_rows(sources: list[dict]) -> list[dict]:
    return [
        {
            "source_id": fm["source_id"],
            "title": fm["title"],
            "source_type": fm.get("source_type") or "report",
            "url": fm.get("url"),
            "authority_tier": fm["authority_tier"],
            "date_authored": fm["date_authored"],
            "sha256_short": str(fm["sha256"])[:12],
        }
        for fm in sources
    ]


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _provenance_rows(pdir: Path, plan: dict) -> list[dict]:
    records = provenance.load(pdir)
    decision_of = {cid: d for d in plan["decisions"] for cid in d["claim_ids"]}
    rows = []
    for cid in sorted(plan["claims"]):
        rec = records.get(cid)
        d = decision_of.get(cid)
        decision = f"{d['decision']} {d['group_id']}" if d else "undecided"
        if not rec:
            rows.append({"claim_id": cid, "decision": decision, "where": f"{cid[:3]}, not located",
                         "excerpt": "-", "evidence": "no source_excerpt recorded"})
            continue
        where = f"{rec['source_id']} {provenance.location_label(rec)}"
        if rec.get("section"):
            where += f", {rec['section']}"
        evidence = "<br>".join(provenance.citation_label(c) for c in rec["citations"])
        rows.append({
            "claim_id": cid,
            "decision": decision,
            "where": _cell(where),
            "excerpt": '"' + _cell(rec["source_excerpt"]) + '"',
            "evidence": evidence or "none at this passage, the source's own analysis",
        })
    return rows


def render_appendices(pdir: Path, plan: dict | None = None) -> str:
    plan = plan or _plan(pdir)
    return _jinja().get_template("master-appendix.md.j2").render(
        sources=_source_rows(load_sources(pdir)),
        provenance_rows=_provenance_rows(pdir, plan),
    )


def with_appendices(text: str, appendices: str) -> str:
    """Replace everything from the source register heading down with freshly
    generated appendices, keeping the operator's body untouched."""
    cut = text.find(APPENDIX_MARK)
    body = text if cut < 0 else text[:cut]
    return body.rstrip("\n") + "\n\n" + appendices


def run_synthesise(project: str, dry_run: bool = False, force: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_previous(pdir, "04-synthesis")
    plan = _plan(pdir)
    sources = load_sources(pdir)
    master_path = pdir / "output" / "MASTER.md"
    appendices = render_appendices(pdir, plan)
    scaffold = _jinja().get_template("master.md.j2").render(
        project=project,
        sources=_source_rows(sources),
        rules=plan["rules"].get("rules", []),
        sections=plan["sections"],
        conflicts=plan["conflicts"],
        claims=_claim_briefs(plan),
    )
    scaffold = with_appendices(scaffold, appendices)
    if master_path.exists() and not force:
        existing = master_path.read_text(encoding="utf-8")
        if existing != scaffold:
            outcome = safe_write(master_path, with_appendices(existing, appendices), pdir, dry_run=dry_run)
            return {
                "ok": True,
                "events": [{"file": "MASTER.md", "action": "kept-existing"}],
                "messages": [
                    "MASTER.md already contains operator work, the body was left untouched.",
                    f"Generated appendices: {outcome}.",
                    "Use --force to regenerate, the prior version moves to _trash.",
                ],
            }
    outcome = safe_write(master_path, scaffold, pdir, dry_run=dry_run)
    return {
        "ok": True,
        "events": [{"file": "MASTER.md", "action": outcome}],
        "messages": [
            f"MASTER.md: {outcome}",
            "Operator writes prose into the scaffold, then runs synth-verify.",
        ],
    }


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split MASTER.md into (heading, content) pairs. Preamble heading is ''."""
    sections = []
    current = ""
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((current, "\n".join(buf)))
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    sections.append((current, "\n".join(buf)))
    return sections


def _blocks(content: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", content) if b.strip()]


def _is_prose(block: str) -> bool:
    first = block.lstrip()
    return not first.startswith((">", "<!--", "|", "#"))


def run_synth_verify(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_previous(pdir, "04-synthesis")
    plan = _plan(pdir)
    master_path = pdir / "output" / "MASTER.md"
    reasons: list[str] = []
    if not master_path.is_file():
        reasons.append("output/MASTER.md missing, run resynth synthesise")
        gate = write_gate(pdir, "04-synthesis", reasons, {}, dry_run=dry_run)
        return {"ok": False, "gate": gate, "messages": [f"gate 04-synthesis: {gate['status']}"]}
    text = with_appendices(master_path.read_text(encoding="utf-8"), render_appendices(pdir, plan))
    safe_write(master_path, text, pdir, dry_run=dry_run)
    if "[!todo]" in text:
        reasons.append("operator todo callouts remain in MASTER.md")
    sections = _split_sections(text)
    headings = [h for h, _ in sections if h]
    for required in ("Conflicts", "Gaps", "Appendix: Source Register"):
        if required not in headings:
            reasons.append(f"mandatory section '{required}' missing")
    cited: set[str] = set()
    for heading, content in sections:
        if heading in APPENDICES:
            continue
        for cid in CITE_RE.findall(content):
            cited.add(cid)
        if heading and heading not in SPECIAL_SECTIONS:
            prose = [b for b in _blocks(content) if _is_prose(b)]
            if not prose:
                reasons.append(f"body section '{heading}' has no prose")
            for block in prose:
                if not CITE_RE.search(block):
                    reasons.append(
                        f"body section '{heading}' has prose without provenance markers"
                    )
    known = set(plan["claims"])
    for cid in sorted(cited - known):
        reasons.append(f"cited claim {cid} does not exist")
    for cid, gid in sorted(plan["winners"].items()):
        if cid not in cited:
            reasons.append(f"winning claim {cid} (group {gid}) is never cited")
    conflicts_text = next((c for h, c in sections if h == "Conflicts"), "")
    for d in plan["conflicts"]:
        for cid in d["claim_ids"]:
            if cid not in CITE_RE.findall(conflicts_text):
                reasons.append(
                    f"conflict claim {cid} (group {d['group_id']}) absent from Conflicts section"
                )
    gaps_text = next((c for h, c in sections if h == "Gaps"), "")
    if not _blocks(gaps_text):
        reasons.append("Gaps section is empty")
    checks = {
        "claims_cited": len(cited & known),
        "winning_claims": len(plan["winners"]),
        "conflict_groups": len(plan["conflicts"]),
    }
    gate = write_gate(pdir, "04-synthesis", reasons, checks, dry_run=dry_run)
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "messages": [f"gate 04-synthesis: {gate['status']}"] + [f"FAIL: {r}" for r in reasons[:30]],
    }


def cited_locations(pdir: Path) -> dict[str, str]:
    """Map claim_id to the first section heading where it is cited."""
    master_path = pdir / "output" / "MASTER.md"
    if not master_path.is_file():
        return {}
    out: dict[str, str] = {}
    for heading, content in _split_sections(master_path.read_text(encoding="utf-8")):
        if heading in APPENDICES:
            continue
        for cid in CITE_RE.findall(content):
            out.setdefault(cid, heading or "preamble")
    return out
