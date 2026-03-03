from datetime import timedelta
from unittest.mock import MagicMock, call, patch

from django.test import TestCase
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.reference_resolver import SKIPPABLE_REFERENCES, ReferenceResolver
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
        api_client = _make_api_client()
        media_handler = MagicMock()
        reference_resolver = MagicMock()
        self.crawler = ChannelCrawler(api_client, media_handler, reference_resolver)

    def _create_messages(self, telegram_ids: list[int]) -> None:
        for tid in telegram_ids:
            Message.objects.create(telegram_id=tid, channel=self.channel)

    def test_empty_channel_returns_empty(self) -> None:
        result = self.crawler._find_missing_message_ids(self.channel)
        self.assertEqual(result, [])

    def test_single_message_returns_empty(self) -> None:
        self._create_messages([5])
        result = self.crawler._find_missing_message_ids(self.channel)
        self.assertEqual(result, [])

    def test_consecutive_messages_no_holes(self) -> None:
        self._create_messages([1, 2, 3, 4, 5])
        result = self.crawler._find_missing_message_ids(self.channel)
        self.assertEqual(result, [])

    def test_single_gap_detected(self) -> None:
        self._create_messages([1, 2, 4, 5])
        result = self.crawler._find_missing_message_ids(self.channel)
        self.assertEqual(result, [3])

    def test_multiple_gaps_detected(self) -> None:
        self._create_messages([1, 2, 4, 7])
        result = self.crawler._find_missing_message_ids(self.channel)
        self.assertEqual(sorted(result), [3, 5, 6])

    def test_large_gap_fills_all_missing_ids(self) -> None:
        self._create_messages([1, 10])
        result = self.crawler._find_missing_message_ids(self.channel)
        self.assertEqual(result, list(range(2, 10)))

    def test_min_telegram_id_filters_earlier_messages(self) -> None:
        self._create_messages([1, 3, 5, 7])  # holes at 2, 4, 6
        result = self.crawler._find_missing_message_ids(self.channel, min_telegram_id=5)
        # Only [5, 7] are considered → hole at 6
        self.assertEqual(result, [6])

    def test_min_telegram_id_below_all_messages_includes_all(self) -> None:
        self._create_messages([2, 5])
        result = self.crawler._find_missing_message_ids(self.channel, min_telegram_id=1)
        self.assertEqual(result, [3, 4])

    def test_ordering_is_by_telegram_id(self) -> None:
        # Messages created in reverse order
        self._create_messages([5, 3, 1])
        result = self.crawler._find_missing_message_ids(self.channel)
        # Gaps between 1→3 (missing 2) and 3→5 (missing 4)
        self.assertEqual(sorted(result), [2, 4])


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
        msg = Message.objects.create(telegram_id=4, channel=self.channel, missing_references="|apichan")
        self.resolver.get_missing_references()
        self.api_client.client.get_entity.assert_called_once_with("apichan")

    def test_flood_error_prevents_clearing_missing_references(self) -> None:
        self.api_client.client.get_entity.side_effect = _flood_error(seconds=10)
        msg = Message.objects.create(telegram_id=5, channel=self.channel, missing_references="|floodchan")
        self.resolver.get_missing_references()
        msg.refresh_from_db()
        # FloodWaitError → missing_references NOT cleared
        self.assertNotEqual(msg.missing_references, "")

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
