"""Observatory statistics on SYNTHETIC rows and scores."""

from __future__ import annotations

import pytest

from slopwatch.measure import compare, low_shares, per_query_low
from slopwatch.models import Score, SerpRow


def row(qid: str, engine: str, rank: int, url: str) -> SerpRow:
    return SerpRow(
        query_id=qid, engine=engine, locale="IN", rank=rank, url=url, domain="d",
        title="t", snippet="s", request_hash=f"{qid}{engine}",
    )  # fmt: skip


def sc(url: str, band: str) -> Score:
    return Score.model_validate({"url": url, "slop_risk": 0.5, "band": band, "reasons": []})


def build() -> tuple[list[SerpRow], dict[str, Score]]:
    rows, scores = [], {}
    for q in range(10):
        for rank in range(1, 5):
            for engine, low_ranks in (("google", {1, 2}), ("duckduckgo", {1})):
                url = f"https://{engine}.example/{q}/{rank}"
                rows.append(row(f"q{q}", engine, rank, url))
                if rank != 4:  # rank 4 is unscored everywhere
                    scores[url] = sc(url, "low" if rank in low_ranks else "ok")
    return rows, scores


def test_low_shares_with_coverage_bounds_and_ci() -> None:
    rows, scores = build()
    shares = {s.group: s for s in low_shares(rows, scores, key=lambda r: (r.engine,))}
    g = shares[("google",)]
    assert (g.n_rows, g.n_scored, g.coverage) == (40, 30, 0.75)
    assert g.low.value == pytest.approx(20 / 30)
    assert g.bounds == (20 / 40, 30 / 40)  # unscored all ok / all low
    assert g.low.low <= g.low.value <= g.low.high
    d = shares[("duckduckgo",)]
    assert d.low.value == pytest.approx(10 / 30) and d.corrected is None


def test_prevalence_correction_applied() -> None:
    rows, scores = build()
    (s,) = low_shares(
        [r for r in rows if r.engine == "google"], scores, key=lambda r: ("all",),
        sensitivity=0.8, specificity=0.9,
    )  # fmt: skip
    assert s.corrected == pytest.approx((20 / 30 + 0.9 - 1) / 0.7)


def test_rank_grouping_and_empty_groups() -> None:
    rows, scores = build()
    by_rank = {s.group: s for s in low_shares(rows, scores, key=lambda r: (str(r.rank),))}
    assert by_rank[("1",)].low.value == 1.0
    assert by_rank[("4",)].n_scored == 0 and by_rank[("4",)].coverage == 0.0
    assert by_rank[("4",)].bounds == (0.0, 1.0)


def test_paired_compare_engines() -> None:
    rows, scores = build()
    g = [r for r in rows if r.engine == "google"]
    d = [r for r in rows if r.engine == "duckduckgo"]
    assert per_query_low(g, scores)["q0"] == pytest.approx(2 / 3)
    diff = compare(g, d, scores)
    assert diff.n_pairs == 10
    assert diff.diff.value == pytest.approx(1 / 3)
    assert diff.p_value < 0.01
