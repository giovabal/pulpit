"""Pulpit configuration loaders/writers for `.operations-crawl` / `.operations-structural`.

The committed bare files under `configuration/` carry the "Pulpit defaults"
baseline used at startup and by the management commands. Built-in defaults in
`defaults.py` apply whenever a file is missing or omits a key. The Operations
panel can additionally save timestamped sidecars (`.operations-{stem}-{ts}`)
that the user labels through a title modal.
"""

from .defaults import CRAWL_DEFAULTS, STRUCTURAL_DEFAULTS
from .loader import (
    BASE_ID,
    get_app_version,
    list_defaults,
    load_crawl_settings,
    load_payload_by_id,
    load_structural_settings,
    read_pulpit_version,
)
from .paths import (
    BASE_DIR,
    CONFIG_DIR,
    CRAWL_PATH,
    ENV_PATH,
    STRUCTURAL_PATH,
    SYSTEM_PATH,
    TASK_STEMS,
)
from .schema import (
    CRAWL_SECTIONS,
    GENERATED_AT_KEY,
    META_GENERATED_AT_KEY,
    META_SECTION,
    META_TITLE_KEY,
    META_VERSION_KEY,
    PULPIT_VERSION_KEY,
    STRUCTURAL_SECTIONS,
)
from .writer import save_named, write_baseline

__all__ = [
    "BASE_DIR",
    "BASE_ID",
    "CONFIG_DIR",
    "CRAWL_DEFAULTS",
    "CRAWL_PATH",
    "CRAWL_SECTIONS",
    "ENV_PATH",
    "GENERATED_AT_KEY",
    "META_GENERATED_AT_KEY",
    "META_SECTION",
    "META_TITLE_KEY",
    "META_VERSION_KEY",
    "PULPIT_VERSION_KEY",
    "STRUCTURAL_DEFAULTS",
    "STRUCTURAL_PATH",
    "STRUCTURAL_SECTIONS",
    "SYSTEM_PATH",
    "TASK_STEMS",
    "get_app_version",
    "list_defaults",
    "load_crawl_settings",
    "load_payload_by_id",
    "load_structural_settings",
    "read_pulpit_version",
    "save_named",
    "write_baseline",
]
