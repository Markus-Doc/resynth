"""Fetchers turn a resolved target into a FetchedDoc dict ready for intake."""

from __future__ import annotations

import html as htmllib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from .. import intake
from ..errors import ResynthError
from . import net
from .net import FetchError
from .reduce_html import reduce_html

PENDING_STUB = (
    "# {title}\n"
    "\n"
    "> [!info] Video transcript pending\n"
    "> RESYNTH could not retrieve a public caption track for this video.\n"
    "> Link: {url}\n"
    "> Re-run `resynth resolve <project>` to retry, or paste the transcript\n"
    "> below this callout. The next resolve run can also upgrade this stub.\n"
)

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}

_VTT_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
)


def classify_target(raw: str) -> str:
    if re.match(r"^https?://", raw, re.IGNORECASE):
        host = (urlsplit(raw).hostname or "").lower()
        if host in _YT_HOSTS:
            return "youtube"
        if host in _VIMEO_HOSTS:
            return "vimeo"
        return "url"
    if Path(raw).exists():
        return "local"
    return "url"


def _doc(
    body: str,
    title: str,
    source_type: str,
    url: str | None,
    origin: str,
    author_or_tool: str = "unknown",
    date_authored: str = "unknown",
    transcript_status: str | None = None,
) -> dict:
    return {
        "body_markdown": body,
        "title": title,
        "source_type": source_type,
        "url": url,
        "origin": origin,
        "author_or_tool": author_or_tool,
        "date_authored": date_authored,
        "transcript_status": transcript_status,
    }


def _heading_title(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def fetch_local(path: str) -> dict:
    src = Path(path)
    try:
        body = intake._convert(src)
    except ResynthError as err:
        raise FetchError(str(err)) from err
    source_type = "pdf" if src.suffix.lower() == ".pdf" else "notes"
    return _doc(body, _heading_title(body) or src.stem, source_type, None, str(src))


def fetch_url(url: str) -> dict:
    payload, content_type, final_url = net.http_get(url)
    ct = (content_type or "").split(";")[0].strip().lower()
    path = urlsplit(final_url or url).path.lower()
    if ct == "application/pdf" or path.endswith(".pdf"):
        handle, name = tempfile.mkstemp(suffix=".pdf")
        tmp = Path(name)
        try:
            with os.fdopen(handle, "wb") as fh:
                fh.write(payload)
            try:
                body = intake._convert(tmp)
            except ResynthError as err:
                raise FetchError(str(err)) from err
        finally:
            tmp.unlink(missing_ok=True)
        title = _heading_title(body) or Path(path).stem or url
        return _doc(body, title, "pdf", url, url)
    if "html" in ct:
        text = net.decode(payload, content_type)
        body, title = reduce_html(text, final_url or url)
        if len(body.strip()) < 200:
            raise FetchError(
                "page yielded no extractable text (login wall or script rendered)"
            )
        return _doc(body, title or url, "html-article", url, url)
    raise FetchError(f"unsupported content type {ct or 'unknown'}")


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _render_transcript(cues: list[tuple[float, float, str]]) -> str:
    paras: list[list[str]] = [[]]
    prev_end: float | None = None
    for start, end, text in cues:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if prev_end is not None and start - prev_end > 8:
            paras.append([])
        paras[-1].append(f"[{_hms(start)}] {text}")
        prev_end = end
    body = "\n\n".join("\n".join(p) for p in paras if p)
    return f"## Transcript\n\n{body}\n"


def _oembed(endpoint: str) -> dict:
    try:
        body, _ct, _final = net.http_get(endpoint)
        data = json.loads(body.decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (FetchError, ValueError):
        return {}


def _video_doc(
    url: str,
    title: str,
    author: str,
    date_authored: str,
    cues: list[tuple[float, float, str]],
) -> dict:
    if cues:
        body = f"# {title}\n\n{_render_transcript(cues)}"
        status = "fetched"
    else:
        body = PENDING_STUB.format(title=title, url=url)
        status = "pending"
    return _doc(body, title, "video-transcript", url, url, author, date_authored, status)


def _youtube_id(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        seg = parts.path.strip("/").split("/")[0]
        return seg or None
    qs = parse_qs(parts.query)
    if qs.get("v"):
        return qs["v"][0]
    match = re.match(r"^/(?:shorts|embed|live)/([^/?#]+)", parts.path)
    return match.group(1) if match else None


def fetch_youtube(url: str) -> dict:
    vid = _youtube_id(url)
    if not vid:
        raise FetchError("could not determine youtube video id")
    meta = _oembed(f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json")
    title = meta.get("title") or url
    author = meta.get("author_name") or "unknown"
    cues: list[tuple[float, float, str]] = []
    try:
        listing, _ct, _final = net.http_get(
            f"https://www.youtube.com/api/timedtext?type=list&v={vid}"
        )
        codes = [t.get("lang_code") or "" for t in ET.fromstring(listing).findall(".//track")]
        codes = [c for c in codes if c]
        code = next((c for c in codes if c.lower().startswith("en")), codes[0] if codes else None)
        if code:
            track, _ct, _final = net.http_get(
                f"https://www.youtube.com/api/timedtext?lang={quote(code)}&v={vid}"
            )
            for el in ET.fromstring(track).findall(".//text"):
                start = float(el.get("start") or 0)
                dur = float(el.get("dur") or 0)
                cues.append((start, start + dur, htmllib.unescape("".join(el.itertext()))))
    except (FetchError, ET.ParseError, ValueError):
        cues = []
    return _video_doc(url, title, author, "unknown", cues)


def _vimeo_id(url: str) -> str | None:
    for seg in urlsplit(url).path.split("/"):
        if seg.isdigit():
            return seg
    return None


def _vtt_seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _parse_vtt(text: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(("NOTE", "STYLE", "REGION")):
            i += 1
            while i < len(lines) and lines[i].strip():
                i += 1
            continue
        if not line or line.startswith("WEBVTT"):
            i += 1
            continue
        match = _VTT_TIME.search(line)
        if not match:
            i += 1
            continue
        start = _vtt_seconds(*match.groups()[:4])
        end = _vtt_seconds(*match.groups()[4:])
        i += 1
        texts = []
        while i < len(lines) and lines[i].strip():
            texts.append(lines[i].strip())
            i += 1
        cue_text = htmllib.unescape(re.sub(r"<[^>]+>", "", " ".join(texts)))
        cues.append((start, end, cue_text))
    return cues


def fetch_vimeo(url: str) -> dict:
    vid = _vimeo_id(url)
    if not vid:
        raise FetchError("could not determine vimeo video id")
    meta = _oembed(f"https://vimeo.com/api/oembed.json?url={quote(url, safe='')}")
    title = meta.get("title") or url
    author = meta.get("author_name") or "unknown"
    date_authored = str(meta.get("upload_date") or "unknown")[:10] or "unknown"
    cues: list[tuple[float, float, str]] = []
    try:
        body, _ct, _final = net.http_get(f"https://player.vimeo.com/video/{vid}/config")
        cfg = json.loads(body.decode("utf-8", errors="replace"))
        tracks = (cfg.get("request") or {}).get("text_tracks") or []
        track = next(
            (t for t in tracks if str(t.get("lang", "")).lower().startswith("en")),
            tracks[0] if tracks else None,
        )
        if track and track.get("url"):
            vtt, _ct, _final = net.http_get(urljoin("https://player.vimeo.com", track["url"]))
            cues = _parse_vtt(vtt.decode("utf-8", errors="replace"))
    except (FetchError, ValueError, AttributeError):
        cues = []
    return _video_doc(url, title, author, date_authored, cues)
