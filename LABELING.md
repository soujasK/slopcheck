# Labeling guide

Frozen before the first label was produced. The section between the
`labeler-guide` markers is the complete guide given to the labelers, verbatim;
nothing else from this repository is shown to them.

<!-- labeler-guide:start -->
## Task

You are given one web search result: the search **query**, the result page's
**title**, its **URL**, and an **excerpt** of at most 300 characters of the
page's main text. You cannot open the page. Answer one question:

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
  the judges see only a 300-character excerpt. This is stated in the README and
  LIMITATIONS.md.

## Deviation (2026-10-03, during labeling)

Labeler A was planned as `gemini-3.8-flash`. Its free tier allows 20 requests per
day (Google's `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), which was
exhausted after 7 items; 200 items would take 10 days, past the deadline. All 200
items are therefore labeled by `gemini-3.5-flash-lite`, the newest Flash-Lite
model (weaker than Flash). The 7 `gemini-3.8-flash` replies remain in the
fixtures but are not used. Labeler B was unaffected. The guide, the items and
the prompt are unchanged.

## Process rules

- The 200-item sample is drawn with a fixed seed (`slopwatch label --n 200 --seed 7`)
  from scored, non-platform results, and committed before labeling.
- The rubric is tuned on the dev half only. The test half is evaluated once, at
  the end, and reported as is.
