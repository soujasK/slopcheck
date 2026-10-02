"""Deterministic, explainable page signals. No AI-text detection, by design."""

from __future__ import annotations

from dataclasses import dataclass

from slopwatch.models import Signals
from slopwatch.signals import ads, affiliate, authorship, commerce, duplicate, thin
from slopwatch.signals.base import ParsedPage, parse_page
from slopwatch.signals.lists import DomainLists, load_lists

__all__ = ["DomainLists", "Extracted", "ParsedPage", "extract", "load_lists", "parse_page"]


@dataclass(frozen=True)
class Extracted:
    signals: Signals  # near_dup_group is None here; set across a SERP set later
    simhash: int
    title: str
    main_text: str


def extract(url: str, html: str, lists: DomainLists) -> Extracted:
    page = parse_page(url, html)
    aff_links, aff_density = affiliate.count(page, lists)
    outbound, commerce_ratio = commerce.ratio(page, lists)
    has_author, has_date, has_about = authorship.check(page)
    text_len, boilerplate = thin.stats(page)
    main = thin.main_text(page)
    signals = Signals(
        affiliate_links=aff_links,
        affiliate_density=aff_density,
        outbound_links=outbound,
        commerce_ratio=commerce_ratio,
        listicle=commerce.is_listicle(page),
        ad_scripts=ads.count(page, lists),
        has_author=has_author,
        has_date=has_date,
        has_about_contact=has_about,
        text_len=text_len,
        boilerplate_ratio=boilerplate,
    )
    return Extracted(signals, duplicate.simhash(main), page.title, main)
