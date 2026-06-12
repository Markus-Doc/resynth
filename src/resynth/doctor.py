"""Environment probe. RESYNTH needs python and git, conversion helpers
are optional and only required for .docx and .pdf intake."""

from __future__ import annotations

import shutil
import subprocess
import sys


def _probe(cmd: str, flag: str = "--version") -> str | None:
    path = shutil.which(cmd)
    if not path:
        return None
    try:
        out = subprocess.run([path, flag], capture_output=True, text=True, timeout=15)
        first = (out.stdout or out.stderr).strip().splitlines()
        return first[0] if first else "present"
    except Exception:
        return "present"


def run_doctor() -> dict:
    py_ok = sys.version_info >= (3, 11)
    checks = {
        "python": {
            "value": sys.version.split()[0],
            "ok": py_ok,
            "required": True,
        },
        "git": {"value": _probe("git"), "ok": _probe("git") is not None, "required": True},
        "pandoc": {
            "value": _probe("pandoc"),
            "ok": _probe("pandoc") is not None,
            "required": False,
        },
        "pdftotext": {
            "value": _probe("pdftotext", "-v"),
            "ok": _probe("pdftotext", "-v") is not None,
            "required": False,
        },
    }
    healthy = all(c["ok"] for c in checks.values() if c["required"])
    notes = []
    if not checks["pandoc"]["ok"]:
        notes.append("pandoc missing, .docx intake unavailable")
    if not checks["pdftotext"]["ok"]:
        notes.append("pdftotext missing, .pdf intake unavailable")
    return {"ok": healthy, "healthy": healthy, "checks": checks, "notes": notes}
