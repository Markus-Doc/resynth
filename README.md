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

## Install

### Windows

Open PowerShell (press the Windows key, type powershell, press Enter), paste
this line and press Enter:

```
irm https://raw.githubusercontent.com/Markus-Doc/resynth/main/install.ps1 | iex
```

The installer checks your machine, sets everything up, and offers to put a
RESYNTH shortcut on your desktop. If Python or Git are missing it installs
them and asks you to run the line once more in a new window.

### macOS and Linux

```
curl -fsSL https://raw.githubusercontent.com/Markus-Doc/resynth/main/install.sh | bash
```

## Use it

Double click the RESYNTH desktop shortcut (or run `resynth` in a terminal).
The guided mode walks you through everything, one step at a time:

1. On first run RESYNTH detects AI assistant CLIs on your machine (Claude
   Code, Codex, Gemini) and offers to wire one in. With an assistant wired
   in, every thinking step can be done for you automatically. Adjust the
   wiring any time: `resynth operator --use claude --model claude-opus-4-8 --effort high`
2. Name your project and describe what you want researched, in one sentence.
3. Already have your research reports? Say yes when asked and RESYNTH skips
   straight to loading them. Otherwise it creates one tailored research
   prompt per platform (your wired assistant can write them), you run them
   on the platforms and save every report as a file.
4. Point RESYNTH at the folder with your reports. It loads and fingerprints
   every one.
5. RESYNTH then drives the consolidation: claims are extracted, compared
   across reports, and written into one master document. With an assistant
   wired in each step runs automatically and is re-checked against the
   quality gate, with up to three corrective passes. Without one, RESYNTH
   opens the right file, explains what to do, and gives you the exact
   instruction to paste into any AI assistant. Nothing advances until its
   gate passes.
6. When every gate is green, RESYNTH seals the result. You get:
   - `MASTER.md`, the single best document, for you to read.
   - `MASTER.json`, the same content structured for an AI agent to action.
   - `AUDIT-REPORT.md`, proof of where every statement came from.

Your projects live in the `RESYNTH` folder in your home directory. You can
stop at any step and pick up where you left off, the guided mode remembers.

Everything below this point is detail for operators and developers.

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
resynth operator                  show or set the wired AI assistant, model and effort
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
