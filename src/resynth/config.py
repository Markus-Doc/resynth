"""Workspace and path resolution for RESYNTH.

The workspace root defaults to the current working directory and can be
overridden with the RESYNTH_ROOT environment variable. All project state
lives under <root>/projects/<project> as plain text files.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ResynthError
from .fsutil import load_yaml

GATE_NAMES = [
    "01-intake",
    "02-extract",
    "03-reconcile",
    "04-synthesis",
    "05-audit",
]

# Light projects skip reconciliation and audit. Their synthesis gate follows
# straight on from extraction.
LIGHT_GATE_NAMES = ["01-intake", "02-extract", "04-synthesis"]
MODES = ("deep", "light")
LIGHT_SOURCE_CAP = 30
LIGHT_CLAIMS_PER_SOURCE = 15
LIGHT_WORD_LIMIT = 1200

PROJECT_SUBDIRS = ["sources", "claims", "index", "output", "gates", "_trash"]

DEFAULT_MERGE_RULES = """\
# RESYNTH merge rules. Edit per project as required.
# rules are applied by the operator during reconciliation and recorded
# in each decision under rule_applied.
rules:
  - newer_beats_older
  - primary_beats_secondary
  - explicit_beats_implied
  - conflicts_are_logged_not_resolved
# Every claim must carry a short verbatim source_excerpt that RESYNTH finds
# in its source, which pins the claim to a line and to the evidence the
# source cites there. Set false only for legacy projects made before 0.3.0.
require_source_excerpt: true
# section_order controls body section ordering in MASTER.md.
# List topic tags in the desired order. Empty means alphabetical.
section_order: []
"""

MODE_RULE = """# deep runs the full five gate pipeline. light is for everyday questions:
# at most {cap} sources, claims that answer the brief only, one AI task and
# a two page master. Set at init, do not change it mid project.
mode: {mode}
"""


def merge_rules_text(mode: str = "deep") -> str:
    if mode not in MODES:
        raise ResynthError(f"unknown mode '{mode}', expected one of {', '.join(MODES)}")
    return DEFAULT_MERGE_RULES + MODE_RULE.format(cap=LIGHT_SOURCE_CAP, mode=mode)


def project_mode(pdir: Path) -> str:
    """light or deep. Projects made before light mode existed are deep."""
    path = pdir / "merge-rules.yaml"
    if not path.is_file():
        return "deep"
    return "light" if (load_yaml(path) or {}).get("mode") == "light" else "deep"


def gate_names(pdir: Path) -> list[str]:
    return LIGHT_GATE_NAMES if project_mode(pdir) == "light" else GATE_NAMES


def workspace_root() -> Path:
    env = os.environ.get("RESYNTH_ROOT")
    return Path(env).resolve() if env else Path.cwd()


def projects_root() -> Path:
    return workspace_root() / "projects"


def project_dir(project: str, must_exist: bool = True) -> Path:
    pdir = projects_root() / project
    if must_exist and not pdir.is_dir():
        raise ResynthError(
            f"project '{project}' not found at {pdir}. Run: resynth init {project}"
        )
    return pdir


def runs_dir() -> Path:
    return workspace_root() / "runs"


def templates_dir() -> Path:
    """Locate the jinja2 templates directory at the repository root."""
    candidates = [
        Path(__file__).resolve().parents[2] / "templates",
        Path(__file__).resolve().parent / "templates",
    ]
    for cand in candidates:
        if cand.is_dir():
            return cand
    raise ResynthError("templates directory not found, expected at repo root")
