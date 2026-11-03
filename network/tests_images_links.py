"""Image copies (network.image_copies), visual originality, outbound links (network.links) and the link layer."""

import collections
import csv
import datetime
import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from network import dyads, exporter, link_layer
from network.graph_builder import build_graph
from network.image_copies import find_image_copies, image_copies_for_channels
from network.links import index_domains, message_sites, platform_of, site_of, text_urls
from network.measures import apply_content_originality, apply_visual_originality
from network.utils import channel_cutoff_q, citation_count
from webapp.models import Domain, DomainCategory, ImageFingerprint, Message, MessagePicture
from webapp.test_helpers import make_channel, make_label

import numpy as np


def _day(day: int, hour: int = 0) -> datetime.datetime:
    return datetime.datetime(2024, 3, 1, hour, tzinfo=datetime.UTC) + datetime.timedelta(days=day)


def _picture(message: Message, photo_id: int) -> MessagePicture:
    return MessagePicture.objects.create(message=message, telegram_id=photo_id, picture=f"photos/{photo_id}.jpg")


class ImageCopyDetectionTests(TestCase):
    """``find_image_copies`` on rows of (message id, channel id, date, grouped_id, photo id)."""

    def test_an_album_is_one_post(self) -> None:
        rows = [
            (1, 10, _day(0), 500, 1),
            (2, 10, _day(0), 500, 2),
            (3, 10, _day(0), 500, 3),
            (4, 20, _day(1), 700, 1),
            (5, 20, _day(1), 700, 2),
        ]
        links, posts = find_image_copies(rows, {})
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(links), 1)
        link = links[0]
        self.assertEqual((link.copy_id, link.origin_id), (4, 1))
        self.assertEqual((link.copy_channel_id, link.origin_channel_id), (20, 10))
        self.assertEqual(link.distance, 0)
        self.assertEqual(link.cluster_size, 2)
        self.assertAlmostEqual(link.lag_hours, 24.0)

    def test_every_copy_points_to_the_earliest_post(self) -> None:
        rows = [(1, 10, _day(0), None, 9), (2, 20, _day(1), None, 9), (3, 30, _day(2), None, 9)]
        by_copy = {link.copy_id: link for link in find_image_copies(rows, {})[0]}
        self.assertEqual(set(by_copy), {2, 3})
        self.assertEqual(by_copy[3].origin_id, 1)
        self.assertEqual(by_copy[3].cluster_size, 3)

    def test_perceptual_hashes_within_the_distance_match(self) -> None:
        rows = [(1, 10, _day(0), None, 101), (2, 20, _day(1), None, 202)]
        hashes = {101: 0b1011, 202: 0b0100}  # 4 differing bits
        links, _ = find_image_copies(rows, hashes, distance=6)
        self.assertEqual([(link.copy_id, link.origin_id, link.distance) for link in links], [(2, 1, 4)])
        self.assertEqual(find_image_copies(rows, hashes, distance=3)[0], [])

    def test_negative_hashes_compare_as_64_bit_patterns(self) -> None:
        rows = [(1, 10, _day(0), None, 101), (2, 20, _day(1), None, 202)]
        hashes = {101: -1, 202: -2}  # all ones vs all ones but the lowest bit
        self.assertEqual(find_image_copies(rows, hashes, distance=1)[0][0].distance, 1)

    def test_a_channels_own_logo_is_not_a_citation(self) -> None:
        own = [(i, 10, _day(i), None, photo) for i in range(6) for photo in (50, 600 + i)]
        later = (99, 20, _day(10), None, 50)
        # The logo on every one of channel 10's posts is its boilerplate: channel 20 showing it copies nothing …
        self.assertEqual(find_image_copies([*own, later], {})[0], [])
        # … while with too few posts to tell, the same picture is a copy of channel 10's post.
        self.assertEqual(len(find_image_copies([own[0], own[1], later], {})[0]), 1)

    def test_self_copy_is_flagged(self) -> None:
        rows = [(1, 10, _day(0), None, 9), (2, 10, _day(3), None, 9)]
        (link,) = find_image_copies(rows, {})[0]
        self.assertTrue(link.is_self_copy)

    def test_rejects_a_distance_outside_64_bits(self) -> None:
        with self.assertRaises(ValueError):
            find_image_copies([], {}, distance=65)


class ImageCopyGraphTests(TestCase):
    def setUp(self) -> None:
        label = make_label("Org", color="#FF0000")
        self.origin = make_channel(telegram_id=1, label=label, title="Origin")
        self.copier = make_channel(telegram_id=2, label=label, title="Copier")
        self.posted = Message.objects.create(telegram_id=1, channel=self.origin, date=_day(0), message="training")
        _picture(self.posted, 77)
        # A forward keeps the photo id but carries a header: a citation already, never a copy.
        forward = Message.objects.create(
            telegram_id=2, channel=self.copier, date=_day(1), forwarded_from=self.origin, fwd_from_date=_day(0)
        )
        _picture(forward, 77)
        self.copy = Message.objects.create(telegram_id=3, channel=self.copier, date=_day(2), message="our club")
        _picture(self.copy, 78)
        ImageFingerprint.objects.create(telegram_id=77, phash=0b1111, dhash=0, width=10, height=10, file_name="a")
        ImageFingerprint.objects.create(telegram_id=78, phash=0b0111, dhash=0, width=10, height=10, file_name="b")

    def test_detection_skips_forwards_and_matches_the_hash(self) -> None:
        detection = image_copies_for_channels([self.origin.pk, self.copier.pk], cutoff_q=channel_cutoff_q(), distance=6)
        (link,) = detection["links"]
        self.assertEqual((link.copy_id, link.origin_id, link.distance), (self.copy.pk, self.posted.pk, 1))
        self.assertEqual(detection["image_posts"], {self.origin.pk: 1, self.copier.pk: 1})
        self.assertEqual(detection["copied_posts"], {self.copier.pk: 1})

    def test_off_by_default(self) -> None:
        graph, _, edge_list, _ = build_graph()
        self.assertEqual(graph.graph["image_copies"], [])
        self.assertFalse(graph.graph["image_copies_enabled"])
        self.assertEqual({edge[6] for edge in edge_list}, {0.0})

    def test_edge_counts_reconcile_with_the_audit_list(self) -> None:
        graph, channel_dict, edge_list, _ = build_graph(include_image_copies=True, image_copy_distance=6)
        data = graph.edges[str(self.copier.pk), str(self.origin.pk)]
        self.assertEqual((data["weight_forwards"], data["weight_image_copies"]), (1.0, 1.0))
        self.assertEqual(citation_count(data), 2)
        self.assertEqual(len(graph.graph["image_copies"]), 1)
        # The copying post joins the citing-message denominator next to the forward.
        self.assertEqual(channel_dict[str(self.copier.pk)]["data"]["citing_messages"], 2)

        events = dyads.citation_events(
            graph, start_date=None, end_date=None, environment_depth=None, include_mentions=False
        )
        self.assertEqual(sorted(e[3] for e in events), ["forward", "image_copy"])

        with tempfile.TemporaryDirectory() as tmp:
            graph_data = {"nodes": [{"id": n, "label": n} for n in graph.nodes]}
            path = exporter.write_image_copies_csv(graph, graph_data, tmp)
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            exporter.write_csv(graph_data, edge_list, [], [], tmp)
            with open(Path(tmp) / "edges.csv", newline="", encoding="utf-8") as fh:
                edges = list(csv.DictReader(fh))
        self.assertEqual(
            [(r["copy_message_id"], r["distance"], r["self_copy"]) for r in rows], [(str(self.copy.pk), "1", "0")]
        )
        self.assertEqual(edges[0]["weight_image_copies"], "1.0")

    def test_a_copy_that_also_mentions_its_origin_is_one_citing_message(self) -> None:
        self.copy.references.add(self.origin)
        graph, channel_dict, _, _ = build_graph(include_image_copies=True, image_copy_distance=6, include_mentions=True)
        data = graph.edges[str(self.copier.pk), str(self.origin.pk)]
        self.assertEqual((data["weight_mentions"], data["weight_image_copies"]), (1.0, 1.0))
        self.assertEqual(channel_dict[str(self.copier.pk)]["data"]["citing_messages"], 2)

    def test_distance_zero_needs_the_same_photo(self) -> None:
        graph, _, _, _ = build_graph(include_image_copies=True, image_copy_distance=0)
        self.assertEqual(graph.graph["image_copies"], [])

    def test_visual_and_content_originality(self) -> None:
        graph, channel_dict, _, _ = build_graph(include_image_copies=True, image_copy_distance=6)
        graph_data = {"nodes": [{"id": n} for n in graph.nodes]}
        apply_visual_originality(graph_data, graph, channel_dict)
        apply_content_originality(graph_data, graph, channel_dict)
        by_id = {n["id"]: n for n in graph_data["nodes"]}
        self.assertEqual(by_id[str(self.origin.pk)]["visual_originality"], 1.0)
        self.assertEqual(by_id[str(self.copier.pk)]["visual_originality"], 0.0)
        # The copier's two messages are a forward and an image copy: nothing original.
        self.assertEqual(by_id[str(self.copier.pk)]["content_originality"], 0.0)

    def test_visual_originality_runs_its_own_detection_without_the_edges(self) -> None:
        graph, channel_dict, _, _ = build_graph()
        graph_data = {"nodes": [{"id": n} for n in graph.nodes]}
        apply_visual_originality(graph_data, graph, channel_dict)
        by_id = {n["id"]: n for n in graph_data["nodes"]}
        self.assertEqual(by_id[str(self.copier.pk)]["visual_originality"], 0.0)


class LinkExtractionTests(TestCase):
    def test_text_urls_trim_punctuation_and_unbalanced_brackets(self) -> None:
        self.assertEqual(
            text_urls("See https://example.com/a). Also (www.gab.com/x) and https://en.wikipedia.org/wiki/A_(b)."),
            ["https://example.com/a", "www.gab.com/x", "https://en.wikipedia.org/wiki/A_(b)"],
        )

    def test_site_rule(self) -> None:
        cases = {
            "https://www.YouTube.com/watch?v=1": "youtube.com",
            "https://m.facebook.com/x": "facebook.com",
            "http://news.bbc.co.uk/a": "bbc.co.uk",
            "https://joe.substack.com/p/x": "joe.substack.com",
            "https://open.substack.com/pub/joe/p/x?r=1": "joe.substack.com",
            "https://open.substack.com/": "open.substack.com",
            "https://shop.name.myshopify.com/": "name.myshopify.com",
            "https://docs.google.com/forms/d/1": "docs.google.com",
            "https://bücher.de/": "xn--bcher-kva.de",
            "https://amp.theguardian.com:443/x": "theguardian.com",
            "shopw2r.com": "shopw2r.com",
            "https://t.me/channel/5": "",
            "https://telegra.ph/article": "",
            "mailto:x@y.org": "",
            "tg://resolve?domain=x": "",
        }
        for url, site in cases.items():
            with self.subTest(url=url):
                self.assertEqual(site_of(url), site)
        self.assertEqual(platform_of("joe.substack.com"), "substack.com")
        self.assertEqual(platform_of("substack.com"), "")

    def test_a_site_counts_once_per_message_from_every_source(self) -> None:
        sites = message_sites(
            "https://gab.com/a https://gab.com/b https://t.me/x",
            "https://odysee.com/@x",
            ["https://bit.ly/abc", "https://gab.com/c"],
        )
        self.assertEqual(sites, {"gab.com", "odysee.com", "bit.ly"})


class IndexDomainsTests(TestCase):
    def setUp(self) -> None:
        label = make_label("Org")
        self.a = make_channel(
            telegram_id=1, label=label, attribution_start=datetime.date(2024, 1, 1), attribution_end=None
        )
        self.b = make_channel(telegram_id=2, label=label)
        Message.objects.create(telegram_id=1, channel=self.a, date=_day(0), message="Donate https://givesendgo.com/x")
        Message.objects.create(
            telegram_id=2, channel=self.b, date=_day(1), message="ok", link_urls=["https://givesendgo.com/y"]
        )
        Message.objects.create(telegram_id=3, channel=self.b, date=_day(2), webpage_url="https://joe.substack.com/p")
        # Before channel a's in-target period: not counted.
        Message.objects.create(
            telegram_id=4,
            channel=self.a,
            date=datetime.datetime(2023, 6, 1, tzinfo=datetime.UTC),
            message="https://gab.com/old",
        )

    def test_counts_and_platform_categories(self) -> None:
        counts = index_domains()
        self.assertEqual(counts["messages"], 3)
        donation = Domain.objects.get(name="givesendgo.com")
        self.assertEqual((donation.posts, donation.channels), (2, 2))
        self.assertEqual(donation.category.role, DomainCategory.ROLE_MONETISATION)
        outlet = Domain.objects.get(name="joe.substack.com")
        self.assertEqual(outlet.category, Domain.objects.get(name="substack.com").category)
        self.assertFalse(Domain.objects.filter(name="gab.com", posts__gt=0).exists())

    def test_a_site_no_longer_linked_keeps_its_row_with_zero_counts(self) -> None:
        index_domains()
        Domain.objects.filter(name="joe.substack.com").update(note="their newsletter")
        Message.objects.filter(telegram_id=3).update(is_lost=True)
        index_domains()
        outlet = Domain.objects.get(name="joe.substack.com")
        self.assertEqual((outlet.posts, outlet.note), (0, "their newsletter"))


class LinkLayerTests(TestCase):
    def setUp(self) -> None:
        self.label_a = make_label("A", color="#FF0000")
        self.label_b = make_label("B", color="#00FF00", group=self.label_a.group)
        self.x = make_channel(telegram_id=1, label=self.label_a, title="X")
        self.y = make_channel(telegram_id=2, label=self.label_b, title="Y")
        # A tie so both channels are in the graph.
        Message.objects.create(telegram_id=1, channel=self.x, date=_day(0), forwarded_from=self.y)
        Message.objects.create(
            telegram_id=2, channel=self.x, date=_day(1), message="https://gab.com/a https://givesendgo.com/b"
        )
        Message.objects.create(telegram_id=3, channel=self.x, date=_day(2), message="https://youtube.com/x")
        Message.objects.create(telegram_id=4, channel=self.x, date=_day(3), message="no link")
        Message.objects.create(telegram_id=5, channel=self.y, date=_day(1), message="https://gab.com/z unknown.org")
        Message.objects.create(telegram_id=6, channel=self.y, date=_day(2), message="https://unknown-site.net")

    def _payload(self) -> dict:
        graph, _, _, _ = build_graph()
        graph_data = {"nodes": [{"id": n, "label": n, "organization": ""} for n in graph.nodes]}
        payload = link_layer.compute_links(graph, graph_data)
        labels = link_layer.inject_node_scores(graph_data, payload)
        self.assertEqual([k for k, _ in labels], [k for k, _ in link_layer.NODE_MEASURES])
        return payload

    def test_channel_measures(self) -> None:
        rows = {row["id"]: row for row in self._payload()["channels"]}
        x = rows[str(self.x.pk)]
        self.assertEqual((x["messages"], x["linking_messages"], x["link_events"]), (4, 2, 3))
        self.assertEqual(x["link_share"], 0.5)
        self.assertEqual(x["distinct_sites"], 3)
        third = round(1 / 3, 4)
        self.assertEqual((x["monetisation_share"], x["mainstream_share"], x["alternative_share"]), (third,) * 3)
        self.assertAlmostEqual(x["platform_diversity"], 3.0)
        y = rows[str(self.y.pk)]
        # gab.com is alternative; unknown-site.net is uncategorised: diversity over the categorised links only.
        self.assertEqual((y["link_events"], y["alternative_share"], y["categorised_share"]), (2, 0.5, 0.5))
        self.assertEqual(y["platform_diversity"], 1.0)

    def test_matrix_and_category_totals_match_the_link_events(self) -> None:
        payload = self._payload()
        self.assertEqual(sum(c["events"] for c in payload["categories"]), payload["summary"]["link_events"])
        matrix = payload["matrices"][0]
        self.assertEqual(sum(map(sum, matrix["counts"])), payload["summary"]["link_events"])
        self.assertEqual(set(matrix["labels"]), {"A", "B"})

    def test_colinking_payload(self) -> None:
        co = self._payload()["colinking"]
        self.assertEqual((co["channels"], co["sites"], co["tested"]), (2, 4, 1))
        self.assertEqual((co["null"], co["p_method"]), ("bicm", "exact"))
        # One shared site (gab.com) is below the listing floor, but the pair stays in the family.
        self.assertEqual(co["pairs"], [])

    def test_bh_counts_the_untested_pairs(self) -> None:
        q = link_layer._bh(np.array([0.01, 0.04]), family=10)
        self.assertAlmostEqual(q[0], 0.1)
        self.assertAlmostEqual(q[1], 0.2)


class ImageAndLinkExportTests(TestCase):
    def setUp(self) -> None:
        label = make_label("Org", color="#FF0000")
        self.a = make_channel(telegram_id=1, label=label, title="A")
        self.b = make_channel(telegram_id=2, label=label, title="B")
        Message.objects.create(telegram_id=1, channel=self.a, date=_day(0), forwarded_from=self.b)
        posted = Message.objects.create(telegram_id=2, channel=self.b, date=_day(1), message="https://gab.com/x")
        _picture(posted, 77)
        copy = Message.objects.create(telegram_id=3, channel=self.a, date=_day(3), message="https://givesendgo.com/y")
        _picture(copy, 77)

    def _run(self, *extra: str) -> Path:
        tmpdir = tempfile.mkdtemp()
        with override_settings(BASE_DIR=Path(tmpdir)):
            call_command("structural_analysis", *extra, name="img-links", stdout=io.StringIO(), stderr=io.StringIO())
        return Path(tmpdir) / "exports" / "img-links"

    def test_export_writes_the_image_and_link_outputs(self) -> None:
        export = self._run(
            "--image-copy-edges",
            "--links",
            "--measures",
            "VISUALORIGINALITY,PAGERANK",
            "--html",
            "--xlsx",
            "--csv",
            "--timeline-step",
            "year",
        )
        for name in (
            "data/image_copies.csv",
            "data/links.json",
            "links.html",
            "links.xlsx",
            "channel_sites.csv",
            "links_colinking.csv",
            "data_2024/links.json",
            "data_2024/image_copies.csv",
        ):
            self.assertTrue((export / name).exists(), name)
        summary = json.loads((export / "summary.json").read_text())
        self.assertEqual(summary["image_copies"], 1)
        self.assertTrue(summary["options"]["image_copy_edges"])
        self.assertTrue(summary["options"]["links"])
        channels = json.loads((export / "data" / "channels.json").read_text())
        keys = {k for k, _ in channels["measures"]}
        self.assertTrue({"visual_originality", "link_share", "monetisation_share"} <= keys)
        timeline = json.loads((export / "data" / "timeline.json").read_text())
        self.assertTrue(all(p["has_links"] for p in timeline["periods"]))
        parameters = (export / "PARAMETERS.md").read_text()
        self.assertIn("Image copies", parameters)
        self.assertIn("Outbound links", parameters)
        self.assertIn("links.html", (export / "index.html").read_text())

    def test_distance_outside_64_bits_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            call_command("structural_analysis", image_copy_distance=70, stdout=io.StringIO(), stderr=io.StringIO())


class ColinkingNullTests(TestCase):
    """The bipartite configuration model and the exact tail of the shared-site count."""

    def test_bicm_reproduces_both_degree_sequences(self) -> None:
        rng = np.random.default_rng(3)
        incidence = (rng.random((15, 25)) < 0.25).astype(float)
        incidence[0, :] = 0
        incidence[0, 3] = 1
        incidence[:, 0] = 1  # a site every channel links to
        p = link_layer.bicm_probabilities(incidence)
        self.assertTrue(np.allclose(p.sum(axis=1), incidence.sum(axis=1), atol=1e-6))
        self.assertTrue(np.allclose(p.sum(axis=0), incidence.sum(axis=0), atol=1e-6))
        self.assertTrue(np.allclose(p[:, 0], 1.0))
        self.assertTrue(((p >= 0) & (p <= 1)).all())

    def test_a_site_nobody_links_has_probability_zero(self) -> None:
        incidence = np.array([[1, 1, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        self.assertTrue(np.allclose(link_layer.bicm_probabilities(incidence)[:, 2], 0.0))

    def test_shared_site_tail_is_the_exact_poisson_binomial(self) -> None:
        import itertools

        p = np.array([[0.9, 0.5, 0.2, 0.7, 0.1], [0.8, 0.6, 0.3, 0.4, 0.5]])
        q = p[0] * p[1]
        for k in range(1, 6):
            brute = sum(
                np.prod([qs if bit else 1 - qs for qs, bit in zip(q, bits, strict=True)])
                for bits in itertools.product((0, 1), repeat=5)
                if sum(bits) >= k
            )
            tail, method = link_layer._shared_site_pvalues(p, np.array([0]), np.array([1]), np.array([k]))
            self.assertEqual(method, "exact")
            self.assertAlmostEqual(float(tail[0]), brute, places=12)

    def test_poisson_approximation_beyond_the_budget(self) -> None:
        from unittest.mock import patch

        from scipy.stats import poisson

        p = np.full((2, 50), 0.1)
        with patch.object(link_layer, "COLINK_EXACT_BUDGET", 0):
            tail, method = link_layer._shared_site_pvalues(p, np.array([0]), np.array([1]), np.array([2]))
        self.assertEqual(method, "poisson")
        self.assertAlmostEqual(float(tail[0]), float(poisson.sf(1, 0.5)))

    def test_popular_sites_do_not_make_a_pair(self) -> None:
        # Ten channels all link the same three big platforms; two of them also share three rare sites.
        channel_sites = {str(i): collections.Counter({"x.com": 1, "youtube.com": 1, "gab.com": 1}) for i in range(10)}
        for site in ("shop.example", "fund.example", "club.example"):
            channel_sites["0"][site] = 1
            channel_sites["1"][site] = 1
        for i in range(2, 10):
            channel_sites[str(i)][f"own{i}.example"] = 1
        site_channels = collections.defaultdict(set)
        for node, sites in channel_sites.items():
            for site in sites:
                site_channels[site].add(node)
        info = {n: {"id": n, "label": n, "organization": ""} for n in channel_sites}
        co = link_layer._colinking(channel_sites, site_channels, info)
        top = co["pairs"][0]
        self.assertEqual({top["a"]["id"], top["b"]["id"]}, {"0", "1"})
        self.assertEqual(top["shared"], 6)
        self.assertEqual(top["common"][:3], ["club.example", "fund.example", "shop.example"])
        others = [pair for pair in co["pairs"] if {pair["a"]["id"], pair["b"]["id"]} != {"0", "1"}]
        # Sharing only the three platforms everyone links is exactly what the model expects.
        self.assertTrue(all(pair["p"] > 0.5 for pair in others))
        self.assertTrue(
            all(
                abs(pair["expected"] - 3.0) < 0.2
                for pair in others
                if "0" not in (pair["a"]["id"], pair["b"]["id"]) and "1" not in (pair["a"]["id"], pair["b"]["id"])
            )
        )
