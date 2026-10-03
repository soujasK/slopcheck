"""Small, dependency-free statistics for defensible reporting.

* ``wilson``         95% CI for a proportion (precision, recall, shares).
* ``bootstrap_ci``   percentile CI for a statistic, resampling whole clusters
                     (queries), because results within one SERP are not
                     independent.
* ``rogan_gladen``   prevalence corrected for a classifier's measured
                     sensitivity and specificity.
* ``paired_diff``    paired bootstrap CI and permutation p-value for a
                     difference between two engines/locales on the same queries.
* ``cohen_kappa``    agreement between two labelings beyond chance.

All randomness is seeded, so every reported interval is reproducible.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import TypeVar

Z95 = 1.959963984540054
DEFAULT_RESAMPLES = 2000
T = TypeVar("T")


@dataclass(frozen=True)
class Interval:
    value: float
    low: float
    high: float

    def fmt(self, digits: int = 2) -> str:
        return f"{self.value:.{digits}f} [{self.low:.{digits}f}, {self.high:.{digits}f}]"

    def pct(self) -> str:
        return f"{self.value:.0%} [{self.low:.0%}, {self.high:.0%}]"


def wilson(successes: int, n: int, z: float = Z95) -> Interval:
    if n == 0:
        return Interval(0.0, 0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(p, max(0.0, centre - half), min(1.0, centre + half))


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = q * (len(sorted_values) - 1)
    lo, hi = math.floor(idx), math.ceil(idx)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def bootstrap_ci(
    clusters: Sequence[Sequence[T]],
    statistic: Callable[[list[T]], float],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 2026,
) -> Interval:
    """Cluster bootstrap: resample clusters with replacement, pool their items."""
    pooled = [x for c in clusters for x in c]
    point = statistic(pooled)
    if len(clusters) < 2:
        return Interval(point, point, point)
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not crypto
    stats = []
    for _ in range(resamples):
        sample = [x for _ in clusters for x in clusters[rng.randrange(len(clusters))]]
        stats.append(statistic(sample))
    stats.sort()
    return Interval(point, _percentile(stats, 0.025), _percentile(stats, 0.975))


def rogan_gladen(apparent: float, sensitivity: float, specificity: float) -> float | None:
    """True prevalence from an imperfect classifier; None when the classifier is
    no better than chance (sensitivity + specificity <= 1)."""
    youden = sensitivity + specificity - 1
    if youden <= 0:
        return None
    return min(1.0, max(0.0, (apparent + specificity - 1) / youden))


@dataclass(frozen=True)
class PairedDiff:
    diff: Interval  # mean(a - b) over paired clusters
    p_value: float  # two-sided sign-flip permutation test
    n_pairs: int


def paired_diff(
    pairs: Sequence[tuple[float, float]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 2026,
) -> PairedDiff:
    """``pairs`` = (a, b) per shared query, e.g. low share on engine A vs B."""
    diffs = [a - b for a, b in pairs]
    n = len(diffs)
    if n == 0:
        return PairedDiff(Interval(0.0, 0.0, 0.0), 1.0, 0)
    mean = sum(diffs) / n
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not crypto
    boot = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    extreme = 0
    for _ in range(resamples):
        flipped = sum(d if rng.random() < 0.5 else -d for d in diffs) / n
        if abs(flipped) >= abs(mean) - 1e-12:
            extreme += 1
    return PairedDiff(
        Interval(mean, _percentile(boot, 0.025), _percentile(boot, 0.975)),
        round((extreme + 1) / (resamples + 1), 4),
        n,
    )


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    """Agreement beyond chance; None if undefined (no items, or chance = 1)."""
    if len(a) != len(b):
        raise ValueError("labelings must be the same length")
    n = len(a)
    if n == 0:
        return None
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    cats = set(a) | set(b)
    expected = sum((list(a).count(c) / n) * (list(b).count(c) / n) for c in cats)
    if expected >= 1:
        return None
    return round((observed - expected) / (1 - expected), 4)
