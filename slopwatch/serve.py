"""``slopwatch serve``: a local web app to search anything and watch the filter work.

Listens on 127.0.0.1 only; the SerpApi key stays on this machine. Each new
search costs one SerpApi credit (repeats are served from the cache); a
per-session credit cap and the project's ledger cap both apply. Result pages are
fetched (robots-aware, cached) and scored with the frozen rubric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlsplit

from slopwatch.filter.core import SlopFilter
from slopwatch.models import Engine, Locale
from slopwatch.queries import serp_params
from slopwatch.serp import SerpClient, SerpError

ENGINES: dict[str, tuple[Engine, Locale]] = {
    "google-in": ("google", "IN"),
    "duckduckgo-in": ("duckduckgo", "IN"),
    "yahoo-in": ("yahoo", "IN"),
    "google-us": ("google", "US"),
}
MAX_QUERY_CHARS = 200


@dataclass
class App:
    serp: SerpClient
    slop_filter: SlopFilter

    def search(self, query: str, engine_key: str) -> tuple[int, dict[str, Any]]:
        query = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not query:
            return 400, {"error": "Type a question to search."}
        if engine_key not in ENGINES:
            return 400, {"error": f"Unknown engine; use one of {', '.join(ENGINES)}."}
        engine, locale = ENGINES[engine_key]
        spent_before = self.serp.ledger.spent
        try:
            page = self.serp.search(engine, serp_params(engine, locale, query))
        except SerpError as exc:
            return 429, {"error": str(exc), **self._credits()}
        results = [{"position": r.rank, "title": r.title, "link": r.url} for r in page.organic]
        annotated = self.slop_filter.apply(query, results, mode="annotate")
        return 200, {
            "query": query,
            "engine": engine_key,
            "threshold": self.slop_filter.threshold(None),
            "results": annotated,
            "cached": page.from_cache,
            "credit_spent": self.serp.ledger.spent - spent_before,
            **self._credits(),
        }

    def _credits(self) -> dict[str, Any]:
        return {
            "session_spent": self.serp.ledger.spent,
            "session_cap": self.serp.ledger.cap,
            "project_spent": self.serp.project.spent,
            "project_cap": self.serp.project.cap,
        }


def page_html() -> bytes:
    return resources.files("slopwatch.report").joinpath("serve.html").read_bytes()


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # quiet console
            return

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            if parts.path == "/":
                self._send(200, page_html(), "text/html; charset=utf-8")
                return
            if parts.path == "/api/search":
                qs = parse_qs(parts.query)
                status, payload = app.search(
                    qs.get("q", [""])[0], qs.get("engine", ["google-in"])[0]
                )
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send(status, body, "application/json; charset=utf-8")
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")

    return Handler


def make_server(app: App, port: int) -> HTTPServer:
    # Single-threaded on purpose: the SQLite cache connection is not shared across threads.
    return HTTPServer(("127.0.0.1", port), make_handler(app))
