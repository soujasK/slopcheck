# SerpApi usage

SlopWatch uses SerpApi only to collect search engine results pages (SERPs). Page
fetching, scoring, evaluation, reporting and filtering cost no credits.

## Budget

| | Credits |
|---|---|
| Hard project cap (constant `PROJECT_CREDIT_CAP` in `slopwatch/config.py`) | **140** |
| Measurement collection (below) | 80 |
| Development probes and agent demo | ≤ 60 |

Every billed request is appended to [`data/serpapi_ledger.jsonl`](data/serpapi_ledger.jsonl)
(timestamp, engine, request hash, redacted params, credits). The cap is checked
against this committed ledger **before** each network call, so it holds across runs
and survives a deleted cache. Each command also has a per-run cap (`--max-credits`,
default 10) and prints `credits: N spent by this command; project ledger X/140`.
Cache hits and replays cost nothing. `slopwatch doctor` shows the ledger total and
the SerpApi account balance (via the free Account API).

## Engines and parameters

Verified against serpapi.com docs on 2026-10-02.

| Engine | Locale | Parameters |
|---|---|---|
| `google` | India | `gl=in`, `hl=en`, `google_domain=google.co.in` |
| `google` | US | `gl=us`, `hl=en`, `google_domain=google.com` |
| `bing` | India | `mkt=en-IN` (`cc` is not sent: the docs say `cc` and `mkt` are mutually exclusive) |

Only `organic_results` are scored, top 10 by rank. Ads, AI Overviews, answer
boxes, "People also ask" and other SERP features are recorded as metadata (which
features were present) and excluded from scoring.

## Collection plan (80 credits)

Defined in [`data/queries.yaml`](data/queries.yaml), frozen and committed before
any collection.

| Step | Queries | Credits |
|---|---|---|
| India, Google | all 40 (10 per category) | 40 |
| India, Bing | 20-query subset | 20 |
| US, Google | same 20-query subset | 20 |
| **Total** | | **80** |

Every query is tagged `locale_neutral` before the draw. The subset is 5 queries per
category, drawn from the **locale-neutral pool only** with `random.Random(2026)`
(`slopwatch.queries.select_subset`) before collection. The drawn ids are stored in
`queries.yaml`, and loading fails if they ever stop matching the tags and seed.
The US comparison is therefore reported as "India vs US on locale-neutral
queries".

## Caching and reproduction

All HTTP goes through a SQLite cache with `live | record | replay` modes.
SerpApi responses are exported as JSON fixtures (API key stripped before hashing
and storage) and committed under `fixtures/`. Third-party page HTML is **not**
committed; see [LIMITATIONS.md](LIMITATIONS.md). `--cache-mode replay` needs no API
key and spends no credits.

## Credits spent

Filled in from the ledger after collection.
