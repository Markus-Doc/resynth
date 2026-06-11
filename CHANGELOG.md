# Changelog

All notable changes to RESYNTH are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-11

First public release.

### Added
- Five stage gated pipeline: intake, extract, reconcile, synthesise, audit,
  with a machine verified gate between every stage.
- Guided wizard mode: double click and follow along, resumable at any step.
- AI operator wiring: detects Claude Code, Codex and Gemini CLIs and runs
  the thinking steps automatically with gate verified retries
  (`resynth operator`).
- Full provenance: every statement in the sealed master traces to a source
  claim, hash verified end to end (`resynth seal`, `resynth audit`).
- Machine readable export for downstream agents (`resynth export` →
  `MASTER.json`).
- One line installers for Windows (`install.ps1`) and macOS/Linux
  (`install.sh`).
- Bundled three source demo with a scripted end to end run
  (`scripts/run_demo.py`).
- Environment doctor (`resynth doctor`) and per command run logs.
