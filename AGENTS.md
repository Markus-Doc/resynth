# Agents: running RESYNTH

For any agent (Claude, Codex, Hermes, a Grok bot or other) asked to run
RESYNTH for the owner.

## Read first
1. `README.md` for what RESYNTH is and the CLI.
2. `docs/OPERATOR-PROTOCOL.md` for the gated pipeline and the copy paste
   prompts for every stage.
3. `docs/PLATFORM-RUNS.md` before running prompts on the research platforms.

## How a standard round runs
1. `resynth doctor` and `resynth update --check`.
2. Drive the CLI commands directly with `--json`, not the guided mode:
   `resynth init <project>` (standard is the default, `--light` only when asked),
   then `resynth brief <project> --topic "..."`.
3. Write one tailored prompt per platform into `prompts/RESEARCH-PROMPTS.md`.
4. Open the platform tabs and set each one up per `docs/PLATFORM-RUNS.md`:
   deep research mode first, then model and effort if still selectable, using
   the account defaults table there.
5. **Stop for the owner's review of the tab settings. Send nothing until the
   owner says go.**
6. Submit, wait, save each report as a file, then `resynth intake`.
7. Optionally `resynth resolve`, then extract, extract-verify, reconcile,
   synthesise, synth-verify, audit, seal and export. Fix every failing reason
   and re-run each gate until it passes. Never edit gate files by hand.

## Rules
- Never sign in, enter passwords, accept terms, click consent banners or pay
  for the owner. An upgrade or subscription page means go back and report.
- No browser alerts or dialogs, no downloads, no sharing, publishing or
  renaming chats.
- Projects live under `RESYNTH_ROOT` (default the current directory). Commit
  and tag sealed projects locally only. The workspace remote is this tool
  repo, so never push a workspace.
