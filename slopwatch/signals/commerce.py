"""Outbound commerce-link ratio, the "best X" listicle pattern, and whether the
page's own site sells directly."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

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


# The page's own site sells: cart / checkout links, buy buttons, product markup.
# Catches first-party "content marketing" (a shop's blog ranking for an
# informational query), which affiliate detection cannot see because the shop
# links to itself.
_CART_PATH = re.compile(r"/(cart|checkout|basket|my-cart|add-to-cart)(/|$)", re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"/(products?|shop|store|collections)/", re.IGNORECASE)
_BUY_PHRASES = ("add to cart", "add to bag", "buy now")
_PRODUCT_TYPES = frozenset({"Product", "Offer", "AggregateOffer", "ProductGroup"})
MIN_PRODUCT_LINKS = 3


def _types(node: dict[str, object]) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return {str(x) for x in t}
    return set()


def sells_directly(page: ParsedPage) -> bool:
    same = page.same_site()
    if any(_CART_PATH.search(urlsplit(link.href).path) for link in same):
        return True
    if (
        sum(1 for link in same if _PRODUCT_PATH.search(urlsplit(link.href).path))
        >= MIN_PRODUCT_LINKS
    ):
        return True
    text = page.text.lower()
    if any(phrase in text for phrase in _BUY_PHRASES):
        return True
    return any(_types(node) & _PRODUCT_TYPES for node in page.jsonld_nodes())
