import asyncio
import datetime
import io
import logging
import os
import shutil
import tempfile
import types
from dataclasses import fields
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.hole_fixer import fix_message_holes, iter_hole_ranges
from crawler.management.commands.crawl_channels import (
    _TELETHON_PKG_PATH,
    Command,
    CrawlOptions,
    ProgressPrinter,
    _make_telethon_unraisable_filter,
)
from crawler.management.commands.search_channels import parse_channel_identifier
from crawler.reference_resolver import (
    ReferenceResolver,
    extract_text_references,
    reference_from_url,
)
from webapp.models import Channel, Message
from webapp.test_helpers import make_channel, make_label
from webapp.utils.channel_types import channel_type_filter

from telethon import errors
from telethon.tl.types import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_client() -> MagicMock:
    """Return a MagicMock that looks like a TelegramAPIClient."""
    api_client = MagicMock()
    api_client.wait.return_value = None
    return api_client


def _crawl_opts(**overrides) -> CrawlOptions:
    """Build a CrawlOptions with every flag off, overriding only what a test needs.

    Every bool field defaults False; the non-bool fields take their natural
    empty default. New fields are picked up automatically (defaulted False),
    so the helper does not need touching when an option is added.
    """
    base = {f.name: False for f in fields(CrawlOptions)}
    base.update(
        refresh_limit=None,
        refresh_from=None,
        refresh_to=None,
        ids_str=None,
        channel_types=[],
        channel_sources=[],
        filter_labels=[],
    )
    base.update(overrides)
    return CrawlOptions(**base)


class BuildCrawlQsFilterLabelsTests(TestCase):
    """--filter-labels limits the crawl to channels under the selected container labels."""

    def setUp(self) -> None:
        from webapp.models import LabelGroup, LabelParent

        continents = LabelGroup.objects.create(name="Continent", is_partition=True, is_container=True)
        self.europe = make_label("Europe", is_in_target=False, group=continents)
        org_a = make_label("OrgA")
        org_b = make_label("OrgB")
        LabelParent.objects.create(label=org_a, parent=self.europe)
        self.inside = make_channel(telegram_id=1, title="Inside", label=org_a)
        self.outside = make_channel(telegram_id=2, title="Outside", label=org_b)
        self.to_inspect = Channel.objects.create(telegram_id=3, title="Inspect", to_inspect=True)

    def test_filter_limits_crawl_queryset(self) -> None:
        qs = Command()._build_crawl_qs(_crawl_opts(channel_types=["CHANNEL"], filter_labels=[self.europe.pk]))
        self.assertCountEqual(list(qs), [self.inside])

    def test_no_filter_keeps_everything(self) -> None:
        qs = Command()._build_crawl_qs(_crawl_opts(channel_types=["CHANNEL"]))
        self.assertCountEqual(list(qs), [self.inside, self.outside, self.to_inspect])

    def test_non_container_filter_label_raises_command_error(self) -> None:
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        org = make_label("Plain")
        with self.assertRaises(CommandError):
            call_command("crawl_channels", filter_labels=str(org.pk), stdout=io.StringIO(), stderr=io.StringIO())


def _make_telegram_channel(telegram_id: int = 999, username: str = "testchan") -> MagicMock:
    """Return a minimal MagicMock that can be passed to Channel.from_telegram_object."""
    tc = MagicMock()
    tc.id = telegram_id
    tc.username = username
    tc.title = f"Test Channel {telegram_id}"
    tc.date = None
    tc.broadcast = True
    tc.verified = False
    tc.megagroup = False
    tc.restricted = False
    tc.signatures = False
    tc.min = False
    tc.scam = False
    tc.has_link = False
    tc.has_geo = False
    tc.slowmode_enabled = False
    tc.fake = False
    tc.gigagroup = False
    tc.access_hash = None
    tc.noforwards = False
    tc.forum = False
    tc.join_to_send = False
    tc.join_request = False
    tc.level = None
    return tc


def _flood_error(seconds: int = 30) -> errors.rpcerrorlist.FloodWaitError:
    """Create a FloodWaitError without calling its constructor."""
    err = errors.rpcerrorlist.FloodWaitError.__new__(errors.rpcerrorlist.FloodWaitError)
    err.seconds = seconds
    return err


def _rpc_error() -> errors.RPCError:
    """Create a generic RPCError without calling its constructor."""
    err = errors.RPCError.__new__(errors.RPCError)
    err.message = "SOME_RPC_ERROR"
    return err


def _username_invalid_error() -> errors.rpcerrorlist.UsernameInvalidError:
    err = errors.rpcerrorlist.UsernameInvalidError.__new__(errors.rpcerrorlist.UsernameInvalidError)
    return err


# ---------------------------------------------------------------------------
# iter_hole_ranges
# ---------------------------------------------------------------------------


class IterHoleRangesTests(TestCase):
    def setUp(self) -> None:
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=50, label=org)

    def _create_messages(self, telegram_ids: list[int]) -> None:
        for tid in telegram_ids:
            Message.objects.create(telegram_id=tid, channel=self.channel)

    def _ranges(self, **kwargs) -> list[tuple[int, int]]:
        # iter_hole_ranges yields (start, end, prev_date, current_date); these tests assert ID ranges.
        return [(start, end) for start, end, _prev, _cur in iter_hole_ranges(self.channel, **kwargs)]

    def test_empty_channel_yields_nothing(self) -> None:
        self.assertEqual(self._ranges(), [])

    def test_single_message_yields_nothing(self) -> None:
        self._create_messages([5])
        self.assertEqual(self._ranges(), [])

    def test_consecutive_messages_yield_nothing(self) -> None:
        self._create_messages([1, 2, 3, 4, 5])
        self.assertEqual(self._ranges(), [])

    def test_single_gap_of_one_yields_correct_range(self) -> None:
        self._create_messages([1, 3])
        self.assertEqual(self._ranges(), [(2, 2)])

    def test_large_gap_yields_inclusive_range(self) -> None:
        self._create_messages([1, 10])
        self.assertEqual(self._ranges(), [(2, 9)])

    def test_multiple_gaps_yield_multiple_ranges(self) -> None:
        self._create_messages([1, 3, 6])
        self.assertEqual(self._ranges(), [(2, 2), (4, 5)])

    def test_min_telegram_id_excludes_earlier_ranges(self) -> None:
        self._create_messages([1, 3, 5, 7])  # gaps at 2, 4, 6
        result = self._ranges(min_telegram_id=5)
        self.assertEqual(result, [(6, 6)])

    def test_min_telegram_id_below_all_messages_includes_all(self) -> None:
        self._create_messages([2, 5])
        result = self._ranges(min_telegram_id=1)
        self.assertEqual(result, [(3, 4)])

    def test_returns_generator(self) -> None:
        import types

        self._create_messages([1, 3])
        self.assertIsInstance(iter_hole_ranges(self.channel), types.GeneratorType)

    def test_orm_sorts_ascending_regardless_of_insertion_order(self) -> None:
        self._create_messages([10, 5, 1])  # created in reverse order
        result = self._ranges()
        # gaps: 1→5 → (2,4), 5→10 → (6,9)
        self.assertEqual(result, [(2, 4), (6, 9)])


# ---------------------------------------------------------------------------
# fix_message_holes
# ---------------------------------------------------------------------------


class FixMessageHolesTests(TestCase):
    def setUp(self) -> None:
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=60, label=org)
        self.api_client = _make_api_client()
        self.telegram_channel = MagicMock()
        self.status_messages: list[str] = []
        # Default: get_messages returns a real message per requested ID
        self.api_client.client.get_messages.side_effect = lambda tc, ids: [self._tg_msg(mid) for mid in ids]

    def _create_messages(self, telegram_ids: list[int]) -> None:
        for tid in telegram_ids:
            Message.objects.create(telegram_id=tid, channel=self.channel)

    def _tg_msg(self, telegram_id: int = 1) -> MagicMock:
        tm = MagicMock()
        tm.id = telegram_id
        tm.peer_id = MagicMock()
        return tm

    def _status(self, msg: str) -> None:
        self.status_messages.append(msg)

    @staticmethod
    def _noop_get_message_fn(ch, tm) -> tuple[bool, int]:
        return True, 0

    def _run(
        self,
        get_message_fn=None,
    ) -> tuple[int, int]:
        if get_message_fn is None:
            get_message_fn = self._noop_get_message_fn
        return fix_message_holes(
            self.channel,
            self.telegram_channel,
            self.api_client,
            get_message_fn,
            self._status,
            "CHAN",
            0,
        )

    # -- no-holes path --

    def test_no_holes_returns_zero_zero(self) -> None:
        self._create_messages([1, 2, 3])
        self.assertEqual(self._run(), (0, 0))

    def test_no_holes_emits_correct_status(self) -> None:
        self._create_messages([1, 2, 3])
        self._run()
        self.assertIn("CHAN | no message holes found", self.status_messages)

    def test_no_holes_does_not_call_api(self) -> None:
        self._create_messages([1, 2, 3])
        self._run()
        self.api_client.client.get_messages.assert_not_called()

    def test_no_holes_updates_checkpoint_to_max(self) -> None:
        self._create_messages([1, 2, 5])
        self._run()
        self.assertEqual(self.channel.last_hole_check_max_telegram_id, 5)

    # -- happy path with holes --

    def test_single_batch_one_api_call(self) -> None:
        self._create_messages([1, 7])  # holes: 2,3,4,5,6
        self._run()
        self.assertEqual(self.api_client.client.get_messages.call_count, 1)

    def test_single_batch_returns_correct_counts(self) -> None:
        self._create_messages([1, 7])  # 5 holes
        result = self._run()
        self.assertEqual(result, (5, 0))

    def test_two_batches_for_150_holes(self) -> None:
        self._create_messages([1, 152])  # holes: 2..151 (150 total)
        result = self._run()
        self.assertEqual(result, (150, 0))
        self.assertEqual(self.api_client.client.get_messages.call_count, 2)

    def test_exactly_batch_size_holes_one_api_call(self) -> None:
        self._create_messages([1, 102])  # holes: 2..101 (100 total = _HOLE_FETCH_BATCH_SIZE)
        self._run()
        self.assertEqual(self.api_client.client.get_messages.call_count, 1)

    def test_batch_size_plus_one_holes_two_api_calls(self) -> None:
        self._create_messages([1, 103])  # 101 holes
        self._run()
        self.assertEqual(self.api_client.client.get_messages.call_count, 2)

    # -- None / image handling --

    def test_none_messages_are_skipped(self) -> None:
        self._create_messages([1, 3])  # hole at 2
        self.api_client.client.get_messages.side_effect = lambda tc, ids: [None]
        result = self._run()
        self.assertEqual(result, (0, 0))

    def test_images_counted_in_return_value(self) -> None:
        def one_image_fn(ch, tm) -> tuple[bool, int]:
            return True, 1

        self._create_messages([1, 3])  # hole at 2
        result = self._run(get_message_fn=one_image_fn)
        self.assertEqual(result, (1, 1))

    # -- checkpoint and baseline --

    def test_baseline_checkpoint_filters_earlier_holes(self) -> None:
        self._create_messages([1, 3, 5, 7])  # gaps at 2, 4, 6
        self.channel.last_hole_check_max_telegram_id = 4
        self._run()
        # Only hole 6 is in scope (min_telegram_id=4 → messages [5,7] → gap (6,6))
        call_args = self.api_client.client.get_messages.call_args
        self.assertEqual(call_args.kwargs["ids"], [6])

    def test_full_run_updates_checkpoint_to_max_id(self) -> None:
        self._create_messages([1, 3, 5])  # holes at 2, 4
        self._run()
        self.assertEqual(self.channel.last_hole_check_max_telegram_id, 5)

    # -- API wait --

    def test_api_wait_called_once_per_batch(self) -> None:
        self._create_messages([1, 252])  # 250 holes → 3 batches
        self._run()
        self.assertEqual(self.api_client.wait.call_count, 3)

    # -- progress status --

    def test_progress_status_message_emitted(self) -> None:
        self._create_messages([1, 3])  # hole at 2
        self._run()
        self.assertIn("CHAN | messages processed: 1", self.status_messages)


# ---------------------------------------------------------------------------
# _fix_missing_media — retiring messages Telegram no longer has
# ---------------------------------------------------------------------------


class FixMissingMediaGoneTests(TestCase):
    """``_fix_missing_media`` must retire messages Telegram no longer has
    (e.g. auto-deleted by a channel TTL) instead of re-fetching them forever.

    A flagged album sibling (``grouped_id`` set, ``media_type=""``) is tagged
    ``"gone"`` from either signal: its id is at or below the channel's
    ``available_min_id`` watermark (tagged with no round-trip), or
    ``get_messages`` returns ``None`` for it (tagged after the fetch).
    Already-typed messages are left untouched.
    """

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.api_client = _make_api_client()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cmd = Command(stdout=io.StringIO())

    def _channel(self, telegram_id: int, available_min_id: int | None = None) -> Channel:
        return make_channel(telegram_id=telegram_id, label=self.org, available_min_id=available_min_id)

    def _album_sibling(self, channel: Channel, telegram_id: int) -> Message:
        # grouped_id set + empty media_type → enrolled via the album-sibling Q.
        return Message.objects.create(channel=channel, telegram_id=telegram_id, grouped_id=777)

    def _run(self, channel: Channel) -> None:
        printer = ProgressPrinter(self.cmd.stdout, total=1)
        self.cmd._fix_missing_media(
            Channel.objects.filter(pk=channel.pk),
            self.api_client,
            self.tmp,
            printer,
            _crawl_opts(fix_missing_media=True, download_images=True),
        )

    def test_below_watermark_marked_gone_without_any_fetch(self) -> None:
        ch = self._channel(telegram_id=501, available_min_id=100)
        below = self._album_sibling(ch, telegram_id=10)
        at_watermark = self._album_sibling(ch, telegram_id=100)  # boundary: <= watermark is gone too
        self._run(ch)
        below.refresh_from_db()
        at_watermark.refresh_from_db()
        self.assertEqual(below.media_type, "gone")
        self.assertEqual(at_watermark.media_type, "gone")
        # A fully-gone channel is skipped without resolving its entity or fetching.
        self.api_client.client.get_entity.assert_not_called()
        self.api_client.client.get_messages.assert_not_called()

    def test_none_result_marked_gone_after_fetch(self) -> None:
        ch = self._channel(telegram_id=502)  # no watermark reported
        m1 = self._album_sibling(ch, telegram_id=10)
        m2 = self._album_sibling(ch, telegram_id=20)
        self.api_client.client.get_messages.side_effect = lambda entity, ids: [None for _ in ids]
        self._run(ch)
        m1.refresh_from_db()
        m2.refresh_from_db()
        self.assertEqual(m1.media_type, "gone")
        self.assertEqual(m2.media_type, "gone")
        self.api_client.client.get_messages.assert_called_once()

    def test_partial_watermark_fetches_only_above_then_marks_all_gone(self) -> None:
        ch = self._channel(telegram_id=503, available_min_id=15)
        below = self._album_sibling(ch, telegram_id=10)  # tagged without a fetch
        above = self._album_sibling(ch, telegram_id=20)  # fetched, comes back None
        self.api_client.client.get_messages.side_effect = lambda entity, ids: [None for _ in ids]
        self._run(ch)
        below.refresh_from_db()
        above.refresh_from_db()
        self.assertEqual(below.media_type, "gone")
        self.assertEqual(above.media_type, "gone")
        # Only the above-watermark id is ever sent to Telegram.
        self.api_client.client.get_messages.assert_called_once()
        _, kwargs = self.api_client.client.get_messages.call_args
        self.assertEqual(list(kwargs["ids"]), [20])

    def test_known_type_below_watermark_is_left_intact(self) -> None:
        ch = self._channel(telegram_id=504, available_min_id=100)
        # media_type="photo" with no MessagePicture → flagged via the photo
        # bucket, but it is not an album sibling, so the guard must not touch it.
        m = Message.objects.create(channel=ch, telegram_id=10, media_type="photo")
        self._run(ch)
        m.refresh_from_db()
        self.assertEqual(m.media_type, "photo")
        self.api_client.client.get_entity.assert_not_called()

    def test_existing_message_is_reclassified_not_marked_gone(self) -> None:
        ch = self._channel(telegram_id=505)
        m = self._album_sibling(ch, telegram_id=30)
        tg = MagicMock()
        tg.id = 30
        tg.peer_id = MagicMock()
        self.api_client.client.get_messages.side_effect = lambda entity, ids: [tg]
        with patch("crawler.management.commands.crawl_channels.MediaHandler") as mock_mh:
            handler = mock_mh.return_value
            for meth in (
                "download_message_picture",
                "download_message_video",
                "download_message_audio",
                "download_message_sticker",
                "download_message_other_media",
            ):
                getattr(handler, meth).return_value = 0
            self._run(ch)
        m.refresh_from_db()
        # A live message that still exists is reclassified by detect_media_type,
        # never retired — the "gone" tag is only for ids Telegram no longer has.
        self.assertNotEqual(m.media_type, "gone")
        self.api_client.client.get_messages.assert_called_once()


class FixMissingMediaPrivateChannelTests(TestCase):
    """A private/banned channel is a routine condition: ``_fix_missing_media``
    must skip it with the plain-language line used by the other subcommands —
    not the raw Telethon RPC text followed by a logged traceback."""

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.api_client = _make_api_client()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = io.StringIO()
        self.cmd = Command(stdout=self.out)

    def test_private_channel_skipped_with_friendly_message(self) -> None:
        ch = make_channel(telegram_id=506, label=self.org)
        msg = Message.objects.create(channel=ch, telegram_id=10, grouped_id=777)
        err = errors.rpcerrorlist.ChannelPrivateError.__new__(errors.rpcerrorlist.ChannelPrivateError)
        self.api_client.client.get_entity.side_effect = err
        printer = ProgressPrinter(self.cmd.stdout, total=1)
        with self.assertNoLogs("crawler.management.commands.crawl_channels", level="ERROR"):
            self.cmd._fix_missing_media(
                Channel.objects.filter(pk=ch.pk),
                self.api_client,
                self.tmp,
                printer,
                _crawl_opts(fix_missing_media=True, download_images=True),
            )
        out = self.out.getvalue()
        self.assertIn("channel is private or inaccessible", out)
        self.assertNotIn("Could not get entity", out)
        self.api_client.client.get_messages.assert_not_called()
        # The message is skipped, not retired — access may be restored later.
        msg.refresh_from_db()
        self.assertEqual(msg.media_type, "")


# ---------------------------------------------------------------------------
# ReferenceResolver._is_paused / _pause
# ---------------------------------------------------------------------------


class ReferencePauseTests(TestCase):
    def setUp(self) -> None:
        self.resolver = ReferenceResolver(_make_api_client())

    def test_not_paused_initially(self) -> None:
        self.assertFalse(self.resolver._is_paused())

    def test_pause_sets_pause_until_in_future(self) -> None:
        error = MagicMock()
        error.seconds = 60
        self.resolver._pause(error)
        self.assertIsNotNone(self.resolver.reference_resolution_paused_until)
        self.assertGreater(self.resolver.reference_resolution_paused_until, timezone.now())

    def test_is_paused_after_pause_call(self) -> None:
        error = MagicMock()
        error.seconds = 60
        self.resolver._pause(error)
        self.assertTrue(self.resolver._is_paused())

    def test_pause_with_zero_seconds_uses_minimum_1(self) -> None:
        error = MagicMock()
        error.seconds = 0
        wait = self.resolver._pause(error)
        self.assertEqual(wait, 1)

    def test_pause_returns_wait_seconds(self) -> None:
        error = MagicMock()
        error.seconds = 45
        wait = self.resolver._pause(error)
        self.assertEqual(wait, 45)

    def test_pause_keeps_larger_deadline(self) -> None:
        error_short = MagicMock()
        error_short.seconds = 5
        error_long = MagicMock()
        error_long.seconds = 120
        self.resolver._pause(error_short)
        first_deadline = self.resolver.reference_resolution_paused_until
        self.resolver._pause(error_long)
        self.assertGreater(self.resolver.reference_resolution_paused_until, first_deadline)

    def test_not_paused_after_deadline_passes(self) -> None:
        # Set pause_until to the past
        self.resolver.reference_resolution_paused_until = timezone.now() - timedelta(seconds=1)
        self.assertFalse(self.resolver._is_paused())


# ---------------------------------------------------------------------------
# ReferenceResolver._resolve_one
# ---------------------------------------------------------------------------


class ResolveOneTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.resolver = ReferenceResolver(self.api_client)
        self.org = make_label(name="Org", is_in_target=True)

    def test_returns_existing_db_channel_without_api_call(self) -> None:
        channel = make_channel(telegram_id=1, username="existingchan", label=self.org)
        result, failed = self.resolver._resolve_one("existingchan")
        self.assertEqual(result, channel)
        self.assertFalse(failed)
        self.api_client.client.get_entity.assert_not_called()

    def test_creates_new_channel_via_api_when_not_in_db(self) -> None:
        mock_tc = _make_telegram_channel(telegram_id=500, username="newchan")
        self.api_client.client.get_entity.return_value = mock_tc
        result, failed = self.resolver._resolve_one("newchan")
        self.assertIsNotNone(result)
        self.assertFalse(failed)
        self.assertTrue(Channel.objects.filter(telegram_id=500).exists())

    def test_value_error_from_api_returns_none_not_failed(self) -> None:
        self.api_client.client.get_entity.side_effect = ValueError("not found")
        result, failed = self.resolver._resolve_one("badref")
        self.assertIsNone(result)
        self.assertFalse(failed)

    def test_username_invalid_error_returns_none_not_failed(self) -> None:
        self.api_client.client.get_entity.side_effect = _username_invalid_error()
        result, failed = self.resolver._resolve_one("invalid__ref")
        self.assertIsNone(result)
        self.assertFalse(failed)

    def test_flood_wait_error_returns_none_failed(self) -> None:
        self.api_client.client.get_entity.side_effect = _flood_error(seconds=30)
        result, failed = self.resolver._resolve_one("ratechan")
        self.assertIsNone(result)
        self.assertTrue(failed)

    def test_flood_wait_error_pauses_resolver(self) -> None:
        self.api_client.client.get_entity.side_effect = _flood_error(seconds=30)
        self.resolver._resolve_one("ratechan")
        self.assertTrue(self.resolver._is_paused())

    def test_generic_rpc_error_returns_none_failed(self) -> None:
        self.api_client.client.get_entity.side_effect = _rpc_error()
        result, failed = self.resolver._resolve_one("errchan")
        self.assertIsNone(result)
        self.assertTrue(failed)

    def test_paused_resolver_skips_api_call(self) -> None:
        # Manually pause the resolver
        self.resolver.reference_resolution_paused_until = timezone.now() + timedelta(seconds=60)
        result, failed = self.resolver._resolve_one("anychan")
        self.assertIsNone(result)
        self.assertTrue(failed)
        self.api_client.client.get_entity.assert_not_called()

    def test_recycled_username_prefers_live_channel_over_lost(self) -> None:
        # The same handle is held by a now-lost old channel and the live channel that
        # took it over: usernames are not unique identities, so prefer the live owner.
        make_channel(telegram_id=1, username="recycled", label=self.org, is_lost=True)
        live = make_channel(telegram_id=2, username="recycled")
        result, failed = self.resolver._resolve_one("recycled")
        self.assertEqual(result, live)
        self.assertFalse(failed)
        self.api_client.client.get_entity.assert_not_called()

    def test_lone_lost_channel_with_username_is_still_returned(self) -> None:
        # No live owner stored → fall back to the lost row (edge to a lost channel is
        # preserved; only collisions change behaviour).
        lost = make_channel(telegram_id=1, username="onlylost", label=self.org, is_lost=True)
        result, failed = self.resolver._resolve_one("onlylost")
        self.assertEqual(result, lost)
        self.assertFalse(failed)
        self.api_client.client.get_entity.assert_not_called()

    def test_user_entity_recorded_as_user_account(self) -> None:
        # t.me/<bot> resolves to a Telethon User: it must land in the USER bucket, not as a
        # broadcast "channel" that passes the default --channel-types CHANNEL filter.
        self.api_client.client.get_entity.return_value = User(id=4242, username="SomeBot", bot=True)
        result, failed = self.resolver._resolve_one("somebot")
        self.assertFalse(failed)
        self.assertIsNotNone(result)
        result.refresh_from_db()
        self.assertTrue(result.is_user_account)
        self.assertFalse(result.broadcast)
        self.assertEqual(result.channel_type_key, "USER")
        self.assertEqual(result.username, "SomeBot")
        self.assertFalse(Channel.objects.filter(channel_type_filter(["CHANNEL"]), telegram_id=4242).exists())
        # The stored handle short-circuits the next lookup — no second get_entity call.
        again, _ = self.resolver._resolve_one("somebot")
        self.assertEqual(again, result)
        self.api_client.client.get_entity.assert_called_once_with("somebot")

    def test_user_entity_never_overwrites_a_channel_with_the_same_numeric_id(self) -> None:
        # User and channel ids are separate namespaces that can coincide numerically.
        channel = make_channel(telegram_id=4242, username="realchan", title="Real channel")
        self.api_client.client.get_entity.return_value = User(id=4242, username="somebot", bot=True)
        result, failed = self.resolver._resolve_one("somebot")
        self.assertIsNone(result)
        self.assertFalse(failed)
        channel.refresh_from_db()
        self.assertFalse(channel.is_user_account)
        self.assertEqual(channel.username, "realchan")
        self.assertEqual(Channel.objects.filter(telegram_id=4242).count(), 1)


# ---------------------------------------------------------------------------
# ReferenceResolver.resolve_message_references
# ---------------------------------------------------------------------------


class ResolveMessageReferencesTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.resolver = ReferenceResolver(self.api_client)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, label=self.org)
        self.message = Message.objects.create(telegram_id=1, channel=self.channel)

    def _make_telegram_message(self, entities: list | None = None) -> MagicMock:
        tm = MagicMock()
        tm.entities = entities or []
        return tm

    def test_message_with_no_references_returns_empty_missing(self) -> None:
        self.message.message = "No links here"
        tm = self._make_telegram_message()
        missing = self.resolver.resolve_message_references(self.message, tm)
        self.assertEqual(missing, [])

    def test_resolvable_reference_added_to_message_references(self) -> None:
        target_channel = make_channel(telegram_id=2, username="targetchan", label=self.org)
        self.message.message = "Check out t.me/targetchan for more info."
        tm = self._make_telegram_message()
        self.resolver.resolve_message_references(self.message, tm)
        self.assertIn(target_channel, self.message.references.all())

    def test_joinchat_reference_is_skipped(self) -> None:
        self.message.message = "Join us at t.me/joinchat/sometoken"
        tm = self._make_telegram_message()
        missing = self.resolver.resolve_message_references(self.message, tm)
        # joinchat is in SKIPPABLE_REFERENCES → not added to missing
        self.assertNotIn("joinchat", missing)
        self.api_client.client.get_entity.assert_not_called()

    def test_unresolvable_reference_added_to_missing(self) -> None:
        self.api_client.client.get_entity.side_effect = _rpc_error()
        self.message.message = "Visit t.me/unknownchan"
        tm = self._make_telegram_message()
        missing = self.resolver.resolve_message_references(self.message, tm)
        self.assertIn("unknownchan", missing)

    def test_entity_url_reference_processed(self) -> None:
        target_channel = make_channel(telegram_id=3, username="urlchan", label=self.org)
        entity = MagicMock()
        entity.url = "https://t.me/urlchan"
        tm = self._make_telegram_message(entities=[entity])
        self.resolver.resolve_message_references(self.message, tm)
        self.assertIn(target_channel, self.message.references.all())

    def test_entity_url_subpath_is_stripped(self) -> None:
        target_channel = make_channel(telegram_id=4, username="pathchan", label=self.org)
        entity = MagicMock()
        entity.url = "https://t.me/pathchan/12345"
        tm = self._make_telegram_message(entities=[entity])
        self.resolver.resolve_message_references(self.message, tm)
        self.assertIn(target_channel, self.message.references.all())

    def test_entity_without_url_attribute_is_ignored(self) -> None:
        entity = MagicMock(spec=[])  # no attributes
        tm = self._make_telegram_message(entities=[entity])
        # Should not raise, just skip
        missing = self.resolver.resolve_message_references(self.message, tm)
        self.assertEqual(missing, [])

    def test_entity_url_not_starting_with_tme_is_ignored(self) -> None:
        entity = MagicMock()
        entity.url = "https://example.com/somepage"
        tm = self._make_telegram_message(entities=[entity])
        missing = self.resolver.resolve_message_references(self.message, tm)
        self.assertEqual(missing, [])
        self.api_client.client.get_entity.assert_not_called()

    def test_entity_url_variants_keep_the_citation(self) -> None:
        # Query strings, fragments, /s/ previews, scheme / host spellings used to leave
        # "chan?boost", "chan#x" or "s" as the handle — a permanent failure, edge lost.
        target = make_channel(telegram_id=5, username="VarChan", label=self.org)
        for url in (
            "https://t.me/varchan?boost",
            "https://t.me/varchan#x",
            "https://t.me/s/varchan",
            "https://t.me/s/varchan/77",
            "http://t.me/varchan",
            "HTTPS://T.ME/VarChan",
            "https://telegram.me/varchan",
            "https://t.me/boost/varchan",
        ):
            with self.subTest(url=url):
                self.message.references.clear()
                entity = MagicMock()
                entity.url = url
                missing = self.resolver.resolve_message_references(self.message, self._make_telegram_message([entity]))
                self.assertEqual(missing, [])
                self.assertEqual(list(self.message.references.all()), [target])
        self.api_client.client.get_entity.assert_not_called()

    def test_plain_text_variants_keep_the_citation(self) -> None:
        target = make_channel(telegram_id=6, username="textchan", label=self.org)
        for text in (
            "Seguici su T.me/TextChan",
            "via http://t.me/textchan.",
            "telegram.me/textchan",
            "preview t.me/s/textchan/12",
        ):
            with self.subTest(text=text):
                self.message.references.clear()
                self.message.message = text
                self.resolver.resolve_message_references(self.message, self._make_telegram_message())
                self.assertEqual(list(self.message.references.all()), [target])
        self.api_client.client.get_entity.assert_not_called()

    def test_reserved_paths_are_not_resolved(self) -> None:
        self.message.message = "t.me/addstickers/pack t.me/c/123/45 t.me/+AbCd t.me/share/url?url=x t.me/s"
        entity = MagicMock()
        entity.url = "https://t.me/proxy?server=1.2.3.4"
        missing = self.resolver.resolve_message_references(self.message, self._make_telegram_message([entity]))
        self.assertEqual(missing, [])
        self.api_client.client.get_entity.assert_not_called()

    def test_bot_link_attaches_a_user_account(self) -> None:
        # The bot reference stays on the message (a USER-inclusive analysis sees it), but the
        # target is typed USER, so a channel-only analysis filters it out.
        self.api_client.client.get_entity.return_value = User(id=4343, username="helperbot", bot=True)
        entity = MagicMock()
        entity.url = "https://t.me/helperbot?start=abc"
        self.resolver.resolve_message_references(self.message, self._make_telegram_message([entity]))
        self.api_client.client.get_entity.assert_called_once_with("helperbot")
        (bot,) = self.message.references.all()
        self.assertTrue(bot.is_user_account)
        self.assertEqual(bot.channel_type_key, "USER")


class TmeLinkParsingTests(SimpleTestCase):
    def test_reference_from_url(self) -> None:
        cases = {
            "https://t.me/chan": "chan",
            "https://t.me/chan?boost": "chan",
            "https://t.me/chan#x": "chan",
            "https://t.me/chan/123?single": "chan",
            "https://t.me/s/chan": "chan",
            "https://t.me/boost/chan": "chan",
            "http://t.me/Chan": "chan",
            "t.me/chan": "chan",
            "HTTPS://WWW.T.ME/Chan": "chan",
            "https://telegram.me/chan": "chan",
            "https://t.me/joinchat/AbC": None,
            "https://t.me/+AbC": None,
            "https://t.me/c/123/45": None,
            "https://t.me/$invoice": None,
            "https://t.me/boost?c=123": None,
            "https://t.me/s": None,
            "https://t.me/": None,
            "https://example.com/t.me/chan": None,
            "https://t.me.evil.com/chan": None,
        }
        for path in ("share/url?url=x", "iv?url=x", "addstickers/a", "addemoji/a", "addlist/a", "proxy?s=1"):
            cases[f"https://t.me/{path}"] = None
        for path in ("socks?s=1", "login/1", "confirmphone?p=1", "setlanguage/it", "addtheme/a", "bg/a", "invoice/a"):
            cases[f"https://t.me/{path}"] = None
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(reference_from_url(url), expected)

    def test_extract_text_references(self) -> None:
        text = (
            "T.me/One, http://t.me/two. telegram.me/three t.me/s/four https://t.me/five?boost "
            "t.me/joinchat/x t.me/+abc t.me/c/1/2 chat.me/nope t.me/some-channel (t.me/six)"
        )
        self.assertEqual(extract_text_references(text), ["one", "two", "three", "four", "five", "some", "six"])
        self.assertEqual(extract_text_references(""), [])
        self.assertEqual(extract_text_references(None), [])


# ---------------------------------------------------------------------------
# ReferenceResolver.get_missing_references
# ---------------------------------------------------------------------------


class GetMissingReferencesTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.resolver = ReferenceResolver(self.api_client)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, label=self.org)

    def test_message_with_empty_missing_references_is_skipped(self) -> None:
        Message.objects.create(telegram_id=1, channel=self.channel, missing_references="")
        self.resolver.get_missing_references()
        self.api_client.client.get_entity.assert_not_called()

    def test_missing_reference_found_in_db_added_without_api_call(self) -> None:
        target = make_channel(telegram_id=2, username="dbchan", label=self.org)
        msg = Message.objects.create(telegram_id=2, channel=self.channel, missing_references="|dbchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        self.assertIn(target, msg.references.all())
        self.api_client.client.get_entity.assert_not_called()

    def test_missing_reference_cleared_after_successful_resolution(self) -> None:
        make_channel(telegram_id=3, username="resolvable", label=self.org)
        msg = Message.objects.create(telegram_id=3, channel=self.channel, missing_references="|resolvable")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        self.assertEqual(msg.missing_references, "")

    def test_api_call_made_for_unknown_reference(self) -> None:
        mock_tc = _make_telegram_channel(telegram_id=999, username="apichan")
        self.api_client.client.get_entity.return_value = mock_tc
        Message.objects.create(telegram_id=4, channel=self.channel, missing_references="|apichan")
        self.resolver.get_missing_references()
        self.api_client.client.get_entity.assert_called_once_with("apichan")

    def test_flood_error_prevents_clearing_missing_references(self) -> None:
        self.api_client.client.get_entity.side_effect = _flood_error(seconds=10)
        msg = Message.objects.create(telegram_id=5, channel=self.channel, missing_references="|floodchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        # FloodWaitError → kept for retry, NOT marked dead
        self.assertEqual(msg.missing_references, "floodchan")

    def test_rpc_error_not_marked_as_dead(self) -> None:
        self.api_client.client.get_entity.side_effect = _rpc_error()
        msg = Message.objects.create(telegram_id=12, channel=self.channel, missing_references="|rpcchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        # Generic RPCError → transient, kept for retry without dead prefix
        self.assertEqual(msg.missing_references, "rpcchan")

    def test_joinchat_skippable_reference_ignored(self) -> None:
        msg = Message.objects.create(telegram_id=6, channel=self.channel, missing_references="|joinchat")
        self.resolver.get_missing_references()
        self.api_client.client.get_entity.assert_not_called()
        msg.refresh_from_db()
        # joinchat is skipped → missing_references cleared (no flood error)
        self.assertEqual(msg.missing_references, "")

    def test_legacy_mangled_references_are_normalised_and_retried(self) -> None:
        # An older parser stored link paths verbatim; a dead verdict on "chan?boost" was about
        # the mangled spelling, so the normalised handle is retried even without force_retry,
        # and the bare /s/ prefix (handle lost) is dropped without an API call.
        target = make_channel(telegram_id=13, username="legacychan", label=self.org)
        msg = Message.objects.create(
            telegram_id=13, channel=self.channel, missing_references="!legacychan?boost|legacychan#x|!s"
        )
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        self.assertEqual(msg.missing_references, "")
        self.assertEqual(list(msg.references.all()), [target])
        self.api_client.client.get_entity.assert_not_called()

    def test_multiple_references_processed_in_one_message(self) -> None:
        ch_a = make_channel(telegram_id=10, username="chana", label=self.org)
        mock_tc = _make_telegram_channel(telegram_id=20, username="chanb")
        self.api_client.client.get_entity.return_value = mock_tc
        msg = Message.objects.create(telegram_id=7, channel=self.channel, missing_references="|chana|chanb")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        self.assertIn(ch_a, msg.references.all())
        self.assertEqual(msg.missing_references, "")

    def test_permanent_failure_marked_as_dead(self) -> None:
        self.api_client.client.get_entity.side_effect = ValueError("not found")
        msg = Message.objects.create(telegram_id=8, channel=self.channel, missing_references="|deadchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        self.assertEqual(msg.missing_references, "!deadchan")

    def test_dead_reference_skipped_by_default(self) -> None:
        msg = Message.objects.create(telegram_id=9, channel=self.channel, missing_references="!deadchan")
        self.resolver.get_missing_references()
        self.api_client.client.get_entity.assert_not_called()
        msg.refresh_from_db()
        self.assertEqual(msg.missing_references, "!deadchan")

    def test_dead_reference_retried_with_force_retry(self) -> None:
        mock_tc = _make_telegram_channel(telegram_id=777, username="deadchan")
        self.api_client.client.get_entity.return_value = mock_tc
        msg = Message.objects.create(telegram_id=10, channel=self.channel, missing_references="!deadchan")
        self.resolver.get_missing_references(force_retry=True)
        self.api_client.client.get_entity.assert_called_once_with("deadchan")
        msg.refresh_from_db()
        self.assertEqual(msg.missing_references, "")

    def test_mixed_dead_and_temp_failure(self) -> None:
        # One reference permanently dead, another still temporarily failing
        def side_effect(ref):
            if ref == "deadchan":
                raise ValueError("not found")
            raise _flood_error(seconds=5)

        self.api_client.client.get_entity.side_effect = side_effect
        msg = Message.objects.create(telegram_id=11, channel=self.channel, missing_references="|deadchan|floodchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        # deadchan → marked dead; floodchan → kept for retry
        self.assertIn("!deadchan", msg.missing_references)
        self.assertIn("floodchan", msg.missing_references)
        self.assertNotIn("!floodchan", msg.missing_references)


# ---------------------------------------------------------------------------
# TelegramAPIClient
# ---------------------------------------------------------------------------


class TelegramAPIClientTests(TestCase):
    def setUp(self) -> None:
        from crawler.client import TelegramAPIClient

        self.mock_telethon = MagicMock()
        self.api_client = TelegramAPIClient(self.mock_telethon)

    def test_client_attribute_set(self) -> None:
        self.assertIs(self.api_client.client, self.mock_telethon)

    def test_wait_time_set_from_settings(self) -> None:
        from django.conf import settings

        self.assertEqual(self.api_client.wait_time, settings.TELEGRAM_CRAWLER_GRACE_TIME)

    def test_last_call_initialised_in_the_past(self) -> None:
        from django.utils import timezone

        self.assertLess(self.api_client.last_call, timezone.now())

    @patch("crawler.client.sleep")
    def test_wait_sleeps_when_called_too_soon(self, mock_sleep: MagicMock) -> None:
        from django.utils import timezone

        from crawler.client import TelegramAPIClient

        client = TelegramAPIClient(MagicMock())
        # Force last_call to now so wait_time - 0 = wait_time > 0
        client.last_call = timezone.now()
        client.wait()
        mock_sleep.assert_called_once()

    @patch("crawler.client.sleep")
    def test_wait_skips_sleep_when_enough_time_passed(self, mock_sleep: MagicMock) -> None:
        from datetime import timedelta

        from django.utils import timezone

        from crawler.client import TelegramAPIClient

        client = TelegramAPIClient(MagicMock())
        # Set last_call far enough in the past
        client.last_call = timezone.now() - timedelta(seconds=client.wait_time + 5)
        client.wait()
        mock_sleep.assert_not_called()

    @patch("crawler.client.sleep")
    def test_wait_updates_last_call(self, _mock_sleep: MagicMock) -> None:
        from datetime import timedelta

        from django.utils import timezone

        from crawler.client import TelegramAPIClient

        client = TelegramAPIClient(MagicMock())
        client.last_call = timezone.now() - timedelta(seconds=client.wait_time + 5)
        before = timezone.now()
        client.wait()
        self.assertGreaterEqual(client.last_call, before)


# ---------------------------------------------------------------------------
# MediaHandler — _cleanup_downloaded_file, _download_media
# ---------------------------------------------------------------------------


class MediaHandlerCleanupTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)

    def test_cleanup_none_does_not_raise(self) -> None:
        self.handler._cleanup_downloaded_file(None)  # must not raise

    def test_cleanup_nonexistent_file_does_not_raise(self) -> None:
        self.handler._cleanup_downloaded_file("/nonexistent/path/photo.jpg")

    def test_cleanup_removes_existing_file(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        self.assertTrue(os.path.exists(path))
        self.handler._cleanup_downloaded_file(path)
        self.assertFalse(os.path.exists(path))

    def test_download_media_without_temp_dir(self) -> None:
        obj = MagicMock()
        self.handler._download_media(obj)
        self.api_client.client.download_media.assert_called_once_with(obj)

    def test_download_media_with_temp_dir_passes_file_arg(self) -> None:
        from crawler.media_handler import MediaHandler

        handler = MediaHandler(self.api_client, download_temp_dir="/tmp/test_dl")
        obj = MagicMock()
        handler._download_media(obj)
        self.api_client.client.download_media.assert_called_once_with(obj, file="/tmp/test_dl")


class MediaHandlerTimeoutTests(TestCase):
    """The per-file download timeout in _download_media (0 = no limit)."""

    def setUp(self) -> None:
        from crawler import media_handler

        media_handler._TIMED_OUT_THIS_RUN.clear()
        self.addCleanup(media_handler._TIMED_OUT_THIS_RUN.clear)

    def _handler(self, download_media, timeout):
        from crawler.media_handler import MediaHandler

        # A plain class (not MagicMock) so _download_media takes the async
        # unwrap path that applies the timeout.
        client = type("FakeClient", (), {"download_media": download_media})()
        client.loop = asyncio.new_event_loop()
        self.addCleanup(client.loop.close)
        api_client = MagicMock()
        api_client.client = client
        return MediaHandler(api_client, download_timeout=timeout)

    def test_timed_out_download_returns_none(self) -> None:
        async def download_media(self, obj, **kwargs):
            await asyncio.sleep(30)
            return "/tmp/never.jpg"

        handler = self._handler(download_media, timeout=0.01)
        self.assertIsNone(handler._download_media(MagicMock()))

    def test_zero_timeout_means_no_limit(self) -> None:
        # wait_for(..., 0) would cancel a still-pending download immediately;
        # 0 must translate to "no timeout" instead.
        async def download_media(self, obj, **kwargs):
            await asyncio.sleep(0)
            return "/tmp/file.jpg"

        handler = self._handler(download_media, timeout=0)
        self.assertEqual(handler._download_media(MagicMock()), "/tmp/file.jpg")

    def test_timed_out_file_not_retried_same_run(self) -> None:
        calls = []

        async def download_media(self, obj, **kwargs):
            calls.append(obj)
            await asyncio.sleep(30)
            return "/tmp/never.jpg"

        handler = self._handler(download_media, timeout=0.01)
        obj = MagicMock()
        self.assertIsNone(handler._download_media(obj))
        self.assertEqual(len(calls), 1)
        # Same file again: skipped without touching Telegram — including from a
        # different MediaHandler of the same run (the fix-missing-media handler).
        self.assertIsNone(handler._download_media(obj))
        other = self._handler(download_media, timeout=0.01)
        self.assertIsNone(other._download_media(obj))
        self.assertEqual(len(calls), 1)

    def test_thumbnail_not_blocked_by_full_file_timeout(self) -> None:
        calls = []

        async def download_media(self, obj, **kwargs):
            calls.append(kwargs.get("thumb"))
            await asyncio.sleep(30)
            return "/tmp/never.jpg"

        handler = self._handler(download_media, timeout=0.01)
        obj = MagicMock()
        self.assertIsNone(handler._download_media(obj))
        # The thumbnail is a separate, much smaller download — still attempted.
        self.assertIsNone(handler._download_media(obj, thumb=-1))
        self.assertEqual(calls, [None, -1])


# ---------------------------------------------------------------------------
# MediaHandler — download_profile_picture
# ---------------------------------------------------------------------------


class MediaHandlerProfilePictureTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, label=self.org)

    def _make_tg_channel(self, telegram_id: int = 1) -> MagicMock:
        tc = MagicMock()
        tc.id = telegram_id
        return tc

    def _make_tg_picture(self, pic_id: int = 100) -> MagicMock:
        p = MagicMock()
        p.id = pic_id
        p.date = None
        return p

    def test_returns_zero_when_channel_not_in_db(self) -> None:
        tc = self._make_tg_channel(telegram_id=9999)
        result = self.handler.download_profile_picture(tc)
        self.assertEqual(result, 0)

    def test_returns_zero_when_no_profile_photos(self) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        self.api_client.client.get_profile_photos.return_value = []
        result = self.handler.download_profile_picture(tc)
        self.assertEqual(result, 0)

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_downloads_and_counts_new_picture(self, mock_from_tg: MagicMock) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=100)
        self.api_client.client.get_profile_photos.return_value = [pic]
        self.handler._download_media = MagicMock(return_value="/tmp/fake.jpg")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.os.path.exists", return_value=True)
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_skips_picture_when_file_on_disk(self, mock_from_tg: MagicMock, _mock_exists: MagicMock) -> None:
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        # A row is "fresh" only when the file is on disk, mime_type is recorded, AND
        # the filename follows the per-photo "<channel>_<photo>.<ext>" scheme.
        ProfilePicture.objects.create(
            telegram_id=200, channel=self.channel, picture="1_200.jpg", mime_type="image/jpeg", date=None
        )

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 0)
        mock_from_tg.assert_not_called()

    @patch("crawler.media_handler.os.path.exists", return_value=True)
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_redownloads_picture_with_shared_filename(self, mock_from_tg: MagicMock, _mock_exists: MagicMock) -> None:
        """Rows pointing at the shared per-channel path ("<channel>.jpg") are
        treated as stale — every photo of the channel overwrote the same file,
        so the bytes on disk are the wrong photo for all but one row; the
        next pass must re-download into the per-photo path."""
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        ProfilePicture.objects.create(
            telegram_id=200, channel=self.channel, picture="1.jpg", mime_type="image/jpeg", date=None
        )
        self.handler._download_media = MagicMock(return_value="/tmp/fake.jpg")
        self.handler._cleanup_downloaded_file = MagicMock()

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.os.path.exists", return_value=False)
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_redownloads_picture_when_file_missing_on_disk(
        self, mock_from_tg: MagicMock, _mock_exists: MagicMock
    ) -> None:
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        ProfilePicture.objects.create(telegram_id=200, channel=self.channel, picture="profile.jpg", date=None)
        self.handler._download_media = MagicMock(return_value="/tmp/fake.jpg")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_redownloads_picture_when_record_has_empty_file_field(self, mock_from_tg: MagicMock) -> None:
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        ProfilePicture.objects.create(telegram_id=200, channel=self.channel, picture="", date=None)
        self.handler._download_media = MagicMock(return_value="/tmp/fake.jpg")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_counts_multiple_new_pictures(self, mock_from_tg: MagicMock) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        pics = [self._make_tg_picture(pic_id=i) for i in range(1, 4)]
        self.api_client.client.get_profile_photos.return_value = pics
        self.handler._download_media = MagicMock(return_value="/tmp/fake.jpg")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 3)
        self.assertEqual(mock_from_tg.call_count, 3)

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_skips_picture_and_creates_no_row_when_download_returns_none(self, mock_from_tg: MagicMock) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=300)
        self.api_client.client.get_profile_photos.return_value = [pic]
        self.handler._download_media = MagicMock(return_value=None)

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 0)
        mock_from_tg.assert_not_called()

    @patch("crawler.media_handler.os.remove")
    @patch("crawler.media_handler.os.path.exists", return_value=True)
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_redownloads_when_existing_row_has_no_mime_type(
        self, mock_from_tg: MagicMock, _mock_exists: MagicMock, _mock_remove: MagicMock
    ) -> None:
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        # File is on disk but mime_type is missing (pre-backfill state).
        ProfilePicture.objects.create(
            telegram_id=200, channel=self.channel, picture="profile.jpg", mime_type="", date=None
        )
        self.handler._download_media = MagicMock(return_value="/tmp/fake.jpg")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.os.remove")
    @patch("crawler.media_handler.os.path.exists", return_value=True)
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_redownloads_video_row_missing_thumbnail(
        self, mock_from_tg: MagicMock, _mock_exists: MagicMock, _mock_remove: MagicMock
    ) -> None:
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        # Existing video row with the main .mp4 on disk but no static thumbnail
        # captured yet — must re-process so the thumbnail download fires.
        ProfilePicture.objects.create(
            telegram_id=200,
            channel=self.channel,
            picture="profile.mp4",
            mime_type="video/mp4",
            thumbnail="",
            date=None,
        )
        self.handler._download_media = MagicMock(return_value="/tmp/fake.mp4")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.mimetypes.guess_type", return_value=("video/mp4", None))
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_video_avatar_downloads_main_file_and_static_thumbnail(
        self, mock_from_tg: MagicMock, _mock_guess: MagicMock
    ) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=300)
        self.api_client.client.get_profile_photos.return_value = [pic]
        # First _download_media call → main video file; second (with thumb=-1) → static frame.
        self.handler._download_media = MagicMock(side_effect=["/tmp/avatar.mp4", "/tmp/avatar_thumb.jpg"])

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        # _download_media called twice: once for main, once with thumb=-1
        self.assertEqual(self.handler._download_media.call_count, 2)
        self.handler._download_media.assert_any_call(pic)
        self.handler._download_media.assert_any_call(pic, thumb=-1)
        defaults = mock_from_tg.call_args.kwargs["defaults"]
        self.assertEqual(defaults["mime_type"], "video/mp4")
        self.assertEqual(defaults["thumbnail"], "/tmp/avatar_thumb.jpg")
        self.assertEqual(defaults["picture"], "/tmp/avatar.mp4")

    @patch("crawler.media_handler.mimetypes.guess_type", return_value=("image/jpeg", None))
    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_static_avatar_does_not_request_thumbnail(self, mock_from_tg: MagicMock, _mock_guess: MagicMock) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=300)
        self.api_client.client.get_profile_photos.return_value = [pic]
        self.handler._download_media = MagicMock(return_value="/tmp/avatar.jpg")

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        # No thumb=-1 follow-up for static avatars
        self.assertEqual(self.handler._download_media.call_count, 1)
        defaults = mock_from_tg.call_args.kwargs["defaults"]
        self.assertEqual(defaults["mime_type"], "image/jpeg")
        self.assertIsNone(defaults["thumbnail"])

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_loop_continues_after_recoverable_error_on_current_picture(self, mock_from_tg: MagicMock) -> None:
        from telethon.errors.rpcerrorlist import FileReferenceExpiredError

        tc = self._make_tg_channel(telegram_id=1)
        current_pic = self._make_tg_picture(pic_id=400)  # iterated first → newest
        older_pic = self._make_tg_picture(pic_id=401)
        self.api_client.client.get_profile_photos.return_value = [current_pic, older_pic]
        err = FileReferenceExpiredError.__new__(FileReferenceExpiredError)
        self.handler._download_media = MagicMock(side_effect=[err, "/tmp/fake.jpg"])

        result = self.handler.download_profile_picture(tc)

        # The current picture fails but the older one still gets processed
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()


# ---------------------------------------------------------------------------
# MediaHandler — download_message_picture
# ---------------------------------------------------------------------------


class MediaHandlerMessagePictureTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_images=False by default
        self.handler_dl = MediaHandler(self.api_client, download_images=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, label=self.org)
        self.message = Message.objects.create(telegram_id=1, channel=self.channel)

    def _make_tg_message(self, has_photo: bool = True) -> MagicMock:
        tm = MagicMock()
        tm.id = 1
        tm.peer_id.channel_id = 10
        if has_photo:
            tm.media.photo = MagicMock()
            tm.media.photo.id = 42
            tm.media.photo.date = None
        else:
            del tm.media.photo  # hasattr returns False
        return tm

    def test_returns_zero_when_download_disabled(self) -> None:
        tm = self._make_tg_message()
        result = self.handler.download_message_picture(tm)
        self.assertEqual(result, 0)

    def test_returns_zero_when_no_photo_attribute(self) -> None:
        tm = self._make_tg_message(has_photo=False)
        result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 0)

    @patch("crawler.media_handler.MessagePicture.from_telegram_object")
    def test_returns_1_on_success(self, mock_from_tg: MagicMock) -> None:
        tm = self._make_tg_message()
        self.handler_dl._download_media = MagicMock(return_value="/tmp/test.jpg")
        result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    def test_returns_zero_when_download_returns_empty(self) -> None:
        # _download_media returning None (timeout, error) must short-circuit
        # before from_telegram_object — otherwise a zombie MessagePicture row
        # with picture=NULL is created and the message becomes unrecoverable
        # by --fix-missing-media (messagepicture__isnull=True excludes it).
        tm = self._make_tg_message()
        self.handler_dl._download_media = MagicMock(return_value=None)
        with patch("crawler.media_handler.MessagePicture.from_telegram_object") as mock_from_tg:
            result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 0)
        mock_from_tg.assert_not_called()

    def test_returns_zero_on_file_migrate_error(self) -> None:
        from telethon.errors.rpcerrorlist import FileMigrateError

        tm = self._make_tg_message()
        err = FileMigrateError.__new__(FileMigrateError)
        self.handler_dl._download_media = MagicMock(side_effect=err)
        result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 0)

    def test_returns_zero_on_message_does_not_exist(self) -> None:
        tm = self._make_tg_message()
        tm.id = 9999  # No message with this telegram_id in DB
        self.handler_dl._download_media = MagicMock(return_value="/tmp/test.jpg")
        result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 0)

    def test_forwarded_photo_creates_separate_messagepicture_row(self) -> None:
        # A forwarded photo carries the same Telegram photo.id under a
        # different Message. Before the composite-key fix, get_or_create
        # matched on telegram_id alone, returned the original row, wrote the
        # file to the original Message's path, and left the forwarded Message
        # uncovered — the symptom that made --fix-missing-media's "saved N"
        # counter climb while files never appeared on disk.
        import tempfile

        from django.core.files.base import ContentFile
        from django.test import override_settings

        from webapp.models import MessagePicture

        forwarded = Message.objects.create(telegram_id=2, channel=self.channel)
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                # Seed the original — same telegram_id (=42, the photo id) the
                # mock _make_tg_message will use, attached to a different
                # Message.
                original_row = MessagePicture.objects.create(message=self.message, telegram_id=42)
                original_row.picture.save("seed.jpg", ContentFile(b"seed-bytes"), save=True)

                tm = self._make_tg_message()
                tm.id = forwarded.telegram_id  # 2 — the forwarded Message
                src_file = os.path.join(media_root, "src.jpg")
                with open(src_file, "wb") as fh:
                    fh.write(b"new-bytes")
                self.handler_dl._download_media = MagicMock(return_value=src_file)
                result = self.handler_dl.download_message_picture(tm)

                self.assertEqual(result, 1)
                rows = MessagePicture.objects.filter(telegram_id=42).order_by("id")
                # One row per Message that references the photo.
                self.assertEqual(rows.count(), 2)
                self.assertEqual({row.message_id for row in rows}, {self.message.id, forwarded.id})
                # Both rows point at the same shared file under photos/<id>.<ext>.
                self.assertTrue(all(r.picture.name == "photos/42.jpg" for r in rows))


# ---------------------------------------------------------------------------
# MediaHandler — sibling-file reuse (forwarded media downloaded once)
# ---------------------------------------------------------------------------


class MediaHandlerSiblingReuseTests(TestCase):
    """A file already stored for the same Telegram file id is linked, not re-downloaded."""

    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client, download_images=True, download_video=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel_a = make_channel(telegram_id=10, label=self.org)
        self.channel_b = make_channel(telegram_id=20, label=self.org)
        self.original = Message.objects.create(telegram_id=1, channel=self.channel_a)
        self.forward = Message.objects.create(telegram_id=2, channel=self.channel_b)

    def _tg_photo_message(self, channel_tid: int, msg_tid: int, photo_id: int = 42) -> MagicMock:
        tm = MagicMock()
        tm.id = msg_tid
        tm.peer_id.channel_id = channel_tid
        tm.media.photo = MagicMock()
        tm.media.photo.id = photo_id
        tm.media.photo.date = None
        return tm

    def test_forward_links_to_existing_file_without_download(self) -> None:
        from django.core.files.base import ContentFile

        from webapp.models import MessagePicture

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                row = MessagePicture.objects.create(message=self.original, telegram_id=42)
                row.picture.save("seed.jpg", ContentFile(b"shared-bytes"), save=True)

                self.handler._download_media = MagicMock(return_value="/tmp/should-not-be-used.jpg")
                tm = self._tg_photo_message(channel_tid=20, msg_tid=2)
                result = self.handler.download_message_picture(tm)

                self.assertEqual(result, 1)
                self.handler._download_media.assert_not_called()
                linked = MessagePicture.objects.get(telegram_id=42, message=self.forward)
                self.assertEqual(linked.picture.name, "photos/42.jpg")
                # The shared bytes are still on disk, untouched.
                with open(os.path.join(media_root, "photos", "42.jpg"), "rb") as fh:
                    self.assertEqual(fh.read(), b"shared-bytes")

    def test_sibling_with_missing_disk_file_still_downloads(self) -> None:
        from webapp.models import MessagePicture

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                # A row exists but its file is gone from disk — reuse must not trust it.
                MessagePicture.objects.create(message=self.original, telegram_id=42, picture="photos/42.jpg")

                src = os.path.join(media_root, "src.jpg")
                with open(src, "wb") as fh:
                    fh.write(b"fresh-bytes")
                self.handler._download_media = MagicMock(return_value=src)
                tm = self._tg_photo_message(channel_tid=20, msg_tid=2)
                result = self.handler.download_message_picture(tm)

                self.assertEqual(result, 1)
                self.handler._download_media.assert_called_once()

    def test_video_document_reuses_sibling_file(self) -> None:
        from django.core.files.base import ContentFile

        from webapp.models import MessageVideo

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                row = MessageVideo.objects.create(message=self.original, telegram_id=77)
                row.video.save("seed.mp4", ContentFile(b"video-bytes"), save=True)

                tm = MagicMock()
                tm.id = 2
                tm.peer_id.channel_id = 20
                tm.document = None
                tm.media.document.id = 77
                tm.media.document.mime_type = "video/mp4"
                tm.media.document.attributes = []
                tm.media.document.date = None
                self.handler._download_media = MagicMock(return_value="/tmp/should-not-be-used.mp4")
                result = self.handler.download_message_video(tm)

                self.assertEqual(result, 1)
                self.handler._download_media.assert_not_called()
                linked = MessageVideo.objects.get(telegram_id=77, message=self.forward)
                self.assertEqual(linked.video.name, "videos/77.mp4")


# ---------------------------------------------------------------------------
# MediaHandler — download_message_video
# ---------------------------------------------------------------------------


class MediaHandlerMessageVideoTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_video=False by default
        self.handler_dl = MediaHandler(self.api_client, download_video=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, label=self.org)
        Message.objects.create(telegram_id=1, channel=self.channel)

    def _make_tg_message(self, mime_type: str = "video/mp4", has_document: bool = True) -> MagicMock:
        tm = MagicMock()
        tm.id = 1
        tm.peer_id.channel_id = 10
        if has_document:
            tm.document.mime_type = mime_type
            tm.media.document.mime_type = mime_type
        else:
            tm.document = None
            tm.media.document = None
        return tm

    def test_returns_zero_when_download_disabled(self) -> None:
        tm = self._make_tg_message()
        result = self.handler.download_message_video(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_returns_zero_when_no_document(self) -> None:
        tm = self._make_tg_message(has_document=False)
        tm.media = None
        result = self.handler_dl.download_message_video(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_returns_zero_when_not_video_mime_type(self) -> None:
        tm = self._make_tg_message(mime_type="image/jpeg")
        result = self.handler_dl.download_message_video(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    @patch("crawler.media_handler.MessageVideo.from_telegram_object")
    def test_downloads_video_with_correct_mime_type(self, mock_from_tg: MagicMock) -> None:
        tm = self._make_tg_message(mime_type="video/mp4")
        self.handler_dl._download_media = MagicMock(return_value="/tmp/test.mp4")
        result = self.handler_dl.download_message_video(tm)
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    def test_returns_zero_when_download_returns_empty(self) -> None:
        # Same zombie-row protection as for pictures: an empty _download_media
        # result must not propagate into a MessageVideo row with video=NULL.
        tm = self._make_tg_message(mime_type="video/mp4")
        self.handler_dl._download_media = MagicMock(return_value=None)
        with patch("crawler.media_handler.MessageVideo.from_telegram_object") as mock_from_tg:
            result = self.handler_dl.download_message_video(tm)
        self.assertEqual(result, 0)
        mock_from_tg.assert_not_called()

    def test_handles_file_migrate_error_gracefully(self) -> None:
        from telethon.errors.rpcerrorlist import FileMigrateError

        tm = self._make_tg_message()
        err = FileMigrateError.__new__(FileMigrateError)
        self.handler_dl._download_media = MagicMock(side_effect=err)
        result = self.handler_dl.download_message_video(tm)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# MediaHandler — download_message_audio
# ---------------------------------------------------------------------------


class MediaHandlerMessageAudioTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_audio=False by default
        self.handler_dl = MediaHandler(self.api_client, download_audio=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, label=self.org)
        Message.objects.create(telegram_id=1, channel=self.channel)

    def _make_tg_message(
        self,
        mime_type: str = "audio/mpeg",
        has_document: bool = True,
        attributes: list | None = None,
    ) -> MagicMock:
        tm = MagicMock()
        tm.id = 1
        tm.peer_id.channel_id = 10
        if has_document:
            tm.document.mime_type = mime_type
            tm.document.attributes = attributes or []
            tm.media.document.mime_type = mime_type
            tm.media.document.attributes = attributes or []
        else:
            tm.document = None
            tm.media.document = None
        return tm

    def test_returns_when_download_disabled(self) -> None:
        tm = self._make_tg_message()
        result = self.handler.download_message_audio(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_returns_when_no_document(self) -> None:
        tm = self._make_tg_message(has_document=False)
        tm.media = None
        result = self.handler_dl.download_message_audio(tm)
        self.assertEqual(result, 0)

    def test_skips_non_audio_mime_without_audio_attr(self) -> None:
        tm = self._make_tg_message(mime_type="application/pdf", attributes=[])
        result = self.handler_dl.download_message_audio(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    @patch("crawler.media_handler.MessageAudio.from_telegram_object")
    def test_downloads_audio_mime(self, mock_from_tg: MagicMock) -> None:
        tm = self._make_tg_message(mime_type="audio/mpeg")
        self.handler_dl._download_media = MagicMock(return_value="/tmp/song.mp3")
        result = self.handler_dl.download_message_audio(tm)
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()
        defaults = mock_from_tg.call_args.kwargs["defaults"]
        self.assertFalse(defaults["is_voice"])

    @patch("crawler.media_handler.MessageAudio.from_telegram_object")
    def test_downloads_voice_note_via_attribute(self, mock_from_tg: MagicMock) -> None:
        from telethon.tl.types import DocumentAttributeAudio

        attr = DocumentAttributeAudio(duration=3, voice=True)
        tm = self._make_tg_message(mime_type="audio/ogg", attributes=[attr])
        self.handler_dl._download_media = MagicMock(return_value="/tmp/voice.ogg")
        result = self.handler_dl.download_message_audio(tm)
        self.assertEqual(result, 1)
        defaults = mock_from_tg.call_args.kwargs["defaults"]
        self.assertTrue(defaults["is_voice"])

    def test_skips_sticker_documents(self) -> None:
        from telethon.tl.types import DocumentAttributeSticker

        attr = DocumentAttributeSticker(alt="🙂", stickerset=MagicMock())
        tm = self._make_tg_message(mime_type="audio/ogg", attributes=[attr])
        result = self.handler_dl.download_message_audio(tm)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# MediaHandler — download_message_sticker
# ---------------------------------------------------------------------------


class MediaHandlerMessageStickerTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_stickers=False by default
        self.handler_dl = MediaHandler(self.api_client, download_stickers=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, label=self.org)
        Message.objects.create(telegram_id=1, channel=self.channel)

    def _make_tg_message(
        self,
        mime_type: str = "image/webp",
        has_document: bool = True,
        attributes: list | None = None,
    ) -> MagicMock:
        tm = MagicMock()
        tm.id = 1
        tm.peer_id.channel_id = 10
        if has_document:
            tm.document.mime_type = mime_type
            tm.document.attributes = attributes or []
            tm.media.document.mime_type = mime_type
            tm.media.document.attributes = attributes or []
        else:
            tm.document = None
            tm.media.document = None
        return tm

    def test_returns_when_download_disabled(self) -> None:
        from telethon.tl.types import DocumentAttributeSticker

        attr = DocumentAttributeSticker(alt="🙂", stickerset=MagicMock())
        tm = self._make_tg_message(attributes=[attr])
        result = self.handler.download_message_sticker(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_skips_documents_without_sticker_attribute(self) -> None:
        tm = self._make_tg_message(mime_type="image/webp", attributes=[])
        result = self.handler_dl.download_message_sticker(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    @patch("crawler.media_handler.MessageSticker.from_telegram_object")
    def test_downloads_static_sticker(self, mock_from_tg: MagicMock) -> None:
        from telethon.tl.types import DocumentAttributeSticker

        attr = DocumentAttributeSticker(alt="🙂", stickerset=MagicMock())
        tm = self._make_tg_message(mime_type="image/webp", attributes=[attr])
        self.handler_dl._download_media = MagicMock(return_value="/tmp/sticker.webp")
        result = self.handler_dl.download_message_sticker(tm)
        self.assertEqual(result, 1)
        defaults = mock_from_tg.call_args.kwargs["defaults"]
        self.assertFalse(defaults["is_animated"])

    @patch("crawler.media_handler.MessageSticker.from_telegram_object")
    def test_marks_tgs_sticker_animated(self, mock_from_tg: MagicMock) -> None:
        from telethon.tl.types import DocumentAttributeSticker

        attr = DocumentAttributeSticker(alt="🌟", stickerset=MagicMock())
        tm = self._make_tg_message(mime_type="application/x-tgsticker", attributes=[attr])
        self.handler_dl._download_media = MagicMock(return_value="/tmp/sticker.tgs")
        result = self.handler_dl.download_message_sticker(tm)
        self.assertEqual(result, 1)
        defaults = mock_from_tg.call_args.kwargs["defaults"]
        self.assertTrue(defaults["is_animated"])


# ---------------------------------------------------------------------------
# MediaHandler — download_message_other_media
# ---------------------------------------------------------------------------


class MediaHandlerMessageOtherMediaTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_other_media=False by default
        self.handler_dl = MediaHandler(self.api_client, download_other_media=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, label=self.org)
        Message.objects.create(telegram_id=1, channel=self.channel)

    def _make_tg_message(self, mime_type: str = "application/pdf", has_document: bool = True) -> MagicMock:
        tm = MagicMock()
        tm.id = 1
        tm.peer_id.channel_id = 10
        if has_document:
            tm.document.mime_type = mime_type
            tm.media.document.mime_type = mime_type
        else:
            tm.document = None
            tm.media.document = None
        return tm

    def test_returns_when_download_disabled(self) -> None:
        tm = self._make_tg_message()
        result = self.handler.download_message_other_media(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_returns_when_no_document(self) -> None:
        tm = self._make_tg_message(has_document=False)
        tm.media = None
        result = self.handler_dl.download_message_other_media(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_skips_video_mime_type(self) -> None:
        tm = self._make_tg_message(mime_type="video/mp4")
        result = self.handler_dl.download_message_other_media(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_skips_audio_mime(self) -> None:
        # Audio mimes are claimed by download_message_audio now, not other_media.
        tm = self._make_tg_message(mime_type="audio/ogg")
        result = self.handler_dl.download_message_other_media(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    def test_skips_sticker_documents(self) -> None:
        from telethon.tl.types import DocumentAttributeSticker

        tm = self._make_tg_message(mime_type="application/x-tgsticker")
        tm.document.attributes = [DocumentAttributeSticker(alt="🙂", stickerset=MagicMock())]
        tm.media.document.attributes = tm.document.attributes
        result = self.handler_dl.download_message_other_media(tm)
        self.assertEqual(result, 0)
        self.api_client.client.download_media.assert_not_called()

    @patch("crawler.media_handler.MessageOtherMedia.from_telegram_object")
    def test_downloads_pdf_document(self, mock_from_tg: MagicMock) -> None:
        tm = self._make_tg_message(mime_type="application/pdf")
        self.handler_dl._download_media = MagicMock(return_value="/tmp/doc.pdf")
        result = self.handler_dl.download_message_other_media(tm)
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.MessageOtherMedia.from_telegram_object")
    def test_downloads_image_as_document(self, mock_from_tg: MagicMock) -> None:
        # Bot-posted images come as documents with image/* mime; the photo branch never sees them.
        tm = self._make_tg_message(mime_type="image/png")
        self.handler_dl._download_media = MagicMock(return_value="/tmp/img.png")
        result = self.handler_dl.download_message_other_media(tm)
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    def test_handles_file_migrate_error_gracefully(self) -> None:
        from telethon.errors.rpcerrorlist import FileMigrateError

        tm = self._make_tg_message()
        err = FileMigrateError.__new__(FileMigrateError)
        self.handler_dl._download_media = MagicMock(side_effect=err)
        try:
            self.handler_dl.download_message_other_media(tm)
        except Exception:
            self.fail("download_message_other_media raised an unexpected exception")


# ---------------------------------------------------------------------------
# MediaHandler — clean_leftovers
# ---------------------------------------------------------------------------


class MediaHandlerCleanLeftoversTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)

    @patch("crawler.media_handler.glob.glob", return_value=[])
    def test_no_leftover_files_no_error(self, _mock_glob: MagicMock) -> None:
        self.handler.clean_leftovers()  # must not raise

    @patch("crawler.media_handler.os.path.islink", return_value=False)
    @patch("crawler.media_handler.os.path.isfile", return_value=True)
    @patch("crawler.media_handler.os.remove")
    @patch("crawler.media_handler.glob.glob")
    def test_removes_all_leftover_photo_files(
        self, mock_glob: MagicMock, mock_remove: MagicMock, _isfile: MagicMock, _islink: MagicMock
    ) -> None:
        mock_glob.return_value = ["/base/photo_1.jpg", "/base/photo_2.jpg"]
        self.handler.clean_leftovers()
        self.assertEqual(mock_remove.call_count, 2)
        mock_remove.assert_any_call("/base/photo_1.jpg")
        mock_remove.assert_any_call("/base/photo_2.jpg")

    @patch("crawler.media_handler.os.path.islink", return_value=False)
    @patch("crawler.media_handler.os.path.isfile", return_value=True)
    @patch("crawler.media_handler.os.remove", side_effect=OSError("permission denied"))
    @patch("crawler.media_handler.glob.glob")
    def test_oserror_on_remove_is_logged_not_raised(
        self, mock_glob: MagicMock, _mock_remove: MagicMock, _isfile: MagicMock, _islink: MagicMock
    ) -> None:
        mock_glob.return_value = ["/base/photo_1.jpg"]
        try:
            self.handler.clean_leftovers()
        except OSError:
            self.fail("clean_leftovers raised OSError unexpectedly")

    @patch("crawler.media_handler.glob.glob", return_value=[])
    def test_removes_temp_dir_when_present(self, _mock_glob: MagicMock) -> None:
        from crawler.media_handler import MediaHandler

        with tempfile.TemporaryDirectory() as tmpdir:
            handler = MediaHandler(self.api_client, download_temp_dir=tmpdir)
            self.assertTrue(os.path.isdir(tmpdir))
            handler.clean_leftovers()
            self.assertFalse(os.path.isdir(tmpdir))

    @patch("crawler.media_handler.glob.glob", return_value=[])
    def test_no_temp_dir_does_not_raise(self, _mock_glob: MagicMock) -> None:
        self.handler.clean_leftovers()  # download_temp_dir is None — must not raise


# ---------------------------------------------------------------------------
# ChannelCrawler — get_basic_channel
# ---------------------------------------------------------------------------


class ChannelCrawlerGetBasicChannelTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = make_label(name="Org", is_in_target=True)

    def test_returns_channel_and_telegram_object_on_success(self) -> None:
        mock_tc = _make_telegram_channel(telegram_id=5, username="testchan")
        self.api_client.client.get_entity.return_value = mock_tc
        channel, tc = self.crawler.get_basic_channel(5)
        self.assertIsNotNone(channel)
        self.assertIs(tc, mock_tc)
        self.assertTrue(Channel.objects.filter(telegram_id=5).exists())

    def test_propagates_channel_private_error(self) -> None:
        from telethon.errors.rpcerrorlist import ChannelPrivateError

        err = ChannelPrivateError.__new__(ChannelPrivateError)
        self.api_client.client.get_entity.side_effect = err
        with self.assertRaises(ChannelPrivateError):
            self.crawler.get_basic_channel(99)

    def test_calls_api_client_wait_before_request(self) -> None:
        mock_tc = _make_telegram_channel(telegram_id=6, username="waitchan")
        self.api_client.client.get_entity.return_value = mock_tc
        self.crawler.get_basic_channel(6)
        self.api_client.wait.assert_called_once()

    def test_returns_none_none_when_get_entity_returns_falsy(self) -> None:
        self.api_client.client.get_entity.return_value = None
        channel, tc = self.crawler.get_basic_channel(7)
        self.assertIsNone(channel)
        self.assertIsNone(tc)

    def test_resolving_real_channel_clears_stale_user_account_flag(self) -> None:
        # A row mislabelled is_user_account/is_lost is self-healed the moment its id
        # resolves to a real Channel entity again.
        make_channel(telegram_id=8, username="healme", is_user_account=True, is_lost=True)
        self.api_client.client.get_entity.return_value = _make_telegram_channel(telegram_id=8, username="healme")

        channel, tc = self.crawler.get_basic_channel(8)

        self.assertIsNotNone(channel)
        self.assertFalse(channel.is_user_account)
        self.assertFalse(channel.is_lost)
        refreshed = Channel.objects.get(telegram_id=8)
        self.assertFalse(refreshed.is_user_account)
        self.assertFalse(refreshed.is_lost)


# ---------------------------------------------------------------------------
# ChannelCrawler — resolve_channel_or_classify (recycled-handle guard)
# ---------------------------------------------------------------------------


class ChannelCrawlerResolveRecycledHandleTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = make_label(name="Org", is_in_target=True)

    @staticmethod
    def _channel_private_error() -> errors.rpcerrorlist.ChannelPrivateError:
        return errors.rpcerrorlist.ChannelPrivateError.__new__(errors.rpcerrorlist.ChannelPrivateError)

    def test_recycled_handle_marks_original_lost_and_acquires_new_channel(self) -> None:
        # An in-target channel (telegram_id=100, @handle) is now gone; its numeric lookup
        # fails, and @handle has since been taken over by a DIFFERENT channel (id=200).
        make_channel(telegram_id=100, username="handle", label=self.org)
        squatter_tc = _make_telegram_channel(telegram_id=200, username="handle")

        def fake_get_entity(seed):
            if seed == "handle":
                return squatter_tc
            raise self._channel_private_error()

        self.api_client.client.get_entity.side_effect = fake_get_entity
        channel, tg_ch, status = self.crawler.resolve_channel_or_classify(100)

        # The original is treated as lost — its identity is NOT grafted onto the squatter.
        self.assertEqual(status, "lost")
        self.assertIsNone(channel)
        # …but the new owner is still acquired into the DB, left unattributed.
        squatter = Channel.objects.get(telegram_id=200)
        self.assertFalse(squatter.channel_labels.filter(label__is_in_target=True).exists())

    def test_username_fallback_resolving_same_id_is_ok(self) -> None:
        # Numeric lookup fails (e.g. stale access_hash) but the username still maps to the
        # SAME channel → genuine recovery, status "ok".
        make_channel(telegram_id=300, username="stillmine", label=self.org)
        same_tc = _make_telegram_channel(telegram_id=300, username="stillmine")

        def fake_get_entity(seed):
            if seed == "stillmine":
                return same_tc
            raise self._channel_private_error()

        self.api_client.client.get_entity.side_effect = fake_get_entity
        channel, tg_ch, status = self.crawler.resolve_channel_or_classify(300)

        self.assertEqual(status, "ok")
        self.assertIsNotNone(channel)
        self.assertEqual(channel.telegram_id, 300)

    def test_recycled_handle_resolving_to_user_marks_original_lost(self) -> None:
        # An in-target channel (telegram_id=400, @handle) is gone; its numeric lookup
        # fails and @handle has since been taken over by a USER account. The original is
        # the real identity and is simply lost — it must NOT be stamped is_user_account.
        from telethon.tl.types import User

        original = make_channel(telegram_id=400, username="handle", label=self.org, megagroup=True)
        user_entity = User(id=999)

        def fake_get_entity(seed):
            if seed == "handle":
                return user_entity
            raise ValueError("no cached entity")

        self.api_client.client.get_entity.side_effect = fake_get_entity
        channel, tg_ch, status = self.crawler.resolve_channel_or_classify(400)

        self.assertEqual(status, "lost")
        self.assertIsNone(channel)
        original.refresh_from_db()
        self.assertFalse(original.is_user_account)

    def test_user_verdict_with_channel_evidence_is_treated_as_lost(self) -> None:
        # The seed itself resolves to a User, but a known megagroup exists under that id
        # (recycled id / entity-cache confusion). Keep the real channel: status "lost".
        from telethon.tl.types import User

        make_channel(telegram_id=600, label=self.org, megagroup=True)
        self.api_client.client.get_entity.return_value = User(id=600)

        channel, tg_ch, status = self.crawler.resolve_channel_or_classify(600)
        self.assertEqual(status, "lost")
        self.assertIsNone(channel)

    def test_user_seed_without_channel_evidence_is_user_account(self) -> None:
        # No channel was ever known under this id → a genuine user account.
        from telethon.tl.types import User

        self.api_client.client.get_entity.return_value = User(id=700)
        channel, tg_ch, status = self.crawler.resolve_channel_or_classify(700)
        self.assertEqual(status, "user_account")
        self.assertIsNone(channel)


# ---------------------------------------------------------------------------
# ChannelCrawler — set_more_channel_details
# ---------------------------------------------------------------------------


class ChannelCrawlerSetMoreDetailsTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, label=self.org)

    def _make_tc(self) -> MagicMock:
        """Minimal telegram channel mock safe for set_more_channel_details."""
        tc = MagicMock()
        tc.restriction_reason = None
        tc.usernames = None
        return tc

    def _make_full_channel_response(self, participants: int = 500, about: str = "desc") -> MagicMock:
        resp = MagicMock()
        resp.full_chat.participants_count = participants
        resp.full_chat.about = about
        resp.full_chat.location = None
        resp.full_chat.linked_chat_id = None
        resp.full_chat.available_min_id = None
        resp.full_chat.slowmode_seconds = None
        resp.full_chat.admins_count = None
        resp.full_chat.online_count = None
        resp.full_chat.requests_pending = None
        resp.full_chat.theme_emoticon = None
        resp.full_chat.ttl_period = None
        resp.full_chat.boosts_applied = None
        resp.full_chat.boosts_unrestrict = None
        resp.full_chat.kicked_count = None
        resp.full_chat.banned_count = None
        resp.full_chat.antispam = False
        resp.full_chat.has_scheduled = False
        resp.full_chat.pinned_msg_id = None
        resp.full_chat.migrated_from_chat_id = None
        resp.chats = []
        return resp

    def test_sets_participants_count(self) -> None:
        tc = MagicMock()
        self.api_client.client.return_value = self._make_full_channel_response(participants=1234)
        self.crawler.set_more_channel_details(self.channel, tc)
        self.assertEqual(self.channel.participants_count, 1234)

    def test_sets_about(self) -> None:
        tc = MagicMock()
        self.api_client.client.return_value = self._make_full_channel_response(about="Great channel")
        self.crawler.set_more_channel_details(self.channel, tc)
        self.assertEqual(self.channel.about, "Great channel")

    def test_sets_location_when_empty(self) -> None:
        tc = MagicMock()
        fake_location = MagicMock()
        fake_location.address = "Test City, 42"
        resp = self._make_full_channel_response()
        resp.full_chat.location = fake_location
        self.api_client.client.return_value = resp
        self.channel.telegram_location = ""
        self.crawler.set_more_channel_details(self.channel, tc)
        self.assertEqual(self.channel.telegram_location, "Test City, 42")

    def test_overwrites_existing_location(self) -> None:
        tc = MagicMock()
        new_location = MagicMock()
        new_location.address = "New Street, 1"
        resp = self._make_full_channel_response()
        resp.full_chat.location = new_location
        self.api_client.client.return_value = resp
        self.channel.telegram_location = "existing location"
        self.crawler.set_more_channel_details(self.channel, tc)
        self.assertEqual(self.channel.telegram_location, "New Street, 1")

    def test_user_entity_does_not_flag_account(self) -> None:
        # channel was built from a real Channel entity; a User here is a recycled-handle
        # mix-up and must not mislabel the row (which would drop it from crawls).
        from telethon.tl.types import User

        self.crawler.set_more_channel_details(self.channel, User(id=123))
        self.channel.refresh_from_db()
        self.assertFalse(self.channel.is_user_account)

    def _make_linked_response(self, linked_id: int, *, megagroup: bool = True) -> MagicMock:
        """Full-channel response declaring ``linked_id`` as the linked chat, with its entity in chats."""
        resp = self._make_full_channel_response()
        resp.full_chat.linked_chat_id = linked_id
        resp.chats = [
            types.SimpleNamespace(
                id=linked_id,
                title="Linked chat",
                broadcast=not megagroup,
                megagroup=megagroup,
                gigagroup=False,
                username="linked_chat",
            )
        ]
        return resp

    def test_discovered_linked_group_inherits_parent_current_attribution(self) -> None:
        self.api_client.client.return_value = self._make_linked_response(222)
        self.crawler.set_more_channel_details(self.channel, self._make_tc())
        linked = Channel.objects.get(telegram_id=222)
        channel_labels = list(linked.channel_labels.all())
        self.assertEqual(len(channel_labels), 1)
        self.assertEqual(channel_labels[0].label, self.org)
        self.assertIsNone(channel_labels[0].start)
        self.assertIsNone(channel_labels[0].end)

    def test_discovered_linked_channel_inherits_from_group_parent(self) -> None:
        group = make_channel(telegram_id=2, label=self.org, broadcast=False, megagroup=True)
        self.api_client.client.return_value = self._make_linked_response(444, megagroup=False)
        self.crawler.set_more_channel_details(group, self._make_tc())
        linked = Channel.objects.get(telegram_id=444)
        self.assertTrue(linked.broadcast)
        self.assertEqual([a.label for a in linked.channel_labels.all()], [self.org])

    def test_discovered_linked_chat_copies_period_bounds(self) -> None:
        start, end = datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        parent = make_channel(telegram_id=3, label=self.org, attribution_start=start, attribution_end=end)
        self.api_client.client.return_value = self._make_linked_response(555)
        self.crawler.set_more_channel_details(parent, self._make_tc())
        attribution = Channel.objects.get(telegram_id=555).channel_labels.get()
        self.assertEqual((attribution.start, attribution.end), (start, end))

    def test_discovered_linked_chat_unattributed_when_parent_unattributed(self) -> None:
        parent = make_channel(telegram_id=4, to_inspect=True)
        self.api_client.client.return_value = self._make_linked_response(666)
        self.crawler.set_more_channel_details(parent, self._make_tc())
        self.assertEqual(Channel.objects.get(telegram_id=666).channel_labels.count(), 0)

    def test_existing_linked_chat_is_not_attributed_again(self) -> None:
        # Discovery (and the attribution copy with it) happens only when the linked
        # row is new — an existing row's analyst-managed timeline must stay untouched.
        existing = make_channel(telegram_id=777, broadcast=False, megagroup=True)
        self.api_client.client.return_value = self._make_linked_response(777)
        self.crawler.set_more_channel_details(self.channel, self._make_tc())
        self.assertEqual(existing.channel_labels.count(), 0)
        self.assertEqual(Channel.objects.filter(telegram_id=777).count(), 1)


# ---------------------------------------------------------------------------
# ChannelCrawler — search_channel
# ---------------------------------------------------------------------------


class ChannelCrawlerSearchChannelTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = make_label(name="Org", is_in_target=True)

    def _make_search_result(self, channels: list) -> MagicMock:
        result = MagicMock()
        result.chats = channels
        return result

    def test_calls_wait_before_api_call(self) -> None:
        self.api_client.client.return_value = self._make_search_result([])
        self.crawler.search_channel("ukraine")
        self.api_client.wait.assert_called_once()

    def test_creates_new_channels_from_results(self) -> None:
        mock_tc = _make_telegram_channel(telegram_id=100, username="newchan")
        self.api_client.client.return_value = self._make_search_result([mock_tc])
        found, new = self.crawler.search_channel("ukraine")
        self.assertEqual(found, 1)
        self.assertEqual(new, 1)
        self.assertTrue(Channel.objects.filter(telegram_id=100).exists())

    def test_skips_channel_already_in_db(self) -> None:
        make_channel(telegram_id=200, label=self.org)
        mock_tc = _make_telegram_channel(telegram_id=200, username="existing")
        self.api_client.client.return_value = self._make_search_result([mock_tc])
        initial_count = Channel.objects.count()
        found, new = self.crawler.search_channel("test")
        self.assertEqual(Channel.objects.count(), initial_count)
        self.assertEqual(found, 1)
        self.assertEqual(new, 0)

    def test_skips_result_without_id_attribute(self) -> None:
        tc_no_id = MagicMock(spec=[])  # no attributes
        self.api_client.client.return_value = self._make_search_result([tc_no_id])
        found, new = self.crawler.search_channel("test")
        self.assertEqual(found, 0)

    def test_returns_count_of_found_channels(self) -> None:
        channels = [_make_telegram_channel(telegram_id=300 + i, username=f"chan{i}") for i in range(3)]
        self.api_client.client.return_value = self._make_search_result(channels)
        found, new = self.crawler.search_channel("batch")
        self.assertEqual(found, 3)


# ---------------------------------------------------------------------------
# ChannelCrawler — pending forwards (DB-backed, crash-safe)
# ---------------------------------------------------------------------------


@override_settings(IGNORE_FLOODWAIT=True, TELEGRAM_FLOODWAIT_SLEEP_SECONDS=0)
class ChannelCrawlerPendingForwardsTests(TestCase):
    def setUp(self) -> None:
        from crawler import channel_crawler

        channel_crawler._UNRESOLVABLE_THIS_RUN.clear()
        self.addCleanup(channel_crawler._UNRESOLVABLE_THIS_RUN.clear)
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = make_label(name="Org", is_in_target=True)
        self.source_channel = make_channel(telegram_id=1, label=self.org)
        self.msg = Message.objects.create(telegram_id=1, channel=self.source_channel)

    def _set_pending(self, channel_id: int) -> None:
        self.msg.pending_forward_telegram_id = channel_id
        self.msg.save(update_fields=["pending_forward_telegram_id"])

    def _make_tg_message(
        self, msg_id: int, fwd_channel_id: int | None = None, channel_post: int | None = None
    ) -> MagicMock:
        """Build a minimal Telethon message mock safe to pass to get_message()."""
        tm = MagicMock()
        tm.id = msg_id
        tm.peer_id.channel_id = self.source_channel.telegram_id
        # TELEGRAM_OBJECT_PROPERTIES must have safe values (not raw MagicMocks).
        tm.date = None
        tm.edit_date = None
        tm.post_author = ""
        tm.out = False
        tm.mentioned = False
        tm.post = False
        tm.from_scheduled = False
        tm.message = ""
        tm.grouped_id = None
        tm.views = None
        tm.forwards = None
        tm.pinned = False
        tm.silent = False
        tm.replies = None
        tm.reply_to = None
        tm.factcheck = None
        tm.entities = []
        tm.media = None
        if fwd_channel_id is not None:
            tm.fwd_from.from_id.channel_id = fwd_channel_id
            tm.fwd_from.channel_post = channel_post
            tm.fwd_from.from_name = None
            tm.fwd_from.date = None
        else:
            tm.fwd_from = None
        return tm

    # -- get_message persists pending_forward_telegram_id to DB --

    def test_get_message_persists_pending_forward_to_db(self) -> None:
        """Novel forwarded-from channel is stored in DB so a crash does not lose it."""
        tm = self._make_tg_message(msg_id=99, fwd_channel_id=9999)

        self.crawler.get_message(self.source_channel, tm)

        msg = Message.objects.get(telegram_id=99, channel=self.source_channel)
        self.assertEqual(msg.pending_forward_telegram_id, 9999)
        self.assertIsNone(msg.forwarded_from)

    def test_get_message_does_not_set_pending_when_channel_already_in_db(self) -> None:
        """Known forwarded-from channel sets forwarded_from directly, no pending field."""
        fwd_channel = make_channel(telegram_id=7777, label=self.org)
        tm = self._make_tg_message(msg_id=100, fwd_channel_id=fwd_channel.telegram_id)

        self.crawler.get_message(self.source_channel, tm)

        msg = Message.objects.get(telegram_id=100, channel=self.source_channel)
        self.assertIsNone(msg.pending_forward_telegram_id)
        self.assertEqual(msg.forwarded_from, fwd_channel)

    def test_get_message_clears_stale_pending_when_channel_now_in_db(self) -> None:
        """If a previous run left pending_forward_telegram_id set and the channel is
        now in the DB, a fresh get_message() call clears the stale flag."""
        fwd_channel = make_channel(telegram_id=8888, label=self.org)
        self._set_pending(8888)  # stale flag from a previous crashed run

        tm = self._make_tg_message(msg_id=self.msg.telegram_id, fwd_channel_id=fwd_channel.telegram_id)

        self.crawler.get_message(self.source_channel, tm)

        self.msg.refresh_from_db()
        self.assertIsNone(self.msg.pending_forward_telegram_id)
        self.assertEqual(self.msg.forwarded_from, fwd_channel)

    # -- get_message gives a stored message its post's tags --

    def _tags_of(self, telegram_id: int) -> list[str]:
        msg = Message.objects.get(channel=self.source_channel, telegram_id=telegram_id)
        return sorted(msg.tag_links.values_list("tagging__tag__name", flat=True))

    def test_stored_share_of_a_tagged_post_takes_its_tags(self) -> None:
        from webapp.models import MessageTag
        from webapp.models.tag_models import tag_post

        origin = make_channel(telegram_id=7777, label=self.org)
        tag_post(Message.objects.create(telegram_id=5, channel=origin), MessageTag.objects.create(name="watch"))

        self.crawler.get_message(self.source_channel, self._make_tg_message(200, fwd_channel_id=7777, channel_post=5))
        self.assertEqual(self._tags_of(200), ["watch"])
        # A re-fetch of the same message adds nothing.
        self.crawler.get_message(self.source_channel, self._make_tg_message(200, fwd_channel_id=7777, channel_post=5))
        self.assertEqual(self._tags_of(200), ["watch"])

    def test_share_is_linked_before_its_source_channel_is_resolved(self) -> None:
        from webapp.models import MessageTag
        from webapp.models.tag_models import message_origin, tag_post

        # Tag a share whose source (9999) is still pending; its post is keyed by that id.
        self.crawler.get_message(self.source_channel, self._make_tg_message(201, fwd_channel_id=9999, channel_post=5))
        first = Message.objects.select_related("channel").get(channel=self.source_channel, telegram_id=201)
        self.assertEqual(message_origin(first), (9999, 5))
        tag_post(first, MessageTag.objects.create(name="watch"))

        self.crawler.get_message(self.source_channel, self._make_tg_message(202, fwd_channel_id=9999, channel_post=5))
        self.assertEqual(self._tags_of(202), ["watch"])

    def test_stored_original_of_a_tagged_share_takes_its_tags(self) -> None:
        from webapp.models import MessageTag
        from webapp.models.tag_models import tag_post

        sharer = make_channel(telegram_id=4444, label=self.org)
        share = Message.objects.create(
            telegram_id=3, channel=sharer, forwarded_from=self.source_channel, fwd_from_channel_post=50
        )
        tag_post(share, MessageTag.objects.create(name="watch"))

        self.crawler.get_message(self.source_channel, self._make_tg_message(50))
        self.assertEqual(self._tags_of(50), ["watch"])

    def test_unrelated_message_takes_no_tags(self) -> None:
        from webapp.models import MessageTag
        from webapp.models.tag_models import tag_post

        tag_post(self.msg, MessageTag.objects.create(name="watch"))
        self.crawler.get_message(self.source_channel, self._make_tg_message(203, fwd_channel_id=7777, channel_post=6))
        self.assertEqual(self._tags_of(203), [])

    # -- _resolve_pending_forwards reads from DB --

    def test_resolve_pending_does_nothing_when_db_empty(self) -> None:
        self.crawler._resolve_pending_forwards()
        self.api_client.client.get_entity.assert_not_called()

    def test_resolve_pending_sets_forwarded_from_and_clears_field(self) -> None:
        self._set_pending(5555)
        fwd_tc = _make_telegram_channel(telegram_id=5555, username="fwdchan")
        self.api_client.client.get_entity.return_value = fwd_tc

        self.crawler._resolve_pending_forwards()

        self.msg.refresh_from_db()
        self.assertIsNotNone(self.msg.forwarded_from)
        self.assertEqual(self.msg.forwarded_from.telegram_id, 5555)
        self.assertIsNone(self.msg.pending_forward_telegram_id)

    def test_resolve_pending_survives_crash_leftovers(self) -> None:
        """pending_forward_telegram_id set from a previous crashed session is resolved."""
        # Simulate: a prior run saved the field but crashed before resolving it.
        # A new ChannelCrawler instance (fresh session) should still fix it.
        self._set_pending(6666)
        fwd_tc = _make_telegram_channel(telegram_id=6666, username="leftover")
        self.api_client.client.get_entity.return_value = fwd_tc
        new_crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())

        new_crawler._resolve_pending_forwards()

        self.msg.refresh_from_db()
        self.assertEqual(self.msg.forwarded_from.telegram_id, 6666)
        self.assertIsNone(self.msg.pending_forward_telegram_id)

    def test_resolve_pending_batches_same_channel_one_api_call(self) -> None:
        """Multiple messages forwarded from the same channel require only one get_entity."""
        msg2 = Message.objects.create(telegram_id=2, channel=self.source_channel)
        self._set_pending(4444)
        msg2.pending_forward_telegram_id = 4444
        msg2.save(update_fields=["pending_forward_telegram_id"])
        fwd_tc = _make_telegram_channel(telegram_id=4444, username="shared")
        self.api_client.client.get_entity.return_value = fwd_tc

        self.crawler._resolve_pending_forwards()

        self.assertEqual(self.api_client.client.get_entity.call_count, 1)
        for m in [self.msg, msg2]:
            m.refresh_from_db()
            self.assertEqual(m.forwarded_from.telegram_id, 4444)
            self.assertIsNone(m.pending_forward_telegram_id)

    def test_resolve_pending_marks_private_channel(self) -> None:
        self._set_pending(3333)
        err = errors.rpcerrorlist.ChannelPrivateError.__new__(errors.rpcerrorlist.ChannelPrivateError)
        self.api_client.client.get_entity.side_effect = err

        self.crawler._resolve_pending_forwards()

        self.msg.refresh_from_db()
        self.assertEqual(self.msg.forwarded_from_private, 3333)
        self.assertIsNone(self.msg.forwarded_from)
        self.assertIsNone(self.msg.pending_forward_telegram_id)

    def test_resolve_pending_marks_unresolvable_as_private(self) -> None:
        """Telethon raises ValueError when it can't find the input entity (e.g. unknown
        access_hash). Treat that the same as ChannelPrivateError: preserve the channel_id
        in forwarded_from_private rather than dropping it."""
        self._set_pending(1608875596)
        self.api_client.client.get_entity.side_effect = ValueError(
            "Could not find the input entity for PeerUser(user_id=1608875596)"
        )

        self.crawler._resolve_pending_forwards()

        self.msg.refresh_from_db()
        self.assertEqual(self.msg.forwarded_from_private, 1608875596)
        self.assertIsNone(self.msg.forwarded_from)
        self.assertIsNone(self.msg.pending_forward_telegram_id)

    def test_resolve_pending_marks_channel_invalid_as_private(self) -> None:
        """CHANNEL_INVALID is the RPC twin of the ValueError above — we hold no access hash
        for the id, so Telegram refuses to address it. Permanent, not worth a retry."""
        self._set_pending(1503997693)
        err = errors.rpcerrorlist.ChannelInvalidError.__new__(errors.rpcerrorlist.ChannelInvalidError)
        self.api_client.client.get_entity.side_effect = err

        self.crawler._resolve_pending_forwards()

        self.msg.refresh_from_db()
        self.assertEqual(self.msg.forwarded_from_private, 1503997693)
        self.assertIsNone(self.msg.forwarded_from)
        self.assertIsNone(self.msg.pending_forward_telegram_id)

    def test_resolve_pending_gives_up_on_an_unclassified_error_for_the_rest_of_the_run(self) -> None:
        """_resolve_pending_forwards runs after every crawled channel, so an id that keeps
        failing must not cost an API call, a rate-limit wait and a traceback on each of them.
        The give-up is process-wide (the environment pass builds its own ChannelCrawler) and
        leaves the row pending, so the next run retries it."""
        self._set_pending(2468)
        self.api_client.client.get_entity.side_effect = RuntimeError("boom")

        self.crawler._resolve_pending_forwards()
        ChannelCrawler(self.api_client, MagicMock(), MagicMock())._resolve_pending_forwards()

        self.assertEqual(self.api_client.client.get_entity.call_count, 1)
        self.assertEqual(self.api_client.wait.call_count, 1)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.pending_forward_telegram_id, 2468)
        self.assertIsNone(self.msg.forwarded_from)

    def test_resolve_pending_on_flood_wait_keeps_field_for_retry(self) -> None:
        self._set_pending(2222)
        self.api_client.client.get_entity.side_effect = _flood_error(seconds=30)

        self.crawler._resolve_pending_forwards()

        self.msg.refresh_from_db()
        # Field must remain set so the next run retries it.
        self.assertEqual(self.msg.pending_forward_telegram_id, 2222)
        self.assertIsNone(self.msg.forwarded_from)

    def test_resolve_pending_calls_wait_once_per_unique_channel(self) -> None:
        msg2 = Message.objects.create(telegram_id=3, channel=self.source_channel)
        self._set_pending(1111)
        msg2.pending_forward_telegram_id = 2222
        msg2.save(update_fields=["pending_forward_telegram_id"])
        self.api_client.client.get_entity.return_value = _make_telegram_channel(telegram_id=1111)

        self.crawler._resolve_pending_forwards()

        self.assertEqual(self.api_client.wait.call_count, 2)


class GetMessageFirstSaveTests(TestCase):
    """get_message writes every Telegram-derived field before the steps that can fail on the network.

    A failing media download or reference lookup used to abort the call before the final save,
    leaving a row without its forward header that the next run (resuming from the newest stored
    id) never revisited.
    """

    def setUp(self) -> None:
        self.media_handler = MagicMock()
        self.media_handler.download_message_picture.side_effect = ConnectionError("download dropped")
        self.resolver = MagicMock()
        self.resolver.resolve_message_references.return_value = ["later"]
        self.crawler = ChannelCrawler(_make_api_client(), self.media_handler, self.resolver)
        self.channel = make_channel(telegram_id=1, label=make_label(name="Org", is_in_target=True))
        self.fwd_date = datetime.datetime(2024, 3, 1, 8, 0, tzinfo=datetime.timezone.utc)

    def _tg_message(self, msg_id: int, fwd_from: Any, text: str = "", entities: list | None = None) -> Any:
        return types.SimpleNamespace(
            id=msg_id,
            peer_id=types.SimpleNamespace(channel_id=self.channel.telegram_id),
            date=datetime.datetime(2024, 3, 2, 9, 0, tzinfo=datetime.timezone.utc),
            message=text,
            entities=entities or [],
            fwd_from=fwd_from,
            media=types.SimpleNamespace(photo=types.SimpleNamespace(id=77)),
            replies=None,
            reply_to=types.SimpleNamespace(reply_to_msg_id=7),
            factcheck=None,
            reactions=None,
            pinned=False,
            views=10,
            forwards=1,
            edit_date=None,
        )

    def test_hidden_user_forward_keeps_its_header_when_the_download_fails(self) -> None:
        from network.near_copies import original_text_q

        hidden = types.SimpleNamespace(from_id=None, from_name="Hidden Author", date=self.fwd_date, channel_post=None)
        with self.assertRaises(ConnectionError):
            self.crawler.get_message(self.channel, self._tg_message(10, hidden, text="shared text"))

        msg = Message.objects.get(channel=self.channel, telegram_id=10)
        self.assertEqual(msg.fwd_from_date, self.fwd_date)
        self.assertEqual(msg.fwd_from_from_name, "Hidden Author")
        self.assertEqual(msg.media_type, "photo")
        self.assertEqual(msg.reply_to_msg_id, 7)
        self.assertEqual(msg.missing_references, "later")
        self.assertFalse(Message.objects.filter(original_text_q(), pk=msg.pk).exists())

    def test_channel_forward_keeps_source_and_tags_when_the_download_fails(self) -> None:
        from webapp.models import MessageTag
        from webapp.models.tag_models import tag_post

        source = make_channel(telegram_id=4242, title="Source")
        tag_post(Message.objects.create(telegram_id=5, channel=source), MessageTag.objects.create(name="watch"))
        header = types.SimpleNamespace(
            from_id=types.SimpleNamespace(channel_id=4242), from_name=None, date=self.fwd_date, channel_post=5
        )
        with self.assertRaises(ConnectionError):
            self.crawler.get_message(self.channel, self._tg_message(11, header))

        msg = Message.objects.get(channel=self.channel, telegram_id=11)
        self.assertEqual(msg.forwarded_from, source)
        self.assertEqual(msg.fwd_from_channel_post, 5)
        self.assertEqual(msg.fwd_from_date, self.fwd_date)
        self.assertEqual(list(msg.tag_links.values_list("tagging__tag__name", flat=True)), ["watch"])

    def test_unknown_source_is_left_pending_when_the_download_fails(self) -> None:
        header = types.SimpleNamespace(
            from_id=types.SimpleNamespace(channel_id=9999), from_name=None, date=self.fwd_date, channel_post=3
        )
        with self.assertRaises(ConnectionError):
            self.crawler.get_message(self.channel, self._tg_message(12, header))
        self.assertEqual(Message.objects.get(channel=self.channel, telegram_id=12).pending_forward_telegram_id, 9999)

    def test_named_references_survive_a_failing_lookup(self) -> None:
        self.resolver.resolve_message_references.side_effect = ConnectionError("lookup dropped")
        link = types.SimpleNamespace(url="https://t.me/Other/12")
        with self.assertRaises(ConnectionError):
            self.crawler.get_message(
                self.channel, self._tg_message(13, None, text="see t.me/somechan", entities=[link])
            )
        msg = Message.objects.get(channel=self.channel, telegram_id=13)
        self.assertEqual(msg.missing_references, "other|somechan")
        self.media_handler.download_message_picture.assert_not_called()

    def test_resolver_verdict_replaces_the_named_references(self) -> None:
        self.media_handler.download_message_picture.side_effect = None
        self.media_handler.download_message_picture.return_value = 1
        self.resolver.resolve_message_references.return_value = []
        stored, images = self.crawler.get_message(self.channel, self._tg_message(14, None, text="see t.me/somechan"))
        self.assertEqual((stored, images), (True, 1))
        self.assertEqual(Message.objects.get(channel=self.channel, telegram_id=14).missing_references, "")


class ReplyPeerIdTests(SimpleTestCase):
    """``reply_to_peer_id`` is recorded only for replies to a message in another chat."""

    def _tg_message(self, reply_to: Any) -> Any:
        from telethon.tl.types import PeerChannel

        return types.SimpleNamespace(
            id=3,
            peer_id=PeerChannel(11),
            reply_to=reply_to,
            pinned=False,
            edit_date=None,
            views=None,
            forwards=None,
            replies=None,
        )

    def _header(self, msg_id: int | None, peer: Any) -> Any:
        from telethon.tl.types import MessageReplyHeader

        return MessageReplyHeader(reply_to_msg_id=msg_id, reply_to_peer_id=peer)

    def test_marks_the_other_chat(self) -> None:
        from crawler.channel_crawler import _reply_peer_id

        from telethon.tl.types import PeerChannel, PeerChat, PeerUser

        self.assertEqual(_reply_peer_id(self._tg_message(self._header(5, PeerChannel(12)))), -1000000000012)
        self.assertEqual(_reply_peer_id(self._tg_message(self._header(5, PeerUser(77)))), 77)
        self.assertEqual(_reply_peer_id(self._tg_message(self._header(5, PeerChat(88)))), -88)

    def test_ignores_same_chat_and_headerless_replies(self) -> None:
        from crawler.channel_crawler import _reply_peer_id

        from telethon.tl.types import PeerChannel

        self.assertIsNone(_reply_peer_id(self._tg_message(self._header(5, None))))
        self.assertIsNone(_reply_peer_id(self._tg_message(self._header(5, PeerChannel(11)))))
        self.assertIsNone(_reply_peer_id(self._tg_message(self._header(None, PeerChannel(12)))))
        self.assertIsNone(_reply_peer_id(self._tg_message(None)))

    def test_first_save_fields_carry_it(self) -> None:
        from telethon.tl.types import PeerChannel

        fields = ChannelCrawler._message_fields(
            types.SimpleNamespace(
                **vars(self._tg_message(self._header(5, PeerChannel(12)))), fwd_from=None, media=None, factcheck=None
            )
        )
        self.assertEqual((fields["reply_to_msg_id"], fields["reply_to_peer_id"]), (5, -1000000000012))

    def test_stats_refresh_backfills_but_never_clears(self) -> None:
        from crawler.channel_crawler import _build_msg_update_kwargs

        from telethon.tl.types import PeerChannel

        now = timezone.now()
        cross = _build_msg_update_kwargs(self._tg_message(self._header(5, PeerChannel(12))), now)
        self.assertEqual((cross["reply_to_msg_id"], cross["reply_to_peer_id"]), (5, -1000000000012))
        for reply_to in (None, self._header(5, None)):
            kwargs = _build_msg_update_kwargs(self._tg_message(reply_to), now)
            self.assertNotIn("reply_to_peer_id", kwargs)
            self.assertNotIn("reply_to_msg_id", kwargs)


# ---------------------------------------------------------------------------
# search_channels management command
# ---------------------------------------------------------------------------

_SEARCH_CMD = "crawler.management.commands.search_channels"


class SearchChannelsCommandTests(TestCase):
    def setUp(self) -> None:
        from webapp.models import SearchTerm

        self.term1 = SearchTerm.objects.create(word="ukraine")
        self.term2 = SearchTerm.objects.create(word="russia")

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_search_channel_called_for_each_term(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        from django.core.management import call_command

        mock_crawler = MagicMock()
        mock_crawler.search_channel.return_value = (0, 0)
        mock_crawler_cls.return_value = mock_crawler
        mock_tc_cls.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_tc_cls.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

        call_command("search_channels", stdout=io.StringIO(), stderr=io.StringIO())

        words_searched = {c.args[0] for c in mock_crawler.search_channel.call_args_list}
        self.assertIn("ukraine", words_searched)
        self.assertIn("russia", words_searched)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_last_check_updated_after_each_term(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        from django.core.management import call_command

        mock_crawler = MagicMock()
        mock_crawler.search_channel.return_value = (0, 0)
        mock_crawler_cls.return_value = mock_crawler
        mock_tc_cls.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_tc_cls.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

        call_command("search_channels", stdout=io.StringIO(), stderr=io.StringIO())

        self.term1.refresh_from_db()
        self.term2.refresh_from_db()
        self.assertIsNotNone(self.term1.last_check)
        self.assertIsNotNone(self.term2.last_check)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_processes_at_most_15_terms(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        from django.core.management import call_command

        from webapp.models import SearchTerm

        SearchTerm.objects.all().delete()
        for i in range(20):
            SearchTerm.objects.create(word=f"term{i}")

        mock_crawler = MagicMock()
        mock_crawler.search_channel.return_value = (0, 0)
        mock_crawler_cls.return_value = mock_crawler
        mock_tc_cls.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_tc_cls.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

        call_command("search_channels", amount=15, stdout=io.StringIO(), stderr=io.StringIO())

        self.assertEqual(mock_crawler.search_channel.call_count, 15)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_extra_term_matching_db_term_searched_once(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        from django.core.management import call_command

        mock_crawler = MagicMock()
        mock_crawler.search_channel.return_value = (0, 0)
        mock_crawler_cls.return_value = mock_crawler
        mock_tc_cls.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_tc_cls.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

        # "ukraine" already exists as a DB term (setUp). Passing it as an extra term —
        # as the Operations panel does when "Save to database" is checked — must not
        # search it twice. Mixed case exercises the normalisation in the dedup.
        call_command("search_channels", extra_terms=["Ukraine"], stdout=io.StringIO(), stderr=io.StringIO())

        searched = [c.args[0] for c in mock_crawler.search_channel.call_args_list]
        self.assertEqual(searched.count("ukraine"), 1)
        self.assertNotIn("Ukraine", searched)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_extra_term_not_in_db_is_searched(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        from django.core.management import call_command

        mock_crawler = MagicMock()
        mock_crawler.search_channel.return_value = (0, 0)
        mock_crawler_cls.return_value = mock_crawler
        mock_tc_cls.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_tc_cls.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

        call_command("search_channels", extra_terms=["belarus"], stdout=io.StringIO(), stderr=io.StringIO())

        searched = [c.args[0] for c in mock_crawler.search_channel.call_args_list]
        self.assertIn("belarus", searched)


# ---------------------------------------------------------------------------
# search_channels --add-channel: identifier parsing
# ---------------------------------------------------------------------------


class ParseChannelIdentifierTests(SimpleTestCase):
    def test_username_forms(self) -> None:
        for raw in ("SomeChan", "@SomeChan", "  @SomeChan  "):
            with self.subTest(raw=raw):
                self.assertEqual(parse_channel_identifier(raw), "SomeChan")

    def test_tme_link_forms(self) -> None:
        for raw in (
            "https://t.me/SomeChan",
            "http://t.me/SomeChan",
            "t.me/SomeChan",
            "www.t.me/SomeChan",
            "telegram.me/SomeChan",
            "HTTPS://T.ME/SomeChan",
            "https://t.me/s/SomeChan",  # web-preview link
            "https://t.me/SomeChan/1234",  # message link
            "https://t.me/SomeChan?single",
            "https://t.me/SomeChan#anchor",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_channel_identifier(raw), "SomeChan")

    def test_numeric_forms(self) -> None:
        self.assertEqual(parse_channel_identifier("1234567890"), 1234567890)
        # Bot-API marked form for channels/supergroups
        self.assertEqual(parse_channel_identifier("-1001234567890"), 1234567890)
        # t.me/c/<id>/<msg> internal links carry the bare channel id
        self.assertEqual(parse_channel_identifier("https://t.me/c/1234567890/55"), 1234567890)

    def test_invite_links_rejected(self) -> None:
        for raw in ("t.me/joinchat/AbCdEf", "https://t.me/+AbCdEf"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_channel_identifier(raw)

    def test_garbage_rejected(self) -> None:
        for raw in ("", "   ", "@", "https://example.com/foo", "t.me/"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_channel_identifier(raw)


# ---------------------------------------------------------------------------
# search_channels --add-channel: command behaviour
# ---------------------------------------------------------------------------


class SearchChannelsAddChannelTests(TestCase):
    """--add-channel resolution paths. No SearchTerm rows exist, so the term-search
    phase is a no-op and only the direct-add phase exercises the mocked crawler."""

    def _run(
        self, mock_crawler_cls: MagicMock, mock_tc_cls: MagicMock, identifiers: list[str]
    ) -> tuple[MagicMock, str]:
        from django.core.management import call_command

        mock_crawler = mock_crawler_cls.return_value
        mock_tc_cls.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_tc_cls.return_value.start.return_value.__exit__ = MagicMock(return_value=False)
        out = io.StringIO()
        call_command("search_channels", add_channels=identifiers, stdout=out, stderr=io.StringIO())
        return mock_crawler, out.getvalue()

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_new_channel_added(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        def _resolve(seed):
            return make_channel(telegram_id=42, username="newchan", title="New Chan"), MagicMock(), "ok"

        mock_crawler_cls.return_value.resolve_channel_or_classify.side_effect = _resolve
        mock_crawler, output = self._run(mock_crawler_cls, mock_tc_cls, ["https://t.me/NewChan/123"])

        # The t.me message link is normalised down to its username segment.
        mock_crawler.resolve_channel_or_classify.assert_called_once_with("NewChan")
        self.assertIn("added: New Chan", output)
        self.assertIn("1 added, 0 already in database, 0 not added", output)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_numeric_identifier_resolved_as_int(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        mock_crawler_cls.return_value.resolve_channel_or_classify.return_value = (None, None, "lost")
        mock_crawler, _ = self._run(mock_crawler_cls, mock_tc_cls, ["-1001234567890"])

        mock_crawler.resolve_channel_or_classify.assert_called_once_with(1234567890)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_channel_already_in_db_by_username_skips_api(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        make_channel(telegram_id=7, username="Existing", title="Existing Chan")

        # Mixed case + @ prefix: the DB lookup is case-insensitive.
        mock_crawler, output = self._run(mock_crawler_cls, mock_tc_cls, ["@existing"])

        mock_crawler.resolve_channel_or_classify.assert_not_called()
        self.assertIn("already in database: Existing Chan", output)
        self.assertIn("0 added, 1 already in database, 0 not added", output)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_channel_already_in_db_by_telegram_id_skips_api(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        make_channel(telegram_id=555, title="By Id")

        mock_crawler, output = self._run(mock_crawler_cls, mock_tc_cls, ["555"])

        mock_crawler.resolve_channel_or_classify.assert_not_called()
        self.assertIn("already in database: By Id", output)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_resolved_id_already_stored_under_changed_username(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        # The handle the analyst typed is new, but resolution lands on a telegram_id
        # already stored (the channel renamed itself): no new row is created.
        existing = make_channel(telegram_id=99, username="oldname", title="Renamed")
        mock_crawler_cls.return_value.resolve_channel_or_classify.return_value = (existing, MagicMock(), "ok")

        _, output = self._run(mock_crawler_cls, mock_tc_cls, ["@newname"])

        self.assertIn("already in database: Renamed", output)
        self.assertIn("(metadata refreshed)", output)
        self.assertIn("0 added, 1 already in database, 0 not added", output)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_unresolvable_identifiers_warn_and_run_continues(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        def _resolve(seed):
            # Lazy creation: the row must not exist when the DB pre-check runs.
            statuses = {"ghost": "lost", "hidden": "private", "someuser": "user_account"}
            if seed in statuses:
                return None, None, statuses[seed]
            return make_channel(telegram_id=1, username="ok", title="Ok"), MagicMock(), "ok"

        mock_crawler_cls.return_value.resolve_channel_or_classify.side_effect = _resolve

        _, output = self._run(mock_crawler_cls, mock_tc_cls, ["ghost", "hidden", "someuser", "ok", "t.me/joinchat/XYZ"])

        self.assertIn("not added (not found on Telegram)", output)
        self.assertIn("not added (channel is private)", output)
        self.assertIn("not added (resolves to a user account, not a channel)", output)
        self.assertIn("not added (invite links cannot be resolved to a channel)", output)
        self.assertIn("added: Ok", output)
        self.assertIn("1 added, 0 already in database, 4 not added", output)

    @override_settings(IGNORE_FLOODWAIT=True)
    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_flood_wait_skips_identifier_and_continues(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        def _resolve(seed):
            if seed == "first":
                raise _flood_error()
            # Lazy creation: the row must not exist when the DB pre-check runs.
            return make_channel(telegram_id=2, username="after", title="After"), MagicMock(), "ok"

        mock_crawler_cls.return_value.resolve_channel_or_classify.side_effect = _resolve

        _, output = self._run(mock_crawler_cls, mock_tc_cls, ["first", "after"])

        self.assertIn("flood wait, skipping", output)
        self.assertIn("added: After", output)
        self.assertIn("1 added, 0 already in database, 1 not added", output)

    @patch(f"{_SEARCH_CMD}.TelegramClient")
    @patch(f"{_SEARCH_CMD}.TelegramAPIClient")
    @patch(f"{_SEARCH_CMD}.ChannelCrawler")
    def test_adds_and_term_search_run_in_same_invocation(
        self, mock_crawler_cls: MagicMock, mock_api_cls: MagicMock, mock_tc_cls: MagicMock
    ) -> None:
        from webapp.models import SearchTerm

        SearchTerm.objects.create(word="ukraine")
        mock_crawler = mock_crawler_cls.return_value
        mock_crawler.search_channel.return_value = (0, 0)
        mock_crawler.resolve_channel_or_classify.return_value = (None, None, "lost")

        mock_crawler, output = self._run(mock_crawler_cls, mock_tc_cls, ["somechan"])

        mock_crawler.resolve_channel_or_classify.assert_called_once_with("somechan")
        self.assertEqual([c.args[0] for c in mock_crawler.search_channel.call_args_list], ["ukraine"])
        self.assertIn("Channel add complete.", output)
        self.assertIn("Search complete.", output)


# ---------------------------------------------------------------------------
# crawl_channels management command
# ---------------------------------------------------------------------------

_GET_CMD = "crawler.management.commands.crawl_channels"


class GetChannelsCommandTests(TestCase):
    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.ch1 = make_channel(telegram_id=1, label=self.org, title="Ch1")
        self.ch2 = make_channel(telegram_id=2, label=self.org, title="Ch2")

    def _patch_command(self) -> tuple:
        tc_patch = patch(f"{_GET_CMD}.TelegramClient")
        api_patch = patch(f"{_GET_CMD}.TelegramAPIClient")
        crawler_patch = patch(f"{_GET_CMD}.ChannelCrawler")
        media_patch = patch(f"{_GET_CMD}.MediaHandler")
        resolver_patch = patch(f"{_GET_CMD}.ReferenceResolver")
        return tc_patch, api_patch, crawler_patch, media_patch, resolver_patch

    def test_get_channel_called_for_each_in_target_channel(self) -> None:
        from django.core.management import call_command

        tc_p, api_p, crawler_p, media_p, resolver_p = self._patch_command()
        with tc_p as mock_tc, api_p, crawler_p as mock_crawler_cls, media_p as mock_media_cls, resolver_p:
            mock_crawler = MagicMock()
            mock_crawler_cls.return_value = mock_crawler
            mock_media = MagicMock()
            mock_media_cls.return_value = mock_media
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

            # `--channel-types` defaults to [] (factory empty) — pass an
            # explicit value so the in-target CHANNEL records survive the filter.
            call_command(
                "crawl_channels",
                get_new_messages=True,
                channel_types="CHANNEL",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

            telegram_ids_crawled = {c.args[0] for c in mock_crawler.get_channel.call_args_list}
            self.assertIn(self.ch1.telegram_id, telegram_ids_crawled)
            self.assertIn(self.ch2.telegram_id, telegram_ids_crawled)

    def test_get_missing_references_called_at_end(self) -> None:
        from django.core.management import call_command

        # Create a message with an unresolved reference so the command has something to retry.
        Message.objects.create(telegram_id=1, channel=self.ch1, missing_references="someref")

        tc_p, api_p, crawler_p, media_p, resolver_p = self._patch_command()
        with tc_p as mock_tc, api_p, crawler_p as mock_crawler_cls, media_p as mock_media_cls, resolver_p:
            mock_crawler = MagicMock()
            mock_crawler_cls.return_value = mock_crawler
            mock_media = MagicMock()
            mock_media_cls.return_value = mock_media
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

            call_command("crawl_channels", retry_references=True, stdout=io.StringIO(), stderr=io.StringIO())

            mock_crawler.get_missing_references.assert_called_once()

    def test_flood_wait_error_during_get_channel_is_skipped(self) -> None:
        from django.core.management import call_command

        tc_p, api_p, crawler_p, media_p, resolver_p = self._patch_command()
        with tc_p as mock_tc, api_p, crawler_p as mock_crawler_cls, media_p as mock_media_cls, resolver_p:
            flood_err = errors.FloodWaitError.__new__(errors.FloodWaitError)
            mock_crawler = MagicMock()
            mock_crawler.get_channel.side_effect = flood_err
            mock_crawler_cls.return_value = mock_crawler
            mock_media = MagicMock()
            mock_media_cls.return_value = mock_media
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

            # Should not raise — FloodWaitError is caught and the channel is skipped
            call_command("crawl_channels", stdout=io.StringIO(), stderr=io.StringIO())

    def test_clean_leftovers_called_after_crawl(self) -> None:
        from django.core.management import call_command

        tc_p, api_p, crawler_p, media_p, resolver_p = self._patch_command()
        with tc_p as mock_tc, api_p, crawler_p as mock_crawler_cls, media_p as mock_media_cls, resolver_p:
            mock_crawler = MagicMock()
            mock_crawler_cls.return_value = mock_crawler
            mock_media = MagicMock()
            mock_media_cls.return_value = mock_media
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

            call_command("crawl_channels", get_new_messages=True, stdout=io.StringIO(), stderr=io.StringIO())

            mock_media.clean_leftovers.assert_called_once()


class DatabaseLockRecoveryTests(TestCase):
    """A "database is locked" skip drops that one channel, never the rest of the run.

    ``_recover_db_lock`` closes the DB connection; a per-channel loop streaming from a chunked
    cursor (``iterator(chunk_size=10)``) then crashed fetching its next chunk. Inside a TestCase
    the real close is a no-op (atomic block, in-memory DB), so the connection is faked to count
    closes and ``cursor_iter`` fails any cursor left open across one — what SQLite does.
    """

    def setUp(self) -> None:
        org = make_label(name="Org", is_in_target=True)
        # More channels than the old chunk of 10, so a second chunk would have been fetched.
        self.telegram_ids = list(range(1, 13))
        for tid in self.telegram_ids:
            make_channel(telegram_id=tid, label=org, title=f"Ch{tid}")
        # Channels are crawled newest-first: lock the third one.
        self.locked_tid = 10
        self.closes = 0

    def _run(self, configure, **options) -> tuple[MagicMock, str]:
        from django.core.management import call_command
        from django.db import ProgrammingError
        from django.db.models.sql import compiler as sql_compiler

        real_cursor_iter = sql_compiler.cursor_iter

        def cursor_iter(cursor, sentinel, col_count, itersize):
            opened_at = self.closes
            for rows in real_cursor_iter(cursor, sentinel, col_count, itersize):
                if self.closes != opened_at:
                    raise ProgrammingError("Cannot operate on a closed database.")
                yield rows

        def close() -> None:
            self.closes += 1

        fake_connection = MagicMock(in_atomic_block=False)
        fake_connection.close.side_effect = close
        out = io.StringIO()
        with (
            patch(f"{_GET_CMD}.TelegramClient") as mock_tc,
            patch(f"{_GET_CMD}.TelegramAPIClient"),
            patch(f"{_GET_CMD}.ChannelCrawler") as mock_crawler_cls,
            patch(f"{_GET_CMD}.MediaHandler"),
            patch(f"{_GET_CMD}.ReferenceResolver"),
            patch(f"{_GET_CMD}.connection", fake_connection),
            patch("django.db.models.sql.compiler.cursor_iter", cursor_iter),
        ):
            mock_crawler = MagicMock()
            configure(mock_crawler)
            mock_crawler_cls.return_value = mock_crawler
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)
            call_command("crawl_channels", channel_types="CHANNEL", stdout=out, stderr=io.StringIO(), **options)
        return mock_crawler, out.getvalue()

    @staticmethod
    def _lock_for(telegram_id: int):
        from django.db import OperationalError

        def side_effect(seed, *args, **kwargs):
            if seed == telegram_id:
                raise OperationalError("database is locked")
            return 0

        return side_effect

    def test_lock_while_crawling_messages_skips_only_that_channel(self) -> None:
        def configure(crawler: MagicMock) -> None:
            crawler.get_channel.side_effect = self._lock_for(self.locked_tid)

        crawler, output = self._run(configure, get_new_messages=True)
        self.assertEqual(self.closes, 1)
        self.assertEqual([c.args[0] for c in crawler.get_channel.call_args_list], sorted(self.telegram_ids)[::-1])
        self.assertIn("Database locked by another program while crawling messages", output)
        self.assertIn("Crawl complete.", output)

    def test_lock_while_updating_channel_info_skips_only_that_channel(self) -> None:
        def configure(crawler: MagicMock) -> None:
            crawler.refresh_channel_info.side_effect = self._lock_for(self.locked_tid)

        crawler, output = self._run(configure, get_channels_info=True)
        self.assertEqual(self.closes, 1)
        self.assertEqual(len(crawler.refresh_channel_info.call_args_list), len(self.telegram_ids))
        self.assertIn("Crawl complete.", output)

    def test_lock_while_resolving_pending_forwards_does_not_abort_the_run(self) -> None:
        from django.db import OperationalError

        def configure(crawler: MagicMock) -> None:
            crawler._resolve_pending_forwards.side_effect = [OperationalError("database is locked")] + [None] * 20

        crawler, output = self._run(configure, get_new_messages=True)
        self.assertEqual(len(crawler.get_channel.call_args_list), len(self.telegram_ids))
        self.assertIn("while resolving forwarded channels", output)
        self.assertIn("Crawl complete.", output)


class DegreeRefreshTests(TestCase):
    """``--in-degrees`` / ``--out-degrees`` rewrite their channels and reset the ones that left both sets."""

    def setUp(self) -> None:
        org = make_label(name="Org", is_in_target=True)
        period = {"attribution_start": datetime.date(2023, 1, 1), "attribution_end": datetime.date(2023, 12, 31)}
        self.amplifier = make_channel(telegram_id=1, title="Amplifier", label=org, **period)
        self.source = make_channel(telegram_id=2, title="Source", label=org, **period)
        self.cited = Channel.objects.create(telegram_id=10, title="Cited")
        # Stale values from earlier refreshes of channels that no longer qualify:
        # never cited again, labels removed, cited only outside the in-target period.
        self.uncited = Channel.objects.create(telegram_id=11, title="Uncited", in_degree=5, out_degree=2)
        self.unlabelled = Channel.objects.create(telegram_id=12, title="Unlabelled", in_degree=7, out_degree=3)
        self.out_of_period = Channel.objects.create(telegram_id=13, title="OutOfPeriod", in_degree=4, out_degree=0)
        self.never_computed = Channel.objects.create(telegram_id=14, title="NeverComputed")
        for tid, cited, when in (
            (100, self.cited, _dated(2023, 6, 1)),
            (101, self.source, _dated(2023, 6, 2)),
            (102, self.out_of_period, _dated(2022, 6, 1)),
        ):
            Message.objects.create(telegram_id=tid, channel=self.amplifier, date=when, forwarded_from=cited)

    def _run(self, **options) -> None:
        from django.core.management import call_command

        call_command("crawl_channels", stdout=io.StringIO(), stderr=io.StringIO(), **options)

    def _degrees(self, channel: Channel) -> tuple[int | None, int | None]:
        channel.refresh_from_db()
        return channel.in_degree, channel.out_degree

    def test_channels_that_left_both_sets_are_reset(self) -> None:
        self._run(in_degrees=True, out_degrees=True)
        self.assertEqual(self._degrees(self.amplifier), (0, 1))
        self.assertEqual(self._degrees(self.source), (1, 0))
        self.assertEqual(self._degrees(self.cited), (1, 0))
        self.assertEqual(self._degrees(self.uncited), (0, 0))
        self.assertEqual(self._degrees(self.unlabelled), (0, 0))
        self.assertEqual(self._degrees(self.out_of_period), (0, 0))
        self.assertEqual(self._degrees(self.never_computed), (None, None))

    def test_reset_runs_when_nothing_is_cited(self) -> None:
        Message.objects.all().delete()
        self._run(out_degrees=True)
        self.assertEqual(self._degrees(self.uncited), (0, 0))
        self.assertEqual(self._degrees(self.out_of_period), (0, 0))

    def test_each_pass_keeps_to_its_own_channels(self) -> None:
        Channel.objects.filter(pk=self.source.pk).update(in_degree=9, out_degree=9)
        # --out-degrees owns the out-of-target channels: in-target ones keep their value.
        self._run(out_degrees=True)
        self.assertEqual(self._degrees(self.source), (9, 9))
        self.assertEqual(self._degrees(self.cited), (1, 0))
        Channel.objects.filter(pk=self.uncited.pk).update(in_degree=5, out_degree=2)
        # --in-degrees owns the in-target channels: out-of-target ones are left alone.
        self._run(in_degrees=True)
        self.assertEqual(self._degrees(self.source), (1, 0))
        self.assertEqual(self._degrees(self.uncited), (5, 2))


class GapCouldBeInTargetTests(TestCase):
    """hole_fixer._gap_could_be_in_target classifies gaps by their bounding stored-message dates."""

    def _dt(self, year, month, day):
        return timezone.make_aware(datetime.datetime(year, month, day), datetime.timezone.utc)

    def test_gap_outside_period_skipped(self) -> None:
        from crawler.hole_fixer import _gap_could_be_in_target

        intervals = [(datetime.date(2024, 1, 1), datetime.date(2024, 3, 31))]
        self.assertFalse(_gap_could_be_in_target(self._dt(2024, 6, 1), self._dt(2024, 6, 2), intervals))

    def test_gap_overlapping_period_kept(self) -> None:
        from crawler.hole_fixer import _gap_could_be_in_target

        intervals = [(datetime.date(2024, 1, 1), datetime.date(2024, 3, 31))]
        self.assertTrue(_gap_could_be_in_target(self._dt(2024, 2, 1), self._dt(2024, 2, 5), intervals))

    def test_gap_with_missing_bounding_date_kept(self) -> None:
        from crawler.hole_fixer import _gap_could_be_in_target

        intervals = [(datetime.date(2024, 1, 1), datetime.date(2024, 3, 31))]
        self.assertTrue(_gap_could_be_in_target(None, self._dt(2024, 6, 1), intervals))


class SkipOutOfTargetStorageTests(TestCase):
    """ChannelCrawler._skip_out_of_target gates message storage by in-target period (to_inspect = store all)."""

    def setUp(self) -> None:
        self.org = make_label(name="O", is_in_target=True)
        self.crawler = ChannelCrawler.__new__(ChannelCrawler)  # methods only; no client needed

    def _msg(self, year, month):
        import types

        return types.SimpleNamespace(date=datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc))

    def test_in_period_stored(self) -> None:
        ch = make_channel(
            telegram_id=1,
            label=self.org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 3, 31),
        )
        self.assertFalse(self.crawler._skip_out_of_target(ch, self._msg(2024, 2)))

    def test_out_of_period_skipped(self) -> None:
        ch = make_channel(
            telegram_id=2,
            label=self.org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 3, 31),
        )
        self.assertTrue(self.crawler._skip_out_of_target(ch, self._msg(2024, 6)))

    def test_to_inspect_stores_all(self) -> None:
        ch = make_channel(telegram_id=3, to_inspect=True)
        self.assertFalse(self.crawler._skip_out_of_target(ch, self._msg(2024, 6)))

    def test_none_date_stored(self) -> None:
        import types

        ch = make_channel(
            telegram_id=4,
            label=self.org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 3, 31),
        )
        self.assertFalse(self.crawler._skip_out_of_target(ch, types.SimpleNamespace(date=None)))


class InTargetPeriodQTests(TestCase):
    """_in_target_period_q: an always-on in-target period lifts the restriction instead of vanishing from the OR."""

    def setUp(self) -> None:
        from webapp.test_helpers import attribute, label_group

        self.attribute = attribute
        self.org = make_label(name="Org", is_in_target=True)
        self.nation = make_label("Italy", is_in_target=True, group=label_group("Nation", is_primary=False))
        self.api_client = _make_api_client()
        self.api_client.wait_time = 0
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())

    def _always_plus_bounded(self) -> Channel:
        channel = make_channel(telegram_id=1, label=self.nation)  # in target for all time
        self.attribute(channel, self.org, datetime.date(2024, 1, 1), datetime.date(2024, 3, 31))
        return channel

    def test_open_period_beside_a_bounded_one_is_no_restriction(self) -> None:
        self.assertIsNone(self.crawler._in_target_period_q(self._always_plus_bounded()))

    def test_bounded_periods_still_restrict(self) -> None:
        channel = make_channel(
            telegram_id=2,
            label=self.org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 3, 31),
        )
        Message.objects.create(telegram_id=1, channel=channel, date=_dated(2023, 6, 1))
        Message.objects.create(telegram_id=2, channel=channel, date=_dated(2024, 2, 1))
        period_q = self.crawler._in_target_period_q(channel)
        self.assertEqual(
            list(Message.objects.filter(period_q, channel=channel).values_list("telegram_id", flat=True)), [2]
        )

    def test_refresh_marks_a_deleted_message_outside_the_bounded_period_lost(self) -> None:
        channel = self._always_plus_bounded()
        Message.objects.create(telegram_id=5, channel=channel, date=_dated(2022, 6, 1))  # deleted on Telegram since
        Message.objects.create(telegram_id=6, channel=channel, date=_dated(2024, 2, 1))
        still_there = types.SimpleNamespace(
            id=6,
            date=_dated(2024, 2, 1),
            message="still here",
            media=None,
            pinned=False,
            edit_date=None,
            views=5,
            forwards=0,
            replies=None,
            factcheck=None,
            reactions=None,
        )
        self.api_client.client.iter_messages.return_value = iter([still_there])

        self.crawler.refresh_message_stats(channel, MagicMock())

        self.assertTrue(Message.objects.get(channel=channel, telegram_id=5).is_lost)
        self.assertFalse(Message.objects.get(channel=channel, telegram_id=6).is_lost)


class TelethonUnraisableFilterTests(TestCase):
    """The ``sys.unraisablehook`` filter swallows the "coroutine ignored
    GeneratorExit" noise Telethon emits when auto-reconnect abandons a
    connection loop, while forwarding every other unraisable untouched."""

    @staticmethod
    def _coro_from(filename: str) -> Any:
        """A stand-in coroutine object whose ``cr_code.co_filename`` is ``filename``."""
        code = types.SimpleNamespace(co_filename=filename)
        return types.SimpleNamespace(cr_code=code)

    @staticmethod
    def _unraisable(obj: Any, exc: BaseException, err_msg: str | None = None) -> Any:
        return types.SimpleNamespace(object=obj, exc_value=exc, exc_type=type(exc), err_msg=err_msg)

    @staticmethod
    def _closing_msg(qualname: str) -> str:
        """Python 3.14's ``err_msg`` for a coroutine finalised with ``object=None``."""
        return f"Exception ignored while closing generator <coroutine object {qualname} at 0x7d5ad8e8e4d0>"

    def setUp(self) -> None:
        self.forwarded: list = []
        self.hook = _make_telethon_unraisable_filter(self.forwarded.append)
        self.telethon = self._coro_from(f"/x/site-packages{_TELETHON_PKG_PATH}network/connection/connection.py")
        self.ours = self._coro_from("/home/jo/job/crawler/channel_crawler.py")

    def test_telethon_ignored_generator_exit_is_swallowed(self) -> None:
        self.hook(self._unraisable(self.telethon, RuntimeError("coroutine ignored GeneratorExit")))
        self.assertEqual(self.forwarded, [])

    def test_telethon_bare_generator_exit_is_swallowed(self) -> None:
        self.hook(self._unraisable(self.telethon, GeneratorExit()))
        self.assertEqual(self.forwarded, [])

    def test_non_telethon_generator_exit_is_forwarded(self) -> None:
        # A GeneratorExit artefact from our own coroutines is a real signal — keep it.
        u = self._unraisable(self.ours, RuntimeError("coroutine ignored GeneratorExit"))
        self.hook(u)
        self.assertEqual(self.forwarded, [u])

    def test_telethon_real_error_is_forwarded(self) -> None:
        # Only the GeneratorExit finalisation noise is filtered; genuine Telethon
        # errors surfaced through the hook must still be visible.
        u = self._unraisable(self.telethon, ValueError("genuine bug"))
        self.hook(u)
        self.assertEqual(self.forwarded, [u])

    def test_non_coroutine_object_is_forwarded(self) -> None:
        u = self._unraisable(object(), OSError("disk gone"))
        self.hook(u)
        self.assertEqual(self.forwarded, [u])

    def test_py314_telethon_loop_named_in_err_msg_is_swallowed(self) -> None:
        # Python 3.14+: no coroutine object, only its repr in err_msg.
        for qualname in ("Connection._recv_loop", "MTProtoSender._send_loop"):
            self.hook(
                self._unraisable(None, RuntimeError("coroutine ignored GeneratorExit"), self._closing_msg(qualname))
            )
        self.assertEqual(self.forwarded, [])

    def test_py314_other_coroutine_named_in_err_msg_is_forwarded(self) -> None:
        u = self._unraisable(
            None, RuntimeError("coroutine ignored GeneratorExit"), self._closing_msg("ChannelCrawler._recv_loop")
        )
        self.hook(u)
        self.assertEqual(self.forwarded, [u])

    def test_py314_telethon_loop_real_error_is_forwarded(self) -> None:
        u = self._unraisable(None, ValueError("genuine bug"), self._closing_msg("Connection._recv_loop"))
        self.hook(u)
        self.assertEqual(self.forwarded, [u])

    def test_real_finalisation_is_swallowed_without_touching_stderr(self) -> None:
        """End-to-end: a ``Connection._recv_loop`` coroutine whose code
        physically lives under a ``…/telethon/…`` path, GC-finalised while
        suspended inside an ``await`` in its ``finally`` (Telethon's exact
        shape), is swallowed with nothing written to stderr — by code path on
        Python < 3.14, by the qualname in ``err_msg`` on 3.14+."""
        import contextlib
        import gc
        import importlib.util
        import sys

        work_dir = tempfile.mkdtemp()
        try:
            pkg_dir = os.path.join(work_dir, "telethon")
            os.makedirs(pkg_dir)
            mod_path = os.path.join(pkg_dir, "connection.py")
            with open(mod_path, "w") as handle:
                handle.write(
                    "class _suspend:\n"
                    "    def __await__(self):\n"
                    "        yield\n"
                    "class Connection:\n"
                    "    async def _recv_loop(self):\n"
                    "        try:\n"
                    "            await _suspend()\n"
                    "        finally:\n"
                    "            await _suspend()\n"
                )
            spec = importlib.util.spec_from_file_location("telethon._unraisable_probe", mod_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            seen: list = []
            previous = sys.unraisablehook
            sys.unraisablehook = _make_telethon_unraisable_filter(seen.append)
            stderr_buffer = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr_buffer):
                    coro = module.Connection()._recv_loop()
                    coro.send(None)  # suspend inside the try
                    del coro
                    gc.collect()
            finally:
                sys.unraisablehook = previous

            self.assertEqual(seen, [])
            self.assertEqual(stderr_buffer.getvalue(), "")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


class FriendlyMediaErrorTests(TestCase):
    """``_friendly_media_error`` turns raw download exceptions into plain language
    a non-technical operator can read, and never leaks the Telethon RPC wording."""

    def test_file_reference_expired_is_plain_language(self) -> None:
        from crawler.media_handler import _friendly_media_error

        from telethon.errors.rpcerrorlist import FileReferenceExpiredError

        msg = _friendly_media_error(FileReferenceExpiredError.__new__(FileReferenceExpiredError))
        self.assertIn("Telegram no longer provides this file", msg)
        self.assertNotIn("GetFileRequest", msg)

    def test_file_reference_invalid_shares_wording(self) -> None:
        from crawler.media_handler import _friendly_media_error

        from telethon.errors.rpcerrorlist import FileReferenceInvalidError

        msg = _friendly_media_error(FileReferenceInvalidError.__new__(FileReferenceInvalidError))
        self.assertIn("Telegram no longer provides this file", msg)

    def test_file_migrate_is_plain_language(self) -> None:
        from crawler.media_handler import _friendly_media_error

        from telethon.errors.rpcerrorlist import FileMigrateError

        msg = _friendly_media_error(FileMigrateError.__new__(FileMigrateError))
        self.assertIn("moved this file to another server", msg)

    def test_message_does_not_exist_is_plain_language(self) -> None:
        from crawler.media_handler import _friendly_media_error

        self.assertIn("isn't stored in the database yet", _friendly_media_error(Message.DoesNotExist()))

    def test_unknown_error_falls_back_to_str(self) -> None:
        from crawler.media_handler import _friendly_media_error

        # Unrecognised errors are not hidden — the original text is preserved.
        self.assertEqual(_friendly_media_error(ValueError("raw low-level detail")), "raw low-level detail")


class FriendlyTelethonWarningTests(TestCase):
    """``_friendly_telethon_warning`` rewrites transient connection chatter and
    leaves everything else untouched."""

    def test_connection_reset_is_rewritten(self) -> None:
        from webapp_engine.command_logging import _friendly_telethon_warning

        out = _friendly_telethon_warning("Server closed the connection: [Errno 104] Connection reset by peer")
        self.assertEqual(out, "Lost contact with Telegram for a moment — reconnecting automatically.")

    def test_unrelated_warning_passes_through(self) -> None:
        from webapp_engine.command_logging import _friendly_telethon_warning

        self.assertIsNone(_friendly_telethon_warning("Gap detected in updates; some messages may be missing"))


class MediaHandlerFriendlyLogIntegrationTests(TestCase):
    """The friendly reason actually reaches the crawl log — the raw Telethon
    "file reference has expired … GetFileRequest" text never appears."""

    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        # The TESTING block in webapp_engine/settings.py silences all logging via
        # logging.disable, which assertLogs cannot bypass — lift it for this class
        # (it asserts on log output) and restore it afterwards.
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)

        self.api_client = _make_api_client()
        self.handler_dl = MediaHandler(self.api_client, download_images=True)
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, label=self.org)
        self.message = Message.objects.create(telegram_id=1, channel=self.channel)

    def _tg_message(self) -> MagicMock:
        tm = MagicMock()
        tm.id = 1
        tm.peer_id.channel_id = 10
        tm.media.photo = MagicMock()
        tm.media.photo.id = 42
        tm.media.photo.date = None
        return tm

    def test_expired_reference_logs_friendly_text(self) -> None:
        from telethon.errors.rpcerrorlist import FileReferenceExpiredError

        tm = self._tg_message()
        self.handler_dl._download_media = MagicMock(
            side_effect=FileReferenceExpiredError.__new__(FileReferenceExpiredError)
        )
        with self.assertLogs("crawler.media_handler", level="WARNING") as captured:
            result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 0)
        logged = "\n".join(captured.output)
        self.assertIn("Couldn't download the picture in message 1", logged)
        self.assertIn("Telegram no longer provides this file", logged)
        self.assertNotIn("GetFileRequest", logged)


# ---------------------------------------------------------------------------
# crawl_channels --environment: window, candidate discovery, windowed get_channel
# ---------------------------------------------------------------------------


class EnvironmentWindowTests(TestCase):
    """The environment window spans the in-scope channels' in-target periods."""

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)

    def test_window_spans_earliest_start_to_latest_end(self) -> None:
        make_channel(
            telegram_id=1,
            label=self.org,
            attribution_start=datetime.date(2022, 3, 1),
            attribution_end=datetime.date(2022, 12, 31),
        )
        make_channel(
            telegram_id=2,
            label=self.org,
            attribution_start=datetime.date(2021, 1, 1),
            attribution_end=datetime.date(2021, 6, 30),
        )
        window = Command._environment_window(Channel.objects.all())
        self.assertEqual(window, (datetime.date(2021, 1, 1), datetime.date(2022, 12, 31)))

    def test_open_period_side_leaves_that_side_unbounded(self) -> None:
        make_channel(telegram_id=1, label=self.org, attribution_start=datetime.date(2022, 3, 1))
        make_channel(
            telegram_id=2,
            label=self.org,
            attribution_start=datetime.date(2021, 1, 1),
            attribution_end=datetime.date(2021, 6, 30),
        )
        self.assertEqual(Command._environment_window(Channel.objects.all()), (datetime.date(2021, 1, 1), None))

    def test_scope_without_in_target_periods_is_unbounded(self) -> None:
        Channel.objects.create(telegram_id=3, title="Inspect", to_inspect=True)
        self.assertEqual(Command._environment_window(Channel.objects.all()), (None, None))

    def test_only_scope_channels_count(self) -> None:
        inside = make_channel(
            telegram_id=1,
            label=self.org,
            attribution_start=datetime.date(2022, 1, 1),
            attribution_end=datetime.date(2022, 12, 31),
        )
        make_channel(telegram_id=2, label=self.org)  # open both sides, but out of the scope queryset
        window = Command._environment_window(Channel.objects.filter(pk=inside.pk))
        self.assertEqual(window, (datetime.date(2022, 1, 1), datetime.date(2022, 12, 31)))


def _dated(year: int, month: int, day: int) -> datetime.datetime:
    return datetime.datetime(year, month, day, 12, 0, tzinfo=datetime.timezone.utc)


class EnvironmentCandidatesTests(TestCase):
    """Level-1 candidates come from in-period citations of the scope; deeper levels from stored messages."""

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.scope = make_channel(
            telegram_id=1,
            title="Scope",
            label=self.org,
            attribution_start=datetime.date(2023, 1, 1),
            attribution_end=datetime.date(2023, 12, 31),
        )
        self.forwarded = Channel.objects.create(telegram_id=10, title="Forwarded")
        self.referenced = Channel.objects.create(telegram_id=11, title="Referenced")
        self.out_of_period = Channel.objects.create(telegram_id=12, title="OutOfPeriod")
        self.in_target_cited = make_channel(telegram_id=13, title="InTargetCited", label=self.org)
        self.inspect_cited = Channel.objects.create(telegram_id=14, title="InspectCited", to_inspect=True)
        self.user_cited = Channel.objects.create(telegram_id=15, title="UserCited", is_user_account=True)
        self.lost_cited = Channel.objects.create(telegram_id=16, title="LostCited", is_lost=True)
        self.group_cited = Channel.objects.create(telegram_id=17, title="GroupCited", megagroup=True)
        self.lost_msg_cited = Channel.objects.create(telegram_id=18, title="LostMessageCited")

        Message.objects.create(
            telegram_id=100, channel=self.scope, date=_dated(2023, 6, 1), forwarded_from=self.forwarded
        )
        ref_msg = Message.objects.create(telegram_id=101, channel=self.scope, date=_dated(2023, 6, 2))
        ref_msg.references.add(self.referenced)
        # Dated outside the in-target period: not a citation the graph would count.
        Message.objects.create(
            telegram_id=102, channel=self.scope, date=_dated(2022, 6, 1), forwarded_from=self.out_of_period
        )
        for tid, cited in ((103, self.in_target_cited), (104, self.inspect_cited), (105, self.user_cited)):
            Message.objects.create(telegram_id=tid, channel=self.scope, date=_dated(2023, 6, 3), forwarded_from=cited)
        for tid, cited in ((106, self.lost_cited), (107, self.group_cited)):
            Message.objects.create(telegram_id=tid, channel=self.scope, date=_dated(2023, 6, 4), forwarded_from=cited)
        Message.objects.create(
            telegram_id=108,
            channel=self.scope,
            date=_dated(2023, 6, 5),
            forwarded_from=self.lost_msg_cited,
            is_lost=True,
        )
        self.opts = _crawl_opts(channel_types=["CHANNEL"])
        self.scope_qs = Channel.objects.filter(pk=self.scope.pk)

    def _level1(self, opts=None) -> list[Channel]:
        return Command._environment_candidates(self.scope_qs, {self.scope.pk}, opts or self.opts)

    def test_level_one_is_the_in_period_citations_of_the_scope(self) -> None:
        self.assertEqual(self._level1(), [self.forwarded, self.referenced])

    def test_retry_lost_and_private_admits_lost_channels(self) -> None:
        found = self._level1(_crawl_opts(channel_types=["CHANNEL"], retry_lost_and_private=True))
        self.assertEqual(found, [self.forwarded, self.referenced, self.lost_cited])

    def test_channel_types_apply(self) -> None:
        found = self._level1(_crawl_opts(channel_types=["CHANNEL", "GROUP"]))
        self.assertIn(self.group_cited, found)

    def test_visited_channels_are_skipped(self) -> None:
        found = Command._environment_candidates(self.scope_qs, {self.scope.pk, self.forwarded.pk}, self.opts)
        self.assertEqual(found, [self.referenced])

    def test_deeper_level_reads_the_seeds_stored_messages_without_period_cutoff(self) -> None:
        deeper = Channel.objects.create(telegram_id=20, title="Deeper")
        deeper_ref = Channel.objects.create(telegram_id=21, title="DeeperRef")
        # Environment channels hold no in-target label, so their messages are used as stored.
        Message.objects.create(telegram_id=200, channel=self.forwarded, date=_dated(2023, 7, 1), forwarded_from=deeper)
        msg = Message.objects.create(telegram_id=201, channel=self.forwarded, date=_dated(2023, 7, 2))
        msg.references.add(deeper_ref)
        # A back-citation of the scope must not re-enter the environment.
        Message.objects.create(
            telegram_id=202, channel=self.forwarded, date=_dated(2023, 7, 3), forwarded_from=self.scope
        )
        visited = {self.scope.pk, self.forwarded.pk, self.referenced.pk}
        found = Command._environment_candidates([self.forwarded.pk, self.referenced.pk], visited, self.opts)
        self.assertEqual(found, [deeper, deeper_ref])

    def test_deeper_level_counts_only_citations_inside_the_window(self) -> None:
        # The seed stored messages past the window (an earlier, wider run; a to_inspect past).
        inside = Channel.objects.create(telegram_id=20, title="Inside")
        after = Channel.objects.create(telegram_id=21, title="After")
        boundary_ref = Channel.objects.create(telegram_id=22, title="BoundaryRef")
        before_ref = Channel.objects.create(telegram_id=23, title="BeforeRef")
        Message.objects.create(telegram_id=200, channel=self.forwarded, date=_dated(2023, 7, 1), forwarded_from=inside)
        Message.objects.create(telegram_id=201, channel=self.forwarded, date=_dated(2024, 1, 1), forwarded_from=after)
        last_day = Message.objects.create(telegram_id=202, channel=self.forwarded, date=_dated(2023, 12, 31))
        last_day.references.add(boundary_ref)  # bounds are inclusive
        too_early = Message.objects.create(telegram_id=203, channel=self.forwarded, date=_dated(2022, 12, 31))
        too_early.references.add(before_ref)
        visited = {self.scope.pk, self.forwarded.pk}
        window = (datetime.date(2023, 1, 1), datetime.date(2023, 12, 31))
        found = Command._environment_candidates([self.forwarded.pk], visited, self.opts, window)
        self.assertEqual(found, [inside, boundary_ref])
        # An open window side is unbounded.
        found = Command._environment_candidates([self.forwarded.pk], visited, self.opts, (None, window[1]))
        self.assertEqual(found, [inside, boundary_ref, before_ref])


class EnvironmentSeedScopeTests(TestCase):
    """The environment is seeded by the in-target channels only — to_inspect ones ride along in the scope."""

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.in_target = make_channel(
            telegram_id=1,
            title="InTarget",
            label=self.org,
            attribution_start=datetime.date(2023, 1, 1),
            attribution_end=datetime.date(2023, 12, 31),
        )
        self.inspect = Channel.objects.create(telegram_id=2, title="Inspect", to_inspect=True)
        self.cited_by_in_target = Channel.objects.create(telegram_id=10, title="CitedByInTarget")
        self.cited_by_inspect = Channel.objects.create(telegram_id=11, title="CitedByInspect")
        self.referenced_by_inspect = Channel.objects.create(telegram_id=12, title="ReferencedByInspect")

        Message.objects.create(
            telegram_id=100, channel=self.in_target, date=_dated(2023, 6, 1), forwarded_from=self.cited_by_in_target
        )
        Message.objects.create(
            telegram_id=101, channel=self.inspect, date=_dated(2023, 6, 1), forwarded_from=self.cited_by_inspect
        )
        ref_msg = Message.objects.create(telegram_id=102, channel=self.inspect, date=_dated(2023, 6, 2))
        ref_msg.references.add(self.referenced_by_inspect)

        self.opts = _crawl_opts(channel_types=["CHANNEL"])
        # The scope the command actually hands _crawl_environment: ever-in-target plus to_inspect.
        self.scope_qs = Command()._build_crawl_qs(self.opts)

    def _level1(self, scope_qs=None) -> list[Channel]:
        scope_qs = self.scope_qs if scope_qs is None else scope_qs
        return Command._environment_candidates(scope_qs, set(scope_qs.values_list("pk", flat=True)), self.opts)

    def test_the_crawl_scope_carries_the_inspect_channel(self) -> None:
        self.assertEqual(set(self.scope_qs), {self.in_target, self.inspect})

    def test_only_the_in_target_channels_citations_seed_level_one(self) -> None:
        # channel_cutoff_q() needs an in-target period covering the message date, and a
        # to_inspect-only channel has none — so neither its forward nor its t.me/ reference counts.
        self.assertEqual(self._level1(), [self.cited_by_in_target])

    def test_window_ignores_the_inspect_channel(self) -> None:
        self.assertEqual(
            Command._environment_window(self.scope_qs),
            (datetime.date(2023, 1, 1), datetime.date(2023, 12, 31)),
        )

    def test_to_inspect_is_no_disqualifier_when_the_channel_is_also_in_target(self) -> None:
        both = make_channel(
            telegram_id=3,
            title="Both",
            label=self.org,
            attribution_start=datetime.date(2023, 1, 1),
            attribution_end=datetime.date(2023, 12, 31),
        )
        both.to_inspect = True
        both.save(update_fields=["to_inspect"])
        cited = Channel.objects.create(telegram_id=13, title="CitedByBoth")
        Message.objects.create(telegram_id=103, channel=both, date=_dated(2023, 6, 1), forwarded_from=cited)
        self.assertEqual(self._level1(Command()._build_crawl_qs(self.opts)), [self.cited_by_in_target, cited])


class GetChannelMessageWindowTests(TestCase):
    """``get_channel(message_window=…)`` stores only in-window messages and clips the Telegram walk."""

    def setUp(self) -> None:
        self.channel = Channel.objects.create(telegram_id=500, title="Env")
        self.api_client = _make_api_client()
        self.api_client.wait_time = 0
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.crawler.resolve_channel_or_classify = MagicMock(return_value=(self.channel, MagicMock(), "ok"))
        self.crawler.set_more_channel_details = MagicMock()
        self.crawler._resolve_pending_forwards = MagicMock()
        self.seen: list[int] = []

        def fake_get_message(channel, telegram_message):
            self.seen.append(telegram_message.id)
            return True, 0

        self.crawler.get_message = fake_get_message
        self.window = (datetime.date(2023, 1, 1), datetime.date(2023, 12, 31))

    @staticmethod
    def _msg(msg_id: int, when: datetime.datetime) -> MagicMock:
        message = MagicMock()
        message.id = msg_id
        message.date = when
        return message

    def test_first_crawl_starts_at_window_start_and_stops_past_window_end(self) -> None:
        self.api_client.client.iter_messages.return_value = iter(
            [
                self._msg(1, _dated(2023, 1, 5)),
                self._msg(2, _dated(2023, 6, 1)),
                self._msg(3, _dated(2023, 12, 31)),
                self._msg(4, _dated(2024, 1, 2)),
                self._msg(5, _dated(2024, 3, 1)),
            ]
        )
        self.crawler.get_channel(500, message_window=self.window)
        self.assertEqual(self.seen, [1, 2, 3])
        kwargs = self.api_client.client.iter_messages.call_args.kwargs
        self.assertTrue(kwargs["reverse"])
        self.assertEqual(kwargs["min_id"], 0)
        self.assertEqual(
            kwargs["offset_date"],
            timezone.make_aware(datetime.datetime(2023, 1, 1)) - datetime.timedelta(seconds=1),
        )

    def test_history_walk_stops_before_window_start(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.channel, date=_dated(2023, 6, 1))
        self.channel.history_coverage = [["2023-06-01", None]]  # as migration 0066 leaves a crawled channel
        self.channel.save(update_fields=["history_coverage"])
        self.api_client.client.iter_messages.side_effect = [
            iter([]),  # recent messages above id 10
            iter(
                [self._msg(9, _dated(2023, 3, 1)), self._msg(8, _dated(2022, 12, 31)), self._msg(7, _dated(2022, 1, 1))]
            ),
        ]
        self.crawler.get_channel(500, message_window=self.window)
        self.assertEqual(self.seen, [9])
        recent_kwargs = self.api_client.client.iter_messages.call_args_list[0].kwargs
        self.assertNotIn("offset_date", recent_kwargs)  # not a first crawl
        self.assertEqual(self.api_client.client.iter_messages.call_args_list[1].kwargs["max_id"], 10)

    def test_window_drives_out_of_target_skip_for_unlabelled_channel(self) -> None:
        self.api_client.client.iter_messages.return_value = iter([])
        self.crawler.get_channel(500, message_window=self.window)
        inside = self._msg(1, _dated(2023, 6, 1))
        outside = self._msg(2, _dated(2022, 6, 1))
        self.assertFalse(self.crawler._skip_out_of_target(self.channel, inside))
        self.assertTrue(self.crawler._skip_out_of_target(self.channel, outside))

    def test_to_inspect_without_window_walks_from_the_start_and_keeps_everything(self) -> None:
        self.channel.to_inspect = True
        self.channel.save(update_fields=["to_inspect"])
        self.api_client.client.iter_messages.return_value = iter(
            [self._msg(1, _dated(2019, 1, 1)), self._msg(2, _dated(2025, 1, 1))]
        )
        self.crawler.get_channel(500)
        self.assertEqual(self.seen, [1, 2])
        self.assertNotIn("offset_date", self.api_client.client.iter_messages.call_args.kwargs)

    def test_nothing_required_walks_nothing(self) -> None:
        # No window, no in-target period, not to_inspect: get_message would store nothing.
        self.crawler.get_channel(500)
        self.api_client.client.iter_messages.assert_not_called()


class CoverageIntervalTests(SimpleTestCase):
    """``crawler.coverage``: inclusive local-date interval arithmetic, ``None`` = unbounded."""

    D = datetime.date

    def test_normalize_sorts_merges_adjacent_days_and_drops_empty(self) -> None:
        from crawler.coverage import normalize

        D = self.D
        self.assertEqual(
            normalize([(D(2021, 1, 1), None), (D(2020, 1, 11), D(2020, 2, 1)), (D(2020, 1, 5), D(2020, 1, 10))]),
            [(D(2020, 1, 5), D(2020, 2, 1)), (D(2021, 1, 1), None)],
        )
        self.assertEqual(normalize([(D(2022, 1, 2), D(2022, 1, 1))]), [])
        self.assertEqual(normalize([(None, D(2020, 1, 1)), (D(2019, 1, 1), None)]), [(None, None)])

    def test_subtract_and_intersect(self) -> None:
        from crawler.coverage import intersect, subtract

        D = self.D
        required = [(None, None)]
        covered = [(D(2021, 1, 1), D(2021, 12, 31)), (D(2023, 1, 1), D(2023, 6, 30))]
        self.assertEqual(
            subtract(required, covered),
            [(None, D(2020, 12, 31)), (D(2022, 1, 1), D(2022, 12, 31)), (D(2023, 7, 1), None)],
        )
        self.assertEqual(
            intersect([(D(2021, 6, 1), D(2023, 2, 1))], covered),
            [(D(2021, 6, 1), D(2021, 12, 31)), (D(2023, 1, 1), D(2023, 2, 1))],
        )

    def test_json_round_trip_drops_malformed_entries(self) -> None:
        from crawler.coverage import from_json, to_json

        D = self.D
        self.assertEqual(
            to_json([(None, D(2020, 1, 1)), (D(2021, 1, 1), None)]), [[None, "2020-01-01"], ["2021-01-01", None]]
        )
        self.assertEqual(
            from_json([[None, "2020-01-01"], ["garbage", None], [1, 2], "x", [None, None, None]]),
            [(None, D(2020, 1, 1))],
        )
        self.assertEqual(from_json(None), [])


class _FakeTelegramHistory:
    """A channel's Telegram history, served the way Telethon's ``iter_messages`` walks it.

    ``reverse=True`` walks up from ``min_id`` (or from ``offset_date``); otherwise the walk
    goes down from ``max_id`` (or from ``offset_date``, exclusive). ``fetched`` records the
    ids each call yielded; ``fail_after`` makes the next call raise after that many messages.
    """

    def __init__(self, messages: list[tuple[int, datetime.datetime]]) -> None:
        self.messages = sorted(messages)
        self.fetched: list[list[int]] = []
        self.fail_after: int | None = None

    def iter_messages(self, entity, *, wait_time=None, min_id=0, max_id=0, offset_date=None, reverse=False):
        if reverse:
            rows = [m for m in self.messages if m[0] > min_id and (offset_date is None or m[1] > offset_date)]
        else:
            rows = [
                m
                for m in reversed(self.messages)
                if m[0] > min_id and (not max_id or m[0] < max_id) and (offset_date is None or m[1] < offset_date)
            ]
        fetched: list[int] = []
        self.fetched.append(fetched)
        fail_after, self.fail_after = self.fail_after, None

        def walk():
            for count, (msg_id, when) in enumerate(rows):
                if count == fail_after:
                    raise ConnectionError("Connection to Telegram lost")
                fetched.append(msg_id)
                message = MagicMock()
                message.id = msg_id
                message.date = when
                yield message

        return walk()


class GetChannelHistoryCoverageTests(TestCase):
    """``get_channel`` walks only the required days missing from ``Channel.history_coverage`` — each once.

    No labelling change has to flag anything: an earlier start, an inserted middle period, a
    later middle end, to_inspect, a wider environment window all show as required days the
    coverage lacks.
    """

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = Channel.objects.create(telegram_id=500, title="Crawled")
        self.telegram = _FakeTelegramHistory(
            [
                (1, _dated(2020, 1, 10)),
                (2, _dated(2020, 6, 10)),
                (3, _dated(2021, 1, 10)),
                (4, _dated(2021, 6, 10)),
                (5, _dated(2022, 1, 10)),
                (6, _dated(2022, 6, 10)),
                (7, _dated(2023, 1, 10)),
                (8, _dated(2023, 6, 10)),
                (9, _dated(2024, 1, 10)),
                (10, _dated(2024, 6, 10)),
            ]
        )
        self.api_client = _make_api_client()
        self.api_client.wait_time = 0
        self.iter_messages = self.api_client.client.iter_messages
        self.iter_messages.side_effect = self.telegram.iter_messages
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        # A fresh row per crawl, as crawl_channels hands get_channel a telegram id.
        self.crawler.resolve_channel_or_classify = MagicMock(
            side_effect=lambda seed: (Channel.objects.get(telegram_id=seed), MagicMock(), "ok")
        )
        self.crawler._resolve_pending_forwards = MagicMock()
        self.stored: list[int] = []

        def fake_get_message(channel, telegram_message):
            if self.crawler._skip_out_of_target(channel, telegram_message):
                return False, 0
            self.stored.append(telegram_message.id)
            Message.objects.update_or_create(
                channel=channel, telegram_id=telegram_message.id, defaults={"date": telegram_message.date}
            )
            return True, 0

        self.crawler.get_message = fake_get_message
        self.today = timezone.localdate().isoformat()

    def _crawl(self, **kwargs) -> list[list[int]]:
        """Run one crawl; return the ids each Telegram walk of it fetched."""
        self.iter_messages.reset_mock()
        self.telegram.fetched = []
        self.stored = []
        self.crawler.get_channel(500, update_info=False, **kwargs)
        return self.telegram.fetched

    def _walk_kwargs(self, index: int) -> dict:
        return self.iter_messages.call_args_list[index].kwargs

    def _coverage(self) -> list:
        return Channel.objects.get(pk=self.channel.pk).history_coverage

    def _period(self, start=None, end=None):
        from webapp.test_helpers import attribute

        return attribute(self.channel, self.org, start, end)

    def test_first_crawl_covers_the_required_days_and_the_next_run_only_walks_up(self) -> None:
        self._period(datetime.date(2021, 1, 1), datetime.date(2021, 12, 31))
        self._period(datetime.date(2023, 1, 1))
        self.assertEqual(self._crawl(), [[3, 4, 5, 6, 7, 8, 9, 10]])
        self.assertEqual(self.stored, [3, 4, 7, 8, 9, 10])
        kwargs = self._walk_kwargs(0)
        self.assertTrue(kwargs["reverse"])
        self.assertEqual(
            kwargs["offset_date"], timezone.make_aware(datetime.datetime(2021, 1, 1)) - timedelta(seconds=1)
        )
        self.assertEqual(self._coverage(), [["2021-01-01", "2021-12-31"], ["2023-01-01", self.today]])
        self.assertTrue(Channel.objects.get(pk=self.channel.pk).are_messages_crawled)

        self.assertEqual(self._crawl(), [[]])  # unchanged channel: the walk up only, no history request
        self.assertEqual(self._walk_kwargs(0)["min_id"], 10)

    def test_walk_up_stops_past_the_last_required_day(self) -> None:
        self._period(datetime.date(2021, 1, 1), datetime.date(2021, 12, 31))
        self.assertEqual(self._crawl(), [[3, 4, 5]])
        self.assertEqual(self._coverage(), [["2021-01-01", "2021-12-31"]])
        self.assertEqual(self._crawl(), [[5]])  # one page above the newest stored message, never the years after

    def test_earlier_start_walks_down_once_to_the_new_start(self) -> None:
        period = self._period(datetime.date(2023, 1, 1))
        self._crawl()
        period.start = datetime.date(2021, 3, 1)
        period.save()
        self.assertEqual(self._crawl(), [[], [6, 5, 4, 3]])  # stops at the first message before the new start
        self.assertEqual(self.stored, [6, 5, 4])
        self.assertEqual(self._walk_kwargs(1)["max_id"], 7)  # right below the oldest stored message
        self.assertEqual(self._coverage(), [["2021-03-01", self.today]])
        self.assertEqual(self._crawl(), [[]])  # fetched once, not on every run

    def test_inserted_middle_period_is_fetched_from_its_end_down_to_its_start(self) -> None:
        self._period(datetime.date(2020, 1, 1), datetime.date(2020, 12, 31))
        self._period(datetime.date(2023, 1, 1))
        self._crawl()
        self.assertEqual(self._coverage(), [["2020-01-01", "2020-12-31"], ["2023-01-01", self.today]])

        self._period(datetime.date(2021, 6, 1), datetime.date(2022, 3, 31))
        self.assertEqual(self._crawl(), [[], [5, 4, 3]])
        self.assertEqual(self.stored, [5, 4])
        self.assertEqual(self._walk_kwargs(1)["offset_date"], timezone.make_aware(datetime.datetime(2022, 4, 1)))
        self.assertEqual(
            self._coverage(),
            [["2020-01-01", "2020-12-31"], ["2021-06-01", "2022-03-31"], ["2023-01-01", self.today]],
        )
        self.assertEqual(self._crawl(), [[]])

    def test_middle_period_end_moved_later_fetches_the_extension(self) -> None:
        middle = self._period(datetime.date(2020, 1, 1), datetime.date(2021, 3, 31))
        self._period(datetime.date(2023, 1, 1))
        self._crawl()
        middle.end = datetime.date(2022, 3, 31)
        middle.save()
        self.assertEqual(self._crawl(), [[], [5, 4, 3]])
        self.assertEqual(self.stored, [5, 4])
        self.assertEqual(self._coverage(), [["2020-01-01", "2022-03-31"], ["2023-01-01", self.today]])

    def test_to_inspect_fetches_the_older_and_middle_history_once(self) -> None:
        self._period(datetime.date(2021, 1, 1), datetime.date(2021, 12, 31))
        self._period(datetime.date(2023, 1, 1))
        self._crawl()
        Channel.objects.filter(pk=self.channel.pk).update(to_inspect=True)  # no save(), no signal: nothing to flag
        self.assertEqual(self._crawl(), [[], [6, 5, 4], [2, 1]])
        self.assertEqual(self.stored, [6, 5, 2, 1])
        self.assertEqual(self._walk_kwargs(1)["offset_date"], timezone.make_aware(datetime.datetime(2023, 1, 1)))
        self.assertEqual(self._walk_kwargs(2)["max_id"], 3)
        self.assertEqual(self._coverage(), [[None, self.today]])
        self.assertEqual(self._crawl(), [[]])

    def test_environment_window_widened_fetches_the_missing_slice_once(self) -> None:
        narrow = (datetime.date(2023, 1, 1), datetime.date(2023, 12, 31))
        wide = (datetime.date(2022, 1, 1), datetime.date(2024, 3, 31))
        self.assertEqual(self._crawl(message_window=narrow), [[7, 8, 9]])
        self.assertEqual(self.stored, [7, 8])
        self.assertEqual(self._coverage(), [["2023-01-01", "2023-12-31"]])

        self.assertEqual(self._crawl(message_window=wide), [[9, 10], [6, 5, 4]])
        self.assertEqual(self.stored, [9, 6, 5])
        self.assertEqual(self._walk_kwargs(1)["max_id"], 7)
        self.assertEqual(self._coverage(), [["2022-01-01", "2024-03-31"]])

        self.assertEqual(self._crawl(message_window=wide), [[10]])
        # A narrower scope later on: nothing newer than the stored history is required, nothing is missing.
        self.assertEqual(self._crawl(message_window=narrow), [])

    def test_crawled_channel_from_before_the_coverage_walks_below_its_oldest_message_once(self) -> None:
        # Migration 0066 leaves a crawled channel covered from its oldest stored message on.
        for msg_id, when in self.telegram.messages[6:]:
            Message.objects.create(channel=self.channel, telegram_id=msg_id, date=when)
        Channel.objects.filter(pk=self.channel.pk).update(history_coverage=[["2023-01-10", None]])
        self._period(datetime.date(2023, 1, 1))
        self.assertEqual(self._crawl(), [[], [6]])  # one request: nothing older was missing
        self.assertEqual(self._walk_kwargs(1)["max_id"], 7)
        self.assertEqual(self._coverage(), [["2023-01-01", None]])

    def test_interrupted_first_crawl_keeps_the_days_it_finished(self) -> None:
        self._period(datetime.date(2021, 1, 1))
        self.telegram.fail_after = 3
        with self.assertRaises(ConnectionError):
            self._crawl()
        self.assertEqual(self.stored, [3, 4, 5])
        # The last day reached (2022-01-10) may hold more messages: it is not claimed.
        self.assertEqual(self._coverage(), [["2021-01-01", "2022-01-09"]])

        self.assertEqual(self._crawl(), [[6, 7, 8, 9, 10], [5, 4]])  # only the unfinished day is walked again
        self.assertEqual(self._walk_kwargs(0)["min_id"], 5)
        self.assertEqual(self._walk_kwargs(1)["offset_date"], timezone.make_aware(datetime.datetime(2022, 1, 11)))
        self.assertEqual(self._coverage(), [["2021-01-01", self.today]])

    def test_interrupted_history_walk_keeps_the_days_it_finished(self) -> None:
        period = self._period(datetime.date(2023, 1, 1))
        self._crawl()
        period.start = datetime.date(2021, 1, 1)
        period.save()
        # The downward walk breaks off after two messages (2022-06-10, 2022-01-10).
        original = self.telegram.iter_messages

        def fail_history(entity, **kwargs):
            if not kwargs.get("reverse"):
                self.telegram.fail_after = 2
            return original(entity, **kwargs)

        self.iter_messages.side_effect = fail_history
        with self.assertRaises(ConnectionError):
            self._crawl()
        self.assertEqual(self._coverage(), [["2022-01-11", self.today]])

        self.iter_messages.side_effect = original
        self.assertEqual(self._crawl(), [[], [5, 4, 3, 2]])
        self.assertEqual(self._walk_kwargs(1)["offset_date"], timezone.make_aware(datetime.datetime(2022, 1, 11)))
        self.assertEqual(self._coverage(), [["2021-01-01", self.today]])

    def test_failure_to_record_the_interrupted_walk_does_not_mask_the_error(self) -> None:
        from django.db import OperationalError

        self._period(datetime.date(2021, 1, 1))
        self.telegram.fail_after = 2
        with (
            patch.object(ChannelCrawler, "_extend_coverage", side_effect=OperationalError("database is locked")),
            self.assertRaises(ConnectionError),
        ):
            self._crawl()

    def test_crawl_end_save_leaves_the_coverage_alone(self) -> None:
        # A purge trimming the coverage during a crawl is not undone by the crawl's final save.
        self._period(datetime.date(2023, 1, 1))

        def trim_meanwhile(*args, **kwargs):
            Channel.objects.filter(pk=self.channel.pk).update(history_coverage=[["2024-01-01", None]])

        self.crawler._resolve_pending_forwards.side_effect = trim_meanwhile
        self._crawl()
        self.assertEqual(self._coverage(), [["2024-01-01", None]])


class HistoryCoverageMigrationTests(TestCase):
    """Data migration 0066: a channel holding messages is covered from its oldest one's local date on."""

    @staticmethod
    def _run() -> None:
        import importlib

        from django.apps import apps

        importlib.import_module("webapp.migrations.0066_channel_history_coverage_init").init_history_coverage(
            apps, None
        )

    @override_settings(TIME_ZONE="Europe/Rome")
    def test_oldest_stored_message_local_date(self) -> None:
        crawled = Channel.objects.create(telegram_id=1)
        # 23:30 UTC on 9 January is already 10 January in Rome.
        Message.objects.create(
            channel=crawled, telegram_id=5, date=datetime.datetime(2023, 1, 9, 23, 30, tzinfo=datetime.timezone.utc)
        )
        Message.objects.create(channel=crawled, telegram_id=9, date=_dated(2024, 2, 1))
        empty = Channel.objects.create(telegram_id=2)
        undated = Channel.objects.create(telegram_id=3)
        Message.objects.create(channel=undated, telegram_id=1)
        self._run()
        coverage = dict(Channel.objects.values_list("telegram_id", "history_coverage"))
        self.assertEqual(coverage, {crawled.telegram_id: [["2023-01-10", None]], empty.telegram_id: [], 3: []})


class PurgeTrimsHistoryCoverageTests(TestCase):
    """``purge_out_of_target_messages`` drops the days whose messages it deletes from the crawler's coverage."""

    def test_purged_days_leave_the_coverage(self) -> None:
        from webapp.management.commands.purge_out_of_target_messages import purge

        org = make_label(name="Org", is_in_target=True)
        narrowed = make_channel(telegram_id=1, label=org, attribution_start=datetime.date(2023, 1, 1))
        Message.objects.create(channel=narrowed, telegram_id=1, date=_dated(2022, 6, 1))  # out of period
        Message.objects.create(channel=narrowed, telegram_id=2, date=_dated(2023, 6, 1))
        dropped = Channel.objects.create(telegram_id=2)  # no in-target period, not a forward source
        Message.objects.create(channel=dropped, telegram_id=1, date=_dated(2023, 6, 1))
        environment = Channel.objects.create(telegram_id=3, environment_depth=1)
        Message.objects.create(channel=environment, telegram_id=1, date=_dated(2019, 6, 1))
        for channel in (narrowed, dropped, environment):
            Channel.objects.filter(pk=channel.pk).update(history_coverage=[[None, "2026-01-01"]])

        purge()
        coverage = dict(Channel.objects.values_list("telegram_id", "history_coverage"))
        self.assertEqual(coverage, {1: [["2023-01-01", "2026-01-01"]], 2: [], 3: [[None, "2026-01-01"]]})


class EnvironmentCommandTests(TestCase):
    """``crawl_channels --environment`` crawls the cited channels level by level and stamps their distance."""

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.scope = make_channel(
            telegram_id=1,
            title="Scope",
            label=self.org,
            attribution_start=datetime.date(2023, 1, 1),
            attribution_end=datetime.date(2023, 12, 31),
        )
        self.level1 = Channel.objects.create(telegram_id=10, title="Level1")
        self.level2 = Channel.objects.create(telegram_id=20, title="Level2")
        Message.objects.create(telegram_id=100, channel=self.scope, date=_dated(2023, 6, 1), forwarded_from=self.level1)
        # Stored by an earlier environment run: what level 2 is discovered from.
        Message.objects.create(
            telegram_id=200, channel=self.level1, date=_dated(2023, 7, 1), forwarded_from=self.level2
        )

    def _run(self, configure=None, **options) -> MagicMock:
        from django.core.management import call_command

        with (
            patch(f"{_GET_CMD}.TelegramClient") as mock_tc,
            patch(f"{_GET_CMD}.TelegramAPIClient"),
            patch(f"{_GET_CMD}.ChannelCrawler") as mock_crawler_cls,
            patch(f"{_GET_CMD}.MediaHandler") as mock_media_cls,
            patch(f"{_GET_CMD}.ReferenceResolver"),
        ):
            mock_crawler = MagicMock()
            if configure is not None:
                configure(mock_crawler)
            mock_crawler_cls.return_value = mock_crawler
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)
            call_command(
                "crawl_channels", channel_types="CHANNEL", stdout=io.StringIO(), stderr=io.StringIO(), **options
            )
            self.media_calls = mock_media_cls.call_args_list
        return mock_crawler

    def test_depth_one_crawls_the_cited_channels_inside_the_window(self) -> None:
        crawler = self._run(environment=True)
        calls = {c.args[0]: c.kwargs for c in crawler.get_channel.call_args_list}
        self.assertEqual(set(calls), {self.level1.telegram_id})
        self.assertEqual(
            calls[self.level1.telegram_id]["message_window"], (datetime.date(2023, 1, 1), datetime.date(2023, 12, 31))
        )
        self.assertTrue(calls[self.level1.telegram_id]["update_info"])
        self.assertFalse(calls[self.level1.telegram_id]["fix_holes"])
        self.level1.refresh_from_db()
        self.level2.refresh_from_db()
        self.assertEqual(self.level1.environment_depth, 1)
        self.assertIsNone(self.level2.environment_depth)

    def test_depth_two_reaches_the_channels_cited_by_level_one(self) -> None:
        crawler = self._run(environment=True, environment_depth=2, fix_holes=True)
        crawled = [c.args[0] for c in crawler.get_channel.call_args_list]
        self.assertEqual(crawled, [self.level1.telegram_id, self.level2.telegram_id])
        self.assertTrue(all(c.kwargs["fix_holes"] for c in crawler.get_channel.call_args_list))
        self.level2.refresh_from_db()
        self.assertEqual(self.level2.environment_depth, 2)

    def test_smallest_distance_is_kept(self) -> None:
        self.level1.environment_depth = 3
        self.level1.save(update_fields=["environment_depth"])
        self._run(environment=True)
        self.level1.refresh_from_db()
        self.assertEqual(self.level1.environment_depth, 1)

    def test_deeper_level_ignores_citations_outside_the_window(self) -> None:
        # Level 1's history from before the window (e.g. stored while it was to_inspect).
        stale = Channel.objects.create(telegram_id=30, title="CitedBeforeTheWindow")
        Message.objects.create(telegram_id=201, channel=self.level1, date=_dated(2022, 6, 1), forwarded_from=stale)
        crawler = self._run(environment=True, environment_depth=2)
        crawled = [c.args[0] for c in crawler.get_channel.call_args_list]
        self.assertEqual(crawled, [self.level1.telegram_id, self.level2.telegram_id])
        stale.refresh_from_db()
        self.assertIsNone(stale.environment_depth)

    def test_failed_crawl_is_not_stamped_and_seeds_no_deeper_level(self) -> None:
        def configure(crawler: MagicMock) -> None:
            crawler.get_channel.side_effect = RuntimeError("Telegram hiccup")

        crawler = self._run(configure, environment=True, environment_depth=2)
        self.assertEqual([c.args[0] for c in crawler.get_channel.call_args_list], [self.level1.telegram_id])
        self.level1.refresh_from_db()
        self.level2.refresh_from_db()
        self.assertIsNone(self.level1.environment_depth)
        self.assertIsNone(self.level2.environment_depth)

    @override_settings(IGNORE_FLOODWAIT=True)
    def test_flood_waited_channel_is_not_stamped(self) -> None:
        def configure(crawler: MagicMock) -> None:
            crawler.get_channel.side_effect = _flood_error()

        self._run(configure, environment=True)
        self.level1.refresh_from_db()
        self.assertIsNone(self.level1.environment_depth)

    def test_channels_found_lost_private_or_user_accounts_are_not_stamped(self) -> None:
        private = self.level1
        lost = Channel.objects.create(telegram_id=11, title="Lost")
        user = Channel.objects.create(telegram_id=12, title="User")
        live = Channel.objects.create(telegram_id=13, title="Live")
        for tid, cited in ((101, lost), (102, user), (103, live)):
            Message.objects.create(telegram_id=tid, channel=self.scope, date=_dated(2023, 6, 1), forwarded_from=cited)
        flags = {private.telegram_id: "is_private", lost.telegram_id: "is_lost", user.telegram_id: "is_user_account"}

        def classify(seed, **kwargs):
            # What get_channel(update_info=True) does for such a channel: flag it and return 0.
            if seed in flags:
                Channel.objects.filter(telegram_id=seed).update(**{flags[seed]: True})
            return 0

        def configure(crawler: MagicMock) -> None:
            crawler.get_channel.side_effect = classify

        crawler = self._run(configure, environment=True, environment_depth=2)
        for channel in (private, lost, user, live):
            channel.refresh_from_db()
        self.assertEqual([private.environment_depth, lost.environment_depth, user.environment_depth], [None] * 3)
        self.assertEqual(live.environment_depth, 1)
        # The private channel's stored citation of level 2 seeds nothing.
        self.assertNotIn(self.level2.telegram_id, [c.args[0] for c in crawler.get_channel.call_args_list])

    def test_lock_while_resolving_pending_forwards_skips_only_that_step(self) -> None:
        from django.db import OperationalError

        other = Channel.objects.create(telegram_id=11, title="OtherLevel1")
        Message.objects.create(telegram_id=101, channel=self.scope, date=_dated(2023, 6, 1), forwarded_from=other)

        def configure(crawler: MagicMock) -> None:
            crawler._resolve_pending_forwards.side_effect = [OperationalError("database is locked"), None]

        crawler = self._run(configure, environment=True)
        self.assertEqual(len(crawler.get_channel.call_args_list), 2)
        self.level1.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((self.level1.environment_depth, other.environment_depth), (1, 1))

    def test_environment_media_handler_uses_its_own_toggles(self) -> None:
        self._run(environment=True, download_video=True, environment_download_images=True)
        # Two handlers: the scope one (video on, images off) and the environment one (images on, video off).
        env_kwargs = self.media_calls[-1].kwargs
        self.assertTrue(env_kwargs["download_images"])
        self.assertFalse(env_kwargs["download_video"])
        scope_kwargs = self.media_calls[0].kwargs
        self.assertTrue(scope_kwargs["download_video"])
        self.assertFalse(scope_kwargs["download_images"])

    def test_disabled_by_default(self) -> None:
        crawler = self._run(get_new_messages=True)
        crawled = {c.args[0] for c in crawler.get_channel.call_args_list}
        self.assertEqual(crawled, {self.scope.telegram_id})
        self.level1.refresh_from_db()
        self.assertIsNone(self.level1.environment_depth)

    def test_depth_below_one_is_rejected(self) -> None:
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("crawl_channels", environment=True, environment_depth=0, stdout=io.StringIO())
