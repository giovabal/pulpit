import csv
import logging
import os
import re
import shutil
import tempfile

from django.test import SimpleTestCase, TestCase

from network import data_dictionary as dd, dominance, event_impact, exporter, label_mixing, link_layer, mrqap
from webapp.audience.tables import TABLE_SECTIONS, section_table

import openpyxl

# Words that say nothing by themselves: a description needs more than its own column name around them.
_FILLER = {"the", "a", "an", "of", "its", "it", "row", "s", "in", "that", "is"}
_OF_THE_ROW = re.compile(r"^(the|its) [\w' -]+ of the row\.?$", re.IGNORECASE)


def _is_a_sentence(key: str, text: str) -> bool:
    """A description that says more than the column's own name: a few words, ended, not "The X of the row"."""
    words = [w.lower() for w in re.findall(r"[^\W_]+", text)]
    named = {w.lower() for w in re.findall(r"[^\W\d_]+", key)}
    informative = [w for w in words if w not in named and w not in _FILLER]
    return (
        len(words) >= 4 and text.rstrip().endswith((".", ")")) and not _OF_THE_ROW.match(text) and len(informative) >= 2
    )


def _write(root: str, relative: str, content: str = "") -> str:
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _writer_tables() -> list[tuple[str, str, list[str]]]:
    """``(file, sheet, headers)`` of the tables whose column layouts the writers declare as constants."""
    channel_headers, _rows = exporter.channel_table(
        {"nodes": []},
        [("pagerank", "PageRank"), ("hits_hub", "HITS hub"), ("burt_constraint", "Burt's constraint")],
        ["leiden", "leiden_cpm_resolution_0_05", "leiden_cpm_resolution_0_5"],
    )
    # Label groups named like the pair columns of other tables, and one in a non-Latin script.
    channel_headers = [*channel_headers, "Label: A", "Label: B", "Label: Group", "Label: Страна", "Label: 国"]
    tables = [
        ("channel_table.xlsx", "Channels", channel_headers),
        ("network_table.xlsx", "Homophily", list(label_mixing.GROUP_COLUMNS)),
        ("network_table.xlsx", "Homophily by label", list(label_mixing.LABEL_COLUMNS)),
        ("network_table.xlsx", "Label flows", list(label_mixing.FLOW_COLUMNS)),
        ("network_table.xlsx", "MRQAP models", list(mrqap.MODEL_COLUMNS)),
        ("network_table.xlsx", "MRQAP coefficients", list(mrqap.COEFFICIENT_COLUMNS)),
        ("dominance.xlsx", "Channels", [name for name, _get in dominance.NODE_COLUMNS]),
        ("dominance.xlsx", "Pairs", [name for name, _get in dominance.PAIR_COLUMNS]),
        ("event_impact.xlsx", "Effects", list(event_impact.EFFECT_COLUMNS)),
        ("links.xlsx", "Channels", [name for name, _get in link_layer.CHANNEL_COLUMNS]),
        ("links.xlsx", "Sites", [name for name, _get in link_layer.SITE_COLUMNS]),
        ("links.xlsx", "Categories", [name for name, _get in link_layer.CATEGORY_COLUMNS]),
        ("links.xlsx", "Co-linking", [name for name, _get in link_layer.PAIR_COLUMNS]),
        ("links.xlsx", "Channel sites", list(link_layer.CHANNEL_SITE_COLUMNS)),
        ("data/near_copies.csv", "", list(exporter._NEAR_COPY_COLUMNS)),
        ("data/image_copies.csv", "", list(exporter._IMAGE_COPY_COLUMNS)),
    ]
    empty = {"channels": [], "groups": [], "pairs": [], "monthly": []}
    for section in TABLE_SECTIONS:
        columns, _rows = section_table(section, empty)
        tables.append((f"audience_{section.replace('-', '_')}.csv", "", list(columns)))
    return tables


class ColumnKeyTests(SimpleTestCase):
    def test_ascii_headers_keep_their_keys(self) -> None:
        self.assertEqual(dd.column_key("In-degree (0–1)"), "in_degree_0_1")
        self.assertEqual(dd.column_key("Level change (%)"), "level_change_pct")
        self.assertEqual(dd.column_key("Dependent→Dominant p"), "dependent_to_dominant_p")
        self.assertEqual(dd.column_key("Burt's Constraint"), "burt_s_constraint")
        self.assertEqual(dd.column_key(" Channel ID "), "channel_id")

    def test_non_ascii_letters_are_kept(self) -> None:
        self.assertEqual(dd.column_key("Label: Страна"), "label_страна")
        self.assertEqual(dd.column_key("Label: 国"), "label_国")
        self.assertEqual(dd.column_key("Label: Région"), "label_région")
        self.assertEqual(dd.column_key("Standardised β"), "standardised_β")
        # A script written with combining marks stays one word.
        self.assertNotIn("_", dd.column_key("हिंदी"))
        # None of them collapses onto the primary Label column.
        self.assertEqual(len({dd.column_key(h) for h in ("Label", "Label: Страна", "Label: 国", "Label: भाषा")}), 4)

    def test_r_squared_is_not_r(self) -> None:
        self.assertEqual(dd.column_key("R²"), "r2")
        self.assertEqual(dd.column_key("R"), "r")
        self.assertNotEqual(dd.describe_column("R²"), dd.describe_column("R"))

    def test_no_two_headers_of_a_table_share_a_key(self) -> None:
        for file, sheet, headers in _writer_tables():
            with self.subTest(file=file, sheet=sheet):
                self.assertEqual(len(set(headers)), len(headers))
                keys = [dd.column_key(h) for h in headers]
                self.assertEqual(len(set(keys)), len(keys), sorted(k for k in keys if keys.count(k) > 1))
                self.assertNotIn("", keys)


class DescriptionTests(SimpleTestCase):
    def test_a_column_is_described_where_it_stands(self) -> None:
        general = dd.COLUMNS
        cases = [
            ("Group", "network_table.xlsx", "Statistics", "family of statistics"),
            ("Group", "network_table.xlsx", "Homophily", "label group"),
            ("Statistic", "dominance.xlsx", "Hierarchy", "hierarchy"),
            ("Label", "network_table.xlsx", "Homophily by label", "label the row describes"),
            ("Label", "audience.xlsx", "Breadth labels", "label the row describes"),
            ("label", "audience_breadth.csv", "", "label the row describes"),
            ("Dependent", "dominance.xlsx", "Pairs", "Name of the dependent channel"),
            ("dependent", "dominance_pairs.csv", "", "Name of the dependent channel"),
            ("Dominant", "dominance.xlsx", "Pairs", "Name of the dominant channel"),
            ("Dependent", "network_table.xlsx", "MRQAP models", "Dependent variable"),
            ("Messages", "links.xlsx", "Channel sites", "linking to the site"),
            ("messages", "links_channel_sites.csv", "", "linking to the site"),
            ("Ratio", "robustness_table.xlsx", "Modular", "inside communities over"),
            ("Ratio", "network_table.xlsx", "Label flows", "Observed ties over expected"),
            ("Ties", "network_table.xlsx", "Label flows", "citing label"),
            ("citations", "network_label_flows.csv", "", "behind those ties"),
            ("Reciprocity", "community_table.xlsx", "Communities", "inside the community"),
            ("Reciprocity", "channel_table.xlsx", "Channels", "citation partners"),
            ("Role", "links.xlsx", "Categories", "category's role"),
            ("Role", "dominance.xlsx", "Channels", "dominant"),
            ("R", "robustness_table.xlsx", "Summary", "R-index"),
            ("R²", "network_table.xlsx", "MRQAP models", "variance"),
            ("p", "network_table.xlsx", "MRQAP coefficients", "double semi-partialling"),
            ("p", "links.xlsx", "Co-linking", "bipartite configuration model"),
            ("Scope", "event_impact.xlsx", "Effects", "whole network"),
            ("Placebo dates", "event_impact.xlsx", "Effects", "Number of placebo weeks"),
        ]
        for header, file, sheet, expected in cases:
            with self.subTest(header=header, file=file, sheet=sheet):
                self.assertIn(expected, dd.describe_column(header, file, sheet))
        # The context wins over the general entry of the same key.
        self.assertNotEqual(dd.describe_column("Group", "network_table.xlsx", "Statistics"), general["group"])
        self.assertNotEqual(dd.describe_column("Dependent", "dominance.xlsx", "Pairs"), general["dependent"])
        self.assertNotEqual(dd.describe_column("Messages", "links.xlsx", "Channel sites"), general["messages"])
        self.assertNotEqual(dd.describe_column("Ratio", "robustness_table.xlsx", "Modular"), general["ratio"])
        # Without a table, and where the key keeps its general meaning, the general entry answers.
        self.assertEqual(dd.describe_column("Messages"), general["messages"])
        self.assertEqual(dd.describe_column("Messages", "channel_table.xlsx", "Channels"), general["messages"])

    def test_a_csv_a_compared_copy_and_a_continued_sheet_read_the_same_table(self) -> None:
        described = dd.describe_column("Dependent", "dominance.xlsx", "Pairs")
        self.assertEqual(dd.describe_column("dependent", "dominance_pairs.csv"), described)
        self.assertEqual(dd.describe_column("Dependent", "dominance_2.xlsx", "Pairs"), described)
        self.assertEqual(dd.table_of("robustness_table.xlsx", "Curves (2)"), "robustness_curves")
        self.assertEqual(dd.table_of("robustness_table.xlsx", "Curves (2) ~2"), "robustness_curves")
        self.assertIn("continues", dd.describe_sheet("robustness_table.xlsx", "Curves (2)"))
        self.assertNotIn("continues", dd.describe_sheet("robustness_table.xlsx", "Curves"))
        self.assertTrue(dd.describe_sheet("network_table_2.xlsx", "Label flows"))

    def test_label_and_community_columns_are_described_by_their_prefix(self) -> None:
        for name in ("A", "B", "Group", "Страна", "Type"):
            with self.subTest(name=name):
                self.assertIn(
                    f"label group “{name}”", dd.describe_column(f"Label: {name}", "channel_table.xlsx", "Channels")
                )
                self.assertIn(f"label group “{name}”", dd.describe_column(f"Label: {name}"))
                # The CSV carries the key only: in the channel table it is still a label group's column.
                key = dd.column_key(f"Label: {name}")
                self.assertIn("label group the column is named after", dd.describe_column(key, "nodes.csv"))
        self.assertIn("“Leiden CPM (resolution=0.05)”", dd.describe_column("Community: Leiden CPM (resolution=0.05)"))
        self.assertIn("grouping method", dd.describe_column("community_leiden_cpm_resolution_0_05", "nodes.csv"))
        self.assertIn("primary label group", dd.describe_column("Label", "channel_table.xlsx", "Channels"))
        # Elsewhere the pair columns keep their own meaning.
        self.assertIn("first channel", dd.describe_column("Label A", "links.xlsx", "Co-linking"))
        self.assertIn("first label of the pair", dd.describe_column("Label A", "audience.xlsx", "Overlap labels"))

    def test_keys_of_the_other_writers_resolve(self) -> None:
        for header in ("Channel A ID", "channel_a_id", "Channel B ID", "channel_b_id", "Channel Telegram ID"):
            with self.subTest(header=header):
                self.assertTrue(dd.describe_column(header, "audience.xlsx", "Overlap pairs"))
        for header in ("Top 10% share", "Top10 share", "top10_share", "top_10_share"):
            with self.subTest(header=header):
                self.assertIn("most active 10%", dd.describe_column(header, "audience.xlsx", "Participation"))
        self.assertTrue(dd.describe_column("Subscribers", "channel_table.xlsx", "Channels"))
        for header in ("HITS hub", "HITS Hub", "Burt's constraint", "Amplification factor", "Content originality"):
            with self.subTest(header=header):
                self.assertTrue(dd.describe_column(header, "channel_table.xlsx", "Channels"))

    def test_every_header_of_the_writers_is_described(self) -> None:
        for file, sheet, headers in _writer_tables():
            for position, header in enumerate(headers):
                with self.subTest(file=file, sheet=sheet, header=header):
                    described = dd.describe_column(header, file, sheet, position=position, count=len(headers))
                    self.assertTrue(_is_a_sentence(dd.column_key(header), described), described)

    def test_every_description_is_a_real_sentence(self) -> None:
        for key, text in dd.COLUMNS.items():
            with self.subTest(key=key):
                self.assertTrue(_is_a_sentence(key, text), text)
        for table, rules in dd.TABLE_COLUMNS.items():
            for pattern, text in rules:
                with self.subTest(table=table, pattern=pattern):
                    self.assertTrue(_is_a_sentence(pattern, text), text)
        for pattern, text in dd.COLUMN_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertTrue(_is_a_sentence(pattern, text), text)
        for (workbook, sheet), text in dd.SHEETS.items():
            with self.subTest(workbook=workbook, sheet=sheet):
                self.assertTrue(_is_a_sentence("", text), text)
        for pattern, _group, text in dd.FILES:
            with self.subTest(file=pattern):
                self.assertTrue(_is_a_sentence("", dd.describe_file(pattern)), text)

    def test_every_table_and_sheet_is_declared_once(self) -> None:
        declared = {table for _file, _sheet, table in dd.TABLES}
        self.assertTrue(set(dd.TABLE_COLUMNS) <= declared, set(dd.TABLE_COLUMNS) - declared)
        self.assertEqual(len({(file, sheet) for file, sheet, _table in dd.TABLES}), len(dd.TABLES))
        for workbook, sheet in dd.SHEETS:
            if sheet != "Matrix":
                with self.subTest(workbook=workbook, sheet=sheet):
                    self.assertTrue(dd.table_of(workbook, sheet))
        for pattern, _group, _text in dd.FILES:
            if pattern.endswith(".csv"):
                with self.subTest(file=pattern):
                    self.assertTrue(dd.table_of(pattern))

    def test_matrix_sheets_are_read_by_position(self) -> None:
        group = "Political family (coarse grouping)"
        sheet = "Matrix Political family (coarse"  # the title Excel's 31 characters leave
        headers = [group, "Shop", "Total"]
        described = [dd.describe_column(h, "links.xlsx", sheet, position=i, count=3) for i, h in enumerate(headers)]
        self.assertIn("label of the row", described[0])
        self.assertIn("category", described[1])
        self.assertIn("every category together", described[2])
        # Without a position the label column is recognised by the (cut, possibly marked) title.
        for title in (sheet, "Matrix Political family (c ~2", "Matrix Nation"):
            name = group if "Political" in title else "Nation"
            with self.subTest(title=title):
                self.assertIn("label of the row", dd.describe_column(name, "links.xlsx", title))
                self.assertIn("category", dd.describe_column("Shop", "links.xlsx", title))
        # A category called like a fixed column is still a category.
        self.assertIn("category", dd.describe_column("Messages", "links.xlsx", "Matrix Nation", position=1, count=3))
        self.assertTrue(dd.describe_sheet("links.xlsx", sheet))


def _hear_warnings(case: SimpleTestCase) -> None:
    """The test settings silence logging (``logging.disable``), which ``assertLogs`` cannot bypass."""
    logging.disable(logging.NOTSET)
    case.addCleanup(logging.disable, logging.CRITICAL)


class FilesTests(SimpleTestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        _hear_warnings(self)

    def _export(self) -> None:
        for folder in ("data", "data_2", "data_coordination", "css", "js", "media"):
            os.makedirs(os.path.join(self.root, folder))
        for key in ("2023", "2024", "2025"):
            _write(self.root, f"data_{key}/channels.json", "x" * 10)
            _write(self.root, f"dyads/waves/wave_{key}.csv", "actor,11,12\n11,0,1\n12,0,0\n")
        _write(self.root, "data_coordination_2024/channels.json", "x" * 7)
        _write(self.root, "data/near_copies.csv", ",".join(exporter._NEAR_COPY_COLUMNS) + "\n")
        _write(self.root, "dyads/waves/presence.csv", "actor,2023,2024,2025\n11,1,1,1\n")
        _write(
            self.root,
            "dyads/actors.csv",
            "id,title,url,Nation,type,observed,dead_leaf,environment_depth,messages,subscribers,"
            "activity_period,is_lost,type\n",
        )
        _write(self.root, "dyads/README.md", "# Dyadic export\n")
        _write(self.root, "nodes.csv", "channel_id,channel,label,label_nation\n")
        _write(self.root, "summary.json", "{}")

    def _rows(self) -> dict[str, list[str]]:
        names = sorted(n for n in os.listdir(self.root) if os.path.isfile(os.path.join(self.root, n)))
        return dict(dd.file_groups(self.root, names))

    def test_period_folders_are_one_row(self) -> None:
        self._export()
        rows = self._rows()
        self.assertEqual(
            rows[dd.FOLDERS_GROUP],
            [
                "data/",
                "data_2/",
                "data_<period>/",
                "data_coordination/",
                "data_coordination_<period>/",
                "dyads/",
                "media/",
            ],
        )
        self.assertEqual(dd.family_members(self.root, "data_<period>/"), ["data_2023/", "data_2024/", "data_2025/"])
        self.assertEqual(dd.family_members(self.root, "data_2023/"), [])
        self.assertIn("3 folders, data_2023/ to data_2025/", dd.describe_file("data_<period>/", self.root))
        self.assertIn("1 folder, data_coordination_2024/", dd.describe_file("data_coordination_<period>/", self.root))
        # Without the export folder the row is still described; a single folder keeps its own description.
        self.assertTrue(dd.describe_file("data_<period>/").endswith("."))
        self.assertEqual(dd.describe_file("data_2024/"), dd.describe_file("data_<period>/"))
        self.assertIn("compared analysis", dd.describe_file("data_2/"))
        # The row's size is its folders' together, as the landing page asks for it.
        self.assertEqual(dd.folder_size(os.path.join(self.root, "data_<period>/")), 30)
        self.assertEqual(dd.folder_size(os.path.join(self.root, "data_2023/")), 10)
        self.assertEqual(dd.anchor("data_<period>/"), "file-data-period")

    def test_tables_inside_folders_are_listed_and_described(self) -> None:
        self._export()
        rows = self._rows()
        self.assertIn("data/near_copies.csv", rows[dd.CSV_GROUP])
        self.assertIn("dyads/actors.csv", rows[dd.CSV_GROUP])
        self.assertIn("dyads/waves/wave_<period>.csv", rows[dd.CSV_GROUP])
        self.assertNotIn("dyads/waves/wave_2023.csv", rows[dd.CSV_GROUP])
        self.assertNotIn("data/image_copies.csv", rows[dd.CSV_GROUP])  # not written by this export
        self.assertIn("dyads/README.md", rows[dd.METHODS_GROUP])
        self.assertTrue(dd.has_columns(self.root, "dyads/waves/wave_<period>.csv"))
        self.assertFalse(dd.has_columns(self.root, "dyads/README.md"))
        self.assertIn(
            "3 files, wave_2023.csv to wave_2025.csv", dd.describe_file("dyads/waves/wave_<period>.csv", self.root)
        )
        entries = {e["name"]: e for e in dd.dictionary(self.root, ["nodes.csv", "summary.json"])}
        # A matrix lists its first column, then one line for its per-channel (or per-period) columns.
        self.assertEqual(
            [h for h, _m in entries["dyads/waves/wave_<period>.csv"]["sheets"][0]["columns"]], ["actor", "<channel id>"]
        )
        self.assertEqual(
            [h for h, _m in entries["dyads/waves/presence.csv"]["sheets"][0]["columns"]], ["actor", "<period>"]
        )
        # dyads/actors.csv is read by position: a label group called "type" is not the channel type.
        actors = entries["dyads/actors.csv"]["sheets"][0]["columns"]
        self.assertEqual([h for h, _m in actors][3:5], ["Nation", "type"])
        self.assertIn("label group", actors[3][1])
        self.assertIn("label group", actors[4][1])
        self.assertIn("Telegram type", actors[-1][1])
        for entry in entries.values():
            for sheet in entry["sheets"]:
                for header, meaning in sheet["columns"]:
                    with self.subTest(file=entry["name"], header=header):
                        self.assertTrue(meaning)

    def test_an_unreadable_table_is_noted_not_raised(self) -> None:
        _write(self.root, "channel_table.xlsx", "not a workbook")
        with open(os.path.join(self.root, "nodes.csv"), "wb") as f:
            f.write(b"\xff\xfe\x00broken\x00,\x80\n")
        _write(self.root, "edges.csv", "")
        with self.assertLogs("network.data_dictionary", level="WARNING"):
            self.assertEqual(dd.columns_of(self.root, "channel_table.xlsx"), [])
        with self.assertLogs("network.data_dictionary", level="WARNING"):
            self.assertEqual(dd.columns_of(self.root, "nodes.csv"), [])
        self.assertEqual(dd.columns_of(self.root, "edges.csv"), [("", [])])  # an empty file is not an error
        with self.assertLogs("network.data_dictionary", level="WARNING"):
            entries = {e["name"]: e for e in dd.dictionary(self.root, ["channel_table.xlsx", "edges.csv", "nodes.csv"])}
        for name in ("channel_table.xlsx", "nodes.csv"):
            self.assertEqual(entries[name]["sheets"], [])
            self.assertTrue(entries[name]["description"].endswith(dd.UNREADABLE_NOTE))
        self.assertNotIn(dd.UNREADABLE_NOTE, entries["edges.csv"]["description"])
        self.assertIn("could not be read", dd._markdown(list(entries.values()), "Demo"))

    def test_markdown_cells_are_escaped(self) -> None:
        header = "Label: a|b `c` <script>"
        _write(self.root, "nodes.csv", "")
        with open(os.path.join(self.root, "nodes.csv"), "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["channel_id", header, "plain"])
        text = dd._markdown(dd.dictionary(self.root, ["nodes.csv"]), "Title | with `code` <b>")
        rows = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line]
        self.assertEqual(len(rows), 4)  # the table's own header row and three columns
        for row in rows:
            with self.subTest(row=row):
                self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 3)  # two cells, whatever the header holds
        self.assertIn("| `` Label: a\\|b `c` <script> `` |", text)
        self.assertIn("label group “a\\|b \\`c\\` \\<script>”", text)
        self.assertIn("# Data dictionary — Title \\| with \\`code\\` \\<b>", text)


class WriteTests(TestCase):
    """``write`` renders the page, which reads the label groups' names: it needs the database."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        _hear_warnings(self)

    def test_page_is_escaped_keeps_the_export_date_and_survives_a_broken_file(self) -> None:
        with open(os.path.join(self.root, "nodes.csv"), "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["channel_id", "Label: <b>x</b>", "<script>alert(1)</script>"])
        _write(self.root, "audience.xlsx", "not a workbook")
        workbook = openpyxl.Workbook()
        workbook.active.title = "Matrix <Nation>"
        workbook.active.append(["<i>Nation</i>", "<u>Shop</u>", "Total"])
        workbook.save(os.path.join(self.root, "links.xlsx"))
        os.makedirs(os.path.join(self.root, "data_2024"))
        _write(self.root, "summary.json", '{"created_at": "2001-02-03T04:05:06", "pulpit_version": "0.1"}')
        with self.assertLogs("network.data_dictionary", level="WARNING"):
            dd.write(self.root, project_title="<em>Demo</em> & co")
        with open(os.path.join(self.root, dd.DATA_PAGE), encoding="utf-8") as f:
            page = f.read()
        for raw in (
            "<b>x</b>",
            "<script>alert(1)</script>",
            "<i>Nation</i>",
            "<u>Shop</u>",
            "<em>Demo</em>",
            "data_<period>/",
        ):
            with self.subTest(raw=raw):
                self.assertNotIn(raw, page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("data_&lt;period&gt;/", page)
        self.assertIn('id="file-data-period"', page)
        self.assertIn("could not be read", page)
        self.assertIn("2001-02-03", page)  # the export's own date, not today's
        with open(os.path.join(self.root, dd.DATA_MD), encoding="utf-8") as f:
            first = f.read()
        self.assertIn("### `data_<period>/`", first)
        self.assertNotIn(f"### `{dd.DATA_MD}`", first)
        with self.assertLogs("network.data_dictionary", level="WARNING"):
            dd.write(self.root, project_title="<em>Demo</em> & co")
        with open(os.path.join(self.root, dd.DATA_MD), encoding="utf-8") as f:
            self.assertEqual(f.read(), first)  # writing it again changes nothing
