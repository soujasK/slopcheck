from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from slopwatch.cache import Cache, CacheMiss, redact_params, request_key
from slopwatch.config import CacheMode

URL = "https://example.test/search.json"


def _put(cache: Cache, key: str, body: bytes = b'{"ok": true}', **kw: object) -> None:
    cache.put(
        key,
        method="GET",
        url=URL,
        params={"q": "x", "api_key": "SECRET"},
        as_of=kw.get("as_of"),  # type: ignore[arg-type]
        status=200,
        headers={"Content-Type": "application/json", "Set-Cookie": "s=1", "X-Other": "y"},
        body=body,
        fetched_at=kw.get("fetched_at"),  # type: ignore[arg-type]
    )


def test_key_is_order_independent_and_ignores_secrets() -> None:
    a = request_key("GET", URL, {"q": "npm", "engine": "google", "api_key": "one"})
    b = request_key("get", URL, {"engine": "google", "q": "npm", "api_key": "two"})
    assert a == b
    assert a == request_key("GET", URL, {"engine": "google", "q": "npm"})


def test_key_varies_with_as_of_params_and_body() -> None:
    base = request_key("GET", URL, {"q": "npm"})
    assert base != request_key("GET", URL, {"q": "npm"}, as_of=date(2025, 9, 8))
    assert base != request_key("GET", URL, {"q": "pypi"})
    assert request_key("POST", URL, body=b"a") != request_key("POST", URL, body=b"b")


def test_redact_params_drops_secrets_and_none() -> None:
    assert redact_params({"q": 1, "API_KEY": "s", "token": "t", "x": None}) == {"q": "1"}
    assert redact_params(None) == {}


def test_roundtrip_compresses_and_filters_headers(memory_cache: Cache) -> None:
    body = b'{"payload": "' + b"a" * 5000 + b'"}'
    _put(memory_cache, "k1", body)
    hit = memory_cache.get("k1")
    assert hit is not None
    assert hit.body == body
    assert hit.json()["payload"].startswith("aaa")
    assert hit.from_cache
    assert hit.headers == {"content-type": "application/json"}
    stored, params = memory_cache._db.execute("SELECT body, params FROM responses").fetchone()
    assert len(stored) < len(body) / 10
    assert json.loads(params) == {"q": "x"}
    assert "SECRET" not in "\n".join(memory_cache._db.iterdump())


def test_replay_miss_raises() -> None:
    with Cache(":memory:", mode=CacheMode.REPLAY) as cache, pytest.raises(CacheMiss):
        cache.lookup("missing")


def test_record_mode_always_misses(memory_cache: Cache) -> None:
    _put(memory_cache, "k")
    memory_cache.mode = CacheMode.RECORD
    assert memory_cache.lookup("k") is None


def test_live_ttl_and_historical_pinning(memory_cache: Cache) -> None:
    stale = datetime.now(UTC) - timedelta(days=3)
    _put(memory_cache, "fresh")
    _put(memory_cache, "stale", fetched_at=stale)
    _put(memory_cache, "historical", fetched_at=stale, as_of=date(2025, 9, 8))
    assert memory_cache.lookup("fresh") is not None
    assert memory_cache.lookup("stale") is None
    assert memory_cache.lookup("historical", as_of=date(2025, 9, 8)) is not None
    assert memory_cache.lookup("nope") is None


def test_export_import_fixture_roundtrip(memory_cache: Cache, tmp_path: Path) -> None:
    _put(memory_cache, "text", as_of=date(2025, 9, 8))
    _put(memory_cache, "binary", body=b"\xff\xfe\x00binary")
    memory_cache.set_cost("text", 1)
    assert memory_cache.export_dir(tmp_path) == 2
    exported = (tmp_path / "text.json").read_text(encoding="utf-8")
    assert "SECRET" not in exported
    assert json.loads(exported)["body_text"] == '{"ok": true}'

    with Cache.from_fixtures(tmp_path) as replay:
        assert replay.mode is CacheMode.REPLAY
        assert len(replay) == 2
        text = replay.lookup("text")
        binary = replay.lookup("binary")
        assert text is not None and text.cost == 1
        assert binary is not None and binary.body == b"\xff\xfe\x00binary"


def test_file_backed_cache_creates_parent(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "cache.sqlite"
    with Cache(path) as cache:
        _put(cache, "k")
    with Cache(path) as reopened:
        assert len(reopened) == 1


def test_export_only_used_keys(tmp_path: Path) -> None:
    with Cache(tmp_path / "c.sqlite") as cache:
        _put(cache, "a")
        _put(cache, "b")
    with Cache(tmp_path / "c.sqlite") as cache:
        assert cache.used == set()
        cache.get("a")
        assert cache.export_dir(tmp_path / "out", only=cache.used) == 1
    assert [p.stem for p in (tmp_path / "out").glob("*.json")] == ["a"]
