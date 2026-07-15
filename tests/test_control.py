from click.testing import CliRunner

from resynth import control
from resynth.cli import main
from resynth.project import run_init


def test_queue_and_consume_directive(ws):
    run_init("demo")
    session = control.start_session("demo")
    event = control.queue("demo", "focus on unresolved conflicts")
    seen = set()
    assert control.next_directive("demo", session, seen) == event
    assert control.next_directive("demo", session, seen) is None
    control.finish_session("demo", session)


def test_control_command_uses_active_session(ws):
    run_init("demo")
    session = control.start_session("demo")
    result = CliRunner().invoke(main, ["control", "demo", "run automatically", "--json"])
    assert result.exit_code == 0, result.output
    queued = control.next_directive("demo", session, set())
    assert queued["directive"] == "run automatically"


def test_control_requires_active_guided_session(ws):
    run_init("demo")
    result = CliRunner().invoke(main, ["control", "demo", "stop", "--json"])
    assert result.exit_code == 1
    assert "no guided RESYNTH session is active" in result.output
