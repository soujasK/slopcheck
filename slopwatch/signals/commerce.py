"""Outbound commerce-link ratio and the "best X" listicle pattern."""

from __future__ import annotations

import re

from slopwatch.signals.affiliate import is_affiliate
from slopwatch.signals.base import ParsedPage
from slopwatch.signals.lists import DomainLists, host_matches

# "10 Best ...", "Best smartphones under 20000", "Top 7 ...", "Top-rated ..."
_BEST_TITLE = re.compile(r"\b(best|top)\b(?!\s+(?:of|up|off|stories|news)\b)", re.IGNORECASE)
_COUNT_IN_TITLE = re.compile(r"\b\d{1,2}\s+(best|top)\b|\b(best|top)\s+\d{1,2}\b", re.IGNORECASE)
# "1. Samsung Galaxy...", "#3 Boat Airdopes", "2) ...", "No. 4 ..."
_NUMBERED_HEADING = re.compile(r"^\s*(#\s?\d{1,2}|no\.\s?\d{1,2}|\d{1,2}\s?[.):-])\s*\S")
MIN_NUMBERED_HEADINGS = 3


def ratio(page: ParsedPage, lists: DomainLists) -> tuple[int, float]:
    """``(outbound_links, commerce_ratio)``. Affiliate links count as commerce."""
    outbound = page.outbound()
    if not outbound:
        return 0, 0.0
    n = sum(
        1 for link in outbound if host_matches(link.host, lists.shops) or is_affiliate(link, lists)
    )
    return len(outbound), round(n / len(outbound), 4)


def is_listicle(page: ParsedPage) -> bool:
    """A "best X" title/H1 that is also structured as a ranked list: either the
    title states a count ("10 best") or at least 3 numbered H2/H3 headings."""
    h1 = next((text for tag, text in page.headings if tag == "h1"), "")
    titles = [t for t in (page.title, h1) if t]
    if not any(_BEST_TITLE.search(t) for t in titles):
        return False
    if any(_COUNT_IN_TITLE.search(t) for t in titles):
        return True
    numbered = sum(
        1 for tag, text in page.headings if tag in {"h2", "h3"} and _NUMBERED_HEADING.match(text)
    )
    return numbered >= MIN_NUMBERED_HEADINGS
