from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from slopwatch.cache import Cache
from slopwatch.config import CacheMode
from slopwatch.http import (
    USER_AGENT,
    HttpClient,
    HttpError,
    NetworkDisabled,
    ResponseTooLarge,
    safe_url,
    user_agent,
)
from tests.conftest import Recorder, make_client, no_network

URL = "https://api.example.test/v1/thing"


def test_retries_transient_then_succeeds() -> None:
    statuses = iter([503, 429, 200])
    rec = Recorder(lambda r: httpx.Response(next(statuses), json={"ok": True}))
    with make_client(rec) as http:
        resp = http.get(URL, {"q": "x"})
    assert resp.status == 200
    assert len(rec.requests) == 3


def test_retries_transport_errors_then_gives_up_without_leaking_secret() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    rec = Recorder(boom)
    with make_client(rec, max_retries=2) as http, pytest.raises(HttpError) as err:
        http.get(URL, {"q": "x", "api_key": "TOPSECRET"})
    assert len(rec.requests) == 3
    assert "TOPSECRET" not in str(err.value)
    assert "ConnectError" in str(err.value)


def test_does_not_retry_client_errors_or_cache_auth_failures() -> None:
    rec = Recorder(lambda r: httpx.Response(401, text="nope"))
    with make_client(rec) as http:
        assert http.get(URL).status == 401
        assert http.get(URL).status == 401
        assert len(http.cache) == 0
    assert len(rec.requests) == 2


def test_stable_404_is_cached_for_replay() -> None:
    rec = Recorder(lambda r: httpx.Response(404, text="missing"))
    with make_client(rec) as http:
        http.get(URL)
        assert http.get(URL).from_cache
    assert len(rec.requests) == 1


def test_cache_hit_skips_network() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json={"n": 1}))
    with make_client(rec) as http:
        first = http.get(URL, {"q": "x", "api_key": "a"})
        second = http.get(URL, {"api_key": "b", "q": "x"})
    assert not first.from_cache and second.from_cache
    assert second.json() == {"n": 1}
    assert len(rec.requests) == 1


def test_api_key_is_sent_but_never_stored() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json={}))
    with make_client(rec) as http:
        http.get(URL, {"q": "x", "api_key": "TOPSECRET"})
        assert rec.requests[0].url.params["api_key"] == "TOPSECRET"
        assert "TOPSECRET" not in "\n".join(http.cache._db.iterdump())


def test_post_json_keys_on_body() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=json.loads(r.content)))
    with make_client(rec) as http:
        a = http.post_json(URL, {"pkg": "a"}, as_of=date(2025, 9, 8))
        b = http.post_json(URL, {"pkg": "b"}, as_of=date(2025, 9, 8))
        a2 = http.post_json(URL, {"pkg": "a"}, as_of=date(2025, 9, 8))
    assert a.json() == {"pkg": "a"} and b.json() == {"pkg": "b"}
    assert a2.from_cache
    assert len(rec.requests) == 2
    assert rec.requests[0].headers["content-type"] == "application/json"


def test_max_bytes_enforced() -> None:
    rec = Recorder(lambda r: httpx.Response(200, content=b"x" * 5000))
    with make_client(rec) as http, pytest.raises(ResponseTooLarge):
        http.get(URL, max_bytes=1000)
    with make_client(rec) as http:
        assert len(http.get(URL, max_bytes=10_000).body) == 5000


def test_replay_mode_never_touches_network() -> None:
    with make_client(no_network, mode=CacheMode.REPLAY) as http:
        with pytest.raises(LookupError):
            http.get(URL)
        with pytest.raises(NetworkDisabled):
            http.get(URL, store=False)


def test_store_false_bypasses_cache() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json={}))
    with make_client(rec, cache=Cache(":memory:")) as http:
        http.get(URL, store=False)
        http.get(URL, store=False)
        assert len(http.cache) == 0
    assert len(rec.requests) == 2


def test_safe_url_hides_secrets() -> None:
    shown = safe_url("https://serpapi.com/search.json", {"q": "npm", "api_key": "S"})
    assert shown == "https://serpapi.com/search.json?q=npm"
    assert safe_url("https://x.test/a") == "https://x.test/a"


def test_user_agent_carries_contact() -> None:
    assert user_agent(None) == USER_AGENT
    ua = user_agent("https://github.com/someone/slopwatch")
    assert ua.startswith("slopwatch/") and "+https://github.com/someone/slopwatch" in ua
    rec = Recorder(lambda r: httpx.Response(200))
    with HttpClient(Cache(":memory:"), transport=httpx.MockTransport(rec), agent=ua) as http:
        http.get(URL)
    assert rec.requests[0].headers["user-agent"] == ua


def test_body_read_timeout_is_retried_then_reported() -> None:
    class StallingStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"<html>"
            raise httpx.ReadTimeout("stalled")

    calls = iter([StallingStream(), None])

    def handler(request: httpx.Request) -> httpx.Response:
        stream = next(calls)
        if stream is None:
            return httpx.Response(200, content=b"<html>ok</html>")
        return httpx.Response(200, stream=stream)

    rec = Recorder(handler)
    with make_client(rec, max_retries=1) as http:
        assert http.get(URL, max_bytes=10_000).body == b"<html>ok</html>"
    assert len(rec.requests) == 2

    def always_stall(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=StallingStream())

    with (
        make_client(Recorder(always_stall), max_retries=1) as http,
        pytest.raises(HttpError, match="ReadTimeout"),
    ):
        http.get(URL, max_bytes=10_000)


def test_cache_url_hides_secret_path_from_cache_and_errors() -> None:
    secret_url = "https://api.example.test/accounts/SECRETACCT/ai/run/model"
    public = "https://api.example.test/accounts/{account}/ai/run/model"
    rec = Recorder(lambda r: httpx.Response(200, json={"ok": 1}))
    with make_client(rec) as http:
        http.post_json(secret_url, {"q": 1}, cache_url=public)
        again = http.post_json(secret_url, {"q": 1}, cache_url=public)
        dump = " ".join(http.cache._db.iterdump())
    assert again.from_cache and len(rec.requests) == 1
    assert "SECRETACCT" in str(rec.requests[0].url)  # the real URL is used on the wire
    assert "SECRETACCT" not in dump and "{account}" in dump

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with make_client(Recorder(boom), max_retries=0) as http, pytest.raises(HttpError) as err:
        http.post_json(secret_url, {"q": 2}, cache_url=public)
    assert "SECRETACCT" not in str(err.value)
