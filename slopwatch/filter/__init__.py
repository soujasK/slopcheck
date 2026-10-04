"""Filter search results for agents. Three lines::

    from slopwatch.filter import filter_results
    clean = filter_results("best sip to invest in 2026", serp["organic_results"])
    # each kept result has result["slopwatch"] = {slop_risk, band, reasons, not_scored}

``filter_results`` fetches each result page (robots.txt respected, cached). For
agent frameworks, use ``slopwatch.filter.serpapi_tools.web_search()``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from slopwatch.cache import Cache
from slopwatch.config import CacheMode, Settings
from slopwatch.filter.core import Assessment, Mode, SlopFilter
from slopwatch.http import HttpClient, user_agent
from slopwatch.pages import PageFetcher

__all__ = ["Assessment", "SlopFilter", "filter_results", "live_filter", "offline_filter"]


def live_filter(cache_path: Path | None = None, contact_url: str | None = None) -> SlopFilter:
    """A filter that fetches result pages (cached in SQLite, robots-aware)."""
    settings = Settings()
    cache = Cache(cache_path or settings.cache_path, mode=CacheMode.LIVE)
    http = HttpClient(
        cache,
        timeout=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        agent=user_agent(contact_url or settings.contact_url),
    )
    return SlopFilter.live(PageFetcher(http, max_bytes=settings.page_max_bytes))


def offline_filter() -> SlopFilter:
    """A filter over the committed measurement data (no network)."""
    return SlopFilter.offline()


def filter_results(
    query: str,
    results: Sequence[Mapping[str, Any]],
    *,
    threshold: float | None = None,
    mode: Mode = "drop",
    slop_filter: SlopFilter | None = None,
) -> list[dict[str, Any]]:
    """Annotate results with SlopWatch scores and drop likely slop.

    ``threshold`` defaults to the rubric's ``low`` band (the evaluated operating
    point); ``mode="annotate"`` keeps everything and only adds scores.
    """
    f = slop_filter or live_filter()
    return f.apply(query, results, threshold=threshold, mode=mode)
