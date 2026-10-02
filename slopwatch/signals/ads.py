"""Ad and tracker load: distinct listed domains referenced by the static HTML."""

from __future__ import annotations

from slopwatch.signals.base import ParsedPage, host_of
from slopwatch.signals.lists import DomainLists


def _listed_domain(host: str, domains: frozenset[str]) -> str | None:
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in domains:
            return candidate
    return None


def count(page: ParsedPage, lists: DomainLists) -> int:
    """Distinct ad/tracker domains in <script src>, <iframe src> and inline scripts."""
    found: set[str] = set()
    for src in page.script_srcs + page.iframe_srcs:
        hit = _listed_domain(host_of(src), lists.ad_domains)
        if hit:
            found.add(hit)
    inline = page.inline_scripts.lower()
    if inline:
        found.update(d for d in lists.ad_domains if d not in found and d in inline)
    return len(found)
