# RESYNTH

Status: working, v0.3.0. Built from June 2026, last updated October 2026. Last reviewed October 2026.

[![CI](https://github.com/Markus-Doc/resynth/actions/workflows/ci.yml/badge.svg)](https://github.com/Markus-Doc/resynth/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

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
   in, every thinking step can be done for you automatically. Routes are
   staged (Sonnet for prompts/extraction, Opus for reconciliation/synthesis,
   with Codex escalation), and can be adjusted with `resynth operator`.
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
   quality gate, with up to three corrective passes. Extraction runs one AI
   task per report, several at once, and each task checks its own work
   before it finishes. Without an assistant, RESYNTH opens the right file,
   explains what to do, and gives you the exact instruction to paste into
   any AI assistant. Nothing advances until its gate passes.
6. When every gate is green, RESYNTH seals the result. You get:
   - `MASTER.md`, the single best document, for you to read. Its last
     section traces every statement to its report, line and excerpt, and to
     the link, footnote or paper DOI that report cited there.
   - `MASTER.json`, the same content structured for an AI agent to action,
     with the same trace on every claim.
   - `AUDIT-REPORT.md`, proof of where every statement came from.

Your projects live in the `RESYNTH` folder in your home directory. You can
stop at any step and pick up where you left off, the guided mode remembers.
At an AI handoff, type a custom instruction instead of `y` or `n` and it is
given to that task. Type `auto` to run the remaining AI stages unattended.
RESYNTH still enforces deterministic gates and does not fabricate missing
research reports. A request mentioning Fable uses Claude Fable 5 for that one
task only and never saves it as the workspace policy.

While guided mode is running, a second terminal (or a supervising agent) can
interrupt its current AI task and steer it naturally:

```
resynth control <project> "stop after this stage and focus on unresolved conflicts"
```

The task is stopped safely, its output is retained, and the instruction is
recorded in the project's control log. Controls are session-only and cannot
bypass evidence rules, passing gates, or the seal confirmation.

Everything below this point is detail for operators and developers.

## The intended workflow

You describe what you want researched in natural language to your agent
session. The agent writes one tailored prompt per deep research platform.
You run those prompts on the platforms and save each report as a file. The
agent then drives the pipeline below, and the result is one BEST master
document, readable by humans, verifiable by machine, and exportable as JSON
for a downstream AI agent to action.

After intake there is one optional extra step. RESYNTH offers to fetch the
links and file references found inside your reports and register them as
extra sources, so the things your reports cite become evidence too.

```
chat -> brief -> per platform prompts -> research reports -> intake ->
resolve (optional) -> extract -> reconcile -> synthesise -> audit -> seal ->
MASTER.md + MASTER.json
```

## Tracing a statement to its origin

Every claim carries a short `source_excerpt` copied verbatim from its
report. The extract gate finds that excerpt in the report, so a claim that is
not in its source cannot pass. Finding it also pins the claim to a line (and
a PDF page or video timestamp) and to the citations the report gives in that
sentence: numbered footnotes, markdown links, bare URLs, author-year
references resolved to DOIs through the report's reference list, and
citation tokens whose URLs were lost when the report was saved. The result is
`index/provenance.jsonl`, rebuilt on every extract-verify, and the Claim
Provenance appendix that RESYNTH writes into `MASTER.md`.

```
resynth trace myproject S02-C003          # where one statement came from
resynth provenance myproject              # how well the whole project traces
resynth provenance myproject --status unresolved   # claims whose citations have no recoverable link
```

`trace` prints the claim, its decision group, the report and line, the
excerpt, the evidence cited there and where the master cites it. Each
citation carries a scope: `sentence` when it sits in the claim's own
sentence, `paragraph` when the report cites once at the end of a run of
sentences, as ChatGPT reports do. A claim with no citation at its passage is
reported as the report's own analysis rather than credited to a source. The
audit gate fails if the provenance index no longer matches the sources and
claims on disk.

Projects made before 0.3.0 have claims without excerpts. Add an excerpt to
each claim, or set `require_source_excerpt: false` in `merge-rules.yaml` to
keep the old behaviour.

## Fetching linked sources

Research reports cite things. `resynth resolve <project>` follows those
citations and turns them into first class sources of their own. It scans
every ingested report for links and file references, fetches each one, and
registers the result with provenance back to the report that mentioned it.
It handles html articles, pdf links, local files, and YouTube and Vimeo
videos. Public video captions become timestamped transcripts.

When a video has no public captions, resolve still creates the source as a
pending transcript stub. You can paste a transcript into the stub yourself,
or re-run resolve later to retry. A later successful fetch upgrades the stub
in place and keeps the same source id.

Resolution is idempotent. Every outcome is recorded in
`index/resolution.jsonl`, fetched and duplicate targets are never fetched
twice, and failed or pending targets are retried on the next run. Fetching
is polite: robots.txt is honoured, requests to the same host are spaced one
second apart, and responses are capped at 10 MiB. Resolution goes one level
deep only. Fetched sources are not scanned for further links unless you
force a re-scan with `--source`.

```
resynth resolve myproject
resynth resolve myproject --only youtube    # just targets matching a substring
resynth resolve myproject --source S03      # re-scan one source, even a fetched one
```

The full reference, including the manifest format, the source schema and
the migration guide, lives in [docs/SOURCE-RESOLUTION.md](docs/SOURCE-RESOLUTION.md).

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
| 2 EXTRACT | resynth extract, resynth extract-verify | zero schema violations, zero dangling references, every excerpt found in its source, every report yields claims |
| 3 RECONCILE | resynth reconcile | every claim in exactly one decision group |
| 4 SYNTHESIS | resynth synthesise, resynth synth-verify | every winning claim cited, conflicts logged, no orphan prose |
| 5 AUDIT | resynth audit, resynth seal | full coverage, no source drift, current provenance, sealed hashes plus git tag |

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
resynth resolve <project>         fetch links and file references inside sources as new first class sources
resynth extract <project>         stage 2 workspace generation
resynth check-claims <project> <source_id>   read-only check of one source's claims, safe in parallel
resynth extract-verify <project>  stage 2 gate, also rebuilds index/provenance.jsonl
resynth reconcile <project>       stage 3, also evaluates the gate
resynth reconcile <project> --fill-unique   record undecided claims outside candidate pairs as UNIQUE
resynth trace <project> <claim_id>          where one claim came from
resynth provenance <project>      provenance summary, --status lists claims by evidence status
resynth synthesise <project>      stage 4 scaffold generation
resynth synth-verify <project>    stage 4 gate
resynth audit <project>           stage 5 coverage, drift, traceability
resynth seal <project>            hash everything, commit SEAL.yaml, tag the repo
resynth export <project>          machine readable output/MASTER.json for agents
resynth status <project>          gate dashboard
resynth migrate <project>         upgrade a project's sources to the current schema (v2)
resynth operator                  show or set staged AI routes, models and effort
resynth control <project> <text>  steer an active guided AI session
resynth doctor                    environment probe
resynth update                    check GitHub and fast-forward the install in place
```

`resynth update` fast-forwards the git install (the one the installer sets
up) to the latest release. Only changed and new files are rewritten, and the
editable install means the new code is live without re-patching. A dependency
reinstall happens only when `pyproject.toml` changed. Use `--check` to look
without applying, `--yes` to skip the prompt. The guided mode also checks at
most once a day on launch and, when a newer version exists, pings the desktop
and offers to update before you start.

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
the documented schema. Restate claims in your own words, one claim per line,
and give each a source_excerpt copied verbatim from the sentence that states
it. Record the confidence the source states, not your own. Reuse topic tags.
Check each source with: resynth check-claims <project> S<NN> --json
Then run: resynth extract-verify <project> --json and fix every violation
until the gate reports PASS.
```

Each claim may also carry an optional `source_locator`, a deep link into the
source built from a url, a page number, a timestamp or an anchor. The full
claim and source schemas live in
[docs/SOURCE-RESOLUTION.md](docs/SOURCE-RESOLUTION.md).

### Agent prompt for stage 3, reconciliation

```
Run: resynth reconcile <project> --json
Read index/RECONCILIATION-INSTRUCTIONS.md and index/claims-index.md.
Write the groups that need judgement to index/reconciliation.jsonl:
CORROBORATED when sources agree, SUPERSEDED only with a merge rule and a
winner, CONFLICT for genuine disagreement which you never resolve,
OUT_OF_SCOPE only with a reason, and UNIQUE for any claim in a candidate pair.
Run: resynth reconcile <project> --fill-unique --json until the gate reports
PASS. It records every other claim as UNIQUE.
```

### Agent prompt for stage 4, synthesis

```
Run: resynth synthesise <project> --json
Replace every todo callout in output/MASTER.md with prose. Each callout lists
its claims with their text and decision, so MASTER.md is the only file you
need. Every paragraph ends with provenance markers, for example
[S01-C003, S02-C011]. Cite every winning claim at least once. Describe each
conflict in the Conflicts section citing both sides without resolving it.
Fill the Gaps section. Leave the generated appendices alone.
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

## Contributing and security

Contributions are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Report
vulnerabilities privately via [SECURITY.md](SECURITY.md). Release history
lives in [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT, copyright M. Walker.

## Ownership and third-party rights

RESYNTH is an original project by M. Walker. The MIT License covers original code, documentation, pipeline design, and methodology. Dependencies, research standards, and user-supplied source documents retain their own rights and terms. See [NOTICE.md](NOTICE.md).
