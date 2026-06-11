"""RESYNTH command line interface."""

from __future__ import annotations

import json as _json
import sys

import click
from rich.console import Console
from rich.table import Table

from . import audit as audit_mod
from . import config
from . import doctor as doctor_mod
from . import export as export_mod
from . import extract as extract_mod
from . import project as project_mod
from . import reconcile as reconcile_mod
from . import synthesise as synth_mod
from .errors import ResynthError
from .gates import all_gates
from .intake import run_intake
from .runlog import write_run_log

console = Console()


def _finish(command: str, project: str | None, result: dict, as_json: bool, dry_run: bool):
    write_run_log(command, project, result.get("events", []), dry_run)
    if as_json:
        clean = {k: v for k, v in result.items() if k != "messages"}
        clean["command"] = command
        click.echo(_json.dumps(clean, indent=2, sort_keys=True, default=str))
    else:
        for line in result.get("messages", []):
            console.print(line)
        if dry_run:
            console.print("[yellow]dry run, nothing written[/yellow]")
    sys.exit(0 if result.get("ok") else 1)


def _run(_command: str, _project: str | None, _as_json: bool, _dry_run: bool, _fn, *args, **kwargs):
    try:
        result = _fn(*args, **kwargs)
    except ResynthError as exc:
        write_run_log(_command, _project, [{"error": str(exc)}], _dry_run)
        if _as_json:
            click.echo(_json.dumps({"command": _command, "ok": False, "error": str(exc)}))
        else:
            console.print(f"[red]error:[/red] {exc}")
        sys.exit(1)
    _finish(_command, _project, result, _as_json, _dry_run)


def common(fn):
    fn = click.option("--dry-run", is_flag=True, help="Report planned actions, write nothing.")(fn)
    fn = click.option("--json", "as_json", is_flag=True, help="Machine readable output.")(fn)
    return fn


@click.group()
def main():
    """RESYNTH, research consolidation with systematic review gates."""


@main.command()
@click.argument("project")
@common
def init(project, as_json, dry_run):
    """Create the project skeleton plus default merge-rules.yaml."""
    _run("init", project, as_json, dry_run, project_mod.run_init, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@click.option("--topic", required=True, help="The research question in natural language.")
@common
def brief(project, topic, as_json, dry_run):
    """Capture the research question and generate the prompt workspace."""
    _run("brief", project, as_json, dry_run, project_mod.run_brief, project, topic, dry_run=dry_run)


@main.command()
@click.argument("project")
@click.option("--source", "sources", multiple=True, required=True, type=click.Path(), help="Source document, repeatable.")
@common
def intake(project, sources, as_json, dry_run):
    """Stage 1: ingest sources with provenance frontmatter."""
    _run("intake", project, as_json, dry_run, run_intake, project, list(sources), dry_run=dry_run)


@main.command()
@click.argument("project")
@common
def extract(project, as_json, dry_run):
    """Stage 2: generate the claim extraction workspace."""
    _run("extract", project, as_json, dry_run, extract_mod.run_extract, project, dry_run=dry_run)


@main.command("extract-verify")
@click.argument("project")
@common
def extract_verify(project, as_json, dry_run):
    """Validate extracted claims and write gate 02."""
    _run("extract-verify", project, as_json, dry_run, extract_mod.run_extract_verify, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@common
def reconcile(project, as_json, dry_run):
    """Stage 3: build the claims index, flag candidates, evaluate decisions."""
    _run("reconcile", project, as_json, dry_run, reconcile_mod.run_reconcile, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@click.option("--force", is_flag=True, help="Regenerate MASTER.md, prior version moves to _trash.")
@common
def synthesise(project, force, as_json, dry_run):
    """Stage 4: generate the master document scaffold."""
    _run("synthesise", project, as_json, dry_run, synth_mod.run_synthesise, project, dry_run=dry_run, force=force)


@main.command("synth-verify")
@click.argument("project")
@common
def synth_verify(project, as_json, dry_run):
    """Verify master prose against the reconciliation record, write gate 04."""
    _run("synth-verify", project, as_json, dry_run, synth_mod.run_synth_verify, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@common
def audit(project, as_json, dry_run):
    """Stage 5: coverage, drift and traceability report, write gate 05."""
    _run("audit", project, as_json, dry_run, audit_mod.run_audit, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@common
def seal(project, as_json, dry_run):
    """Hash all artifacts into SEAL.yaml and tag the git repo."""
    _run("seal", project, as_json, dry_run, audit_mod.run_seal, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@common
def export(project, as_json, dry_run):
    """Write output/MASTER.json for downstream AI agents."""
    _run("export", project, as_json, dry_run, export_mod.run_export, project, dry_run=dry_run)


@main.command()
@click.argument("project")
@common
def status(project, as_json, dry_run):
    """Gate dashboard for all five stages."""

    def _status():
        pdir = config.project_dir(project)
        gates = all_gates(pdir)
        if not as_json:
            table = Table(title=f"RESYNTH gates: {project}")
            table.add_column("Gate")
            table.add_column("Status")
            for gate, state in gates.items():
                colour = {"PASS": "green", "FAIL": "red"}.get(state, "yellow")
                table.add_row(gate, f"[{colour}]{state}[/{colour}]")
            console.print(table)
        return {"ok": True, "project": project, "gates": gates, "messages": []}

    _run("status", project, as_json, dry_run, _status)


@main.command()
@common
def doctor(as_json, dry_run):
    """Probe the environment: python, git, pandoc, pdftotext."""

    def _doctor():
        result = doctor_mod.run_doctor()
        table = Table(title="RESYNTH doctor")
        table.add_column("Check")
        table.add_column("Found")
        table.add_column("State")
        for name, check in result["checks"].items():
            state = "ok" if check["ok"] else ("MISSING" if check["required"] else "optional, absent")
            table.add_row(name, str(check["value"]), state)
        if not as_json:
            console.print(table)
            for note in result["notes"]:
                console.print(f"[yellow]{note}[/yellow]")
            console.print("environment healthy" if result["healthy"] else "[red]environment unhealthy[/red]")
        return result

    _run("doctor", None, as_json, dry_run, _doctor)


if __name__ == "__main__":
    main()
