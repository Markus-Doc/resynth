"""Stage 2: CLAIM EXTRACTION. RESYNTH generates the workspace and
validates the operator's output. It never extracts claims itself."""

from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import config
from .errors import ResynthError
from . import provenance
from .fsutil import iter_jsonl, load_yaml, safe_write
from .gates import require_previous, write_gate
from .intake import load_sources

CLAIM_ID_RE = re.compile(r"^S\d{2}-C\d{3}$")
CLAIM_TYPES = {"fact", "finding", "recommendation", "definition", "metric", "procedure"}
CONFIDENCE = {"high", "medium", "low", "unstated"}
REQUIRED_FIELDS = {
    "claim_id",
    "source_id",
    "claim_text",
    "claim_type",
    "topic_tags",
    "supporting_quote_location",
    "confidence_as_stated",
    "depends_on",
}
OPTIONAL_FIELDS = {"source_locator", "source_excerpt"}
LOCATOR_KEYS = {"url", "page", "timestamp", "anchor"}
TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
COVERAGE_MIN_BYTES = 2048
COVERAGE_MIN_CLAIMS = 3

TEMPLATE_LINE = {
    "claim_id": "{sid}-C001",
    "source_id": "{sid}",
    "claim_text": "Normalised restatement of one claim from the source",
    "claim_type": "fact",
    "topic_tags": ["example-tag"],
    "supporting_quote_location": "Section heading or location reference",
    "source_excerpt": "Short verbatim phrase copied from the source sentence",
    "confidence_as_stated": "unstated",
    "depends_on": [],
}


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(config.templates_dir())),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _workspace_header(sid: str) -> str:
    example = json.dumps(
        {k: (v.format(sid=sid) if isinstance(v, str) else v) for k, v in TEMPLATE_LINE.items()}
    )
    return (
        f"# RESYNTH claim extraction workspace for {sid}\n"
        f"# One JSON object per line. Lines starting with # are ignored.\n"
        f"# Schema template, copy the line below, remove the leading #, fill it in:\n"
        f"# {example}\n"
        f'# optional: "source_locator": {{"url": "https://...", "page": 12, '
        f'"timestamp": "00:14:32", "anchor": "section-slug"}}\n'
    )


def run_extract(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_previous(pdir, "02-extract")
    sources = load_sources(pdir)
    events = []
    for fm in sources:
        sid = fm["source_id"]
        path = pdir / "claims" / f"{sid}-claims.jsonl"
        if path.exists():
            events.append({"file": path.name, "action": "kept-existing"})
            continue
        outcome = safe_write(path, _workspace_header(sid), pdir, dry_run=dry_run)
        events.append({"file": path.name, "action": outcome})
    instructions = _jinja().get_template("extraction-instructions.md.j2").render(
        project=project,
        sources=[{k: v for k, v in fm.items() if not k.startswith("_")} for fm in sources],
        schema_example=_workspace_header("S01"),
    )
    outcome = safe_write(
        pdir / "claims" / "EXTRACTION-INSTRUCTIONS.md", instructions, pdir, dry_run=dry_run
    )
    events.append({"file": "EXTRACTION-INSTRUCTIONS.md", "action": outcome})
    return {
        "ok": True,
        "events": events,
        "messages": [f"{e['file']}: {e['action']}" for e in events]
        + ["extraction workspace ready, operator fills claims then runs extract-verify"],
    }


def _validate_locator(loc) -> list[str]:
    if not isinstance(loc, dict):
        return ["source_locator must be an object"]
    errors = []
    if not loc:
        errors.append("source_locator must have at least one of url, page, timestamp, anchor")
    errors.extend(f"unknown source_locator key {k}" for k in sorted(loc.keys() - LOCATOR_KEYS))
    if "url" in loc and (not isinstance(loc["url"], str) or not loc["url"].strip()):
        errors.append("source_locator.url must be a non-empty string")
    if "page" in loc and (
        not isinstance(loc["page"], int) or isinstance(loc["page"], bool) or loc["page"] < 1
    ):
        errors.append("source_locator.page must be a positive integer")
    if "timestamp" in loc and (
        not isinstance(loc["timestamp"], str) or not TIMESTAMP_RE.match(loc["timestamp"])
    ):
        errors.append("source_locator.timestamp must look like H:MM or HH:MM:SS")
    if "anchor" in loc and (not isinstance(loc["anchor"], str) or not loc["anchor"].strip()):
        errors.append("source_locator.anchor must be a non-empty string")
    return errors


def validate_claim(obj: dict, sid: str) -> list[str]:
    errors = []
    missing = REQUIRED_FIELDS - obj.keys()
    extra = obj.keys() - REQUIRED_FIELDS - OPTIONAL_FIELDS
    errors.extend(f"missing field {f}" for f in sorted(missing))
    errors.extend(f"unknown field {f}" for f in sorted(extra))
    if missing or extra:
        return errors
    cid = obj["claim_id"]
    if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
        errors.append(f"claim_id '{cid}' does not match SNN-CNNN format")
    elif not cid.startswith(f"{sid}-"):
        errors.append(f"claim_id '{cid}' does not belong to source {sid}")
    if obj["source_id"] != sid:
        errors.append(f"source_id '{obj['source_id']}' does not match file source {sid}")
    if not isinstance(obj["claim_text"], str) or not obj["claim_text"].strip():
        errors.append("claim_text must be a non-empty string")
    if obj["claim_type"] not in CLAIM_TYPES:
        errors.append(f"claim_type '{obj['claim_type']}' not in {sorted(CLAIM_TYPES)}")
    tags = obj["topic_tags"]
    if (
        not isinstance(tags, list)
        or not tags
        or not all(isinstance(t, str) and t.strip() for t in tags)
    ):
        errors.append("topic_tags must be a non-empty list of strings")
    loc = obj["supporting_quote_location"]
    if not isinstance(loc, str) or not loc.strip():
        errors.append("supporting_quote_location must be a non-empty string")
    elif len(loc) > 240:
        errors.append("supporting_quote_location too long, use a section reference not a quote")
    if obj["confidence_as_stated"] not in CONFIDENCE:
        errors.append(
            f"confidence_as_stated '{obj['confidence_as_stated']}' not in {sorted(CONFIDENCE)}"
        )
    deps = obj["depends_on"]
    if not isinstance(deps, list) or not all(
        isinstance(d, str) and CLAIM_ID_RE.match(d) for d in deps
    ):
        errors.append("depends_on must be a list of claim ids in SNN-CNNN format")
    if "source_locator" in obj:
        errors.extend(_validate_locator(obj["source_locator"]))
    if "source_excerpt" in obj:
        excerpt = obj["source_excerpt"]
        size = len(provenance.normalise(excerpt)) if isinstance(excerpt, str) else 0
        if not isinstance(excerpt, str) or size < provenance.EXCERPT_MIN:
            errors.append(f"source_excerpt must be a verbatim phrase of at least {provenance.EXCERPT_MIN} characters")
        elif size > provenance.EXCERPT_MAX:
            errors.append(f"source_excerpt too long, keep it under {provenance.EXCERPT_MAX} characters")
    return errors


def excerpts_required(pdir: Path) -> bool:
    """Projects require a verifiable source_excerpt on every claim unless
    merge-rules.yaml sets require_source_excerpt: false (legacy projects)."""
    path = pdir / "merge-rules.yaml"
    if not path.is_file():
        return True
    return load_yaml(path).get("require_source_excerpt", True) is not False


def load_all_claims(pdir: Path) -> list[dict]:
    """Load claims across all sources, raising on any invalid line."""
    claims = []
    for f in sorted((pdir / "claims").glob("S*-claims.jsonl")):
        sid = f.name.split("-")[0]
        for lineno, _raw, obj, err in iter_jsonl(f):
            if err:
                raise ResynthError(f"{f.name}:{lineno}: {err}")
            problems = validate_claim(obj, sid)
            if problems:
                raise ResynthError(f"{f.name}:{lineno}: {problems[0]}")
            claims.append(obj)
    return claims


def run_extract_verify(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_previous(pdir, "02-extract")
    sources = load_sources(pdir)
    reasons: list[str] = []
    warnings: list[str] = []
    seen_ids: dict[str, str] = {}
    claims_by_source: dict[str, int] = {}
    all_claims: list[dict] = []
    for fm in sources:
        sid = fm["source_id"]
        path = pdir / "claims" / f"{sid}-claims.jsonl"
        if not path.is_file():
            reasons.append(f"{sid}: claims file missing, run resynth extract")
            continue
        count = 0
        src_type = fm.get("source_type")
        src_url = fm.get("url")
        for lineno, _raw, obj, err in iter_jsonl(path):
            where = f"{path.name}:{lineno}"
            if err:
                reasons.append(f"{where}: {err}")
                continue
            for problem in validate_claim(obj, sid):
                reasons.append(f"{where}: {problem}")
            cid = obj.get("claim_id")
            if isinstance(cid, str):
                if cid in seen_ids:
                    reasons.append(f"{where}: duplicate claim_id {cid}, first seen {seen_ids[cid]}")
                else:
                    seen_ids[cid] = where
            loc = obj.get("source_locator")
            loc = loc if isinstance(loc, dict) else {}
            if src_type == "video-transcript" and not loc.get("timestamp"):
                warnings.append(f"{cid}: video source claim without a timestamp locator")
            if src_url and loc.get("url") and loc["url"] != src_url:
                warnings.append(f"{cid}: locator url does not match the source url")
            count += 1
            all_claims.append(obj)
        claims_by_source[sid] = count
        if count == 0:
            # A report that yields nothing usually means its extraction never
            # ran or failed. A fetched link may legitimately hold nothing.
            msg = f"{sid}: no claims extracted from this source"
            (warnings if fm.get("resolved_from") else reasons).append(msg)
        elif len(fm["_body"].encode("utf-8")) > COVERAGE_MIN_BYTES and count < COVERAGE_MIN_CLAIMS:
            warnings.append(
                f"{sid}: source over 2KB yielded only {count} claims, check coverage"
            )
    required = excerpts_required(pdir)
    for obj in all_claims:
        if "source_excerpt" not in obj:
            msg = f"{obj.get('claim_id')}: missing source_excerpt, copy a short verbatim phrase from the source"
            (reasons if required else warnings).append(msg)
    records, prov_errors, prov_warnings = provenance.build(sources, all_claims)
    reasons.extend(prov_errors)
    warnings.extend(prov_warnings)
    known = set(seen_ids)
    for obj in all_claims:
        for dep in obj.get("depends_on") or []:
            if dep not in known:
                reasons.append(f"{obj.get('claim_id')}: dangling depends_on reference {dep}")
    if not all_claims and not reasons:
        reasons.append("no claims extracted across any source")
    checks = {
        "claims_per_source": claims_by_source,
        "total_claims": len(all_claims),
        "provenance": provenance.summary(records),
    }
    if not reasons:
        provenance.write(pdir, records, dry_run=dry_run)
    gate = write_gate(pdir, "02-extract", reasons, checks, warnings=warnings, dry_run=dry_run)
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "messages": [f"gate 02-extract: {gate['status']}"]
        + [f"FAIL: {r}" for r in reasons]
        + [f"warn: {w}" for w in warnings],
    }


def check_source_claims(project: str, source_id: str) -> dict:
    """Read-only check of one source's claims file. Writes nothing, so several
    operators extracting different sources in parallel can each run it."""
    pdir = config.project_dir(project)
    sources = {fm["source_id"]: fm for fm in load_sources(pdir)}
    if source_id not in sources:
        raise ResynthError(f"unknown source {source_id}")
    path = pdir / "claims" / f"{source_id}-claims.jsonl"
    if not path.is_file():
        raise ResynthError(f"{path.name} missing, run resynth extract {project}")
    problems: list[str] = []
    claims: list[dict] = []
    seen: set[str] = set()
    required = excerpts_required(pdir)
    for lineno, _raw, obj, err in iter_jsonl(path):
        where = f"{path.name}:{lineno}"
        if err:
            problems.append(f"{where}: {err}")
            continue
        problems.extend(f"{where}: {p}" for p in validate_claim(obj, source_id))
        if obj.get("claim_id") in seen:
            problems.append(f"{where}: duplicate claim_id {obj.get('claim_id')}")
        seen.add(obj.get("claim_id"))
        if "source_excerpt" not in obj and required:
            problems.append(f"{where}: missing source_excerpt")
        claims.append(obj)
    _records, errors, warnings = provenance.build([sources[source_id]], claims)
    problems.extend(errors)
    if not claims:
        problems.append(f"{path.name}: no claims yet")
    status = "PASS" if not problems else "FAIL"
    return {
        "ok": not problems,
        "source_id": source_id,
        "claims": len(claims),
        "problems": problems,
        "warnings": warnings,
        "messages": [f"{source_id} claims check: {status} ({len(claims)} claims)"]
        + [f"FAIL: {p}" for p in problems] + [f"warn: {w}" for w in warnings],
    }
