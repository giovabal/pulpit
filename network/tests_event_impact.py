"""Tests of the event-impact interrupted time series (network.event_impact) and of the event label scope."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from events.models import Event, EventType
from network import event_impact
from network.event_impact import _fit_at, _nw_lag, _ols_hac, compute_event_impact
from network.graph_builder import build_graph
from webapp.models import Message
from webapp.test_helpers import attribute, label_group, make_channel, make_label

import numpy as np

START = datetime.datetime(2024, 1, 1, 12, tzinfo=datetime.UTC)  # a Monday


class OlsHacTests(TestCase):
    def test_matches_a_direct_newey_west(self) -> None:
        rng = np.random.default_rng(0)
        n = 40
        x = np.column_stack([np.ones(n), np.arange(n), (np.arange(n) >= 20).astype(float)])
        y = 1 + 0.1 * np.arange(n) + 2 * x[:, 2] + rng.normal(size=n)
        beta, se = _ols_hac(x, y, np.zeros(n))
        # Reference: the textbook Bartlett-kernel sandwich, written out with loops.
        resid = y - x @ beta
        lag = _nw_lag(n)
        s = sum(np.outer(x[t] * resid[t], x[t] * resid[t]) for t in range(n))
        for k in range(1, lag + 1):
            w = 1 - k / (lag + 1)
            for t in range(k, n):
                g = np.outer(x[t] * resid[t], x[t - k] * resid[t - k])
                s = s + w * (g + g.T)
        inv = np.linalg.inv(x.T @ x)
        np.testing.assert_allclose(se, np.sqrt(np.diag(inv @ s @ inv)), rtol=1e-10)
        self.assertAlmostEqual(beta[2], 2.0, delta=1.0)

    def test_recovers_a_planted_level_and_slope_change(self) -> None:
        rng = np.random.default_rng(1)
        t = np.arange(60)
        y = 0.3 + 0.001 * t + 0.2 * (t >= 30) + 0.005 * (t - 30) * (t >= 30) + rng.normal(scale=0.01, size=60)
        fit = _fit_at(30, 26, {"network": y}, "share")
        self.assertAlmostEqual(fit["level"][0], 0.2, delta=0.02)
        self.assertAlmostEqual(fit["slope"][0], 0.005, delta=0.002)
        self.assertEqual((fit["n_pre"], fit["n_post"]), (26, 26))

    def test_comparative_design_isolates_the_affected_group(self) -> None:
        rng = np.random.default_rng(2)
        t = np.arange(60)
        trend = 0.4 + 0.002 * t
        shock = 0.1 * (t >= 30)  # a movement-wide shift both groups share …
        affected = trend + shock + 0.15 * (t >= 30) + rng.normal(scale=0.005, size=60)  # … plus the event's own
        comparison = trend + shock + rng.normal(scale=0.005, size=60)
        fit = _fit_at(30, 26, {"affected": affected, "comparison": comparison}, "share")
        self.assertAlmostEqual(fit["level"][0], 0.15, delta=0.02)

    def test_too_few_weeks_is_insufficient(self) -> None:
        y = np.full(60, np.nan)
        y[25:35] = 1.0
        self.assertIsNone(_fit_at(30, 26, {"network": y}, "share"))


@override_settings(TIME_ZONE="UTC")
class ComputeEventImpactTests(TestCase):
    def setUp(self) -> None:
        self.nation = label_group("Nation", is_primary=False)
        org = make_label("Org")
        self.italy, self.france = make_label("Italy", group=self.nation), make_label("France", group=self.nation)
        self.channels = []
        for i in range(4):
            channel = make_channel(telegram_id=i + 1, label=org, title=f"C{i}")
            attribute(channel, self.italy if i < 2 else self.france)
            self.channels.append(channel)
        self.event_type = EventType.objects.create(name="Ban", color="#aa0000")
        self._telegram_id = 1000

    def _post(self, channel, week: int, count: int, source=None) -> None:
        for k in range(count):
            self._telegram_id += 1
            Message.objects.create(
                telegram_id=self._telegram_id,
                channel=channel,
                forwarded_from=source,
                date=START + datetime.timedelta(weeks=week, hours=k),
            )

    def _history(self, after_italy: int, after_france: int, weeks: int = 120, break_week: int = 60) -> None:
        rng = np.random.default_rng(3)
        for week in range(weeks):
            for i, channel in enumerate(self.channels):
                base = 3 + int(rng.integers(0, 2))
                boost = (after_italy if i < 2 else after_france) if week >= break_week else 0
                self._post(channel, week, base + boost)
                # A forward every week keeps the in-scope citation graph connected.
                self._post(channel, week, 1, source=self.channels[(i + 1) % 4])
        for channel in self.channels:
            channel.save()

    def _event(self, week: int, subject: str, labels=()) -> Event:
        event = Event.objects.create(
            date=(START + datetime.timedelta(weeks=week)).date(), subject=subject, action=self.event_type
        )
        event.labels.set(labels)
        return event

    def _metric(self, payload, subject: str, key: str) -> dict:
        event = next(e for e in payload["events"] if e["subject"] == subject)
        return next(m for m in event["metrics"] if m["key"] == key)

    def test_unscoped_break_has_a_small_placebo_p(self) -> None:
        self._history(after_italy=6, after_france=6)
        self._event(60, "Crackdown")
        graph, *_ = build_graph()
        payload = compute_event_impact(graph, window_weeks=26)
        messages = self._metric(payload, "Crackdown", "messages")
        self.assertFalse(messages["insufficient"])
        self.assertGreater(messages["level"]["coef"], 0.3)  # log(1 + 2·(4+6+1)) vs log(1 + 2·(4+1)) … well above 0
        self.assertLess(messages["level"]["p_placebo"], 0.05)
        self.assertIsNotNone(messages["level"]["q"])
        self.assertGreater(messages["placebos"], 19)

    def test_no_break_gives_no_effect(self) -> None:
        self._history(after_italy=0, after_france=0)
        self._event(60, "Nothing happened")
        graph, *_ = build_graph()
        payload = compute_event_impact(graph, window_weeks=26)
        messages = self._metric(payload, "Nothing happened", "messages")
        self.assertGreater(messages["level"]["p_placebo"], 0.05)

    def test_scoped_event_compares_affected_with_the_rest(self) -> None:
        self._history(after_italy=6, after_france=0)
        self._event(60, "Italian ban", labels=[self.italy])
        graph, *_ = build_graph()
        payload = compute_event_impact(graph, window_weeks=26)
        event = next(e for e in payload["events"] if e["subject"] == "Italian ban")
        self.assertEqual(event["design"], "comparative")
        self.assertEqual(event["labels"], ["Nation: Italy"])
        messages = self._metric(payload, "Italian ban", "messages")
        self.assertGreater(messages["level"]["coef"], 0.3)
        self.assertIn("observed_affected", messages)
        self.assertIn("fit_comparison", messages)

    def test_close_events_are_flagged_as_confounded(self) -> None:
        self._history(after_italy=0, after_france=0)
        self._event(60, "First")
        self._event(70, "Second")
        graph, *_ = build_graph()
        payload = compute_event_impact(graph, window_weeks=26)
        first = next(e for e in payload["events"] if e["subject"] == "First")
        self.assertEqual(first["confounded_by"], ["Second"])
        rows = event_impact.effect_rows(payload)
        self.assertTrue(rows and all(len(r) == len(event_impact.EFFECT_COLUMNS) for r in rows))
        header, series = event_impact.series_rows(payload)
        self.assertEqual(len(series), len(payload["weeks"]))
        self.assertEqual(header[0], "week")

    def test_timeline_events_carry_the_period_key(self) -> None:
        from network.periods import build_periods

        self._event(10, "Early", labels=[self.france])
        timeline = build_periods("quarter", None, datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
        (event,) = event_impact.timeline_events(timeline, "quarter")
        self.assertEqual(event["period_key"], "2024Q1")
        self.assertEqual(event["labels"], ["Nation: France"])


class EventScopeApiTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("staff@example.org", password="x", is_staff=True)
        self.client.force_login(self.user)
        group = label_group("Nation", is_primary=False)
        self.germany = make_label("Germany", group=group)
        self.event_type = EventType.objects.create(name="Ban")

    def test_create_and_patch_label_scope(self) -> None:
        url = "/manage/api/events/"
        resp = self.client.post(
            url,
            {
                "date": "2025-03-01",
                "subject": "German ban",
                "action_id": self.event_type.pk,
                "label_ids": [self.germany.pk],
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["label_ids"], [self.germany.pk])
        self.assertEqual(body["labels"][0]["group"], "Nation")
        detail = f"/manage/api/events/{body['id']}/"
        resp = self.client.patch(detail, {"label_ids": []}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["labels"], [])
        self.assertEqual(Event.objects.get(pk=body["id"]).labels.count(), 0)
