"""Hard-coded defaults for the two `.operations-*` TOML files.

These dicts are the single source of truth. The loader merges file content on
top of them, and the writer uses them to bootstrap a fresh file when a "Save
as defaults" click happens with no existing file on disk.

When adding a new option:
    1. Add the key + default value here, under the matching section.
    2. Wire it through `webapp_engine/settings.py` (read from `_crawl` or
       `_structural` and expose under the existing Django setting name).
    3. If the Operations panel surfaces it, add an entry to
       `TASK_DEFAULT_SPECS` in `runner/views.py` so "Save as defaults"
       persists it.
"""

CRAWL_DEFAULTS: dict = {
    # Note: Telegram client tuning (session_name, connection_retries, etc.) used
    # to live in a [telegram] block here. It now lives in `.env` — these are
    # deployment infrastructure knobs, not per-run analysis options.
    "downloads": {
        "images": False,
        "video": False,
        "audio": False,
        "stickers": False,
        "other_media": False,
    },
    "scope": {
        "channel_types": ["CHANNEL"],
    },
    "channels": {
        "get_channels_info": False,
        "update_type_excluded_info": False,
        "mine_about_texts": False,
        "fetch_recommended": False,
        "retry_lost_and_private": False,
    },
    "messages": {
        "get_new_messages": False,
        "fetch_replies": False,
        "refresh_messages_stats": False,
        "fix_holes": False,
        "fix_missing_media": False,
        "retry_lost_messages": False,
        "retry_references": False,
        "force_retry_unresolved_references": False,
    },
    "degrees": {
        "in_degrees": False,
        "out_degrees": False,
    },
}


STRUCTURAL_DEFAULTS: dict = {
    # All entries here represent a "factory empty" baseline: a bare
    # `python manage.py structural_analysis` with no flags must do nothing.
    # Tuning constants that only matter when an opt-in feature is enabled
    # (leiden resolutions, mcl inflation, spreading runs, vacancy windows,
    # robustness numerics, dead_leaves_color, output_dir) keep sensible
    # values — they're never consulted when no flag selects the feature
    # that needs them.
    "graph": {
        "dead_leaves_color": "#596a64",
        "community_palette": "",
        "community_palette_reversed": False,
        "output_dir": "graph",
    },
    "outputs": {
        "graph": False,
        "graph_3d": False,
        "html": False,
        "xlsx": False,
        "gexf": False,
        "graphml": False,
        "csv": False,
        "seo": False,
        "vertical_layout": False,
        "structural_similarity": False,
        "behavioural_equivalence": False,
        "consensus_matrix": False,
        "draw_dead_leaves": False,
        "timeline_step": "none",
    },
    "edges": {
        "weight_strategy": "",
        "include_mentions": False,
        "include_self_references": False,
    },
    "scope": {
        "include_lost": False,
        "include_private": False,
    },
    "computation": {
        "fa2_iterations": "",
        "community_distribution_threshold": 0,
        "leiden_coarse_resolution": 0.01,
        "leiden_fine_resolution": 0.05,
        "mcl_inflation": 2.0,
        "spreading_runs": 200,
        "diffusion_window": 30,
    },
    "layouts": {
        "layouts_2d": [],
        "layouts_3d": [],
    },
    "measures": {
        "selected": [],
        "bridging_basis": "",
    },
    "communities": {
        "strategies": [],
    },
    "network_stats": {
        "groups": [],
    },
    "vacancy": {
        "measures": [],
        "months_before": 12,
        "months_after": 24,
        "max_candidates": 30,
        "ppr_alpha": 0.85,
    },
    "robustness": {
        # `enabled` is intentionally absent — it is derived from `bool(strategies)`
        # in settings.py. A separate file-level switch would drift from the
        # strategy list, since the Operations panel has no separate enable knob.
        # `strategies` defaults to [] so the built-in defaults represent a clean
        # "nothing configured" baseline (consistent with outputs.* / scope.* defaults).
        # The bundled .operations-structural baseline supplies an opinionated list.
        "alpha": 0.05,
        "strategies": [],
        "runs": 100,
        "null": 20,
        "seed": 42,
        "sample": 500,
    },
    "interest": {
        # Per-message structural reach (C + D). The hot layer (z-scored
        # engagement) is computed at crawl time and is not configurable here.
        "structural": False,
        "window_days": 30,
        "include_mentions": False,
    },
}
