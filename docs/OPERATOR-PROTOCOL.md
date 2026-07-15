# RESYNTH Operator Protocol

> [!abstract] Purpose
> How an AI agent session (Claude Code or equivalent) drives RESYNTH end to
> end. RESYNTH supplies structure, gates and evidence. The operator supplies
> judgement. The platform itself never calls a model.

## Staged AI routing and review

`operator.yaml` is a versioned, workspace-scoped routing profile. The shipped
policy uses Claude Sonnet (low) for prompts, Sonnet (medium) for extraction,
and Claude Opus (high) for reconciliation and synthesis. Extraction can
escalate to Opus; reconciliation and synthesis can escalate to Codex Sol at
xhigh effort. Inspect it with `resynth operator`; edit one route with, for
example, `resynth operator --stage extract --role author --model sonnet
--effort medium`, or restore the policy with `resynth operator --reset`.

If Claude reports a context-window limit, RESYNTH announces and runs a single
workspace-write Codex Terra fallback at the same effort. It does not fail over
for other errors and never chains another automatic retry. After a passing
extraction, reconciliation or synthesis gate, Codex Terra may review the
artifacts read-only. Its report is an AI quality signal, not verification of
source truth: accept it, explicitly rerun with the stronger route, revise
manually, or stop.

In guided mode, AI handoff questions accept more than yes/no: type a custom
instruction and it is appended to that one delegated task, or type `auto` to
run remaining AI stages automatically. Automatic mode still requires passing
deterministic gates and does not bypass source intake, manual-file fallback or
the final sealing confirmation. A custom Fable request uses `claude-fable-5`
for that task only; it does not alter `operator.yaml`.

## The two pass discipline

The single most important rule. Synthesis happens in two passes and never
directly from raw sources.

1. Pass one extracts claims from each source in isolation into the claims workspace.
2. Pass two synthesises prose from the reconciled claims index, never from the original documents.

This prevents the most common consolidation failure, where the loudest or
longest source dominates the master document. Once claims are extracted, the
sources are only consulted again to verify a quote location.

## The conflict rule

Conflicts are logged, never silently resolved. When two sources genuinely
disagree, the disagreement is a finding in its own right. It goes into the
CONFLICTS section of the master with both sides cited. Resolving it requires
a documented rule from merge-rules.yaml recorded in the decision, and only a
SUPERSEDED decision may do that.

## The verification loop

After writing prose, always run the verifier and fix what it reports, then
run it again. Never edit the gate files by hand. The loop for stage 4 is:

1. resynth synthesise <project>
2. write prose into output/MASTER.md
3. resynth synth-verify <project>
4. fix every reported reason and repeat step 3 until PASS

## Full pipeline walkthrough

```
resynth init <project>
resynth brief <project> --topic "the research question"
# operator writes one prompt per platform in prompts/RESEARCH-PROMPTS.md
# user runs the prompts, saves each report as a file
resynth intake <project> --source report-a.md --source report-b.md
resynth extract <project>
# operator fills claims/S*-claims.jsonl per EXTRACTION-INSTRUCTIONS.md
resynth extract-verify <project>
resynth reconcile <project>
# operator writes index/reconciliation.jsonl per RECONCILIATION-INSTRUCTIONS.md
resynth reconcile <project>
resynth synthesise <project>
# operator writes prose into output/MASTER.md
resynth synth-verify <project>
resynth audit <project>
resynth seal <project>
resynth export <project>
resynth status <project>
```

Use the --json flag on every command when an agent is the operator, the
output parses cleanly and the exit code is 0 only on success.

## Copy paste agent prompts

### Stage 0, research prompt authoring

```
Read projects/<project>/BRIEF.md and projects/<project>/prompts/RESEARCH-PROMPTS.md.
For each platform section, replace the todo callout with one tailored deep
research prompt for that platform. Every prompt must ask for clear headings,
explicit confidence statements per finding, named sources, and a closing
summary of open questions. Tailor depth and style to each platform's
strengths. Do not run any research yourself.
```

### Stage 2, claim extraction

```
Run: resynth extract <project> --json
Read projects/<project>/claims/EXTRACTION-INSTRUCTIONS.md and follow it exactly.
For each source file under projects/<project>/sources/, read only that source
and append its claims to the matching claims/S<NN>-claims.jsonl file, one JSON
object per line in the documented schema. Restate each claim in your own
words, one claim per line, split compound statements. Record the confidence
the source itself states, not your own. Reuse topic tags across sources.
Then run: resynth extract-verify <project> --json
Fix every reported violation and re-run until the gate reports PASS.
```

### Stage 3, reconciliation

```
Run: resynth reconcile <project> --json
Read projects/<project>/index/RECONCILIATION-INSTRUCTIONS.md, the claims index
at index/claims-index.md and the flagged pairs in index/candidates.jsonl.
Classify every candidate and every remaining claim into decision groups in
index/reconciliation.jsonl, one JSON object per line. Every extracted claim
must land in exactly one group. Use CORROBORATED when sources agree, UNIQUE
for single source claims, SUPERSEDED only with a rule from merge-rules.yaml
and a named winner, CONFLICT for genuine disagreement which you must never
resolve, OUT_OF_SCOPE only with a one line reason. Set decided_by to your
agent name. Then re-run: resynth reconcile <project> --json
Fix every reported reason until the gate reports PASS.
```

### Stage 4, synthesis

```
Run: resynth synthesise <project> --json
Open projects/<project>/output/MASTER.md. Replace every todo callout with
prose. Work only from the claims index and the reconciliation decisions,
never from the raw sources. Every paragraph must end with provenance markers
listing the claim ids it rests on, for example [S01-C003, S02-C011]. Cite
every claim from every CORROBORATED and UNIQUE group and every SUPERSEDED
winner at least once. Describe each CONFLICT in the Conflicts section citing
both sides without resolving it. State the known gaps in the Gaps section or
state that none were identified.
Then run: resynth synth-verify <project> --json
Fix every reported reason and re-run until the gate reports PASS.
```

### Stage 5, audit and seal

```
Run: resynth audit <project> --json
If the gate fails, report the reasons, never weaken or bypass them. When it
passes, run: resynth seal <project> --json
Then: resynth export <project> --json
Report the seal tag and hand output/MASTER.md and output/MASTER.json to the
user or the downstream agent.
```
