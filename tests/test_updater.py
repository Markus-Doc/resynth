"""Self update engine tests, driven against real throwaway git repos."""

import subprocess
from pathlib import Path

import pytest

from resynth import updater


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _commit(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def install(tmp_path, monkeypatch):
    """An 'origin' repo and a cloned 'install' wired up as the app root."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "-c", "init.defaultBranch=main", "init")
    _git(origin, "config", "user.name", "RESYNTH Test")
    _git(origin, "config", "user.email", "resynth-test@localhost")
    (origin / "pyproject.toml").write_text("[project]\nname='resynth'\n", encoding="utf-8")
    _commit(origin, "app.py", "print(1)\n", "initial")

    app = tmp_path / "app"
    _git(tmp_path, "clone", "--quiet", str(origin), "app")

    monkeypatch.setattr(updater, "app_root", lambda: app)
    monkeypatch.setattr(updater, "state_path", lambda: tmp_path / "state" / "check.json")
    return origin, app


def test_app_root_finds_this_checkout():
    # In the dev tree the package sits two parents under a real git repo.
    assert updater.app_root() is not None


def test_check_reports_up_to_date(install):
    status = updater.check(throttle=False)
    assert status["supported"] is True
    assert status["available"] is False


def test_check_detects_new_commit(install):
    origin, _ = install
    _commit(origin, "app.py", "print(2)\n", "second")
    status = updater.check(throttle=False)
    assert status["available"] is True
    assert status["latest"] != status["current"]
    assert status["latest_short"] != status["current_short"]


def test_throttle_reuses_cache_until_ttl(install):
    origin, _ = install
    first = updater.check(throttle=True)
    assert first["available"] is False and first.get("cached") is False
    # A new commit lands, but a throttled check should not see it yet.
    _commit(origin, "app.py", "print(2)\n", "second")
    cached = updater.check(throttle=True)
    assert cached.get("cached") is True
    assert cached["available"] is False
    # An unthrottled check probes the network and sees the new revision.
    fresh = updater.check(throttle=False)
    assert fresh["available"] is True


def test_apply_fast_forwards_and_lists_only_changed(install, monkeypatch):
    origin, app = install
    monkeypatch.setattr(updater, "_reinstall_deps", lambda root: True)
    _commit(origin, "app.py", "print(2)\n", "edit app")
    _commit(origin, "new.py", "x = 1\n", "add new file")

    result = updater.apply()
    assert result["ok"] is True and result["updated"] is True
    assert set(result["changed_files"]) == {"app.py", "new.py"}
    assert result["deps_changed"] is False
    assert result["deps_reinstalled"] is None
    assert (app / "new.py").is_file()
    assert updater.current_sha(app) == _git(origin, "rev-parse", "HEAD")


def test_apply_reinstalls_only_when_pyproject_changes(install, monkeypatch):
    origin, _ = install
    calls = []
    monkeypatch.setattr(updater, "_reinstall_deps", lambda root: calls.append(root) or True)
    _commit(origin, "pyproject.toml", "[project]\nname='resynth'\nversion='9'\n", "bump deps")

    result = updater.apply()
    assert result["deps_changed"] is True
    assert result["deps_reinstalled"] is True
    assert len(calls) == 1


def test_apply_noop_when_already_current(install):
    result = updater.apply()
    assert result["ok"] is True
    assert result["updated"] is False


def test_incoming_commits_lists_subjects(install):
    origin, _ = install
    _commit(origin, "app.py", "print(2)\n", "shiny new feature")
    subjects = updater.incoming_commits(updater.app_root())
    assert "shiny new feature" in subjects


def test_check_unsupported_outside_git(monkeypatch):
    monkeypatch.setattr(updater, "app_root", lambda: None)
    status = updater.check(throttle=False)
    assert status["supported"] is False
    assert status["available"] is False
