"""Local control queue for interrupting and steering a guided run."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from pathlib import Path

from . import config
from .errors import ResynthError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _index(project: str) -> Path:
    return config.project_dir(project) / "index"


def _session_path(project: str) -> Path:
    return _index(project) / "control-session.json"


def _events_path(project: str) -> Path:
    return _index(project) / "control-events.jsonl"


def _log_path(project: str) -> Path:
    return _index(project) / "control-log.jsonl"


def _append(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def start_session(project: str) -> str:
    session = uuid.uuid4().hex
    path = _session_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session": session, "status": "active", "started": _now()}), encoding="utf-8")
    _append(_log_path(project), {"at": _now(), "event": "session_started", "session": session})
    return session


def finish_session(project: str, session: str) -> None:
    path = _session_path(project)
    if path.is_file():
        path.write_text(json.dumps({"session": session, "status": "finished", "finished": _now()}), encoding="utf-8")
    _append(_log_path(project), {"at": _now(), "event": "session_finished", "session": session})


def queue(project: str, directive: str) -> dict:
    directive = directive.strip()
    if not directive:
        raise ResynthError("control directive cannot be empty")
    path = _session_path(project)
    if not path.is_file():
        raise ResynthError("no guided RESYNTH session is active for this project")
    try:
        session_state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResynthError("guided control session is unreadable") from exc
    if session_state.get("status") != "active" or not session_state.get("session"):
        raise ResynthError("no guided RESYNTH session is active for this project")
    event = {"id": uuid.uuid4().hex, "at": _now(), "event": "directive", "session": session_state["session"], "directive": directive}
    _append(_events_path(project), event)
    _append(_log_path(project), {"at": _now(), "event": "queued", **event})
    return event


def next_directive(project: str, session: str, consumed: set[str]) -> dict | None:
    path = _events_path(project)
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "directive" and event.get("session") == session and event.get("id") not in consumed:
            consumed.add(event["id"])
            _append(_log_path(project), {"at": _now(), "event": "received", "session": session, "directive_id": event["id"], "directive": event["directive"]})
            return event
    return None


def log_action(project: str, session: str, directive: dict, action: str, detail: str = "") -> None:
    _append(_log_path(project), {"at": _now(), "event": "interpreted", "session": session, "directive_id": directive.get("id"), "directive": directive.get("directive"), "action": action, "detail": detail})
