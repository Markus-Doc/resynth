"""Guided interactive mode. Launched by running resynth with no command.

The wizard runs every mechanical step itself and pauses only where the
operator (the user, or their AI agent) must supply judgement. The user
never needs to learn the CLI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import config, operator_ai
from .audit import run_audit, run_seal
from .errors import ResynthError
from .export import run_export
from .extract import run_extract, run_extract_verify
from .gates import all_gates
from .intake import SUPPORTED, run_intake
from .project import run_brief, run_init
from .reconcile import run_reconcile
from .synthesise import run_synth_verify, run_synthesise

console = Console()

DELEGATED_PROMPTS = {
    "prompts": (
        "You are the RESYNTH operator working in this RESYNTH workspace.\n"
        "Open projects/{project}/BRIEF.md to read the research question, then\n"
        "edit projects/{project}/prompts/RESEARCH-PROMPTS.md and replace every\n"
        "todo callout with one tailored deep research prompt for that platform.\n"
        "Ask each platform for clear headings, explicit confidence statements\n"
        "per finding and named sources. Edit no other files."
    ),
    "extract": (
        "You are the RESYNTH operator working in this RESYNTH workspace.\n"
        "Read projects/{project}/claims/EXTRACTION-INSTRUCTIONS.md and follow it\n"
        "exactly. For each source file under projects/{project}/sources/, read\n"
        "only that source and append its claims to the matching\n"
        "projects/{project}/claims/S<NN>-claims.jsonl file, one JSON object per\n"
        "line in the documented schema. Restate each claim in your own words,\n"
        "one claim per line, split compound statements, reuse topic tags across\n"
        "sources. Record the confidence the source states, not your own.\n"
        "Edit only the claims jsonl files."
    ),
    "reconcile": (
        "You are the RESYNTH operator working in this RESYNTH workspace.\n"
        "Read projects/{project}/index/RECONCILIATION-INSTRUCTIONS.md, the\n"
        "claims index at projects/{project}/index/claims-index.md and the\n"
        "flagged pairs in projects/{project}/index/candidates.jsonl. Write\n"
        "decision groups to projects/{project}/index/reconciliation.jsonl, one\n"
        "JSON object per line, so that every extracted claim lands in exactly\n"
        "one group. CORROBORATED when sources agree, UNIQUE for single source\n"
        "claims, SUPERSEDED only with a rule from merge-rules.yaml and a named\n"
        "winner, CONFLICT for genuine disagreement which you must never\n"
        "resolve, OUT_OF_SCOPE only with a one line note. Set decided_by to\n"
        "your CLI name. Edit only reconciliation.jsonl."
    ),
    "synthesise": (
        "You are the RESYNTH operator working in this RESYNTH workspace.\n"
        "Edit projects/{project}/output/MASTER.md and replace every todo\n"
        "callout with final prose. Work only from\n"
        "projects/{project}/index/claims-index.md and\n"
        "projects/{project}/index/reconciliation.jsonl, never from the raw\n"
        "sources. Every paragraph must end with provenance markers listing the\n"
        "claim ids it rests on, for example [S01-C003, S02-C011]. Cite every\n"
        "claim from every CORROBORATED and UNIQUE group and every SUPERSEDED\n"
        "winner at least once. Describe each CONFLICT in the Conflicts section\n"
        "citing both sides without resolving it. Fill the Gaps section.\n"
        "Edit only MASTER.md."
    ),
}

AGENT_PROMPTS = {
    "prompts": (
        "Read docs/OPERATOR-PROTOCOL.md if present, then open\n"
        "projects/<project>/prompts/RESEARCH-PROMPTS.md and replace every todo\n"
        "callout with one tailored deep research prompt for that platform.\n"
        "Ask each platform for clear headings, confidence statements and named sources."
    ),
    "extract": (
        "Read projects/<project>/claims/EXTRACTION-INSTRUCTIONS.md and follow it\n"
        "exactly. For each source under sources/, append its claims to the matching\n"
        "claims/S<NN>-claims.jsonl file, one JSON object per line. Then run\n"
        "resynth extract-verify <project> and fix every violation until PASS."
    ),
    "reconcile": (
        "Read projects/<project>/index/RECONCILIATION-INSTRUCTIONS.md, the claims\n"
        "index and candidates.jsonl. Write decision groups to\n"
        "index/reconciliation.jsonl so every claim lands in exactly one group.\n"
        "Then run resynth reconcile <project> until the gate reports PASS."
    ),
    "synthesise": (
        "Open projects/<project>/output/MASTER.md and replace every todo callout\n"
        "with prose, working only from the claims index and decisions. End every\n"
        "paragraph with its provenance markers, for example [S01-C003]. Then run\n"
        "resynth synth-verify <project> and fix every reason until PASS."
    ),
}


def project_state(pdir: Path) -> str:
    """The next pipeline step for a project. Pure, testable."""
    gates = all_gates(pdir)
    if not (pdir / "BRIEF.md").is_file():
        return "brief"
    if not list((pdir / "sources").glob("S*.md")):
        return "intake"
    if gates["02-extract"] != "PASS":
        return "extract"
    if gates["03-reconcile"] != "PASS":
        return "reconcile"
    if gates["04-synthesis"] != "PASS":
        return "synthesise"
    if gates["05-audit"] != "PASS":
        return "audit"
    if not (pdir / "output" / "SEAL.yaml").is_file():
        return "seal"
    return "done"


def _open_file(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        console.print(f"open this file yourself: {path}")


def _pause() -> bool:
    """Returns False when the user wants to quit."""
    answer = Prompt.ask(
        "\n[bold]Press Enter when you have done this[/bold] (or type q to quit)",
        default="",
        show_default=False,
    )
    return answer.strip().lower() != "q"


def _panel(title: str, body: str) -> None:
    console.print(Panel(body, title=title, border_style="cyan"))


def _show_reasons(result: dict) -> None:
    reasons = result.get("gate", {}).get("reasons", [])
    if reasons:
        console.print("[red]Things still to fix:[/red]")
        for r in reasons[:15]:
            console.print(f"  [red]-[/red] {r}")


def _status_table(project: str, pdir: Path) -> None:
    table = Table(title=f"Project: {project}")
    table.add_column("Gate")
    table.add_column("Status")
    for gate, state in all_gates(pdir).items():
        colour = {"PASS": "green", "FAIL": "red"}.get(state, "yellow")
        table.add_row(gate, f"[{colour}]{state}[/{colour}]")
    console.print(table)


def _ensure_workspace() -> Path:
    root = config.workspace_root()
    (root / "projects").mkdir(parents=True, exist_ok=True)
    return root


def _ensure_git(root: Path) -> None:
    def git(*args, ok_fail=False):
        try:
            proc = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, encoding="utf-8", errors="replace"
            )
        except OSError as err:
            raise ResynthError(f"git could not be run: {err}") from err
        if proc.returncode != 0 and not ok_fail:
            raise ResynthError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    if not (root / ".git").exists():
        git("init")
        gi = root / ".gitignore"
        if not gi.exists():
            gi.write_text("runs/\n", encoding="utf-8")
    if git("config", "user.email", ok_fail=True).returncode != 0:
        git("config", "user.name", "RESYNTH")
        git("config", "user.email", "resynth@localhost")
    git("add", "-A")
    git("commit", "-m", "RESYNTH workspace state", ok_fail=True)


def _setup_operator(root: Path) -> dict:
    """Load or first-time configure the AI operator wiring."""
    cfg = operator_ai.load()
    if cfg.get("cli"):
        return cfg
    if operator_ai.config_path().is_file():
        return cfg
    found = operator_ai.detect()
    if found:
        labels = ", ".join(operator_ai.KNOWN_CLIS[f]["label"] for f in found)
        console.print(f"\nI found these AI assistants on your machine: [cyan]{labels}[/cyan]")
        if Confirm.ask(
            f"Use [cyan]{found[0]}[/cyan] to do the AI work automatically?", default=True
        ):
            cfg["cli"] = found[0]
        elif len(found) > 1:
            choice = Prompt.ask("Which one?", choices=found + ["none"], default="none")
            if choice != "none":
                cfg["cli"] = choice
        operator_ai.save(cfg)
        if cfg.get("cli"):
            console.print(
                f"Wired in [cyan]{cfg['cli']}[/cyan] with model "
                f"[cyan]{operator_ai.resolved_model(cfg) or 'default'}[/cyan] and "
                f"[cyan]{cfg['effort']}[/cyan] reasoning effort. "
                "Adjust any time with: resynth operator --use ... --model ... --effort ..."
            )
    else:
        hints = "\n".join(
            f"  {v['label']}: {v['install_hint']}" for v in operator_ai.KNOWN_CLIS.values()
        )
        _panel(
            "No AI assistant CLI found",
            "RESYNTH can hand the thinking steps to an AI assistant installed\n"
            "on your machine. None was found, so I will guide you manually.\n\n"
            f"To wire one in later, install one of these and re-run RESYNTH:\n{hints}",
        )
        operator_ai.save(cfg)
    return cfg


def _choose_project(root: Path) -> str | None:
    projects = sorted(p.name for p in (root / "projects").iterdir() if p.is_dir())
    if projects:
        console.print("\nYour projects:")
        for name in projects:
            state = project_state(root / "projects" / name)
            console.print(f"  [cyan]{name}[/cyan]  next step: {state}")
        choice = Prompt.ask(
            "Type a project name to continue it, a new name to start fresh, or q to quit",
        ).strip()
    else:
        console.print("\nNo projects yet, let us start your first one.")
        choice = Prompt.ask(
            "Give your research project a short name (no spaces), or q to quit"
        ).strip()
    if not choice or choice.lower() in {"q", "quit", "exit"}:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in choice).strip("-").lower()
    if safe not in projects:
        run_init(safe)
        console.print(f"created project [cyan]{safe}[/cyan]")
    return safe


def _last_save_note(pdir: Path, started: float) -> str:
    try:
        latest = max((f.stat().st_mtime for f in pdir.rglob("*") if f.is_file()), default=0.0)
    except OSError:
        return ""
    if latest < started:
        return ", nothing saved yet"
    ago = max(0, int(time.time() - latest))
    return f", last file saved {ago}s ago"


def _run_with_progress(ai_cfg: dict, prompt: str, root: Path, pdir: Path) -> int:
    """Run one delegated task with a live elapsed/activity status line."""
    label = operator_ai.KNOWN_CLIS.get(ai_cfg["cli"], {}).get("label", ai_cfg["cli"])
    started = time.time()
    with console.status(f"[cyan]{label} is working...[/cyan]") as status:
        stop = threading.Event()

        def tick():
            while not stop.wait(2):
                m, s = divmod(int(time.time() - started), 60)
                status.update(
                    f"[cyan]{label} is working, {m}m {s:02d}s elapsed"
                    f"{_last_save_note(pdir, started)} "
                    "(it reports in full when done, Ctrl+C to stop it)[/cyan]"
                )

        ticker = threading.Thread(target=tick, daemon=True)
        ticker.start()
        try:
            return operator_ai.run_task(
                ai_cfg, prompt, root, on_line=lambda ln: console.print(f"[dim]{ln}[/dim]")
            )
        finally:
            stop.set()
            ticker.join(timeout=5)


def _delegate(project: str, root: Path, ai_cfg: dict, key: str, feedback: list[str]) -> bool:
    """Run one operator task through the configured AI CLI. True on rc 0."""
    prompt = DELEGATED_PROMPTS[key].format(project=project)
    if feedback:
        prompt += (
            "\n\nA previous attempt failed verification with these reasons, fix them:\n"
            + "\n".join(f"- {r}" for r in feedback[:15])
        )
    console.print(
        f"\n[cyan]Handing this step to {ai_cfg['cli']} "
        f"(model {operator_ai.resolved_model(ai_cfg) or 'default'}, "
        f"effort {ai_cfg.get('effort', 'high')})...[/cyan]\n"
    )
    rc = _run_with_progress(ai_cfg, prompt, root, config.project_dir(project))
    if rc == 127:
        known = operator_ai.KNOWN_CLIS.get(ai_cfg["cli"], {})
        label = known.get("label", ai_cfg["cli"])
        body = (
            f"I could not launch {label} on this machine, so I will guide\n"
            "you through this step manually instead."
        )
        if known.get("install_hint"):
            body += (
                "\n\nTo let it do the work next time, install it and re-run RESYNTH:\n"
                f"  {known['install_hint']}"
            )
        _panel("Your AI assistant could not be launched", body)
    elif rc != 0:
        console.print(f"[red]{ai_cfg['cli']} exited with code {rc}.[/red]")
    return rc == 0


def _step_brief(project: str, pdir: Path, root: Path, ai_cfg: dict) -> bool:
    topic = Prompt.ask("\nWhat do you want researched? Describe it in one sentence")
    if not topic.strip():
        return True
    run_brief(project, topic)
    if Confirm.ask(
        "Do you already have your research reports saved as files?", default=False
    ):
        console.print("Good, we will load them next.")
        return True
    prompts_file = pdir / "prompts" / "RESEARCH-PROMPTS.md"
    delegated = False
    if ai_cfg.get("cli") and Confirm.ask(
        f"Let {ai_cfg['cli']} write the platform research prompts for you now?",
        default=True,
    ):
        delegated = _delegate(project, root, ai_cfg, "prompts", [])
    if delegated:
        _panel(
            "Step 1 of 6: research prompts",
            "Your prompts are ready, I will open them now.\n\n"
            "Run each prompt on its platform (Claude, ChatGPT, Gemini,\n"
            "Perplexity) and save every finished report as a file.\n"
            "Markdown (.md) or plain text (.txt) files work best.",
        )
    else:
        _panel(
            "Step 1 of 6: research prompts",
            "I created a prompts file and will open it now.\n\n"
            "Fill in one prompt per platform, or paste this into your AI assistant\n"
            "and let it write them for you:\n\n"
            f"[dim]{AGENT_PROMPTS['prompts'].replace('<project>', project)}[/dim]\n\n"
            "Then run each prompt on its platform (Claude, ChatGPT, Gemini,\n"
            "Perplexity) and save every finished report as a file.\n"
            "Markdown (.md) or plain text (.txt) files work best.",
        )
    _open_file(prompts_file)
    return _pause()


def _step_intake(project: str) -> bool:
    _panel(
        "Step 2 of 6: load your research reports",
        "Tell me where your saved reports are. You can give a folder\n"
        "(I will load every report in it) or a single file. Paste the full\n"
        "path, for example your Downloads folder.",
    )
    raw = Prompt.ask("Folder or file path").strip().strip('"')
    if not raw:
        return True
    path = Path(raw).expanduser()
    if path.is_dir():
        files = sorted(
            str(f) for f in path.iterdir() if f.suffix.lower() in SUPPORTED and f.is_file()
        )
    elif path.is_file():
        files = [str(path)]
    else:
        console.print(f"[red]I could not find {path}[/red]")
        return True
    if not files:
        console.print("[red]No readable reports found there (.md .txt .docx .pdf)[/red]")
        return True
    try:
        result = run_intake(project, files)
    except ResynthError as exc:
        console.print(f"[red]{exc}[/red]")
        return True
    for event in result["events"]:
        console.print(f"  {event['source']}: {event['action']}")
    _show_reasons(result)
    return True


def _step_operator(
    project: str,
    pdir: Path,
    root: Path,
    ai_cfg: dict,
    key: str,
    title: str,
    body: str,
    open_path: Path,
    verify,
) -> bool:
    _panel(title, body)
    if ai_cfg.get("cli") and Confirm.ask(
        f"Let {ai_cfg['cli']} do this step for you now?", default=True
    ):
        feedback: list[str] = []
        for attempt in range(1, 4):
            if not _delegate(project, root, ai_cfg, key, feedback):
                break
            result = verify()
            if result["ok"]:
                console.print("[green]Gate PASS, moving on.[/green]")
                return True
            feedback = result.get("gate", {}).get("reasons", [])
            _show_reasons(result)
            if attempt < 3:
                console.print(f"[yellow]Retrying with feedback, attempt {attempt + 1} of 3...[/yellow]")
        console.print("[yellow]Falling back to manual mode for this step.[/yellow]")
    console.print(
        "\nIf an AI agent is your operator, paste this to it:\n"
        f"[dim]{AGENT_PROMPTS[key].replace('<project>', project)}[/dim]"
    )
    _open_file(open_path)
    if not _pause():
        return False
    result = verify()
    if result["ok"]:
        console.print("[green]Gate PASS, moving on.[/green]")
    else:
        _show_reasons(result)
    return True


def _run_project(project: str, root: Path, ai_cfg: dict) -> None:
    pdir = config.project_dir(project)
    while True:
        state = project_state(pdir)
        if state == "brief":
            if not _step_brief(project, pdir, root, ai_cfg):
                return
        elif state == "intake":
            if not _step_intake(project):
                return
        elif state == "extract":
            run_extract(project)
            if not _step_operator(
                project,
                pdir,
                root,
                ai_cfg,
                "extract",
                "Step 3 of 6: pull out the claims",
                "Every report now has a claims worksheet under claims/.\n"
                "Each claim from each report goes in as one line, following\n"
                "the instructions file I am opening now.",
                pdir / "claims" / "EXTRACTION-INSTRUCTIONS.md",
                lambda: run_extract_verify(project),
            ):
                return
        elif state == "reconcile":
            run_reconcile(project)
            if not _step_operator(
                project,
                pdir,
                root,
                ai_cfg,
                "reconcile",
                "Step 4 of 6: compare the claims",
                "Now every claim gets classified: corroborated, unique,\n"
                "superseded, conflict or out of scope. The instructions file\n"
                "I am opening explains each one.",
                pdir / "index" / "RECONCILIATION-INSTRUCTIONS.md",
                lambda: run_reconcile(project),
            ):
                return
        elif state == "synthesise":
            run_synthesise(project)
            if not _step_operator(
                project,
                pdir,
                root,
                ai_cfg,
                "synthesise",
                "Step 5 of 6: write the master document",
                "The master document scaffold is ready. Replace every todo\n"
                "callout with the final prose, keeping the provenance markers.",
                pdir / "output" / "MASTER.md",
                lambda: run_synth_verify(project),
            ):
                return
        elif state == "audit":
            result = run_audit(project)
            if result["ok"]:
                console.print("[green]Audit PASS, every claim is accounted for.[/green]")
            else:
                _show_reasons(result)
                if not _pause():
                    return
        elif state == "seal":
            if Confirm.ask("\nSeal and lock this master document now?", default=True):
                _ensure_git(root)
                sealed = run_seal(project)
                run_export(project)
                console.print(f"[green]Sealed as {sealed['tag']}[/green]")
            else:
                return
        else:
            _finish(project, pdir)
            return


def _finish(project: str, pdir: Path) -> None:
    _status_table(project, pdir)
    out = pdir / "output"
    _panel(
        "Step 6 of 6: done",
        "Your master research document is complete and verified.\n\n"
        f"Read it:            {out / 'MASTER.md'}\n"
        f"For AI agents:      {out / 'MASTER.json'}\n"
        f"Provenance proof:   {out / 'AUDIT-REPORT.md'}",
    )
    if Confirm.ask("Open the master document now?", default=True):
        _open_file(out / "MASTER.md")


def run_wizard() -> int:
    console.print(
        Panel(
            "[bold]RESYNTH[/bold] turns several research reports on one topic into\n"
            "a single verified master document. I will guide you the whole way.",
            border_style="cyan",
        )
    )
    root = _ensure_workspace()
    ai_cfg = _setup_operator(root)
    try:
        project = _choose_project(root)
        if not project:
            return 0
        _status_table(project, config.project_dir(project))
        _run_project(project, root, ai_cfg)
    except (KeyboardInterrupt, EOFError):
        console.print("\nbye")
    except ResynthError as exc:
        console.print(f"[red]error:[/red] {exc}")
        return 1
    return 0
