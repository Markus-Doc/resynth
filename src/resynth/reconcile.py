"""Stage 3: RECONCILIATION. Builds the cross source claims index,
flags candidate duplicates and conflicts mechanically, and validates
the operator's reconciliation decisions."""

from __future__ import annotations

import json
import math
import re
from itertools import combinations
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import config
from .extract import CLAIM_ID_RE, load_all_claims
from .fsutil import iter_jsonl, load_yaml, safe_write
from .gates import require_previous, write_gate

DECISIONS = {"CORROBORATED", "UNIQUE", "SUPERSEDED", "CONFLICT", "OUT_OF_SCOPE"}
GROUP_ID_RE = re.compile(r"^G\d{3,}$")
FILL_UNIQUE_BY = "resynth --fill-unique"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
# IDF-weighted overlap thresholds, tuned on a 155-claim, three-report
# project: recall 0.46 at precision 0.34 against the operator's final groups,
# where plain Jaccard at 0.35 flagged nothing. A pair sharing a topic tag
# needs less lexical overlap than an untagged pair.
TAGGED_THRESHOLD = 0.12
UNTAGGED_THRESHOLD = 0.3
MIN_SHARED_TOKENS = 2
MAX_CANDIDATES = 400
STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been
before being below between both but by can could did do does doing down during each
few for from further had has have having here how i if in into is it its itself just
may might more most must no nor not of off on once only or other our out over own per
same should so some such than that the their them then there these they this those
through to too under until up very was we were what when where which while who whom
why will with within without would you your one two three via using used use make
makes made within across rather never every any each only also
""".split())


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(config.templates_dir())),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _tokens(text: str) -> set[str]:
    """Content tokens: stopwords dropped, plurals folded, dotted and hyphenated
    identifiers (model names, versions, regions) kept whole."""
    out = set()
    for tok in TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS or (len(tok) < 3 and not tok.isdigit()):
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.add(tok)
    return out


def _numbers(tokens: set[str]) -> set[str]:
    return {t for t in tokens if any(ch.isdigit() for ch in t)}


def _candidates(claims: list[dict]) -> list[dict]:
    """Cross-source claim pairs that may be duplicates or conflicts.

    Token sets are computed once per claim. Pairs from the same source are
    skipped, since reconciliation is about agreement between sources. Shared
    tokens are weighted by inverse document frequency, so a shared product
    name counts for more than a shared common word, and the weight is divided
    by the smaller claim's weight, so a short claim restated inside a longer
    one still scores high. Shared numbers that differ under a shared tag are
    flagged as a possible conflict even at lower overlap."""
    ordered = sorted(claims, key=lambda c: c["claim_id"])
    tokens = {c["claim_id"]: _tokens(c["claim_text"]) for c in ordered}
    freq: dict[str, int] = {}
    for toks in tokens.values():
        for tok in toks:
            freq[tok] = freq.get(tok, 0) + 1
    idf = {tok: math.log((len(ordered) + 1) / (n + 0.5)) for tok, n in freq.items()}
    weight = {cid: sum(idf[t] for t in toks) for cid, toks in tokens.items()}
    scored = []
    for a, b in combinations(ordered, 2):
        if a["source_id"] == b["source_id"]:
            continue
        ta, tb = tokens[a["claim_id"]], tokens[b["claim_id"]]
        if not ta or not tb:
            continue
        common = ta & tb
        smaller = min(weight[a["claim_id"]], weight[b["claim_id"]])
        overlap = sum(idf[t] for t in common) / smaller if smaller > 0 else 0.0
        shared_tags = sorted(set(a["topic_tags"]) & set(b["topic_tags"]))
        kind = None
        if len(common) >= MIN_SHARED_TOKENS:
            if overlap >= (TAGGED_THRESHOLD if shared_tags else UNTAGGED_THRESHOLD):
                kind = "overlap"
        na, nb = _numbers(ta), _numbers(tb)
        if shared_tags and na and nb and na != nb and len(common - na - nb) >= 2:
            kind = kind or "numeric-difference"
        if kind:
            scored.append((overlap, a["claim_id"], b["claim_id"], shared_tags, kind))
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    out = []
    for n, (overlap, ida, idb, shared_tags, kind) in enumerate(scored[:MAX_CANDIDATES], 1):
        out.append({
            "candidate_id": f"P{n:03d}",
            "claim_ids": [ida, idb],
            "shared_tags": shared_tags,
            "token_overlap": round(overlap, 3),
            "kind": kind,
        })
    return out


def _locator_hint(claim: dict) -> str:
    """Short deep link hint for the claims index, empty when absent."""
    loc = claim.get("source_locator")
    if not isinstance(loc, dict):
        return ""
    if loc.get("timestamp"):
        return f" @ {loc['timestamp']}"
    if loc.get("page"):
        return f" p. {loc['page']}"
    if loc.get("anchor"):
        return f" #{loc['anchor']}"
    return ""


def _claims_index_md(project: str, claims: list[dict]) -> str:
    """Every claim listed once, under its first topic tag, with any further
    tags noted inline. Listing a claim under each of its tags repeated it
    for every extra tag, which cost tokens without adding information."""
    by_tag: dict[str, list[dict]] = {}
    for c in claims:
        by_tag.setdefault(c["topic_tags"][0], []).append(c)
    lines = [
        f"# Claims index: {project}",
        "",
        "> [!info] Generated by resynth reconcile",
        "> Every extracted claim, listed once under its first topic tag.",
        "> Further tags follow the word also.",
        "",
    ]
    for tag in sorted(by_tag):
        lines.append(f"## {tag}")
        lines.append("")
        for c in sorted(by_tag[tag], key=lambda c: c["claim_id"]):
            extra = c["topic_tags"][1:]
            also = f", also {', '.join(extra)}" if extra else ""
            lines.append(
                f"- {c['claim_id']} ({c['claim_type']}, {c['confidence_as_stated']}{also})"
                f"{_locator_hint(c)} {c['claim_text']}"
            )
        lines.append("")
    return "\n".join(lines)


def validate_decision(obj: dict, known_claims: set[str], rules: list[str]) -> list[str]:
    errors = []
    required = {"group_id", "claim_ids", "decision", "rule_applied", "decided_by"}
    missing = required - obj.keys()
    errors.extend(f"missing field {f}" for f in sorted(missing))
    if missing:
        return errors
    if not isinstance(obj["group_id"], str) or not GROUP_ID_RE.match(obj["group_id"]):
        errors.append(f"group_id '{obj['group_id']}' does not match GNNN format")
    cids = obj["claim_ids"]
    if not isinstance(cids, list) or not cids:
        errors.append("claim_ids must be a non-empty list")
        cids = []
    for cid in cids:
        if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
            errors.append(f"claim id '{cid}' does not match SNN-CNNN format")
        elif cid not in known_claims:
            errors.append(f"claim id '{cid}' was never extracted")
    decision = obj["decision"]
    if decision not in DECISIONS:
        errors.append(f"decision '{decision}' not in {sorted(DECISIONS)}")
    if not isinstance(obj["decided_by"], str) or not obj["decided_by"].strip():
        errors.append("decided_by must be a non-empty string")
    if not isinstance(obj["rule_applied"], str) or not obj["rule_applied"].strip():
        errors.append("rule_applied must be a non-empty string")
    if decision == "SUPERSEDED":
        winner = obj.get("winner")
        if winner not in cids:
            errors.append("SUPERSEDED decision requires a winner drawn from claim_ids")
        if obj["rule_applied"] not in rules:
            errors.append(
                f"SUPERSEDED rule_applied '{obj['rule_applied']}' not in merge-rules.yaml"
            )
    if decision == "OUT_OF_SCOPE" and not str(obj.get("note", "")).strip():
        errors.append("OUT_OF_SCOPE decision requires a one line note giving the reason")
    return errors


def load_decisions(pdir: Path) -> list[dict]:
    path = pdir / "index" / "reconciliation.jsonl"
    if not path.is_file():
        return []
    out = []
    for _lineno, _raw, obj, err in iter_jsonl(path):
        if not err:
            out.append(obj)
    return out


def merge_rules(pdir: Path) -> dict:
    return load_yaml(pdir / "merge-rules.yaml")


def evaluate_gate(pdir: Path, dry_run: bool = False) -> dict:
    claims = load_all_claims(pdir)
    known = {c["claim_id"] for c in claims}
    rules = merge_rules(pdir).get("rules", [])
    reasons: list[str] = []
    path = pdir / "index" / "reconciliation.jsonl"
    decisions = []
    if path.is_file():
        for lineno, _raw, obj, err in iter_jsonl(path):
            if err:
                reasons.append(f"reconciliation.jsonl:{lineno}: {err}")
                continue
            reasons.extend(
                f"reconciliation.jsonl:{lineno}: {e}"
                for e in validate_decision(obj, known, rules)
            )
            decisions.append(obj)
    seen: dict[str, str] = {}
    group_ids: set[str] = set()
    for d in decisions:
        gid = str(d.get("group_id"))
        if gid in group_ids:
            reasons.append(f"duplicate group_id {gid}")
        group_ids.add(gid)
        for cid in d.get("claim_ids") or []:
            if cid in seen:
                reasons.append(f"claim {cid} appears in {seen[cid]} and {gid}")
            else:
                seen[cid] = gid
    undecided = sorted(known - set(seen))
    reasons.extend(f"claim {cid} has no reconciliation decision" for cid in undecided)
    warnings = []
    decision_of = {cid: d for d in decisions for cid in d.get("claim_ids") or []}
    for cand in _load_candidates(pdir):
        a, b = cand["claim_ids"]
        da, db = decision_of.get(a), decision_of.get(b)
        if da and db and da is not db and da.get("decision") == db.get("decision") == "UNIQUE":
            warnings.append(f"{cand['candidate_id']}: {a} and {b} were flagged as related but both stand UNIQUE")
    checks = {
        "claims_total": len(known),
        "claims_decided": len(seen),
        "decision_groups": len(decisions),
        "auto_filled_unique": sum(1 for d in decisions if d.get("decided_by") == FILL_UNIQUE_BY),
    }
    return write_gate(pdir, "03-reconcile", reasons, checks, warnings=warnings, dry_run=dry_run)


def _load_candidates(pdir: Path) -> list[dict]:
    path = pdir / "index" / "candidates.jsonl"
    if not path.is_file():
        return []
    return [obj for _n, _raw, obj, err in iter_jsonl(path) if not err]


def fill_unique(pdir: Path, claims: list[dict], candidates: list[dict], dry_run: bool = False) -> dict:
    """Record a UNIQUE group for every claim the operator left undecided,
    except claims flagged in a candidate pair, which always need an explicit
    operator decision. The operator then only writes the groups that need
    judgement, and the auto-filled groups stay visible through decided_by."""
    path = pdir / "index" / "reconciliation.jsonl"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    decisions = load_decisions(pdir)
    decided = {cid for d in decisions for cid in d.get("claim_ids") or []}
    flagged = {cid for c in candidates for cid in c["claim_ids"]}
    numbers = [int(m.group(1)) for d in decisions if (m := re.match(r"^G(\d+)$", str(d.get("group_id"))))]
    next_n = max(numbers, default=0) + 1
    lines, held = [], []
    for c in sorted(claims, key=lambda c: c["claim_id"]):
        cid = c["claim_id"]
        if cid in decided:
            continue
        if cid in flagged:
            held.append(cid)
            continue
        lines.append(json.dumps({
            "group_id": f"G{next_n:03d}", "claim_ids": [cid], "decision": "UNIQUE",
            "rule_applied": "single_source", "decided_by": FILL_UNIQUE_BY, "winner": None,
            "note": "no operator decision and no candidate relationship flagged",
        }))
        next_n += 1
    if lines:
        text = existing if not existing or existing.endswith("\n") else existing + "\n"
        safe_write(path, text + "\n".join(lines) + "\n", pdir, dry_run=dry_run)
    return {"filled": len(lines), "held_for_operator": held}


def run_reconcile(project: str, dry_run: bool = False, fill: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_previous(pdir, "03-reconcile")
    claims = load_all_claims(pdir)
    events = []
    index_md = _claims_index_md(project, claims)
    events.append(
        {"file": "claims-index.md", "action": safe_write(pdir / "index" / "claims-index.md", index_md, pdir, dry_run=dry_run)}
    )
    cands = _candidates(claims)
    cand_text = "".join(json.dumps(c) + "\n" for c in cands)
    events.append(
        {"file": "candidates.jsonl", "action": safe_write(pdir / "index" / "candidates.jsonl", cand_text, pdir, dry_run=dry_run)}
    )
    rules = merge_rules(pdir)
    instructions = _jinja().get_template("reconciliation-instructions.md.j2").render(
        project=project, candidates=cands, rules=rules.get("rules", [])
    )
    events.append(
        {
            "file": "RECONCILIATION-INSTRUCTIONS.md",
            "action": safe_write(pdir / "index" / "RECONCILIATION-INSTRUCTIONS.md", instructions, pdir, dry_run=dry_run),
        }
    )
    rec_path = pdir / "index" / "reconciliation.jsonl"
    if not rec_path.exists():
        header = (
            "# RESYNTH reconciliation decisions. One JSON object per line.\n"
            "# Lines starting with # are ignored. See RECONCILIATION-INSTRUCTIONS.md.\n"
            '# Template: {"group_id": "G001", "claim_ids": ["S01-C001"], "decision": "UNIQUE", '
            '"rule_applied": "single_source", "decided_by": "operator", "winner": null, "note": ""}\n'
        )
        events.append(
            {"file": "reconciliation.jsonl", "action": safe_write(rec_path, header, pdir, dry_run=dry_run)}
        )
    filled = None
    if fill:
        filled = fill_unique(pdir, claims, cands, dry_run=dry_run)
    gate = evaluate_gate(pdir, dry_run=dry_run)
    fill_msgs = []
    if filled is not None:
        fill_msgs.append(f"auto-filled UNIQUE groups: {filled['filled']}")
        if filled["held_for_operator"]:
            fill_msgs.append(
                "flagged in candidate pairs, decide these explicitly: " + ", ".join(filled["held_for_operator"])
            )
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "events": events,
        "candidates": len(cands),
        "filled": filled,
        "messages": [f"{e['file']}: {e['action']}" for e in events]
        + [f"candidate relationships flagged: {len(cands)}"] + fill_msgs + [f"gate 03-reconcile: {gate['status']}"]
        + [f"FAIL: {r}" for r in gate["reasons"][:20]],
    }
