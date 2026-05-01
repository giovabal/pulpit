import os
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.hole_fixer import find_missing_message_ids, fix_message_holes, iter_hole_ranges
from crawler.reference_resolver import ReferenceResolver
from webapp.models import Channel, Message, Organization

from telethon import errors

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_client() -> MagicMock:
    """Return a MagicMock that looks like a TelegramAPIClient."""
    api_client = MagicMock()
    api_client.wait.return_value = None
    return api_client


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
# ChannelCrawler._find_missing_message_ids
# ---------------------------------------------------------------------------


class FindMissingMessageIdsTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org1", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, organization=org)

    def _create_messages(self, telegram_ids: list[int]) -> None:
        for tid in telegram_ids:
            Message.objects.create(telegram_id=tid, channel=self.channel)

    def test_empty_channel_returns_empty(self) -> None:
        result = find_missing_message_ids(self.channel)
        self.assertEqual(result, [])

    def test_single_message_returns_empty(self) -> None:
        self._create_messages([5])
        result = find_missing_message_ids(self.channel)
        self.assertEqual(result, [])

    def test_consecutive_messages_no_holes(self) -> None:
        self._create_messages([1, 2, 3, 4, 5])
        result = find_missing_message_ids(self.channel)
        self.assertEqual(result, [])

    def test_single_gap_detected(self) -> None:
        self._create_messages([1, 2, 4, 5])
        result = find_missing_message_ids(self.channel)
        self.assertEqual(result, [3])

    def test_multiple_gaps_detected(self) -> None:
        self._create_messages([1, 2, 4, 7])
        result = find_missing_message_ids(self.channel)
        self.assertEqual(sorted(result), [3, 5, 6])

    def test_large_gap_fills_all_missing_ids(self) -> None:
        self._create_messages([1, 10])
        result = find_missing_message_ids(self.channel)
        self.assertEqual(result, list(range(2, 10)))

    def test_min_telegram_id_filters_earlier_messages(self) -> None:
        self._create_messages([1, 3, 5, 7])  # holes at 2, 4, 6
        result = find_missing_message_ids(self.channel, min_telegram_id=5)
        # Only [5, 7] are considered → hole at 6
        self.assertEqual(result, [6])

    def test_min_telegram_id_below_all_messages_includes_all(self) -> None:
        self._create_messages([2, 5])
        result = find_missing_message_ids(self.channel, min_telegram_id=1)
        self.assertEqual(result, [3, 4])

    def test_ordering_is_by_telegram_id(self) -> None:
        # Messages created in reverse order
        self._create_messages([5, 3, 1])
        result = find_missing_message_ids(self.channel)
        # Gaps between 1→3 (missing 2) and 3→5 (missing 4)
        self.assertEqual(sorted(result), [2, 4])


# ---------------------------------------------------------------------------
# iter_hole_ranges
# ---------------------------------------------------------------------------


class IterHoleRangesTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=50, organization=org)

    def _create_messages(self, telegram_ids: list[int]) -> None:
        for tid in telegram_ids:
            Message.objects.create(telegram_id=tid, channel=self.channel)

    def test_empty_channel_yields_nothing(self) -> None:
        self.assertEqual(list(iter_hole_ranges(self.channel)), [])

    def test_single_message_yields_nothing(self) -> None:
        self._create_messages([5])
        self.assertEqual(list(iter_hole_ranges(self.channel)), [])

    def test_consecutive_messages_yield_nothing(self) -> None:
        self._create_messages([1, 2, 3, 4, 5])
        self.assertEqual(list(iter_hole_ranges(self.channel)), [])

    def test_single_gap_of_one_yields_correct_range(self) -> None:
        self._create_messages([1, 3])
        self.assertEqual(list(iter_hole_ranges(self.channel)), [(2, 2)])

    def test_large_gap_yields_inclusive_range(self) -> None:
        self._create_messages([1, 10])
        self.assertEqual(list(iter_hole_ranges(self.channel)), [(2, 9)])

    def test_multiple_gaps_yield_multiple_ranges(self) -> None:
        self._create_messages([1, 3, 6])
        self.assertEqual(list(iter_hole_ranges(self.channel)), [(2, 2), (4, 5)])

    def test_min_telegram_id_excludes_earlier_ranges(self) -> None:
        self._create_messages([1, 3, 5, 7])  # gaps at 2, 4, 6
        result = list(iter_hole_ranges(self.channel, min_telegram_id=5))
        self.assertEqual(result, [(6, 6)])

    def test_min_telegram_id_below_all_messages_includes_all(self) -> None:
        self._create_messages([2, 5])
        result = list(iter_hole_ranges(self.channel, min_telegram_id=1))
        self.assertEqual(result, [(3, 4)])

    def test_returns_generator(self) -> None:
        import types

        self._create_messages([1, 3])
        self.assertIsInstance(iter_hole_ranges(self.channel), types.GeneratorType)

    def test_orm_sorts_ascending_regardless_of_insertion_order(self) -> None:
        self._create_messages([10, 5, 1])  # created in reverse order
        result = list(iter_hole_ranges(self.channel))
        # gaps: 1→5 → (2,4), 5→10 → (6,9)
        self.assertEqual(result, [(2, 4), (6, 9)])


# ---------------------------------------------------------------------------
# fix_message_holes
# ---------------------------------------------------------------------------


class FixMessageHolesTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=60, organization=org)
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
    def _noop_get_message_fn(ch, tm) -> int:
        return 0

    def _run(
        self,
        remaining_limit: int | None = None,
        get_message_fn=None,
    ) -> tuple[int, int]:
        if get_message_fn is None:
            get_message_fn = self._noop_get_message_fn
        return fix_message_holes(
            self.channel,
            self.telegram_channel,
            self.api_client,
            get_message_fn,
            remaining_limit,
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

    # -- remaining_limit --

    def test_remaining_limit_truncates_fetch_count(self) -> None:
        self._create_messages([1, 152])  # 150 holes
        result = self._run(remaining_limit=50)
        self.assertEqual(result, (50, 0))

    def test_remaining_limit_emits_limit_reached_status(self) -> None:
        self._create_messages([1, 152])  # 150 holes
        self._run(remaining_limit=50)
        self.assertIn("CHAN | hole-fix limit reached, checkpoint saved", self.status_messages)

    def test_remaining_limit_checkpoint_at_last_processed_id(self) -> None:
        self._create_messages([1, 152])  # holes start at 2
        self._run(remaining_limit=50)
        # 50 holes processed: IDs 2..51 → last batch[-1] = 51
        self.assertEqual(self.channel.last_hole_check_max_telegram_id, 51)

    def test_remaining_limit_exceeds_holes_no_limit_status(self) -> None:
        self._create_messages([1, 6])  # 4 holes
        self._run(remaining_limit=100)
        self.assertNotIn("CHAN | hole-fix limit reached, checkpoint saved", self.status_messages)

    def test_remaining_limit_exceeds_holes_processes_all(self) -> None:
        self._create_messages([1, 6])  # 4 holes
        result = self._run(remaining_limit=100)
        self.assertEqual(result, (4, 0))

    def test_remaining_limit_none_processes_all(self) -> None:
        self._create_messages([1, 102])  # 100 holes
        result = self._run(remaining_limit=None)
        self.assertEqual(result, (100, 0))

    # -- None / image handling --

    def test_none_messages_are_skipped(self) -> None:
        self._create_messages([1, 3])  # hole at 2
        self.api_client.client.get_messages.side_effect = lambda tc, ids: [None]
        result = self._run()
        self.assertEqual(result, (0, 0))

    def test_images_counted_in_return_value(self) -> None:
        def one_image_fn(ch, tm) -> int:
            return 1

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
        self.org = Organization.objects.create(name="Org", is_interesting=True)

    def test_returns_existing_db_channel_without_api_call(self) -> None:
        channel = Channel.objects.create(telegram_id=1, username="existingchan", organization=self.org)
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


# ---------------------------------------------------------------------------
# ReferenceResolver.resolve_message_references
# ---------------------------------------------------------------------------


class ResolveMessageReferencesTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.resolver = ReferenceResolver(self.api_client)
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, organization=self.org)
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
        target_channel = Channel.objects.create(telegram_id=2, username="targetchan", organization=self.org)
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
        target_channel = Channel.objects.create(telegram_id=3, username="urlchan", organization=self.org)
        entity = MagicMock()
        entity.url = "https://t.me/urlchan"
        tm = self._make_telegram_message(entities=[entity])
        self.resolver.resolve_message_references(self.message, tm)
        self.assertIn(target_channel, self.message.references.all())

    def test_entity_url_subpath_is_stripped(self) -> None:
        target_channel = Channel.objects.create(telegram_id=4, username="pathchan", organization=self.org)
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


# ---------------------------------------------------------------------------
# ReferenceResolver.get_missing_references
# ---------------------------------------------------------------------------


class GetMissingReferencesTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.resolver = ReferenceResolver(self.api_client)
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, organization=self.org)

    def test_message_with_empty_missing_references_is_skipped(self) -> None:
        Message.objects.create(telegram_id=1, channel=self.channel, missing_references="")
        self.resolver.get_missing_references()
        self.api_client.client.get_entity.assert_not_called()

    def test_missing_reference_found_in_db_added_without_api_call(self) -> None:
        target = Channel.objects.create(telegram_id=2, username="dbchan", organization=self.org)
        msg = Message.objects.create(telegram_id=2, channel=self.channel, missing_references="|dbchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        self.assertIn(target, msg.references.all())
        self.api_client.client.get_entity.assert_not_called()

    def test_missing_reference_cleared_after_successful_resolution(self) -> None:
        Channel.objects.create(telegram_id=3, username="resolvable", organization=self.org)
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

    def test_multiple_references_processed_in_one_message(self) -> None:
        ch_a = Channel.objects.create(telegram_id=10, username="chana", organization=self.org)
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


# ---------------------------------------------------------------------------
# MediaHandler — download_profile_picture
# ---------------------------------------------------------------------------


class MediaHandlerProfilePictureTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, organization=self.org)

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
        self.handler._download_media = MagicMock(return_value=None)

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_skips_already_downloaded_picture(self, mock_from_tg: MagicMock) -> None:
        from webapp.models import ProfilePicture

        tc = self._make_tg_channel(telegram_id=1)
        pic = self._make_tg_picture(pic_id=200)
        self.api_client.client.get_profile_photos.return_value = [pic]
        # Pre-create the ProfilePicture in DB (without a real file)
        ProfilePicture.objects.create(telegram_id=200, channel=self.channel, picture="", date=None)

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 0)
        mock_from_tg.assert_not_called()

    @patch("crawler.media_handler.ProfilePicture.from_telegram_object")
    def test_counts_multiple_new_pictures(self, mock_from_tg: MagicMock) -> None:
        tc = self._make_tg_channel(telegram_id=1)
        pics = [self._make_tg_picture(pic_id=i) for i in range(1, 4)]
        self.api_client.client.get_profile_photos.return_value = pics
        self.handler._download_media = MagicMock(return_value=None)

        result = self.handler.download_profile_picture(tc)

        self.assertEqual(result, 3)
        self.assertEqual(mock_from_tg.call_count, 3)


# ---------------------------------------------------------------------------
# MediaHandler — download_message_picture
# ---------------------------------------------------------------------------


class MediaHandlerMessagePictureTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_images=False by default
        self.handler_dl = MediaHandler(self.api_client, download_images=True)
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=10, organization=self.org)
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
        self.handler_dl._download_media = MagicMock(return_value=None)
        result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 1)
        mock_from_tg.assert_called_once()

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
        self.handler_dl._download_media = MagicMock(return_value=None)
        result = self.handler_dl.download_message_picture(tm)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# MediaHandler — download_message_video
# ---------------------------------------------------------------------------


class MediaHandlerMessageVideoTests(TestCase):
    def setUp(self) -> None:
        from crawler.media_handler import MediaHandler

        self.api_client = _make_api_client()
        self.handler = MediaHandler(self.api_client)  # download_video=False by default
        self.handler_dl = MediaHandler(self.api_client, download_video=True)
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=10, organization=self.org)
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

    def test_returns_when_download_disabled(self) -> None:
        tm = self._make_tg_message()
        # Should return None without doing anything
        result = self.handler.download_message_video(tm)
        self.assertIsNone(result)
        self.api_client.client.download_media.assert_not_called()

    def test_returns_when_no_document(self) -> None:
        tm = self._make_tg_message(has_document=False)
        tm.media = None
        self.handler_dl.download_message_video(tm)
        self.api_client.client.download_media.assert_not_called()

    def test_returns_when_not_video_mime_type(self) -> None:
        tm = self._make_tg_message(mime_type="image/jpeg")
        self.handler_dl.download_message_video(tm)
        self.api_client.client.download_media.assert_not_called()

    @patch("crawler.media_handler.MessageVideo.from_telegram_object")
    def test_downloads_video_with_correct_mime_type(self, mock_from_tg: MagicMock) -> None:
        tm = self._make_tg_message(mime_type="video/mp4")
        self.handler_dl._download_media = MagicMock(return_value=None)
        self.handler_dl.download_message_video(tm)
        mock_from_tg.assert_called_once()

    def test_handles_file_migrate_error_gracefully(self) -> None:
        from telethon.errors.rpcerrorlist import FileMigrateError

        tm = self._make_tg_message()
        err = FileMigrateError.__new__(FileMigrateError)
        self.handler_dl._download_media = MagicMock(side_effect=err)
        try:
            self.handler_dl.download_message_video(tm)
        except Exception:
            self.fail("download_message_video raised an unexpected exception")


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

    @patch("crawler.media_handler.os.remove")
    @patch("crawler.media_handler.glob.glob")
    def test_removes_all_leftover_photo_files(self, mock_glob: MagicMock, mock_remove: MagicMock) -> None:
        mock_glob.return_value = ["/base/photo_1.jpg", "/base/photo_2.jpg"]
        self.handler.clean_leftovers()
        self.assertEqual(mock_remove.call_count, 2)
        mock_remove.assert_any_call("/base/photo_1.jpg")
        mock_remove.assert_any_call("/base/photo_2.jpg")

    @patch("crawler.media_handler.os.remove", side_effect=OSError("permission denied"))
    @patch("crawler.media_handler.glob.glob")
    def test_oserror_on_remove_is_logged_not_raised(self, mock_glob: MagicMock, _mock_remove: MagicMock) -> None:
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
        self.org = Organization.objects.create(name="Org", is_interesting=True)

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


# ---------------------------------------------------------------------------
# ChannelCrawler — set_more_channel_details
# ---------------------------------------------------------------------------


class ChannelCrawlerSetMoreDetailsTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, organization=self.org)

    def _make_full_channel_response(self, participants: int = 500, about: str = "desc") -> MagicMock:
        resp = MagicMock()
        resp.full_chat.participants_count = participants
        resp.full_chat.about = about
        resp.full_chat.location = None
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


# ---------------------------------------------------------------------------
# ChannelCrawler — search_channel
# ---------------------------------------------------------------------------


class ChannelCrawlerSearchChannelTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = Organization.objects.create(name="Org", is_interesting=True)

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
        Channel.objects.create(telegram_id=200, organization=self.org)
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


class ChannelCrawlerPendingForwardsTests(TestCase):
    def setUp(self) -> None:
        self.api_client = _make_api_client()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.source_channel = Channel.objects.create(telegram_id=1, organization=self.org)
        self.msg = Message.objects.create(telegram_id=1, channel=self.source_channel)

    def _set_pending(self, channel_id: int) -> None:
        self.msg.pending_forward_telegram_id = channel_id
        self.msg.save(update_fields=["pending_forward_telegram_id"])

    def _make_tg_message(self, msg_id: int, fwd_channel_id: int | None = None) -> MagicMock:
        """Build a minimal Telethon message mock safe to pass to get_message()."""
        tm = MagicMock()
        tm.id = msg_id
        tm.peer_id.channel_id = self.source_channel.telegram_id
        # TELEGRAM_OBJECT_PROPERTIES must have safe values (not raw MagicMocks).
        tm.date = None
        tm.out = False
        tm.mentioned = False
        tm.post = False
        tm.from_scheduled = False
        tm.message = ""
        tm.grouped_id = None
        tm.views = None
        tm.forwards = None
        tm.pinned = False
        tm.entities = []
        tm.media = None
        if fwd_channel_id is not None:
            tm.fwd_from.from_id.channel_id = fwd_channel_id
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
        fwd_channel = Channel.objects.create(telegram_id=7777, organization=self.org)
        tm = self._make_tg_message(msg_id=100, fwd_channel_id=fwd_channel.telegram_id)

        self.crawler.get_message(self.source_channel, tm)

        msg = Message.objects.get(telegram_id=100, channel=self.source_channel)
        self.assertIsNone(msg.pending_forward_telegram_id)
        self.assertEqual(msg.forwarded_from, fwd_channel)

    def test_get_message_clears_stale_pending_when_channel_now_in_db(self) -> None:
        """If a previous run left pending_forward_telegram_id set and the channel is
        now in the DB, a fresh get_message() call clears the stale flag."""
        fwd_channel = Channel.objects.create(telegram_id=8888, organization=self.org)
        self._set_pending(8888)  # stale flag from a previous crashed run

        tm = self._make_tg_message(msg_id=self.msg.telegram_id, fwd_channel_id=fwd_channel.telegram_id)

        self.crawler.get_message(self.source_channel, tm)

        self.msg.refresh_from_db()
        self.assertIsNone(self.msg.pending_forward_telegram_id)
        self.assertEqual(self.msg.forwarded_from, fwd_channel)

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

        call_command("search_channels")

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

        call_command("search_channels")

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

        call_command("search_channels", amount=15)

        self.assertEqual(mock_crawler.search_channel.call_count, 15)


# ---------------------------------------------------------------------------
# crawl_channels management command
# ---------------------------------------------------------------------------

_GET_CMD = "crawler.management.commands.crawl_channels"


class GetChannelsCommandTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.ch1 = Channel.objects.create(telegram_id=1, organization=self.org, title="Ch1")
        self.ch2 = Channel.objects.create(telegram_id=2, organization=self.org, title="Ch2")

    def _patch_command(self) -> tuple:
        tc_patch = patch(f"{_GET_CMD}.TelegramClient")
        api_patch = patch(f"{_GET_CMD}.TelegramAPIClient")
        crawler_patch = patch(f"{_GET_CMD}.ChannelCrawler")
        media_patch = patch(f"{_GET_CMD}.MediaHandler")
        resolver_patch = patch(f"{_GET_CMD}.ReferenceResolver")
        return tc_patch, api_patch, crawler_patch, media_patch, resolver_patch

    def test_get_channel_called_for_each_interesting_channel(self) -> None:
        from django.core.management import call_command

        tc_p, api_p, crawler_p, media_p, resolver_p = self._patch_command()
        with tc_p as mock_tc, api_p, crawler_p as mock_crawler_cls, media_p as mock_media_cls, resolver_p:
            mock_crawler = MagicMock()
            mock_crawler_cls.return_value = mock_crawler
            mock_media = MagicMock()
            mock_media_cls.return_value = mock_media
            mock_tc.return_value.start.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_tc.return_value.start.return_value.__exit__ = MagicMock(return_value=False)

            call_command("crawl_channels", get_new_messages=True)

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

            call_command("crawl_channels")

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
            call_command("crawl_channels")

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

            call_command("crawl_channels")

            mock_media.clean_leftovers.assert_called_once()
