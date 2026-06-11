"""Project lifecycle: init and the research brief workspace.

The brief stage front loads the user's research intent. The operator
(an AI agent in chat) turns the brief into one tailored prompt per deep
research platform, the user runs those, and the returned reports become
intake sources.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader

from . import config
from .errors import ResynthError
from .fsutil import safe_write

PLATFORMS = [
    "claude-research",
    "chatgpt-deep-research",
    "gemini-deep-research",
    "perplexity-deep-research",
]


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(config.templates_dir())),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def run_init(project: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project, must_exist=False)
    if pdir.exists():
        raise ResynthError(f"project '{project}' already exists at {pdir}")
    events = []
    if not dry_run:
        for sub in config.PROJECT_SUBDIRS:
            (pdir / sub).mkdir(parents=True, exist_ok=True)
        (pdir / "prompts").mkdir(exist_ok=True)
    outcome = safe_write(pdir / "merge-rules.yaml", config.DEFAULT_MERGE_RULES, pdir, dry_run=dry_run)
    events.append({"file": "merge-rules.yaml", "action": outcome})
    return {
        "ok": True,
        "events": events,
        "messages": [
            f"project '{project}' initialised at {pdir}",
            "next: resynth brief to capture the research question, or resynth intake",
        ],
    }


def run_brief(project: str, topic: str, dry_run: bool = False) -> dict:
    pdir = config.project_dir(project)
    if not topic.strip():
        raise ResynthError("brief requires a non-empty --topic")
    env = _jinja()
    events = []
    brief = env.get_template("brief.md.j2").render(project=project, topic=topic.strip())
    events.append({"file": "BRIEF.md", "action": safe_write(pdir / "BRIEF.md", brief, pdir, dry_run=dry_run)})
    prompts = env.get_template("research-prompts.md.j2").render(
        project=project, topic=topic.strip(), platforms=PLATFORMS
    )
    events.append(
        {
            "file": "prompts/RESEARCH-PROMPTS.md",
            "action": safe_write(pdir / "prompts" / "RESEARCH-PROMPTS.md", prompts, pdir, dry_run=dry_run),
        }
    )
    return {
        "ok": True,
        "events": events,
        "messages": [f"{e['file']}: {e['action']}" for e in events]
        + ["operator fills one prompt per platform, user runs them, reports come back via intake"],
    }
