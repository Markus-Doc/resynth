from helpers import (
    make_project,
    run_full,
    to_audited,
    to_extracted,
    to_reconciled,
    to_synthesised,
)

from resynth.project import run_brief, run_init
from resynth import config
from resynth.wizard import project_state


def test_state_progression(ws):
    run_init("demo")
    pdir = config.project_dir("demo")
    assert project_state(pdir) == "brief"
    run_brief("demo", "How should passwords be stored?")
    assert project_state(pdir) == "intake"


def test_state_after_intake(ws):
    pdir = make_project()
    run_brief("demo", "topic")
    assert project_state(pdir) == "extract"


def test_state_through_pipeline(ws):
    pdir = to_extracted()
    run_brief("demo", "topic")
    assert project_state(pdir) == "reconcile"


def test_state_synthesise_and_beyond(ws):
    pdir = to_reconciled()
    run_brief("demo", "topic")
    assert project_state(pdir) == "synthesise"
    pdir = config.project_dir("demo")


def test_state_audit_seal_done(ws):
    pdir = to_synthesised()
    run_brief("demo", "topic")
    assert project_state(pdir) == "audit"


def test_state_done_after_seal(ws):
    pdir = run_full()
    run_brief("demo", "topic")
    assert project_state(pdir) == "done"
