"""Parse a page once into the facts every signal extractor needs.

Uses only the standard-library HTML parser: deterministic, dependency-free and
tolerant of broken markup. Region tracking (article/main vs nav/header/footer/
aside) uses open-tag counters, which is robust to unclosed tags in practice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from slopwatch.domains import registrable_domain

_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template", "iframe", "head"})
_MAIN_TAGS = frozenset({"article", "main"})
_BOILER_TAGS = frozenset({"nav", "header", "footer", "aside"})
_BLOCK_TAGS = frozenset(
    {"p", "div", "li", "tr", "section", "article", "main", "br", "h1", "h2", "h3", "h4", "h5",
     "h6", "pre", "blockquote", "header", "footer", "nav", "aside", "dt", "dd", "td", "th"}
)  # fmt: skip
_HEADINGS = frozenset({"h1", "h2", "h3"})
_AUTHOR_CLASS = re.compile(r"(^|[\s_-])(author|byline|writer)([\s_-]|$)", re.IGNORECASE)
MAX_INLINE_SCRIPT_CHARS = 200_000


@dataclass(frozen=True)
class Link:
    href: str  # absolute
    host: str  # lowercased, no www.
    rel: frozenset[str]
    text: str


@dataclass
class ParsedPage:
    url: str
    title: str = ""
    links: list[Link] = field(default_factory=list)
    script_srcs: list[str] = field(default_factory=list)
    iframe_srcs: list[str] = field(default_factory=list)
    inline_scripts: str = ""
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    headings: list[tuple[str, str]] = field(default_factory=list)  # (tag, text)
    time_datetimes: list[str] = field(default_factory=list)
    itemprops: set[str] = field(default_factory=set)
    author_class_seen: bool = False
    text: str = ""  # all visible text
    main_text: str = ""  # visible text inside <article>/<main>
    boiler_text: str = ""  # visible text inside nav/header/footer/aside, outside main
    content_text: str = ""  # visible text outside nav/header/footer/aside (main + rest)

    @property
    def site(self) -> str:
        return registrable_domain(self.url)

    def outbound(self) -> list[Link]:
        """Unique-by-href links to other registrable domains (http/https only)."""
        seen: set[str] = set()
        out: list[Link] = []
        for link in self.links:
            if not link.href.startswith(("http://", "https://")) or link.href in seen:
                continue
            if registrable_domain(link.host) == self.site:
                continue
            seen.add(link.href)
            out.append(link)
        return out

    def same_site(self) -> list[Link]:
        return [
            link
            for link in self.links
            if link.href.startswith(("http://", "https://"))
            and registrable_domain(link.host) == self.site
        ]

    def jsonld_nodes(self) -> Iterator[dict[str, Any]]:
        """Every JSON-LD object, flattening @graph and top-level lists."""
        stack: list[Any] = list(self.jsonld)
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                graph = node.get("@graph")
                if graph is not None:
                    stack.append(graph)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _norm(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


class _Parser(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page = ParsedPage(url=url)
        self.base = url
        self._skip = 0
        self._main = 0
        self._boiler = 0
        self._in_title = False
        self._title: list[str] = []
        self._all: list[str] = []
        self._mainp: list[str] = []
        self._boilp: list[str] = []
        self._contentp: list[str] = []
        self._link: tuple[str, frozenset[str]] | None = None
        self._link_text: list[str] = []
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self._script_type: str | None = None
        self._script_buf: list[str] = []
        self._inline_len = 0

    # -- tags -----------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base" and a.get("href"):
            self.base = urljoin(self.base, a["href"])
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.page.meta:
                self.page.meta[key] = a["content"].strip()
        elif tag == "a" and a.get("href"):
            href = urljoin(self.base, a["href"].strip())
            self._link = (href, frozenset(a.get("rel", "").lower().split()))
            self._link_text = []
        elif tag == "link" and "author" in a.get("rel", "").lower().split() and a.get("href"):
            self.page.links.append(
                Link(urljoin(self.base, a["href"]), host_of(urljoin(self.base, a["href"])),
                     frozenset({"author"}), "")
            )  # fmt: skip
        elif tag == "script":
            if a.get("src"):
                self.page.script_srcs.append(urljoin(self.base, a["src"]))
            self._script_type = a.get("type", "").lower()
            self._script_buf = []
        elif tag == "iframe" and a.get("src"):
            self.page.iframe_srcs.append(urljoin(self.base, a["src"]))
        elif tag == "time" and a.get("datetime"):
            self.page.time_datetimes.append(a["datetime"])
        if tag in _HEADINGS:
            self._heading = tag
            self._heading_text = []
        if a.get("itemprop"):
            self.page.itemprops.update(a["itemprop"].lower().split())
        if _AUTHOR_CLASS.search(a.get("class", "")) or _AUTHOR_CLASS.search(a.get("id", "")):
            self.page.author_class_seen = True
        if tag in _MAIN_TAGS:
            self._main += 1
        elif tag in _BOILER_TAGS:
            self._boiler += 1
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._link is not None:
            href, rel = self._link
            text = " ".join("".join(self._link_text).split())
            self.page.links.append(Link(href, host_of(href), rel, text))
            self._link = None
        elif tag == "script":
            self._finish_script()
        if tag == self._heading:
            text = " ".join("".join(self._heading_text).split())
            if text:
                self.page.headings.append((tag, text))
            self._heading = None
        if tag in _MAIN_TAGS and self._main:
            self._main -= 1
        elif tag in _BOILER_TAGS and self._boiler:
            self._boiler -= 1
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._script_buf.append(data)
            return
        if self._in_title:
            self._title.append(data)
            return
        if self._skip:
            return
        if self._link is not None:
            self._link_text.append(data)
        if self._heading is not None:
            self._heading_text.append(data)
        self._emit(data)

    # -- helpers --------------------------------------------------------------
    def _emit(self, data: str) -> None:
        self._all.append(data)
        if self._main:
            self._mainp.append(data)
            self._contentp.append(data)
        elif self._boiler:
            self._boilp.append(data)
        else:
            self._contentp.append(data)

    def _finish_script(self) -> None:
        body = "".join(self._script_buf)
        if self._script_type == "application/ld+json":
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                self.page.jsonld.append(parsed)
            elif isinstance(parsed, list):
                self.page.jsonld.extend(x for x in parsed if isinstance(x, dict))
        elif body.strip() and self._inline_len < MAX_INLINE_SCRIPT_CHARS:
            chunk = body[: MAX_INLINE_SCRIPT_CHARS - self._inline_len]
            self.page.inline_scripts += chunk + "\n"
            self._inline_len += len(chunk)
        self._script_type = None
        self._script_buf = []

    def result(self) -> ParsedPage:
        self.page.title = " ".join("".join(self._title).split())
        self.page.text = _norm("".join(self._all))
        self.page.main_text = _norm("".join(self._mainp))
        self.page.boiler_text = _norm("".join(self._boilp))
        self.page.content_text = _norm("".join(self._contentp))
        return self.page


def parse_page(url: str, html: str) -> ParsedPage:
    parser = _Parser(url)
    parser.feed(html)
    parser.close()
    return parser.result()
