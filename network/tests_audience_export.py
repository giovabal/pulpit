"""The Audience sections in a ``structural_analysis`` export (network/audience_layer.py)."""

import csv
import datetime
import io
import itertools
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from network import audience_layer
from network.graph_builder import build_graph
from webapp import audience
from webapp.models import Message, MessageReply
from webapp.test_helpers import make_channel, make_label

import openpyxl

# Distinctive commenter ids: none of them may appear in the export.
_SENDERS = (987_654_321, 987_654_322, 987_654_323)


def _day(day: int, month: int = 5) -> datetime.datetime:
    return datetime.datetime(2024, month, day, 12, 0, tzinfo=datetime.timezone.utc)


class AudienceExportTests(TestCase):
    """In-target A and B (A forwards B, both with comments); out-of-target C, forwarded by A — a dead leaf
    whose comments never count."""

    def setUp(self) -> None:
        org = make_label("Org", color="#FF0000")
        self.a = make_channel(telegram_id=1, label=org, title="A", linked_chat_id=11)
        self.b = make_channel(telegram_id=2, label=org, title="B", linked_chat_id=12)
        self.c = make_channel(telegram_id=3, title="C", label=make_label("Other", is_in_target=False), in_degree=1)
        self.post_a = Message.objects.create(telegram_id=1, channel=self.a, date=_day(1), forwarded_from=self.b)
        self.post_b = Message.objects.create(telegram_id=1, channel=self.b, date=_day(2))
        self.late_b = Message.objects.create(telegram_id=2, channel=self.b, date=_day(2, month=9))
        Message.objects.create(telegram_id=2, channel=self.a, date=_day(3), forwarded_from=self.c)
        # A September citation, so the third quarter has a graph (a period without a tie is not exported).
        Message.objects.create(telegram_id=3, channel=self.a, date=_day(5, month=9), forwarded_from=self.b)
        self.post_c = Message.objects.create(telegram_id=1, channel=self.c, date=_day(4))
        self._ids = itertools.count(1)

    def reply(self, post: Message, sender_id: int, n: int = 1) -> None:
        MessageReply.objects.bulk_create(
            MessageReply(
                parent_message=post, telegram_id=next(self._ids), date=post.date, text="hi", sender_id=sender_id
            )
            for _ in range(n)
        )

    def _comments(self) -> None:
        self.reply(self.post_a, _SENDERS[0], n=3)
        self.reply(self.post_b, _SENDERS[0])
        self.reply(self.post_b, _SENDERS[1])
        self.reply(self.late_b, _SENDERS[2], n=2)
        self.reply(self.post_c, _SENDERS[2], n=5)  # dead leaf: out of scope

    def _run(self, *extra: str) -> Path:
        tmpdir = tempfile.mkdtemp()
        with override_settings(BASE_DIR=Path(tmpdir)):
            call_command("structural_analysis", *extra, name="aud", stdout=io.StringIO(), stderr=io.StringIO())
        return Path(tmpdir) / "exports" / "aud"

    def test_observed_channels_leave_out_dead_leaves(self) -> None:
        graph = build_graph(draw_dead_leaves=True)[0]
        self.assertIn(str(self.c.pk), graph)
        self.assertEqual(audience_layer.observed_channel_ids(graph), frozenset({self.a.pk, self.b.pk}))

    def test_export_writes_every_audience_output(self) -> None:
        self._comments()
        export = self._run("--html", "--xlsx", "--csv")
        for name in ("data/audience.json", "audience.html", "audience.xlsx", "audience_participation.csv"):
            self.assertTrue((export / name).exists(), name)
        for stem in audience_layer.CSV_STEMS.values():
            self.assertTrue((export / f"audience_{stem}.csv").exists(), stem)
        payload = json.loads((export / "data" / "audience.json").read_text())
        overall = payload["participation"]["overall"]
        self.assertEqual((overall["accounts"], overall["replies"]), (3, 7))
        self.assertEqual(payload["coverage"]["scope_channels"], 2)
        self.assertEqual({row["channel"]["label"] for row in payload["participation"]["channels"]}, {"A", "B"})
        self.assertEqual(payload["participation"]["channels"][0]["channel"]["organization"], "Org")
        # Same figures as the page's own computation over the same channels.
        page = audience.participation(audience.Scope(channel_ids=frozenset({self.a.pk, self.b.pk})))
        self.assertEqual(overall["gini"], page["overall"]["gini"])

        text = (export / "data" / "audience.json").read_text()
        for sender in _SENDERS:
            self.assertNotIn(str(sender), text)
        with open(export / "audience_participation.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][0], "channel_id")
        self.assertEqual(len(rows), 3)
        wb = openpyxl.load_workbook(export / "audience.xlsx")
        self.assertIn("Summary", wb.sheetnames)
        self.assertIn("Overlap pairs", wb.sheetnames)
        summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(min_row=2, values_only=True)}
        self.assertEqual(summary["Commenters"], 3)

        self.assertIn("audience.html", (export / "index.html").read_text())
        parameters = (export / "PARAMETERS.md").read_text()
        self.assertIn("### Audience", parameters)
        self.assertIn("BULK_THREAD_COMMENTS", parameters)
        self.assertTrue(json.loads((export / "summary.json").read_text())["options"]["audience"])

    def test_export_dates_bound_the_posts(self) -> None:
        self._comments()
        export = self._run("--html", "--enddate", "2024-06-30")
        payload = json.loads((export / "data" / "audience.json").read_text())
        self.assertEqual(payload["participation"]["overall"]["replies"], 5)  # the September replies are out
        self.assertEqual(payload["end_date"], "2024-06-30")

    def test_timeline_periods_get_their_own_audience(self) -> None:
        self._comments()
        export = self._run("--html", "--xlsx", "--timeline-step", "quarter")
        timeline = json.loads((export / "data" / "timeline.json").read_text())
        flags = {p["key"]: p["has_audience"] for p in timeline["periods"]}
        self.assertEqual(flags, {"2024Q2": True, "2024Q3": True})
        q2 = json.loads((export / "data_2024Q2" / "audience.json").read_text())
        q3 = json.loads((export / "data_2024Q3" / "audience.json").read_text())
        self.assertEqual(q2["participation"]["overall"]["replies"], 5)  # the May posts
        self.assertEqual(q3["participation"]["overall"]["replies"], 2)  # the September post
        self.assertEqual((q3["start_date"], q3["end_date"]), ("2024-07-01", "2024-09-30"))
        wb = openpyxl.load_workbook(export / "audience.xlsx")
        self.assertEqual([c.value for c in wb["Summary"][1]], ["Figure", "All", "2024Q2", "2024Q3"])
        replies = next(row for row in wb["Summary"].iter_rows(min_row=2, values_only=True) if row[0] == "Replies")
        self.assertEqual(replies[1:], (7, 5, 2))
        for name in ("Participation All", "Participation 2024Q2", "Overlap pairs 2024Q3"):
            self.assertIn(name, wb.sheetnames)

    def test_a_period_without_replies_has_no_audience(self) -> None:
        self.reply(self.post_a, _SENDERS[0], n=2)  # May only
        export = self._run("--html", "--timeline-step", "quarter")
        flags = {
            p["key"]: p["has_audience"] for p in json.loads((export / "data" / "timeline.json").read_text())["periods"]
        }
        self.assertEqual(flags, {"2024Q2": True, "2024Q3": False})
        self.assertFalse((export / "data_2024Q3" / "audience.json").exists())

    def test_no_audience_skips_it(self) -> None:
        self._comments()
        export = self._run("--html", "--no-audience")
        self.assertFalse((export / "data" / "audience.json").exists())
        self.assertFalse((export / "audience.html").exists())
        self.assertNotIn("audience.html", (export / "index.html").read_text())
        self.assertFalse(json.loads((export / "summary.json").read_text())["options"]["audience"])

    def test_without_replies_nothing_is_written(self) -> None:
        export = self._run("--html")
        self.assertFalse((export / "data" / "audience.json").exists())
        self.assertNotIn("audience.html", (export / "index.html").read_text())
        self.assertIn("skipped, no reply in scope", (export / "PARAMETERS.md").read_text())
