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
    'Edit through the Operations panel ("Save as defaults") or directly here.\n'
    "Do not remove `pulpit_version`: future Pulpit releases use it to migrate\n"
    "the file in place when key names or sections change."
)

STRUCTURAL_HEADER_COMMENT = (
    "Pulpit operations defaults — structural analysis\n"
    'Edit through the Operations panel ("Save as defaults") or directly here.\n'
    "Do not remove `pulpit_version`: future Pulpit releases use it to migrate\n"
    "the file in place when key names or sections change."
)
