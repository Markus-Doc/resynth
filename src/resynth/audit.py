"""Stage 5: AUDIT. Coverage, drift and traceability, then the seal."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import config
from .errors import ResynthError
from .extract import load_all_claims
from .fsutil import dump_yaml, safe_write, sha256_text
from .gates import require_gate, require_previous, write_gate
from .intake import load_sources
from .reconcile import load_decisions
from .synthesise import cited_locations, winning_claims


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(config.templates_dir())),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def run_audit(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_previous(pdir, "05-audit")
    sources = load_sources(pdir)
    claims = load_all_claims(pdir)
    decisions = load_decisions(pdir)
    reasons: list[str] = []

    drift = {}
    for fm in sources:
        actual = sha256_text(fm["_body"])
        drift[fm["source_id"]] = "ok" if actual == fm["sha256"] else "DRIFTED"
        if actual != fm["sha256"]:
            reasons.append(f"source {fm['source_id']} changed since intake, hash mismatch")

    decision_of: dict[str, dict] = {}
    for d in decisions:
        for cid in d["claim_ids"]:
            decision_of[cid] = d
    dropped = sorted(c["claim_id"] for c in claims if c["claim_id"] not in decision_of)
    for cid in dropped:
        reasons.append(f"claim {cid} dropped without an OUT_OF_SCOPE decision")

    winners = winning_claims(decisions)
    locations = cited_locations(pdir)
    matrix = []
    per_source: dict[str, dict[str, int]] = {}
    for c in sorted(claims, key=lambda c: c["claim_id"]):
        cid = c["claim_id"]
        d = decision_of.get(cid)
        decision = d["decision"] if d else "UNDECIDED"
        if d and decision == "SUPERSEDED" and d.get("winner") != cid:
            status = f"superseded by {d['winner']}"
        elif decision == "OUT_OF_SCOPE":
            status = "excluded"
        elif decision == "CONFLICT":
            status = "logged in Conflicts"
        else:
            status = "cited" if cid in locations else "NOT CITED"
        matrix.append(
            {
                "source_id": c["source_id"],
                "claim_id": cid,
                "decision": decision,
                "group_id": d["group_id"] if d else "",
                "location": locations.get(cid, ""),
                "status": status,
            }
        )
        stats = per_source.setdefault(c["source_id"], {"extracted": 0, "accounted": 0})
        stats["extracted"] += 1
        if d:
            stats["accounted"] += 1

    report = _jinja().get_template("audit-report.md.j2").render(
        project=project,
        matrix=matrix,
        per_source=sorted(per_source.items()),
        drift=sorted(drift.items()),
        winners_total=len(winners),
        conflicts_total=sum(1 for d in decisions if d["decision"] == "CONFLICT"),
    )
    safe_write(pdir / "output" / "AUDIT-REPORT.md", report, pdir, dry_run=dry_run)
    checks = {
        "coverage": {sid: f"{s['accounted']}/{s['extracted']}" for sid, s in sorted(per_source.items())},
        "drift": drift,
        "dropped_claims": dropped,
    }
    gate = write_gate(pdir, "05-audit", reasons, checks, dry_run=dry_run)
    return {
        "ok": gate["status"] == "PASS",
        "gate": gate,
        "messages": [
            "output/AUDIT-REPORT.md written",
            f"gate 05-audit: {gate['status']}",
        ]
        + [f"FAIL: {r}" for r in reasons[:20]],
    }


def _git(args: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace"
        )
    except OSError as err:
        raise ResynthError(f"git could not be run: {err}") from err
    if proc.returncode != 0:
        raise ResynthError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run_seal(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    require_gate(pdir, "05-audit")
    root = config.workspace_root()
    try:
        _git(["rev-parse", "--show-toplevel"], root)
    except ResynthError:
        raise ResynthError(f"workspace {root} is not inside a git repository, seal needs git")
    existing = _git(["tag", "--list", f"resynth-{project}-v*"], root).splitlines()
    versions = [int(t.rsplit("v", 1)[1]) for t in existing if t.rsplit("v", 1)[1].isdigit()]
    version = max(versions, default=0) + 1
    tag = f"resynth-{project}-v{version}"

    hashes: dict[str, str] = {}
    targets = [pdir / "output" / "MASTER.md", pdir / "output" / "AUDIT-REPORT.md"]
    targets += sorted((pdir / "sources").glob("S*.md"))
    targets += sorted((pdir / "claims").glob("S*-claims.jsonl"))
    targets += [pdir / "index" / "reconciliation.jsonl", pdir / "merge-rules.yaml"]
    for t in targets:
        if not t.is_file():
            raise ResynthError(f"seal target missing: {t}")
        rel = t.relative_to(pdir).as_posix()
        hashes[rel] = sha256_text(t.read_text(encoding="utf-8"))

    seal = {"project": project, "version": version, "tag": tag, "sha256": hashes}
    seal_path = pdir / "output" / "SEAL.yaml"
    outcome = safe_write(seal_path, dump_yaml(seal), pdir, dry_run=dry_run)
    if dry_run:
        return {"ok": True, "messages": [f"dry run, would seal as {tag}"]}
    top = Path(_git(["rev-parse", "--show-toplevel"], root)).resolve()
    rel_seal = Path(os.path.relpath(seal_path.resolve(), top)).as_posix()
    # -f: workspaces cloned from this repo gitignore projects/*; the seal
    # file must be tracked regardless so the tag has something to pin.
    _git(["add", "-f", rel_seal], root)
    status = _git(["status", "--porcelain", "--", rel_seal], root)
    if status:
        _git(["commit", "-m", f"Seal {project} v{version}"], root)
    _git(["tag", tag], root)
    return {
        "ok": True,
        "tag": tag,
        "version": version,
        "events": [{"file": "SEAL.yaml", "action": outcome}],
        "messages": [f"sealed {project} as {tag}", "output/SEAL.yaml written and committed"],
    }
