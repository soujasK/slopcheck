"""SlopWatch command line.

Every command takes ``--cache-mode live|record|replay`` and ends by printing the
credits it spent and the project ledger total. ``replay`` reads only the committed
fixtures/ directory and needs no API key.

Exit codes: 0 ok, 1 a doctor check failed, 2 usage error, 3 credit cap hit.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from slopwatch import __version__
from slopwatch.cache import Cache
from slopwatch.config import PROJECT_CREDIT_CAP, CacheMode, Settings
from slopwatch.http import HttpClient, HttpError
from slopwatch.queries import PlanError, load_plan
from slopwatch.serp import ProjectLedger, SerpClient

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
