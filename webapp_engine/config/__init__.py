"""Pulpit configuration loaders for `.operations-crawl` and `.operations-structural`.

These TOML files live under `configuration/` and hold the defaults that the
Operations panel and the `crawl_channels` / `structural_analysis` management
commands read at startup. Built-in defaults in `defaults.py` apply whenever a
file is missing or omits a key — so a fresh install runs without either file
needing to exist.
"""

from .defaults import CRAWL_DEFAULTS, STRUCTURAL_DEFAULTS
from .loader import (
    get_app_version,
    load_crawl_payload,
    load_crawl_settings,
    load_structural_payload,
    load_structural_settings,
    optional_int,
    read_pulpit_version,
)
from .paths import (
    BASE_DIR,
    CONFIG_DIR,
    CRAWL_PATH,
    ENV_PATH,
    STRUCTURAL_PATH,
    SYSTEM_PATH,
)
from .schema import (
    CRAWL_SECTIONS,
    GENERATED_AT_KEY,
    PULPIT_VERSION_KEY,
    STRUCTURAL_SECTIONS,
)
from .writer import save_crawl_settings, save_structural_settings

__all__ = [
    "BASE_DIR",
    "CONFIG_DIR",
    "CRAWL_DEFAULTS",
    "CRAWL_PATH",
    "CRAWL_SECTIONS",
    "ENV_PATH",
    "GENERATED_AT_KEY",
    "PULPIT_VERSION_KEY",
    "STRUCTURAL_DEFAULTS",
    "STRUCTURAL_PATH",
    "STRUCTURAL_SECTIONS",
    "SYSTEM_PATH",
    "get_app_version",
    "load_crawl_payload",
    "load_crawl_settings",
    "load_structural_payload",
    "load_structural_settings",
    "optional_int",
    "read_pulpit_version",
    "save_crawl_settings",
    "save_structural_settings",
]
