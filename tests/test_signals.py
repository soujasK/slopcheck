"""Signal extractor tests on SYNTHETIC HTML pages (tests/html/). Third-party pages
are never committed, so these pages are hand-written to exercise each signal."""

from __future__ import annotations

from pathlib import Path

import pytest

from slopwatch.config import REPO_ROOT
from slopwatch.signals import (
    ads,
    affiliate,
    authorship,
    commerce,
    duplicate,
    extract,
    load_lists,
    parse_page,
    thin,
)
from slopwatch.signals.base import Link
from slopwatch.signals.lists import DomainLists, host_matches

HTML = Path(__file__).parent / "html"
LISTICLE_URL = "https://www.dealsite.example/best-phones-under-20000/"
OFFICIAL_URL = "https://www.incometax.gov.in/iec/foportal/help/link-aadhaar"
NEWS_URL = "https://news.example.in/business/tax-regime-2026"
THIN_URL = "https://www.blog.example/fastag"


@pytest.fixture(scope="module")
def lists() -> DomainLists:
    return load_lists(REPO_ROOT / "data")


def page(name: str, url: str):  # type: ignore[no-untyped-def]
    return parse_page(url, (HTML / name).read_text(encoding="utf-8"))


# -- parsing -------------------------------------------------------------------


def test_parse_regions_links_and_jsonld() -> None:
    p = page("news_article.html", NEWS_URL)
    assert p.title.startswith("Old vs new tax regime")
    assert p.main_text.startswith("Old vs new tax regime: which one")
    assert "Trending" in p.boiler_text and "Trending" not in p.main_text
    assert "Copyright" not in p.content_text
    assert {link.href for link in p.outbound()} == {
        "https://www.incometax.gov.in/iec/foportal/income-tax-calculator",
        "https://othernews.example.com/x",
    }
    types = {n.get("@type") for n in p.jsonld_nodes()}
    assert {"Organization", "NewsArticle"} <= types  # @graph flattened, broken block skipped
    assert any(h == ("h1", "Old vs new tax regime: which one should salaried people pick?")
               for h in p.headings)  # fmt: skip


def test_parse_resolves_relative_links_and_base() -> None:
    html = '<base href="https://cdn.example/x/"><a href="a">A</a><script src="s.js"></script>'
    p = parse_page("https://site.example/page", html)
    assert p.links[0].href == "https://cdn.example/x/a"
    assert p.script_srcs == ["https://cdn.example/x/s.js"]


def test_jsonld_list_and_inline_scripts() -> None:
    html = (
        '<script type="application/ld+json">[{"@type": "Article", "author": "Org"}, 3]</script>'
        "<p>text</p><script>var x = 'googlesyndication.com'</script><script></script>"
    )
    p = parse_page("https://a.example/", html)
    assert [n["@type"] for n in p.jsonld_nodes()] == ["Article"]
    assert p.inline_scripts == "var x = 'googlesyndication.com'\n"


def test_host_matches_suffixes() -> None:
    domains = frozenset({"amazon.in", "amzn.to"})
    assert host_matches("www.amazon.in", domains)
    assert host_matches("smile.amazon.in", domains)
    assert not host_matches("notamazon.in", domains)
    assert not host_matches("in", domains)


# -- affiliate -----------------------------------------------------------------


def test_affiliate_listicle(lists: DomainLists) -> None:
    n, density = affiliate.count(page("affiliate_listicle.html", LISTICLE_URL), lists)
    # amzn.to, flipkart affid, amazon tag, rel=sponsored croma, cuelinks of 7 outbound
    assert n == 5
    assert density == pytest.approx(5 / 7, abs=1e-4)


@pytest.mark.parametrize(
    ("href", "rel", "expected"),
    [
        ("https://www.amazon.in/dp/X?tag=site-21", "", True),
        ("https://www.amazon.in/dp/X?ref=nav", "", False),
        ("https://shop.example/p?utm_medium=Affiliate", "", True),
        ("https://shop.example/p?utm_medium=email", "", False),
        ("https://any.example/p?irclickid=abc", "", True),
        ("https://www.flipkart.com/p?affid=x", "", True),
        ("https://www.myntra.com/p?affid=x", "", True),
        ("https://brand.example/p", "sponsored", True),
        ("https://brand.example/p", "nofollow", False),
        ("https://go.skimresources.com/?id=1", "", True),
    ],
)
def test_is_affiliate(lists: DomainLists, href: str, rel: str, expected: bool) -> None:
    from slopwatch.signals.base import host_of

    link = Link(href, host_of(href), frozenset(rel.split()), "")
    assert affiliate.is_affiliate(link, lists) is expected


def test_no_outbound_links_means_zero(lists: DomainLists) -> None:
    p = parse_page("https://a.example/", '<a href="/x">x</a><a href="mailto:a@b.c">m</a>')
    assert affiliate.count(p, lists) == (0, 0.0)
    assert commerce.ratio(p, lists) == (0, 0.0)


def test_official_and_news_have_no_affiliates(lists: DomainLists) -> None:
    assert affiliate.count(page("official_howto.html", OFFICIAL_URL), lists) == (0, 0.0)
    assert affiliate.count(page("news_article.html", NEWS_URL), lists) == (0, 0.0)


# -- commerce --------------------------------------------------------------------


def test_commerce_ratio(lists: DomainLists) -> None:
    outbound, ratio = commerce.ratio(page("affiliate_listicle.html", LISTICLE_URL), lists)
    assert outbound == 7
    assert ratio == pytest.approx(6 / 7, abs=1e-4)  # all but the gsmarena specs link
    assert commerce.ratio(page("official_howto.html", OFFICIAL_URL), lists) == (2, 0.0)


@pytest.mark.parametrize(
    ("title", "headings", "expected"),
    [
        ("10 Best Smartphones Under 20000", [], True),
        ("Top 7 air fryers", [], True),
        ("Best running shoes for beginners", [("h2", f"{i}. Shoe {i}") for i in range(1, 4)], True),
        ("Best running shoes for beginners", [("h2", "Cushioning"), ("h2", "Fit")], False),
        ("How to stop spam calls", [("h2", "1. Settings")] * 5, False),
        ("Best of 2026: our year in review", [("h2", f"#{i} story") for i in range(5)], False),
        ("Laptop buying guide", [("h2", "1. CPU"), ("h2", "2. RAM"), ("h2", "3. SSD")], False),
    ],
)
def test_is_listicle(title: str, headings: list[tuple[str, str]], expected: bool) -> None:
    p = parse_page("https://a.example/", "")
    p.title = title
    p.headings = headings
    assert commerce.is_listicle(p) is expected


def test_listicle_from_h1_only() -> None:
    p = parse_page("https://a.example/", "<title>Shoes</title><h1>Top 5 shoes</h1>")
    assert commerce.is_listicle(p)


# -- ads -----------------------------------------------------------------------------


def test_ads_counts_distinct_domains(lists: DomainLists) -> None:
    # 6 script srcs + pubmatic/rubicon/openx named in an inline bidder config
    assert ads.count(page("affiliate_listicle.html", LISTICLE_URL), lists) == 9
    assert ads.count(page("news_article.html", NEWS_URL), lists) == 2
    assert ads.count(page("official_howto.html", OFFICIAL_URL), lists) == 1


def test_ads_dedupes_same_network(lists: DomainLists) -> None:
    html = (
        '<script src="https://securepubads.g.doubleclick.net/a.js"></script>'
        '<script src="https://stats.g.doubleclick.net/b.js"></script>'
        '<iframe src="https://tpc.googlesyndication.com/x"></iframe>'
        "<script>load('https://securepubads.g.doubleclick.net/c.js')</script>"
    )
    assert ads.count(parse_page("https://a.example/", html), lists) == 2


# -- authorship ------------------------------------------------------------------------


def test_authorship_by_page() -> None:
    assert authorship.check(page("affiliate_listicle.html", LISTICLE_URL)) == (False, False, False)
    assert authorship.check(page("official_howto.html", OFFICIAL_URL)) == (False, True, True)
    assert authorship.check(page("news_article.html", NEWS_URL)) == (True, True, True)
    assert authorship.check(page("thin_page.html", THIN_URL)) == (False, False, False)


@pytest.mark.parametrize(
    "html",
    [
        '<meta name="author" content="Dr. A. Rao">',
        '<script type="application/ld+json">{"@type":"Article","author":{"name":"X"}}</script>',
        '<script type="application/ld+json">{"@type":"Article","creator":"Team"}</script>',
        '<span itemprop="author">X</span>',
        '<link rel="author" href="/team/x">',
        '<a rel="author" href="/team/x">X</a>',
        '<div class="post-author">X</div>',
        '<p id="byline">By X</p>',
    ],
)
def test_author_evidence(html: str) -> None:
    assert authorship.has_author(parse_page("https://a.example/", html))


@pytest.mark.parametrize(
    "html",
    [
        '<meta property="article:published_time" content="2026-01-01T00:00:00Z">',
        '<script type="application/ld+json">{"dateModified":"2026-01-01"}</script>',
        '<time datetime="2026-01-01">Jan 1</time>',
        '<span itemprop="datePublished">2026</span>',
        "<p>Updated: Sept 3, 2026</p>",
        "<p>Published on 3rd September 2026 by staff</p>",
        "<p>Last updated 03/09/2026</p>",
    ],
)
def test_date_evidence(html: str) -> None:
    assert authorship.has_date(parse_page("https://a.example/", html))


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Copyright 2026</p>", False),
        ("<p>Updated recently</p>", False),
        ('<script type="application/ld+json">{"author": "", "datePublished": " "}</script>', False),
    ],
)
def test_no_false_evidence(html: str, expected: bool) -> None:
    p = parse_page("https://a.example/", html)
    assert authorship.has_date(p) is expected
    assert authorship.has_author(p) is expected


def test_about_contact_must_be_same_site() -> None:
    off_site = '<a href="https://other.example/about-us">About</a>'
    assert not authorship.has_about_contact(parse_page("https://a.example/", off_site))
    by_text = '<a href="/company-info">Contact us</a>'
    assert authorship.has_about_contact(parse_page("https://a.example/", by_text))


# -- thin ------------------------------------------------------------------------------


def test_thin_stats() -> None:
    official_len, official_boiler = thin.stats(page("official_howto.html", OFFICIAL_URL))
    assert official_len > 1500 and official_boiler < 0.15
    thin_len, thin_boiler = thin.stats(page("thin_page.html", THIN_URL))
    assert thin_len < 100 and thin_boiler > 0.6
    # no <article>/<main>: main text falls back to everything outside nav/header/footer
    listicle = page("affiliate_listicle.html", LISTICLE_URL)
    assert thin.main_text(listicle).startswith("10 Best Smartphones")
    assert "Disclaimer" not in thin.main_text(listicle)
    assert thin.stats(parse_page("https://a.example/", "")) == (0, 0.0)


# -- duplicate -------------------------------------------------------------------------

BASE = " ".join(f"sentence {i} about checking the fastag balance in the app" for i in range(60))


def test_simhash_is_stable_and_similarity_sensitive() -> None:
    a = duplicate.simhash(BASE)
    assert a == duplicate.simhash(BASE.upper())  # case-insensitive
    assert a == 0x0 or a.bit_length() <= 64
    near = duplicate.simhash(BASE.replace("sentence 7 ", "line 7 "))
    far = duplicate.simhash("completely different words about mattresses and back pain " * 40)
    assert duplicate.distance(a, near) <= duplicate.MAX_DISTANCE
    assert duplicate.distance(a, far) > duplicate.MAX_DISTANCE
    assert duplicate.simhash("") == 0
    assert duplicate.simhash("two words") != 0


def test_groups_only_across_domains_within_a_serp() -> None:
    h = duplicate.simhash(BASE)
    other = duplicate.simhash("completely different words about mattresses and back pain " * 40)
    items = [
        duplicate.DupItem("serp1", "https://a.example/x", h, 3000),
        duplicate.DupItem("serp1", "https://www.b.example/y", h, 3000),
        duplicate.DupItem("serp1", "https://a.example/z", h, 3000),  # same site as a/x
        duplicate.DupItem("serp1", "https://c.example/q", other, 3000),
        duplicate.DupItem("serp1", "https://d.example/short", h, 100),  # too short
        duplicate.DupItem("serp2", "https://e.example/w", h, 3000),  # different SERP
    ]
    groups = duplicate.groups(items)
    assert set(groups) == {"https://a.example/x", "https://www.b.example/y", "https://a.example/z"}
    assert len(set(groups.values())) == 1
    assert next(iter(groups.values())).startswith("dup-")


def test_groups_chain_across_serps() -> None:
    h = duplicate.simhash(BASE)
    items = [
        duplicate.DupItem("s1", "https://a.example/1", h, 900),
        duplicate.DupItem("s1", "https://b.example/1", h, 900),
        duplicate.DupItem("s2", "https://b.example/1", h, 900),
        duplicate.DupItem("s2", "https://c.example/1", h, 900),
    ]
    assert len(set(duplicate.groups(items).values())) == 1
    assert len(duplicate.groups(items)) == 3


# -- end to end ----------------------------------------------------------------------------


def test_extract_combines_signals(lists: DomainLists) -> None:
    html = (HTML / "affiliate_listicle.html").read_text(encoding="utf-8")
    out = extract(LISTICLE_URL, html, lists)
    s = out.signals
    assert (s.affiliate_links, s.outbound_links, s.listicle, s.ad_scripts) == (5, 7, True, 9)
    assert (s.has_author, s.has_date, s.has_about_contact) == (False, False, False)
    assert s.text_len == len(out.main_text) and s.text_len < 1500
    assert s.near_dup_group is None
    assert out.title.startswith("10 Best Smartphones")
    assert out.simhash == duplicate.simhash(out.main_text)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<a href="/cart">Cart</a>', True),
        ('<a href="https://www.shop.example/checkout/">Checkout</a>', True),
        ('<a href="https://other.example/cart">Their cart</a>', False),  # not same site
        ("".join(f'<a href="/products/p{i}">P{i}</a>' for i in range(3)), True),
        ("".join(f'<a href="/products/p{i}">P{i}</a>' for i in range(2)), False),
        ("<button>Add to Cart</button>", True),
        ("<p>Buy now and save</p>", True),
        ('<script type="application/ld+json">{"@type": ["Product"], "name": "x"}</script>', True),
        ('<script type="application/ld+json">{"@type": "Article"}</script>', False),
        ("<p>We explain how carts work.</p>", False),
    ],
)
def test_sells_directly(html: str, expected: bool) -> None:
    assert commerce.sells_directly(parse_page("https://www.shop.example/blog/x", html)) is expected


def test_extract_sets_sells_directly(lists: DomainLists) -> None:
    html = (HTML / "affiliate_listicle.html").read_text(encoding="utf-8")
    assert extract(LISTICLE_URL, html, lists).signals.sells_directly is False
