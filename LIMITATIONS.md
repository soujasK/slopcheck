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
