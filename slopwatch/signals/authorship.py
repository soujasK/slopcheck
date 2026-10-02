"""Identifiable responsibility: author, publication date, about/contact pages.

Evidence is taken from schema.org JSON-LD, meta tags, microdata, rel=author,
byline markup and visible "Updated on <date>" text. An organisation named as
author counts as an author (responsibility can be institutional).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from slopwatch.signals.base import ParsedPage

_AUTHOR_META = frozenset(
    {"author", "article:author", "dc.creator", "parsely-author", "sailthru.author", "byl"}
)
_DATE_META = frozenset(
    {
        "article:published_time",
        "article:modified_time",
        "og:updated_time",
        "date",
        "pubdate",
        "publish-date",
        "publishdate",
        "dc.date",
        "dc.date.issued",
        "dcterms.date",
        "dcterms.modified",
        "parsely-pub-date",
        "datepublished",
        "datemodified",
        "sailthru.date",
    }
)
_DATE_KEYS = ("datePublished", "dateModified", "dateCreated", "uploadDate")
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_VALUE = (
    rf"(\d{{1,2}}(st|nd|rd|th)?\s+{_MONTH},?\s+\d{{4}}"
    rf"|{_MONTH}\s+\d{{1,2}}(st|nd|rd|th)?,?\s+\d{{4}}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2})"
)
_VISIBLE_DATE = re.compile(
    r"\b(published|updated|posted|last\s+updated|modified|reviewed|written)\b[^\n]{0,30}?"
    + _DATE_VALUE,
    re.IGNORECASE,
)
VISIBLE_DATE_WINDOW = 5000
_ABOUT_CONTACT_PATH = re.compile(
    r"/(about|about-us|aboutus|about_us|contact|contact-us|contactus|contact_us|who-we-are"
    r"|our-team|team|editorial-policy|editorial-guidelines|our-story|company)(/|\.html?|$)",
    re.IGNORECASE,
)
_ABOUT_CONTACT_TEXT = frozenset(
    {"about", "about us", "contact", "contact us", "who we are", "our team", "our story"}
)


def _named(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return _named(value.get("name")) or bool(value.get("@id"))
    if isinstance(value, list):
        return any(_named(v) for v in value)
    return False


def has_author(page: ParsedPage) -> bool:
    if any(_named(n.get("author")) or _named(n.get("creator")) for n in page.jsonld_nodes()):
        return True
    if any(page.meta.get(k) for k in _AUTHOR_META):
        return True
    if "author" in page.itemprops or page.author_class_seen:
        return True
    return any("author" in link.rel for link in page.links)


def has_date(page: ParsedPage) -> bool:
    for node in page.jsonld_nodes():
        if any(isinstance(node.get(k), str) and node[k].strip() for k in _DATE_KEYS):
            return True
    if any(page.meta.get(k) for k in _DATE_META):
        return True
    if page.time_datetimes or {"datepublished", "datemodified"} & page.itemprops:
        return True
    window = (page.main_text or page.text)[:VISIBLE_DATE_WINDOW]
    return bool(_VISIBLE_DATE.search(window))


def has_about_contact(page: ParsedPage) -> bool:
    for link in page.same_site():
        if _ABOUT_CONTACT_PATH.search(urlsplit(link.href).path):
            return True
        if link.text.strip().lower() in _ABOUT_CONTACT_TEXT:
            return True
    return False


def check(page: ParsedPage) -> tuple[bool, bool, bool]:
    """``(has_author, has_date, has_about_contact)``."""
    return has_author(page), has_date(page), has_about_contact(page)
