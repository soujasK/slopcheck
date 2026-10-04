"""Fit rubric weights on development labels (transparent, deterministic).

Procedure (declared in ANALYSIS_PLAN.md before it was run):

1. Each candidate rule is a yes/no condition on Signals (``CANDIDATES``).
2. An L2-regularised logistic regression is fitted on the development items
   (plain batch gradient descent, fixed iterations: fully deterministic).
3. A rule's weight is its positive coefficient divided by the sum of positive
   coefficients; rules with non-positive coefficients are dropped. The score is
   still the capped sum of fired-rule weights, so every score keeps its reasons.
4. The ``low`` threshold is chosen by 5-fold cross-validation (folds fixed by
   seed): among thresholds with out-of-fold precision >= ``MIN_PRECISION``, the
   one with the best out-of-fold F1; if none, the highest out-of-fold precision
   among thresholds flagging at least ``MIN_FLAGGED`` items. ``mixed`` = half of it.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from slopwatch.models import Signals

MIN_PRECISION = 0.70
MIN_FLAGGED = 10
L2 = 1.0
ITERATIONS = 1500
LEARNING_RATE = 0.5
FOLDS = 5
FOLD_SEED = 2026


@dataclass(frozen=True)
class Candidate:
    id: str
    conditions: tuple[dict[str, object], ...]  # rubric YAML conditions (all must hold)
    reason: str
    test: Callable[[Signals], bool]


def _cov_below(field: str, limit: float) -> Callable[[Signals], bool]:
    def test(s: Signals) -> bool:
        value = getattr(s, field)
        return value is not None and value < limit

    return test


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "no_author",
        ({"signal": "has_author", "eq": False},),
        "no named author",
        lambda s: not s.has_author,
    ),
    Candidate(
        "anonymous",
        ({"signal": "has_author", "eq": False}, {"signal": "has_date", "eq": False}),
        "no author or date",
        lambda s: not s.has_author and not s.has_date,
    ),
    Candidate(
        "sells_directly",
        ({"signal": "sells_directly", "eq": True},),
        "the site sells products on this page (cart, buy button or product markup)",
        lambda s: s.sells_directly,
    ),
    Candidate(
        "title_off_query",
        ({"signal": "query_title_coverage", "lt": 0.5},),
        "title and headings cover {query_title_coverage:.0%} of the query's words",
        _cov_below("query_title_coverage", 0.5),
    ),
    Candidate(
        "text_off_query",
        ({"signal": "query_text_coverage", "lt": 0.6},),
        "main text covers {query_text_coverage:.0%} of the query's words",
        _cov_below("query_text_coverage", 0.6),
    ),
    Candidate(
        "thin",
        ({"signal": "text_len", "lt": 1500},),
        "thin main text ({text_len} chars)",
        lambda s: s.text_len < 1500,
    ),
    Candidate(
        "ad_heavy",
        ({"signal": "ad_scripts", "gte": 8},),
        "{ad_scripts} ad/tracker domains loaded",
        lambda s: s.ad_scripts >= 8,
    ),
    Candidate(
        "affiliate_present",
        ({"signal": "affiliate_links", "gte": 1},),
        "contains affiliate links ({affiliate_links})",
        lambda s: s.affiliate_links >= 1,
    ),
    Candidate(
        "listicle",
        ({"signal": "listicle", "eq": True},),
        "'best X' listicle pattern",
        lambda s: s.listicle,
    ),
    Candidate(
        "no_about_contact",
        ({"signal": "has_about_contact", "eq": False},),
        "no about or contact page linked",
        lambda s: not s.has_about_contact,
    ),
    Candidate(
        "near_duplicate",
        ({"signal": "near_dup_group", "set": True},),
        "near-duplicate of a page on another domain in the same results",
        lambda s: s.near_dup_group is not None,
    ),
)


def features(s: Signals) -> list[float]:
    return [1.0 if c.test(s) else 0.0 for c in CANDIDATES]


def fit_logistic(x: Sequence[Sequence[float]], y: Sequence[int]) -> tuple[list[float], float]:
    """L2-regularised logistic regression by batch gradient descent."""
    n, d = len(x), len(x[0]) if x else 0
    w, b = [0.0] * d, 0.0
    for _ in range(ITERATIONS):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(x, y, strict=True):
            z = b + sum(wj * xj for wj, xj in zip(w, xi, strict=True))
            p = 1.0 / (1.0 + math.exp(-max(min(z, 35.0), -35.0)))
            err = p - yi
            gb += err
            for j in range(d):
                gw[j] += err * xi[j]
        for j in range(d):
            w[j] -= LEARNING_RATE * (gw[j] / n + L2 * w[j] / n)
        b -= LEARNING_RATE * gb / n
    return w, b


def rule_weights(coefs: Sequence[float]) -> list[float]:
    positive = [max(0.0, c) for c in coefs]
    total = sum(positive)
    return [round(c / total, 4) if total else 0.0 for c in positive]


def risk(weights: Sequence[float], feats: Sequence[float]) -> float:
    return min(1.0, sum(w * f for w, f in zip(weights, feats, strict=True)))


@dataclass(frozen=True)
class FitResult:
    weights: list[float]
    coefficients: list[float]
    low: float
    oof_precision: float
    oof_recall: float
    oof_f1: float
    oof_flagged: int
    met_min_precision: bool


def _prf(scores: Sequence[float], y: Sequence[int], t: float) -> tuple[float, float, float, int]:
    flagged = [s >= t for s in scores]
    tp = sum(1 for f, yi in zip(flagged, y, strict=True) if f and yi)
    fp = sum(1 for f, yi in zip(flagged, y, strict=True) if f and not yi)
    fn = sum(1 for f, yi in zip(flagged, y, strict=True) if not f and yi)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1, tp + fp


def fit_rubric(signals: Sequence[Signals], y: Sequence[int]) -> FitResult:
    x = [features(s) for s in signals]
    order = list(range(len(x)))
    random.Random(FOLD_SEED).shuffle(order)  # noqa: S311 - reproducible folds, not crypto
    oof = [0.0] * len(x)
    for k in range(FOLDS):
        held = set(order[k::FOLDS])
        train = [i for i in range(len(x)) if i not in held]
        coefs, _ = fit_logistic([x[i] for i in train], [y[i] for i in train])
        weights = rule_weights(coefs)
        for i in held:
            oof[i] = risk(weights, x[i])
    thresholds = sorted({round(s, 4) for s in oof if s > 0})
    stats = [(t, *_prf(oof, y, t)) for t in thresholds]
    ok = [s for s in stats if s[1] >= MIN_PRECISION and s[4] > 0]
    if ok:
        best = max(ok, key=lambda s: (s[3], s[1], -s[0]))
        met = True
    else:
        enough = [s for s in stats if s[4] >= MIN_FLAGGED] or stats
        best = max(enough, key=lambda s: (s[1], s[3], -s[0]))
        met = False
    coefs, _ = fit_logistic(x, y)
    t, p, r, f1, flagged = best
    return FitResult(
        rule_weights(coefs),
        [round(c, 4) for c in coefs],
        t,
        round(p, 4),
        round(r, 4),
        round(f1, 4),
        flagged,
        met,
    )


def rubric_yaml(result: FitResult, *, version: int, note: str) -> str:
    """Rubric v3 in the standard rubric format (frozen)."""
    lines = [f"# {line}" for line in note.splitlines()]
    lines += [
        "",
        f"version: {version}",
        "status: frozen",
        "",
        "bands:",
        f"  low: {result.low}",
        f"  mixed: {round(result.low / 2, 4)}",
        "",
        "rules:",
    ]
    for cand, weight in zip(CANDIDATES, result.weights, strict=True):
        if weight <= 0:
            continue
        lines += [f"  - id: {cand.id}", f"    weight: {weight}", "    all:"]
        for cond in cand.conditions:
            ((op, val),) = ((k, v) for k, v in cond.items() if k != "signal")
            shown = str(val).lower() if isinstance(val, bool) else val
            lines.append(f"      - {{signal: {cond['signal']}, {op}: {shown}}}")
        lines.append(f'    reason: "{cand.reason}"')
        lines.append("")
    return "\n".join(lines) + "\n"
