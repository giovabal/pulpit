"""Commenter accounts (webapp/commenters.py): the bot / bulk flags, the analyst's override, the home
page's unique commenters, Manage → Commenters, the crawler recording Telegram's bot flag, and the
channels commenting as themselves added to the channels list (crawler/commenting_channels.py)."""

import datetime
import io
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from crawler import commenting_channels
from webapp import commenters
from webapp.cache import compute_home_summary
from webapp.models import Channel, CommenterReview, Message, MessageReply
from webapp.models.telegram_models import CHANNEL_PEER_MARK
from webapp.test_helpers import make_channel, make_label

from telethon import errors
from telethon.extensions import BinaryReader
from telethon.tl.types import Channel as TelegramChannel, ChannelForbidden, ChatPhotoEmpty, User

BULK = commenters.BULK_THREAD_COMMENTS
_DATE = datetime.datetime(2024, 5, 1, 12, 0, tzinfo=datetime.timezone.utc)


class _Corpus(TestCase):
    """Two in-target channels with posts; replies added per test."""

    def setUp(self) -> None:
        org = make_label("Org")
        self.alpha = make_channel(telegram_id=1, title="Alpha", label=org)
        self.beta = make_channel(telegram_id=2, title="Beta", label=org)
        self.posts = [
            Message.objects.create(channel=channel, telegram_id=tid, date=_DATE)
            for channel in (self.alpha, self.beta)
            for tid in (1, 2)
        ]
        self._next_id = 1

    def reply(self, post: Message, sender_id: int, n: int = 1, text: str = "hi", **kwargs) -> None:
        rows = []
        for _ in range(n):
            rows.append(
                MessageReply(
                    parent_message=post,
                    telegram_id=self._next_id,
                    date=_DATE,
                    text=text,
                    sender_id=sender_id,
                    sender_name=kwargs.get("name", f"User {sender_id}"),
                    sender_is_bot=kwargs.get("bot"),
                )
            )
            self._next_id += 1
        MessageReply.objects.bulk_create(rows)


class AutomaticFlagTests(_Corpus):
    def test_bulk_poster_needs_the_threshold_under_one_post(self) -> None:
        self.reply(self.posts[0], 10, n=BULK, text="")
        self.reply(self.posts[0], 11, n=BULK - 1)
        for post in self.posts:  # many replies, but never BULK under one post
            self.reply(post, 12, n=BULK - 1)
        self.assertEqual(commenters.automatic_flags(), {10: [commenters.REASON_BULK]})

    def test_telegram_bot_flag(self) -> None:
        self.reply(self.posts[0], 20, bot=True)
        self.reply(self.posts[0], 21, bot=False)
        self.reply(self.posts[0], 22)
        self.assertEqual(commenters.automatic_flags(), {20: [commenters.REASON_TELEGRAM_BOT]})

    def test_channels_posting_as_themselves_are_not_commenters(self) -> None:
        self.reply(self.posts[0], -1001, n=BULK)
        self.assertEqual(commenters.automatic_flags(), {})
        self.assertEqual(commenters.commenter_rows(), [])

    def test_flags_read_every_stored_reply_whatever_the_scope(self) -> None:
        self.reply(self.posts[0], 10, n=BULK)
        self.assertEqual(commenters.automatic_flags([10, 99]), {10: [commenters.REASON_BULK]})
        self.assertEqual(commenters.automatic_flags([99]), {})


class OverrideTests(_Corpus):
    def setUp(self) -> None:
        super().setUp()
        self.reply(self.posts[0], 10, n=BULK)  # flagged
        self.reply(self.posts[0], 11)  # not flagged

    def test_flagged_accounts_are_left_out(self) -> None:
        self.assertEqual(commenters.excluded_sender_ids(), {10})

    def test_keep_overrides_a_flag_and_exclude_adds_an_account(self) -> None:
        commenters.set_review(10, decision=commenters.DECISION_KEEP)
        commenters.set_review(11, decision=commenters.DECISION_EXCLUDE)
        self.assertEqual(commenters.excluded_sender_ids(), {11})
        rows = {r["sender_id"]: r for r in commenters.commenter_rows()}
        self.assertEqual((rows[10]["decision"], rows[10]["excluded"]), ("keep", False))
        self.assertEqual([r["key"] for r in rows[10]["reasons"]], ["bulk"])
        self.assertEqual((rows[11]["decision"], rows[11]["excluded"]), ("exclude", True))

    def test_back_to_automatic_without_a_note_deletes_the_review(self) -> None:
        commenters.set_review(11, decision=commenters.DECISION_EXCLUDE, note="admin")
        commenters.set_review(11, decision=commenters.DECISION_AUTO)
        self.assertEqual(CommenterReview.objects.get(sender_id=11).note, "admin")
        commenters.set_review(11, note="")
        self.assertFalse(CommenterReview.objects.filter(sender_id=11).exists())

    def test_a_review_saves_only_the_fields_it_is_given(self) -> None:
        commenters.set_review(11, note="admin")
        commenters.set_review(11, decision=commenters.DECISION_EXCLUDE)
        review = CommenterReview.objects.get(sender_id=11)
        self.assertEqual((review.excluded, review.note), (True, "admin"))

    def test_audience_replies_drops_the_left_out_accounts(self) -> None:
        self.reply(self.posts[1], -1001)
        self.assertEqual(set(commenters.audience_replies().values_list("sender_id", flat=True)), {11})


class CommenterRowTests(_Corpus):
    def test_row_counts(self) -> None:
        self.reply(self.posts[0], 10, n=3, text="")
        self.reply(self.posts[0], 10, bot=False)
        self.reply(self.posts[2], 10, n=2)
        row = commenters.commenter_rows()[0]
        self.assertEqual(
            (row["comments"], row["posts"], row["channels"], row["max_per_post"], row["no_text_share"]),
            (6, 2, 2, 4, 0.5),
        )
        self.assertIs(row["telegram_bot"], False)
        self.assertEqual(row["first"], _DATE.isoformat())

    def test_bot_flag_not_captured_is_none(self) -> None:
        self.reply(self.posts[0], 10)
        self.assertIsNone(commenters.commenter_rows()[0]["telegram_bot"])

    def test_most_active_first(self) -> None:
        self.reply(self.posts[0], 10)
        self.reply(self.posts[0], 11, n=3)
        self.assertEqual([r["sender_id"] for r in commenters.commenter_rows()], [11, 10])


class HomeSummaryTests(_Corpus):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _commenters_entry(self) -> dict:
        views_card = compute_home_summary()[0][3]
        return views_card["secondary"][1]

    def test_unique_commenters_leave_out_flagged_accounts(self) -> None:
        self.reply(self.posts[0], 10, n=BULK)
        self.reply(self.posts[0], 11)
        self.reply(self.posts[2], 12)
        entry = self._commenters_entry()
        self.assertEqual(entry["value"], "2")
        self.assertIn("1 account flagged", entry["title"])

    def test_no_note_when_nothing_is_left_out(self) -> None:
        self.reply(self.posts[0], 11)
        entry = self._commenters_entry()
        self.assertEqual(entry["value"], "1")
        self.assertNotIn("left out", entry["title"])


class CommenterApiTests(_Corpus):
    API = "/manage/api/commenters/"

    def setUp(self) -> None:
        super().setUp()
        self.reply(self.posts[0], 10, n=BULK, text="", name="Archive")
        self.reply(self.posts[0], 11, name="Raph")
        self.reply(self.posts[2], 12, name="Corvus")

    def patch(self, sender_id: int, data: dict):
        return self.client.patch(f"{self.API}{sender_id}/", json.dumps(data), content_type="application/json")

    def ids(self, query: str = "") -> list[int]:
        return [r["sender_id"] for r in self.client.get(f"{self.API}?{query}").json()["results"]]

    def test_page(self) -> None:
        self.assertEqual(self.client.get(reverse("backoffice:commenters")).status_code, 200)

    def test_list_and_filters(self) -> None:
        self.assertEqual(self.ids(), [10, 11, 12])
        self.assertEqual(self.ids("status=excluded"), [10])
        self.assertEqual(self.ids("status=flagged"), [10])
        self.assertEqual(self.ids("q=rap"), [11])
        self.assertEqual(self.ids("q=12"), [12])
        self.assertEqual(self.client.get(f"{self.API}?limit=1").json()["count"], 3)

    def test_decision_and_note(self) -> None:
        resp = self.patch(10, {"decision": "keep"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()["decision"], resp.json()["excluded"]), ("keep", False))
        self.patch(11, {"note": "  channel admin "})
        self.assertEqual(CommenterReview.objects.get(sender_id=11).note, "channel admin")
        self.assertEqual(self.ids("status=reviewed"), [10, 11])
        self.assertEqual(self.ids("status=excluded"), [])

    def test_a_decision_refreshes_the_home_page(self) -> None:
        cache.clear()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.patch(10, {"decision": "keep"})
        self.assertIn(">3</strong> unique commenters", self.client.get("/").content.decode())

    def test_invalid_input(self) -> None:
        self.assertEqual(self.patch(10, {"decision": "maybe"}).status_code, 400)
        self.assertEqual(self.patch(10, {"note": 5}).status_code, 400)
        self.assertEqual(self.patch(999, {"decision": "keep"}).status_code, 404)

    def test_accounts_cannot_be_created_or_deleted(self) -> None:
        self.assertEqual(self.client.post(self.API, {}).status_code, 405)
        self.assertEqual(self.client.delete(f"{self.API}10/").status_code, 405)


class CrawlerBotFlagTests(TestCase):
    """fetch_channel_replies records Telegram's User.bot for each reply's sender."""

    def test_sender_is_bot_is_recorded(self) -> None:
        from crawler.channel_crawler import ChannelCrawler

        channel = make_channel(telegram_id=1, title="Alpha", label=make_label("Org"), linked_chat_id=5)
        Message.objects.create(channel=channel, telegram_id=7, date=_DATE, replies=3)

        def tg_reply(reply_id: int, sender) -> MagicMock:
            reply = MagicMock(id=reply_id, date=_DATE, message="hi", sender=sender, views=None, post_author=None)
            reply.sender_id = getattr(sender, "id", None)
            return reply

        bot = User(id=100, first_name="Helper", bot=True)
        person = User(id=101, first_name="Raph", bot=False)
        as_channel = MagicMock(spec=["id", "title"], id=-1005, title="A channel")
        api_client = MagicMock()
        api_client.client.iter_messages.return_value = [tg_reply(1, bot), tg_reply(2, person), tg_reply(3, as_channel)]

        ChannelCrawler(api_client, MagicMock(), MagicMock()).fetch_channel_replies(channel)

        flags = dict(MessageReply.objects.values_list("sender_id", "sender_is_bot"))
        self.assertEqual(flags, {100: True, 101: False, -1005: None})
        # A channel commenting as itself is stored under its title.
        self.assertEqual(MessageReply.objects.get(sender_id=-1005).sender_name, "A channel")


def _marked(telegram_id: int) -> int:
    """A channel's id as a reply's sender_id."""
    return -(CHANNEL_PEER_MARK + telegram_id)


def _parsed(tl_object):
    """A Telethon object as Telegram would hand it over: absent flags read back as False, not None."""
    return BinaryReader(bytes(tl_object)).tgread_object()


def _live(telegram_id: int, title: str = "Live", username: str = "live") -> TelegramChannel:
    return _parsed(
        TelegramChannel(
            id=telegram_id,
            title=title,
            photo=ChatPhotoEmpty(),
            date=_DATE,
            access_hash=telegram_id * 10,
            username=username,
            broadcast=True,
        )
    )


def _forbidden(telegram_id: int, title: str = "Closed") -> ChannelForbidden:
    return _parsed(ChannelForbidden(id=telegram_id, access_hash=telegram_id * 10, title=title, broadcast=True))


class UnknownCommentingChannelTests(_Corpus):
    """Which reply senders are channels with no row."""

    def test_own_posts_discussion_group_people_and_stored_channels_are_left_out(self) -> None:
        Channel.objects.filter(pk=self.beta.pk).update(linked_chat_id=50)
        self.reply(self.posts[0], _marked(1), name="Alpha")  # Alpha under its own post
        self.reply(self.posts[2], _marked(50), name="Beta chat")  # Beta's discussion group
        self.reply(self.posts[0], _marked(2), name="Beta")  # a stored channel
        self.reply(self.posts[0], 77, name="A person")
        self.reply(self.posts[0], _marked(900), n=2, name="Gone")
        self.reply(self.posts[2], _marked(900), name="Gone, renamed")
        self.reply(self.posts[1], _marked(901), name="Other")

        found = commenting_channels.unknown_commenting_channels()

        self.assertEqual([(c.telegram_id, c.name, c.comments) for c in found], [(900, "Gone", 3), (901, "Other", 1)])

    def test_a_user_account_holding_the_id_is_skipped_not_overwritten(self) -> None:
        person = make_channel(telegram_id=900, is_user_account=True, username="someone")
        self.reply(self.posts[0], _marked(900), name="Gone")

        found = commenting_channels.unknown_commenting_channels()
        self.assertEqual([c.telegram_id for c in found], [900])
        crawler = MagicMock()
        counts = commenting_channels.recover_commenting_channels(crawler, found)

        self.assertEqual(counts, {commenting_channels.STATUS_USER_CLASH: 1})
        crawler.resolve_channel_or_classify.assert_not_called()
        self.assertEqual(list(Channel.objects.filter(telegram_id=900)), [person])
        self.assertIsNone(commenting_channels.store_reply_sender(_live(900), self.alpha))


class StoreReplySenderTests(TestCase):
    """The fetch-time hook: a channel commenting as itself gets a row as its replies arrive."""

    def setUp(self) -> None:
        self.host = make_channel(telegram_id=1, title="Host", linked_chat_id=5)

    def test_live_and_forbidden_senders_get_rows(self) -> None:
        live = commenting_channels.store_reply_sender(_live(900, "Live one", "liveone"), self.host)
        closed = commenting_channels.store_reply_sender(_forbidden(901, "Closed one"), self.host)

        self.assertEqual(
            (live.title, live.username, live.access_hash, live.is_private), ("Live one", "liveone", 9000, False)
        )
        closed.refresh_from_db()
        self.assertEqual((closed.title, closed.is_private, closed.is_lost), ("Closed one", True, False))

    def test_stored_own_and_non_channel_senders_are_ignored(self) -> None:
        make_channel(telegram_id=900, title="Known")
        self.assertIsNone(commenting_channels.store_reply_sender(_live(900), self.host))
        self.assertIsNone(commenting_channels.store_reply_sender(_live(1), self.host))  # the post's channel
        self.assertIsNone(commenting_channels.store_reply_sender(_forbidden(5), self.host))  # its discussion group
        self.assertIsNone(commenting_channels.store_reply_sender(User(id=902, first_name="P"), self.host))
        self.assertEqual(Channel.objects.count(), 2)

    def test_fetch_channel_replies_stores_each_commenting_channel_once(self) -> None:
        from crawler.channel_crawler import ChannelCrawler

        channel = self.host
        Message.objects.create(channel=channel, telegram_id=7, date=_DATE, replies=4)
        senders = [_live(900), _live(900), _forbidden(901), _forbidden(5)]
        replies = []
        for reply_id, sender in enumerate(senders, start=1):
            reply = MagicMock(id=reply_id, date=_DATE, message="hi", sender=sender, views=None, post_author=None)
            reply.sender_id = _marked(sender.id)
            replies.append(reply)
        api_client = MagicMock()
        api_client.client.iter_messages.return_value = replies

        ChannelCrawler(api_client, MagicMock(), MagicMock()).fetch_channel_replies(channel)

        self.assertEqual(
            sorted(Channel.objects.exclude(pk=channel.pk).values_list("telegram_id", "is_private")),
            [(900, False), (901, True)],
        )
        self.assertEqual(MessageReply.objects.count(), 4)


class RecoverCommentingChannelTests(_Corpus):
    """The backfill: a placeholder per unknown commenting channel, then Telegram's verdict."""

    def setUp(self) -> None:
        super().setUp()
        for tid in (900, 901, 902, 903):
            self.reply(self.posts[0], _marked(tid), name=f"Commenter {tid}")
        self.session = Path(tempfile.mkdtemp()) / "test.session"
        with closing(sqlite3.connect(self.session)) as db:
            db.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY, hash INTEGER, username TEXT)")
            db.execute("INSERT INTO entities VALUES (?, ?, ?)", (_marked(901), 9010, "oldhandle"))
            db.commit()

    def _crawler(self, verdicts: dict) -> MagicMock:
        def classify(seed):
            verdict = verdicts[seed]
            if isinstance(verdict, BaseException):
                raise verdict
            if verdict == "ok":  # get_basic_channel refreshes the row from the live entity
                entity = _live(seed, "Alive now", "alivenow")
                return Channel.from_telegram_object(entity, force_update=True), entity, "ok"
            return None, User(id=seed, first_name="P") if verdict == "user_account" else None, verdict

        crawler = MagicMock()
        crawler.resolve_channel_or_classify.side_effect = classify
        return crawler

    def test_each_verdict_lands_on_its_row(self) -> None:
        crawler = self._crawler({900: "ok", 901: "private", 902: "lost", 903: "user_account"})
        reported = []
        with override_settings(TELEGRAM_SESSION_NAME=str(self.session)):
            counts = commenting_channels.recover_commenting_channels(
                crawler, report=lambda c, outcome: reported.append((c.telegram_id, outcome))
            )

        self.assertEqual(counts, {"live": 1, "private": 1, "lost": 2})
        self.assertEqual(reported, [(900, "live"), (901, "private"), (902, "lost"), (903, "lost")])
        rows = {c.telegram_id: c for c in Channel.objects.filter(telegram_id__gte=900)}
        self.assertEqual((rows[900].title, rows[900].username, rows[900].is_lost), ("Alive now", "alivenow", False))
        crawler.set_more_channel_details.assert_called_once()
        # Placeholders keep the name they commented under and the session's cached hash and handle.
        self.assertEqual(
            (rows[901].title, rows[901].username, rows[901].access_hash, rows[901].is_private),
            ("Commenter 901", "oldhandle", 9010, True),
        )
        self.assertTrue(rows[902].is_lost and rows[903].is_lost and not rows[903].is_user_account)
        self.assertEqual(commenting_channels.unknown_commenting_channels(), [])

    def test_no_verdict_leaves_no_placeholder(self) -> None:
        flood = errors.FloodWaitError(request=None, capture=30)
        crawler = self._crawler({900: "lost", 901: flood})
        with override_settings(TELEGRAM_SESSION_NAME=str(self.session)), self.assertRaises(errors.FloodWaitError):
            commenting_channels.recover_commenting_channels(crawler)

        self.assertEqual(
            list(Channel.objects.filter(telegram_id__gte=900).values_list("telegram_id", flat=True)), [900]
        )
        self.assertEqual([c.telegram_id for c in commenting_channels.unknown_commenting_channels()], [901, 902, 903])

    def test_dry_run_writes_nothing(self) -> None:
        from django.core.management import call_command

        before = Channel.objects.count()
        with override_settings(TELEGRAM_SESSION_NAME=str(self.session)):
            call_command("store_commenting_channels", "--dry-run", stdout=(out := io.StringIO()))

        self.assertEqual(Channel.objects.count(), before)
        self.assertIn("@oldhandle", out.getvalue())
        self.assertIn("Commenter 900", out.getvalue())
