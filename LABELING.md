# Labeling guide

Frozen before the first label was produced. The section between the
`labeler-guide` markers is the complete guide given to the labelers, verbatim;
nothing else from this repository is shown to them.

<!-- labeler-guide:start -->
## Task

You are given one web search result: the search **query**, the result page's
**title**, its **URL**, and the beginning of the page's **main text** (up to
2,000 characters). You cannot open the page. Answer one question:

> Is this a page an AI agent should ground an answer to this query on?

Choose exactly one label:

- **low**: the page's primary purpose is monetised referral or mass-produced
  content rather than answering the query.
- **ok**: the page genuinely answers the query **and** has identifiable
  responsibility: a named author, an organisation, or an official source.
- **unsure**: you cannot tell from what you see, or the page fits neither
  definition. Use it honestly rather than guessing.

## Signs of "low"

- Product roundups ("10 best ...") whose links mostly go to shops through
  affiliate links, with little evidence of hands-on testing.
- Generic text that could be about any product or condition, padded with
  keyword variations of the query.
- Doorway or tag pages, scraped or spun copies of other pages, auto-generated
  question-and-answer pages.
- Health or finance advice with no author, no organisation and no sources, sold
  next to products or ads.

## Signs of "ok"

- Official sources: government portals, regulators, banks' own help pages,
  hospital or medical-body pages.
- Articles with a named author or a clearly identified organisation that answer
  the query directly.
- Product reviews that show their own testing (measurements, photos,
  comparisons), even if they also carry affiliate links.

Affiliate links alone do not make a page low; the question is the page's
primary purpose.

## Judge the page for this query, not the site

A reputable site's thin tag page can be low, and a small blog that answers the
query well with a named author can be ok. The domain in the URL is evidence,
not the verdict.
<!-- labeler-guide:end -->

## Decisions recorded before labeling

- **Platform pages are a separate class.** Results on video, forum, social,
  app-store and shop domains (`data/platform_domains.yaml` plus the shops in
  `data/commerce_domains.yaml`) are not articles. They are excluded from the
  label sample and from precision/recall, and their share of results is
  reported separately.
- **Labels come from two LLMs, not from humans.** There is no human labeling.
  Labeler A is Google `gemini-3.5-flash-lite` (see the deviation note below);
  labeler B is Cloudflare Workers AI
  `@cf/openai/gpt-oss-120b` (fallback `@cf/meta/llama-3.3-70b-instruct-fp8-fast`,
  used only if the primary is unavailable, and reported if used). Both get the
  guide above plus one item, at temperature 0, and must answer strict JSON
  `{"label": "ok"|"low"|"unsure", "reason": "..."}`. They never see scores,
  signals, the rubric or its reasons. Every request and response is recorded
  as a fixture.
- **Agreement and evaluation.** Cohen's kappa between A and B is reported. The
  scorer is evaluated only on items where A and B agree on ok or low; the
  number of items dropped (disagreement or any `unsure`) is reported.
- These labels measure agreement with two LLM judges, not human judgement, and
  the judges see only part of the page (round 1: a 300-character excerpt;
  round 2: the first 2,000 characters of main text). This is stated in the README and
  LIMITATIONS.md.

## Deviation (2026-10-03, during labeling)

Labeler A was planned as `gemini-3.8-flash`. Its free tier allows 20 requests per
day (Google's `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), which was
exhausted after 7 items; 200 items would take 10 days, past the deadline. All 200
items are therefore labeled by `gemini-3.5-flash-lite`, the newest Flash-Lite
model (weaker than Flash). The 7 `gemini-3.8-flash` replies remain in the
fixtures but are not used. Labeler B was unaffected. The guide, the items and
the prompt are unchanged.

## Round 2 (declared 2026-10-03, before any round-2 label)

Round 1 (above protocol, 300-character excerpt) gave Cohen's kappa 0.47 between
the labelers, and on the dev split the frozen rubric v1 reached precision 0.20
and the best v2 candidate 0.38. Because the round-1 ground truth was judged too
unreliable (the labelers could not see the page beyond 300 characters), all 200
items are labeled again, **after** those dev results were seen:

- Same items, same labelers and models (A `gemini-3.5-flash-lite`, B
  `@cf/openai/gpt-oss-120b`), temperature 0, same JSON contract.
- The only change: the item shows the first 2,000 characters of the page's main
  text (from the fetched snapshot, verified against its SHA-256) instead of the
  300-character excerpt; the guide's first paragraph says so (round 1's wording
  is in git history).
- Still blind: never scores, signals, the rubric or its reasons.
- Ground truth = round-2 items where A and B agree on ok or low. Round-1 labels
  are kept (`labels/round1/`) and reported.
- Rubric choice: among the four rubrics already committed (v1 and candidates
  v2a, v2b, v2c), the one with the highest dev F1 on round-2 labels; then the
  test split is evaluated once.
- The 2,000-character texts are third-party content and are not committed, so
  round-2 requests cannot be rebuilt from a fresh clone; labels and recorded
  responses are committed.

## Round 3 (declared 2026-10-04, before any round-3 label or model fit)

Fresh held-out test set: 150 results whose URLs are in no earlier sample,
drawn with seed 2027 from scored, non-platform results. Same labelers, models,
guide and protocol as round 2. Used once, as the test for the model developed
on the 155 round-2 items. Files: `labels/round3/`.

## Process rules

- The 200-item sample is drawn with a fixed seed (`slopwatch label --n 200 --seed 7`)
  from scored, non-platform results, and committed before labeling.
- The rubric is tuned on the dev half only. The test half is evaluated once, at
  the end, and reported as is.
