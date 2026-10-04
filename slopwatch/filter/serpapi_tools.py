"""SlopWatch for SerpApi's official agent tooling (``serpapi-search-tools``).

``serpapi_search_tools.web_search()`` builds a native search tool for 14 agent
frameworks (OpenAI Agents SDK, LangChain, LangGraph, CrewAI, LlamaIndex, Claude
Agent SDK, Google ADK, ...) and accepts any ``client`` with
``search(params) -> dict``. :class:`SlopWatchClient` wraps the real SerpApi
client and scores ``organic_results`` before the tool formats them, so::

    from slopwatch.filter.serpapi_tools import web_search   # instead of serpapi_search_tools
    tools = [web_search()]

gives an agent search results with likely slop removed and every remaining
result annotated with ``slopwatch: {slop_risk, band, reasons, not_scored}``.
Only JSON output can be filtered, so ``response_format`` is forced to JSON.

Requires the optional dependency: ``pip install slopwatch[agents]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from slopwatch.filter.core import Mode, SlopFilter


class SearchClient(Protocol):
    def search(self, params: dict[str, Any]) -> Mapping[str, Any] | str: ...


class SlopWatchClient:
    """A ``serpapi-search-tools`` search client that filters organic results."""

    def __init__(
        self,
        inner: SearchClient | None = None,
        *,
        slop_filter: SlopFilter,
        threshold: float | None = None,
        mode: Mode = "drop",
        api_key: str | None = None,
    ) -> None:
        if inner is None:
            import serpapi

            inner = serpapi.Client(api_key=api_key) if api_key else serpapi.Client()
        self.inner = inner
        self.slop_filter = slop_filter
        self.threshold = threshold
        self.mode: Mode = mode

    def search(self, params: dict[str, Any]) -> Mapping[str, Any]:
        if params.get("output") == "md":
            raise ValueError("SlopWatch filters JSON results; use response_format='json'")
        raw = self.inner.search(params)
        if not isinstance(raw, Mapping):
            raise TypeError("SlopWatch needs JSON (mapping) results from the SerpApi client")
        result = dict(raw)
        query = str(params.get("q") or params.get("p") or "")
        organic = result.get("organic_results")
        if isinstance(organic, list):
            kept = self.slop_filter.apply(query, organic, threshold=self.threshold, mode=self.mode)
            result["organic_results"] = kept
            result["slopwatch"] = {
                "dropped": len(organic) - len(kept),
                "threshold": self.slop_filter.threshold(self.threshold),
                "rubric_version": self.slop_filter.rubric.version,
            }
        return result


def web_search(
    *,
    slop_filter: SlopFilter | None = None,
    threshold: float | None = None,
    mode: Mode = "drop",
    client: SearchClient | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> Any:
    """Drop-in for ``serpapi_search_tools.web_search`` with SlopWatch filtering.

    ``slop_filter`` defaults to a live filter (fetches result pages). All other
    keyword arguments go to ``serpapi_search_tools.web_search``.
    """
    from serpapi_search_tools import SearchResultFormat
    from serpapi_search_tools import web_search as _web_search

    fmt = kwargs.pop("response_format", SearchResultFormat.JSON)
    if SearchResultFormat(fmt) is not SearchResultFormat.JSON:
        raise ValueError("SlopWatch filters JSON results; use response_format='json'")
    if slop_filter is None:
        from slopwatch.filter import live_filter

        slop_filter = live_filter()
    wrapped = SlopWatchClient(
        client, slop_filter=slop_filter, threshold=threshold, mode=mode, api_key=api_key
    )
    return _web_search(client=wrapped, response_format=SearchResultFormat.JSON, **kwargs)
