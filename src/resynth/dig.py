"""Niche source discovery, a stage 1 verb like resolve.

dig searches places the big engines bury: Hacker News, the Marginalia small
web index, open access papers on OpenAlex, Stack Exchange answers and GitHub
projects. With a Brave Search key it also reads pages three and four of a
mainstream engine and pushes down anything that ranks on page one. Results
are scored for how unusual they are, and the best are fetched and registered
as sources. Every candidate, kept or not, is recorded in index/dig.jsonl with
the engine, query and rank that found it.

No key is needed. Optional keys come from environment variables:
BRAVE_API_KEY, MARGINALIA_API_KEY, OPENALEX_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit

from . import config, intake
from .errors import ResynthError
from .fsutil import iter_jsonl, safe_write
from .project import brief_topic
from .resolve import net
from .resolve.fetchers import _doc, classify_target, fetch_url, fetch_vimeo, fetch_youtube
from .resolve.net import FetchError
from .resolve.reduce_html import reduce_html

MANIFEST = "dig.jsonl"
PER_ENGINE = 10
DEFAULT_LIMIT = 20
SHARE_NUM, SHARE_DEN = 2, 5
STACK_SITES = ("stackoverflow", "stats", "quant", "money")
# Hosts that refuse automated fetches, dropped before they use up a pick.
BLOCKED = ("ssrn.com", "doi.org/10.2139/ssrn")
_SE_RE = re.compile(r"^https?://([a-z.]+)/questions/(\d+)")

# How far off the beaten track each engine sits. Higher means less likely
# to be in a mainstream top five.
ENGINE_WEIGHT = {
    "marginalia": 3.0,
    "hn": 2.5,
    "brave-deep": 2.5,
    "openalex": 2.0,
    "stackexchange": 2.0,
    "github": 1.5,
}
BIG_SITES = {
    "wikipedia.org", "medium.com", "forbes.com", "investopedia.com", "nerdwallet.com",
    "youtube.com", "reddit.com", "linkedin.com", "quora.com", "cnbc.com", "bloomberg.com",
    "reuters.com", "nytimes.com", "amazon.com", "facebook.com", "x.com", "twitter.com",
    "businessinsider.com", "techcrunch.com", "theverge.com", "wsj.com", "ft.com",
}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "best", "by", "can", "do", "does", "for",
    "from", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or", "should", "that",
    "the", "their", "there", "this", "to", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
    # Question padding that says nothing about the subject.
    "about", "actually", "between", "big", "covering", "get", "goes", "good", "happen",
    "happens", "including", "into", "large", "less", "more", "most", "new", "practical",
    "practice", "really", "run", "running", "small", "still", "them", "these", "they",
    "things", "those", "using", "use", "work", "works", "wrong",
}
QUERIES_FILE = "DIG-QUERIES.txt"
_HEADER = (
    "# RESYNTH dig manifest. One JSON object per line records a search hit:\n"
    "# where it was found, its obscurity score and whether it became a source.\n"
    "# Maintained by `resynth dig`."
)
_KEYS = ["url", "title", "engine", "query", "rank", "score", "status", "source_id", "note"]
_FETCHERS = {"youtube": fetch_youtube, "vimeo": fetch_vimeo, "url": fetch_url}


def manifest_path(pdir: Path) -> Path:
    return pdir / "index" / MANIFEST


def queries_for(topic: str) -> list[str]:
    """Fallback queries from the brief when no query file exists: names first
    (capitalised words past the first), then the remaining keywords, as a four
    word and a two word query, because several engines need every word."""
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.#-]*", topic)
    names = [t.lower() for i, t in enumerate(tokens) if i and t[0].isupper()]
    words = [t.lower() for t in tokens]
    ordered = []
    for w in names + words:
        if w not in STOPWORDS and len(w) > 2 and w not in ordered:
            ordered.append(w)
    out = []
    for n in (4, 2):
        q = " ".join(ordered[:n])
        if q and q not in out:
            out.append(q)
    return out


def saved_queries(pdir: Path) -> list[str]:
    """Queries in prompts/DIG-QUERIES.txt, one per line, # for comments. The
    guided mode has the AI write them, anyone can edit them."""
    path = pdir / "prompts" / QUERIES_FILE
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _relevant(hit: dict, query: str) -> bool:
    """A hit must share at least one query word in its title or snippet.
    Engines that match on body text alone return a lot of noise."""
    text = f"{hit['title']} {hit.get('snippet', '')}".lower()
    terms = [w for w in re.findall(r"[a-z0-9][a-z0-9+.#-]*", query.lower()) if w not in STOPWORDS]
    return not terms or any(t in text for t in terms)


def _json(url: str, headers: dict[str, str] | None = None) -> dict:
    body, content_type, _final = net.http_get(url, headers)
    try:
        return json.loads(net.decode(body, content_type))
    except ValueError as err:
        raise FetchError("search response was not JSON") from err


def _hit(url: str | None, title: str | None, snippet: str | None = "") -> dict | None:
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    if any(b in url.lower() for b in BLOCKED):
        return None
    return {"url": url, "title": (title or url).strip(), "snippet": (snippet or "").strip()}


def search_hn(query: str) -> list[dict]:
    data = _json(f"https://hn.algolia.com/api/v1/search?query={quote(query)}"
                 f"&tags=story&hitsPerPage={PER_ENGINE}")
    hits = []
    for h in data.get("hits", []):
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        hits.append(_hit(url, h.get("title"), h.get("story_text")))
    return hits


def search_marginalia(query: str) -> list[dict]:
    key = os.environ.get("MARGINALIA_API_KEY") or "public"
    data = _json(f"https://api2.marginalia-search.com/search?query={quote_plus(query)}"
                 f"&count={PER_ENGINE}", {"API-Key": key})
    return [_hit(r.get("url"), r.get("title"), r.get("description")) for r in data.get("results", [])]


def search_openalex(query: str) -> list[dict]:
    """Open access works only, so the hit can actually be fetched and read."""
    url = (f"https://api.openalex.org/works?search={quote(query)}&per-page={PER_ENGINE}"
           "&filter=is_oa:true&select=title,open_access,cited_by_count")
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        url += f"&api_key={quote(key)}"
    hits = []
    for w in _json(url).get("results", []):
        hit = _hit((w.get("open_access") or {}).get("oa_url"), w.get("title"))
        if hit:
            hit["cited"] = w.get("cited_by_count") or 0
        hits.append(hit)
    return hits


def search_stackexchange(query: str) -> list[dict]:
    hits = []
    for site in STACK_SITES:
        data = _json("https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance"
                     f"&q={quote(query)}&site={site}&pagesize=3&filter=default")
        hits.extend(_hit(i.get("link"), i.get("title")) for i in data.get("items", []))
    return hits


def search_github(query: str) -> list[dict]:
    data = _json(f"https://api.github.com/search/repositories?q={quote(query)}&per_page={PER_ENGINE}",
                 {"Accept": "application/vnd.github+json"})
    return [_hit(r.get("html_url"), r.get("full_name"), r.get("description")) for r in data.get("items", [])]


def _brave(query: str, offset: int, key: str) -> list[dict]:
    data = _json(f"https://api.search.brave.com/res/v1/web/search?q={quote(query)}"
                 f"&count=10&offset={offset}", {"X-Subscription-Token": key, "Accept": "application/json"})
    return [_hit(r.get("url"), r.get("title"), r.get("description"))
            for r in (data.get("web") or {}).get("results", [])]


def _se_site(host: str) -> str:
    return host.removesuffix(".stackexchange.com").removesuffix(".com")


def fetch_stackexchange(url: str) -> dict:
    """Stack Exchange refuses bots on its pages, so read the question and its
    top answers through the API instead."""
    m = _SE_RE.match(url)
    if not m:
        return fetch_url(url)
    site, qid = _se_site(m.group(1)), m.group(2)
    api = f"https://api.stackexchange.com/2.3/questions/{qid}"
    question = (_json(f"{api}?site={site}&filter=withbody").get("items") or [None])[0]
    if not question:
        raise FetchError("question not found")
    answers = _json(f"{api}/answers?site={site}&filter=withbody&sort=votes&pagesize=5").get("items", [])
    title = reduce_html(f"<p>{question.get('title', '')}</p>", url)[0].strip() or url
    parts = [f"# {title}", "", reduce_html(question.get("body", ""), url)[0].strip()]
    for a in answers:
        label = "accepted answer" if a.get("is_accepted") else "answer"
        parts += ["", f"## {label.capitalize()}, score {a.get('score', 0)}", "",
                  reduce_html(a.get("body", ""), url)[0].strip()]
    created = question.get("creation_date")
    when = date.fromtimestamp(created).isoformat() if created else "unknown"
    return _doc("\n".join(parts) + "\n", title, "html-article", url, url,
                author_or_tool="stack exchange", date_authored=when)


ENGINES = {
    "hn": search_hn,
    "marginalia": search_marginalia,
    "openalex": search_openalex,
    "stackexchange": search_stackexchange,
    "github": search_github,
}


def _domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _norm(url: str) -> str:
    parts = urlsplit(url)
    return f"{(parts.hostname or '').lower().removeprefix('www.')}{parts.path.rstrip('/')}?{parts.query}"


def score(hit: dict, engines: set[str], page_one: set[str]) -> float:
    """Obscurity score: the best engine that found it, plus a point for a
    PDF, a small site and each further engine that agrees, half a point for
    a paper others cite, minus three when the hit is on a mainstream page
    one, and a little for lower rank."""
    value = max(ENGINE_WEIGHT[e] for e in engines)
    value += len(engines) - 1
    if urlsplit(hit["url"]).path.lower().endswith(".pdf"):
        value += 1
    if engines & {"hn", "marginalia", "brave-deep"} and _domain(hit["url"]) not in BIG_SITES:
        value += 1
    if hit.get("cited", 0) >= 5:
        value += 0.5
    if _norm(hit["url"]) in page_one:
        value -= 3
    return round(value - 0.05 * hit["rank"], 2)


def collect(queries: list[str]) -> tuple[list[dict], list[str]]:
    """Search every engine with every query. Returns ranked candidates and
    one note per engine that failed, so a dead engine never stops a dig."""
    found: dict[str, dict] = {}
    notes: list[str] = []
    page_one: set[str] = set()
    engines = dict(ENGINES)
    brave_key = os.environ.get("BRAVE_API_KEY")
    if brave_key:
        engines["brave-deep"] = lambda q: _brave(q, 2, brave_key) + _brave(q, 3, brave_key)
    for query in queries:
        if brave_key:
            try:
                page_one |= {_norm(h["url"]) for h in _brave(query, 0, brave_key) if h}
            except FetchError as err:
                notes.append(f"brave page one, '{query}': {err}")
        for name, search in engines.items():
            try:
                hits = [h for h in search(query) if h and _relevant(h, query)]
                short = " ".join(query.split()[:3])
                if not hits and short != query:
                    hits = [h for h in search(short) if h and _relevant(h, short)]
            except FetchError as err:
                notes.append(f"{name}, '{query}': {err}")
                continue
            for rank, h in enumerate(hits, 1):
                key = _norm(h["url"])
                rec = found.setdefault(key, {**h, "engine": name, "query": query, "rank": rank,
                                             "_engines": set()})
                rec["_engines"].add(name)
    ranked = []
    for rec in found.values():
        rec["score"] = score(rec, rec["_engines"], page_one)
        rec["engine"] = "+".join(sorted(rec.pop("_engines")))
        ranked.append(rec)
    ranked.sort(key=lambda r: (-r["score"], r["url"]))
    return ranked, notes


def _load_manifest(pdir: Path) -> dict[str, dict]:
    path = manifest_path(pdir)
    out: dict[str, dict] = {}
    if path.is_file():
        for _n, _raw, obj, _err in iter_jsonl(path):
            if obj and obj.get("url"):
                out[obj["url"]] = obj
    return out


def run_dig(project: str, queries: list[str] | None = None, limit: int | None = None,
            dry_run: bool = False) -> dict:
    """Search the niche engines, fetch the most unusual hits and register
    them as sources. Light projects stop at their source cap. Re-evaluates
    gate 01-intake like resolve."""
    pdir = config.project_dir(project)
    queries = list(queries or []) or saved_queries(pdir) or queries_for(brief_topic(pdir))
    if not queries:
        raise ResynthError(f"dig needs a research question, run: resynth brief {project} --topic ...")
    sources = intake.load_sources(pdir)
    if limit is None:
        limit = DEFAULT_LIMIT
    if config.project_mode(pdir) == "light":
        limit = min(limit, config.LIGHT_SOURCE_CAP - len(sources))
    if limit <= 0:
        return {"ok": True, "counts": {"fetched": 0}, "events": [],
                "messages": ["source cap reached, dig fetched nothing"]}
    ranked, notes = collect(queries)
    prior = _load_manifest(pdir)
    counts = {"candidates": len(ranked), "fetched": 0, "failed": 0, "duplicate": 0}
    messages = ["searched for: " + " | ".join(queries)]
    messages += [f"engine skipped: {n}" for n in notes]
    events: list[dict] = []
    records: dict[str, dict] = dict(prior)
    # No engine may fill more than SHARE of the picks, so one prolific index
    # does not crowd out the odder finds.
    per_engine = max(3, -(-limit * SHARE_NUM // SHARE_DEN))
    taken: dict[str, int] = {}
    for rec in ranked:
        status = (prior.get(rec["url"]) or {}).get("status")
        if status in ("fetched", "duplicate"):
            continue
        lead = rec["engine"].split("+")[0]
        if counts["fetched"] >= limit or taken.get(lead, 0) >= per_engine:
            records.setdefault(rec["url"], {**rec, "status": "not_taken"})
            continue
        taken[lead] = taken.get(lead, 0) + 1
        if dry_run:
            counts["fetched"] += 1
            messages.append(f"{rec['score']:>5} {rec['engine']}: {rec['url']}")
            continue
        try:
            fetch = (fetch_stackexchange if _SE_RE.match(rec["url"])
                     else _FETCHERS.get(classify_target(rec["url"]), fetch_url))
            doc = fetch(rec["url"])
        except FetchError as err:
            taken[lead] -= 1
            counts["failed"] += 1
            records[rec["url"]] = {**rec, "status": "failed", "note": str(err)}
            continue
        result = intake.register_source(
            pdir, doc["body_markdown"], title=doc["title"], origin=doc["origin"],
            source_type=doc["source_type"], url=doc["url"],
            author_or_tool=f"dig via {rec['engine']}", date_authored=doc["date_authored"],
            transcript_status=doc["transcript_status"],
        )
        status = "duplicate" if result["action"] == "duplicate" else "fetched"
        counts[status] += 1
        records[rec["url"]] = {**rec, "status": status, "source_id": result["source_id"]}
        events.append({"target": rec["url"], "action": status, "source_id": result["source_id"]})
        messages.append(f"{rec['url']}: {status} as {result['source_id']} "
                        f"(score {rec['score']}, {rec['engine']})")
    if dry_run:
        return {"ok": True, "counts": counts, "events": events, "messages": messages}
    lines = [_HEADER] + [json.dumps({k: r.get(k) for k in _KEYS}, ensure_ascii=False)
                         for r in sorted(records.values(), key=lambda r: (-(r.get("score") or 0), r["url"]))]
    safe_write(manifest_path(pdir), "\n".join(lines) + "\n", pdir)
    gate = intake.check_intake_gate(pdir)
    messages.append(f"gate 01-intake: {gate['status']}")
    return {"ok": gate["status"] == "PASS", "gate": gate, "counts": counts,
            "events": events, "messages": messages}
