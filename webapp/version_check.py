"""Check whether a newer Pulpit release exists upstream.

Pulpit is upgraded with ``git pull``; nothing tells the operator a new release
has landed. This module fetches the project's own ``.system`` file from the
GitHub default branch — the same file (and the same ``APP_VERSION`` line) the
running instance reads locally — and compares versions. The result feeds the
``/version/check/`` endpoint, which the web UI polls to light up the "update
available" dots on the Manage button / Maintenance menu and the banner on the
Maintenance page.

Design notes:
  * The network read is cached in the shared ``FileBasedCache`` (see
    :mod:`webapp.cache`) so GitHub is contacted at most once a day across the
    webserver and management-command processes.
  * Everything fails open: any network or parse error yields "no update", never
    an exception in the request path, so offline / air-gapped / white-labelled
    deployments are unaffected.
  * Only ``github.com`` repositories are supported; a non-GitHub
    ``REPOSITORY_URL`` simply disables the check.
"""

from __future__ import annotations

import re
import urllib.request
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

from webapp_engine.config.loader import parse_app_version

# The upstream lookup is cached: a successful read for a day, an empty/failed
# read for an hour — long enough not to hammer GitHub on an outage, short enough
# not to suppress the check for a whole day after a transient failure.
VERSION_CACHE_KEY = "pulpit:version:latest"
_SUCCESS_TTL = 24 * 60 * 60
_FAILURE_TTL = 60 * 60

_FETCH_TIMEOUT = 3  # seconds; keep the endpoint snappy even on a cold cache
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)")


def _raw_system_urls() -> list[str]:
    """Return candidate raw-`.system` URLs for the configured GitHub repo.

    ``raw.githubusercontent.com`` needs an explicit branch ref (it does not
    resolve ``HEAD``), so try ``main`` then ``master``. Returns ``[]`` when
    ``REPOSITORY_URL`` is not a github.com URL, which disables the check.
    """
    repo_url = getattr(settings, "REPOSITORY_URL", "") or ""
    parsed = urlparse(repo_url)
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return []
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return []
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return [f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/.system" for branch in ("main", "master")]


def _fetch_latest_version() -> str | None:
    """Fetch and parse APP_VERSION from the upstream `.system`; None on any error."""
    for url in _raw_system_urls():
        try:
            with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    continue
                text = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue
        version = parse_app_version(text)
        if version:
            return version
    return None


def get_latest_version(force_refresh: bool = False) -> str | None:
    """Return the cached upstream version, fetching on a cold or expired cache.

    With ``force_refresh`` the cached value is ignored and GitHub is contacted
    again, but the fresh result is still written back to the shared cache — so
    the Maintenance "Check for updates" button both answers immediately and
    refreshes the day-cache that the attention dots and banner read from.
    """
    if not force_refresh:
        cached = cache.get(VERSION_CACHE_KEY)
        if cached is not None:
            return cached.get("latest")
    latest = _fetch_latest_version()
    cache.set(VERSION_CACHE_KEY, {"latest": latest}, _SUCCESS_TTL if latest else _FAILURE_TTL)
    return latest


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.match(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def compare_versions(current: str, latest: str) -> bool:
    """Return True iff ``latest`` is numerically newer than ``current``.

    Both are normalised to their leading dotted-integer prefix, so pre-release
    suffixes are ignored (``"0.22dev"`` -> ``(0, 22)``); a dev build therefore
    never nags about its own release number. Unparsable input -> False.
    """
    cur = _version_tuple(current)
    new = _version_tuple(latest)
    if cur is None or new is None:
        return False
    length = max(len(cur), len(new))
    cur += (0,) * (length - len(cur))
    new += (0,) * (length - len(new))
    return new > cur


def version_status(force_refresh: bool = False) -> dict:
    """Build the payload served by the ``/version/check/`` endpoint.

    ``force_refresh`` is threaded through to bypass the day-cache for an
    explicit, operator-initiated check (see :func:`get_latest_version`).
    """
    current = getattr(settings, "APP_VERSION", "") or ""
    latest = get_latest_version(force_refresh=force_refresh)
    return {
        "current": current,
        "latest": latest,
        "update_available": bool(latest) and compare_versions(current, latest),
        "repository_url": getattr(settings, "REPOSITORY_URL", "") or "",
    }
