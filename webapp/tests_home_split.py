import datetime

from django.test import TestCase
from django.urls import reverse

from webapp.cache import compute_home_summary
from webapp.home_split import _compact, compute_home_split
from webapp.models import LabelGroup, LabelParent, Message, MessageReply
from webapp.test_helpers import attribute, make_channel, make_label


class HomeSplitTests(TestCase):
    """The home page's summary cards under ``?split=<label group>`` (``webapp.home_split``)."""

    def setUp(self) -> None:
        self.org = make_label(name="Org", is_in_target=True)
        self.nation = LabelGroup.objects.create(name="Nation", is_partition=True)
        self.germany = make_label(name="Germany", group=self.nation, is_in_target=False)
        self.uk = make_label(name="UK", group=self.nation, is_in_target=False)
        self.next_id = 0

    def channel(self, *labels, **fields):
        self.next_id += 1
        channel = make_channel(telegram_id=self.next_id, title=f"C{self.next_id}", label=self.org, **fields)
        for label in labels:
            attribute(channel, label)
        return channel

    def post(self, channel, date="2024-05-10T12:00:00Z", **fields) -> Message:
        self.next_id += 1
        return Message.objects.create(telegram_id=self.next_id, channel=channel, date=date, **fields)

    def reply(self, post, sender_id) -> None:
        self.next_id += 1
        MessageReply.objects.create(parent_message=post, telegram_id=self.next_id, sender_id=sender_id, date=post.date)

    def table(self, card, voice=None, group=None) -> dict:
        split = compute_home_split(voice, group or self.nation)[card]
        return {row["label"]: [cell["title"] or cell["text"] for cell in row["cells"]] for row in split["rows"]}

    def assert_adds_up(self, voice=None) -> None:
        """Every column sums to the card's own figure."""
        cards = {card["key"]: card for row in compute_home_summary(voice) for card in row}

        def total(card, column):
            return sum(int(cells[column].replace(",", "")) for cells in self.table(card, voice).values())

        for key in ("channels", "messages", "media", "views", "forwards", "mentions"):
            self.assertEqual(total(key, 0), int(cards[key]["value"].replace(",", "")), key)
        for key, column, entry in (
            ("messages", 1, 0),
            ("views", 1, 0),
            ("forwards", 1, 0),
            ("forwards", 2, 1),
            ("mentions", 1, 0),
            ("mentions", 2, 1),
        ):
            expected = int(cards[key]["secondary"][entry]["value"].replace(",", ""))
            self.assertEqual(total(key, column), expected, (key, column))

    def populate(self):
        german, british, unlabelled = self.channel(self.germany), self.channel(self.uk), self.channel()
        outside = make_channel(telegram_id=900, title="Outside")
        self.post(german, views=100, media_type="photo")
        self.post(german, views=1000, forwarded_from=british, media_type="video", date="2024-07-01T12:00:00Z")
        self.post(german, forwarded_from=german)
        self.post(british, views=30, forwarded_from=outside)
        self.post(british, views=5, media_type="none").references.add(german, british, outside)
        self.post(unlabelled, views=7, media_type="audio").references.add(german)
        return german, british, unlabelled

    def test_every_card(self) -> None:
        german, british, _unlabelled = self.populate()
        german.participants_count = 1500
        german.save()
        post = self.post(german)
        for sender in (11, 11, 12):
            self.reply(post, sender)
        self.reply(self.post(british), 11)
        none = "No Nation label"
        self.assertEqual(self.table("channels"), {"Germany": ["1"], "UK": ["1"], none: ["1"]})
        self.assertEqual(self.table("messages"), {"Germany": ["4", "3"], "UK": ["3", "1"], none: ["1", "0"]})
        self.assertEqual(self.table("media")["Germany"], ["2", "1", "1"])
        self.assertEqual(self.table("media")[none], ["1", "0", "0"])
        # Account 11 commented under both labels: it counts in each row.
        self.assertEqual(
            self.table("views"),
            {"Germany": ["1,100", "1,500", "2"], "UK": ["35", "0", "1"], none: ["7", "0", "0"]},
        )
        self.assertEqual(self.table("forwards"), {"Germany": ["1", "1", "0"], "UK": ["0", "0", "1"], none: ["0"] * 3})
        self.assertEqual(self.table("mentions"), {"Germany": ["0"] * 3, "UK": ["1", "1", "1"], none: ["1", "0", "0"]})
        self.assertEqual(self.table("dates")["Germany"], ["May 2024", "Jul 2024"])
        self.assert_adds_up()

    def test_under_a_scope(self) -> None:
        self.populate()
        self.assertEqual(self.table("messages", voice=self.germany), {"Germany": ["3", "0"]})
        self.assert_adds_up(self.germany)

    def test_a_message_counts_under_the_label_of_its_date(self) -> None:
        channel = self.channel()
        attribute(channel, self.germany, end=datetime.date(2024, 5, 31))
        attribute(channel, self.uk, start=datetime.date(2024, 6, 1))
        self.post(channel, views=10)
        self.post(channel, views=20, date="2024-06-10T12:00:00Z")
        self.post(channel, views=40, date="2024-06-11T12:00:00Z")
        self.assertEqual(self.table("messages"), {"Germany": ["1", "0"], "UK": ["2", "0"]})
        # The channel itself counts once, under its label today.
        self.assertEqual(self.table("channels"), {"Germany": ["0"], "UK": ["1"]})
        self.assert_adds_up()

    def test_channel_without_a_current_label_counts_under_its_latest_past_one(self) -> None:
        channel = self.channel()
        attribute(channel, self.uk, start=datetime.date(2020, 1, 1), end=datetime.date(2021, 1, 1))
        attribute(channel, self.germany, start=datetime.date(2022, 1, 1), end=datetime.date(2023, 1, 1))
        self.assertEqual(self.table("channels"), {"Other": ["1"]})  # it has no post: no label has a line of its own
        self.post(channel, date="2022-05-01T12:00:00Z")
        self.assertEqual(self.table("channels"), {"Germany": ["1"]})

    def test_container_group(self) -> None:
        continents = LabelGroup.objects.create(name="Continent", is_partition=True, is_container=True)
        europe = make_label(name="Europe", group=continents, is_in_target=False)
        LabelParent.objects.create(label=self.germany, parent=europe)
        self.populate()
        self.assertEqual(self.table("channels", group=continents), {"Europe": ["1"], "No Continent label": ["2"]})

    def test_rows_carry_the_chart_colours(self) -> None:
        self.populate()
        rows = compute_home_split(None, self.nation)["messages"]["rows"]
        self.assertEqual([row["color"] for row in rows], [1, 2, "rest"])

    def test_page_draws_the_tables_only_when_split(self) -> None:
        self.populate()
        plain = self.client.get(reverse("home"))
        self.assertNotContains(plain, "sc-split-wrap")
        split = self.client.get(reverse("home"), {"split": self.nation.pk})
        self.assertContains(split, "sc-split-wrap", count=7)
        # One button per card, each naming the table it opens; closed until clicked.
        self.assertContains(split, 'class="sc-split-toggle" aria-expanded="false"', count=7)
        for key in ("channels", "messages", "media", "views", "forwards", "mentions", "dates"):
            self.assertContains(split, f'aria-controls="sc-split-{key}"', count=1)
            self.assertContains(split, f'id="sc-split-{key}"', count=1)
        self.assertNotContains(plain, "sc-split-toggle")
        self.assertContains(split, "Messages collected by Nation")
        # The cached unsplit summary is left alone.
        self.assertNotContains(self.client.get(reverse("home")), "sc-split-wrap")

    def test_compact_figures(self) -> None:
        for value, text in ((0, "0"), (999, "999"), (5_387, "5.4K"), (45_466, "45.5K"), (812_000, "812K")):
            self.assertEqual(_compact(value), text)
        self.assertEqual(_compact(35_195_794), "35.2M")
        self.assertEqual(_compact(182_582_479), "183M")
