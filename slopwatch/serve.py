"""``slopwatch serve``: a local web app to search anything and watch the filter work.

Workflow (driven by the page, one short request at a time, so a single-threaded
server can stream progress):

1. ``/api/start``  SerpApi search; the result list comes back immediately.
2. ``/api/step``   reads and scores the next result page (robots-aware, cached).
3. ``/api/answer`` the same agent answers twice: from the raw top 5 and from the
   SlopWatch-filtered top 5, each citation marked clear or slop.

Listens on 127.0.0.1 only; keys stay on this machine. Each new search costs one
SerpApi credit (repeats come from the cache); per-session and project caps apply.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlsplit

from slopwatch.demo import Source
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
TOP_K = 5
MAX_JOBS = 50

Agent = Callable[[str, list[Source]], tuple[str, list[int]]]


@dataclass
class Job:
    query: str
    engine: str
    results: list[dict[str, Any]]
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return len(self.scores) >= len(self.results)


@dataclass
class App:
    serp: SerpClient
    slop_filter: SlopFilter
    agent: Agent | None = None
    # Read-only views (Observatory, Method); computed once from committed data.
    overview: dict[str, Any] = field(default_factory=dict)
    # Questions already searched by this project (query plans); powers suggestions.
    known: list[str] = field(default_factory=list)
    jobs: dict[str, Job] = field(default_factory=dict)
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    # -- step 1 -------------------------------------------------------------------
    def start(self, query: str, engine_key: str) -> tuple[int, dict[str, Any]]:
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
        results = [
            {"position": r.rank, "title": r.title, "link": r.url, "snippet": r.snippet}
            for r in page.organic
        ]
        job_id = str(next(self._ids))
        self.jobs[job_id] = Job(query, engine_key, results)
        while len(self.jobs) > MAX_JOBS:
            self.jobs.pop(next(iter(self.jobs)))
        return 200, {
            "job": job_id,
            "query": query,
            "engine": engine_key,
            "threshold": self.slop_filter.threshold(None),
            "results": results,
            "cached": page.from_cache,
            # when SerpApi produced these results (a cached search replays that snapshot)
            "fetched_at": page.fetched_at.isoformat(),
            "credit_spent": self.serp.ledger.spent - spent_before,
            "agent": self.agent is not None,
            **self._credits(),
        }

    # -- step 2 -------------------------------------------------------------------
    def step(self, job_id: str) -> tuple[int, dict[str, Any]]:
        job = self.jobs.get(job_id)
        if job is None:
            return 404, {"error": "This search has expired; search again."}
        if job.done:
            return 200, {"done": True, "progress": [len(job.scores), len(job.results)]}
        index = len(job.scores)
        link = job.results[index]["link"]
        (assessment,) = self.slop_filter.assess(job.query, [link])
        job.scores[link] = assessment.as_dict()
        return 200, {
            "index": index,
            "link": link,
            "slopwatch": job.scores[link],
            "done": job.done,
            "progress": [len(job.scores), len(job.results)],
        }

    # -- step 3 -------------------------------------------------------------------
    def answer(self, job_id: str) -> tuple[int, dict[str, Any]]:
        job = self.jobs.get(job_id)
        if job is None:
            return 404, {"error": "This search has expired; search again."}
        if not job.done:
            return 409, {"error": "Still reading pages."}
        if self.agent is None:
            return 503, {"error": "Set GEMINI_API_KEY (in .env) to see the agent's answers."}
        cut = self.slop_filter.threshold(None)

        def is_slop(link: str) -> bool:
            risk = job.scores[link]["slop_risk"]
            return risk is not None and risk >= cut

        raw = job.results[:TOP_K]
        kept = [r for r in job.results if not is_slop(r["link"])][:TOP_K]
        dropped = [r["link"] for r in raw if is_slop(r["link"])]
        before = self._ask(job, raw)
        after = before if not dropped else self._ask(job, kept)
        return 200, {
            "dropped": dropped,
            "same_sources": not dropped,
            "before": before,
            "after": after,
        }

    def _ask(self, job: Job, results: list[dict[str, Any]]) -> dict[str, Any]:
        assert self.agent is not None
        sources = []
        for n, r in enumerate(results, start=1):
            s = job.scores[r["link"]]
            text = (
                self.slop_filter.agent_texts.get(r["link"])
                or self.slop_filter.excerpts.get(r["link"])
                or r.get("snippet")
                or ""
            )
            sources.append(
                Source(n, r["link"], r["title"], text, s["slop_risk"], s["band"], s["not_scored"])
            )
        text, cited = self.agent(job.query, sources)
        by_n = {s.n: s for s in sources}
        return {
            "answer": text,
            "sources": [
                {"n": s.n, "link": s.url, "band": s.band, "not_scored": s.not_scored}
                for s in sources
            ],
            "cited": [
                {
                    "n": c,
                    "link": by_n[c].url,
                    "band": by_n[c].band,
                    "not_scored": by_n[c].not_scored,
                }
                for c in cited
                if c in by_n
            ],
        }

    # -- as-you-type (read-only, never spends) ---------------------------------------
    def _cached(self, query: str, engine_key: str) -> bool:
        engine, locale = ENGINES[engine_key]
        return not self.serp.would_spend(engine, serp_params(engine, locale, query))

    def peek(self, query: str, engine_key: str) -> tuple[int, dict[str, Any]]:
        """Would this exact search come from the cache (free) or cost a credit?"""
        query = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not query or engine_key not in ENGINES:
            return 400, {"error": "query and a known engine are required"}
        cached = self._cached(query, engine_key)
        left = max(self.serp.ledger.cap - self.serp.ledger.spent, 0)
        return 200, {"query": query, "engine": engine_key, "cached": cached,
                     "cost": 0 if cached else 1, "can_run": cached or left > 0,
                     "session_left": left}  # fmt: skip

    def suggest(self, prefix: str, engine_key: str, limit: int = 6) -> tuple[int, dict[str, Any]]:
        """Known questions matching every typed word (word-prefix match), cached ones first."""
        if engine_key not in ENGINES:
            return 400, {"error": "unknown engine"}
        words = [w for w in " ".join(prefix.lower().split()).split(" ") if w]
        if not words:
            return 200, {"suggestions": []}
        hits = []
        for text in self.known:
            toks = text.lower().split()
            if all(any(t.startswith(w) for t in toks) for w in words):
                hits.append(text)
        rows = [{"q": t, "cached": self._cached(t, engine_key)} for t in hits[: limit * 3]]
        rows.sort(key=lambda r: (not r["cached"], len(r["q"])))
        return 200, {"suggestions": rows[:limit]}

    # -- one-shot (API / scripts) ---------------------------------------------------
    def search(self, query: str, engine_key: str) -> tuple[int, dict[str, Any]]:
        """Start, score every result, return everything in one response."""
        status, started = self.start(query, engine_key)
        if status != 200:
            return status, started
        job = self.jobs[started["job"]]
        while not job.done:
            self.step(started["job"])
        started["results"] = [{**r, "slopwatch": job.scores[r["link"]]} for r in job.results]
        return 200, started

    def rubric(self) -> dict[str, Any]:
        r = self.slop_filter.rubric
        return {
            "version": r.version,
            "low": r.bands.low,
            "mixed": r.bands.mixed,
            "rules": [
                {
                    "id": rule.id,
                    "weight": rule.weight,
                    "reason": rule.reason,
                    "conditions": [c.model_dump(exclude_none=True) for c in rule.all],
                }
                for rule in sorted(r.rules, key=lambda x: -x.weight)
            ],
        }

    def _credits(self) -> dict[str, Any]:
        return {
            "session_spent": self.serp.ledger.spent,
            "session_cap": self.serp.ledger.cap,
            "project_spent": self.serp.project.spent,
            "project_cap": self.serp.project.cap,
        }


# The console is a React app (web/), built into slopwatch/report/app/ so it ships in
# the wheel: no Node needed to run it, and no network (fonts and libraries bundled).
APP = resources.files("slopwatch.report").joinpath("app")
ASSET_TYPES = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".svg": "image/svg+xml",
}
SAFE_ASSET = re.compile(r"^[A-Za-z0-9._-]+$")


def page_html() -> bytes:
    return APP.joinpath("index.html").read_bytes()


def asset(name: str) -> tuple[bytes, str] | None:
    """A built asset by bare file name (hashed by Vite); None if unknown or unsafe."""
    suffix = name[name.rfind(".") :] if "." in name else ""
    if not SAFE_ASSET.match(name) or suffix not in ASSET_TYPES:
        return None
    f = APP.joinpath("assets", name)
    return (f.read_bytes(), ASSET_TYPES[suffix]) if f.is_file() else None


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # quiet console
            return

        def _send(self, status: int, body: bytes, ctype: str, *, immutable: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-store"
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            qs = parse_qs(parts.query)

            def arg(name: str, default: str = "") -> str:
                return qs.get(name, [default])[0]

            if parts.path == "/":
                self._send(200, page_html(), "text/html; charset=utf-8")
            elif parts.path.startswith("/assets/"):
                found = asset(parts.path.removeprefix("/assets/"))
                if found is None:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                else:
                    self._send(200, *found, immutable=True)
            elif parts.path == "/api/start":
                self._json(*app.start(arg("q"), arg("engine", "google-in")))
            elif parts.path == "/api/step":
                self._json(*app.step(arg("job")))
            elif parts.path == "/api/answer":
                self._json(*app.answer(arg("job")))
            elif parts.path == "/api/overview":
                self._json(200, app.overview or {"error": "no measurement data"})
            elif parts.path == "/api/rubric":
                self._json(200, app.rubric())
            elif parts.path == "/api/peek":
                self._json(*app.peek(arg("q"), arg("engine", "google-in")))
            elif parts.path == "/api/suggest":
                self._json(*app.suggest(arg("q"), arg("engine", "google-in")))
            elif parts.path == "/api/search":
                self._json(*app.search(arg("q"), arg("engine", "google-in")))
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

    return Handler


def make_server(app: App, port: int) -> HTTPServer:
    # Single-threaded on purpose: the SQLite cache connection is not shared across threads.
    return HTTPServer(("127.0.0.1", port), make_handler(app))
