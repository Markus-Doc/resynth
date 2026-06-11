from resynth import operator_ai


def test_defaults_are_high_effort(ws):
    cfg = operator_ai.load()
    assert cfg["effort"] == "high"
    assert cfg["cli"] is None


def test_claude_defaults_to_opus_high_effort(ws):
    cfg = {"cli": "claude", "model": None, "effort": "high"}
    assert operator_ai.resolved_model(cfg) == "claude-opus-4-8"
    cmd, env = operator_ai.build_command(cfg, "do the thing")
    assert cmd[0] == "claude" and "-p" in cmd
    assert "claude-opus-4-8" in cmd
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
