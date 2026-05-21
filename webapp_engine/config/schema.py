META_SECTION = "meta"
META_TITLE_KEY = "title"
META_VERSION_KEY = "pulpit_version"
META_GENERATED_AT_KEY = "generated_at"

# Legacy top-level keys kept only so older on-disk files still parse cleanly.
PULPIT_VERSION_KEY = "pulpit_version"
GENERATED_AT_KEY = "generated_at"

CRAWL_SECTIONS: tuple[str, ...] = (
    "telegram",
    "downloads",
    "scope",
    "channels",
    "messages",
    "degrees",
)

STRUCTURAL_SECTIONS: tuple[str, ...] = (
    "graph",
    "outputs",
    "edges",
    "scope",
    "computation",
    "layouts",
    "measures",
    "communities",
    "network_stats",
    "vacancy",
    "robustness",
)

CRAWL_HEADER_COMMENT = (
    "Pulpit operations defaults — crawling\n"
    'Saved through the Operations panel ("Save as defaults") or hand-edited.\n'
    "The [meta] section's `title` and `pulpit_version` identify the snapshot;\n"
    "future Pulpit releases use `pulpit_version` to migrate the file in place."
)

STRUCTURAL_HEADER_COMMENT = (
    "Pulpit operations defaults — structural analysis\n"
    'Saved through the Operations panel ("Save as defaults") or hand-edited.\n'
    "The [meta] section's `title` and `pulpit_version` identify the snapshot;\n"
    "future Pulpit releases use `pulpit_version` to migrate the file in place."
)
