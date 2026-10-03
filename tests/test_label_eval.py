"""Labeling and evaluation tests on SYNTHETIC rows, labels and scores."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from slopwatch.evaluate import evaluate, render_markdown
from slopwatch.label import (
    LabelItem,
    _allocate,
    draw_sample,
    load_labels,
    load_sample,
    run_labeler,
)
from slopwatch.models import Label, Page, Query, Score, SerpRow
from slopwatch.store import write_jsonl

QUERIES = {
    (f"{cat}-{i}", loc): Query(id=f"{cat}-{i}", category=full, locale=loc, text=f"{cat} q{i}")
    for cat, full in [("h", "health"), ("f", "personal_finance")]
    for i in range(5)
    for loc in ("IN", "US")
}


def rows() -> list[SerpRow]:
    out = []
    for (qid, loc), _q in QUERIES.items():
        engines = ["google", "duckduckgo"] if loc == "IN" else ["google"]
        for engine in engines:
            for rank in range(1, 11):
                url = f"https://{engine}{rank}.example/{loc}/{qid}"
                out.append(
                    SerpRow(
                        query_id=qid, engine=engine, locale=loc, rank=rank, url=url,
                        domain="d", title=f"T {qid} {rank}", snippet="s", request_hash=qid,
                    )
                )  # fmt: skip
    return out


def test_allocate_is_proportional_and_exact() -> None:
    sizes = {("a", "", ""): 50, ("b", "", ""): 30, ("c", "", ""): 20}
    assert _allocate(sizes, 10) == {("a", "", ""): 5, ("b", "", ""): 3, ("c", "", ""): 2}
    odd = _allocate({("a", "", ""): 2, ("b", "", ""): 1, ("c", "", ""): 1}, 3)
    assert sum(odd.values()) == 3 and all(odd[k] <= s for k, s in [(("a", "", ""), 2)])
    assert _allocate({("a", "", ""): 2}, 10) == {("a", "", ""): 2}


def test_draw_sample_is_stratified_seeded_and_scored_only() -> None:
    all_rows = rows()
    scored = {r.url for r in all_rows if r.rank != 10}  # rank-10 pages "unscored"
    pages = [
        Page(url=u, status=200, fetched_at=None, title="Page title", excerpt="ex") for u in scored
    ]
    a = draw_sample(all_rows, pages, scored, QUERIES, n=40, seed=7)
    b = draw_sample(all_rows, pages, scored, QUERIES, n=40, seed=7)
    assert a == b and len(a) == 40
    assert a != draw_sample(all_rows, pages, scored, QUERIES, n=40, seed=8)
    assert all(it.url in scored and it.rank != 10 for it in a)
    strata = Counter((it.category, it.engine, it.locale) for it in a)
    # 6 strata of equal size -> 40/6: every stratum gets 6 or 7
    assert set(strata.values()) <= {6, 7} and len(strata) == 6
    splits = Counter(it.split for it in a)
    assert abs(splits["dev"] - splits["test"]) <= len(strata)
    assert a[0].title == "Page title" and a[0].excerpt == "ex"
    assert len({it.key for it in a}) == 40


def test_same_url_and_query_is_labeled_once() -> None:
    q = {("q", "IN"): Query(id="q", category="health", locale="IN", text="t")}
    dup = [
        SerpRow(
            query_id="q", engine=e, locale="IN", rank=1, url="https://a.example/",
            domain="a.example", title="t", snippet="s", request_hash=e,
        )
        for e in ("google", "duckduckgo", "yahoo")
    ]  # fmt: skip
    sample = draw_sample(dup, [], {"https://a.example/"}, q, n=10, seed=7)
    assert len(sample) == 1 and sample[0].title == "t"


def _items() -> list[LabelItem]:
    return [
        LabelItem(
            url=f"https://x.example/{i}", query_id="q", query_text="best phone",
            category="product_reviews", engine="google", locale="IN", rank=i + 1,
            title=f"T{i}", excerpt="", split="dev" if i % 2 == 0 else "test",
        )
        for i in range(4)
    ]  # fmt: skip


def test_labeler_keys_notes_skip_back_and_resume(tmp_path: Path) -> None:
    items = _items()
    sample = tmp_path / "sample.jsonl"
    write_jsonl(sample, items, key=lambda it: it.rank)
    assert load_sample(sample) == sorted(items, key=lambda it: it.rank)
    labels = tmp_path / "labels.jsonl"
    out: list[str] = []
    keys = iter(["n", "o", "x", "s", "l", "b", "u", "q"])
    written = run_labeler(
        items, labels, getch=lambda: next(keys), prompt=lambda _p: " ad-heavy ",
        echo=out.append, now=lambda: datetime(2026, 10, 4, tzinfo=UTC),
    )  # fmt: skip
    # item0 ok (with note), x unknown, skip item1, item2 low, back to item2, relabel unsure
    assert written == 3
    got = load_labels(labels)
    assert got[("https://x.example/0", "q")].label == "ok"
    assert got[("https://x.example/0", "q")].note == "ad-heavy"
    assert got[("https://x.example/2", "q")].label == "unsure"  # latest wins
    assert ("https://x.example/1", "q") not in got
    shown = "\n".join(out)
    assert "QUERY  best phone" in shown and "unknown key 'x'" in shown
    assert "slop" not in shown.lower() and "risk" not in shown.lower()  # never the score
    # resume: only unlabeled items are shown
    out.clear()
    keys2 = iter(["l", "o"])
    run_labeler(items, labels, getch=lambda: next(keys2), prompt=str, echo=out.append)
    assert "2/4 already labeled; 2 to go" in out[0]
    assert len(load_labels(labels)) == 4


def _score(url: str, risk: float, band: str) -> Score:
    return Score.model_validate({"url": url, "slop_risk": risk, "band": band, "reasons": ["r"]})


def test_evaluate_metrics_confusion_and_errors() -> None:
    items = _items()
    t = datetime(2026, 10, 4, tzinfo=UTC)
    labels = {
        it.key: Label(url=it.url, query_id="q", label=lab, labeled_at=t)
        for it, lab in zip(items, ["low", "ok", "low", "unsure"], strict=True)
    }
    scores = {
        items[0].url: _score(items[0].url, 0.9, "low"),  # TP
        items[1].url: _score(items[1].url, 0.7, "low"),  # FP
        items[2].url: _score(items[2].url, 0.1, "ok"),  # FN
        items[3].url: _score(items[3].url, 0.6, "low"),  # unsure: excluded
    }
    rep = evaluate(items, labels, scores, split="all")
    assert rep.n == 3
    assert (rep.precision_low, rep.recall_low, rep.f1_low) == (0.5, 0.5, 0.5)
    assert rep.confusion["unsure"]["low"] == 1 and rep.confusion["ok"]["low"] == 1
    # FN at risk 0.1 (severity 0.9) ranks above FP at 0.7
    assert [e.label for e in rep.errors] == ["low", "ok"]
    dev = evaluate(items, labels, scores, split="dev")
    assert dev.n == 2 and dev.split == "dev"
    md = render_markdown(rep)
    assert "| Precision | 0.50 |" in md and "false negative" in md
    empty = evaluate(items, {}, scores, split="test")
    assert (empty.n, empty.precision_low, empty.f1_low) == (0, 0.0, 0.0)
    assert "None." in render_markdown(empty)
