# Labeling guide

DRAFT for review. Freeze (commit) this file and `data/rubric.yaml` before the first
label is written.

## The question

For each result you see the **query**, the page **title**, its **URL** and a short
**excerpt** of the main text. You never see the score. Answer one question:

> Is this a page an AI agent should ground an answer to this query on?

| Key | Label | Use when |
|---|---|---|
| `l` | **low** | The page's primary purpose is monetised referral or mass-produced content rather than answering the query. |
| `o` | **ok** | The page genuinely answers the query **and** has identifiable responsibility: a named author, an organisation, or an official source. |
| `u` | **unsure** | You cannot tell from what you see, or the page fits neither definition. Excluded from the metrics. Use it honestly rather than guessing. |

Other keys: `n` add a note before labeling, `s` skip, `b` back, `q` quit (progress is saved).

You may open the URL in a browser when the excerpt is not enough. Spend at most
about 30 seconds per page; if it still is not clear, use `unsure`.

## "low": signs to look for

- Product roundups ("10 best …") where most links go to shops through affiliate
  links, with little evidence of hands-on testing.
- Generic text that could be about any product or condition, padded with
  keyword variations of the query.
- Doorway or tag pages, scraped or spun copies of other pages, auto-generated
  Q&A.
- Health or finance advice with no author, no organisation and no sources, sold
  next to products or ads.

## "ok": signs to look for

- Official sources (government portals, regulators, banks' own help pages,
  hospital or medical-body pages).
- Articles with a named author or a clearly identified organisation that answer
  the query directly.
- Product reviews that show their own testing (measurements, photos, comparisons),
  even if they also carry affiliate links.

Affiliate links alone do not make a page low. The question is the page's primary
purpose.

## Judging the query, not the site

Label the page for **this query**. A reputable site's thin tag page can be low,
and a small blog that answers the query well with a named author can be ok.

## Open question: platform pages (decide before freezing)

The SERPs contain many pages that are not articles: YouTube videos (56 rows),
Reddit and Quora threads, Facebook posts, and shop product pages (Flipkart,
Amazon). The text signals were designed for articles and will misread these: a
video page looks "thin", a product page looks "commercial". Options:

1. **Label them like any page** using the definitions above (a helpful forum
   thread is ok, a shop page answering a "best X" query is low or unsure). Simple,
   but the scorer will probably make systematic errors on them.
2. **Treat them as a separate class** ("platform"): not scored as ok/low, excluded
   from precision/recall, and reported separately in the observatory ("X% of top
   results are video/forum/shop pages"). More honest about what the signals can
   do; needs a fixed, committed list of platform domains.
3. **Label them `unsure`** by rule. Cheapest, but hides a large share of results.

The choice is recorded here before labeling starts.

## Process rules

- The 200-item sample is drawn with a fixed seed (`slopwatch label --n 200 --seed 7`)
  and committed before labeling.
- One labeler (solo); there is no inter-rater agreement. This is stated in
  LIMITATIONS.md.
- Labels are append-only; relabeling an item keeps the latest label.
- The rubric is tuned on the dev half only. The test half is evaluated once, at
  the end, and reported as is.
