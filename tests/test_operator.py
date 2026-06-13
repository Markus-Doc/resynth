from resynth import operator_ai


def test_defaults_are_high_effort(ws):
    cfg = operator_ai.load()
    assert cfg["effort"] == "high"
    assert cfg["cli"] is None


def test_claude_uses_cli_default_model_high_effort(ws):
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    # No model pinned: resynth must not pass --model, so the claude CLI uses
    # whatever default model the authed session has set.
    assert operator_ai.resolved_model(cfg) is None
    cmd, env = operator_ai.build_command(cfg, "do the thing")
    assert cmd[0] == "claude" and "-p" in cmd
    assert "--model" not in cmd
    assert "--permission-mode" in cmd
    assert env.get("MAX_THINKING_TOKENS") == "31999"
    assert any("Reasoning effort: high" in part for part in cmd)


def test_model_and_effort_overrides(ws):
    cfg = {"cli": "claude", "model": "claude-sonnet-4-6", "effort": "medium"}
    cmd, env = operator_ai.build_command(cfg, "task")
    assert "claude-sonnet-4-6" in cmd
    assert "MAX_THINKING_TOKENS" not in env


def test_codex_and_gemini_commands(ws):
    cmd, _ = operator_ai.build_command({"cli": "codex", "model": None, "effort": "high"}, "task")
    assert cmd[:2] == ["codex", "exec"]
    assert "model_reasoning_effort=high" in cmd
    cmd, _ = operator_ai.build_command({"cli": "gemini", "model": None, "effort": "high"}, "task")
    assert cmd[0] == "gemini" and "-p" in cmd


def test_save_and_load_roundtrip(ws):
    cfg = operator_ai.load()
    cfg.update(cli="claude", effort="medium")
    operator_ai.save(cfg)
    again = operator_ai.load()
    assert again["cli"] == "claude"
    assert again["effort"] == "medium"
    assert operator_ai.config_path().is_file()


def test_detect_uses_path(ws, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/x" if name == "claude" else None)
    assert operator_ai.detect() == ["claude"]


def test_run_task_spawns_resolved_path(ws, monkeypatch, tmp_path):
    resolved = r"C:\fake\claude.cmd"
    seen = {}
    monkeypatch.setattr("shutil.which", lambda name: resolved)

    class FakeProc:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return FakeProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "task", tmp_path) == 0
    assert seen["argv"][0] == resolved


def test_run_task_pipes_prompt_to_batch_shim(ws, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("shutil.which", lambda name: r"C:\fake\claude.cmd")

    class FakeProc:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["input"] = kwargs.get("input")
        return FakeProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "the task", tmp_path) == 0
    assert not any("the task" in part for part in seen["argv"])
    assert "the task" in seen["input"]


def test_run_task_keeps_prompt_in_argv_for_real_executables(ws, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")

    class FakeProc:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["input"] = kwargs.get("input")
        return FakeProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "the task", tmp_path) == 0
    assert any("the task" in part for part in seen["argv"])
    assert seen["input"] is None


def test_run_task_streams_lines_to_callback(ws, monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: r"C:\fake\claude.cmd")

    class FakeStdin:
        def __init__(self):
            self.text = ""
            self.closed = False

        def write(self, text):
            self.text += text

        def close(self):
            self.closed = True

    class FakeProc:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = iter(["first line\n", "second line\n"])

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    proc = FakeProc()
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: proc)
    lines = []
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "the task", tmp_path, on_line=lines.append) == 0
    assert lines == ["first line", "second line"]
    assert "the task" in proc.stdin.text and proc.stdin.closed


def test_run_task_streaming_returns_127_on_spawn_failure(ws, monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: r"C:\fake\claude.cmd")

    def fake_popen(*a, **k):
        raise FileNotFoundError(a[0][0])

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "task", tmp_path, on_line=lambda ln: None) == 127


def test_run_task_returns_127_when_cli_missing(ws, monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "task", tmp_path) == 127


def test_run_task_returns_127_on_spawn_failure(ws, monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: r"C:\fake\claude.cmd")

    def fake_run(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("subprocess.run", fake_run)
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.run_task(cfg, "task", tmp_path) == 127
