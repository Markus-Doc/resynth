"""Machine readable export of the sealed master for downstream AI agents."""

from __future__ import annotations

import json

from . import config
from .fsutil import safe_write
from .gates import require_gate
from .synthesise import _plan, _split_sections


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
        "format": "resynth-master/1",
        "sections": sections,
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
