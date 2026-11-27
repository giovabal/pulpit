import datetime
import io
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from crawler.mention_backfill import apply_plan, look_up_handles, plan_backfill
from crawler.reference_resolver import (
    ReferenceResolver,
    extract_text_mentions,
    message_references,
    reference_from_url,
)
from webapp.models import Channel, Message
from webapp.test_helpers import make_channel, make_label

from telethon import errors
from telethon.tl.types import ChannelForbidden, User, Username

_CMD = "crawler.management.commands.backfill_mentions"
_DATE = datetime.datetime(2026, 11, 15, tzinfo=datetime.timezone.utc)


def _flood_error(seconds: int = 3600) -> errors.FloodWaitError:
    error = errors.FloodWaitError.__new__(errors.FloodWaitError)
    error.seconds = seconds
    return error


def _telegram_channel(telegram_id: int, username: str) -> MagicMock:
    channel = MagicMock(spec=["id", "username", "title", "broadcast"])
    channel.id = telegram_id
    channel.username = username
    channel.title = username
    channel.broadcast = True
    return channel


def _resolver(entities: dict | None = None) -> ReferenceResolver:
    """A resolver whose Telegram knows only *entities* (handle → entity, or an exception to raise)."""

    def get_entity(handle: str):
        answer = (entities or {}).get(handle, ValueError("nobody"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    api_client = MagicMock()
    api_client.client.get_entity.side_effect = get_entity
    return ReferenceResolver(api_client)


class MentionParsingTests(SimpleTestCase):
    def test_handles_are_read(self) -> None:
        text = "Gruppe Köln\n@group_koeln (@group_contact) oder @Forum13. Kanal:@chan1/@chan2 @some_chan-Kanal @abcd"
        self.assertEqual(
            extract_text_mentions(text),
            ["group_koeln", "group_contact", "forum13", "chan1", "chan2", "some_chan", "abcd"],
        )

    def test_what_is_not_a_telegram_handle(self) -> None:
        for text in (
            "",
            None,
            "mail me@club.de or info@club.org",
            "https://youtube.com/@someone youtube.com/@someone tiktok.com/@someone/video/1 www.x.com/@someone",
            "@some.brand",
            "@user@mastodon.social",
            "@foo__bar @trailing_ @1digit @abc",
            "@nämlich",
            "@" + "a" * 33,
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_text_mentions(text), [])

    def test_a_handle_also_linked_counts_as_the_link(self) -> None:
        self.assertEqual(message_references("t.me/Chan1 @chan1 @Chan2 @t.me/chan3", None), {"chan1", "@chan2", "chan3"})

    def test_at_sign_in_a_link_path_is_dropped(self) -> None:
        self.assertEqual(reference_from_url("https://t.me/@Chan"), "chan")
        self.assertIsNone(reference_from_url("https://t.me/@"))


class ExtraUsernamesTests(SimpleTestCase):
    def test_active_handles_besides_the_username(self) -> None:
        channel = Channel(username="Main")
        handles = [Username(username="MAIN", active=True), Username(username="other", active=True)]
        channel.set_extra_usernames(MagicMock(usernames=[*handles, Username(username="old", active=False)]))
        self.assertEqual(channel.extra_usernames, ["other"])
        self.assertEqual(Channel.handles_of(channel.username, channel.extra_usernames), ["main", "other"])

    def test_none_without_other_handles(self) -> None:
        channel = Channel(username="Main")
        for usernames in (None, [], [Username(username="main", active=True)]):
            channel.set_extra_usernames(MagicMock(usernames=usernames))
            self.assertIsNone(channel.extra_usernames)
        self.assertEqual(Channel.handles_of("", None), [])


class MentionResolutionTests(TestCase):
    def setUp(self) -> None:
        self.channel = make_channel(
            telegram_id=1, username="OwnChan", label=make_label(name="Org", is_in_target=True), title="Own"
        )
        self.message = Message.objects.create(telegram_id=1, channel=self.channel, date=_DATE)

    def _resolve(self, resolver: ReferenceResolver, text: str) -> list[str]:
        self.message.message = text
        return resolver.resolve_message_references(self.message, MagicMock(entities=[]))

    def test_stored_channel_is_mentioned_without_a_lookup(self) -> None:
        target = make_channel(telegram_id=2, username="TargetChan")
        resolver = _resolver()
        self.assertEqual(self._resolve(resolver, "siehe @targetchan"), [])
        self.assertEqual(list(self.message.references.all()), [target])
        resolver.api_client.client.get_entity.assert_not_called()

    def test_unknown_channel_is_fetched_by_its_bare_handle(self) -> None:
        resolver = _resolver({"newchan": _telegram_channel(500, "NewChan")})
        self._resolve(resolver, "@NewChan")
        resolver.api_client.client.get_entity.assert_called_once_with("newchan")
        self.assertEqual([c.telegram_id for c in self.message.references.all()], [500])

    def test_a_channel_holding_several_handles_answers_to_each(self) -> None:
        target = make_channel(telegram_id=2, username="", extra_usernames=["FirstName", "second_name"])
        make_channel(telegram_id=3, username="", extra_usernames=["firstnamelonger"])
        resolver = _resolver()
        self._resolve(resolver, "@firstname @SECOND_NAME")
        self.assertEqual(list(self.message.references.all()), [target])
        resolver.api_client.client.get_entity.assert_not_called()

    def test_a_looked_up_channel_keeps_its_several_handles(self) -> None:
        entity = _telegram_channel(500, None)  # several handles: Telegram sends no username
        entity.title = "New"
        entity.usernames = [Username(username="NewChan", active=True), Username(username="gone", active=False)]
        self._resolve(_resolver({"newchan": entity}), "@NewChan")
        stored = Channel.objects.get(telegram_id=500)
        self.assertEqual((stored.username, stored.extra_usernames), ("", ["NewChan"]))
        next_run = _resolver()
        self.assertEqual(next_run._resolve_one("@newchan"), (stored, False))
        next_run.api_client.client.get_entity.assert_not_called()

    def test_a_forbidden_channel_keeps_the_handle_it_was_found_by(self) -> None:
        entity = ChannelForbidden(id=600, access_hash=1, title="Closed", broadcast=True, megagroup=False)  # no handle
        self._resolve(_resolver({"closedchan": entity}), "@ClosedChan")
        stored = Channel.objects.get(telegram_id=600)
        self.assertEqual(stored.username, "closedchan")
        self.assertEqual(list(self.message.references.all()), [stored])
        next_run = _resolver()
        self.assertEqual(next_run._resolve_one("@closedchan"), (stored, False))
        next_run.api_client.client.get_entity.assert_not_called()

    def test_a_handle_already_held_is_not_overwritten(self) -> None:
        make_channel(telegram_id=700, username="CurrentName", title="Renamed")
        self._resolve(_resolver({"oldname": _telegram_channel(700, "CurrentName")}), "@oldname")
        self.assertEqual(Channel.objects.get(telegram_id=700).username, "CurrentName")

    def test_own_and_forwarded_handles_are_signatures(self) -> None:
        source = make_channel(telegram_id=3, username="sourcechan")
        self.message.forwarded_from = source
        self._resolve(_resolver(), "via @sourcechan — folgt @ownchan")
        self.assertFalse(self.message.references.exists())

    def test_own_t_me_link_is_still_recorded(self) -> None:
        self._resolve(_resolver(), "t.me/ownchan")
        self.assertEqual(list(self.message.references.all()), [self.channel])

    def test_bots_are_kept_and_people_are_not(self) -> None:
        resolver = _resolver(
            {"helperbot": User(id=70, username="helperbot", bot=True), "someone": User(id=71, username="someone")}
        )
        self.assertEqual(self._resolve(resolver, "@helperbot @someone"), [])
        (bot,) = self.message.references.all()
        self.assertTrue(bot.is_bot)
        self.assertFalse(Channel.objects.filter(telegram_id=71).exists())

    def test_stored_person_is_not_mentioned_but_stays_linkable(self) -> None:
        person = make_channel(telegram_id=72, username="someperson", is_user_account=True)
        self._resolve(_resolver(), "@someperson")
        self.assertFalse(self.message.references.exists())
        self._resolve(_resolver(), "t.me/someperson")
        self.assertEqual(list(self.message.references.all()), [person])

    def test_final_answers_are_asked_once_per_run(self) -> None:
        resolver = _resolver({"someone": User(id=71, username="someone")})
        for _ in range(3):
            self._resolve(resolver, "@someone @nobodyhere")
        self.assertEqual(resolver.api_client.client.get_entity.call_count, 2)

    def test_flood_wait_queues_the_handle_and_retry_settles_it(self) -> None:
        missing = self._resolve(_resolver({"newchan": _flood_error()}), "@newchan @ownchan")
        self.assertEqual(missing, ["@newchan"])
        self.message.missing_references = "|".join(missing)
        self.message.save()
        _resolver({"newchan": _telegram_channel(500, "newchan")}).get_missing_references()
        self.message.refresh_from_db()
        self.assertEqual(self.message.missing_references, "")
        self.assertEqual([c.telegram_id for c in self.message.references.all()], [500])

    def test_retry_marks_people_as_settled(self) -> None:
        self.message.missing_references = "@someone"
        self.message.save()
        _resolver({"someone": User(id=71, username="someone")}).get_missing_references()
        self.message.refresh_from_db()
        self.assertEqual(self.message.missing_references, "!@someone")


class MentionBackfillTests(TestCase):
    def setUp(self) -> None:
        label = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, username="OwnChan", label=label, title="Own")
        self.target = make_channel(telegram_id=2, username="TargetChan", title="Target")
        self.outside = make_channel(telegram_id=3, username="outside")
        make_channel(telegram_id=4, username="someperson", is_user_account=True)

    def _post(self, telegram_id: int, text: str, channel: Channel | None = None, **fields) -> Message:
        return Message.objects.create(
            telegram_id=telegram_id, channel=channel or self.channel, date=_DATE, message=text, **fields
        )

    def test_plan_sorts_the_handles(self) -> None:
        post = self._post(1, "@targetchan @ownchan @someperson @unknown1")
        self._post(2, "no handle, only me@mail.org")
        self._post(3, "@targetchan", channel=self.outside)  # not in target: out of scope
        self._post(4, "@targetchan").references.add(self.target)
        plan = plan_backfill()
        self.assertEqual(plan.posts, 2)
        self.assertEqual(plan.references, [(post.pk, self.target.pk)])
        self.assertEqual(plan.unknown, {"unknown1": [post.pk]})
        self.assertEqual(plan.skipped, {"signatures": 1, "people": 1, "already stored": 1})

    def test_extra_usernames_are_known_handles(self) -> None:
        several = make_channel(telegram_id=5, username="", extra_usernames=["MultiOne", "multitwo"])
        first, second = self._post(1, "@multione"), self._post(2, "@MultiTwo")
        plan = plan_backfill()
        self.assertEqual(plan.references, [(first.pk, several.pk), (second.pk, several.pk)])
        self.assertEqual(plan.unknown, {})

    def test_apply_is_repeatable_and_keeps_other_pending_references(self) -> None:
        post = self._post(1, "@targetchan @unknown1", missing_references="waiting")
        for _ in range(2):
            apply_plan(plan_backfill())
        post.refresh_from_db()
        self.assertEqual(list(post.references.all()), [self.target])
        self.assertEqual(post.missing_references, "waiting|@unknown1")

    def test_look_up_settles_every_message_of_a_handle(self) -> None:
        posts = [self._post(1, "@newchan"), self._post(2, "@newchan @someone", missing_references="waiting")]
        plan = plan_backfill()
        apply_plan(plan)
        resolver = _resolver({"newchan": _telegram_channel(500, "newchan"), "someone": User(id=71, username="someone")})
        counts = look_up_handles(resolver, plan)
        self.assertEqual(counts, {"found": 1, "dropped": 1, "references": 2})
        self.assertEqual(resolver.api_client.client.get_entity.call_count, 2)
        for post in posts:
            post.refresh_from_db()
            self.assertEqual([c.telegram_id for c in post.references.all()], [500])
        self.assertEqual([p.missing_references for p in posts], ["", "waiting|!@someone"])
        # A settled handle is not asked again.
        again = plan_backfill()
        self.assertEqual(again.unknown, {})
        self.assertEqual(again.skipped["looked up before"], 1)

    def test_handle_of_the_posts_own_channel_under_another_name_is_a_signature(self) -> None:
        post = self._post(1, "@oldname")
        plan = plan_backfill()
        apply_plan(plan)
        look_up_handles(_resolver({"oldname": _telegram_channel(1, "OwnChan")}), plan)
        post.refresh_from_db()
        self.assertFalse(post.references.exists())
        self.assertEqual(post.missing_references, "")

    def test_references_already_stored_are_not_counted_again(self) -> None:
        # A channel answering to a second handle is looked up on every run: its row stores one username.
        self._post(1, "@othername").references.add(self.target)
        counts = look_up_handles(_resolver({"othername": _telegram_channel(2, "TargetChan")}), plan_backfill())
        self.assertEqual((counts["found"], counts["references"]), (1, 0))

    def test_flood_wait_stops_and_leaves_the_rest_queued(self) -> None:
        posts = [self._post(1, "@aaaa"), self._post(2, "@bbbb"), self._post(3, "@aaaa")]
        plan = plan_backfill()
        apply_plan(plan)
        resolver = _resolver({"aaaa": _flood_error()})
        self.assertEqual(look_up_handles(resolver, plan)["left"], 2)
        resolver.api_client.client.get_entity.assert_called_once_with("aaaa")  # the most used first
        for post, queued in zip(posts, ("@aaaa", "@bbbb", "@aaaa"), strict=True):
            post.refresh_from_db()
            self.assertEqual(post.missing_references, queued)

    def test_limit(self) -> None:
        self._post(1, "@aaaa @bbbb @cccc")
        plan = plan_backfill()
        resolver = _resolver()
        counts = look_up_handles(resolver, plan, limit=2)
        self.assertEqual((counts["dropped"], counts["left"]), (2, 1))
        self.assertEqual(resolver.api_client.client.get_entity.call_count, 2)


class BackfillMentionsCommandTests(TestCase):
    def setUp(self) -> None:
        channel = make_channel(telegram_id=1, username="own", label=make_label(name="Org", is_in_target=True))
        self.target = make_channel(telegram_id=2, username="targetchan", title="Target")
        self.post = Message.objects.create(
            telegram_id=1, channel=channel, date=_DATE, message="@targetchan @unknown1 @unknown2"
        )

    def _run(self, **options) -> str:
        out = io.StringIO()
        call_command("backfill_mentions", stdout=out, stderr=io.StringIO(), **options)
        return out.getvalue()

    @patch(f"{_CMD}.TelegramClient")
    def test_dry_run_writes_nothing(self, mock_client: MagicMock) -> None:
        output = self._run(dry_run=True, resolve=True)
        self.assertIn("1 mentions to record, 2 unknown handles", output)
        self.assertIn("@unknown1", output)
        self.post.refresh_from_db()
        self.assertFalse(self.post.references.exists())
        self.assertEqual(self.post.missing_references, "")
        mock_client.assert_not_called()

    @patch(f"{_CMD}.invalidate_home_summary_cache")
    @patch(f"{_CMD}.TelegramClient")
    def test_default_run_never_connects(self, mock_client: MagicMock, mock_invalidate: MagicMock) -> None:
        self._run()
        self.post.refresh_from_db()
        self.assertEqual(list(self.post.references.all()), [self.target])
        self.assertEqual(self.post.missing_references, "@unknown1|@unknown2")
        mock_client.assert_not_called()
        mock_invalidate.assert_called_once()

    @patch(f"{_CMD}.invalidate_home_summary_cache")
    @patch(f"{_CMD}.ReferenceResolver")
    @patch(f"{_CMD}.TelegramClient")
    def test_resolve_looks_up_the_unknown(
        self, mock_client: MagicMock, mock_resolver: MagicMock, mock_invalidate: MagicMock
    ) -> None:
        mock_resolver.return_value = _resolver({"unknown1": _telegram_channel(500, "unknown1")})
        output = self._run(resolve=True)
        self.assertIn("1 handles found, 1 dropped", output)
        self.assertEqual({c.telegram_id for c in self.post.references.all()}, {2, 500})

    def test_bad_limit(self) -> None:
        with self.assertRaises(CommandError):
            self._run(limit=0)
