"""Query relevance: does the page address *this* query?

Coverage = share of the query's content words (lowercased, stopwords removed)
that appear in the page's title + H1-H3 headings, and in the first 5,000
characters of its main text. Deterministic and explainable ("the page's title
mentions 1 of 4 query terms"). Relevance depends on the (page, query) pair, so
it is stored per SERP row, never per page.
"""

from __future__ import annotations

import re

from slopwatch.signals.base import ParsedPage
from slopwatch.signals.thin import main_text

TEXT_WINDOW = 5000
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "best",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "should",
        "the",
        "to",
        "what",
        "when",
        "which",
        "why",
        "with",
        "without",
        "you",
        "your",
        "vs",
        "versus",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")


def terms(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) > 1 and t not in STOPWORDS}


def coverage(query: str, text: str) -> float:
    q = terms(query)
    if not q:
        return 1.0
    return round(len(q & terms(text)) / len(q), 4)


def relevance(query: str, page: ParsedPage) -> tuple[float, float]:
    """``(title_coverage, text_coverage)`` of the query by this page."""
    head = " ".join([page.title, *(text for _, text in page.headings)])
    return coverage(query, head), coverage(query, main_text(page)[:TEXT_WINDOW])
