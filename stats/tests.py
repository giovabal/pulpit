import json

from django.test import TestCase
from django.urls import reverse

from webapp.models import Channel, Message, Organization


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
