"""Registrable-domain grouping without a public-suffix-list dependency.

Copied from Zero Hour. Used to tell whether two results come from the same
publisher (near-duplicate detection only counts copies across *different*
publishers). A compact list of multi-label public suffixes plus hosting suffixes
where each subdomain is a different publisher (github.io, blogspot.com, ...)
covers the sources seen in practice; anything else falls back to the last two
labels.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from urllib.parse import urlsplit

_SUFFIXES = """
co.uk org.uk ac.uk gov.uk me.uk ltd.uk plc.uk net.uk sch.uk nhs.uk com.au net.au org.au
edu.au gov.au asn.au id.au co.nz org.nz net.nz ac.nz govt.nz co.jp ne.jp or.jp ac.jp
go.jp gr.jp co.in net.in org.in ac.in gov.in edu.in res.in firm.in gen.in ind.in com.br
net.br org.br gov.br edu.br com.cn net.cn org.cn gov.cn edu.cn ac.cn com.tw org.tw
edu.tw gov.tw idv.tw com.hk org.hk edu.hk gov.hk net.hk com.sg edu.sg gov.sg org.sg
net.sg com.my org.my edu.my gov.my net.my com.ph org.ph edu.ph gov.ph net.ph co.id ac.id
or.id go.id web.id my.id co.za org.za ac.za gov.za net.za co.kr or.kr ac.kr go.kr ne.kr
re.kr co.il org.il ac.il gov.il net.il com.mx org.mx edu.mx gob.mx net.mx com.ar org.ar
gob.ar edu.ar net.ar com.tr org.tr edu.tr gov.tr net.tr com.ua org.ua net.ua gov.ua
edu.ua com.pl org.pl net.pl edu.pl gov.pl com.ru org.ru net.ru com.vn edu.vn gov.vn
net.vn com.pk edu.pk gov.pk org.pk com.ng org.ng edu.ng gov.ng co.ke or.ke ac.ke go.ke
com.eg edu.eg gov.eg com.sa edu.sa gov.sa co.th ac.th go.th or.th in.th com.co edu.co
gov.co com.pe edu.pe gob.pe com.es org.es edu.es gob.es co.at or.at ac.at gv.at com.gr
edu.gr gov.gr github.io gitlab.io pages.dev vercel.app netlify.app herokuapp.com
blogspot.com wordpress.com substack.com tumblr.com hashnode.dev medium.com
readthedocs.io azurewebsites.net cloudfront.net
"""
MULTI_LABEL_SUFFIXES = frozenset(_SUFFIXES.split())


@lru_cache(maxsize=4096)
def registrable_domain(host_or_url: str) -> str:
    """``news.bbc.co.uk`` -> ``bbc.co.uk``; ``labs.snyk.io`` -> ``snyk.io``."""
    raw = host_or_url.strip()
    host = (urlsplit(raw).hostname if "://" in raw else raw) or ""
    host = host.lower().rstrip(".").removeprefix("www.")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    for size in (3, 2):
        if len(labels) > size and ".".join(labels[-size:]) in MULTI_LABEL_SUFFIXES:
            return ".".join(labels[-(size + 1) :])
    return ".".join(labels[-2:])
