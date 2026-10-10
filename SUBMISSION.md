# Submission text (copy into the hackathon form)

**Project name:** SlopWatch

**Tagline:** Don't feed your agent slop.

**Track:** Knowledge & Public Interest

**Repository:** https://github.com/soujasK/slopwatch

## What it does

More and more Indians get answers to health, money and civic questions from AI
assistants, and those assistants answer from the top web search results, which
they trust blindly. SlopWatch measures, openly and with tested methods, what
those results actually contain for Indian users, and filters likely low-quality
pages before an AI repeats them.

1. **Observatory.** 100 SerpApi searches (40 real Indian questions about health,
   money, products and tech on Google India; a locale-neutral subset on
   DuckDuckGo India, Yahoo India and Google US). Each of 681 unique result pages was
   fetched once (robots.txt respected) and scored with transparent, deterministic
   signals. The report gives every number with a 95% interval, coverage and
   bounds for pages we could not score.
2. **Filter.** A Python package that scores each search result and drops likely
   slop, with the reasons attached ("no named author; title covers 33% of the
   query"). It plugs into SerpApi's official agent tooling
   (`serpapi-search-tools`), so agents on any of its 14 supported frameworks get
   filtered results by changing one import.

Key findings: in Indian results, low quality is not classic affiliate spam but
anonymous pages, pages that do not answer the query (a UN climate report at #2
for "best 1.5 ton inverter AC") and sellers' own blogs. Google showed an AI
Overview on 39 of 40 India searches (59 of 60 including the US set). 22% of pages refused automated access; 14
answered "402 Payment Required".

## Who benefits

The public first: people asking AI assistants health, money, scam and
government-service questions, who cannot see which sources the answer came from.
Researchers, journalists and fact-checkers get an open, reproducible measurement
of what Indian searches hand to AI, with every number's uncertainty and every
failed test published. Developers building agents and RAG systems on raw search
APIs get a drop-in filter that removes likely slop, with reasons, before their
agent reads it.

## How SerpApi is used

- **Data source:** 100 searches across the `google`, `duckduckgo` and `yahoo`
  engines with India and US locales, collected through a cached client with a hard
  credit cap and a committed spend ledger (174 credits: 100 for the measurement, 30 and 32 for two held-out tests, 9 wasted by a re-run, the rest probes). Every response is
  committed as a fixture, so the whole analysis replays offline with no key.
- **Integration:** `SlopWatchClient` wraps SerpApi's client inside
  `serpapi-search-tools`' `web_search` tool, filtering `organic_results` before the
  tool formats them; a live `slopwatch search` command does SerpApi search, page
  fetch, scoring and filtering in one step.

## Validation (honest)

Labels come from two LLMs judging blind (no human labels; Cohen's kappa 0.66 on
development data, 0.42 and 0.53 on the two fresh tests). Our first two rubrics
failed their pre-registered held-out tests (precision 0.37, then 0.57), and we
report both. The final rubric was fitted on development data only and tested
once on 30 brand-new Google India queries: **precision 0.88 [0.53, 0.98], recall
0.30, specificity 0.99** (n = 102). That meets our 0.70 precision target, though
the interval is wide; a one-line baseline ("no author and no date") reached a
slightly higher F1 by flagging 3.5 times as many pages at half the precision.
A fifth, one-time test on four topics it was never tuned on (government services,
scams, legal rights, education) gave precision 0.56: below the bar, reported as a
limit. SlopWatch almost never removes a good page and misses most bad ones. Details in
EVAL.md.

## Disclosures

- **Existing work:** the HTTP cache, HTTP client, SerpApi client and page fetcher
  were adapted from the author's earlier project Zero Hour; everything else was
  built for this hackathon (visible in the git history).
- **AI tools used:** Claude Code (development). As blind validation labelers
  only: Google Gemini (`gemini-3.5-flash-lite`), Cloudflare Workers AI
  (`gpt-oss-120b`) and, as an independent audit judge, `gemini-3.7-flash` on Google
  Cloud Vertex AI; Gemini is also the agent in the demo. No LLM is used in scoring.