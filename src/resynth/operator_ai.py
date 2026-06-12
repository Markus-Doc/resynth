"""Pluggable AI operator wiring.

RESYNTH's pipeline stays AI free. This module lets the guided mode hand
the operator steps to an AI CLI installed on the user's machine (Claude
Code, Codex, Gemini). The choice lives in operator.yaml at the workspace
root and is fully adjustable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

from . import config
from .fsutil import dump_yaml

EFFORTS = ["low", "medium", "high"]

KNOWN_CLIS = {
    "claude": {
        "label": "Claude Code",
        "default_model": "claude-opus-4-8",
        "install_hint": "npm install -g @anthropic-ai/claude-code",
    },
    "codex": {
        "label": "Codex CLI",
        "default_model": None,
        "install_hint": "npm install -g @openai/codex",
    },
    "gemini": {
        "label": "Gemini CLI",
        "default_model": None,
        "install_hint": "npm install -g @google/gemini-cli",
    },
}

DEFAULTS = {"cli": None, "model": None, "effort": "high"}


def config_path() -> Path:
    return config.workspace_root() / "operator.yaml"


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = config_path()
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    return cfg


def save(cfg: dict) -> None:
    data = {k: cfg.get(k) for k in DEFAULTS}
    config_path().write_text(dump_yaml(data), encoding="utf-8", newline="\n")


def detect() -> list[str]:
    return [name for name in KNOWN_CLIS if shutil.which(name)]


def resolved_model(cfg: dict) -> str | None:
    if cfg.get("model"):
        return cfg["model"]
    known = KNOWN_CLIS.get(cfg.get("cli") or "")
    return known["default_model"] if known else None


def full_prompt(cfg: dict, prompt: str) -> str:
    effort = cfg.get("effort") or "high"
    return f"Reasoning effort: {effort}.\n\n{prompt}"


def build_command(cfg: dict, prompt: str, *, prompt_via_stdin: bool = False) -> tuple[list[str], dict]:
    """Return (argv, extra_env) to run one operator task non-interactively.

    With prompt_via_stdin the prompt is left out of argv and the caller
    pipes it on stdin instead.
    """
    cli = cfg["cli"]
    effort = cfg.get("effort") or "high"
    model = resolved_model(cfg)
    prompt = full_prompt(cfg, prompt)
    env: dict[str, str] = {}
    if cli == "claude":
        cmd = ["claude", "-p"] if prompt_via_stdin else ["claude", "-p", prompt]
        cmd += ["--permission-mode", "acceptEdits"]
        if model:
            cmd += ["--model", model]
        if effort == "high":
            env["MAX_THINKING_TOKENS"] = "31999"
        return cmd, env
    if cli == "codex":
        cmd = ["codex", "exec", "-c", f"model_reasoning_effort={effort}"]
        if model:
            cmd += ["-m", model]
        return cmd + ["-" if prompt_via_stdin else prompt], env
    if cli == "gemini":
        cmd = ["gemini"] if prompt_via_stdin else ["gemini", "-p", prompt]
        if model:
            cmd += ["-m", model]
        return cmd, env
    return ([cli] if prompt_via_stdin else [cli, prompt]), env


def run_task(cfg: dict, prompt: str, cwd: Path) -> int:
    """Run the configured AI CLI on one operator task, streaming output."""
    exe = shutil.which(cfg["cli"])
    if not exe:
        return 127
    # Windows runs .cmd/.bat shims through cmd.exe, which re-parses argv and
    # mangles multi-line prompts, so those get the prompt on stdin instead.
    via_stdin = exe.lower().endswith((".cmd", ".bat"))
    cmd, extra_env = build_command(cfg, prompt, prompt_via_stdin=via_stdin)
    cmd[0] = exe
    env = {**os.environ, **extra_env}
    run_kwargs: dict = {"cwd": cwd, "env": env, "timeout": 1800}
    if via_stdin:
        run_kwargs.update(input=full_prompt(cfg, prompt), encoding="utf-8")
    try:
        return subprocess.run(cmd, **run_kwargs).returncode
    except subprocess.TimeoutExpired:
        return 124
    except KeyboardInterrupt:
        return 130
    except OSError:
        return 127
