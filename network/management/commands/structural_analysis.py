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
from django.template.loader import render_to_string

from network import community, community_stats, exporter, graph_builder, layout, measures, tables
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
            default=False,
            help="Generate the 2D interactive graph (graph.html and layout computation).",
        )
        parser.add_argument(
            "--3dgraph",
            dest="graph_3d",
            action="store_true",
            default=False,
            help="Also produce a 3D graph (graph3d.html). Slower on large graphs.",
        )
        parser.add_argument(
            "--html",
            dest="html",
            action="store_true",
            default=False,
            help="Generate HTML table output (channel_table.html, network_table.html, community_table.html).",
        )
        parser.add_argument(
            "--xlsx",
            dest="xlsx",
            action="store_true",
            default=False,
            help="Also produce Excel spreadsheet output (channel_table.xlsx, network_table.xlsx, community_table.xlsx).",
        )
        parser.add_argument(
            "--gexf",
            dest="gexf",
            action="store_true",
            default=False,
            help="Also write network.gexf with all computed measures embedded as node attributes.",
        )
        parser.add_argument(
            "--graphml",
            dest="graphml",
            action="store_true",
            default=False,
            help="Also write network.graphml with all computed measures embedded as node attributes.",
        )
        parser.add_argument(
            "--seo",
            action="store_true",
            default=False,
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
            default=5000,
            metavar="N",
            help="Number of ForceAtlas2 iterations for the 2D and 3D layout. Default: 5000.",
        )
        parser.add_argument(
            "--vertical-layout",
            dest="vertical_layout",
            action="store_true",
            default=False,
            help=(
                "Orient the graph vertically. By default the layout is horizontal. "
                "When the computed aspect ratio does not match the chosen orientation the graph is rotated 90°."
            ),
        )
        parser.add_argument(
            "--measures",
            dest="measures",
            default="PAGERANK",
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
            default="ORGANIZATION",
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
            default="ALL",
            metavar="GROUPS",
            help=(
                "Comma-separated list of whole-network stat groups to compute (requires --html, --xlsx, or "
                "--consensus-matrix). Available: SIZE, PATHS, COHESION, COMPONENTS, DEGCORRELATION, "
                "CENTRALIZATION, CONTENT, ALL. Default: ALL."
            ),
        )
        parser.add_argument(
            "--edge-weight-strategy",
            dest="edge_weight_strategy",
            default="PARTIAL_REFERENCES",
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
            default=200,
            metavar="N",
            help="Number of Monte Carlo SIR simulations per node for the SPREADING measure. Default: 200.",
        )
        parser.add_argument(
            "--draw-dead-leaves",
            dest="draw_dead_leaves",
            action="store_true",
            default=False,
            help=(
                "Include non-interesting channels that are referenced by interesting ones as leaf nodes in the graph."
            ),
        )
        parser.add_argument(
            "--leiden-coarse-resolution",
            dest="leiden_coarse_resolution",
            type=float,
            default=0.01,
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
            default=0.05,
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
            default=2.0,
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
            default=False,
            help=(
                "Generate a consensus matrix page (consensus_matrix.html) showing how consistently "
                "each channel pair is co-clustered across all non-ORGANIZATION community detection strategies. "
                "Requires at least two non-ORGANIZATION strategies."
            ),
        )
        parser.add_argument(
            "--community-distribution-threshold",
            dest="community_distribution_threshold",
            type=int,
            default=10,
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
                "Comma-separated list of ChannelGroup names. "
                "When provided, only channels belonging to at least one of these groups are included in the graph. "
                "Leave unset to include all interesting channels regardless of group membership."
            ),
        )
        parser.add_argument(
            "--timeline-step",
            dest="timeline_step",
            default="none",
            choices=["none", "year"],
            help=(
                "Repeat the export for each calendar year found in the data. "
                "'none' disables this (default); 'year' generates per-year outputs "
                "(graph_YYYY.html, channel_table_YYYY.html, data_YYYY/, etc.) alongside "
                "the full-range export, and adds a Timeline section to the index."
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
                self.stdout.write("- seeding from reference layout")
                initial_pos = {n: reference_positions[n] for n in graph.nodes()}
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
                self.stdout.write("- rotating layout 90°")
                positions = layout.rotate_positions(positions)

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
                    self.stdout.write("- seeding 3D from reference layout")
                    initial_pos_3d = {n: reference_positions_3d[n] for n in graph.nodes()}
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
        do_html: bool,
        do_xlsx: bool,
        do_consensus_matrix: bool,
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
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)
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
        )

        communities_data = community.build_communities_payload(communities_strategy, strategy_results)
        need_metrics = do_html or do_xlsx or do_consensus_matrix
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
                has_consensus_matrix=do_consensus_matrix,
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

        has_channel_html = has_channel_xlsx = False
        has_network_html = has_network_xlsx = False
        has_community_html = has_community_xlsx = False
        has_consensus_matrix_html = False

        if do_html:
            ctx = _mk_ctx(
                f"Channels ({year})",
                description=f"Network data for {n_nodes} channels in {year}.",
            )
            content = render_to_string("network/channel_table.html", ctx)
            with open(os.path.join(root_target, f"channel_table_{year}.html"), "w") as fh:
                fh.write(tables._patch_timeline_html(content, year))
            has_channel_html = True

            ctx = _mk_ctx(f"Network ({year})")
            content = render_to_string("network/network_table.html", ctx)
            with open(os.path.join(root_target, f"network_table_{year}.html"), "w") as fh:
                fh.write(tables._patch_timeline_html(content, year))
            has_network_html = True

            ctx = _mk_ctx(f"Communities ({year})")
            content = render_to_string("network/community_table.html", ctx)
            with open(os.path.join(root_target, f"community_table_{year}.html"), "w") as fh:
                fh.write(tables._patch_timeline_html(content, year))
            has_community_html = True

        # Per-year XLSX files are not written individually; data is returned so the
        # caller can assemble a single multi-sheet workbook for each table type.

        if do_consensus_matrix:
            ctx = _mk_ctx(f"Consensus matrix ({year})")
            content = render_to_string("network/consensus_matrix.html", ctx)
            with open(os.path.join(root_target, f"consensus_matrix_{year}.html"), "w") as fh:
                fh.write(tables._patch_timeline_html(content, year))
            has_consensus_matrix_html = True

        return {
            "year": year,
            "nodes": n_nodes,
            "edges": n_edges,
            "has_graph": True,
            "has_channel_html": has_channel_html,
            "has_channel_xlsx": has_channel_xlsx,
            "has_network_html": has_network_html,
            "has_network_xlsx": has_network_xlsx,
            "has_community_html": has_community_html,
            "has_community_xlsx": has_community_xlsx,
            "has_consensus_matrix_html": has_consensus_matrix_html,
            # Returned to the caller so it can assemble multi-sheet XLSX workbooks.
            "_xlsx_graph_data": graph_data if do_xlsx else None,
            "_xlsx_community_data": community_table_data if do_xlsx else None,
        }

    def handle(self, *args: Any, **options: Any) -> None:
        raw_community_strategies = _parse_csv(options["community_strategies"])
        communities_strategy = (
            measures.ALL_STRATEGIES if "ALL" in raw_community_strategies else raw_community_strategies
        )
        raw_network_measures = _parse_csv(options["measures"])
        network_measures = measures.ALL_MEASURES if "ALL" in raw_network_measures else raw_network_measures
        raw_network_stat_groups = _parse_csv(options["network_stat_groups"])
        network_stat_groups = (
            measures.ALL_NETWORK_STAT_GROUPS if "ALL" in raw_network_stat_groups else raw_network_stat_groups
        )
        channel_types_raw = options["channel_types"]
        channel_types = (
            _parse_csv(channel_types_raw) if channel_types_raw is not None else settings.DEFAULT_CHANNEL_TYPES
        )
        channel_groups_raw = options["channel_groups"]
        channel_groups = _parse_csv(channel_groups_raw) if channel_groups_raw else []
        edge_weight_strategy: str = options["edge_weight_strategy"]
        bridging_token = self._validate_settings(
            communities_strategy, network_measures, network_stat_groups, channel_types, edge_weight_strategy
        )
        selected_measures = set(network_measures)
        selected_network_groups = frozenset(network_stat_groups)

        do_graph = options["graph"]
        do_3dgraph = options["graph_3d"]
        do_html = options["html"]
        do_xlsx = options["xlsx"]
        do_gexf = options["gexf"]
        do_graphml = options["graphml"]
        do_consensus_matrix = options["consensus_matrix"]

        fa2_iterations: int = options["fa2_iterations"]
        vertical_layout: bool = options["vertical_layout"]
        target_layout = layout.LAYOUT_VERTICAL if vertical_layout else layout.LAYOUT_HORIZONTAL

        seo = options["seo"]
        start_date = self._parse_date(options["startdate"], "--startdate")
        end_date = self._parse_date(options["enddate"], "--enddate")

        self.stdout.write("Create graph … ", ending="")
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
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")

        strategy_results = self._compute_communities(graph, channel_dict, edge_list, communities_strategy, options)
        positions, positions_3d = self._compute_layout(graph, do_graph, do_3dgraph, fa2_iterations, target_layout)

        graph_data = exporter.build_graph_data(graph, channel_dict, positions)
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
        communities_data = community.build_communities_payload(communities_strategy, strategy_results)
        strategies = [s.lower() for s in communities_strategy]

        if do_graph or do_3dgraph:
            self.stdout.write("\nGenerate map")
            exporter.ensure_graph_root(root_target)
            self.stdout.write("- config files")
            exporter.apply_robots_to_graph_html(
                root_target, seo, project_title=project_title, include_3d=do_3dgraph, vertical_layout=vertical_layout
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
                        do_html,
                        do_xlsx,
                        do_consensus_matrix,
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
            timeline_entries=timeline_entries or None,
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
