from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from slopwatch.cli import app, credits_line
from slopwatch.serp import ProjectLedger

runner = CliRunner()


def test_doctor_offline_without_key(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--offline"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "0/140 spent" in out
    assert "frozen: 40 queries, 100 searches" in out
    assert "not set" in out
    assert "credits: 0 spent by this command; project ledger 0/140 (140 left)" in out


def test_doctor_replay_mode_reads_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = tmp_path / "fx"
    fixtures.mkdir()
    monkeypatch.setenv("SLOPWATCH_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    result = runner.invoke(app, ["doctor", "--cache-mode", "replay"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "mode=replay" in result.output and "not verified" in result.output


def test_doctor_checks_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    real_send = httpx.Client.send

    def fake_send(self: httpx.Client, request: httpx.Request, **kw: object) -> httpx.Response:
        assert request.url.path == "/account.json"
        return httpx.Response(
            200, json={"plan_name": "Free", "this_month_usage": 43, "total_searches_left": 99}
        )

    monkeypatch.setattr(httpx.Client, "send", fake_send)
    result = runner.invoke(app, ["doctor"], env={"COLUMNS": "200"})
    monkeypatch.setattr(httpx.Client, "send", real_send)
    assert result.exit_code == 0, result.output
    assert "account left=99" in result.output
    assert "fewer than the project's" in result.output


def test_doctor_fails_on_rejected_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "bad")

    def fake_send(self: httpx.Client, request: httpx.Request, **kw: object) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key"})

    monkeypatch.setattr(httpx.Client, "send", fake_send)
    result = runner.invoke(app, ["doctor"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "rejected" in result.output


def test_doctor_fails_on_corrupt_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("{not json\n", encoding="utf-8")
    monkeypatch.setenv("SLOPWATCH_LEDGER_PATH", str(ledger))
    result = runner.invoke(app, ["doctor", "--offline"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "UNREADABLE" in result.output


def test_doctor_reports_bad_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "queries.yaml").write_text("version: 1\nstatus: nope\n", encoding="utf-8")
    monkeypatch.setenv("SLOPWATCH_DATA_DIR", str(data))
    result = runner.invoke(app, ["doctor", "--offline"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "rubric.yaml" in result.output and "missing" in result.output


def test_doctor_warns_when_budget_short(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "".join(json.dumps({"credits": 1}) + "\n" for _ in range(120)), encoding="utf-8"
    )
    monkeypatch.setenv("SLOPWATCH_LEDGER_PATH", str(ledger))
    result = runner.invoke(app, ["doctor", "--offline"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    assert "plan needs 100 > 20 left" in result.output
    assert credits_line(2, ProjectLedger(ledger)).startswith("credits: 2 spent")
