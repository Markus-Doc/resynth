"""Workspace and path resolution for RESYNTH.

The workspace root defaults to the current working directory and can be
overridden with the RESYNTH_ROOT environment variable. All project state
lives under <root>/projects/<project> as plain text files.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ResynthError

GATE_NAMES = [
    "01-intake",
    "02-extract",
    "03-reconcile",
    "04-synthesis",
    "05-audit",
]

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
# section_order controls body section ordering in MASTER.md.
# List topic tags in the desired order. Empty means alphabetical.
section_order: []
"""


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
