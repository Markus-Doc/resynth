import io
import shutil
import urllib.error
from pathlib import Path
from urllib.parse import quote

import pytest

from helpers import snapshot

from resynth import config
from resynth.errors import ResynthError
from resynth.fsutil import iter_jsonl, parse_frontmatter, sha256_text
from resynth.intake import run_intake
from resynth.project import run_init
from resynth.resolve import manifest_path, preview_targets, run_resolve
from resynth.resolve import net
from resynth.resolve.discover import discover_targets
from resynth.resolve.fetchers import (
    classify_target,
    fetch_local,
    fetch_url,
    fetch_vimeo,
    fetch_youtube,
)
from resynth.resolve.net import FetchError
from resynth.resolve.reduce_html import extract_title, reduce_html

FIX = Path(__file__).parent / "fixtures" / "resolve"

ARTICLE_URL = "https://example-articles.test/guide"
COPY_URL = "https://example-articles.test/guide-copy"
VIMEO_URL = "https://vimeo.com/123456"
YT_URL = "https://www.youtube.com/watch?v=abc123XYZ"
BLOCKED_URL = "https://blocked.test/secret"

YT_OEMBED = f"https://www.youtube.com/oembed?url={quote(YT_URL, safe='')}&format=json"
YT_LIST = "https://www.youtube.com/api/timedtext?type=list&v=abc123XYZ"
YT_TRACK = "https://www.youtube.com/api/timedtext?lang=en&v=abc123XYZ"
VIMEO_OEMBED = f"https://vimeo.com/api/oembed.json?url={quote(VIMEO_URL, safe='')}"
VIMEO_CONFIG = "https://player.vimeo.com/video/123456/config"
VIMEO_VTT = "https://player.vimeo.com/texttrack/123.vtt?token=x"


class _Headers:
    def __init__(self, ctype):
        self.ctype = ctype

    def get(self, name, default=None):
        return self.ctype if name.lower() == "content-type" else default


class _Resp:
    def __init__(self, url, status, ctype, body):
        self.url = url
        self.status = status
        self.headers = _Headers(ctype)
        self._body = body

    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNet:
    """Maps url -> (status, content_type, bytes); unmapped urls assert."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, req, timeout=None, **kwargs):
        url = getattr(req, "full_url", req)
        self.calls.append(url)
        assert url in self.mapping, f"unmapped url: {url}"
        status, ctype, body = self.mapping[url]
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "error", None, io.BytesIO(b""))
        return _Resp(url, status, ctype, body)


def robots_404(host):
    return (f"https://{host}/robots.txt", (404, "text/plain", b""))


def base_mapping():
    return dict(
        [
            robots_404("example-articles.test"),
            robots_404("www.youtube.com"),
            robots_404("vimeo.com"),
            robots_404("player.vimeo.com"),
            (
                "https://blocked.test/robots.txt",
                (200, "text/plain", (FIX / "robots_disallow.txt").read_bytes()),
            ),
            (ARTICLE_URL, (200, "text/html; charset=utf-8", (FIX / "article.html").read_bytes())),
            (COPY_URL, (200, "text/html; charset=utf-8", (FIX / "article.html").read_bytes())),
            (YT_OEMBED, (200, "application/json", (FIX / "youtube_oembed.json").read_bytes())),
            (YT_LIST, (200, "text/xml", b"<transcript_list></transcript_list>")),
            (VIMEO_OEMBED, (200, "application/json", (FIX / "vimeo_oembed.json").read_bytes())),
            (VIMEO_CONFIG, (404, "application/json", b"")),
        ]
    )


def use_net(monkeypatch, mapping):
    fake = FakeNet(mapping)
    monkeypatch.setattr(net, "urlopen", fake)
    return fake


@pytest.fixture(autouse=True)
def _clean_net(monkeypatch):
    monkeypatch.setattr(net, "_robots", {})
    monkeypatch.setattr(net, "_last_hit", {})
    monkeypatch.setattr(net, "sleep", lambda _s: None)


def make_links_project(ws):
    srcdir = ws / "incoming"
    srcdir.mkdir()
    notes = srcdir / "notes-with-links.md"
    shutil.copy(FIX / "notes-with-links.md", notes)
    (srcdir / "extra-notes.md").write_text(
        "# Extra notes\n\nLocal supporting notes for the resolve test suite.\n",
        encoding="utf-8",
    )
    run_init("links")
    run_intake("links", [str(notes)])
    return config.project_dir("links")


def local_target(ws):
    return str((ws / "incoming" / "extra-notes.md").resolve())


def load_manifest(pdir):
    return {
        rec["target"]: rec for _n, _raw, rec, _err in iter_jsonl(manifest_path(pdir)) if rec
    }


# --- classify ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("https://www.youtube.com/watch?v=abc", "youtube"),
        ("https://youtu.be/abc", "youtube"),
        ("https://m.youtube.com/shorts/abc", "youtube"),
        ("https://vimeo.com/123456", "vimeo"),
        ("https://player.vimeo.com/video/123456", "vimeo"),
        ("https://example.com/page", "url"),
        ("http://example.com/page.pdf", "url"),
    ],
)
def test_classify_target_urls(raw, kind):
    assert classify_target(raw) == kind


def test_classify_target_local(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("x", encoding="utf-8")
    assert classify_target(str(f)) == "local"
    assert classify_target(str(tmp_path / "missing.md")) == "url"


# --- reducer ----------------------------------------------------------------


def test_reduce_html_main_only_and_block_forms():
    html = (FIX / "article.html").read_text(encoding="utf-8")
    body, title = reduce_html(html, ARTICLE_URL)
    assert title == "Field Guide to Widgets"
    assert "# Field Guide to Widgets" in body
    assert "## Setup" in body
    assert "- First step: inventory existing widgets" in body
    assert "> Quoted wisdom about widgets from the maintainers." in body
    assert "```\nwidgetctl install --all\n```" in body
    assert "Name | Status" in body
    assert "Alpha | stable" in body
    assert "the spec (https://example-articles.test/spec.html)" in body
    assert "manual (https://example-articles.test/manual)" in body
    for noise in (
        "Site navigation",
        "Site header",
        "Footer copyright",
        "Related links",
        "scriptVar",
        "Outside main",
    ):
        assert noise not in body


def test_extract_title_precedence():
    og = (
        '<html><head><meta property="og:title" content="OG Title">'
        "<title>Doc Title</title></head><body><h1>H1 Title</h1></body></html>"
    )
    assert extract_title(og) == "OG Title"
    titled = "<html><head><title>Doc Title</title></head><body><h1>H1 Title</h1></body></html>"
    assert extract_title(titled) == "Doc Title"
    assert extract_title("<html><body><h1>H1 Title</h1></body></html>") == "H1 Title"
    assert extract_title("<html><body><p>nothing</p></body></html>") is None


# --- net --------------------------------------------------------------------


def test_robots_disallow_blocks_fetch(monkeypatch):
    use_net(
        monkeypatch,
        dict([("https://blocked.test/robots.txt", (200, "text/plain", (FIX / "robots_disallow.txt").read_bytes()))]),
    )
    with pytest.raises(FetchError, match="robots"):
        net.http_get(BLOCKED_URL)


def test_size_cap(monkeypatch):
    big = b"x" * (net.MAX_BYTES + 1)
    use_net(
        monkeypatch,
        dict([robots_404("big.test"), ("https://big.test/file", (200, "text/html", big))]),
    )
    with pytest.raises(FetchError, match="10 MiB"):
        net.http_get("https://big.test/file")


def test_rate_limit_sleeps_between_same_host_requests(monkeypatch):
    use_net(
        monkeypatch,
        dict(
            [
                robots_404("rate.test"),
                robots_404("other.test"),
                ("https://rate.test/a", (200, "text/plain", b"a")),
                ("https://rate.test/b", (200, "text/plain", b"b")),
                ("https://other.test/c", (200, "text/plain", b"c")),
            ]
        ),
    )
    naps = []
    monkeypatch.setattr(net, "sleep", naps.append)
    net.http_get("https://rate.test/a")
    net.http_get("https://rate.test/b")
    assert len(naps) == 1
    assert 0 < naps[0] <= net.HOST_DELAY
    net.http_get("https://other.test/c")
    assert len(naps) == 1


# --- fetchers ---------------------------------------------------------------


def test_fetch_local(tmp_path):
    f = tmp_path / "extra.md"
    f.write_text("# Local Title\n\nBody text.\n", encoding="utf-8")
    doc = fetch_local(str(f))
    assert doc["title"] == "Local Title"
    assert doc["source_type"] == "notes"
    assert doc["url"] is None
    assert doc["origin"] == str(f)
    assert doc["transcript_status"] is None
    assert "Body text." in doc["body_markdown"]
    plain = tmp_path / "plain.txt"
    plain.write_text("no heading here\n", encoding="utf-8")
    assert fetch_local(str(plain))["title"] == "plain"


def test_fetch_url_article(monkeypatch):
    use_net(monkeypatch, base_mapping())
    doc = fetch_url(ARTICLE_URL)
    assert doc["source_type"] == "html-article"
    assert doc["title"] == "Field Guide to Widgets"
    assert doc["url"] == ARTICLE_URL
    assert doc["origin"] == ARTICLE_URL
    assert "# Field Guide to Widgets" in doc["body_markdown"]


def test_fetch_url_no_extractable_text(monkeypatch):
    tiny = b"<html><body><main><p>too short</p></main></body></html>"
    use_net(
        monkeypatch,
        dict([robots_404("tiny.test"), ("https://tiny.test/p", (200, "text/html", tiny))]),
    )
    with pytest.raises(FetchError, match="no extractable text"):
        fetch_url("https://tiny.test/p")


def test_fetch_url_unsupported_content_type(monkeypatch):
    use_net(
        monkeypatch,
        dict([robots_404("img.test"), ("https://img.test/x", (200, "image/png", b"\x89PNG"))]),
    )
    with pytest.raises(FetchError, match="unsupported content type"):
        fetch_url("https://img.test/x")


def test_fetch_youtube_happy_path(monkeypatch):
    mapping = base_mapping()
    mapping[YT_LIST] = (200, "text/xml", (FIX / "youtube_timedtext_list.xml").read_bytes())
    mapping[YT_TRACK] = (200, "text/xml", (FIX / "youtube_timedtext_en.xml").read_bytes())
    use_net(monkeypatch, mapping)
    doc = fetch_youtube(YT_URL)
    assert doc["transcript_status"] == "fetched"
    assert doc["source_type"] == "video-transcript"
    assert doc["title"] == "Deep Dive Video"
    assert doc["author_or_tool"] == "Chan Academy"
    body = doc["body_markdown"]
    assert body.startswith("# Deep Dive Video\n\n## Transcript\n")
    assert "[00:00:00] Welcome to the deep dive." in body
    assert "[00:00:04] Today we cover widgets & gadgets." in body
    # gap over 8 seconds starts a new paragraph
    assert "gadgets.\n\n[00:00:20] After a long pause we resume." in body


def test_fetch_youtube_no_captions_yields_pending_stub(monkeypatch):
    use_net(monkeypatch, base_mapping())
    doc = fetch_youtube(YT_URL)
    assert doc["transcript_status"] == "pending"
    assert doc["title"] == "Deep Dive Video"
    body = doc["body_markdown"]
    assert body.startswith("# Deep Dive Video\n")
    assert "> [!info] Video transcript pending" in body
    assert f"> Link: {YT_URL}" in body


def test_fetch_vimeo_happy_path(monkeypatch):
    mapping = base_mapping()
    mapping[VIMEO_CONFIG] = (200, "application/json", (FIX / "vimeo_config.json").read_bytes())
    mapping[VIMEO_VTT] = (200, "text/vtt", (FIX / "vimeo_track.vtt").read_bytes())
    use_net(monkeypatch, mapping)
    doc = fetch_vimeo(VIMEO_URL)
    assert doc["transcript_status"] == "fetched"
    assert doc["title"] == "Vimeo Talk"
    assert doc["author_or_tool"] == "Speaker Person"
    assert doc["date_authored"] == "2024-05-01"
    body = doc["body_markdown"]
    assert "[00:00:00] Welcome to the talk." in body
    assert "[00:00:04] We discuss widgets at length." in body
    assert "length.\n\n[00:00:20] Closing remarks after a pause." in body


def test_fetch_vimeo_no_captions_yields_pending_stub(monkeypatch):
    use_net(monkeypatch, base_mapping())
    doc = fetch_vimeo(VIMEO_URL)
    assert doc["transcript_status"] == "pending"
    assert "> [!info] Video transcript pending" in doc["body_markdown"]
    assert f"> Link: {VIMEO_URL}" in doc["body_markdown"]


# --- discovery --------------------------------------------------------------


def test_discover_targets_urls_and_punctuation():
    body = (
        "see https://example.com/x, then <https://example.com/y> and\n"
        "[wiki](https://example.com/page_(1)) plus https://example.com/a#frag.\n"
        "repeat https://example.com/x once more\n"
    )
    raws = [t["raw"] for t in discover_targets(body, "")]
    assert raws == [
        "https://example.com/x",
        "https://example.com/y",
        "https://example.com/page_(1)",
        "https://example.com/a#frag",
    ]


def test_discover_targets_local_paths(tmp_path):
    extra = tmp_path / "extra.md"
    extra.write_text("x", encoding="utf-8")
    origin = str(tmp_path / "notes.md")
    body = f"see [extra](extra.md) and `missing.md` and `{extra}`\nplain extra.md mention\n"
    targets = discover_targets(body, origin)
    assert targets == [{"raw": str(extra.resolve()), "kind": "local"}]


def test_preview_targets(ws, monkeypatch):
    pdir = make_links_project(ws)
    targets = preview_targets("links")
    assert [t["raw"] for t in targets] == [
        ARTICLE_URL,
        COPY_URL,
        VIMEO_URL,
        YT_URL,
        BLOCKED_URL,
        local_target(ws),
    ]
    assert [t["kind"] for t in targets] == ["url", "url", "vimeo", "youtube", "url", "local"]
    assert all(t["parent"] == "S01" for t in targets)


# --- run_resolve ------------------------------------------------------------


def test_run_resolve_requires_project_and_sources(ws):
    with pytest.raises(ResynthError, match="not found"):
        run_resolve("nope")
    run_init("empty")
    with pytest.raises(ResynthError, match="no sources"):
        run_resolve("empty")


def test_run_resolve_unknown_source_id(ws):
    make_links_project(ws)
    with pytest.raises(ResynthError, match="unknown source"):
        run_resolve("links", source_ids=["S99"])


def test_run_resolve_integration(ws, monkeypatch):
    pdir = make_links_project(ws)
    use_net(monkeypatch, base_mapping())
    result = run_resolve("links")
    assert result["ok"] is True
    assert result["gate"]["status"] == "PASS"
    assert result["counts"] == {
        "fetched": 2,
        "cached": 0,
        "duplicate": 1,
        "transcript_pending": 2,
        "failed": 1,
    }
    files = sorted(f.name for f in (pdir / "sources").glob("S*.md"))
    assert len(files) == 5

    article = next((pdir / "sources").glob("S02-*.md"))
    fm, body = parse_frontmatter(article.read_text(encoding="utf-8"), article.name)
    assert fm["schema_version"] == 2
    assert fm["source_type"] == "html-article"
    assert fm["url"] == ARTICLE_URL
    assert fm["resolved_from"] == "S01"
    assert fm["sha256"] == sha256_text(body)
    assert "transcript_status" not in fm

    vimeo = next((pdir / "sources").glob("S03-*.md"))
    fm_v, body_v = parse_frontmatter(vimeo.read_text(encoding="utf-8"), vimeo.name)
    assert fm_v["source_type"] == "video-transcript"
    assert fm_v["transcript_status"] == "pending"
    assert "> [!info] Video transcript pending" in body_v

    local = next((pdir / "sources").glob("S05-*.md"))
    fm_l, _body_l = parse_frontmatter(local.read_text(encoding="utf-8"), local.name)
    assert fm_l["source_type"] == "notes"
    assert fm_l["url"] is None
    assert fm_l["resolved_from"] == "S01"

    recs = load_manifest(pdir)
    assert manifest_path(pdir).read_text(encoding="utf-8").startswith("#")
    assert len(recs) == 6
    assert recs[ARTICLE_URL]["status"] == "fetched"
    assert recs[ARTICLE_URL]["source_id"] == "S02"
    assert recs[COPY_URL] == {**recs[COPY_URL], "status": "duplicate", "source_id": "S02"}
    assert recs[VIMEO_URL]["status"] == "transcript_pending"
    assert recs[YT_URL]["status"] == "transcript_pending"
    assert recs[BLOCKED_URL]["status"] == "failed"
    assert recs[BLOCKED_URL]["note"] == "disallowed by robots.txt"
    assert recs[BLOCKED_URL]["source_id"] is None
    assert recs[local_target(ws)]["status"] == "fetched"
    assert all(r["resolved_from"] == "S01" for r in recs.values())

    msgs = result["messages"]
    assert f"{ARTICLE_URL}: fetched as S02 (html-article)" in msgs
    assert f"{COPY_URL}: duplicate of S02" in msgs
    assert f"{VIMEO_URL}: transcript pending, stub created as S03" in msgs
    assert f"{YT_URL}: transcript pending, stub created as S04" in msgs
    assert f"{BLOCKED_URL}: failed (disallowed by robots.txt)" in msgs
    assert f"{local_target(ws)}: fetched as S05 (notes)" in msgs
    assert msgs[-1] == "gate 01-intake: PASS"


def test_run_resolve_second_run_is_idempotent(ws, monkeypatch):
    make_links_project(ws)
    use_net(monkeypatch, base_mapping())
    run_resolve("links")
    before = snapshot(ws)
    result = run_resolve("links")
    assert snapshot(ws) == before
    # fetched and duplicate targets are cached; pending and failed retry
    assert result["counts"] == {
        "fetched": 0,
        "cached": 3,
        "duplicate": 0,
        "transcript_pending": 2,
        "failed": 1,
    }
    msgs = result["messages"]
    assert f"{ARTICLE_URL}: cached (S02)" in msgs
    assert f"{COPY_URL}: cached (S02)" in msgs
    assert f"{local_target(ws)}: cached (S05)" in msgs


def test_transcript_upgrade_in_place(ws, monkeypatch):
    pdir = make_links_project(ws)
    fake = use_net(monkeypatch, base_mapping())
    run_resolve("links")
    stub = next((pdir / "sources").glob("S03-*.md"))
    fm_before, _ = parse_frontmatter(stub.read_text(encoding="utf-8"), stub.name)
    fake.mapping[VIMEO_CONFIG] = (
        200,
        "application/json",
        (FIX / "vimeo_config.json").read_bytes(),
    )
    fake.mapping[VIMEO_VTT] = (200, "text/vtt", (FIX / "vimeo_track.vtt").read_bytes())
    result = run_resolve("links")
    assert result["counts"]["fetched"] == 1
    assert result["counts"]["cached"] == 3
    assert result["counts"]["transcript_pending"] == 1
    assert f"{VIMEO_URL}: fetched as S03 (video-transcript)" in result["messages"]

    upgraded = next((pdir / "sources").glob("S03-*.md"))
    assert upgraded.name == stub.name
    fm, body = parse_frontmatter(upgraded.read_text(encoding="utf-8"), upgraded.name)
    assert fm["source_id"] == "S03"
    assert fm["transcript_status"] == "fetched"
    assert fm["sha256"] == sha256_text(body)
    assert fm["recency_rank"] == fm_before["recency_rank"]
    assert fm["date_ingested"] == fm_before["date_ingested"]
    assert fm["resolved_from"] == "S01"
    assert "## Transcript" in body
    assert "[00:00:00] Welcome to the talk." in body
    recs = load_manifest(pdir)
    assert recs[VIMEO_URL]["status"] == "fetched"
    assert recs[VIMEO_URL]["source_id"] == "S03"
    assert len(list((pdir / "sources").glob("S*.md"))) == 5


def test_run_resolve_dry_run_writes_nothing(ws, monkeypatch):
    pdir = make_links_project(ws)
    fake = use_net(monkeypatch, {})
    before = snapshot(ws)
    result = run_resolve("links", dry_run=True)
    assert snapshot(ws) == before
    assert fake.calls == []
    assert not manifest_path(pdir).exists()
    would = [m for m in result["messages"] if "would fetch" in m]
    assert len(would) == 6
    assert f"{VIMEO_URL}: would fetch (vimeo)" in result["messages"]
    assert f"{YT_URL}: would fetch (youtube)" in result["messages"]
    assert f"{local_target(ws)}: would fetch (local)" in result["messages"]


def test_run_resolve_only_filter(ws, monkeypatch):
    pdir = make_links_project(ws)
    use_net(monkeypatch, base_mapping())
    result = run_resolve("links", only="vimeo")
    assert result["counts"] == {
        "fetched": 0,
        "cached": 0,
        "duplicate": 0,
        "transcript_pending": 1,
        "failed": 0,
    }
    recs = load_manifest(pdir)
    assert list(recs) == [VIMEO_URL]
