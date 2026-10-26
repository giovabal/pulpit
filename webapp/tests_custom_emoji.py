"""Custom emoji in the web app: drawing them (templatetags/custom_emoji.py) and pack usage (emoji_usage.py)."""

import csv
import datetime
import io

from django.template.defaultfilters import linebreaks_filter, urlize
from django.test import TestCase
from django.urls import reverse

from webapp import emoji_usage
from webapp.models import (
    CustomEmoji,
    CustomEmojiPack,
    Message,
    MessageCustomEmoji,
    MessageCustomReaction,
    MessageReaction,
)
from webapp.templatetags.custom_emoji import message_html, reaction_pills
from webapp.test_helpers import make_channel, make_label


def _dated(year: int, month: int, day: int) -> datetime.datetime:
    return datetime.datetime(year, month, day, 12, 0, tzinfo=datetime.timezone.utc)


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class _EmojiFixture(TestCase):
    def setUp(self) -> None:
        self.pack = CustomEmojiPack.objects.create(telegram_id=900, title="Fire pack", short_name="firepack")
        self.fire = CustomEmoji.objects.create(
            telegram_id=77, alt="🔥", mime_type="image/webp", pack=self.pack, file="stickers/emoji/77.webp"
        )
        self.wave = CustomEmoji.objects.create(
            telegram_id=78, alt="👋", mime_type="application/x-tgsticker", pack=self.pack, file="stickers/emoji/78.tgs"
        )
        self.org = make_label("Org")
        self.channel = make_channel(telegram_id=1, title="Alpha", username="alpha", label=self.org)

    def _post(self, text: str, *spans: tuple[CustomEmoji, str], channel=None, **fields) -> Message:
        message = Message.objects.create(
            channel=channel or self.channel,
            telegram_id=Message.objects.count() + 1,
            message=text,
            date=fields.pop("date", _dated(2024, 5, 1)),
            **fields,
        )
        for emoji, before in spans:
            MessageCustomEmoji.objects.create(message=message, emoji=emoji, offset=_utf16(before), length=2)
        return message


class MessageHtmlTests(_EmojiFixture):
    def test_text_without_custom_emoji_renders_as_before(self) -> None:
        post = self._post("Line one https://example.com\n\nLine <two>")
        expected = urlize(linebreaks_filter(post.message, autoescape=True), autoescape=True)
        self.assertEqual(message_html(post), expected)

    def test_a_custom_emoji_replaces_its_fallback_in_place(self) -> None:
        post = self._post("Hot 🔥 news <b> https://example.com", (self.fire, "Hot "))
        html = message_html(post)
        self.assertIn(
            'Hot <img class="custom-emoji" src="/media/stickers/emoji/77.webp" alt="🔥" title="🔥 · Fire pack"', html
        )
        self.assertNotIn("🔥 news", html)
        self.assertIn("&lt;b&gt;", html)
        self.assertIn('<a href="https://example.com" rel="nofollow">https://example.com</a>', html)
        self.assertTrue(html.startswith("<p>"))

    def test_lottie_emoji_keep_the_fallback_until_the_script_draws_them(self) -> None:
        html = message_html(self._post("Hi 👋", (self.wave, "Hi ")))
        self.assertIn('data-tgs-src="/media/stickers/emoji/78.tgs" data-play="loop" role="img" aria-label="👋"', html)
        self.assertIn(">👋</span>", html)

    def test_text_colour_emoji_are_masked(self) -> None:
        self.fire.text_color = True
        self.fire.save()
        html = message_html(self._post("🔥", (self.fire, "")))
        self.assertIn("custom-emoji--mask", html)
        self.assertIn("--custom-emoji-src: url('/media/stickers/emoji/77.webp')", html)

    def test_an_emoji_without_file_keeps_its_fallback(self) -> None:
        self.fire.file = ""
        self.fire.save()
        self.assertEqual(message_html(self._post("Hot 🔥", (self.fire, "Hot "))), "<p>Hot 🔥</p>")

    def test_spans_that_do_not_fit_the_text_are_ignored(self) -> None:
        post = self._post("short")
        MessageCustomEmoji.objects.create(message=post, emoji=self.fire, offset=40, length=2)
        self.assertEqual(message_html(post), "<p>short</p>")

    def test_line_breaks_around_an_emoji(self) -> None:
        html = message_html(self._post("a\n🔥\n\nb", (self.fire, "a\n")))
        self.assertTrue(html.startswith("<p>a<br><img "))
        self.assertTrue(html.endswith("</p>\n\n<p>b</p>"))


class ReactionPillsTests(_EmojiFixture):
    def test_the_custom_bucket_is_split_into_its_emoji(self) -> None:
        post = self._post("x")
        MessageReaction.objects.create(message=post, emoji="❤", count=9)
        MessageReaction.objects.create(message=post, emoji="custom", count=7)
        MessageCustomReaction.objects.create(message=post, emoji=self.fire, count=4)
        unresolved = CustomEmoji.objects.create(telegram_id=79)
        MessageCustomReaction.objects.create(message=post, emoji=unresolved, count=1)

        pills = reaction_pills(post)

        self.assertEqual([p["count"] for p in pills], [9, 4, 3])
        self.assertEqual(pills[0]["html"], "❤️")
        self.assertIn("stickers/emoji/77.webp", pills[1]["html"])
        self.assertEqual(pills[2]["html"], "custom")


class UsageRowsTests(_EmojiFixture):
    def setUp(self) -> None:
        super().setUp()
        self.beta = make_channel(telegram_id=2, title="Beta", label=self.org)

    def test_own_posts_forwards_and_reactions_are_counted_apart(self) -> None:
        self._post("🔥 🔥", (self.fire, ""), (self.fire, "🔥 "), date=_dated(2024, 1, 5))
        self._post("👋", (self.wave, ""), date=_dated(2024, 6, 1))
        self._post("🔥", (self.fire, ""), forwarded_from=self.beta)
        reacted = self._post("plain")
        MessageCustomReaction.objects.create(message=reacted, emoji=self.fire, count=6)

        rows = emoji_usage.usage_rows(emoji_usage.scope_messages())

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["channel_id"], row["pack_id"]), (self.channel.pk, self.pack.pk))
        self.assertEqual((row["own_uses"], row["own_messages"]), (3, 2))
        self.assertEqual((row["forwarded_uses"], row["forwarded_messages"]), (1, 1))
        self.assertEqual(row["reactions"], 6)
        self.assertEqual((row["first_used"], row["last_used"]), (_dated(2024, 1, 5), _dated(2024, 6, 1)))

    def test_out_of_period_and_lost_messages_are_left_out(self) -> None:
        bounded = make_channel(
            telegram_id=3,
            label=self.org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 12, 31),
        )
        self._post("🔥", (self.fire, ""), channel=bounded, date=_dated(2023, 6, 1))
        self._post("🔥", (self.fire, ""), channel=bounded, is_lost=True)
        self.assertEqual(emoji_usage.usage_rows(emoji_usage.scope_messages()), [])

    def test_pack_summaries_count_the_channels_using_a_pack_in_own_posts(self) -> None:
        self._post("🔥", (self.fire, ""))
        self._post("🔥", (self.fire, ""), channel=self.beta, forwarded_from=self.channel)
        orphan = CustomEmoji.objects.create(telegram_id=80, alt="⭐")
        self._post("⭐", (orphan, ""), channel=self.beta)

        summaries = emoji_usage.summaries(emoji_usage.usage_rows(emoji_usage.scope_messages()), "pack")

        self.assertEqual([s["pack_id"] for s in summaries], [self.pack.pk, None])
        self.assertEqual(
            (summaries[0]["channels"], summaries[0]["own_uses"], summaries[0]["forwarded_uses"]), (1, 1, 1)
        )


class EmojiPackViewsTests(_EmojiFixture):
    def setUp(self) -> None:
        super().setUp()
        self._post("Hot 🔥", (self.fire, "Hot "))
        self._post("Hi 👋", (self.wave, "Hi "))

    def test_packs_page_lists_the_pack_with_its_preview(self) -> None:
        response = self.client.get(reverse("emoji-packs"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Fire pack", html)
        self.assertIn("https://t.me/addemoji/firepack", html)
        self.assertIn("stickers/emoji/77.webp", html)
        self.assertIn(reverse("emoji-pack-usage-csv"), html)

    def test_pack_detail_lists_its_emoji_and_channels(self) -> None:
        response = self.client.get(reverse("emoji-pack-detail", kwargs={"pk": self.pack.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["emoji"] for row in response.context["emoji_rows"]], [self.fire, self.wave])
        self.assertEqual(response.context["emoji_rows"][0]["own_uses"], 1)
        self.assertEqual([row["channel"] for row in response.context["rows"]], [self.channel])

    def test_csv_has_one_row_per_channel_and_pack(self) -> None:
        response = self.client.get(reverse("emoji-pack-usage-csv"))
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {k: rows[0][k] for k in ("channel_username", "label", "pack_short_name", "own_uses", "first_used")},
            {
                "channel_username": "alpha",
                "label": "Org",
                "pack_short_name": "firepack",
                "own_uses": "2",
                "first_used": "2024-05-01",
            },
        )

    def test_channel_page_shows_its_packs_and_draws_the_emoji(self) -> None:
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.channel.pk}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("1 custom emoji pack in own posts", html)
        self.assertIn(reverse("emoji-pack-detail", kwargs={"pk": self.pack.pk}), html)
        self.assertIn('Hot <img class="custom-emoji"', html)

    def test_channel_list_links_the_packs_page(self) -> None:
        self.assertContains(self.client.get(reverse("channel-list")), reverse("emoji-packs"))

    def test_unknown_pack_is_404(self) -> None:
        self.assertEqual(self.client.get(reverse("emoji-pack-detail", kwargs={"pk": 999})).status_code, 404)

    def _second_pack(self) -> CustomEmojiPack:
        other = CustomEmojiPack.objects.create(telegram_id=901, title="Other pack")
        star = CustomEmoji.objects.create(
            telegram_id=79, alt="⭐", mime_type="image/webp", pack=other, file="stickers/emoji/79.webp"
        )
        self._post("⭐", (star, ""))
        return other

    def test_packs_page_filters_by_in_target(self) -> None:
        other = self._second_pack()
        self.pack.is_in_target = True
        self.pack.save()

        def listed(query: str) -> list:
            return [row["pack"] for row in self.client.get(reverse("emoji-packs") + query).context["packs"]]

        self.assertEqual(listed(""), [self.pack, other])
        self.assertEqual(listed("?target=in"), [self.pack])
        self.assertEqual(listed("?target=out"), [other])
        self.assertEqual(listed("?target=bogus"), [self.pack, other])
        self.assertContains(self.client.get(reverse("emoji-packs")), "in target</span>", count=1)

    def test_pack_csv_flags_and_filters_in_target_packs(self) -> None:
        self._second_pack()
        self.pack.is_in_target = True
        self.pack.save()

        def rows(query: str) -> list[dict]:
            body = self.client.get(reverse("emoji-pack-usage-csv") + query).content.decode()
            return list(csv.DictReader(io.StringIO(body)))

        self.assertEqual({r["pack_short_name"]: r["pack_in_target"] for r in rows("")}, {"firepack": "1", "": "0"})
        self.assertEqual([r["pack_title"] for r in rows("?target=out")], ["Other pack"])

    def test_group_packs_are_shown_and_exported(self) -> None:
        group = make_channel(telegram_id=55, title="Org chat", megagroup=True, emoji_pack=self.pack)

        html = self.client.get(reverse("channel-detail", kwargs={"pk": group.pk})).content.decode()
        self.assertIn("Group emoji pack:", html)
        self.assertIn(reverse("emoji-pack-detail", kwargs={"pk": self.pack.pk}), html)
        self.assertContains(self.client.get(reverse("emoji-packs")), "The own emoji pack of Org chat")
        detail = self.client.get(reverse("emoji-pack-detail", kwargs={"pk": self.pack.pk})).content.decode()
        self.assertIn(f'The own emoji pack of <a href="{group.get_absolute_url()}">Org chat</a>', detail)
        body = self.client.get(reverse("emoji-pack-usage-csv")).content.decode()
        self.assertEqual(list(csv.DictReader(io.StringIO(body)))[0]["pack_group_channel_ids"], "55")

    def test_channel_page_marks_in_target_packs(self) -> None:
        self.pack.is_in_target = True
        self.pack.save()
        html = self.client.get(reverse("channel-detail", kwargs={"pk": self.channel.pk})).content.decode()
        self.assertIn("In-target pack · 2 uses", html)


class CustomEmojiPagesTests(_EmojiFixture):
    def setUp(self) -> None:
        super().setUp()
        self.beta = make_channel(telegram_id=2, title="Beta", label=self.org)
        self._post("🔥 a", (self.fire, ""), date=_dated(2024, 1, 10))
        self._post("🔥 b", (self.fire, ""), date=_dated(2024, 3, 2))
        self._post("🔥 c", (self.fire, ""), channel=self.beta, date=_dated(2024, 3, 5), forwarded_from=self.channel)
        self._post("👋", (self.wave, ""), channel=self.beta, date=_dated(2024, 2, 1))
        MessageCustomReaction.objects.create(message=self._post("plain"), emoji=self.fire, count=4)

    def test_emoji_level_rows(self) -> None:
        rows = {
            (r["channel_id"], r["emoji_id"]): r for r in emoji_usage.usage_rows(emoji_usage.scope_messages(), "emoji")
        }
        alpha_fire = rows[(self.channel.pk, self.fire.pk)]
        self.assertEqual((alpha_fire["own_uses"], alpha_fire["reactions"]), (2, 4))
        self.assertEqual(rows[(self.beta.pk, self.fire.pk)]["forwarded_uses"], 1)
        self.assertEqual(rows[(self.beta.pk, self.wave.pk)]["own_uses"], 1)

    def test_monthly_own_uses_fills_the_gaps_and_skips_forwards(self) -> None:
        self.assertEqual(
            emoji_usage.monthly_own_uses(emoji_usage.scope_messages(), self.fire),
            {"labels": ["2024-01", "2024-02", "2024-03"], "values": [1, 0, 1]},
        )
        self.assertEqual(
            emoji_usage.monthly_own_uses(emoji_usage.scope_messages(), CustomEmoji.objects.create(telegram_id=5)),
            {"labels": [], "values": []},
        )

    def test_list_page(self) -> None:
        response = self.client.get(reverse("custom-emoji-list"))
        self.assertEqual(response.status_code, 200)
        rows = list(response.context["page_obj"].object_list)
        self.assertEqual([row["emoji"] for row in rows], [self.fire, self.wave])
        self.assertEqual((rows[0]["channels"], rows[0]["own_uses"], rows[0]["forwarded_uses"]), (1, 2, 1))
        self.assertContains(response, reverse("custom-emoji-detail", kwargs={"pk": self.fire.pk}))
        self.assertEqual(list(self.client.get(reverse("custom-emoji-list") + "?target=in").context["page_obj"]), [])

    def test_detail_page(self) -> None:
        response = self.client.get(reverse("custom-emoji-detail", kwargs={"pk": self.fire.pk}))
        self.assertEqual(response.status_code, 200)
        summary = response.context["summary"]
        self.assertEqual((summary["own_uses"], summary["forwarded_uses"], summary["reactions"]), (2, 1, 4))
        self.assertEqual([row["channel"] for row in response.context["rows"]], [self.channel, self.beta])
        self.assertEqual(response.context["monthly"]["values"], [1, 0, 1])
        self.assertEqual(len(response.context["page_obj"].object_list), 3)
        self.assertContains(response, 'id="emoji-monthly-data"')

    def test_detail_page_options_apply_to_its_posts(self) -> None:
        response = self.client.get(reverse("custom-emoji-detail", kwargs={"pk": self.fire.pk}), {"q": "b"})
        self.assertEqual([post.message for post in response.context["page_obj"]], ["🔥 b"])

    def test_emoji_csv(self) -> None:
        body = self.client.get(reverse("custom-emoji-usage-csv")).content.decode()
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual(
            sorted((r["channel_title"], r["emoji_alt"], r["own_uses"], r["forwarded_uses"]) for r in rows),
            [("Alpha", "🔥", "2", "0"), ("Beta", "👋", "1", "0"), ("Beta", "🔥", "0", "1")],
        )
        self.assertEqual({r["pack_short_name"] for r in rows}, {"firepack"})


class CustomEmojiKindTests(TestCase):
    def test_media_path_uses_the_format_extension(self) -> None:
        for mime, expected in (
            ("image/webp", "stickers/emoji/5.webp"),
            ("application/x-tgsticker", "stickers/emoji/5.tgs"),
            ("video/webm", "stickers/emoji/5.webm"),
            ("", "stickers/emoji/5.bin"),
        ):
            self.assertEqual(CustomEmoji(telegram_id=5, mime_type=mime).get_media_path("x.bin"), expected)

    def test_kind(self) -> None:
        kinds = [CustomEmoji(mime_type=m).kind for m in ("application/x-tgsticker", "video/webm", "image/webp", "")]
        self.assertEqual(kinds, ["lottie", "video", "image", "image"])
