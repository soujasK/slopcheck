"""SlopWatch command line.

Every command takes ``--cache-mode live|record|replay`` and ends by printing the
credits it spent and the project ledger total. ``replay`` reads only the committed
fixtures/ directory and needs no API key.

Exit codes: 0 ok, 1 a doctor check failed, 2 usage error, 3 credit cap hit.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from slopwatch import __version__, pipeline
from slopwatch.cache import Cache
from slopwatch.config import (
    DEFAULT_RUN_CREDITS,
    LIVE_CREDIT_CAP,
    LIVE_SESSION_CREDITS,
    PROJECT_CREDIT_CAP,
    CacheMode,
    Settings,
)
from slopwatch.demo import Source as DemoSource
from slopwatch.demo import ask_agent, run_demo
from slopwatch.demo import load_questions as load_demo_questions
from slopwatch.demo import render_markdown as render_demo
from slopwatch.demo import to_json as demo_to_json
from slopwatch.evaluate import evaluate as evaluate_labels
from slopwatch.evaluate import render_markdown
from slopwatch.filter import live_filter, offline_filter
from slopwatch.filter.core import SlopFilter
from slopwatch.fit import CANDIDATES, fit_rubric, rubric_yaml
from slopwatch.http import HttpClient, HttpError, user_agent
from slopwatch.label import (
    append_label,
    draw_sample,
    load_labels,
    load_sample,
    recheck_items,
    run_labeler,
    self_agreement,
)
from slopwatch.llm_label import (
    DEFAULT_NEURON_BUDGET,
    GEMINI_MODEL,
    JUDGE_C_MODEL,
    CloudflareBackend,
    GeminiBackend,
    QuotaExhausted,
    RunStats,
    VertexGeminiBackend,
    agreement_report,
    audit_report,
    label_items,
    load_guide,
    render_agreement,
    render_audit,
)
from slopwatch.models import Page, RelevanceRecord, SerpRow, SignalRecord
from slopwatch.pages import PageFetcher
from slopwatch.platform import load_platforms
from slopwatch.queries import Job, PlanError, load_plan, serp_params
from slopwatch.report.observatory import build as build_report
from slopwatch.report.observatory import compute as compute_overview
from slopwatch.report.story import build_story
from slopwatch.score import MIN_READABLE_CHARS, load_rubric, row_signals, score_rows
from slopwatch.serp import ProjectLedger, SerpClient, SerpError
from slopwatch.signals import load_lists
from slopwatch.store import (
    PAGES,
    RELEVANCE,
    SCORES,
    SERP_META,
    SERPS,
    SIGNALS,
    read_jsonl,
    write_jsonl,
)

app = typer.Typer(
    name="slopwatch",
    help="Don't feed your agent slop.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CREDIT_CAP = 0, 1, 2, 3

CacheModeOpt = Annotated[
    CacheMode | None,
    typer.Option("--cache-mode", help="live | record | replay (default: SLOPWATCH_CACHE_MODE)"),
]


def _version(value: bool) -> None:
    if value:
        console.print(f"slopwatch {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """Don't feed your agent slop."""


def open_cache(settings: Settings, mode: CacheMode) -> Cache:
    """Replay reads the committed fixtures only; live/record use the local SQLite cache."""
    if mode is CacheMode.REPLAY:
        if settings.fixtures_dir.is_dir():
            return Cache.from_fixtures(settings.fixtures_dir)
        return Cache(":memory:", mode=CacheMode.REPLAY)
    return Cache(settings.cache_path, mode=mode, ttl_seconds=settings.cache_ttl_seconds)


def credits_line(spent_this_run: int, ledger: ProjectLedger, *, live: bool = False) -> str:
    try:
        total = (
            f"live searches so far {ledger.spent} (separate from the research ledger)"
            if live
            else f"project ledger {ledger.spent}/{ledger.cap} ({ledger.remaining} left)"
        )
    except ValueError:
        total = f"project ledger {ledger.path} is UNREADABLE"
    return f"credits: {spent_this_run} spent by this command; {total}"


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


_STYLE = {Status.OK: "green", Status.WARN: "yellow", Status.FAIL: "red"}


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def _yaml_status(path: Path) -> str:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return str(raw.get("status", "?")) if isinstance(raw, dict) else "?"


def run_checks(settings: Settings, mode: CacheMode, *, offline: bool) -> list[Check]:
    checks: list[Check] = []
    py = sys.version_info
    checks.append(
        Check("python", Status.OK if py >= (3, 11) else Status.FAIL, f"{py.major}.{py.minor}")
    )

    ledger = ProjectLedger(settings.ledger_path)
    try:
        spent = ledger.spent
    except ValueError as exc:  # corrupt ledger: refuse to guess
        checks.append(Check("credits (project ledger)", Status.FAIL, f"unreadable: {exc}"))
        return checks
    checks.append(
        Check(
            "credits (project ledger)",
            Status.WARN if spent >= 0.8 * PROJECT_CREDIT_CAP else Status.OK,
            f"{spent}/{PROJECT_CREDIT_CAP} spent, {ledger.remaining} left; "
            f"per-command default cap {settings.max_credits}",
        )
    )

    queries_path = settings.data_dir / "queries.yaml"
    try:
        plan = load_plan(queries_path)
    except (OSError, PlanError, ValueError) as exc:
        checks.append(Check("queries.yaml", Status.FAIL, str(exc).splitlines()[0]))
    else:
        needed = plan.credits_needed()
        checks.append(
            Check(
                "queries.yaml",
                Status.OK if plan.frozen else Status.WARN,
                f"{plan.status}: {len(plan.specs)} queries, {len(plan.jobs)} searches "
                f"(<= {needed} credits uncached)",
            )
        )
        if needed > ledger.remaining:
            checks.append(
                Check("budget", Status.WARN, f"plan needs {needed} > {ledger.remaining} left")
            )
    rubric_path = settings.data_dir / "rubric.yaml"
    if rubric_path.exists():
        status = _yaml_status(rubric_path)
        checks.append(
            Check("rubric.yaml", Status.OK if status == "frozen" else Status.WARN, status)
        )
    else:
        checks.append(Check("rubric.yaml", Status.FAIL, "missing"))

    try:
        cache = open_cache(settings, mode)
    except Exception as exc:  # any failure here means nothing can run
        checks.append(Check("cache", Status.FAIL, f"{settings.cache_path}: {exc}"))
        return checks
    with cache:
        where = settings.fixtures_dir if mode is CacheMode.REPLAY else settings.cache_path
        checks.append(Check("cache", Status.OK, f"mode={mode}, {where} ({len(cache)} responses)"))
        n_fixtures = (
            len(list(settings.fixtures_dir.glob("*.json"))) if settings.fixtures_dir.is_dir() else 0
        )
        checks.append(Check("fixtures", Status.OK, f"{n_fixtures} recorded responses"))

        if settings.serpapi_api_key is None:
            checks.append(
                Check(
                    "SERPAPI_API_KEY",
                    Status.WARN,
                    "not set: collection disabled; --cache-mode replay works offline",
                )
            )
        elif offline or mode is CacheMode.REPLAY:
            checks.append(Check("SERPAPI_API_KEY", Status.OK, "set (not verified: offline)"))
        else:
            with HttpClient(cache, timeout=settings.http_timeout_seconds) as http:
                serp = SerpClient(http, settings.serpapi_api_key, project=ledger)
                try:
                    acct = serp.account()
                except HttpError as exc:
                    checks.append(Check("SERPAPI_API_KEY", Status.FAIL, f"rejected: {exc}"))
                else:
                    left = acct.get("total_searches_left", acct.get("plan_searches_left"))
                    checks.append(
                        Check(
                            "SERPAPI_API_KEY",
                            Status.OK,
                            f"valid; plan={acct.get('plan_name', '?')}, "
                            f"used this month={acct.get('this_month_usage', '?')}, "
                            f"account left={left}",
                        )
                    )
                    if isinstance(left, int) and left < ledger.remaining:
                        checks.append(
                            Check(
                                "credits (SerpApi account)",
                                Status.WARN,
                                f"account has {left} left, fewer than the project's "
                                f"{ledger.remaining}",
                            )
                        )
    return checks


def _query_texts(settings: Settings) -> dict[str, str]:
    plan = load_plan(settings.data_dir / "queries.yaml")
    return {spec.id: spec.text for spec in plan.specs}


def _settings_and_mode(cache_mode: CacheMode | None) -> tuple[Settings, CacheMode]:
    settings = Settings()
    return settings, cache_mode or settings.cache_mode


@app.command()
def collect(
    plan_path: Annotated[
        Path | None, typer.Option("--plan", help="Query plan (default data/queries.yaml).")
    ] = None,
    max_credits: Annotated[
        int | None,
        typer.Option("--max-credits", min=0, help=f"Per-run cap (default {DEFAULT_RUN_CREDITS})."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help=f"Confirm spending more than {DEFAULT_RUN_CREDITS}.")
    ] = False,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--job", help="Run only this plan job, as QUERY_ID/ENGINE/LOCALE (repeatable)."
        ),
    ] = None,
    cache_mode: CacheModeOpt = None,
) -> None:
    """Run the frozen query plan through SerpApi and write data/serps.jsonl."""
    settings, mode = _settings_and_mode(cache_mode)
    ledger = ProjectLedger(settings.ledger_path)
    plan = load_plan(plan_path or settings.data_dir / "queries.yaml")
    if not plan.frozen:
        err_console.print("collect: queries.yaml is a draft; freeze and commit it first")
        raise typer.Exit(EXIT_USAGE)
    if only:
        try:
            plan = plan.restrict(only)
        except PlanError as exc:
            err_console.print(f"collect: {exc}")
            raise typer.Exit(EXIT_USAGE) from None
    cap = settings.max_credits if max_credits is None else max_credits
    with (
        open_cache(settings, mode) as cache,
        HttpClient(
            cache, timeout=settings.http_timeout_seconds, max_retries=settings.http_max_retries
        ) as http,
    ):
        serp = SerpClient(http, settings.serpapi_api_key, project=ledger, max_credits=cap)
        pre = pipeline.preview(plan, serp)
        console.print(
            f"collect: {pre.total} searches in plan; {pre.cached} cached, "
            f"{pre.to_spend} would spend credits (run cap {cap}, project left {ledger.remaining})"
        )
        if pre.to_spend > cap:
            err_console.print(f"collect: needs {pre.to_spend} credits; rerun with --max-credits")
            console.print(credits_line(0, ledger))
            raise typer.Exit(EXIT_USAGE)
        if pre.to_spend > DEFAULT_RUN_CREDITS and not yes:
            err_console.print(f"collect: rerun with --yes to spend {pre.to_spend} credits")
            console.print(credits_line(0, ledger))
            raise typer.Exit(EXIT_USAGE)

        def tick(i: int, job: Job) -> None:
            if i % 10 == 0 or i == pre.total:
                console.print(f"  {i}/{pre.total} searches")

        result = pipeline.collect(plan, serp, progress=tick)
        data = settings.data_dir
        n_rows = write_jsonl(
            data / SERPS, result.rows, key=lambda r: (r.locale, r.engine, r.query_id, r.rank)
        )
        write_jsonl(data / SERP_META, result.meta, key=lambda m: (m.locale, m.engine, m.query_id))
        if mode is not CacheMode.REPLAY:
            n_fx = cache.export_dir(settings.fixtures_dir, only=result.keys)
            console.print(f"collect: exported {n_fx} SerpApi fixtures to {settings.fixtures_dir}")
        console.print(f"collect: {result.done}/{pre.total} searches, {n_rows} organic rows")
        console.print(credits_line(serp.ledger.spent, ledger))
    if result.error:
        err_console.print(f"collect: stopped early: {result.error}")
        raise typer.Exit(EXIT_CREDIT_CAP)


@app.command()
def fetch(
    limit: Annotated[
        int | None, typer.Option("--limit", min=1, help="Fetch only the first N URLs (dev).")
    ] = None,
    cache_mode: CacheModeOpt = None,
) -> None:
    """Fetch every SERP URL once (robots-aware) and write pages + signals JSONL.

    The only step that needs the network: page HTML is never committed, so a
    replay uses the committed data/pages.jsonl and data/signals.jsonl instead.
    """
    settings, mode = _settings_and_mode(cache_mode)
    ledger = ProjectLedger(settings.ledger_path)
    if mode is CacheMode.REPLAY:
        err_console.print(
            "fetch: needs the network (page HTML is not committed). In replay mode, "
            "score/evaluate/report read the committed data/pages.jsonl and signals.jsonl."
        )
        console.print(credits_line(0, ledger))
        raise typer.Exit(EXIT_USAGE)
    data = settings.data_dir
    rows = read_jsonl(data / SERPS, SerpRow)
    if not rows:
        err_console.print("fetch: no SERP rows; run `slopwatch collect` first")
        raise typer.Exit(EXIT_USAGE)
    urls = pipeline.unique_urls(rows)[:limit]
    lists = load_lists(data)
    console.print(f"fetch: {len(urls)} unique URLs from {len(rows)} SERP rows")
    if not settings.contact_url:
        err_console.print(
            "fetch: SLOPWATCH_CONTACT_URL not set; some sites refuse anonymous crawlers"
        )
    with (
        open_cache(settings, mode) as cache,
        HttpClient(
            cache,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            agent=user_agent(settings.contact_url),
        ) as http,
    ):

        def tick(i: int, page: Page) -> None:
            if i % 25 == 0 or i == len(urls):
                console.print(f"  {i}/{len(urls)} pages")

        fetcher = PageFetcher(http, max_bytes=settings.page_max_bytes)
        result = pipeline.fetch_pages(urls, fetcher, lists, progress=tick)
    write_jsonl(data / PAGES, result.pages, key=lambda p: p.url)
    write_jsonl(data / SIGNALS, result.records, key=lambda r: r.url)
    if limit is None:
        with open_cache(settings, mode) as cache:
            rel = pipeline.relevance_records(rows, result.records, cache, _query_texts(settings))
        write_jsonl(data / RELEVANCE, rel, key=lambda r: (r.url, r.query_id))
    reasons = Counter(p.unscored_reason for p in result.pages if p.unscored_reason)
    console.print(f"fetch: {len(result.records)} scored, {sum(reasons.values())} unscored")
    for reason, n in sorted(reasons.items()):
        console.print(f"  unscored {reason}: {n}")
    if limit is None:
        gaps = pipeline.coverage_gaps(rows, result.pages, result.records)
        if gaps:  # pragma: no cover - invariant guard
            err_console.print(f"fetch: {len(gaps)} URLs have neither signals nor a reason")
            raise typer.Exit(EXIT_FAIL)
    console.print(credits_line(0, ledger))


@app.command()
def resignal() -> None:
    """Re-extract signals for scored pages from the local HTML cache (hash-checked).

    Needs the local cache from the original `fetch` (page HTML is never
    committed). Refuses if any page's HTML is missing or differs from the hash
    in data/signals.jsonl.
    """
    settings = Settings()
    records = read_jsonl(settings.data_dir / SIGNALS, SignalRecord)
    if not records:
        err_console.print("resignal: no data/signals.jsonl")
        raise typer.Exit(EXIT_USAGE)
    with Cache(settings.cache_path, mode=CacheMode.LIVE) as cache:
        try:
            fresh = pipeline.resignal(records, cache, load_lists(settings.data_dir))
        except pipeline.SnapshotMismatch as exc:
            err_console.print(f"resignal: {exc}")
            raise typer.Exit(EXIT_FAIL) from None
    write_jsonl(settings.data_dir / SIGNALS, fresh, key=lambda r: r.url)
    rows = read_jsonl(settings.data_dir / SERPS, SerpRow)
    with Cache(settings.cache_path, mode=CacheMode.LIVE) as cache:
        rel = pipeline.relevance_records(rows, fresh, cache, _query_texts(settings))
    write_jsonl(settings.data_dir / RELEVANCE, rel, key=lambda r: (r.url, r.query_id))
    console.print(f"resignal: {len(rel)} (url, query) relevance records")
    console.print(f"resignal: {len(fresh)} pages re-extracted from hash-verified snapshots")


SAMPLE = "sample.jsonl"
LABELS = "labels.jsonl"
RECHECK = "recheck.jsonl"


def _labels_dir() -> Path:
    """labels/ or, with SLOPWATCH_LABEL_SET=name, labels/<name>/ (e.g. a fresh
    held-out round)."""
    settings = Settings()
    base = settings.data_dir.parent / "labels"
    return base / settings.label_set if settings.label_set else base


def _used_urls() -> set[str]:
    """URLs in every existing label sample (a new set must not reuse them)."""
    base = Settings().data_dir.parent / "labels"
    used: set[str] = set()
    for path in base.rglob(SAMPLE):
        used.update(it.url for it in load_sample(path))
    return used


def _load_scored(settings: Settings) -> tuple[list[SerpRow], list[SignalRecord]]:
    rows = read_jsonl(settings.data_dir / SERPS, SerpRow)
    records = read_jsonl(settings.data_dir / SIGNALS, SignalRecord)
    if not rows or not records:
        err_console.print("no SERP rows or signals; run `slopwatch collect` and `fetch` first")
        raise typer.Exit(EXIT_USAGE)
    return rows, records


@app.command()
def score(cache_mode: CacheModeOpt = None) -> None:
    """Score every fetched page with data/rubric.yaml (slop_risk: higher = worse).

    Reads only committed data (signals.jsonl), so it works in replay mode.
    """
    settings, _mode = _settings_and_mode(cache_mode)
    rows, records = _load_scored(settings)
    rubric = load_rubric(settings.data_dir / "rubric.yaml")
    relevance = read_jsonl(settings.data_dir / RELEVANCE, RelevanceRecord)
    scores = list(score_rows(rows, records, relevance, rubric).values())
    write_jsonl(settings.data_dir / SCORES, scores, key=lambda s: (s.url, s.query_id or ""))
    bands = Counter(s.band for s in scores)
    console.print(
        f"score: rubric v{rubric.version} ({rubric.status}); {len(scores)} results scored: "
        + ", ".join(f"{b} {bands.get(b, 0)}" for b in ("ok", "mixed", "low"))
    )
    console.print(credits_line(0, ProjectLedger(settings.ledger_path)))


@app.command()
def label(
    n: Annotated[int, typer.Option("--n", min=1, help="Sample size.")] = 200,
    seed: Annotated[int, typer.Option("--seed", help="Sampling seed.")] = 7,
    recheck: Annotated[
        int | None,
        typer.Option("--recheck", min=1, help="Blindly re-label N labeled items (consistency)."),
    ] = None,
) -> None:
    """Draw the label sample (first run), then label it one page at a time.

    The first run only draws labels/sample.jsonl and stops, so it can be
    committed before any labeling. The labeler never shows scores.
    """
    settings = Settings()
    labels_dir = _labels_dir()
    sample_path = labels_dir / SAMPLE
    if not sample_path.exists():
        rows, records = _load_scored(settings)
        pages = read_jsonl(settings.data_dir / PAGES, Page)
        plan = load_plan(settings.data_dir / "queries.yaml")
        queries = {(j.query.id, j.query.locale): j.query for j in plan.jobs}
        platforms = load_platforms(settings.data_dir)
        used = _used_urls() if settings.label_set else set()
        items = draw_sample(
            rows,
            pages,
            # pages too thin to score (MIN_READABLE_CHARS) are never scored, so not drawn
            {r.url for r in records if r.signals.text_len >= MIN_READABLE_CHARS},
            queries,
            n=n,
            seed=seed,
            exclude=lambda url: platforms.kind(url) is not None or url in used,
        )
        write_jsonl(sample_path, items, key=lambda it: 0)  # keep the seeded order
        splits = Counter(it.split for it in items)
        console.print(
            f"label: drew {len(items)} items (seed {seed}; dev {splits['dev']}, "
            f"test {splits['test']}) -> {sample_path}"
        )
        console.print("label: commit labels/sample.jsonl, then run `slopwatch label` again")
        return
    items = load_sample(sample_path)
    target = labels_dir / LABELS
    if recheck is not None:
        items = recheck_items(items, load_labels(target), recheck)
        target = labels_dir / RECHECK
        console.print(
            f"label: re-check pass over {len(items)} items (your first labels are hidden)"
        )
    run_labeler(
        items,
        target,
        getch=typer.getchar,
        prompt=lambda text: str(typer.prompt(text, default="", show_default=False)),
        echo=console.print,
    )


@app.command()
def evaluate(
    split: Annotated[str, typer.Option("--split", help="dev | test | all")] = "dev",
    out: Annotated[Path | None, typer.Option("--out", help="Append the report here.")] = None,
    labels_from: Annotated[
        str,
        typer.Option(
            "--labels-from", help="agreed = A+B ground truth; c = audit judge C (secondary)"
        ),
    ] = "agreed",
    cache_mode: CacheModeOpt = None,
) -> None:
    """Precision/recall/F1 for "low" against hand labels. Tune on dev only."""
    if split not in ("dev", "test", "all"):
        err_console.print("evaluate: --split must be dev, test or all")
        raise typer.Exit(EXIT_USAGE)
    if labels_from not in ("agreed", "c"):
        err_console.print("evaluate: --labels-from must be agreed or c")
        raise typer.Exit(EXIT_USAGE)
    settings, _mode = _settings_and_mode(cache_mode)
    rows, records = _load_scored(settings)
    rubric_path = settings.data_dir / "rubric.yaml"
    rubric = load_rubric(rubric_path)
    relevance = read_jsonl(settings.data_dir / RELEVANCE, RelevanceRecord)
    scores = score_rows(rows, records, relevance, rubric)
    items = load_sample(_labels_dir() / SAMPLE)
    labels = load_labels(
        _labels_dir() / LABELS if labels_from == "agreed" else _llm_labels_path("c")
    )
    report = evaluate_labels(
        items,
        labels,
        scores,
        split=split,  # type: ignore[arg-type]
        signals=row_signals(rows, records, relevance),
    )
    digest = hashlib.sha256(rubric_path.read_bytes()).hexdigest()[:12]
    text = (
        f"<!-- rubric v{rubric.version} ({rubric.status}) sha256:{digest}; "
        f"{len(labels)} labels"
        + ("; reference = audit judge C, secondary" if labels_from == "c" else "")
        + " -->\n"
        + render_markdown(report)
    )
    n_twice, kappa = self_agreement(labels, load_labels(_labels_dir() / RECHECK))
    if n_twice:
        shown = "undefined" if kappa is None else f"{kappa:.2f}"
        text += (
            f"\nLabeler self-agreement (blind re-label of {n_twice} items): "
            f"Cohen's kappa = {shown}\n"
        )
    console.print(text, markup=False)
    if out is not None:
        with out.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        console.print(f"evaluate: appended to {out}")
    console.print(credits_line(0, ProjectLedger(settings.ledger_path)))


LLM_USAGE = "llm_usage.jsonl"


def _llm_labels_path(labeler: str) -> Path:
    return _labels_dir() / f"llm_{labeler}.jsonl"


def _neurons_today(usage_path: Path, labeler: str) -> float:
    if not usage_path.exists():
        return 0.0
    today = dt.datetime.now(dt.UTC).date().isoformat()
    total = 0.0
    for line in usage_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("labeler") == labeler and str(entry.get("ts", "")).startswith(today):
            total += float(entry.get("neurons", 0.0))
    return total


@app.command("llm-label")
def llm_label_cmd(
    labeler: Annotated[
        str,
        typer.Option("--labeler", help="a = Gemini, b = Cloudflare, c = audit judge (paid key)"),
    ],
    budget: Annotated[
        float, typer.Option("--neuron-budget", help="Cloudflare neurons allowed today.")
    ] = DEFAULT_NEURON_BUDGET,
    min_interval: Annotated[
        float, typer.Option("--min-interval", min=0, help="Seconds between Gemini requests.")
    ] = 7.0,
    model: Annotated[
        str | None, typer.Option("--model", help="Override labeler A's or C's Gemini model.")
    ] = None,
    context: Annotated[
        str,
        typer.Option(
            "--context", help="main = first 2,000 chars of main text (round 2); excerpt = round 1"
        ),
    ] = "main",
    snapshot_cache: Annotated[
        Path | None,
        typer.Option("--snapshot-cache", help="Cache holding page snapshots (default: main cache)"),
    ] = None,
    cache_mode: CacheModeOpt = None,
) -> None:
    """Blind LLM labeling of labels/sample.jsonl (validation only, never scoring)."""
    if labeler not in ("a", "b", "c"):
        err_console.print("llm-label: --labeler must be a, b or c")
        raise typer.Exit(EXIT_USAGE)
    settings, mode = _settings_and_mode(cache_mode)
    # Judge C uses GEMINI_PAID_API_KEY if set, else GEMINI_API_KEY (fine once that
    # key's project has billing; a free-tier key stops at its daily quota).
    c_key = settings.gemini_paid_api_key or settings.gemini_api_key
    if (
        labeler == "c"
        and c_key is None
        and settings.vertex_project is None
        and mode is not CacheMode.REPLAY
    ):
        err_console.print("llm-label: judge C needs GEMINI_PAID_API_KEY or GEMINI_API_KEY")
        raise typer.Exit(EXIT_USAGE)
    items = load_sample(_labels_dir() / SAMPLE)
    if not items:
        err_console.print("llm-label: no labels/sample.jsonl; run `slopwatch label` first")
        raise typer.Exit(EXIT_USAGE)
    guide = load_guide(settings.data_dir.parent / "LABELING.md")
    if context not in ("main", "excerpt"):
        err_console.print("llm-label: --context must be main or excerpt")
        raise typer.Exit(EXIT_USAGE)
    texts: dict[str, str] | None = None
    if context == "main":
        records = read_jsonl(settings.data_dir / SIGNALS, SignalRecord)
        wanted = {it.url for it in items}
        snap_path = snapshot_cache or settings.cache_path
        if not snap_path.exists():
            err_console.print(
                f"llm-label: no snapshot cache at {snap_path} (needed for --context main)"
            )
            raise typer.Exit(EXIT_USAGE)
        with Cache(snap_path, mode=CacheMode.LIVE) as snap:
            try:
                texts = pipeline.main_texts([r for r in records if r.url in wanted], snap)
            except pipeline.SnapshotMismatch as exc:
                err_console.print(f"llm-label: {exc}")
                raise typer.Exit(EXIT_FAIL) from None
    out_path = _llm_labels_path(labeler)
    done = set(load_labels(out_path))
    usage_path = _labels_dir() / LLM_USAGE
    left: float | None = None
    if labeler == "b" and mode is not CacheMode.REPLAY:
        left = max(budget - _neurons_today(usage_path, "b"), 0.0)
        console.print(f"llm-label b: neuron budget left today {left:.0f} of {budget:.0f}")
    with (
        open_cache(settings, mode) as cache,
        HttpClient(cache, timeout=120.0, max_retries=settings.http_max_retries) as http,
    ):
        backend: GeminiBackend | CloudflareBackend
        if labeler == "a":
            backend = GeminiBackend(
                http,
                settings.gemini_api_key,
                model=model or GEMINI_MODEL,
                min_interval=min_interval,
            )
        elif labeler == "c" and settings.vertex_project:
            backend = VertexGeminiBackend(
                http,
                settings.vertex_project,
                model or JUDGE_C_MODEL,
                min_interval=min_interval,
            )
        elif labeler == "c":
            backend = GeminiBackend(
                http,
                c_key,
                model=model or JUDGE_C_MODEL,
                min_interval=min_interval,
            )
        else:
            backend = CloudflareBackend(
                http, settings.cloudflare_api_token, settings.cloudflare_account_id
            )
        stats = RunStats()
        quota_note = ""
        try:
            stats = label_items(
                items,
                backend,
                guide,
                done=done,
                write=lambda lab: append_label(out_path, lab),
                neuron_budget=left,
                stats=stats,
                context=(lambda it: texts.get(it.url)) if texts is not None else None,
            )
        except QuotaExhausted as exc:
            quota_note = str(exc)
        finally:
            # export whatever was recorded, even if the run stopped early
            if mode is not CacheMode.REPLAY:
                n_fx = cache.export_dir(settings.fixtures_dir, only=cache.used)
                console.print(f"llm-label {labeler}: exported {n_fx} fixtures")
    entry = {
        "ts": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "labeler": labeler,
        "models": sorted(stats.models),
        "labeled": stats.labeled,
        "from_cache": stats.from_cache,
        "retries": stats.retries,
        "invalid_final": stats.invalid_final,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "neurons": round(stats.neurons, 2),
        "fallback_used": isinstance(backend, CloudflareBackend) and backend.fallback_used,
        "context": context,
    }
    if mode is not CacheMode.REPLAY:
        usage_path.parent.mkdir(parents=True, exist_ok=True)
        with usage_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    total = len(load_labels(out_path))
    console.print(
        f"llm-label {labeler}: labeled {stats.labeled} now ({total}/{len(items)} total), "
        f"models {', '.join(sorted(stats.models)) or '-'}, retries {stats.retries}, "
        f"invalid {stats.invalid_final}, tokens in/out {stats.input_tokens}/"
        f"{stats.output_tokens}, neurons {stats.neurons:.1f}"
    )
    if quota_note:
        console.print(f"llm-label {labeler}: stopped: {quota_note}; rerun later to continue")
    if stats.stopped_for_budget:
        console.print(
            f"llm-label {labeler}: stopped at today's neuron budget; rerun tomorrow to continue"
        )
    console.print(credits_line(0, ProjectLedger(settings.ledger_path)))


@app.command()
def agreement() -> None:
    """Labels per class for each LLM labeler, A-vs-B Cohen's kappa, agreed items.

    Writes the agreed ok/low items to labels/labels.jsonl (the ground truth used
    by `slopwatch evaluate`). Does not evaluate the scorer.
    """
    items = load_sample(_labels_dir() / SAMPLE)
    a, b = load_labels(_llm_labels_path("a")), load_labels(_llm_labels_path("b"))
    rep = agreement_report(items, a, b)
    write_jsonl(_labels_dir() / LABELS, rep.agreed, key=lambda lab: (lab.url, lab.query_id))
    console.print(render_agreement(rep), markup=False)


@app.command()
def audit() -> None:
    """Audit judge C against labelers A and B and their agreed ground truth (secondary)."""
    c = load_labels(_llm_labels_path("c"))
    if not c:
        err_console.print("audit: no judge C labels; run `slopwatch llm-label --labeler c` first")
        raise typer.Exit(EXIT_USAGE)
    rep = audit_report(
        load_labels(_llm_labels_path("a")),
        load_labels(_llm_labels_path("b")),
        c,
        load_labels(_labels_dir() / LABELS),
    )
    console.print(render_audit(rep, JUDGE_C_MODEL), markup=False)


@app.command("filter")
def filter_cmd(
    serp_json: Annotated[
        Path, typer.Option("--serp-json", help="A SerpApi JSON response ('-' = stdin).")
    ],
    threshold: Annotated[
        float | None,
        typer.Option("--threshold", help="Drop slop_risk >= this (default: low band)."),
    ] = None,
    query: Annotated[
        str | None, typer.Option("--query", help="Query text (default: search_parameters.q).")
    ] = None,
    annotate: Annotated[
        bool, typer.Option("--annotate", help="Keep every result; only add scores.")
    ] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Use committed data only (no page fetches).")
    ] = False,
) -> None:
    """Filter a SerpApi response: prints the JSON with organic_results scored/filtered."""
    raw = sys.stdin.read() if str(serp_json) == "-" else serp_json.read_text(encoding="utf-8")
    payload = json.loads(raw)
    params = payload.get("search_parameters") or {}
    q = query or params.get("q") or params.get("p")
    if not q:
        err_console.print("filter: no query (pass --query or include search_parameters.q)")
        raise typer.Exit(EXIT_USAGE)
    f = offline_filter() if offline else live_filter()
    organic = payload.get("organic_results") or []
    kept = f.apply(str(q), organic, threshold=threshold, mode="annotate" if annotate else "drop")
    payload["organic_results"] = kept
    payload["slopwatch"] = {
        "dropped": len(organic) - len(kept),
        "threshold": f.threshold(threshold),
        "rubric_version": f.rubric.version,
    }
    # UTF-8 bytes regardless of the console code page (Windows defaults to cp1252).
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        sys.stdout.write(text)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    engine: Annotated[str, typer.Option("--engine", help="google | duckduckgo | yahoo")] = "google",
    locale: Annotated[str, typer.Option("--locale", help="IN | US")] = "IN",
    threshold: Annotated[float | None, typer.Option("--threshold")] = None,
    annotate: Annotated[bool, typer.Option("--annotate")] = False,
    cache_mode: CacheModeOpt = None,
) -> None:
    """Live: search via SerpApi (1 credit unless cached), then score and filter results."""
    if engine not in ("google", "duckduckgo", "yahoo") or locale not in ("IN", "US"):
        err_console.print("search: --engine google|duckduckgo|yahoo, --locale IN|US")
        raise typer.Exit(EXIT_USAGE)
    settings, mode = _settings_and_mode(cache_mode)
    ledger = ProjectLedger(settings.live_ledger_path, cap=LIVE_CREDIT_CAP)
    with (
        open_cache(settings, mode) as cache,
        HttpClient(
            cache,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            agent=user_agent(settings.contact_url),
        ) as http,
    ):
        serp = SerpClient(http, settings.serpapi_api_key, project=ledger, max_credits=1)
        try:
            page = serp.search(engine, serp_params(engine, locale, query))  # type: ignore[arg-type]
        except SerpError as exc:
            err_console.print(f"search: {exc}")
            console.print(credits_line(serp.ledger.spent, ledger, live=True))
            raise typer.Exit(EXIT_CREDIT_CAP) from None
        f = SlopFilter.live(PageFetcher(http, max_bytes=settings.page_max_bytes))
        results = [{"position": r.rank, "title": r.title, "link": r.url} for r in page.organic]
        kept = f.apply(query, results, threshold=threshold, mode="annotate" if annotate else "drop")
    table = Table(title=f"{query}  ({engine}, {locale})")
    for col in ("#", "slop_risk", "band", "url", "why"):
        table.add_column(col, overflow="fold")
    kept_urls = {r["link"] for r in kept}
    for r in [*kept, *({**x, "slopwatch": None} for x in results if x["link"] not in kept_urls)]:
        s = r["slopwatch"]
        if s is None:
            table.add_row(str(r["position"]), "", "[red]dropped[/]", r["link"], "")
            continue
        risk = "" if s["slop_risk"] is None else f"{s['slop_risk']:.2f}"
        why = "; ".join(s["reasons"]) or (s["not_scored"] or "")
        table.add_row(str(r["position"]), risk, str(s["band"] or "-"), r["link"], why)
    console.print(table)
    console.print(f"kept {len(kept)} of {len(results)}")
    console.print(credits_line(serp.ledger.spent, ledger, live=True))


@app.command()
def serve(
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
    max_credits: Annotated[
        int, typer.Option("--max-credits", min=0, help="SerpApi credits this session may use.")
    ] = LIVE_SESSION_CREDITS,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
) -> None:
    """Local web app: search anything, watch the filter remove slop (127.0.0.1 only)."""
    from slopwatch.serve import App, make_server

    settings = Settings()
    if settings.serpapi_api_key is None:
        err_console.print("serve: SERPAPI_API_KEY is not set (put it in the environment or .env)")
        raise typer.Exit(EXIT_USAGE)
    ledger = ProjectLedger(settings.live_ledger_path, cap=LIVE_CREDIT_CAP)
    cache = Cache(
        settings.cache_path,
        mode=CacheMode.LIVE,
        ttl_seconds=settings.cache_ttl_seconds,
        cross_thread=True,
    )
    http = HttpClient(
        cache,
        timeout=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        agent=user_agent(settings.contact_url),
    )
    serp = SerpClient(http, settings.serpapi_api_key, project=ledger, max_credits=max_credits)
    live = SlopFilter.live(PageFetcher(http, max_bytes=settings.page_max_bytes))
    agent = None
    if settings.gemini_api_key is not None:
        backend = GeminiBackend(http, settings.gemini_api_key, min_interval=4.0)

        def agent(question: str, sources: list[DemoSource]) -> tuple[str, list[int]]:
            return ask_agent(backend, question, sources)

    else:
        console.print("serve: GEMINI_API_KEY not set; pages are scored but agent answers are off")
    overview: dict[str, Any] = {}
    try:
        overview = compute_overview(settings.data_dir.parent)
    except (OSError, ValueError) as exc:  # the live search still works without it
        console.print(f"serve: Observatory view unavailable ({exc})")
    server = make_server(App(serp, live, agent, overview), port)
    url = f"http://127.0.0.1:{port}/"
    console.print(f"SlopWatch Live at {url}  (Ctrl+C to stop; up to {max_credits} credits)")
    console.print(credits_line(0, ledger, live=True))
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        http.close()
        cache.close()
        console.print(credits_line(serp.ledger.spent, ledger))


@app.command()
def report(
    out: Annotated[Path, typer.Option("--out")] = Path("report/observatory.html"),
    cache_mode: CacheModeOpt = None,
) -> None:
    """Build the observatory HTML (and numbers.json) from committed data only."""
    settings, _mode = _settings_and_mode(cache_mode)
    numbers = build_report(settings.data_dir.parent, out)
    story = build_story(settings.data_dir.parent, out.parent / "story.html")
    console.print(f"report: {story} (narrative page)")
    o = numbers["overall_india"]
    console.print(
        f"report: {out} | India low share {o['value']:.1%} "
        f"(95% CI {o['ci'][0]:.1%}-{o['ci'][1]:.1%}, n = {o['n_scored']}, "
        f"coverage {o['coverage']:.0%})"
    )
    console.print(credits_line(0, ProjectLedger(settings.ledger_path)))


@app.command()
def demo(
    questions: Annotated[Path, typer.Option("--questions")] = Path("data/demo_questions.yaml"),
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("report"),
    min_interval: Annotated[float, typer.Option("--min-interval", min=0)] = 7.0,
    cache_mode: CacheModeOpt = None,
) -> None:
    """Agent before/after on the committed demo questions (all reported).

    One Gemini call per question per condition (skipped when the filter drops
    nothing). Responses are recorded as fixtures; replay needs no key.
    """
    settings, mode = _settings_and_mode(cache_mode)
    meta, qs = load_demo_questions(questions)
    with (
        open_cache(settings, mode) as cache,
        HttpClient(cache, timeout=120.0, max_retries=settings.http_max_retries) as http,
    ):
        backend = GeminiBackend(http, settings.gemini_api_key, min_interval=min_interval)

        def agent(question: str, sources: list[DemoSource]) -> tuple[str, list[int]]:
            return ask_agent(backend, question, sources)

        try:
            results = run_demo(
                qs,
                data_dir=settings.data_dir,
                slop_filter=offline_filter(),
                agent=agent,
                engine=str(meta.get("engine", "google")),
                locale=str(meta.get("locale", "IN")),
                k=int(meta.get("top_k", 5)),
            )
        finally:
            if mode is not CacheMode.REPLAY:
                cache.export_dir(settings.fixtures_dir, only=cache.used)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "demo.json").write_text(
        json.dumps(demo_to_json(results), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md = render_demo(results)
    Path("DEMO_RESULTS.md").write_text(md, encoding="utf-8", newline="\n")
    console.print(md.split("\n## ")[0], markup=False)
    console.print(credits_line(0, ProjectLedger(settings.ledger_path)))


@app.command()
def fit(
    out: Annotated[Path, typer.Option("--out", help="Where to write the fitted rubric.")] = Path(
        "data/rubric_candidates/v4.yaml"
    ),
    version: Annotated[int, typer.Option("--version", min=1)] = 4,
    holdout: Annotated[
        list[str] | None,
        typer.Option("--holdout", help="Label set(s) that must never be read (held-out tests)."),
    ] = None,
) -> None:
    """Fit rule weights on all development labels: every label set under labels/
    (all splits) except the --holdout set(s). Procedure: slopwatch/fit.py."""
    settings = Settings()
    rows, records = _load_scored(settings)
    relevance = read_jsonl(settings.data_dir / RELEVANCE, RelevanceRecord)
    base = settings.data_dir.parent / "labels"
    skip = set(holdout or [])
    items, labels, used_sets = [], {}, []
    for sample_path in sorted(base.rglob(SAMPLE)):
        name = sample_path.parent.relative_to(base).as_posix()
        if name in skip or (name == "." and "main" in skip):
            continue
        items += load_sample(sample_path)
        labels.update(load_labels(sample_path.parent / LABELS))
        used_sets.append("main" if name == "." else name)
    sig = row_signals(rows, records, relevance)
    xs, ys = [], []
    for it in items:
        lab = labels.get(it.key)
        if lab is None or lab.label == "unsure" or it.key not in sig:
            continue
        xs.append(sig[it.key])
        ys.append(int(lab.label == "low"))
    res = fit_rubric(xs, ys)
    coefs = ", ".join(f"{c.id} {v}" for c, v in zip(CANDIDATES, res.coefficients, strict=True))
    note_lines = [
        f"Rubric v{version}: weights fitted on {len(ys)} development items ({sum(ys)} low), "
        f"LLM label sets {', '.join(used_sets)} (slopwatch fit; procedure in slopwatch/fit.py).",
        f"5-fold out-of-fold: precision {res.oof_precision}, recall {res.oof_recall}, "
        f"F1 {res.oof_f1}, flagged {res.oof_flagged}; precision floor "
        f"{'met' if res.met_min_precision else 'NOT met'}.",
        f"Coefficients: {coefs}",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        rubric_yaml(res, version=version, note="\n".join(note_lines)),
        encoding="utf-8",
        newline="\n",
    )
    load_rubric(out)  # validate
    for line in note_lines:
        console.print(line)
    console.print(f"fit: wrote {out}")


@app.command()
def doctor(
    cache_mode: CacheModeOpt = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Skip the (free) SerpApi account check.")
    ] = False,
) -> None:
    """Check key, cache, fixtures, frozen inputs and credits used/left."""
    settings = Settings()
    mode = cache_mode or settings.cache_mode
    checks = run_checks(settings, mode, offline=offline)
    table = Table(title=f"slopwatch {__version__} doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    for c in checks:
        table.add_row(c.name, f"[{_STYLE[c.status]}]{c.status}[/]", c.detail)
    console.print(table)
    failed = [c for c in checks if c.status is Status.FAIL]
    console.print(credits_line(0, ProjectLedger(settings.ledger_path)))
    raise typer.Exit(EXIT_FAIL if failed else EXIT_OK)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
