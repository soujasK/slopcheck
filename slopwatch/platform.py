"""Platform pages (video, forum, social, app store, shop): not articles.

The text signals are designed for articles, so platform results are a separate
class (data/platform_domains.yaml + shops from data/commerce_domains.yaml): they
are excluded from the label sample and the precision/recall metrics, and their
share of results is reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from slopwatch.signals.base import host_of
from slopwatch.signals.lists import load_lists

KINDS = ("video", "forum", "social", "app_store")


@dataclass(frozen=True)
class PlatformList:
    by_domain: dict[str, str]  # domain -> kind

    def kind(self, url: str) -> str | None:
        parts = host_of(url).split(".")
        for i in range(len(parts) - 1):
            hit = self.by_domain.get(".".join(parts[i:]))
            if hit:
                return hit
        return None


def load_platforms(data_dir: Path) -> PlatformList:
    raw: Any = yaml.safe_load((data_dir / "platform_domains.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("platform_domains.yaml: expected a mapping")
    by_domain = dict.fromkeys(load_lists(data_dir).shops, "shop")
    for kind in KINDS:
        for domain in raw.get(kind) or []:
            by_domain[str(domain).lower()] = kind
    return PlatformList(by_domain)
