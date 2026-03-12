from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import community, exporter, graph_builder, layout
from webapp.utils.channel_types import VALID_CHANNEL_TYPES

VALID_MEASURES = {"PAGERANK", "HITSHUB", "HITSAUTH", "BETWEENNESS", "INDEGCENTRALITY"}


TABLE_FORMAT_CHOICES = ["none", "html", "xls", "html+xls"]


class Command(BaseCommand):
    args = ""
    help = "write file"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--table-format",
            choices=TABLE_FORMAT_CHOICES,
            default="html",
            help='Tabular output format alongside the graph: "html" (default), "xls", "html+xls", or "none".',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.LAYOUT not in (layout.LAYOUT_HORIZONTAL, layout.LAYOUT_VERTICAL):
            raise CommandError(f"Invalid LAYOUT value: {settings.LAYOUT!r}. Choose HORIZONTAL or VERTICAL.")
        invalid_strategies = [s for s in settings.COMMUNITIES_STRATEGY if s not in community.VALID_STRATEGIES]
        if invalid_strategies:
            raise CommandError(
                f"Invalid COMMUNITIES_STRATEGY value(s): {invalid_strategies!r}. "
                f"Choose from {sorted(community.VALID_STRATEGIES)}."
            )
        invalid_measures = [m for m in settings.NETWORK_MEASURES if m not in VALID_MEASURES]
        if invalid_measures:
            raise CommandError(
                f"Invalid NETWORK_MEASURES value(s): {invalid_measures!r}. Choose from {sorted(VALID_MEASURES)}."
            )
        invalid_channel_types = [t for t in settings.CHANNEL_TYPES if t not in VALID_CHANNEL_TYPES]
        if invalid_channel_types:
            raise CommandError(
                f"Invalid CHANNEL_TYPES value(s): {invalid_channel_types!r}. Choose from {sorted(VALID_CHANNEL_TYPES)}."
            )
        measures = set(settings.NETWORK_MEASURES)

        self.stdout.write("Create graph … ", ending="")
        self.stdout.flush()
        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=settings.DRAW_DEAD_LEAVES,
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")

        self.stdout.write("Calculate communities")
        strategy_results: dict[str, tuple] = {}
        for strategy in settings.COMMUNITIES_STRATEGY:
            self.stdout.write(f"- {strategy.lower()} … ", ending="")
            self.stdout.flush()
            try:
                community_map, community_palette = community.detect(
                    strategy, settings.COMMUNITIES_PALETTE, graph, channel_dict
                )
            except ValueError as e:
                raise CommandError(str(e)) from e
            community.apply_to_graph(graph, channel_dict, community_map, community_palette, strategy)
            strategy_results[strategy] = (community_map, community_palette)
            n_communities = len(set(community_map.values()))
            self.stdout.write(f"{n_communities} communities")
        community.apply_edge_colors(graph, edge_list, channel_dict)

        self.stdout.write(
            f"\nSet spatial distribution of nodes ({settings.FA2_ITERATIONS} FA2 iterations) … ", ending=""
        )
        self.stdout.flush()
        positions = layout.compute_layout(graph, settings.FA2_ITERATIONS)
        self.stdout.write("done")

        xs, ys = zip(*positions.values(), strict=False)
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if (settings.LAYOUT == layout.LAYOUT_HORIZONTAL and height > width) or (
            settings.LAYOUT == layout.LAYOUT_VERTICAL and width > height
        ):
            self.stdout.write("- rotating layout 90°")
            positions = layout.rotate_positions(positions)

        self.stdout.write("\nCalculations on the graph")
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)

        self.stdout.write("- largest component … ", ending="")
        self.stdout.flush()
        main_component = exporter.find_main_component(graph)
        self.stdout.write(f"{len(main_component)} nodes")

        self.stdout.write("- degrees, activity and fans")
        measures_labels = exporter.apply_base_node_measures(graph_data, graph, channel_dict)

        if "PAGERANK" in measures:
            self.stdout.write("- pagerank … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_pagerank(graph_data, graph)
            self.stdout.write("done")

        if measures & {"HITSHUB", "HITSAUTH"}:
            self.stdout.write("- HITS … ", ending="")
            self.stdout.flush()
            hits_labels = exporter.apply_hits(graph_data, graph)
            _hits_key_map = {"hits_hub": "HITSHUB", "hits_authority": "HITSAUTH"}
            measures_labels += [(k, label) for k, label in hits_labels if _hits_key_map[k] in measures]
            self.stdout.write("done")

        if "BETWEENNESS" in measures:
            self.stdout.write("- betweenness centrality … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_betweenness_centrality(graph_data, graph)
            self.stdout.write("done")

        if "INDEGCENTRALITY" in measures:
            self.stdout.write("- in-degree centrality … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_in_degree_centrality(graph_data, graph)
            self.stdout.write("done")

        self.stdout.write("- small components")
        exporter.reposition_isolated_nodes(graph_data, main_component)

        self.stdout.write("\nGenerate map")
        root_target = "graph"
        exporter.ensure_graph_root(root_target)

        self.stdout.write("- config files")
        communities_data = community.build_communities_payload(settings.COMMUNITIES_STRATEGY, strategy_results)
        exporter.write_graph_files(
            graph_data,
            communities_data,
            measures_labels,
            channel_qs,
            output_filename="graph/data.json",
            accessory_filename="graph/data_accessory.json",
        )

        table_format = options["table_format"]
        strategies = [s.lower() for s in settings.COMMUNITIES_STRATEGY]
        if "html" in table_format:
            self.stdout.write("- table (html)")
            exporter.write_table_html(graph_data, measures_labels, strategies, output_filename="graph/table.html")
        if "xls" in table_format:
            self.stdout.write("- table (xls)")
            exporter.write_table_xls(graph_data, measures_labels, strategies, output_filename="graph/table.xlsx")

        self.stdout.write("- media")
        exporter.copy_channel_media(channel_qs, "graph")

        self.stdout.write(self.style.SUCCESS("\nDone."))
