"""File system helpers. All writes are non-destructive.

Replaced files are moved to a timestamped _trash directory inside the
project before the new content is written. Unchanged content is never
rewritten, which keeps every stage idempotent.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .errors import ResynthError


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def trash(path: Path, project_dir: Path) -> Path:
    """Move an existing file into the project's _trash directory."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        rel = path.resolve().relative_to(project_dir.resolve())
    except ValueError:
        rel = Path(path.name)
    dest = project_dir / "_trash" / stamp / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def safe_write(path: Path, content: str, project_dir: Path, dry_run: bool = False) -> str:
    """Write content to path without destroying prior state.

    Returns one of: unchanged, created, replaced, dry-run.
    """
    outcome = "created"
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return "unchanged"
        if dry_run:
            return "dry-run"
        trash(path, project_dir)
        outcome = "replaced"
    elif dry_run:
        return "dry-run"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return outcome


def read_text(path: Path) -> str:
    if not path.is_file():
        raise ResynthError(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


def iter_jsonl(path: Path):
    """Yield (lineno, raw_line, obj_or_None, error_or_None) for a JSONL file.

    Blank lines and lines starting with # are skipped. The comment extension
    is deliberate so generated workspaces can carry inline instructions.
    """
    for lineno, raw in enumerate(read_text(path).splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            obj = json.loads(stripped)
            err = None if isinstance(obj, dict) else "line is not a JSON object"
            yield lineno, raw, obj if err is None else None, err
        except json.JSONDecodeError as exc:
            yield lineno, raw, None, f"invalid JSON: {exc.msg}"


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file strictly, raising on the first malformed line."""
    out = []
    for lineno, _raw, obj, err in iter_jsonl(path):
        if err:
            raise ResynthError(f"{path.name}:{lineno}: {err}")
        out.append(obj)
    return out


def dump_yaml(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(read_text(path))
    if not isinstance(data, dict):
        raise ResynthError(f"{path} did not parse as a YAML mapping")
    return data


def parse_frontmatter(text: str, name: str) -> tuple[dict, str]:
    """Split a source file into (frontmatter dict, body)."""
    if not text.startswith("---\n"):
        raise ResynthError(f"{name}: missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ResynthError(f"{name}: unterminated YAML frontmatter")
    fm = yaml.safe_load(text[4:end])
    if not isinstance(fm, dict):
        raise ResynthError(f"{name}: frontmatter is not a mapping")
    return fm, text[end + 5 :]
