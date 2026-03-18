from django.test import TestCase
from django.urls import reverse

from webapp.models import Channel, Message, Organization


class StatsViewsTests(TestCase):
    def test_messages_history_data_renders_bokeh_html(self):
        organization = Organization.objects.create(name="Interesting Org", is_interesting=True)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=organization)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-20T00:00:00Z")

        response = self.client.get(reverse("messages-history-data"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertContains(response, "Bokeh")
        self.assertContains(response, "Messages history")

    def test_active_channels_history_data_renders_bokeh_html(self):
        organization = Organization.objects.create(name="Interesting Org", is_interesting=True)
        channel1 = Channel.objects.create(telegram_id=1, title="C1", organization=organization)
        channel2 = Channel.objects.create(telegram_id=2, title="C2", organization=organization)
        Message.objects.create(telegram_id=1, channel=channel1, date="2024-01-20T00:00:00Z")
        Message.objects.create(telegram_id=2, channel=channel2, date="2024-01-22T00:00:00Z")

        response = self.client.get(reverse("active-channels-history-data"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertContains(response, "Bokeh")
        self.assertContains(response, "active channels")
