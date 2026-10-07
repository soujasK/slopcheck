"""SerpApi client tests. Payloads here are SYNTHETIC, shaped after the documented
SerpApi response schemas; they are not recorded fixtures. Real recordings live
under fixtures/ and are produced only by `record` mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from slopwatch.cache import Cache
from slopwatch.config import CacheMode
from slopwatch.queries import serp_params
from slopwatch.serp import (
    CreditCapExceeded,
    MissingApiKey,
    ProjectCapExceeded,
    ProjectLedger,
    SerpClient,
    SerpError,
    parse_features,
    parse_organic,
)
from tests.conftest import Recorder, make_client, no_network

KEY = SecretStr("test-key-not-real")


def organic(n: int, host: str = "site{i}.example") -> list[dict[str, Any]]:
    return [
        {
            "position": i + 1,
            "title": f"Result {i + 1}",
            "link": f"https://www.{host.format(i=i)}/page",
            "snippet": f"snippet {i + 1}",
        }
        for i in range(n)
    ]


GOOGLE_IN: dict[str, Any] = {
    "search_metadata": {"status": "Success"},
    "search_parameters": {"engine": "google", "gl": "in"},
    "ads": [{"title": "Sponsored", "link": "https://ads.example/x"}],
    "ai_overview": {"text_blocks": [{"snippet": "..."}]},
    "related_questions": [],
    "organic_results": organic(12),
}


def serp_handler(payload: dict[str, Any]) -> Recorder:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "serpapi.com"
        return httpx.Response(200, json=payload)

    return Recorder(handler)


@pytest.fixture
def ledger(tmp_path: Path) -> ProjectLedger:
    return ProjectLedger(tmp_path / "ledger.jsonl", cap=140)


def client(http: Any, ledger: ProjectLedger, key: SecretStr | None = KEY, cap: int = 10) -> Any:
    return SerpClient(http, key, project=ledger, max_credits=cap)


def test_parse_organic_top10_dedup_and_ranks() -> None:
    items = organic(3)
    items.insert(1, dict(items[0]))  # duplicate URL
    items.append({"title": "no link"})
    items.append({"title": "relative", "link": "/local"})
    results = parse_organic({"organic_results": items + organic(15, "more{i}.example")})
    assert len(results) == 10
    assert [r.rank for r in results] == list(range(1, 11))
    assert results[0].domain == "site0.example"
    assert results[1].url == "https://www.site1.example/page"
    assert parse_organic({}) == []


def test_parse_features_records_non_organic_blocks() -> None:
    assert parse_features(GOOGLE_IN) == ["ads", "ai_overview"]


def test_search_sends_locale_params_and_records_ledger(ledger: ProjectLedger) -> None:
    rec = serp_handler(GOOGLE_IN)
    with make_client(rec) as http:
        serp = client(http, ledger)
        page = serp.search("google", serp_params("google", "IN", "best sip to invest"))
    sent = rec.requests[0].url.params
    assert sent["engine"] == "google"
    assert (sent["gl"], sent["hl"], sent["google_domain"]) == ("in", "en", "google.co.in")
    assert sent["api_key"] == "test-key-not-real"
    assert "api_key" not in page.params
    assert len(page.organic) == 10
    assert page.features == ["ads", "ai_overview"]
    assert serp.ledger.spent == 1 and serp.ledger.remaining == 9
    (entry,) = ledger.entries()
    assert entry["request_hash"] == page.request_hash
    assert entry["params"]["q"] == "best sip to invest"
    assert "test-key-not-real" not in ledger.path.read_text(encoding="utf-8")


def test_bing_uses_mkt_not_cc(ledger: ProjectLedger) -> None:
    rec = serp_handler({"organic_results": organic(2)})
    with make_client(rec) as http:
        client(http, ledger).search("bing", serp_params("bing", "IN", "q"))
    sent = rec.requests[0].url.params
    assert sent["mkt"] == "en-IN" and "cc" not in sent


def test_yahoo_uses_p_as_query_param(ledger: ProjectLedger) -> None:
    rec = serp_handler({"organic_results": organic(3), "ads_results": [{"link": "x"}]})
    with make_client(rec) as http:
        serp = client(http, ledger)
        with pytest.raises(ValueError, match="'p' for engine 'yahoo'"):
            serp.search("yahoo", {"q": "wrong param"})
        page = serp.search("yahoo", serp_params("yahoo", "IN", "is term insurance worth it"))
    sent = rec.requests[0].url.params
    assert sent["p"] == "is term insurance worth it" and sent["yahoo_domain"] == "in"
    assert "q" not in sent
    assert len(page.organic) == 3 and page.features == ["ads_results"]
    assert serp.ledger.entries[0].query == "is term insurance worth it"


def test_cache_hit_is_free(ledger: ProjectLedger) -> None:
    rec = serp_handler(GOOGLE_IN)
    with make_client(rec) as http:
        serp = client(http, ledger)
        assert serp.would_spend("google", {"q": "q"})
        serp.search("google", {"q": "q"})
        assert not serp.would_spend("google", {"q": "q"})
        again = serp.search("google", {"q": "q"})
    assert again.from_cache
    assert serp.ledger.spent == 1 and serp.ledger.saved == 1
    assert [e.credits for e in serp.ledger.entries] == [1, 0]
    assert ledger.spent == 1
    assert len(rec.requests) == 1


def test_run_cap_is_hard(ledger: ProjectLedger) -> None:
    rec = serp_handler(GOOGLE_IN)
    with make_client(rec) as http:
        serp = client(http, ledger, cap=2)
        serp.search("google", {"q": "a"})
        serp.search("google", {"q": "b"})
        with pytest.raises(CreditCapExceeded):
            serp.search("google", {"q": "c"})
        # cached queries remain available after the cap is hit
        assert serp.search("google", {"q": "a"}).from_cache
    assert len(rec.requests) == 2


def test_project_cap_is_hard_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    rec = serp_handler(GOOGLE_IN)
    with make_client(rec) as http:
        first = client(http, ProjectLedger(path, cap=3), cap=10)
        first.search("google", {"q": "a"})
        first.search("google", {"q": "b"})
        # a new run with a fresh per-run cap still sees the project total
        second = client(http, ProjectLedger(path, cap=3), cap=10)
        second.search("google", {"q": "c"})
        with pytest.raises(ProjectCapExceeded, match="3/3"):
            second.search("google", {"q": "d"})
    assert len(rec.requests) == 3
    assert ProjectLedger(path).spent == 3


def test_default_project_cap_is_180(tmp_path: Path) -> None:
    ledger = ProjectLedger(tmp_path / "l.jsonl")
    assert ledger.cap == 180 and ledger.spent == 0 and ledger.remaining == 180


def test_missing_key_only_matters_on_cache_miss(ledger: ProjectLedger) -> None:
    with make_client(no_network) as http:
        with pytest.raises(MissingApiKey):
            client(http, ledger, key=None).search("google", {"q": "q"})
        with pytest.raises(MissingApiKey):
            client(http, ledger, key=None).account()
        with pytest.raises(ValueError, match="'q'"):
            client(http, ledger).search("google", {"gl": "in"})


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"error": "Invalid API key."}), "Invalid API key"),
        (httpx.Response(500, content=b"<html>"), "unparseable"),
        (httpx.Response(400, json={}), "unknown error"),
        (httpx.Response(200, json={"error": "Something broke"}), "Something broke"),
    ],
)
def test_serpapi_errors_are_not_billed(
    response: httpx.Response, message: str, ledger: ProjectLedger
) -> None:
    rec = Recorder(lambda r: response)
    with make_client(rec, max_retries=0) as http, pytest.raises(SerpError, match=message):
        client(http, ledger).search("google", {"q": "q"})
    assert ledger.spent == 0


def test_no_results_is_a_valid_billed_answer(ledger: ProjectLedger) -> None:
    payload = {"error": "Google hasn't returned any results for this query."}
    with make_client(serp_handler(payload)) as http:
        serp = client(http, ledger)
        page = serp.search("google", {"q": "very obscure"})
    assert page.organic == [] and serp.ledger.spent == 1 and ledger.spent == 1


def test_recorded_call_replays_offline(tmp_path: Path, ledger: ProjectLedger) -> None:
    """Phase 0 acceptance: record a SerpApi call, export it as a fixture, and
    replay it with the network disabled and no API key, at zero credit cost."""
    fixtures = tmp_path / "fixtures"
    params = serp_params("google", "IN", "how to improve cibil score fast")
    with make_client(serp_handler(GOOGLE_IN), mode=CacheMode.RECORD) as http:
        recorded = client(http, ledger).search("google", params)
        assert http.cache.export_dir(fixtures) == 1
    fixture = next(fixtures.glob("*.json")).read_text(encoding="utf-8")
    assert "test-key-not-real" not in fixture
    assert json.loads(fixture)["cost"] == 1
    assert ledger.spent == 1

    with make_client(no_network, cache=Cache.from_fixtures(fixtures)) as http:
        serp = client(http, ledger, key=None, cap=0)
        replayed = serp.search("google", params)
    assert replayed.from_cache
    assert replayed.organic == recorded.organic
    assert replayed.features == recorded.features
    assert serp.ledger.spent == 0 and serp.ledger.saved == 1
    assert ledger.spent == 1  # replay never touches the ledger


def test_replay_miss_would_not_spend(ledger: ProjectLedger) -> None:
    with make_client(no_network, mode=CacheMode.REPLAY) as http:
        serp = client(http, ledger)
        assert not serp.would_spend("google", {"q": "q"})
        with pytest.raises(LookupError):
            serp.search("google", {"q": "q"})


def test_account_api_not_cached(ledger: ProjectLedger) -> None:
    rec = Recorder(
        lambda r: httpx.Response(200, json={"plan_name": "Free", "total_searches_left": 207})
    )
    with make_client(rec) as http:
        serp = client(http, ledger)
        assert serp.account()["total_searches_left"] == 207
        assert len(http.cache) == 0
    rejected = Recorder(lambda r: httpx.Response(401, json={"error": "bad"}))
    with make_client(rejected) as http, pytest.raises(Exception, match="401"):
        client(http, ledger).account()
