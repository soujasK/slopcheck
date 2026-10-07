# SlopWatch

[![ci](https://github.com/soujasK/slopwatch/actions/workflows/ci.yml/badge.svg)](https://github.com/soujasK/slopwatch/actions/workflows/ci.yml)

> **Don't feed your agent slop.**

AI agents and RAG systems answer from the top web search results and trust them
blindly. SlopWatch **measures** what those results actually contain for Indian
users, across Google, DuckDuckGo and Yahoo (via [SerpApi](https://serpapi.com)),
and ships a **filter** that scores each result with transparent, deterministic
signals and drops likely slop before it reaches the model, as a drop-in for
SerpApi's official agent tooling (14 agent frameworks).

Built for the SerpApi India Hackathon 2026 (Open-Source Integrations).

[Story](report/story.html) · [Observatory report](report/observatory.html) · [EVAL.md](EVAL.md) ·
[DEMO_RESULTS.md](DEMO_RESULTS.md) · [LIMITATIONS.md](LIMITATIONS.md)

## The problem

Search engines have fought SEO spam for years; research found product-review
results on Google, Bing and DuckDuckGo heavily dominated by affiliate-driven
content (Bevendorff et al., *Is Google Getting Worse?*, ECIR 2024). A human can
skip a dodgy page. An agent quotes it. Developers who build agents on raw search
APIs get ten results with **no quality signal at all**, and nobody had measured
what Indian users' searches return to an agent, per engine and per topic.

## What we measured (snapshot of 2026-10-03)

100 SerpApi searches: 40 real Indian queries (health, personal finance, product
reviews, tech how-tos) on Google India; 20 locale-neutral ones on DuckDuckGo
India, Yahoo India and Google US. 822 organic results, 681 unique pages, each
fetched once (robots.txt respected) and scored. Every share below is over scored,
non-platform results, with a 95% cluster-bootstrap interval over queries.

| | Share with low-quality signals | n scored | coverage |
|---|---|---|---|
| **India, all engines** | **4.5%** [2.2%, 7.2%] | 426 | 77% |
| Google India | 7.1% [3.3%, 11.7%] | 170 | 75% |
| DuckDuckGo India | 2.7% [0.0%, 5.8%] | 147 | 77% |
| Yahoo India | 2.8% [0.0%, 6.9%] | 109 | 81% |
| Google US (locale-neutral queries) | 15.6% [6.3%, 25.4%] | 64 | 61% |
| Google India (same queries) | 6.6% [1.3%, 13.5%] | 76 | 73% |

Scored with rubric v4. If every unscored India result were ok the share would be
3.4%; if every one were low, 27%. Because the filter catches only about three in
ten low-quality pages, 4.5% understates what the LLM judges would call low;
corrected for the error rates measured on the round-4 test (Rogan-Gladen) it is
about 11%, a very uncertain estimate (recall was measured on only 23 low pages).
Paired comparisons on the same queries (19 pairs each) found **no statistically
detectable difference** between Google India and DuckDuckGo/Yahoo India, or
between Google India and Google US (India − US: −9.3 points, 95% CI −24.2 to
+3.9, p = 0.24).

**Findings**

1. **Indian "slop" is not classic affiliate spam.** Affiliate links and "best X"
   listicles did *not* predict low quality here (their fitted weights were
   negative). What did: **no named author**, **pages that do not address the
   query** (a UN climate report ranking for "best 1.5 ton inverter AC"; a US
   research program called "IMPROVE" in the top 5 for "how to improve cibil
   score fast"), and **sellers' own content** (pharmacy and product blogs).
2. **Google shows an AI Overview on 59 of 60 searches** (39/40 India, 20/20 US),
   and fills 30% of its India top results with platform pages (YouTube, Reddit,
   Quora, shops) against 3-4% on DuckDuckGo and Yahoo.
3. **The web is closing to crawlers:** 22% of pages refused us (403s, robots.txt)
   and 14 answered *402 Payment Required* (pay-per-crawl). US publishers block
   more (66% coverage vs ~80% for India).
4. **Low-band pages appear at every rank** on Google India, including the top
   result (5%, n = 22); no rank stands out (0-12%, small n per rank).

## Validation (labels from two LLMs, not humans)

We report the whole history, including what failed (details: [EVAL.md](EVAL.md),
[ANALYSIS_PLAN.md](ANALYSIS_PLAN.md), [LABELING.md](LABELING.md)).

- Ground truth: two LLMs (Google `gemini-3.5-flash-lite`, Cloudflare
  `gpt-oss-120b`) label each result blind (never seeing scores or signals);
  only items where both agree count. Agreement: Cohen's kappa 0.47 with a
  300-char excerpt, **0.66** with 2,000 chars of main text. **No human
  validation.**
- **Round 2 (rubric v2): failed.** Test precision 0.37 [0.19, 0.59], recall 0.35,
  n = 71, below the pre-registered 0.70 gate and below the one-line baseline "no
  author and no date". That test set was then retired.
- **Round 3 (rubric v3): failed the gate.** Fitted on the 155 round-2 items,
  frozen, tested once on 114 agreed results from 150 fresh pages (kappa 0.42):
  precision 0.57 [0.25, 0.84], recall 0.19, F1 0.29. It beat every baseline.
- **Round 4 (rubric v4): passed the gate.** Fitted on all 257 development items
  (cross-validated precision 0.80), frozen, then tested **once** on 102 agreed
  results from 30 brand-new Google India queries (kappa 0.53): **precision 0.88
  [0.53, 0.98], recall 0.30 [0.16, 0.51], F1 0.45, specificity 0.99.** The
  interval is wide (8 pages flagged). The one-line baseline "no author and no
  date" reached a slightly higher F1 (0.47) by flagging 28 pages at precision
  0.43, so the pre-registered "beats every baseline on F1" criterion was **not**
  met.

The filter is conservative: it almost never removes a page the judges called ok
(1 of 79), but it catches only about three in ten low-quality pages. Treat a drop
as "probably not a source to ground on", not as a verdict on a site.

## Use it

```bash
pip install "slopwatch[agents] @ git+https://github.com/soujasK/slopwatch"   # Python 3.11+
# or from a clone: pip install -e ".[agents]"
```

Three lines in any Python agent:

```python
from slopwatch.filter import filter_results
clean = filter_results("best sip to invest in 2026", serp["organic_results"])
# each kept result: result["slopwatch"] = {slop_risk, band, reasons, not_scored}
```

**SerpApi's official agent tooling** (OpenAI Agents SDK, LangChain, LangGraph,
CrewAI, LlamaIndex, Claude Agent SDK, Google ADK, and more):

```python
from slopwatch.filter.serpapi_tools import web_search   # instead of serpapi_search_tools
tools = [web_search()]                                    # same tool, slop filtered
```

**LangChain `SerpAPIWrapper`:** `slopwatch.filter.langchain.filtered_results(wrapper, query)`.

**CLI**

```bash
slopwatch serve                                                # local app: ask anything, compare the agent's answer with and without the filter
slopwatch search "is it safe to take dolo 650 every day"      # live: SerpApi + filter
slopwatch filter --serp-json results.json --threshold 0.6      # pipe-friendly
slopwatch report --cache-mode replay                           # rebuild the observatory
slopwatch demo --cache-mode replay                             # agent before/after
slopwatch doctor                                               # key, cache, credits
```

Every result keeps its reasons, e.g. `0.63 low: no named author; no author or
date; title and headings cover 33% of the query's words`. Platform pages and
pages that cannot be fetched are never dropped; they are marked `not_scored`.

**The console (`slopwatch serve`)** is a React 19 + TypeScript app (Vite,
Tailwind CSS 4, Radix UI, Motion) in [`web/`](web/). Its production build is
committed in `slopwatch/report/app/` and ships in the package, so running it needs
no Node and no network (fonts and libraries are bundled). To change the UI:
`cd web && npm install && npm run dev` (proxies the API to a running
`slopwatch serve`), then `npm run build`. Open a ready-made run with a link such as
`http://127.0.0.1:8765/?q=how%20to%20improve%20cibil%20score%20fast`.

## How it uses SerpApi

SerpApi is the data source and the integration target: 100 searches across
`google`, `duckduckgo` and `yahoo` with India and US locales for the measurement
([SERPAPI_USAGE.md](SERPAPI_USAGE.md): engines, parameters, credits per stage),
a live `search` command, and a `SlopWatchClient` that plugs into
`serpapi-search-tools` so filtering happens inside SerpApi's own agent tools. A
hard research credit cap (140) is enforced against a committed ledger; 133 were
spent (100 measurement, 30 for the round-4 test, plus probes; 3 on Bing, which
returned unusable India results). Live questions (`serve`, `search`) use your own
key and a separate local ledger, so they never count against that cap; `serve`
allows 50 new searches per session by default (`--max-credits` to change).

## How it works

```
queries.yaml ─► SerpApi (google / duckduckgo / yahoo, IN + US) ─► top organic results
                                                                     │
           robots-aware page fetch (10 s, 2 MB, cached) ◄────────────┘
                     │
                     ▼
deterministic signals: author/date, query relevance, sells-directly, affiliate,
ads, thin text, near-duplicates  ──►  rubric v4 (weights fitted, frozen)
                     │                         │
                     ▼                         ▼
           observatory report          filter + agent adapters
All HTTP goes through one SQLite cache (live / record / replay); SerpApi and LLM
responses are committed as fixtures, page HTML is not.
```

## Reproduce

```bash
git clone https://github.com/soujasK/slopwatch && cd slopwatch
pip install -e ".[dev]"
slopwatch report --cache-mode replay     # no API key, no network, < 3 minutes
pytest                                   # offline; >= 80% coverage enforced
```

`collect` replays from the committed SerpApi fixtures byte-for-byte. Page HTML is
deliberately not committed (third-party content), so `fetch` needs the network;
everything downstream (`score`, `evaluate`, `report`, `filter --offline`, `demo`)
replays from committed data.

## Prior art

- Bevendorff, Wiegmann, Potthast, Stein, *Is Google Getting Worse? A Longitudinal
  Investigation of SEO Spam in Search Engines*, ECIR 2024 (product reviews, DE/US;
  Google, Bing, DuckDuckGo).
- Work on LLM search agents trusting manipulated or low-quality pages (e.g.
  arXiv 2606.16821, 2605.29224, 2509.23694).
- Domain reliability ratings licensed to AI providers (NewsGuard); manual
  include/exclude domain lists in search APIs (Tavily, Exa); Marginalia's
  affiliate/tracking filters in its own index; site-quality SEO tools.

SlopWatch differs by scoring **individual results for a given query**, with
explainable deterministic signals, **validated** against held-out labels, measured
on **Indian queries**, and shipped as a filter inside SerpApi's agent tooling.

## Ethics

- No copies of third-party pages are published; the repo holds SERP data, page
  hashes, fetch metadata, excerpts of at most 300 characters and derived signals.
- robots.txt is respected; disallowed or unreachable pages are reported as
  unscored and never fetched. The crawler identifies itself with a contact URL.
- Aggregates only. No per-site "spam" list; examples show only which signals fired.

## Disclosures (required by the hackathon)

- **Pre-existing code:** the HTTP cache, HTTP client, SerpApi client and
  robots-aware page fetcher were adapted from the author's earlier project
  *Zero Hour*; everything else was built for this hackathon (see git history).
- **AI tools:** development assisted by Claude Code. Google Gemini and Cloudflare
  Workers AI were used only as blind labelers for validation and to play the agent
  in the demo; no LLM is used in scoring.

MIT License.
