"""Run logging. Timestamps live here and only here, never in artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config


def write_run_log(command: str, project: str | None, events: list[dict], dry_run: bool) -> str:
    now = datetime.now(timezone.utc)
    rdir = config.runs_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    name = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{command}.jsonl"
    path = rdir / name
    lines = [
        json.dumps(
            {
                "ts": now.isoformat(),
                "command": command,
                "project": project,
                "dry_run": dry_run,
            }
        )
    ]
    lines.extend(json.dumps(ev) for ev in events)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return str(path)
