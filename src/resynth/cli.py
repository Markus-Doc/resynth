"""RESYNTH command line interface."""

from __future__ import annotations

import json as _json
import sys
import traceback

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from . import audit as audit_mod
from . import config
from . import doctor as doctor_mod
from . import export as export_mod
from . import extract as extract_mod
from . import migrate as migrate_mod
from . import project as project_mod
from . import reconcile as reconcile_mod
from . import resolve as resolve_mod
from . import synthesise as synth_mod
from . import updater as updater_mod
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


class _GuardedGroup(click.Group):
    """Entry point guard: unexpected failures stay short and human readable."""

    def main(self, *args, standalone_mode=True, **kwargs):
        if not standalone_mode:
            return super().main(*args, standalone_mode=False, **kwargs)
        try:
            rv = super().main(*args, standalone_mode=False, **kwargs)
        except click.ClickException as exc:
            exc.show()
            sys.exit(exc.exit_code)
        except (click.exceptions.Abort, KeyboardInterrupt, EOFError):
            console.print("\nbye")
            sys.exit(130)
        except ResynthError as exc:
            console.print(f"[red]error:[/red] {exc}")
            sys.exit(1)
        except Exception as exc:  # noqa: BLE001
            log_path = None
            try:
                log_path = write_run_log(
                    "crash",
                    None,
                    [
                        {
                            "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc(),
                        }
                    ],
                    False,
                )
            except Exception:
                log_path = None
            console.print(f"[red]Something went wrong that RESYNTH did not expect:[/red] {exc}")
            if log_path:
                console.print(f"The full details are saved here: {log_path}")
                console.print("If it happens again, share that file when you report the problem.")
            else:
                console.print(
                    "Please try the command again, and report the problem if it keeps happening."
                )
            sys.exit(1)
        sys.exit(rv if isinstance(rv, int) else 0)


@click.group(cls=_GuardedGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="resynth")
@click.pass_context
def main(ctx):
    """RESYNTH, research consolidation with systematic review gates.

    Run with no command for the guided step by step mode.
    """
    if ctx.invoked_subcommand is None:
        from .wizard import run_wizard

        sys.exit(run_wizard())


@main.command()
def guide():
    """Guided step by step mode, the same as running resynth bare."""
    from .wizard import run_wizard

    sys.exit(run_wizard())


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
@click.option("--source", "source_ids", multiple=True, help="Scan only these source ids (allows re-scanning resolved sources).")
@click.option("--only", default=None, help="Only targets containing this substring.")
@common
def resolve(project, source_ids, only, as_json, dry_run):
    """Fetch links and file references inside sources as new first class sources."""
    _run(
        "resolve",
        project,
        as_json,
        dry_run,
        resolve_mod.run_resolve,
        project,
        only=only,
        source_ids=list(source_ids) or None,
        dry_run=dry_run,
    )


@main.command()
@click.argument("project")
@common
def migrate(project, as_json, dry_run):
    """Upgrade a project's sources to the current schema (v2). Re-seal is a separate step."""
    _run("migrate", project, as_json, dry_run, migrate_mod.run_migrate, project, dry_run=dry_run)


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
@click.option("--stage", type=click.Choice(["prompts", "extract", "reconcile", "synthesise", "fallback", "review"]), default=None, help="Route stage to change.")
@click.option("--role", type=click.Choice(["author", "escalation", "fallback", "review"]), default="author", help="Route role to change.")
@click.option("--use", "use_cli", default=None, help="AI CLI for the selected route.")
@click.option("--model", default=None, help="Model override, for example claude-opus-4-8.")
@click.option("--effort", default=None, type=click.Choice(["low", "medium", "high", "xhigh"]), help="Reasoning effort.")
@click.option("--reset", is_flag=True, help="Restore the shipped staged routing policy.")
@click.option("--clear", is_flag=True, help="Clear the selected route's CLI (legacy alias).")
@common
def operator(stage, role, use_cli, model, effort, reset, clear, as_json, dry_run):
    """Show or change versioned per-stage AI routes."""
    from . import operator_ai

    def _operator():
        cfg = operator_ai.load()
        changed = reset
        if reset:
            cfg = operator_ai._copy_defaults()
        if any([use_cli, model, effort, clear]) and not stage:
            raise ResynthError("choose --stage when changing a route")
        if any([use_cli, model, effort, clear]):
            target_role = "fallback" if stage == "fallback" else ("review" if stage == "review" else role)
            try:
                route = operator_ai.route_for(cfg, stage, target_role)
            except ValueError as exc:
                raise ResynthError(str(exc)) from exc
            if clear:
                route["cli"] = None
            if use_cli:
                route["cli"] = use_cli
            if model:
                route["model"] = model
            if effort:
                route["effort"] = effort
            cfg["routes"][stage][target_role] = route
            changed = True
        if changed and not dry_run:
            operator_ai.save(cfg, legacy=False)
        detected = operator_ai.detect()
        messages = ["staged routing policy (operator.yaml v2):"]
        for route_stage, roles in cfg["routes"].items():
            for route_role, route_cfg in roles.items():
                messages.append(f"{route_stage}/{route_role}: {route_cfg['cli']} {operator_ai.resolved_model(route_cfg) or 'CLI default'} ({route_cfg['effort']})")
        messages.append(f"detected on this machine: {', '.join(detected) or 'none'}")
        return {
            "ok": True,
            "config": cfg,
            "detected": detected,
            "messages": messages,
        }

    _run("operator", None, as_json, dry_run, _operator)


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


@main.command()
@click.option("--check", "check_only", is_flag=True, help="Only report whether an update exists.")
@click.option("--yes", "assume_yes", is_flag=True, help="Apply without asking.")
@common
def update(check_only, assume_yes, as_json, dry_run):
    """Check GitHub for a newer RESYNTH and fast-forward this install."""
    from rich.panel import Panel
    from rich.prompt import Confirm

    def _update():
        root = updater_mod.app_root()
        status = updater_mod.check(throttle=False)
        if not status.get("supported"):
            msg = "Self update only works for the git install (the one the installer sets up)."
            if not as_json:
                console.print(f"[yellow]{msg}[/yellow]")
            return {"ok": True, "supported": False, "messages": []}
        if status.get("error") and not status.get("current"):
            return {"ok": False, "error": status["error"], "messages": []}
        if not status.get("available"):
            cur = status.get("current_short", __version__)
            if not as_json:
                console.print(f"[green]RESYNTH is up to date[/green] (v{__version__}, {cur}).")
            return {"ok": True, "available": False, **status, "messages": []}

        commits = updater_mod.incoming_commits(root) if not as_json else []
        if not as_json:
            lines = [
                f"A newer RESYNTH is available.",
                "",
                f"  installed   [yellow]{status['current_short']}[/yellow]  (v{__version__})",
                f"  available   [green]{status['latest_short']}[/green]",
            ]
            if commits:
                lines += ["", "[bold]What's new[/bold]"]
                lines += [f"  • {c}" for c in commits]
            console.print(Panel("\n".join(lines), title="✨ Update available", border_style="cyan"))

        if check_only or dry_run:
            return {"ok": True, "available": True, **status, "messages": []}
        if not assume_yes and not as_json:
            if not Confirm.ask("Update now?", default=True):
                return {"ok": True, "available": True, "applied": False, "messages": []}

        result = updater_mod.apply()
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "update failed"), "messages": []}
        if not result.get("updated"):
            return {"ok": True, "applied": False, "messages": ["already up to date"]}
        if not as_json:
            n = len(result["changed_files"])
            console.print(
                f"[green]Updated[/green] {result['old_short']} → {result['new_short']} "
                f"({n} file{'s' if n != 1 else ''} changed)."
            )
            if result.get("deps_changed"):
                ok = result.get("deps_reinstalled")
                console.print(
                    "[green]Dependencies reinstalled.[/green]"
                    if ok
                    else "[yellow]Dependencies changed but reinstall failed; "
                    "run the installer to repair.[/yellow]"
                )
            console.print("Restart RESYNTH to run the new version.")
        return {"ok": True, "applied": True, **result, "messages": []}

    _run("update", None, as_json, dry_run, _update)


if __name__ == "__main__":
    main()
