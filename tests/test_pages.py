from __future__ import annotations

import hashlib

import httpx
import pytest

from slopwatch.config import CacheMode
from slopwatch.pages import PageFetcher, html_to_text, make_excerpt
from tests.conftest import Recorder, make_client, no_network

HTML = (
    "<html><head><title> Best  SIP 2026 </title><script>var ads=1;</script></head>"
    "<body><nav>Home</nav><article><h1>Best SIP</h1><p>Invest &amp; grow.</p>"
    "<table><tr><td>Fund</td><td>CAGR</td></tr></table></article>"
    "<style>p{}</style><noscript>enable js</noscript></body></html>"
)


def site(
    robots: httpx.Response | None = None,
    page: httpx.Response | None = None,
) -> Recorder:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots or httpx.Response(404)
        return page or httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    return Recorder(handler)


def test_html_to_text_drops_scripts_and_head() -> None:
    title, text = html_to_text(HTML)
    assert title == "Best SIP 2026"
    assert "Invest & grow." in text and "Fund | CAGR" in text.replace(" |  | ", " | ")
    assert "ads" not in text and "p{}" not in text and "enable js" not in text


def test_fetch_ok_records_hash_and_text_len() -> None:
    rec = site()
    with make_client(rec) as http:
        result = PageFetcher(http).fetch("https://a.example/sip")
    assert result.html == HTML
    page = result.page
    assert page.unscored_reason is None and not page.robots_blocked
    assert page.status == 200 and page.fetched_at is not None
    assert page.html_hash == hashlib.sha256(HTML.encode()).hexdigest()
    assert page.text_len == len(html_to_text(HTML)[1])


def test_robots_checked_once_per_origin() -> None:
    rec = site(robots=httpx.Response(200, text="User-agent: *\nDisallow: /private\n"))
    with make_client(rec) as http:
        fetcher = PageFetcher(http)
        assert fetcher.fetch("https://a.example/ok").page.unscored_reason is None
        blocked = fetcher.fetch("https://a.example/private/x").page
    assert blocked.unscored_reason == "robots_blocked" and blocked.robots_blocked
    assert blocked.status is None
    paths = [r.url.path for r in rec.requests]
    assert paths.count("/robots.txt") == 1 and "/private/x" not in paths


def test_robots_rules_for_our_agent() -> None:
    rules = "User-agent: slopwatch\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    with make_client(site(robots=httpx.Response(200, text=rules))) as http:
        assert PageFetcher(http).fetch("https://a.example/").page.unscored_reason == (
            "robots_blocked"
        )


def test_unreachable_robots_means_do_not_fetch() -> None:
    rec = site(robots=httpx.Response(503))
    with make_client(rec, max_retries=0) as http:
        page = PageFetcher(http).fetch("https://a.example/x").page
    assert page.unscored_reason == "robots_unavailable" and not page.robots_blocked
    assert [r.url.path for r in rec.requests] == ["/robots.txt"]


@pytest.mark.parametrize(
    ("response", "reason", "status"),
    [
        (httpx.Response(403, text="denied"), "http_error", 403),
        (
            httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}),
            "not_html",
            200,
        ),
        (
            httpx.Response(200, content=b"x" * 3000, headers={"content-type": "text/html"}),
            "too_large",
            None,
        ),
        (httpx.Response(502), "http_error", 502),
    ],
)
def test_unscored_reasons(response: httpx.Response, reason: str, status: int | None) -> None:
    with make_client(site(page=response), max_retries=0) as http:
        result = PageFetcher(http, max_bytes=2000).fetch("https://a.example/x")
    assert result.page.unscored_reason == reason
    assert result.page.status == status
    assert result.html is None


def test_transport_failure_is_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ReadTimeout("slow")

    with make_client(Recorder(handler), max_retries=0) as http:
        page = PageFetcher(http).fetch("https://a.example/x").page
    assert page.unscored_reason == "fetch_failed" and page.status is None


def test_replay_without_fixture_is_not_recorded() -> None:
    with make_client(no_network, mode=CacheMode.REPLAY) as http:
        # robots.txt is missing too -> conservative verdict, no network
        assert PageFetcher(http).fetch("https://a.example/x").page.unscored_reason == (
            "robots_unavailable"
        )


def test_replay_with_robots_but_no_page_is_not_recorded() -> None:
    with make_client(site(), mode=CacheMode.LIVE) as http:
        PageFetcher(http).robots_verdict("https://a.example/x")
        http.cache.mode = CacheMode.REPLAY
        page = PageFetcher(http).fetch("https://a.example/x").page
    assert page.unscored_reason == "not_recorded"


def test_excerpt_is_capped_at_300_chars() -> None:
    long = "<html><body><p>" + ("word " * 400) + "</p></body></html>"
    with make_client(
        site(page=httpx.Response(200, text=long, headers={"content-type": "text/html"}))
    ) as http:
        page = PageFetcher(http).fetch("https://a.example/long").page
    assert len(page.excerpt) <= 300 and page.excerpt.endswith("…")
    assert not page.excerpt[:-1].endswith(" ")
    assert make_excerpt(" short\n text ") == "short text"


def test_page_model_rejects_long_excerpt() -> None:
    from pydantic import ValidationError

    from slopwatch.models import Page

    with pytest.raises(ValidationError):
        Page(url="u", status=200, fetched_at=None, excerpt="x" * 301)
