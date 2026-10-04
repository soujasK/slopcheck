"""Narrative page ("story"): the project told in a few sentences and visuals.

Data comes only from committed files (the same numbers as the observatory), is
embedded as JSON, and the page draws itself with inline JS/SVG. ``build_story``
writes a full HTML document; ``story_fragment`` returns the page body only
(for hosts that add their own document skeleton).
"""

from __future__ import annotations

import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from slopwatch.filter.core import SlopFilter
from slopwatch.models import Page, RelevanceRecord, SerpRow, SignalRecord
from slopwatch.platform import load_platforms
from slopwatch.report.observatory import compute
from slopwatch.score import load_rubric, score_rows
from slopwatch.store import PAGES, RELEVANCE, SERPS, SIGNALS, read_jsonl

GROUPS = (("google", "IN", "Google India"), ("duckduckgo", "IN", "DuckDuckGo India"),
          ("yahoo", "IN", "Yahoo India"), ("google", "US", "Google US"))  # fmt: skip
HERO_QUERY_ID = "health-04"


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def story_data(root: Path) -> dict[str, Any]:
    data = root / "data"
    rows = read_jsonl(data / SERPS, SerpRow)
    records = read_jsonl(data / SIGNALS, SignalRecord)
    relevance = read_jsonl(data / RELEVANCE, RelevanceRecord)
    pages = {p.url: p for p in read_jsonl(data / PAGES, Page)}
    platforms = load_platforms(data)
    scores = score_rows(rows, records, relevance, load_rubric(data / "rubric.yaml"))
    numbers = compute(root)

    def status(r: SerpRow) -> str:
        if platforms.kind(r.url):
            return "platform"
        s = scores.get((r.url, r.query_id))
        if s is None:
            return "blocked"
        return "slop" if s.band == "low" else "clean"

    grid = []
    for engine, locale, name in GROUPS:
        group = sorted(
            (r for r in rows if r.engine == engine and r.locale == locale),
            key=lambda r: (r.query_id, r.rank),
        )
        counts = Counter(status(r) for r in group)
        grid.append({"name": name, "cells": [status(r)[0] for r in group], "counts": dict(counts)})

    hero_rows = sorted(
        (
            r
            for r in rows
            if r.query_id == HERO_QUERY_ID and r.engine == "google" and r.locale == "IN"
        ),
        key=lambda r: r.rank,
    )
    query = next(r for r in rows if r.query_id == HERO_QUERY_ID)
    from slopwatch.queries import load_plan

    query_text = {s.id: s.text for s in load_plan(data / "queries.yaml").specs}[query.query_id]
    hero = []
    for a, r in zip(
        SlopFilter.offline(data).assess(query_text, [r.url for r in hero_rows]),
        hero_rows,
        strict=True,
    ):
        hero.append(
            {
                "rank": r.rank,
                "domain": _domain(r.url),
                "title": r.title,
                "band": a.band,
                "not_scored": a.not_scored,
                "reasons": list(a.reasons),
            }
        )

    refused = sum(
        1
        for p in pages.values()
        if p.unscored_reason == "robots_blocked"
        or (p.unscored_reason == "http_error" and p.status == 403)
    )
    pay_per_crawl = sum(1 for p in pages.values() if p.status == 402)
    demo_path = root / "report" / "demo.json"
    demo = json.loads(demo_path.read_text(encoding="utf-8")) if demo_path.exists() else []

    return {
        "query": query_text,
        "hero": hero,
        "grid": grid,
        "n_searches": numbers["n_searches"],
        "n_rows": numbers["n_rows"],
        "n_pages": len(pages),
        "overall": numbers["overall_india"],
        "by_engine": numbers["by_engine"],
        "india_vs_us": numbers["india_vs_us"],
        "comparisons": numbers["comparisons"],
        "ai_overview": numbers["ai_overview"],
        "platform_share": {k: v["share"] for k, v in numbers["platform_share"].items()},
        "refused_share": refused / len(pages),
        "pay_per_crawl": pay_per_crawl,
        "validation": numbers["validation"],
        "demo": {
            "n": len(demo),
            "dropped": sum(1 for d in demo if d["dropped"]),
            "changed": sum(1 for d in demo if d["changed"]),
        },
        "collected": numbers["collected"],
    }


def _template() -> str:
    return resources.files("slopwatch.report").joinpath("story.html").read_text(encoding="utf-8")


def story_fragment(root: Path) -> str:
    payload = json.dumps(story_data(root), ensure_ascii=False).replace("</", "<\\/")
    return _template().replace("__STORY_DATA__", payload)


def build_story(root: Path, out: Path) -> Path:
    body = story_fragment(root)
    doc = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        "</head><body>\n" + body + "\n</body></html>\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8", newline="\n")
    return out
