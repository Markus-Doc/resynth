"""Stage 2: CLAIM EXTRACTION. RESYNTH generates the workspace and
validates the operator's output. It never extracts claims itself."""

from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import config
from .errors import ResynthError
from .fsutil import iter_jsonl, safe_write
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
OPTIONAL_FIELDS = {"source_locator"}
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
    return errors


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
        if len(fm["_body"].encode("utf-8")) > COVERAGE_MIN_BYTES and count < COVERAGE_MIN_CLAIMS:
            warnings.append(
                f"{sid}: source over 2KB yielded only {count} claims, check coverage"
            )
    known = set(seen_ids)
    for obj in all_claims:
        for dep in obj.get("depends_on") or []:
            if dep not in known:
                reasons.append(f"{obj.get('claim_id')}: dangling depends_on reference {dep}")
    if not all_claims and not reasons:
        reasons.append("no claims extracted across any source")
    checks = {"claims_per_source": claims_by_source, "total_claims": len(all_claims)}
    gate = write_gate(pdir, "02-extract", reasons, checks, warnings=warnings, dry_run=dry_run)
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "messages": [f"gate 02-extract: {gate['status']}"]
        + [f"FAIL: {r}" for r in reasons]
        + [f"warn: {w}" for w in warnings],
    }
