"""Load the query set and expand it into SerpApi jobs per engine and locale.

Every query is tagged ``locale_neutral`` before the draw. The Bing / US
comparison subset is drawn by a fixed seed from the locale-neutral pool only
(``select_subset``) and the resulting ids are written into queries.yaml; loading
fails if the stored ids do not match the tags and seed, so the subset cannot be
hand-picked after the fact.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from slopwatch.models import Category, Engine, Locale, Query, SerpRow
from slopwatch.serp import SerpPage

# Locale parameters per engine (serpapi.com docs, checked 2026-10-02). Bing's `cc`
# and `mkt` are mutually exclusive; `mkt` pins both language and market.
LOCALE_PARAMS: dict[Locale, dict[Engine, dict[str, str]]] = {
    "IN": {
        "google": {"gl": "in", "hl": "en", "google_domain": "google.co.in"},
        "bing": {"mkt": "en-IN"},
    },
    "US": {
        "google": {"gl": "us", "hl": "en", "google_domain": "google.com"},
        "bing": {"mkt": "en-US"},
    },
}


class PlanError(ValueError):
    pass


class QuerySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: Category
    text: str
    # False for queries that only make sense in India (INR prices, Aadhaar, Indian
    # brands...). Only neutral queries are eligible for the India-vs-US subset.
    locale_neutral: bool

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("empty query text")
        return " ".join(v.split())


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    locale: Locale
    engines: list[Engine]
    queries: Literal["all", "subset"]


class Subset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int
    per_category: int
    ids: list[str]


class QueryFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    status: Literal["draft", "frozen"]
    subset: Subset
    plan: list[PlanStep]
    queries: list[QuerySpec]


@dataclass(frozen=True)
class Job:
    query: Query
    engine: Engine

    @property
    def params(self) -> dict[str, str]:
        return serp_params(self.engine, self.query.locale, self.query.text)


@dataclass(frozen=True)
class Plan:
    status: Literal["draft", "frozen"]
    specs: list[QuerySpec]
    subset_ids: list[str]
    jobs: list[Job]

    @property
    def frozen(self) -> bool:
        return self.status == "frozen"

    def credits_needed(self) -> int:
        return len(self.jobs)


def serp_params(engine: Engine, locale: Locale, text: str) -> dict[str, str]:
    return {"q": text, **LOCALE_PARAMS[locale][engine]}


def select_subset(specs: list[QuerySpec], seed: int, per_category: int) -> list[str]:
    """``per_category`` locale-neutral ids from each category, sampled with
    ``random.Random(seed)`` over categories and ids in sorted order (stable across
    Python versions)."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not crypto
    chosen: list[str] = []
    for category in sorted({q.category for q in specs}):
        ids = sorted(q.id for q in specs if q.category == category and q.locale_neutral)
        if len(ids) < per_category:
            raise PlanError(
                f"category {category} has {len(ids)} < {per_category} locale-neutral queries"
            )
        chosen.extend(sorted(rng.sample(ids, per_category)))
    return chosen


def load_plan(path: Path) -> Plan:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    qf = QueryFile.model_validate(raw)
    dupes = [i for i, n in Counter(q.id for q in qf.queries).items() if n > 1]
    if dupes:
        raise PlanError(f"duplicate query ids: {', '.join(sorted(dupes))}")
    expected = select_subset(qf.queries, qf.subset.seed, qf.subset.per_category)
    if qf.subset.ids != expected:
        raise PlanError(
            f"subset.ids do not match tags and seed {qf.subset.seed}; "
            f"expected: {', '.join(expected)}"
        )
    in_subset = set(expected)
    jobs: list[Job] = []
    for step in qf.plan:
        chosen = [q for q in qf.queries if step.queries == "all" or q.id in in_subset]
        for spec in chosen:
            query = Query(id=spec.id, category=spec.category, locale=step.locale, text=spec.text)
            jobs.extend(Job(query, engine) for engine in step.engines)
    return Plan(status=qf.status, specs=qf.queries, subset_ids=expected, jobs=jobs)


def to_rows(page: SerpPage, query: Query) -> list[SerpRow]:
    return [
        SerpRow(
            query_id=query.id,
            engine=page.engine,
            locale=query.locale,
            rank=r.rank,
            url=r.url,
            domain=r.domain,
            title=r.title,
            snippet=r.snippet,
            request_hash=page.request_hash,
        )
        for r in page.organic
    ]
