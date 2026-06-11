"""Read `.operations-crawl` / `.operations-structural` (plus user-saved snapshots) and merge with defaults.

The loader is intentionally tiny: it parses the TOML, strips the `[meta]`
header section, deep-merges the rest over the hard-coded `CRAWL_DEFAULTS` /
`STRUCTURAL_DEFAULTS`, and returns a nested `SimpleNamespace` for attribute
access (`_crawl.channels.get_channels_info`).

The bare files (`.operations-{crawl,structural}`) are the committed "Pulpit
default" baselines used at startup and by the management commands. The
Operations panel can additionally save timestamped sidecars
(`.operations-{stem}-{timestamp}`) that users name through a modal — the
listing and load helpers here power the picker in that modal.

When a file is missing or malformed, the defaults are returned unchanged —
the crawler and structural-analysis commands stay runnable without either
file existing on disk.
"""

import datetime as _dt
import logging
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

from .defaults import CRAWL_DEFAULTS, STRUCTURAL_DEFAULTS
from .paths import CONFIG_DIR, CRAWL_PATH, STRUCTURAL_PATH, SYSTEM_PATH, TASK_STEMS
from .schema import (
    GENERATED_AT_KEY,
    META_GENERATED_AT_KEY,
    META_SECTION,
    META_TITLE_KEY,
    META_VERSION_KEY,
    PULPIT_VERSION_KEY,
)

logger = logging.getLogger(__name__)

BASE_ID = "base"
# UTC ISO-style timestamp with `:` replaced by `-` so the filename is safe on
# every filesystem and routable in a Django `<str:id>` URL path.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


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


def _strip_header(parsed: dict) -> dict:
    """Remove the `[meta]` section plus legacy top-level header keys.

    The user-facing payload is just the data sections; the meta is informational
    and never deep-merged into the live settings.
    """
    parsed.pop(META_SECTION, None)
    # Legacy: pre-[meta] files stored these at the top level.
    parsed.pop(PULPIT_VERSION_KEY, None)
    parsed.pop(GENERATED_AT_KEY, None)
    # Legacy: pre-`.env`-migration files carried a [telegram] block that's now
    # owned by `.env`. Drop it silently so old snapshots still load — the values
    # are obsolete here and would otherwise warn on each parse.
    parsed.pop("telegram", None)
    return parsed


# Section.key → modern Section.key. Files written by older Pulpit releases (or
# hand-edited from old docs) carry the legacy spellings; we translate them
# silently on read so analysts don't have to migrate by hand. The writer always
# emits the modern names, so re-saving an old file upgrades it in place.
_LEGACY_TOML_KEY_RENAMES: dict[str, str] = {
    "messages.fixholes": "messages.fix_holes",
    "messages.force_retry_unresolved": "messages.force_retry_unresolved_references",
    "layouts.two_d": "layouts.layouts_2d",
    "layouts.three_d": "layouts.layouts_3d",
}


def _migrate_legacy_keys(parsed: dict) -> dict:
    for legacy, modern in _LEGACY_TOML_KEY_RENAMES.items():
        l_section, l_key = legacy.split(".", 1)
        m_section, m_key = modern.split(".", 1)
        legacy_table = parsed.get(l_section)
        if not isinstance(legacy_table, dict) or l_key not in legacy_table:
            continue
        modern_table = parsed.setdefault(m_section, {})
        # Modern key wins if both are present (e.g. partial mid-migration files).
        modern_table.setdefault(m_key, legacy_table[l_key])
        del legacy_table[l_key]
    return parsed


# Measure tokens and robustness attack strategies removed in v0.26 (the path/flow/brokerage
# family). An old config may still name them in ``measures.selected`` / ``robustness.strategies``
# or carry the now-defunct ``*.bridging_basis`` / ``computation.spreading_runs`` keys.
_DROPPED_MEASURE_TOKENS: frozenset[str] = frozenset(
    {
        "BETWEENNESS",
        "HARMONICCENTRALITY",
        "CORENESS",
        "COLLECTIVEINFLUENCE",
        "TROPHICLEVEL",
        "BROKERAGEROLES",
        "SPREADING",
        "BRIDGINGCENTRALITY",
        "BRIDGING",
    }
)
_DROPPED_ATTACK_STRATEGIES: frozenset[str] = frozenset(
    {"harmonic", "betweenness", "betweenness_dyn", "bridging", "spreading"}
)
# Flow / random-walk community strategies removed in v0.26 (same one-degree rationale as the
# measures). An old config may still name them in ``communities.strategies``.
_DROPPED_COMMUNITY_STRATEGIES: frozenset[str] = frozenset({"INFOMAP", "INFOMAP_MEMORY", "MCL", "WALKTRAP", "STRONGCC"})


def _token_base(token: object) -> str:
    """The token name with any ``(params)`` suffix stripped (e.g. ``SPREADING(runs=2000)`` → ``SPREADING``)."""
    return str(token).strip().split("(", 1)[0].strip()


def _migrate_dropped_measures(parsed: dict) -> dict:
    """v0.25→v0.26: drop the removed path/flow/brokerage measures, attack strategies, and
    flow/random-walk community strategies.

    Strips the removed measure tokens from ``measures.selected``, the removed attack strategies
    from ``robustness.strategies``, and the removed community strategies from
    ``communities.strategies`` (all honouring an optional ``(params)`` suffix), and deletes the
    now-defunct ``measures.bridging_basis`` / ``robustness.bridging_basis`` /
    ``computation.spreading_runs`` keys. Idempotent: a current config has nothing to strip.
    """
    measures = parsed.get("measures")
    if isinstance(measures, dict):
        measures.pop("bridging_basis", None)
        selected = measures.get("selected")
        if isinstance(selected, list):
            measures["selected"] = [t for t in selected if _token_base(t).upper() not in _DROPPED_MEASURE_TOKENS]
    robustness = parsed.get("robustness")
    if isinstance(robustness, dict):
        robustness.pop("bridging_basis", None)
        strategies = robustness.get("strategies")
        if isinstance(strategies, list):
            robustness["strategies"] = [
                s for s in strategies if _token_base(s).lower() not in _DROPPED_ATTACK_STRATEGIES
            ]
    communities = parsed.get("communities")
    if isinstance(communities, dict):
        strategies = communities.get("strategies")
        if isinstance(strategies, list):
            communities["strategies"] = [
                s for s in strategies if _token_base(s).upper() not in _DROPPED_COMMUNITY_STRATEGIES
            ]
    computation = parsed.get("computation")
    if isinstance(computation, dict):
        computation.pop("spreading_runs", None)
    return parsed


def _migrate_community_params(parsed: dict) -> dict:
    """v0.24→v0.25: the fixed LEIDEN_CPM_COARSE / LEIDEN_CPM_FINE presets collapsed into one
    parameterised LEIDEN_CPM, and CPM resolution moved from ``[computation]`` into the per-instance
    strategy tokens. Convert an old config in place: each preset becomes ``LEIDEN_CPM(resolution=<its
    γ>)``; the now-defunct ``[computation]`` keys are dropped (MCL was removed in v0.26, so its old
    ``mcl_inflation`` key is just discarded). Gated on the presence of those keys so a current config
    is left untouched (idempotent).
    """
    communities = parsed.get("communities")
    computation = parsed.get("computation")
    if not isinstance(communities, dict) or not isinstance(computation, dict):
        return parsed
    coarse = computation.pop("leiden_coarse_resolution", None)
    fine = computation.pop("leiden_fine_resolution", None)
    inflation = computation.pop("mcl_inflation", None)
    if coarse is None and fine is None and inflation is None:
        return parsed  # already migrated / written by ≥0.25
    selected = communities.get("strategies")
    if isinstance(selected, list):
        converted: list = []
        for token in selected:
            name = str(token).strip().upper()
            if name == "LEIDEN_CPM_COARSE":
                converted.append(f"LEIDEN_CPM(resolution={coarse})" if coarse is not None else "LEIDEN_CPM")
            elif name == "LEIDEN_CPM_FINE":
                converted.append(f"LEIDEN_CPM(resolution={fine})" if fine is not None else "LEIDEN_CPM")
            else:
                converted.append(token)
        communities["strategies"] = converted
    return parsed


def _parse_toml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("failed to parse %s: %s", path, exc)
        return None


def _load(path: Path, defaults: dict, *, hermetic: bool) -> SimpleNamespace:
    if hermetic:
        return _to_namespace(defaults)
    parsed = _parse_toml(path)
    if parsed is None:
        return _to_namespace(defaults)
    _strip_header(parsed)
    _migrate_legacy_keys(parsed)
    _migrate_dropped_measures(parsed)
    _migrate_community_params(parsed)
    return _to_namespace(_deep_merge(defaults, parsed))


def _load_payload(path: Path, defaults: dict) -> dict | None:
    """Return the on-disk TOML deep-merged over defaults, or None if absent/malformed.

    Used by the Operations panel's "Load defaults" path, which needs to surface
    "file not present" to the client rather than silently substituting defaults.
    """
    parsed = _parse_toml(path)
    if parsed is None:
        return None
    _strip_header(parsed)
    _migrate_legacy_keys(parsed)
    _migrate_dropped_measures(parsed)
    _migrate_community_params(parsed)
    return _deep_merge(defaults, parsed)


def load_crawl_settings(*, hermetic: bool = False) -> SimpleNamespace:
    return _load(CRAWL_PATH, CRAWL_DEFAULTS, hermetic=hermetic)


def load_structural_settings(*, hermetic: bool = False) -> SimpleNamespace:
    return _load(STRUCTURAL_PATH, STRUCTURAL_DEFAULTS, hermetic=hermetic)


def _task_defaults(task: str) -> dict:
    return CRAWL_DEFAULTS if task == "crawl_channels" else STRUCTURAL_DEFAULTS


def _path_for_id(task: str, snapshot_id: str) -> Path:
    """Resolve `(task, id)` to an absolute path under CONFIG_DIR.

    `id` is either the literal "base" (→ bare `.operations-{stem}` file) or a
    timestamp matching `_TIMESTAMP_RE` (→ `.operations-{stem}-{id}` sidecar).
    Anything else returns a non-existing path so the caller's `.exists()`
    check produces the expected 404.
    """
    stem = TASK_STEMS[task]
    if snapshot_id == BASE_ID:
        return CONFIG_DIR / stem
    if _TIMESTAMP_RE.match(snapshot_id):
        return CONFIG_DIR / f"{stem}-{snapshot_id}"
    return CONFIG_DIR / f"__invalid__{snapshot_id}"


def _format_human(iso_str: str | None) -> str | None:
    """Render an ISO 8601 UTC timestamp (with or without separators) as
    `YYYY-MM-DD HH:MM UTC`. Returns None if the input is missing or unparseable —
    callers degrade to displaying just the title."""
    if not iso_str:
        return None
    if isinstance(iso_str, _dt.datetime):
        # tomllib parses an unquoted TOML datetime (a legal hand-edit of the
        # snapshot file) natively — there is no string to parse.
        dt = iso_str
    elif isinstance(iso_str, _dt.date):
        dt = _dt.datetime.combine(iso_str, _dt.time.min)
    else:
        try:
            dt = _dt.datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _id_to_iso(snapshot_id: str) -> str | None:
    """Convert a filename-id (`YYYY-MM-DDTHH-MM-SSZ`) back to ISO 8601."""
    if not _TIMESTAMP_RE.match(snapshot_id):
        return None
    # Replace the dashes that stand in for time-component colons.
    date, _, time = snapshot_id.partition("T")
    h, m, s = time[:-1].split("-")  # drop the trailing 'Z'
    return f"{date}T{h}:{m}:{s}Z"


def load_payload_by_id(task: str, snapshot_id: str) -> dict | None:
    """Return the form-shaped merged dict for a single snapshot, or None if absent."""
    if task not in TASK_STEMS:
        return None
    return _load_payload(_path_for_id(task, snapshot_id), _task_defaults(task))


def _read_meta(parsed: dict | None) -> dict:
    """Extract the `[meta]` block (or its legacy top-level equivalents)."""
    if not parsed:
        return {}
    meta = parsed.get(META_SECTION) or {}
    if not isinstance(meta, dict):
        meta = {}
    # Backfill from legacy top-level keys when the file predates `[meta]`.
    if META_VERSION_KEY not in meta and PULPIT_VERSION_KEY in parsed:
        meta[META_VERSION_KEY] = parsed[PULPIT_VERSION_KEY]
    if META_GENERATED_AT_KEY not in meta and GENERATED_AT_KEY in parsed:
        meta[META_GENERATED_AT_KEY] = parsed[GENERATED_AT_KEY]
    return meta


def list_defaults(task: str) -> list[dict]:
    """List the bare-baseline + every saved snapshot for `task`.

    Returns dicts shaped for the load-modal picker: ``id``, ``title``,
    ``pulpit_version``, ``generated_at_iso``, ``generated_at_human``, ``is_base``.
    Ordered: base first, then user snapshots by id descending (newest first —
    the id is a UTC timestamp, so lexicographic = chronological).
    """
    if task not in TASK_STEMS:
        return []
    stem = TASK_STEMS[task]
    out: list[dict] = []

    base_path = CONFIG_DIR / stem
    if base_path.exists():
        meta = _read_meta(_parse_toml(base_path))
        out.append(
            {
                "id": BASE_ID,
                "title": meta.get(META_TITLE_KEY) or "Pulpit defaults",
                "pulpit_version": meta.get(META_VERSION_KEY) or "",
                "generated_at_iso": meta.get(META_GENERATED_AT_KEY) or "",
                "generated_at_human": _format_human(meta.get(META_GENERATED_AT_KEY)),
                "is_base": True,
            }
        )

    saved: list[dict] = []
    if CONFIG_DIR.exists():
        prefix = f"{stem}-"
        for path in CONFIG_DIR.iterdir():
            if not path.is_file() or not path.name.startswith(prefix):
                continue
            snapshot_id = path.name[len(prefix) :]
            if not _TIMESTAMP_RE.match(snapshot_id):
                continue
            meta = _read_meta(_parse_toml(path))
            iso = meta.get(META_GENERATED_AT_KEY) or _id_to_iso(snapshot_id)
            saved.append(
                {
                    "id": snapshot_id,
                    "title": meta.get(META_TITLE_KEY) or "(untitled)",
                    "pulpit_version": meta.get(META_VERSION_KEY) or "",
                    "generated_at_iso": iso or "",
                    "generated_at_human": _format_human(iso),
                    "is_base": False,
                }
            )
    saved.sort(key=lambda d: d["id"], reverse=True)
    out.extend(saved)
    return out


def load_crawl_payload() -> dict | None:
    return _load_payload(CRAWL_PATH, CRAWL_DEFAULTS)


def load_structural_payload() -> dict | None:
    return _load_payload(STRUCTURAL_PATH, STRUCTURAL_DEFAULTS)


def read_pulpit_version(path: Path) -> str | None:
    """Return the `pulpit_version` field from a TOML file, or None if absent.

    Accepts both the new `[meta].pulpit_version` and the legacy top-level form
    so files written by older Pulpit releases still report a version.
    """
    parsed = _parse_toml(path)
    if parsed is None:
        return None
    return _read_meta(parsed).get(META_VERSION_KEY)


def parse_app_version(text: str) -> str | None:
    """Return the APP_VERSION value from `.system`-format text, or None if absent.

    Shared by :func:`get_app_version` (local file) and the upstream update check
    in :mod:`webapp.version_check` (remote `.system`), so the running version and
    the latest-available version can never be parsed differently.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "APP_VERSION":
            return value.strip().strip('"').strip("'")
    return None


def get_app_version() -> str:
    """Read APP_VERSION from `.system` without dragging Django settings in.

    The writer stamps the result into each TOML file's [meta] block so future
    migrations can compare against the running version.
    """
    if not SYSTEM_PATH.exists():
        return "unknown"
    try:
        version = parse_app_version(SYSTEM_PATH.read_text())
    except OSError:
        return "unknown"
    return version if version is not None else "unknown"
