"""Shared pipeline drivers for the test suite."""

import subprocess
from pathlib import Path

from resynth import config, demo_operator
from resynth.audit import run_audit, run_seal
from resynth.extract import run_extract, run_extract_verify
from resynth.intake import run_intake
from resynth.project import run_init
from resynth.reconcile import run_reconcile
from resynth.synthesise import run_synth_verify, run_synthesise

REPO = Path(__file__).resolve().parents[1]
DEMO_SOURCES = [
    REPO / "examples" / "demo" / "standards-review.md",
    REPO / "examples" / "demo" / "engineering-field-notes.md",
    REPO / "examples" / "demo" / "incident-retrospective.md",
]


def make_project(project="demo") -> Path:
    run_init(project)
    run_intake(project, [str(p) for p in DEMO_SOURCES])
    return config.project_dir(project)


def to_extracted(project="demo") -> Path:
    pdir = make_project(project)
    run_extract(project)
    demo_operator.write_claims(pdir)
    run_extract_verify(project)
    return pdir


def to_reconciled(project="demo") -> Path:
    pdir = to_extracted(project)
    run_reconcile(project)
    demo_operator.write_decisions(pdir)
    run_reconcile(project)
    return pdir


def to_synthesised(project="demo") -> Path:
    pdir = to_reconciled(project)
    run_synthesise(project)
    demo_operator.write_prose(pdir)
    run_synth_verify(project)
    return pdir


def to_audited(project="demo") -> Path:
    pdir = to_synthesised(project)
    run_audit(project)
    return pdir


def git_init(root: Path) -> None:
    for args in (
        ["init"],
        ["config", "user.name", "RESYNTH Test"],
        ["config", "user.email", "resynth-test@localhost"],
        ["add", "-A"],
        ["commit", "-m", "test workspace", "--allow-empty"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def run_full(project="demo") -> Path:
    pdir = to_audited(project)
    git_init(config.workspace_root())
    run_seal(project)
    return pdir


def snapshot(*dirs: Path) -> dict:
    files = {}
    for d in dirs:
        for f in sorted(d.rglob("*")):
            if f.is_file():
                files[str(f)] = f.read_bytes()
    return files
