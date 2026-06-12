# Changelog

All notable changes to RESYNTH are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-06-12

### Added
- Source resolution (`resynth resolve`): follows links and file references
  found inside ingested sources and registers what it fetches as new first
  class sources with provenance. Five target kinds: html articles, pdf
  links, local files, YouTube videos and Vimeo videos. Public video
  captions become timestamped transcripts.
- Transcript pending stubs: a video without public captions still becomes
  a real source, and a later successful fetch upgrades the stub in place,
  keeping its source id.
- The resolution manifest at `index/resolution.jsonl`: records every
  target and its outcome so re-runs are idempotent. Fetched and duplicate
  targets are never retried, failed and pending ones are.
- Schema v2 source frontmatter: `source_type`, `url`, `resolved_from` and,
  for video sources, `transcript_status`.
- Optional `source_locator` on claims, a deep link into the source built
  from a url, page, timestamp or anchor, validated by `extract-verify`.
- `resynth migrate`: explicit upgrade of a project's sources to schema v2.
  Bodies and content hashes are untouched, re-sealing stays a separate
  operator step.
- `resynth --version`.
- MASTER.json format `resynth-master/2` with a sources array, plus a
  `load_master` reader that accepts both `/1` and `/2`.
- The guided wizard offers source resolution straight after intake.
- Completion ping: when a delegated AI step runs longer than 90 seconds,
  RESYNTH plays a sound and shows a desktop notification (Windows toast /
  macOS notification) when it finishes, and again when the master document
  is sealed — safe to walk away from long steps.
- Live progress while an AI assistant works on a delegated step: a status
  line with elapsed time and when the project last had a file saved, plus
  the assistant's output streamed as it arrives, instead of a silent prompt
  until completion.

### Changed
- Default model for the Claude Code operator is now Fable 5
  (`claude-fable-5`), Anthropic's newest and fastest top-tier model;
  override per workspace in `operator.yaml` as before.
- The MASTER.md source register gains Type and Link columns, so every
  source's kind and origin url are visible in the sealed master.

### Fixed
- Sealing failed with "paths are ignored by one of your .gitignore files"
  in workspaces where `projects/*` is gitignored (any workspace cloned from
  this repo): the seal file is now force-added so the tag always has a
  tracked seal to pin.
- Windows: AI delegation crashed with a raw traceback when the configured
  CLI was installed as an npm `.cmd` shim (the common case for Claude Code,
  Codex and Gemini). External tools are now spawned by their resolved path,
  and batch shims receive the prompt on stdin so multi line prompts survive
  cmd.exe argument parsing.
- The wizard now falls back to manual guidance with a friendly install hint
  when the AI assistant cannot be launched, instead of dying.
- The CLI never prints a raw traceback: unexpected errors show a short
  message plus the path to a saved crash log and exit nonzero.
- Git, pandoc and pdftotext launches are hardened the same way (resolved
  paths, friendly errors when missing, UTF-8 output decoding), and sealing
  no longer fails on OneDrive/symlinked workspace paths.

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
