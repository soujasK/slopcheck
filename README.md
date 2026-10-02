# SlopWatch

Don't feed your agent slop. (Work in progress; full README lands in Phase 3.)

## Ethics

- No copies of third-party pages are published. The repo holds SERP data, page
  hashes, fetch metadata, excerpts of at most 300 characters and derived signals
  (see [LIMITATIONS.md](LIMITATIONS.md)).
- robots.txt is respected; pages it disallows, or whose robots.txt is unreachable,
  are reported as unscored and are never fetched.
- Results are reported in aggregate. There is no per-site "spam" list; example
  pages are shown only with the low-quality signals that fired.
