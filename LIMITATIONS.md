# Limitations

What SlopWatch's numbers can and cannot support.

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

## Labels: two LLMs, no human validation

Ground truth comes from two LLMs (Google `gemini-3.5-flash-lite`, Cloudflare
`@cf/openai/gpt-oss-120b`) labeling blind; only items where both agree count.
There is no human labeling and no inter-rater check against a person. Agreement
between the two was Cohen's kappa 0.47 with a 300-character excerpt and 0.66
with 2,000 characters of main text. Using only agreed items favours clearer
cases. LLM judges share training data and may share blind spots. Labeler A was
planned as `gemini-3.8-flash` but its free tier allows 20 requests per day, so
all 200/150 items were labeled with `gemini-3.5-flash-lite` (a smaller model).
13 round-2 items were not labeled by B (Cloudflare daily quota) and were dropped.

## Validation history

The first held-out test failed (rubric v2: precision 0.37, n = 71) and is
reported. The second, on 150 fresh pages (114 agreed), gave rubric v3 precision
0.57 [0.25, 0.84] and recall 0.19: still below the 0.70 target. Only 7 results
were flagged in that test, so the precision interval is wide. Labeler agreement
on the fresh set was lower (kappa 0.42). The rubric was then refitted on development data and tested once on a
fresh held-out sample. The rubric is tuned for precision; at its operating point
it catches roughly one in five low-quality pages (test recall 0.19), so shares
of "low" results are lower bounds of what the labelers would call low. The
prevalence correction divides by that recall and is very unstable (per-engine
corrected values range from 0% to 38%). Where the
round-3 test provides sensitivity and specificity, a prevalence-corrected share
(Rogan-Gladen) is reported next to the raw share.

## Signals

- Heuristic and deterministic. No AI-text detection, by design.
- Query relevance is lexical (stemmed word overlap): synonyms ("heartburn" for
  "acidity") count as off-query.
- Author/date detection reads markup and visible bylines; JavaScript-rendered
  pages may look anonymous or empty.
- Ad and tracker counts see only scripts present in the static HTML.

## Platform pages

Video, forum, social, app-store and shop results (about 30% of Google results)
are reported as a separate class and never scored: the signals were designed for
articles.

## Statistical power

Engine and locale comparisons are paired over 20 queries; only large differences
are detectable. "No detectable difference" is not "no difference".

## Agent demo

8 pre-registered questions, one Gemini call per condition, sources limited to
committed text (titles, snippets, excerpts of at most 300 characters). The
filter dropped a top-5 source for 2 of 8 questions; the demo shows the mechanism,
not a measured effect on answer quality.
