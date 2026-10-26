"""Custom emoji capture and resolution (crawler/custom_emoji.py, channel_crawler._save_reactions)."""

import datetime
import os
import shutil
import tempfile
import types
from typing import Any
from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from crawler import custom_emoji
from crawler.channel_crawler import ChannelCrawler, _save_reactions
from crawler.custom_emoji import custom_emoji_spans, resolve_custom_emoji, save_message_custom_emoji
from crawler.media_handler import MediaHandler
from webapp.management.commands.purge_orphan_media import collect_referenced_paths
from webapp.models import (
    CustomEmoji,
    CustomEmojiPack,
    Message,
    MessageCustomEmoji,
    MessageCustomReaction,
    MessageReaction,
)
from webapp.test_helpers import make_channel, make_label

from telethon import errors
from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest, GetStickerSetRequest
from telethon.tl.types import (
    DocumentAttributeCustomEmoji,
    InputStickerSetID,
    MessageEntityBold,
    MessageEntityCustomEmoji,
    ReactionCustomEmoji,
    ReactionEmoji,
    ReactionPaid,
)


def _dated(year: int, month: int, day: int) -> datetime.datetime:
    return datetime.datetime(year, month, day, 12, 0, tzinfo=datetime.timezone.utc)


def _document(doc_id: int, alt: str = "🔥", pack_id: int = 900, mime: str = "application/x-tgsticker") -> Any:
    attribute = DocumentAttributeCustomEmoji(
        alt=alt, stickerset=InputStickerSetID(id=pack_id, access_hash=4242), free=True, text_color=False
    )
    return types.SimpleNamespace(id=doc_id, mime_type=mime, attributes=[attribute])


def _reactions(*pairs: tuple) -> Any:
    return types.SimpleNamespace(
        results=[types.SimpleNamespace(reaction=reaction, count=count) for reaction, count in pairs]
    )


class _FakeClient:
    """``api_client.client``: answers the two custom-emoji requests, recording each one."""

    def __init__(self, documents: dict[int, Any], sticker_sets: dict[int, Any] | None = None) -> None:
        self.documents = documents
        self.sticker_sets = sticker_sets or {}
        self.requests: list[Any] = []
        self.fail_documents: Exception | None = None

    def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        if isinstance(request, GetCustomEmojiDocumentsRequest):
            if self.fail_documents is not None:
                raise self.fail_documents
            return [self.documents[i] for i in request.document_id if i in self.documents]
        if isinstance(request, GetStickerSetRequest):
            sticker_set = self.sticker_sets.get(request.stickerset.id)
            if sticker_set is None:
                raise errors.StickersetInvalidError(request=request)
            return types.SimpleNamespace(set=sticker_set)
        raise AssertionError(f"unexpected request {request!r}")


def _api_client(client: _FakeClient) -> MagicMock:
    api_client = MagicMock()
    api_client.wait.return_value = None
    api_client.client = client
    return api_client


class CustomEmojiSpansTests(TestCase):
    def test_only_custom_emoji_entities_are_spans(self) -> None:
        message = types.SimpleNamespace(
            entities=[
                MessageEntityBold(offset=0, length=4),
                MessageEntityCustomEmoji(offset=5, length=2, document_id=77),
            ]
        )
        self.assertEqual(custom_emoji_spans(message), [(77, 5, 2)])

    def test_entities_that_are_not_a_list_are_ignored(self) -> None:
        self.assertEqual(custom_emoji_spans(MagicMock()), [])
        self.assertEqual(custom_emoji_spans(types.SimpleNamespace()), [])


class SaveMessageCustomEmojiTests(TestCase):
    def setUp(self) -> None:
        self.channel = make_channel(telegram_id=1, label=make_label("Org"))
        self.message = Message.objects.create(channel=self.channel, telegram_id=10, message="a 🔥 b 🔥")

    def _tg(self, *spans: tuple[int, int, int]) -> Any:
        return types.SimpleNamespace(
            entities=[MessageEntityCustomEmoji(offset=o, length=n, document_id=d) for d, o, n in spans]
        )

    def test_spans_point_at_placeholder_emoji(self) -> None:
        save_message_custom_emoji(self.message.pk, self._tg((77, 2, 2), (77, 7, 2)))

        emoji = CustomEmoji.objects.get()
        self.assertEqual(emoji.telegram_id, 77)
        self.assertIsNone(emoji.fetched_at)
        self.assertEqual(
            list(self.message.custom_emoji_spans.values_list("emoji_id", "offset", "length")),
            [(emoji.pk, 2, 2), (emoji.pk, 7, 2)],
        )

    def test_a_second_save_replaces_the_spans(self) -> None:
        save_message_custom_emoji(self.message.pk, self._tg((77, 2, 2), (78, 7, 2)))
        save_message_custom_emoji(self.message.pk, self._tg((79, 2, 2)))

        self.assertEqual(
            list(self.message.custom_emoji_spans.values_list("emoji__telegram_id", flat=True)),
            [79],
        )

    def test_a_message_without_custom_emoji_only_reads(self) -> None:
        with self.assertNumQueries(1):
            save_message_custom_emoji(self.message.pk, self._tg())


class SaveReactionsCustomEmojiTests(TestCase):
    def setUp(self) -> None:
        self.channel = make_channel(telegram_id=1, label=make_label("Org"))
        self.message = Message.objects.create(channel=self.channel, telegram_id=10)

    def test_custom_emoji_reactions_are_kept_per_emoji_inside_the_custom_bucket(self) -> None:
        tg = types.SimpleNamespace(
            reactions=_reactions(
                (ReactionEmoji(emoticon="❤"), 5),
                (ReactionCustomEmoji(document_id=77), 3),
                (ReactionCustomEmoji(document_id=78), 2),
                (ReactionPaid(), 4),
            )
        )
        _save_reactions(self.message.pk, tg)

        self.assertEqual(
            dict(MessageReaction.objects.filter(message=self.message).values_list("emoji", "count")),
            {"❤": 5, "custom": 9},
        )
        self.assertEqual(
            dict(self.message.custom_reactions.values_list("emoji__telegram_id", "count")),
            {77: 3, 78: 2},
        )
        self.message.refresh_from_db()
        self.assertEqual(self.message.total_reactions, 14)

    def test_reactions_gone_from_telegram_clear_the_breakdown(self) -> None:
        _save_reactions(self.message.pk, types.SimpleNamespace(reactions=_reactions((ReactionCustomEmoji(77), 3))))
        _save_reactions(self.message.pk, types.SimpleNamespace(reactions=None))

        self.assertFalse(MessageCustomReaction.objects.exists())
        self.assertFalse(MessageReaction.objects.exists())


class GetMessageCustomEmojiTests(TestCase):
    def test_get_message_records_the_spans(self) -> None:
        channel = make_channel(telegram_id=1, label=make_label("Org"))
        crawler = ChannelCrawler(MagicMock(), MagicMock(), MagicMock())
        crawler.reference_resolver.resolve_message_references.return_value = []
        tg = types.SimpleNamespace(
            id=10,
            peer_id=types.SimpleNamespace(channel_id=1),
            date=_dated(2024, 3, 2),
            message="go 🔥",
            entities=[MessageEntityCustomEmoji(offset=3, length=2, document_id=77)],
            fwd_from=None,
            media=None,
            replies=None,
            reply_to=None,
            factcheck=None,
            reactions=None,
            pinned=False,
            views=1,
            forwards=0,
            edit_date=None,
        )
        self.assertEqual(crawler.get_message(channel, tg), (True, 0))
        span = MessageCustomEmoji.objects.get()
        self.assertEqual((span.message.telegram_id, span.emoji.telegram_id, span.offset), (10, 77, 3))


class RefreshBackfillsCustomEmojiTests(TestCase):
    def setUp(self) -> None:
        self.channel = make_channel(telegram_id=1, label=make_label("Org"))
        self.api_client = MagicMock()
        self.api_client.wait_time = 0
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())

    def _refresh(self, stored_text: str, telegram_text: str) -> None:
        Message.objects.create(channel=self.channel, telegram_id=6, date=_dated(2024, 2, 1), message=stored_text)
        self.api_client.client.iter_messages.return_value = iter(
            [
                types.SimpleNamespace(
                    id=6,
                    date=_dated(2024, 2, 1),
                    message=telegram_text,
                    entities=[MessageEntityCustomEmoji(offset=0, length=2, document_id=77)],
                    media=None,
                    pinned=False,
                    edit_date=None,
                    views=5,
                    forwards=0,
                    replies=None,
                    factcheck=None,
                    reactions=None,
                )
            ]
        )
        self.crawler.refresh_message_stats(self.channel, MagicMock())

    def test_spans_are_backfilled_while_the_text_is_unchanged(self) -> None:
        self._refresh("🔥 news", "🔥 news")
        self.assertEqual(MessageCustomEmoji.objects.get().emoji.telegram_id, 77)

    def test_a_replaced_text_leaves_the_spans_alone(self) -> None:
        self._refresh("🔥 news", "🔥 This channel can't be displayed")
        self.assertFalse(MessageCustomEmoji.objects.exists())


class ResolveCustomEmojiTests(TestCase):
    def setUp(self) -> None:
        custom_emoji._ATTEMPTED_THIS_RUN.clear()
        custom_emoji._PACKS_ATTEMPTED_THIS_RUN.clear()
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        sticker_set = types.SimpleNamespace(title="Fire pack", short_name="firepack", count=40)
        self.client = _FakeClient({77: _document(77), 78: _document(78, alt="😀")}, {900: sticker_set})
        self.api_client = _api_client(self.client)
        for doc_id in (77, 78, 79):
            CustomEmoji.objects.create(telegram_id=doc_id)

    def _handler(self, download: bool) -> MediaHandler:
        handler = MediaHandler(self.api_client, download_stickers=download)

        def fake_download(document: Any, thumb: Any = None) -> str:
            path = os.path.join(self.media_root, f"download_{document.id}.tgs")
            with open(path, "wb") as f:
                f.write(b"\x1f\x8b fake tgs")
            return path

        handler._download_media = MagicMock(side_effect=fake_download)
        return handler

    def test_placeholders_get_their_metadata_and_pack(self) -> None:
        resolved, downloaded = resolve_custom_emoji(self.api_client, self._handler(download=False))

        self.assertEqual((resolved, downloaded), (2, 0))
        fire = CustomEmoji.objects.get(telegram_id=77)
        self.assertEqual(
            (fire.alt, fire.mime_type, fire.is_free, fire.kind), ("🔥", "application/x-tgsticker", True, "lottie")
        )
        self.assertIsNotNone(fire.fetched_at)
        self.assertFalse(fire.file)
        pack = fire.pack
        self.assertEqual(
            (pack.telegram_id, pack.access_hash, pack.title, pack.short_name), (900, 4242, "Fire pack", "firepack")
        )
        self.assertEqual((pack.emoji_count, pack.telegram_url), (40, "https://t.me/addemoji/firepack"))
        self.assertEqual(CustomEmoji.objects.get(telegram_id=78).pack, pack)

    def test_an_id_telegram_does_not_return_is_marked_unavailable(self) -> None:
        resolve_custom_emoji(self.api_client)
        gone = CustomEmoji.objects.get(telegram_id=79)
        self.assertTrue(gone.is_unavailable)
        self.assertIsNotNone(gone.fetched_at)

    def test_files_are_downloaded_once_per_document_under_stickers_emoji(self) -> None:
        resolved, downloaded = resolve_custom_emoji(self.api_client, self._handler(download=True))

        self.assertEqual((resolved, downloaded), (2, 2))
        fire = CustomEmoji.objects.get(telegram_id=77)
        self.assertEqual(fire.file.name, "stickers/emoji/77.tgs")
        self.assertTrue(os.path.exists(os.path.join(self.media_root, "stickers", "emoji", "77.tgs")))
        self.assertFalse(os.path.exists(os.path.join(self.media_root, "download_77.tgs")))
        self.assertIn("stickers/emoji/77.tgs", collect_referenced_paths())

    def test_resolved_emoji_without_file_are_fetched_again_once_downloads_are_on(self) -> None:
        resolve_custom_emoji(self.api_client, self._handler(download=False))
        custom_emoji._ATTEMPTED_THIS_RUN.clear()  # a later run

        _, downloaded = resolve_custom_emoji(self.api_client, self._handler(download=True))

        self.assertEqual(downloaded, 2)

    def test_the_same_run_does_not_ask_twice(self) -> None:
        resolve_custom_emoji(self.api_client)
        CustomEmoji.objects.create(telegram_id=80)
        self.client.requests.clear()

        resolve_custom_emoji(self.api_client)

        documents = [r for r in self.client.requests if isinstance(r, GetCustomEmojiDocumentsRequest)]
        self.assertEqual([r.document_id for r in documents], [[80]])

    def test_check_files_refetches_a_file_missing_from_disk(self) -> None:
        resolve_custom_emoji(self.api_client, self._handler(download=True))
        os.remove(os.path.join(self.media_root, "stickers", "emoji", "77.tgs"))
        custom_emoji._ATTEMPTED_THIS_RUN.clear()

        self.assertEqual(resolve_custom_emoji(self.api_client, self._handler(download=True))[1], 0)
        self.assertEqual(resolve_custom_emoji(self.api_client, self._handler(download=True), check_files=True)[1], 1)

    @override_settings(IGNORE_FLOODWAIT=True)
    def test_a_flood_wait_leaves_the_rest_pending_and_skips_the_packs(self) -> None:
        self.client.fail_documents = errors.FloodWaitError(request=None, capture=5)

        self.assertEqual(resolve_custom_emoji(self.api_client), (0, 0))

        self.assertEqual(CustomEmoji.objects.filter(fetched_at__isnull=True).count(), 3)
        self.assertFalse(any(isinstance(r, GetStickerSetRequest) for r in self.client.requests))

    def test_a_pack_telegram_no_longer_has_is_marked_unavailable(self) -> None:
        self.client.sticker_sets.clear()
        resolve_custom_emoji(self.api_client)
        pack = CustomEmojiPack.objects.get()
        self.assertTrue(pack.is_unavailable)
        self.assertEqual(pack.display_title, "Pack 900")


class GroupEmojiPackTests(TestCase):
    """A boosted supergroup's own emoji pack (ChannelFull.emojiset) is recorded with the channel details."""

    def setUp(self) -> None:
        self.api_client = MagicMock()
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())
        self.channel = make_channel(telegram_id=1, label=make_label("Org"))

    def _details(self, emojiset: Any) -> None:
        full = types.SimpleNamespace(
            participants_count=10, about="", location=None, linked_chat_id=None, emojiset=emojiset
        )
        self.api_client.client.return_value = types.SimpleNamespace(full_chat=full, chats=[])
        telegram_channel = MagicMock(restriction_reason=None, usernames=None)
        self.crawler.set_more_channel_details(self.channel, telegram_channel)
        self.channel.refresh_from_db()

    def test_the_group_pack_is_recorded_and_titled(self) -> None:
        self._details(types.SimpleNamespace(id=900, access_hash=7, title="Org pack", short_name="orgpack", count=30))

        pack = self.channel.emoji_pack
        self.assertEqual((pack.telegram_id, pack.access_hash, pack.title, pack.emoji_count), (900, 7, "Org pack", 30))
        self.assertIsNotNone(pack.fetched_at)
        self.assertEqual(list(pack.group_channels.all()), [self.channel])

    def test_an_existing_pack_is_reused_and_refreshed(self) -> None:
        existing = CustomEmojiPack.objects.create(telegram_id=900, title="Old title")
        self._details(types.SimpleNamespace(id=900, access_hash=7, title="New title", short_name="orgpack", count=30))

        self.assertEqual(self.channel.emoji_pack, existing)
        existing.refresh_from_db()
        self.assertEqual(existing.title, "New title")

    def test_a_dropped_pack_is_cleared(self) -> None:
        self._details(types.SimpleNamespace(id=900, access_hash=7, title="Org pack", short_name="orgpack", count=30))
        self._details(None)
        self.assertIsNone(self.channel.emoji_pack)
        self.assertTrue(CustomEmojiPack.objects.filter(telegram_id=900).exists())

    def test_no_stickerset_object_records_nothing(self) -> None:
        self._details(MagicMock())  # what an under-specified (mocked) response carries
        self.assertIsNone(self.channel.emoji_pack)
        self.assertFalse(CustomEmojiPack.objects.exists())
