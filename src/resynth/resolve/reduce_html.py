"""Reduce noisy HTML to markdown-ish clean text using the stdlib parser."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

DROP = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "form",
    "nav",
    "header",
    "footer",
    "aside",
    "iframe",
}
REGION = {"main", "article"}
HEADINGS = {f"h{n}": n for n in range(1, 7)}
BLOCK_PREFIX = {"p": "", "blockquote": "> ", "li": "- "}


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _Reducer(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.blocks: list[tuple[bool, str]] = []
        self.cur: list | None = None  # [prefix, parts, is_pre]
        self.drop = 0
        self.region_seen = False
        self.in_region = False
        self.region_depth = 0
        self.links: list[str | None] = []
        self.cells: list[str] | None = None

    def _open(self, prefix: str, pre: bool = False) -> None:
        self._flush()
        self.cur = [prefix, [], pre]

    def _flush(self) -> None:
        if self.cur is None:
            return
        prefix, parts, pre = self.cur
        self.cur = None
        raw = "".join(parts)
        if pre:
            text = raw.strip("\n")
            if text.strip():
                self.blocks.append((self.in_region, f"```\n{text}\n```"))
            return
        text = _collapse(raw)
        if not text:
            return
        if self.cells is not None:
            self.cells.append(text)
            return
        self.blocks.append((self.in_region, prefix + text))

    def handle_starttag(self, tag, attrs):
        if tag in DROP:
            self.drop += 1
            return
        if self.drop:
            return
        if tag in REGION:
            if not self.region_seen:
                self.region_seen = True
                self.in_region = True
                self.region_depth = 1
            elif self.in_region:
                self.region_depth += 1
            return
        if tag in HEADINGS:
            self._open("#" * HEADINGS[tag] + " ")
        elif tag == "pre":
            self._open("", pre=True)
        elif tag in BLOCK_PREFIX:
            if tag == "p" and self.cur is not None and self.cur[0] in ("> ", "- "):
                self.cur[1].append(" ")
            else:
                self._open(BLOCK_PREFIX[tag])
        elif tag == "tr":
            self._flush()
            self.cells = []
        elif tag in ("td", "th"):
            if self.cells is not None:
                self._open("")
        elif tag == "br":
            if self.cur is not None:
                self.cur[1].append(" ")
        elif tag == "a":
            href = dict(attrs).get("href")
            self.links.append(urljoin(self.base_url, href) if href else None)

    def handle_endtag(self, tag):
        if tag in DROP:
            if self.drop:
                self.drop -= 1
            return
        if self.drop:
            return
        if tag in REGION:
            if self.in_region:
                self.region_depth -= 1
                if self.region_depth <= 0:
                    self.in_region = False
            return
        if tag in HEADINGS or tag == "pre":
            self._flush()
        elif tag == "p":
            if self.cur is not None and self.cur[0] == "":
                self._flush()
        elif tag == "blockquote":
            if self.cur is not None and self.cur[0] == "> ":
                self._flush()
        elif tag == "li":
            if self.cur is not None and self.cur[0] == "- ":
                self._flush()
        elif tag in ("td", "th"):
            self._flush()
        elif tag == "tr":
            self._flush()
            if self.cells is not None:
                row = " | ".join(cell for cell in self.cells if cell)
                if row:
                    self.blocks.append((self.in_region, row))
                self.cells = None
        elif tag == "table":
            self.cells = None
        elif tag == "a":
            if self.links:
                href = self.links.pop()
                if href and self.cur is not None:
                    self.cur[1].append(f" ({href})")

    def handle_data(self, data):
        if self.drop or self.cur is None:
            return
        self.cur[1].append(data)


class _TitleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.og: str | None = None
        self.title: str | None = None
        self.h1: str | None = None
        self._stack: list[list] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and self.og is None:
            prop = a.get("property") or a.get("name")
            if prop == "og:title" and a.get("content"):
                self.og = _collapse(a["content"])
        elif tag in ("title", "h1"):
            self._stack.append([tag, []])

    def handle_data(self, data):
        if self._stack:
            self._stack[-1][1].append(data)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1][0] == tag:
            name, parts = self._stack.pop()
            text = _collapse("".join(parts))
            if name == "title" and self.title is None and text:
                self.title = text
            if name == "h1" and self.h1 is None and text:
                self.h1 = text


def extract_title(html: str) -> str | None:
    """Page title, preferring og:title, then <title>, then the first h1."""
    parser = _TitleParser()
    parser.feed(html)
    parser.close()
    return parser.og or parser.title or parser.h1


def reduce_html(html: str, base_url: str) -> tuple[str, str | None]:
    """Return (markdown_body, title) for an HTML page."""
    reducer = _Reducer(base_url)
    reducer.feed(html)
    reducer.close()
    reducer._flush()
    blocks = [
        text for in_region, text in reducer.blocks if in_region or not reducer.region_seen
    ]
    body = "\n\n".join(blocks)
    return (body + "\n" if body else ""), extract_title(html)
