from django.test import TestCase
from django.urls import reverse

from webapp.models import Channel, Message, Organization


class StatsViewsTests(TestCase):
    def test_stats_page_contains_iframe(self):
        response = self.client.get(reverse("stats-page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("messages-history-data"))

    def test_messages_history_data_renders_bokeh_html(self):
        organization = Organization.objects.create(name="Interesting Org", is_interesting=True)
        channel = Channel.objects.create(telegram_id=1, title="C1", organization=organization)
        Message.objects.create(telegram_id=1, channel=channel, date="2024-01-20T00:00:00Z")

        response = self.client.get(reverse("messages-history-data"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertContains(response, "Bokeh")
        self.assertContains(response, "Monthly total messages from interesting channels")
