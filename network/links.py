"""Outbound links: the web sites a message points to, and the domain index behind Manage → Domains.

A message can link out in four places: URLs written in its text, hidden links behind link text and
auto-linked bare domains (``Message.link_urls``, captured by the crawler from the message entities), its
inline URL buttons (also in ``link_urls``) and its link preview (``Message.webpage_url``). This module
turns them into **sites**:

* the host is lower-cased, its port dropped, an IDN encoded to punycode, and a leading ``www.``, ``m.``,
  ``mobile.`` or ``amp.`` stripped;
* the site is the **registered domain** — the last two labels, three under a common second-level suffix
  (``co.uk``, ``com.br``, …) — so ``news.example.co.uk`` and ``example.co.uk`` are one site;
* except on **platform hosts** (``*.substack.com``, ``*.blogspot.com``, ``*.myshopify.com``, …), where
  every subdomain is somebody's own outlet and stays a site of its own, and a few **service hosts**
  (``docs.google.com``, ``drive.google.com``, …) whose subdomain names a different service;
* Telegram's own hosts (``t.me``, ``telegram.me``, ``telegra.ph``, …) are left out: a t.me link is a
  citation, already in the graph.

A site counts once per message, however often the message repeats it. Shortened links are not resolved
(that would take a network request per link); shorteners are a category of their own.
"""

import collections
import datetime
import re
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

from django.db.models import Q

from network.parameters import FixedParameter

#: Hosts that are Telegram itself: links to them are citations or Telegram's own pages, not outbound links.
TELEGRAM_HOSTS: frozenset[str] = frozenset(
    {"t.me", "telegram.me", "telegram.dog", "telegram.org", "telegra.ph", "telesco.pe", "graph.org"}
)
#: Leading labels that name a mobile / accelerated copy of the same site.
STRIPPED_PREFIXES: tuple[str, ...] = ("www.", "m.", "mobile.", "amp.")
#: Second-level public suffixes under which the registered domain keeps three labels.
SECOND_LEVEL_SUFFIXES: frozenset[str] = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "me.uk",
        "ltd.uk",
        "plc.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "org.nz",
        "co.za",
        "org.za",
        "com.br",
        "org.br",
        "net.br",
        "com.ar",
        "com.mx",
        "com.tr",
        "com.ua",
        "org.ua",
        "com.pl",
        "co.jp",
        "co.kr",
        "co.in",
        "co.il",
        "com.cn",
        "com.hk",
        "com.sg",
        "com.ru",
        "com.es",
        "com.pt",
        "co.at",
        "or.at",
    }
)
#: Hosting platforms where each subdomain is a separate outlet (a blog, a newsletter, a shop, a link page).
PLATFORM_HOSTS: frozenset[str] = frozenset(
    {
        "substack.com",
        "blogspot.com",
        "wordpress.com",
        "github.io",
        "tumblr.com",
        "carrd.co",
        "neocities.org",
        "weebly.com",
        "wixsite.com",
        "myshopify.com",
        "bigcartel.com",
        "square.site",
        "itch.io",
        "locals.com",
        "gitbook.io",
    }
)
#: Subdomains kept whole because they name a different service of the same company.
SERVICE_HOSTS: frozenset[str] = frozenset(
    {
        "docs.google.com",
        "drive.google.com",
        "sites.google.com",
        "groups.google.com",
        "music.youtube.com",
        "web.archive.org",
    }
)

_URL_RE = re.compile(r"(?:https?://|\bwww\.)[^\s<>\"'`«»“”‘’]+", re.IGNORECASE)
_TRAILING = ".,;:!?…'\"»”’›*_~"
_HOST_RE = re.compile(r"^[a-z0-9.-]+$")

SITE_RULE = (
    "lower-cased host without port, IDN as punycode, leading www./m./mobile./amp. stripped; the registered domain "
    "(two labels, three under a second-level suffix), except platform hosts (each subdomain an outlet; "
    "open.substack.com/pub/<name> = <name>.substack.com) and service hosts (kept whole); Telegram hosts excluded; "
    "one count per (message, site)"
)

_SOURCE = "network/links.py"

#: The rules fixed in this module (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Outbound links: site rule",
        value=SITE_RULE,
        scope="links",
        affects="What one site is, and so every site count, share and co-linking tie.",
        source=f"{_SOURCE}: SITE_RULE",
    ),
    FixedParameter(
        name="Outbound links: platform hosts",
        value=", ".join(sorted(PLATFORM_HOSTS)),
        scope="links",
        affects="Hosting platforms whose subdomains are separate sites (a newsletter, a shop, a blog).",
        source=f"{_SOURCE}: PLATFORM_HOSTS",
    ),
    FixedParameter(
        name="Outbound links: Telegram hosts",
        value=", ".join(sorted(TELEGRAM_HOSTS)),
        scope="links",
        affects="Hosts left out: a t.me link is a citation already in the graph.",
        source=f"{_SOURCE}: TELEGRAM_HOSTS",
    ),
)


def _clean_url(raw: str) -> str:
    url = raw.rstrip(_TRAILING)
    # A closing bracket belongs to the URL only when the URL opened one (Wikipedia-style paths).
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while url.endswith(closing) and url.count(closing) > url.count(opening):
            url = url[:-1].rstrip(_TRAILING)
    return url


def text_urls(text: str | None) -> list[str]:
    """The ``http(s)://`` and ``www.`` URLs written in *text*, trailing punctuation trimmed."""
    return [url for url in (_clean_url(m.group(0)) for m in _URL_RE.finditer(text or "")) if url]


def host_of(url: str) -> str:
    """The normalised host of *url* (scheme optional), or ``""`` when it has none."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        if url.lower().startswith(("mailto:", "tg:", "tel:", "javascript:")):
            return ""
        url = "http://" + url
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    host = host.strip(".").lower()
    if not host:
        return ""
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    if not _HOST_RE.match(host) or "." not in host:
        return ""
    while True:
        for prefix in STRIPPED_PREFIXES:
            if host.startswith(prefix) and host.count(".") > 1:
                host = host[len(prefix) :]
                break
        else:
            return host


def registered_domain(host: str) -> str:
    """The registered domain of a normalised *host*: two labels, three under a second-level suffix."""
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


#: Hosts that redirect to a platform outlet named in the path: ``open.substack.com/pub/<name>/…`` is
#: ``<name>.substack.com``.
PATH_OUTLET_HOSTS: dict[str, str] = {"open.substack.com": "substack.com"}
_PATH_OUTLET_RE = re.compile(r"^/pub/([a-z0-9-]+)(?:/|$)", re.IGNORECASE)


def site_of(url: str) -> str:
    """The site *url* points to (module docstring), or ``""`` for Telegram's own hosts and non-web links."""
    host = host_of(url)
    if not host:
        return ""
    if host in PATH_OUTLET_HOSTS:
        match = _PATH_OUTLET_RE.match(urlsplit(url if "://" in url else "http://" + url).path or "")
        if match:
            return f"{match.group(1).lower()}.{PATH_OUTLET_HOSTS[host]}"
    domain = registered_domain(host)
    if host in TELEGRAM_HOSTS or domain in TELEGRAM_HOSTS:
        return ""
    if host in SERVICE_HOSTS:
        return host
    if domain in PLATFORM_HOSTS and host != domain:
        # The outlet is the label right under the platform: shop.name.myshopify.com → name.myshopify.com.
        return ".".join(host.split(".")[-(domain.count(".") + 2) :])
    return domain


def platform_of(site: str) -> str:
    """The hosting platform of a platform-hosted *site* (``name.substack.com`` → ``substack.com``), else ``""``."""
    domain = registered_domain(site)
    return domain if domain in PLATFORM_HOSTS and site != domain else ""


def message_urls(text: str | None, webpage_url: str | None = None, link_urls: Iterable[str] | None = None) -> list[str]:
    """Every URL a message carries: its text URLs, its captured link entities and buttons, its preview."""
    urls = text_urls(text)
    urls.extend(u for u in (link_urls or ()) if isinstance(u, str))
    if webpage_url:
        urls.append(webpage_url)
    return urls


def message_sites(text: str | None, webpage_url: str | None = None, link_urls: Iterable[str] | None = None) -> set[str]:
    """The sites a message links to — each once (module docstring)."""
    return {site for site in (site_of(url) for url in message_urls(text, webpage_url, link_urls)) if site}


def link_candidates_q() -> Q:
    """Messages that may carry an outbound link — a cheap pre-filter before parsing the text."""
    return (
        Q(message__icontains="http") | Q(message__icontains="www.") | ~Q(webpage_url="") | Q(link_urls__0__isnull=False)
    )


def scan_message_sites(
    message_q: Q,
    *,
    progress: Callable[[str], None] | None = None,
) -> "Iterable[tuple[int, int, datetime.datetime | None, set[str]]]":
    """``(message id, channel id, date, sites)`` for every alive message matching *message_q* that links out."""
    from webapp.models import Message

    qs = (
        Message.objects.alive()
        .filter(message_q)
        .filter(link_candidates_q())
        .values_list("id", "channel_id", "date", "message", "webpage_url", "link_urls")
    )
    for i, (message_id, channel_id, date, text, webpage_url, link_urls) in enumerate(qs.iterator(chunk_size=2000), 1):
        sites = message_sites(text, webpage_url, link_urls)
        if sites:
            yield message_id, channel_id, date, sites
        if progress and i % 5000 == 0:
            progress(f"scanning messages … {i}")


def index_domains(*, progress: Callable[[str], None] | None = None) -> dict[str, int]:
    """Rebuild the ``Domain`` counts from the in-target channels' alive, in-period messages.

    Every site seen gets a row (new ones inherit the category of their hosting platform's own row, so a new
    ``name.substack.com`` is filed with ``substack.com``); a row no message links to any more keeps its
    category and note with zero counts. Returns ``{"messages", "domains", "new"}``.
    """
    from network.utils import channel_cutoff_q
    from webapp.models import Domain

    posts: collections.Counter[str] = collections.Counter()
    channels: dict[str, set[int]] = collections.defaultdict(set)
    first: dict[str, datetime.datetime] = {}
    last: dict[str, datetime.datetime] = {}
    messages = 0
    for _message_id, channel_id, date, sites in scan_message_sites(channel_cutoff_q(), progress=progress):
        messages += 1
        for site in sites:
            posts[site] += 1
            channels[site].add(channel_id)
            if date is not None:
                if site not in first or date < first[site]:
                    first[site] = date
                if site not in last or date > last[site]:
                    last[site] = date

    existing = {d.name: d for d in Domain.objects.all()}
    category_of = {name: d.category_id for name, d in existing.items()}
    new_rows = []
    for site in posts:
        if site not in existing:
            new_rows.append(Domain(name=site, category_id=category_of.get(platform_of(site))))
    Domain.objects.bulk_create(new_rows, batch_size=500)
    rows = list(Domain.objects.all())
    for row in rows:
        row.posts = posts.get(row.name, 0)
        row.channels = len(channels.get(row.name, ()))
        row.first_seen = first.get(row.name)
        row.last_seen = last.get(row.name)
    Domain.objects.bulk_update(rows, ["posts", "channels", "first_seen", "last_seen"], batch_size=500)
    if progress:
        progress(f"indexed {len(posts)} sites over {messages} messages")
    return {"messages": messages, "domains": len(posts), "new": len(new_rows)}


def domain_categories() -> "tuple[dict[str, int | None], dict[int, Any]]":
    """``({site: category id}, {category id: DomainCategory})`` for every indexed site."""
    from webapp.models import Domain, DomainCategory

    return (
        dict(Domain.objects.values_list("name", "category_id")),
        {c.pk: c for c in DomainCategory.objects.all()},
    )


def category_for(site: str, site_categories: dict[str, int | None]) -> int | None:
    """The category of *site*: its own row's, else its hosting platform's (a site not indexed yet)."""
    if site in site_categories:
        return site_categories[site]
    platform = platform_of(site)
    return site_categories.get(platform) if platform else None
