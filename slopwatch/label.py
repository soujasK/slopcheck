"""Labeling: a seeded, stratified sample and a fast one-key-per-page labeler.

The sample is drawn from SERP rows that have signals, stratified by (category,
engine, locale) with proportional allocation, BEFORE any score is looked at, and
written to labels/sample.jsonl to be committed before labeling starts. Each
stratum's items alternate between the dev and test splits, so both splits are
stratified too. The labeler shows title, URL, query and a <=300-char excerpt,
never the score.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from slopwatch.models import Category, Engine, Label, LabelValue, Locale, Page, Query, SerpRow
from slopwatch.store import read_jsonl

Split = Literal["dev", "test"]


class LabelItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    query_id: str
    query_text: str
    category: Category
    engine: Engine
    locale: Locale
    rank: int
    title: str
    excerpt: str
    split: Split

    @property
    def key(self) -> tuple[str, str]:
        return (self.url, self.query_id)


def _allocate(sizes: dict[tuple[str, str, str], int], n: int) -> dict[tuple[str, str, str], int]:
    """Proportional allocation with largest remainders, capped by stratum size."""
    total = sum(sizes.values())
    if n >= total:
        return dict(sizes)
    quotas = {k: n * v / total for k, v in sizes.items()}
    alloc = {k: min(int(q), sizes[k]) for k, q in quotas.items()}
    order = sorted(sizes, key=lambda k: (-(quotas[k] - int(quotas[k])), k))
    i = 0
    while sum(alloc.values()) < n:
        k = order[i % len(order)]
        if alloc[k] < sizes[k]:
            alloc[k] += 1
        i += 1
    return alloc


def draw_sample(
    rows: list[SerpRow],
    pages: list[Page],
    scored_urls: set[str],
    queries: dict[tuple[str, Locale], Query],
    *,
    n: int,
    seed: int,
) -> list[LabelItem]:
    """``queries`` is keyed by (query_id, locale)."""
    page_by_url = {p.url: p for p in pages}
    seen: set[tuple[str, str]] = set()
    strata: dict[tuple[str, str, str], list[SerpRow]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r.locale, r.engine, r.query_id, r.rank)):
        if row.url not in scored_urls or (row.url, row.query_id) in seen:
            continue
        seen.add((row.url, row.query_id))
        query = queries[(row.query_id, row.locale)]
        strata[(query.category, row.engine, row.locale)].append(row)
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not crypto
    alloc = _allocate({k: len(v) for k, v in strata.items()}, n)
    items: list[LabelItem] = []
    for stratum in sorted(strata):
        chosen = rng.sample(strata[stratum], alloc[stratum])
        for i, row in enumerate(chosen):
            query = queries[(row.query_id, row.locale)]
            page = page_by_url.get(row.url)
            items.append(
                LabelItem(
                    url=row.url,
                    query_id=row.query_id,
                    query_text=query.text,
                    category=query.category,
                    engine=row.engine,
                    locale=row.locale,
                    rank=row.rank,
                    title=(page.title if page and page.title else row.title),
                    excerpt=page.excerpt if page else "",
                    split="dev" if i % 2 == 0 else "test",
                )
            )
    # Present items in a seeded random order so fatigue is not correlated with strata.
    rng.shuffle(items)
    return items


def load_sample(path: Path) -> list[LabelItem]:
    return read_jsonl(path, LabelItem)


def load_labels(path: Path) -> dict[tuple[str, str], Label]:
    """Latest label per (url, query_id); the file is append-only."""
    return {(lab.url, lab.query_id): lab for lab in read_jsonl(path, Label)}


def append_label(path: Path, label: Label) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(label.model_dump_json() + "\n")


KEYS: dict[str, LabelValue] = {"o": "ok", "l": "low", "u": "unsure"}
HELP = "[o] ok  [l] low  [u] unsure  [n] add note first  [s] skip  [b] back  [q] quit"


def render(item: LabelItem, position: int, total: int) -> str:
    return "\n".join(
        [
            "",
            f"── {position}/{total} ─ {item.category} · {item.engine} · {item.locale} "
            f"· rank {item.rank}",
            f"QUERY  {item.query_text}",
            f"TITLE  {item.title}",
            f"URL    {item.url}",
            f"TEXT   {item.excerpt or '(no excerpt)'}",
            HELP,
        ]
    )


def run_labeler(
    items: list[LabelItem],
    labels_path: Path,
    *,
    getch: Callable[[], str],
    prompt: Callable[[str], str],
    echo: Callable[[str], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Label every item not yet labeled. Returns how many labels were written."""
    done = load_labels(labels_path)
    todo = [it for it in items if it.key not in done]
    echo(f"{len(items) - len(todo)}/{len(items)} already labeled; {len(todo)} to go")
    written = 0
    i = 0
    note = ""
    while i < len(todo):
        item = todo[i]
        echo(render(item, len(items) - len(todo) + i + 1, len(items)))
        key = getch().lower()
        if key == "q":
            break
        if key == "s":
            i += 1
            note = ""
        elif key == "b":
            i = max(i - 1, 0)
            note = ""
        elif key == "n":
            note = prompt("note").strip()
            echo(f"note: {note}")
        elif key in KEYS:
            label = Label(
                url=item.url, query_id=item.query_id, label=KEYS[key], note=note, labeled_at=now()
            )
            append_label(labels_path, label)
            written += 1
            echo(f"→ {label.label}")
            i += 1
            note = ""
        else:
            echo(f"unknown key {key!r}")
    echo(f"wrote {written} labels to {labels_path}")
    return written
