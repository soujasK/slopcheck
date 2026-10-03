"""Rubric engine tests on SYNTHETIC signals (no measurement data is scored here)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slopwatch.config import REPO_ROOT
from slopwatch.models import SerpRow, SignalRecord, Signals
from slopwatch.score import RubricError, load_rubric, score, score_all, with_near_dups
from slopwatch.signals import duplicate

RUBRIC = REPO_ROOT / "data" / "rubric.yaml"


def sig(**kw: object) -> Signals:
    base: dict[str, object] = {
        "affiliate_links": 0, "affiliate_density": 0.0, "outbound_links": 10,
        "commerce_ratio": 0.0, "listicle": False, "ad_scripts": 0, "has_author": True,
        "has_date": True, "has_about_contact": True, "text_len": 5000,
        "boilerplate_ratio": 0.2, "near_dup_group": None,
    }  # fmt: skip
    base.update(kw)
    return Signals.model_validate(base)


def test_real_rubric_loads() -> None:
    rubric = load_rubric(RUBRIC)
    assert rubric.bands.low > rubric.bands.mixed
    assert len(rubric.rules) >= 5


def test_clean_page_is_ok_with_no_reasons() -> None:
    s = score("u", sig(), load_rubric(RUBRIC))
    assert (s.slop_risk, s.band, s.reasons) == (0.0, "ok", [])


def test_affiliate_listicle_is_low_with_reasons() -> None:
    s = score(
        "u",
        sig(
            affiliate_links=14, affiliate_density=0.21, outbound_links=20, commerce_ratio=0.6,
            listicle=True, ad_scripts=12, has_author=False, has_date=False,
        ),
        load_rubric(RUBRIC),
    )  # fmt: skip
    assert s.band == "low" and s.slop_risk == 1.0  # capped
    assert "14 affiliate links (density 0.21)" in s.reasons
    assert "no author or date" in s.reasons
    assert "60% of 20 outbound links go to shops" in s.reasons


def test_commerce_needs_enough_links() -> None:
    rubric = load_rubric(RUBRIC)
    few = score("u", sig(outbound_links=2, commerce_ratio=1.0), rubric)
    assert not any("shops" in r for r in few.reasons)


def test_bands_and_weights(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        """
version: 1
status: frozen
bands: {low: 0.5, mixed: 0.2}
rules:
  - {id: a, weight: 0.3, all: [{signal: has_author, eq: false}], reason: "no author"}
  - {id: b, weight: 0.25, all: [{signal: text_len, lt: 100}], reason: "thin {text_len}"}
  - {id: c, weight: 0.1, all: [{signal: near_dup_group, set: true}], reason: "dup"}
  - {id: d, weight: 0.1, all: [{signal: ad_scripts, gt: 3}, {signal: ad_scripts, lte: 5}],
     reason: "some ads"}
""",
        encoding="utf-8",
    )
    rubric = load_rubric(path)
    assert score("u", sig(has_author=False), rubric).band == "mixed"
    both = score("u", sig(has_author=False, text_len=50), rubric)
    assert (both.slop_risk, both.band, both.reasons) == (0.55, "low", ["no author", "thin 50"])
    assert score("u", sig(near_dup_group="dup-1"), rubric).reasons == ["dup"]
    assert score("u", sig(ad_scripts=4), rubric).reasons == ["some ads"]
    assert score("u", sig(ad_scripts=6), rubric).reasons == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("{signal: nope, gte: 1}", "unknown signal"),
        ("{signal: text_len, gte: 1, lt: 5}", "exactly one op"),
        ("{signal: text_len}", "exactly one op"),
    ],
)
def test_bad_conditions_rejected(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        "version: 1\nstatus: draft\nbands: {low: 0.5, mixed: 0.2}\n"
        f"rules:\n  - {{id: a, weight: 0.3, all: [{body}], reason: x}}\n",
        encoding="utf-8",
    )
    with pytest.raises(RubricError, match=message):
        load_rubric(path)


@pytest.mark.parametrize(
    ("rules", "bands", "message"),
    [
        ('[{id: a, weight: 0.3, all: [{signal: listicle, eq: true}], reason: "{nope}"}]',
         "{low: 0.5, mixed: 0.2}", "bad reason template"),
        ("[{id: a, weight: 0.3, all: [{signal: listicle, eq: true}], reason: x},"
         " {id: a, weight: 0.3, all: [{signal: listicle, eq: true}], reason: y}]",
         "{low: 0.5, mixed: 0.2}", "duplicate rule ids"),
        ("[{id: a, weight: 0.3, all: [{signal: listicle, eq: true}], reason: x}]",
         "{low: 0.2, mixed: 0.5}", "mixed must be below"),
    ],
)  # fmt: skip
def test_bad_rubrics_rejected(tmp_path: Path, rules: str, bands: str, message: str) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        f"version: 1\nstatus: draft\nbands: {bands}\nrules: {rules}\n", encoding="utf-8"
    )
    with pytest.raises(RubricError, match=message):
        load_rubric(path)


def _row(url: str, request_hash: str, rank: int = 1) -> SerpRow:
    return SerpRow(
        query_id="q", engine="google", locale="IN", rank=rank, url=url, domain="d",
        title="t", snippet="s", request_hash=request_hash,
    )  # fmt: skip


def test_near_dups_filled_across_serp_set() -> None:
    text = " ".join(f"word{i} shared text body" for i in range(200))
    h = f"{duplicate.simhash(text):016x}"
    records = [
        SignalRecord(url="https://a.example/1", html_hash="x", signals=sig(), simhash=h),
        SignalRecord(url="https://b.example/1", html_hash="y", signals=sig(), simhash=h),
        SignalRecord(url="https://c.example/1", html_hash="z", signals=sig(), simhash=h),
    ]
    rows = [
        _row("https://a.example/1", "s1"),
        _row("https://b.example/1", "s1", 2),
        _row("https://c.example/1", "s2"),  # alone in its SERP
        _row("https://unscored.example/", "s1", 3),  # no signals record
    ]
    filled = with_near_dups(rows, records)
    assert filled["https://a.example/1"].near_dup_group is not None
    assert (
        filled["https://a.example/1"].near_dup_group == filled["https://b.example/1"].near_dup_group
    )
    assert filled["https://c.example/1"].near_dup_group is None
    scores = score_all(rows, records, load_rubric(RUBRIC))
    assert [s.url for s in scores] == sorted(r.url for r in records)
    assert any("near-duplicate" in r for r in scores[0].reasons)
