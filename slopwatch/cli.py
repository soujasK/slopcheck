"""SlopWatch command line.

Every command takes ``--cache-mode live|record|replay`` and ends by printing the
credits it spent and the project ledger total. ``replay`` reads only the committed
fixtures/ directory and needs no API key.

Exit codes: 0 ok, 1 a doctor check failed, 2 usage error, 3 credit cap hit.
"""

from __future__ import annotations

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
from slopwatch.config import DEFAULT_RUN_CREDITS, PROJECT_CREDIT_CAP, CacheMode, Settings
from slopwatch.http import HttpClient, HttpError, user_agent
from slopwatch.models import Page, SerpRow
from slopwatch.pages import PageFetcher
from slopwatch.queries import Job, PlanError, load_plan
from slopwatch.serp import ProjectLedger, SerpClient
from slopwatch.signals import load_lists
from slopwatch.store import PAGES, SERP_META, SERPS, SIGNALS, read_jsonl, write_jsonl

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


def credits_line(spent_this_run: int, ledger: ProjectLedger) -> str:
    try:
        total = f"project ledger {ledger.spent}/{ledger.cap} ({ledger.remaining} left)"
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
