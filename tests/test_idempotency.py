from helpers import DEMO_SOURCES, make_project, snapshot

from resynth.extract import run_extract
from resynth.intake import run_intake


def test_intake_and_extract_are_idempotent(ws):
    pdir = make_project()
    run_extract("demo")
    watched = [pdir / "sources", pdir / "claims", pdir / "gates"]
    first = snapshot(*watched)
    run_intake("demo", [str(p) for p in DEMO_SOURCES])
    run_extract("demo")
    second = snapshot(*watched)
    assert first == second
    assert not list((pdir / "_trash").rglob("*"))
