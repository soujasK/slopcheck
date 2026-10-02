"""Main-text length and boilerplate ratio.

Main text is the visible text inside <article>/<main> when the page marks one up
with at least ``MIN_MAIN_CHARS``; otherwise it is all visible text minus
nav/header/footer/aside. boilerplate_ratio is the share of visible text that is
not main text.
"""

from __future__ import annotations

from slopwatch.signals.base import ParsedPage

MIN_MAIN_CHARS = 200


def main_text(page: ParsedPage) -> str:
    if len(page.main_text) >= MIN_MAIN_CHARS:
        return page.main_text
    return page.content_text


def stats(page: ParsedPage) -> tuple[int, float]:
    """``(main_text_len, boilerplate_ratio)``."""
    total = len(page.text)
    if total == 0:
        return 0, 0.0
    main_len = min(len(main_text(page)), total)
    return main_len, round(1 - main_len / total, 4)
