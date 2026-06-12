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

    @staticmethod
    def _texts(lines: list[dict]) -> list[str]:
        return [line["text"] for line in lines]

    def test_plain_lines_returned(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"line one\nline two\nline three\n")
        lines, offset = get_log_lines("structural_analysis")
        self.assertEqual(self._texts(lines), ["line one", "line two", "line three"])
        self.assertEqual([line["cls"] for line in lines], ["", "", ""])
        self.assertGreater(offset, 0)

    def test_ansi_escapes_stripped(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"\x1b[32mGreen text\x1b[0m\n")
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(self._texts(lines), ["Green text"])

    def test_ansi_colour_classifies_severity(self):
        from runner.tasks import get_log_lines

        # Django style markup (DJANGO_COLORS=dark + --force-color): the SGR
        # colour decides the class even when the wording matches no keyword.
        self._write_log(
            "structural_analysis",
            b"\x1b[33;1mCould not resolve entity for X\x1b[0m\n"
            b"\x1b[31;1mfatal: cannot continue\x1b[0m\n"
            b"\x1b[32;1mCrawl finished.\x1b[0m\n",
        )
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual([line["cls"] for line in lines], ["line-warning", "line-error", "line-success"])

    def test_ansi_colour_beats_keyword_fallback(self):
        from runner.tasks import get_log_lines

        # A handled, WARNING-styled line mentioning "Error" must stay yellow.
        self._write_log("structural_analysis", b"\x1b[33;1mError fetching messages for X: timeout\x1b[0m\n")
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(lines[0]["cls"], "line-warning")

    def test_keyword_fallback_for_unstyled_lines(self):
        from runner.tasks import get_log_lines

        self._write_log(
            "structural_analysis",
            b"Traceback (most recent call last):\nplain progress\ndone\nSkipping channel 1\n",
        )
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(
            [line["cls"] for line in lines],
            ["line-error", "", "line-success", "line-warning"],
        )

    def test_carriage_return_keeps_last_segment(self):
        from runner.tasks import get_log_lines

        # Progress-bar style: earlier content overwritten by CR; only final segment shown.
        self._write_log("structural_analysis", b"loading\rprogress 50%\rprogress 100%\n")
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(self._texts(lines), ["progress 100%"])

    def test_carriage_return_classifies_visible_segment_only(self):
        from runner.tasks import get_log_lines

        # The styled segment was overwritten by an unstyled one: no colour.
        self._write_log("structural_analysis", b"\x1b[31;1mbad\x1b[0m\rall good now\n")
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(lines, [{"text": "all good now", "cls": ""}])

    def test_python_warning_lines_dropped(self):
        from runner.tasks import get_log_lines

        content = b"/home/user/app.py:42: DeprecationWarning: old api\n  old_function()\nnormal output\n"
        self._write_log("structural_analysis", content)
        lines, _ = get_log_lines("structural_analysis")
        self.assertEqual(self._texts(lines), ["normal output"])

    def test_offset_resumes_from_byte_position(self):
        from runner.tasks import get_log_lines

        self._write_log("structural_analysis", b"first\nsecond\n")
        _, offset = get_log_lines("structural_analysis")
        self._write_log("structural_analysis", b"first\nsecond\nthird\n")
        lines, _ = get_log_lines("structural_analysis", offset)
        self.assertEqual(self._texts(lines), ["third"])

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

    def test_launch_forces_color_without_recording_it(self):
        from runner.tasks import launch

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("runner.tasks.subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch("search_channels", ["--amount", "5"])
        # --force-color makes Django emit the self.style.* ANSI codes into the
        # pipe (severity classification reads them); it is an implementation
        # detail of the runner, so it must not leak into the user-visible args.
        wrapper_cmd = mock_popen.call_args.args[0]
        self.assertIn("--force-color", wrapper_cmd)
        self.assertEqual(mock_popen.call_args.kwargs["env"]["DJANGO_COLORS"], "dark")
        meta = json.loads((self.tmp_dir / "runner_search_channels.meta.json").read_text())
        self.assertNotIn("--force-color", meta["args"])


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

    def test_run_accepts_search_channels_zero_amount(self):
        # amount=0 is legal — it searches only the extra/form terms (no queued SearchTerms).
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch"),
        ):
            resp = self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"amount": "0"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_run_rejects_search_channels_negative_amount(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"amount": "-3"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("positive", resp.json()["error"])

    def test_run_accepts_search_channels_blank_amount(self):
        # Blank means "process all queued terms" — still legal.
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch"),
        ):
            resp = self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"amount": ""},
            )
        self.assertEqual(resp.status_code, 200)

    def test_run_rejects_compare_analysis_empty_project_dir(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["compare_analysis"]),
                {"project_dir": "", "compare_target": "foo"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("project_dir", resp.json()["error"])

    def test_run_rejects_compare_analysis_empty_target(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["compare_analysis"]),
                {"project_dir": "/tmp/foo", "compare_target": ""},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Target export name", resp.json()["error"])


# ---------------------------------------------------------------------------
# runner/views.py — WriteCliCommandView
# ---------------------------------------------------------------------------


class WriteCliCommandViewTests(TestCase):
    def test_unknown_task_returns_404(self):
        resp = self.client.post(reverse("operations-write-cli-command", args=["nope"]))
        self.assertEqual(resp.status_code, 404)

    def test_crawl_empty_form_emits_full_no_constellation(self):
        resp = self.client.post(reverse("operations-write-cli-command", args=["crawl_channels"]))
        self.assertEqual(resp.status_code, 200)
        cmd = resp.json()["command"]
        self.assertTrue(cmd.startswith("python manage.py crawl_channels"))
        self.assertIn("--no-get-channels-info", cmd)
        self.assertIn("--no-fix-holes", cmd)

    def test_structural_with_flags(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={
                "graph": "on",
                "html": "on",
                "include_mentions": "on",
                "community_strategies": ["LEIDEN"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        cmd = resp.json()["command"]
        self.assertTrue(cmd.startswith("python manage.py structural_analysis"))
        self.assertIn("--graph-2d", cmd)
        self.assertIn("--html", cmd)
        self.assertIn("--mentions", cmd)
        self.assertIn("--community-strategies LEIDEN", cmd)

    def test_command_quotes_args_with_spaces(self):
        # search_channels --extra-term may carry multi-word phrases.  The
        # preview must remain executable when pasted into a shell.
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["search_channels"]),
            data={"extra_terms": "hello world\nbearbeit"},
        )
        self.assertEqual(resp.status_code, 200)
        cmd = resp.json()["command"]
        self.assertIn("--extra-term 'hello world'", cmd)
        self.assertIn("--extra-term bearbeit", cmd)

    def test_structural_validation_rejects_bad_module_role_basis(self):
        # The community basis travels inside the MODULEROLE token; a basis that names a
        # strategy not in community_strategies is rejected.
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={
                "measures": ["MODULEROLE(basis=LEIDEN)"],
                "community_strategies": ["LEIDEN_DIRECTED"],
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("MODULEROLE basis", resp.json()["error"])

    def test_structural_accepts_parameterised_strategy_and_family_basis(self):
        # A repeated parameterised strategy + a MODULEROLE basis naming the family validates fine.
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={
                "measures": ["MODULEROLE(basis=LEIDEN_CPM)"],
                "community_strategies": ["LEIDEN_CPM(resolution=0.01)", "LEIDEN_CPM(resolution=0.05)"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("--community-strategies", resp.json()["command"])

    def test_structural_validation_rejects_malformed_strategy_token(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["LEIDEN(resolution=0.1)"]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Community strategies", resp.json()["error"])


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
            patch("runner.views.tasks.get_log_lines", return_value=([{"text": "hello", "cls": ""}], 5)),
        ):
            resp = self.client.get(reverse("operations-status", args=["structural_analysis"]))
        data = resp.json()
        self.assertEqual(data["lines"], [{"text": "hello", "cls": ""}])
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
                "--no-fetch-recommended",
                "--no-retry-lost-and-private",
                "--no-get-new-messages",
                "--no-fetch-replies",
                "--no-refresh-messages-stats",
                "--no-fix-holes",
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
            "fix_holes": "--fix-holes",
            "fetch_recommended": "--fetch-recommended",
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

    def test_refresh_messages_stats_without_value(self):
        args = _build_args("crawl_channels", FakePost({"refresh_messages_stats": "1", "refresh_value": ""}))
        self.assertIn("--refresh-messages-stats", args)
        self.assertNotIn("200", args)

    def test_refresh_messages_stats_with_limit_value(self):
        args = _build_args("crawl_channels", FakePost({"refresh_messages_stats": "1", "refresh_limit": "200"}))
        # Every crawl_channels toggle is a bool_explicit spec, so the empty
        # checkboxes emit a constellation of --no-<flag> entries. Filter them
        # out to assert on just the refresh-related portion.
        non_no = [a for a in args if not a.startswith("--no-")]
        self.assertEqual(non_no, ["--refresh-messages-stats", "--refresh-limit", "200"])

    def test_refresh_messages_stats_with_date_value(self):
        args = _build_args("crawl_channels", FakePost({"refresh_messages_stats": "1", "refresh_from": "2024-01-01"}))
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

    def test_add_channels_repeated_verbatim(self):
        # Identifiers must not be lowercased or space-collapsed: the command
        # normalises them itself (and usernames are case-insensitive anyway).
        post = FakePost({"add_channels": "https://t.me/SomeChannel\n  @Name  \n12345\n\n"})
        args = _build_args("search_channels", post)
        self.assertEqual(
            args,
            [
                "--add-channel",
                "https://t.me/SomeChannel",
                "--add-channel",
                "@Name",
                "--add-channel",
                "12345",
            ],
        )

    def test_blank_add_channel_lines_skipped(self):
        post = FakePost({"add_channels": "\n  \n"})
        self.assertEqual(_build_args("search_channels", post), [])


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: structural_analysis
# ---------------------------------------------------------------------------


class BuildArgsExportNetworkTests(TestCase):
    def test_export_name_appended(self):
        # Every output toggle is bool_explicit, so an empty form emits the matching
        # --no-X for each one (graph-2d, graph-3d, html, xlsx, gexf, graphml, csv,
        # seo, vertical-layout, draw-dead-leaves, community-palette-reversed,
        # self-references, consensus-matrix, structural-similarity, include-lost,
        # include-private) plus --no-robustness.  This is the desired behaviour —
        # explicit "off" beats a saved-true default.
        args = _build_args("structural_analysis", FakePost({"export_name": "baseline", "include_mentions": "on"}))
        self.assertEqual(args[:2], ["--name", "baseline"])
        # include_mentions checked ⇒ explicit --mentions, not a silent fallback.
        self.assertIn("--mentions", args)
        for negation in (
            "--no-graph-2d",
            "--no-graph-3d",
            "--no-html",
            "--no-xlsx",
            "--no-gexf",
            "--no-graphml",
            "--no-csv",
            "--no-seo",
            "--no-vertical-layout",
            "--no-draw-dead-leaves",
            "--no-community-palette-reversed",
            "--no-self-references",
            "--no-consensus-matrix",
            "--no-structural-similarity",
            "--no-include-lost",
            "--no-include-private",
            "--no-robustness",
        ):
            self.assertIn(negation, args)

    def test_include_mentions_bool_explicit(self):
        # include_mentions must always transmit its state explicitly so a loaded
        # snapshot's value can't be silently overridden by settings.SA_INCLUDE_MENTIONS.
        args_on = _build_args("structural_analysis", FakePost({"include_mentions": "on"}))
        self.assertIn("--mentions", args_on)
        self.assertNotIn("--no-mentions", args_on)
        args_off = _build_args("structural_analysis", FakePost())
        self.assertIn("--no-mentions", args_off)
        self.assertNotIn("--mentions", args_off)

    def test_boolean_output_flags(self):
        for field, flag in [
            ("graph", "--graph-2d"),
            ("html", "--html"),
            ("graph_3d", "--graph-3d"),
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
        post = FakePost({"measures": ["PAGERANK", "OUTDEGCENTRALITY"]})
        args = _build_args("structural_analysis", post)
        idx = args.index("--measures")
        self.assertIn("PAGERANK", args[idx + 1])
        self.assertIn("OUTDEGCENTRALITY", args[idx + 1])

    def test_date_filters(self):
        post = FakePost({"startdate": "2024-01-01", "enddate": "2024-12-31"})
        args = _build_args("structural_analysis", post)
        self.assertIn("--startdate", args)
        self.assertIn("--enddate", args)

    def test_numeric_params(self):
        post = FakePost({"fa2_iterations": "1000"})
        args = _build_args("structural_analysis", post)
        self.assertIn("--fa2-iterations", args)

    def test_community_strategies_csv(self):
        post = FakePost({"community_strategies": ["LEIDEN", "LEIDEN_DIRECTED"]})
        args = _build_args("structural_analysis", post)
        idx = args.index("--community-strategies")
        self.assertIn("LEIDEN", args[idx + 1])
        self.assertIn("LEIDEN_DIRECTED", args[idx + 1])

    def test_community_strategies_parameterised_tokens_join_in_order(self):
        # The builder posts one token per chip (with its parameters); csv joins them in order,
        # and repeated LEIDEN_CPM at different resolutions both survive.
        post = FakePost(
            {
                "community_strategies": [
                    "LEIDEN_CPM(resolution=0.01)",
                    "LEIDEN_CPM(resolution=0.05)",
                    "LEIDEN_DIRECTED",
                ]
            }
        )
        args = _build_args("structural_analysis", post)
        idx = args.index("--community-strategies")
        self.assertEqual(args[idx + 1], "LEIDEN_CPM(resolution=0.01),LEIDEN_CPM(resolution=0.05),LEIDEN_DIRECTED")

    def test_timeline_step_year(self):
        args = _build_args("structural_analysis", FakePost({"timeline_step": "1"}))
        idx = args.index("--timeline-step")
        self.assertEqual(args[idx + 1], "year")

    def test_empty_strings_not_added(self):
        # Value-kind blanks (export_name, fa2_iterations, startdate) are dropped;
        # bool_explicit specs still emit --no-X for every unchecked toggle.
        post = FakePost({"export_name": "", "fa2_iterations": "", "startdate": "", "include_mentions": "on"})
        args = _build_args("structural_analysis", post)
        self.assertNotIn("--name", args)
        self.assertNotIn("--fa2-iterations", args)
        self.assertNotIn("--startdate", args)
        # All bool_explicit defaults emit --no-X when the box is unchecked.
        for negation in ("--no-graph-2d", "--no-html", "--no-community-palette-reversed", "--no-robustness"):
            self.assertIn(negation, args)


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
        # `seo` is bool_explicit so an empty post emits --no-seo. Project dir stays out.
        args = _build_args("compare_analysis", FakePost({"project_dir": ""}))
        self.assertEqual(args, ["--no-seo"])


# ---------------------------------------------------------------------------
# runner/views.py — _build_args: structural_analysis (robustness flags)
# ---------------------------------------------------------------------------


class BuildArgsStructuralRobustnessTests(TestCase):
    # In the Operations panel, the robustness master switch is implicit: at least
    # one strategy ticked ⇒ --robustness, none ticked ⇒ --no-robustness. The CLI
    # --robustness/--no-robustness pair (BooleanOptionalAction) lets the UI fully
    # override the SA_ROBUSTNESS setting (derived from bool(strategies)).

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
        post = FakePost({"robustness_strategies": ["pagerank", "in_strength_dyn", "pagerank_dyn"]})
        args = _build_args("structural_analysis", post)
        self.assertIn("--robustness", args)
        self.assertNotIn("--no-robustness", args)
        self.assertIn("--robustness-strategies", args)
        idx = args.index("--robustness-strategies")
        self.assertEqual(args[idx + 1], "pagerank,in_strength_dyn,pagerank_dyn")

    def test_measure_tokens_pass_through_verbatim(self) -> None:
        # Each chip already carries its parameters in the token; --measures is a plain CSV join,
        # preserving order and per-instance parameters (a measure may repeat with different params).
        post = FakePost(
            {"measures": ["PAGERANK", "DIFFUSIONLAG(window=30)", "MODULEROLE(basis=LEIDEN)", "DIFFUSIONLAG(window=60)"]}
        )
        args = _build_args("structural_analysis", post)
        idx = args.index("--measures")
        self.assertEqual(
            args[idx + 1], "PAGERANK,DIFFUSIONLAG(window=30),MODULEROLE(basis=LEIDEN),DIFFUSIONLAG(window=60)"
        )

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
        loader.CONFIG_DIR = paths.CONFIG_DIR
        loader.CRAWL_PATH = paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = paths.CONFIG_DIR
        return self.tmp

    def __exit__(self, *exc):
        from webapp_engine.config import loader, paths, writer

        for attr, value in self._orig.items():
            setattr(paths, attr, value)
        loader.CONFIG_DIR = paths.CONFIG_DIR
        loader.CRAWL_PATH = paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = paths.CONFIG_DIR


def _saved_file_content(tmp: Path, stem: str) -> str:
    """Read the single timestamped sidecar that a `Save` request just created."""
    candidates = sorted(p for p in tmp.iterdir() if p.name.startswith(f"{stem}-"))
    assert candidates, f"no {stem}-* sidecar produced"
    return candidates[-1].read_text()


class DefaultsViewTests(TestCase):
    def test_unknown_task_returns_404(self) -> None:
        resp = self.client.post(reverse("operations-defaults", args=["nope"]), data={"title": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_save_requires_title(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["crawl_channels"]),
                data={"get_channels_info": "on"},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("title", resp.json()["error"])

    def test_crawl_save_writes_timestamped_file(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["crawl_channels"]),
                data={
                    "title": "My crawl",
                    "get_channels_info": "on",
                    "download_video": "on",
                    "channel_type_channel": "on",
                    "channel_type_group": "on",
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["saved"])
            self.assertEqual(data["item"]["title"], "My crawl")
            self.assertFalse(data["item"]["is_base"])
            content = _saved_file_content(tmp, ".operations-crawl")
            self.assertIn('title = "My crawl"', content)
            self.assertIn("video = true", content)
            self.assertIn("get_channels_info = true", content)
            self.assertIn('channel_types = ["CHANNEL", "GROUP"]', content)

    def test_structural_save_round_trip(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "Big run",
                    "graph": "on",
                    "html": "on",
                    "fa2_iterations": "3000",
                    "measures": ["PAGERANK", "DIFFUSIONLAG(window=60)"],
                    "timeline_step": "on",
                    "robustness_strategies": ["pagerank", "random"],
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn("graph = true", content)
            self.assertIn("fa2_iterations = 3000", content)
            # Measure tokens are saved verbatim, including per-instance parameters.
            self.assertIn('selected = ["PAGERANK", "DIFFUSIONLAG(window=60)"]', content)
            self.assertIn('timeline_step = "year"', content)
            self.assertIn('strategies = ["pagerank", "random"]', content)
            self.assertNotIn("enabled", content.split("[robustness]", 1)[-1].split("[", 1)[0])

    def test_robustness_strategies_empty_when_none_ticked(self) -> None:
        # `robustness.enabled` is no longer written — SA_ROBUSTNESS is derived
        # from bool(strategies) in settings.py.
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "no-strats", "html": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertNotIn("enabled =", content.split("[robustness]", 1)[-1].split("[", 1)[0])
            self.assertIn("strategies = []", content)

    def test_blank_int_falls_back_to_default(self) -> None:
        # The defaults are now factory-empty no-ops (community_distribution_threshold = 0).
        # A blank form value falls back to the no-op default, not to a curated value.
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "community_distribution_threshold": "", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("community_distribution_threshold = 0", _saved_file_content(tmp, ".operations-structural"))

    def test_fa2_iterations_multiplier_form_saved_as_string(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "fa2_iterations": "10x", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn('fa2_iterations = "10x"', _saved_file_content(tmp, ".operations-structural"))

    def test_fa2_iterations_integer_form_saved_as_int(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "fa2_iterations": "3000", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("fa2_iterations = 3000", _saved_file_content(tmp, ".operations-structural"))

    def test_fa2_iterations_blank_falls_back_to_default(self) -> None:
        # No-op factory default is "" (empty string) — the saved file mirrors it.
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "fa2_iterations": "", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn('fa2_iterations = ""', _saved_file_content(tmp, ".operations-structural"))

    def test_community_palette_round_trip(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "t",
                    "community_palette": "vaporwave",
                    "community_palette_reversed": "on",
                    "graph": "on",
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn('community_palette = "vaporwave"', content)
            self.assertIn("community_palette_reversed = true", content)

    def test_community_palette_reversed_unchecked_persists_false(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "community_palette": "vaporwave", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("community_palette_reversed = false", _saved_file_content(tmp, ".operations-structural"))

    def test_save_rejects_unknown_palette(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "community_palette": "NOT_A_REAL_PALETTE", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Unknown palette", resp.json()["error"])

    def test_save_rejects_module_role_basis_not_in_strategies(self) -> None:
        # MODULEROLE(basis=LEIDEN) is configured but community_strategies doesn't include LEIDEN —
        # the MODULEROLE measure would point at a partition that's never computed.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "bad-basis",
                    "measures": ["MODULEROLE(basis=LEIDEN)"],
                    "community_strategies": ["KCORE"],
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("MODULEROLE basis", resp.json()["error"])

    def test_save_accepts_module_role_when_basis_in_strategies(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "good-basis",
                    "measures": ["MODULEROLE(basis=LEIDEN)"],
                    "community_strategies": ["LEIDEN", "KCORE"],
                },
            )
            self.assertEqual(resp.status_code, 200)

    def test_save_rejects_module_role_basis_unknown_strategy(self) -> None:
        # An unknown basis is rejected by the measure-token parser itself.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "bogus-basis",
                    "measures": ["MODULEROLE(basis=NOT_A_REAL_STRATEGY)"],
                    "community_strategies": ["LEIDEN"],
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("not a valid choice", resp.json()["error"])

    def test_save_accepts_repeated_parameterised_measure(self) -> None:
        # The same measure may be saved more than once with different parameters.
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "two-lags",
                    "measures": ["DIFFUSIONLAG(window=30)", "DIFFUSIONLAG(window=60)"],
                    "community_strategies": ["LEIDEN"],
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn('selected = ["DIFFUSIONLAG(window=30)", "DIFFUSIONLAG(window=60)"]', content)

    def test_save_rejects_duplicate_drop_once_measure(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "dup", "measures": ["PAGERANK", "PAGERANK"]},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("more than once", resp.json()["error"])

    def test_save_rejects_consensus_matrix_with_few_strategies(self) -> None:
        # Consensus matrix needs ≥2 non-ORGANIZATION strategies; ORGANIZATION-only is empty output.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "thin-consensus",
                    "consensus_matrix": "on",
                    "community_strategies": ["ORGANIZATION", "LEIDEN"],  # only 1 non-org
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Consensus matrix requires", resp.json()["error"])

    def test_save_accepts_consensus_matrix_with_two_strategies(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "ok-consensus",
                    "consensus_matrix": "on",
                    "community_strategies": ["LEIDEN", "LEIDEN_DIRECTED"],
                },
            )
            self.assertEqual(resp.status_code, 200)

    def test_save_rejects_overlong_title(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["crawl_channels"]),
                data={"title": "x" * 121, "get_channels_info": "on"},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("at most", resp.json()["error"])

    def test_save_named_advances_timestamp_on_collision(self) -> None:
        # Two saves within the same UTC second must not silently overwrite —
        # the second one's filename should advance by 1 second.
        from webapp_engine.config import save_named

        with _RedirectConfigPathsForRunner() as tmp:
            first = save_named("crawl_channels", {}, title="first")
            second = save_named("crawl_channels", {}, title="second")
            self.assertNotEqual(first["id"], second["id"])
            self.assertTrue((tmp / first["filename"]).exists())
            self.assertTrue((tmp / second["filename"]).exists())
            self.assertIn('title = "first"', (tmp / first["filename"]).read_text())
            self.assertIn('title = "second"', (tmp / second["filename"]).read_text())

    def test_list_returns_base_when_only_baseline_present(self) -> None:
        from webapp_engine.config import write_baseline

        with _RedirectConfigPathsForRunner():
            write_baseline("crawl_channels", {"downloads": {"images": True}})
            resp = self.client.get(reverse("operations-defaults", args=["crawl_channels"]))
            self.assertEqual(resp.status_code, 200)
            items = resp.json()["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], "base")
            self.assertEqual(items[0]["title"], "Pulpit defaults")

    def test_list_then_load_round_trip(self) -> None:
        with _RedirectConfigPathsForRunner():
            self.client.post(
                reverse("operations-defaults", args=["crawl_channels"]),
                data={"title": "Snap1", "download_audio": "on"},
            )
            items = self.client.get(reverse("operations-defaults", args=["crawl_channels"])).json()["items"]
            snap = next(it for it in items if it["title"] == "Snap1")
            resp = self.client.get(reverse("operations-defaults-item", args=["crawl_channels", snap["id"]]))
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["values"]["download_audio"])

    def test_load_unknown_id_returns_404(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.get(reverse("operations-defaults-item", args=["crawl_channels", "2099-01-01T00-00-00Z"]))
            self.assertEqual(resp.status_code, 404)


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
