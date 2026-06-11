"""Gate files. Each pipeline stage writes a YAML gate report.

A stage may only run when the previous stage's gate reports PASS.
Gate files carry no timestamps so re-evaluation with unchanged inputs
is byte identical.
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .errors import ResynthError
from .fsutil import dump_yaml, load_yaml, safe_write

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"

STAGE_BEFORE = {
    "02-extract": "01-intake",
    "03-reconcile": "02-extract",
    "04-synthesis": "03-reconcile",
    "05-audit": "04-synthesis",
}


def gate_path(pdir: Path, gate: str) -> Path:
    return pdir / "gates" / f"{gate}.yaml"


def read_gate(pdir: Path, gate: str) -> dict:
    path = gate_path(pdir, gate)
    if not path.is_file():
        return {"gate": gate, "status": PENDING, "reasons": []}
    return load_yaml(path)


def write_gate(
    pdir: Path,
    gate: str,
    reasons: list[str],
    checks: dict,
    warnings: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    status = PASS if not reasons else FAIL
    data = {
        "gate": gate,
        "status": status,
        "reasons": reasons,
        "warnings": warnings or [],
        "checks": checks,
    }
    safe_write(gate_path(pdir, gate), dump_yaml(data), pdir, dry_run=dry_run)
    return data


def require_gate(pdir: Path, gate: str) -> None:
    """Raise unless the named gate currently reports PASS."""
    state = read_gate(pdir, gate)
    if state.get("status") != PASS:
        raise ResynthError(
            f"gate {gate} is {state.get('status')}, this stage cannot run. "
            f"Resolve the earlier stage first."
        )


def require_previous(pdir: Path, gate: str) -> None:
    prev = STAGE_BEFORE.get(gate)
    if prev:
        require_gate(pdir, prev)


def all_gates(pdir: Path) -> dict[str, str]:
    return {g: read_gate(pdir, g).get("status", PENDING) for g in config.GATE_NAMES}
