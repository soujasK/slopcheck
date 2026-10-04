"""SQLite-backed HTTP response cache with live / record / replay modes.

Copied from Zero Hour and trimmed (findings store and spend table removed; the
credit ledger now lives in ``serp.ProjectLedger``).

Every outbound request (SerpApi, robots.txt, page fetches) is keyed by
``sha256(method, url, sorted params, as_of[, body])``. Secret-bearing parameters
are stripped *before* hashing and storage, so cache files and exported fixtures
never contain credentials and keys are stable across different API keys.

Bodies are stored gzip-compressed. Fixtures are exported as one JSON file per
entry (diffable, reviewable) and loaded back into an in-memory cache for replay.
They are produced by ``export_dir`` from a ``record`` run and must not be
hand-edited.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any

from slopwatch.config import CacheMode

SECRET_PARAM_NAMES = frozenset({"api_key", "apikey", "key", "token", "access_token"})
SECRET_HEADER_NAMES = frozenset({"authorization", "x-api-key", "cookie", "set-cookie"})
# Bodies above this size are exported gzip+base64 instead of as text.
EXPORT_TEXT_LIMIT = 100_000
# Only these response headers are persisted; nothing else is needed downstream.
KEPT_HEADER_NAMES = frozenset({"content-type", "date", "last-modified"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    method     TEXT NOT NULL,
    url        TEXT NOT NULL,
    params     TEXT NOT NULL,
    as_of      TEXT,
    status     INTEGER NOT NULL,
    headers    TEXT NOT NULL,
    body       BLOB NOT NULL,
    cost       INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);
"""


class CacheMiss(LookupError):
    """Raised in replay mode when a request has no stored response."""


def redact_params(params: Mapping[str, Any] | None) -> dict[str, str]:
    """Drop secret parameters and normalise values to strings."""
    if not params:
        return {}
    return {
        str(k): str(v)
        for k, v in params.items()
        if str(k).lower() not in SECRET_PARAM_NAMES and v is not None
    }


def request_key(
    method: str,
    url: str,
    params: Mapping[str, Any] | None = None,
    as_of: date | None = None,
    body: bytes | None = None,
) -> str:
    """Deterministic cache key. Param order and secret params do not affect it."""
    payload: dict[str, Any] = {
        "method": method.upper(),
        "url": url,
        "params": sorted(redact_params(params).items()),
        "as_of": as_of.isoformat() if as_of else None,
    }
    if body is not None:
        payload["body_sha256"] = hashlib.sha256(body).hexdigest()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CachedResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    fetched_at: datetime
    from_cache: bool
    cost: int = 0

    def json(self) -> Any:
        return json.loads(self.body)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _filter_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        k.lower(): v
        for k, v in headers.items()
        if k.lower() in KEPT_HEADER_NAMES and k.lower() not in SECRET_HEADER_NAMES
    }


class Cache:
    def __init__(
        self,
        path: Path | str = ":memory:",
        mode: CacheMode = CacheMode.LIVE,
        ttl_seconds: int = 24 * 3600,
        cross_thread: bool = False,
    ) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.mode = mode
        self.ttl = timedelta(seconds=ttl_seconds)
        # cross_thread: the connection may be used from another thread, never concurrently
        # (e.g. a single-threaded local server running off the main thread).
        self._db = sqlite3.connect(str(path), check_same_thread=not cross_thread)
        # Keys read or written through this instance (for minimal fixture exports).
        self.used: set[str] = set()
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # -- context management -------------------------------------------------
    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- reads ----------------------------------------------------------------
    def get(self, key: str) -> CachedResponse | None:
        """Raw read, ignoring mode and TTL."""
        self.used.add(key)
        row = self._db.execute(
            "SELECT status, headers, body, fetched_at, cost FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        status, headers, body, fetched_at, cost = row
        return CachedResponse(
            status=int(status),
            headers=json.loads(headers),
            body=gzip.decompress(body),
            fetched_at=datetime.fromisoformat(fetched_at),
            from_cache=True,
            cost=int(cost),
        )

    def lookup(self, key: str, *, as_of: date | None = None) -> CachedResponse | None:
        """Mode-aware read used by the HTTP layer.

        Returns a response to serve, or None meaning "go to the network".
        Raises CacheMiss in replay mode when nothing is stored.
        """
        if self.mode is CacheMode.RECORD:
            return None
        hit = self.get(key)
        if self.mode is CacheMode.REPLAY:
            if hit is None:
                raise CacheMiss(f"no recorded response for request {key[:12]}")
            return hit
        if hit is None:
            return None
        # Historical (as_of-pinned) responses never go stale; current ones expire.
        if as_of is not None and as_of < datetime.now(UTC).date():
            return hit
        if datetime.now(UTC) - hit.fetched_at <= self.ttl:
            return hit
        return None

    def __len__(self) -> int:
        (n,) = self._db.execute("SELECT COUNT(*) FROM responses").fetchone()
        return int(n)

    # -- writes ---------------------------------------------------------------
    def put(
        self,
        key: str,
        *,
        method: str,
        url: str,
        params: Mapping[str, Any] | None,
        as_of: date | None,
        status: int,
        headers: Mapping[str, str],
        body: bytes,
        cost: int = 0,
        fetched_at: datetime | None = None,
    ) -> None:
        self.used.add(key)
        self._db.execute(
            "INSERT OR REPLACE INTO responses "
            "(key, method, url, params, as_of, status, headers, body, cost, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                method.upper(),
                url,
                json.dumps(redact_params(params), sort_keys=True),
                as_of.isoformat() if as_of else None,
                status,
                json.dumps(_filter_headers(headers), sort_keys=True),
                gzip.compress(body, mtime=0),
                cost,
                (fetched_at or datetime.now(UTC)).isoformat(),
            ),
        )
        self._db.commit()

    def set_cost(self, key: str, cost: int) -> None:
        self._db.execute("UPDATE responses SET cost = ? WHERE key = ?", (cost, key))
        self._db.commit()

    # -- fixtures ---------------------------------------------------------------
    def export_dir(self, directory: Path, *, only: set[str] | None = None) -> int:
        """Write stored responses as ``<key>.json`` (all, or just ``only``)."""
        directory.mkdir(parents=True, exist_ok=True)
        rows = [
            row
            for row in self._db.execute(
                "SELECT key, method, url, params, as_of, status, headers, body, cost, fetched_at "
                "FROM responses ORDER BY key"
            ).fetchall()
            if only is None or row[0] in only
        ]
        for key, method, url, params, as_of, status, headers, body, cost, fetched_at in rows:
            raw = gzip.decompress(body)
            entry: dict[str, Any] = {
                "key": key,
                "method": method,
                "url": url,
                "params": json.loads(params),
                "as_of": as_of,
                "status": status,
                "headers": json.loads(headers),
                "cost": cost,
                "fetched_at": fetched_at,
            }
            text: str | None = None
            if len(raw) <= EXPORT_TEXT_LIMIT:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
            if text is not None:
                entry["body_text"] = text
            else:
                entry["body_gz_b64"] = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
            (directory / f"{key}.json").write_text(
                json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return len(rows)

    def import_dir(self, directory: Path) -> int:
        count = 0
        for file in sorted(directory.glob("*.json")):
            entry = json.loads(file.read_text(encoding="utf-8"))
            if "body_text" in entry:
                body = entry["body_text"].encode("utf-8")
            elif "body_gz_b64" in entry:
                body = gzip.decompress(base64.b64decode(entry["body_gz_b64"]))
            else:
                body = base64.b64decode(entry["body_b64"])
            self.put(
                entry["key"],
                method=entry["method"],
                url=entry["url"],
                params=entry["params"],
                as_of=date.fromisoformat(entry["as_of"]) if entry["as_of"] else None,
                status=entry["status"],
                headers=entry["headers"],
                body=body,
                cost=entry.get("cost", 0),
                fetched_at=datetime.fromisoformat(entry["fetched_at"]),
            )
            count += 1
        return count

    @classmethod
    def from_fixtures(cls, directory: Path) -> Cache:
        """In-memory replay cache populated from an exported fixture directory."""
        cache = cls(":memory:", mode=CacheMode.REPLAY)
        cache.import_dir(directory)
        return cache
