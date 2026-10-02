from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest

from slopwatch.cache import Cache
from slopwatch.config import CacheMode
from slopwatch.http import HttpClient

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    """MockTransport handler wrapper that records every request it sees."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network call: {request.method} {request.url.host}")


def make_client(
    handler: Handler,
    *,
    mode: CacheMode = CacheMode.LIVE,
    cache: Cache | None = None,
    max_retries: int = 3,
) -> HttpClient:
    return HttpClient(
        cache or Cache(":memory:", mode=mode),
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        sleep=lambda _s: None,
    )


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Tests never see real secrets and never touch the user's cache or ledger."""
    for var in (
        "SERPAPI_API_KEY",
        "SLOPWATCH_SERPAPI_API_KEY",
        "SLOPWATCH_LLM_API_KEY",
        "ANTHROPIC_API_KEY",
        "SLOPWATCH_CACHE_MODE",
    ):
        monkeypatch.delenv(var, raising=False)
    tmp = tmp_path_factory.mktemp("state")
    monkeypatch.setenv("SLOPWATCH_CACHE_PATH", str(tmp / "cache.sqlite"))
    # The real ledger is committed project state; tests must never append to it.
    monkeypatch.setenv("SLOPWATCH_LEDGER_PATH", str(tmp / "ledger.jsonl"))
    monkeypatch.setenv("SLOPWATCH_FIXTURES_DIR", str(tmp / "fixtures"))


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any request that reaches a real transport fails the test immediately."""

    def blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"real network access in a test: {request.url.host}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


@pytest.fixture
def memory_cache() -> Iterator[Cache]:
    with Cache(":memory:") as cache:
        yield cache
