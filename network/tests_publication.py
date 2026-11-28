import datetime
import io
import json
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from network import exporter, publication, tables
from network.management.commands.compare_analysis import _recorded_public_url
from webapp.models import Message
from webapp.test_helpers import make_channel, make_label

URL = "https://example.org/report/"


def _read(root: str, name: str) -> str:
    with open(os.path.join(root, name), encoding="utf-8") as f:
        return f.read()


def _head(root: str, name: str) -> str:
    content = _read(root, name)
    return content[: content.index("</head>")]


class NormalisePublicUrlTests(SimpleTestCase):
    def test_empty_is_unset(self) -> None:
        self.assertEqual(publication.normalise_public_url(None), "")
        self.assertEqual(publication.normalise_public_url("  "), "")

    def test_folder_address_with_trailing_slash(self) -> None:
        self.assertEqual(publication.normalise_public_url("HTTPS://Example.ORG/report"), URL)
        self.assertEqual(publication.normalise_public_url("https://example.org/report/index.html"), URL)
        self.assertEqual(publication.normalise_public_url("https://example.org"), "https://example.org/")

    def test_rejects_what_is_not_an_absolute_web_address(self) -> None:
        for value in ("example.org/report", "ftp://example.org/", "https://example.org/?a=1", "/report/"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                publication.normalise_public_url(value)


class ApplyToPageTests(SimpleTestCase):
    PAGE = (
        "<!DOCTYPE html>\n<html>\n<head>\n"
        '  <meta name="robots" content="noindex">\n'
        "  <title>Demo | Network statistics</title>\n"
        '  <meta property="og:title" content="stale">\n'
        '  <meta name="twitter:card" content="summary">\n'
        "</head>\n<body></body>\n</html>\n"
    )

    def test_private_page_refuses_indexing_and_ai(self) -> None:
        out = publication.apply_to_page(self.PAGE, "network_table.html", seo=False)
        self.assertEqual(out.count('name="robots"'), 1)
        self.assertIn(f'content="{publication.PRIVATE_ROBOTS}"', out)
        self.assertIn('<meta name="tdm-reservation" content="1">', out)
        self.assertIn('<meta name="referrer" content="no-referrer">', out)
        # A template's sharing tags go: nothing about the page is offered for previews.
        self.assertNotIn("og:", out)
        self.assertNotIn("twitter:", out)

    def test_search_optimised_page(self) -> None:
        out = publication.apply_to_page(self.PAGE, "network_table.html", seo=True, public_url=URL, site_name="Demo")
        self.assertIn(f'content="{publication.INDEX_ROBOTS}"', out)
        self.assertIn(f'<link rel="canonical" href="{URL}network_table.html">', out)
        self.assertIn('<meta property="og:title" content="Demo | Network statistics">', out)
        self.assertNotIn("stale", out)
        self.assertIn(publication.PAGE_DESCRIPTIONS["network_table.html"], out)
        # The breadcrumb names the page without the site name it starts with.
        self.assertIn('"name": "Network statistics"', out)
        self.assertNotIn("tdm-reservation", out)

    def test_own_description_is_kept(self) -> None:
        page = self.PAGE.replace("</title>", '</title>\n  <meta name="description" content="Own words.">')
        out = publication.apply_to_page(page, "network_table.html", seo=True)
        self.assertIn('<meta property="og:description" content="Own words.">', out)
        self.assertEqual(out.count('name="description"'), 1)

    def test_no_canonical_without_public_url(self) -> None:
        out = publication.apply_to_page(self.PAGE, "network_table.html", seo=True)
        self.assertNotIn("canonical", out)
        self.assertNotIn("og:url", out)

    def test_idempotent_and_switchable(self) -> None:
        once = publication.apply_to_page(self.PAGE, "network_table.html", seo=True, public_url=URL)
        self.assertEqual(publication.apply_to_page(once, "network_table.html", seo=True, public_url=URL), once)
        private = publication.apply_to_page(once, "network_table.html", seo=False)
        self.assertEqual(private, publication.apply_to_page(self.PAGE, "network_table.html", seo=False))

    def test_title_holding_script_cannot_break_out(self) -> None:
        page = self.PAGE.replace("Demo | Network statistics", "&lt;/script&gt;&lt;b&gt;")
        out = publication.apply_to_page(page, "index.html", seo=True)
        ld = out[out.index('<script type="application/ld+json">') :]
        self.assertNotIn("</script><b>", ld)

    def test_compared_copy_reuses_its_original_description(self) -> None:
        self.assertTrue(publication.page_description("channel_table_2.html").endswith("in the compared analysis."))
        self.assertEqual(publication.page_description("unknown.html"), "")


class PublishTests(TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(settings.BASE_DIR / "webapp_engine" / "map", self.root, dirs_exist_ok=True)

    def _build(self, seo: bool) -> None:
        # 2D map requested, 3D not: graph3d.html is a template copy nothing links to.
        exporter.apply_robots_to_graph_html(self.root, seo, project_title="Demo", node_count=3, edge_count=2)
        tables.write_table_html(
            {"nodes": [{}] * 3, "edges": []}, os.path.join(self.root, "channel_table.html"), seo=seo
        )
        tables.write_index_html(
            os.path.join(self.root, "index.html"),
            seo=seo,
            project_title="Demo",
            include_graph=True,
            include_channel_html=True,
            include_channel_xlsx=True,
        )
        for name in ("channel_table.xlsx", "nodes.csv", "network.gexf"):
            with open(os.path.join(self.root, name), "w") as f:
                f.write("x")
        with open(os.path.join(self.root, "summary.json"), "w") as f:
            json.dump(
                {
                    "nodes": 3,
                    "edges": 2,
                    "created_at": "2026-01-15T10:00:00",
                    "options": {"startdate": "2024-01-01", "enddate": "2024-12-31", "public_url": URL},
                },
                f,
            )

    def test_private_export(self) -> None:
        self._build(seo=False)
        written = publication.publish(self.root, seo=False, public_url=URL, site_name="Demo")
        self.assertEqual(written, ["robots.txt", ".htaccess", "_headers"])
        for page in ("index.html", "graph.html", "graph3d.html", "channel_table.html"):
            with self.subTest(page=page):
                head = _head(self.root, page)
                self.assertIn(f'content="{publication.PRIVATE_ROBOTS}"', head)
                self.assertEqual(head.count('name="robots"'), 1)
                self.assertNotIn("canonical", head)
        robots = _read(self.root, "robots.txt")
        self.assertIn("User-agent: GPTBot\n", robots)
        self.assertIn("User-agent: Google-Extended\n", robots)
        self.assertTrue(robots.rstrip().endswith("User-agent: *\nDisallow: /"))
        htaccess = _read(self.root, ".htaccess")
        self.assertIn(f'X-Robots-Tag "{publication.PRIVATE_ROBOTS}"', htaccess)
        self.assertIn("ClaudeBot", htaccess)
        # robots.txt-only tokens never appear in a request, so the user-agent block leaves them out.
        self.assertNotIn("Google-Extended", htaccess)
        self.assertIn(f"X-Robots-Tag: {publication.PRIVATE_ROBOTS}", _read(self.root, "_headers"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "sitemap.xml")))

    def test_search_optimised_export(self) -> None:
        self._build(seo=True)
        written = publication.publish(self.root, seo=True, public_url=URL, site_name="Demo")
        self.assertEqual(written, ["robots.txt", "sitemap.xml"])
        index = _head(self.root, "index.html")
        self.assertIn(f'<link rel="canonical" href="{URL}">', index)
        ld = json.loads(index.split('<script type="application/ld+json">')[1].split("</script>")[0])
        self.assertEqual(ld["@type"], "Dataset")
        self.assertEqual(ld["name"], "Demo")
        self.assertGreaterEqual(len(ld["description"]), publication.DATASET_MIN_DESCRIPTION)
        self.assertIn("3 Telegram channels", ld["description"])
        self.assertEqual(ld["temporalCoverage"], "2024-01-01/2024-12-31")
        self.assertEqual(ld["dateModified"], "2026-01-15")
        self.assertEqual(
            {d["contentUrl"] for d in ld["distribution"]},
            {f"{URL}channel_table.xlsx", f"{URL}network.gexf", f"{URL}nodes.csv"},
        )
        self.assertIn("<title>Demo | Structural map</title>", _head(self.root, "graph.html"))
        # The unrequested 3D template copy is not linked from the landing page: kept out of the index.
        self.assertIn('<meta name="robots" content="noindex">', _head(self.root, "graph3d.html"))
        sitemap = _read(self.root, "sitemap.xml")
        self.assertIn(f"<loc>{URL}</loc>", sitemap)
        self.assertIn(f"<loc>{URL}graph.html</loc>", sitemap)
        self.assertNotIn("graph3d.html", sitemap)
        self.assertIn(f"Sitemap: {URL}sitemap.xml", _read(self.root, "robots.txt"))

    def test_switching_policy_removes_the_other_policys_files(self) -> None:
        self._build(seo=False)
        publication.publish(self.root, seo=False, public_url=URL)
        publication.publish(self.root, seo=True, public_url=URL)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".htaccess")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "_headers")))
        publication.publish(self.root, seo=False)
        self.assertFalse(os.path.exists(os.path.join(self.root, "sitemap.xml")))

    def test_a_file_pulpit_did_not_write_is_left_alone(self) -> None:
        self._build(seo=True)
        with open(os.path.join(self.root, ".htaccess"), "w") as f:
            f.write("AuthType Basic\n")
        publication.publish(self.root, seo=True, public_url=URL)
        self.assertEqual(_read(self.root, ".htaccess"), "AuthType Basic\n")

    def test_no_sitemap_without_public_url(self) -> None:
        self._build(seo=True)
        self.assertEqual(publication.publish(self.root, seo=True), ["robots.txt"])
        self.assertNotIn("Sitemap:", _read(self.root, "robots.txt"))

    def test_missing_folder_is_a_no_op(self) -> None:
        self.assertEqual(publication.publish(os.path.join(self.root, "absent"), seo=True), [])

    def test_compare_reuses_the_recorded_public_url(self) -> None:
        self._build(seo=True)
        self.assertEqual(_recorded_public_url(self.root), URL)
        self.assertEqual(_recorded_public_url(os.path.join(self.root, "absent")), "")


class ExportPublicationTests(TestCase):
    """A real structural_analysis run ends with the publication pass, whatever it wrote."""

    def setUp(self) -> None:
        label = make_label("Org", color="#FF0000")
        a = make_channel(telegram_id=1, label=label, title="A")
        b = make_channel(telegram_id=2, label=label, title="B")
        day = datetime.datetime(2024, 3, 1, tzinfo=datetime.UTC)
        Message.objects.create(telegram_id=1, channel=a, date=day, forwarded_from=b)

    def _run(self, *extra: str) -> Path:
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        with override_settings(BASE_DIR=Path(tmpdir)):
            call_command("structural_analysis", *extra, name="pub", stdout=io.StringIO(), stderr=io.StringIO())
        return Path(tmpdir) / "exports" / "pub"

    def test_private_by_default_even_without_a_map(self) -> None:
        export = self._run("--html", "--csv")
        self.assertTrue((export / ".htaccess").exists())
        self.assertTrue((export / "_headers").exists())
        self.assertIn("Disallow: /", (export / "robots.txt").read_text())
        self.assertIn(publication.PRIVATE_ROBOTS, (export / "channel_table.html").read_text())
        self.assertIsNone(json.loads((export / "summary.json").read_text())["options"]["public_url"])

    def test_seo_with_public_url(self) -> None:
        export = self._run("--html", "--csv", "--seo", "--public-url", "https://example.org/report")
        self.assertTrue((export / "sitemap.xml").exists())
        self.assertFalse((export / ".htaccess").exists())
        index = (export / "index.html").read_text()
        self.assertIn(f'<link rel="canonical" href="{URL}">', index)
        self.assertIn('"@type": "Dataset"', index)
        self.assertIn(f"{URL}nodes.csv", index)
        options = json.loads((export / "summary.json").read_text())["options"]
        self.assertEqual(options["public_url"], URL)

    def test_invalid_public_url_is_a_command_error(self) -> None:
        with self.assertRaisesMessage(CommandError, "--public-url"):
            call_command("structural_analysis", public_url="example.org", stdout=io.StringIO(), stderr=io.StringIO())
