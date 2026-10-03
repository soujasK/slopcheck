"""Collect/fetch pipeline tests. SerpApi payloads and pages are SYNTHETIC; no
real network is touched and no credits are spent."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from slopwatch import pipeline
from slopwatch.cli import app
from slopwatch.config import REPO_ROOT
from slopwatch.models import Page, SerpRow, SignalRecord
from slopwatch.pages import PageFetcher
from slopwatch.queries import load_plan
from slopwatch.serp import ProjectLedger, SerpClient
from slopwatch.signals import load_lists
from slopwatch.store import read_jsonl
from tests.conftest import Recorder, make_client

HTML = Path(__file__).parent / "html"
KEY = SecretStr("test-key-not-real")
runner = CliRunner()


def slug(q: str) -> str:
    return quote(q.replace(" ", "-"), safe="-")


def serp_payload(q: str, engine: str) -> dict[str, Any]:
    """10 organic results; the first 4 URLs are shared across all queries so the
    fetch step has a small, fixed set of pages to serve."""
    shared = [
        "https://www.dealsite.example/best-phones/",
        "https://www.incometax.gov.in/iec/foportal/help/link-aadhaar",
        "https://news.example.in/business/tax-regime",
        "https://www.blog.example/fastag",
    ]
    links = shared + [f"https://{engine}{i}.example/{slug(q)}" for i in range(6)]
    return {
        "search_metadata": {"status": "Success"},
        "ads": [{"link": "https://ad.example/"}],
        "organic_results": [
            {"position": i + 1, "link": link, "title": f"T{i}", "snippet": "S"}
            for i, link in enumerate(links)
        ],
    }


SITE_PAGES = {
    "www.dealsite.example": "affiliate_listicle.html",
    "www.incometax.gov.in": "official_howto.html",
    "news.example.in": "news_article.html",
    "www.blog.example": "thin_page.html",
}


def fake_web(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "serpapi.com":
        params = dict(request.url.params)
        assert params["api_key"] == "test-key-not-real"
        q = params.get("q") or params["p"]  # Yahoo uses p
        return httpx.Response(200, json=serp_payload(q, params["engine"]))
    if path == "/robots.txt":
        if host == "google0.example":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(404)
    if host in SITE_PAGES:
        body = (HTML / SITE_PAGES[host]).read_text(encoding="utf-8")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})
    if host.startswith("bing1"):
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
    if host.startswith("google2"):
        return httpx.Response(403, text="forbidden")
    return httpx.Response(200, text="<p>tiny</p>", headers={"content-type": "text/html"})


# -- pipeline functions -------------------------------------------------------------


def test_collect_preview_and_partial_stop(tmp_path: Path) -> None:
    plan = load_plan(REPO_ROOT / "data" / "queries.yaml")
    ledger = ProjectLedger(tmp_path / "ledger.jsonl")
    with make_client(Recorder(fake_web)) as http:
        serp = SerpClient(http, KEY, project=ledger, max_credits=5)
        assert pipeline.preview(plan, serp) == pipeline.CollectPreview(100, 0, 100)
        result = pipeline.collect(plan, serp)
        assert result.done == 5 and result.error and "cap of 5" in result.error
        assert len(result.rows) == 50 and len(result.meta) == 5 and len(result.keys) == 5
        assert result.meta[0].features == ["ads"] and result.meta[0].n_organic == 10
        # what was collected is cached: preview now sees 5 free searches
        assert pipeline.preview(plan, serp).cached == 5
    assert ledger.spent == 5


def test_fetch_pages_covers_every_row(tmp_path: Path) -> None:
    rows = [
        SerpRow(
            query_id="q",
            engine="google",
            locale="IN",
            rank=i + 1,
            url=u,
            domain="d",
            title="t",
            snippet="s",
            request_hash="h",
        )
        for i, u in enumerate(
            [
                "https://www.dealsite.example/best-phones/",
                "https://www.incometax.gov.in/iec/foportal/help/link-aadhaar",
                "https://google0.example/blocked",
                "https://bing1.example/doc.pdf",
                "https://google2.example/forbidden",
                "https://www.dealsite.example/best-phones/",  # duplicate URL
            ]
        )
    ]
    urls = pipeline.unique_urls(rows)
    assert len(urls) == 5
    seen: list[int] = []
    with make_client(Recorder(fake_web)) as http:
        result = pipeline.fetch_pages(
            urls,
            PageFetcher(http),
            load_lists(REPO_ROOT / "data"),
            progress=lambda i, p: seen.append(i),
        )
    assert seen == [1, 2, 3, 4, 5]
    by_url = {p.url: p for p in result.pages}
    assert by_url["https://google0.example/blocked"].unscored_reason == "robots_blocked"
    assert by_url["https://bing1.example/doc.pdf"].unscored_reason == "not_html"
    assert by_url["https://google2.example/forbidden"].unscored_reason == "http_error"
    deal = by_url["https://www.dealsite.example/best-phones/"]
    assert deal.unscored_reason is None and deal.excerpt.startswith("10 Best Smartphones")
    assert len(result.records) == 2
    rec = next(r for r in result.records if "dealsite" in r.url)
    assert rec.signals.affiliate_links == 5 and len(rec.simhash) == 16
    assert rec.html_hash == deal.html_hash
    assert pipeline.coverage_gaps(rows, result.pages, result.records) == []
    assert pipeline.coverage_gaps(rows, [], []) == sorted(set(urls))


def test_parse_failure_is_an_explicit_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("bad html")

    monkeypatch.setattr(pipeline, "extract", boom)
    with make_client(Recorder(fake_web)) as http:
        result = pipeline.fetch_pages(
            ["https://www.blog.example/fastag"], PageFetcher(http), load_lists(REPO_ROOT / "data")
        )
    assert result.records == []
    assert result.pages[0].unscored_reason == "parse_failed"


# -- CLI ------------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name in ("queries.yaml", "rubric.yaml", "affiliate_domains.yaml", "ad_domains.yaml",
                 "commerce_domains.yaml"):  # fmt: skip
        shutil.copy(REPO_ROOT / "data" / name, data / name)
    monkeypatch.setenv("SLOPWATCH_DATA_DIR", str(data))
    monkeypatch.setenv("SLOPWATCH_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("SLOPWATCH_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("SLOPWATCH_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    return data


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder(fake_web)

    def send(self: httpx.Client, request: httpx.Request, **kw: object) -> httpx.Response:
        return rec(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    return rec


def invoke(*args: str) -> Any:
    return runner.invoke(app, list(args), env={"COLUMNS": "200"})


def test_collect_refuses_draft_plan(data_dir: Path, web: Recorder) -> None:
    q = data_dir / "queries.yaml"
    q.write_text(q.read_text(encoding="utf-8").replace("status: frozen", "status: draft"))
    result = invoke("collect")
    assert result.exit_code == 2 and "draft" in result.output
    assert web.requests == []


def test_collect_asks_before_spending_more_than_10(
    data_dir: Path, web: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key-not-real")
    result = invoke("collect", "--max-credits", "100")
    assert result.exit_code == 2
    assert "rerun with --yes to spend 100 credits" in result.output
    assert "credits: 0 spent by this command" in result.output
    too_low = invoke("collect", "--yes")
    assert too_low.exit_code == 2 and "needs 100 credits" in too_low.output
    assert web.requests == []


def test_collect_then_replay_offline_is_identical(
    data_dir: Path, web: Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key-not-real")
    live = invoke("collect", "--max-credits", "100", "--yes")
    assert live.exit_code == 0, live.output
    assert "credits: 100 spent by this command; project ledger 100/140 (40 left)" in live.output
    serps = (data_dir / "serps.jsonl").read_bytes()
    rows = read_jsonl(data_dir / "serps.jsonl", SerpRow)
    assert len(rows) == 1000 and {r.rank for r in rows} == set(range(1, 11))
    fixtures = list((tmp_path / "fixtures").glob("*.json"))
    assert len(fixtures) == 100
    assert not any("test-key-not-real" in f.read_text(encoding="utf-8") for f in fixtures)
    ledger_lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger_lines) == 100 and "test-key-not-real" not in "".join(ledger_lines)

    # replay: no key, network blocked, no credits, byte-identical output
    monkeypatch.delenv("SERPAPI_API_KEY")
    web.requests.clear()
    (data_dir / "serps.jsonl").unlink()
    replay = invoke("collect", "--cache-mode", "replay")
    assert replay.exit_code == 0, replay.output
    assert "100 cached, 0 would spend" in replay.output
    assert "credits: 0 spent by this command; project ledger 100/140" in replay.output
    assert web.requests == []
    assert (data_dir / "serps.jsonl").read_bytes() == serps


def test_collect_stops_at_cap_with_exit_3(
    data_dir: Path, web: Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key-not-real")
    # 75 credits already used: the project cap allows only 65 more
    (tmp_path / "ledger.jsonl").write_text(
        "".join(json.dumps({"credits": 1}) + "\n" for _ in range(75)), encoding="utf-8"
    )
    result = invoke("collect", "--max-credits", "100", "--yes")
    assert result.exit_code == 3
    assert "project SerpApi cap reached: 140/140" in result.output
    assert len(read_jsonl(data_dir / "serps.jsonl", SerpRow)) == 650


def test_fetch_writes_pages_and_signals(
    data_dir: Path, web: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key-not-real")
    assert invoke("collect", "--max-credits", "100", "--yes").exit_code == 0
    refused = invoke("fetch", "--cache-mode", "replay")
    assert refused.exit_code == 2 and "needs the network" in refused.output
    result = invoke("fetch")
    assert result.exit_code == 0, result.output
    rows = read_jsonl(data_dir / "serps.jsonl", SerpRow)
    pages = read_jsonl(data_dir / "pages.jsonl", Page)
    records = read_jsonl(data_dir / "signals.jsonl", SignalRecord)
    assert len(pages) == len({r.url for r in rows})
    assert pipeline.coverage_gaps(rows, pages, records) == []  # Phase 1 acceptance
    assert "unscored robots_blocked:" in result.output
    assert "credits: 0 spent by this command" in result.output
    assert all(len(p.excerpt) <= 300 for p in pages)
    # no page HTML anywhere in committed data
    blob = "".join(p.read_text(encoding="utf-8") for p in data_dir.glob("*.jsonl"))
    assert "<html" not in blob and "<p>" not in blob
    limited = invoke("fetch", "--limit", "3")
    assert limited.exit_code == 0 and "fetch: 3 unique URLs" in limited.output


def test_fetch_without_serps(data_dir: Path) -> None:
    result = invoke("fetch")
    assert result.exit_code == 2 and "run `slopwatch collect` first" in result.output


def test_collect_single_job_probe(
    data_dir: Path, web: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key-not-real")
    bad = invoke("collect", "--job", "made-up/google/IN")
    assert bad.exit_code == 2 and "not in the frozen plan" in bad.output
    result = invoke("collect", "--job", "health-01/google/IN")
    assert result.exit_code == 0, result.output
    assert "1 searches in plan; 0 cached, 1 would spend" in result.output
    assert "credits: 1 spent by this command; project ledger 1/140" in result.output
    rows = read_jsonl(data_dir / "serps.jsonl", SerpRow)
    assert {r.query_id for r in rows} == {"health-01"} and len(rows) == 10
