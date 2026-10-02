"""Collection and fetch steps, independent of the CLI so they are testable.

collect:  frozen query plan -> SerpApi -> SerpRow (top 10 organic) + SerpMeta
fetch:    unique SERP URLs -> robots-aware page fetch -> Page + SignalRecord

Every SERP row ends up with either a SignalRecord or a Page carrying an explicit
``unscored_reason``; nothing is guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from slopwatch.cache import CacheMiss
from slopwatch.models import Page, SerpMeta, SerpRow, SignalRecord
from slopwatch.pages import PageFetcher, make_excerpt
from slopwatch.queries import Job, Plan, to_rows
from slopwatch.serp import SerpClient, SerpError
from slopwatch.signals import DomainLists, extract

log = logging.getLogger(__name__)


# -- collect ---------------------------------------------------------------------


@dataclass(frozen=True)
class CollectPreview:
    total: int
    cached: int
    to_spend: int


def preview(plan: Plan, serp: SerpClient) -> CollectPreview:
    """How many searches would reach SerpApi (cost a credit) right now."""
    to_spend = sum(1 for job in plan.jobs if serp.would_spend(job.engine, job.params))
    return CollectPreview(len(plan.jobs), len(plan.jobs) - to_spend, to_spend)


@dataclass
class CollectResult:
    rows: list[SerpRow] = field(default_factory=list)
    meta: list[SerpMeta] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)
    done: int = 0
    # Set when collection stopped early (cap reached, SerpApi error, replay miss).
    error: str | None = None


def collect(
    plan: Plan, serp: SerpClient, *, progress: Callable[[int, Job], None] | None = None
) -> CollectResult:
    result = CollectResult()
    for i, job in enumerate(plan.jobs, start=1):
        try:
            page = serp.search(job.engine, job.params)
        except (SerpError, CacheMiss) as exc:
            result.error = f"{job.query.id}/{job.engine}/{job.query.locale}: {exc}"
            break
        result.rows.extend(to_rows(page, job.query))
        result.meta.append(
            SerpMeta(
                query_id=job.query.id,
                engine=job.engine,
                locale=job.query.locale,
                request_hash=page.request_hash,
                n_organic=len(page.organic),
                features=page.features,
                fetched_at=page.fetched_at,
            )
        )
        result.keys.add(page.request_hash)
        result.done = i
        if progress:
            progress(i, job)
    return result


# -- fetch -----------------------------------------------------------------------


@dataclass
class FetchResult:
    pages: list[Page] = field(default_factory=list)
    records: list[SignalRecord] = field(default_factory=list)


def unique_urls(rows: list[SerpRow]) -> list[str]:
    return sorted({row.url for row in rows})


def fetch_pages(
    urls: list[str],
    fetcher: PageFetcher,
    lists: DomainLists,
    *,
    progress: Callable[[int, Page], None] | None = None,
) -> FetchResult:
    out = FetchResult()
    for i, url in enumerate(urls, start=1):
        fetched = fetcher.fetch(url)
        page = fetched.page
        if fetched.html is not None and page.html_hash is not None:
            try:
                ex = extract(url, fetched.html, lists)
            except Exception:  # one malformed page must not stop a 600-page run
                log.exception("signal extraction failed for %s", url)
                page = page.model_copy(update={"unscored_reason": "parse_failed"})
            else:
                # The labeling excerpt comes from the main text, not nav/footer.
                page = page.model_copy(update={"excerpt": make_excerpt(ex.main_text)})
                out.records.append(
                    SignalRecord(
                        url=url,
                        html_hash=page.html_hash,
                        signals=ex.signals,
                        simhash=f"{ex.simhash:016x}",
                    )
                )
        out.pages.append(page)
        if progress:
            progress(i, page)
    return out


def coverage_gaps(rows: list[SerpRow], pages: list[Page], records: list[SignalRecord]) -> list[str]:
    """URLs in the SERPs that have neither signals nor an explicit unscored reason."""
    scored = {r.url for r in records}
    explained = {p.url for p in pages if p.unscored_reason is not None}
    return sorted({row.url for row in rows} - scored - explained)
