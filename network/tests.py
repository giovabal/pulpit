import datetime
import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from network.community import (
    COMMUNITY_ALGORITHMS,
    apply_edge_colors,
    apply_to_graph,
    build_communities_payload,
    build_community_label,
    build_community_palette,
    detect_infomap,
    detect_kcore,
    detect_label_propagation,
    detect_leiden,
    detect_louvain,
    detect_organization,
    normalize_community_map,
)
from network.community_stats import (
    _freeman_centralization,
    _network_summary,
    compute_community_metrics,
    network_summary_rows,
)
from network.exporter import (
    build_graph_data,
    ensure_graph_root,
    find_main_component,
    reposition_isolated_nodes,
    write_graph_files,
)
from network.graph_builder import build_graph
from network.layout import compute_layout
from network.measures import (
    apply_amplification_factor,
    apply_base_node_measures,
    apply_betweenness_centrality,
    apply_bridging_centrality,
    apply_burt_constraint,
    apply_closeness_centrality,
    apply_content_originality,
    apply_ego_network_density,
    apply_flow_betweenness_centrality,
    apply_harmonic_centrality,
    apply_hits,
    apply_in_degree_centrality,
    apply_katz_centrality,
    apply_local_clustering,
    apply_out_degree_centrality,
    apply_pagerank,
    apply_spreading_efficiency,
    compute_betweenness,
)
from webapp.models import Channel, Message, Organization
from webapp.utils.colors import parse_color

import networkx as nx
import numpy as np

# ---------------------------------------------------------------------------
# community.py — normalize_community_map
# ---------------------------------------------------------------------------


class NormalizeCommunityMapTests(TestCase):
    def test_empty_map_returns_empty(self) -> None:
        self.assertEqual(normalize_community_map({}), {})

    def test_single_node_maps_to_community_1(self) -> None:
        result = normalize_community_map({"a": 5})
        self.assertEqual(result, {"a": 1})

    def test_largest_community_gets_id_1(self) -> None:
        # community 99 has 2 nodes, community 1 has 1 node
        result = normalize_community_map({"x": 99, "y": 99, "z": 1})
        self.assertEqual(result["x"], 1)
        self.assertEqual(result["y"], 1)
        self.assertEqual(result["z"], 2)

    def test_tie_broken_by_original_community_id_ascending(self) -> None:
        # Two communities of equal size (1 each); lower original id gets remapped first
        result = normalize_community_map({"a": 10, "b": 20})
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)

    def test_all_original_nodes_preserved(self) -> None:
        original = {"n1": 3, "n2": 3, "n3": 7, "n4": 7, "n5": 9}
        result = normalize_community_map(original)
        self.assertEqual(set(result.keys()), set(original.keys()))

    def test_community_ids_start_at_1(self) -> None:
        result = normalize_community_map({"a": 10, "b": 20, "c": 30})
        self.assertGreaterEqual(min(result.values()), 1)


# ---------------------------------------------------------------------------
# community.py — build_community_label
# ---------------------------------------------------------------------------


class BuildCommunityLabelTests(TestCase):
    def test_integer_id_with_algorithm_strategy(self) -> None:
        self.assertEqual(build_community_label(1, "LOUVAIN"), "1-louvain")

    def test_string_id_with_organization_strategy(self) -> None:
        self.assertEqual(build_community_label("my-org", "ORGANIZATION"), "my-org-organization")

    def test_spaces_become_hyphens_via_slugify(self) -> None:
        self.assertEqual(build_community_label("Foo Bar", "TEST"), "foo-bar-test")

    def test_uppercase_strategy_lowercased(self) -> None:
        label = build_community_label(5, "KCORE")
        self.assertIn("kcore", label)


# ---------------------------------------------------------------------------
# community.py — build_community_palette
# ---------------------------------------------------------------------------


class BuildCommunityPaletteTests(TestCase):
    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_empty_community_map_returns_empty(self, _mock: MagicMock) -> None:
        result = build_community_palette({}, "SomePalette")
        self.assertEqual(result, {})

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00"])
    def test_returns_one_entry_per_community(self, _mock: MagicMock) -> None:
        community_map = {"a": 1, "b": 2}
        result = build_community_palette(community_map, "SomePalette")
        self.assertIn(1, result)
        self.assertIn(2, result)
        self.assertEqual(len(result), 2)

    @patch("network.community.palette_colors", return_value=["#ff0000"])
    def test_palette_values_are_three_int_tuples(self, _mock: MagicMock) -> None:
        community_map = {"a": 1}
        result = build_community_palette(community_map, "SomePalette")
        color = result[1]
        self.assertIsInstance(color, tuple)
        self.assertEqual(len(color), 3)
        self.assertTrue(all(isinstance(c, int) for c in color))

    @patch("network.community.palette_colors", return_value=["#ff0000"])
    def test_expands_colors_when_fewer_palette_entries_than_communities(self, _mock: MagicMock) -> None:
        community_map = {"a": 1, "b": 2, "c": 3}
        result = build_community_palette(community_map, "SomePalette")
        self.assertEqual(set(result.keys()), {1, 2, 3})

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_canonical_order_when_reverse_false(self, _mock: MagicMock) -> None:
        community_map = {"a": 1, "b": 2, "c": 3}
        result = build_community_palette(community_map, "vaporwave")
        self.assertEqual(result[1], parse_color("#ff0000"))
        self.assertEqual(result[2], parse_color("#00ff00"))
        self.assertEqual(result[3], parse_color("#0000ff"))

    def test_reverse_kwarg_forwards_to_palette_colors(self) -> None:
        # palette_colors honours its own ``reverse`` kwarg (it forwards it to
        # pypalettes.load_palette); build_community_palette only has to pass it through.
        community_map = {"a": 1, "b": 2, "c": 3}
        with patch("network.community.palette_colors") as mock:
            mock.return_value = ["#0000ff", "#00ff00", "#ff0000"]
            result = build_community_palette(community_map, "vaporwave", reverse=True)
        mock.assert_called_once_with("vaporwave", reverse=True)
        self.assertEqual(result[1], parse_color("#0000ff"))
        self.assertEqual(result[3], parse_color("#ff0000"))


# ---------------------------------------------------------------------------
# community.py — detect_organization
# ---------------------------------------------------------------------------


class DetectOrganizationTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Test Org", is_in_target=True, color="#FF0000")
        self.ch1 = Channel.objects.create(telegram_id=1, organization=self.org)
        self.ch2 = Channel.objects.create(telegram_id=2, organization=self.org)

    def test_maps_channels_to_org_id(self) -> None:
        channel_dict = {
            str(self.ch1.pk): {"channel": self.ch1, "data": {}},
            str(self.ch2.pk): {"channel": self.ch2, "data": {}},
        }
        community_map, _ = detect_organization(channel_dict)
        self.assertEqual(community_map[str(self.ch1.pk)], self.org.pk)
        self.assertEqual(community_map[str(self.ch2.pk)], self.org.pk)

    def test_channel_without_org_excluded_from_map(self) -> None:
        ch3 = Channel.objects.create(telegram_id=3, organization=None)
        channel_dict = {str(ch3.pk): {"channel": ch3, "data": {}}}
        community_map, _ = detect_organization(channel_dict)
        self.assertNotIn(str(ch3.pk), community_map)

    def test_palette_uses_org_color(self) -> None:
        channel_dict = {str(self.ch1.pk): {"channel": self.ch1, "data": {}}}
        _, palette = detect_organization(channel_dict)
        expected = parse_color(self.org.color)
        self.assertEqual(palette[self.org.pk], expected)

    def test_palette_has_one_entry_per_unique_org(self) -> None:
        org2 = Organization.objects.create(name="Org2", is_in_target=True, color="#0000FF")
        ch4 = Channel.objects.create(telegram_id=4, organization=org2)
        channel_dict = {
            str(self.ch1.pk): {"channel": self.ch1, "data": {}},
            str(ch4.pk): {"channel": ch4, "data": {}},
        }
        _, palette = detect_organization(channel_dict)
        self.assertEqual(len(palette), 2)


# ---------------------------------------------------------------------------
# community.py — detect_label_propagation
# ---------------------------------------------------------------------------


class DetectLabelPropagationTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b", "c", "d"])
        self.graph.add_edges_from([("a", "b"), ("b", "c"), ("c", "a"), ("d", "a")])

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_returns_community_map_and_palette(self, _mock: MagicMock) -> None:
        community_map, palette = detect_label_propagation(self.graph, "SomePalette")
        self.assertIsInstance(community_map, dict)
        self.assertIsInstance(palette, dict)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_all_nodes_assigned(self, _mock: MagicMock) -> None:
        community_map, _ = detect_label_propagation(self.graph, "SomePalette")
        self.assertEqual(set(community_map.keys()), set(self.graph.nodes()))

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_community_ids_start_at_1(self, _mock: MagicMock) -> None:
        community_map, _ = detect_label_propagation(self.graph, "SomePalette")
        self.assertGreaterEqual(min(community_map.values()), 1)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_palette_covers_all_detected_communities(self, _mock: MagicMock) -> None:
        community_map, palette = detect_label_propagation(self.graph, "SomePalette")
        for community_id in community_map.values():
            self.assertIn(community_id, palette)


# community.py — detect_louvain
# ---------------------------------------------------------------------------


class DetectLouvainTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b", "c", "d"])
        self.graph.add_edges_from([("a", "b"), ("b", "c"), ("c", "a"), ("d", "a")])

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_returns_community_map_and_palette(self, _mock: MagicMock) -> None:
        community_map, palette = detect_louvain(self.graph, "SomePalette")
        self.assertIsInstance(community_map, dict)
        self.assertIsInstance(palette, dict)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_all_nodes_assigned(self, _mock: MagicMock) -> None:
        community_map, _ = detect_louvain(self.graph, "SomePalette")
        self.assertEqual(set(community_map.keys()), set(self.graph.nodes()))

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_community_ids_start_at_1(self, _mock: MagicMock) -> None:
        community_map, _ = detect_louvain(self.graph, "SomePalette")
        self.assertGreaterEqual(min(community_map.values()), 1)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_palette_covers_all_detected_communities(self, _mock: MagicMock) -> None:
        community_map, palette = detect_louvain(self.graph, "SomePalette")
        for community_id in community_map.values():
            self.assertIn(community_id, palette)


# ---------------------------------------------------------------------------
# community.py — detect_kcore
# ---------------------------------------------------------------------------


class DetectKcoreTests(TestCase):
    def setUp(self) -> None:
        # Triangle a-b-c has coreness 2; d is a leaf with coreness 1
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b", "c", "d"])
        self.graph.add_edges_from([("a", "b"), ("b", "c"), ("c", "a"), ("a", "d")])

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00"])
    def test_all_nodes_assigned(self, _mock: MagicMock) -> None:
        community_map, _ = detect_kcore(self.graph, "SomePalette")
        self.assertEqual(set(community_map.keys()), set(self.graph.nodes()))

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00"])
    def test_shells_produce_distinct_communities(self, _mock: MagicMock) -> None:
        community_map, _ = detect_kcore(self.graph, "SomePalette")
        # a, b, c have coreness 2; d has coreness 1 → 2 distinct community values
        self.assertGreaterEqual(len(set(community_map.values())), 2)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00"])
    def test_community_ids_start_at_1(self, _mock: MagicMock) -> None:
        community_map, _ = detect_kcore(self.graph, "SomePalette")
        self.assertGreaterEqual(min(community_map.values()), 1)


# ---------------------------------------------------------------------------
# community.py — apply_to_graph
# ---------------------------------------------------------------------------


class ApplyToGraphTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_node("1", data={"color": ""})
        self.graph.add_node("2", data={"color": ""})
        self.graph.add_edge("1", "2")
        self.community_map = {"1": 1, "2": 2}
        self.community_palette = {1: (255, 0, 0), 2: (0, 255, 0)}
        self.channel_dict: dict = {
            "1": {"channel": None, "data": {}},
            "2": {"channel": None, "data": {}},
        }

    def test_sets_communities_on_graph_nodes(self) -> None:
        apply_to_graph(self.graph, self.channel_dict, self.community_map, self.community_palette, "LOUVAIN")
        for node_id in ["1", "2"]:
            self.assertIn("communities", self.graph.nodes[node_id]["data"])

    def test_sets_color_on_graph_nodes(self) -> None:
        apply_to_graph(self.graph, self.channel_dict, self.community_map, self.community_palette, "LOUVAIN")
        for node_id in ["1", "2"]:
            color = self.graph.nodes[node_id]["data"]["color"]
            self.assertIsInstance(color, str)
            self.assertEqual(len(color.split(",")), 3)  # "r,g,b" format

    def test_updates_channel_dict_with_communities_and_color(self) -> None:
        apply_to_graph(self.graph, self.channel_dict, self.community_map, self.community_palette, "LOUVAIN")
        for key in ["1", "2"]:
            self.assertIn("communities", self.channel_dict[key]["data"])
            self.assertIn("color", self.channel_dict[key]["data"])

    def test_louvain_community_label_includes_community_id_and_strategy(self) -> None:
        apply_to_graph(self.graph, self.channel_dict, self.community_map, self.community_palette, "LOUVAIN")
        self.assertEqual(self.graph.nodes["1"]["data"]["communities"]["louvain"], "1-louvain")
        self.assertEqual(self.graph.nodes["2"]["data"]["communities"]["louvain"], "2-louvain")

    def test_node_without_community_gets_fallback_color(self) -> None:
        # community_map is empty → no community assigned → nodes use DEFAULT_FALLBACK_COLOR
        apply_to_graph(self.graph, self.channel_dict, {}, self.community_palette, "LOUVAIN")
        for node_id in ["1", "2"]:
            color = self.graph.nodes[node_id]["data"]["color"]
            self.assertIsInstance(color, str)
            self.assertEqual(color, "204,204,204")  # DEFAULT_FALLBACK_COLOR

    def test_algorithm_strategy_uses_integer_label(self) -> None:
        for strategy in COMMUNITY_ALGORITHMS:
            apply_to_graph(self.graph, self.channel_dict, self.community_map, self.community_palette, strategy)
            community_label = self.graph.nodes["1"]["data"]["communities"][strategy.lower()]
            # Label must contain the integer community id
            self.assertIn("1", community_label)


# ---------------------------------------------------------------------------
# community.py — apply_edge_colors
# ---------------------------------------------------------------------------


class ApplyEdgeColorsTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_node("1", data={"color": "255,0,0"})
        self.graph.add_node("2", data={"color": "0,0,255"})
        self.graph.add_edge("1", "2", weight=1.0)
        self.channel_dict = {
            "1": {"data": {"color": "255,0,0"}},
            "2": {"data": {"color": "0,0,255"}},
        }
        self.edge_list = [["1", "2", 1.0]]

    def test_assigns_color_to_edges(self) -> None:
        apply_edge_colors(self.graph, self.edge_list, self.channel_dict)
        self.assertIn("color", self.graph.edges["1", "2"])

    def test_color_is_comma_separated_rgb_string(self) -> None:
        apply_edge_colors(self.graph, self.edge_list, self.channel_dict)
        color = self.graph.edges["1", "2"]["color"]
        parts = color.split(",")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))

    def test_edge_color_is_darkened_average(self) -> None:
        # red (255,0,0) + blue (0,0,255) → avg (127,0,127) → * 0.75 → (95,0,95)
        apply_edge_colors(self.graph, self.edge_list, self.channel_dict)
        color = self.graph.edges["1", "2"]["color"]
        r, g, b = (int(p) for p in color.split(","))
        self.assertEqual(g, 0)  # green channel stays 0
        self.assertEqual(r, b)  # red and blue channels are symmetric


# ---------------------------------------------------------------------------
# community.py — build_communities_payload
# ---------------------------------------------------------------------------


class BuildCommunitiesPayloadTests(TestCase):
    def test_algorithm_strategy_builds_groups_from_community_map(self) -> None:
        community_map = {"a": 1, "b": 1, "c": 2}
        community_palette = {1: (255, 0, 0), 2: (0, 255, 0)}
        result = build_communities_payload(["LOUVAIN"], {"LOUVAIN": (community_map, community_palette)})
        self.assertIn("louvain", result)
        self.assertIn("groups", result["louvain"])
        self.assertIn("main_groups", result["louvain"])
        self.assertEqual(len(result["louvain"]["groups"]), 2)

    def test_groups_sorted_by_count_descending(self) -> None:
        community_map = {"a": 1, "b": 1, "c": 1, "d": 2}  # community 1: 3 nodes, 2: 1 node
        community_palette = {1: (255, 0, 0), 2: (0, 255, 0)}
        result = build_communities_payload(["LOUVAIN"], {"LOUVAIN": (community_map, community_palette)})
        counts = [g[1] for g in result["louvain"]["groups"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_algorithm_main_groups_maps_id_to_label(self) -> None:
        community_map = {"a": 1}
        community_palette = {1: (255, 0, 0)}
        result = build_communities_payload(["KCORE"], {"KCORE": (community_map, community_palette)})
        self.assertIn("1", result["kcore"]["main_groups"])

    def test_organization_strategy_uses_db(self) -> None:
        Organization.objects.create(name="My Org", is_in_target=True)
        result = build_communities_payload(["ORGANIZATION"], {"ORGANIZATION": ({}, {})})
        org_names = [g[2] for g in result["organization"]["groups"]]
        self.assertIn("My Org", org_names)

    def test_out_of_target_orgs_excluded_from_organization_strategy(self) -> None:
        Organization.objects.create(name="Hidden Org", is_in_target=False)
        result = build_communities_payload(["ORGANIZATION"], {"ORGANIZATION": ({}, {})})
        org_names = [g[2] for g in result["organization"]["groups"]]
        self.assertNotIn("Hidden Org", org_names)

    def test_organization_strategy_main_groups_uses_key_and_name(self) -> None:
        org = Organization.objects.create(name="My Org", is_in_target=True)
        result = build_communities_payload(["ORGANIZATION"], {"ORGANIZATION": ({}, {})})
        self.assertEqual(result["organization"]["main_groups"].get(org.key), org.name)

    def test_multiple_strategies_all_included(self) -> None:
        community_map = {"a": 1}
        community_palette = {1: (255, 0, 0)}
        results = {
            "LOUVAIN": (community_map, community_palette),
            "KCORE": (community_map, community_palette),
        }
        result = build_communities_payload(["LOUVAIN", "KCORE"], results)
        self.assertIn("louvain", result)
        self.assertIn("kcore", result)


# ---------------------------------------------------------------------------
# graph_builder.py — build_graph
# ---------------------------------------------------------------------------


class BuildGraphTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org1", is_in_target=True, color="#FF0000")
        self.ch1 = Channel.objects.create(telegram_id=1, organization=self.org, title="Channel 1")
        self.ch2 = Channel.objects.create(telegram_id=2, organization=self.org, title="Channel 2")

    def _create_forward(self) -> Message:
        """Create a message in ch2 forwarded from ch1 and refresh degrees."""
        msg = Message.objects.create(telegram_id=1, channel=self.ch2, forwarded_from=self.ch1)
        self.ch1.save()
        self.ch2.save()
        return msg

    def test_raises_value_error_when_no_edges(self) -> None:
        with self.assertRaises(ValueError):
            build_graph()

    def test_builds_graph_with_forwarded_message_edges(self) -> None:
        self._create_forward()
        graph, channel_dict, edge_list, channel_qs = build_graph()
        self.assertGreater(len(edge_list), 0)

    def test_both_channels_appear_in_channel_dict(self) -> None:
        self._create_forward()
        _, channel_dict, _, _ = build_graph()
        self.assertIn(str(self.ch1.pk), channel_dict)
        self.assertIn(str(self.ch2.pk), channel_dict)

    def test_edge_weight_normalized_to_max_10(self) -> None:
        self._create_forward()
        graph, _, edge_list, _ = build_graph()
        for _u, _v, data in graph.edges(data=True):
            self.assertLessEqual(data["weight"], 10.0)
            self.assertGreater(data["weight"], 0)

    @override_settings(REVERSED_EDGES=False)
    def test_reversed_edges_false_gives_source_to_target_direction(self) -> None:
        self._create_forward()
        graph, _, _, _ = build_graph()
        # ch1 is source of forwards, ch2 is destination → edge ch1→ch2
        self.assertIn((str(self.ch1.pk), str(self.ch2.pk)), graph.edges())

    @override_settings(REVERSED_EDGES=True)
    def test_reversed_edges_true_flips_direction(self) -> None:
        self._create_forward()
        graph, _, _, _ = build_graph()
        # With REVERSED_EDGES, direction is flipped: ch2→ch1
        self.assertIn((str(self.ch2.pk), str(self.ch1.pk)), graph.edges())

    def test_builds_graph_with_reference_edges(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch2)
        msg.references.add(self.ch1)
        graph, _, edge_list, _ = build_graph()
        self.assertGreater(len(edge_list), 0)

    def test_draw_dead_leaves_includes_channels_with_in_degree(self) -> None:
        ch3 = Channel.objects.create(telegram_id=3, organization=None, title="Dead Leaf")
        # ch2 (in target) forwards from ch3 → ch3 gets in_degree > 0
        Message.objects.create(telegram_id=10, channel=self.ch2, forwarded_from=ch3)
        ch3.refresh_degrees()
        ch3.refresh_from_db()
        self.assertGreater(ch3.in_degree or 0, 0)
        # Create a ch1↔ch2 edge so graph is valid
        self._create_forward()
        _, channel_dict_dl, _, _ = build_graph(draw_dead_leaves=True)
        self.assertIn(str(ch3.pk), channel_dict_dl)

    def test_draw_dead_leaves_false_excludes_out_of_target(self) -> None:
        ch3 = Channel.objects.create(telegram_id=3, organization=None, title="Dead Leaf")
        self._create_forward()
        _, channel_dict, _, _ = build_graph(draw_dead_leaves=False)
        self.assertNotIn(str(ch3.pk), channel_dict)

    def test_returns_queryset_of_channels(self) -> None:
        self._create_forward()
        _, _, _, channel_qs = build_graph()
        self.assertIn(self.ch1, channel_qs)
        self.assertIn(self.ch2, channel_qs)

    def _create_forward_on_date(self, date: datetime.datetime) -> Message:
        msg = Message.objects.create(telegram_id=99, channel=self.ch2, forwarded_from=self.ch1, date=date)
        self.ch1.save()
        self.ch2.save()
        return msg

    def test_startdate_excludes_messages_before_date(self) -> None:
        self._create_forward_on_date(datetime.datetime(2023, 1, 15, tzinfo=datetime.timezone.utc))
        with self.assertRaises(ValueError):
            build_graph(start_date=datetime.date(2023, 2, 1))

    def test_enddate_excludes_messages_after_date(self) -> None:
        self._create_forward_on_date(datetime.datetime(2023, 3, 1, tzinfo=datetime.timezone.utc))
        with self.assertRaises(ValueError):
            build_graph(end_date=datetime.date(2023, 2, 28))

    def test_date_range_includes_matching_messages(self) -> None:
        self._create_forward_on_date(datetime.datetime(2023, 6, 15, tzinfo=datetime.timezone.utc))
        # ch1 needs a published message in range so it isn't removed from the graph
        Message.objects.create(
            telegram_id=100, channel=self.ch1, date=datetime.datetime(2023, 6, 10, tzinfo=datetime.timezone.utc)
        )
        graph, _, edge_list, _ = build_graph(
            start_date=datetime.date(2023, 6, 1),
            end_date=datetime.date(2023, 6, 30),
        )
        self.assertGreater(len(edge_list), 0)

    def test_date_filter_removes_channels_with_no_messages_in_range(self) -> None:
        self._create_forward_on_date(datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc))
        # Add a third channel with a message in range to ensure the graph has edges
        ch3 = Channel.objects.create(telegram_id=3, organization=self.org, title="Channel 3")
        Message.objects.create(
            telegram_id=100,
            channel=ch3,
            forwarded_from=self.ch1,
            date=datetime.datetime(2023, 6, 15, tzinfo=datetime.timezone.utc),
        )
        # ch1 also needs a published message in range so it remains in the filtered graph
        Message.objects.create(
            telegram_id=101,
            channel=self.ch1,
            date=datetime.datetime(2023, 3, 1, tzinfo=datetime.timezone.utc),
        )
        self.ch1.save()
        ch3.save()
        _, channel_dict, _, channel_qs = build_graph(start_date=datetime.date(2023, 1, 1))
        self.assertNotIn(str(self.ch2.pk), channel_dict)
        self.assertNotIn(self.ch2, channel_qs)

    def test_channel_qs_filtered_to_active_channels(self) -> None:
        self._create_forward_on_date(datetime.datetime(2023, 6, 15, tzinfo=datetime.timezone.utc))
        # ch1 needs a published message in range so it isn't removed from the graph
        Message.objects.create(
            telegram_id=100, channel=self.ch1, date=datetime.datetime(2023, 6, 10, tzinfo=datetime.timezone.utc)
        )
        _, _, _, channel_qs = build_graph(
            start_date=datetime.date(2023, 6, 1),
            end_date=datetime.date(2023, 6, 30),
        )
        self.assertIn(self.ch2, channel_qs)


# ---------------------------------------------------------------------------
# exporter.py — build_graph_data
# ---------------------------------------------------------------------------


def _make_graph_with_positions() -> tuple[nx.DiGraph, dict, dict[str, tuple[float, float]]]:
    """Return a minimal 2-node directed graph, channel_dict, and positions."""
    graph = nx.DiGraph()
    node_data_1 = {
        "pk": "1",
        "label": "Ch1",
        "communities": {"louvain": "1-louvain"},
        "color": "255,0,0",
        "pic": "",
        "url": "https://t.me/ch1",
        "activity_period": "Unknown",
        "fans": 0,
        "in_deg": 0,
        "is_lost": False,
        "is_private": False,
        "messages_count": 0,
        "out_deg": 0,
    }
    node_data_2 = {
        "pk": "2",
        "label": "Ch2",
        "communities": {"louvain": "2-louvain"},
        "color": "0,0,255",
        "pic": "",
        "url": "https://t.me/ch2",
        "activity_period": "Unknown",
        "fans": 0,
        "in_deg": 0,
        "is_lost": False,
        "is_private": False,
        "messages_count": 0,
        "out_deg": 0,
    }
    graph.add_node("1", data=node_data_1)
    graph.add_node("2", data=node_data_2)
    graph.add_edge("1", "2", weight=5.0, color="100,100,100")
    positions = {"1": (1.0, 2.0), "2": (3.0, 4.0)}
    return graph, {}, positions


class BuildGraphDataTests(TestCase):
    def setUp(self) -> None:
        self.graph, self.channel_dict, self.positions = _make_graph_with_positions()

    def test_nodes_list_length_matches_graph(self) -> None:
        graph_data = build_graph_data(self.graph, self.channel_dict, self.positions)
        self.assertEqual(len(graph_data["nodes"]), 2)

    def test_edges_list_length_matches_graph(self) -> None:
        graph_data = build_graph_data(self.graph, self.channel_dict, self.positions)
        self.assertEqual(len(graph_data["edges"]), 1)

    def test_node_has_all_required_keys(self) -> None:
        graph_data = build_graph_data(self.graph, self.channel_dict, self.positions)
        required = {
            "id",
            "x",
            "y",
            "label",
            "communities",
            "color",
            "pic",
            "url",
            "activity_period",
            "fans",
            "in_deg",
            "is_lost",
            "is_private",
            "messages_count",
            "out_deg",
        }
        for node in graph_data["nodes"]:
            missing = required - node.keys()
            self.assertFalse(missing, f"Node is missing keys: {missing}")

    def test_edge_has_all_required_keys(self) -> None:
        graph_data = build_graph_data(self.graph, self.channel_dict, self.positions)
        edge = graph_data["edges"][0]
        for key in ("source", "target", "weight", "color", "id"):
            self.assertIn(key, edge)

    def test_node_positions_are_applied(self) -> None:
        graph_data = build_graph_data(self.graph, self.channel_dict, self.positions)
        node_map = {n["id"]: n for n in graph_data["nodes"]}
        self.assertAlmostEqual(node_map["1"]["x"], 1.0)
        self.assertAlmostEqual(node_map["1"]["y"], 2.0)
        self.assertAlmostEqual(node_map["2"]["x"], 3.0)
        self.assertAlmostEqual(node_map["2"]["y"], 4.0)

    def test_edge_ids_are_sequential(self) -> None:
        graph_data = build_graph_data(self.graph, self.channel_dict, self.positions)
        edge_ids = [e["id"] for e in graph_data["edges"]]
        self.assertEqual(edge_ids, list(range(len(edge_ids))))


# ---------------------------------------------------------------------------
# exporter.py — apply_base_node_measures
# ---------------------------------------------------------------------------


class ApplyBaseNodeMeasuresTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org1", is_in_target=True, color="#FF0000")
        self.ch1 = Channel.objects.create(telegram_id=1, organization=org, title="Chan1", participants_count=500)
        self.ch2 = Channel.objects.create(telegram_id=2, organization=org, title="Chan2", participants_count=300)
        # ch1 has a message forwarded from ch2
        Message.objects.create(telegram_id=1, channel=self.ch1, forwarded_from=self.ch2)
        self.ch1.save()
        self.ch2.save()

        self.graph = nx.DiGraph()
        self.graph.add_node(str(self.ch1.pk), data={"pk": str(self.ch1.pk)})
        self.graph.add_node(str(self.ch2.pk), data={"pk": str(self.ch2.pk)})
        self.graph.add_edge(str(self.ch2.pk), str(self.ch1.pk), weight=5.0)
        self.channel_dict = {
            str(self.ch1.pk): {"channel": self.ch1},
            str(self.ch2.pk): {"channel": self.ch2},
        }
        self.graph_data = {
            "nodes": [
                {"id": str(self.ch1.pk), "in_deg": 0, "out_deg": 0, "fans": 0, "messages_count": 0, "label": ""},
                {"id": str(self.ch2.pk), "in_deg": 0, "out_deg": 0, "fans": 0, "messages_count": 0, "label": ""},
            ],
            "edges": [],
        }

    def test_returns_non_empty_measures_labels(self) -> None:
        labels = apply_base_node_measures(self.graph_data, self.graph, self.channel_dict)
        self.assertIsInstance(labels, list)
        self.assertGreater(len(labels), 0)

    def test_labels_are_key_description_pairs(self) -> None:
        labels = apply_base_node_measures(self.graph_data, self.graph, self.channel_dict)
        for key, description in labels:
            self.assertIsInstance(key, str)
            self.assertIsInstance(description, str)

    def test_fans_filled_from_participants_count(self) -> None:
        apply_base_node_measures(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertEqual(node_map[str(self.ch1.pk)]["fans"], 500)
        self.assertEqual(node_map[str(self.ch2.pk)]["fans"], 300)

    def test_label_filled_from_channel_title(self) -> None:
        apply_base_node_measures(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertEqual(node_map[str(self.ch1.pk)]["label"], "Chan1")
        self.assertEqual(node_map[str(self.ch2.pk)]["label"], "Chan2")

    def test_in_degree_filled_from_graph(self) -> None:
        apply_base_node_measures(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        # ch1 has one incoming edge from ch2 (weight 5.0)
        self.assertGreater(node_map[str(self.ch1.pk)]["in_deg"], 0)
        self.assertEqual(node_map[str(self.ch2.pk)]["in_deg"], 0)

    def test_messages_count_filled_from_db(self) -> None:
        apply_base_node_measures(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertEqual(node_map[str(self.ch1.pk)]["messages_count"], 1)
        self.assertEqual(node_map[str(self.ch2.pk)]["messages_count"], 0)


# ---------------------------------------------------------------------------
# exporter.py — apply_pagerank
# ---------------------------------------------------------------------------


class ApplyPageRankTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["1", "2", "3"])
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("3", "1")])
        self.graph_data = {
            "nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
            "edges": [],
        }

    def test_adds_pagerank_key_to_all_nodes(self) -> None:
        apply_pagerank(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("pagerank", node)

    def test_returns_list_with_pagerank_label(self) -> None:
        labels = apply_pagerank(self.graph_data, self.graph)
        keys = [k for k, _ in labels]
        self.assertIn("pagerank", keys)

    def test_pagerank_values_are_floats(self) -> None:
        apply_pagerank(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIsInstance(node["pagerank"], float)

    def test_pagerank_values_sum_to_one(self) -> None:
        apply_pagerank(self.graph_data, self.graph)
        total = sum(n["pagerank"] for n in self.graph_data["nodes"])
        self.assertAlmostEqual(total, 1.0, places=5)


# ---------------------------------------------------------------------------
# exporter.py — find_main_component
# ---------------------------------------------------------------------------


class FindMainComponentTests(TestCase):
    def test_returns_a_set(self) -> None:
        graph = nx.DiGraph()
        graph.add_edges_from([("a", "b"), ("b", "c")])
        result = find_main_component(graph)
        self.assertIsInstance(result, set)

    def test_returns_largest_weakly_connected_component(self) -> None:
        graph = nx.DiGraph()
        # Component 1: a-b-c (size 3)
        graph.add_edges_from([("a", "b"), ("b", "c")])
        # Component 2: d-e (size 2)
        graph.add_edge("d", "e")
        result = find_main_component(graph)
        self.assertEqual(result, {"a", "b", "c"})

    def test_single_component_graph_returns_all_nodes(self) -> None:
        graph = nx.DiGraph()
        graph.add_edges_from([("x", "y"), ("y", "z"), ("z", "x")])
        result = find_main_component(graph)
        self.assertEqual(result, {"x", "y", "z"})


# ---------------------------------------------------------------------------
# exporter.py — reposition_isolated_nodes
# ---------------------------------------------------------------------------


class RepositionIsolatedNodesTests(TestCase):
    def _make_graph_data(self) -> dict:
        return {
            "nodes": [
                {"id": "1", "x": 10.0, "y": 10.0},  # main component
                {"id": "2", "x": 20.0, "y": 20.0},  # main component
                {"id": "3", "x": 0.0, "y": 0.0},  # isolated
            ],
            "edges": [],
        }

    def test_main_component_node_positions_unchanged(self) -> None:
        graph_data = self._make_graph_data()
        reposition_isolated_nodes(graph_data, {"1", "2"})
        node_map = {n["id"]: n for n in graph_data["nodes"]}
        self.assertAlmostEqual(node_map["1"]["x"], 10.0)
        self.assertAlmostEqual(node_map["1"]["y"], 10.0)
        self.assertAlmostEqual(node_map["2"]["x"], 20.0)
        self.assertAlmostEqual(node_map["2"]["y"], 20.0)

    def test_isolated_node_repositioned_near_max(self) -> None:
        graph_data = self._make_graph_data()
        reposition_isolated_nodes(graph_data, {"1", "2"})
        node_map = {n["id"]: n for n in graph_data["nodes"]}
        # First isolated node lands at (max_x - 0*d, max_y - 0*d) = (max_x, max_y)
        self.assertAlmostEqual(node_map["3"]["x"], 20.0)
        self.assertAlmostEqual(node_map["3"]["y"], 20.0)

    def test_all_nodes_retain_x_y_coordinates(self) -> None:
        graph_data = self._make_graph_data()
        reposition_isolated_nodes(graph_data, {"1", "2"})
        for node in graph_data["nodes"]:
            self.assertIn("x", node)
            self.assertIn("y", node)

    def test_empty_isolated_set_leaves_all_nodes_in_place(self) -> None:
        graph_data = self._make_graph_data()
        reposition_isolated_nodes(graph_data, {"1", "2", "3"})
        node_map = {n["id"]: n for n in graph_data["nodes"]}
        self.assertAlmostEqual(node_map["3"]["x"], 0.0)
        self.assertAlmostEqual(node_map["3"]["y"], 0.0)


# ---------------------------------------------------------------------------
# exporter.py — ensure_graph_root
# ---------------------------------------------------------------------------


class EnsureGraphRootTests(TestCase):
    def test_creates_directory_if_not_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "graph_root")
            ensure_graph_root(target)
            self.assertTrue(os.path.isdir(target))

    def test_removes_existing_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "graph_root")
            os.makedirs(target)
            sentinel = os.path.join(target, "old_file.txt")
            with open(sentinel, "w") as f:
                f.write("stale data")
            ensure_graph_root(target)
            self.assertFalse(os.path.exists(sentinel))
            self.assertTrue(os.path.isdir(target))

    def test_succeeds_even_without_map_template(self) -> None:
        # webapp_engine/map may not exist in test environment; ensure_graph_root
        # catches the OSError and should not propagate it.
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "graph_root")
            try:
                ensure_graph_root(target)
            except OSError:
                self.fail("ensure_graph_root raised OSError unexpectedly")


# ---------------------------------------------------------------------------
# exporter.py — write_graph_files
# ---------------------------------------------------------------------------


class WriteGraphFilesTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org1", is_in_target=True, color="#FF0000")
        self.ch = Channel.objects.create(telegram_id=1, organization=org, title="Chan1")
        self.channel_qs = Channel.objects.filter(pk=self.ch.pk)
        self.graph_data = {"nodes": [{"id": "1", "x": 0.0, "y": 0.0}], "edges": []}
        self.communities_data = {
            "louvain": {
                "main_groups": {"1": "1-louvain"},
                "groups": [("1", 5, "1-louvain", "#FF0000")],
            }
        }
        self.measures_labels = [("in_deg", "Inbound connections"), ("pagerank", "PageRank")]

    def test_writes_output_json_with_nodes_and_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_graph_files(self.graph_data, self.communities_data, self.measures_labels, self.channel_qs, tmpdir)
            out_file = os.path.join(tmpdir, "data", "channel_position.json")
            self.assertTrue(os.path.exists(out_file))
            with open(out_file) as f:
                data = json.load(f)
            self.assertIn("nodes", data)
            self.assertIn("edges", data)

    def test_writes_accessory_json_with_required_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_graph_files(self.graph_data, self.communities_data, self.measures_labels, self.channel_qs, tmpdir)
            channels_file = os.path.join(tmpdir, "data", "channels.json")
            self.assertTrue(os.path.exists(channels_file))
            with open(channels_file) as f:
                acc_data = json.load(f)
            for key in ("measures", "total_pages_count"):
                self.assertIn(key, acc_data)
            communities_file = os.path.join(tmpdir, "data", "communities.json")
            self.assertTrue(os.path.exists(communities_file))

    def test_accessory_total_pages_count_matches_queryset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_graph_files(self.graph_data, self.communities_data, self.measures_labels, self.channel_qs, tmpdir)
            with open(os.path.join(tmpdir, "data", "channels.json")) as f:
                acc_data = json.load(f)
            self.assertEqual(acc_data["total_pages_count"], self.channel_qs.count())


# ---------------------------------------------------------------------------
# layout.py — compute_layout
# ---------------------------------------------------------------------------


class ComputeLayoutTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b", "c"])
        self.graph.add_edges_from([("a", "b"), ("b", "c"), ("c", "a")])

    def test_returns_positions_for_all_nodes(self) -> None:
        positions = compute_layout(self.graph, iterations=10)
        self.assertEqual(set(positions.keys()), set(self.graph.nodes()))

    def test_positions_are_float_tuples(self) -> None:
        positions = compute_layout(self.graph, iterations=10)
        for _node_id, pos in positions.items():
            self.assertIsInstance(pos, tuple)
            self.assertEqual(len(pos), 2)
            self.assertIsInstance(pos[0], float)
            self.assertIsInstance(pos[1], float)

    def test_single_node_graph_gets_position(self) -> None:
        graph = nx.DiGraph()
        graph.add_node("solo")
        positions = compute_layout(graph, iterations=5)
        self.assertIn("solo", positions)


# ---------------------------------------------------------------------------
# community.py — detect_infomap
# ---------------------------------------------------------------------------


class DetectInfomapTests(TestCase):
    def setUp(self) -> None:
        # Two clear clusters connected by a weak bridge
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b", "c", "d", "e", "f"])
        self.graph.add_edges_from(
            [
                ("a", "b"),
                ("b", "c"),
                ("c", "a"),  # cluster 1
                ("d", "e"),
                ("e", "f"),
                ("f", "d"),  # cluster 2
                ("c", "d"),  # bridge
            ]
        )

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_returns_community_map_and_palette(self, _mock: MagicMock) -> None:
        community_map, palette = detect_infomap(self.graph, "SomePalette")
        self.assertIsInstance(community_map, dict)
        self.assertIsInstance(palette, dict)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_all_nodes_assigned(self, _mock: MagicMock) -> None:
        community_map, _ = detect_infomap(self.graph, "SomePalette")
        self.assertEqual(set(community_map.keys()), set(self.graph.nodes()))

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_community_ids_start_at_1(self, _mock: MagicMock) -> None:
        community_map, _ = detect_infomap(self.graph, "SomePalette")
        self.assertGreaterEqual(min(community_map.values()), 1)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_palette_covers_all_detected_communities(self, _mock: MagicMock) -> None:
        community_map, palette = detect_infomap(self.graph, "SomePalette")
        for community_id in community_map.values():
            self.assertIn(community_id, palette)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_isolated_node_gets_own_community(self, _mock: MagicMock) -> None:
        # Infomap requires at least one link; add an edge between two connected nodes
        # plus an isolated node so the fallback assignment branch is exercised.
        graph = nx.DiGraph()
        graph.add_edge("a", "b")
        graph.add_node("isolated")
        community_map, _ = detect_infomap(graph, "SomePalette")
        self.assertIn("isolated", community_map)


# ---------------------------------------------------------------------------
# community.py — detect_leiden
# ---------------------------------------------------------------------------


class DetectLeidenTests(TestCase):
    def setUp(self) -> None:
        # Two clear clusters connected by a weak bridge
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b", "c", "d", "e", "f"])
        self.graph.add_edges_from(
            [
                ("a", "b"),
                ("b", "c"),
                ("c", "a"),  # cluster 1
                ("d", "e"),
                ("e", "f"),
                ("f", "d"),  # cluster 2
                ("c", "d"),  # bridge
            ]
        )

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_returns_community_map_and_palette(self, _mock: MagicMock) -> None:
        community_map, palette = detect_leiden(self.graph, "SomePalette")
        self.assertIsInstance(community_map, dict)
        self.assertIsInstance(palette, dict)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_all_nodes_assigned(self, _mock: MagicMock) -> None:
        community_map, _ = detect_leiden(self.graph, "SomePalette")
        self.assertEqual(set(community_map.keys()), set(self.graph.nodes()))

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_community_ids_start_at_1(self, _mock: MagicMock) -> None:
        community_map, _ = detect_leiden(self.graph, "SomePalette")
        self.assertGreaterEqual(min(community_map.values()), 1)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_palette_covers_all_detected_communities(self, _mock: MagicMock) -> None:
        community_map, palette = detect_leiden(self.graph, "SomePalette")
        for community_id in community_map.values():
            self.assertIn(community_id, palette)

    @patch("network.community.palette_colors", return_value=["#ff0000", "#00ff00", "#0000ff"])
    def test_isolated_nodes_merged_into_same_community(self, _mock: MagicMock) -> None:
        graph = nx.DiGraph()
        graph.add_edge("a", "b")
        graph.add_node("iso1")
        graph.add_node("iso2")
        community_map, _ = detect_leiden(graph, "SomePalette")
        self.assertEqual(community_map["iso1"], community_map["iso2"])


# ---------------------------------------------------------------------------
# community.py — detect() dispatcher
# ---------------------------------------------------------------------------


class DetectDispatcherTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["a", "b"])
        self.graph.add_edge("a", "b")
        self.org = Organization.objects.create(name="Org", is_in_target=True)
        self.ch1 = Channel.objects.create(telegram_id=1, organization=self.org)
        self.ch2 = Channel.objects.create(telegram_id=2, organization=self.org)
        self.channel_dict = {
            str(self.ch1.pk): {"channel": self.ch1, "data": {}},
            str(self.ch2.pk): {"channel": self.ch2, "data": {}},
        }

    @patch("network.community.detect_louvain")
    def test_louvain_strategy_calls_detect_louvain(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("LOUVAIN", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette", reverse=False)

    @patch("network.community.detect_kcore")
    def test_kcore_strategy_calls_detect_kcore(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("KCORE", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette", reverse=False)

    @patch("network.community.detect_infomap")
    def test_infomap_strategy_calls_detect_infomap(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("INFOMAP", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette", reverse=False)

    @patch("network.community.detect_leiden")
    def test_leiden_strategy_calls_detect_leiden(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("LEIDEN", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette", reverse=False)

    @patch("network.community.detect_organization")
    def test_unknown_strategy_falls_back_to_detect_organization(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("ORGANIZATION", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.channel_dict)

    def test_unknown_strategy_raises_value_error(self) -> None:
        from network.community import detect

        with self.assertRaises(ValueError, msg="Unknown community strategy"):
            detect("", "palette", self.graph, self.channel_dict)


# ---------------------------------------------------------------------------
# exporter.py — copy_channel_media
# ---------------------------------------------------------------------------


class CopyChannelMediaTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org", is_in_target=True)

    def test_channel_without_username_is_skipped(self) -> None:
        ch = Channel.objects.create(telegram_id=1, organization=self.org, username="")
        with tempfile.TemporaryDirectory() as tmpdir:
            from network.exporter import copy_channel_media

            # No error, nothing copied
            copy_channel_media(Channel.objects.filter(pk=ch.pk), tmpdir)
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "channels")))

    def test_missing_source_dir_is_silently_ignored(self) -> None:
        ch = Channel.objects.create(telegram_id=2, organization=self.org, username="testchan")
        with tempfile.TemporaryDirectory() as tmpdir:
            from network.exporter import copy_channel_media

            # MEDIA_ROOT/channels/testchan/profile doesn't exist → FileNotFoundError silently caught
            copy_channel_media(Channel.objects.filter(pk=ch.pk), tmpdir)
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "channels", "testchan")))

    def test_existing_source_dir_is_copied(self) -> None:
        ch = Channel.objects.create(telegram_id=3, organization=self.org, username="copychan")
        with tempfile.TemporaryDirectory() as media_root, tempfile.TemporaryDirectory() as output_root:
            src = os.path.join(media_root, "channels", "copychan", "profile")
            os.makedirs(src)
            sentinel = os.path.join(src, "photo.jpg")
            with open(sentinel, "w") as f:
                f.write("fake image")
            from django.test import override_settings

            from network.exporter import copy_channel_media

            with override_settings(MEDIA_ROOT=media_root):
                copy_channel_media(Channel.objects.filter(pk=ch.pk), output_root)
            dst = os.path.join(output_root, "media", "channels", "copychan", "profile", "photo.jpg")
            self.assertTrue(os.path.exists(dst))

    def test_oserror_on_copy_is_logged_not_raised(self) -> None:
        ch = Channel.objects.create(telegram_id=4, organization=self.org, username="errchan")
        with tempfile.TemporaryDirectory() as media_root, tempfile.TemporaryDirectory() as output_root:
            src = os.path.join(media_root, "channels", "errchan", "profile")
            os.makedirs(src)
            dst_parent = os.path.join(output_root, "channels", "errchan", "profile")
            os.makedirs(dst_parent)  # pre-create dst so copytree raises OSError (already exists)
            from network.exporter import copy_channel_media

            with override_settings(MEDIA_ROOT=media_root):
                try:
                    copy_channel_media(Channel.objects.filter(pk=ch.pk), output_root)
                except OSError:
                    self.fail("copy_channel_media raised OSError unexpectedly")


# ---------------------------------------------------------------------------
# structural_analysis management command
# ---------------------------------------------------------------------------


_EXPORT_CMD = "network.management.commands.structural_analysis"


def _patch_export_pipeline() -> list:
    """Return a list of patch decorators for all structural_analysis submodule calls."""
    targets = [
        f"{_EXPORT_CMD}.graph_builder.build_graph",
        f"{_EXPORT_CMD}.community.detect",
        f"{_EXPORT_CMD}.community.apply_to_graph",
        f"{_EXPORT_CMD}.community.apply_edge_colors",
        f"{_EXPORT_CMD}.community.build_communities_payload",
        f"{_EXPORT_CMD}.layout.forceatlas2_positions",
        f"{_EXPORT_CMD}.exporter.build_graph_data",
        f"{_EXPORT_CMD}.exporter.find_main_component",
        f"{_EXPORT_CMD}.measures.apply_base_node_measures",
        f"{_EXPORT_CMD}.measures.apply_pagerank",
        f"{_EXPORT_CMD}.exporter.reposition_isolated_nodes",
        f"{_EXPORT_CMD}.exporter.ensure_graph_root",
        f"{_EXPORT_CMD}.exporter.write_graph_files",
        f"{_EXPORT_CMD}.tables.write_table_html",
        f"{_EXPORT_CMD}.tables.write_table_xlsx",
        f"{_EXPORT_CMD}.exporter.copy_channel_media",
    ]
    # Apply in reverse so the first target becomes the first positional arg
    decorators = [patch(t) for t in reversed(targets)]
    return decorators


class ExportNetworkCommandTests(TestCase):
    def setUp(self) -> None:
        _b = _EXPORT_CMD
        for target in [
            f"{_b}.exporter.write_meta_json",
            f"{_b}.exporter.write_robots_txt",
            f"{_b}.exporter.write_summary_json",
            f"{_b}.tables.write_index_html",
            f"{_b}.tables.write_network_metrics_json",
            f"{_b}.tables.write_community_metrics_json",
            f"{_b}.tables.write_network_table_html",
            f"{_b}.tables.write_community_table_html",
            f"{_b}.tables.write_network_table_xlsx",
            f"{_b}.tables.write_community_table_xlsx",
            f"{_b}.community_stats.compute_community_metrics",
            f"{_b}.os.makedirs",
            f"{_b}.os.rename",
        ]:
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    def _configure_happy_path(
        self,
        mock_build: MagicMock,
        mock_detect: MagicMock,
        mock_layout: MagicMock,
        mock_graph_data: MagicMock,
        mock_main_comp: MagicMock,
        mock_measures: MagicMock,
        mock_pagerank: MagicMock,
        mock_communities_payload: MagicMock,
    ) -> None:
        fake_graph = nx.DiGraph()
        fake_graph.add_node("1")
        fake_qs = MagicMock()
        fake_qs.filter.return_value = fake_qs
        fake_qs.count.return_value = 0
        mock_build.return_value = (fake_graph, {"1": {}}, [["1", "2", 1.0]], fake_qs)
        mock_detect.return_value = ({"1": 1}, {1: (255, 0, 0)})
        mock_layout.return_value = {"1": (0.0, 0.0)}
        mock_graph_data.return_value = {"nodes": [], "edges": []}
        mock_main_comp.return_value = {"1"}
        mock_measures.return_value = [("in_deg", "Inbound")]
        mock_pagerank.return_value = [("pagerank", "PageRank")]
        mock_communities_payload.return_value = {"organization": {"groups": [], "main_groups": {}}}

    def test_raises_command_error_on_invalid_startdate(self) -> None:
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("structural_analysis", startdate="not-a-date")

    def test_raises_command_error_on_invalid_enddate(self) -> None:
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("structural_analysis", enddate="2023-13-01")

    @patch(f"{_EXPORT_CMD}.exporter.copy_channel_media")
    @patch(f"{_EXPORT_CMD}.tables.write_table_xlsx")
    @patch(f"{_EXPORT_CMD}.tables.write_table_html")
    @patch(f"{_EXPORT_CMD}.exporter.write_graph_files")
    @patch(f"{_EXPORT_CMD}.exporter.ensure_graph_root")
    @patch(f"{_EXPORT_CMD}.exporter.reposition_isolated_nodes")
    @patch(f"{_EXPORT_CMD}.measures.apply_pagerank")
    @patch(f"{_EXPORT_CMD}.measures.apply_base_node_measures")
    @patch(f"{_EXPORT_CMD}.exporter.find_main_component")
    @patch(f"{_EXPORT_CMD}.exporter.build_graph_data")
    @patch(f"{_EXPORT_CMD}.layout.forceatlas2_positions")
    @patch(f"{_EXPORT_CMD}.community.build_communities_payload")
    @patch(f"{_EXPORT_CMD}.community.apply_edge_colors")
    @patch(f"{_EXPORT_CMD}.community.apply_to_graph")
    @patch(f"{_EXPORT_CMD}.community.detect")
    @patch(f"{_EXPORT_CMD}.graph_builder.build_graph")
    def test_raises_command_error_when_no_edges(
        self,
        mock_build: MagicMock,
        *_mocks: MagicMock,
    ) -> None:
        from django.core.management import call_command
        from django.core.management.base import CommandError

        mock_build.side_effect = ValueError("There are no relationships between channels.")
        with self.assertRaises(CommandError):
            # graph=True bypasses the bare-CLI early-exit so build_graph is reached.
            call_command("structural_analysis", graph=True)

    @patch(f"{_EXPORT_CMD}.exporter.copy_channel_media")
    @patch(f"{_EXPORT_CMD}.tables.write_table_xlsx")
    @patch(f"{_EXPORT_CMD}.tables.write_table_html")
    @patch(f"{_EXPORT_CMD}.exporter.write_graph_files")
    @patch(f"{_EXPORT_CMD}.exporter.ensure_graph_root")
    @patch(f"{_EXPORT_CMD}.exporter.reposition_isolated_nodes")
    @patch(f"{_EXPORT_CMD}.measures.apply_pagerank")
    @patch(f"{_EXPORT_CMD}.measures.apply_base_node_measures")
    @patch(f"{_EXPORT_CMD}.exporter.find_main_component")
    @patch(f"{_EXPORT_CMD}.exporter.build_graph_data")
    @patch(f"{_EXPORT_CMD}.layout.forceatlas2_positions")
    @patch(f"{_EXPORT_CMD}.community.build_communities_payload")
    @patch(f"{_EXPORT_CMD}.community.apply_edge_colors")
    @patch(f"{_EXPORT_CMD}.community.apply_to_graph")
    @patch(f"{_EXPORT_CMD}.community.detect")
    @patch(f"{_EXPORT_CMD}.graph_builder.build_graph")
    def test_all_pipeline_steps_called(
        self,
        mock_build: MagicMock,
        mock_detect: MagicMock,
        mock_apply_to_graph: MagicMock,
        mock_edge_colors: MagicMock,
        mock_communities_payload: MagicMock,
        mock_layout: MagicMock,
        mock_graph_data: MagicMock,
        mock_main_comp: MagicMock,
        mock_measures: MagicMock,
        mock_pagerank: MagicMock,
        mock_reposition: MagicMock,
        mock_ensure: MagicMock,
        mock_write: MagicMock,
        mock_table_html: MagicMock,
        mock_table_xls: MagicMock,
        mock_copy: MagicMock,
    ) -> None:
        from django.core.management import call_command

        self._configure_happy_path(
            mock_build,
            mock_detect,
            mock_layout,
            mock_graph_data,
            mock_main_comp,
            mock_measures,
            mock_pagerank,
            mock_communities_payload,
        )
        # The defaults are factory-empty; pass community_strategies + measures
        # explicitly so the community-detection and measures pipelines run.
        call_command(
            "structural_analysis",
            graph=True,
            html=True,
            community_strategies="ORGANIZATION",
            measures="PAGERANK",
            edge_weight_strategy="PARTIAL_REFERENCES",
        )

        mock_build.assert_called_once()
        mock_detect.assert_called()
        mock_apply_to_graph.assert_called()
        mock_edge_colors.assert_called_once()
        mock_layout.assert_called_once()
        mock_graph_data.assert_called_once()
        mock_main_comp.assert_called_once()
        mock_measures.assert_called_once()
        mock_pagerank.assert_called_once()
        mock_reposition.assert_called_once()
        mock_ensure.assert_called_once()
        mock_write.assert_called_once()
        mock_table_html.assert_called_once()
        mock_table_xls.assert_not_called()
        mock_copy.assert_called_once()

    @patch(f"{_EXPORT_CMD}.exporter.copy_channel_media")
    @patch(f"{_EXPORT_CMD}.tables.write_table_xlsx")
    @patch(f"{_EXPORT_CMD}.tables.write_table_html")
    @patch(f"{_EXPORT_CMD}.exporter.write_graph_files")
    @patch(f"{_EXPORT_CMD}.exporter.ensure_graph_root")
    @patch(f"{_EXPORT_CMD}.exporter.reposition_isolated_nodes")
    @patch(f"{_EXPORT_CMD}.measures.apply_pagerank")
    @patch(f"{_EXPORT_CMD}.measures.apply_base_node_measures")
    @patch(f"{_EXPORT_CMD}.exporter.find_main_component")
    @patch(f"{_EXPORT_CMD}.exporter.build_graph_data")
    @patch(f"{_EXPORT_CMD}.layout.forceatlas2_positions")
    @patch(f"{_EXPORT_CMD}.community.build_communities_payload")
    @patch(f"{_EXPORT_CMD}.community.apply_edge_colors")
    @patch(f"{_EXPORT_CMD}.community.apply_to_graph")
    @patch(f"{_EXPORT_CMD}.community.detect")
    @patch(f"{_EXPORT_CMD}.graph_builder.build_graph")
    def test_table_format_none_skips_both(
        self,
        mock_build: MagicMock,
        mock_detect: MagicMock,
        mock_apply_to_graph: MagicMock,
        mock_edge_colors: MagicMock,
        mock_communities_payload: MagicMock,
        mock_layout: MagicMock,
        mock_graph_data: MagicMock,
        mock_main_comp: MagicMock,
        mock_measures: MagicMock,
        mock_pagerank: MagicMock,
        mock_reposition: MagicMock,
        mock_ensure: MagicMock,
        mock_write: MagicMock,
        mock_table_html: MagicMock,
        mock_table_xls: MagicMock,
        mock_copy: MagicMock,
    ) -> None:
        from django.core.management import call_command

        self._configure_happy_path(
            mock_build,
            mock_detect,
            mock_layout,
            mock_graph_data,
            mock_main_comp,
            mock_measures,
            mock_pagerank,
            mock_communities_payload,
        )
        # graph=True bypasses the bare-CLI early-exit; html=False suppresses tables.
        call_command(
            "structural_analysis",
            graph=True,
            html=False,
            community_strategies="ORGANIZATION",
            edge_weight_strategy="PARTIAL_REFERENCES",
        )
        mock_table_html.assert_not_called()
        mock_table_xls.assert_not_called()

    @patch(f"{_EXPORT_CMD}.exporter.copy_channel_media")
    @patch(f"{_EXPORT_CMD}.tables.write_table_xlsx")
    @patch(f"{_EXPORT_CMD}.tables.write_table_html")
    @patch(f"{_EXPORT_CMD}.exporter.write_graph_files")
    @patch(f"{_EXPORT_CMD}.exporter.ensure_graph_root")
    @patch(f"{_EXPORT_CMD}.exporter.reposition_isolated_nodes")
    @patch(f"{_EXPORT_CMD}.measures.apply_pagerank")
    @patch(f"{_EXPORT_CMD}.measures.apply_base_node_measures")
    @patch(f"{_EXPORT_CMD}.exporter.find_main_component")
    @patch(f"{_EXPORT_CMD}.exporter.build_graph_data")
    @patch(f"{_EXPORT_CMD}.layout.forceatlas2_positions")
    @patch(f"{_EXPORT_CMD}.community.build_communities_payload")
    @patch(f"{_EXPORT_CMD}.community.apply_edge_colors")
    @patch(f"{_EXPORT_CMD}.community.apply_to_graph")
    @patch(f"{_EXPORT_CMD}.community.detect")
    @patch(f"{_EXPORT_CMD}.graph_builder.build_graph")
    def test_table_format_xls_only(
        self,
        mock_build: MagicMock,
        mock_detect: MagicMock,
        mock_apply_to_graph: MagicMock,
        mock_edge_colors: MagicMock,
        mock_communities_payload: MagicMock,
        mock_layout: MagicMock,
        mock_graph_data: MagicMock,
        mock_main_comp: MagicMock,
        mock_measures: MagicMock,
        mock_pagerank: MagicMock,
        mock_reposition: MagicMock,
        mock_ensure: MagicMock,
        mock_write: MagicMock,
        mock_table_html: MagicMock,
        mock_table_xls: MagicMock,
        mock_copy: MagicMock,
    ) -> None:
        from django.core.management import call_command

        self._configure_happy_path(
            mock_build,
            mock_detect,
            mock_layout,
            mock_graph_data,
            mock_main_comp,
            mock_measures,
            mock_pagerank,
            mock_communities_payload,
        )
        call_command(
            "structural_analysis",
            html=False,
            xlsx=True,
            community_strategies="ORGANIZATION",
            edge_weight_strategy="PARTIAL_REFERENCES",
        )
        mock_table_html.assert_not_called()
        mock_table_xls.assert_called_once()

    @patch(f"{_EXPORT_CMD}.exporter.copy_channel_media")
    @patch(f"{_EXPORT_CMD}.tables.write_table_xlsx")
    @patch(f"{_EXPORT_CMD}.tables.write_table_html")
    @patch(f"{_EXPORT_CMD}.exporter.write_graph_files")
    @patch(f"{_EXPORT_CMD}.exporter.ensure_graph_root")
    @patch(f"{_EXPORT_CMD}.exporter.reposition_isolated_nodes")
    @patch(f"{_EXPORT_CMD}.measures.apply_pagerank")
    @patch(f"{_EXPORT_CMD}.measures.apply_base_node_measures")
    @patch(f"{_EXPORT_CMD}.exporter.find_main_component")
    @patch(f"{_EXPORT_CMD}.exporter.build_graph_data")
    @patch(f"{_EXPORT_CMD}.layout.forceatlas2_positions")
    @patch(f"{_EXPORT_CMD}.community.build_communities_payload")
    @patch(f"{_EXPORT_CMD}.community.apply_edge_colors")
    @patch(f"{_EXPORT_CMD}.community.apply_to_graph")
    @patch(f"{_EXPORT_CMD}.community.detect")
    @patch(f"{_EXPORT_CMD}.graph_builder.build_graph")
    def test_table_format_html_xls_calls_both(
        self,
        mock_build: MagicMock,
        mock_detect: MagicMock,
        mock_apply_to_graph: MagicMock,
        mock_edge_colors: MagicMock,
        mock_communities_payload: MagicMock,
        mock_layout: MagicMock,
        mock_graph_data: MagicMock,
        mock_main_comp: MagicMock,
        mock_measures: MagicMock,
        mock_pagerank: MagicMock,
        mock_reposition: MagicMock,
        mock_ensure: MagicMock,
        mock_write: MagicMock,
        mock_table_html: MagicMock,
        mock_table_xls: MagicMock,
        mock_copy: MagicMock,
    ) -> None:
        from django.core.management import call_command

        self._configure_happy_path(
            mock_build,
            mock_detect,
            mock_layout,
            mock_graph_data,
            mock_main_comp,
            mock_measures,
            mock_pagerank,
            mock_communities_payload,
        )
        call_command(
            "structural_analysis",
            html=True,
            xlsx=True,
            community_strategies="ORGANIZATION",
            edge_weight_strategy="PARTIAL_REFERENCES",
        )
        mock_table_html.assert_called_once()
        mock_table_xls.assert_called_once()


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_hits
# ---------------------------------------------------------------------------


class ApplyHitsTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(["1", "2", "3"])
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("3", "1")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_hub_and_authority_to_all_nodes(self) -> None:
        apply_hits(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("hits_hub", node)
            self.assertIn("hits_authority", node)

    def test_returns_two_labels(self) -> None:
        labels = apply_hits(self.graph_data, self.graph)
        keys = [k for k, _ in labels]
        self.assertIn("hits_hub", keys)
        self.assertIn("hits_authority", keys)

    def test_hub_and_authority_are_floats(self) -> None:
        apply_hits(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIsInstance(node["hits_hub"], float)
            self.assertIsInstance(node["hits_authority"], float)


# ---------------------------------------------------------------------------
# measures/_centrality.py — compute_betweenness / apply_betweenness_centrality
# ---------------------------------------------------------------------------


class ComputeBetweennessTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("a", "b"), ("b", "c"), ("a", "c")])

    def test_returns_dict_of_floats(self) -> None:
        result = compute_betweenness(self.graph)
        self.assertIsInstance(result, dict)
        for v in result.values():
            self.assertIsInstance(v, float)

    def test_intermediate_node_has_highest_betweenness(self) -> None:
        # a→b→c: b lies on the only path a→c (alongside the direct edge)
        graph = nx.DiGraph()
        graph.add_edges_from([("a", "b"), ("b", "c")])
        result = compute_betweenness(graph)
        # b is the only possible intermediate node
        self.assertGreater(result["b"], result["a"])
        self.assertGreater(result["b"], result["c"])


class ApplyBetweennessTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("1", "3")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_betweenness_key(self) -> None:
        apply_betweenness_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("betweenness", node)

    def test_precomputed_values_used_directly(self) -> None:
        precomputed = {"1": 0.5, "2": 0.25, "3": 0.0}
        apply_betweenness_centrality(self.graph_data, self.graph, betweenness=precomputed)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertAlmostEqual(node_map["1"]["betweenness"], 0.5)
        self.assertAlmostEqual(node_map["2"]["betweenness"], 0.25)


# ---------------------------------------------------------------------------
# measures/_centrality.py — in/out degree, harmonic, Katz centralities
# ---------------------------------------------------------------------------


class ApplyInDegreeCentralityTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("3", "2")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_in_degree_centrality_key(self) -> None:
        apply_in_degree_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("in_degree_centrality", node)

    def test_sink_node_has_higher_in_degree_than_source(self) -> None:
        apply_in_degree_centrality(self.graph_data, self.graph)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertGreater(node_map["2"]["in_degree_centrality"], node_map["1"]["in_degree_centrality"])


class ApplyOutDegreeCentralityTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("1", "3")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_out_degree_centrality_key(self) -> None:
        apply_out_degree_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("out_degree_centrality", node)

    def test_source_node_has_higher_out_degree_than_sinks(self) -> None:
        apply_out_degree_centrality(self.graph_data, self.graph)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertGreater(node_map["1"]["out_degree_centrality"], node_map["2"]["out_degree_centrality"])


class ApplyHarmonicCentralityTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("1", "3")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_harmonic_centrality_key(self) -> None:
        apply_harmonic_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("harmonic_centrality", node)

    def test_values_in_unit_interval(self) -> None:
        apply_harmonic_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertGreaterEqual(node["harmonic_centrality"], 0.0)
            self.assertLessEqual(node["harmonic_centrality"], 1.0)


class ApplyKatzCentralityTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("3", "1")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_katz_centrality_key(self) -> None:
        apply_katz_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("katz_centrality", node)

    def test_values_are_positive_floats(self) -> None:
        apply_katz_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIsInstance(node["katz_centrality"], float)
            self.assertGreater(node["katz_centrality"], 0.0)


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_closeness_centrality
# ---------------------------------------------------------------------------


class ApplyClosenessCentralityTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("1", "3")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_closeness_centrality_key(self) -> None:
        apply_closeness_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("closeness_centrality", node)

    def test_values_in_unit_interval(self) -> None:
        apply_closeness_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertGreaterEqual(node["closeness_centrality"], 0.0)
            self.assertLessEqual(node["closeness_centrality"], 1.0)

    def test_sink_node_has_highest_closeness(self) -> None:
        # Node "3" is reachable from all others in 1 hop, so it has maximal in-closeness.
        apply_closeness_centrality(self.graph_data, self.graph)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertGreater(node_map["3"]["closeness_centrality"], node_map["1"]["closeness_centrality"])

    def test_isolated_node_gets_zero(self) -> None:
        graph = nx.DiGraph()
        graph.add_node("isolated")
        graph_data: dict = {"nodes": [{"id": "isolated"}], "edges": []}
        apply_closeness_centrality(graph_data, graph)
        self.assertEqual(graph_data["nodes"][0]["closeness_centrality"], 0.0)


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_flow_betweenness_centrality
# ---------------------------------------------------------------------------


class ApplyFlowBetweennessTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("1", "3")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_flow_betweenness_key(self) -> None:
        apply_flow_betweenness_centrality(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("flow_betweenness", node)

    def test_disconnected_graph_outside_nodes_get_zero(self) -> None:
        graph = nx.DiGraph()
        graph.add_edges_from([("a", "b"), ("b", "c")])
        graph.add_node("isolated")
        graph_data: dict = {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "isolated"}],
            "edges": [],
        }
        apply_flow_betweenness_centrality(graph_data, graph)
        node_map = {n["id"]: n for n in graph_data["nodes"]}
        self.assertEqual(node_map["isolated"]["flow_betweenness"], 0.0)


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_burt_constraint
# ---------------------------------------------------------------------------


class ApplyBurtConstraintTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("1", "3")])
        self.graph.add_node("isolated")
        self.graph_data: dict = {
            "nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "isolated"}],
            "edges": [],
        }

    def test_adds_burt_constraint_key(self) -> None:
        apply_burt_constraint(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("burt_constraint", node)

    def test_isolated_node_gets_none(self) -> None:
        apply_burt_constraint(self.graph_data, self.graph)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertIsNone(node_map["isolated"]["burt_constraint"])

    def test_connected_node_gets_numeric_value(self) -> None:
        apply_burt_constraint(self.graph_data, self.graph)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertIsNotNone(node_map["1"]["burt_constraint"])
        self.assertIsInstance(node_map["1"]["burt_constraint"], float)


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_bridging_centrality
# ---------------------------------------------------------------------------


class ApplyBridgingCentralityTests(TestCase):
    def setUp(self) -> None:
        # Two triangles linked by a bridge node "bridge"
        self.graph = nx.DiGraph()
        self.graph.add_edges_from(
            [
                ("a", "b"),
                ("b", "a"),
                ("b", "bridge"),
                ("bridge", "c"),
                ("c", "d"),
                ("d", "c"),
            ]
        )
        for node_id, comm in [("a", "X"), ("b", "X"), ("bridge", "Y"), ("c", "Y"), ("d", "Y")]:
            self.graph.nodes[node_id]["data"] = {"communities": {"louvain": comm}}
        self.graph_data: dict = {
            "nodes": [{"id": n} for n in ["a", "b", "bridge", "c", "d"]],
            "edges": [],
        }

    def test_adds_bridging_centrality_key(self) -> None:
        apply_bridging_centrality(self.graph_data, self.graph, "louvain")
        for node in self.graph_data["nodes"]:
            self.assertIn("bridging_centrality", node)

    def test_bridge_node_scores_higher_than_within_community_node(self) -> None:
        apply_bridging_centrality(self.graph_data, self.graph, "louvain")
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        # "bridge" connects both communities; "a" connects only within X
        self.assertGreater(node_map["bridge"]["bridging_centrality"], node_map["a"]["bridging_centrality"])


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_ego_network_density
# ---------------------------------------------------------------------------


class ApplyEgoNetworkDensityTests(TestCase):
    def test_adds_ego_network_density_key(self) -> None:
        graph = nx.DiGraph()
        graph.add_edges_from([("v", "a"), ("v", "b"), ("a", "b")])
        gd: dict = {"nodes": [{"id": n} for n in graph.nodes()], "edges": []}
        apply_ego_network_density(gd, graph)
        for node in gd["nodes"]:
            self.assertIn("ego_network_density", node)

    def test_returns_label(self) -> None:
        graph = nx.DiGraph()
        graph.add_edges_from([("v", "a"), ("v", "b")])
        gd: dict = {"nodes": [{"id": "v"}], "edges": []}
        labels = apply_ego_network_density(gd, graph)
        self.assertEqual(labels, [("ego_network_density", "Ego Network Density")])

    def test_hub_with_disconnected_neighbours_gets_zero(self) -> None:
        # hub → a, b, c; a, b, c share no edges → density 0.0
        graph = nx.DiGraph()
        graph.add_edges_from([("hub", "a"), ("hub", "b"), ("hub", "c")])
        gd: dict = {"nodes": [{"id": "hub"}], "edges": []}
        apply_ego_network_density(gd, graph)
        self.assertAlmostEqual(gd["nodes"][0]["ego_network_density"], 0.0)

    def test_echo_with_fully_connected_neighbours_gets_one(self) -> None:
        # echo → a, b, c; a, b, c have all 6 directed edges between them → density 1.0
        graph = nx.DiGraph()
        graph.add_edges_from(
            [
                ("echo", "a"),
                ("echo", "b"),
                ("echo", "c"),
                ("a", "b"),
                ("b", "a"),
                ("b", "c"),
                ("c", "b"),
                ("a", "c"),
                ("c", "a"),
            ]
        )
        gd: dict = {"nodes": [{"id": "echo"}], "edges": []}
        apply_ego_network_density(gd, graph)
        self.assertAlmostEqual(gd["nodes"][0]["ego_network_density"], 1.0)

    def test_isolated_node_gets_none(self) -> None:
        graph = nx.DiGraph()
        graph.add_node("isolated")
        gd: dict = {"nodes": [{"id": "isolated"}], "edges": []}
        apply_ego_network_density(gd, graph)
        self.assertIsNone(gd["nodes"][0]["ego_network_density"])

    def test_single_neighbour_gets_none(self) -> None:
        graph = nx.DiGraph()
        graph.add_edge("v", "x")
        gd: dict = {"nodes": [{"id": "v"}], "edges": []}
        apply_ego_network_density(gd, graph)
        self.assertIsNone(gd["nodes"][0]["ego_network_density"])

    def test_echo_scores_higher_than_hub(self) -> None:
        hub_graph = nx.DiGraph()
        hub_graph.add_edges_from([("hub", "a"), ("hub", "b"), ("hub", "c")])
        hub_gd: dict = {"nodes": [{"id": "hub"}], "edges": []}
        apply_ego_network_density(hub_gd, hub_graph)

        echo_graph = nx.DiGraph()
        echo_graph.add_edges_from(
            [
                ("echo", "a"),
                ("echo", "b"),
                ("echo", "c"),
                ("a", "b"),
                ("b", "a"),
                ("b", "c"),
                ("c", "b"),
                ("a", "c"),
                ("c", "a"),
            ]
        )
        echo_gd: dict = {"nodes": [{"id": "echo"}], "edges": []}
        apply_ego_network_density(echo_gd, echo_graph)

        self.assertGreater(echo_gd["nodes"][0]["ego_network_density"], hub_gd["nodes"][0]["ego_network_density"])

    def test_values_in_unit_interval(self) -> None:
        graph = nx.DiGraph()
        graph.add_edges_from([("v", "a"), ("v", "b"), ("a", "b")])
        gd: dict = {"nodes": [{"id": "v"}], "edges": []}
        apply_ego_network_density(gd, graph)
        val = gd["nodes"][0]["ego_network_density"]
        self.assertGreaterEqual(val, 0.0)
        self.assertLessEqual(val, 1.0)


# ---------------------------------------------------------------------------
# measures/_centrality.py — apply_local_clustering
# ---------------------------------------------------------------------------


class ApplyLocalClusteringTests(TestCase):
    def setUp(self) -> None:
        # A directed 3-cycle: every node participates in exactly one directed triangle.
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("3", "1")])
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_local_clustering_key(self) -> None:
        apply_local_clustering(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertIn("local_clustering", node)

    def test_values_in_unit_interval(self) -> None:
        apply_local_clustering(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertGreaterEqual(node["local_clustering"], 0.0)
            self.assertLessEqual(node["local_clustering"], 1.0)

    def test_cycle_nodes_have_nonzero_clustering(self) -> None:
        # Every node in a 3-cycle is part of a directed triangle.
        apply_local_clustering(self.graph_data, self.graph)
        for node in self.graph_data["nodes"]:
            self.assertGreater(node["local_clustering"], 0.0)

    def test_isolated_node_gets_zero(self) -> None:
        graph = nx.DiGraph()
        graph.add_node("isolated")
        graph_data: dict = {"nodes": [{"id": "isolated"}], "edges": []}
        apply_local_clustering(graph_data, graph)
        self.assertEqual(graph_data["nodes"][0]["local_clustering"], 0.0)

    def test_returns_label(self) -> None:
        labels = apply_local_clustering(self.graph_data, self.graph)
        keys = [k for k, _ in labels]
        self.assertIn("local_clustering", keys)


# ---------------------------------------------------------------------------
# measures/_spreading.py — apply_spreading_efficiency
# ---------------------------------------------------------------------------


class ApplySpreadingEfficiencyTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from(
            [("1", "2", {"weight": 1.0}), ("2", "3", {"weight": 1.0}), ("1", "3", {"weight": 1.0})]
        )
        self.graph_data: dict = {"nodes": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "edges": []}

    def test_adds_spreading_efficiency_key(self) -> None:
        apply_spreading_efficiency(self.graph_data, self.graph, runs=10)
        for node in self.graph_data["nodes"]:
            self.assertIn("spreading_efficiency", node)

    def test_single_node_graph_gets_zero(self) -> None:
        graph = nx.DiGraph()
        graph.add_node("solo")
        graph_data: dict = {"nodes": [{"id": "solo"}], "edges": []}
        apply_spreading_efficiency(graph_data, graph, runs=5)
        self.assertEqual(graph_data["nodes"][0]["spreading_efficiency"], 0.0)

    def test_values_in_unit_interval(self) -> None:
        apply_spreading_efficiency(self.graph_data, self.graph, runs=10)
        for node in self.graph_data["nodes"]:
            self.assertGreaterEqual(node["spreading_efficiency"], 0.0)
            self.assertLessEqual(node["spreading_efficiency"], 1.0)


# ---------------------------------------------------------------------------
# measures/_content.py — apply_amplification_factor
# ---------------------------------------------------------------------------


class ApplyAmplificationFactorTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org", is_in_target=True, color="#FF0000")
        self.ch1 = Channel.objects.create(telegram_id=10, organization=org, title="Source")
        self.ch2 = Channel.objects.create(telegram_id=11, organization=org, title="Amplifier")
        # ch1 has 4 own messages; ch2 forwards 2 of ch1's messages into ch2's channel
        # → ch1's content is "amplified" 2 times; ch1 has 4 messages → factor = 2/4 = 0.5
        Message.objects.create(telegram_id=1, channel=self.ch1)
        Message.objects.create(telegram_id=2, channel=self.ch1)
        Message.objects.create(telegram_id=3, channel=self.ch1)
        Message.objects.create(telegram_id=4, channel=self.ch1)
        Message.objects.create(telegram_id=5, channel=self.ch2, forwarded_from=self.ch1)
        Message.objects.create(telegram_id=6, channel=self.ch2, forwarded_from=self.ch1)
        self.channel_dict = {
            str(self.ch1.pk): {"channel": self.ch1},
            str(self.ch2.pk): {"channel": self.ch2},
        }
        self.graph_data: dict = {
            "nodes": [{"id": str(self.ch1.pk)}, {"id": str(self.ch2.pk)}],
            "edges": [],
        }
        self.graph = nx.DiGraph()

    def test_amplification_factor_computed_correctly(self) -> None:
        apply_amplification_factor(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        # ch1 has 4 messages and is forwarded 2 times → 2/4 = 0.5
        self.assertAlmostEqual(node_map[str(self.ch1.pk)]["amplification_factor"], 0.5)
        # ch2 is never forwarded from → 0.0
        self.assertEqual(node_map[str(self.ch2.pk)]["amplification_factor"], 0.0)

    def test_channel_with_no_messages_gets_zero(self) -> None:
        apply_amplification_factor(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertEqual(node_map[str(self.ch2.pk)]["amplification_factor"], 0.0)


# ---------------------------------------------------------------------------
# measures/_content.py — apply_content_originality
# ---------------------------------------------------------------------------


class ApplyContentOriginalityTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org2", is_in_target=True, color="#00FF00")
        self.ch1 = Channel.objects.create(telegram_id=20, organization=org, title="Original")
        self.ch2 = Channel.objects.create(telegram_id=21, organization=org, title="Forwarder")
        # ch1: 4 messages, 0 forwarded → originality 1.0
        for i in range(4):
            Message.objects.create(telegram_id=100 + i, channel=self.ch1)
        # ch2: 4 messages, 2 forwarded → originality 0.5
        Message.objects.create(telegram_id=200, channel=self.ch2, forwarded_from=self.ch1)
        Message.objects.create(telegram_id=201, channel=self.ch2, forwarded_from=self.ch1)
        Message.objects.create(telegram_id=202, channel=self.ch2)
        Message.objects.create(telegram_id=203, channel=self.ch2)
        graph = nx.DiGraph()
        self.channel_dict = {
            str(self.ch1.pk): {"channel": self.ch1},
            str(self.ch2.pk): {"channel": self.ch2},
        }
        self.graph_data: dict = {
            "nodes": [{"id": str(self.ch1.pk)}, {"id": str(self.ch2.pk)}],
            "edges": [],
        }
        self.graph = graph

    def test_all_original_messages_scores_one(self) -> None:
        apply_content_originality(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertAlmostEqual(node_map[str(self.ch1.pk)]["content_originality"], 1.0)

    def test_half_forwarded_scores_half(self) -> None:
        apply_content_originality(self.graph_data, self.graph, self.channel_dict)
        node_map = {n["id"]: n for n in self.graph_data["nodes"]}
        self.assertAlmostEqual(node_map[str(self.ch2.pk)]["content_originality"], 0.5)

    def test_channel_with_no_messages_gets_none(self) -> None:
        org = Organization.objects.create(name="OrgEmpty", is_in_target=True, color="#0000FF")
        empty_ch = Channel.objects.create(telegram_id=99, organization=org, title="Empty")
        channel_dict = {str(empty_ch.pk): {"channel": empty_ch}}
        graph_data: dict = {"nodes": [{"id": str(empty_ch.pk)}], "edges": []}
        apply_content_originality(graph_data, nx.DiGraph(), channel_dict)
        self.assertIsNone(graph_data["nodes"][0]["content_originality"])


# ---------------------------------------------------------------------------
# community_stats.py — _freeman_centralization
# ---------------------------------------------------------------------------


class FreemanCentralizationTests(TestCase):
    def test_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(_freeman_centralization([]))

    def test_returns_none_for_single_value(self) -> None:
        self.assertIsNone(_freeman_centralization([0.5]))

    def test_returns_none_when_all_zero(self) -> None:
        self.assertIsNone(_freeman_centralization([0.0, 0.0, 0.0]))

    def test_returns_zero_for_equal_values(self) -> None:
        result = _freeman_centralization([0.5, 0.5, 0.5])
        self.assertAlmostEqual(result, 0.0)

    def test_returns_one_for_star_pattern(self) -> None:
        # One node with max centrality, all others at zero → centralization = 1.0
        result = _freeman_centralization([1.0, 0.0, 0.0])
        self.assertAlmostEqual(result, 1.0)

    def test_none_entries_ignored(self) -> None:
        # None entries should be filtered; result same as [1.0, 0.0, 0.0]
        result = _freeman_centralization([1.0, None, 0.0, None, 0.0])
        self.assertAlmostEqual(result, 1.0)


# ---------------------------------------------------------------------------
# community_stats.py — _network_summary
# ---------------------------------------------------------------------------


class NetworkSummaryTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("a", "b"), ("b", "c"), ("c", "a"), ("a", "c")])

    def test_returns_expected_keys(self) -> None:
        summary = _network_summary(self.graph)
        for key in ("n", "e", "density", "reciprocity", "avg_clustering", "wcc_count", "scc_count"):
            self.assertIn(key, summary)

    def test_node_and_edge_counts_correct(self) -> None:
        summary = _network_summary(self.graph)
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["e"], 4)

    def test_density_in_unit_interval(self) -> None:
        summary = _network_summary(self.graph)
        self.assertGreaterEqual(summary["density"], 0.0)
        self.assertLessEqual(summary["density"], 1.0)

    def test_empty_graph_does_not_raise(self) -> None:
        summary = _network_summary(nx.DiGraph())
        self.assertEqual(summary["n"], 0)
        self.assertEqual(summary["e"], 0)


# ---------------------------------------------------------------------------
# community_stats.py — network_summary_rows
# ---------------------------------------------------------------------------


class NetworkSummaryRowsTests(TestCase):
    def _make_summary(self) -> dict:
        return {
            "n": 5,
            "e": 8,
            "density": 0.4,
            "reciprocity": 0.25,
            "avg_clustering": 0.3,
            "avg_path_length": 2.1,
            "diameter": 4,
            "path_on_full": True,
            "wcc_count": 1,
            "wcc_fraction": 1.0,
            "scc_count": 2,
            "scc_fraction": 0.6,
            "assortativity": {"in_in": None, "in_out": None, "out_in": None, "out_out": None},
            "centralizations": {},
        }

    def test_returns_list_of_three_tuples(self) -> None:
        rows = network_summary_rows(self._make_summary())
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIsInstance(row, tuple)
            self.assertEqual(len(row), 3)

    def test_nodes_row_present(self) -> None:
        rows = network_summary_rows(self._make_summary())
        labels = [r[0] for r in rows]
        self.assertIn("Nodes", labels)

    def test_edges_row_value_matches_summary(self) -> None:
        rows = network_summary_rows(self._make_summary())
        row_map = {r[0]: r[1] for r in rows}
        self.assertEqual(row_map["Nodes"], 5)
        self.assertEqual(row_map["Edges"], 8)


# ---------------------------------------------------------------------------
# community_stats.py — compute_community_metrics
# ---------------------------------------------------------------------------


class ComputeCommunityMetricsTests(TestCase):
    def setUp(self) -> None:
        self.graph = nx.DiGraph()
        self.graph.add_edges_from([("1", "2"), ("2", "3"), ("3", "1")])
        for node_id in ["1", "2", "3"]:
            self.graph.nodes[node_id]["data"] = {"communities": {"leiden": f"comm_{node_id}"}}
        self.graph_data: dict = {
            "nodes": [
                {"id": "1", "communities": {"leiden": "comm_1"}},
                {"id": "2", "communities": {"leiden": "comm_2"}},
                {"id": "3", "communities": {"leiden": "comm_3"}},
            ],
            "edges": [],
        }
        self.communities_data = {
            "leiden": {
                "groups": [
                    (1, 1, "comm_1", "#ff0000"),
                    (2, 1, "comm_2", "#00ff00"),
                    (3, 1, "comm_3", "#0000ff"),
                ]
            }
        }

    def test_returns_network_summary_and_strategies_keys(self) -> None:
        result = compute_community_metrics(self.graph_data, self.communities_data, self.graph, ["leiden"])
        self.assertIn("network_summary", result)
        self.assertIn("strategies", result)

    def test_network_summary_has_correct_node_count(self) -> None:
        result = compute_community_metrics(self.graph_data, self.communities_data, self.graph, ["leiden"])
        self.assertEqual(result["network_summary"]["n"], 3)

    def test_strategy_entry_present_for_requested_strategy(self) -> None:
        result = compute_community_metrics(self.graph_data, self.communities_data, self.graph, ["leiden"])
        self.assertIn("leiden", result["strategies"])

    def test_status_callback_called_for_each_step(self) -> None:
        calls: list[str] = []
        compute_community_metrics(
            self.graph_data,
            self.communities_data,
            self.graph,
            ["leiden"],
            status_callback=calls.append,
        )
        # callback called once for "network" and once per strategy
        self.assertGreaterEqual(len(calls), 2)


class DisparityFilterTests(TestCase):
    def _star(self, n_leaves: int, weights: "list[float] | None" = None) -> nx.DiGraph:
        """Directed star ``A → L0, L1, …`` with the given outgoing weights."""
        g = nx.DiGraph()
        if weights is None:
            weights = [1.0] * n_leaves
        for i, w in enumerate(weights):
            g.add_edge("A", f"L{i}", weight=w)
        return g

    def test_single_outgoing_edge_kept_under_strict_threshold(self) -> None:
        # A → B (only outgoing), B has only incoming from A: k_out=k_in=1 → α=0 both sides
        g = nx.DiGraph()
        g.add_edge("A", "B", weight=42.0)
        from network.robustness import disparity_filter

        backbone = disparity_filter(g, alpha=1e-12)
        self.assertEqual(set(backbone.edges()), {("A", "B")})

    def test_uniform_distribution_is_filtered_out(self) -> None:
        # Source A fans out to 4 targets with equal weight; each target also has
        # 4 incoming edges of equal weight from background sources. With p = 1/4
        # and k = 4 the disparity α = (3/4)^3 = 0.4219… well above the 0.05
        # threshold from *both* sides, so A's outgoing edges should be removed.
        from network.robustness import disparity_filter

        g = nx.DiGraph()
        for tgt in ("B", "C", "D", "E"):
            g.add_edge("A", tgt, weight=1.0)
            for src in range(3):  # 3 extra background sources → target k_in = 4
                g.add_edge(f"S{tgt}{src}", tgt, weight=1.0)
        backbone = disparity_filter(g, alpha=0.05)
        for tgt in ("B", "C", "D", "E"):
            self.assertNotIn(("A", tgt), backbone.edges())

    def test_dominant_edge_survives_strict_threshold(self) -> None:
        # Hub A: one dominant edge to B (weight 100), nine background edges of weight 1.
        # B also has many incoming edges so α_in is not trivially 0.
        # α_out for (A, B) = (1 - 100/109)^9 = (9/109)^9 ≈ 2.4e-10 ≪ 0.05.
        from network.robustness import disparity_filter

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=100.0)
        for i in range(9):
            g.add_edge("A", f"X{i}", weight=1.0)
        for i in range(9):
            g.add_edge(f"Y{i}", "B", weight=1.0)
        backbone = disparity_filter(g, alpha=0.05)
        self.assertIn(("A", "B"), backbone.edges())
        # The nine background edges of A are not concentrated enough on either side
        # (each target has k_in = 1, though, so α_in = 0 from that side → kept).
        # So this test only checks the dominant edge — see next test for full filtering.

    def test_alpha_threshold_at_one_keeps_every_edge(self) -> None:
        # min(α_in, α_out) is always < 1 for any positive-weight edge, so α=1 → everything kept.
        from network.robustness import disparity_filter

        g = self._star(5, weights=[1.0, 2.0, 3.0, 4.0, 5.0])
        backbone = disparity_filter(g, alpha=1.0)
        self.assertEqual(g.number_of_edges(), backbone.number_of_edges())

    def test_invalid_alpha_raises(self) -> None:
        from network.robustness import disparity_filter

        g = self._star(2)
        with self.assertRaises(ValueError):
            disparity_filter(g, alpha=0.0)
        with self.assertRaises(ValueError):
            disparity_filter(g, alpha=1.5)
        with self.assertRaises(ValueError):
            disparity_filter(g, alpha=-0.1)

    def test_nodes_and_node_attributes_preserved(self) -> None:
        from network.robustness import disparity_filter

        g = nx.DiGraph()
        g.add_node("A", color="red", label="source")
        g.add_node("B", color="blue", label="target")
        g.add_edge("A", "B", weight=1.0)
        backbone = disparity_filter(g, alpha=0.5)
        self.assertEqual(set(backbone.nodes()), {"A", "B"})
        self.assertEqual(backbone.nodes["A"]["color"], "red")
        self.assertEqual(backbone.nodes["B"]["label"], "target")

    def test_edge_attributes_preserved_on_retained_edges(self) -> None:
        from network.robustness import disparity_filter

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=1.0, color="green", tag="forward")
        backbone = disparity_filter(g, alpha=0.5)
        self.assertEqual(backbone.edges["A", "B"]["color"], "green")
        self.assertEqual(backbone.edges["A", "B"]["tag"], "forward")

    def test_isolated_nodes_remain_in_backbone(self) -> None:
        # Filtering may strip all of a node's edges; the node itself is kept.
        from network.robustness import disparity_filter

        g = nx.DiGraph()
        # uniform 4-fan with k_in = 4 on every target → α ≈ 0.42 > 0.05 from both sides
        for tgt in ("B", "C", "D", "E"):
            g.add_edge("A", tgt, weight=1.0)
            for src in range(3):
                g.add_edge(f"S{tgt}{src}", tgt, weight=1.0)
        backbone = disparity_filter(g, alpha=0.05)
        self.assertIn("A", backbone.nodes())  # A may be isolated but must be present

    def test_compute_alpha_values_returns_pair_per_edge_in_unit_interval(self) -> None:
        from network.robustness import compute_alpha_values

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=10.0)
        g.add_edge("A", "C", weight=1.0)
        g.add_edge("D", "B", weight=1.0)
        alphas = compute_alpha_values(g)
        self.assertEqual(set(alphas.keys()), {("A", "B"), ("A", "C"), ("D", "B")})
        for a_in, a_out in alphas.values():
            self.assertGreaterEqual(a_in, 0.0)
            self.assertLessEqual(a_in, 1.0)
            self.assertGreaterEqual(a_out, 0.0)
            self.assertLessEqual(a_out, 1.0)

    def test_compute_alpha_values_matches_serrano_formula(self) -> None:
        # Source A has k_out = 3, weights [1, 1, 1] → p = 1/3, α = (2/3)^2 ≈ 0.4444
        # Target B/C/D each has k_in = 1 → α_in = 0
        from network.robustness import compute_alpha_values

        g = nx.DiGraph()
        for tgt in ("B", "C", "D"):
            g.add_edge("A", tgt, weight=1.0)
        alphas = compute_alpha_values(g)
        expected_alpha_out = (2.0 / 3.0) ** 2
        for tgt in ("B", "C", "D"):
            a_in, a_out = alphas[("A", tgt)]
            self.assertAlmostEqual(a_out, expected_alpha_out, places=10)
            self.assertEqual(a_in, 0.0)


class AttackCurveTests(TestCase):
    def test_wcc_curve_on_directed_chain_matches_closed_form(self) -> None:
        # Chain A → B → C → D, removed in order. WCC is computed undirected, so
        # the residual chain shrinks one node at a time: S(q) = (N - q) / N.
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C"), ("C", "D")])
        curve = attack_curve(g, ["A", "B", "C", "D"], "WCC")
        self.assertEqual(curve, [1.0, 0.75, 0.5, 0.25, 0.0])

    def test_wcc_curve_on_clique_decreases_linearly(self) -> None:
        # In a directed clique every removal leaves a smaller clique, fully connected.
        from network.robustness import attack_curve

        g = nx.complete_graph(5, create_using=nx.DiGraph)
        curve = attack_curve(g, list(g.nodes()), "WCC")
        for q, s in enumerate(curve):
            self.assertAlmostEqual(s, (5 - q) / 5)

    def test_wcc_curve_on_star_center_first_collapses_immediately(self) -> None:
        # Removing the centre of a star isolates every leaf → S(1) = 1/N.
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edges_from([("C", "L1"), ("C", "L2"), ("C", "L3"), ("C", "L4")])
        curve = attack_curve(g, ["C", "L1", "L2", "L3", "L4"], "WCC")
        # S(0)=1, S(1..4)=1/5 (each leaf is its own singleton WCC), S(5)=0
        self.assertEqual(curve, [1.0, 0.2, 0.2, 0.2, 0.2, 0.0])

    def test_wcc_curve_on_star_leaves_first_decreases_smoothly(self) -> None:
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edges_from([("C", "L1"), ("C", "L2"), ("C", "L3"), ("C", "L4")])
        curve = attack_curve(g, ["L1", "L2", "L3", "L4", "C"], "WCC")
        self.assertEqual(curve, [1.0, 0.8, 0.6, 0.4, 0.2, 0.0])

    def test_scc_curve_on_directed_cycle(self) -> None:
        # A → B → C → A: one SCC of size 3, then only singletons after any removal.
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C"), ("C", "A")])
        curve = attack_curve(g, ["A", "B", "C"], "SCC")
        self.assertAlmostEqual(curve[0], 1.0)
        self.assertAlmostEqual(curve[1], 1.0 / 3.0)
        self.assertAlmostEqual(curve[2], 1.0 / 3.0)
        self.assertAlmostEqual(curve[3], 0.0)

    def test_reach_curve_on_directed_chain_matches_closed_form(self) -> None:
        # A → B → C → D: reachable pairs = AB, AC, AD, BC, BD, CD = 6.
        # Total ordered pairs = 4*3 = 12. S(0) = 6/12 = 0.5.
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C"), ("C", "D")])
        curve = attack_curve(g, ["A", "B", "C", "D"], "REACH", reach_sample=None)
        self.assertAlmostEqual(curve[0], 0.5)
        # Removing A drops 3 pairs (A→B, A→C, A→D) → 3/12 = 0.25
        self.assertAlmostEqual(curve[1], 0.25)

    def test_reach_curve_with_sampling_stays_in_unit_interval(self) -> None:
        from network.robustness import attack_curve

        g = nx.gnp_random_graph(50, 0.1, seed=42, directed=True)
        rng = np.random.default_rng(7)
        curve = attack_curve(g, list(g.nodes()), "REACH", reach_sample=10, rng=rng)
        for s in curve:
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_reach_sampling_reproducible_with_seed(self) -> None:
        from network.robustness import attack_curve

        g = nx.gnp_random_graph(40, 0.15, seed=42, directed=True)
        order = list(g.nodes())
        c1 = attack_curve(g, order, "REACH", reach_sample=8, rng=np.random.default_rng(0))
        c2 = attack_curve(g, order, "REACH", reach_sample=8, rng=np.random.default_rng(0))
        self.assertEqual(c1, c2)

    def test_invalid_metric_raises(self) -> None:
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edge("A", "B")
        with self.assertRaises(ValueError):
            attack_curve(g, ["A"], "INVALID")  # type: ignore[arg-type]

    def test_empty_graph_returns_single_zero(self) -> None:
        from network.robustness import attack_curve

        self.assertEqual(attack_curve(nx.DiGraph(), [], "WCC"), [0.0])

    def test_removal_order_with_missing_nodes_is_silently_skipped(self) -> None:
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edge("A", "B")
        curve = attack_curve(g, ["A", "X", "B"], "WCC")
        # S(0)=1 (one WCC of 2 over 2), S(1)=0.5 after A, X is missing → 0.5, S(3)=0
        self.assertEqual(curve, [1.0, 0.5, 0.5, 0.0])

    def test_does_not_mutate_input_graph(self) -> None:
        from network.robustness import attack_curve

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C")])
        before = (set(g.nodes()), set(g.edges()))
        attack_curve(g, ["A", "B"], "WCC")
        after = (set(g.nodes()), set(g.edges()))
        self.assertEqual(before, after)


class RIndexAndThresholdTests(TestCase):
    def test_r_index_on_chain_matches_closed_form(self) -> None:
        # Closed form for a chain removed sequentially: R = (N-1) / (2N).
        from network.robustness import attack_curve, r_index

        g = nx.DiGraph()
        g.add_edges_from([(str(i), str(i + 1)) for i in range(3)])
        curve = attack_curve(g, ["0", "1", "2", "3"], "WCC")
        self.assertAlmostEqual(r_index(curve), 3.0 / 8.0)

    def test_r_index_on_clique_matches_closed_form(self) -> None:
        from network.robustness import attack_curve, r_index

        g = nx.complete_graph(5, create_using=nx.DiGraph)
        curve = attack_curve(g, list(g.nodes()), "WCC")
        self.assertAlmostEqual(r_index(curve), (5 - 1) / (2 * 5))

    def test_r_index_star_center_first_lower_than_leaves_first(self) -> None:
        # Targeted hub removal must give a strictly lower R than peripheral.
        from network.robustness import attack_curve, r_index

        g = nx.DiGraph()
        g.add_edges_from([("C", "L1"), ("C", "L2"), ("C", "L3"), ("C", "L4")])
        r_center = r_index(attack_curve(g, ["C", "L1", "L2", "L3", "L4"], "WCC"))
        r_leaves = r_index(attack_curve(g, ["L1", "L2", "L3", "L4", "C"], "WCC"))
        self.assertLess(r_center, r_leaves)
        # And matches the analytical values exactly: 0.16 vs 0.40.
        self.assertAlmostEqual(r_center, 0.16)
        self.assertAlmostEqual(r_leaves, 0.40)

    def test_r_index_zero_on_empty_or_single_point_curve(self) -> None:
        from network.robustness import r_index

        self.assertEqual(r_index([]), 0.0)
        self.assertEqual(r_index([1.0]), 0.0)

    def test_critical_threshold_returns_fraction_at_collapse(self) -> None:
        from network.robustness import critical_threshold

        # N=4, S(0)=1, threshold = 0.05*1 = 0.05; first drop below at q=2.
        curve = [1.0, 0.5, 0.04, 0.0, 0.0]
        self.assertAlmostEqual(critical_threshold(curve, drop_to=0.05), 0.5)

    def test_critical_threshold_none_when_never_reached(self) -> None:
        from network.robustness import critical_threshold

        self.assertIsNone(critical_threshold([1.0, 0.9, 0.8, 0.7, 0.6, 0.5], drop_to=0.05))

    def test_critical_threshold_handles_degenerate_inputs(self) -> None:
        from network.robustness import critical_threshold

        self.assertIsNone(critical_threshold([], 0.05))
        self.assertIsNone(critical_threshold([0.0, 0.0], 0.05))
        self.assertIsNone(critical_threshold([0.0], 0.05))


class WeightedGlobalEfficiencyTests(TestCase):
    def test_returns_zero_for_acyclic_graph(self) -> None:
        # A → B has no two-node SCC, so efficiency is 0.
        from network.robustness import weighted_global_efficiency

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=2.0)
        self.assertEqual(weighted_global_efficiency(g), 0.0)

    def test_two_node_bidirectional_matches_formula(self) -> None:
        # Distance = 1/weight = 0.5; 1/d = 2.0 per ordered pair; sum / (n*(n-1)) = 4/2 = 2.0.
        from network.robustness import weighted_global_efficiency

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=2.0)
        g.add_edge("B", "A", weight=2.0)
        self.assertAlmostEqual(weighted_global_efficiency(g), 2.0)

    def test_two_node_unit_weight_matches_unweighted_value(self) -> None:
        # With weight 1 the weighted form coincides with the unweighted efficiency = 1.
        from network.robustness import weighted_global_efficiency

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=1.0)
        g.add_edge("B", "A", weight=1.0)
        self.assertAlmostEqual(weighted_global_efficiency(g), 1.0)

    def test_empty_and_singleton_graphs_return_zero(self) -> None:
        from network.robustness import weighted_global_efficiency

        self.assertEqual(weighted_global_efficiency(nx.DiGraph()), 0.0)
        g = nx.DiGraph()
        g.add_node("A")
        self.assertEqual(weighted_global_efficiency(g), 0.0)

    def test_nodes_argument_restricts_before_scc_search(self) -> None:
        # Full graph: bidirectional triangle A↔B↔C↔A → one SCC = {A, B, C}.
        # Restricted to {A, B}: only the A↔B pair, SCC = {A, B}, efficiency = 1.
        from network.robustness import weighted_global_efficiency

        g = nx.DiGraph()
        for u, v in [("A", "B"), ("B", "A"), ("B", "C"), ("C", "B"), ("A", "C"), ("C", "A")]:
            g.add_edge(u, v, weight=1.0)
        self.assertAlmostEqual(weighted_global_efficiency(g), 1.0)  # full triangle
        self.assertAlmostEqual(weighted_global_efficiency(g, nodes={"A", "B"}), 1.0)


class RemovalOrderTests(TestCase):
    def test_strategy_constants_partition_correctly(self) -> None:
        from network.robustness import ALL_STRATEGIES, DEFAULT_STRATEGIES, DYNAMIC_STRATEGIES, STATIC_STRATEGIES

        self.assertEqual(set(ALL_STRATEGIES), STATIC_STRATEGIES | DYNAMIC_STRATEGIES)
        self.assertEqual(STATIC_STRATEGIES & DYNAMIC_STRATEGIES, set())
        # Static includes random + degree (2) + prestige (4) + reach (2) + brokerage (4) + spreading (1) = 14
        self.assertEqual(len(STATIC_STRATEGIES), 14)
        # Dynamic includes in_strength_dyn, out_strength_dyn, pagerank_dyn, katz_dyn, hits_hub_dyn, hits_authority_dyn, betweenness_dyn
        self.assertEqual(len(DYNAMIC_STRATEGIES), 7)
        self.assertEqual(len(ALL_STRATEGIES), 21)
        # The default set is the original 5 (preserves backwards-compatible behaviour)
        self.assertEqual(DEFAULT_STRATEGIES, ["random", "in_strength", "out_strength", "pagerank", "betweenness"])

    def test_random_returns_permutation_of_nodes(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C"), ("C", "D")])
        order = removal_order(g, "random", rng=np.random.default_rng(0))
        self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_random_reproducible_with_same_seed(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(20, 0.2, seed=42, directed=True)
        o1 = removal_order(g, "random", rng=np.random.default_rng(0))
        o2 = removal_order(g, "random", rng=np.random.default_rng(0))
        self.assertEqual(o1, o2)
        # Different seeds should diverge (probability ≈ 1 for a 20-node permutation)
        o3 = removal_order(g, "random", rng=np.random.default_rng(1))
        self.assertNotEqual(o1, o3)

    def test_in_strength_static_sorted_descending(self) -> None:
        from network.robustness import removal_order

        # B in_str=3, C in_str=2, A and X both in_str=0
        g = nx.DiGraph()
        g.add_edge("X", "B", weight=3.0)
        g.add_edge("X", "C", weight=2.0)
        g.add_node("A")
        order = removal_order(g, "in_strength")
        # Sort: B(3), C(2), A(0), X(0)  — A before X by ascending ID
        self.assertEqual(order, ["B", "C", "A", "X"])

    def test_out_strength_static_sorted_descending(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=5.0)
        g.add_edge("A", "C", weight=3.0)
        g.add_edge("D", "C", weight=1.0)
        # A out_str=8, D out_str=1, B and C out_str=0
        order = removal_order(g, "out_strength")
        self.assertEqual(order, ["A", "D", "B", "C"])

    def test_static_tie_breaking_is_ascending_node_id(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        for nid in ("Z", "A", "M"):
            g.add_node(nid)
        order = removal_order(g, "in_strength")
        self.assertEqual(order, ["A", "M", "Z"])

    def test_in_strength_dyn_differs_from_static_on_chain(self) -> None:
        # Chain A → B → C → D, all weight 1.
        # Static in_strength: B, C, D tied at 1; sort by ID; A=0 last → [B, C, D, A].
        # Dynamic: B picked first (tie at 1, smallest ID). Removing B disconnects C, so C and D
        # now both have in_str 0 except D which still has in_edge from C → D picked next.
        # Then A and C both 0 → A (smaller ID), then C.
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=1.0)
        g.add_edge("B", "C", weight=1.0)
        g.add_edge("C", "D", weight=1.0)
        self.assertEqual(removal_order(g, "in_strength"), ["B", "C", "D", "A"])
        self.assertEqual(removal_order(g, "in_strength_dyn"), ["B", "D", "A", "C"])

    def test_pagerank_returns_permutation_of_nodes(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(15, 0.2, seed=42, directed=True)
        order = removal_order(g, "pagerank")
        self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_pagerank_dyn_returns_permutation_of_nodes(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(15, 0.2, seed=42, directed=True)
        order = removal_order(g, "pagerank_dyn")
        self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_betweenness_picks_center_first_on_bidirectional_star(self) -> None:
        # Bidirectional star: every leaf-to-leaf shortest path passes through the centre.
        from network.robustness import removal_order

        g = nx.DiGraph()
        for leaf in ("L1", "L2", "L3", "L4"):
            g.add_edge("C", leaf, weight=1.0)
            g.add_edge(leaf, "C", weight=1.0)
        order = removal_order(g, "betweenness")
        self.assertEqual(order[0], "C")

    def test_betweenness_dyn_returns_permutation_of_nodes(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(10, 0.3, seed=42, directed=True)
        order = removal_order(g, "betweenness_dyn")
        self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_empty_graph_returns_empty_order(self) -> None:
        from network.robustness import removal_order

        self.assertEqual(removal_order(nx.DiGraph(), "in_strength"), [])
        self.assertEqual(removal_order(nx.DiGraph(), "random", rng=np.random.default_rng(0)), [])
        self.assertEqual(removal_order(nx.DiGraph(), "pagerank_dyn"), [])
        self.assertEqual(removal_order(nx.DiGraph(), "betweenness_dyn"), [])

    def test_invalid_strategy_raises(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_node("A")
        with self.assertRaises(ValueError):
            removal_order(g, "no-such-strategy")

    def test_does_not_mutate_input_graph(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C"), ("C", "A")])
        before_nodes, before_edges = set(g.nodes()), set(g.edges())
        for strat in ("in_strength", "pagerank", "betweenness", "pagerank_dyn", "betweenness_dyn"):
            removal_order(g, strat)
        self.assertEqual((set(g.nodes()), set(g.edges())), (before_nodes, before_edges))

    def test_new_static_scorers_return_permutations(self) -> None:
        # Every new graph-based static scorer should produce a permutation of the node set.
        from network.robustness import removal_order

        g = nx.gnp_random_graph(15, 0.25, seed=42, directed=True)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = 1.0
        for strat in (
            "katz",
            "hits_hub",
            "hits_authority",
            "harmonic",
            "closeness",
            "flow_betweenness",
            "burt_constraint",
            "spreading",
        ):
            with self.subTest(strategy=strat):
                order = removal_order(g, strat)
                self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_new_dynamic_scorers_return_permutations(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(10, 0.3, seed=42, directed=True)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = 1.0
        for strat in ("out_strength_dyn", "katz_dyn", "hits_hub_dyn", "hits_authority_dyn"):
            with self.subTest(strategy=strat):
                order = removal_order(g, strat)
                self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_burt_constraint_sorts_ascending(self) -> None:
        # A bridge node between two cliques has low constraint (~0); clique-internal
        # nodes have higher constraint.  Ascending sort puts the bridge first.
        from network.robustness import removal_order

        g = nx.DiGraph()
        # Two 3-cliques (A,B,C) and (D,E,F) connected via bridge node X
        for a, b in [("A", "B"), ("B", "C"), ("C", "A"), ("B", "A"), ("C", "B"), ("A", "C")]:
            g.add_edge(a, b, weight=1.0)
        for a, b in [("D", "E"), ("E", "F"), ("F", "D"), ("E", "D"), ("F", "E"), ("D", "F")]:
            g.add_edge(a, b, weight=1.0)
        g.add_edge("A", "X", weight=1.0)
        g.add_edge("X", "A", weight=1.0)
        g.add_edge("X", "D", weight=1.0)
        g.add_edge("D", "X", weight=1.0)
        order = removal_order(g, "burt_constraint")
        # X is the only bridge node — should have the lowest constraint and be removed first.
        self.assertEqual(order[0], "X")

    def test_bridging_with_explicit_partition_basis(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(10, 0.3, seed=42, directed=True)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = 1.0
        partition = {n: (n % 2) for n in g.nodes()}
        order = removal_order(g, "bridging(louvain)", partitions={"louvain": partition})
        self.assertEqual(sorted(order), sorted(g.nodes()))

    def test_bridging_bare_defaults_to_leiden_directed(self) -> None:
        from network.robustness import removal_order

        g = nx.gnp_random_graph(10, 0.3, seed=42, directed=True)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = 1.0
        partition = {n: (n % 3) for n in g.nodes()}
        # Bare "bridging" must look up "leiden_directed" — not "leiden".
        order = removal_order(g, "bridging", partitions={"leiden_directed": partition})
        self.assertEqual(sorted(order), sorted(g.nodes()))
        # Sanity: with only "leiden" available, bare "bridging" must error.
        with self.assertRaises(ValueError):
            removal_order(g, "bridging", partitions={"leiden": partition})

    def test_bridging_missing_partition_raises(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=1.0)
        with self.assertRaises(ValueError):
            removal_order(g, "bridging")  # no partitions kwarg
        with self.assertRaises(ValueError):
            removal_order(g, "bridging(louvain)", partitions={"leiden": {"A": 0, "B": 0}})

    def test_strategy_names_are_case_insensitive(self) -> None:
        from network.robustness import removal_order

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=1.0)
        self.assertEqual(removal_order(g, "PageRank"), removal_order(g, "pagerank"))
        self.assertEqual(removal_order(g, "BETWEENNESS"), removal_order(g, "betweenness"))


class RewireWeightsTests(TestCase):
    def _gnp(self, n: int = 30, p: float = 0.15, seed: int = 42) -> nx.DiGraph:
        g = nx.gnp_random_graph(n, p, seed=seed, directed=True)
        rng = np.random.default_rng(seed)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = float(rng.uniform(0.5, 5.0))
        return g

    def test_topology_preserved(self) -> None:
        from network.robustness import rewire_weights

        g = self._gnp()
        h = rewire_weights(g, rng=np.random.default_rng(0))
        self.assertEqual(set(g.nodes()), set(h.nodes()))
        self.assertEqual(set(g.edges()), set(h.edges()))

    def test_total_weight_preserved(self) -> None:
        from network.robustness import rewire_weights

        g = self._gnp()
        before = sum(d["weight"] for _, _, d in g.edges(data=True))
        h = rewire_weights(g, rng=np.random.default_rng(0))
        after = sum(d["weight"] for _, _, d in h.edges(data=True))
        self.assertAlmostEqual(before, after, places=10)

    def test_weight_multiset_preserved(self) -> None:
        from network.robustness import rewire_weights

        g = self._gnp()
        before = sorted(d["weight"] for _, _, d in g.edges(data=True))
        h = rewire_weights(g, rng=np.random.default_rng(0))
        after = sorted(d["weight"] for _, _, d in h.edges(data=True))
        for a, b in zip(before, after, strict=True):
            self.assertAlmostEqual(a, b, places=10)

    def test_default_n_swaps_actually_moves_weights(self) -> None:
        # With 10|E| attempts the probability of an identity permutation is ≈ 0.
        from network.robustness import rewire_weights

        g = self._gnp()
        h = rewire_weights(g, rng=np.random.default_rng(0))
        moved = sum(g.edges[e]["weight"] != h.edges[e]["weight"] for e in g.edges())
        self.assertGreater(moved, g.number_of_edges() // 2)

    def test_reproducible_with_same_seed(self) -> None:
        from network.robustness import rewire_weights

        g = self._gnp()
        h1 = rewire_weights(g, rng=np.random.default_rng(7))
        h2 = rewire_weights(g, rng=np.random.default_rng(7))
        for e in g.edges():
            self.assertEqual(h1.edges[e]["weight"], h2.edges[e]["weight"])

    def test_does_not_mutate_input(self) -> None:
        from network.robustness import rewire_weights

        g = self._gnp()
        snapshot = {e: g.edges[e]["weight"] for e in g.edges()}
        rewire_weights(g, rng=np.random.default_rng(0))
        for e, w in snapshot.items():
            self.assertEqual(g.edges[e]["weight"], w)

    def test_n_swaps_zero_returns_identical_weights(self) -> None:
        from network.robustness import rewire_weights

        g = self._gnp()
        h = rewire_weights(g, n_swaps=0, rng=np.random.default_rng(0))
        for e in g.edges():
            self.assertEqual(g.edges[e]["weight"], h.edges[e]["weight"])

    def test_small_graph_returns_copy_unchanged(self) -> None:
        from network.robustness import rewire_weights

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=3.0)  # only 1 edge → nothing to swap
        h = rewire_weights(g, rng=np.random.default_rng(0))
        self.assertEqual(h.edges["A", "B"]["weight"], 3.0)
        # And empty graph
        h2 = rewire_weights(nx.DiGraph(), rng=np.random.default_rng(0))
        self.assertEqual(h2.number_of_nodes(), 0)


class NullDistributionTests(TestCase):
    def test_yields_requested_number_of_graphs(self) -> None:
        from network.robustness import null_distribution

        g = nx.gnp_random_graph(20, 0.2, seed=42, directed=True)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = 1.0
        result = list(null_distribution(g, n_simulations=5, rng=np.random.default_rng(0)))
        self.assertEqual(len(result), 5)
        for h in result:
            self.assertEqual(set(h.edges()), set(g.edges()))  # same topology

    def test_zero_simulations_yields_nothing(self) -> None:
        from network.robustness import null_distribution

        g = nx.DiGraph()
        g.add_edge("A", "B", weight=1.0)
        self.assertEqual(list(null_distribution(g, n_simulations=0)), [])

    def test_successive_simulations_differ_under_shared_rng(self) -> None:
        # Two consecutive nulls drawn from the same rng should be different
        # (since the rng state advances between calls).
        from network.robustness import null_distribution

        g = nx.gnp_random_graph(30, 0.3, seed=42, directed=True)
        rng_seed = np.random.default_rng(42)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = float(rng_seed.uniform(0.5, 5.0))
        nulls = list(null_distribution(g, n_simulations=2, rng=np.random.default_rng(0)))
        w1 = [nulls[0].edges[e]["weight"] for e in g.edges()]
        w2 = [nulls[1].edges[e]["weight"] for e in g.edges()]
        self.assertNotEqual(w1, w2)


class ZScoreTests(TestCase):
    def test_basic_computation(self) -> None:
        from network.robustness import z_score

        # samples have mean 5, sample std (ddof=1) = sqrt(2.5) ≈ 1.5811
        z, mu, sigma = z_score(observed=10.0, null_samples=[3.0, 4.0, 5.0, 6.0, 7.0])
        self.assertAlmostEqual(mu, 5.0)
        self.assertAlmostEqual(sigma, np.std([3.0, 4.0, 5.0, 6.0, 7.0], ddof=1))
        self.assertAlmostEqual(z, (10.0 - 5.0) / sigma)

    def test_zero_std_returns_nan_z(self) -> None:
        from network.robustness import z_score

        z, mu, sigma = z_score(observed=10.0, null_samples=[5.0, 5.0, 5.0])
        self.assertEqual(mu, 5.0)
        self.assertEqual(sigma, 0.0)
        self.assertTrue(np.isnan(z))

    def test_single_sample_treated_as_zero_std(self) -> None:
        from network.robustness import z_score

        z, mu, sigma = z_score(observed=10.0, null_samples=[3.0])
        self.assertEqual(mu, 3.0)
        self.assertEqual(sigma, 0.0)
        self.assertTrue(np.isnan(z))

    def test_empty_samples_returns_nan_triple(self) -> None:
        from network.robustness import z_score

        z, mu, sigma = z_score(observed=10.0, null_samples=[])
        self.assertTrue(np.isnan(z))
        self.assertTrue(np.isnan(mu))
        self.assertTrue(np.isnan(sigma))

    def test_negative_z_when_observed_below_mean(self) -> None:
        from network.robustness import z_score

        z, _, _ = z_score(observed=1.0, null_samples=[5.0, 5.5, 6.0, 6.5, 7.0])
        self.assertLess(z, 0)


class ModularRobustnessCurvesTests(TestCase):
    def _two_cliques_with_bridge(self) -> tuple[nx.DiGraph, dict[str, int]]:
        # Two 3-node directed cliques + a single inter-community bridge A → D.
        # Each clique contributes 6 directed edges (3 pairs × 2 directions).
        g = nx.DiGraph()
        for u, v in [("A", "B"), ("B", "A"), ("A", "C"), ("C", "A"), ("B", "C"), ("C", "B")]:
            g.add_edge(u, v)
        for u, v in [("D", "E"), ("E", "D"), ("D", "F"), ("F", "D"), ("E", "F"), ("F", "E")]:
            g.add_edge(u, v)
        g.add_edge("A", "D")  # the only inter-community edge
        partition = {"A": 0, "B": 0, "C": 0, "D": 1, "E": 1, "F": 1}
        return g, partition

    def test_curve_length_matches_removal_order_plus_one(self) -> None:
        from network.robustness import modular_robustness_curves

        g, part = self._two_cliques_with_bridge()
        curves = modular_robustness_curves(g, ["A", "B", "C"], part)
        for key in ("intra", "inter", "ratio"):
            self.assertEqual(len(curves[key]), 4)

    def test_baselines_at_q_zero(self) -> None:
        # 12 intra edges (6 per clique) + 1 inter; both baselines = 1.0
        from network.robustness import modular_robustness_curves

        g, part = self._two_cliques_with_bridge()
        curves = modular_robustness_curves(g, [], part)
        self.assertEqual(curves["intra"], [1.0])
        self.assertEqual(curves["inter"], [1.0])
        # ratio = 12 / 1 = 12.0
        self.assertEqual(curves["ratio"], [12.0])

    def test_bridge_endpoint_removal_strips_inter_edge(self) -> None:
        # Removing A drops the single inter edge (A→D) and four intra edges
        # incident on A (A→B, A→C, B→A, C→A).  Expected after q=1:
        #   intra_q = 12 - 4 = 8  →  intra[1] = 8/12 ≈ 0.667
        #   inter_q = 1 - 1 = 0    →  inter[1] = 0.0; ratio[1] = None
        from network.robustness import modular_robustness_curves

        g, part = self._two_cliques_with_bridge()
        curves = modular_robustness_curves(g, ["A"], part)
        self.assertAlmostEqual(curves["intra"][1], 8 / 12)
        self.assertEqual(curves["inter"][1], 0.0)
        self.assertIsNone(curves["ratio"][1])

    def test_all_same_community_inter_curve_is_zero(self) -> None:
        from network.robustness import modular_robustness_curves

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C")])
        part = {"A": 0, "B": 0, "C": 0}
        curves = modular_robustness_curves(g, ["A", "B", "C"], part)
        # inter_0 == 0 → entire inter curve is 0.0
        self.assertEqual(curves["inter"], [0.0, 0.0, 0.0, 0.0])
        # ratio is always None when inter is 0 throughout
        self.assertEqual(curves["ratio"], [None, None, None, None])

    def test_all_different_communities_intra_curve_is_zero(self) -> None:
        from network.robustness import modular_robustness_curves

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C")])
        part = {"A": 0, "B": 1, "C": 2}
        curves = modular_robustness_curves(g, ["A"], part)
        self.assertEqual(curves["intra"], [0.0, 0.0])
        # inter_0 = 2, after removing A → 1 inter edge gone
        self.assertAlmostEqual(curves["inter"][0], 1.0)
        self.assertAlmostEqual(curves["inter"][1], 0.5)
        self.assertAlmostEqual(curves["ratio"][0], 0.0)
        self.assertAlmostEqual(curves["ratio"][1], 0.0)

    def test_self_loop_counted_once(self) -> None:
        # A→A (self-loop), A→B, B→A. All same community.  Removing A should
        # drop all 3 edges, not 4 (which would be the bug from counting the
        # self-loop both in out_edges and in_edges).
        from network.robustness import modular_robustness_curves

        g = nx.DiGraph()
        g.add_edges_from([("A", "A"), ("A", "B"), ("B", "A")])
        part = {"A": 0, "B": 0}
        curves = modular_robustness_curves(g, ["A"], part)
        # intra_0 = 3 → intra[0] = 1.0, intra[1] = 0/3 = 0.0
        self.assertEqual(curves["intra"], [1.0, 0.0])

    def test_unassigned_nodes_treated_as_inter(self) -> None:
        # B has no entry in partition → A→B counts as inter even though B's
        # community is conceptually "unknown".
        from network.robustness import modular_robustness_curves

        g = nx.DiGraph()
        g.add_edge("A", "B")
        part = {"A": 0}  # B missing
        curves = modular_robustness_curves(g, [], part)
        self.assertEqual(curves["intra"], [0.0])  # intra_0 == 0
        self.assertEqual(curves["inter"], [1.0])  # the one edge is inter

    def test_missing_nodes_in_removal_order_are_skipped(self) -> None:
        from network.robustness import modular_robustness_curves

        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("B", "C")])
        part = {"A": 0, "B": 0, "C": 0}
        # "X" is not in the graph
        curves = modular_robustness_curves(g, ["A", "X", "B"], part)
        # After A: lose A→B → intra = 1, fraction = 1/2 = 0.5
        # After X (skipped): unchanged → 0.5
        # After B: lose B→C → intra = 0, fraction = 0.0
        self.assertEqual(curves["intra"], [1.0, 0.5, 0.5, 0.0])

    def test_does_not_mutate_input_graph(self) -> None:
        from network.robustness import modular_robustness_curves

        g, part = self._two_cliques_with_bridge()
        before_nodes, before_edges = set(g.nodes()), set(g.edges())
        modular_robustness_curves(g, ["A", "B", "D"], part)
        self.assertEqual((set(g.nodes()), set(g.edges())), (before_nodes, before_edges))

    def test_empty_graph_returns_single_zero_baselines(self) -> None:
        from network.robustness import modular_robustness_curves

        curves = modular_robustness_curves(nx.DiGraph(), [], {})
        self.assertEqual(curves["intra"], [0.0])
        self.assertEqual(curves["inter"], [0.0])
        self.assertEqual(curves["ratio"], [None])


class RobustnessRunnerTests(TestCase):
    def _toy_graph(self, n: int = 20, p: float = 0.2, seed: int = 42) -> nx.DiGraph:
        g = nx.gnp_random_graph(n, p, seed=seed, directed=True)
        rng = np.random.default_rng(seed)
        for u, v in g.edges():
            g.edges[u, v]["weight"] = float(rng.uniform(0.5, 5.0))
        return g

    def _fast_cfg(self, **kwargs: Any) -> Any:
        from network.robustness import RobustnessConfig

        defaults: dict[str, Any] = {
            "alpha": None,
            "n_random_runs": 3,
            "n_null": 0,
            "seed": 0,
            "reach_sample": 10,
        }
        defaults.update(kwargs)
        return RobustnessConfig(**defaults)

    # -- config validation ----------------------------------------------------

    def test_config_defaults_match_spec(self) -> None:
        from network.robustness import RobustnessConfig

        c = RobustnessConfig()
        self.assertEqual(
            (c.alpha, c.n_random_runs, c.n_null, c.seed, c.reach_sample, c.strategies),
            (0.05, 100, 20, 42, 500, None),
        )

    def test_config_rejects_invalid_values(self) -> None:
        from network.robustness import RobustnessConfig

        with self.assertRaises(ValueError):
            RobustnessConfig(n_random_runs=0)
        with self.assertRaises(ValueError):
            RobustnessConfig(n_null=-1)
        with self.assertRaises(ValueError):
            RobustnessConfig(alpha=1.5)
        with self.assertRaises(ValueError):
            RobustnessConfig(reach_sample=0)

    def test_config_rejects_empty_strategies_list(self) -> None:
        from network.robustness import RobustnessConfig

        with self.assertRaises(ValueError):
            RobustnessConfig(strategies=[])

    def test_config_rejects_unknown_strategy(self) -> None:
        from network.robustness import RobustnessConfig

        with self.assertRaises(ValueError):
            RobustnessConfig(strategies=["no-such-strategy"])

    def test_config_accepts_bridging_with_partition(self) -> None:
        from network.robustness import RobustnessConfig

        # parse_strategy treats bridging(LEIDEN) as a valid token
        RobustnessConfig(strategies=["pagerank", "bridging(leiden)"])

    # -- payload shape --------------------------------------------------------

    def test_payload_top_level_keys(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(), config=self._fast_cfg())
        self.assertEqual(set(out.keys()), {"config", "graph", "efficiency", "strategies", "modular"})

    def test_payload_strategy_keys_defaults_to_default_set(self) -> None:
        from network.robustness import DEFAULT_STRATEGIES, run_robustness

        out = run_robustness(self._toy_graph(), config=self._fast_cfg())
        self.assertEqual(set(out["strategies"].keys()), set(DEFAULT_STRATEGIES))

    def test_payload_strategy_keys_match_explicit_selection(self) -> None:
        from network.robustness import run_robustness

        chosen = ["pagerank", "betweenness_dyn", "hits_authority", "spreading"]
        out = run_robustness(self._toy_graph(n=10), config=self._fast_cfg(strategies=chosen))
        self.assertEqual(set(out["strategies"].keys()), set(chosen))

    def test_payload_strategy_label_present_per_strategy(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(), config=self._fast_cfg(strategies=["pagerank"]))
        self.assertEqual(out["strategies"]["pagerank"]["label"], "PageRank")

    def test_each_strategy_has_three_curves_and_r_fc(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(), config=self._fast_cfg())
        for s, payload in out["strategies"].items():
            for m in ("wcc", "scc", "reach"):
                self.assertIn(f"curve_{m}", payload, msg=f"strategy {s!r} missing curve_{m}")
                self.assertIn(f"r_{m}", payload)
                self.assertIn(f"fc_{m}", payload)
            self.assertIsNone(payload["null"])  # n_null=0

    def test_curve_length_matches_backbone_node_count_plus_one(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(n=12), config=self._fast_cfg())
        n_plus_1 = out["graph"]["backbone_n"] + 1
        for payload in out["strategies"].values():
            for m in ("wcc", "scc", "reach"):
                self.assertEqual(len(payload[f"curve_{m}"]), n_plus_1)

    # -- disparity filter ------------------------------------------------------

    def test_alpha_none_skips_filter(self) -> None:
        from network.robustness import run_robustness

        g = self._toy_graph()
        out = run_robustness(g, config=self._fast_cfg(alpha=None))
        self.assertFalse(out["graph"]["filtered"])
        self.assertEqual(out["graph"]["backbone_m"], g.number_of_edges())

    def test_alpha_zero_skips_filter(self) -> None:
        from network.robustness import run_robustness

        g = self._toy_graph()
        out = run_robustness(g, config=self._fast_cfg(alpha=0))
        self.assertFalse(out["graph"]["filtered"])
        self.assertEqual(out["graph"]["backbone_m"], g.number_of_edges())

    def test_alpha_within_range_applies_filter(self) -> None:
        from network.robustness import run_robustness

        g = self._toy_graph()
        out = run_robustness(g, config=self._fast_cfg(alpha=0.5))
        self.assertTrue(out["graph"]["filtered"])
        self.assertLessEqual(out["graph"]["backbone_m"], g.number_of_edges())

    # -- null model -----------------------------------------------------------

    def test_null_populated_when_n_null_positive(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(n=12), config=self._fast_cfg(n_null=3))
        for payload in out["strategies"].values():
            self.assertIsNotNone(payload["null"])
            for m in ("wcc", "scc", "reach"):
                self.assertIn(f"r_{m}", payload["null"])
                self.assertEqual(set(payload["null"][f"r_{m}"].keys()), {"mean", "std", "z"})
                self.assertIn(f"curve_{m}_mean", payload["null"])
                self.assertIn(f"curve_{m}_std", payload["null"])

    def test_null_curves_have_matching_length(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(n=10), config=self._fast_cfg(n_null=2))
        n_plus_1 = out["graph"]["backbone_n"] + 1
        for payload in out["strategies"].values():
            for m in ("wcc", "scc", "reach"):
                self.assertEqual(len(payload["null"][f"curve_{m}_mean"]), n_plus_1)
                self.assertEqual(len(payload["null"][f"curve_{m}_std"]), n_plus_1)

    # -- modular --------------------------------------------------------------

    def test_modular_none_when_no_partitions(self) -> None:
        from network.robustness import run_robustness

        out = run_robustness(self._toy_graph(), config=self._fast_cfg())
        self.assertIsNone(out["modular"])

    def test_modular_populated_when_partitions_given(self) -> None:
        from network.robustness import DEFAULT_STRATEGIES, run_robustness

        g = self._toy_graph(n=10)
        # Hand-built two-block partition
        partition = {n: (0 if n < 5 else 1) for n in g.nodes()}
        out = run_robustness(g, partitions={"hand": partition}, config=self._fast_cfg())
        self.assertIsNotNone(out["modular"])
        self.assertEqual(set(out["modular"].keys()), {"hand"})
        self.assertEqual(set(out["modular"]["hand"].keys()), set(DEFAULT_STRATEGIES))
        # Each per-strategy entry is the modular_robustness_curves dict.
        for payload in out["modular"]["hand"].values():
            self.assertEqual(set(payload.keys()), {"intra", "inter", "ratio"})

    def test_bridging_needs_named_partition(self) -> None:
        from network.robustness import run_robustness

        g = self._toy_graph(n=10)
        # bridging(louvain) requires "louvain" in partitions; we only supply "leiden".
        partition = {n: (n % 2) for n in g.nodes()}
        with self.assertRaises(ValueError):
            run_robustness(g, partitions={"leiden": partition}, config=self._fast_cfg(strategies=["bridging(louvain)"]))

    def test_bridging_runs_with_matching_partition(self) -> None:
        from network.robustness import run_robustness

        g = self._toy_graph(n=10)
        partition = {n: (n % 2) for n in g.nodes()}
        # Bare "bridging" defaults to leiden_directed.
        out = run_robustness(
            g, partitions={"leiden_directed": partition}, config=self._fast_cfg(strategies=["bridging"])
        )
        self.assertIn("bridging(leiden_directed)", out["strategies"])
        self.assertEqual(
            out["strategies"]["bridging(leiden_directed)"]["label"],
            "Bridging centrality (leiden_directed)",
        )

    # -- reproducibility ------------------------------------------------------

    def test_same_seed_produces_identical_payloads(self) -> None:
        from network.robustness import run_robustness

        g = self._toy_graph()
        out1 = run_robustness(g, config=self._fast_cfg(n_null=2, seed=99))
        out2 = run_robustness(g, config=self._fast_cfg(n_null=2, seed=99))
        # Compare every strategy's R values; both whole payloads must match.
        for s in out1["strategies"]:
            for m in ("wcc", "scc", "reach"):
                self.assertEqual(out1["strategies"][s][f"r_{m}"], out2["strategies"][s][f"r_{m}"])
                self.assertEqual(
                    out1["strategies"][s]["null"][f"r_{m}"]["z"],
                    out2["strategies"][s]["null"][f"r_{m}"]["z"],
                )

    # -- progress callback ----------------------------------------------------

    def test_progress_callback_receives_expected_labels(self) -> None:
        from network.robustness import run_robustness

        labels: list[str] = []
        g = self._toy_graph(n=8)
        partition = {n: (n % 2) for n in g.nodes()}
        run_robustness(g, partitions={"hand": partition}, config=self._fast_cfg(n_null=1), progress=labels.append)
        self.assertIn("disparity", labels)
        self.assertIn("baseline-efficiency", labels)
        self.assertIn("pagerank", labels)
        self.assertTrue(any(s.startswith("null/") for s in labels))
        self.assertTrue(any(s.startswith("modular/") for s in labels))

    # -- JSON serialisability -------------------------------------------------

    def test_payload_is_json_serialisable(self) -> None:
        import json

        from network.robustness import run_robustness

        g = self._toy_graph(n=8)
        out = run_robustness(
            g,
            partitions={"hand": {n: n % 2 for n in g.nodes()}},
            config=self._fast_cfg(n_null=1),
        )
        # Round-trip must not fail (no inf/nan in the curves; None used for undefined ratios).
        encoded = json.dumps(out)
        self.assertIsInstance(encoded, str)
        decoded = json.loads(encoded)
        self.assertEqual(set(decoded.keys()), {"config", "graph", "efficiency", "strategies", "modular"})


class WriteRobustnessJsonTests(TestCase):
    def test_round_trip_under_tempdir(self) -> None:
        from network.exporter import write_robustness_json

        payload = {"strategies": {"pagerank": {"r_wcc": 0.42}}, "config": {"seed": 1}}
        with tempfile.TemporaryDirectory() as tmp:
            write_robustness_json(payload, tmp)
            path = os.path.join(tmp, "data", "robustness.json")
            self.assertTrue(os.path.isfile(path))
            with open(path) as f:
                decoded = json.load(f)
            self.assertEqual(decoded, payload)


class WriteRobustnessTableXlsxTests(TestCase):
    def _payload(self) -> dict[str, Any]:
        return {
            "config": {"seed": 0},
            "graph": {"n": 3, "m": 3, "alpha": 0.05, "backbone_n": 3, "backbone_m": 3, "filtered": True},
            "efficiency": {"baseline": 1.0},
            "strategies": {
                "pagerank": {
                    "curve_wcc": [1.0, 0.5, 0.0, 0.0],
                    "curve_scc": [1.0, 0.5, 0.0, 0.0],
                    "curve_reach": [0.5, 0.25, 0.0, 0.0],
                    "r_wcc": 0.125,
                    "r_scc": 0.125,
                    "r_reach": 0.0625,
                    "fc_wcc": 0.5,
                    "fc_scc": 0.5,
                    "fc_reach": 0.5,
                    "null": {
                        "r_wcc": {"mean": 0.12, "std": 0.01, "z": 0.5},
                        "r_scc": {"mean": 0.12, "std": 0.01, "z": 0.5},
                        "r_reach": {"mean": 0.06, "std": 0.005, "z": 1.25},
                        "curve_wcc_mean": [1.0, 0.45, 0.0, 0.0],
                        "curve_wcc_std": [0.0, 0.05, 0.0, 0.0],
                        "curve_scc_mean": [1.0, 0.45, 0.0, 0.0],
                        "curve_scc_std": [0.0, 0.05, 0.0, 0.0],
                        "curve_reach_mean": [0.5, 0.2, 0.0, 0.0],
                        "curve_reach_std": [0.0, 0.05, 0.0, 0.0],
                    },
                },
            },
            "modular": {
                "leiden": {
                    "pagerank": {
                        "intra": [1.0, 0.5, 0.0, 0.0],
                        "inter": [1.0, 0.0, 0.0, 0.0],
                        "ratio": [1.0, None, None, None],
                    }
                }
            },
        }

    def test_workbook_has_summary_curve_and_modular_sheets(self) -> None:
        from network.tables import write_robustness_table_xlsx

        import openpyxl

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "robustness_table.xlsx")
            write_robustness_table_xlsx(self._payload(), output_filename=out, project_title="Test")
            self.assertTrue(os.path.isfile(out))
            wb = openpyxl.load_workbook(out)
            self.assertIn("Summary", wb.sheetnames)
            self.assertTrue(any(name.startswith("Curve") for name in wb.sheetnames))
            self.assertTrue(any(name.startswith("Modular") for name in wb.sheetnames))

    def test_summary_sheet_has_one_row_per_strategy_metric_combo(self) -> None:
        from network.tables import write_robustness_table_xlsx

        import openpyxl

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "robustness_table.xlsx")
            write_robustness_table_xlsx(self._payload(), output_filename=out)
            wb = openpyxl.load_workbook(out)
            ws = wb["Summary"]
            self.assertEqual(ws.max_row, 4)  # header + 3 metrics × 1 strategy
            r_values = [ws.cell(row=r, column=3).value for r in range(2, ws.max_row + 1)]
            self.assertIn(0.125, r_values)
            self.assertIn(0.0625, r_values)

    def test_handles_payload_without_null(self) -> None:
        from network.tables import write_robustness_table_xlsx

        import openpyxl

        payload = self._payload()
        payload["strategies"]["pagerank"]["null"] = None
        payload.pop("modular")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "robustness_table.xlsx")
            write_robustness_table_xlsx(payload, output_filename=out)
            wb = openpyxl.load_workbook(out)
            self.assertIn("Summary", wb.sheetnames)

    def test_year_data_produces_year_suffixed_sheets(self) -> None:
        # With year_data the workbook becomes one contiguous block of sheets per
        # scope: All first, then each year.  Sheet names get a space-separated
        # suffix; the legacy "Summary" sheet (no suffix) must not appear.
        from network.tables import write_robustness_table_xlsx

        import openpyxl

        global_payload = self._payload()
        year_payload = self._payload()
        year_data = [(2019, year_payload), (2020, year_payload)]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "robustness_table.xlsx")
            write_robustness_table_xlsx(global_payload, output_filename=out, year_data=year_data)
            wb = openpyxl.load_workbook(out)
            for expected in (
                "Summary All",
                "Summary 2019",
                "Summary 2020",
                "Curve pagerank All",
                "Curve pagerank 2019",
                "Curve pagerank 2020",
                "Modular leiden All",
                "Modular leiden 2019",
                "Modular leiden 2020",
            ):
                self.assertIn(expected, wb.sheetnames, msg=f"missing sheet {expected!r}")
            # Legacy un-suffixed sheets must not coexist with the year-grouped layout.
            self.assertNotIn("Summary", wb.sheetnames)
            self.assertNotIn("Curve pagerank", wb.sheetnames)

    def test_sheet_name_helper_respects_31_char_cap(self) -> None:
        # Long partition name + year suffix must stay within Excel's 31-char limit.
        from network.tables import _robustness_sheet_name

        self.assertEqual(_robustness_sheet_name("Summary", ""), "Summary")
        self.assertEqual(_robustness_sheet_name("Summary", "All"), "Summary All")
        long_partition = "Modular leiden_directed_super_long"
        out = _robustness_sheet_name(long_partition, "2020")
        self.assertLessEqual(len(out), 31)
        self.assertTrue(out.endswith(" 2020"))


# ---------------------------------------------------------------------------
# network.layout.resolve_iterations
# ---------------------------------------------------------------------------


class ResolveIterationsTests(TestCase):
    """fa2_iterations accepts an integer or an Nx multiplier; floored at 100."""

    def test_integer_returned_as_is(self) -> None:
        from network.layout import resolve_iterations

        self.assertEqual(resolve_iterations(5000, num_nodes=100), 5000)
        self.assertEqual(resolve_iterations("5000", num_nodes=100), 5000)

    def test_multiplier_scaled_by_node_count(self) -> None:
        from network.layout import resolve_iterations

        self.assertEqual(resolve_iterations("7x", num_nodes=1000), 7000)
        self.assertEqual(resolve_iterations("2.5x", num_nodes=400), 1000)

    def test_floored_at_100(self) -> None:
        from network.layout import resolve_iterations

        self.assertEqual(resolve_iterations(50, num_nodes=1000), 100)
        self.assertEqual(resolve_iterations("0.01x", num_nodes=10), 100)
        self.assertEqual(resolve_iterations("7x", num_nodes=0), 100)

    def test_default_used_when_blank_or_none(self) -> None:
        from network.layout import FA2_ITERATIONS_DEFAULT, resolve_iterations

        # FA2_ITERATIONS_DEFAULT is "7x", so 7 × 50 = 350.
        self.assertEqual(FA2_ITERATIONS_DEFAULT, "7x")
        self.assertEqual(resolve_iterations(None, num_nodes=50), 350)
        self.assertEqual(resolve_iterations("", num_nodes=50), 350)

    def test_case_insensitive_x(self) -> None:
        from network.layout import resolve_iterations

        self.assertEqual(resolve_iterations("3X", num_nodes=200), 600)
