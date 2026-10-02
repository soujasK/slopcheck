"""Committed pipeline data: deterministic JSONL files under data/.

Rows are written sorted and with LF line endings so re-running a step on the
same inputs produces a byte-identical file (clean git diffs).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

SERPS = "serps.jsonl"
SERP_META = "serp_meta.jsonl"
PAGES = "pages.jsonl"
SIGNALS = "signals.jsonl"


def write_jsonl(path: Path, rows: Iterable[M], key: Callable[[M], Any]) -> int:
    ordered = sorted(rows, key=key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in ordered:
            fh.write(json.dumps(row.model_dump(mode="json"), sort_keys=True, ensure_ascii=False))
            fh.write("\n")
    return len(ordered)


def read_jsonl(path: Path, model: type[M]) -> list[M]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [model.model_validate_json(line) for line in lines if line.strip()]
