"""LLM labeler tests against MOCK APIs. No real model is called and no real
item is labeled here."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from slopwatch.config import REPO_ROOT
from slopwatch.label import LabelItem
from slopwatch.llm_label import (
    CF_FALLBACK,
    CF_PRIMARY,
    CloudflareBackend,
    GeminiBackend,
    VertexGeminiBackend,
    agreement_report,
    audit_report,
    item_prompt,
    label_items,
    load_guide,
    parse_reply,
    render_agreement,
    render_audit,
    system_prompt,
)
from slopwatch.models import Label, Signals
from tests.conftest import Recorder, make_client

GUIDE = load_guide(REPO_ROOT / "LABELING.md")


def item(i: int = 0, split: str = "dev") -> LabelItem:
    return LabelItem.model_validate(
        {
            "url": f"https://site{i}.example/page", "query_id": f"q{i}",
            "query_text": "best sip to invest", "category": "personal_finance",
            "engine": "google", "locale": "IN", "rank": 1, "title": f"Title {i}",
            "excerpt": "Top 10 SIPs for 2026 with returns", "split": split,
        }
    )  # fmt: skip


def test_guide_is_only_the_marked_section() -> None:
    assert GUIDE.startswith("## Task") and "Judge the page for this query" in GUIDE
    assert "Decisions recorded" not in GUIDE and "rubric" not in GUIDE.lower()


def test_labelers_never_see_scores_signals_or_rubric() -> None:
    text = (system_prompt(GUIDE) + item_prompt(item())).lower()
    forbidden = ["slop_risk", "rubric", "band", "reasons", "score", *Signals.model_fields]
    assert not [w for w in forbidden if w.lower() in text]
    assert "query: best sip to invest" in text and "url: https://site0.example/page" in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"label": "low", "reason": "affiliate roundup"}', ("low", "affiliate roundup")),
        ('```json\n{"label": "ok", "reason": "official"}\n```', ("ok", "official")),
        ('{"label": "LOW", "reason": "x"}', None),
        ('{"label": "low"}', None),
        ('{"label": "maybe", "reason": "x"}', None),
        ("not json", None),
        ("[1, 2]", None),
        ("{bad json}", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_reply(text: str | None, expected: tuple[str, str] | None) -> None:
    assert parse_reply(text) == expected


def gemini_response(text: str) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {
            "promptTokenCount": 900,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 50,
        },
    }


def test_gemini_backend_payload_and_key_never_stored() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["generationConfig"]["temperature"] == 0
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert request.headers["x-goog-api-key"] == "GKEY-not-real"
        return httpx.Response(200, json=gemini_response('{"label": "ok", "reason": "fine"}'))

    rec = Recorder(handler)
    with make_client(rec) as http:
        backend = GeminiBackend(http, SecretStr("GKEY-not-real"))
        reply = backend.ask(system_prompt(GUIDE), item_prompt(item()), attempt=0)
        assert parse_reply(reply.text) == ("ok", "fine")
        assert (reply.input_tokens, reply.output_tokens) == (900, 70)
        again = backend.ask(system_prompt(GUIDE), item_prompt(item()), attempt=0)
        assert again.from_cache and len(rec.requests) == 1
        assert "GKEY-not-real" not in " ".join(http.cache._db.iterdump())
    bad = Recorder(lambda r: httpx.Response(403, json={"error": "denied"}))
    with make_client(bad) as http, pytest.raises(Exception, match="Gemini HTTP 403"):
        GeminiBackend(http, SecretStr("k")).ask("s", "u", attempt=0)


def cf_response(text: str, neurons: float = 50.0) -> dict[str, Any]:
    return {
        "result": {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 150, "neurons": neurons},
        },
        "success": True,
    }


def test_cloudflare_backend_hides_account_and_reports_neurons() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert "/accounts/ACCT-SECRET/" in str(request.url)
        assert request.headers["authorization"] == "Bearer CF-TOKEN-not-real"
        return httpx.Response(200, json=cf_response('{"label": "low", "reason": "spam"}'))

    with make_client(Recorder(handler)) as http:
        backend = CloudflareBackend(http, SecretStr("CF-TOKEN-not-real"), SecretStr("ACCT-SECRET"))
        reply = backend.ask("sys", "user", attempt=0)
        dump = " ".join(http.cache._db.iterdump())
    assert reply.neurons == 50.0 and reply.model == CF_PRIMARY
    assert seen[0]["temperature"] == 0 and seen[0]["reasoning"] == {"effort": "low"}
    assert "ACCT-SECRET" not in dump and "CF-TOKEN-not-real" not in dump


def test_cloudflare_falls_back_only_when_primary_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if CF_PRIMARY in str(request.url):
            return httpx.Response(404, json={"errors": [{"message": "No such model"}]})
        assert "reasoning" not in json.loads(request.content)
        return httpx.Response(200, json=cf_response('{"label": "ok", "reason": "x"}'))

    with make_client(Recorder(handler)) as http:
        backend = CloudflareBackend(http, SecretStr("t"), SecretStr("a"))
        reply = backend.ask("s", "u", attempt=0)
    assert reply.model == CF_FALLBACK and backend.fallback_used

    always_404 = Recorder(lambda r: httpx.Response(404, json={}))
    with make_client(always_404) as http, pytest.raises(Exception, match="Cloudflare HTTP 404"):
        CloudflareBackend(http, SecretStr("t"), SecretStr("a")).ask("s", "u", attempt=0)


def test_label_items_retries_invalid_json_then_records() -> None:
    replies = iter(["sure!", '{"label": "low", "reason": "affiliate"}', "x", "y", "z"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cf_response(next(replies), neurons=10.0))

    written: list[Label] = []
    with make_client(Recorder(handler)) as http:
        backend = CloudflareBackend(http, SecretStr("t"), SecretStr("a"))
        stats = label_items(
            [item(0), item(1), item(2)], backend, GUIDE,
            done={item(2).key}, write=written.append,
            now=lambda: datetime(2026, 10, 4, tzinfo=UTC),
        )  # fmt: skip
    assert [w.label for w in written] == ["low", "unsure"]
    assert written[0].note == "affiliate"
    assert written[1].note.startswith("INVALID")
    assert (stats.labeled, stats.retries, stats.invalid_final) == (2, 4, 1)
    assert stats.neurons == 50.0 and stats.input_tokens == 6000


def test_label_items_stops_at_neuron_budget() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cf_response('{"label": "ok", "reason": "x"}', 60.0))

    written: list[Label] = []
    with make_client(Recorder(handler)) as http:
        backend = CloudflareBackend(http, SecretStr("t"), SecretStr("a"))
        stats = label_items(
            [item(i) for i in range(5)], backend, GUIDE, done=set(), write=written.append,
            neuron_budget=100.0,
        )  # fmt: skip
    assert len(written) == 2 and stats.stopped_for_budget


def _lab(it: LabelItem, label: str, note: str = "r") -> Label:
    return Label.model_validate(
        {"url": it.url, "query_id": it.query_id, "label": label, "note": note,
         "labeled_at": datetime(2026, 10, 4, tzinfo=UTC)}
    )  # fmt: skip


def test_agreement_report() -> None:
    items = [item(i, "dev" if i % 2 == 0 else "test") for i in range(6)]
    a = {
        it.key: _lab(it, lab)
        for it, lab in zip(items, ["low", "ok", "ok", "low", "unsure", "ok"], strict=True)
    }
    b = {
        it.key: _lab(it, lab)
        for it, lab in zip(items[:5], ["low", "ok", "low", "low", "unsure"], strict=True)
    }
    a[items[5].key] = _lab(items[5], "ok", "INVALID: no valid JSON")
    rep = agreement_report(items, a, b)
    assert rep.n_both == 5 and rep.counts_a == {"ok": 3, "low": 2, "unsure": 1}
    assert [x.label for x in rep.agreed] == ["low", "ok", "low"]
    assert rep.agreed_by_split == {"dev": {"ok": 0, "low": 1}, "test": {"ok": 1, "low": 1}}
    assert (rep.dropped_disagree, rep.dropped_unsure, rep.invalid_a) == (1, 1, 1)
    assert rep.kappa is not None and 0 < rep.kappa < 1
    assert rep.raw_agreement == 0.8
    text = render_agreement(rep)
    assert "no human validation" in text and "Cohen's kappa A vs B" in text
    empty = agreement_report(items, {}, {})
    assert empty.n_both == 0 and empty.kappa is None and empty.raw_agreement == 0.0


def test_cli_llm_label_agreement_and_offline_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from slopwatch.cli import app
    from slopwatch.store import write_jsonl

    labels = tmp_path / "labels"
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "LABELING.md").write_text(
        (REPO_ROOT / "LABELING.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    items = [item(i, "dev" if i % 2 == 0 else "test") for i in range(4)]
    write_jsonl(labels / "sample.jsonl", items, key=lambda it: 0)
    monkeypatch.setenv("SLOPWATCH_DATA_DIR", str(data))
    monkeypatch.setenv("SLOPWATCH_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("SLOPWATCH_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("GEMINI_API_KEY", "GKEY-not-real")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "CF-TOKEN-not-real")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "ACCT-SECRET")

    def send(self: httpx.Client, request: httpx.Request, **kw: object) -> httpx.Response:
        user = json.loads(request.content)
        text = json.dumps(user)
        label = "low" if "Title 0" in text or "Title 1" in text else "ok"
        reply = json.dumps({"label": label, "reason": "mock"})
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, json=gemini_response(reply), request=request)
        return httpx.Response(200, json=cf_response(reply, 40.0), request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    runner = CliRunner()
    bad = runner.invoke(app, ["llm-label", "--labeler", "c"])
    assert bad.exit_code == 2
    ra = runner.invoke(
        app,
        ["llm-label", "--labeler", "a", "--min-interval", "0", "--context", "excerpt"],
        env={"COLUMNS": "200"},
    )
    assert ra.exit_code == 0, ra.output
    rb = runner.invoke(
        app, ["llm-label", "--labeler", "b", "--context", "excerpt"], env={"COLUMNS": "200"}
    )
    assert rb.exit_code == 0, rb.output
    assert "neurons 160.0" in rb.output
    ag = runner.invoke(app, ["agreement"], env={"COLUMNS": "200"})
    assert ag.exit_code == 0, ag.output
    assert "Cohen's kappa A vs B: 1.00" in ag.output and "agreed on ok/low: 4" in ag.output
    assert len((labels / "labels.jsonl").read_text(encoding="utf-8").splitlines()) == 4
    fixtures = "".join(
        p.read_text(encoding="utf-8") for p in (tmp_path / "fixtures").glob("*.json")
    )
    for secret in ("GKEY-not-real", "CF-TOKEN-not-real", "ACCT-SECRET"):
        assert secret not in fixtures
    usage = (labels / "llm_usage.jsonl").read_text(encoding="utf-8")
    assert '"neurons": 160.0' in usage

    # replay: no keys, no network, same labels
    for var in ("GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.delenv(var)

    def no_send(self: httpx.Client, request: httpx.Request, **kw: object) -> httpx.Response:
        raise AssertionError("network used in replay")

    monkeypatch.setattr(httpx.Client, "send", no_send)
    before = {k: v.label for k, v in _load(labels / "llm_b.jsonl").items()}
    (labels / "llm_b.jsonl").unlink()
    rp = runner.invoke(
        app, ["llm-label", "--labeler", "b", "--cache-mode", "replay", "--context", "excerpt"]
    )
    assert rp.exit_code == 0, rp.output
    assert {k: v.label for k, v in _load(labels / "llm_b.jsonl").items()} == before


def _load(path: Path) -> dict[tuple[str, str], Label]:
    from slopwatch.label import load_labels

    return load_labels(path)


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s

    def clock(self) -> float:
        return self.now


def test_gemini_paces_requests_and_waits_on_429() -> None:
    from slopwatch.llm_label import GeminiBackend

    statuses = iter([200, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 429:
            return httpx.Response(
                429, json={"error": {"message": "Resource exhausted (per minute)"}}
            )
        return httpx.Response(200, json=gemini_response('{"label": "ok", "reason": "x"}'))

    ft = FakeTime()
    with make_client(Recorder(handler), max_retries=0) as http:
        g = GeminiBackend(http, SecretStr("k"), min_interval=7.0, sleep=ft.sleep, clock=ft.clock)
        g.ask("s", "u1", attempt=0)
        g.ask("s", "u2", attempt=0)  # paced 7s, then 429 -> waits 15s, then paced again
        assert g.ask("s", "u1", attempt=0).from_cache  # cache hit: no pacing
    assert ft.slept == [7.0, 15.0]


def test_gemini_daily_quota_raises_quota_exhausted() -> None:
    from slopwatch.llm_label import GeminiBackend, QuotaExhausted

    body = {"error": {"message": "Quota exceeded for GenerateRequestsPerDay"}}
    with make_client(Recorder(lambda r: httpx.Response(429, json=body)), max_retries=0) as http:
        g = GeminiBackend(http, SecretStr("k"), min_interval=0, sleep=lambda s: None)
        with pytest.raises(QuotaExhausted, match="daily"):
            g.ask("s", "u", attempt=0)
    per_minute = {"error": {"message": "rate limit"}}
    with make_client(
        Recorder(lambda r: httpx.Response(429, json=per_minute)), max_retries=0
    ) as http:
        g = GeminiBackend(http, SecretStr("k"), min_interval=0, sleep=lambda s: None)
        with pytest.raises(QuotaExhausted, match="kept returning HTTP 429"):
            g.ask("s", "u", attempt=0)
    overloaded = iter([503, 503, 200])

    def flaky(request: httpx.Request) -> httpx.Response:
        status = next(overloaded)
        if status == 503:
            return httpx.Response(503, json={"error": {"message": "model overloaded"}})
        return httpx.Response(200, json=gemini_response('{"label": "low", "reason": "x"}'))

    ft = FakeTime()
    with make_client(Recorder(flaky), max_retries=0) as http:
        g = GeminiBackend(http, SecretStr("k"), min_interval=0, sleep=ft.sleep, clock=ft.clock)
        assert parse_reply(g.ask("s", "u", attempt=0).text) == ("low", "x")
    assert ft.slept == [15.0, 30.0]


def test_network_errors_wait_then_resume_or_stop_cleanly() -> None:
    from slopwatch.llm_label import QuotaExhausted

    calls = iter(["down", "down", "ok"])

    def handler(request: httpx.Request) -> httpx.Response:
        if next(calls) == "down":
            raise httpx.ConnectError("no route")
        return httpx.Response(200, json=cf_response('{"label": "ok", "reason": "x"}', 5.0))

    waits: list[float] = []
    written: list[Label] = []
    with make_client(Recorder(handler), max_retries=0) as http:
        backend = CloudflareBackend(http, SecretStr("t"), SecretStr("a"))
        label_items([item(0)], backend, GUIDE, done=set(), write=written.append, sleep=waits.append)
    assert waits == [15.0, 30.0] and [w.label for w in written] == ["ok"]

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with make_client(Recorder(dead), max_retries=0) as http:
        backend = CloudflareBackend(http, SecretStr("t"), SecretStr("a"))
        with pytest.raises(QuotaExhausted, match="cloudflare unavailable"):
            label_items([item(1)], backend, GUIDE, done=set(), write=written.append,
                        sleep=lambda s: None)  # fmt: skip
    bad_request = Recorder(lambda r: httpx.Response(401, json={}))
    with make_client(bad_request, max_retries=0) as http:
        backend = CloudflareBackend(http, SecretStr("t"), SecretStr("a"))
        with pytest.raises(Exception, match="Cloudflare HTTP 401"):
            label_items([item(2)], backend, GUIDE, done=set(), write=written.append)


def test_round2_prompt_shows_main_text_and_stays_blind() -> None:
    from slopwatch.llm_label import MAIN_TEXT_CHARS

    text = "word " * 1000
    prompt = item_prompt(item(), text)
    assert "Main text (first 2000 characters): word word" in prompt
    assert "Excerpt:" not in prompt
    body = prompt.split("characters): ", 1)[1]
    assert len(body) <= MAIN_TEXT_CHARS
    assert item_prompt(item(), "").endswith("(no text available)")
    low = (system_prompt(GUIDE) + prompt).lower()
    assert not [w for w in ["slop_risk", "rubric", "score", *Signals.model_fields] if w in low]
    assert "2,000 characters" in GUIDE


def test_cli_context_main_requires_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from slopwatch.cli import app
    from slopwatch.store import write_jsonl

    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "LABELING.md").write_text(
        (REPO_ROOT / "LABELING.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    write_jsonl(tmp_path / "labels" / "sample.jsonl", [item(0)], key=lambda it: 0)
    monkeypatch.setenv("SLOPWATCH_DATA_DIR", str(data))
    monkeypatch.setenv("SLOPWATCH_CACHE_PATH", str(tmp_path / "missing.sqlite"))
    r = CliRunner().invoke(app, ["llm-label", "--labeler", "a"])
    assert r.exit_code == 2 and "no snapshot cache" in r.output
    bad = CliRunner().invoke(app, ["llm-label", "--labeler", "a", "--context", "nope"])
    assert bad.exit_code == 2


def test_audit_report_compares_judge_c_with_ground_truth() -> None:
    items = [item(i) for i in range(4)]
    a = {it.key: _lab(it, lab) for it, lab in zip(items, ["low", "ok", "ok", "low"], strict=True)}
    b = {it.key: _lab(it, lab) for it, lab in zip(items, ["low", "ok", "low", "low"], strict=True)}
    c = {
        it.key: _lab(it, lab) for it, lab in zip(items, ["low", "low", "ok", "unsure"], strict=True)
    }
    agreed = {(x.url, x.query_id): x for x in agreement_report(items, a, b).agreed}
    rep = audit_report(a, b, c, agreed)
    assert rep.n_c == 4 and rep.n_agreed == 3
    assert rep.c_on_agreed == {
        "ok": {"ok": 0, "low": 1, "unsure": 0},
        "low": {"ok": 0, "low": 1, "unsure": 1},
    }
    text = render_audit(rep, "judge-model")
    assert "never used for fitting" in text and "C confirms 1 of 3 agreed items (33%)" in text


def test_cli_judge_c_requires_paid_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from slopwatch.cli import app

    monkeypatch.delenv("GEMINI_PAID_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = CliRunner().invoke(app, ["llm-label", "--labeler", "c", "--cache-mode", "live"])
    assert r.exit_code == 2 and "GEMINI_PAID_API_KEY or GEMINI_API_KEY" in r.output
    bad = CliRunner().invoke(app, ["llm-label", "--labeler", "z"])
    assert bad.exit_code == 2


def test_vertex_backend_uses_bearer_token_and_hides_project_and_token() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "aiplatform.googleapis.com"
        assert "/projects/my-proj-not-real/locations/global/" in request.url.path
        assert request.headers["authorization"] == "Bearer TOKEN-not-real"
        assert "x-goog-api-key" not in request.headers
        return httpx.Response(200, json=gemini_response('{"label": "low", "reason": "x"}'))

    def token() -> str:
        calls.append("t")
        return "TOKEN-not-real"

    rec = Recorder(handler)
    with make_client(rec) as http:
        backend = VertexGeminiBackend(http, "my-proj-not-real", "judge-model", token=token)
        reply = backend.ask(system_prompt(GUIDE), item_prompt(item()), attempt=0)
        assert parse_reply(reply.text) == ("low", "x") and reply.model == "judge-model"
        again = backend.ask(system_prompt(GUIDE), item_prompt(item()), attempt=0)
        assert again.from_cache and len(rec.requests) == 1 and calls == ["t"]
        dump = " ".join(http.cache._db.iterdump())
        assert "TOKEN-not-real" not in dump and "my-proj-not-real" not in dump
