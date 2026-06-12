"""Discover fetchable targets referenced inside a source body.

URLs are taken from bare links and markdown link destinations. Local paths
are only accepted from markdown destinations or backtick spans, with a
supported suffix, and only when the file actually exists. Nothing else is
guessed.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..intake import SUPPORTED

_TARGET_RE = re.compile(
    r"\]\(((?:[^()\s]|\([^()]*\))+)\)"  # markdown link destination
    r"|(https?://[^\s<>\"'`\]]+)"  # bare url
    r"|`([^`\n]+)`"  # backtick span
)
_TRAILING = ")>,.;:]\"'"
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/)")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def _strip_url(url: str) -> str:
    while url:
        ch = url[-1]
        if ch not in _TRAILING:
            break
        if ch == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def _resolve_local(raw: str, origin: str) -> str | None:
    cand = raw.strip()
    if not cand or _SCHEME_RE.match(cand):
        return None
    if Path(cand).suffix.lower() not in SUPPORTED:
        return None
    if _ABS_RE.match(cand):
        path = Path(cand)
        if path.is_file():
            return str(path.resolve())
    if origin and not _SCHEME_RE.match(origin):
        path = Path(origin).parent / cand
        if path.is_file():
            return str(path.resolve())
    return None


def discover_targets(body: str, origin: str) -> list[dict]:
    """Return ordered, deduped targets: {"raw": str, "kind": "url"|"local"}."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(raw: str, kind: str) -> None:
        if raw and raw not in seen:
            seen.add(raw)
            out.append({"raw": raw, "kind": kind})

    for match in _TARGET_RE.finditer(body):
        dest, bare, span = match.groups()
        if dest is not None:
            if dest.lower().startswith(("http://", "https://")):
                add(dest, "url")
            elif not _SCHEME_RE.match(dest):
                local = _resolve_local(dest, origin)
                if local:
                    add(local, "local")
        elif bare is not None:
            url = _strip_url(bare)
            if url:
                add(url, "url")
        else:
            local = _resolve_local(span, origin)
            if local:
                add(local, "local")
    return out
