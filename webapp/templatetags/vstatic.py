"""Modification-time-versioned static URLs.

``{% vstatic 'app/js/file.js' %}`` renders the same URL as ``{% static %}``
plus a ``?v=<mtime>`` query string. Browsers heuristically cache static
responses (the dev server sends ``Last-Modified`` but no ``Cache-Control``),
so after a code edit or a Pulpit upgrade the UI could keep executing a stale
cached script until a hard refresh; the version query turns every changed
file into a new URL, making a plain reload always pick up current assets.

The mtime is looked up on every render under ``DEBUG`` (edits show up
immediately) and once per process otherwise.
"""

import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static as static_url

register = template.Library()

_versions: dict[str, str | None] = {}


def _version(path: str) -> str | None:
    if not settings.DEBUG and path in _versions:
        return _versions[path]
    absolute = finders.find(path)
    version = str(int(os.path.getmtime(absolute))) if absolute else None
    _versions[path] = version
    return version


@register.simple_tag
def vstatic(path: str) -> str:
    url = static_url(path)
    version = _version(path)
    return f"{url}?v={version}" if version else url
