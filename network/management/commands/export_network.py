import datetime
import os
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import community, community_stats, exporter, graph_builder, layout, measures, tables
from network.graph_builder import VALID_EDGE_WEIGHT_STRATEGIES
from webapp.utils.channel_types import VALID_CHANNEL_TYPES


class Command(BaseCommand):
    args = ""
    help = "write file"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--graph",
            dest="graph",
            action="store_true",
            default=False,
            help="Generate the 2D interactive graph (graph.html and layout computation).",
        )
        parser.add_argument(
            "--3d",
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
            "--compare",
            default=None,
            metavar="PROJECT_DIR",
            help=(
                "Path to a graph/ output directory from a previous export_network run "
                "(the directory that contains index.html). "
                "Its data/, graph files, *_table.html and *.xlsx files are copied with _2 suffixes; "
                "network_compare_table.html is generated with side-by-side metrics tables and scatter plots."
            ),
        )

    def _validate_settings(self, communities_strategy: list[str], network_measures: list[str]) -> str | None:
        """Validate all settings. Raises CommandError on failure. Returns the BRIDGING token or None."""
        if settings.LAYOUT not in (layout.LAYOUT_HORIZONTAL, layout.LAYOUT_VERTICAL):
            raise CommandError(f"Invalid LAYOUT value: {settings.LAYOUT!r}. Choose HORIZONTAL or VERTICAL.")

        invalid_strategies = [s for s in communities_strategy if s not in community.VALID_STRATEGIES]
        if invalid_strategies:
            raise CommandError(
                f"Invalid COMMUNITY_STRATEGIES value(s): {invalid_strategies!r}. "
                f"Choose from {sorted(community.VALID_STRATEGIES) + ['ALL']}."
            )
        invalid_measures = [m for m in network_measures if not measures.is_valid_measure(m)]
        if invalid_measures:
            valid_display = sorted(measures.VALID_MEASURES) + ["ALL", "BRIDGING", "BRIDGING(<STRATEGY>)"]
            raise CommandError(f"Invalid NETWORK_MEASURES value(s): {invalid_measures!r}. Choose from {valid_display}.")
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
                    f"BRIDGING community basis {bstrategy!r} is not in COMMUNITY_STRATEGIES. "
                    f"Add it or change the BRIDGING strategy."
                )
        invalid_channel_types = [t for t in settings.CHANNEL_TYPES if t not in VALID_CHANNEL_TYPES]
        if invalid_channel_types:
            raise CommandError(
                f"Invalid CHANNEL_TYPES value(s): {invalid_channel_types!r}. Choose from {sorted(VALID_CHANNEL_TYPES)}."
            )
        if settings.EDGE_WEIGHT_STRATEGY not in VALID_EDGE_WEIGHT_STRATEGIES:
            raise CommandError(
                f"Invalid EDGE_WEIGHT_STRATEGY value: {settings.EDGE_WEIGHT_STRATEGY!r}. "
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

    def handle(self, *args: Any, **options: Any) -> None:
        communities_strategy = (
            measures.ALL_STRATEGIES if "ALL" in settings.COMMUNITY_STRATEGIES else settings.COMMUNITY_STRATEGIES
        )
        network_measures = measures.ALL_MEASURES if "ALL" in settings.NETWORK_MEASURES else settings.NETWORK_MEASURES
        bridging_token = self._validate_settings(communities_strategy, network_measures)
        selected_measures = set(network_measures)

        do_graph = options["graph"]
        do_3dgraph = options["graph_3d"]
        do_html = options["html"]
        do_xlsx = options["xlsx"]
        do_gexf = options["gexf"]
        do_graphml = options["graphml"]

        seo = options["seo"]
        start_date = self._parse_date(options["startdate"], "--startdate")
        end_date = self._parse_date(options["enddate"], "--enddate")
        compare_data_dir = options["compare"]
        if compare_data_dir is not None:
            compare_data_dir = os.path.abspath(compare_data_dir)
            if not os.path.isdir(compare_data_dir):
                raise CommandError(f"--compare: not a directory: {compare_data_dir!r}")
            if not os.path.isfile(os.path.join(compare_data_dir, "index.html")):
                raise CommandError(
                    f"--compare: {compare_data_dir!r} does not look like a graph/ output directory "
                    "(no index.html found). Point to the directory that contains index.html."
                )

        self.stdout.write("Create graph … ", ending="")
        self.stdout.flush()
        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=settings.DRAW_DEAD_LEAVES,
                start_date=start_date,
                end_date=end_date,
                recency_weights=settings.RECENCY_WEIGHTS,
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")

        self.stdout.write("Calculate communities")
        strategy_results: dict[str, tuple] = {}
        for strategy in communities_strategy:
            self.stdout.write(f"- {strategy.lower()} … ", ending="")
            self.stdout.flush()
            try:
                community_map, community_palette = community.detect(
                    strategy, settings.COMMUNITY_PALETTE, graph, channel_dict
                )
            except ValueError as e:
                raise CommandError(str(e)) from e
            community.apply_to_graph(graph, channel_dict, community_map, community_palette, strategy)
            strategy_results[strategy] = (community_map, community_palette)
            n_communities = len(set(community_map.values()))
            self.stdout.write(f"{n_communities} communities")
        community.apply_edge_colors(graph, edge_list, channel_dict)

        positions_3d: dict | None = None
        if do_graph or do_3dgraph:
            self.stdout.write("\nSet spatial distribution of nodes")
            self.stdout.write("- Kamada-Kawai … ", ending="")
            self.stdout.flush()
            initial_pos = layout.kamada_kawai_positions(graph)
            self.stdout.write("done")
            self.stdout.write(f"- ForceAtlas2 ({settings.FA2_ITERATIONS} iterations) … ", ending="")
            self.stdout.flush()
            positions = layout.forceatlas2_positions(graph, initial_pos, settings.FA2_ITERATIONS)
            self.stdout.write("done")

            xs, ys = zip(*positions.values(), strict=False)
            width = max(xs) - min(xs)
            height = max(ys) - min(ys)
            if (settings.LAYOUT == layout.LAYOUT_HORIZONTAL and height > width) or (
                settings.LAYOUT == layout.LAYOUT_VERTICAL and width > height
            ):
                self.stdout.write("- rotating layout 90°")
                positions = layout.rotate_positions(positions)

            if do_3dgraph:
                self.stdout.write("- Kamada-Kawai 3D … ", ending="")
                self.stdout.flush()
                initial_pos_3d = layout.kamada_kawai_positions_3d(graph)
                self.stdout.write("done")
                self.stdout.write(f"- ForceAtlas2 3D ({settings.FA2_ITERATIONS} iterations) … ", ending="")
                self.stdout.flush()
                positions_3d = layout.forceatlas2_positions_3d(graph, initial_pos_3d, settings.FA2_ITERATIONS)
                self.stdout.write("done")
        else:
            positions = {}

        self.stdout.write("\nCalculations on the graph")
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)

        self.stdout.write("- largest component … ", ending="")
        self.stdout.flush()
        main_component = exporter.find_main_component(graph)
        self.stdout.write(f"{len(main_component)} nodes")

        self.stdout.write("- degrees, activity and fans")
        measures_labels = measures.apply_base_node_measures(
            graph_data, graph, channel_dict, start_date=start_date, end_date=end_date
        )

        # Pre-compute betweenness once when both BETWEENNESS and BRIDGING are active.
        _cached_betweenness: "dict | None" = None
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
                lambda gd, g: measures.apply_spreading_efficiency(gd, g, runs=settings.SPREADING_RUNS),
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
            exporter.reposition_isolated_nodes(graph_data, main_component)

        root_target = settings.GRAPH_OUTPUT_DIR
        project_title: str = settings.PROJECT_TITLE
        communities_data = community.build_communities_payload(communities_strategy, strategy_results)

        if do_graph or do_3dgraph:
            self.stdout.write("\nGenerate map")
            exporter.ensure_graph_root(root_target)
            self.stdout.write("- config files")
            exporter.apply_robots_to_graph_html(root_target, seo, project_title=project_title, include_3d=do_3dgraph)
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

        strategies = [s.lower() for s in communities_strategy]
        if do_html or do_xlsx:
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
            )
        if do_html:
            self.stdout.write("- table (html)")
            tables.write_table_html(
                graph_data,
                output_filename=os.path.join(root_target, "channel_table.html"),
                seo=seo,
                project_title=project_title,
            )
            self.stdout.write("- network table (html)")
            tables.write_network_metrics_json(community_table_data, strategies, graph_dir=root_target)
            tables.write_network_table_html(
                output_filename=os.path.join(root_target, "network_table.html"),
                seo=seo,
                project_title=project_title,
            )
            self.stdout.write("- community table (html)")
            tables.write_community_metrics_json(community_table_data, strategies, graph_dir=root_target)
            tables.write_community_table_html(
                output_filename=os.path.join(root_target, "community_table.html"),
                seo=seo,
                project_title=project_title,
            )
        if do_xlsx:
            self.stdout.write("- table (xlsx)")
            tables.write_table_xlsx(
                graph_data,
                measures_labels,
                strategies,
                output_filename=os.path.join(root_target, "channel_table.xlsx"),
                project_title=project_title,
            )
            self.stdout.write("- network table (xlsx)")
            tables.write_network_table_xlsx(
                community_table_data,
                strategies,
                output_filename=os.path.join(root_target, "network_table.xlsx"),
                project_title=project_title,
            )
            self.stdout.write("- community table (xlsx)")
            tables.write_community_table_xlsx(
                community_table_data,
                strategies,
                output_filename=os.path.join(root_target, "community_table.xlsx"),
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

        compare_files: set[str] = set()
        if compare_data_dir is not None:
            self.stdout.write("- compare network files")
            compare_files = tables.copy_compare_project(compare_data_dir, root_target)
            self.stdout.write("- network compare table (html)")
            tables.write_network_compare_table_html(
                output_filename=os.path.join(root_target, "network_compare_table.html"),
                seo=seo,
                project_title=project_title,
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
            include_compare_html=compare_data_dir is not None,
            compare_files=compare_files,
            strategies=strategies,
        )

        self.stdout.write(self.style.SUCCESS("\nDone."))
