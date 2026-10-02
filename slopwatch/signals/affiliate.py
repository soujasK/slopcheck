"""Affiliate link count and density.

density = affiliate links / outbound links (unique URLs). A link is an affiliate
link if it goes through a known affiliate network or shortener, carries a
network-specific tracking parameter (Amazon ``tag=``, Flipkart ``affid=``...), a
generic affiliate parameter, ``utm_medium=affiliate``, or ``rel="sponsored"``.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from slopwatch.signals.base import Link, ParsedPage
from slopwatch.signals.lists import DomainLists, host_matches


def is_affiliate(link: Link, lists: DomainLists) -> bool:
    if "sponsored" in link.rel:
        return True
    if host_matches(link.host, lists.affiliate_hosts):
        return True
    params = dict(parse_qsl(urlsplit(link.href).query, keep_blank_values=False))
    if not params:
        return False
    for rule in lists.affiliate_param_rules:
        if host_matches(link.host, rule.hosts) and rule.params & params.keys():
            return True
    if lists.affiliate_generic_params & params.keys():
        return True
    return params.get("utm_medium", "").lower() in lists.affiliate_utm_mediums


def count(page: ParsedPage, lists: DomainLists) -> tuple[int, float]:
    """``(affiliate_links, affiliate_density)``."""
    outbound = page.outbound()
    if not outbound:
        return 0, 0.0
    n = sum(1 for link in outbound if is_affiliate(link, lists))
    return n, round(n / len(outbound), 4)
