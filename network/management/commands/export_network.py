import datetime
import os
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import community, community_stats, exporter, graph_builder, layout, measures, tables
from network.graph_builder import VALID_EDGE_WEIGHT_STRATEGIES
from webapp.utils.channel_types import VALID_CHANNEL_TYPES

TABLE_FORMAT_CHOICES = ["none", "html", "xlsx", "html+xlsx"]


class Command(BaseCommand):
    args = ""
    help = "write file"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--table-format",
            choices=TABLE_FORMAT_CHOICES,
            default="html",
            help='Tabular output format alongside the graph: "html" (default), "xlsx", "html+xlsx", or "none".',
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
            "--nograph",
            action="store_true",
            default=False,
            help=(
                "Skip the graph mini-site: no layout computation, no graph.html, no media copy. "
                "Only tabular output (channel_table / community_table) is produced. "
                "Implies --table-format html+xlsx unless --table-format is set explicitly."
            ),
        )
        parser.add_argument(
            "--3d",
            action="store_true",
            default=False,
            dest="graph_3d",
            help=(
                "Also produce a 3D graph visualisation (graph3d.html). "
                "ForceAtlas2 runs in 3D using the vectorised O(n²) back-end "
                "(Barnes-Hut is 2D-only), so this is slower on large graphs."
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

        nograph = options["nograph"]
        seo = options["seo"]
        graph_3d = options["graph_3d"]
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
        if not nograph:
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

            if graph_3d:
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
        ]
        for key, label, fn in [*measures.MEASURE_STEPS, *_orm_steps]:
            if key in selected_measures:
                self.stdout.write(f"- {label} … ", ending="")
                self.stdout.flush()
                measures_labels += (getattr(measures, fn) if isinstance(fn, str) else fn)(graph_data, graph)
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
            measures_labels += measures.apply_bridging_centrality(graph_data, graph, strategy_key)
            self.stdout.write("done")

        if not nograph:
            self.stdout.write("- small components")
            exporter.reposition_isolated_nodes(graph_data, main_component)

        root_target = settings.GRAPH_OUTPUT_DIR
        project_title: str = settings.PROJECT_TITLE
        communities_data = community.build_communities_payload(communities_strategy, strategy_results)

        if not nograph:
            self.stdout.write("\nGenerate map")
            exporter.ensure_graph_root(root_target)
            self.stdout.write("- config files")
            exporter.apply_robots_to_graph_html(root_target, seo, project_title=project_title, include_3d=graph_3d)
            exporter.write_robots_txt(root_target, seo)

        self.stdout.write("- data files")
        exporter.write_graph_files(
            graph_data,
            communities_data,
            measures_labels,
            channel_qs,
            graph_dir=root_target,
            include_positions=not nograph,
            positions_3d=positions_3d,
        )

        table_format = options["table_format"]
        strategies = [s.lower() for s in communities_strategy]
        if "html" in table_format or "xlsx" in table_format:
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
        if "html" in table_format:
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
        if "xlsx" in table_format:
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

        if not nograph:
            self.stdout.write("- media")
            exporter.copy_channel_media(channel_qs, root_target)

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
            include_graph=not nograph,
            include_3d_graph=not nograph and graph_3d,
            include_channel_html="html" in table_format,
            include_channel_xlsx="xlsx" in table_format,
            include_network_html="html" in table_format,
            include_network_xlsx="xlsx" in table_format,
            include_community_html="html" in table_format,
            include_community_xlsx="xlsx" in table_format,
            include_compare_html=compare_data_dir is not None,
            compare_files=compare_files,
            strategies=strategies,
        )

        self.stdout.write(self.style.SUCCESS("\nDone."))
