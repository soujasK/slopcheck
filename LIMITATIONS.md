# Limitations

Draft. Completed in Phase 3; items are recorded here as design decisions are made.

## Reproducibility: page HTML is not committed

The repository does not contain copies of third-party web pages. What is committed:

- SerpApi responses (SERP JSON fixtures),
- per-page fetch metadata: URL, HTTP status, fetch time, SHA-256 of the HTML,
  title, an excerpt of at most 300 characters, text length, and the unscored
  reason if any,
- derived signals per page.

`score`, `evaluate`, `report` and `filter` replay from these with no network and no
API key. `fetch` is the only step that needs the network; re-running it later
fetches pages as they are then, which may differ from the snapshot. The stored
HTML hash shows whether a page changed, but the original HTML cannot be
recovered from the repo, so the signal extractors cannot be re-run on the
original snapshot by a third party.

## Engines

- Bing could not be measured. SerpApi's Bing engine returned empty or
  first-word-only results for India in three probes (see SERPAPI_USAGE.md), so
  it was replaced before collection by DuckDuckGo and Yahoo.
- DuckDuckGo and Yahoo both draw heavily on Bing's index (in the probe, all 7
  Yahoo results were also in DuckDuckGo's top 10). They are reported as the
  "Bing family", not as independent engines.

## Result counts

"Top 10" means the organic results the engine returned on its first page, up
to 10. Google returned 6 to 10 (it showed an AI Overview on 39 of 40 India
searches and 20 of 20 US searches), DuckDuckGo 9 to 10, Yahoo always 7.
Fetching a second page would have doubled the SerpApi cost. The report states
the actual n per engine.

## Snapshot

All SERPs were collected on 2026-10-03 from one location via SerpApi. Results
vary by day, user and location; this is one snapshot, not a trend.

## Coverage (pages that could be scored)

482 of 681 unique pages (593 of 822 SERP rows, 72%) were fetched and scored.
The rest are reported as unscored with a reason, never guessed: 81 refused our
crawler with HTTP 403, 14 answered 402 Payment Required (pay-per-crawl), 68 are
disallowed by robots.txt (Reddit, Quora, Facebook, LinkedIn, Instagram among
them), 13 were unreachable, and a few were too large, not HTML or had a broken
robots.txt.

Coverage is not uniform: 72-81% of rows for the India engines but only 56% for
Google US, where several large publishers block crawlers. Every comparison in
the report shows its coverage next to it; low-quality shares are computed over
scored rows only.
