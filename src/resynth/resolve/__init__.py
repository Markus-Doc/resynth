"""Stage 1.5: RESOLVE. Follow links inside ingested sources, fetch the
linked material and register it as new sources with provenance.

Outcomes are tracked in index/resolution.jsonl so re-runs are cheap and
byte identical when nothing changed.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .. import config, intake
from ..errors import ResynthError
from ..fsutil import iter_jsonl, parse_frontmatter, safe_write, sha256_text
from .discover import discover_targets
from .fetchers import classify_target, fetch_local, fetch_url, fetch_vimeo, fetch_youtube
from .net import FetchError

MANIFEST = "resolution.jsonl"

_HEADER = (
    "# RESYNTH source resolution manifest. One JSON object per line records a\n"
    "# discovered link target and its outcome: fetched, duplicate,\n"
    "# transcript_pending or failed. Maintained by `resynth resolve`."
)
_KEYS = ["target", "kind", "status", "source_id", "resolved_from", "sha256", "fetched_at", "note"]
_FETCHERS = {"local": fetch_local, "youtube": fetch_youtube, "vimeo": fetch_vimeo, "url": fetch_url}


def manifest_path(pdir: Path) -> Path:
    return pdir / "index" / MANIFEST


def _load_manifest(pdir: Path) -> dict[str, dict]:
    path = manifest_path(pdir)
    out: dict[str, dict] = {}
    if path.is_file():
        for _lineno, _raw, obj, err in iter_jsonl(path):
            if obj is not None and obj.get("target"):
                out[obj["target"]] = obj
    return out


def _write_manifest(pdir: Path, records: list[dict]) -> None:
    lines = [_HEADER]
    lines += [json.dumps({k: rec.get(k) for k in _KEYS}, ensure_ascii=False) for rec in records]
    safe_write(manifest_path(pdir), "\n".join(lines) + "\n", pdir)


def _record(
    target: str,
    kind: str,
    status: str,
    *,
    source_id: str | None = None,
    resolved_from: str | None = None,
    sha256: str | None = None,
    note: str | None = None,
    prior: dict | None = None,
) -> dict:
    rec = {
        "target": target,
        "kind": kind,
        "status": status,
        "source_id": source_id,
        "resolved_from": resolved_from,
        "sha256": sha256,
        "fetched_at": None,
        "note": note,
    }
    if (
        prior is not None
        and prior.get("fetched_at")
        and all(prior.get(k) == rec[k] for k in _KEYS if k != "fetched_at")
    ):
        return prior
    rec["fetched_at"] = date.today().isoformat()
    return rec


def _scan_targets(scan: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for fm in scan:
        origin = fm.get("origin")
        origin = origin if isinstance(origin, str) else ""
        for t in discover_targets(fm.get("_body", ""), origin):
            if t["raw"] in seen:
                continue
            seen.add(t["raw"])
            out.append(
                {"raw": t["raw"], "kind": classify_target(t["raw"]), "parent": fm.get("source_id")}
            )
    return out


def preview_targets(project: str) -> list[dict]:
    """Discovery only, no network: targets with parent sid and kind."""
    pdir = config.project_dir(project)
    scan = [fm for fm in intake.load_sources(pdir) if not fm.get("resolved_from")]
    return _scan_targets(scan)


def _upgrade_source(pdir: Path, sid: str, doc: dict) -> str:
    """Rewrite an existing pending stub in place, keeping its identity."""
    matches = sorted((pdir / "sources").glob(f"{sid}-*.md"))
    if not matches:
        raise ResynthError(f"source file for {sid} not found, cannot upgrade transcript")
    path = matches[0]
    fm, _old = parse_frontmatter(path.read_text(encoding="utf-8"), path.name)
    body = doc["body_markdown"]
    fm["title"] = doc["title"]
    fm["sha256"] = sha256_text(body)
    fm["transcript_status"] = doc["transcript_status"]
    safe_write(path, f"---\n{intake.frontmatter_block(fm)}---\n{body}", pdir)
    return fm["sha256"]


def run_resolve(
    project: str,
    only: str | None = None,
    source_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    pdir = config.project_dir(project)
    sources = intake.load_sources(pdir)
    if not sources:
        raise ResynthError(
            f"project '{project}' has no sources, run: resynth intake {project} <files>"
        )
    if source_ids:
        by_id = {fm.get("source_id"): fm for fm in sources}
        missing = [sid for sid in source_ids if sid not in by_id]
        if missing:
            raise ResynthError(f"unknown source id(s): {', '.join(missing)}")
        scan = [by_id[sid] for sid in source_ids]
    else:
        scan = [fm for fm in sources if not fm.get("resolved_from")]
    targets = _scan_targets(scan)
    prior_manifest = _load_manifest(pdir)
    manifest = dict(prior_manifest)
    counts = {"fetched": 0, "cached": 0, "duplicate": 0, "transcript_pending": 0, "failed": 0}
    messages: list[str] = []
    events: list[dict] = []

    for t in targets:
        raw, kind, parent = t["raw"], t["kind"], t["parent"]
        if only and only.lower() not in raw.lower():
            continue
        prior = prior_manifest.get(raw)
        if prior and prior.get("status") in ("fetched", "duplicate"):
            counts["cached"] += 1
            messages.append(f"{raw}: cached ({prior.get('source_id')})")
            events.append({"target": raw, "action": "cached", "source_id": prior.get("source_id")})
            continue
        if dry_run:
            counts["fetched"] += 1
            messages.append(f"{raw}: would fetch ({kind})")
            events.append({"target": raw, "action": "would-fetch", "kind": kind})
            continue
        try:
            doc = _FETCHERS[kind](raw)
        except FetchError as err:
            note = str(err)
            manifest[raw] = _record(
                raw,
                kind,
                "failed",
                source_id=prior.get("source_id") if prior else None,
                resolved_from=parent,
                note=note,
                prior=prior,
            )
            counts["failed"] += 1
            messages.append(f"{raw}: failed ({note})")
            events.append({"target": raw, "action": "failed", "note": note})
            continue
        pending = doc["transcript_status"] == "pending"
        prior_sid = prior.get("source_id") if prior else None
        if prior_sid and prior.get("status") in ("transcript_pending", "failed"):
            resolved_from = prior.get("resolved_from") or parent
            if pending:
                manifest[raw] = _record(
                    raw,
                    kind,
                    "transcript_pending",
                    source_id=prior_sid,
                    resolved_from=resolved_from,
                    sha256=prior.get("sha256"),
                    prior=prior,
                )
                counts["transcript_pending"] += 1
                messages.append(f"{raw}: transcript pending, stub created as {prior_sid}")
                events.append(
                    {"target": raw, "action": "transcript-pending", "source_id": prior_sid}
                )
                continue
            digest = _upgrade_source(pdir, prior_sid, doc)
            manifest[raw] = _record(
                raw,
                kind,
                "fetched",
                source_id=prior_sid,
                resolved_from=resolved_from,
                sha256=digest,
                prior=prior,
            )
            counts["fetched"] += 1
            messages.append(f"{raw}: fetched as {prior_sid} ({doc['source_type']})")
            events.append({"target": raw, "action": "upgraded", "source_id": prior_sid})
            continue
        result = intake.register_source(
            pdir,
            doc["body_markdown"],
            title=doc["title"],
            origin=doc["origin"],
            source_type=doc["source_type"],
            url=doc["url"],
            resolved_from=parent,
            author_or_tool=doc["author_or_tool"],
            date_authored=doc["date_authored"],
            transcript_status=doc["transcript_status"],
        )
        sid = result["source_id"]
        if result["action"] == "duplicate":
            status = "duplicate"
            messages.append(f"{raw}: duplicate of {sid}")
        elif pending:
            status = "transcript_pending"
            messages.append(f"{raw}: transcript pending, stub created as {sid}")
        else:
            status = "fetched"
            messages.append(f"{raw}: fetched as {sid} ({doc['source_type']})")
        counts[status] += 1
        manifest[raw] = _record(
            raw, kind, status, source_id=sid, resolved_from=parent, sha256=result["sha256"],
            prior=prior,
        )
        events.append({"target": raw, "action": status, "source_id": sid})

    if not dry_run:
        ordered: list[dict] = []
        emitted: set[str] = set()
        for t in targets:
            rec = manifest.get(t["raw"])
            if rec is not None and t["raw"] not in emitted:
                ordered.append(rec)
                emitted.add(t["raw"])
        for raw, rec in prior_manifest.items():
            if raw not in emitted:
                ordered.append(rec)
                emitted.add(raw)
        if ordered:
            _write_manifest(pdir, ordered)
    gate = intake.check_intake_gate(pdir, dry_run=dry_run)
    messages.append(f"gate 01-intake: {gate['status']}")
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "counts": counts,
        "events": events,
        "messages": messages,
    }
