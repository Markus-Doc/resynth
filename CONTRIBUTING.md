# Contributing to RESYNTH

Thanks for your interest. Bug reports, fixes and focused improvements are
welcome.

## Ground rules

- RESYNTH has **zero runtime AI dependency** by design. Contributions must
  not add model calls, API keys or network access to the pipeline itself.
  AI assistants operate the pipeline from outside, via the CLI.
- All pipeline state stays plain text on disk and diffable in git.
- No destructive operations: replaced files move to a timestamped `_trash`
  directory, never deleted.
- Every architectural decision gets a one line rationale in `DECISIONS.md`.

## Development setup

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\pip
resynth doctor
pytest
```

Requires Python 3.11+ and git. The test suite includes a full end to end
pipeline run and takes only a few seconds.

## Submitting changes

1. Fork and branch from `main`.
2. Keep changes focused; one concern per pull request.
3. Add or update tests for anything behavioural. `pytest` must pass.
4. If you changed a design decision, record it in `DECISIONS.md`.

## Reporting issues

Use GitHub issues for bugs and feature requests. For security problems, see
[SECURITY.md](SECURITY.md) — never open a public issue for those.
