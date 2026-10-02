from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from slopwatch.config import REPO_ROOT
from slopwatch.queries import PlanError, load_plan, select_subset, serp_params, to_rows
from slopwatch.serp import parse_organic

REAL = REPO_ROOT / "data" / "queries.yaml"


def test_real_query_set_matches_measurement_design() -> None:
    plan = load_plan(REAL)
    assert len(plan.specs) == 40
    assert Counter(q.category for q in plan.specs) == {
        "health": 10,
        "personal_finance": 10,
        "product_reviews": 10,
        "tech_howto": 10,
    }
    by = Counter((j.query.locale, j.engine) for j in plan.jobs)
    assert by == {("IN", "google"): 40, ("IN", "bing"): 20, ("US", "google"): 20}
    assert plan.credits_needed() == 80
    assert len({(j.query.id, j.query.locale, j.engine) for j in plan.jobs}) == 80
    # Bing-IN and Google-US run the same seeded subset, 5 per category
    bing = {j.query.id for j in plan.jobs if j.engine == "bing"}
    us = {j.query.id for j in plan.jobs if j.query.locale == "US"}
    assert bing == us == set(plan.subset_ids)
    assert set(Counter(i.split("-")[0] for i in bing).values()) == {5}
    neutral = {q.id for q in plan.specs if q.locale_neutral}
    assert bing <= neutral


def test_locale_params() -> None:
    assert serp_params("google", "IN", "q") == {
        "q": "q",
        "gl": "in",
        "hl": "en",
        "google_domain": "google.co.in",
    }
    assert serp_params("google", "US", "q")["google_domain"] == "google.com"
    assert serp_params("bing", "IN", "q") == {"q": "q", "mkt": "en-IN"}


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "q.yaml"
    path.write_text(body, encoding="utf-8")
    return path


HEADER = (
    "version: 1\nstatus: frozen\n"
    "subset: {seed: 1, per_category: 1, ids: [a]}\n"
    "plan:\n  - {locale: IN, engines: [google], queries: all}\n"
    "  - {locale: US, engines: [google], queries: subset}\n"
)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    body = (
        HEADER
        + "queries:\n"
        + "  - {id: a, category: health, text: x, locale_neutral: true}\n"
        + "  - {id: a, category: health, text: y, locale_neutral: true}\n"
    )
    with pytest.raises(PlanError, match="duplicate"):
        load_plan(_write(tmp_path, body))


@pytest.mark.parametrize(
    "line",
    [
        "  - {id: a, category: sports, text: x, locale_neutral: true}",
        "  - {id: a, category: health, text: '  ', locale_neutral: true}",
        "  - {id: a, category: health, text: x, locale_neutral: true, extra: 1}",
        "  - {id: a, category: health, text: x}",
    ],
)
def test_invalid_queries_rejected(tmp_path: Path, line: str) -> None:
    with pytest.raises(ValidationError):
        load_plan(_write(tmp_path, HEADER + "queries:\n" + line + "\n"))


def test_frozen_flag_and_whitespace_normalised(tmp_path: Path) -> None:
    plan = load_plan(
        _write(
            tmp_path,
            HEADER
            + "queries:\n  - {id: a, category: health, text: ' a   b ', locale_neutral: true}\n",
        )
    )
    assert plan.frozen and plan.jobs[0].params["q"] == "a b"


def test_select_subset_is_seeded_and_stable() -> None:
    specs = load_plan(REAL).specs
    a = select_subset(specs, 2026, 5)
    assert a == select_subset(list(reversed(specs)), 2026, 5)  # input order irrelevant
    # only the health draw (5 of 6) depends on the seed, so some seeds coincide
    assert any(select_subset(specs, seed, 5) != a for seed in range(20))
    with pytest.raises(PlanError, match="5 < 6 locale-neutral"):
        select_subset(specs, 2026, 6)
    # the neutral pool, not the whole category, is what gets sampled
    assert {i for i in a if i.startswith("finance")} == {f"finance-{n:02d}" for n in range(6, 11)}


def test_hand_edited_subset_rejected(tmp_path: Path) -> None:
    body = REAL.read_text(encoding="utf-8").replace("health-01, health-03", "health-01, health-09")
    with pytest.raises(PlanError, match="do not match tags and seed 2026"):
        load_plan(_write(tmp_path, body))


def test_to_rows() -> None:
    from datetime import UTC, datetime

    from slopwatch.serp import SerpPage

    plan = load_plan(REAL)
    job = plan.jobs[0]
    organic = parse_organic(
        {"organic_results": [{"link": "https://www.x.example/a", "title": "T", "snippet": "S"}]}
    )
    page = SerpPage("h", "google", job.params, organic, [], datetime.now(UTC), False)
    (row,) = to_rows(page, job.query)
    assert (row.query_id, row.engine, row.locale, row.rank) == (job.query.id, "google", "IN", 1)
    assert row.domain == "x.example" and row.request_hash == "h"


def test_restrict_to_named_jobs() -> None:
    plan = load_plan(REAL)
    probe = plan.restrict(["health-01/google/IN"])
    assert [j.key for j in probe.jobs] == ["health-01/google/IN"]
    assert probe.frozen and probe.credits_needed() == 1
    with pytest.raises(PlanError, match="not in the frozen plan: health-02/bing/IN"):
        plan.restrict(["health-02/bing/IN"])  # health-02 is not in the Bing subset
