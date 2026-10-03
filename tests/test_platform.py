from __future__ import annotations

import pytest

from slopwatch.config import REPO_ROOT
from slopwatch.platform import load_platforms


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.youtube.com/watch?v=x", "video"),
        ("https://m.youtube.com/watch?v=x", "video"),
        ("https://healthislife.quora.com/What-are", "forum"),
        ("https://www.reddit.com/r/IndiaInvestments/", "forum"),
        ("https://techcommunity.microsoft.com/t/x", "forum"),
        ("https://www.facebook.com/post/1", "social"),
        ("https://apps.apple.com/us/app/x/id1", "app_store"),
        ("https://www.flipkart.com/redmi/p/itm1", "shop"),
        ("https://www.amazon.in/dp/B0X", "shop"),
        ("https://www.healthline.com/nutrition/x", None),
        ("https://support.google.com/x", None),
        ("https://www.microsoft.com/x", None),
    ],
)
def test_platform_kinds(url: str, kind: str | None) -> None:
    assert load_platforms(REPO_ROOT / "data").kind(url) == kind
