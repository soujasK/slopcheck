"""The single outbound-HTTP path (copied from Zero Hour). Every request is routed
through ``Cache``.

Retries transient failures (transport errors, 429, 5xx) with exponential
backoff, enforces timeouts and a response size cap, and never logs secrets.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

import httpx

from slopwatch import __version__
from slopwatch.cache import Cache, CachedResponse, redact_params, request_key
from slopwatch.config import CacheMode

log = logging.getLogger(__name__)
# httpx/httpcore log full request URLs (incl. query-string API keys) at INFO/DEBUG.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

USER_AGENT = f"slopwatch/{__version__} (research; one fetch per page; respects robots.txt)"


def user_agent(contact: str | None) -> str:
    """Some sites (e.g. Wikimedia) refuse crawlers whose UA carries no contact."""
    if not contact:
        return USER_AGENT
    return f"slopwatch/{__version__} (+{contact}; research; respects robots.txt)"


RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Transient or credential-dependent answers are never cached.
UNCACHEABLE_STATUSES = frozenset({401, 407, 429})


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NetworkDisabled(HttpError):
    """A non-cacheable request was attempted in replay mode."""


class ResponseTooLarge(HttpError):
    pass


def safe_url(url: str, params: Mapping[str, Any] | None = None) -> str:
    """URL for logs and errors: host + path + non-secret params only."""
    parts = urlsplit(url)
    shown = redact_params(params)
    query = "&".join(f"{k}={v}" for k, v in sorted(shown.items()))
    return f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{query}" if query else "")


class HttpClient:
    def __init__(
        self,
        cache: Cache,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        agent: str = USER_AGENT,
    ) -> None:
        self.cache = cache
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": agent},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- public API -------------------------------------------------------------
    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        as_of: date | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
        store: bool = True,
    ) -> CachedResponse:
        return self.request(
            "GET",
            url,
            params=params,
            as_of=as_of,
            headers=headers,
            max_bytes=max_bytes,
            store=store,
        )

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        as_of: date | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> CachedResponse:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        merged = {"Content-Type": "application/json", **(headers or {})}
        return self.request("POST", url, body=body, as_of=as_of, headers=merged)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: bytes | None = None,
        as_of: date | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
        store: bool = True,
    ) -> CachedResponse:
        """Cache-routed request.

        ``store=False`` is for requests whose responses must never be persisted
        (e.g. account metadata); they still pass through this layer and are
        refused in replay mode.
        """
        key = request_key(method, url, params, as_of, body)
        if store:
            hit = self.cache.lookup(key, as_of=as_of)
            if hit is not None:
                log.debug("cache hit %s %s", method, safe_url(url, params))
                return hit
        elif self.cache.mode is CacheMode.REPLAY:
            raise NetworkDisabled(f"network disabled in replay mode: {safe_url(url, params)}")

        resp = self._send(method, url, params=params, body=body, headers=headers)
        content = self._read_capped(resp, max_bytes)
        result = CachedResponse(
            status=resp.status_code,
            headers=dict(resp.headers),
            body=content,
            fetched_at=datetime.now(UTC),
            from_cache=False,
        )
        # Stable answers (incl. 404 / 403) are cached so replays see the same world;
        # server errors and auth/rate-limit responses are not.
        if store and resp.status_code < 500 and resp.status_code not in UNCACHEABLE_STATUSES:
            self.cache.put(
                key,
                method=method,
                url=url,
                params=params,
                as_of=as_of,
                status=result.status,
                headers=result.headers,
                body=content,
                fetched_at=result.fetched_at,
            )
        return result

    # -- internals ------------------------------------------------------------
    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        body: bytes | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        shown = safe_url(url, params)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                delay = self.backoff_base * (2 ** (attempt - 1))
                log.info("retry %d/%d for %s in %.1fs", attempt, self.max_retries, shown, delay)
                self._sleep(delay)
            try:
                req = self._client.build_request(
                    method, url, params=dict(params or {}), content=body, headers=headers
                )
                resp = self._client.send(req, stream=True)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                resp.close()
                last_error = HttpError(f"HTTP {resp.status_code} from {shown}", resp.status_code)
                continue
            return resp
        # Exception text can embed the full URL (and its secrets); report the type only.
        reason = last_error if isinstance(last_error, HttpError) else type(last_error).__name__
        raise HttpError(f"request failed after retries: {shown}: {reason}") from None

    @staticmethod
    def _read_capped(resp: httpx.Response, max_bytes: int | None) -> bytes:
        try:
            if max_bytes is None:
                return resp.read()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ResponseTooLarge(f"response exceeds {max_bytes} bytes", resp.status_code)
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            resp.close()
