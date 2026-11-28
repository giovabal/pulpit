"""How an export presents itself once it is uploaded to a public web server.

``structural_analysis --seo`` (panel *Presentation → SEO-optimised*) picks one of two policies.
:func:`publish` applies it to the whole export folder as the run's last step, and ``compare_analysis``
applies it again after adding its pages, so every page follows the policy whichever writer made it,
the compared export's ``*_2.html`` copies included.

**Search-optimised** (``--seo``). Every page the landing page links to is indexable and carries a
description and Open Graph / Twitter tags. With ``--public-url`` (the address the export will be
published at) it also carries a canonical link and ``og:url``, and ``sitemap.xml`` lists those pages.
The landing page describes the export as a schema.org ``Dataset`` whose downloads are its CSV, XLSX,
GEXF and GraphML files, which is what Google Dataset Search reads. The other pages carry a breadcrumb
back to it. ``robots.txt`` lets every crawler in and names the sitemap. A page nothing links to, such
as a map template copied without its data, stays out of the index.

**Private** (the default). Every page asks not to be indexed, followed, cached, quoted, translated or
used for AI. It does so through the robots meta tag and through the TDMRep ``tdm-reservation``, the
machine-readable text-and-data-mining opt-out of EU Directive 2019/790, art. 4. Pages also send no
referrer, so following a link out does not give the export's address to another site. ``robots.txt``
turns away every crawler and names the AI crawlers one by one. ``.htaccess`` (Apache) and ``_headers``
(Netlify, Cloudflare Pages) send the same signals as HTTP headers on every file, reaching the JSON,
CSV, spreadsheets and pictures that a meta tag cannot. On Apache, ``.htaccess`` also answers the AI
crawlers with 403 Forbidden, because several of them ignore robots.txt.
"""

from __future__ import annotations

import datetime
import html
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from network.pages import LANDING_PAGE, page_description

ROBOTS_TXT = "robots.txt"
SITEMAP_XML = "sitemap.xml"
HTACCESS = ".htaccess"
HEADERS_FILE = "_headers"
# Opening words of every server file written here: a file that starts with them is ours to replace
# or delete when the policy changes, and any other file is left alone.
SITE_FILE_MARK = "Written by Pulpit"

INDEX_ROBOTS = "index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"
PRIVATE_ROBOTS = "noindex, nofollow, noarchive, nosnippet, noimageindex, notranslate, noai, noimageai"
# A search-optimised export's page that the landing page does not link to.
UNLISTED_ROBOTS = "noindex"

# User agents of the crawlers that gather pages for AI models or answer engines, and of the fetchers
# their assistants send when a user hands them a link. robots.txt names each of them, and on Apache
# .htaccess refuses them. Sources: each operator's crawler documentation, and the ai.robots.txt list.
AI_USER_AGENTS: tuple[str, ...] = (
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "anthropic-ai",
    "PerplexityBot",
    "Perplexity-User",
    "Google-CloudVertexBot",
    "GoogleOther",
    "CCBot",
    "Bytespider",
    "Amazonbot",
    "meta-externalagent",
    "meta-externalfetcher",
    "FacebookBot",
    "cohere-ai",
    "cohere-training-data-crawler",
    "MistralAI-User",
    "DuckAssistBot",
    "YouBot",
    "Diffbot",
    "AI2Bot",
    "Ai2Bot-Dolma",
    "omgili",
    "omgilibot",
    "Timpibot",
    "ImagesiftBot",
    "img2dataset",
    "PanguBot",
    "iaskspider",
    "ICC-Crawler",
)
# robots.txt tokens that name what an ordinary search crawler's pages may be used for (AI training,
# grounding) rather than a crawler of their own. No request carries them, so only robots.txt names them.
AI_ROBOTS_TOKENS: tuple[str, ...] = ("Google-Extended", "Applebot-Extended", "Webzio-Extended")

# Keywords of the landing page's Dataset description.
DATASET_KEYWORDS: tuple[str, ...] = (
    "Telegram",
    "Telegram channels",
    "social network analysis",
    "network graph",
    "forwards",
    "mentions",
    "community detection",
)
# Shortest Dataset description Google Dataset Search accepts.
DATASET_MIN_DESCRIPTION = 50
# The export's downloads, by extension, as the Dataset's distributions.
DOWNLOAD_TYPES: dict[str, str] = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".gexf": "application/gexf+xml",
    ".graphml": "application/graphml+xml",
}

_BLOCK_START = "<!-- pulpit:publication -->"
_BLOCK_END = "<!-- /pulpit:publication -->"
_BLOCK_RE = re.compile(r"\n?[ \t]*" + re.escape(_BLOCK_START) + r".*?" + re.escape(_BLOCK_END), re.S)
# Head tags the policy owns, wherever a template or an earlier writer put them.
_OWNED_TAG_RE = re.compile(
    r'\n?[ \t]*(?:<meta\s+(?:name|property)="(?:robots|referrer|tdm-reservation|og:[\w:]+|twitter:[\w:]+)"[^>]*>'
    r'|<link\s+rel="canonical"[^>]*>'
    r"|<!-- (?:Open Graph|Twitter Card) -->)",
    re.I,
)
_ROBOTS_META_RE = re.compile(r'(<meta\s+name="robots"\s+content=")[^"]*(")', re.I)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_DESCRIPTION_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)
_PAGE_LINK_RE = re.compile(r'href="([^"#?:/]+\.html)(?:[#?][^"]*)?"', re.I)


def robots_content(seo: bool) -> str:
    """The ``<meta name="robots">`` value of a page written under the *seo* policy."""
    return INDEX_ROBOTS if seo else PRIVATE_ROBOTS


def set_robots_meta(content: str, seo: bool) -> str:
    """*content* with its robots meta tag set to the *seo* policy's value."""
    return _ROBOTS_META_RE.sub(lambda m: f"{m.group(1)}{robots_content(seo)}{m.group(2)}", content, count=1)


def normalise_public_url(value: str | None) -> str:
    """``--public-url`` as the export's base address, ending with ``/``, or ``""`` when unset.

    Raises ``ValueError`` unless *value* is an absolute http(s) address with no query or fragment.
    A trailing ``index.html`` is dropped, since the landing page is published as the folder's address.
    """
    value = (value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{value!r} is not an absolute http(s) address, such as https://example.org/report/")
    if parts.query or parts.fragment:
        raise ValueError(f"{value!r} must not carry a query (?…) or a fragment (#…)")
    path = parts.path
    if path.endswith("/" + LANDING_PAGE):
        path = path[: -len(LANDING_PAGE)]
    if not path.endswith("/"):
        path += "/"
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def page_url(public_url: str, page: str) -> str:
    """Public address of *page*: the folder's own address for the landing page."""
    return public_url if page == LANDING_PAGE else public_url + page


@dataclass(frozen=True)
class _Facts:
    """What the landing page's Dataset description says about the export, from its ``summary.json``."""

    nodes: int | None = None
    edges: int | None = None
    start: str | None = None
    end: str | None = None
    modified: str | None = None


def analysed_range(summary: dict[str, Any]) -> tuple[str | None, str | None]:
    """The period an export covers, as ISO days: each side is the requested bound (``--startdate`` /
    ``--enddate``) or, without one, the first / last day of the analysed messages. ``None`` = unknown."""
    options = summary.get("options") if isinstance(summary.get("options"), dict) else {}

    def day(value: Any) -> str | None:
        return value[:10] if isinstance(value, str) and value else None

    return (
        day(options.get("startdate")) or day(summary.get("first_message")),
        day(options.get("enddate")) or day(summary.get("last_message")),
    )


def _read_facts(root: str) -> _Facts:
    try:
        with open(os.path.join(root, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        return _Facts()
    if not isinstance(summary, dict):
        return _Facts()
    created = summary.get("created_at")
    start, end = analysed_range(summary)
    return _Facts(
        nodes=summary.get("nodes") if isinstance(summary.get("nodes"), int) else None,
        edges=summary.get("edges") if isinstance(summary.get("edges"), int) else None,
        start=start,
        end=end,
        modified=created[:10] if isinstance(created, str) and created else None,
    )


def _landing_description(facts: _Facts) -> str:
    if facts.nodes:
        subject = f"An analysis of {facts.nodes:,} Telegram channels"
        if facts.edges:
            subject += f" and the {facts.edges:,} citation ties between them"
    else:
        subject = "An analysis of a network of Telegram channels"
    if facts.start and facts.end:
        subject += f", from {facts.start} to {facts.end}"
    elif facts.start:
        subject += f", from {facts.start}"
    elif facts.end:
        subject += f", up to {facts.end}"
    return subject + ": interactive maps, channel and community statistics, and the data behind them."


def _linked_pages(root: str) -> set[str] | None:
    """Root pages the landing page links to, plus itself; ``None`` when there is no landing page."""
    try:
        with open(os.path.join(root, LANDING_PAGE), encoding="utf-8") as f:
            landing = f.read()
    except OSError:
        return None
    return {LANDING_PAGE, *_PAGE_LINK_RE.findall(landing)}


def _downloads(root: str) -> list[str]:
    return sorted(
        name
        for name in os.listdir(root)
        if not name.startswith(".")
        and os.path.splitext(name)[1].lower() in DOWNLOAD_TYPES
        and os.path.isfile(os.path.join(root, name))
    )


def _json_ld(data: dict[str, Any]) -> str:
    # "</" escaped so a project title holding "</script>" cannot close the element early.
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _dataset_ld(title: str, description: str, url: str, facts: _Facts, downloads: list[str]) -> dict[str, Any]:
    if len(description) < DATASET_MIN_DESCRIPTION:
        description = f"{description.rstrip('.')}. {_landing_description(facts)}".lstrip(". ")
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": title,
        "description": description,
        "keywords": list(DATASET_KEYWORDS),
        "isAccessibleForFree": True,
    }
    if url:
        data["url"] = url
    if facts.modified:
        data["dateModified"] = facts.modified
    if facts.start or facts.end:
        data["temporalCoverage"] = f"{facts.start or '..'}/{facts.end or '..'}"
    if downloads:
        data["distribution"] = [
            {
                "@type": "DataDownload",
                "name": name,
                "encodingFormat": DOWNLOAD_TYPES[os.path.splitext(name)[1].lower()],
                "contentUrl": (url or "") + name,
            }
            for name in downloads
        ]
    return data


def _breadcrumb_ld(site_name: str, public_url: str, page_name: str, url: str) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": site_name or "Network analysis", "item": public_url},
            {"@type": "ListItem", "position": 2, "name": page_name, "item": url},
        ],
    }


def _head_block(
    page: str,
    head: str,
    *,
    seo: bool,
    listed: bool,
    public_url: str,
    site_name: str,
    facts: _Facts,
    downloads: list[str],
) -> list[str]:
    """The policy's head tags for *page*, whose ``<head>`` (owned tags already stripped) is *head*."""
    if not seo:
        return [
            f'<meta name="robots" content="{PRIVATE_ROBOTS}">',
            '<meta name="tdm-reservation" content="1">',
            '<meta name="referrer" content="no-referrer">',
        ]
    if not listed:
        return [f'<meta name="robots" content="{UNLISTED_ROBOTS}">']

    esc = html.escape
    title_match = _TITLE_RE.search(head)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    own_description = _DESCRIPTION_RE.search(head)
    description = html.unescape(own_description.group(1)).strip() if own_description else ""
    lines = [f'<meta name="robots" content="{INDEX_ROBOTS}">']
    if not description:
        description = _landing_description(facts) if page == LANDING_PAGE else page_description(page)
        if description:
            lines.append(f'<meta name="description" content="{esc(description)}">')
    url = page_url(public_url, page) if public_url else ""
    if url:
        lines.append(f'<link rel="canonical" href="{esc(url)}">')
    lines.append('<meta property="og:type" content="website">')
    if site_name:
        lines.append(f'<meta property="og:site_name" content="{esc(site_name)}">')
    if title:
        lines.append(f'<meta property="og:title" content="{esc(title)}">')
    if description:
        lines.append(f'<meta property="og:description" content="{esc(description)}">')
    if url:
        lines.append(f'<meta property="og:url" content="{esc(url)}">')
    lines.append('<meta name="twitter:card" content="summary">')
    if title:
        lines.append(f'<meta name="twitter:title" content="{esc(title)}">')
    if description:
        lines.append(f'<meta name="twitter:description" content="{esc(description)}">')
    if page == LANDING_PAGE:
        ld = _dataset_ld(title or site_name or "Network analysis", description, url, facts, downloads)
    elif url:
        prefix = f"{site_name} | "
        page_name = title[len(prefix) :] if site_name and title.startswith(prefix) else title
        ld = _breadcrumb_ld(site_name, public_url, page_name or page, url)
    else:
        ld = None
    if ld is not None:
        lines.append(f'<script type="application/ld+json">{_json_ld(ld)}</script>')
    return lines


def apply_to_page(
    content: str,
    page: str,
    *,
    seo: bool,
    listed: bool = True,
    public_url: str = "",
    site_name: str = "",
    facts: _Facts | None = None,
    downloads: list[str] | None = None,
) -> str:
    """*content*, the HTML of the export page *page*, with its head tags set to the policy.

    Idempotent: the block a previous call inserted, and every policy-owned tag a template wrote (robots,
    referrer, TDM reservation, canonical, Open Graph, Twitter), are removed before the new block goes in,
    right after the ``<title>``. A description the page wrote itself is kept.
    """
    head_end = content.lower().find("</head>")
    if head_end == -1:
        return content
    head, rest = content[:head_end], content[head_end:]
    head = _OWNED_TAG_RE.sub("", _BLOCK_RE.sub("", head))
    lines = _head_block(
        page,
        head,
        seo=seo,
        listed=listed,
        public_url=public_url,
        site_name=site_name,
        facts=facts or _Facts(),
        downloads=downloads or [],
    )
    block = "\n".join(f"  {line}" for line in (_BLOCK_START, *lines, _BLOCK_END))
    title = _TITLE_RE.search(head)
    if title:
        at = title.end()
    else:
        head_tag = re.search(r"<head[^>]*>", head, re.I)
        at = head_tag.end() if head_tag else 0
    return head[:at] + "\n" + block + head[at:] + rest


def _robots_txt(seo: bool, sitemap_url: str) -> str:
    subfolder = (
        "# Crawlers read robots.txt only at the root of a site: when this export sits in a subfolder,\n"
        "# copy these rules into the site's own robots.txt (prefixing the folder to each path)."
    )
    if seo:
        lines = [f"# {SITE_FILE_MARK} (export with --seo): every crawler is welcome.", subfolder]
        lines += ["User-agent: *", "Allow: /"]
        if sitemap_url:
            lines += ["", f"Sitemap: {sitemap_url}"]
    else:
        lines = [
            f"# {SITE_FILE_MARK} (export without --seo): no crawler is welcome, and the AI crawlers",
            "# are also named one by one.",
            subfolder,
        ]
        lines += [f"User-agent: {agent}" for agent in (*AI_USER_AGENTS, *AI_ROBOTS_TOKENS)]
        lines += ["Disallow: /", "", "User-agent: *", "Disallow: /"]
    return "\n".join(lines) + "\n"


def _htaccess() -> str:
    agents = "|".join(re.escape(agent) for agent in AI_USER_AGENTS)
    return (
        "\n".join(
            (
                f"# {SITE_FILE_MARK} (export without --seo): keep this folder out of search engines and AI crawlers.",
                "# Apache reads it where AllowOverride allows FileInfo. If the server answers 500 Internal Server",
                "# Error once the folder is uploaded, the host does not allow these settings: delete this file.",
                "<IfModule mod_headers.c>",
                f'  Header always set X-Robots-Tag "{PRIVATE_ROBOTS}"',
                '  Header always set tdm-reservation "1"',
                '  Header always set Referrer-Policy "no-referrer"',
                "</IfModule>",
                "# AI crawlers get 403 Forbidden for everything but robots.txt.",
                "<IfModule mod_rewrite.c>",
                "  RewriteEngine On",
                "  RewriteCond %{REQUEST_URI} !/robots\\.txt$",
                f"  RewriteCond %{{HTTP_USER_AGENT}} ({agents}) [NC]",
                "  RewriteRule ^ - [F]",
                "</IfModule>",
            )
        )
        + "\n"
    )


def _headers_file() -> str:
    return (
        "\n".join(
            (
                f"# {SITE_FILE_MARK} (export without --seo): response headers for Netlify and Cloudflare Pages,",
                "# read from the root of the published site.",
                "/*",
                f"  X-Robots-Tag: {PRIVATE_ROBOTS}",
                "  tdm-reservation: 1",
                "  Referrer-Policy: no-referrer",
            )
        )
        + "\n"
    )


def _sitemap_xml(public_url: str, pages: list[str], lastmod: str | None) -> str:
    ordered = sorted(pages, key=lambda p: (p != LANDING_PAGE, p))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- {SITE_FILE_MARK} (export with --seo) -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for page in ordered:
        lines.append("  <url>")
        lines.append(f"    <loc>{html.escape(page_url(public_url, page))}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _is_ours(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            return SITE_FILE_MARK in f.read(512)
    except (OSError, UnicodeDecodeError):
        return False


def _write(root: str, name: str, content: str) -> None:
    with open(os.path.join(root, name), "w", encoding="utf-8") as f:
        f.write(content)


def publish(root: str, *, seo: bool, public_url: str = "", site_name: str = "") -> list[str]:
    """Apply the publication policy to the export folder *root*; return the server files written.

    Rewrites the head of every page at the folder's root (:func:`apply_to_page`), then writes
    ``robots.txt`` and either ``sitemap.xml`` (search-optimised, given *public_url*) or ``.htaccess``
    and ``_headers`` (private). The other policy's files are deleted when they are ours (they carry
    :data:`SITE_FILE_MARK`), so ``compare_analysis`` can switch an export from one policy to the other.
    *public_url* is :func:`normalise_public_url`'s output, *site_name* the project title.
    """
    if not os.path.isdir(root):
        return []
    facts = _read_facts(root)
    downloads = _downloads(root)
    linked = _linked_pages(root)
    pages = sorted(
        name for name in os.listdir(root) if name.endswith(".html") and os.path.isfile(os.path.join(root, name))
    )
    listed_pages: list[str] = []
    for page in pages:
        listed = linked is None or page in linked
        path = os.path.join(root, page)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        updated = apply_to_page(
            content,
            page,
            seo=seo,
            listed=listed,
            public_url=public_url,
            site_name=site_name,
            facts=facts,
            downloads=downloads,
        )
        if updated != content:
            _write(root, page, updated)
        if seo and listed:
            listed_pages.append(page)

    lastmod = facts.modified or datetime.date.today().isoformat()
    sitemap_url = public_url + SITEMAP_XML if seo and public_url and listed_pages else ""
    written = [ROBOTS_TXT]
    _write(root, ROBOTS_TXT, _robots_txt(seo, sitemap_url))
    if seo:
        stale = (HTACCESS, HEADERS_FILE)
        if sitemap_url:
            _write(root, SITEMAP_XML, _sitemap_xml(public_url, listed_pages, lastmod))
            written.append(SITEMAP_XML)
        else:
            stale += (SITEMAP_XML,)
    else:
        stale = (SITEMAP_XML,)
        _write(root, HTACCESS, _htaccess())
        _write(root, HEADERS_FILE, _headers_file())
        written += [HTACCESS, HEADERS_FILE]
    for name in stale:
        path = os.path.join(root, name)
        if os.path.isfile(path) and _is_ours(path):
            os.remove(path)
    return written
