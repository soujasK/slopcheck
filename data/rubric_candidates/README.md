# Rubric v2 candidates

Declared and committed before any of them was evaluated. Each is evaluated on
the **dev** split only; the one with the highest dev F1 (ties: the simpler one)
becomes `data/rubric.yaml` v2. The test split is evaluated once, with that
rubric only. Motivation (from dev errors of v1): most pages the labelers called
low were anonymous pages and shops' own blogs, which v1 (built around affiliate
links) did not catch.

- v2a: v1 + `no_author` (0.30) + `sells_directly` (0.25); bands unchanged
- v2b: anonymity-first: `anonymous` 0.40, + `no_author` 0.15, + `sells_directly` 0.25
- v2c: v2a with bands low 0.40 / mixed 0.20
