"""SerpApi client with two hard credit caps and an append-only spend ledger.

Adapted from Zero Hour. Engines and parameters (verified against serpapi.com
docs, 2026-10-02):

* ``google``  ``gl`` (country), ``hl`` (language), ``google_domain``. Web results
              under ``organic_results``; ads, AI Overview, answer boxes etc. are
              separate top-level keys.
* ``bing``    ``mkt`` (``<lang>-<country>``, e.g. ``en-IN``). ``cc`` is the
              alternative and the docs say the two are mutually exclusive, so only
              ``mkt`` is used. Web results under ``organic_results``.

Caps, both checked *before* any network call:

* run cap      ``--max-credits`` for one command (default 10).
* project cap  ``PROJECT_CREDIT_CAP`` (140) over everything in the committed ledger
               ``data/serpapi_ledger.jsonl``, so it survives a deleted cache.

A request costs 1 credit only when it reaches SerpApi. Cache hits and replays
cost nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from pydantic import SecretStr

from slopwatch.cache import redact_params, request_key
from slopwatch.config import PROJECT_CREDIT_CAP
from slopwatch.http import HttpClient, HttpError
from slopwatch.models import Engine

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"
TOP_N = 10
# Top-level response keys that are bookkeeping, not SERP features.
_NON_FEATURE_KEYS = frozenset(
    {
        "search_metadata",
        "search_parameters",
        "search_information",
        "organic_results",
        "pagination",
        "serpapi_pagination",
        "error",
    }
)


class SerpError(RuntimeError):
    pass


class MissingApiKey(SerpError):
    pass


class CreditCapExceeded(SerpError):
    def __init__(self, cap: int) -> None:
        super().__init__(f"SerpApi credit cap of {cap} reached for this run")
        self.cap = cap


class ProjectCapExceeded(SerpError):
    def __init__(self, cap: int, spent: int) -> None:
        super().__init__(f"project SerpApi cap reached: {spent}/{cap} credits in the ledger")
        self.cap = cap
        self.spent = spent


class ProjectLedger:
    """Append-only JSONL record of every credit spent by this project.

    One line per billed request; no secrets (params are redacted). The file is
    committed, so the cap and SERPAPI_USAGE.md numbers are auditable.
    """

    def __init__(self, path: Path, cap: int = PROJECT_CREDIT_CAP) -> None:
        self.path = path
        self.cap = cap

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    @property
    def spent(self) -> int:
        return sum(int(e.get("credits", 0)) for e in self.entries())

    @property
    def remaining(self) -> int:
        return max(self.cap - self.spent, 0)

    def record(
        self, *, engine: str, request_hash: str, params: Mapping[str, Any], credits: int = 1
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "engine": engine,
            "request_hash": request_hash,
            "params": redact_params(params),
            "credits": credits,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


@dataclass(frozen=True)
class SpendEntry:
    engine: str
    query: str
    credits: int
    from_cache: bool


@dataclass
class CreditLedger:
    """Per-run accounting."""

    cap: int
    spent: int = 0
    # Credits the replayed/cached responses originally cost when recorded.
    saved: int = 0
    entries: list[SpendEntry] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(self.cap - self.spent, 0)


@dataclass(frozen=True)
class OrganicResult:
    rank: int
    url: str
    domain: str
    title: str
    snippet: str


@dataclass(frozen=True)
class SerpPage:
    request_hash: str
    engine: Engine
    params: dict[str, str]
    organic: list[OrganicResult]
    # Non-organic SERP features present (ads, ai_overview, ...), metadata only.
    features: list[str]
    fetched_at: datetime
    from_cache: bool


class SerpClient:
    def __init__(
        self,
        http: HttpClient,
        api_key: SecretStr | None,
        *,
        project: ProjectLedger,
        max_credits: int = 10,
    ) -> None:
        self.http = http
        self._api_key = api_key
        self.project = project
        self.ledger = CreditLedger(cap=max_credits)

    def would_spend(self, engine: Engine, params: Mapping[str, str]) -> bool:
        """True if this search is not cached and would cost a credit."""
        key = request_key("GET", SERPAPI_SEARCH_URL, {"engine": engine, **params})
        try:
            return self.http.cache.lookup(key) is None
        except LookupError:  # replay miss: it would fail, not spend
            return False

    def search(self, engine: Engine, params: Mapping[str, str]) -> SerpPage:
        """Run one search. ``params`` holds ``q`` plus locale parameters."""
        if "q" not in params:
            raise ValueError("params must include 'q'")
        full: dict[str, str] = {"engine": engine, **params}
        key = request_key("GET", SERPAPI_SEARCH_URL, full)
        hit = self.http.cache.lookup(key)
        if hit is None:
            if self.ledger.spent >= self.ledger.cap:
                raise CreditCapExceeded(self.ledger.cap)
            project_spent = self.project.spent
            if project_spent >= self.project.cap:
                raise ProjectCapExceeded(self.project.cap, project_spent)
            if self._api_key is None:
                raise MissingApiKey("SERPAPI_API_KEY is not set (replay mode needs no key)")

        resp = self.http.get(
            SERPAPI_SEARCH_URL,
            {**full, "api_key": self._api_key.get_secret_value() if self._api_key else None},
        )
        if resp.status >= 400:
            raise SerpError(f"SerpApi HTTP {resp.status}: {_error_message(resp.body)}")
        payload = cast(dict[str, Any], resp.json())
        error = payload.get("error")
        # "no results" is a valid (billed) answer; anything else is a failure.
        if error and "hasn't returned any results" not in str(error):
            raise SerpError(f"SerpApi error: {error}")

        if resp.from_cache:
            self.ledger.saved += resp.cost
            credits = 0
        else:
            credits = 1
            self.ledger.spent += 1
            self.project.record(engine=engine, request_hash=key, params=full)
            self.http.cache.set_cost(key, 1)
        self.ledger.entries.append(
            SpendEntry(engine, params["q"], credits, from_cache=resp.from_cache)
        )
        return SerpPage(
            request_hash=key,
            engine=engine,
            params=full,
            organic=parse_organic(payload),
            features=parse_features(payload),
            fetched_at=resp.fetched_at,
            from_cache=resp.from_cache,
        )

    def account(self) -> dict[str, Any]:
        """SerpApi Account API: free, never cached or recorded."""
        if self._api_key is None:
            raise MissingApiKey("SERPAPI_API_KEY is not set")
        resp = self.http.get(
            SERPAPI_ACCOUNT_URL, {"api_key": self._api_key.get_secret_value()}, store=False
        )
        if resp.status >= 400:
            raise HttpError(f"SerpApi account HTTP {resp.status}", resp.status)
        return cast(dict[str, Any], resp.json())


# -- parsing -------------------------------------------------------------------


def parse_organic(payload: Mapping[str, Any], limit: int = TOP_N) -> list[OrganicResult]:
    """Top ``limit`` organic results, deduplicated by URL, ranked 1..n."""
    results: list[OrganicResult] = []
    seen: set[str] = set()
    for item in payload.get("organic_results") or []:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("link") or "")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append(
            OrganicResult(
                rank=len(results) + 1,
                url=url,
                domain=host_of(url),
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
            )
        )
        if len(results) == limit:
            break
    return results


def parse_features(payload: Mapping[str, Any]) -> list[str]:
    return sorted(k for k, v in payload.items() if k not in _NON_FEATURE_KEYS and v)


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _error_message(body: bytes) -> str:
    try:
        msg = json.loads(body).get("error")
        return str(msg) if msg else "unknown error"
    except (ValueError, AttributeError):
        return "unparseable error body"
