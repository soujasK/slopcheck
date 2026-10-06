"""SlopWatch filter: score search results and annotate or drop likely slop.

Signals are deterministic and every score carries its reasons. Pages come from
one of two sources:

* **live**: each result page is fetched (robots.txt respected, cached) and its
  signals and query relevance are extracted on the spot;
* **offline**: the committed measurement data (data/signals.jsonl,
  data/relevance.jsonl) is used, so the demo and tests run with no network.

Platform pages (video, forum, social, app store, shop) and pages that cannot
be fetched are never dropped: they are annotated with why they were not scored.

Accuracy (EVAL.md): on held-out results labeled by two LLMs, the rubric's
``low`` band has moderate precision; treat a drop as "probably not a source to
ground on", not as a verdict about the site.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from slopwatch.config import REPO_ROOT
from slopwatch.models import Band, RelevanceRecord, SignalRecord, Signals
from slopwatch.pages import PageFetcher, make_excerpt
from slopwatch.platform import PlatformList, load_platforms
from slopwatch.queries import load_plan
from slopwatch.score import Rubric, load_rubric, score
from slopwatch.signals import DomainLists, duplicate, extract, load_lists
from slopwatch.signals.base import parse_page
from slopwatch.signals.relevance import relevance
from slopwatch.store import PAGES, RELEVANCE, SIGNALS, read_jsonl

DATA_DIR = REPO_ROOT / "data"
AGENT_TEXT_CHARS = 1500
Mode = Literal["drop", "annotate"]


@dataclass(frozen=True)
class Assessment:
    url: str
    slop_risk: float | None  # None when not scored
    band: Band | None
    reasons: tuple[str, ...] = ()
    not_scored: str | None = None  # why not: "platform:video", "robots_blocked", ...

    def as_dict(self) -> dict[str, Any]:
        return {
            "slop_risk": self.slop_risk,
            "band": self.band,
            "reasons": list(self.reasons),
            "not_scored": self.not_scored,
        }


@dataclass
class _PageFacts:
    signals: Signals | None
    simhash: int | None
    reason: str | None  # not-scored reason
    title_cov: float | None = None
    text_cov: float | None = None


@dataclass
class SlopFilter:
    """Score and filter search results with the frozen rubric (data/rubric.yaml)."""

    rubric: Rubric
    lists: DomainLists
    platforms: PlatformList
    fetcher: PageFetcher | None = None
    _offline_signals: dict[str, SignalRecord] = field(default_factory=dict)
    _offline_relevance: dict[tuple[str, str], RelevanceRecord] = field(default_factory=dict)
    _offline_unscored: dict[str, str] = field(default_factory=dict)
    # <=300-char main-text excerpt per page (what an agent would read); filled as pages
    # are assessed live, or from data/pages.jsonl offline.
    excerpts: dict[str, str] = field(default_factory=dict)
    # Live mode only: up to AGENT_TEXT_CHARS of main text for an agent to read; kept in
    # memory for this process, never written to committed data.
    agent_texts: dict[str, str] = field(default_factory=dict)
    _query_ids: dict[str, str] = field(default_factory=dict)

    # -- construction ------------------------------------------------------------
    @classmethod
    def offline(cls, data_dir: Path = DATA_DIR) -> SlopFilter:
        """Use the committed measurement data; no network."""
        f = cls._base(data_dir)
        f._offline_signals = {r.url: r for r in read_jsonl(data_dir / SIGNALS, SignalRecord)}
        f._offline_relevance = {
            (r.url, r.query_id): r for r in read_jsonl(data_dir / RELEVANCE, RelevanceRecord)
        }
        from slopwatch.models import Page

        pages = read_jsonl(data_dir / PAGES, Page)
        f._offline_unscored = {p.url: p.unscored_reason for p in pages if p.unscored_reason}
        f.excerpts = {p.url: p.excerpt for p in pages if p.excerpt}
        f._query_ids = {s.text.lower(): s.id for s in load_plan(data_dir / "queries.yaml").specs}
        return f

    @classmethod
    def live(cls, fetcher: PageFetcher, data_dir: Path = DATA_DIR) -> SlopFilter:
        """Fetch each result page (robots-aware, cached) and score it."""
        f = cls._base(data_dir)
        f.fetcher = fetcher
        return f

    @classmethod
    def _base(cls, data_dir: Path) -> SlopFilter:
        return cls(
            rubric=load_rubric(data_dir / "rubric.yaml"),
            lists=load_lists(data_dir),
            platforms=load_platforms(data_dir),
        )

    # -- scoring ----------------------------------------------------------------
    def _facts(self, query: str, url: str) -> _PageFacts:
        kind = self.platforms.kind(url)
        if kind is not None:
            return _PageFacts(None, None, f"platform:{kind}")
        if self.fetcher is not None:
            fetched = self.fetcher.fetch(url)
            if fetched.html is None:
                return _PageFacts(None, None, fetched.page.unscored_reason or "fetch_failed")
            ex = extract(url, fetched.html, self.lists)
            self.excerpts[url] = make_excerpt(ex.main_text)
            self.agent_texts[url] = " ".join(ex.main_text.split())[:AGENT_TEXT_CHARS]
            title_cov, text_cov = relevance(query, parse_page(url, fetched.html))
            return _PageFacts(ex.signals, ex.simhash, None, title_cov, text_cov)
        rec = self._offline_signals.get(url)
        if rec is None:
            return _PageFacts(None, None, self._offline_unscored.get(url, "not_recorded"))
        qid = self._query_ids.get(query.lower())
        rel = self._offline_relevance.get((url, qid)) if qid else None
        return _PageFacts(
            rec.signals,
            int(rec.simhash, 16),
            None,
            rel.title_coverage if rel else None,
            rel.text_coverage if rel else None,
        )

    def assess(self, query: str, urls: Sequence[str]) -> list[Assessment]:
        facts = {url: self._facts(query, url) for url in dict.fromkeys(urls)}
        dup_items = [
            duplicate.DupItem("set", url, f.simhash, f.signals.text_len)
            for url, f in facts.items()
            if f.signals is not None and f.simhash is not None
        ]
        groups = duplicate.groups(dup_items)
        out: list[Assessment] = []
        for url in urls:
            f = facts[url]
            if f.signals is None:
                out.append(Assessment(url, None, None, (), f.reason))
                continue
            sig = f.signals.model_copy(
                update={
                    "near_dup_group": groups.get(url),
                    "query_title_coverage": f.title_cov,
                    "query_text_coverage": f.text_cov,
                }
            )
            s = score(url, sig, self.rubric)
            out.append(Assessment(url, s.slop_risk, s.band, tuple(s.reasons)))
        return out

    def threshold(self, threshold: float | None) -> float:
        """Default: the rubric's ``low`` band, the evaluated operating point."""
        return self.rubric.bands.low if threshold is None else threshold

    def apply(
        self,
        query: str,
        results: Sequence[Mapping[str, Any]],
        *,
        threshold: float | None = None,
        mode: Mode = "drop",
        link_key: str = "link",
    ) -> list[dict[str, Any]]:
        """Return results annotated with ``slopwatch``; in ``drop`` mode, results
        with slop_risk >= threshold are removed. Unscored results are kept."""
        cut = self.threshold(threshold)
        urls = [str(r.get(link_key) or "") for r in results]
        assessments = self.assess(query, [u for u in urls if u])
        by_url = {a.url: a for a in assessments}
        kept: list[dict[str, Any]] = []
        for result, url in zip(results, urls, strict=True):
            a = by_url.get(url, Assessment(url, None, None, (), "no_link"))
            annotated = {**result, "slopwatch": a.as_dict()}
            if mode == "drop" and a.slop_risk is not None and a.slop_risk >= cut:
                continue
            kept.append(annotated)
        return kept
