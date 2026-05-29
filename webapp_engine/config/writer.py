"""Write user-saved `.operations-{stem}-{timestamp}` snapshots.

`tomlkit` is used (rather than the stdlib `tomllib` plus a hand-rolled writer)
because it preserves user comments and section ordering when an analyst
hand-edits a snapshot. Each save always creates a NEW file — the bare
`.operations-{stem}` baseline ("Pulpit defaults") is read-only via this API.

Public API:
    save_named(task, payload, title) -> dict   # metadata for the new file

`payload` is a nested dict matching the schema (e.g. ``{"telegram": {"connection_retries": 20}}``).
The function fills in any schema-defined defaults the payload omits, wraps a
`[meta]` block with `title`, `pulpit_version`, and `generated_at`, and writes
atomically.
"""

import datetime as _dt
import os

from .defaults import CRAWL_DEFAULTS, STRUCTURAL_DEFAULTS
from .loader import get_app_version
from .paths import CONFIG_DIR, TASK_STEMS
from .schema import (
    CRAWL_HEADER_COMMENT,
    CRAWL_SECTIONS,
    META_GENERATED_AT_KEY,
    META_SECTION,
    META_TITLE_KEY,
    META_VERSION_KEY,
    STRUCTURAL_HEADER_COMMENT,
    STRUCTURAL_SECTIONS,
)

import tomlkit
from tomlkit import TOMLDocument, comment, document, nl, table

_TASK_CONFIG = {
    "crawl_channels": (CRAWL_DEFAULTS, CRAWL_SECTIONS, CRAWL_HEADER_COMMENT),
    "structural_analysis": (STRUCTURAL_DEFAULTS, STRUCTURAL_SECTIONS, STRUCTURAL_HEADER_COMMENT),
}


def save_named(task: str, payload: dict, title: str) -> dict:
    """Write a new timestamped snapshot for `task` and return metadata.

    Raises ValueError on unknown task or empty title.
    """
    if task not in _TASK_CONFIG:
        raise ValueError(f"Unknown task: {task!r}")
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")

    defaults, sections, header = _TASK_CONFIG[task]
    stem = TASK_STEMS[task]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Snapshot IDs are second-precision UTC. If two saves arrive in the same
    # second (rapid double-click) the second would silently overwrite the
    # first; advance the timestamp until we find a free filename.
    now = _dt.datetime.now(_dt.UTC).replace(microsecond=0)
    while True:
        snapshot_id = now.strftime("%Y-%m-%dT%H-%M-%SZ")
        iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        filename = f"{stem}-{snapshot_id}"
        path = CONFIG_DIR / filename
        if not path.exists():
            break
        now += _dt.timedelta(seconds=1)

    doc = _build_document(defaults, sections, header, title=title, version=get_app_version(), iso=iso)
    _overlay_payload(doc, payload)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp_path, path)

    return {
        "id": snapshot_id,
        "filename": filename,
        "title": title,
        "pulpit_version": get_app_version(),
        "generated_at_iso": iso,
        "generated_at_human": now.strftime("%Y-%m-%d %H:%M UTC"),
        "is_base": False,
    }


# Sentinel used by tests/migrations that need to (re)write the bare baseline
# file. Not exposed through the Operations panel — the panel can only create
# timestamped sidecars.
def write_baseline(task: str, payload: dict, title: str = "Pulpit defaults") -> None:
    """Overwrite the bare `.operations-{stem}` baseline. Not used by the panel."""
    if task not in _TASK_CONFIG:
        raise ValueError(f"Unknown task: {task!r}")
    defaults, sections, header = _TASK_CONFIG[task]
    path = CONFIG_DIR / TASK_STEMS[task]
    iso = _dt.datetime.now(_dt.UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = _build_document(defaults, sections, header, title=title, version=get_app_version(), iso=iso)
    _overlay_payload(doc, payload)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp_path, path)


def _build_document(
    defaults: dict, sections: tuple[str, ...], header: str, *, title: str, version: str, iso: str
) -> TOMLDocument:
    doc = document()
    for line in header.splitlines():
        doc.add(comment(line))
    doc.add(nl())
    meta = table()
    meta[META_TITLE_KEY] = title
    meta[META_VERSION_KEY] = version
    meta[META_GENERATED_AT_KEY] = iso
    doc[META_SECTION] = meta
    for section in sections:
        if section not in defaults:
            continue
        t = table()
        for key, value in defaults[section].items():
            t[key] = value
        doc[section] = t
    return doc


def _overlay_payload(doc: TOMLDocument, payload: dict) -> None:
    for section, fields in (payload or {}).items():
        if not isinstance(fields, dict):
            continue
        if section not in doc:
            doc[section] = table()
        for key, value in fields.items():
            doc[section][key] = value


# Reserved id constants kept here so views can avoid magic strings.
__all__ = ["save_named", "write_baseline"]
