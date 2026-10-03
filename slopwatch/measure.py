"""Observatory statistics: low-quality shares with honest uncertainty.

Every share is reported with:

* ``n`` scored rows and ``coverage`` (scored rows / all rows in the group),
* a 95% cluster-bootstrap interval, clustering by query (results on one SERP
  are not independent),
* worst/best-case ``bounds`` if every unscored row were low / ok,
* optionally a prevalence-corrected value (Rogan-Gladen) using the scorer's
  sensitivity and specificity measured on held-out labels.

Engine and locale comparisons use the same queries on both sides, so they are
paired by query.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from slopwatch.models import Score, SerpRow
from slopwatch.stats import Interval, PairedDiff, bootstrap_ci, paired_diff, rogan_gladen

Group = tuple[str, ...]


@dataclass(frozen=True)
class Share:
    group: Group
    n_rows: int  # all rows in the group
    n_scored: int
    low: Interval  # share of scored rows in the low band, with 95% CI
    bounds: tuple[float, float]  # (all unscored ok, all unscored low)
    corrected: float | None = None  # Rogan-Gladen, if sensitivity/specificity given

    @property
    def coverage(self) -> float:
        return self.n_scored / self.n_rows if self.n_rows else 0.0


def _share_low(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def low_shares(
    rows: list[SerpRow],
    scores: dict[str, Score],
    key: Callable[[SerpRow], Group],
    *,
    sensitivity: float | None = None,
    specificity: float | None = None,
) -> list[Share]:
    """Share of low-band results per group (e.g. per engine x locale)."""
    groups: dict[Group, list[SerpRow]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    out: list[Share] = []
    for group in sorted(groups):
        members = groups[group]
        by_query: dict[str, list[bool]] = defaultdict(list)
        for row in members:
            score = scores.get(row.url)
            if score is not None:
                by_query[row.query_id].append(score.band == "low")
        clusters = [by_query[q] for q in sorted(by_query)]
        flags = [f for c in clusters for f in c]
        n_rows, n_scored, n_low = len(members), len(flags), sum(flags)
        ci = bootstrap_ci(clusters, _share_low)
        bounds = (n_low / n_rows, (n_low + n_rows - n_scored) / n_rows) if n_rows else (0.0, 0.0)
        corrected = None
        if sensitivity is not None and specificity is not None and flags:
            corrected = rogan_gladen(ci.value, sensitivity, specificity)
        out.append(Share(group, n_rows, n_scored, ci, bounds, corrected))
    return out


def per_query_low(rows: list[SerpRow], scores: dict[str, Score]) -> dict[str, float]:
    by_query: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        score = scores.get(row.url)
        if score is not None:
            by_query[row.query_id].append(score.band == "low")
    return {q: _share_low(f) for q, f in by_query.items() if f}


def compare(rows_a: list[SerpRow], rows_b: list[SerpRow], scores: dict[str, Score]) -> PairedDiff:
    """Paired difference in per-query low share, A minus B, over shared queries."""
    a, b = per_query_low(rows_a, scores), per_query_low(rows_b, scores)
    shared = sorted(a.keys() & b.keys())
    return paired_diff([(a[q], b[q]) for q in shared])
