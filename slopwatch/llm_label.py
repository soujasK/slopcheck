"""Two blind LLM labelers for validating the scorer. Never used in scoring.

Each labeler sees exactly: the guide section of LABELING.md (between the
``labeler-guide`` markers) and one item's query, title, URL and excerpt. It
never sees scores, signals, the rubric or its reasons. Temperature 0, strict
JSON ``{"label": "ok"|"low"|"unsure", "reason": "..."}``, validated; on an
invalid reply the request is repeated with a short correction (a different
request, so it is cached separately). Every request goes through the HTTP cache
and is exported as a fixture, so labels replay offline with no keys.

* Labeler A: Google Gemini (``generateContent``, JSON schema output).
* Labeler B: Cloudflare Workers AI ``@cf/openai/gpt-oss-120b`` with low reasoning
  effort; ``@cf/meta/llama-3.3-70b-instruct-fp8-fast`` only if the primary model
  is unavailable. Responses report exact neuron usage, which is checked against
  a daily budget (free tier: 10,000 neurons per day).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import SecretStr

from slopwatch.cache import CachedResponse
from slopwatch.http import HttpClient, HttpError
from slopwatch.label import LabelItem
from slopwatch.models import Label, LabelValue
from slopwatch.stats import cohen_kappa

log = logging.getLogger(__name__)

GUIDE_START = "<!-- labeler-guide:start -->"
GUIDE_END = "<!-- labeler-guide:end -->"
VALID: frozenset[str] = frozenset({"ok", "low", "unsure"})
MAX_ATTEMPTS = 3
GEMINI_MODEL = "gemini-3.8-flash"
CF_PRIMARY = "@cf/openai/gpt-oss-120b"
CF_FALLBACK = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_NEURON_BUDGET = 9500.0  # stay under the 10,000/day free allocation

OUTPUT_RULES = (
    'Reply with JSON only, exactly of the form {"label": "ok" | "low" | "unsure", '
    '"reason": "<one short sentence>"}. No other text.'
)
CORRECTION = "Your previous reply was not valid. " + OUTPUT_RULES


def correction_text(attempt: int) -> str:
    """Differs per attempt so each retry is a new request, not a cache hit."""
    return f"{CORRECTION} (attempt {attempt + 1} of {MAX_ATTEMPTS})"


def load_guide(labeling_md: Path) -> str:
    text = labeling_md.read_text(encoding="utf-8")
    start, end = text.find(GUIDE_START), text.find(GUIDE_END)
    if start < 0 or end <= start:
        raise ValueError("LABELING.md has no labeler-guide section")
    return text[start + len(GUIDE_START) : end].strip()


def system_prompt(guide: str) -> str:
    return f"{guide}\n\n{OUTPUT_RULES}"


def item_prompt(item: LabelItem) -> str:
    """The only item fields a labeler sees. Built from an explicit allow-list."""
    return "\n".join(
        [
            f"Query: {item.query_text}",
            f"Title: {item.title}",
            f"URL: {item.url}",
            f"Excerpt: {item.excerpt or '(no excerpt available)'}",
        ]
    )


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_reply(text: str | None) -> tuple[LabelValue, str] | None:
    """Strict: a JSON object with a valid label and a string reason, else None."""
    if not text:
        return None
    match = _JSON_OBJECT.search(text.strip())
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    label, reason = obj.get("label"), obj.get("reason")
    if label not in VALID or not isinstance(reason, str):
        return None
    return label, reason.strip()[:500]


@dataclass(frozen=True)
class Reply:
    text: str | None
    model: str
    from_cache: bool
    input_tokens: int = 0
    output_tokens: int = 0
    neurons: float = 0.0


class Backend(Protocol):
    name: str

    def ask(self, system: str, user: str, attempt: int) -> Reply: ...


class ModelUnavailable(RuntimeError):
    pass


class QuotaExhausted(RuntimeError):
    """The provider's daily quota is used up; stop and resume later."""


RATE_LIMIT_WAITS = (15.0, 30.0, 60.0, 60.0, 120.0, 120.0)  # seconds, on HTTP 429
# Rate limit and overload answers: wait and retry instead of failing the run.
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class GeminiBackend:
    name = "gemini"

    def __init__(
        self,
        http: HttpClient,
        key: SecretStr | None,
        model: str = GEMINI_MODEL,
        *,
        min_interval: float = 7.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http, self._key, self.model = http, key, model
        self.min_interval, self._sleep, self._clock = min_interval, sleep, clock
        self._last = -1e9

    def _post(self, payload: dict[str, Any], headers: dict[str, str]) -> CachedResponse:
        """Paced request; 429s wait and retry; a daily-quota 429 raises QuotaExhausted.
        Cache hits are never paced."""
        url = GEMINI_URL.format(model=self.model)
        for wait in (*RATE_LIMIT_WAITS, None):
            if self.http.would_hit_cache("POST", url, payload):
                return self.http.post_json(url, payload, headers=headers)
            gap = self._clock() - self._last
            if gap < self.min_interval:
                self._sleep(self.min_interval - gap)
            self._last = self._clock()
            resp = self.http.post_json(url, payload, headers=headers)
            if resp.status not in TRANSIENT_STATUSES:
                return resp
            if resp.status == 429 and (
                "per day" in resp.text.lower() or "perday" in resp.text.lower()
            ):
                raise QuotaExhausted("Gemini daily quota exhausted; resume after reset")
            if wait is None:
                break
            log.info("Gemini HTTP %d; waiting %.0fs", resp.status, wait)
            self._sleep(wait)
        raise QuotaExhausted(f"Gemini kept returning HTTP {resp.status}; resume later")

    def ask(self, system: str, user: str, attempt: int) -> Reply:
        contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": user}]}]
        if attempt:
            contents.append({"role": "user", "parts": [{"text": correction_text(attempt)}]})
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "label": {"type": "STRING", "enum": sorted(VALID)},
                        "reason": {"type": "STRING"},
                    },
                    "required": ["label", "reason"],
                },
            },
        }
        headers = {"x-goog-api-key": self._key.get_secret_value()} if self._key else {}
        resp = self._post(payload, headers)
        if resp.status >= 400:
            raise HttpError(f"Gemini HTTP {resp.status}", resp.status)
        data = resp.json()
        usage = data.get("usageMetadata") or {}
        text = None
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            text = None
        return Reply(
            text=text,
            model=self.model,
            from_cache=resp.from_cache,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0))
            + int(usage.get("thoughtsTokenCount", 0)),
        )


class CloudflareBackend:
    name = "cloudflare"

    def __init__(
        self,
        http: HttpClient,
        token: SecretStr | None,
        account: SecretStr | None,
        models: tuple[str, ...] = (CF_PRIMARY, CF_FALLBACK),
    ) -> None:
        self.http, self._token, self._account = http, token, account
        self.models = models
        self.model = models[0]
        self.fallback_used = False

    def _payload(self, system: str, user: str, attempt: int) -> dict[str, Any]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if attempt:
            messages.append({"role": "user", "content": correction_text(attempt)})
        payload: dict[str, Any] = {"messages": messages, "temperature": 0, "max_tokens": 1024}
        if self.model == CF_PRIMARY:
            payload["reasoning"] = {"effort": "low"}
        return payload

    def ask(self, system: str, user: str, attempt: int) -> Reply:
        while True:
            account = self._account.get_secret_value() if self._account else "none"
            headers = (
                {"Authorization": f"Bearer {self._token.get_secret_value()}"} if self._token else {}
            )
            resp = self.http.post_json(
                CF_URL.format(account=account, model=self.model),
                self._payload(system, user, attempt),
                headers=headers,
                # the account id never reaches the cache, fixtures or logs
                cache_url=CF_URL.format(account="{account}", model=self.model),
            )
            if resp.status in (400, 404) and self._switch_model():
                continue
            if resp.status >= 400:
                raise HttpError(f"Cloudflare HTTP {resp.status}", resp.status)
            break
        result = resp.json().get("result") or {}
        usage = result.get("usage") or {}
        text = None
        try:
            text = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = result.get("response") if isinstance(result.get("response"), str) else None
        return Reply(
            text=text,
            model=self.model,
            from_cache=resp.from_cache,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            neurons=0.0 if resp.from_cache else float(usage.get("neurons", 0.0)),
        )

    def _switch_model(self) -> bool:
        """Fall back once, only when the primary model is rejected as unavailable."""
        idx = self.models.index(self.model)
        if idx + 1 >= len(self.models):
            return False
        self.model = self.models[idx + 1]
        self.fallback_used = True
        return True


@dataclass
class RunStats:
    labeled: int = 0
    from_cache: int = 0
    invalid_final: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    neurons: float = 0.0
    models: set[str] = field(default_factory=set)
    stopped_for_budget: bool = False


def _ask_patiently(
    backend: Backend, system: str, user: str, attempt: int, sleep: Callable[[float], None]
) -> Reply:
    """Network errors and transient HTTP answers wait and retry; if the provider
    stays unavailable the run stops cleanly (QuotaExhausted) and can resume."""
    for wait in (*RATE_LIMIT_WAITS, None):
        try:
            return backend.ask(system, user, attempt=attempt)
        except HttpError as exc:
            if exc.status is not None and exc.status not in TRANSIENT_STATUSES:
                raise
            if wait is None:
                raise QuotaExhausted(f"{backend.name} unavailable: {exc}") from None
            log.info("%s unavailable (%s); waiting %.0fs", backend.name, exc, wait)
            sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def label_items(
    items: list[LabelItem],
    backend: Backend,
    guide: str,
    *,
    done: set[tuple[str, str]],
    write: Callable[[Label], None],
    neuron_budget: float | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    stats: RunStats | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RunStats:
    """Label items not in ``done``. Stops before exceeding ``neuron_budget``.
    Pass ``stats`` to keep partial counts if the run is interrupted."""
    stats = stats if stats is not None else RunStats()
    system = system_prompt(guide)
    for item in items:
        if item.key in done:
            continue
        if neuron_budget is not None and stats.neurons >= neuron_budget:
            stats.stopped_for_budget = True
            break
        parsed: tuple[LabelValue, str] | None = None
        for attempt in range(MAX_ATTEMPTS):
            reply = _ask_patiently(backend, system, item_prompt(item), attempt, sleep)
            stats.models.add(reply.model)
            stats.input_tokens += 0 if reply.from_cache else reply.input_tokens
            stats.output_tokens += 0 if reply.from_cache else reply.output_tokens
            stats.neurons += reply.neurons
            stats.from_cache += int(reply.from_cache)
            parsed = parse_reply(reply.text)
            if parsed is not None:
                break
            stats.retries += 1
        if parsed is None:
            stats.invalid_final += 1
            label: LabelValue = "unsure"
            reason = "INVALID: no valid JSON after retries"
        else:
            label, reason = parsed
        write(
            Label(url=item.url, query_id=item.query_id, label=label, note=reason, labeled_at=now())
        )
        stats.labeled += 1
    return stats


Labeler = Literal["a", "b"]


@dataclass(frozen=True)
class AgreementReport:
    n_items: int
    n_both: int  # items labeled by both A and B
    counts_a: dict[str, int]
    counts_b: dict[str, int]
    kappa: float | None
    raw_agreement: float
    agreed: list[Label]  # A and B agree on ok or low
    agreed_by_split: dict[str, dict[str, int]]
    dropped_disagree: int
    dropped_unsure: int  # both said unsure, or one said unsure
    invalid_a: int
    invalid_b: int


def agreement_report(
    items: list[LabelItem],
    a: dict[tuple[str, str], Label],
    b: dict[tuple[str, str], Label],
) -> AgreementReport:
    keys = [it.key for it in items if it.key in a and it.key in b]
    split = {it.key: it.split for it in items}
    la = [a[k].label for k in keys]
    lb = [b[k].label for k in keys]
    agreed: list[Label] = []
    by_split: dict[str, dict[str, int]] = {"dev": {"ok": 0, "low": 0}, "test": {"ok": 0, "low": 0}}
    disagree = unsure = 0
    for k, x, y in zip(keys, la, lb, strict=True):
        if x == y and x in ("ok", "low"):
            agreed.append(
                Label(
                    url=k[0],
                    query_id=k[1],
                    label=x,
                    note=f"A+B agree; A: {a[k].note} | B: {b[k].note}"[:1000],
                    labeled_at=max(a[k].labeled_at, b[k].labeled_at),
                )
            )
            by_split[split[k]][x] += 1
        elif "unsure" in (x, y):
            unsure += 1
        else:
            disagree += 1
    return AgreementReport(
        n_items=len(items),
        n_both=len(keys),
        counts_a={v: sum(1 for x in a.values() if x.label == v) for v in ("ok", "low", "unsure")},
        counts_b={v: sum(1 for x in b.values() if x.label == v) for v in ("ok", "low", "unsure")},
        kappa=cohen_kappa(la, lb),
        raw_agreement=round(sum(1 for x, y in zip(la, lb, strict=True) if x == y) / len(keys), 4)
        if keys
        else 0.0,
        agreed=agreed,
        agreed_by_split=by_split,
        dropped_disagree=disagree,
        dropped_unsure=unsure,
        invalid_a=sum(1 for x in a.values() if x.note.startswith("INVALID")),
        invalid_b=sum(1 for x in b.values() if x.note.startswith("INVALID")),
    )


def render_agreement(rep: AgreementReport) -> str:
    kappa = "undefined" if rep.kappa is None else f"{rep.kappa:.2f}"
    lines = [
        "LLM label agreement (labels from two LLMs; no human validation)",
        f"items in sample: {rep.n_items}; labeled by both A and B: {rep.n_both}",
        "",
        "| Labeler | ok | low | unsure | invalid JSON |",
        "|---|---|---|---|---|",
        f"| A (Gemini) | {rep.counts_a['ok']} | {rep.counts_a['low']} | "
        f"{rep.counts_a['unsure']} | {rep.invalid_a} |",
        f"| B (Cloudflare) | {rep.counts_b['ok']} | {rep.counts_b['low']} | "
        f"{rep.counts_b['unsure']} | {rep.invalid_b} |",
        "",
        f"Cohen's kappa A vs B: {kappa} (raw agreement {rep.raw_agreement:.0%})",
        f"agreed on ok/low: {len(rep.agreed)} "
        f"(dev ok {rep.agreed_by_split['dev']['ok']} / low {rep.agreed_by_split['dev']['low']}; "
        f"test ok {rep.agreed_by_split['test']['ok']} / low {rep.agreed_by_split['test']['low']})",
        f"dropped: {rep.dropped_disagree} ok/low disagreements, "
        f"{rep.dropped_unsure} with an 'unsure'",
    ]
    return "\n".join(lines) + "\n"
