"""Runtime configuration.

Secrets come only from the environment or a git-ignored ``.env`` file in the
repo root (``SERPAPI_API_KEY``, ``GEMINI_API_KEY``, ``CLOUDFLARE_API_TOKEN``,
``CLOUDFLARE_ACCOUNT_ID``) and are held as ``SecretStr`` so they never appear in
reprs or logs. Everything else can be
overridden with ``SLOPWATCH_*`` variables, except the project credit cap, which is
a constant on purpose.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CacheMode(StrEnum):
    """How the HTTP cache layer behaves.

    live:   read-through. Serve fresh cache hits, otherwise hit the network and store.
    record: always hit the network and overwrite the stored response (fixture capture).
    replay: fixtures only. A miss is an error; the network is never touched.
    """

    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


# Hard ceiling on SerpApi credits this project may ever spend, counted from the
# committed ledger. Not configurable: raising it means editing code in review.
PROJECT_CREDIT_CAP = 180  # 140 until 2026-10-07; raised by the author for the round-5 test (32)
# Per-command default; anything larger must be asked for explicitly (--max-credits).
DEFAULT_RUN_CREDITS = 10
# Live use (`serve`, `search`) is anyone asking their own questions with their own key.
# It is recorded in a separate, git-ignored ledger so it never eats into the research
# cap above; the real limit is the user's SerpApi plan plus the per-session cap.
LIVE_CREDIT_CAP = 100_000
LIVE_SESSION_CREDITS = 50

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SLOPWATCH_", extra="ignore", env_file=REPO_ROOT / ".env"
    )

    serpapi_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SERPAPI_API_KEY", "SLOPWATCH_SERPAPI_API_KEY"),
    )
    # LLM labelers (validation only; never used in scoring).
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "SLOPWATCH_GEMINI_API_KEY")
    )
    # Paid (billing-enabled) Gemini key for audit judge C only; free-tier limits make
    # the stronger model impractical on GEMINI_API_KEY.
    gemini_paid_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_PAID_API_KEY", "SLOPWATCH_GEMINI_PAID_API_KEY"),
    )
    cloudflare_api_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CLOUDFLARE_API_TOKEN", "SLOPWATCH_CLOUDFLARE_API_TOKEN"),
    )
    cloudflare_account_id: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CLOUDFLARE_ACCOUNT_ID", "SLOPWATCH_CLOUDFLARE_ACCOUNT_ID"),
    )

    cache_path: Path = Path(".slopwatch") / "cache.sqlite"
    cache_mode: CacheMode = CacheMode.LIVE
    # Live-mode freshness. SERP snapshots are pinned by fixtures, so a long TTL is fine.
    cache_ttl_seconds: int = 30 * 24 * 3600
    fixtures_dir: Path = REPO_ROOT / "fixtures"
    # Append-only, committed record of every credit spent (feeds the project cap).
    ledger_path: Path = REPO_ROOT / "data" / "serpapi_ledger.jsonl"
    # Live searches (serve / search): local only, not committed, not part of the cap.
    live_ledger_path: Path = REPO_ROOT / ".slopwatch" / "live_ledger.jsonl"
    data_dir: Path = REPO_ROOT / "data"

    max_credits: int = Field(default=DEFAULT_RUN_CREDITS, ge=0)

    http_timeout_seconds: float = 10.0
    http_max_retries: int = Field(default=2, ge=0)
    page_max_bytes: int = 2 * 1024 * 1024
    # Contact URL put in the crawler User-Agent (e.g. the public repo). Some sites
    # refuse anonymous crawlers; set SLOPWATCH_CONTACT_URL before `fetch`.
    contact_url: str | None = None
    # Label set directory under labels/ (empty = the main set); see `slopwatch label`.
    label_set: str = ""
