"""Local web app tests: real HTTP server on 127.0.0.1, FAKE SerpApi and pages."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from slopwatch.cache import Cache
from slopwatch.filter.core import SlopFilter
from slopwatch.pages import PageFetcher
from slopwatch.serp import ProjectLedger, SerpClient
from slopwatch.serve import App, make_server, page_html
from tests.conftest import Recorder, make_client

ARTICLE = (
    "<html><head><title>Dolo 650 daily use</title></head><body><main><h1>Is Dolo 650 safe "
    "every day</h1>" + "<p>Paracetamol dose safety for daily use explained.</p>" * 40
    + "</main></body></html>"
)  # fmt: skip
ANON_OFFTOPIC = (
    "<html><head><title>Cart deals</title></head><body><div>"
    + "<p>Buy now: kitchen mixers and blenders on sale.</p>" * 40
    + '<a href="/cart">Cart</a></div></body></html>'
)


def fake_web(request: httpx.Request) -> httpx.Response:
    if request.url.host == "serpapi.com":
        return httpx.Response(200, json={"organic_results": [
            {"position": 1, "title": "Dolo 650", "link": "https://health.example/dolo"},
            {"position": 2, "title": "Deals", "link": "https://shop.example/deals"},
            {"position": 3, "title": "Video", "link": "https://www.youtube.com/watch?v=1"},
        ]})  # fmt: skip
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    body = ARTICLE if request.url.host == "health.example" else ANON_OFFTOPIC
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def make_app(tmp_path: Path, cap: int = 3) -> tuple[App, Recorder]:
    rec = Recorder(fake_web)
    http = make_client(rec, cache=Cache(":memory:", cross_thread=True))
    serp = SerpClient(
        http, SecretStr("test-key-not-real"),
        project=ProjectLedger(tmp_path / "ledger.jsonl"), max_credits=cap,
    )  # fmt: skip
    return App(serp, SlopFilter.live(PageFetcher(http))), rec


def test_app_search_scores_and_caches(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    status, body = app.search("  is it safe to take dolo 650 every day ", "google-in")
    assert status == 200 and body["query"] == "is it safe to take dolo 650 every day"
    by_link = {r["link"]: r["slopwatch"] for r in body["results"]}
    assert by_link["https://www.youtube.com/watch?v=1"]["not_scored"] == "platform:video"
    shop = by_link["https://shop.example/deals"]
    assert shop["band"] == "low" and any("sells products" in r for r in shop["reasons"])
    assert by_link["https://health.example/dolo"]["band"] != "low"
    assert body["credit_spent"] == 1 and body["session_spent"] == 1 and body["project_spent"] == 1
    again = app.search("is it safe to take dolo 650 every day", "google-in")[1]
    assert again["cached"] and again["credit_spent"] == 0


def test_app_rejects_bad_input_and_enforces_cap(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path, cap=1)
    assert app.search("   ", "google-in")[0] == 400
    assert app.search("q", "bing")[0] == 400
    assert app.search("first", "duckduckgo-in")[0] == 200
    status, body = app.search("second", "yahoo-in")
    assert status == 429 and "cap" in body["error"] and body["session_spent"] == 1


def test_http_server_serves_page_and_api(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    server = make_server(app, 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def get(path: str) -> tuple[int, bytes, str]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.read(), resp.getheader("Content-Type") or ""

        status, body, ctype = get("/")
        assert status == 200 and "text/html" in ctype and b"SlopWatch Console" in body
        status, body, _ = get("/api/search?q=dolo%20650&engine=google-us")
        payload: dict[str, Any] = json.loads(body)
        assert status == 200 and payload["engine"] == "google-us" and len(payload["results"]) == 3
        assert get("/nope")[0] == 404
        assert get("/api/search?q=")[0] == 400
    finally:
        server.shutdown()
        server.server_close()
    assert server.server_address[0] == "127.0.0.1"


def test_page_html_is_self_describing() -> None:
    html = page_html().decode("utf-8")
    assert "<title>SlopWatch Console</title>" in html
    assert all(p in html for p in ("/api/start", "/api/step", "/api/answer"))
    assert "prefers-color-scheme: dark" in html


def test_start_step_answer_workflow(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def agent(question: str, sources: list[Any]) -> tuple[str, list[int]]:
        calls.append([s.url for s in sources])
        return f"answer from {len(sources)} sources", [1, 2]

    app, _ = make_app(tmp_path)
    app.agent = agent
    status, started = app.start("dolo 650 daily", "google-in")
    assert status == 200 and started["agent"] and len(started["results"]) == 3
    job = started["job"]
    assert app.answer(job)[0] == 409  # still reading
    steps = []
    while True:
        st, body = app.step(job)
        assert st == 200
        steps.append(body)
        if body["done"]:
            break
    assert [s["progress"][0] for s in steps] == [1, 2, 3]
    assert app.step(job)[1] == {"done": True, "progress": [3, 3]}
    st, ans = app.answer(job)
    assert (
        st == 200 and ans["dropped"] == ["https://shop.example/deals"] and not ans["same_sources"]
    )
    assert len(calls) == 2 and "https://shop.example/deals" not in calls[1]
    assert ans["before"]["cited"][1]["link"] == "https://shop.example/deals"
    assert ans["after"]["answer"].startswith("answer from")
    assert app.step("nope")[0] == 404 and app.answer("nope")[0] == 404


def test_answer_without_agent_explains(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    job = app.start("q", "google-in")[1]["job"]
    while not app.step(job)[1]["done"]:
        pass
    st, body = app.answer(job)
    assert st == 503 and "GEMINI_API_KEY" in body["error"]


def test_overview_and_rubric_endpoints(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    app.overview = {"overall_india": {"value": 0.05}}
    server = make_server(app, 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/overview")
        assert json.loads(conn.getresponse().read())["overall_india"]["value"] == 0.05
        conn.request("GET", "/api/rubric")
        rubric = json.loads(conn.getresponse().read())
        assert rubric["version"] == 4 and rubric["rules"]
        weights = [r["weight"] for r in rubric["rules"]]
        assert weights == sorted(weights, reverse=True)
    finally:
        server.shutdown()
        server.server_close()
