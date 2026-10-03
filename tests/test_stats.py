from __future__ import annotations

import pytest

from slopwatch.stats import (
    Interval,
    bootstrap_ci,
    cohen_kappa,
    paired_diff,
    rogan_gladen,
    wilson,
)


def test_wilson_matches_reference_values() -> None:
    # Reference: 8/10 -> Wilson 95% [0.490, 0.943]
    ci = wilson(8, 10)
    assert ci.value == 0.8
    assert ci.low == pytest.approx(0.4902, abs=1e-3)
    assert ci.high == pytest.approx(0.9433, abs=1e-3)
    assert wilson(0, 0) == Interval(0.0, 0.0, 1.0)
    assert wilson(0, 20).low == 0.0 and wilson(20, 20).high == 1.0
    assert ci.fmt() == "0.80 [0.49, 0.94]" and wilson(1, 2).pct().startswith("50% [")


def share(xs: list[int]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def test_cluster_bootstrap_is_seeded_and_brackets_point() -> None:
    clusters = [[1, 0, 0], [1, 1, 0], [0, 0, 0], [1, 1, 1], [0, 1, 0]]
    a = bootstrap_ci(clusters, share)
    assert a == bootstrap_ci(clusters, share)
    assert a.low <= a.value <= a.high and a.value == pytest.approx(7 / 15)
    assert a.high - a.low > 0.1
    assert bootstrap_ci([[1, 0]], share) == Interval(0.5, 0.5, 0.5)


def test_rogan_gladen() -> None:
    # perfect classifier: apparent = true
    assert rogan_gladen(0.3, 1.0, 1.0) == pytest.approx(0.3)
    # known case: true 0.2, sens 0.8, spec 0.9 -> apparent 0.16 + 0.08 = 0.24
    assert rogan_gladen(0.24, 0.8, 0.9) == pytest.approx(0.2)
    assert rogan_gladen(0.3, 0.5, 0.5) is None
    assert rogan_gladen(0.01, 0.8, 0.9) == 0.0  # clipped


def test_paired_diff_detects_shift_and_null() -> None:
    shifted = [(0.5 + i * 0.01, 0.2 + i * 0.01) for i in range(20)]
    d = paired_diff(shifted)
    assert d.n_pairs == 20 and d.diff.value == pytest.approx(0.3)
    assert d.diff.low > 0 and d.p_value < 0.01
    null = [(0.3, 0.4), (0.4, 0.3), (0.2, 0.2), (0.5, 0.4), (0.4, 0.5)]
    assert paired_diff(null).p_value > 0.5
    assert paired_diff([]).n_pairs == 0


def test_cohen_kappa() -> None:
    assert cohen_kappa(["ok", "low", "ok"], ["ok", "low", "ok"]) == 1.0
    # textbook: 20 items, 15 agree, marginals 50/50 -> (0.75-0.5)/0.5 = 0.5
    a = ["y"] * 10 + ["n"] * 10
    b = ["y"] * 7 + ["n"] * 3 + ["y"] * 2 + ["n"] * 8
    assert cohen_kappa(a, b) == pytest.approx((0.75 - 0.5) / 0.5)
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["ok", "ok"], ["ok", "ok"]) is None  # chance agreement = 1
    with pytest.raises(ValueError, match="same length"):
        cohen_kappa(["ok"], [])
