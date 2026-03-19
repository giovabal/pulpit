import datetime
import re
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import community, exporter, graph_builder, layout
from webapp.utils.channel_types import VALID_CHANNEL_TYPES

VALID_MEASURES = {
    "PAGERANK",
    "HITSHUB",
    "HITSAUTH",
    "BETWEENNESS",
    "INDEGCENTRALITY",
    "OUTDEGCENTRALITY",
    "HARMONICCENTRALITY",
    "KATZ",
}

_BRIDGING_RE = re.compile(r"^BRIDGING(?:\(([A-Z]+)\))?$")
_BRIDGING_DEFAULT_STRATEGY = "LEIDEN"

# Expansion targets for the ALL shortcut
_ALL_MEASURES = [*sorted(VALID_MEASURES), "BRIDGING"]
_ALL_STRATEGIES = ["ORGANIZATION", "LEIDEN", "LOUVAIN", "KCORE", "INFOMAP"]


def _is_valid_measure(token: str) -> bool:
    return token in VALID_MEASURES or bool(_BRIDGING_RE.match(token))


def _find_bridging_token(measures: list[str]) -> str | None:
    return next((m for m in measures if _BRIDGING_RE.match(m)), None)


def _bridging_strategy(token: str) -> str:
    """Return the community strategy encoded in a BRIDGING token (defaults to LEIDEN)."""
    m = _BRIDGING_RE.match(token)
    return (m.group(1) or _BRIDGING_DEFAULT_STRATEGY) if m else _BRIDGING_DEFAULT_STRATEGY


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

    def _parse_date(self, value: str | None, flag: str) -> datetime.date | None:
        if value is None:
            return None
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as err:
            raise CommandError(f"Invalid date for {flag}: {value!r}. Expected format: yyyy-mm-dd.") from err

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.LAYOUT not in (layout.LAYOUT_HORIZONTAL, layout.LAYOUT_VERTICAL):
            raise CommandError(f"Invalid LAYOUT value: {settings.LAYOUT!r}. Choose HORIZONTAL or VERTICAL.")

        communities_strategy = (
            _ALL_STRATEGIES if "ALL" in settings.COMMUNITY_STRATEGIES else settings.COMMUNITY_STRATEGIES
        )
        network_measures = _ALL_MEASURES if "ALL" in settings.NETWORK_MEASURES else settings.NETWORK_MEASURES

        invalid_strategies = [s for s in communities_strategy if s not in community.VALID_STRATEGIES]
        if invalid_strategies:
            raise CommandError(
                f"Invalid COMMUNITY_STRATEGIES value(s): {invalid_strategies!r}. "
                f"Choose from {sorted(community.VALID_STRATEGIES) + ['ALL']}."
            )
        invalid_measures = [m for m in network_measures if not _is_valid_measure(m)]
        if invalid_measures:
            valid_display = sorted(VALID_MEASURES) + ["ALL", "BRIDGING", "BRIDGING(<STRATEGY>)"]
            raise CommandError(f"Invalid NETWORK_MEASURES value(s): {invalid_measures!r}. Choose from {valid_display}.")
        bridging_token = _find_bridging_token(network_measures)
        if bridging_token is not None:
            bstrategy = _bridging_strategy(bridging_token)
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
        measures = set(network_measures)

        seo = options["seo"]
        start_date = self._parse_date(options["startdate"], "--startdate")
        end_date = self._parse_date(options["enddate"], "--enddate")

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

        self.stdout.write("\nCalculations on the graph")
        graph_data = exporter.build_graph_data(graph, channel_dict, positions)

        self.stdout.write("- largest component … ", ending="")
        self.stdout.flush()
        main_component = exporter.find_main_component(graph)
        self.stdout.write(f"{len(main_component)} nodes")

        self.stdout.write("- degrees, activity and fans")
        measures_labels = exporter.apply_base_node_measures(
            graph_data, graph, channel_dict, start_date=start_date, end_date=end_date
        )

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

        if "OUTDEGCENTRALITY" in measures:
            self.stdout.write("- out-degree centrality … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_out_degree_centrality(graph_data, graph)
            self.stdout.write("done")

        if "HARMONICCENTRALITY" in measures:
            self.stdout.write("- harmonic centrality … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_harmonic_centrality(graph_data, graph)
            self.stdout.write("done")

        if "KATZ" in measures:
            self.stdout.write("- Katz centrality … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_katz_centrality(graph_data, graph)
            self.stdout.write("done")

        if bridging_token is not None:
            strategy_key = _bridging_strategy(bridging_token).lower()
            self.stdout.write(f"- bridging centrality (community basis: {strategy_key}) … ", ending="")
            self.stdout.flush()
            measures_labels += exporter.apply_bridging_centrality(graph_data, graph, strategy_key)
            self.stdout.write("done")

        self.stdout.write("- small components")
        exporter.reposition_isolated_nodes(graph_data, main_component)

        self.stdout.write("\nGenerate map")
        root_target = "graph"
        exporter.ensure_graph_root(root_target)

        self.stdout.write("- config files")
        exporter.apply_robots_to_graph_html(root_target, seo)
        exporter.write_robots_txt(root_target, seo)
        communities_data = community.build_communities_payload(communities_strategy, strategy_results)
        exporter.write_graph_files(
            graph_data,
            communities_data,
            measures_labels,
            channel_qs,
            output_filename="graph/data.json",
            accessory_filename="graph/data_accessory.json",
        )

        table_format = options["table_format"]
        strategies = [s.lower() for s in communities_strategy]
        if "html" in table_format:
            self.stdout.write("- table (html)")
            exporter.write_table_html(
                graph_data, measures_labels, strategies, output_filename="graph/channel_table.html", seo=seo
            )
            self.stdout.write("- community table (html)")
            exporter.write_community_table_html(
                graph_data, communities_data, graph, strategies, output_filename="graph/community_table.html", seo=seo
            )
        if "xls" in table_format:
            self.stdout.write("- table (xls)")
            exporter.write_table_xls(
                graph_data, measures_labels, strategies, output_filename="graph/channel_table.xlsx"
            )
            self.stdout.write("- community table (xls)")
            exporter.write_community_table_xls(
                graph_data, communities_data, graph, strategies, output_filename="graph/community_table.xlsx"
            )

        self.stdout.write("- media")
        exporter.copy_channel_media(channel_qs, "graph")

        self.stdout.write(self.style.SUCCESS("\nDone."))
