# Analysis plan (pre-registered)

Written and committed **before any labeling and before any score of the
measurement data was looked at**. The git history is the evidence. Every number
in the final report comes from the procedures below; deviations, if any, are
listed in the report with the reason.

## 1. Data

- SERPs: `data/serps.jsonl` (100 searches, 822 organic rows, collected 2026-10-03;
  see SERPAPI_USAGE.md).
- Pages: `data/pages.jsonl`, `data/signals.jsonl` (482 of 681 unique pages scored;
  every other row carries an unscored reason).
- Scores: `slopwatch score` with the frozen `data/rubric.yaml`.

## 2. Validation of the scorer

- **Sample**: 200 (url, query) items, drawn by `slopwatch label --n 200 --seed 7`,
  stratified by category x engine x locale with proportional allocation, split
  into dev (100) and test (100) alternately within each stratum. Committed before
  labeling.
- **Labels**: two independent LLM labelers, no human labeling (decision recorded
  in LABELING.md before labeling): A = Google `gemini-3.5-flash-lite` (see
  Deviations), B = Cloudflare
  `@cf/openai/gpt-oss-120b`. Both are blind (guide + query, title, URL, excerpt
  only; never scores, signals or rubric), temperature 0, strict JSON. All
  requests and responses are recorded as fixtures.
- **Agreement**: Cohen's kappa between A and B on the 200 items, and labels per
  class for each labeler.
- **Ground truth for evaluation**: items where A and B agree on `ok` or `low`.
  Items with disagreement or any `unsure` are dropped and the count is reported.
- **Primary metric**: precision for the class "low" (predicted low = band `low`)
  on the **test** split, with a 95% Wilson interval. Secondary: recall, F1,
  specificity, confusion matrix.
- **Gate**: if test precision < 0.70, stop and decide (fix signals or fall back),
  as set in the project brief. The number is reported either way.
- **Tuning**: the rubric may be changed only using the dev split, each change in
  its own commit. The test split is evaluated once; `slopwatch evaluate` stamps
  the rubric hash into the output so a later change is detectable.
- **Baselines** on the same items: "any affiliate link", "no author and no
  date", "'best X' listicle", and random flagging at the scorer's rate. The
  rubric is claimed useful only if its test F1 exceeds every baseline's.
- All reports say plainly that labels come from two LLMs with no human
  validation, with kappa and n. They are never called human labels.

## 3. Observatory measurements

For each group, the report gives the share of **scored** rows in the `low` band,
together with:

- `n` scored rows and **coverage** (scored / all rows),
- a **95% cluster-bootstrap interval** (2000 resamples, seed 2026, clusters =
  queries),
- **bounds** if every unscored row were ok / low,
- a **prevalence-corrected** share (Rogan-Gladen) using the test-split
  sensitivity (recall) and specificity, shown next to the raw share.

Groups, fixed in advance:

1. India, by engine (Google, DuckDuckGo, Yahoo) and by category.
2. India vs US on Google, on the 20 locale-neutral queries only.
3. Low share by rank position (1-10), India Google.
4. Share of results that are platform pages (video, forum, social, app store,
   shop), by engine. Low shares in groups 1-3 are computed over scored,
   non-platform rows.

Comparisons (paired by query, same queries on both sides; difference in
per-query low share with a 95% paired-bootstrap interval and a two-sided
sign-flip permutation p-value, 2000 resamples, seed 2026):

- Google IN vs DuckDuckGo IN; Google IN vs Yahoo IN (20 shared queries).
- Google IN vs Google US (20 locale-neutral queries).

With 20 pairs, only large differences can be detected; a non-significant
difference is reported as "no detectable difference", not as "no difference".
DuckDuckGo and Yahoo are reported as the "Bing family" (shared index).

## 4. Agent before/after demo

8 questions fixed in `data/demo_questions.yaml` before running the demo. For
each: the share of cited sources in the `low` band with raw top-5 vs filtered
top-5, and whether the answer changed. All 8 are reported; none are dropped.

## Deviations

- 2026-10-03: labeler A changed from `gemini-3.8-flash` to `gemini-3.5-flash-lite`
  because the former's free tier allows 20 requests per day (see LABELING.md).
  Decided before any agreement or evaluation result was computed.

- 2026-10-03: **label round 2.** After seeing round-1 dev results (rubric v1
  precision 0.20; best v2 candidate 0.38; labeler kappa 0.47), all 200 items are
  re-labeled with the labelers seeing the first 2,000 characters of main text
  instead of a 300-character excerpt (protocol in LABELING.md, committed before
  any round-2 label). Round-2 agreed labels become the ground truth; round-1
  results are reported alongside. The rubric is chosen among the four already
  committed (v1, v2a, v2b, v2c) by round-2 dev F1; the test split is evaluated
  once. Signal added before round 2: `sells_directly`.

- 2026-10-04: **round 3 (fresh held-out set).** Rubric v2 failed the gate on the
  round-2 test split (precision 0.37; EVAL.md), which therefore can no longer be
  used for testing. All 155 round-2 labeled items become development data. A
  new sample of 150 results whose URLs appear in no earlier sample is drawn
  (`SLOPWATCH_LABEL_SET=round3 slopwatch label --n 150 --seed 2027`) and
  committed before any new model is fitted; it is labeled by the same two LLMs
  with the round-2 protocol (2,000 chars of main text) and used **only** as a
  one-time test. New signals may be built and rule weights may be fitted on
  the 155 development items only. The round-2 failure stays reported.

- 2026-10-04: **rubric v3 fitting procedure** (declared before it was run on
  real data): 11 yes/no candidate rules (slopwatch/fit.py `CANDIDATES`, incl.
  the new query-relevance and sells_directly signals); L2 logistic regression
  on the 155 development items; rule weight = positive coefficient / sum of
  positive coefficients (others dropped); `low` threshold by 5-fold
  cross-validation = best out-of-fold F1 among thresholds with out-of-fold
  precision >= 0.70 (else highest out-of-fold precision with >= 10 flagged);
  `mixed` = half of it. The result is frozen as rubric v3 and tested once on
  round 3.

## 5. What will not be claimed

- No per-site "spam" verdicts; examples show only the signals that fired.
- No claim about trends (one snapshot).
- No claim about how humans experience these SERPs (we measure what an agent
  retrieves via SerpApi).
