from __future__ import annotations

import pytest

from slopwatch.domains import registrable_domain


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.economictimes.indiatimes.com/x", "indiatimes.com"),
        ("news.bbc.co.uk", "bbc.co.uk"),
        ("https://incometax.gov.in/iec/foportal", "incometax.gov.in"),
        ("https://www.bankbazaar.co.in/a", "bankbazaar.co.in"),
        ("someone.blogspot.com", "someone.blogspot.com"),
        ("WWW.Example.COM.", "example.com"),
        ("192.168.0.1", "192.168.0.1"),
        ("localhost", "localhost"),
    ],
)
def test_registrable_domain(value: str, expected: str) -> None:
    assert registrable_domain(value) == expected
