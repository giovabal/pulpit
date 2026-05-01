import json

from django.test import TestCase
from django.urls import reverse

from stats.queries import (
    channel_month_spine as _channel_month_spine,
    global_month_spine as _global_month_spine,
    reindex_to_spine as _reindex_to_spine,
)
from webapp.models import Channel, Message, Organization

import pandas as pd


class StatsViewsTests(TestCase):
    def test_messages_history_data_returns_json(self):
        organization = Organization.objects.create(name="Interesting Org", is_interesting=True)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=organization)
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
        organization = Organization.objects.create(name="Interesting Org", is_interesting=True)
        channel1 = Channel.objects.create(telegram_id=1, title="C1", organization=organization)
        channel2 = Channel.objects.create(telegram_id=2, title="C2", organization=organization)
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
        org = Organization.objects.create(name="Org", is_interesting=True)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-03-15T00:00:00Z")
        self.assertEqual(_global_month_spine(), ["2024-03"])

    def test_multi_month_span_fills_intermediate_months(self):
        org = Organization.objects.create(name="Org", is_interesting=True)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-01T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=channel, date="2024-03-01T00:00:00Z")
        self.assertEqual(_global_month_spine(), ["2024-01", "2024-02", "2024-03"])

    def test_ignores_non_interesting_channels(self):
        org = Organization.objects.create(name="Org", is_interesting=False)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-01T00:00:00Z")
        self.assertEqual(_global_month_spine(), [])

    def test_ignores_messages_without_date(self):
        org = Organization.objects.create(name="Org", is_interesting=True)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)
        Message.objects.create(telegram_id=1, channel=channel, date=None)
        self.assertEqual(_global_month_spine(), [])


class ChannelMonthSpineTests(TestCase):
    def setUp(self):
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)

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
        result = _reindex_to_spine(df, "count", ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(list(result["month"]), ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(list(result["count"]), [5, 0, 3])

    def test_preserves_existing_values(self):
        df = pd.DataFrame({"month": ["2024-01"], "val": [42]})
        result = _reindex_to_spine(df, "val", ["2024-01"])
        self.assertEqual(list(result["val"]), [42])

    def test_all_months_missing_fills_all_zeros(self):
        df = pd.DataFrame({"month": [], "val": []})
        result = _reindex_to_spine(df, "val", ["2024-01", "2024-02"])
        self.assertEqual(list(result["val"]), [0, 0])


# ---------------------------------------------------------------------------
# Global time-series views
# ---------------------------------------------------------------------------


class ForwardsHistoryDataViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=self.org)
        self.source = Channel.objects.create(telegram_id=2, title="C2", organization=self.org)

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

    def test_excludes_non_interesting_channels(self):
        non_org = Organization.objects.create(name="Non", is_interesting=False)
        non_channel = Channel.objects.create(telegram_id=3, title="C3", organization=non_org)
        Message.objects.create(
            telegram_id=1, channel=non_channel, date="2024-01-15T00:00:00Z", forwarded_from=self.source
        )
        response = self.client.get(reverse("forwards-history-data"))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])


class ViewsHistoryDataViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=self.org)

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
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=self.org)

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


# ---------------------------------------------------------------------------
# Channel-specific time-series views
# ---------------------------------------------------------------------------


class ChannelMessagesHistoryViewTests(TestCase):
    def setUp(self):
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)

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
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)

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
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)
        self.source = Channel.objects.create(telegram_id=2, title="C2", organization=org)

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
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=self.org)
        self.forwarder = Channel.objects.create(telegram_id=2, title="C2", organization=self.org)

    def test_unknown_channel_returns_404(self):
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": 999}))
        self.assertEqual(response.status_code, 404)

    def test_no_forwards_returns_empty_response(self):
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])
        self.assertEqual(data["y_label"], "forwards received")

    def test_counts_forwards_from_interesting_channels(self):
        # The spine is built from the target channel's own messages, so it needs at least one.
        Message.objects.create(telegram_id=10, channel=self.channel, date="2024-08-01T00:00:00Z")
        Message.objects.create(
            telegram_id=1, channel=self.forwarder, date="2024-08-01T00:00:00Z", forwarded_from=self.channel
        )
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], ["2024-08"])
        self.assertEqual(data["values"], [1])

    def test_excludes_forwards_from_non_interesting_channels(self):
        non_org = Organization.objects.create(name="Non", is_interesting=False)
        non_forwarder = Channel.objects.create(telegram_id=3, title="C3", organization=non_org)
        Message.objects.create(
            telegram_id=1, channel=non_forwarder, date="2024-08-01T00:00:00Z", forwarded_from=self.channel
        )
        response = self.client.get(reverse("channel-forwards-received-history", kwargs={"pk": self.channel.pk}))
        data = json.loads(response.content)
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["values"], [])


class ChannelAvgInvolvementHistoryViewTests(TestCase):
    def setUp(self):
        org = Organization.objects.create(name="Org", is_interesting=True)
        self.channel = Channel.objects.create(telegram_id=1, title="C1", organization=org)

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
