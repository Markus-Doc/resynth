"""dig: niche search, obscurity scoring and registration, all offline."""

import json

import pytest

from resynth import config, dig
from resynth.fsutil import iter_jsonl
from resynth.intake import load_sources
from resynth.project import run_brief, run_init
from resynth.resolve.net import FetchError


def page(url):
    return {"body_markdown": f"# Page\n\nText fetched from {url} for the dig tests.\n",
            "title": url, "source_type": "html-article", "url": url, "origin": url,
            "author_or_tool": "test", "date_authored": "unknown", "transcript_status": None}


@pytest.fixture
def engines(monkeypatch):
    results = {
        "hn": [{"url": "https://tiny.blog/post", "title": "Tiny intraday", "snippet": ""},
               {"url": "https://www.forbes.com/big", "title": "Big tiny intraday", "snippet": ""}],
        "marginalia": [{"url": "https://tiny.blog/post/", "title": "Tiny intraday", "snippet": ""}],
        "openalex": [{"url": f"https://papers.test/{i}.pdf", "title": f"P{i} intraday", "snippet": ""}
                     for i in range(8)],
        "stackexchange": [],
        "github": [{"url": "https://github.com/a/b", "title": "a/b intraday", "snippet": ""}],
    }

    def make(name):
        def search(_query):
            if name == "stackexchange":
                raise FetchError("http 403 Forbidden")
            return [dict(h) for h in results[name]]
        return search

    monkeypatch.setattr(dig, "ENGINES", {n: make(n) for n in results})
    monkeypatch.setattr(dig, "fetch_url", page)
    monkeypatch.setitem(dig._FETCHERS, "url", page)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    return results


def setup(mode="deep"):
    run_init("dg", mode=mode)
    run_brief("dg", "What intraday mean reversion edges still work for retail traders?")
    return config.project_dir("dg")


def test_queries_drop_padding_and_lead_with_names():
    assert dig.queries_for(
        "What goes wrong in practice when retail traders run crypto bots on Binance?") == [
        "binance retail traders crypto", "binance retail"]


def test_saved_queries_win(ws, engines):
    pdir = setup()
    (pdir / "prompts" / dig.QUERIES_FILE).write_text("# mine\nbinance api limits\n", encoding="utf-8")
    result = dig.run_dig("dg", limit=1, dry_run=True)
    assert result["messages"][0] == "searched for: binance api limits"


def test_irrelevant_hits_dropped():
    assert dig._relevant({"title": "Binance rate limits", "snippet": ""}, "binance api")
    assert not dig._relevant({"title": "Perl error handling", "snippet": ""}, "binance api")


def test_agreement_and_small_sites_rank_first(ws, engines):
    ranked, notes = dig.collect(["tiny"])
    assert ranked[0]["url"] == "https://tiny.blog/post"
    assert ranked[0]["engine"] == "hn+marginalia"
    big = next(r for r in ranked if "forbes" in r["url"])
    assert big["score"] < ranked[0]["score"] - 1
    assert notes == ["stackexchange, 'tiny': http 403 Forbidden"]


def test_page_one_hits_are_pushed_down(ws, engines, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    calls = []

    def brave(query, offset, key):
        calls.append(offset)
        return [{"url": "https://tiny.blog/post", "title": "Tiny intraday", "snippet": ""}] if offset == 0 else []

    monkeypatch.setattr(dig, "_brave", brave)
    ranked, _ = dig.collect(["tiny"])
    assert sorted(calls) == [0, 2, 3]
    assert ranked[0]["url"] != "https://tiny.blog/post"


def test_dig_registers_sources_with_engine_share_cap(ws, engines):
    pdir = setup()
    result = dig.run_dig("dg", limit=5)
    assert result["ok"] and result["counts"]["fetched"] == 5
    found = [fm["author_or_tool"] for fm in load_sources(pdir)]
    assert found.count("dig via openalex") == 3
    records = [o for _n, _r, o, _e in iter_jsonl(dig.manifest_path(pdir)) if o]
    assert {r["status"] for r in records} == {"fetched", "not_taken"}
    again = dig.run_dig("dg", limit=5)
    assert all(e["source_id"] not in {fm["source_id"] for fm in load_sources(pdir)[:5]}
               for e in again["events"])


def test_light_dig_stops_at_cap(ws, engines, monkeypatch):
    pdir = setup("light")
    monkeypatch.setattr(config, "LIGHT_SOURCE_CAP", 2)
    dig.run_dig("dg")
    assert len(load_sources(pdir)) == 2
    assert dig.run_dig("dg")["messages"] == ["source cap reached, dig fetched nothing"]


def test_dry_run_writes_nothing(ws, engines):
    pdir = setup()
    result = dig.run_dig("dg", limit=3, dry_run=True)
    assert result["counts"]["fetched"] == 3
    assert not load_sources(pdir) and not dig.manifest_path(pdir).exists()


def test_blocked_hosts_dropped():
    assert dig._hit("https://papers.ssrn.com/sol3/x.pdf", "x") is None


def test_stackexchange_read_through_api(monkeypatch):
    replies = {
        "https://api.stackexchange.com/2.3/questions/42?site=quant&filter=withbody":
            {"items": [{"title": "Gap risk?", "body": "<p>How do gaps affect a z-score?</p>",
                        "creation_date": 1716695680}]},
        "https://api.stackexchange.com/2.3/questions/42/answers?site=quant&filter=withbody&sort=votes&pagesize=5":
            {"items": [{"is_accepted": True, "score": 7, "body": "<p>Use returns, not prices.</p>"}]},
    }
    monkeypatch.setattr(dig, "_json", lambda url, headers=None: replies[url])
    doc = dig.fetch_stackexchange("https://quant.stackexchange.com/questions/42/gap-risk")
    assert doc["title"] == "Gap risk?"
    assert "## Accepted answer, score 7" in doc["body_markdown"]
    assert "Use returns, not prices." in doc["body_markdown"]
    assert json.dumps(doc)
