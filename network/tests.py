import datetime
import json
import os
import tempfile
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


# ---------------------------------------------------------------------------
# community.py — detect_organization
# ---------------------------------------------------------------------------


class DetectOrganizationTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Test Org", is_interesting=True, color="#FF0000")
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
        org2 = Organization.objects.create(name="Org2", is_interesting=True, color="#0000FF")
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
        Organization.objects.create(name="My Org", is_interesting=True)
        result = build_communities_payload(["ORGANIZATION"], {"ORGANIZATION": ({}, {})})
        org_names = [g[2] for g in result["organization"]["groups"]]
        self.assertIn("My Org", org_names)

    def test_non_interesting_orgs_excluded_from_organization_strategy(self) -> None:
        Organization.objects.create(name="Hidden Org", is_interesting=False)
        result = build_communities_payload(["ORGANIZATION"], {"ORGANIZATION": ({}, {})})
        org_names = [g[2] for g in result["organization"]["groups"]]
        self.assertNotIn("Hidden Org", org_names)

    def test_organization_strategy_main_groups_uses_key_and_name(self) -> None:
        org = Organization.objects.create(name="My Org", is_interesting=True)
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
        self.org = Organization.objects.create(name="Org1", is_interesting=True, color="#FF0000")
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
        # ch2 (interesting) forwards from ch3 → ch3 gets in_degree > 0
        Message.objects.create(telegram_id=10, channel=self.ch2, forwarded_from=ch3)
        ch3.refresh_degrees()
        ch3.refresh_from_db()
        self.assertGreater(ch3.in_degree or 0, 0)
        # Create a ch1↔ch2 edge so graph is valid
        self._create_forward()
        _, channel_dict_dl, _, _ = build_graph(draw_dead_leaves=True)
        self.assertIn(str(ch3.pk), channel_dict_dl)

    def test_draw_dead_leaves_false_excludes_non_interesting(self) -> None:
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
        org = Organization.objects.create(name="Org1", is_interesting=True, color="#FF0000")
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
        org = Organization.objects.create(name="Org1", is_interesting=True, color="#FF0000")
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
        self.org = Organization.objects.create(name="Org", is_interesting=True)
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
        mock_detect.assert_called_once_with(self.graph, "palette")

    @patch("network.community.detect_kcore")
    def test_kcore_strategy_calls_detect_kcore(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("KCORE", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette")

    @patch("network.community.detect_infomap")
    def test_infomap_strategy_calls_detect_infomap(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("INFOMAP", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette")

    @patch("network.community.detect_leiden")
    def test_leiden_strategy_calls_detect_leiden(self, mock_detect: MagicMock) -> None:
        from network.community import detect

        mock_detect.return_value = ({}, {})
        detect("LEIDEN", "palette", self.graph, self.channel_dict)
        mock_detect.assert_called_once_with(self.graph, "palette")

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
        self.org = Organization.objects.create(name="Org", is_interesting=True)

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
            call_command("structural_analysis")

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
        call_command("structural_analysis", graph=True, html=True)

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
        call_command("structural_analysis", html=False)
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
        call_command("structural_analysis", html=False, xlsx=True)
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
        call_command("structural_analysis", html=True, xlsx=True)
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
        org = Organization.objects.create(name="Org", is_interesting=True, color="#FF0000")
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
        org = Organization.objects.create(name="Org2", is_interesting=True, color="#00FF00")
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
        org = Organization.objects.create(name="OrgEmpty", is_interesting=True, color="#0000FF")
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
