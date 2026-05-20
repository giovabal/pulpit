"""Tests for runner: task state machine, log parsing, launch/abort guards, views, and _build_args."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from runner.views import _build_args
from webapp.models import ChannelGroup, SearchTerm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_meta(tmp_dir: Path, task: str, **kwargs) -> None:
    defaults = {"start_time": "2026-01-01T00:00:00+00:00", "end_time": None, "args": [], "pid": None, "exit_code": None}
    (tmp_dir / f"runner_{task}.meta.json").write_text(json.dumps({**defaults, **kwargs}))


class _TmpMixin:
    """Redirect runner._TMP_DIR to a throwaway directory for each test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._td.name)
        self._patcher = patch("runner.tasks._TMP_DIR", new=self.tmp_dir)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._td.cleanup()


class FakePost(dict):
    """Minimal POST-data stand-in: dict with a getlist() method."""

    def getlist(self, key):
        v = self.get(key, [])
        return v if isinstance(v, list) else [v]


# ---------------------------------------------------------------------------
# runner/tasks.py — get_status
# ---------------------------------------------------------------------------


class GetStatusIdleTests(_TmpMixin, TestCase):
    def test_no_meta_file_returns_idle(self):
        from runner.tasks import get_status

        s = get_status("crawl_channels")
        self.assertEqual(s["status"], "idle")
        self.assertIsNone(s["pid"])
        self.assertIsNone(s["exit_code"])
        self.assertEqual(s["args"], [])

    def test_corrupt_meta_returns_idle(self):
        from runner.tasks import get_status

        (self.tmp_dir / "runner_crawl_channels.meta.json").write_text("NOT JSON{")
        self.assertEqual(get_status("crawl_channels")["status"], "idle")


class GetStatusTerminalTests(_TmpMixin, TestCase):
    def test_exit_zero_is_done(self):
        from runner.tasks import get_status

        _write_meta(self.tmp_dir, "structural_analysis", pid=1, exit_code=0, end_time="2026-01-01T01:00:00+00:00")
        s = get_status("structural_analysis")
        self.assertEqual(s["status"], "done")
        self.assertEqual(s["exit_code"], 0)

    def test_nonzero_exit_is_failed(self):
        from runner.tasks import get_status

        _write_meta(self.tmp_dir, "structural_analysis", pid=1, exit_code=2)
        self.assertEqual(get_status("structural_analysis")["status"], "failed")

    def test_returns_stored_args(self):
        from runner.tasks import get_status

        _write_meta(self.tmp_dir, "search_channels", exit_code=0, args=["--amount", "5"])
        self.assertEqual(get_status("search_channels")["args"], ["--amount", "5"])


class GetStatusRunningTests(_TmpMixin, TestCase):
    def test_live_pid_no_exit_code_is_running(self):
        import os

        from runner.tasks import get_status

        _write_meta(self.tmp_dir, "crawl_channels", pid=os.getpid())
        self.assertEqual(get_status("crawl_channels")["status"], "running")

    def test_dead_pid_no_exit_code_is_failed(self):
        from runner.tasks import get_status

        _write_meta(self.tmp_dir, "crawl_channels", pid=99999)
        with patch("runner.tasks._is_running", return_value=False):
            self.assertEqual(get_status("crawl_channels")["status"], "failed")


# ---------------------------------------------------------------------------
# runner/tasks.py — get_log_lines
# ---------------------------------------------------------------------------


class GetLogLinesTests(_TmpMixin, TestCase):
    def _write_log(self, task: str, content: bytes) -> None:
        (self.tmp_dir / f"runner_{task}.log").write_bytes(content)

    def test_no_file_returns_empty(self):
        from runner.tasks import get_log_lines

        lines, offset = get_log_lines("crawl_channels")
        self.assertEqual(lines, [])
        self.assertEqual(offset, 0)

    def test_plain_lines_returned(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"line one\nline two\nline three\n")
        lines, offset = get_log_lines("structural_analysis")
        self.assertEqual(lines, ["line one", "line two", "line three"])
        self.assertGreater(offset, 0)

    def test_ansi_escapes_stripped(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"\x1b[32mGreen text\x1b[0m\n")
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(lines, ["Green text"])

    def test_carriage_return_keeps_last_segment(self):
        from runner.tasks import get_log_lines

        # Progress-bar style: earlier content overwritten by CR; only final segment shown.
        self._write_log("structural_analysis", b"loading\rprogress 50%\rprogress 100%\n")
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(lines, ["progress 100%"])

    def test_python_warning_lines_dropped(self):
        from runner.tasks import get_log_lines

        content = b"/home/user/app.py:42: DeprecationWarning: old api\n  old_function()\nnormal output\n"
        self._write_log("structural_analysis", content)
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(lines, ["normal output"])

    def test_offset_resumes_from_byte_position(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"first\nsecond\n")
        _, offset = get_log_lines("structural_analysis")
        self._write_log("structural_analysis", b"first\nsecond\nthird\n")
        lines, _ = get_log_lines("structural_analysis", offset)
        self.assertEqual(lines, ["third"])

    def test_empty_file_returns_empty_list(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"")
        lines, offset = get_log_lines("structural_analysis")
        self.assertEqual(lines, [])


# ---------------------------------------------------------------------------
# runner/tasks.py — launch / abort guards
# ---------------------------------------------------------------------------


class LaunchGuardsTests(_TmpMixin, TestCase):
    def test_unknown_task_raises_value_error(self):
        from runner.tasks import launch

        with self.assertRaises(ValueError):
            launch("no_such_command", [])

    def test_already_running_raises_runtime_error(self):
        import os

        from runner.tasks import launch

        _write_meta(self.tmp_dir, "crawl_channels", pid=os.getpid())
        with self.assertRaises(RuntimeError):
            launch("crawl_channels", [])

    def test_launch_writes_meta_with_pid(self):
        from runner.tasks import launch

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("runner.tasks.subprocess.Popen", return_value=mock_proc):
            launch("search_channels", ["--amount", "5"])
        meta = json.loads((self.tmp_dir / "runner_search_channels.meta.json").read_text())
        self.assertEqual(meta["pid"], 12345)
        self.assertEqual(meta["args"], ["--amount", "5"])
        self.assertIsNone(meta["exit_code"])


class AbortGuardsTests(_TmpMixin, TestCase):
    def test_unknown_task_returns_false(self):
        from runner.tasks import abort

        self.assertFalse(abort("no_such_command"))

    def test_not_running_task_returns_false(self):
        from runner.tasks import abort

        _write_meta(self.tmp_dir, "structural_analysis", exit_code=0)
        self.assertFalse(abort("structural_analysis"))

    def test_running_task_sends_sigterm(self):
        import os
        import signal

        from runner.tasks import abort

        _write_meta(self.tmp_dir, "crawl_channels", pid=os.getpid())
        with patch("runner.tasks.os.kill") as mock_kill:
            result = abort("crawl_channels")
        self.assertTrue(result)
        # os.kill is also called with signal 0 inside _is_running; assert SIGTERM was sent.
        mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)

    def test_process_already_gone_returns_false(self):
        import os

        from runner.tasks import abort

        _write_meta(self.tmp_dir, "crawl_channels", pid=os.getpid())
        with patch("runner.tasks.os.kill", side_effect=ProcessLookupError):
            self.assertFalse(abort("crawl_channels"))


# ---------------------------------------------------------------------------
# runner/views.py — OperationsView
# ---------------------------------------------------------------------------


class OperationsViewTests(TestCase):
    def test_get_returns_200(self):
        resp = self.client.get(reverse("operations"))
        self.assertEqual(resp.status_code, 200)

    def test_context_contains_all_four_tasks(self):
        resp = self.client.get(reverse("operations"))
        names = [t["name"] for t in resp.context["tasks"]]
        self.assertIn("search_channels", names)
        self.assertIn("crawl_channels", names)
        self.assertIn("structural_analysis", names)
        self.assertIn("compare_analysis", names)

    def test_tasks_in_workflow_order(self):
        resp = self.client.get(reverse("operations"))
        names = [t["name"] for t in resp.context["tasks"]]
        self.assertLess(names.index("search_channels"), names.index("crawl_channels"))
        self.assertLess(names.index("crawl_channels"), names.index("structural_analysis"))
        self.assertLess(names.index("structural_analysis"), names.index("compare_analysis"))

    def test_context_contains_channel_groups(self):
        ChannelGroup.objects.create(name="Alpha")
        resp = self.client.get(reverse("operations"))
        keys = [g["key"] for g in resp.context["channel_groups"]]
        self.assertIn("alpha", keys)


# ---------------------------------------------------------------------------
# runner/views.py — RunTaskView
# ---------------------------------------------------------------------------


class RunTaskViewTests(TestCase):
    def test_unknown_task_returns_404(self):
        resp = self.client.post(reverse("operations-run", args=["no_such_task"]))
        self.assertEqual(resp.status_code, 404)

    def test_already_running_returns_409(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "running"}):
            resp = self.client.post(reverse("operations-run", args=["structural_analysis"]))
        self.assertEqual(resp.status_code, 409)

    def test_launch_error_returns_500(self):
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch", side_effect=RuntimeError("boom")),
        ):
            resp = self.client.post(reverse("operations-run", args=["structural_analysis"]))
        self.assertEqual(resp.status_code, 500)

    def test_successful_launch_returns_started(self):
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch"),
        ):
            resp = self.client.post(reverse("operations-run", args=["structural_analysis"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "started")

    def test_save_terms_creates_search_terms(self):
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch"),
        ):
            self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"save_terms": "1", "extra_terms": "term one\nterm two"},
            )
        words = set(SearchTerm.objects.values_list("word", flat=True))
        self.assertIn("term one", words)
        self.assertIn("term two", words)

    def test_save_terms_lowercases_and_deduplicates(self):
        SearchTerm.objects.create(word="term one")
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch"),
        ):
            self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"save_terms": "1", "extra_terms": "TERM ONE\n  Term Two  "},
            )
        self.assertEqual(SearchTerm.objects.filter(word="term one").count(), 1)


# ---------------------------------------------------------------------------
# runner/views.py — AbortTaskView
# ---------------------------------------------------------------------------


class AbortTaskViewTests(TestCase):
    def test_unknown_task_returns_404(self):
        resp = self.client.post(reverse("operations-abort", args=["no_such_task"]))
        self.assertEqual(resp.status_code, 404)

    def test_abort_not_running_returns_sent_false(self):
        with patch("runner.views.tasks.abort", return_value=False):
            resp = self.client.post(reverse("operations-abort", args=["structural_analysis"]))
        self.assertFalse(resp.json()["sent"])

    def test_abort_running_returns_sent_true(self):
        with patch("runner.views.tasks.abort", return_value=True):
            resp = self.client.post(reverse("operations-abort", args=["structural_analysis"]))
        self.assertTrue(resp.json()["sent"])


# ---------------------------------------------------------------------------
# runner/views.py — TaskStatusView
# ---------------------------------------------------------------------------


class TaskStatusViewTests(TestCase):
    def test_unknown_task_returns_404(self):
        resp = self.client.get(reverse("operations-status", args=["no_such_task"]))
        self.assertEqual(resp.status_code, 404)

    def test_response_includes_lines_and_offset(self):
        with (
            patch(
                "runner.views.tasks.get_status",
                return_value={
                    "status": "idle",
                    "start_time": None,
                    "end_time": None,
                    "args": [],
                    "exit_code": None,
                    "pid": None,
                },
            ),
            patch("runner.views.tasks.get_log_lines", return_value=(["hello"], 5)),
        ):
            resp = self.client.get(reverse("operations-status", args=["structural_analysis"]))
        data = resp.json()
        self.assertEqual(data["lines"], ["hello"])
        self.assertEqual(data["next_offset"], 5)
        self.assertEqual(data["status"], "idle")

    def test_offset_param_forwarded(self):
        with (
            patch(
                "runner.views.tasks.get_status",
                return_value={
                    "status": "idle",
                    "start_time": None,
                    "end_time": None,
                    "args": [],
                    "exit_code": None,
                    "pid": None,
                },
            ),
            patch("runner.views.tasks.get_log_lines", return_value=([], 20)) as mock_log,
        ):
            self.client.get(reverse("operations-status", args=["structural_analysis"]) + "?offset=20")
        mock_log.assert_called_once_with("structural_analysis", 20)


# ---------------------------------------------------------------------------
# runner/views.py — ExportsListView / ExportDetailView
# ---------------------------------------------------------------------------


class ExportsListViewTests(TestCase):
    def test_empty_exports_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-exports"))
        self.assertEqual(resp.json()["exports"], [])

    def test_export_with_summary_json_appears_in_list(self):
        with tempfile.TemporaryDirectory() as td:
            exp = Path(td) / "exports" / "myexport"
            exp.mkdir(parents=True)
            (exp / "summary.json").write_text(
                json.dumps({"created_at": "2026-01-01T00:00:00", "nodes": 42, "edges": 100})
            )
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-exports"))
        exports = resp.json()["exports"]
        self.assertEqual(len(exports), 1)
        self.assertEqual(exports[0]["name"], "myexport")
        self.assertEqual(exports[0]["nodes"], 42)

    def test_export_without_summary_json_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "exports" / "nosummary").mkdir(parents=True)
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-exports"))
        self.assertEqual(resp.json()["exports"], [])

    def test_export_with_bad_json_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            exp = Path(td) / "exports" / "bad"
            exp.mkdir(parents=True)
            (exp / "summary.json").write_text("not json")
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-exports"))
        self.assertEqual(resp.json()["exports"], [])

    def test_exports_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            for name, ts in [("alpha", "2026-01-01T00:00:00"), ("beta", "2026-06-01T00:00:00")]:
                p = Path(td) / "exports" / name
                p.mkdir(parents=True)
                (p / "summary.json").write_text(json.dumps({"created_at": ts}))
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-exports"))
        names = [e["name"] for e in resp.json()["exports"]]
        self.assertEqual(names, ["beta", "alpha"])


class ExportDetailViewTests(TestCase):
    def test_missing_export_returns_404(self):
        with tempfile.TemporaryDirectory() as td:
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-export-detail", args=["nonexistent"]))
        self.assertEqual(resp.status_code, 404)

    def test_bad_json_returns_500(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "exports" / "broken"
            p.mkdir(parents=True)
            (p / "summary.json").write_text("bad json")
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-export-detail", args=["broken"]))
        self.assertEqual(resp.status_code, 500)

    def test_valid_export_returns_summary(self):
        payload = {"nodes": 10, "edges": 20, "measures": "PAGERANK"}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "exports" / "good"
            p.mkdir(parents=True)
            (p / "summary.json").write_text(json.dumps(payload))
            with override_settings(BASE_DIR=Path(td)):
                resp = self.client.get(reverse("operations-export-detail", args=["good"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["nodes"], 10)


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: crawl_channels
# ---------------------------------------------------------------------------


class BuildArgsGetChannelsTests(TestCase):
    def test_empty_post_only_emits_explicit_bool_defaults(self):
        # Every crawl_channels toggle is a bool_explicit spec so an unchecked
        # Operations-panel checkbox emits the --no-<flag> form. An empty POST
        # therefore yields the --no- form of every toggle (and nothing else).
        self.assertEqual(
            _build_args("crawl_channels", FakePost()),
            [
                "--no-get-channels-info",
                "--no-update-type-excluded-info",
                "--no-mine-about-texts",
                "--no-fetch-recommended-channels",
                "--no-retry-lost-and-private",
                "--no-get-new-messages",
                "--no-fetch-replies",
                "--no-refresh-messages-stats",
                "--no-fixholes",
                "--no-fix-missing-media",
                "--no-retry-lost-messages",
                "--no-retry-references",
                "--no-force-retry-unresolved-references",
                "--no-download-images",
                "--no-download-video",
                "--no-download-audio",
                "--no-download-stickers",
                "--no-download-other-media",
                "--no-in-degrees",
                "--no-out-degrees",
            ],
        )

    def test_each_boolean_flag_mapped(self):
        flags = {
            "get_new_messages": "--get-new-messages",
            "fix_holes": "--fixholes",
            "fetch_recommended_channels": "--fetch-recommended-channels",
            "retry_references": "--retry-references",
            "force_retry_unresolved_references": "--force-retry-unresolved-references",
            "mine_about_texts": "--mine-about-texts",
            "in_degrees": "--in-degrees",
            "out_degrees": "--out-degrees",
            "fix_missing_media": "--fix-missing-media",
            "update_type_excluded_info": "--update-type-excluded-info",
        }
        for field, expected_flag in flags.items():
            with self.subTest(field=field):
                args = _build_args("crawl_channels", FakePost({field: "1"}))
                self.assertIn(expected_flag, args)

    def test_do_refresh_without_value(self):
        args = _build_args("crawl_channels", FakePost({"do_refresh": "1", "refresh_value": ""}))
        self.assertIn("--refresh-messages-stats", args)
        self.assertNotIn("200", args)

    def test_do_refresh_with_limit_value(self):
        args = _build_args("crawl_channels", FakePost({"do_refresh": "1", "refresh_limit": "200"}))
        # Every crawl_channels toggle is a bool_explicit spec, so the empty
        # checkboxes emit a constellation of --no-<flag> entries. Filter them
        # out to assert on just the refresh-related portion.
        non_no = [a for a in args if not a.startswith("--no-")]
        self.assertEqual(non_no, ["--refresh-messages-stats", "--refresh-limit", "200"])

    def test_do_refresh_with_date_value(self):
        args = _build_args("crawl_channels", FakePost({"do_refresh": "1", "refresh_from": "2024-01-01"}))
        self.assertIn("2024-01-01", args)

    def test_ids_appended(self):
        args = _build_args("crawl_channels", FakePost({"ids": "-30, 50-80"}))
        self.assertIn("--ids", args)
        self.assertIn("-30, 50-80", args)

    def test_channel_types_comma_joined(self):
        post = FakePost({"channel_type_channel": "1", "channel_type_group": "1"})
        args = _build_args("crawl_channels", post)
        idx = args.index("--channel-types")
        self.assertIn("CHANNEL", args[idx + 1])
        self.assertIn("GROUP", args[idx + 1])

    def test_channel_groups_comma_joined(self):
        post = FakePost({"channel_groups": ["GroupA", "GroupB"]})
        args = _build_args("crawl_channels", post)
        self.assertIn("--channel-groups", args)
        val = args[args.index("--channel-groups") + 1]
        self.assertIn("GroupA", val)
        self.assertIn("GroupB", val)


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: search_channels
# ---------------------------------------------------------------------------


class BuildArgsSearchChannelsTests(TestCase):
    def test_empty_post_produces_no_args(self):
        self.assertEqual(_build_args("search_channels", FakePost()), [])

    def test_amount_appended(self):
        args = _build_args("search_channels", FakePost({"amount": "10"}))
        self.assertEqual(args, ["--amount", "10"])

    def test_extra_terms_normalised_and_repeated(self):
        post = FakePost({"extra_terms": "Term One\n  TERM TWO  \n"})
        args = _build_args("search_channels", post)
        self.assertIn("--extra-term", args)
        self.assertIn("term one", args)
        self.assertIn("term two", args)

    def test_blank_extra_term_lines_skipped(self):
        post = FakePost({"extra_terms": "\n\n"})
        self.assertEqual(_build_args("search_channels", post), [])


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: structural_analysis
# ---------------------------------------------------------------------------


class BuildArgsExportNetworkTests(TestCase):
    def test_export_name_appended(self):
        # No robustness strategy ticked ⇒ --no-robustness trails; ``community_palette_reversed``
        # is a ``bool_explicit`` spec so an explicit --no-community-palette-reversed slips in
        # whenever the form omits the checkbox.
        args = _build_args("structural_analysis", FakePost({"export_name": "baseline", "include_mentions": "on"}))
        self.assertEqual(args, ["--name", "baseline", "--no-community-palette-reversed", "--no-robustness"])

    def test_boolean_output_flags(self):
        for field, flag in [
            ("graph", "--2dgraph"),
            ("html", "--html"),
            ("graph_3d", "--3dgraph"),
            ("xlsx", "--xlsx"),
            ("gexf", "--gexf"),
            ("graphml", "--graphml"),
            ("seo", "--seo"),
            ("vertical_layout", "--vertical-layout"),
            ("draw_dead_leaves", "--draw-dead-leaves"),
            ("consensus_matrix", "--consensus-matrix"),
            ("timeline_step", "--timeline-step"),
        ]:
            with self.subTest(field=field):
                args = _build_args("structural_analysis", FakePost({field: "1"}))
                self.assertIn(flag, args)

    def test_measures_csv(self):
        post = FakePost({"measures": ["PAGERANK", "BETWEENNESS"]})
        args = _build_args("structural_analysis", post)
        idx = args.index("--measures")
        self.assertIn("PAGERANK", args[idx + 1])
        self.assertIn("BETWEENNESS", args[idx + 1])

    def test_date_filters(self):
        post = FakePost({"startdate": "2024-01-01", "enddate": "2024-12-31"})
        args = _build_args("structural_analysis", post)
        self.assertIn("--startdate", args)
        self.assertIn("--enddate", args)

    def test_numeric_params(self):
        post = FakePost({"fa2_iterations": "1000", "spreading_runs": "50", "recency_weights": "90"})
        args = _build_args("structural_analysis", post)
        self.assertIn("--fa2-iterations", args)
        self.assertIn("--spreading-runs", args)
        self.assertIn("--recency-weights", args)

    def test_community_strategies_csv(self):
        post = FakePost({"community_strategies": ["LEIDEN", "LOUVAIN"]})
        args = _build_args("structural_analysis", post)
        idx = args.index("--community-strategies")
        self.assertIn("LEIDEN", args[idx + 1])

    def test_timeline_step_year(self):
        args = _build_args("structural_analysis", FakePost({"timeline_step": "1"}))
        idx = args.index("--timeline-step")
        self.assertEqual(args[idx + 1], "year")

    def test_empty_strings_not_added(self):
        # All value-kind fields blank ⇒ only the implicit --no-community-palette-reversed
        # (from the bool_explicit spec) and --no-robustness survive.
        post = FakePost({"export_name": "", "fa2_iterations": "", "startdate": "", "include_mentions": "on"})
        self.assertEqual(
            _build_args("structural_analysis", post),
            ["--no-community-palette-reversed", "--no-robustness"],
        )


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: compare_analysis
# ---------------------------------------------------------------------------


class BuildArgsCompareAnalysisTests(TestCase):
    def test_project_dir_is_positional(self):
        args = _build_args("compare_analysis", FakePost({"project_dir": "/path/to/export"}))
        self.assertEqual(args[0], "/path/to/export")

    def test_target_appended(self):
        args = _build_args("compare_analysis", FakePost({"compare_target": "baseline"}))
        self.assertIn("--target", args)
        self.assertIn("baseline", args)

    def test_seo_flag(self):
        args = _build_args("compare_analysis", FakePost({"seo": "1"}))
        self.assertIn("--seo", args)

    def test_empty_project_dir_not_added(self):
        self.assertEqual(_build_args("compare_analysis", FakePost({"project_dir": ""})), [])


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: structural_analysis (robustness flags)
# ---------------------------------------------------------------------------


class BuildArgsStructuralRobustnessTests(TestCase):
    # In the Operations panel, the robustness master switch is implicit: at least
    # one strategy ticked ⇒ --robustness, none ticked ⇒ --no-robustness. The CLI
    # --robustness/--no-robustness pair (BooleanOptionalAction) lets the UI fully
    # override the robustness.enabled default in configuration/.operations-structural.

    def test_empty_post_emits_no_robustness(self) -> None:
        args = _build_args("structural_analysis", FakePost())
        self.assertIn("--no-robustness", args)
        self.assertNotIn("--robustness", args)
        for flag in (
            "--robustness-alpha",
            "--robustness-strategies",
            "--robustness-runs",
            "--robustness-null",
            "--robustness-seed",
            "--robustness-sample",
        ):
            self.assertNotIn(flag, args)

    def test_strategy_checkboxes_imply_robustness_and_emit_csv(self) -> None:
        post = FakePost({"robustness_strategies": ["pagerank", "betweenness_dyn", "hits_authority"]})
        args = _build_args("structural_analysis", post)
        self.assertIn("--robustness", args)
        self.assertNotIn("--no-robustness", args)
        self.assertIn("--robustness-strategies", args)
        idx = args.index("--robustness-strategies")
        self.assertEqual(args[idx + 1], "pagerank,betweenness_dyn,hits_authority")

    def test_bridging_basis_dropdown_rewrites_to_parenthesised_form(self) -> None:
        # The bridging-basis dropdown is shared between the BRIDGING measure and
        # the bridging robustness attack — both pick it up under the same field name.
        post = FakePost(
            {
                "robustness_strategies": ["pagerank", "bridging"],
                "bridging_basis": "LOUVAIN",
            }
        )
        args = _build_args("structural_analysis", post)
        idx = args.index("--robustness-strategies")
        self.assertEqual(args[idx + 1], "pagerank,bridging(louvain)")

    def test_bridging_basis_blank_leaves_bare_bridging(self) -> None:
        # Empty dropdown value means "use the backend default" — emit bare bridging
        # so the runner picks leiden_directed.
        post = FakePost({"robustness_strategies": ["bridging"], "bridging_basis": ""})
        args = _build_args("structural_analysis", post)
        idx = args.index("--robustness-strategies")
        self.assertEqual(args[idx + 1], "bridging")

    def test_bridging_basis_also_rewrites_measures(self) -> None:
        # Shared field — BRIDGING in measures gets the same basis appended.
        post = FakePost(
            {
                "measures": ["PAGERANK", "BRIDGING"],
                "bridging_basis": "LOUVAIN",
            }
        )
        args = _build_args("structural_analysis", post)
        idx = args.index("--measures")
        self.assertEqual(args[idx + 1], "PAGERANK,BRIDGING(LOUVAIN)")

    def test_measures_without_bridging_unchanged_by_basis(self) -> None:
        post = FakePost(
            {
                "measures": ["PAGERANK", "BETWEENNESS"],
                "bridging_basis": "LOUVAIN",
            }
        )
        args = _build_args("structural_analysis", post)
        idx = args.index("--measures")
        self.assertEqual(args[idx + 1], "PAGERANK,BETWEENNESS")

    def test_no_strategies_omits_robustness(self) -> None:
        # Without any strategy ticked, the analysis is explicitly turned off.
        args = _build_args("structural_analysis", FakePost())
        self.assertIn("--no-robustness", args)
        self.assertNotIn("--robustness-strategies", args)

    def test_numeric_params_emit_flag_value_pairs(self) -> None:
        # Tuning fields still emit their flag/value pair regardless of whether
        # robustness is on — they are ignored by the backend when --no-robustness
        # wins, but kept in sync with the form's current values.
        post = FakePost(
            {
                "robustness_strategies": ["pagerank"],
                "robustness_alpha": "0.1",
                "robustness_runs": "50",
                "robustness_null": "10",
                "robustness_seed": "7",
                "robustness_sample": "200",
            }
        )
        args = _build_args("structural_analysis", post)
        self.assertIn("--robustness", args)
        for flag, value in (
            ("--robustness-alpha", "0.1"),
            ("--robustness-runs", "50"),
            ("--robustness-null", "10"),
            ("--robustness-seed", "7"),
            ("--robustness-sample", "200"),
        ):
            self.assertIn(flag, args)
            self.assertEqual(args[args.index(flag) + 1], value)

    def test_empty_value_field_skipped(self) -> None:
        # value-kind specs drop the flag entirely when the field is blank.
        args = _build_args(
            "structural_analysis", FakePost({"robustness_strategies": ["pagerank"], "robustness_alpha": ""})
        )
        self.assertIn("--robustness", args)
        self.assertNotIn("--robustness-alpha", args)


# ---------------------------------------------------------------------------
# SaveDefaultsView — POST /operations/save-defaults/<task>/
# ---------------------------------------------------------------------------


class _RedirectConfigPathsForRunner:
    """Test helper that redirects the config-module path constants to a temp dir."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig: dict = {}

    def __enter__(self):
        from webapp_engine.config import loader, paths, writer

        for attr in ("CONFIG_DIR", "CRAWL_PATH", "STRUCTURAL_PATH"):
            self._orig[attr] = getattr(paths, attr)
        paths.CONFIG_DIR = self.tmp
        paths.CRAWL_PATH = self.tmp / ".operations-crawl"
        paths.STRUCTURAL_PATH = self.tmp / ".operations-structural"
        loader.CRAWL_PATH = paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = paths.STRUCTURAL_PATH
        writer.CRAWL_PATH = paths.CRAWL_PATH
        writer.STRUCTURAL_PATH = paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = paths.CONFIG_DIR
        return self.tmp

    def __exit__(self, *exc):
        from webapp_engine.config import loader, paths, writer

        for attr, value in self._orig.items():
            setattr(paths, attr, value)
        loader.CRAWL_PATH = paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = paths.STRUCTURAL_PATH
        writer.CRAWL_PATH = paths.CRAWL_PATH
        writer.STRUCTURAL_PATH = paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = paths.CONFIG_DIR


class SaveDefaultsViewTests(TestCase):
    def test_unknown_task_returns_404(self) -> None:
        resp = self.client.post(reverse("operations-save-defaults", args=["nope"]))
        self.assertEqual(resp.status_code, 404)

    def test_crawl_save_writes_file(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["crawl_channels"]),
                data={
                    "get_channels_info": "on",
                    "download_video": "on",
                    "channel_type_channel": "on",
                    "channel_type_group": "on",
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["saved"])

            content = (tmp / ".operations-crawl").read_text()
            self.assertIn("video = true", content)
            self.assertIn("get_channels_info = true", content)
            self.assertIn('channel_types = ["CHANNEL", "GROUP"]', content)

    def test_structural_save_round_trip(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={
                    "graph": "on",
                    "html": "on",
                    "fa2_iterations": "3000",
                    "measures": ["PAGERANK", "BETWEENNESS"],
                    "bridging_basis": "LEIDEN",
                    "timeline_step": "on",
                    "robustness_strategies": ["pagerank", "random"],
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn("graph = true", content)
            self.assertIn("fa2_iterations = 3000", content)
            self.assertIn('selected = ["PAGERANK", "BETWEENNESS"]', content)
            self.assertIn('bridging_basis = "LEIDEN"', content)
            self.assertIn('timeline_step = "year"', content)
            self.assertIn('strategies = ["pagerank", "random"]', content)
            self.assertIn("enabled = true", content)

    def test_robustness_enabled_false_when_no_strategies(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"html": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn("enabled = false", content)
            self.assertIn("strategies = []", content)

    def test_blank_int_falls_back_to_default(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"community_distribution_threshold": "", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn("community_distribution_threshold = 10", content)

    def test_fa2_iterations_multiplier_form_saved_as_string(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"fa2_iterations": "10x", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn('fa2_iterations = "10x"', content)

    def test_fa2_iterations_integer_form_saved_as_int(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"fa2_iterations": "3000", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn("fa2_iterations = 3000", content)

    def test_fa2_iterations_blank_falls_back_to_default(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"fa2_iterations": "", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn('fa2_iterations = "7x"', content)

    def test_community_palette_round_trip(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={
                    "community_palette": "vaporwave",
                    "community_palette_reversed": "on",
                    "graph": "on",
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn('community_palette = "vaporwave"', content)
            self.assertIn("community_palette_reversed = true", content)

    def test_community_palette_reversed_unchecked_persists_false(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"community_palette": "vaporwave", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = (tmp / ".operations-structural").read_text()
            self.assertIn("community_palette_reversed = false", content)

    def test_save_rejects_unknown_palette(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-save-defaults", args=["structural_analysis"]),
                data={"community_palette": "NOT_A_REAL_PALETTE", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Unknown palette", resp.json()["error"])


class PaletteColorsViewTests(TestCase):
    def test_known_palette_returns_hex_list(self) -> None:
        resp = self.client.get(reverse("operations-palette", args=["vaporwave"]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "vaporwave")
        self.assertFalse(data["reverse"])
        self.assertTrue(data["colors"])
        for hex_value in data["colors"]:
            self.assertRegex(hex_value, r"^#[0-9a-fA-F]{6}$")

    def test_reverse_query_param_returns_reversed_colours(self) -> None:
        canonical = self.client.get(reverse("operations-palette", args=["vaporwave"])).json()["colors"]
        reversed_colors = self.client.get(reverse("operations-palette", args=["vaporwave"]) + "?reverse=1").json()[
            "colors"
        ]
        self.assertEqual(reversed_colors, list(reversed(canonical)))

    def test_unknown_palette_returns_404(self) -> None:
        resp = self.client.get(reverse("operations-palette", args=["NOT_A_REAL_PALETTE"]))
        self.assertEqual(resp.status_code, 404)
