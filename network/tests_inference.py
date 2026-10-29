"""Tests of the inference layer: label mixing, whole-network significance, MRQAP and the dyadic export."""

import csv
import datetime
import io
import json
import tempfile
from collections import Counter
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from network import community_stats, dyads, label_mixing, mrqap, network_nulls
from network.graph_builder import build_graph
from network.utils import citation_count, dead_leaf_ids
from webapp.models import Message
from webapp.test_helpers import attribute, label_group, make_channel, make_label

import networkx as nx
import numpy as np


def _labelled_graph(edges: list[tuple[str, str]], labels: dict[str, int], group_id: int = 1) -> nx.DiGraph:
    """A hand-built citation graph whose nodes carry ``group_partitions`` like ``build_graph``'s."""
    graph = nx.DiGraph()
    for node, label in labels.items():
        graph.add_node(node, data={"group_partitions": {group_id: (label, "#000000")}})
    for u, v in edges:
        graph.add_edge(u, v, weight=1.0, weight_raw=1.0, weight_forwards=2.0, weight_mentions=0.0, weight_copies=0.0)
    return graph


def _mixing(graph: nx.DiGraph, labels: dict[str, int], permutations: int = 500, seed: int = 7) -> dict:
    return label_mixing._group_mixing(
        graph, 1, "Group", labels, {1: "A", 2: "B", 3: "C"}, permutations=permutations, seed=seed
    )


class LabelMixingTests(TestCase):
    def setUp(self) -> None:
        self.labels = {"a1": 1, "a2": 1, "a3": 1, "b1": 2, "b2": 2, "b3": 2}

    def test_perfect_homophily(self) -> None:
        edges = [("a1", "a2"), ("a2", "a3"), ("a3", "a1"), ("b1", "b2"), ("b2", "b3"), ("b3", "b1")]
        result = _mixing(_labelled_graph(edges, self.labels), self.labels)
        self.assertAlmostEqual(result["assortativity"]["ties"]["value"], 1.0)
        self.assertAlmostEqual(result["ei_index"]["value"], -1.0)
        for row in result["rows"]:
            self.assertAlmostEqual(row["baseline_share"], 0.4)  # (3 − 1) / (6 − 1)
            self.assertAlmostEqual(row["ih_out"], 1.0)
            self.assertAlmostEqual(row["ih_in"], 1.0)

    def test_planted_homophily_is_significant(self) -> None:
        # Six channels allow only ten distinct relabellings; twenty per label give the test power.
        labels = {f"{side}{i}": label for side, label in (("a", 1), ("b", 2)) for i in range(20)}
        edges = [(f"{s}{i}", f"{s}{(i + k) % 20}") for s in "ab" for i in range(20) for k in (1, 2)]
        edges += [("a0", "b0"), ("b5", "a5")]
        result = _mixing(_labelled_graph(edges, labels), labels, permutations=400)
        self.assertGreater(result["assortativity"]["ties"]["value"], 0.9)
        self.assertLess(result["assortativity"]["ties"]["p"], 0.05)
        self.assertTrue(all(row["ih_out_q"] < 0.05 for row in result["rows"]))

    def test_heterophily_is_negative(self) -> None:
        edges = [("a1", "b1"), ("a2", "b2"), ("a3", "b3"), ("b1", "a2"), ("b2", "a3"), ("b3", "a1")]
        result = _mixing(_labelled_graph(edges, self.labels), self.labels)
        self.assertLess(result["assortativity"]["ties"]["value"], 0)
        self.assertAlmostEqual(result["ei_index"]["value"], 1.0)
        for row in result["rows"]:
            self.assertAlmostEqual(row["ih_out"], (0 - 0.4) / (1 - 0.4), places=4)

    def test_assortativity_matches_networkx(self) -> None:
        rng = np.random.default_rng(3)
        nodes = [f"n{i}" for i in range(30)]
        labels = {n: int(rng.integers(1, 4)) for n in nodes}
        edges = sorted({(u, v) for u, v in rng.choice(nodes, size=(120, 2)).tolist() if u != v})
        graph = _labelled_graph(edges, labels)
        result = _mixing(graph, labels, permutations=200)
        check = nx.DiGraph(graph)
        for node, label in labels.items():
            check.nodes[node]["lab"] = label
        self.assertAlmostEqual(
            result["assortativity"]["ties"]["value"], nx.attribute_assortativity_coefficient(check, "lab"), places=5
        )
        # Random labels: no homophily to find.
        self.assertGreater(result["assortativity"]["ties"]["p"], 0.05)

    def test_inbreeding_homophily_hand_computed(self) -> None:
        labels = {"a1": 1, "a2": 1, "b1": 2, "b2": 2, "b3": 2}
        # a1 cites a2 and b1 → H_out(A) = 1/2 over A's two sent ties … plus a2 → b2: H_out(A) = 1/3.
        edges = [("a1", "a2"), ("a1", "b1"), ("a2", "b2"), ("b1", "b2"), ("b2", "b3"), ("b3", "a1")]
        result = _mixing(_labelled_graph(edges, labels), labels, permutations=100)
        row_a = next(r for r in result["rows"] if r["label"] == "A")
        w = (2 - 1) / (5 - 1)
        self.assertAlmostEqual(row_a["h_out"], round(1 / 3, 4))
        self.assertAlmostEqual(row_a["ih_out"], round((1 / 3 - w) / (1 - w), 4))
        self.assertAlmostEqual(row_a["h_in"], round(1 / 2, 4))  # A receives a1→a2 and b3→a1

    def test_flows_sum_to_the_ties_and_citations(self) -> None:
        edges = [("a1", "a2"), ("a1", "b1"), ("b1", "b2"), ("b2", "a3"), ("a3", "a1")]
        result = _mixing(_labelled_graph(edges, self.labels), self.labels, permutations=100)
        flows = result["flows"]
        self.assertEqual(sum(map(sum, flows["ties"])), len(edges))
        self.assertEqual(sum(map(sum, flows["citations"])), 2 * len(edges))
        expected = sum(v for row in flows["expected_ties"] for v in row)
        self.assertAlmostEqual(expected, len(edges), places=6)  # permutations move ties, never add any

    def test_seeded_results_are_reproducible(self) -> None:
        edges = [("a1", "a2"), ("a2", "b1"), ("b1", "b2"), ("b3", "a1"), ("a3", "b3")]
        graph = _labelled_graph(edges, self.labels)
        self.assertEqual(_mixing(graph, self.labels, seed=11), _mixing(graph, self.labels, seed=11))

    def test_single_channel_label_has_no_inbreeding_homophily(self) -> None:
        labels = {**self.labels, "c1": 3}
        edges = [("a1", "a2"), ("c1", "a1"), ("b1", "c1"), ("b2", "b3")]
        result = _mixing(_labelled_graph(edges, labels), labels, permutations=100)
        row_c = next(r for r in result["rows"] if r["label"] == "C")
        self.assertEqual(row_c["channels"], 1)
        self.assertIsNone(row_c["ih_out"])
        self.assertIsNone(row_c["ih_in_q"])

    def test_row_layouts_match_their_columns(self) -> None:
        edges = [("a1", "a2"), ("a1", "b1"), ("b1", "b2")]
        payload = {"permutations": 50, "groups": [_mixing(_labelled_graph(edges, self.labels), self.labels, 50)]}
        for rows, columns in (
            (label_mixing.group_rows(payload, "All"), label_mixing.GROUP_COLUMNS),
            (label_mixing.label_rows(payload, "All"), label_mixing.LABEL_COLUMNS),
            (label_mixing.flow_rows(payload, "All"), label_mixing.FLOW_COLUMNS),
        ):
            self.assertTrue(rows)
            self.assertTrue(all(len(row) == len(columns) for row in rows))


class ComputeLabelMixingTests(TestCase):
    def test_dead_leaves_stay_out_and_count_as_out_of_scope(self) -> None:
        group = label_group("Nation", is_primary=False)
        italy, france = make_label("Italy", group=group), make_label("France", group=group)
        labels = {"1": italy.pk, "2": italy.pk, "3": france.pk, "4": france.pk}
        graph = _labelled_graph([("1", "2"), ("3", "4"), ("1", "3"), ("1", "dead")], labels, group.pk)
        graph.nodes["dead"]["data"] = {"group_partitions": {group.pk: (italy.pk, "#000")}}
        graph.graph["dead_leaves"] = frozenset({"dead"})
        result = label_mixing.compute_label_mixing(graph, permutations=50)
        self.assertEqual([g["group"] for g in result["groups"]], ["Nation"])
        nation = result["groups"][0]
        self.assertEqual(nation["channels"], 4)  # the dead leaf is not a labelled channel
        self.assertEqual(nation["ties"], 3)
        row_italy = next(r for r in nation["rows"] if r["label"] == "Italy")
        self.assertAlmostEqual(row_italy["out_of_scope_ties_share"], round(1 / 3, 4))

    def test_no_partition_labels_returns_no_group(self) -> None:
        graph = nx.DiGraph([("1", "2")])
        self.assertEqual(label_mixing.compute_label_mixing(graph)["groups"], [])


class NetworkNullsTests(TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(5)
        nodes = [str(i) for i in range(25)]
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(nodes)
        for u, v in rng.choice(nodes, size=(90, 2)).tolist():
            if u != v:
                self.graph.add_edge(u, v, weight=float(rng.integers(1, 5)))
        self.graph.add_edge("0", "dead", weight=1.0)
        self.graph.add_edge("1", "dead", weight=1.0)
        self.dead = frozenset({"dead"})

    def test_random_digraph_respects_the_boundary(self) -> None:
        rng = np.random.default_rng(1)
        observed_ties = sum(1 for u, v in self.graph.edges() if u != v)
        for _ in range(5):
            random_graph = network_nulls.random_boundary_digraph(self.graph, self.dead, rng)
            self.assertEqual(random_graph.number_of_edges(), observed_ties)
            self.assertEqual(random_graph.out_degree("dead"), 0)
            self.assertFalse(list(nx.selfloop_edges(random_graph)))

    def test_significance_marks_what_each_baseline_holds_fixed(self) -> None:
        result = network_nulls.network_significance(
            self.graph,
            self.dead,
            statistics=community_stats.tie_statistics,
            centralization=community_stats._freeman_centralization,
            selected_groups=frozenset({"PATHS", "COHESION", "CENTRALIZATION"}),
            centrality_keys=["pagerank", "in_degree_centrality"],
            samples=15,
        )
        self.assertEqual(result["reciprocity"]["reciprocal"], {"fixed": True})
        self.assertEqual(result["in_degree_cv"]["configuration"], {"fixed": True})
        self.assertEqual(result["centralization.in_degree_centrality"]["configuration"], {"fixed": True})
        self.assertIn("z", result["centralization.in_degree_centrality"]["random"])
        self.assertIn("p", result["transitivity"]["configuration"])
        self.assertNotIn("assortativity.in_in", result)  # DEGCORRELATION not selected

    def test_tie_statistics_match_the_network_summary(self) -> None:
        self.graph.graph["dead_leaves"] = self.dead
        summary = community_stats._network_summary(self.graph)
        ties = community_stats.tie_statistics(self.graph, self.dead)
        self.assertEqual(summary["reciprocity"], ties["reciprocity"])
        self.assertEqual(summary["transitivity"], round(ties["transitivity"], 6))
        self.assertEqual(summary["assortativity"], ties["assortativity"])

    def test_summary_rows_carry_the_significance(self) -> None:
        summary = community_stats._network_summary(self.graph)
        summary["centralizations"] = {}
        summary["significance"] = {"reciprocity": {"configuration": {"mean": 0.1, "z": 2.0, "p": 0.04}}}
        rows = {label: sig for label, _value, _group, sig in community_stats.network_summary_rows(summary)}
        self.assertEqual(rows["Reciprocity (0–1)"]["configuration"]["z"], 2.0)
        self.assertIsNone(rows["Nodes"])


class MrqapTests(TestCase):
    def _planted(self, seed: int = 2) -> tuple[nx.DiGraph, dict]:
        group = label_group("Region", is_primary=False)
        regions = [make_label(f"R{i}", group=group) for i in range(3)]
        rng = np.random.default_rng(seed)
        nodes = [str(i) for i in range(36)]
        region_of = {n: regions[i % 3].pk for i, n in enumerate(nodes)}
        graph = nx.DiGraph()
        for n in nodes:
            graph.add_node(n, data={"group_partitions": {group.pk: (region_of[n], "#000")}})
        for u in nodes:
            for v in nodes:
                if u != v and rng.random() < (0.35 if region_of[u] == region_of[v] else 0.05):
                    graph.add_edge(u, v, weight=1.0, weight_forwards=float(rng.integers(1, 4)))
        graph_data = {
            "nodes": [
                {"id": n, "messages_count": int(rng.integers(5, 200)), "fans": int(rng.integers(10, 5000))}
                for n in nodes
            ],
            "edges": [],
        }
        return graph, graph_data

    def test_recovers_a_planted_homophily_effect(self) -> None:
        graph, graph_data = self._planted()
        result = mrqap.compute_mrqap(graph, graph_data, permutations=200, seed=1)
        self.assertIsNone(result["skipped"])
        tie = next(m for m in result["models"] if m["dependent"] == "tie")
        same = next(c for c in tie["coefficients"] if c["key"].startswith("same_labelgroup"))
        self.assertGreater(same["coef"], 0.15)
        self.assertLess(same["p"], 0.05)
        audience = next(c for c in tie["coefficients"] if c["key"] == "sender_audience")
        self.assertGreater(audience["p"], 0.05)  # random covariate: no effect

    def test_coefficients_equal_least_squares(self) -> None:
        graph, graph_data = self._planted()
        design = mrqap.build_design(graph, graph_data)
        result = mrqap.compute_mrqap(graph, graph_data, permutations=0, design=design)
        full = np.column_stack([np.ones(design.predictors.shape[0]), design.predictors])
        beta, *_ = np.linalg.lstsq(full, design.dependents["log_citations"], rcond=None)
        model = next(m for m in result["models"] if m["dependent"] == "log_citations")
        self.assertAlmostEqual(model["intercept"], round(beta[0], 6))
        for k, coefficient in enumerate(model["coefficients"]):
            self.assertAlmostEqual(coefficient["coef"], round(beta[k + 1], 6))
            self.assertIsNone(coefficient["p"])

    def test_skips_tiny_graphs(self) -> None:
        graph = nx.DiGraph([("1", "2")])
        result = mrqap.compute_mrqap(graph, {"nodes": [], "edges": []}, permutations=10)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["models"], [])


class DyadicExportTests(TestCase):
    def setUp(self) -> None:
        self.nation = label_group("Nation", is_primary=False)
        org = make_label("Org")
        italy, france = make_label("Italy", group=self.nation), make_label("France", group=self.nation)
        self.channels = []
        for i, nation in enumerate((italy, italy, france, france), start=1):
            channel = make_channel(telegram_id=i, label=org, title=f"C{i}", username=f"c{i}")
            attribute(channel, nation)
            self.channels.append(channel)
        c1, c2, c3, c4 = self.channels
        base = datetime.datetime(2024, 3, 1, 12, tzinfo=datetime.UTC)
        for k, (channel, source) in enumerate(((c2, c1), (c2, c1), (c3, c1), (c4, c3), (c1, c4))):
            Message.objects.create(
                telegram_id=100 + k, channel=channel, forwarded_from=source, date=base + datetime.timedelta(hours=k)
            )
        mention = Message.objects.create(telegram_id=200, channel=c3, date=base + datetime.timedelta(days=1))
        mention.references.add(c2)
        for channel in self.channels:
            channel.save()

    def test_events_reconcile_with_the_edge_counts(self) -> None:
        graph, *_ = build_graph(include_mentions=True)
        events = dyads.citation_events(
            graph, start_date=None, end_date=None, environment_depth=None, include_mentions=True
        )
        per_pair = Counter((str(sender), str(receiver), kind) for sender, receiver, _t, kind, _id in events)
        for u, v, data in graph.edges(data=True):
            self.assertEqual(per_pair[(u, v, "forward")], int(data["weight_forwards"]))
            self.assertEqual(per_pair[(u, v, "mention")], int(data["weight_mentions"]))
        self.assertEqual(len(events), sum(citation_count(d) for _u, _v, d in graph.edges(data=True)))
        timestamps = [t for _s, _r, t, _k, _i in events]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_bundle_files_and_waves(self) -> None:
        graph, *_ = build_graph(include_mentions=True)
        graph_data = {"nodes": [{"id": n, "messages_count": 1, "fans": 1} for n in graph], "edges": []}
        wave = dyads.wave_of(2024, graph)
        with tempfile.TemporaryDirectory() as tmp:
            directory = dyads.write_dyadic_bundle(
                tmp,
                graph,
                graph_data,
                start_date=None,
                end_date=None,
                environment_depth=None,
                include_mentions=True,
                waves=[wave],
            )
            names = {p.name for p in Path(directory).iterdir()}
            self.assertTrue({"actors.csv", "edgelist.csv", "events.csv", "README.md", "waves"} <= names)
            with open(Path(directory) / "actors.csv", encoding="utf-8") as handle:
                actors = list(csv.DictReader(handle))
            self.assertEqual({a["Nation"] for a in actors}, {"Italy", "France"})
            with open(Path(directory) / "waves" / "wave_2024.csv", encoding="utf-8") as handle:
                matrix = list(csv.reader(handle))
            ties = sum(int(x) for row in matrix[1:] for x in row[1:])
            self.assertEqual(ties, len(wave[2]))
            self.assertEqual(ties, graph.number_of_edges() - len(list(nx.selfloop_edges(graph))))


class InferenceCommandTests(TestCase):
    def test_export_with_every_inference_option(self) -> None:
        nation = label_group("Nation", is_primary=False)
        org = make_label("Org")
        nations = [make_label(name, group=nation) for name in ("Italy", "France", "Spain")]
        channels = []
        for i in range(9):
            channel = make_channel(telegram_id=i + 1, label=org, title=f"C{i}")
            attribute(channel, nations[i % 3])
            channels.append(channel)
        rng = np.random.default_rng(4)
        date = datetime.datetime(2024, 5, 1, tzinfo=datetime.UTC)
        telegram_id = 1
        for channel in channels:
            for source in rng.choice(channels, size=4, replace=False):
                if source.pk != channel.pk:
                    Message.objects.create(telegram_id=telegram_id, channel=channel, forwarded_from=source, date=date)
                    telegram_id += 1
        for channel in channels:
            channel.save()

        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(BASE_DIR=Path(tmpdir)):
            call_command(
                "structural_analysis",
                measures="PAGERANK,INDEGCENTRALITY",
                network_stat_groups="ALL,SIGNIFICANCE",
                mrqap=True,
                mrqap_permutations=20,
                dyadic_export=True,
                html=True,
                xlsx=True,
                csv=True,
                name="inference-e2e",
                stdout=out,
                stderr=io.StringIO(),
            )
            export_dir = Path(tmpdir) / "exports" / "inference-e2e"
            metrics = json.loads((export_dir / "data" / "network_metrics.json").read_text())
            mrqap_payload = json.loads((export_dir / "data" / "mrqap.json").read_text())
            summary = json.loads((export_dir / "summary.json").read_text())
            parameters_md = (export_dir / "PARAMETERS.md").read_text(encoding="utf-8")
            self.assertTrue((export_dir / "label_flows.csv").is_file())
            self.assertTrue((export_dir / "dyads" / "events.csv").is_file())
            self.assertTrue((export_dir / "dyads" / "dyads.csv").is_file())
            import openpyxl

            sheets = openpyxl.load_workbook(export_dir / "network_table.xlsx").sheetnames

        groups = [g["group"] for g in metrics["label_mixing"]["groups"]]
        self.assertIn("Nation", groups)
        self.assertEqual([c[0] for c in metrics["significance_columns"]][-1], "label_permutation")
        self.assertIn("configuration", [c[0] for c in metrics["significance_columns"]])
        self.assertIsNone(mrqap_payload["skipped"])
        self.assertEqual(metrics["mrqap"]["dyads"], 9 * 8)
        self.assertTrue(summary["options"]["mrqap"])
        self.assertIn("Nation", [h["group"] for h in summary["homophily"]])
        self.assertTrue({"Homophily", "Label flows", "MRQAP"} <= set(sheets))
        self.assertIn("Label permutations", parameters_md)
        self.assertIn("Network significance: random graphs per baseline", parameters_md)
        self.assertIn("MRQAP permutations", parameters_md)

    def test_all_does_not_imply_significance(self) -> None:
        from network.measures import ALL_NETWORK_STAT_GROUPS

        self.assertIn("HOMOPHILY", ALL_NETWORK_STAT_GROUPS)
        self.assertNotIn("SIGNIFICANCE", ALL_NETWORK_STAT_GROUPS)

    def test_dead_leaf_helper_reads_build_graph_output(self) -> None:
        # Guard for the label-mixing / MRQAP node rule: build_graph's dead leaves are what both exclude.
        graph = nx.DiGraph([("1", "2")])
        graph.graph["dead_leaves"] = frozenset({"2"})
        self.assertEqual(dead_leaf_ids(graph), frozenset({"2"}))
