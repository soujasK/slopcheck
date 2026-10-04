"""Agent before/after demo with a FAKE agent / mocked Gemini (no real LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from slopwatch.config import REPO_ROOT
from slopwatch.demo import Source, load_questions, render_markdown, run_demo, to_json
from slopwatch.filter import offline_filter

QUESTIONS = REPO_ROOT / "data" / "demo_questions.yaml"


def test_demo_questions_are_seeded_and_committed() -> None:
    meta, qs = load_questions(QUESTIONS)
    assert meta["seed"] == 8 and meta["top_k"] == 5 and len(qs) == 8
    assert {q["id"].split("-")[0] for q in qs} == {"health", "finance", "product", "tech"}


def test_run_demo_with_fake_agent_reports_every_question() -> None:
    _, qs = load_questions(QUESTIONS)
    calls: list[tuple[str, int]] = []

    def agent(question: str, sources: list[Source]) -> tuple[str, list[int]]:
        calls.append((question, len(sources)))
        return f"answer from {len(sources)} sources", [1, 2]

    f = offline_filter()
    # threshold 0 in the filter would drop every scored page; use a strict filter
    # to force at least one drop and exercise the "after" call
    f.rubric = f.rubric.model_copy(
        update={"bands": f.rubric.bands.model_copy(update={"low": 0.01})}
    )
    results = run_demo(qs, data_dir=REPO_ROOT / "data", slop_filter=f, agent=agent)
    assert len(results) == 8
    assert all(len(d.before.sources) <= 5 for d in results)
    with_drops = [d for d in results if d.dropped]
    assert with_drops and len(calls) == 8 + len(with_drops)
    for d in with_drops:
        assert not {s.url for s in d.after.sources} & set(d.dropped)
    md = render_markdown(results)
    assert md.count("\n## ") == 8 and "Questions where the cited sources changed" in md
    js = to_json(results)
    assert len(js) == 8 and {"before", "after", "changed", "dropped"} <= js[0].keys()


def test_cli_demo_records_and_replays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from slopwatch.cli import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLOPWATCH_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("SLOPWATCH_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("GEMINI_API_KEY", "GKEY-not-real")

    def send(self: httpx.Client, request: httpx.Request, **kw: object) -> httpx.Response:
        assert "generativelanguage" in str(request.url)
        body = {"answer": "Take antacids; see a doctor if it persists.", "cited": [1, 7]}
        reply = {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]}
        return httpx.Response(200, json=reply, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    runner = CliRunner()
    args = ["demo", "--questions", str(QUESTIONS), "--min-interval", "0"]
    r = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert r.exit_code == 0, r.output
    demo = json.loads((tmp_path / "report" / "demo.json").read_text(encoding="utf-8"))
    assert len(demo) == 8 and demo[0]["before"]["cited"] == [1]  # out-of-range 7 ignored
    assert (tmp_path / "DEMO_RESULTS.md").exists()
    fx = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "fixtures").glob("*.json"))
    assert "GKEY-not-real" not in fx

    def no_net(self: httpx.Client, request: httpx.Request, **kw: object) -> Any:
        raise AssertionError("network in replay")

    monkeypatch.setattr(httpx.Client, "send", no_net)
    monkeypatch.delenv("GEMINI_API_KEY")
    rp = runner.invoke(app, [*args, "--cache-mode", "replay"], env={"COLUMNS": "200"})
    assert rp.exit_code == 0, rp.output
