"""Claim provenance. Pins every claim to a verified place in its source and
to the evidence the source itself cites at that place.

Each claim carries a short verbatim ``source_excerpt``. This module finds the
excerpt in the ingested source body, records the line, page, heading and
video timestamp it sits at, and extracts the citations inside the sentence or
table row that holds it: numbered footnotes, markdown links, bare URLs,
author-year references resolved against the source's reference list, and
citation tokens whose targets are missing from the saved file.

The output is index/provenance.jsonl. It is derived data, rebuilt from the
sources and claims on every extract-verify, and never edited by hand.
"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .fsutil import iter_jsonl, safe_write

PROVENANCE_FILE = "provenance.jsonl"
EXCERPT_MIN = 15
EXCERPT_MAX = 300

# Characters that differ between a source and a faithful copy of it: smart
# quotes and dashes, non-breaking spaces, markdown emphasis and escapes.
_TRANSLATE = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u00a0": " ",
})
_DROP = set("*_`\\")
# Spans skipped while matching, because a copied excerpt usually omits them:
# ChatGPT citation token blocks and numbered footnote markers.
_TOKEN_BLOCK = re.compile("\ue200(?:file)?cite\ue202(.*?)\ue201", re.S)
_FOOTNOTE_MARK = re.compile(r"\\?\[(?:\^(\w{1,12})|(\d{1,3}))\\?\](?!:|\()")
_SKIP_RE = re.compile(_TOKEN_BLOCK.pattern + r"|" + _FOOTNOTE_MARK.pattern, re.S)

_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_URL = re.compile(r"https?://[^\s<>\"'`|)\]]+")
_AUTHOR_YEAR = re.compile(r"\(([^()\n]*?[A-Z\u00c0-\u024f][^()]*?\b(?:19|20)\d{2}[a-z]?[^()]*?)\)")
_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)")
_HEADING_NUM = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z][^.|]{2,70}$")
_TIMESTAMP = re.compile(r"\[(\d{1,2}:\d{2}:\d{2})\]")
_REF_HEADING = re.compile(
    r"^\s*(?:#+\s*)?(?:\d+\.?\s*)?(references|bibliography|works cited|sources|citations|notes)\s*:?\s*$",
    re.I,
)
_REF_START = re.compile(r"^[A-Z\u00c0-\u024f][\w'\u00c0-\u024f-]+(?: [A-Z][\w-]+)*, (?:[A-Z]\.|[A-Z][a-z]+)")
_NUMBERED_LINK_NOTE = re.compile(r"^\s*(\d{1,3})\.\s+\[(.+?)\]\((https?://[^)\s]+)\)")
_MD_FOOTNOTE_DEF = re.compile(r"^\s*\[\^?(\w{1,12})\]:\s*(.*)$")
_BRACKET_NOTE = re.compile(r"^\s*\[(\d{1,3})\]\s+(.*)$")


def normalise(text: str) -> str:
    """Normalised form used to compare an excerpt with its source."""
    out, prev_space = [], True
    for ch in _SKIP_RE.sub(" ", text).translate(_TRANSLATE):
        if ch in _DROP:
            continue
        if ch.isspace():
            if not prev_space:
                out.append(" ")
            prev_space = True
        else:
            out.append(ch.casefold())
            prev_space = False
    return "".join(out).strip()


@dataclass
class SourceText:
    """A source body indexed for excerpt search and citation lookup."""

    source_id: str
    body: str
    source_type: str = "report"
    norm: str = ""
    offsets: list[int] = field(default_factory=list)
    line_starts: list[int] = field(default_factory=list)
    page_breaks: list[int] = field(default_factory=list)
    footnotes: dict[str, dict] = field(default_factory=dict)
    references: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        skip = [(m.start(), m.end()) for m in _SKIP_RE.finditer(self.body)]
        out, offsets, prev_space, k = [], [], True, 0
        i = 0
        text = self.body
        while i < len(text):
            if k < len(skip) and i == skip[k][0]:
                i = skip[k][1]
                k += 1
                ch = " "
                pos = i
            else:
                ch = text[i].translate(_TRANSLATE)
                pos = i
                i += 1
            if ch in _DROP:
                continue
            if ch.isspace():
                if not prev_space:
                    out.append(" ")
                    offsets.append(pos)
                prev_space = True
            else:
                out.append(ch.casefold())
                offsets.append(pos)
                prev_space = False
        self.norm = "".join(out)
        self.offsets = offsets
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
        self.page_breaks = [m.start() for m in re.finditer("\f", text)]
        self.lines = text.split("\n")
        self.footnotes = _parse_footnotes(self.lines)
        self.references = _parse_references(self.lines)

    def find(self, excerpt: str) -> list[tuple[int, int]]:
        """Every (start, end) offset in the body where the excerpt occurs."""
        needle = normalise(excerpt)
        if not needle:
            return []
        hits = []
        start = self.norm.find(needle)
        while start >= 0:
            end = start + len(needle) - 1
            hits.append((self.offsets[start], self.offsets[end] + 1))
            start = self.norm.find(needle, start + 1)
        return hits

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self.line_starts, offset)

    def page_of(self, offset: int) -> int | None:
        if not self.page_breaks:
            return None
        return bisect.bisect_right(self.page_breaks, offset) + 1

    def heading_before(self, line: int) -> str | None:
        plain = self._plain_text()
        for i in range(line - 1, -1, -1):
            text = self.lines[i].replace("\f", "")
            m = _HEADING_MD.match(text)
            if m:
                return m.group(1).strip("# ").strip()
            if _HEADING_NUM.match(text):
                return text.strip()
            if plain and self._looks_like_heading(i):
                return text.strip()
        return None

    def _plain_text(self) -> bool:
        """True for converted text (PDF, docx) that has no markdown headings."""
        if not hasattr(self, "_plain"):
            self._plain = not any(_HEADING_MD.match(t) for t in self.lines)
        return self._plain

    def _looks_like_heading(self, i: int) -> bool:
        """A short capitalised line standing alone between blank lines."""
        text = self.lines[i].replace("\f", "").strip()
        if not text or len(text) > 60 or text[-1] in ".,;:" or not text[0].isupper():
            return False
        if len(text.split()) > 6 or "  " in text:
            return False
        before = self.lines[i - 1].replace("\f", "").strip() if i > 0 else ""
        return not before

    def timestamp_before(self, offset: int) -> str | None:
        last = None
        for m in _TIMESTAMP.finditer(self.body, 0, offset + 1):
            last = m.group(1)
        return last


def _parse_footnotes(lines: list[str]) -> dict[str, dict]:
    """Numbered source lists and markdown footnote definitions."""
    notes: dict[str, dict] = {}
    for text in lines:
        m = _NUMBERED_LINK_NOTE.match(text)
        if m:
            notes.setdefault(m.group(1), {"title": _unescape(m.group(2)), "url": m.group(3)})
            continue
        m = _MD_FOOTNOTE_DEF.match(text) or _BRACKET_NOTE.match(text)
        if m:
            rest = m.group(2)
            link = _MD_LINK.search(rest)
            url = link.group(2) if link else (_URL.search(rest).group(0) if _URL.search(rest) else None)
            title = link.group(1) if link else _URL.sub("", rest).strip(" .-") or None
            notes.setdefault(m.group(1), {"title": _unescape(title) if title else None,
                                          "url": url.rstrip(".,") if url else None})
    return notes


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _parse_references(lines: list[str]) -> list[dict]:
    """Author-year reference entries after a References style heading."""
    start = next((i for i, t in enumerate(lines) if _REF_HEADING.match(t.replace("\f", ""))), None)
    if start is None:
        return []
    kept = []
    for raw in lines[start + 1:]:
        text = raw.replace("\f", "").rstrip()
        if not text.strip() or re.match(r"^\s*\d+ / \d+\s*$", text):
            continue
        kept.append(text.strip())
    entries: list[str] = []
    cur: list[str] = []
    for text in kept:
        # A new entry starts at an author pattern, unless the previous line
        # ended mid author list, as long multi-line author lists do.
        if _REF_START.match(text) and cur and not cur[-1].endswith(","):
            entries.append(" ".join(cur))
            cur = []
        cur.append(text)
    if cur:
        entries.append(" ".join(cur))
    refs = []
    for entry in entries:
        m = re.match(r"^([^,]+), (.*?)\(((?:19|20)\d{2})[a-z]?\)\.? (.+?)\. ", entry)
        if not m:
            continue
        authors = f"{m.group(1)}, {m.group(2)}"
        doi = re.search(r"https?://doi\.org/\S+", entry)
        url = doi.group(0) if doi else (_URL.search(entry).group(0) if _URL.search(entry) else None)
        refs.append({
            "surname": m.group(1).strip(), "year": m.group(3), "title": m.group(4).strip(),
            "n_authors": authors.count("., ") + 1, "authors": authors,
            "url": url.rstrip(".,") if url else None,
        })
    return refs


def _resolve_author_year(cite: str, refs: list[dict]) -> list[dict]:
    m = re.match(r"^\s*([A-Z\u00c0-\u024f][\w'\u00c0-\u024f-]+)(.*?)((?:19|20)\d{2})", cite)
    if not m:
        return []
    hits = [r for r in refs if r["surname"] == m.group(1) and r["year"] == m.group(3)]
    middle = m.group(2)
    if "et al" in middle:
        hits = [r for r in hits if r["n_authors"] >= 3] or hits
    elif "&" in middle or " and " in middle:
        second = re.split(r"&| and ", middle, maxsplit=1)[1].strip(" ,")
        hits = [r for r in hits if r["n_authors"] == 2 and second in r["authors"]] or hits
    else:
        hits = [r for r in hits if r["n_authors"] == 1] or hits
    return hits


# A list item, table row or heading on the next line also ends a sentence.
_BLOCK_BREAK = r"\n\s*\n|\n(?=\s*(?:[-*+]\s|\d+\.\s|#|\|))"
_SENTENCE_END = re.compile(
    r"[.!?][\"')\u201d\u2019]?(?=\s|\\?\[\^?\d|\ue200|$)|" + _BLOCK_BREAK
)
_PARAGRAPH_END = re.compile(_BLOCK_BREAK)
_TRAILING_MARKS = re.compile(r"(?:\s*(?:" + _FOOTNOTE_MARK.pattern + r"|" + _TOKEN_BLOCK.pattern + r"))*", re.S)
_ANY_CITATION = re.compile(_FOOTNOTE_MARK.pattern + r"|" + _TOKEN_BLOCK.pattern + r"|" + _AUTHOR_YEAR.pattern, re.S)


def _citation_spans(src: SourceText, start: int, end: int) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """The sentence, list item or table row that holds the excerpt, with any
    citation markers trailing its closing punctuation, and, when that holds no
    citation, the stretch of the same paragraph up to the next citation.
    Some writers (ChatGPT in particular) cite once at the end of a run of
    sentences, so the paragraph fallback is recorded with its own scope."""
    text = src.body
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    if text[line_start:line_end].lstrip().startswith("|"):
        return (line_start, line_end), None
    m = _SENTENCE_END.search(text, end)
    span_end = m.end() if m else len(text)
    span_end = _TRAILING_MARKS.match(text, span_end).end()
    para = _PARAGRAPH_END.search(text, span_end)
    para_end = para.start() if para else len(text)
    nxt = _ANY_CITATION.search(text, span_end, para_end)
    fallback = None
    if nxt:
        close = _TRAILING_MARKS.match(text, nxt.end()).end()
        fallback = (span_end, close)
    return (start, span_end), fallback


def _citations(src: SourceText, span: str, resolved_urls: dict[str, str]) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple] = set()

    def add(entry: dict) -> None:
        key = (entry["kind"], entry.get("marker"), entry.get("url"))
        if key in seen:
            return
        seen.add(key)
        if entry.get("url") and entry["url"] in resolved_urls:
            entry["fetched_as"] = resolved_urls[entry["url"]]
        found.append(entry)

    for m in _FOOTNOTE_MARK.finditer(span):
        key = m.group(1) or m.group(2)
        note = src.footnotes.get(key)
        if note:
            add({"kind": "footnote", "marker": f"[{key}]", "title": note["title"], "url": note["url"]})
        else:
            add({"kind": "footnote", "marker": f"[{key}]", "title": None, "url": None,
                 "note": "marker has no matching entry in the source"})
    for m in _TOKEN_BLOCK.finditer(span):
        for token in m.group(1).split("\ue202"):
            add({"kind": "citation_token", "marker": token, "title": None, "url": None,
                 "note": "the saved file holds this citation token but not its URL"})
    linked = set()
    for m in _MD_LINK.finditer(span):
        linked.add(m.group(2))
        add({"kind": "link", "marker": None, "title": _unescape(m.group(1)), "url": m.group(2)})
    for m in _URL.finditer(span):
        url = m.group(0).rstrip(".,;:")
        if url not in linked:
            add({"kind": "url", "marker": None, "title": None, "url": url})
    if src.references:
        for m in _AUTHOR_YEAR.finditer(" ".join(span.split())):
            for cite in m.group(1).split(";"):
                cite = cite.strip()
                if not re.search(r"(?:19|20)\d{2}", cite):
                    continue
                matches = _resolve_author_year(cite, src.references)
                if not matches:
                    add({"kind": "paper", "marker": cite, "title": None, "url": None,
                         "note": "not found in the source's reference list"})
                for ref in matches:
                    entry = {"kind": "paper", "marker": cite, "title": ref["title"], "url": ref["url"]}
                    if len(matches) > 1:
                        entry["note"] = "author and year match more than one reference"
                    add(entry)
    return found


def status_of(citations: list[dict]) -> str:
    if any(c.get("url") for c in citations):
        return "cited"
    if citations:
        return "unresolved"
    return "uncited"


def locate_claim(src: SourceText, claim: dict, resolved_urls: dict[str, str] | None = None) -> tuple[dict | None, list[str], list[str]]:
    """Return (record, errors, warnings) for one claim."""
    cid = claim.get("claim_id")
    excerpt = claim.get("source_excerpt")
    if not isinstance(excerpt, str) or not excerpt.strip():
        return None, [], []
    hits = src.find(excerpt)
    if not hits:
        return None, [f"{cid}: source_excerpt not found verbatim in {src.source_id}"], []
    warnings = []
    if len(hits) > 1:
        warnings.append(f"{cid}: source_excerpt occurs {len(hits)} times in {src.source_id}, the first is used, lengthen it to be unique")
    start, end = hits[0]
    (span_start, span_end), fallback = _citation_spans(src, start, end)
    citations = _citations(src, src.body[span_start:span_end], resolved_urls or {})
    for c in citations:
        c["scope"] = "sentence"
    if not citations and fallback:
        citations = _citations(src, src.body[fallback[0]:fallback[1]], resolved_urls or {})
        for c in citations:
            c["scope"] = "paragraph"
    record = {
        "claim_id": cid,
        "source_id": src.source_id,
        "source_excerpt": excerpt,
        "line_start": src.line_of(start),
        "line_end": src.line_of(end - 1),
        "section": src.heading_before(src.line_of(start)),
        "occurrences": len(hits),
        "citations": citations,
        "status": status_of(citations),
    }
    page = src.page_of(start)
    if page:
        record["page"] = page
    if src.source_type == "video-transcript":
        stamp = src.timestamp_before(start)
        if stamp:
            record["timestamp"] = stamp
    return record, [], warnings


def build(sources: list[dict], claims: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """Provenance records for every claim that carries an excerpt."""
    texts = {fm["source_id"]: SourceText(fm["source_id"], fm["_body"], fm.get("source_type") or "report")
             for fm in sources}
    resolved_urls = {fm["url"]: fm["source_id"] for fm in sources if fm.get("url")}
    records, errors, warnings = [], [], []
    for claim in claims:
        src = texts.get(claim.get("source_id"))
        if src is None:
            continue
        rec, errs, warns = locate_claim(src, claim, resolved_urls)
        errors.extend(errs)
        warnings.extend(warns)
        if rec:
            records.append(rec)
    return records, errors, warnings


def write(pdir: Path, records: list[dict], dry_run: bool = False) -> str:
    header = (
        "# RESYNTH claim provenance, derived from sources and claims by extract-verify.\n"
        "# Do not edit. Each line pins one claim to its source and the evidence cited there.\n"
    )
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in sorted(records, key=lambda r: r["claim_id"]))
    return safe_write(pdir / "index" / PROVENANCE_FILE, header + body, pdir, dry_run=dry_run)


def load(pdir: Path) -> dict[str, dict]:
    path = pdir / "index" / PROVENANCE_FILE
    if not path.is_file():
        return {}
    return {obj["claim_id"]: obj for _n, _raw, obj, err in iter_jsonl(path) if not err}


def summary(records: dict[str, dict] | list[dict]) -> dict:
    values = list(records.values()) if isinstance(records, dict) else records
    counts = {"cited": 0, "unresolved": 0, "uncited": 0}
    for r in values:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"claims_located": len(values), **counts}


def location_label(rec: dict) -> str:
    """Short human readable location, for example 'p. 3, L125-126'."""
    lines = f"L{rec['line_start']}" + (f"-{rec['line_end']}" if rec["line_end"] != rec["line_start"] else "")
    parts = []
    if rec.get("page"):
        parts.append(f"p. {rec['page']}")
    if rec.get("timestamp"):
        parts.append(rec["timestamp"])
    parts.append(lines)
    return ", ".join(parts)


def citation_label(c: dict, markdown: bool = True) -> str:
    marker, title, url = c.get("marker"), c.get("title"), c.get("url")
    if c.get("kind") == "paper":
        label = f"{marker}: {title}" if title else marker
    elif marker and c.get("kind") in {"footnote", "citation_token"}:
        label = f"{marker} {title}" if title else marker
    else:
        label = title or url or "citation"
    if markdown:
        label = label.replace("|", "\\|")
    if url and markdown:
        text = f"[{label}]({url})" if label != url else f"<{url}>"
    elif url and label != url:
        text = f"{label} <{url}>"
    else:
        text = label
    if c.get("fetched_as"):
        text += f" (fetched as {c['fetched_as']})"
    if c.get("scope") == "paragraph":
        text += " (cited later in the same paragraph)"
    if c.get("note"):
        text += f" ({c['note']})"
    return text
