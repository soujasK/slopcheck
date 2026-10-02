"""Near-duplicate pages across different publishers in the same SERP set.

64-bit simhash over word 3-shingles of the main text (blake2b, so values are
stable across runs and Python versions). Two pages are near-duplicates when
their simhashes differ in at most ``MAX_DISTANCE`` bits, both have at least
``MIN_TEXT_LEN`` chars of main text, they appear in the same SERP (same request),
and they come from different registrable domains. Groups are connected
components; a group id is derived from its sorted member URLs.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from slopwatch.domains import registrable_domain

MAX_DISTANCE = 3
MIN_TEXT_LEN = 500
_WORD = re.compile(r"\w+", re.UNICODE)


def simhash(text: str) -> int:
    tokens = _WORD.findall(text.lower())
    shingles = (
        [" ".join(tokens[i : i + 3]) for i in range(len(tokens) - 2)]
        if len(tokens) >= 3
        else tokens
    )
    if not shingles:
        return 0
    weights = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    return sum(1 << bit for bit in range(64) if weights[bit] > 0)


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


@dataclass(frozen=True)
class DupItem:
    set_key: str  # SERP request hash
    url: str
    simhash: int
    text_len: int


def groups(items: list[DupItem], *, max_distance: int = MAX_DISTANCE) -> dict[str, str]:
    """``{url: group_id}`` for every URL that has a near-duplicate."""
    parent: dict[str, str] = {}

    def find(u: str) -> str:
        parent.setdefault(u, u)
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    by_set: dict[str, list[DupItem]] = defaultdict(list)
    for item in items:
        if item.text_len >= MIN_TEXT_LEN:
            by_set[item.set_key].append(item)
    linked: set[str] = set()
    for members in by_set.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if a.url == b.url or registrable_domain(a.url) == registrable_domain(b.url):
                    continue
                if distance(a.simhash, b.simhash) <= max_distance:
                    parent[find(a.url)] = find(b.url)
                    linked.update((a.url, b.url))
    components: dict[str, list[str]] = defaultdict(list)
    for url in linked:
        components[find(url)].append(url)
    result: dict[str, str] = {}
    for urls in components.values():
        gid = "dup-" + hashlib.sha256("\n".join(sorted(urls)).encode()).hexdigest()[:10]
        result.update(dict.fromkeys(urls, gid))
    return result
