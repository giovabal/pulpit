"""Read `.operations-crawl` and `.operations-structural` and merge with defaults.

The loader is intentionally tiny: it parses the TOML, deep-merges over the
hard-coded `CRAWL_DEFAULTS` / `STRUCTURAL_DEFAULTS`, and returns a nested
`SimpleNamespace` for attribute access (`_crawl.telegram.connection_retries`).

When a file is missing or malformed, the defaults are returned unchanged — the
crawler and structural-analysis commands stay runnable without either file
existing on disk.
"""

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from .defaults import CRAWL_DEFAULTS, STRUCTURAL_DEFAULTS
from .paths import CRAWL_PATH, STRUCTURAL_PATH, SYSTEM_PATH
from .schema import GENERATED_AT_KEY, PULPIT_VERSION_KEY


def optional_int(value):
    """Normalise empty/blank/None/'none' to None; otherwise coerce to int.

    The "blank means None" sentinel is used by `SA_RECENCY_WEIGHTS` and any
    other knob that supports an "unset" state from the TOML side (TOML can't
    encode `None`).
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"none", ""}:
        return None
    return int(value)


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
    return value


def _load(path: Path, defaults: dict, *, hermetic: bool) -> SimpleNamespace:
    if hermetic or not path.exists():
        return _to_namespace(defaults)
    try:
        with path.open("rb") as fh:
            parsed = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        sys.stderr.write(f"[config] failed to parse {path}: {exc}; using built-in defaults\n")
        return _to_namespace(defaults)
    parsed.pop(PULPIT_VERSION_KEY, None)
    parsed.pop(GENERATED_AT_KEY, None)
    return _to_namespace(_deep_merge(defaults, parsed))


def _load_payload(path: Path, defaults: dict) -> dict | None:
    """Return the on-disk TOML deep-merged over defaults, or None if absent/malformed.

    Distinct from `_load` because the Operations panel's "Load defaults" path needs
    to surface "file not present" to the client, rather than silently substituting
    built-in defaults.
    """
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            parsed = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        sys.stderr.write(f"[config] failed to parse {path}: {exc}\n")
        return None
    parsed.pop(PULPIT_VERSION_KEY, None)
    parsed.pop(GENERATED_AT_KEY, None)
    return _deep_merge(defaults, parsed)


def load_crawl_settings(*, hermetic: bool = False) -> SimpleNamespace:
    return _load(CRAWL_PATH, CRAWL_DEFAULTS, hermetic=hermetic)


def load_structural_settings(*, hermetic: bool = False) -> SimpleNamespace:
    return _load(STRUCTURAL_PATH, STRUCTURAL_DEFAULTS, hermetic=hermetic)


def load_crawl_payload() -> dict | None:
    return _load_payload(CRAWL_PATH, CRAWL_DEFAULTS)


def load_structural_payload() -> dict | None:
    return _load_payload(STRUCTURAL_PATH, STRUCTURAL_DEFAULTS)


def read_pulpit_version(path: Path) -> str | None:
    """Return the `pulpit_version` field from a TOML file, or None if absent.

    Used by future Django data migrations that need to know which Pulpit
    release wrote the file and rewrite it in place when keys are renamed.
    """
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh).get(PULPIT_VERSION_KEY)
    except (tomllib.TOMLDecodeError, OSError):
        return None


def get_app_version() -> str:
    """Read APP_VERSION from `.system` without dragging Django settings in.

    The writer stamps the result into each TOML file's header so future
    migrations can compare against the running version.
    """
    if not SYSTEM_PATH.exists():
        return "unknown"
    try:
        for line in SYSTEM_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "APP_VERSION":
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return "unknown"
