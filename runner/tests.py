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
        self.assertIn("Alpha", resp.context["channel_groups"])


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
    def test_empty_post_produces_no_args(self):
        self.assertEqual(_build_args("crawl_channels", FakePost()), [])

    def test_each_boolean_flag_mapped(self):
        flags = {
            "get_new_messages": "--get-new-messages",
            "fix_holes": "--fixholes",
            "fetch_recommended_channels": "--fetch-recommended-channels",
            "retry_references": "--retry-references",
            "force_retry_unresolved_references": "--force-retry-unresolved-references",
            "mine_about_texts": "--mine-about-texts",
            "refresh_degrees": "--refresh-degrees",
            "fix_missing_media": "--fix-missing-media",
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
        args = _build_args("crawl_channels", FakePost({"do_refresh": "1", "refresh_value": "200"}))
        self.assertEqual(args, ["--refresh-messages-stats", "200"])

    def test_do_refresh_with_date_value(self):
        args = _build_args("crawl_channels", FakePost({"do_refresh": "1", "refresh_value": "2024-01-01"}))
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
        args = _build_args("structural_analysis", FakePost({"export_name": "baseline"}))
        self.assertEqual(args, ["--name", "baseline"])

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
        post = FakePost({"export_name": "", "fa2_iterations": "", "startdate": ""})
        self.assertEqual(_build_args("structural_analysis", post), [])


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
