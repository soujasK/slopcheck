# SerpApi usage

SlopWatch uses SerpApi only to collect search engine results pages (SERPs). Page
fetching, scoring, evaluation, reporting and filtering cost no credits.

## Budget

| | Credits |
|---|---|
| Hard project cap (constant `PROJECT_CREDIT_CAP` in `slopwatch/config.py`; 140 until the round-5 test was declared) | **180** |
| Measurement collection (below) | 100 |
| Development probes, agent demo and round-4 test queries | ≤ 40 |

Every billed request is appended to [`data/serpapi_ledger.jsonl`](data/serpapi_ledger.jsonl)
(timestamp, engine, request hash, redacted params, credits). The cap is checked
against this committed ledger **before** each network call, so it holds across runs
and survives a deleted cache. Each command also has a per-run cap (`--max-credits`,
default 10) and prints `credits: N spent by this command; project ledger X/180`.
Cache hits and replays cost nothing. `slopwatch doctor` shows the ledger total and
the SerpApi account balance (via the free Account API).

**Live use is separate.** `slopwatch serve` and `slopwatch search` answer anyone's
own questions with their own key. They record spend in a git-ignored
`.slopwatch/live_ledger.jsonl` and do **not** count against the research cap, so a
fresh clone can search any question (limited by the user's SerpApi plan and a
per-session cap: `serve --max-credits`, default 50; `search` spends at most 1).

## Engines and parameters

Verified against serpapi.com docs on 2026-10-02 (Google, Bing) and 2026-10-03 (DuckDuckGo, Yahoo).

| Engine | Locale | Parameters |
|---|---|---|
| `google` | India | `gl=in`, `hl=en`, `google_domain=google.co.in` |
| `google` | US | `gl=us`, `hl=en`, `google_domain=google.com` |
| `duckduckgo` | India | `kl=in-en` ([region list](https://serpapi.com/duckduckgo-regions)) |
| `yahoo` | India | `p=<query>` (Yahoo's query parameter), `yahoo_domain=in` (in.search.yahoo.com, [domain list](https://serpapi.com/yahoo-domains)) |

### Why DuckDuckGo and not Bing

The plan originally used Bing for the second India engine. Before collection,
probes of SerpApi's `bing` engine for India returned unusable results:

| Probe | Parameters | Result |
|---|---|---|
| health-01 | `mkt=en-IN` | no results ("Fully empty") |
| health-03 | `mkt=en-IN` | 7 results, all about the word "normal" alone (dictionaries, a film) |
| health-03 | `cc=IN` | no results ("Fully empty") |

The same health-03 query on `duckduckgo` with `kl=in-en` returned 10 relevant
results including Indian sources, so DuckDuckGo (the third engine in Bevendorff
et al.) replaced Bing, with the same 20-query subset. The change was made before
any measurement data was collected; all probes are in the ledger and `fixtures/`.

Yahoo India was then added as a third, widely known engine (also before
collection). Its probe for health-03 returned 7 relevant results, all of which
also appear in DuckDuckGo's top 10: both draw heavily on Bing's index. The
report therefore treats DuckDuckGo and Yahoo as the "Bing family", not as two
independent engines.

Only `organic_results` are scored: the top 10 by rank, or fewer when the engine
returns fewer (Google often shows 8 or 9 organic results next to an AI Overview;
a second page would double the cost, so the report states the actual n). Ads,
AI Overviews, answer boxes, "People also ask" and other SERP features are recorded
as metadata (which features were present) and excluded from scoring.

## Collection plan (100 credits)

Defined in [`data/queries.yaml`](data/queries.yaml), frozen and committed before
any collection.

| Step | Queries | Credits |
|---|---|---|
| India, Google | all 40 (10 per category) | 40 |
| India, DuckDuckGo | 20-query subset | 20 |
| India, Yahoo | same 20-query subset | 20 |
| US, Google | same 20-query subset | 20 |
| **Total** | | **100** |

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

| Step | Credits |
|---|---|
| Probe: Google India (health-01) | 1 |
| Probes: Bing India (2 x `mkt=en-IN`, 1 x `cc=IN`), all unusable | 3 |
| Probe: DuckDuckGo India (health-03) | 1 |
| Probe: Yahoo India (health-03) | 1 |
| Measurement collection (97 searches; 3 probes reused from cache) | 97 |
| Round-4 held-out test: 30 fresh Google India queries (`data_round4/`) | 30 |
| Round-5 out-of-domain test: 32 Google India queries (`data_round5/`) | 32 |
| Wasted: 9 round-5 searches re-bought by a rerun in `record` mode (which always refetches) instead of `live` | 9 |
| **Total** | **174** of the 180 cap |

The Google, DuckDuckGo and Yahoo probes are jobs in the plan, so the full
collection reuses them from the cache: it needs 97 more credits, not 100. The 3
Bing credits bought no measurement data.
