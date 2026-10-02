"""Polite page fetching: robots.txt, 10 s timeout, 2 MB cap, cached via HttpClient.

Page HTML lives only in the local cache (gitignored). What is committed is the
``Page`` record (hash, status, title, <= 300-char excerpt) plus derived signals.

Adapted from Zero Hour (robots handling and text extraction kept as-is; Wayback
and publication-date logic dropped). Every fetch yields a ``Page`` record; a page
that cannot be fetched carries an explicit ``unscored_reason`` and is never
scored by guesswork.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from slopwatch.cache import CacheMiss
from slopwatch.http import HttpClient, HttpError, ResponseTooLarge
from slopwatch.models import EXCERPT_MAX_CHARS, Page, UnscoredReason

log = logging.getLogger(__name__)

ROBOTS_AGENT = "slopwatch"
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "en-IN,en;q=0.9",
}
MAX_TEXT_CHARS = 400_000
_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template", "iframe", "head"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "section",
        "article",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "blockquote",
        "header",
        "footer",
        "main",
        "dt",
        "dd",
    }
)
_CELL_TAGS = frozenset({"td", "th"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in _CELL_TAGS:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """``(title, visible text)`` with scripts, styles and <head> removed."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()[:MAX_TEXT_CHARS]
    return " ".join(parser.title.split()), text


def make_excerpt(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    """At most ``limit`` chars of whitespace-collapsed text, cut at a word boundary."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


@dataclass(frozen=True)
class FetchResult:
    page: Page
    # Raw HTML for signal extraction; None when the page is unscored.
    html: str | None = None


def _unscored(url: str, reason: UnscoredReason, status: int | None = None) -> FetchResult:
    return FetchResult(
        Page(
            url=url,
            status=status,
            fetched_at=None,
            robots_blocked=reason == "robots_blocked",
            unscored_reason=reason,
        )
    )


class PageFetcher:
    def __init__(self, http: HttpClient, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.http = http
        self.max_bytes = max_bytes
        self._robots: dict[str, RobotFileParser | None] = {}

    def robots_verdict(self, url: str) -> UnscoredReason | None:
        """None if fetching is allowed, otherwise why not."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            try:
                resp = self.http.get(f"{origin}/robots.txt", max_bytes=512_000)
            except (HttpError, CacheMiss):
                resp = None
            if resp is None or resp.status >= 500:
                # unreachable robots.txt: be conservative and do not fetch
                self._robots[origin] = None
            else:
                parser = RobotFileParser()
                # 4xx means no robots.txt: everything is allowed
                parser.parse([] if resp.status >= 400 else resp.text.splitlines())
                self._robots[origin] = parser
        robots = self._robots[origin]
        if robots is None:
            return "robots_unavailable"
        return None if robots.can_fetch(ROBOTS_AGENT, url) else "robots_blocked"

    def fetch(self, url: str) -> FetchResult:
        verdict = self.robots_verdict(url)
        if verdict is not None:
            log.info("robots: %s for %s", verdict, url)
            return _unscored(url, verdict)
        try:
            resp = self.http.get(url, headers=PAGE_HEADERS, max_bytes=self.max_bytes)
        except ResponseTooLarge:
            return _unscored(url, "too_large")
        except CacheMiss:
            return _unscored(url, "not_recorded")
        except HttpError as exc:
            log.info("page fetch failed %s: %s", url, exc)
            return _unscored(url, "fetch_failed", exc.status)
        if resp.status >= 400:
            return _unscored(url, "http_error", resp.status)
        ctype = resp.headers.get("content-type", "text/html").lower()
        if "html" not in ctype:
            return _unscored(url, "not_html", resp.status)
        html = resp.text
        title, text = html_to_text(html)
        page = Page(
            url=url,
            status=resp.status,
            fetched_at=resp.fetched_at.astimezone(UTC),
            title=title[:200],
            excerpt=make_excerpt(text),
            text_len=len(text),
            html_hash=hashlib.sha256(resp.body).hexdigest(),
        )
        return FetchResult(page, html)
