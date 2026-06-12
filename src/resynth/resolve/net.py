"""HTTP access for source resolution.

Every request goes through this module's `urlopen` attribute so tests can
patch a single seam. Robots.txt is honoured and requests to one host are
rate limited.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .. import __version__

urlopen = urllib.request.urlopen
monotonic = time.monotonic
sleep = time.sleep

USER_AGENT = (
    f"resynth/{__version__} (+https://github.com/Markus-Doc/resynth) "
    "research consolidation tool"
)
TIMEOUT = 30
MAX_BYTES = 10 * 1024 * 1024
HOST_DELAY = 1.0

_robots: dict[str, RobotFileParser | None] = {}
_last_hit: dict[str, float] = {}

_CHARSET_RE = re.compile(r"charset=[\"']?([\w.:-]+)", re.IGNORECASE)


class FetchError(Exception):
    """A target could not be fetched. str(err) is the short reason."""


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def _robot_parser(base: str) -> RobotFileParser | None:
    if base in _robots:
        return _robots[base]
    parser: RobotFileParser | None
    try:
        with urlopen(_request(base + "/robots.txt"), timeout=TIMEOUT) as resp:
            raw = resp.read(MAX_BYTES)
        parser = RobotFileParser()
        parser.parse(raw.decode("utf-8", errors="replace").splitlines())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        parser = None
    _robots[base] = parser
    return parser


def _check_robots(url: str) -> None:
    parts = urlsplit(url)
    parser = _robot_parser(f"{parts.scheme}://{parts.netloc}")
    if parser is not None and not parser.can_fetch(USER_AGENT, url):
        raise FetchError("disallowed by robots.txt")


def _throttle(host: str) -> None:
    last = _last_hit.get(host)
    if last is not None:
        wait = HOST_DELAY - (monotonic() - last)
        if wait > 0:
            sleep(wait)
    _last_hit[host] = monotonic()


def http_get(url: str) -> tuple[bytes, str, str]:
    """GET a url, returning (body, content-type header, final url)."""
    _check_robots(url)
    _throttle(urlsplit(url).netloc.lower())
    try:
        with urlopen(_request(url), timeout=TIMEOUT) as resp:
            body = resp.read(MAX_BYTES + 1)
            content_type = resp.headers.get("Content-Type") or ""
            final_url = getattr(resp, "url", None) or resp.geturl()
    except urllib.error.HTTPError as err:
        raise FetchError(f"http {err.code} {err.reason}") from err
    except urllib.error.URLError as err:
        raise FetchError(f"unreachable: {err.reason}") from err
    except (TimeoutError, OSError) as err:
        raise FetchError(str(err) or err.__class__.__name__) from err
    if len(body) > MAX_BYTES:
        raise FetchError("response exceeds 10 MiB")
    return body, content_type, final_url


def decode(body: bytes, content_type: str) -> str:
    match = _CHARSET_RE.search(content_type or "")
    if not match:
        match = _CHARSET_RE.search(body[:2048].decode("ascii", errors="ignore"))
    if match:
        try:
            return body.decode(match.group(1), errors="replace")
        except LookupError:
            pass
    return body.decode("utf-8", errors="replace")
