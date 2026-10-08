# DECISIONS

Every architectural decision with a one line rationale.

- Dependency set is exactly click, pyyaml, rich and jinja2, nothing else was needed.
- src layout with an editable install keeps the CLI importable in tests without packaging tricks.
- Workspace root is the current directory with a RESYNTH_ROOT override, which keeps the tool relocatable and trivially testable.
- All state is markdown, YAML and JSONL on disk, so every pipeline step is diffable in git and inspectable by hand.
- JSONL files ignore lines starting with #, a deliberate extension so generated workspaces can carry inline instructions and schema templates.
- date_ingested lives in source frontmatter, and idempotency holds because re-intake of an already ingested hash is skipped rather than rewritten.
- Gate files carry no timestamps, so re-evaluating a gate with unchanged inputs is byte identical.
- Gate 02 additionally requires at least one claim in total, because an empty extraction passing the pipeline would be meaningless.
- Stages that depend on operator input (reconcile, synth-verify) evaluate their own gate, so their first run fails by design until the operator completes the workspace.
- synthesise never overwrites an edited MASTER.md without --force, and every replacement moves the prior version into _trash.
- seal commits SEAL.yaml before tagging, so the tag points at the sealed state and the working tree stays clean.
- Sealed versions are discovered from existing git tags, so re-sealing produces v2, v3 and so on without a counter file.
- Converted sources (.docx, .pdf) are hashed on their converted text, so drift checks re-hash the stored body and stay self contained.
- demo_operator ships canned, deterministic operator inputs for the demo and the end to end test, it is not AI and the pipeline never imports it.
- The brief stage, the prompts workspace and the export command were added at user direction on 2026-06-11 to serve the multi platform deep research workflow, extending the original five stage directive.
- Kali VM execution was dropped at user direction on 2026-06-11, RESYNTH is host native pure Python and runs anywhere Python 3.11 runs.
- Templates live at the repository root and are located relative to the package, with a package local fallback.
- Bare resynth launches a guided wizard that runs every mechanical step itself and pauses only where operator judgement is needed, so end users never learn the CLI.
- Distribution is a one line installer plus a launcher and optional desktop shortcut rather than a PyInstaller executable, because an unsigned executable triggers SmartScreen warnings that hurt non technical users more than a script install does.
- The installer keeps app code under the local app data directory and user projects in a RESYNTH folder in the home directory, so updates never touch user data.
- The wizard initialises a git repository in the workspace with a local fallback identity at seal time, so sealing works on machines with no git configuration.
- AI inference is wired in as a pluggable external operator CLI (operator.yaml at the workspace root), the pipeline itself stays AI free and the zero runtime AI guarantee now means zero embedded AI, not zero AI assistance.
- The wired assistant defaults to Claude Code at high reasoning effort and pins no model, so delegated steps use whatever default model the authed claude CLI has set and never break when a specific model is retired or gated, override per workspace with resynth operator --model.
- Delegated operator steps verify against the stage gate and retry up to three times with the gate reasons fed back, then fall back to manual mode.
- The brief step asks whether reports already exist and skips prompt generation when they do, consolidation only is a first class flow.
- resolve is a stage 01 verb that re-evaluates the intake gate, not a sixth gate, so already sealed projects never grow a phantom PENDING gate.
- Fetchers use only the Python standard library (urllib, html.parser, xml.etree), so the four dependency decision holds.
- Video transcripts are best effort, a pending stub is a real source that upgrades in place and keeps its source id, so claim ids built on it stay stable.
- Source schema v2 is adopted only through an explicit resynth migrate, never silently, and re-sealing afterwards stays an operator act.
- MASTER.json format resynth-master/2 ships together with a load_master reader that accepts both /1 and /2, so downstream consumers never break on old exports.
- Resolution is depth one by design, fetched sources are not scanned for further links unless the operator forces a re-scan with --source.
- AI routing is versioned and per-stage: model policy is explicit, context-limit
  fallback is limited to Claude-to-Codex once, and read-only AI review is
  advisory rather than source verification; deterministic gates remain the
  authority for advancement.
- Every claim carries a verbatim source_excerpt because a section reference cannot be checked by machine. Finding the excerpt in the source both rejects claims the source does not contain and pins each claim to a line and to the citations around it, so provenance survives synthesis without trusting the operator.
- Excerpt matching ignores case, whitespace, quote and dash style, markdown emphasis, footnote markers and citation tokens, because a faithful copy differs from the source in exactly those ways and nothing else.
- Provenance is derived data (index/provenance.jsonl), rebuilt by extract-verify rather than gated separately, so already sealed projects never grow a phantom gate, and the audit gate fails when it no longer matches the sources and claims.
- A citation is taken from the excerpt's own sentence first and from the rest of its paragraph only when the sentence cites nothing, recorded with a paragraph scope, because ChatGPT and similar tools cite once at the end of a run of sentences.
- Citation tokens without URLs, such as ChatGPT's, are recorded as unresolved rather than dropped, so the gap is visible and a re-export with links can close it.
- MASTER.md appendices are generated and refreshed by synthesise and synth-verify, and claim ids listed in them never count as citations, so the operator owns only the body prose.
- Guided extraction runs one AI task per source, seeded by the first source's tags and then in parallel, because a single task reading every source spent its context on sources it was not working on and forced a whole-stage retry on any failure.
- Delegated tasks run their stage check in-session (check-claims, reconcile --fill-unique, synth-verify) through python -m resynth with the wizard's own interpreter, so they work whether or not resynth is on PATH.
- reconcile --fill-unique never fills a claim that appears in a candidate pair, so the shortcut saves writing trivial UNIQUE groups without letting a possible duplicate or conflict pass undecided.
- Candidate detection weights shared words by inverse document frequency and compares only cross-source pairs, with thresholds tuned against a real 155-claim project, because plain Jaccard on restated claims flagged nothing.
