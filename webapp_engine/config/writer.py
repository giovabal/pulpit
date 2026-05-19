"""Write `.operations-crawl` and `.operations-structural` from a nested payload.

`tomlkit` is used (rather than the stdlib `tomllib` plus a hand-rolled writer)
because it preserves user comments and section ordering across round-trips.
When the user manually edits a file to add a note to a field, clicking "Save
as defaults" later should not blow that note away.

Public API:
    save_crawl_settings(payload)
    save_structural_settings(payload)

`payload` is a nested dict matching the schema (e.g. `{"telegram": {"connection_retries": 20}}`).
Unspecified keys retain their existing on-disk values; the file is created
with full defaults from `defaults.py` on first write.
"""

import datetime as _dt
import os
from pathlib import Path

from .defaults import CRAWL_DEFAULTS, STRUCTURAL_DEFAULTS
from .loader import get_app_version
from .paths import CONFIG_DIR, CRAWL_PATH, STRUCTURAL_PATH
from .schema import (
    CRAWL_HEADER_COMMENT,
    CRAWL_SECTIONS,
    GENERATED_AT_KEY,
    PULPIT_VERSION_KEY,
    STRUCTURAL_HEADER_COMMENT,
    STRUCTURAL_SECTIONS,
)

import tomlkit
from tomlkit import TOMLDocument, comment, document, nl


def save_crawl_settings(payload: dict) -> None:
    _write(CRAWL_PATH, payload, CRAWL_DEFAULTS, CRAWL_SECTIONS, CRAWL_HEADER_COMMENT)


def save_structural_settings(payload: dict) -> None:
    _write(STRUCTURAL_PATH, payload, STRUCTURAL_DEFAULTS, STRUCTURAL_SECTIONS, STRUCTURAL_HEADER_COMMENT)


def _build_fresh_document(defaults: dict, sections: tuple[str, ...], header: str) -> TOMLDocument:
    doc = document()
    for line in header.splitlines():
        doc.add(comment(line))
    doc.add(nl())
    doc[PULPIT_VERSION_KEY] = get_app_version()
    doc[GENERATED_AT_KEY] = _now_iso()
    doc.add(nl())
    for section in sections:
        if section not in defaults:
            continue
        table = tomlkit.table()
        for key, value in defaults[section].items():
            table[key] = _to_toml_value(value)
        doc[section] = table
    return doc


def _write(
    path: Path,
    payload: dict,
    defaults: dict,
    sections: tuple[str, ...],
    header: str,
) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        except tomlkit.exceptions.TOMLKitError:
            doc = _build_fresh_document(defaults, sections, header)
    else:
        doc = _build_fresh_document(defaults, sections, header)

    # Refresh version + timestamp on every save so future migrations can
    # see when the file was last touched.
    doc[PULPIT_VERSION_KEY] = get_app_version()
    doc[GENERATED_AT_KEY] = _now_iso()

    for section, fields in payload.items():
        if not isinstance(fields, dict):
            continue
        if section not in doc:
            doc[section] = tomlkit.table()
        for key, value in fields.items():
            doc[section][key] = _to_toml_value(value)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp_path, path)


def _to_toml_value(value):
    # tomlkit accepts native Python booleans, ints, floats, strings, and lists
    # of those — but only via its own typed constructors when the surrounding
    # document was built fresh. For the dict-literal path we let tomlkit infer.
    return value


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
