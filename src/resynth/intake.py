"""Stage 1: INTAKE. Copy sources into the project with provenance
frontmatter and a verified content hash."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from . import config
from .errors import ResynthError
from .fsutil import parse_frontmatter, safe_write, sha256_text
from .gates import write_gate

FRONTMATTER_FIELDS = [
    "source_id",
    "title",
    "origin",
    "author_or_tool",
    "date_authored",
    "date_ingested",
    "authority_tier",
    "recency_rank",
    "sha256",
]

AUTHORITY_TIERS = {"primary", "secondary", "tertiary", "unknown"}
SUPPORTED = {".md", ".txt", ".docx", ".pdf"}

SCHEMA_VERSION = 2
SOURCE_TYPES = {
    "report",
    "html-article",
    "pdf",
    "video-transcript",
    "webinar",
    "study-notes",
    "dataset",
    "notes",
    "other",
}
TRANSCRIPT_STATUSES = {"fetched", "pending"}
RESOLVED_FROM_RE = re.compile(r"^S\d{2}$")
V2_FIELDS = ["schema_version", "source_type", "url", "resolved_from"]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:48] or "source"


def _convert(path: Path) -> str:
    """Return the text content of a source file, converting if needed."""
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".docx":
        tool, args = "pandoc", [str(path), "-t", "gfm"]
        hint = "install pandoc to ingest .docx files (https://pandoc.org/installing.html)"
    elif suffix == ".pdf":
        tool, args = "pdftotext", ["-layout", str(path), "-"]
        hint = "install pdftotext to ingest .pdf files (part of poppler, https://poppler.freedesktop.org)"
    else:
        raise ResynthError(
            f"unsupported source format '{suffix}' for {path.name}. "
            f"Supported: .md .txt .docx .pdf"
        )
    exe = shutil.which(tool)
    if not exe:
        raise ResynthError(f"{tool} not found. {hint}")
    try:
        proc = subprocess.run(
            [exe, *args], capture_output=True, encoding="utf-8", errors="replace"
        )
    except OSError as err:
        raise ResynthError(f"{tool} could not be run: {err}") from err
    if proc.returncode != 0:
        raise ResynthError(f"{tool} failed on {path.name}: {proc.stderr.strip()}")
    return proc.stdout


def load_sources(pdir: Path) -> list[dict]:
    """Parse all ingested sources, returning frontmatter dicts with body."""
    out = []
    for f in sorted((pdir / "sources").glob("S*.md")):
        fm, body = parse_frontmatter(f.read_text(encoding="utf-8"), f.name)
        fm["_file"] = f.name
        fm["_body"] = body
        out.append(fm)
    return out


def frontmatter_block(fm: dict) -> str:
    """Render the YAML frontmatter body with keys in canonical order."""
    import yaml

    keys = [*FRONTMATTER_FIELDS, *V2_FIELDS]
    if "transcript_status" in fm:
        keys.append("transcript_status")
    ordered = {k: fm[k] for k in keys if k in fm}
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False)


def register_source(
    pdir: Path,
    body: str,
    *,
    title: str,
    origin: str,
    source_type: str = "report",
    url: str | None = None,
    resolved_from: str | None = None,
    author_or_tool: str = "unknown",
    date_authored: str = "unknown",
    transcript_status: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Number, dedup and write a source file with schema-v2 frontmatter."""
    digest = sha256_text(body)
    existing = load_sources(pdir)
    for prior in existing:
        if prior.get("sha256") == digest:
            return {
                "action": "duplicate",
                "source_id": prior["source_id"],
                "file": prior["_file"],
                "sha256": digest,
            }
    numbers = [
        int(m.group(1))
        for f in (pdir / "sources").glob("S*.md")
        if (m := re.match(r"^S(\d+)", f.name))
    ]
    n = max(numbers, default=0) + 1
    sid = f"S{n:02d}"
    fm = {
        "source_id": sid,
        "title": title,
        "origin": origin,
        "author_or_tool": author_or_tool,
        "date_authored": date_authored,
        "date_ingested": date.today().isoformat(),
        "authority_tier": "unknown",
        "recency_rank": n,
        "sha256": digest,
        "schema_version": SCHEMA_VERSION,
        "source_type": source_type,
        "url": url,
        "resolved_from": resolved_from,
    }
    if transcript_status is not None:
        fm["transcript_status"] = transcript_status
    dest = pdir / "sources" / f"{sid}-{slugify(title)}.md"
    if dry_run:
        return {"action": "dry-run", "source_id": sid, "file": dest.name, "sha256": digest}
    safe_write(dest, f"---\n{frontmatter_block(fm)}---\n" + body, pdir)
    return {"action": "created", "source_id": sid, "file": dest.name, "sha256": digest}


def _title_of(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _check_v2(fm: dict, known_ids: set) -> list[str]:
    problems = []
    stype = fm.get("source_type")
    if stype and stype not in SOURCE_TYPES:
        problems.append(f"invalid source_type '{stype}'")
    for key in ("url", "resolved_from"):
        if key not in fm:
            problems.append(f"missing frontmatter field {key}")
    ref = fm.get("resolved_from")
    if ref is not None:
        if not isinstance(ref, str) or not RESOLVED_FROM_RE.match(ref):
            problems.append(f"invalid resolved_from '{ref}'")
        elif ref not in known_ids:
            problems.append(f"resolved_from references unknown source {ref}")
    if "transcript_status" in fm:
        if fm["transcript_status"] not in TRANSCRIPT_STATUSES:
            problems.append(f"invalid transcript_status '{fm['transcript_status']}'")
        if stype != "video-transcript":
            problems.append("transcript_status only allowed for video-transcript sources")
    return problems


def check_intake_gate(pdir: Path, dry_run: bool = False) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    checks: dict = {"sources": {}}
    sources = load_sources(pdir)
    known_ids = {fm.get("source_id") for fm in sources}
    if not sources:
        reasons.append("no sources ingested")
    legacy = 0
    for fm in sources:
        sid = fm.get("source_id", fm["_file"])
        problems = []
        version = fm.get("schema_version")
        if "schema_version" not in fm:
            legacy += 1
        elif version != SCHEMA_VERSION:
            problems.append(f"unsupported schema_version {version}")
        required = list(FRONTMATTER_FIELDS)
        if version == SCHEMA_VERSION:
            required.append("source_type")
        for field in required:
            if field not in fm or fm[field] in (None, ""):
                problems.append(f"missing frontmatter field {field}")
        tier = fm.get("authority_tier")
        if tier and tier not in AUTHORITY_TIERS:
            problems.append(f"invalid authority_tier '{tier}'")
        if version == SCHEMA_VERSION:
            problems.extend(_check_v2(fm, known_ids))
        actual = sha256_text(fm["_body"])
        if fm.get("sha256") != actual:
            problems.append("sha256 does not match body content")
        checks["sources"][sid] = "ok" if not problems else problems
        reasons.extend(f"{sid}: {p}" for p in problems)
    if legacy:
        warnings.append(
            f"{legacy} source(s) use the pre 0.2.0 schema, run: resynth migrate {pdir.name}"
        )
    checks["source_count"] = len(sources)
    return write_gate(pdir, "01-intake", reasons, checks, warnings=warnings, dry_run=dry_run)


def run_intake(project: str, source_paths: list[str], dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    by_hash = {fm["sha256"]: fm["source_id"] for fm in load_sources(pdir)}
    events = []
    for raw in source_paths:
        src = Path(raw)
        if src.suffix.lower() not in SUPPORTED:
            raise ResynthError(
                f"unsupported source format '{src.suffix}' for {src.name}. "
                f"Supported: .md .txt .docx .pdf"
            )
        if not src.is_file():
            raise ResynthError(f"source file not found: {src}")
        body = _convert(src)
        digest = sha256_text(body)
        if digest in by_hash:
            events.append(
                {
                    "source": src.name,
                    "action": "rejected-duplicate",
                    "duplicate_of": by_hash[digest],
                }
            )
            continue
        result = register_source(
            pdir,
            body,
            title=_title_of(body, src.stem),
            origin=str(src),
            source_type="pdf" if src.suffix.lower() == ".pdf" else "report",
            dry_run=dry_run,
        )
        events.append(
            {"source": src.name, "action": result["action"], "source_id": result["source_id"]}
        )
        by_hash[digest] = result["source_id"]
    gate = check_intake_gate(pdir, dry_run=dry_run)
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "events": events,
        "messages": [f"{e['source']}: {e['action']}" for e in events]
        + [f"gate 01-intake: {gate['status']}"],
    }
