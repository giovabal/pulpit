from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import community, exporter, graph_builder, layout


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.LAYOUT not in (layout.LAYOUT_HORIZONTAL, layout.LAYOUT_VERTICAL):
            raise CommandError(f"Invalid LAYOUT value: {settings.LAYOUT!r}. Choose HORIZONTAL or VERTICAL.")
        invalid_strategies = [s for s in settings.COMMUNITIES_STRATEGY if s not in community.VALID_STRATEGIES]
        if invalid_strategies:
            raise CommandError(
                f"Invalid COMMUNITIES_STRATEGY value(s): {invalid_strategies!r}. "
                f"Choose from {sorted(community.VALID_STRATEGIES)}."
            )

        self.stdout.write("Create graph")
        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=settings.DRAW_DEAD_LEAVES,
            )
        except ValueError as e:
            raise CommandError(str(e)) from e

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

        self.stdout.write("\nSet spatial distribution of nodes")
        positions = layout.compute_layout(graph, settings.FA2_ITERATIONS)

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
        communities_data = community.build_communities_payload(settings.COMMUNITIES_STRATEGY, strategy_results)
        exporter.write_graph_files(
            graph_data,
            communities_data,
            measures_labels,
            channel_qs,
            output_filename="graph/telegram_graph/data.json",
            accessory_filename="graph/telegram_graph/data_accessory.json",
        )

        self.stdout.write("- media")
        exporter.copy_channel_media(channel_qs, "graph/telegram_graph")
