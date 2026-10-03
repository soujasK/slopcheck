"""Pydantic v2 data models shared across the pipeline (spec section 5)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EXCERPT_MAX_CHARS = 300

# bing is kept for the recorded probes; SerpApi Bing returned unusable India results.
Engine = Literal["google", "bing", "duckduckgo"]
Locale = Literal["IN", "US"]
Category = Literal["health", "personal_finance", "product_reviews", "tech_howto"]
Band = Literal["ok", "mixed", "low"]
LabelValue = Literal["ok", "low", "unsure"]
# Why a SERP row has no signals. Unscored rows are reported, never guessed.
UnscoredReason = Literal[
    "robots_blocked",  # robots.txt disallows our agent
    "robots_unavailable",  # robots.txt unreachable / 5xx: treated as disallow
    "http_error",  # page answered >= 400
    "not_html",  # PDF, image, etc.
    "too_large",  # body over the 2 MB cap
    "fetch_failed",  # timeout / transport error after retries
    "not_recorded",  # replay mode and no fixture for this page
    "parse_failed",  # HTML fetched but signal extraction raised
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Query(_Frozen):
    id: str
    category: Category
    locale: Locale
    text: str


class SerpRow(_Frozen):
    query_id: str
    engine: Engine
    locale: Locale
    rank: int = Field(ge=1, le=10)
    url: str
    domain: str
    title: str
    snippet: str
    request_hash: str


class SerpMeta(_Frozen):
    """One collected SERP: which non-organic features were present (metadata only)."""

    query_id: str
    engine: Engine
    locale: Locale
    request_hash: str
    n_organic: int
    features: list[str]
    fetched_at: dt.datetime


class Page(_Frozen):
    """Fetch metadata. This, not the page HTML, is what gets committed: third-party
    HTML is never stored in the repo, only a hash and a short excerpt for labeling."""

    url: str
    status: int | None
    fetched_at: dt.datetime | None
    title: str = ""
    excerpt: str = Field(default="", max_length=EXCERPT_MAX_CHARS)
    text_len: int = 0
    html_hash: str | None = None
    robots_blocked: bool = False
    unscored_reason: UnscoredReason | None = None


class Signals(_Frozen):
    affiliate_links: int
    affiliate_density: float  # affiliate links / outbound links
    # Unique outbound links; lets the rubric ignore ratios over tiny denominators.
    outbound_links: int
    commerce_ratio: float  # shop + affiliate links / outbound links
    listicle: bool
    ad_scripts: int  # distinct ad/tracker domains in static HTML
    has_author: bool
    has_date: bool
    has_about_contact: bool
    text_len: int  # main-text chars
    boilerplate_ratio: float  # share of visible text outside the main text
    near_dup_group: str | None = None  # filled at score time, across a SERP set


class SignalRecord(_Frozen):
    """Per-page output of `fetch`, committed to data/signals.jsonl."""

    url: str
    html_hash: str
    signals: Signals
    simhash: str  # 16 hex chars; near-duplicate grouping happens at score time


class Score(_Frozen):
    url: str
    # Higher = worse. 0 = no low-quality signals fired; filters drop slop_risk >= threshold.
    slop_risk: float = Field(ge=0.0, le=1.0)
    band: Band
    reasons: list[str]


class Label(_Frozen):
    url: str
    query_id: str
    label: LabelValue
    note: str = ""
    labeled_at: dt.datetime


class EvalError(_Frozen):
    url: str
    label: LabelValue
    band: Band
    reasons: list[str]


class EvalReport(_Frozen):
    split: Literal["dev", "test", "all"]
    n: int
    precision_low: float
    recall_low: float
    f1_low: float
    # confusion[label][band] = count
    confusion: dict[str, dict[str, int]]
    errors: list[EvalError]
