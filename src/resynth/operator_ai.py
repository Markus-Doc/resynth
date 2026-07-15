"""Versioned AI operator routing and safe external CLI execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import shutil
import subprocess
import queue
import threading
from pathlib import Path
from typing import Any

import yaml

from . import config
from .fsutil import dump_yaml

EFFORTS = ["low", "medium", "high", "xhigh"]
STAGES = ("prompts", "extract", "reconcile", "synthesise")
ROLES = ("author", "escalation", "fallback", "review")

KNOWN_CLIS = {
    "claude": {"label": "Claude Code", "default_model": None,
               "install_hint": "npm install -g @anthropic-ai/claude-code"},
    "codex": {"label": "Codex CLI", "default_model": None,
              "install_hint": "npm install -g @openai/codex"},
    "gemini": {"label": "Gemini CLI", "default_model": None,
               "install_hint": "npm install -g @google/gemini-cli"},
}

DEFAULTS: dict[str, Any] = {
    "version": 2,
    "routes": {
        "prompts": {"author": {"cli": "claude", "model": "sonnet", "effort": "low"}},
        "extract": {"author": {"cli": "claude", "model": "sonnet", "effort": "medium"},
                    "escalation": {"cli": "claude", "model": "opus", "effort": "high"}},
        "reconcile": {"author": {"cli": "claude", "model": "opus", "effort": "high"},
                      "escalation": {"cli": "codex", "model": "gpt-5.6-sol", "effort": "xhigh"}},
        "synthesise": {"author": {"cli": "claude", "model": "opus", "effort": "high"},
                       "escalation": {"cli": "codex", "model": "gpt-5.6-sol", "effort": "xhigh"}},
        "fallback": {"fallback": {"cli": "codex", "model": "gpt-5.6-terra", "effort": "high"}},
        "review": {"review": {"cli": "codex", "model": "gpt-5.6-terra", "effort": "high"}},
    },
}


@dataclass
class TaskResult:
    exit_code: int
    output: str = ""
    command: tuple[str, ...] = ()
    interrupted: bool = False

    def __eq__(self, other: object) -> bool:
        return self.exit_code == other if isinstance(other, int) else super().__eq__(other)


def config_path() -> Path:
    return config.workspace_root() / "operator.yaml"


def _copy_defaults() -> dict:
    cfg = yaml.safe_load(yaml.safe_dump(DEFAULTS))
    # Read-only compatibility fields for callers from operator.yaml v1. They
    # are never persisted and do not participate in route selection.
    cfg.update({"cli": None, "model": None, "effort": "high"})
    return cfg


def _is_legacy(data: dict) -> bool:
    return "version" not in data and any(k in data for k in ("cli", "model", "effort"))


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _migrate_legacy(data: dict, path: Path) -> dict:
    """Turn v1's flat selected operator into per-stage author overrides."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"operator.yaml.v1-{stamp}.bak")
    # A collision is unlikely but never overwrite a user's prior backup.
    n = 1
    while backup.exists():
        backup = path.with_name(f"operator.yaml.v1-{stamp}-{n}.bak")
        n += 1
    shutil.copy2(path, backup)
    cfg = _copy_defaults()
    route = {k: data.get(k) for k in ("cli", "model", "effort") if data.get(k) is not None}
    for stage in STAGES:
        _merge(cfg["routes"][stage]["author"], route)
    data_v2 = {k: v for k, v in cfg.items() if k not in {"cli", "model", "effort"}}
    path.write_text(dump_yaml(data_v2), encoding="utf-8", newline="\n")
    return cfg


def load() -> dict:
    path = config_path()
    if not path.is_file():
        return _copy_defaults()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return _copy_defaults()
    if _is_legacy(data):
        return _migrate_legacy(data, path)
    cfg = _copy_defaults()
    _merge(cfg, data)
    cfg["version"] = 2
    compat = cfg["routes"]["prompts"]["author"]
    cfg.update({k: compat.get(k) for k in ("cli", "model", "effort")})
    return cfg


def save(cfg: dict, *, legacy: bool = True) -> None:
    # Honour a v1-style programmatic update by applying it consistently to
    # author routes, then write only the v2 schema.
    if legacy and (cfg.get("cli") is not None or cfg.get("model") is not None or cfg.get("effort") not in (None, "high")):
        legacy = {k: cfg.get(k) for k in ("cli", "model", "effort") if cfg.get(k) is not None}
        for stage in STAGES:
            _merge(cfg["routes"][stage]["author"], legacy)
    data = {k: v for k, v in cfg.items() if k not in {"cli", "model", "effort"}}
    config_path().write_text(dump_yaml(data), encoding="utf-8", newline="\n")


def reset() -> dict:
    cfg = _copy_defaults()
    save(cfg)
    return cfg


def detect() -> list[str]:
    return [name for name in KNOWN_CLIS if shutil.which(name)]


def route_for(cfg: dict, stage: str, role: str = "author") -> dict:
    if stage not in STAGES and stage not in {"fallback", "review"}:
        raise ValueError(f"unknown operator stage: {stage}")
    if stage == "fallback":
        return dict(cfg["routes"]["fallback"]["fallback"])
    if stage == "review":
        return dict(cfg["routes"]["review"]["review"])
    route = cfg["routes"].get(stage, {}).get(role)
    if not route:
        raise ValueError(f"no {role} route configured for {stage}")
    return dict(route)


def resolved_model(cfg: dict) -> str | None:
    if cfg.get("model"):
        return cfg["model"]
    known = KNOWN_CLIS.get(cfg.get("cli") or "")
    return known["default_model"] if known else None


def build_command(cfg: dict, prompt: str, *, prompt_via_stdin: bool = False,
                  mode: str = "write") -> tuple[list[str], dict]:
    """Build explicit argv.  ``mode`` controls Codex filesystem permissions."""
    cli, effort, model = cfg["cli"], cfg.get("effort") or "high", resolved_model(cfg)
    env: dict[str, str] = {}
    if cli == "claude":
        annotated_prompt = f"Reasoning effort: {effort}.\n\n{prompt}"
        cmd = ["claude", "-p"] if prompt_via_stdin else ["claude", "-p", annotated_prompt]
        cmd += ["--permission-mode", "acceptEdits", "--effort", effort]
        if model:
            cmd += ["--model", model]
        if effort == "high":  # retained for older Claude CLI installations
            env["MAX_THINKING_TOKENS"] = "31999"
        return cmd, env
    if cli == "codex":
        sandbox = "read-only" if mode == "review" else "workspace-write"
        cmd = ["codex", "exec", "--sandbox", sandbox, "--ask-for-approval", "never",
               "-c", f"model_reasoning_effort={effort}"]
        if model:
            cmd += ["-m", model]
        return cmd + ["-" if prompt_via_stdin else prompt], env
    if cli == "gemini":
        cmd = ["gemini"] if prompt_via_stdin else ["gemini", "-p", prompt]
        if model:
            cmd += ["-m", model]
        return cmd, env
    return ([cli] if prompt_via_stdin else [cli, prompt]), env


def is_context_exhaustion(output: str) -> bool:
    text = output.lower()
    return any(marker in text for marker in (
        "context window", "context limit", "maximum context", "maximum prompt",
        "prompt token", "too many tokens", "context_length_exceeded",
    ))


def run_task(cfg: dict, prompt: str, cwd: Path, on_line=None, *, mode: str = "write",
             should_stop=None) -> TaskResult:
    """Run an external CLI and return its exit status and complete captured output."""
    exe = shutil.which(cfg["cli"])
    if not exe:
        return TaskResult(127)
    via_stdin = exe.lower().endswith((".cmd", ".bat"))
    cmd, extra_env = build_command(cfg, prompt, prompt_via_stdin=via_stdin, mode=mode)
    cmd[0] = exe
    env = {**os.environ, **extra_env}
    # Keep the simple non-streaming path compatible with callers that mock
    # subprocess.run, while still returning captured output in real use.
    if on_line is None:
        try:
            kwargs: dict[str, Any] = {"cwd": cwd, "env": env, "timeout": 1800,
                                      "capture_output": True, "encoding": "utf-8", "errors": "replace"}
            if via_stdin:
                kwargs["input"] = prompt
            completed = subprocess.run(cmd, **kwargs)
            output = "\n".join(x for x in (getattr(completed, "stdout", ""), getattr(completed, "stderr", "")) if x)
            return TaskResult(completed.returncode, output, tuple(cmd))
        except subprocess.TimeoutExpired:
            return TaskResult(124, command=tuple(cmd))
        except (OSError, KeyboardInterrupt):
            return TaskResult(127, command=tuple(cmd))
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE if via_stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    except OSError:
        return TaskResult(127, command=tuple(cmd))
    lines: list[str] = []
    interrupted = False
    try:
        if via_stdin:
            proc.stdin.write(prompt)
            proc.stdin.close()
        if should_stop is None:
            for line in proc.stdout:
                line = line.rstrip("\n")
                lines.append(line)
                on_line(line)
            rc = proc.wait(timeout=1800)
        else:
            output: queue.Queue[str | None] = queue.Queue()
            def read_output():
                for line in proc.stdout:
                    output.put(line)
                output.put(None)
            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            eof = False
            while not eof:
                directive = should_stop()
                if directive is not None:
                    proc.kill()
                    interrupted = True
                    break
                try:
                    line = output.get(timeout=0.2)
                except queue.Empty:
                    if proc.poll() is not None:
                        eof = True
                    continue
                if line is None:
                    eof = True
                else:
                    line = line.rstrip("\n")
                    lines.append(line)
                    on_line(line)
            rc = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill(); rc = 124
    except KeyboardInterrupt:
        proc.kill(); rc = 130
    except OSError:
        proc.kill(); rc = 124
    return TaskResult(rc, "\n".join(lines), tuple(cmd), interrupted)
