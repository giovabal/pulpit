"""Helpers for reading the most recent ``structural_analysis`` export.

The web views that ride on top of structural outputs (top-messages,
highlights) load JSON files from the latest published export on demand
rather than ingesting them back into the DB — see the plan in
``/home/jo/.claude/plans/i-want-to-implement-radiant-lovelace.md``,
§4.5 ("Surfacing read path").
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_EXPORTS_SUBDIR = "exports"


def latest_export_dir() -> Path | None:
    """Return the most recently modified directory under ``exports/`` whose
    ``summary.json`` exists (the marker of a fully published export, written
    last by ``structural_analysis``)."""
    root = Path(settings.BASE_DIR) / _EXPORTS_SUBDIR
    if not root.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        # Skip incomplete or backup directories.
        if entry.name.endswith(".tmp") or entry.name.endswith(".old"):
            continue
        if not (entry / "summary.json").is_file():
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, entry))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def latest_export_payload(filename: str) -> Any | None:
    """Load and decode a JSON file from the latest published export.

    Returns ``None`` if no export is published or the file is absent. Decode
    errors are logged once per call and treated as "absent" so a malformed
    file does not take down the views that consume it.
    """
    export_dir = latest_export_dir()
    if export_dir is None:
        return None
    path = export_dir / "data" / filename
    if not path.is_file():
        return None
    return _load_json_cached(str(path), path.stat().st_mtime)


@lru_cache(maxsize=8)
def _load_json_cached(path: str, _mtime: float) -> Any | None:
    """``_mtime`` is part of the cache key so a re-published export invalidates."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load export payload %s: %s", path, exc)
        return None
