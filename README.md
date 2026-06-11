# RESYNTH

A CLI research consolidation platform. RESYNTH ingests multiple research
documents on a shared topic and produces a single master source of truth
document using systematic review methodology, with full provenance, explicit
conflict handling and machine verifiable completeness.

RESYNTH is a framework and pipeline, not a chatbot. The synthesis
intelligence is supplied by the AI agent session that operates the pipeline
from outside, via this CLI. The platform itself has zero runtime AI
dependency. Every stage is runnable, inspectable and re-runnable from the
shell with deterministic file backed state.

## The intended workflow

You describe what you want researched in natural language to your agent
session. The agent writes one tailored prompt per deep research platform.
You run those prompts on the platforms and save each report as a file. The
agent then drives the pipeline below, and the result is one BEST master
document, readable by humans, verifiable by machine, and exportable as JSON
for a downstream AI agent to action.

```
chat -> brief -> per platform prompts -> research reports -> intake ->
extract -> reconcile -> synthesise -> audit -> seal -> MASTER.md + MASTER.json
```

## Install

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\pip
resynth doctor
```

Requires Python 3.11 or later and git. pandoc and pdftotext are optional and
only needed for .docx and .pdf intake.

## The five gated stages

| Stage | Command | Gate |
| --- | --- | --- |
| 1 INTAKE | resynth intake | every source has complete frontmatter and a verified hash |
| 2 EXTRACT | resynth extract, resynth extract-verify | zero schema violations, zero dangling references |
| 3 RECONCILE | resynth reconcile | every claim in exactly one decision group |
| 4 SYNTHESIS | resynth synthesise, resynth synth-verify | every winning claim cited, conflicts logged, no orphan prose |
| 5 AUDIT | resynth audit, resynth seal | full coverage, no source drift, sealed hashes plus git tag |

A stage cannot run until the previous gate reports PASS. Check progress at
any time with resynth status <project>, machine readable with --json.

## Quickstart on the bundled demo

```
resynth init demo
resynth intake demo --source examples/demo/standards-review.md --source examples/demo/engineering-field-notes.md --source examples/demo/incident-retrospective.md
resynth extract demo
# operator fills the claims workspaces, see below
resynth extract-verify demo
resynth reconcile demo
# operator writes reconciliation decisions
resynth reconcile demo
resynth synthesise demo
# operator writes prose into output/MASTER.md
resynth synth-verify demo
resynth audit demo
resynth seal demo
resynth export demo
```

A fully scripted version with simulated operator inputs lives in
scripts/run_demo.py and in the end to end test.

## CLI reference

```
resynth init <project>            create project skeleton plus default merge-rules.yaml
resynth brief <project> --topic   capture the research question, generate the prompt workspace
resynth intake <project> --source <file> ...   stage 1, repeatable per file
resynth extract <project>         stage 2 workspace generation
resynth extract-verify <project>  stage 2 gate
resynth reconcile <project>       stage 3, also evaluates the gate
resynth synthesise <project>      stage 4 scaffold generation
resynth synth-verify <project>    stage 4 gate
resynth audit <project>           stage 5 coverage, drift, traceability
resynth seal <project>            hash everything, commit SEAL.yaml, tag the repo
resynth export <project>          machine readable output/MASTER.json for agents
resynth status <project>          gate dashboard
resynth doctor                    environment probe
```

Every command supports --dry-run and --json and writes a run log under
runs/. Exit code is 0 only on success.

## Operator protocol, the short version

The full protocol with copy paste agent prompts for every stage lives in
docs/OPERATOR-PROTOCOL.md. The three rules that matter most:

1. Two passes, always. Extract claims first, synthesise from the claims index second, never from raw sources.
2. Conflicts are logged, never silently resolved. A SUPERSEDED decision with a documented merge rule is the only sanctioned override.
3. Verify after synthesis. Run synth-verify, fix every reason, repeat until PASS. Never edit gate files by hand.

### Agent prompt for stage 2, claim extraction

```
Run: resynth extract <project> --json
Read projects/<project>/claims/EXTRACTION-INSTRUCTIONS.md and follow it exactly.
For each source under projects/<project>/sources/, read only that source and
append its claims to claims/S<NN>-claims.jsonl, one JSON object per line in
the documented schema. Restate claims in your own words, one claim per line.
Record the confidence the source states, not your own. Reuse topic tags.
Then run: resynth extract-verify <project> --json and fix every violation
until the gate reports PASS.
```

### Agent prompt for stage 3, reconciliation

```
Run: resynth reconcile <project> --json
Read index/RECONCILIATION-INSTRUCTIONS.md, index/claims-index.md and
index/candidates.jsonl. Classify every candidate and every claim into
decision groups in index/reconciliation.jsonl. Every claim lands in exactly
one group. CORROBORATED when sources agree, UNIQUE for single source claims,
SUPERSEDED only with a merge rule and a winner, CONFLICT for genuine
disagreement which you never resolve, OUT_OF_SCOPE only with a reason.
Re-run: resynth reconcile <project> --json until the gate reports PASS.
```

### Agent prompt for stage 4, synthesis

```
Run: resynth synthesise <project> --json
Replace every todo callout in output/MASTER.md with prose, working only from
the claims index and the reconciliation decisions. Every paragraph ends with
provenance markers, for example [S01-C003, S02-C011]. Cite every winning
claim at least once. Describe each conflict in the Conflicts section citing
both sides without resolving it. Fill the Gaps section.
Run: resynth synth-verify <project> --json and fix every reason until PASS.
```

## Repository layout

```
pyproject.toml
DECISIONS.md         every architectural decision with a one line rationale
docs/                operator protocol
src/resynth/         package code
templates/           jinja2 templates for scaffolds, instructions, reports
tests/               pytest suite including the end to end pipeline test
examples/demo/       three synthetic research docs with overlap, a conflict and unique claims
scripts/run_demo.py  scripted five stage demo with simulated operator input
runs/                run logs, gitignored
```

## Guarantees

- Zero runtime AI dependency, no API keys, no model calls.
- All state is plain text on disk, diffable in git.
- No destructive operations, replaced files move to a timestamped _trash directory.
- Idempotent stages, re-running with unchanged inputs changes nothing.
- A sealed master is hash verified end to end, from source bytes to the final tag.

## Licence

MIT, copyright M. Walker.
