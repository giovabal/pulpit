import json

from django.test import TestCase
from django.urls import reverse

from stats.queries import (
    channel_month_spine as _channel_month_spine,
    global_month_spine as _global_month_spine,
    reindex_to_spine as _reindex_to_spine,
)
from webapp.models import LabelGroup, LabelParent, Message
from webapp.test_helpers import attribute, make_channel, make_label

import pandas as pd


class StatsViewsTests(TestCase):
    def test_messages_history_data_returns_json(self):
        lbl = make_label(name="In-target Org", is_in_target=True)
        channel = make_channel(telegram_id=1, title="C1", label=lbl)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-20T00:00:00Z")

        response = self.client.get(reverse("messages-history-data"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = json.loads(response.content)
        self.assertIn("labels", data)
        self.assertIn("values", data)
        self.assertEqual(data["y_label"], "messages")
        self.assertEqual(data["labels"], ["2024-01"])
        self.assertEqual(data["values"], [1])

    def test_active_channels_history_data_returns_json(self):
        lbl = make_label(name="In-target Org", is_in_target=True)
        channel1 = make_channel(telegram_id=1, title="C1", label=lbl)
        channel2 = make_channel(telegram_id=2, title="C2", label=lbl)
        Message.objects.create(telegram_id=1, channel=channel1, date="2024-01-20T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=channel2, date="2024-01-22T00:00:00Z")

        response = self.client.get(reverse("active-channels-history-data"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = json.loads(response.content)
        self.assertIn("labels", data)
        self.assertIn("values", data)
        self.assertEqual(data["y_label"], "active channels")
        self.assertEqual(data["labels"], ["2024-01"])
        self.assertEqual(data["values"], [2])


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class GlobalMonthSpineTests(TestCase):
    def test_empty_db_returns_empty_list(self):
        self.assertEqual(_global_month_spine(), [])

    def test_single_message_returns_single_month(self):
        org = make_label(name="Org", is_in_target=True)
        channel = make_channel(telegram_id=1, title="C1", label=org)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-03-15T00:00:00Z")
        self.assertEqual(_global_month_spine(), ["2024-03"])

    def test_multi_month_span_fills_intermediate_months(self):
        org = make_label(name="Org", is_in_target=True)
        channel = make_channel(telegram_id=1, title="C1", label=org)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-01T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=channel, date="2024-03-01T00:00:00Z")
        self.assertEqual(_global_month_spine(), ["2024-01", "2024-02", "2024-03"])

    def test_ignores_out_of_target_channels(self):
        org = make_label(name="Org", is_in_target=False)
        channel = make_channel(telegram_id=1, title="C1", label=org)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-01T00:00:00Z")
        self.assertEqual(_global_month_spine(), [])

    def test_ignores_messages_without_date(self):
        org = make_label(name="Org", is_in_target=True)
        channel = make_channel(telegram_id=1, title="C1", label=org)
        Message.objects.create(telegram_id=1, channel=channel, date=None)
        self.assertEqual(_global_month_spine(), [])


class ChannelMonthSpineTests(TestCase):
    def setUp(self):
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=org)

    def test_no_messages_returns_empty_list(self):
        self.assertEqual(_channel_month_spine(self.channel), [])

    def test_single_message_returns_single_month(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-06-10T00:00:00Z")
        self.assertEqual(_channel_month_spine(self.channel), ["2024-06"])

    def test_multi_month_span_fills_intermediate_months(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-01-01T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-04-01T00:00:00Z")
        self.assertEqual(_channel_month_spine(self.channel), ["2024-01", "2024-02", "2024-03", "2024-04"])

    def test_ignores_messages_without_date(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date=None)
        self.assertEqual(_channel_month_spine(self.channel), [])


class ReindexToSpineTests(TestCase):
    def test_fills_missing_months_with_zero(self):
        df = pd.DataFrame({"month": ["2024-01", "2024-03"], "count": [5, 3]})
        result = _reindex_to_spine(df, ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(list(result["month"]), ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(list(result["count"]), [5, 0, 3])

    def test_preserves_existing_values(self):
        df = pd.DataFrame({"month": ["2024-01"], "val": [42]})
        result = _reindex_to_spine(df, ["2024-01"])
        self.assertEqual(list(result["val"]), [42])

    def test_all_months_missing_fills_all_zeros(self):
        df = pd.DataFrame({"month": [], "val": []})
        result = _reindex_to_spine(df, ["2024-01", "2024-02"])
        self.assertEqual(list(result["val"]), [0, 0])


# ---------------------------------------------------------------------------
# Global time-series views
# ---------------------------------------------------------------------------


class ForwardsHistoryDataViewTests(TestCase):
    def setUp(self):
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=self.org)
        self.source = make_channel(telegram_id=2, title="C2", label=self.org)

    def test_empty_db_returns_empty_response(self):
        response = self.client.get(reverse("forwards-history-data"))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "forwards")

    def test_counts_only_forwarded_messages(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-01-10T00:00:00Z")
        Message.objects.create(
            telegram_id=2, channel=self.channel, date="2024-01-15T00:00:00Z", forwarded_from=self.source
        )
        response = self.client.get(reverse("forwards-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-01"])
        self.assertEqual(data["values"], [1])

    def test_fills_empty_months_with_zero(self):
        Message.objects.create(
            telegram_id=1, channel=self.channel, date="2024-01-15T00:00:00Z", forwarded_from=self.source
        )
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-03-10T00:00:00Z")
        response = self.client.get(reverse("forwards-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(data["values"], [1, 0, 0])

    def test_excludes_out_of_target_channels(self):
        non_org = make_label(name="Non", is_in_target=False)
        non_channel = make_channel(telegram_id=3, title="C3", label=non_org)
        Message.objects.create(
            telegram_id=1, channel=non_channel, date="2024-01-15T00:00:00Z", forwarded_from=self.source
        )
        response = self.client.get(reverse("forwards-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])


class ViewsHistoryDataViewTests(TestCase):
    def setUp(self):
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=self.org)

    def test_empty_db_returns_empty_response(self):
        response = self.client.get(reverse("views-history-data"))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "views")

    def test_sums_views_per_month(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-02-01T00:00:00Z", views=100)
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-02-15T00:00:00Z", views=200)
        response = self.client.get(reverse("views-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-02"])
        self.assertEqual(data["values"], [300])

    def test_null_views_count_as_zero(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-02-01T00:00:00Z", views=None)
        response = self.client.get(reverse("views-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-02"])
        self.assertEqual(data["values"], [0])


class AvgInvolvementHistoryDataViewTests(TestCase):
    def setUp(self):
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=self.org)

    def test_empty_db_returns_empty_response(self):
        response = self.client.get(reverse("avg-involvement-history-data"))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "avg views")

    def test_averages_views_per_month(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-05-01T00:00:00Z", views=100)
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-05-15T00:00:00Z", views=300)
        response = self.client.get(reverse("avg-involvement-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-05"])
        self.assertEqual(data["values"], [200])

    def test_null_views_default_to_zero_in_average(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-05-01T00:00:00Z", views=None)
        response = self.client.get(reverse("avg-involvement-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-05"])
        self.assertEqual(data["values"], [0])

    def _median_line(self, **params):
        data = json.loads(self.client.get(reverse("avg-involvement-history-data"), params).content)
        (line,) = data["extra_lines"]
        self.assertEqual(line["label"], "median of active channels")
        return data, line["values"]

    def test_median_counts_each_active_channel_once(self):
        # A prolific big channel pulls the mean of all posts, not the median of channels.
        others = [make_channel(telegram_id=n, title=f"C{n}", label=self.org) for n in (2, 3, 4)]
        for n in range(8):
            Message.objects.create(telegram_id=n, channel=self.channel, date="2024-05-01T00:00:00Z", views=1000)
        for channel, views in zip(others[:2], ((10, 30), (50, 50)), strict=True):
            for n, v in enumerate(views):
                Message.objects.create(telegram_id=n, channel=channel, date="2024-05-02T00:00:00Z", views=v)
        # others[2] posts nothing: not an active channel.
        data, medians = self._median_line()
        self.assertEqual(data["values_label"], "mean of all posts")
        self.assertEqual(data["values"], [(8 * 1000 + 140) / 12])
        self.assertEqual(medians, [50])

    def test_median_is_empty_where_no_channel_posted_or_views_are_unknown(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-03-01T12:00:00Z", views=100)
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-05-01T12:00:00Z", views=None)
        data, medians = self._median_line()
        self.assertEqual(data["labels"], ["2024-03", "2024-04", "2024-05"])
        self.assertEqual(data["values"], [100, 0, 0])
        self.assertEqual(medians, [100, None, None])

    def test_median_follows_the_in_target_periods(self):
        bounded = make_channel(telegram_id=2, title="C2")
        attribute(bounded, self.org, start="2024-06-01")
        for channel, views in ((self.channel, 100), (bounded, 900)):
            for n, date in enumerate(("2024-05-10T12:00:00Z", "2024-06-10T12:00:00Z")):
                Message.objects.create(telegram_id=n, channel=channel, date=date, views=views)
        _, medians = self._median_line()
        self.assertEqual(medians, [100, 500])

    def test_other_series_have_no_extra_line(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-05-01T00:00:00Z", views=100)
        data = json.loads(self.client.get(reverse("views-history-data")).content)
        self.assertNotIn("extra_lines", data)


class _TwoLinesChartMixin:
    url_name: str

    def setUp(self):
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=self.org)
        self.next_id = 0

    def post(self, channel=None, date="2024-05-10T12:00:00Z", **fields):
        self.next_id += 1
        return Message.objects.create(telegram_id=self.next_id, channel=channel or self.channel, date=date, **fields)

    def url(self):
        return reverse(self.url_name)

    def lines(self, **params):
        data = json.loads(self.client.get(self.url(), params).content)
        (extra,) = data["extra_lines"]
        return data["labels"], data["values"], extra["values"]

    def test_no_messages_returns_empty_response(self):
        data = json.loads(self.client.get(self.url()).content)
        self.assertEqual((data["labels"], data["values"]), ([], []))


class OwnForwardedViewsHistoryTests(_TwoLinesChartMixin, TestCase):
    url_name = "own-forwarded-views-history-data"

    def test_own_posts_and_forwards_are_apart(self):
        source = make_channel(telegram_id=9, title="Source")
        self.post(views=100)
        self.post(views=300)
        self.post(views=30, forwarded_from=source)
        self.post(views=50, fwd_from_from_name="Hidden user")  # a header without a source channel
        other = make_channel(telegram_id=2, title="C2", label=self.org)
        self.post(other, views=1000)
        self.assertEqual(self.lines(), (["2024-05"], [600], [40]))

    def test_months_without_a_kind_are_gaps(self):
        source = make_channel(telegram_id=9, title="Source")
        self.post(views=100, date="2024-03-10T12:00:00Z")
        self.post(views=30, forwarded_from=source)
        self.post(views=None)
        self.assertEqual(self.lines(), (["2024-03", "2024-04", "2024-05"], [100, None, None], [None, None, 30]))


class ReactionRateHistoryTests(_TwoLinesChartMixin, TestCase):
    url_name = "reaction-rate-history-data"

    def test_rate_of_all_posts_and_of_the_median_channel(self):
        self.post(views=1000, total_reactions=10)
        self.post(views=3000, total_reactions=10)
        other = make_channel(telegram_id=2, title="C2", label=self.org)
        self.post(other, views=100, total_reactions=4)
        # All together 24 / 4,100; the channels' own rates are 5 and 40.
        self.assertEqual(self.lines(), (["2024-05"], [5.9], [22.5]))

    def test_an_album_is_one_post(self):
        for views, reactions in ((480, 20), (500, 0), (490, 0)):
            self.post(views=views, total_reactions=reactions, grouped_id=77)
        self.assertEqual(self.lines(), (["2024-05"], [40], [40]))

    def test_starts_when_telegram_added_reactions(self):
        self.post(views=1000, date="2021-11-10T12:00:00Z")
        self.post(views=1000, total_reactions=10, date="2022-02-10T12:00:00Z")
        self.assertEqual(self.lines(), (["2022-01", "2022-02"], [None, 10], [None, 10]))

    def test_only_older_posts_gives_an_empty_chart(self):
        self.post(views=1000, date="2021-11-10T12:00:00Z")
        data = json.loads(self.client.get(self.url()).content)
        self.assertEqual((data["labels"], data["values"]), ([], []))

    def test_albums_are_keyed_by_channel(self):
        other = make_channel(telegram_id=2, title="C2", label=self.org)
        for channel in (self.channel, other):
            self.post(channel, views=1000, total_reactions=10, grouped_id=77)
        self.assertEqual(self.lines()[1], [10])

    def test_forwards_and_posts_without_views_are_left_out(self):
        source = make_channel(telegram_id=9, title="Source")
        self.post(views=1000, total_reactions=10)
        self.post(views=1000, total_reactions=500, forwarded_from=source)
        self.post(views=0, total_reactions=3)
        self.post(views=None, total_reactions=3)
        self.assertEqual(self.lines(), (["2024-05"], [10], [10]))

    def test_months_without_own_posts_are_gaps(self):
        self.post(views=1000, total_reactions=10, date="2024-03-10T12:00:00Z")
        self.post(views=1000, total_reactions=20)
        self.assertEqual(self.lines(), (["2024-03", "2024-04", "2024-05"], [10, None, 20], [10, None, 20]))

    def test_follows_the_in_target_periods(self):
        bounded = make_channel(telegram_id=2, title="C2")
        attribute(bounded, self.org, start="2024-06-01")
        self.post(views=1000, total_reactions=10)
        self.post(bounded, views=1000, total_reactions=90)
        self.assertEqual(self.lines()[1], [10])


class SplitChartsTests(TestCase):
    """``?split=<label group>`` on the home page's charts (``stats.split.LabelSplit``)."""

    def setUp(self):
        self.org = make_label(name="Org", is_in_target=True)
        self.nation = LabelGroup.objects.create(name="Nation", is_partition=True)
        self.labels = {}
        self.next_id = 0

    def label(self, name):
        if name not in self.labels:
            self.labels[name] = make_label(name=name, group=self.nation, is_in_target=False)
        return self.labels[name]

    def channels(self, nation, n):
        made = []
        for _ in range(n):
            self.next_id += 1
            channel = make_channel(telegram_id=self.next_id, title=f"{nation} {self.next_id}", label=self.org)
            if nation:
                attribute(channel, self.label(nation))
            made.append(channel)
        return made

    def post(self, channel, date="2024-05-10T12:00:00Z", **fields):
        self.next_id += 1
        return Message.objects.create(telegram_id=self.next_id, channel=channel, date=date, **fields)

    def charts(self, name, **params):
        data = json.loads(self.client.get(reverse(name), {"split": self.nation.pk, **params}).content)
        return data, [{line["label"]: line["values"] for line in chart["lines"]} for chart in data["charts"]]

    def test_totals_add_up_over_the_lines(self):
        for channel in self.channels("Germany", 2) + self.channels("UK", 1) + self.channels(None, 1):
            self.post(channel, views=100, total_reactions=3)
            self.post(channel, views=50, total_reactions=0, date="2024-07-10T12:00:00Z")
        for name, expected in (
            ("messages-history-data", {"Germany": [2, 0, 2], "UK": [1, 0, 1], "No Nation label": [1, 0, 1]}),
            ("views-history-data", {"Germany": [200, 0, 100], "UK": [100, 0, 50], "No Nation label": [100, 0, 50]}),
            ("active-channels-history-data", {"Germany": [2, 0, 2], "UK": [1, 0, 1], "No Nation label": [1, 0, 1]}),
            ("reactions-history-data", {"Germany": [6, 0, 0], "UK": [3, 0, 0], "No Nation label": [3, 0, 0]}),
        ):
            with self.subTest(chart=name):
                data, (lines,) = self.charts(name)
                self.assertEqual(data["labels"], ["2024-05", "2024-06", "2024-07"])
                self.assertEqual(data["split"], "Nation")
                self.assertEqual(lines, expected)

    def test_the_most_active_labels_get_a_line_the_others_share_one(self):
        for n, nation in enumerate(("A", "B", "C", "D", "E", "F", "G")):
            for channel in self.channels(nation, 7 - n):
                self.post(channel)
        data, (lines,) = self.charts("messages-history-data")
        self.assertEqual(list(lines), ["A", "B", "C", "D", "E", "Other (2)"])
        self.assertEqual(lines["Other (2)"], [2 + 1])
        self.assertEqual([x["kind"] for x in data["charts"][0]["lines"]], ["label"] * 5 + ["other"])

    def test_every_chart_draws_the_same_lines(self):
        # Germany forwards only: it still has its line (empty) on the charts of own posts.
        source = make_channel(telegram_id=900, title="Source")
        for channel in self.channels("Germany", 5):
            self.post(channel, views=30, forwarded_from=source)
        for channel in self.channels("UK", 6):
            self.post(channel, views=100, total_reactions=1)
        for name in (
            "messages-history-data",
            "forwards-history-data",
            "avg-involvement-history-data",
            "own-forwarded-views-history-data",
            "reaction-rate-history-data",
        ):
            with self.subTest(chart=name):
                for chart in self.charts(name)[1]:
                    self.assertEqual(list(chart), ["UK", "Germany"])
        own, forwards = self.charts("own-forwarded-views-history-data")[1]
        self.assertEqual((own, forwards), ({"UK": [100], "Germany": [None]}, {"UK": [None], "Germany": [30]}))

    def test_medians_need_enough_active_channels(self):
        for channel, views in zip(self.channels("Germany", 5), (10, 20, 30, 40, 5000), strict=True):
            self.post(channel, views=views)
        for channel in self.channels("UK", 4):
            self.post(channel, views=100)
        data, (lines,) = self.charts("avg-involvement-history-data")
        self.assertEqual(lines, {"Germany": [30], "UK": [None]})
        self.assertEqual(data["y_label"], "median channel's views per post")

    def test_median_is_over_channels_not_days(self):
        channels = self.channels("Germany", 5)
        for day in range(1, 9):  # one channel posting on eight days counts once
            self.post(channels[0], views=1000, date=f"2024-05-{day:02d}T12:00:00Z")
        for channel in channels[1:]:
            self.post(channel, views=10)
        self.assertEqual(self.charts("avg-involvement-history-data")[1][0]["Germany"], [10])

    def test_reaction_rate_counts_an_album_once(self):
        for channel in self.channels("Germany", 5):
            for views, reactions in ((480, 20), (500, 0)):
                self.post(channel, views=views, total_reactions=reactions, grouped_id=77)
        data, (lines,) = self.charts("reaction-rate-history-data")
        self.assertEqual(lines, {"Germany": [40]})

    def test_label_is_read_at_the_posts_date(self):
        (channel,) = self.channels(None, 1)
        attribute(channel, self.label("Germany"), end="2024-05-31")
        attribute(channel, self.label("UK"), start="2024-06-01")
        self.post(channel)
        self.post(channel, date="2024-06-10T12:00:00Z")
        self.assertEqual(self.charts("messages-history-data")[1], [{"Germany": [1, 0], "UK": [0, 1]}])

    def test_container_group_splits_through_the_child_labels(self):
        continents = LabelGroup.objects.create(name="Continent", is_partition=True, is_container=True)
        europe = make_label(name="Europe", group=continents, is_in_target=False)
        LabelParent.objects.create(label=self.label("Germany"), parent=europe)
        for channel in self.channels("Germany", 2) + self.channels("USA", 1):
            self.post(channel)
        data, (lines,) = self.charts("messages-history-data", split=continents.pk)
        self.assertEqual(lines, {"Europe": [2], "No Continent label": [1]})

    def test_scope_and_split_combine(self):
        for nation, n in (("Germany", 2), ("UK", 1)):
            for channel in self.channels(nation, n):
                self.post(channel)
        _, (lines,) = self.charts("messages-history-data", filter=self.label("Germany").pk)
        self.assertEqual(lines, {"Germany": [2]})

    def test_without_split_the_charts_are_unchanged(self):
        self.post(self.channels("Germany", 1)[0], views=10)
        for value in ("", "x", "999999"):
            data = json.loads(self.client.get(reverse("messages-history-data"), {"split": value}).content)
            self.assertNotIn("charts", data)
            self.assertEqual(data["values"], [1])

    def test_empty_database(self):
        data = json.loads(self.client.get(reverse("messages-history-data"), {"split": self.nation.pk}).content)
        self.assertEqual((data["labels"], data["values"]), ([], []))


class _ChannelTwoLinesChartMixin(_TwoLinesChartMixin):
    def url(self):
        return reverse(self.url_name, kwargs={"pk": self.channel.pk})

    def test_unknown_channel_returns_404(self):
        self.assertEqual(self.client.get(reverse(self.url_name, kwargs={"pk": 999})).status_code, 404)

    def test_only_this_channels_posts_in_its_in_target_periods_count(self):
        bounded = make_channel(telegram_id=2, title="C2")
        attribute(bounded, self.org, start="2024-06-01")
        self.post(bounded, views=1000, total_reactions=90)  # before its period
        self.post(bounded, views=1000, total_reactions=10, date="2024-06-10T12:00:00Z")
        self.post(views=5000, total_reactions=5000)
        self.channel = bounded
        labels, values, _extra = self.lines()
        self.assertEqual(labels, ["2024-05", "2024-06"])
        self.assertIsNone(values[0])
        self.assertEqual(values[1], {"channel-reaction-rate-history": 10}.get(self.url_name, 1000))


class ChannelOwnForwardedViewsHistoryTests(_ChannelTwoLinesChartMixin, TestCase):
    url_name = "channel-own-forwarded-views-history"

    def test_mean_of_each_kind(self):
        source = make_channel(telegram_id=9, title="Source")
        for views in (100, 200, 600):
            self.post(views=views)
        self.post(views=30, forwarded_from=source)
        self.post(views=51, fwd_from_from_name="Hidden user")
        self.assertEqual(self.lines(), (["2024-05"], [300], [40.5]))


class ChannelReactionRateHistoryTests(_ChannelTwoLinesChartMixin, TestCase):
    url_name = "channel-reaction-rate-history"

    def test_rate_of_all_posts_and_of_the_median_post(self):
        self.post(views=1000, total_reactions=10)
        self.post(views=100, total_reactions=3)
        for views, reactions in ((450, 100), (500, 0)):  # an album: one post, 100 / 500
            self.post(views=views, total_reactions=reactions, grouped_id=77)
        self.assertEqual(self.lines(), (["2024-05"], [70.6], [30]))


class HomeFilterScopeTests(TestCase):
    """``?filter=<container label>`` scopes the global time-series endpoints.

    The scope is the channels holding a label assigned under the voice — and
    nothing else: container labels are never channel-linked, so a stray direct
    attribution predating the container flag must not count either.
    """

    def setUp(self):
        continents = LabelGroup.objects.create(name="Continents", is_container=True)
        self.europe = make_label(name="Europe", group=continents, is_in_target=False)
        org_a = make_label(name="OrgA", is_in_target=True)
        org_b = make_label(name="OrgB", is_in_target=True)
        org_c = make_label(name="OrgC", is_in_target=True)
        LabelParent.objects.create(label=org_a, parent=self.europe)
        child_holder = make_channel(telegram_id=1, title="Child", label=org_a)
        outsider = make_channel(telegram_id=2, title="Outside", label=org_b)
        direct_holder = make_channel(telegram_id=3, title="Direct", label=org_c)
        attribute(direct_holder, self.europe)  # .create() bypasses clean() — simulates a pre-container row
        Message.objects.create(telegram_id=1, channel=child_holder, date="2024-01-10T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=outsider, date="2024-01-15T00:00:00Z")
        Message.objects.create(telegram_id=3, channel=direct_holder, date="2024-01-20T00:00:00Z")

    def test_scoped_to_voice_counts_child_label_holders_only(self):
        response = self.client.get(reverse("messages-history-data"), {"filter": self.europe.pk})
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-01"])
        self.assertEqual(data["values"], [1])

    def test_without_filter_counts_all(self):
        response = self.client.get(reverse("messages-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["values"], [3])

    def test_unknown_filter_value_is_ignored(self):
        response = self.client.get(reverse("messages-history-data"), {"filter": "nonsense"})
        data = json.loads(response.content)
        self.assertEqual(data["values"], [3])


# ---------------------------------------------------------------------------
# Channel-specific time-series views
# ---------------------------------------------------------------------------


class ChannelMessagesHistoryViewTests(TestCase):
    def setUp(self):
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=org)

    def test_unknown_channel_returns_404(self):
        response = self.client.get(reverse("channel-messages-history", kwargs={"pk": 999}))
        self.assertEqual(response.status_code, 404)

    def test_channel_without_messages_returns_empty_response(self):
        response = self.client.get(reverse("channel-messages-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "messages")

    def test_counts_messages_per_month(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-04-05T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-04-20T00:00:00Z")
        response = self.client.get(reverse("channel-messages-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-04"])
        self.assertEqual(data["values"], [2])

    def test_fills_empty_months_with_zero(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-01-01T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-03-01T00:00:00Z")
        response = self.client.get(reverse("channel-messages-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(data["values"], [1, 0, 1])


class ChannelViewsHistoryViewTests(TestCase):
    def setUp(self):
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=org)

    def test_unknown_channel_returns_404(self):
        response = self.client.get(reverse("channel-views-history", kwargs={"pk": 999}))
        self.assertEqual(response.status_code, 404)

    def test_channel_without_messages_returns_empty_response(self):
        response = self.client.get(reverse("channel-views-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "views")

    def test_sums_views_per_month(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-06-01T00:00:00Z", views=50)
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-06-15T00:00:00Z", views=150)
        response = self.client.get(reverse("channel-views-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-06"])
        self.assertEqual(data["values"], [200])

    def test_message_without_views_excluded_from_sum_but_not_spine(self):
        # The spine is built from all messages with dates; messages without views are excluded
        # from the views query, so the month appears in labels with value 0.
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-06-01T00:00:00Z", views=None)
        response = self.client.get(reverse("channel-views-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-06"])
        self.assertEqual(data["values"], [0])


class ChannelForwardsHistoryViewTests(TestCase):
    def setUp(self):
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=org)
        self.source = make_channel(telegram_id=2, title="C2", label=org)

    def test_unknown_channel_returns_404(self):
        response = self.client.get(reverse("channel-forwards-history", kwargs={"pk": 999}))
        self.assertEqual(response.status_code, 404)

    def test_channel_without_forwards_returns_empty_response(self):
        response = self.client.get(reverse("channel-forwards-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "forwards sent")

    def test_counts_only_forwarded_messages(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-07-01T00:00:00Z")
        Message.objects.create(
            telegram_id=2, channel=self.channel, date="2024-07-10T00:00:00Z", forwarded_from=self.source
        )
        response = self.client.get(reverse("channel-forwards-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-07"])
        self.assertEqual(data["values"], [1])

    def test_fills_empty_months_with_zero(self):
        Message.objects.create(
            telegram_id=1, channel=self.channel, date="2024-01-01T00:00:00Z", forwarded_from=self.source
        )
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-03-01T00:00:00Z")
        response = self.client.get(reverse("channel-forwards-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(data["values"], [1, 0, 0])


class ChannelForwardsReceivedHistoryViewTests(TestCase):
    def setUp(self):
        self.org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=self.org)
        self.forwarder = make_channel(telegram_id=2, title="C2", label=self.org)

    def test_unknown_channel_returns_404(self):
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": 999}))
        self.assertEqual(response.status_code, 404)

    def test_no_forwards_returns_empty_response(self):
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "forwards received")

    def test_counts_forwards_from_in_target_channels(self):
        # The spine is built from the target channel's own messages, so it needs at least one.
        Message.objects.create(telegram_id=10, channel=self.channel, date="2024-08-01T00:00:00Z")
        Message.objects.create(
            telegram_id=1, channel=self.forwarder, date="2024-08-01T00:00:00Z", forwarded_from=self.channel
        )
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-08"])
        self.assertEqual(data["values"], [1])

    def test_excludes_forwards_from_out_of_target_channels(self):
        non_org = make_label(name="Non", is_in_target=False)
        non_forwarder = make_channel(telegram_id=3, title="C3", label=non_org)
        Message.objects.create(
            telegram_id=1, channel=non_forwarder, date="2024-08-01T00:00:00Z", forwarded_from=self.channel
        )
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])


class ChannelAvgInvolvementHistoryViewTests(TestCase):
    def setUp(self):
        org = make_label(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, title="C1", label=org)

    def test_unknown_channel_returns_404(self):
        response = self.client.get(reverse("channel-avg-involvement-history", kwargs={"pk": 999}))
        self.assertEqual(response.status_code, 404)

    def test_channel_without_messages_returns_empty_response(self):
        response = self.client.get(reverse("channel-avg-involvement-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "avg views")

    def test_averages_views_per_month_rounded(self):
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-09-01T00:00:00Z", views=100)
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-09-15T00:00:00Z", views=200)
        Message.objects.create(telegram_id=3, channel=self.channel, date="2024-09-20T00:00:00Z", views=333)
        response = self.client.get(reverse("channel-avg-involvement-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-09"])
        self.assertEqual(data["values"], [round((100 + 200 + 333) / 3)])

    def test_null_views_excluded_from_average(self):
        # Avg(..., default=0) only applies when there are no rows at all; null views
        # are excluded from the average, so only messages with actual view counts contribute.
        Message.objects.create(telegram_id=1, channel=self.channel, date="2024-09-01T00:00:00Z", views=None)
        Message.objects.create(telegram_id=2, channel=self.channel, date="2024-09-15T00:00:00Z", views=100)
        response = self.client.get(reverse("channel-avg-involvement-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-09"])
        self.assertEqual(data["values"], [100])

    def test_median_post_beside_the_mean(self):
        for n, (date, views) in enumerate(
            (("2024-09-02", 10), ("2024-09-03", 20), ("2024-09-04", 3000), ("2024-11-02", None), ("2024-11-03", 7))
        ):
            Message.objects.create(telegram_id=n, channel=self.channel, date=f"{date}T12:00:00Z", views=views)
        response = self.client.get(reverse("channel-avg-involvement-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["values_label"], "mean of all posts")
        self.assertEqual(data["values"], [1010, 0, 7])
        self.assertEqual(data["extra_lines"], [{"label": "median post", "values": [20, None, 7]}])
