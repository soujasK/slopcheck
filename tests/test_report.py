"""Observatory report built from the committed data (no network, no keys)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from slopwatch.cli import app
from slopwatch.config import REPO_ROOT
from slopwatch.report.observatory import Bar, _bars_svg, compute


def test_compute_has_every_preregistered_group() -> None:
    n = compute(REPO_ROOT)
    assert set(n["by_engine"]) == {"google", "duckduckgo", "yahoo"}
    assert set(n["by_category"]) == {"health", "personal_finance", "product_reviews", "tech_howto"}
    assert set(n["india_vs_us"]) == {"IN", "US"}
    assert set(n["comparisons"]) == {
        "google_in_vs_google_us", "google_in_vs_duckduckgo_in", "google_in_vs_yahoo_in",
    }  # fmt: skip
    for share in [n["overall_india"], *n["by_engine"].values(), *n["by_rank"].values()]:
        lo, hi = share["ci"]
        assert 0 <= lo <= share["value"] <= hi <= 1 or share["n_scored"] == 0
        assert share["bounds"][0] <= share["bounds"][1]
    assert n["ai_overview"]["Google IN"] == "39/40"
    assert "round2_test" in n["validation"]


def test_bars_svg_has_tooltips_and_whiskers() -> None:
    svg = _bars_svg([Bar("Google", 0.2, 0.1, 0.3, 50, "coverage 80%")])
    assert "<title>Google: 20% (95% CI 10%-30%), n = 50; coverage 80%</title>" in svg
    assert svg.count('class="whisker"') == 3


def test_cli_report_writes_self_contained_html(tmp_path: Path) -> None:
    out = tmp_path / "obs.html"
    r = CliRunner().invoke(app, ["report", "--out", str(out), "--cache-mode", "replay"])
    assert r.exit_code == 0, r.output
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "<title>SlopWatch Observatory</title>" in page
    assert "prefers-color-scheme:dark" in page and 'data-theme="dark"' in page
    assert not re.search(r'<(script|link)[^>]+(src|href)="http', page)  # no external assets
    assert "two LLMs" in page and "Table view" in page
    numbers = json.loads((tmp_path / "numbers.json").read_text(encoding="utf-8"))
    assert numbers["n_searches"] == 100


def test_story_page_is_built_from_committed_data(tmp_path: Path) -> None:
    from slopwatch.report.story import build_story, story_data

    d = story_data(REPO_ROOT)
    assert sum(len(g["cells"]) for g in d["grid"]) == d["n_rows"] == 822
    assert {c for g in d["grid"] for c in g["cells"]} <= {"c", "s", "p", "b"}
    assert any(h["band"] == "low" and h["reasons"] for h in d["hero"])
    page = build_story(REPO_ROOT, tmp_path / "story.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "__STORY_DATA__" not in page
    assert "<title>SlopWatch</title>" in page and "prefers-color-scheme: dark" in page
    assert not re.search(r"[\U0001F300-\U0001FAFF]", page)  # no emoji
