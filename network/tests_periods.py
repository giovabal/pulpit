"""Tests of the timeline periods (network.periods) and of a quarter-timeline export."""

import datetime
import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from network.periods import build_periods, overlapping, period_of, step_key, validate
from webapp.models import Message
from webapp.test_helpers import make_channel, make_label

D = datetime.date


class BuildPeriodsTests(TestCase):
    def test_years_match_the_calendar_years(self) -> None:
        periods = build_periods("year", None, D(2023, 2, 10), D(2025, 6, 1))
        self.assertEqual([p.key for p in periods], ["2023", "2024", "2025"])
        self.assertEqual((periods[0].start, periods[0].end), (D(2023, 1, 1), D(2023, 12, 31)))
        self.assertEqual([p.index for p in periods], [0, 1, 2])

    def test_quarters_and_months(self) -> None:
        quarters = build_periods("quarter", None, D(2024, 2, 1), D(2024, 11, 30))
        self.assertEqual([p.key for p in quarters], ["2024Q1", "2024Q2", "2024Q3", "2024Q4"])
        self.assertEqual(
            (quarters[1].label, quarters[1].start, quarters[1].end), ("2024 Q2", D(2024, 4, 1), D(2024, 6, 30))
        )
        months = build_periods("month", None, D(2024, 1, 31), D(2024, 3, 1))
        self.assertEqual(
            [(p.key, p.label) for p in months],
            [("2024-01", "Jan 2024"), ("2024-02", "Feb 2024"), ("2024-03", "Mar 2024")],
        )
        self.assertEqual(months[1].end, D(2024, 2, 29))  # leap year
        self.assertEqual(sorted(p.key for p in months), [p.key for p in months])  # keys sort in time order

    def test_sliding_windows_keep_only_full_windows(self) -> None:
        windows = build_periods("quarter", 12, D(2023, 2, 1), D(2024, 8, 1))
        # Windows ending 2023Q4, 2024Q1, 2024Q2, 2024Q3 start on/after 2023-01-01; earlier ones would reach back.
        self.assertEqual([p.key for p in windows], ["2023Q4", "2024Q1", "2024Q2", "2024Q3"])
        self.assertEqual((windows[1].start, windows[1].end), (D(2023, 4, 1), D(2024, 3, 31)))
        self.assertEqual(windows[1].label, "Apr 2023 – Mar 2024")
        self.assertTrue(overlapping("quarter", 12))
        self.assertFalse(overlapping("quarter", None))

    def test_clamped_to_the_run_window(self) -> None:
        periods = build_periods(
            "year", None, D(2023, 1, 1), D(2024, 12, 31), clamp_start=D(2023, 6, 1), clamp_end=D(2024, 3, 1)
        )
        self.assertEqual(
            [(p.start, p.end) for p in periods], [(D(2023, 6, 1), D(2023, 12, 31)), (D(2024, 1, 1), D(2024, 3, 1))]
        )

    def test_window_must_be_a_multiple_of_the_step(self) -> None:
        with self.assertRaises(ValueError):
            validate("quarter", 5)
        with self.assertRaises(ValueError):
            validate("month", 1)  # no longer than the step: not a sliding window
        with self.assertRaises(ValueError):
            validate("week", None)
        validate("month", 3)

    def test_period_of_and_step_key(self) -> None:
        quarters = build_periods("quarter", None, D(2024, 1, 1), D(2024, 12, 31))
        self.assertEqual(period_of(quarters, D(2024, 5, 5)).key, "2024Q2")
        self.assertIsNone(period_of(quarters, D(2025, 1, 1)))
        self.assertEqual(step_key(D(2024, 12, 31), "month"), "2024-12")


class QuarterTimelineCommandTests(TestCase):
    def setUp(self) -> None:
        label = make_label("Org1", color="#FF0000")
        self.channels = [make_channel(telegram_id=i, label=label, title=f"C{i}") for i in range(1, 5)]
        telegram_id = 100
        for month in (2, 5, 8):  # three quarters of 2024
            for src, dst in [(0, 1), (1, 0), (2, 3), (3, 2), (0, 2)]:
                telegram_id += 1
                Message.objects.create(
                    telegram_id=telegram_id,
                    channel=self.channels[dst],
                    forwarded_from=self.channels[src],
                    date=datetime.datetime(2024, month, 10, tzinfo=datetime.UTC),
                )
        for channel in self.channels:
            channel.save()

    def _run(self, *extra: str, **kwargs) -> tuple[Path, str]:
        out = io.StringIO()
        tmpdir = tempfile.mkdtemp()
        with override_settings(BASE_DIR=Path(tmpdir)):
            call_command("structural_analysis", *extra, name="periods-e2e", stdout=out, stderr=io.StringIO(), **kwargs)
        return Path(tmpdir) / "exports" / "periods-e2e", out.getvalue()

    def test_quarter_timeline_writes_period_dirs_and_timeline(self) -> None:
        export, _out = self._run(
            "--timeline-step",
            "quarter",
            "--community-strategies",
            "LEIDEN,LEIDEN_TEMPORAL",
            "--html",
            "--measures",
            "PAGERANK",
        )
        timeline = json.loads((export / "data" / "timeline.json").read_text())
        self.assertEqual(timeline["step"], "quarter")
        self.assertFalse(timeline["overlapping"])
        keys = [p["key"] for p in timeline["periods"]]
        self.assertEqual(keys, ["2024Q1", "2024Q2", "2024Q3"])
        self.assertEqual(timeline["periods"][0]["label"], "2024 Q1")
        for key in keys:
            self.assertTrue((export / f"data_{key}" / "channels.json").is_file(), key)
        parameters = (export / "PARAMETERS.md").read_text(encoding="utf-8")
        self.assertIn("| Timeline step | `quarter` |", parameters)

    def test_sliding_window_refuses_temporal_leiden(self) -> None:
        with self.assertRaisesRegex(CommandError, "disjoint periods"):
            self._run("--timeline-step", "month", "--timeline-window", "3", "--community-strategies", "LEIDEN_TEMPORAL")

    def test_window_needs_a_step(self) -> None:
        with self.assertRaisesRegex(CommandError, "needs --timeline-step"):
            self._run("--timeline-window", "12", "--measures", "PAGERANK")

    def test_sliding_window_export_marks_overlap(self) -> None:
        export, _out = self._run(
            "--timeline-step", "month", "--timeline-window", "3", "--html", "--measures", "PAGERANK"
        )
        timeline = json.loads((export / "data" / "timeline.json").read_text())
        self.assertTrue(timeline["overlapping"])
        self.assertEqual(timeline["window_months"], 3)
        # The first full 3-month window starts with the data's first month (Feb 2024) and ends in April.
        self.assertEqual(timeline["periods"][0]["key"], "2024-04")
        self.assertEqual(timeline["periods"][0]["start"], "2024-02-01")
