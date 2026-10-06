"""Rubric fitting on SYNTHETIC signals."""

from __future__ import annotations

from pathlib import Path

from slopwatch.fit import CANDIDATES, features, fit_logistic, fit_rubric, rubric_yaml, rule_weights
from slopwatch.models import Signals
from slopwatch.score import load_rubric, score


def sig(**kw: object) -> Signals:
    base: dict[str, object] = {
        "affiliate_links": 0, "affiliate_density": 0.0, "outbound_links": 10,
        "commerce_ratio": 0.0, "listicle": False, "ad_scripts": 0, "has_author": True,
        "has_date": True, "has_about_contact": True, "text_len": 5000,
        "boilerplate_ratio": 0.2, "query_title_coverage": 1.0, "query_text_coverage": 1.0,
    }  # fmt: skip
    base.update(kw)
    return Signals.model_validate(base)


def dataset() -> tuple[list[Signals], list[int]]:
    xs: list[Signals] = []
    ys: list[int] = []
    for i in range(60):  # low: anonymous and off-query, a few noisy
        xs.append(sig(has_author=False, has_date=i % 5 == 0, query_title_coverage=0.25))
        ys.append(1)
    for i in range(120):  # ok: authored and on-query, a few anonymous
        xs.append(sig(has_author=i % 6 != 0, listicle=i % 4 == 0))
        ys.append(0)
    return xs, ys


def test_features_follow_candidates() -> None:
    f = features(sig(has_author=False, query_title_coverage=0.25, query_text_coverage=None))
    by_id = dict(zip((c.id for c in CANDIDATES), f, strict=True))
    assert by_id["no_author"] == 1.0 and by_id["title_off_query"] == 1.0
    assert by_id["text_off_query"] == 0.0  # unknown relevance never fires


def test_logistic_learns_the_signal_and_is_deterministic() -> None:
    xs, ys = dataset()
    x = [features(s) for s in xs]
    coefs, _ = fit_logistic(x, ys)
    by_id = dict(zip((c.id for c in CANDIDATES), coefs, strict=True))
    assert by_id["title_off_query"] > 0 and by_id["no_author"] > 0
    assert by_id["listicle"] < by_id["title_off_query"]
    assert fit_logistic(x, ys) == (coefs, fit_logistic(x, ys)[1])
    w = rule_weights([2.0, -1.0, 2.0])
    assert w == [0.5, -0.25, 0.5]  # protective (negative) weights are kept
    assert rule_weights([-1.0]) == [0.0]


def test_fit_rubric_threshold_and_yaml_roundtrip(tmp_path: Path) -> None:
    xs, ys = dataset()
    res = fit_rubric(xs, ys)
    assert res.met_min_precision and res.oof_precision >= 0.7 and res.oof_recall > 0.5
    assert res == fit_rubric(xs, ys)  # deterministic
    path = tmp_path / "v3.yaml"
    path.write_text(rubric_yaml(res, version=3, note="test\nfit"), encoding="utf-8")
    rubric = load_rubric(path)
    assert rubric.status == "frozen" and rubric.bands.low == res.low
    low = score("u", sig(has_author=False, has_date=False, query_title_coverage=0.25), rubric)
    ok = score("u", sig(), rubric)
    assert low.band == "low" and ok.band == "ok"
    assert any("cover" in r for r in low.reasons)


def test_fit_rubric_reports_when_precision_floor_unreachable() -> None:
    xs = [sig(has_author=bool(i % 2)) for i in range(40)]
    ys = [i % 3 == 0 for i in range(40)]  # labels unrelated to the signal
    res = fit_rubric(xs, [int(y) for y in ys])
    assert not res.met_min_precision
