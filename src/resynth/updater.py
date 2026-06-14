"""Self update for the git-based install.

RESYNTH installs as a shallow git checkout with an editable pip install
(`pip install -e`), so an update is just a fast-forward git pull: only the
files that actually changed are rewritten, and because the install is
editable the new code is live immediately, with no re-patch. A pip
reinstall only happens when the dependency set in pyproject.toml changes.

Everything here is best effort. The network probe is throttled to once a
day and never raises, so a launch never stalls or fails on a bad network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BRANCH = "main"
CHECK_TTL_SECONDS = 24 * 60 * 60  # throttle the network probe to once a day
_NET_TIMEOUT = 8
_PULL_TIMEOUT = 120


def app_root() -> Path | None:
    """Return the git checkout that holds this install, or None.

    The package lives at <root>/src/resynth/, so the root is two parents
    up. Self update only applies when that root is a git working tree
    (the standard installer layout); a plain PyPI install returns None.
    """
    root = Path(__file__).resolve().parents[2]
    return root if (root / ".git").exists() else None


def state_path() -> Path:
    """Where the throttle cache and last result live, outside the checkout."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RESYNTH"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "resynth"
    return base / "update-check.json"


def _read_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(data: dict) -> None:
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    except OSError:
        pass


def _git(root: Path, *args: str, timeout: int = _NET_TIMEOUT) -> tuple[int, str]:
    """Run one git command in root, returning (returncode, stdout+stderr)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def current_sha(root: Path) -> str | None:
    rc, out = _git(root, "rev-parse", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def remote_sha(root: Path, branch: str = BRANCH) -> str | None:
    """The tip sha of the remote branch, fetched without downloading objects."""
    rc, out = _git(root, "ls-remote", "origin", branch)
    if rc != 0:
        return None
    head = out.split()
    return head[0] if head else None


def _short(sha: str | None) -> str | None:
    return sha[:7] if sha else None


def check(*, throttle: bool = True) -> dict:
    """Decide whether a newer revision is available on origin.

    Returns a dict that always carries ``available``; ``error`` is set when
    the probe could not run. With throttle the network is skipped if the
    last probe is younger than the TTL and the cached result is reused.
    """
    root = app_root()
    if root is None:
        return {"available": False, "supported": False, "error": "not a git install"}

    local = current_sha(root)
    if local is None:
        return {"available": False, "supported": True, "error": "no local revision"}

    state = _read_state()
    now = time.time()
    if (
        throttle
        and state.get("local") == local
        and now - state.get("checked_at", 0) < CHECK_TTL_SECONDS
        and "latest" in state
    ):
        latest = state["latest"]
        return {
            "available": bool(latest) and latest != local,
            "supported": True,
            "current": local,
            "current_short": _short(local),
            "latest": latest,
            "latest_short": _short(latest),
            "cached": True,
        }

    latest = remote_sha(root)
    if latest is None:
        return {
            "available": False,
            "supported": True,
            "current": local,
            "current_short": _short(local),
            "error": "could not reach origin",
        }

    _write_state(
        {
            "local": local,
            "latest": latest,
            "checked_at": now,
            "checked_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return {
        "available": latest != local,
        "supported": True,
        "current": local,
        "current_short": _short(local),
        "latest": latest,
        "latest_short": _short(latest),
        "cached": False,
    }


def incoming_commits(root: Path, limit: int = 12) -> list[str]:
    """Subjects of commits on origin that are not in the local checkout.

    Needs object data, so it fetches first (a delta transfer). Returns an
    empty list if anything goes wrong.
    """
    if _git(root, "fetch", "--quiet", "origin", BRANCH, timeout=_PULL_TIMEOUT)[0] != 0:
        return []
    rc, out = _git(
        root,
        "log",
        "--no-merges",
        f"--max-count={limit}",
        "--pretty=format:%s",
        f"HEAD..origin/{BRANCH}",
    )
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _changed_files(root: Path, old: str, new: str) -> list[str]:
    rc, out = _git(root, "diff", "--name-only", old, new)
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _venv_pip(root: Path) -> list[str] | None:
    candidates = [
        root / ".venv" / "Scripts" / "pip.exe",
        root / ".venv" / "bin" / "pip",
    ]
    for cand in candidates:
        if cand.is_file():
            return [str(cand)]
    return None


def _reinstall_deps(root: Path) -> bool:
    """Re-run the editable install so changed dependencies are picked up."""
    pip = _venv_pip(root)
    cmd = (pip or [sys.executable, "-m", "pip"]) + ["install", "--quiet", "-e", str(root)]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def apply() -> dict:
    """Fast-forward the install to origin and report exactly what changed.

    Only changed and new files are written (git fast-forward), so unrelated
    files are left untouched. A pip reinstall runs only when pyproject.toml
    moved, keeping routine updates fast.
    """
    root = app_root()
    if root is None:
        return {"ok": False, "error": "RESYNTH is not a git install, nothing to update"}

    old = current_sha(root)
    if _git(root, "fetch", "--quiet", "origin", BRANCH, timeout=_PULL_TIMEOUT)[0] != 0:
        return {"ok": False, "error": "could not fetch from origin"}

    rc, out = _git(root, "merge", "--ff-only", f"origin/{BRANCH}", timeout=_PULL_TIMEOUT)
    if rc != 0:
        return {
            "ok": False,
            "error": (
                "the installed copy has diverged from origin and cannot fast-forward. "
                "Reinstall to recover.\n" + out.strip()
            ),
        }

    new = current_sha(root)
    if old == new:
        return {"ok": True, "updated": False, "current": new, "current_short": _short(new)}

    changed = _changed_files(root, old, new)
    deps_changed = "pyproject.toml" in changed
    deps_ok = _reinstall_deps(root) if deps_changed else None
    _write_state(
        {
            "local": new,
            "latest": new,
            "checked_at": time.time(),
            "checked_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return {
        "ok": True,
        "updated": True,
        "old": old,
        "old_short": _short(old),
        "new": new,
        "new_short": _short(new),
        "changed_files": changed,
        "deps_changed": deps_changed,
        "deps_reinstalled": deps_ok,
    }
