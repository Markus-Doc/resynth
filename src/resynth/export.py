"""Machine readable export of the sealed master for downstream AI agents.

Downstream consumers read the file back with :func:`load_master`, which
accepts both the resynth-master/1 and resynth-master/2 payload formats.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .errors import ResynthError
from .fsutil import safe_write
from .gates import require_gate
from .intake import load_sources
from .synthesise import _plan, _split_sections

FORMAT_V1 = "resynth-master/1"
FORMAT_V2 = "resynth-master/2"


def _export_sources(pdir: Path) -> list[dict]:
    """Source frontmatter dicts in a uniform v2 shape, sorted by source_id."""
    out = []
    for fm in load_sources(pdir):
        src = {k: v for k, v in fm.items() if k not in {"_file", "_body"}}
        src.setdefault("schema_version", 1)
        src.setdefault("source_type", "report")
        src.setdefault("url", None)
        src.setdefault("resolved_from", None)
        out.append(src)
    return sorted(out, key=lambda s: s["source_id"])


def run_export(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_gate(pdir, "04-synthesis")
    plan = _plan(pdir)
    master = (pdir / "output" / "MASTER.md").read_text(encoding="utf-8")
    sections = [
        {"heading": h, "text": c.strip()} for h, c in _split_sections(master) if h
    ]
    payload = {
        "project": project,
        "format": FORMAT_V2,
        "sections": sections,
        "sources": _export_sources(pdir),
        "claims": sorted(plan["claims"].values(), key=lambda c: c["claim_id"]),
        "decisions": plan["decisions"],
        "winning_claims": plan["winners"],
        "conflicts": [d["group_id"] for d in plan["conflicts"]],
    }
    out = pdir / "output" / "MASTER.json"
    outcome = safe_write(
        out, json.dumps(payload, indent=2, sort_keys=True) + "\n", pdir, dry_run=dry_run
    )
    return {
        "ok": True,
        "events": [{"file": "MASTER.json", "action": outcome}],
        "messages": [f"output/MASTER.json: {outcome}"],
    }


def load_master(path: Path) -> dict:
    """Read a MASTER.json of format resynth-master/1 or /2."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tag = data.get("format") if isinstance(data, dict) else None
    if tag == FORMAT_V1:
        data.setdefault("sources", [])
        data["format_version"] = 1
    elif tag == FORMAT_V2:
        data["format_version"] = 2
    else:
        raise ResynthError(f"unsupported master format {tag}")
    return data
