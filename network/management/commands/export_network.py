from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import community, exporter, graph_builder, layout


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write("Create graph")
        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=settings.DRAW_DEAD_LEAVES,
            )
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write("Calculate communities")
        community_map, community_palette = community.detect(
            settings.COMMUNITIES, settings.COMMUNITIES_PALETTE, graph, channel_dict
        )
        community.apply_to_graph(graph, channel_dict, community_map, community_palette, settings.COMMUNITIES)
        community.apply_edge_colors(graph, edge_list, channel_dict)

        self.stdout.write("\nSet spatial distribution of nodes")
        positions = layout.compute_layout(graph, settings.FA2_ITERATIONS)

        self.stdout.write("\nCalculations on the graph")
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)

        self.stdout.write("- largest component")
        main_component = exporter.find_main_component(graph)

        self.stdout.write("- degrees, activity and fans")
        measures_labels = exporter.apply_base_node_measures(graph_data, graph, channel_dict)

        self.stdout.write("- pagerank")
        measures_labels += exporter.apply_pagerank(graph_data, graph)

        self.stdout.write("- small components")
        exporter.reposition_isolated_nodes(graph_data, main_component)

        self.stdout.write("\nGenerate map")
        root_target = "graph"
        exporter.ensure_graph_root(root_target)

        self.stdout.write("- config files")
        group_data = community.build_group_payload(settings.COMMUNITIES, community_map, community_palette)
        exporter.write_graph_files(
            graph_data,
            group_data,
            measures_labels,
            channel_qs,
            output_filename="graph/telegram_graph/data.json",
            accessory_filename="graph/telegram_graph/data_accessory.json",
        )

        self.stdout.write("- media")
        exporter.copy_channel_media(channel_qs, "graph/telegram_graph")
