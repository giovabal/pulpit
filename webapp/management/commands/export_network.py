from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.relational_graph import RelationalGraph


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args, **options):
        print("Create graph")
        g = RelationalGraph(settings.COMMUNITIES, settings.COMMUNITIES_PALETTE, settings.DRAW_DEAD_LEAVES)

        print("Calculate communities")
        g.set_communities()
        g.apply_palette_colors()

        print("\nSet spatial distribution of nodes")
        g.set_layout_positions(settings.FA2_ITERATIONS)

        print("\nCalculations on the graph")
        g.set_data()

        print("- largest component")
        g.set_main_component()

        print("- degrees, activity and fans")
        g.apply_base_node_measures()

        print("- pagerank")
        g.apply_pagerank()

        print("- small components")
        g.reposition_isolated_nodes()

        print("\nGenerate map")
        root_target = "graph"
        g.ensure_graph_root(root_target)

        print("- config files")
        output_filename = "graph/telegram_graph/data.json"
        g.build_group_payload()
        accessory_filename = "graph/telegram_graph/data_accessory.json"
        g.write_graph_files(output_filename, accessory_filename)

        print("- media")
        root_target = "graph/telegram_graph"
        g.copy_channel_media(root_target)
