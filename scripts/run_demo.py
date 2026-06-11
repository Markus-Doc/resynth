"""Drive the full five stage pipeline on examples/demo with simulated
operator inputs. Run from the repository root:

    python scripts/run_demo.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from resynth import config, demo_operator  # noqa: E402
from resynth.audit import run_audit, run_seal  # noqa: E402
from resynth.export import run_export  # noqa: E402
from resynth.extract import run_extract, run_extract_verify  # noqa: E402
from resynth.gates import all_gates  # noqa: E402
from resynth.intake import run_intake  # noqa: E402
from resynth.project import run_brief, run_init  # noqa: E402
from resynth.reconcile import run_reconcile  # noqa: E402
from resynth.synthesise import run_synth_verify, run_synthesise  # noqa: E402

SOURCES = [
    REPO / "examples" / "demo" / "standards-review.md",
    REPO / "examples" / "demo" / "engineering-field-notes.md",
    REPO / "examples" / "demo" / "incident-retrospective.md",
]


def main() -> int:
    project = "demo"
    pdir = config.projects_root() / project
    if not pdir.exists():
        run_init(project)
        run_brief(project, "How should passwords be stored and protected securely?")
    run_intake(project, [str(p) for p in SOURCES])
    run_extract(project)
    demo_operator.write_claims(pdir)
    assert run_extract_verify(project)["ok"], "extract gate failed"
    run_reconcile(project)
    demo_operator.write_decisions(pdir)
    assert run_reconcile(project)["ok"], "reconcile gate failed"
    run_synthesise(project)
    if "[!todo]" in (pdir / "output" / "MASTER.md").read_text(encoding="utf-8"):
        demo_operator.write_prose(pdir)
    assert run_synth_verify(project)["ok"], "synthesis gate failed"
    assert run_audit(project)["ok"], "audit gate failed"
    seal = run_seal(project)
    run_export(project)
    print(f"sealed: {seal.get('tag', 'dry run')}")
    for gate, state in all_gates(pdir).items():
        print(f"{gate}: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
