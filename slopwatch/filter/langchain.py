"""LangChain integration: a search tool that returns SlopWatch-filtered results.

For LangChain agents, the simplest path is SerpApi's own tooling, which already
creates native LangChain tools: ``slopwatch.filter.serpapi_tools.web_search()``.
This module adds a dependency-light alternative for code that uses
``langchain_community.utilities.SerpAPIWrapper`` directly::

    from slopwatch.filter.langchain import filtered_results
    results = filtered_results(SerpAPIWrapper(), "best sip to invest in 2026")

Requires ``langchain-community`` (optional).
"""

from __future__ import annotations

from typing import Any, Protocol

from slopwatch.filter.core import Mode, SlopFilter


class _Wrapper(Protocol):
    def results(self, query: str) -> dict[str, Any]: ...


def filtered_results(
    wrapper: _Wrapper,
    query: str,
    *,
    slop_filter: SlopFilter | None = None,
    threshold: float | None = None,
    mode: Mode = "drop",
) -> list[dict[str, Any]]:
    """Run ``wrapper.results(query)`` (SerpAPIWrapper's raw-results method) and
    return its organic results, scored and filtered by SlopWatch."""
    if slop_filter is None:
        from slopwatch.filter import live_filter

        slop_filter = live_filter()
    raw = wrapper.results(query)
    organic = raw.get("organic_results") or []
    return slop_filter.apply(query, organic, threshold=threshold, mode=mode)
