"""Tests for runner: task state machine, log parsing, launch/abort guards, views, and _build_args."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import skipIf
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from runner.views import UnsafeArgumentError, _build_args
from webapp.models import SearchTerm

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

    def test_keyword_fallback_ignores_channel_title(self):
        from runner.tasks import get_log_lines

        # Per-channel progress lines embed the channel's own title, which is
        # free text: a channel named "COMEDY OF ERRORS | fans" must not
        # paint its whole crawl red. Only the status after the last " | "
        # counts; lines without a title are still read in full.
        self._write_log(
            "crawl_channels",
            b"[532/1896] [id=710] COMEDY OF ERRORS | fans | fetching profile pictures\n"
            b"[532/1896] [id=710] COMEDY OF ERRORS | fans | messages processed: 120728\n"
            b"[532/1896] [id=710] COMEDY OF ERRORS | fans | completed (1 new messages, 0 downloaded images)\n"
            b"[533/1896] [id=711] Skipping Club | error fetching messages\n"
            b"[534/1896] resolving forwarded channels \xe2\x80\xa6 3/31\n",
        )
        lines, _ = get_log_lines("crawl_channels")
        self.assertEqual([line["cls"] for line in lines], ["", "", "line-success", "line-error", ""])

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

    def test_launch_points_the_command_to_a_fresh_cleanup_note(self):
        from runner.control import CLEANUP_ENV
        from runner.tasks import launch

        note = self.tmp_dir / "runner_structural_analysis.cleanup.json"
        note.write_text("{}")  # left by a run whose wrapper died too
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("runner.tasks.subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch("structural_analysis", [])
        self.assertEqual(mock_popen.call_args.kwargs["env"][CLEANUP_ENV], str(note))
        self.assertFalse(note.exists())


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

    def test_cpm_chips_default_to_auto_resolution(self):
        # LEIDEN_CPM / LEIDEN_TEMPORAL have no fixed γ: the chip's resolution input starts empty (the
        # token builder then omits it → a bare token, γ = network density) and says so.
        import html
        import re

        resp = self.client.get(reverse("operations"))
        page = resp.content.decode()
        for strategy in ("LEIDEN_CPM", "LEIDEN_TEMPORAL"):
            with self.subTest(strategy=strategy):
                match = re.search(r'data-strategy="' + strategy + r'"[^>]*data-params=\'([^\']*)\'', page)
                self.assertIsNotNone(match)
                params = {p["name"]: p for p in json.loads(html.unescape(match.group(1)))}
                self.assertEqual(params["resolution"]["default"], "")
                self.assertIn("auto", params["resolution"]["placeholder"])
                self.assertIn("density", params["resolution"]["hint"])
        self.assertNotIn("around 0.05", page)

    def test_tasks_in_workflow_order(self):
        resp = self.client.get(reverse("operations"))
        names = [t["name"] for t in resp.context["tasks"]]
        self.assertLess(names.index("search_channels"), names.index("crawl_channels"))
        self.assertLess(names.index("crawl_channels"), names.index("structural_analysis"))
        self.assertLess(names.index("structural_analysis"), names.index("compare_analysis"))

    def test_context_caps_environment_level_at_the_deepest_registered(self):
        from webapp.models import Channel

        resp = self.client.get(reverse("operations"))
        self.assertEqual(resp.context["environment_deepest"], 0)
        self.assertContains(resp, 'name="environment_depth" id="environment_depth" value="0" min="0" max="0"')
        self.assertContains(resp, "No environment has been crawled yet.")
        Channel.objects.create(telegram_id=1, title="E1", environment_depth=1)
        Channel.objects.create(telegram_id=2, title="E3", environment_depth=3)
        resp = self.client.get(reverse("operations"))
        self.assertEqual(resp.context["environment_deepest"], 3)
        self.assertContains(resp, 'max="3"')
        self.assertContains(resp, "Deepest level crawled so far: 3.")

    def test_context_contains_container_groups_with_labels_only(self):
        from webapp.models import Label, LabelGroup

        continents = LabelGroup.objects.create(name="Continent", is_container=True)
        Label.objects.create(group=continents, name="Europe")
        LabelGroup.objects.create(name="Empty container", is_container=True)  # no labels → not offered
        LabelGroup.objects.create(name="Plain group")
        resp = self.client.get(reverse("operations"))
        names = [g.name for g in resp.context["container_groups"]]
        self.assertEqual(names, ["Continent"])


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

    def test_run_rejects_option_injection_without_launching(self):
        # export_name "--pythonpath=<zip>" + dead_leaves_color "--settings=evil" would make the
        # subprocess's django.setup() import attacker code: refused as a 400, nothing launched.
        cases = [
            (
                "structural_analysis",
                {"export_name": "--pythonpath=/srv/media/others/1.zip", "dead_leaves_color": "--settings=evil"},
            ),
            ("search_channels", {"add_channels": "@fine\n--settings=evil"}),  # lines field
            ("compare_analysis", {"project_dir": "--settings=evil", "compare_target": "b"}),  # positional
            ("crawl_channels", {"filter_labels": ["--settings=evil"]}),  # forged checkbox list
        ]
        for task, data in cases:
            with (
                self.subTest(task=task),
                patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
                patch("runner.views.tasks.launch") as launch,
            ):
                resp = self.client.post(reverse("operations-run", args=[task]), data)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("must not start with '-'", resp.json()["error"])
                launch.assert_not_called()

    def test_run_rejected_injection_does_not_save_terms(self):
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch"),
        ):
            resp = self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"save_terms": "1", "extra_terms": "fine term\n--settings=evil"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(SearchTerm.objects.exists())

    def test_run_accepts_negative_channel_id(self):
        # A bare negative number (a -100… channel id) is a legitimate leading-dash value.
        with (
            patch("runner.views.tasks.get_status", return_value={"status": "idle"}),
            patch("runner.views.tasks.launch") as launch,
        ):
            resp = self.client.post(
                reverse("operations-run", args=["search_channels"]),
                {"add_channels": "-1001234567890"},
            )
        self.assertEqual(resp.status_code, 200)
        launch.assert_called_once_with("search_channels", ["--add-channel", "-1001234567890"])

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

    def test_run_rejects_non_numeric_download_timeout(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["crawl_channels"]),
                {"download_timeout": "abc"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Download timeout", resp.json()["error"])

    def test_run_rejects_negative_download_timeout(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["crawl_channels"]),
                {"download_timeout": "-5"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Download timeout", resp.json()["error"])

    def test_run_rejects_negative_structural_environment_depth(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["structural_analysis"]),
                {"graph": "on", "environment_depth": "-1"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Environment level", resp.json()["error"])

    def test_run_rejects_structural_public_url_without_scheme(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["structural_analysis"]),
                {"graph": "on", "seo": "on", "public_url": "example.org/report"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Public URL", resp.json()["error"])

    def test_run_rejects_structural_near_copy_threshold_above_one(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["structural_analysis"]),
                {"graph": "on", "near_copy_edges": "on", "near_copy_threshold": "1.5"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Near-copy similarity", resp.json()["error"])

    def test_run_rejects_structural_image_copy_distance_outside_64_bits(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["structural_analysis"]),
                {"graph": "on", "image_copy_edges": "on", "image_copy_distance": "65"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Image-copy distance", resp.json()["error"])

    def test_structural_image_copy_and_links_flags(self):
        args = _build_args(
            "structural_analysis", FakePost({"image_copy_edges": "on", "image_copy_distance": "4", "links": "on"})
        )
        self.assertIn("--image-copy-edges", args)
        self.assertEqual(args[args.index("--image-copy-distance") + 1], "4")
        self.assertIn("--links", args)
        self.assertIn("--no-links", _build_args("structural_analysis", FakePost()))

    def test_structural_audience_flag(self):
        self.assertIn("--audience", _build_args("structural_analysis", FakePost({"audience": "on"})))
        # An unchecked box must beat the on-by-default option.
        self.assertIn("--no-audience", _build_args("structural_analysis", FakePost()))

    def test_run_rejects_structural_environment_level_deeper_than_crawled(self):
        from webapp.models import Channel

        Channel.objects.create(telegram_id=1, title="E1", environment_depth=1)
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["structural_analysis"]),
                {"graph": "on", "environment_depth": "2"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("exceeds the deepest level crawled so far (1)", resp.json()["error"])

    def test_run_rejects_non_numeric_environment_depth(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["crawl_channels"]),
                {"environment": "on", "environment_depth": "deep"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Environment depth", resp.json()["error"])

    def test_run_rejects_zero_environment_depth(self):
        with patch("runner.views.tasks.get_status", return_value={"status": "idle"}):
            resp = self.client.post(
                reverse("operations-run", args=["crawl_channels"]),
                {"environment": "on", "environment_depth": "0"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Environment depth", resp.json()["error"])


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
                "community_backbone_alpha": "0.05",
            },
        )
        self.assertEqual(resp.status_code, 200)
        cmd = resp.json()["command"]
        self.assertTrue(cmd.startswith("python manage.py structural_analysis"))
        self.assertIn("--graph-2d", cmd)
        self.assertIn("--html", cmd)
        self.assertIn("--mentions", cmd)
        self.assertIn("--community-strategies LEIDEN", cmd)
        self.assertIn("--community-backbone-alpha 0.05", cmd)

    def test_structural_accepts_sbm_weights_and_refine_params(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["SBM(mode=NESTED,weights=POISSON,refine=MCMC)", "SBM(mode=FLAT)"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SBM(mode=NESTED,weights=POISSON,refine=MCMC)", resp.json()["command"])

    def test_structural_rejects_bad_sbm_weights_value(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["SBM(weights=GAMMA)"]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Community strategies", resp.json()["error"])

    def test_structural_rejects_temporal_without_timeline(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["LEIDEN", "LEIDEN_TEMPORAL"]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("timeline", resp.json()["error"])

    def test_structural_rejects_temporal_with_sliding_window(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={
                "community_strategies": ["LEIDEN", "LEIDEN_TEMPORAL"],
                "timeline_step": "quarter",
                "timeline_window": "12",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("disjoint periods", resp.json()["error"])

    def test_structural_accepts_temporal_with_timeline(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={
                "community_strategies": ["LEIDEN", "LEIDEN_TEMPORAL(resolution=0.05,interslice=1.0)"],
                "timeline_step": "quarter",
            },
        )
        self.assertEqual(resp.status_code, 200)
        cmd = resp.json()["command"]
        self.assertIn("LEIDEN_TEMPORAL(resolution=0.05,interslice=1.0)", cmd)
        self.assertIn("--timeline-step quarter", cmd)

    def test_structural_accepts_sbm_assortative(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["SBM_ASSORTATIVE(refine=MCMC)", "SBM_ASSORTATIVE"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SBM_ASSORTATIVE(refine=MCMC)", resp.json()["command"])

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

    def test_rejects_option_injection(self):
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"export_name": "--settings=evil"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("export_name", resp.json()["error"])

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

    def test_structural_accepts_bare_and_auto_cpm(self):
        # A bare LEIDEN_CPM (γ = network density) rides to the CLI as a bare token; ``resolution=auto``
        # is the same instance, so listing both is a duplicate.
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["LEIDEN_CPM", "LEIDEN_CPM(resolution=0.05)"]},
        )
        self.assertEqual(resp.status_code, 200)
        cmd = resp.json()["command"]
        self.assertIn("LEIDEN_CPM,LEIDEN_CPM(resolution=0.05)", cmd)
        self.assertNotIn("--leiden-cpm-resolution", cmd)
        resp = self.client.post(
            reverse("operations-write-cli-command", args=["structural_analysis"]),
            data={"community_strategies": ["LEIDEN_CPM", "LEIDEN_CPM(resolution=auto)"]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Community strategies", resp.json()["error"])

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
        mock_log.assert_called_once_with("structural_analysis", 20, since=None)


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

    def test_delete_from_analysis_page_passes_csrf(self):
        # The Analysis page renders no {% csrf_token %} under WEB_ACCESS=ALL, so it must set the
        # cookie itself — otherwise its Delete button's X-CSRFToken is empty and Django 403s.
        client = self.client_class(enforce_csrf_checks=True)
        page = client.get(reverse("analysis"))
        self.assertIn("csrftoken", page.cookies)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "exports" / "doomed"
            p.mkdir(parents=True)
            (p / "summary.json").write_text("{}")
            with override_settings(BASE_DIR=Path(td)):
                resp = client.delete(
                    reverse("operations-export-detail", args=["doomed"]),
                    HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
                )
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(p.exists())


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
                "--no-hash-images",
                "--no-index-domains",
                "--no-environment",
                "--no-environment-download-images",
                "--no-environment-download-video",
                "--no-environment-download-audio",
                "--no-environment-download-stickers",
                "--no-environment-download-other-media",
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
            "hash_images": "--hash-images",
            "index_domains": "--index-domains",
        }
        for field, expected_flag in flags.items():
            with self.subTest(field=field):
                args = _build_args("crawl_channels", FakePost({field: "1"}))
                self.assertIn(expected_flag, args)

    def test_environment_flags_and_depth(self):
        args = _build_args(
            "crawl_channels",
            FakePost({"environment": "1", "environment_depth": "2", "environment_download_audio": "1"}),
        )
        non_no = [a for a in args if not a.startswith("--no-")]
        self.assertEqual(non_no, ["--environment", "--environment-depth", "2", "--environment-download-audio"])
        self.assertIn("--no-environment-download-images", args)

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

    def test_filter_labels_comma_joined(self):
        # The Scope filter checkboxes (container labels) join into one --filter-labels value.
        post = FakePost({"filter_labels": ["3", "5"]})
        args = _build_args("crawl_channels", post)
        self.assertIn("--filter-labels", args)
        self.assertEqual(args[args.index("--filter-labels") + 1], "3,5")

    def test_download_timeout_value(self):
        args = _build_args("crawl_channels", FakePost({"download_timeout": "600"}))
        self.assertIn("--download-timeout", args)
        self.assertEqual(args[args.index("--download-timeout") + 1], "600")


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
    def test_filter_labels_comma_joined(self):
        # The Scope filter checkboxes (container labels) join into one --filter-labels value.
        post = FakePost({"filter_labels": ["3", "5"]})
        args = _build_args("structural_analysis", post)
        self.assertIn("--filter-labels", args)
        self.assertEqual(args[args.index("--filter-labels") + 1], "3,5")

    def test_no_filter_labels_when_none_selected(self):
        self.assertNotIn("--filter-labels", _build_args("structural_analysis", FakePost()))

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
            "--no-dominance",
            "--no-include-lost",
            "--no-include-private",
            "--no-robustness",
        ):
            self.assertIn(negation, args)

    def test_inference_flags(self):
        # The dyadic regression and the dyadic export are bool_explicit toggles; the permutation count a value.
        args_off = _build_args("structural_analysis", FakePost())
        self.assertIn("--no-mrqap", args_off)
        self.assertIn("--no-dyadic-export", args_off)
        self.assertNotIn("--mrqap-permutations", args_off)
        args_on = _build_args(
            "structural_analysis",
            FakePost(
                {
                    "mrqap": "on",
                    "mrqap_permutations": "500",
                    "dyadic_export": "on",
                    "network_stat_groups": ["HOMOPHILY", "SIGNIFICANCE"],
                }
            ),
        )
        self.assertIn("--mrqap", args_on)
        self.assertIn("--dyadic-export", args_on)
        self.assertEqual(args_on[args_on.index("--mrqap-permutations") + 1], "500")
        self.assertEqual(args_on[args_on.index("--network-stat-groups") + 1], "HOMOPHILY,SIGNIFICANCE")

    def test_public_url_value_flag(self):
        self.assertNotIn("--public-url", _build_args("structural_analysis", FakePost()))
        args = _build_args("structural_analysis", FakePost({"public_url": " https://example.org/report/ "}))
        self.assertEqual(args[args.index("--public-url") + 1], "https://example.org/report/")

    def test_environment_depth_value_flag(self):
        self.assertNotIn("--environment-depth", _build_args("structural_analysis", FakePost()))
        args = _build_args("structural_analysis", FakePost({"environment_depth": "2"}))
        idx = args.index("--environment-depth")
        self.assertEqual(args[idx + 1], "2")

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

    def test_label_groups_merge_into_community_strategies(self):
        # The dedicated "Label groups" field and the algorithmic Community strategies share one
        # --community-strategies value; the manual partitions lead (matching community.py ALL order).
        post = FakePost({"label_groups": ["LABELGROUP1"], "community_strategies": ["LEIDEN", "LEIDEN_DIRECTED"]})
        args = _build_args("structural_analysis", post)
        idx = args.index("--community-strategies")
        self.assertEqual(args[idx + 1], "LABELGROUP1,LEIDEN,LEIDEN_DIRECTED")

    def test_label_groups_only_still_emit_community_strategies(self):
        # Selecting only label groups (no algorithmic strategy) must still pass the flag.
        post = FakePost({"label_groups": ["LABELGROUP1"]})
        args = _build_args("structural_analysis", post)
        self.assertIn("--community-strategies", args)
        self.assertEqual(args[args.index("--community-strategies") + 1], "LABELGROUP1")

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

    def test_timeline_step_and_window(self):
        args = _build_args("structural_analysis", FakePost({"timeline_step": "month", "timeline_window": "6"}))
        self.assertEqual(args[args.index("--timeline-step") + 1], "month")
        self.assertEqual(args[args.index("--timeline-window") + 1], "6")
        self.assertNotIn("--timeline-window", _build_args("structural_analysis", FakePost({"timeline_step": "year"})))

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
# runner/views.py — _build_args: option injection through form values
# ---------------------------------------------------------------------------


class BuildArgsOptionInjectionTests(TestCase):
    # Django's ManagementUtility honours --settings / --pythonpath from any argv position before
    # the command's argparse runs, so no form value may become an argv element spelling an option.

    def test_dash_values_refused_in_every_free_text_kind(self) -> None:
        cases = [
            ("structural_analysis", {"export_name": "--pythonpath=/srv/media/others/1.zip"}),  # value
            ("structural_analysis", {"dead_leaves_color": "--settings=evil"}),  # value
            ("structural_analysis", {"measures": ["--settings=evil"]}),  # csv
            ("structural_analysis", {"layouts_2d": ["--settings=evil"]}),  # csv_unique
            ("structural_analysis", {"label_groups": ["--settings=evil"]}),  # community_strategies
            ("structural_analysis", {"robustness_strategies": ["--settings=evil"]}),  # robustness_strategies
            ("crawl_channels", {"filter_labels": ["--settings=evil"]}),  # csv (forged checkbox list)
            ("search_channels", {"extra_terms": "--settings=evil"}),  # extra_terms
            ("search_channels", {"add_channels": "@fine\n--settings=evil"}),  # lines
            ("compare_analysis", {"project_dir": "--settings=evil"}),  # positional
            ("compare_analysis", {"project_dir": "-x"}),  # short-option spelling
        ]
        for task, post in cases:
            with self.subTest(task=task, post=post), self.assertRaises(UnsafeArgumentError) as ctx:
                _build_args(task, FakePost(post))
            self.assertIn("must not start with '-'", str(ctx.exception))

    def test_negative_numbers_and_id_ranges_still_pass(self) -> None:
        args = _build_args("search_channels", FakePost({"add_channels": "-1001234567890"}))
        self.assertEqual(args, ["--add-channel", "-1001234567890"])
        args = _build_args("structural_analysis", FakePost({"robustness_seed": "-1", "near_copy_threshold": "-0.5"}))
        self.assertEqual(args[args.index("--robustness-seed") + 1], "-1")
        self.assertEqual(args[args.index("--near-copy-threshold") + 1], "-0.5")
        for ids in ("-30", "-30, 50-80", "-30,50-80"):
            with self.subTest(ids=ids):
                args = _build_args("crawl_channels", FakePost({"ids": ids}))
                self.assertEqual(args[args.index("--ids") + 1], ids)

    def test_dash_inside_a_value_is_harmless(self) -> None:
        # Only a *leading* dash makes argparse read an element as an option.
        args = _build_args("structural_analysis", FakePost({"export_name": "run-2026--settings=x"}))
        self.assertEqual(args[args.index("--name") + 1], "run-2026--settings=x")


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

    def test_crawl_environment_round_trip(self) -> None:
        # Saved under [environment] and projected back onto the form by the load endpoint.
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["crawl_channels"]),
                data={
                    "title": "With environment",
                    "environment": "on",
                    "environment_depth": "3",
                    "environment_download_stickers": "on",
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-crawl")
            env_section = content.split("[environment]", 1)[-1].split("\n[", 1)[0]
            self.assertIn("enabled = true", env_section)
            self.assertIn("depth = 3", env_section)
            self.assertIn("stickers = true", env_section)
            self.assertIn("images = false", env_section)
            item_id = resp.json()["item"]["id"]
            loaded = self.client.get(reverse("operations-defaults-item", args=["crawl_channels", item_id]))
            self.assertEqual(loaded.status_code, 200)
            form = loaded.json()["values"]
            self.assertTrue(form["environment"])
            self.assertEqual(form["environment_depth"], 3)
            self.assertTrue(form["environment_download_stickers"])
            self.assertFalse(form["environment_download_images"])

    def test_structural_environment_depth_round_trip(self) -> None:
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "env", "graph": "on", "environment_depth": "2"},
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn("environment_depth = 2", content.split("[scope]", 1)[-1].split("\n[", 1)[0])
            item_id = resp.json()["item"]["id"]
            loaded = self.client.get(reverse("operations-defaults-item", args=["structural_analysis", item_id]))
            self.assertEqual(loaded.json()["values"]["environment_depth"], 2)

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
                    "timeline_step": "quarter",
                    "timeline_window": "12",
                    "robustness_strategies": ["pagerank", "random"],
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn("graph = true", content)
            self.assertIn("fa2_iterations = 3000", content)
            # Measure tokens are saved verbatim, including per-instance parameters.
            self.assertIn('selected = ["PAGERANK", "DIFFUSIONLAG(window=60)"]', content)
            self.assertIn('timeline_step = "quarter"', content)
            self.assertIn("timeline_window = 12", content)
            self.assertIn('strategies = ["pagerank", "random"]', content)
            self.assertNotIn("enabled", content.split("[robustness]", 1)[-1].split("[", 1)[0])

    def test_robustness_strategies_empty_when_none_ticked(self) -> None:
        # `robustness.enabled` is not written — SA_ROBUSTNESS is derived
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

    def test_community_backbone_alpha_round_trip(self) -> None:
        # Saved under [communities] and projected back onto the form by the load endpoint.
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={"title": "t", "community_backbone_alpha": "0.05", "graph": "on"},
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn("backbone_alpha = 0.05", content.split("[communities]", 1)[-1])

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
        # MODULEROLE basis is free-form (it may name a LABELGROUP), so an unknown basis is
        # caught by settings validation: it must be one of the selected community strategies.
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
            self.assertIn("must be one of the selected community strategies", resp.json()["error"])

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
        # Consensus matrix needs ≥2 non-metadata strategies; a LABELGROUP metadata partition
        # (the ORGANIZATION successor) doesn't count, so LABELGROUP1 + LEIDEN is too thin.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "thin-consensus",
                    "consensus_matrix": "on",
                    "community_strategies": ["LABELGROUP1", "LEIDEN"],  # only 1 non-metadata
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

    def test_save_rejects_consensus_matrix_counting_kcore(self) -> None:
        # KCORE is a shell decomposition the matrix excludes, so LEIDEN + KCORE is still too thin.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "kcore-consensus",
                    "consensus_matrix": "on",
                    "community_strategies": ["LEIDEN", "KCORE"],
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Consensus matrix requires", resp.json()["error"])

    def test_save_rejects_consensus_strategy_with_few_inputs(self) -> None:
        # The CONSENSUS strategy aggregates the other algorithmic partitions; KCORE and another
        # CONSENSUS instance don't count as inputs.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "thin-consensus-strategy",
                    "community_strategies": ["LEIDEN", "KCORE", "CONSENSUS"],
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Consensus strategy requires", resp.json()["error"])

    def test_save_accepts_consensus_strategy_with_two_inputs(self) -> None:
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "ok-consensus-strategy",
                    "community_strategies": ["LEIDEN", "LOUVAIN", "CONSENSUS(threshold=0.75)"],
                },
            )
            self.assertEqual(resp.status_code, 200)

    def test_save_persists_label_groups_separately(self) -> None:
        # The "Label groups" field is stored under communities.label_groups, not folded into
        # communities.strategies, so the two selectors round-trip independently. (The seed migration
        # creates a primary partition LabelGroup at pk=1, so LABELGROUP1 is a valid token.)
        with _RedirectConfigPathsForRunner() as tmp:
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "with-label-group",
                    "label_groups": ["LABELGROUP1"],
                    "community_strategies": ["LEIDEN_DIRECTED"],
                },
            )
            self.assertEqual(resp.status_code, 200)
            content = _saved_file_content(tmp, ".operations-structural")
            self.assertIn('label_groups = ["LABELGROUP1"]', content)
            self.assertIn('strategies = ["LEIDEN_DIRECTED"]', content)

    def test_save_consensus_matrix_counts_label_groups_as_metadata(self) -> None:
        # A label group selected in its own field is still a metadata partition, so it doesn't count
        # toward the ≥2 algorithmic strategies the consensus matrix needs — proving the validator
        # reads label_groups together with community_strategies.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "thin-consensus-lg",
                    "consensus_matrix": "on",
                    "label_groups": ["LABELGROUP1"],
                    "community_strategies": ["LEIDEN"],  # only 1 algorithmic strategy
                },
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Consensus matrix requires", resp.json()["error"])

    def test_save_accepts_module_role_basis_on_selected_label_group(self) -> None:
        # A MODULEROLE basis may name a label group selected in the "Label groups" field; the
        # basis-in-selected-strategies check must therefore see label_groups too.
        with _RedirectConfigPathsForRunner():
            resp = self.client.post(
                reverse("operations-defaults", args=["structural_analysis"]),
                data={
                    "title": "role-on-label-group",
                    "measures": ["MODULEROLE(basis=LABELGROUP1)"],
                    "label_groups": ["LABELGROUP1"],
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


# ---------------------------------------------------------------------------
# Pause: runner/tasks.py state + requests, runner/views.py endpoints
# ---------------------------------------------------------------------------


class PauseStateTests(_TmpMixin, TestCase):
    def _running(self, task: str = "crawl_channels") -> None:
        import os

        _write_meta(self.tmp_dir, task, pid=os.getpid())

    def _touch(self, task: str, suffix: str) -> None:
        (self.tmp_dir / f"runner_{task}{suffix}").touch()

    def _pause(self, task: str = "crawl_channels") -> str:
        from runner.tasks import get_status

        return get_status(task)["pause"]

    def test_idle_task_has_no_pause(self):
        self.assertEqual(self._pause(), "none")

    def test_running_without_files_is_none(self):
        self._running()
        self.assertEqual(self._pause(), "none")

    def test_request_file_alone_is_requested(self):
        self._running()
        self._touch("crawl_channels", ".pause")
        self.assertEqual(self._pause(), "requested")

    def test_both_files_is_paused(self):
        self._running()
        self._touch("crawl_channels", ".pause")
        self._touch("crawl_channels", ".paused")
        self.assertEqual(self._pause(), "paused")

    def test_paused_file_without_request_is_resuming(self):
        self._running()
        self._touch("crawl_channels", ".paused")
        self.assertEqual(self._pause(), "resuming")

    def test_finished_run_ignores_leftover_files(self):
        _write_meta(self.tmp_dir, "crawl_channels", exit_code=143)
        self._touch("crawl_channels", ".pause")
        self._touch("crawl_channels", ".paused")
        self.assertEqual(self._pause(), "none")

    def test_non_pausable_task_ignores_files(self):
        self._running("structural_analysis")
        self._touch("structural_analysis", ".pause")
        self.assertEqual(self._pause("structural_analysis"), "none")


class PauseRequestTests(_TmpMixin, TestCase):
    def _request(self, task: str = "crawl_channels") -> Path:
        return self.tmp_dir / f"runner_{task}.pause"

    def test_request_on_running_task_creates_the_file(self):
        import os

        from runner.tasks import request_pause

        _write_meta(self.tmp_dir, "crawl_channels", pid=os.getpid())
        self.assertTrue(request_pause("crawl_channels"))
        self.assertTrue(self._request().exists())

    def test_request_on_finished_task_is_refused(self):
        from runner.tasks import request_pause

        _write_meta(self.tmp_dir, "crawl_channels", exit_code=0)
        self.assertFalse(request_pause("crawl_channels"))
        self.assertFalse(self._request().exists())

    def test_request_on_non_pausable_task_is_refused(self):
        import os

        from runner.tasks import request_pause

        _write_meta(self.tmp_dir, "structural_analysis", pid=os.getpid())
        self.assertFalse(request_pause("structural_analysis"))
        self.assertFalse(self._request("structural_analysis").exists())

    def test_cancel_removes_the_request(self):
        from runner.tasks import cancel_pause

        self._request().touch()
        self.assertTrue(cancel_pause("crawl_channels"))
        self.assertFalse(self._request().exists())

    def test_cancel_without_request_returns_false(self):
        from runner.tasks import cancel_pause

        self.assertFalse(cancel_pause("crawl_channels"))

    def test_cancel_leaves_the_paused_file_to_the_command(self):
        from runner.tasks import cancel_pause

        self._request().touch()
        paused = self.tmp_dir / "runner_crawl_channels.paused"
        paused.touch()
        cancel_pause("crawl_channels")
        self.assertTrue(paused.exists())  # the command removes it once it has reconnected

    def test_reset_clears_pause_files(self):
        from runner.tasks import reset

        _write_meta(self.tmp_dir, "crawl_channels", exit_code=143)
        self._request().touch()
        (self.tmp_dir / "runner_crawl_channels.paused").touch()
        self.assertTrue(reset("crawl_channels"))
        self.assertEqual(list(self.tmp_dir.glob("runner_crawl_channels.paus*")), [])

    def test_launch_clears_stale_files_and_passes_their_paths(self):
        from runner.control import PAUSE_REQUEST_ENV, PAUSED_ENV
        from runner.tasks import launch

        self._request().touch()
        (self.tmp_dir / "runner_crawl_channels.paused").touch()
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("runner.tasks.subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch("crawl_channels", [])
        self.assertEqual(list(self.tmp_dir.glob("runner_crawl_channels.paus*")), [])
        env = mock_popen.call_args.kwargs["env"]
        self.assertEqual(env[PAUSE_REQUEST_ENV], str(self._request()))
        self.assertEqual(env[PAUSED_ENV], str(self.tmp_dir / "runner_crawl_channels.paused"))

    def test_launch_of_non_pausable_task_passes_no_paths(self):
        import os

        from runner.control import PAUSE_REQUEST_ENV
        from runner.tasks import launch

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        environ = {k: v for k, v in os.environ.items() if k != PAUSE_REQUEST_ENV}
        with (
            patch.dict("os.environ", environ, clear=True),
            patch("runner.tasks.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            launch("structural_analysis", [])
        self.assertNotIn(PAUSE_REQUEST_ENV, mock_popen.call_args.kwargs["env"])


class PauseViewTests(TestCase):
    def test_unknown_task_returns_404(self):
        for name in ("operations-pause", "operations-pause-cancel"):
            resp = self.client.post(reverse(name, args=["no_such_task"]))
            self.assertEqual(resp.status_code, 404)

    def test_non_pausable_task_returns_400(self):
        for name in ("operations-pause", "operations-pause-cancel"):
            resp = self.client.post(reverse(name, args=["structural_analysis"]))
            self.assertEqual(resp.status_code, 400)

    def test_request_returns_the_new_state(self):
        with (
            patch("runner.views.tasks.request_pause", return_value=True),
            patch("runner.views.tasks.get_status", return_value={"pause": "requested"}),
        ):
            resp = self.client.post(reverse("operations-pause", args=["crawl_channels"]))
        self.assertEqual(resp.json(), {"requested": True, "pause": "requested"})

    def test_cancel_returns_the_new_state(self):
        with (
            patch("runner.views.tasks.cancel_pause", return_value=True),
            patch("runner.views.tasks.get_status", return_value={"pause": "resuming"}),
        ):
            resp = self.client.post(reverse("operations-pause-cancel", args=["search_channels"]))
        self.assertEqual(resp.json(), {"cancelled": True, "pause": "resuming"})

    def test_panel_renders_pause_buttons_on_pausable_cards_only(self):
        resp = self.client.get(reverse("operations"))
        self.assertContains(resp, 'id="pause-crawl_channels"')
        self.assertContains(resp, 'id="pause-cancel-search_channels"')
        self.assertNotContains(resp, 'id="pause-structural_analysis"')

    def test_panel_badge_reads_paused(self):
        def fake_status(name):
            from runner.tasks import _idle_status

            if name == "crawl_channels":
                return {**_idle_status(), "status": "running", "pid": 1, "pause": "paused"}
            return _idle_status()

        with patch("runner.views.tasks.get_status", side_effect=fake_status):
            resp = self.client.get(reverse("operations"))
        self.assertContains(resp, 'class="ops-badge ops-badge--paused" id="badge-crawl_channels"')
        self.assertContains(resp, 'data-pause="paused" data-running="1"')


# ---------------------------------------------------------------------------
# runner/control.py — the command side
# ---------------------------------------------------------------------------


class _FakeConnections:
    def __init__(self, in_atomic_block: bool = False) -> None:
        self.closed = 0
        self._conn = MagicMock(in_atomic_block=in_atomic_block)

    def all(self, initialized_only: bool = False):
        return [self._conn]

    def close_all(self) -> None:
        self.closed += 1


class PauseGateTests(_TmpMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.request = self.tmp_dir / "req"
        self.paused = self.tmp_dir / "ack"
        self.events: list[str] = []
        self.out = MagicMock()

    def _gate(self, sleep=None):
        from runner.control import PauseGate

        return PauseGate(self.request, self.paused, stdout=self.out, sleep=sleep or self._resume_on_first_sleep)

    def _resume_on_first_sleep(self, _seconds):
        self.events.append(f"sleep paused_file={self.paused.exists()}")
        self.request.unlink()

    def _lines(self) -> str:
        return "\n".join(str(call.args[0]) for call in self.out.write.call_args_list)

    def test_disabled_gate_is_a_no_op(self):
        from runner.control import PauseGate

        gate = PauseGate()
        self.assertFalse(gate.enabled)
        with gate.holding(lambda: self.events.append("release"), lambda: None, label="x"):
            self.assertFalse(gate.checkpoint())
        self.assertEqual(gate._holds, [])
        self.assertEqual(self.events, [])

    def test_from_env(self):
        from runner.control import PAUSE_REQUEST_ENV, PAUSED_ENV, PauseGate

        with patch.dict("os.environ", {PAUSE_REQUEST_ENV: str(self.request), PAUSED_ENV: str(self.paused)}):
            gate = PauseGate.from_env()
        self.assertEqual((gate.request_path, gate.paused_path), (self.request, self.paused))
        with patch.dict("os.environ", {PAUSE_REQUEST_ENV: "", PAUSED_ENV: ""}):
            self.assertFalse(PauseGate.from_env().enabled)

    def test_no_request_does_nothing(self):
        gate = self._gate()
        fake = _FakeConnections()
        with patch("runner.control.connections", fake):
            self.assertFalse(gate.checkpoint())
        self.assertEqual(fake.closed, 0)

    def test_pause_releases_waits_and_restores(self):
        gate = self._gate()
        self.request.touch()
        fake = _FakeConnections()
        with (
            patch("runner.control.connections", fake),
            gate.holding(lambda: self.events.append("release A"), lambda: self.events.append("restore A"), label="A"),
            gate.holding(lambda: self.events.append("release B"), lambda: self.events.append("restore B"), label="B"),
        ):
            self.assertTrue(gate.checkpoint())
        # Released last-in first-out, the paused file written before the wait, restored in order.
        self.assertEqual(self.events, ["release B", "release A", "sleep paused_file=True", "restore A", "restore B"])
        self.assertEqual(fake.closed, 1)
        self.assertFalse(self.paused.exists())
        self.assertIn("Paused: released the database and A and B.", self._lines())
        self.assertIn("Resumed after", self._lines())

    def test_inside_a_transaction_waits_for_the_next_checkpoint(self):
        gate = self._gate()
        self.request.touch()
        fake = _FakeConnections(in_atomic_block=True)
        with patch("runner.control.connections", fake):
            self.assertFalse(gate.checkpoint())
        self.assertEqual(fake.closed, 0)
        self.assertFalse(self.paused.exists())
        self.assertTrue(self.request.exists())

    def test_real_atomic_block_is_detected(self):
        # TestCase wraps the test in a transaction: the real guard must refuse to close it.
        gate = self._gate()
        self.request.touch()
        SearchTerm.objects.exists()  # initialise the connection inside the test transaction
        self.assertFalse(gate.checkpoint())
        self.assertFalse(self.paused.exists())

    def test_failed_restore_stays_paused_until_the_next_resume(self):
        attempts = []

        def restore():
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("network down")

        def sleep(_seconds):
            self.request.unlink()

        gate = self._gate(sleep=sleep)
        self.request.touch()
        with patch("runner.control.connections", _FakeConnections()), gate.holding(lambda: None, restore, label="T"):
            self.assertTrue(gate.checkpoint())
        self.assertEqual(len(attempts), 2)
        self.assertIn("Could not resume (network down): still paused.", self._lines())
        self.assertFalse(self.paused.exists())

    def test_abort_while_paused_removes_the_paused_file_without_restoring(self):
        def sleep(_seconds):
            raise SystemExit(143)

        gate = self._gate(sleep=sleep)
        self.request.touch()
        with (
            patch("runner.control.connections", _FakeConnections()),
            gate.holding(lambda: None, lambda: self.events.append("restore"), label="T"),
            self.assertRaises(SystemExit),
        ):
            gate.checkpoint()
        self.assertEqual(self.events, [])
        self.assertFalse(self.paused.exists())


class SigtermExitsTests(TestCase):
    def test_sigterm_raises_system_exit_and_handler_is_restored(self):
        import os
        import signal
        import time

        from runner.control import sigterm_exits

        before = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(SystemExit) as caught, sigterm_exits():
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(100):  # the handler runs at the next bytecode boundary
                time.sleep(0.01)
        self.assertEqual(caught.exception.code, 143)
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


# ---------------------------------------------------------------------------
# runner/tmp_dir.py — what writes in tmp/, and emptying it
# ---------------------------------------------------------------------------


class TmpDirTests(_TmpMixin, TestCase):
    def setUp(self):
        super().setUp()
        # exports/ under a throwaway BASE_DIR: never the real one.
        self._base = tempfile.TemporaryDirectory()
        self.exports_dir = Path(self._base.name) / "exports"
        self.exports_dir.mkdir()
        self._base_dir = override_settings(BASE_DIR=Path(self._base.name))
        self._base_dir.enable()

    def tearDown(self):
        self._base_dir.disable()
        self._base.cleanup()
        super().tearDown()

    def _old(self, path: Path) -> Path:
        """Backdate an entry past the fresh-crawl grace period."""
        import os
        import time

        old = time.time() - 3600
        os.utime(path, (old, old), follow_symlinks=False)
        return path

    def _leftover_crawl(self, name: str = "crawl_channels_dead") -> Path:
        folder = self.tmp_dir / name
        folder.mkdir()
        (folder / "half.jpg").write_bytes(b"x" * 100)
        (self.tmp_dir / f"{name}.lock").write_bytes(b"")  # its process is gone: nobody holds it
        self._old(self.tmp_dir / f"{name}.lock")
        return self._old(folder)

    def _groups(self, data: dict) -> dict:
        return {g["key"]: (g["entries"], g["bytes"]) for g in data["groups"]}

    def _export_dir(self, name: str, size: int = 10) -> Path:
        folder = self.exports_dir / name
        folder.mkdir()
        (folder / "summary.json").write_bytes(b"s" * size)
        return self._old(folder)

    def test_lock_is_seen_while_held_and_removed_after(self):
        from runner.tmp_dir import held_lock, is_locked

        lock = self.tmp_dir / "x.lock"
        self.assertFalse(is_locked(lock))
        with held_lock(lock):
            self.assertTrue(is_locked(lock))
        self.assertFalse(lock.exists())
        self.assertFalse(is_locked(lock))

    def test_crawl_download_dir_is_locked_for_the_run_and_removed_after(self):
        from runner.tmp_dir import crawl_download_dir, is_locked

        with crawl_download_dir() as path:
            folder = Path(path)
            self.assertEqual(folder.parent, self.tmp_dir)
            self.assertTrue(folder.name.startswith("crawl_channels_"))
            self.assertTrue(is_locked(Path(path + ".lock")))
        self.assertEqual(list(self.tmp_dir.iterdir()), [])

    def test_scan_groups_the_entries(self):
        from runner.tmp_dir import scan

        self._leftover_crawl()
        (self.tmp_dir / "runner_crawl_channels.log").write_bytes(b"y" * 10)
        (self.tmp_dir / "stray.txt").write_bytes(b"z" * 3)
        data = scan()
        groups = self._groups(data)
        self.assertEqual(groups["crawl"], (2, 100))  # the folder and its dead lock
        self.assertEqual(groups["tasks"], (1, 10))
        self.assertEqual(groups["other"], (1, 3))
        self.assertEqual(data["total_bytes"], 113)
        self.assertEqual(data["blockers"], [])
        self.assertTrue(data["clearable"])

    def test_empty_folder_is_not_clearable(self):
        from runner.tmp_dir import scan

        self.assertFalse(scan()["clearable"])

    def test_running_panel_task_blocks(self):
        import os

        from runner.tmp_dir import scan

        self._leftover_crawl()
        _write_meta(self.tmp_dir, "structural_analysis", pid=os.getpid())
        data = scan()
        self.assertEqual(data["blockers"], ["Structural Analysis is running in the Operations panel."])
        self.assertFalse(data["clearable"])

    def test_terminal_crawl_blocks(self):
        from runner.tmp_dir import held_lock, scan

        folder = self.tmp_dir / "crawl_channels_live"
        folder.mkdir()
        self._old(folder)  # old enough that only the lock says it is in use
        with held_lock(self.tmp_dir / "crawl_channels_live.lock"):
            data = scan()
        self.assertEqual(self._groups(data)["crawl_active"][0], 2)
        self.assertEqual(
            data["blockers"],
            [f"A crawl started from a terminal is downloading into {self.tmp_dir.name}/crawl_channels_live/."],
        )
        self.assertFalse(data["clearable"])

    def test_a_just_created_crawl_folder_counts_as_in_use(self):
        from runner.tmp_dir import scan

        (self.tmp_dir / "crawl_channels_new").mkdir()  # its run may not have taken the lock yet
        self.assertEqual(self._groups(scan())["crawl_active"][0], 1)

    def test_clear_refuses_while_in_use(self):
        import os

        from runner.tmp_dir import TmpInUseError, clear

        self._leftover_crawl()
        _write_meta(self.tmp_dir, "crawl_channels", pid=os.getpid())
        with self.assertRaises(TmpInUseError) as caught:
            clear()
        self.assertEqual(caught.exception.blockers, ["Crawl Channels is running in the Operations panel."])
        self.assertTrue((self.tmp_dir / "crawl_channels_dead").exists())

    def test_clear_empties_the_folder_and_keeps_it(self):
        from runner.tmp_dir import clear

        self._leftover_crawl()
        _write_meta(self.tmp_dir, "crawl_channels", exit_code=0)
        (self.tmp_dir / "runner_crawl_channels.log").write_bytes(b"y" * 10)
        report = clear()
        self.assertEqual(list(self.tmp_dir.iterdir()), [])
        self.assertTrue(self.tmp_dir.is_dir())
        self.assertEqual(report.removed_entries, 4)
        self.assertGreaterEqual(report.freed_bytes, 110)
        self.assertEqual(report.errors, [])

    def test_clear_unlinks_a_symlink_without_following_it(self):
        from runner.tmp_dir import clear

        with tempfile.TemporaryDirectory() as outside:
            kept = Path(outside) / "keep.txt"
            kept.write_text("mine")
            (self.tmp_dir / "link").symlink_to(outside, target_is_directory=True)
            clear()
            self.assertTrue(kept.exists())
        self.assertFalse((self.tmp_dir / "link").exists())

    def test_clear_empties_the_page_cache_through_the_cache_api(self):
        from django.core.cache import caches

        from runner.tmp_dir import clear, scan

        location = self.tmp_dir / "django-cache"
        file_cache = {
            "default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": str(location)}
        }
        with override_settings(CACHES=file_cache):
            caches["default"].set("k", "v")
            self.assertEqual(self._groups(scan())["cache"][0], 1)
            report = clear()
            self.assertIsNone(caches["default"].get("k"))
        self.assertTrue(report.cache_cleared)
        self.assertTrue(location.is_dir())  # emptied, not removed: a write in flight still finds it

    def test_launches_wait_while_tmp_is_emptied(self):
        from runner import tasks

        with tasks.launches_held():
            self.assertTrue(all(lock.locked() for lock in tasks._LAUNCH_LOCKS.values()))
        self.assertFalse(any(lock.locked() for lock in tasks._LAUNCH_LOCKS.values()))

    def test_lock_held_elsewhere_is_waited_for_then_refused(self):
        import threading
        import time

        from runner.tmp_dir import LockHeldError, held_lock, is_locked

        lock = self.tmp_dir / "x.lock"
        with held_lock(lock), self.assertRaises(LockHeldError):
            with held_lock(lock, wait=0):
                pass
        # A holder letting go within the wait (Maintenance probing it) is waited for, and the
        # waiter ends up holding the file that is there, not the one its holder removed.
        released = threading.Event()

        def hold_briefly():
            with held_lock(lock):
                released.wait(0.2)

        holder = threading.Thread(target=hold_briefly)
        holder.start()
        time.sleep(0.05)
        with held_lock(lock, wait=2):
            self.assertTrue(is_locked(lock))
        holder.join()
        self.assertFalse(lock.exists())

    def test_scan_lists_what_stopped_analyses_left_in_exports(self):
        from runner.tmp_dir import scan

        self._export_dir("published", size=7)  # an export: never listed
        self._export_dir("published.old", size=5)  # its backup, left by a run killed while publishing
        self._export_dir("killed.tmp", size=3)
        (self.exports_dir / "killed.lock").write_bytes(b"")
        self._old(self.exports_dir / "killed.lock")
        self._export_dir("halfway.old", size=2)  # its export is missing: put back, not deleted
        (self.exports_dir / "notes.txt").write_text("not ours")
        data = scan()
        groups = self._groups(data)
        self.assertEqual(groups["exports"], (3, 8))  # published.old, killed.tmp, killed.lock
        self.assertEqual(groups["exports_restore"], (1, 2))
        self.assertEqual(groups["exports_active"], (0, 0))
        self.assertEqual(data["total_bytes"], 10)
        self.assertTrue(data["clearable"])

    def test_running_analysis_keeps_its_folders_without_blocking(self):
        from runner.tmp_dir import clear, export_in_progress, scan

        self._export_dir("stale.tmp")
        with export_in_progress("live"):
            self._export_dir("live.tmp")
            data = scan()
            self.assertEqual(self._groups(data)["exports_active"][0], 2)  # its staging and its lock
            self.assertEqual(data["blockers"], [])
            self.assertTrue(data["clearable"])
            report = clear()
            self.assertTrue((self.exports_dir / "live.tmp" / "summary.json").exists())
            self.assertFalse((self.exports_dir / "stale.tmp").exists())
            self.assertEqual(sorted(report.skipped), ["exports/live.lock", "exports/live.tmp"])
        self.assertFalse((self.exports_dir / "live.lock").exists())

    def test_only_a_running_analysis_is_nothing_to_delete(self):
        from runner.tmp_dir import export_in_progress, scan

        with export_in_progress("live"):
            self._export_dir("live.tmp")
            self.assertFalse(scan()["clearable"])

    def test_a_just_created_staging_folder_counts_as_in_use(self):
        from runner.tmp_dir import scan

        (self.exports_dir / "new.tmp").mkdir()
        self.assertEqual(self._groups(scan())["exports_active"][0], 1)

    def test_clear_removes_the_leftovers_and_puts_a_half_replaced_export_back(self):
        from runner.tmp_dir import clear

        self._export_dir("published")
        self._export_dir("published.old")
        self._export_dir("killed.tmp")
        (self.exports_dir / "killed.lock").write_bytes(b"")
        self._old(self.exports_dir / "killed.lock")
        self._export_dir("halfway.old")
        self._export_dir("halfway.tmp")  # the new export it was publishing: dropped, as the next run would
        (self.exports_dir / "notes.txt").write_text("not ours")
        report = clear()
        self.assertEqual(sorted(p.name for p in self.exports_dir.iterdir()), ["halfway", "notes.txt", "published"])
        self.assertTrue((self.exports_dir / "halfway" / "summary.json").exists())
        self.assertEqual(report.restored, ["halfway"])
        self.assertEqual(report.removed_entries, 4)
        self.assertEqual(report.freed_bytes, 30)
        self.assertEqual((report.skipped, report.errors), ([], []))

    def test_clear_refusal_keeps_the_exports_leftovers(self):
        import os

        from runner.tmp_dir import TmpInUseError, clear

        self._export_dir("killed.tmp")
        _write_meta(self.tmp_dir, "structural_analysis", pid=os.getpid())
        with self.assertRaises(TmpInUseError):
            clear()
        self.assertTrue((self.exports_dir / "killed.tmp").exists())

    def test_a_lock_taken_meanwhile_is_kept(self):
        from runner.tmp_dir import _remove_lock, held_lock

        lock = self.exports_dir / "live.lock"
        with held_lock(lock):
            self.assertFalse(_remove_lock(lock))
            self.assertTrue(lock.exists())
        lock.write_bytes(b"")
        self.assertTrue(_remove_lock(lock))
        self.assertFalse(lock.exists())

    def test_export_staging_goes_however_the_run_ends(self):
        from runner.tmp_dir import export_in_progress

        staging = self.exports_dir / "run.tmp"
        backup = self._export_dir("run.old")  # possibly the only published copy: never deleted here
        with export_in_progress("run"):
            staging.mkdir()
        self.assertFalse(staging.exists())
        with self.assertRaises(KeyboardInterrupt), export_in_progress("run"):
            staging.mkdir()
            raise KeyboardInterrupt
        self.assertFalse(staging.exists())
        self.assertTrue(backup.exists())
        self.assertEqual(sorted(p.name for p in self.exports_dir.iterdir()), ["run.old"])

    def test_the_cleanup_note_names_the_staging_while_the_run_lives(self):
        import os

        from runner.control import CLEANUP_ENV
        from runner.tmp_dir import export_in_progress

        note = self.tmp_dir / "runner_structural_analysis.cleanup.json"
        with patch.dict(os.environ, {CLEANUP_ENV: str(note)}), export_in_progress("run"):
            self.assertEqual(
                json.loads(note.read_text()),
                {"lock": str(self.exports_dir / "run.lock"), "remove": [str(self.exports_dir / "run.tmp")]},
            )
        self.assertFalse(note.exists())


# A stand-in for structural_analysis under the panel: holds its export's lock, stages, leaves the
# cleanup note through runner.control.removed_if_killed, then waits to be aborted.
_KILLED_CHILD = """
import fcntl, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from runner.control import removed_if_killed
exports = Path(sys.argv[2])
lock, staging = exports / "run.lock", exports / "run.tmp"
if sys.argv[3] == "hold":
    handle = open(lock, "a+b")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
staging.mkdir()
(staging / "half.json").write_text("{}")
with removed_if_killed(lock, [staging]):
    time.sleep(30)
"""


@skipIf(sys.platform == "win32", "the panel's abort is a POSIX signal")
class AbortCleanupTests(_TmpMixin, TestCase):
    """The panel's wrapper deletes what an aborted command named in its cleanup note."""

    def setUp(self):
        super().setUp()
        self.exports = self.tmp_dir / "exports"
        self.exports.mkdir()
        self.note = self.tmp_dir / "runner_structural_analysis.cleanup.json"

    def _abort(self, child_holds_lock: bool = True) -> tuple[dict, str]:
        import os
        import signal
        import subprocess
        import time

        from django.conf import settings

        from runner.control import CLEANUP_ENV
        from runner.tasks import _WRAPPER_SCRIPT

        meta = self.tmp_dir / "runner_structural_analysis.meta.json"
        meta.write_text(json.dumps({"pid": None, "exit_code": None}))
        child = [sys.executable, "-c", _KILLED_CHILD, str(settings.BASE_DIR), str(self.exports)]
        child.append("hold" if child_holds_lock else "free")
        wrapper = subprocess.Popen(
            [sys.executable, "-c", _WRAPPER_SCRIPT, str(meta), *child],
            env={**os.environ, CLEANUP_ENV: str(self.note)},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 20
        while not self.note.exists():  # the child is staging
            self.assertLess(time.monotonic(), deadline, "the child never wrote its cleanup note")
            time.sleep(0.02)
        wrapper.send_signal(signal.SIGTERM)  # what runner.tasks.abort sends
        out, _ = wrapper.communicate(timeout=20)
        return json.loads(meta.read_text()), out.decode()

    def test_abort_deletes_the_staging_and_the_dead_lock(self):
        meta, log = self._abort()
        self.assertEqual(meta["exit_code"], -15)  # killed outright, as before: no unwinding
        self.assertEqual(list(self.exports.iterdir()), [])
        self.assertFalse(self.note.exists())
        self.assertIn("Removing exports/run.tmp/", log)

    def test_a_run_that_took_the_lock_over_keeps_the_folders(self):
        from runner.tmp_dir import held_lock

        with held_lock(self.exports / "run.lock"):
            _meta, log = self._abort(child_holds_lock=False)
            self.assertTrue((self.exports / "run.tmp" / "half.json").exists())
        self.assertFalse(self.note.exists())
        self.assertNotIn("Removing", log)
