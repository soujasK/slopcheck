"""Agent before/after demo: the same one-call agent answers each demo question
from the raw top-k results and from the SlopWatch-filtered top-k results.

Sources are built only from committed data (SERP title and URL, the page's
<=300-char excerpt or the SERP snippet), so every request is reproducible and
the recorded Gemini responses replay offline. The LLM is used only to play the
agent; it never scores anything.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from slopwatch.filter.core import SlopFilter
from slopwatch.http import HttpClient
from slopwatch.llm_label import GEMINI_URL, GeminiBackend
from slopwatch.models import Page, SerpRow
from slopwatch.store import PAGES, SERPS, read_jsonl

AGENT_SYSTEM = (
    "You are a search assistant. Answer the user's question using ONLY the numbered "
    "sources given. Cite the sources you rely on by number. Keep the answer under 100 "
    'words. Reply with JSON only: {"answer": "...", "cited": [source numbers]}.'
)


@dataclass(frozen=True)
class Source:
    n: int
    url: str
    title: str
    text: str
    slop_risk: float | None
    band: str | None
    not_scored: str | None


@dataclass(frozen=True)
class Run:
    sources: list[Source]
    answer: str
    cited: list[int]

    def cited_sources(self) -> list[Source]:
        by_n = {s.n: s for s in self.sources}
        return [by_n[c] for c in self.cited if c in by_n]


@dataclass(frozen=True)
class DemoResult:
    id: str
    question: str
    dropped: list[str]  # URLs removed from the top-k by the filter
    before: Run
    after: Run

    @property
    def changed(self) -> bool:
        before = {s.url for s in self.before.cited_sources()}
        after = {s.url for s in self.after.cited_sources()}
        return before != after


def load_questions(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw, list(raw["questions"])


def _sources(
    question: str,
    results: list[dict[str, Any]],
    excerpts: Mapping[str, str],
    k: int,
) -> list[Source]:
    out = []
    for i, r in enumerate(results[:k], start=1):
        s = r["slopwatch"]
        text = excerpts.get(r["link"]) or r.get("snippet") or ""
        out.append(
            Source(i, r["link"], r["title"], text, s["slop_risk"], s["band"], s["not_scored"])
        )
    return out


def _prompt(question: str, sources: list[Source]) -> str:
    blocks = [f"[{s.n}] {s.title}\nURL: {s.url}\n{s.text}" for s in sources]
    return f"Question: {question}\n\nSources:\n\n" + "\n\n".join(blocks)


def ask_agent(
    backend: GeminiBackend, question: str, sources: list[Source]
) -> tuple[str, list[int]]:
    payload = {
        "systemInstruction": {"parts": [{"text": AGENT_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": _prompt(question, sources)}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "answer": {"type": "STRING"},
                    "cited": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                },
                "required": ["answer", "cited"],
            },
        },
    }
    key = backend.key_value()
    headers = {"x-goog-api-key": key} if key else {}
    resp = backend.post_paced(payload, headers)
    if resp.status >= 400:
        raise RuntimeError(f"Gemini HTTP {resp.status}")
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    obj = json.loads(text)
    cited = sorted({int(c) for c in obj.get("cited", []) if 1 <= int(c) <= len(sources)})
    return str(obj.get("answer", "")).strip(), cited


def run_demo(
    questions: list[dict[str, str]],
    *,
    data_dir: Path,
    slop_filter: SlopFilter,
    agent: Callable[[str, list[Source]], tuple[str, list[int]]],
    engine: str = "google",
    locale: str = "IN",
    k: int = 5,
) -> list[DemoResult]:
    rows = read_jsonl(data_dir / SERPS, SerpRow)
    excerpts = {p.url: p.excerpt for p in read_jsonl(data_dir / PAGES, Page) if p.excerpt}
    out: list[DemoResult] = []
    for q in questions:
        serp = sorted(
            (
                r
                for r in rows
                if r.query_id == q["id"] and r.engine == engine and r.locale == locale
            ),
            key=lambda r: r.rank,
        )
        results = [{"title": r.title, "link": r.url, "snippet": r.snippet} for r in serp]
        annotated = slop_filter.apply(q["text"], results, mode="annotate")
        kept = slop_filter.apply(q["text"], results, mode="drop")
        kept_urls = {r["link"] for r in kept}
        dropped = [r["link"] for r in annotated[:k] if r["link"] not in kept_urls]
        before_src = _sources(q["text"], annotated, excerpts, k)
        after_src = _sources(q["text"], kept, excerpts, k)
        b_answer, b_cited = agent(q["text"], before_src)
        if dropped:
            a_answer, a_cited = agent(q["text"], after_src)
        else:  # identical sources: identical request, no second call
            a_answer, a_cited = b_answer, b_cited
        out.append(
            DemoResult(
                q["id"], q["text"], dropped,
                Run(before_src, b_answer, b_cited), Run(after_src, a_answer, a_cited),
            )
        )  # fmt: skip
    return out


def to_json(results: list[DemoResult]) -> list[dict[str, Any]]:
    def run(r: Run) -> dict[str, Any]:
        return {
            "answer": r.answer,
            "cited": r.cited,
            "sources": [s.__dict__ for s in r.sources],
        }

    return [
        {
            "id": d.id,
            "question": d.question,
            "dropped": d.dropped,
            "changed": d.changed,
            "before": run(d.before),
            "after": run(d.after),
        }
        for d in results
    ]


def _band(s: Source) -> str:
    return s.band or (s.not_scored or "?")


def render_markdown(results: list[DemoResult]) -> str:
    changed = sum(d.changed for d in results)
    with_drops = sum(1 for d in results if d.dropped)
    lines = [
        "# Agent before/after: all 8 demo questions",
        "",
        f"Questions with at least one top-5 source dropped: **{with_drops} of {len(results)}**. "
        f"Questions where the cited sources changed: **{changed} of {len(results)}**.",
        "",
        "| # | Question | Dropped (top 5) | Cited before (band) | Cited after (band) | Changed |",
        "|---|---|---|---|---|---|",
    ]
    for i, d in enumerate(results, start=1):
        before = ", ".join(f"[{s.n}] {_band(s)}" for s in d.before.cited_sources()) or "-"
        after = ", ".join(f"[{s.n}] {_band(s)}" for s in d.after.cited_sources()) or "-"
        lines.append(
            f"| {i} | {d.question} | {len(d.dropped)} | {before} | {after} | "
            f"{'yes' if d.changed else 'no'} |"
        )
    for d in results:
        lines += ["", f"## {d.question}", ""]
        if d.dropped:
            lines.append("Dropped: " + ", ".join(d.dropped))
            lines.append("")
        lines.append(f"**Before:** {d.before.answer}")
        lines.append("")
        lines.append(f"**After:** {d.after.answer}")
    return "\n".join(lines) + "\n"


__all__ = ["GEMINI_URL", "DemoResult", "HttpClient", "ask_agent", "run_demo"]
