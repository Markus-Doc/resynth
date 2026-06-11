"""Guided interactive mode. Launched by running resynth with no command.

The wizard runs every mechanical step itself and pauses only where the
operator (the user, or their AI agent) must supply judgement. The user
never needs to learn the CLI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import config
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
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
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


def _step_brief(project: str, pdir: Path) -> bool:
    topic = Prompt.ask("\nWhat do you want researched? Describe it in one sentence")
    if not topic.strip():
        return True
    run_brief(project, topic)
    prompts_file = pdir / "prompts" / "RESEARCH-PROMPTS.md"
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


def _step_operator(project: str, pdir: Path, key: str, title: str, body: str, open_path: Path, verify) -> bool:
    _panel(
        title,
        body
        + "\n\nIf an AI agent is your operator, paste this to it:\n\n"
        + f"[dim]{AGENT_PROMPTS[key].replace('<project>', project)}[/dim]",
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


def _run_project(project: str, root: Path) -> None:
    pdir = config.project_dir(project)
    while True:
        state = project_state(pdir)
        if state == "brief":
            if not _step_brief(project, pdir):
                return
        elif state == "intake":
            if not _step_intake(project):
                return
        elif state == "extract":
            run_extract(project)
            if not _step_operator(
                project,
                pdir,
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
    try:
        project = _choose_project(root)
        if not project:
            return 0
        _status_table(project, config.project_dir(project))
        _run_project(project, root)
    except (KeyboardInterrupt, EOFError):
        console.print("\nbye")
    except ResynthError as exc:
        console.print(f"[red]error:[/red] {exc}")
        return 1
    return 0
