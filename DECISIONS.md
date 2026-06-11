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
