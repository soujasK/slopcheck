"""Filter and adapter tests. Offline filter uses the committed measurement data;
adapters run against FAKE SerpApi clients (no network, no credits)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from slopwatch.filter import filter_results, offline_filter
from slopwatch.filter.core import SlopFilter
from slopwatch.filter.langchain import filtered_results
from slopwatch.filter.serpapi_tools import SlopWatchClient, web_search
from slopwatch.pages import PageFetcher
from tests.conftest import Recorder, make_client

QUERY = "best medicine for acidity and gas without prescription"


def committed_results(query_id: str = "health-01") -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in open("data/serps.jsonl", encoding="utf-8")  # noqa: SIM115
    ]
    return [
        {"title": r["title"], "link": r["url"], "position": r["rank"]}
        for r in rows
        if r["query_id"] == query_id and r["engine"] == "google" and r["locale"] == "IN"
    ]


def test_offline_annotates_every_result_and_never_drops_platforms() -> None:
    f = offline_filter()
    results = committed_results()
    out = f.apply(QUERY, results, mode="annotate")
    assert len(out) == len(results)
    kinds = {r["slopwatch"]["not_scored"] for r in out if r["slopwatch"]["not_scored"]}
    assert {"platform:video", "platform:forum", "platform:shop"} <= kinds
    scored = [r for r in out if r["slopwatch"]["slop_risk"] is not None]
    assert scored and all(r["slopwatch"]["band"] in ("ok", "mixed", "low") for r in scored)
    # relevance reached the scorer: at least one reason mentions query coverage
    assert any("query's words" in reason for r in scored for reason in r["slopwatch"]["reasons"])


def test_drop_mode_uses_threshold_and_keeps_unscored() -> None:
    f = offline_filter()
    results = [
        *committed_results(),
        {"title": "no link"},
        {"title": "x", "link": "https://nowhere.example/"},
    ]
    everything = f.apply(QUERY, results, mode="drop", threshold=0.0)
    # threshold 0 drops every scored result; unscored and link-less results stay
    assert all(r["slopwatch"]["slop_risk"] is None for r in everything)
    assert {r["slopwatch"]["not_scored"] for r in everything} >= {"no_link", "not_recorded"}
    nothing = f.apply(QUERY, results, mode="drop", threshold=1.01)
    assert len(nothing) == len(results)
    assert f.threshold(None) == f.rubric.bands.low


def test_live_filter_fetches_and_scores(tmp_path: Any) -> None:
    html = (
        "<html><head><title>Acidity medicine guide</title></head><body><main>"
        "<h1>Best medicine for acidity and gas</h1>"
        + "<p>Antacids and prescription-free options for acidity and gas relief explained.</p>" * 40
        + '<a href="/cart">Cart</a></main></body></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    with make_client(Recorder(handler)) as http:
        f = SlopFilter.live(PageFetcher(http))
        (a,) = f.assess(QUERY, ["https://shop.example/acidity"])
    assert a.slop_risk is not None and a.not_scored is None
    assert any("sells products" in r for r in a.reasons)
    assert not any("query's words" in r for r in a.reasons)  # on-topic page


class FakeSerpApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(params)
        return {
            "search_metadata": {"status": "Success"},
            "organic_results": committed_results(),
        }


def test_slopwatch_client_filters_inside_serpapi_tool() -> None:
    fake = FakeSerpApi()
    tool = web_search(client=fake, slop_filter=offline_filter(), threshold=0.0)
    payload = json.loads(tool(query=QUERY))
    assert fake.calls and fake.calls[0]["q"] == QUERY
    kept = payload["organic_results"]
    assert kept and all("slopwatch" in r for r in kept)
    assert all(r["slopwatch"]["slop_risk"] is None for r in kept)  # threshold 0 drops all scored


def test_slopwatch_client_annotate_mode_and_guards() -> None:
    client = SlopWatchClient(FakeSerpApi(), slop_filter=offline_filter(), mode="annotate")
    out = client.search({"q": QUERY, "engine": "google"})
    assert out["slopwatch"]["dropped"] == 0
    assert out["slopwatch"]["rubric_version"] == 3
    with pytest.raises(ValueError, match="JSON"):
        client.search({"q": QUERY, "output": "md"})

    class MarkdownOnly:
        def search(self, params: dict[str, Any]) -> str:
            return "# results"

    with pytest.raises(TypeError, match="JSON"):
        SlopWatchClient(MarkdownOnly(), slop_filter=offline_filter()).search({"q": QUERY})
    with pytest.raises(ValueError, match="json"):
        web_search(client=FakeSerpApi(), slop_filter=offline_filter(), response_format="markdown")


def test_langchain_helper_with_wrapper_like_object() -> None:
    class Wrapper:
        def results(self, query: str) -> dict[str, Any]:
            return {"organic_results": committed_results()}

    out = filtered_results(Wrapper(), QUERY, slop_filter=offline_filter(), mode="annotate")
    assert len(out) == len(committed_results())


def test_filter_results_entry_point() -> None:
    out = filter_results(QUERY, committed_results(), slop_filter=offline_filter(), mode="annotate")
    assert out[0]["slopwatch"].keys() == {"slop_risk", "band", "reasons", "not_scored"}
