import argparse
import datetime
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Min

from network import community, community_stats, exporter, graph_builder, layout, measures, tables, vacancy_analysis
from network.graph_builder import VALID_EDGE_WEIGHT_STRATEGIES
from network.utils import GraphData
from webapp.models import Message
from webapp.utils.channel_types import VALID_CHANNEL_TYPES

import networkx as nx


def _parse_csv(value: str) -> list[str]:
    """Split a comma-separated string into a list of uppercase tokens."""
    return [s.strip().upper() for s in value.split(",") if s.strip()]


class Command(BaseCommand):
    args = ""
    help = "Build the network graph, compute measures, detect communities, and export output files."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--2dgraph",
            dest="graph",
            action="store_true",
            default=None,
            help="Generate the 2D interactive graph (graph.html and layout computation).",
        )
        parser.add_argument(
            "--3dgraph",
            dest="graph_3d",
            action="store_true",
            default=None,
            help="Also produce a 3D graph (graph3d.html). Slower on large graphs.",
        )
        parser.add_argument(
            "--html",
            dest="html",
            action="store_true",
            default=None,
            help="Generate HTML table output (channel_table.html, network_table.html, community_table.html).",
        )
        parser.add_argument(
            "--xlsx",
            dest="xlsx",
            action="store_true",
            default=None,
            help="Also produce Excel spreadsheet output (channel_table.xlsx, network_table.xlsx, community_table.xlsx).",
        )
        parser.add_argument(
            "--gexf",
            dest="gexf",
            action="store_true",
            default=None,
            help="Also write network.gexf with all computed measures embedded as node attributes.",
        )
        parser.add_argument(
            "--graphml",
            dest="graphml",
            action="store_true",
            default=None,
            help="Also write network.graphml with all computed measures embedded as node attributes.",
        )
        parser.add_argument(
            "--csv",
            dest="csv",
            action="store_true",
            default=None,
            help="Also write nodes.csv (one row per channel, same columns as channel_table.xlsx) and edges.csv (source_label, target_label, weight, weight_forwards, weight_mentions).",
        )
        parser.add_argument(
            "--seo",
            action="store_true",
            default=None,
            help=(
                "Optimise the output mini-site for search engine discovery: sets indexable robots tags "
                "and adds meta descriptions. Without this flag the output actively discourages indexing."
            ),
        )
        parser.add_argument(
            "--startdate",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only include messages on or after this date.",
        )
        parser.add_argument(
            "--enddate",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only include messages on or before this date.",
        )
        parser.add_argument(
            "--fa2-iterations",
            dest="fa2_iterations",
            type=int,
            default=None,
            metavar="N",
            help="Number of ForceAtlas2 iterations for the 2D and 3D layout. Default: 5000.",
        )
        parser.add_argument(
            "--vertical-layout",
            dest="vertical_layout",
            action="store_true",
            default=None,
            help=(
                "Orient the graph vertically. By default the layout is horizontal. "
                "When the computed aspect ratio does not match the chosen orientation the graph is rotated 90°."
            ),
        )
        parser.add_argument(
            "--2dlayouts",
            dest="layouts_2d",
            default=None,
            metavar="LAYOUTS",
            help=(
                "Comma-separated list of 2D layout algorithms to compute. "
                "When omitted, ForceAtlas2 (FA2) is computed as the only layout. "
                "The browser graph viewer offers a dropdown to switch between them at viewing time. "
                "Available: FA2, CIRCULAR, KAMADA_KAWAI, COMMUNITY_SHELL, TSNE, UMAP, HYPERBOLIC, ALL. Requires --2dgraph."
            ),
        )
        parser.add_argument(
            "--3dlayouts",
            dest="layouts_3d",
            default=None,
            metavar="LAYOUTS",
            help=(
                "Comma-separated list of 3D layout algorithms to compute. "
                "When omitted, ForceAtlas2 (FA2) is computed as the only layout. "
                "The 3D graph viewer offers a dropdown to switch between them at viewing time. "
                "Available: FA2, SPECTRAL, SPRING, KAMADA_KAWAI, TSNE, UMAP, ALL. Requires --3dgraph."
            ),
        )
        parser.add_argument(
            "--measures",
            dest="measures",
            default=None,
            metavar="MEASURES",
            help=(
                "Comma-separated list of centrality measures to compute. "
                "Available: PAGERANK, HITSHUB, HITSAUTH, BETWEENNESS, FLOWBETWEENNESS, INDEGCENTRALITY, "
                "OUTDEGCENTRALITY, HARMONICCENTRALITY, KATZ, SPREADING, BRIDGING or BRIDGING(STRATEGY), "
                "BURTCONSTRAINT, EGODENSITY, AMPLIFICATION, CONTENTORIGINALITY, ALL. Default: PAGERANK."
            ),
        )
        parser.add_argument(
            "--community-strategies",
            dest="community_strategies",
            default=None,
            metavar="STRATEGIES",
            help=(
                "Comma-separated list of community detection algorithms to apply. "
                "Available: ORGANIZATION, LEIDEN, LEIDEN_DIRECTED, LOUVAIN, KCORE, INFOMAP, ALL. "
                "Default: ORGANIZATION."
            ),
        )
        parser.add_argument(
            "--network-stat-groups",
            dest="network_stat_groups",
            default=None,
            metavar="GROUPS",
            help=(
                "Comma-separated list of whole-network stat groups to compute (requires --html, --xlsx, or "
                "--consensus-matrix). Available: SIZE, PATHS, COHESION, COMPONENTS, DEGCORRELATION, "
                "CENTRALIZATION, CONTENT, ALL. Default: ALL."
            ),
        )
        parser.add_argument(
            "--mentions",
            dest="include_mentions",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Include t.me/ mention references as edges alongside forwards (default: on). "
                "Use --no-mentions to build the graph from forwards only."
            ),
        )
        parser.add_argument(
            "--self-references",
            dest="include_self_references",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Include self-references (a channel forwarding from or mentioning itself) as "
                "self-loop edges in the graph (default: off). "
                "Only mention-based self-references are affected by --no-mentions."
            ),
        )
        parser.add_argument(
            "--edge-weight-strategy",
            dest="edge_weight_strategy",
            default=None,
            choices=sorted(VALID_EDGE_WEIGHT_STRATEGIES),
            metavar="STRATEGY",
            help=(
                "How edge weights are computed from forward and citation counts. "
                "NONE = all edges equal weight; TOTAL = raw count; "
                "PARTIAL_MESSAGES = count / total messages; "
                "PARTIAL_REFERENCES = count / forwarded-or-citing messages (default)."
            ),
        )
        parser.add_argument(
            "--recency-weights",
            dest="recency_weights",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Apply recency decay: messages up to N days old carry full weight; "
                "older messages decay as exp(-(age-N)/N). "
                "Omit to weight all messages equally."
            ),
        )
        parser.add_argument(
            "--spreading-runs",
            dest="spreading_runs",
            type=int,
            default=None,
            metavar="N",
            help="Number of Monte Carlo SIR simulations per node for the SPREADING measure. Default: 200.",
        )
        parser.add_argument(
            "--diffusion-window",
            dest="diffusion_window",
            type=int,
            default=None,
            metavar="DAYS",
            help=(
                "Reaction window in days for the DIFFUSIONLAG measure: only forwards within this many days of the "
                "original post are included. Use 0 to disable the window. Default: 30."
            ),
        )
        parser.add_argument(
            "--draw-dead-leaves",
            dest="draw_dead_leaves",
            action="store_true",
            default=None,
            help=(
                "Include non-interesting channels that are referenced by interesting ones as leaf nodes in the graph."
            ),
        )
        parser.add_argument(
            "--leiden-coarse-resolution",
            dest="leiden_coarse_resolution",
            type=float,
            default=None,
            metavar="γ",
            help=(
                "CPM resolution parameter for LEIDEN_CPM_COARSE. "
                "Communities form when their internal edge density exceeds γ. "
                "Lower values → fewer, larger communities. Default: 0.01."
            ),
        )
        parser.add_argument(
            "--leiden-fine-resolution",
            dest="leiden_fine_resolution",
            type=float,
            default=None,
            metavar="γ",
            help=(
                "CPM resolution parameter for LEIDEN_CPM_FINE. "
                "Communities form when their internal edge density exceeds γ. "
                "Higher values → more, smaller communities. Default: 0.05."
            ),
        )
        parser.add_argument(
            "--mcl-inflation",
            dest="mcl_inflation",
            type=float,
            default=None,
            metavar="r",
            help=(
                "Inflation parameter for Markov Clustering (MCL). "
                "Higher values → more, smaller communities. Typical range 1.5–4.0. Default: 2.0."
            ),
        )
        parser.add_argument(
            "--consensus-matrix",
            dest="consensus_matrix",
            action="store_true",
            default=None,
            help=(
                "Generate a consensus matrix page (consensus_matrix.html) showing how consistently "
                "each channel pair is co-clustered across all non-ORGANIZATION community detection strategies. "
                "Requires at least two non-ORGANIZATION strategies."
            ),
        )
        parser.add_argument(
            "--structural-similarity",
            dest="structural_similarity",
            action="store_true",
            default=None,
            help=(
                "Generate a structural similarity matrix page (structural_similarity.html) showing "
                "pairwise cosine similarity of per-channel feature vectors built from all computed "
                "network measures. Measures are min-max normalised per column; None values treated as 0."
            ),
        )
        parser.add_argument(
            "--community-distribution-threshold",
            dest="community_distribution_threshold",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Minimum percentage (0–100) a community must reach in at least one organisation row "
                "to be shown in the Organisation × Community distribution cross-tab. "
                "Columns below this threshold in every row are hidden. Default: 10."
            ),
        )
        parser.add_argument(
            "--channel-types",
            dest="channel_types",
            default=None,
            metavar="TYPES",
            help=(
                "Comma-separated list of Telegram entity types to include in the graph. "
                "Available: CHANNEL (broadcast channels), GROUP (supergroups/gigagroups), "
                "USER (user accounts and bots). Defaults to the DEFAULT_CHANNEL_TYPES setting."
            ),
        )
        parser.add_argument(
            "--channel-groups",
            dest="channel_groups",
            default=None,
            metavar="GROUPS",
            help=(
                "Comma-separated list of ChannelGroup keys. "
                "When provided, only channels belonging to at least one of these groups are included in the graph. "
                "Leave unset to include all interesting channels regardless of group membership."
            ),
        )
        parser.add_argument(
            "--include-lost",
            dest="include_lost",
            action="store_true",
            default=None,
            help="Include channels marked as lost in the graph (excluded by default).",
        )
        parser.add_argument(
            "--include-private",
            dest="include_private",
            action="store_true",
            default=None,
            help="Include channels marked as private in the graph (excluded by default).",
        )
        parser.add_argument(
            "--timeline-step",
            dest="timeline_step",
            default=None,
            choices=["none", "year"],
            help=(
                "Repeat the export for each calendar year found in the data. "
                "'none' disables this (default); 'year' generates per-year outputs "
                "(graph_YYYY.html, channel_table_YYYY.html, data_YYYY/, etc.) alongside "
                "the full-range export, and adds a Timeline section to the index."
            ),
        )
        # ── Vacancy analysis ──────────────────────────────────────────────────
        parser.add_argument(
            "--vacancy-measures",
            dest="vacancy_measures",
            default=None,
            metavar="MEASURES",
            help=(
                "Comma-separated list of vacancy succession algorithms to compute. "
                "Available: AMPLIFIER_JACCARD, STRUCTURAL_EQUIV, BROKERAGE, "
                "CASCADE_OVERLAP, PPR, TEMPORAL, ALL. "
                "When at least one is selected, data/vacancy_analysis.json and "
                "vacancy_analysis.html are written for all vacancies in the database. "
                "Default: none (vacancy analysis disabled)."
            ),
        )
        parser.add_argument(
            "--vacancy-months-before",
            dest="vacancy_months_before",
            type=int,
            default=None,
            metavar="N",
            help="Look-back window (months) before each vacancy's death date. Default: 12.",
        )
        parser.add_argument(
            "--vacancy-months-after",
            dest="vacancy_months_after",
            type=int,
            default=None,
            metavar="N",
            help="Forward window (months) after each vacancy's death date. Default: 24.",
        )
        parser.add_argument(
            "--vacancy-max-candidates",
            dest="vacancy_max_candidates",
            type=int,
            default=None,
            metavar="N",
            help="Maximum replacement candidates scored per vacancy. Default: 30.",
        )
        parser.add_argument(
            "--vacancy-ppr-alpha",
            dest="vacancy_ppr_alpha",
            type=float,
            default=None,
            metavar="α",
            help=(
                "Damping factor for Personalized PageRank (PPR measure). "
                "Higher values weight long-range connections more. Default: 0.85."
            ),
        )
        parser.add_argument(
            "--name",
            dest="name",
            default="",
            help=(
                "Name for this export. Output is written to exports/<name>/. "
                "If omitted, a YYYYMMDD-HHMMSS timestamp is used. "
                "Name is slug-sanitized (alphanumeric, hyphens, underscores)."
            ),
        )

    def _validate_settings(
        self,
        communities_strategy: list[str],
        network_measures: list[str],
        network_stat_groups: list[str],
        channel_types: list[str],
        edge_weight_strategy: str,
        vacancy_measures: list[str],
    ) -> str | None:
        """Validate all settings. Raises CommandError on failure. Returns the BRIDGING token or None."""
        invalid_strategies = [s for s in communities_strategy if s not in community.VALID_STRATEGIES]
        if invalid_strategies:
            raise CommandError(
                f"Invalid --community-strategies value(s): {invalid_strategies!r}. "
                f"Choose from {sorted(community.VALID_STRATEGIES) + ['ALL']}."
            )
        invalid_measures = [m for m in network_measures if not measures.is_valid_measure(m)]
        if invalid_measures:
            valid_display = sorted(measures.VALID_MEASURES) + ["ALL", "BRIDGING", "BRIDGING(<STRATEGY>)"]
            raise CommandError(f"Invalid --measures value(s): {invalid_measures!r}. Choose from {valid_display}.")
        bridging_token = measures.find_bridging_token(network_measures)
        if bridging_token is not None:
            bstrategy = measures.bridging_strategy(bridging_token)
            if bstrategy not in community.VALID_STRATEGIES:
                raise CommandError(
                    f"Invalid strategy in {bridging_token!r}: {bstrategy!r}. "
                    f"Choose from {sorted(community.VALID_STRATEGIES)}."
                )
            if bstrategy not in communities_strategy:
                raise CommandError(
                    f"BRIDGING community basis {bstrategy!r} is not in --community-strategies. "
                    f"Add it or change the BRIDGING strategy."
                )
        invalid_stat_groups = [g for g in network_stat_groups if g not in measures.VALID_NETWORK_STAT_GROUPS]
        if invalid_stat_groups:
            valid_display = sorted(measures.VALID_NETWORK_STAT_GROUPS) + ["ALL"]
            raise CommandError(
                f"Invalid --network-stat-groups value(s): {invalid_stat_groups!r}. Choose from {valid_display}."
            )
        invalid_channel_types = [t for t in channel_types if t not in VALID_CHANNEL_TYPES]
        if invalid_channel_types:
            raise CommandError(
                f"Invalid --channel-types value(s): {invalid_channel_types!r}. Choose from {sorted(VALID_CHANNEL_TYPES)}."
            )
        if edge_weight_strategy not in VALID_EDGE_WEIGHT_STRATEGIES:
            raise CommandError(
                f"Invalid --edge-weight-strategy value: {edge_weight_strategy!r}. "
                f"Choose from {sorted(VALID_EDGE_WEIGHT_STRATEGIES)}."
            )
        invalid_vacancy = [m for m in vacancy_measures if m not in vacancy_analysis.VALID_VACANCY_MEASURES]
        if invalid_vacancy:
            valid_display = sorted(vacancy_analysis.VALID_VACANCY_MEASURES) + ["ALL"]
            raise CommandError(
                f"Invalid --vacancy-measures value(s): {invalid_vacancy!r}. Choose from {valid_display}."
            )
        return bridging_token

    def _parse_date(self, value: str | None, flag: str) -> datetime.date | None:
        if value is None:
            return None
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as err:
            raise CommandError(f"Invalid date for {flag}: {value!r}. Expected format: yyyy-mm-dd.") from err

    def _compute_communities(
        self,
        graph: nx.DiGraph,
        channel_dict: dict,
        edge_list: list,
        communities_strategy: list[str],
        options: dict,
    ) -> dict[str, tuple]:
        """Run all community detection strategies and apply results to the graph."""
        strategy_results: dict[str, tuple] = {}
        self.stdout.write("Calculate communities")
        self.stdout.flush()
        for strategy in communities_strategy:
            self.stdout.write(f"- {strategy.lower()} … ", ending="")
            self.stdout.flush()
            try:
                community_map, community_palette = community.detect(
                    strategy,
                    settings.COMMUNITY_PALETTE,
                    graph,
                    channel_dict,
                    leiden_coarse_resolution=options["leiden_coarse_resolution"],
                    leiden_fine_resolution=options["leiden_fine_resolution"],
                    mcl_inflation=options["mcl_inflation"],
                )
            except ValueError as e:
                raise CommandError(str(e)) from e
            community.apply_to_graph(graph, channel_dict, community_map, community_palette, strategy)
            strategy_results[strategy] = (community_map, community_palette)
            n_communities = len(set(community_map.values()))
            self.stdout.write(f"{n_communities} communities")
            self.stdout.flush()
        community.apply_edge_colors(graph, edge_list, channel_dict)
        return strategy_results

    def _compute_layout(
        self,
        graph: nx.DiGraph,
        do_graph: bool,
        do_3dgraph: bool,
        fa2_iterations: int,
        target_layout: str,
        reference_positions: "dict | None" = None,
        reference_positions_3d: "dict | None" = None,
    ) -> tuple[dict, dict | None]:
        """Compute 2D (and optionally 3D) ForceAtlas2 positions.

        When *reference_positions* / *reference_positions_3d* are supplied
        (full-range layout) the per-year export skips the independent
        Kamada-Kawai run and seeds FA2 from the reference instead, running KK
        only for nodes absent from the reference.  For 2D the orientation is
        also corrected via discrete 90°-rotation alignment.
        """
        positions_3d: dict | None = None
        if not (do_graph or do_3dgraph):
            return {}, None

        self.stdout.write("\nSet spatial distribution of nodes")

        if reference_positions is not None:
            # Seed FA2 from the full-range layout so each year starts from the
            # same orientation.  KK is only computed for nodes absent from the
            # reference (channels that first appear in this specific year).
            new_nodes = [n for n in graph.nodes() if n not in reference_positions]
            if new_nodes:
                self.stdout.write(f"- Kamada-Kawai ({len(new_nodes)} new nodes) … ", ending="")
                self.stdout.flush()
                kk_pos = layout.kamada_kawai_positions(graph)
                initial_pos = {n: reference_positions.get(n, kk_pos[n]) for n in graph.nodes()}
                self.stdout.write("done")
            else:
                self.stdout.write("- seeding from reference layout … ", ending="")
                self.stdout.flush()
                initial_pos = {n: reference_positions[n] for n in graph.nodes()}
                self.stdout.write("done")
        else:
            self.stdout.write("- Kamada-Kawai … ", ending="")
            self.stdout.flush()
            initial_pos = layout.kamada_kawai_positions(graph)
            self.stdout.write("done")

        self.stdout.write(f"- ForceAtlas2 ({fa2_iterations} iterations) … ", ending="")
        self.stdout.flush()
        positions = layout.forceatlas2_positions(graph, initial_pos, fa2_iterations)
        self.stdout.write("done")

        if reference_positions is not None:
            # Align orientation to the reference using the best of the four
            # axis-aligned rotations (avoids drift introduced by FA2).
            self.stdout.write("- aligning orientation … ", ending="")
            positions = layout.align_to_reference(positions, reference_positions)
            self.stdout.write("done")
        else:
            # Full-range export: apply the existing aspect-ratio heuristic.
            xs, ys = zip(*positions.values(), strict=False)
            width = max(xs) - min(xs)
            height = max(ys) - min(ys)
            if (target_layout == layout.LAYOUT_HORIZONTAL and height > width) or (
                target_layout == layout.LAYOUT_VERTICAL and width > height
            ):
                self.stdout.write("- rotating layout 90° … ", ending="")
                self.stdout.flush()
                positions = layout.rotate_positions(positions)
                self.stdout.write("done")

        if do_3dgraph:
            if reference_positions_3d is not None:
                new_nodes_3d = [n for n in graph.nodes() if n not in reference_positions_3d]
                if new_nodes_3d:
                    self.stdout.write(f"- Kamada-Kawai 3D ({len(new_nodes_3d)} new nodes) … ", ending="")
                    self.stdout.flush()
                    kk_pos_3d = layout.kamada_kawai_positions_3d(graph)
                    initial_pos_3d = {n: reference_positions_3d.get(n, kk_pos_3d[n]) for n in graph.nodes()}
                    self.stdout.write("done")
                else:
                    self.stdout.write("- seeding 3D from reference layout … ", ending="")
                    self.stdout.flush()
                    initial_pos_3d = {n: reference_positions_3d[n] for n in graph.nodes()}
                    self.stdout.write("done")
            else:
                self.stdout.write("- Kamada-Kawai 3D … ", ending="")
                self.stdout.flush()
                initial_pos_3d = layout.kamada_kawai_positions_3d(graph)
                self.stdout.write("done")
            self.stdout.write(f"- ForceAtlas2 3D ({fa2_iterations} iterations) … ", ending="")
            self.stdout.flush()
            positions_3d = layout.forceatlas2_positions_3d(graph, initial_pos_3d, fa2_iterations)
            self.stdout.write("done")

        return positions, positions_3d

    def _compute_measures(
        self,
        graph: nx.DiGraph,
        graph_data: GraphData,
        channel_dict: dict,
        selected_measures: set[str],
        bridging_token: str | None,
        start_date: datetime.date | None,
        end_date: datetime.date | None,
        do_graph: bool,
        do_3dgraph: bool,
        spreading_runs: int,
        diffusion_window: int,
    ) -> list[tuple[str, str]]:
        """Compute all network measures and return (key, label) pairs for each active measure."""
        self.stdout.write("\nCalculations on the graph")
        self.stdout.write("- largest component … ", ending="")
        self.stdout.flush()
        main_component_nodes = exporter.find_main_component(graph)
        self.stdout.write(f"{len(main_component_nodes)} nodes")

        self.stdout.write("- degrees, activity and fans")
        measures_labels = measures.apply_base_node_measures(
            graph_data, graph, channel_dict, start_date=start_date, end_date=end_date
        )

        # Pre-compute betweenness once when both BETWEENNESS and BRIDGING are active.
        _cached_betweenness: dict | None = None
        if "BETWEENNESS" in selected_measures and bridging_token is not None:
            _cached_betweenness = measures.compute_betweenness(graph)

        _orm_steps = [
            (
                "AMPLIFICATION",
                "amplification factor",
                lambda gd, g: measures.apply_amplification_factor(
                    gd, g, channel_dict, start_date=start_date, end_date=end_date
                ),
            ),
            (
                "CONTENTORIGINALITY",
                "content originality",
                lambda gd, g: measures.apply_content_originality(
                    gd, g, channel_dict, start_date=start_date, end_date=end_date
                ),
            ),
            (
                "DIFFUSIONLAG",
                "diffusion lag",
                lambda gd, g: measures.apply_diffusion_lag(
                    gd, g, channel_dict, start_date=start_date, end_date=end_date, window_days=diffusion_window
                ),
            ),
            (
                "SPREADING",
                "spreading efficiency (SIR)",
                lambda gd, g: measures.apply_spreading_efficiency(gd, g, runs=spreading_runs),
            ),
        ]
        for key, label, fn in [*measures.MEASURE_STEPS, *_orm_steps]:
            if key in selected_measures:
                self.stdout.write(f"- {label} … ", ending="")
                self.stdout.flush()
                if key == "BETWEENNESS" and _cached_betweenness is not None:
                    step_labels = measures.apply_betweenness_centrality(
                        graph_data, graph, betweenness=_cached_betweenness
                    )
                elif isinstance(fn, str):
                    step_labels = getattr(measures, fn)(graph_data, graph)
                else:
                    step_labels = fn(graph_data, graph)
                measures_labels += step_labels
                self.stdout.write("done")

        if selected_measures & {"HITSHUB", "HITSAUTH"}:
            self.stdout.write("- HITS … ", ending="")
            self.stdout.flush()
            hits_labels = measures.apply_hits(graph_data, graph)
            _hits_key_map = {"hits_hub": "HITSHUB", "hits_authority": "HITSAUTH"}
            measures_labels += [(k, lbl) for k, lbl in hits_labels if _hits_key_map[k] in selected_measures]
            self.stdout.write("done")

        if bridging_token is not None:
            strategy_key = measures.bridging_strategy(bridging_token).lower()
            self.stdout.write(f"- bridging centrality (community basis: {strategy_key}) … ", ending="")
            self.stdout.flush()
            measures_labels += measures.apply_bridging_centrality(
                graph_data, graph, strategy_key, betweenness=_cached_betweenness
            )
            self.stdout.write("done")

        if do_graph or do_3dgraph:
            self.stdout.write("- small components")
            exporter.reposition_isolated_nodes(graph_data, main_component_nodes)

        return measures_labels

    def _run_year_export(
        self,
        year: int,
        root_target: str,
        options: dict,
        selected_measures: set[str],
        bridging_token: str | None,
        communities_strategy: list[str],
        strategies: list[str],
        do_graph: bool,
        do_3dgraph: bool,
        do_xlsx: bool,
        channel_types: list[str],
        channel_groups: list[str],
        edge_weight_strategy: str,
        fa2_iterations: int,
        target_layout: str,
        seo: bool,
        project_title: str,
        selected_network_groups: "frozenset[str]",
        reference_positions: dict | None = None,
        reference_positions_3d: dict | None = None,
        extra_layout_names: list[str] | None = None,
        extra_layout_names_3d: list[str] | None = None,
    ) -> dict | None:
        """Run the full export pipeline for a single calendar year and write per-year files."""
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)

        self.stdout.write(f"\n  {year} … ", ending="")
        self.stdout.flush()

        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=options["draw_dead_leaves"],
                start_date=start_date,
                end_date=end_date,
                recency_weights=options["recency_weights"],
                channel_types=channel_types,
                channel_groups=channel_groups or None,
                edge_weight_strategy=edge_weight_strategy,
                include_mentions=options["include_mentions"],
                include_self_references=options["include_self_references"],
                include_lost=options["include_lost"],
                include_private=options["include_private"],
            )
        except ValueError as e:
            self.stdout.write(self.style.WARNING(f"skipped ({e})"))
            return None

        if not graph.nodes:
            self.stdout.write(self.style.WARNING("skipped (empty graph)"))
            return None

        n_nodes, n_edges = len(graph.nodes), len(graph.edges)
        self.stdout.write(f"{n_nodes} nodes, {n_edges} edges")

        strategy_results = self._compute_communities(graph, channel_dict, edge_list, communities_strategy, options)
        positions, positions_3d = self._compute_layout(
            graph,
            do_graph,
            do_3dgraph,
            fa2_iterations,
            target_layout,
            reference_positions,
            reference_positions_3d,
        )

        year_extra_positions: dict[str, dict] = {}
        year_extra_positions_3d: dict[str, dict] = {}
        if do_graph and extra_layout_names:
            _extra_layout_funcs_2d = {
                "CIRCULAR": layout.circular_positions,
                "KAMADA_KAWAI": layout.kamada_kawai_positions,
                "COMMUNITY_SHELL": lambda g: layout.community_shell_positions(g, strategy_results),
                "TSNE": layout.tsne_positions_2d,
                "UMAP": layout.umap_positions_2d,
                "HYPERBOLIC": layout.hyperbolic_positions,
            }
            for name in extra_layout_names:
                if name == "FA2":
                    continue
                year_extra_positions[name.lower()] = _extra_layout_funcs_2d[name](graph)
        if do_3dgraph and extra_layout_names_3d:
            _extra_layout_funcs_3d = {
                "SPECTRAL": layout.spectral_positions,
                "SPRING": layout.spring_positions,
                "KAMADA_KAWAI": layout.kamada_kawai_positions_3d,
                "TSNE": layout.tsne_positions_3d,
                "UMAP": layout.umap_positions_3d,
            }
            for name in extra_layout_names_3d:
                if name == "FA2":
                    continue
                year_extra_positions_3d[name.lower()] = _extra_layout_funcs_3d[name](graph)

        self.stdout.write("\nBuild graph data … ", ending="")
        self.stdout.flush()
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)
        self.stdout.write("done")
        measures_labels = self._compute_measures(
            graph,
            graph_data,
            channel_dict,
            selected_measures,
            bridging_token,
            start_date,
            end_date,
            do_graph,
            do_3dgraph,
            options["spreading_runs"],
            options["diffusion_window"],
        )

        communities_data = community.build_communities_payload(communities_strategy, strategy_results)
        need_metrics = True
        community_table_data = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            exporter.write_graph_files(
                graph_data,
                communities_data,
                measures_labels,
                channel_qs,
                graph_dir=tmp_dir,
                include_positions=do_graph or do_3dgraph,
                positions_3d=positions_3d,
                extra_positions=year_extra_positions or None,
                extra_positions_3d=year_extra_positions_3d or None,
            )
            exporter.write_meta_json(
                graph_dir=tmp_dir,
                project_title=project_title,
                reversed_edges=settings.REVERSED_EDGES,
                edge_weight_strategy=edge_weight_strategy,
                start_date=start_date,
                end_date=end_date,
                total_nodes=n_nodes,
                total_edges=n_edges,
                community_distribution_threshold=options["community_distribution_threshold"],
                has_consensus_matrix=False,
            )
            if need_metrics:
                community_table_data = community_stats.compute_community_metrics(
                    graph_data,
                    communities_data,
                    graph,
                    strategies,
                    measures_labels=measures_labels,
                    status_callback=None,
                    channel_qs=channel_qs,
                    start_date=start_date,
                    end_date=end_date,
                    selected_network_groups=selected_network_groups,
                )
                tables.write_network_metrics_json(community_table_data, strategies, graph_dir=tmp_dir)
                tables.write_community_metrics_json(community_table_data, strategies, graph_dir=tmp_dir)

            year_data_dst = os.path.join(root_target, f"data_{year}")
            if os.path.exists(year_data_dst):
                shutil.rmtree(year_data_dst)
            shutil.move(os.path.join(tmp_dir, "data"), year_data_dst)

        def _mk_ctx(title_part: str, *, description: str = "") -> dict:
            full_title = f"{project_title} | {title_part}" if project_title else title_part
            return {
                "title": full_title,
                "robots_meta": "index, follow" if seo else "noindex, nofollow",
                "description": description,
            }

        # Per-year XLSX files are not written individually; data is returned so the
        # caller can assemble a single multi-sheet workbook for each table type.
        return {
            "year": year,
            "nodes": n_nodes,
            "edges": n_edges,
            "has_graph": True,
            "has_channel_html": True,
            "has_network_html": True,
            "has_community_html": True,
            # Returned to the caller so it can assemble multi-sheet XLSX workbooks.
            "_xlsx_graph_data": graph_data if do_xlsx else None,
            "_xlsx_community_data": community_table_data if do_xlsx else None,
        }

    def handle(self, *args: Any, **options: Any) -> None:
        # Resolve None (not passed on CLI) from .analysis-defaults settings
        def _o(key: str, setting_val: Any) -> Any:
            v = options[key]
            return v if v is not None else setting_val

        raw_community_strategies = _parse_csv(_o("community_strategies", settings.SA_COMMUNITY_STRATEGIES))
        communities_strategy = (
            measures.ALL_STRATEGIES if "ALL" in raw_community_strategies else raw_community_strategies
        )
        raw_network_measures = _parse_csv(_o("measures", settings.SA_MEASURES))
        network_measures = measures.ALL_MEASURES if "ALL" in raw_network_measures else raw_network_measures
        raw_network_stat_groups = _parse_csv(_o("network_stat_groups", settings.SA_NETWORK_STAT_GROUPS))
        network_stat_groups = (
            measures.ALL_NETWORK_STAT_GROUPS if "ALL" in raw_network_stat_groups else raw_network_stat_groups
        )
        channel_types_raw = options["channel_types"]
        channel_types = (
            _parse_csv(channel_types_raw) if channel_types_raw is not None else settings.DEFAULT_CHANNEL_TYPES
        )
        channel_groups_raw = options["channel_groups"]
        channel_groups = _parse_csv(channel_groups_raw) if channel_groups_raw else []
        edge_weight_strategy: str = _o("edge_weight_strategy", settings.SA_EDGE_WEIGHT_STRATEGY)
        _raw_vacancy = _o("vacancy_measures", settings.SA_VACANCY_MEASURES) or ""
        raw_vacancy_measures = _parse_csv(_raw_vacancy) if _raw_vacancy else []
        selected_vacancy_measures = (
            set(vacancy_analysis.ALL_VACANCY_MEASURES) if "ALL" in raw_vacancy_measures else set(raw_vacancy_measures)
        )
        bridging_token = self._validate_settings(
            communities_strategy,
            network_measures,
            network_stat_groups,
            channel_types,
            edge_weight_strategy,
            list(selected_vacancy_measures),
        )
        selected_measures = set(network_measures)
        selected_network_groups = frozenset(network_stat_groups)

        do_graph = _o("graph", settings.SA_OUTPUT_GRAPH)
        do_3dgraph = _o("graph_3d", settings.SA_OUTPUT_3DGRAPH)
        do_html = _o("html", settings.SA_OUTPUT_HTML)
        do_xlsx = _o("xlsx", settings.SA_OUTPUT_XLSX)
        do_gexf = _o("gexf", settings.SA_OUTPUT_GEXF)
        do_graphml = _o("graphml", settings.SA_OUTPUT_GRAPHML)
        do_csv = _o("csv", settings.SA_OUTPUT_CSV)
        do_consensus_matrix = _o("consensus_matrix", settings.SA_CONSENSUS_MATRIX)
        do_structural_similarity = _o("structural_similarity", settings.SA_STRUCTURAL_SIMILARITY)

        fa2_iterations: int = _o("fa2_iterations", settings.SA_FA2_ITERATIONS)
        vertical_layout: bool = _o("vertical_layout", settings.SA_VERTICAL_LAYOUT)
        target_layout = layout.LAYOUT_VERTICAL if vertical_layout else layout.LAYOUT_HORIZONTAL

        extra_layout_names = _parse_csv(_o("layouts_2d", settings.SA_LAYOUTS_2D) or "")
        if "ALL" in extra_layout_names:
            extra_layout_names = sorted(layout.EXTRA_LAYOUT_CHOICES_2D)
        extra_layout_names = [n for n in extra_layout_names if n in layout.EXTRA_LAYOUT_CHOICES_2D]

        extra_layout_names_3d = _parse_csv(_o("layouts_3d", settings.SA_LAYOUTS_3D) or "")
        if "ALL" in extra_layout_names_3d:
            extra_layout_names_3d = sorted(layout.EXTRA_LAYOUT_CHOICES_3D)
        extra_layout_names_3d = [n for n in extra_layout_names_3d if n in layout.EXTRA_LAYOUT_CHOICES_3D]

        seo = _o("seo", settings.SA_SEO)
        start_date = self._parse_date(options["startdate"], "--startdate")
        end_date = self._parse_date(options["enddate"], "--enddate")
        draw_dead_leaves = _o("draw_dead_leaves", settings.SA_DRAW_DEAD_LEAVES)
        include_mentions = _o("include_mentions", settings.SA_INCLUDE_MENTIONS)
        include_self_references = _o("include_self_references", settings.SA_INCLUDE_SELF_REFERENCES)
        include_lost = _o("include_lost", settings.SA_INCLUDE_LOST)
        include_private = _o("include_private", settings.SA_INCLUDE_PRIVATE)
        timeline_step = _o("timeline_step", settings.SA_TIMELINE_STEP)
        vacancy_months_before = _o("vacancy_months_before", settings.SA_VACANCY_MONTHS_BEFORE)
        vacancy_months_after = _o("vacancy_months_after", settings.SA_VACANCY_MONTHS_AFTER)
        vacancy_max_candidates = _o("vacancy_max_candidates", settings.SA_VACANCY_MAX_CANDIDATES)
        vacancy_ppr_alpha = _o("vacancy_ppr_alpha", settings.SA_VACANCY_PPR_ALPHA)
        spreading_runs = _o("spreading_runs", settings.SA_SPREADING_RUNS)
        diffusion_window = _o("diffusion_window", settings.SA_DIFFUSION_WINDOW)
        leiden_coarse = _o("leiden_coarse_resolution", settings.SA_LEIDEN_COARSE_RESOLUTION)
        leiden_fine = _o("leiden_fine_resolution", settings.SA_LEIDEN_FINE_RESOLUTION)
        mcl_inflation = _o("mcl_inflation", settings.SA_MCL_INFLATION)
        community_dist_threshold = _o("community_distribution_threshold", settings.SA_COMMUNITY_DISTRIBUTION_THRESHOLD)

        # Patch options dict so internal helpers (_compute_communities, _run_year_export, etc.) use resolved values
        options.update(
            graph=do_graph,
            graph_3d=do_3dgraph,
            html=do_html,
            xlsx=do_xlsx,
            gexf=do_gexf,
            graphml=do_graphml,
            csv=do_csv,
            consensus_matrix=do_consensus_matrix,
            structural_similarity=do_structural_similarity,
            seo=seo,
            vertical_layout=vertical_layout,
            fa2_iterations=fa2_iterations,
            draw_dead_leaves=draw_dead_leaves,
            include_mentions=include_mentions,
            include_self_references=include_self_references,
            include_lost=include_lost,
            include_private=include_private,
            timeline_step=timeline_step,
            spreading_runs=spreading_runs,
            diffusion_window=diffusion_window,
            leiden_coarse_resolution=leiden_coarse,
            leiden_fine_resolution=leiden_fine,
            mcl_inflation=mcl_inflation,
            community_distribution_threshold=community_dist_threshold,
            vacancy_months_before=vacancy_months_before,
            vacancy_months_after=vacancy_months_after,
            vacancy_max_candidates=vacancy_max_candidates,
            vacancy_ppr_alpha=vacancy_ppr_alpha,
        )

        self.stdout.write("Create graph … ", ending="")
        self.stdout.flush()
        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=draw_dead_leaves,
                start_date=start_date,
                end_date=end_date,
                recency_weights=options["recency_weights"],
                channel_types=channel_types,
                channel_groups=channel_groups or None,
                edge_weight_strategy=edge_weight_strategy,
                include_mentions=include_mentions,
                include_self_references=include_self_references,
                include_lost=include_lost,
                include_private=include_private,
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")
        self.stdout.flush()

        strategy_results = self._compute_communities(graph, channel_dict, edge_list, communities_strategy, options)
        positions, positions_3d = self._compute_layout(graph, do_graph, do_3dgraph, fa2_iterations, target_layout)

        extra_positions: dict[str, dict] = {}
        fa2_in_2d = do_graph and "FA2" in extra_layout_names
        extra_positions_3d: dict[str, dict] = {}
        fa2_in_3d = do_3dgraph and "FA2" in extra_layout_names_3d
        if do_graph and extra_layout_names:
            _extra_layout_funcs_2d = {
                "CIRCULAR": layout.circular_positions,
                "KAMADA_KAWAI": layout.kamada_kawai_positions,
                "COMMUNITY_SHELL": lambda g: layout.community_shell_positions(g, strategy_results),
                "TSNE": layout.tsne_positions_2d,
                "UMAP": layout.umap_positions_2d,
                "HYPERBOLIC": layout.hyperbolic_positions,
            }
            non_fa2 = [n for n in extra_layout_names if n != "FA2"]
            if non_fa2:
                self.stdout.write("\nCompute extra 2D layouts")
            for name in non_fa2:
                self.stdout.write(f"- {name.lower()} … ", ending="")
                self.stdout.flush()
                extra_positions[name.lower()] = _extra_layout_funcs_2d[name](graph)
                self.stdout.write("done")
        if do_3dgraph and extra_layout_names_3d:
            _extra_layout_funcs_3d = {
                "SPECTRAL": layout.spectral_positions,
                "SPRING": layout.spring_positions,
                "KAMADA_KAWAI": layout.kamada_kawai_positions_3d,
                "TSNE": layout.tsne_positions_3d,
                "UMAP": layout.umap_positions_3d,
            }
            non_fa2_3d = [n for n in extra_layout_names_3d if n != "FA2"]
            if non_fa2_3d:
                self.stdout.write("\nCompute extra 3D layouts")
            for name in non_fa2_3d:
                self.stdout.write(f"- {name.lower()} … ", ending="")
                self.stdout.flush()
                extra_positions_3d[name.lower()] = _extra_layout_funcs_3d[name](graph)
                self.stdout.write("done")

        self.stdout.write("\nBuild graph data … ", ending="")
        self.stdout.flush()
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)
        self.stdout.write("done")
        measures_labels = self._compute_measures(
            graph,
            graph_data,
            channel_dict,
            selected_measures,
            bridging_token,
            start_date,
            end_date,
            do_graph,
            do_3dgraph,
            options["spreading_runs"],
            options["diffusion_window"],
        )

        export_name = re.sub(r"[^\w\-]", "-", (options.get("name") or "").strip()).strip("-")
        if not export_name:
            export_name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        _final_target = str(Path(settings.BASE_DIR) / "exports" / export_name)
        # All writes go to the staging directory; it is renamed to _final_target only after
        # write_summary_json completes, making every live export atomically consistent.
        root_target = _final_target + ".tmp"
        shutil.rmtree(root_target, ignore_errors=True)  # clean up any interrupted previous run
        shutil.rmtree(_final_target + ".old", ignore_errors=True)  # clean up any orphaned backup
        project_title: str = settings.PROJECT_TITLE
        self.stdout.write("Build communities data … ", ending="")
        self.stdout.flush()
        communities_data = community.build_communities_payload(communities_strategy, strategy_results)
        self.stdout.write("done")
        strategies = [s.lower() for s in communities_strategy]

        # Copy the map template (js/, css/, static assets) whenever any HTML page is being
        # generated, not just when a graph is requested — table pages and the structural
        # similarity matrix all reference the same local CSS/JS files.
        need_static_assets = (
            do_graph
            or do_3dgraph
            or do_html
            or do_consensus_matrix
            or do_structural_similarity
            or bool(selected_vacancy_measures)
        )
        if need_static_assets:
            exporter.ensure_graph_root(root_target)

        if do_graph or do_3dgraph:
            self.stdout.write("\nGenerate map")
            self.stdout.write("- config files")
            exporter.apply_robots_to_graph_html(
                root_target,
                seo,
                project_title=project_title,
                include_3d=do_3dgraph,
                vertical_layout=vertical_layout,
                extra_layouts=(["fa2"] if fa2_in_2d else []) + list(extra_positions.keys()),
                extra_layouts_3d=(["fa2"] if fa2_in_3d else []) + list(extra_positions_3d.keys()),
            )
            exporter.write_robots_txt(root_target, seo)

        self.stdout.write("- data files")
        exporter.write_graph_files(
            graph_data,
            communities_data,
            measures_labels,
            channel_qs,
            graph_dir=root_target,
            include_positions=do_graph or do_3dgraph,
            positions_3d=positions_3d,
            extra_positions=extra_positions or None,
            extra_positions_3d=extra_positions_3d or None,
        )
        exporter.write_meta_json(
            graph_dir=root_target,
            project_title=project_title,
            reversed_edges=settings.REVERSED_EDGES,
            edge_weight_strategy=edge_weight_strategy,
            start_date=start_date,
            end_date=end_date,
            total_nodes=len(graph.nodes),
            total_edges=len(graph.edges),
            community_distribution_threshold=options["community_distribution_threshold"],
            has_consensus_matrix=do_consensus_matrix,
        )

        need_community_metrics = do_html or do_xlsx or do_consensus_matrix
        if need_community_metrics:
            self.stdout.write("- community metrics")
            _steps = ["network"] + strategies
            _step_iter = iter(_steps)
            next(_step_iter)  # skip "network"; already announced below

            def _on_metrics_step(label: str) -> None:
                self.stdout.write("done")
                next_label = next(_step_iter, None)
                if next_label is not None:
                    sd = communities_data.get(next_label)
                    n = len(sd.get("groups") or []) if sd else 0
                    self.stdout.write(f"  - {next_label} ({n} communities) … ", ending="")
                    self.stdout.flush()

            self.stdout.write("  - network … ", ending="")
            self.stdout.flush()
            community_table_data = community_stats.compute_community_metrics(
                graph_data,
                communities_data,
                graph,
                strategies,
                measures_labels=measures_labels,
                status_callback=_on_metrics_step,
                channel_qs=channel_qs,
                start_date=start_date,
                end_date=end_date,
                selected_network_groups=selected_network_groups,
            )
            tables.write_network_metrics_json(community_table_data, strategies, graph_dir=root_target)
            tables.write_community_metrics_json(community_table_data, strategies, graph_dir=root_target)
        if do_html:
            self.stdout.write("- table (html)")
            tables.write_table_html(
                graph_data,
                output_filename=os.path.join(root_target, "channel_table.html"),
                seo=seo,
                project_title=project_title,
            )
            self.stdout.write("- network table (html)")
            tables.write_network_table_html(
                output_filename=os.path.join(root_target, "network_table.html"),
                seo=seo,
                project_title=project_title,
            )
            self.stdout.write("- community table (html)")
            tables.write_community_table_html(
                output_filename=os.path.join(root_target, "community_table.html"),
                seo=seo,
                project_title=project_title,
            )
        # XLSX written after the timeline loop so year sheets can be included.

        if do_consensus_matrix:
            self.stdout.write("- consensus matrix (html)")
            tables.write_consensus_matrix_html(
                output_filename=os.path.join(root_target, "consensus_matrix.html"),
                seo=seo,
                project_title=project_title,
            )

        if do_structural_similarity:
            self.stdout.write("- structural similarity (html + json)")
            os.makedirs(root_target, exist_ok=True)
            sim_data = community_stats._compute_structural_similarity(graph_data, measures_labels)
            if sim_data is not None:
                tables.write_structural_similarity_json(sim_data, root_target)
            tables.write_structural_similarity_html(
                output_filename=os.path.join(root_target, "structural_similarity.html"),
                seo=seo,
                project_title=project_title,
            )

        if do_graph or do_3dgraph:
            self.stdout.write("- media")
            exporter.copy_channel_media(channel_qs, root_target)

        if do_gexf:
            self.stdout.write("- gexf")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_gexf(graph, graph_data, os.path.join(root_target, "network.gexf"))

        if do_graphml:
            self.stdout.write("- graphml")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_graphml(graph, graph_data, os.path.join(root_target, "network.graphml"))

        if do_csv:
            self.stdout.write("- csv")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_csv(graph_data, edge_list, measures_labels, strategies, root_target)

        do_vacancy = bool(selected_vacancy_measures)
        if do_vacancy:
            self.stdout.write("\nVacancy analysis")
            _vac_n = [0]

            def _vac_progress(title: str) -> None:
                if _vac_n[0] > 0:
                    self.stdout.write("done")
                _vac_n[0] += 1
                self.stdout.write(f"  [{_vac_n[0]}] {title} … ", ending="")
                self.stdout.flush()

            vac_payload = vacancy_analysis.compute_vacancy_analysis(
                graph=graph,
                channel_dict=channel_dict,
                selected_measures=selected_vacancy_measures,
                months_before=options["vacancy_months_before"],
                months_after=options["vacancy_months_after"],
                max_candidates=options["vacancy_max_candidates"],
                sir_runs=options["spreading_runs"],
                ppr_alpha=options["vacancy_ppr_alpha"],
                progress_callback=_vac_progress,
            )
            if _vac_n[0] > 0:
                self.stdout.write("done")
            else:
                self.stdout.write("- no vacancies found")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_vacancy_analysis_json(vac_payload, root_target)
            self.stdout.write("- vacancy_analysis.json")
            tables.write_vacancy_analysis_html(
                output_filename=os.path.join(root_target, "vacancy_analysis.html"),
                seo=seo,
                project_title=project_title,
            )
            self.stdout.write("- vacancy_analysis.html")

        timeline_entries: list[dict] = []
        if options["timeline_step"] == "year":
            year_agg = Message.objects.aggregate(min_date=Min("date"), max_date=Max("date"))
            min_date, max_date = year_agg["min_date"], year_agg["max_date"]
            if min_date is None:
                self.stdout.write(self.style.WARNING("\nTimeline: no messages found, skipping."))
            else:
                self.stdout.write(f"\nTimeline export ({min_date.year}–{max_date.year})")
                for yr in range(min_date.year, max_date.year + 1):
                    entry = self._run_year_export(
                        yr,
                        root_target,
                        options,
                        selected_measures,
                        bridging_token,
                        communities_strategy,
                        strategies,
                        do_graph,
                        do_3dgraph,
                        do_xlsx,
                        channel_types,
                        channel_groups,
                        edge_weight_strategy,
                        fa2_iterations,
                        target_layout,
                        seo,
                        project_title,
                        selected_network_groups,
                        reference_positions=positions if do_graph else None,
                        reference_positions_3d=positions_3d if do_3dgraph else None,
                        extra_layout_names=extra_layout_names if extra_layout_names else None,
                        extra_layout_names_3d=extra_layout_names_3d if extra_layout_names_3d else None,
                    )
                    if entry is not None:
                        timeline_entries.append(entry)
                if timeline_entries:
                    tables.write_timeline_json(timeline_entries, graph_dir=root_target)

        if do_xlsx:
            year_xlsx = [
                (e["year"], e["_xlsx_graph_data"], e["_xlsx_community_data"])
                for e in timeline_entries
                if e.get("_xlsx_graph_data") is not None
            ]
            channel_years = [(yr, gd) for yr, gd, _ in year_xlsx] or None
            network_years = [(yr, ctd) for yr, _, ctd in year_xlsx if ctd is not None] or None
            self.stdout.write("- table (xlsx)")
            tables.write_table_xlsx(
                graph_data,
                measures_labels,
                strategies,
                output_filename=os.path.join(root_target, "channel_table.xlsx"),
                project_title=project_title,
                year_data=channel_years,
            )
            self.stdout.write("- network table (xlsx)")
            tables.write_network_table_xlsx(
                community_table_data,
                strategies,
                output_filename=os.path.join(root_target, "network_table.xlsx"),
                project_title=project_title,
                year_data=network_years,
            )
            self.stdout.write("- community table (xlsx)")
            tables.write_community_table_xlsx(
                community_table_data,
                strategies,
                output_filename=os.path.join(root_target, "community_table.xlsx"),
                project_title=project_title,
                year_data=network_years,
            )

        self.stdout.write("- index")
        os.makedirs(root_target, exist_ok=True)
        tables.write_index_html(
            output_filename=os.path.join(root_target, "index.html"),
            seo=seo,
            project_title=project_title,
            include_graph=do_graph,
            include_3d_graph=do_3dgraph,
            include_channel_html=do_html,
            include_channel_xlsx=do_xlsx,
            include_network_html=do_html,
            include_network_xlsx=do_xlsx,
            include_community_html=do_html,
            include_community_xlsx=do_xlsx,
            include_compare_html=False,
            compare_files=set(),
            strategies=strategies,
            include_consensus_matrix_html=do_consensus_matrix,
            include_structural_similarity=do_structural_similarity,
            timeline_entries=timeline_entries or None,
            include_vacancy_analysis=do_vacancy,
        )

        exporter.write_summary_json(root_target, export_name or None, options, len(graph.nodes), len(graph.edges))

        # Atomic swap: two-step rename so there is never a window where neither the old
        # nor the new export exists.  On POSIX, os.rename is atomic per inode, but cannot
        # replace a non-empty directory in a single call, hence the intermediate .old step.
        _old = _final_target + ".old"
        if os.path.isdir(_final_target):
            os.rename(_final_target, _old)
        os.rename(root_target, _final_target)
        if os.path.isdir(_old):
            shutil.rmtree(_old, ignore_errors=True)

        self.stdout.write(self.style.SUCCESS("\nDone."))
