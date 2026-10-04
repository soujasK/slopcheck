"""Rubric scoring: Signals -> slop_risk (0..1, higher = worse), band, reasons.

The rubric (data/rubric.yaml) is a list of rules. A rule fires when all of its
conditions hold; slop_risk is the capped sum of the weights of the rules that
fired, and every fired rule contributes one human-readable reason. Nothing else
goes into the score, so every number in the report can be traced to rules.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from slopwatch.models import Band, RelevanceRecord, Score, SerpRow, SignalRecord, Signals
from slopwatch.signals import duplicate

Op = Literal["gte", "gt", "lte", "lt", "eq", "set"]
_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "gte": operator.ge,
    "gt": operator.gt,
    "lte": operator.le,
    "lt": operator.lt,
    "eq": operator.eq,
}
SIGNAL_FIELDS = frozenset(Signals.model_fields)


class RubricError(ValueError):
    pass


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: str
    gte: float | None = None
    gt: float | None = None
    lte: float | None = None
    lt: float | None = None
    eq: bool | float | None = None
    set: bool | None = None

    @model_validator(mode="after")
    def _one_op(self) -> Condition:
        if self.signal not in SIGNAL_FIELDS:
            raise ValueError(f"unknown signal {self.signal!r}")
        ops = [
            op for op in ("gte", "gt", "lte", "lt", "eq", "set") if getattr(self, op) is not None
        ]
        if len(ops) != 1:
            raise ValueError(f"condition on {self.signal!r} needs exactly one op, got {ops}")
        return self

    def holds(self, signals: Signals) -> bool:
        value = getattr(signals, self.signal)
        if self.set is not None:
            return (value is not None) is self.set
        for name, fn in _OPS.items():
            target = getattr(self, name)
            if target is not None:
                return value is not None and bool(fn(value, target))
        raise AssertionError("unreachable: validated to have one op")  # pragma: no cover


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    weight: float = Field(gt=0, le=1)
    all: list[Condition] = Field(min_length=1)
    reason: str

    def fires(self, signals: Signals) -> bool:
        return all(c.holds(signals) for c in self.all)

    def explain(self, signals: Signals) -> str:
        return self.reason.format(**signals.model_dump())


class Bands(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    low: float = Field(gt=0, le=1)
    mixed: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> Bands:
        if self.mixed >= self.low:
            raise ValueError("bands.mixed must be below bands.low")
        return self


class Rubric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    status: Literal["draft", "frozen"]
    bands: Bands
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_and_formattable(self) -> Rubric:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule ids")
        probe = Signals(
            affiliate_links=1, affiliate_density=0.1, outbound_links=1, commerce_ratio=0.1,
            listicle=True, ad_scripts=1, has_author=True, has_date=True,
            has_about_contact=True, text_len=1, boilerplate_ratio=0.1, near_dup_group="g",
        )  # fmt: skip
        for rule in self.rules:
            try:
                rule.explain(probe)
            except (KeyError, ValueError, IndexError) as exc:
                raise ValueError(f"rule {rule.id}: bad reason template: {exc}") from None
        return self

    def band(self, slop_risk: float) -> Band:
        if slop_risk >= self.bands.low:
            return "low"
        if slop_risk >= self.bands.mixed:
            return "mixed"
        return "ok"


def load_rubric(path: Path) -> Rubric:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return Rubric.model_validate(raw)
    except ValueError as exc:
        raise RubricError(f"{path}: {exc}") from exc


def score(url: str, signals: Signals, rubric: Rubric, query_id: str | None = None) -> Score:
    fired = [rule for rule in rubric.rules if rule.fires(signals)]
    risk = round(min(1.0, sum(rule.weight for rule in fired)), 4)
    return Score(
        url=url,
        query_id=query_id,
        slop_risk=risk,
        band=rubric.band(risk),
        reasons=[rule.explain(signals) for rule in fired],
    )


def with_near_dups(rows: list[SerpRow], records: list[SignalRecord]) -> dict[str, Signals]:
    """Signals per URL with ``near_dup_group`` filled in across each SERP set."""
    by_url = {r.url: r for r in records}
    items = [
        duplicate.DupItem(
            set_key=row.request_hash,
            url=row.url,
            simhash=int(by_url[row.url].simhash, 16),
            text_len=by_url[row.url].signals.text_len,
        )
        for row in rows
        if row.url in by_url
    ]
    groups = duplicate.groups(items)
    return {
        url: rec.signals.model_copy(update={"near_dup_group": groups.get(url)})
        for url, rec in by_url.items()
    }


def score_all(rows: list[SerpRow], records: list[SignalRecord], rubric: Rubric) -> list[Score]:
    signals = with_near_dups(rows, records)
    return [score(url, sig, rubric) for url, sig in sorted(signals.items())]


RowKey = tuple[str, str]  # (url, query_id)


def row_signals(
    rows: list[SerpRow], records: list[SignalRecord], relevance: list[RelevanceRecord]
) -> dict[RowKey, Signals]:
    """Signals per (url, query): page signals + near-duplicate group + relevance."""
    page = with_near_dups(rows, records)
    rel = {(r.url, r.query_id): r for r in relevance}
    out: dict[RowKey, Signals] = {}
    for row in rows:
        key = (row.url, row.query_id)
        if row.url not in page or key in out:
            continue
        r = rel.get(key)
        out[key] = page[row.url].model_copy(
            update={
                "query_title_coverage": r.title_coverage if r else None,
                "query_text_coverage": r.text_coverage if r else None,
            }
        )
    return out


def score_rows(
    rows: list[SerpRow],
    records: list[SignalRecord],
    relevance: list[RelevanceRecord],
    rubric: Rubric,
) -> dict[RowKey, Score]:
    return {
        key: score(key[0], sig, rubric, query_id=key[1])
        for key, sig in sorted(row_signals(rows, records, relevance).items())
    }
