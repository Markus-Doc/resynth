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


def _frontmatter_block(fm: dict) -> str:
    import yaml

    ordered = {k: fm[k] for k in FRONTMATTER_FIELDS}
    block = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{block}---\n"


def _title_of(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def check_intake_gate(pdir: Path, dry_run: bool = False) -> dict:
    reasons: list[str] = []
    checks: dict = {"sources": {}}
    sources = load_sources(pdir)
    if not sources:
        reasons.append("no sources ingested")
    for fm in sources:
        sid = fm.get("source_id", fm["_file"])
        problems = []
        for field in FRONTMATTER_FIELDS:
            if field not in fm or fm[field] in (None, ""):
                problems.append(f"missing frontmatter field {field}")
        tier = fm.get("authority_tier")
        if tier and tier not in AUTHORITY_TIERS:
            problems.append(f"invalid authority_tier '{tier}'")
        actual = sha256_text(fm["_body"])
        if fm.get("sha256") != actual:
            problems.append("sha256 does not match body content")
        checks["sources"][sid] = "ok" if not problems else problems
        reasons.extend(f"{sid}: {p}" for p in problems)
    checks["source_count"] = len(sources)
    return write_gate(pdir, "01-intake", reasons, checks, dry_run=dry_run)


def run_intake(project: str, source_paths: list[str], dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    existing = load_sources(pdir)
    by_hash = {fm["sha256"]: fm["source_id"] for fm in existing}
    next_n = len(existing) + 1
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
        sid = f"S{next_n:02d}"
        fm = {
            "source_id": sid,
            "title": _title_of(body, src.stem),
            "origin": str(src),
            "author_or_tool": "unknown",
            "date_authored": "unknown",
            "date_ingested": date.today().isoformat(),
            "authority_tier": "unknown",
            "recency_rank": next_n,
            "sha256": digest,
        }
        dest = pdir / "sources" / f"{sid}-{slugify(src.stem)}.md"
        outcome = safe_write(dest, _frontmatter_block(fm) + body, pdir, dry_run=dry_run)
        events.append({"source": src.name, "action": outcome, "source_id": sid})
        by_hash[digest] = sid
        next_n += 1
    gate = check_intake_gate(pdir, dry_run=dry_run)
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "events": events,
        "messages": [f"{e['source']}: {e['action']}" for e in events]
        + [f"gate 01-intake: {gate['status']}"],
    }
