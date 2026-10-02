"""Domain lists used by the signal extractors (data/*_domains.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def host_matches(host: str, domains: frozenset[str]) -> bool:
    """True if ``host`` equals or is a subdomain of any listed domain."""
    host = host.lower().removeprefix("www.")
    parts = host.split(".")
    return any(".".join(parts[i:]) in domains for i in range(len(parts) - 1))


@dataclass(frozen=True)
class ParamRule:
    hosts: frozenset[str]
    params: frozenset[str]


@dataclass(frozen=True)
class DomainLists:
    affiliate_hosts: frozenset[str]
    affiliate_param_rules: tuple[ParamRule, ...]
    affiliate_generic_params: frozenset[str]
    affiliate_utm_mediums: frozenset[str]
    ad_domains: frozenset[str]  # ads + trackers
    shops: frozenset[str]


def _set(values: Any) -> frozenset[str]:
    return frozenset(str(v).lower() for v in (values or []))


def load_lists(data_dir: Path) -> DomainLists:
    def read(name: str) -> dict[str, Any]:
        raw = yaml.safe_load((data_dir / name).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{name}: expected a mapping")
        return raw

    aff = read("affiliate_domains.yaml")
    ads = read("ad_domains.yaml")
    shops = read("commerce_domains.yaml")
    return DomainLists(
        affiliate_hosts=_set(aff.get("redirect_hosts")),
        affiliate_param_rules=tuple(
            ParamRule(_set(r.get("hosts")), frozenset(str(p) for p in r.get("params") or []))
            for r in aff.get("param_rules") or []
        ),
        affiliate_generic_params=frozenset(str(p) for p in aff.get("generic_params") or []),
        affiliate_utm_mediums=_set(aff.get("affiliate_utm_mediums")),
        ad_domains=_set(ads.get("ads")) | _set(ads.get("trackers")),
        shops=_set(shops.get("shops")),
    )
