"""Project upgrader for RESYNTH v0.2.0. Rewrites schema v1 source
frontmatter to schema v2 in place, preserving each source body byte for
byte so the stored content hashes remain valid."""

from __future__ import annotations

from . import config, intake
from .errors import ResynthError
from .fsutil import parse_frontmatter, safe_write


def run_migrate(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    files = sorted((pdir / "sources").glob("S*.md"))
    if not files:
        raise ResynthError("no sources to migrate, run resynth intake first")
    events: list[dict] = []
    messages: list[str] = []
    upgraded = 0
    for f in files:
        fm, body = parse_frontmatter(f.read_text(encoding="utf-8"), f.name)
        sid = fm.get("source_id", f.name)
        if "schema_version" in fm:
            events.append({"source": sid, "action": "unchanged"})
            messages.append(f"{sid}: already schema v2")
            continue
        origin = str(fm.get("origin", ""))
        stype = "pdf" if origin.lower().endswith(".pdf") else "report"
        fm["schema_version"] = intake.SCHEMA_VERSION
        fm["source_type"] = stype
        fm["url"] = None
        fm["resolved_from"] = None
        content = f"---\n{intake.frontmatter_block(fm)}---\n" + body
        outcome = safe_write(f, content, pdir, dry_run=dry_run)
        events.append({"source": sid, "action": outcome, "source_type": stype})
        if outcome == "dry-run":
            messages.append(f"{sid}: would upgrade to schema v2 (source_type {stype})")
        else:
            upgraded += 1
            messages.append(f"{sid}: upgraded to schema v2 (source_type {stype})")
    if upgraded:
        messages.extend(
            [
                "Frontmatter has changed, so the existing seal no longer matches these files.",
                "The sealed git tag still pins the old state.",
                f"When you are ready, re-seal with: resynth audit {project} "
                f"then resynth seal {project}",
            ]
        )
    gate = None
    if not dry_run:
        gate = intake.check_intake_gate(pdir)
        messages.append(f"gate 01-intake: {gate['status']}")
    return {
        "ok": True if dry_run else gate["status"] == "PASS",
        "gate": gate,
        "events": events,
        "messages": messages,
    }
