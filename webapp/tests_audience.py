"""The Audience page (webapp/audience/): participation inequality, breadth, audience overlap, retention and
channels as commenters — their statistics, pages and CSVs — and the subscriber history."""

import csv
import datetime
import io
import itertools
import random

from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from webapp import audience, commenters
from webapp.audience.breadth import hill_one, rarefaction
from webapp.audience.channel_commenters import MARKED_CHANNEL_OFFSET, channel_telegram_id
from webapp.audience.overlap import (
    _elementary,
    _without_one,
    citation_counts,
    fit_fixed_size_weights,
    overlap_pairs,
    qap_correlation,
)
from webapp.models import ChannelSubscriberCount, LabelGroup, LabelParent, Message, MessageReply
from webapp.test_helpers import attribute, make_channel, make_label

import numpy as np

_DATE = datetime.datetime(2024, 5, 1, 12, 0, tzinfo=datetime.timezone.utc)


def _naive_medcouple(values: list[float]) -> float:
    """The medcouple straight from its definition (Brys, Hubert & Struyf 2004), pair by pair."""
    x = sorted(values)
    m = float(np.median(x))
    upper = sorted((v for v in x if v >= m), reverse=True)
    lower = sorted((v for v in x if v <= m), reverse=True)
    k = sum(1 for v in x if v == m)
    # The tied observations sit at the end of `upper` and the start of `lower`; number them 0..k-1.
    first_tie_up = len(upper) - k
    kernel = []
    for i, u in enumerate(upper):
        for j, low in enumerate(lower):
            if u == low == m:
                kernel.append(float(np.sign(k - 1 - (i - first_tie_up) - j)))
            else:
                kernel.append(((u - m) - (m - low)) / (u - low))
    return float(np.median(kernel))


class MeasureTests(TestCase):
    def test_gini(self) -> None:
        self.assertEqual(audience.gini([5, 5, 5, 5]), 0.0)
        # One account writes everything: raw Gini (n−1)/n, corrected to 1.
        self.assertAlmostEqual(audience.gini([0, 0, 0, 12]), 1.0)
        # [1, 3]: raw Gini 0.25, × n/(n−1) = 0.5.
        self.assertAlmostEqual(audience.gini([1, 3]), 0.5)
        self.assertIsNone(audience.gini([4]))

    def test_top_share_takes_the_ceiling_of_p_n(self) -> None:
        counts = [1] * 9 + [11]  # 10 accounts, 20 replies
        self.assertAlmostEqual(audience.top_share(counts, 0.10), 11 / 20)
        self.assertAlmostEqual(audience.top_share(counts, 0.01), 11 / 20)  # ⌈0.1⌉ = 1 account
        self.assertAlmostEqual(audience.top_share(counts, 0.15), 12 / 20)  # ⌈1.5⌉ = 2 accounts

    def test_effective_number(self) -> None:
        self.assertAlmostEqual(audience.effective_number([3, 3, 3]), 3.0)
        self.assertAlmostEqual(audience.effective_number([1, 1, 2]), 1 / (0.25**2 * 2 + 0.5**2))

    def test_medcouple_matches_the_definition(self) -> None:
        rng = random.Random(7)
        pool = [1, 1, 1, 2, 2, 3, 4, 5, 8, 13, 40]
        for _ in range(300):
            values = [rng.choice(pool) for _ in range(rng.randint(1, 30))]
            self.assertAlmostEqual(audience.medcouple(values), _naive_medcouple(values), msg=values)

    def test_medcouple_known_values(self) -> None:
        self.assertEqual(audience.medcouple([1, 2, 3, 4, 5]), 0.0)  # symmetric
        self.assertGreater(audience.medcouple([1, 1, 1, 2, 2, 3, 9, 30]), 0)  # right-skewed
        self.assertLess(audience.medcouple([-30, -9, -3, -2, -2, -1, -1, -1]), 0)

    def test_adjusted_fences_widen_the_upper_whisker_on_right_skew(self) -> None:
        values = [1] * 50 + [2] * 20 + [3] * 10 + [5] * 8 + [10] * 6 + [40] * 3
        fences = audience.adjusted_fences(values)
        q1, q3 = np.percentile(values, [25, 75])
        self.assertGreater(fences["medcouple"], 0)
        self.assertAlmostEqual(fences["upper"], q3 + 1.5 * np.exp(3 * fences["medcouple"]) * (q3 - q1))
        self.assertGreater(fences["upper"], q3 + 1.5 * (q3 - q1))  # wider than Tukey's

    def test_lorenz_points_run_from_origin_to_one(self) -> None:
        points = audience.lorenz_points([1, 1, 2, 6])
        self.assertEqual(points[0], [0.0, 0.0])
        self.assertEqual(points[-1], [1.0, 1.0])
        self.assertEqual(points[2], [0.5, 0.2])  # the two one-reply accounts wrote 2 of 10
        self.assertLessEqual(len(audience.lorenz_points(list(range(1, 1000)), max_points=50)), 51)

    def test_activity_bins_cover_every_account(self) -> None:
        counts = [1, 1, 2, 4, 7, 30, 150]
        bins = audience.activity_bins(counts)
        self.assertEqual(sum(b["accounts"] for b in bins), len(counts))
        self.assertEqual(sum(b["replies"] for b in bins), sum(counts))
        self.assertEqual([b["label"] for b in bins][:3], ["1", "2", "3–5"])
        self.assertEqual(bins[-1]["label"], "101+")
        self.assertEqual(bins[-1]["accounts"], 1)


class _Corpus(TestCase):
    """In-target channels A (bounded in-target period) and B, one out-of-target channel."""

    def setUp(self) -> None:
        org = make_label("Org")
        self.a = make_channel(
            telegram_id=1,
            title="A",
            label=org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 12, 31),
            participants_count=200,
        )
        self.b = make_channel(telegram_id=2, title="B", label=org, participants_count=50)
        self.out = make_channel(telegram_id=3, title="Out", label=make_label("Other", is_in_target=False))
        self.post_a = Message.objects.create(channel=self.a, telegram_id=1, date=_DATE)
        self.old_a = Message.objects.create(channel=self.a, telegram_id=2, date=_DATE.replace(year=2022))
        self.post_b = Message.objects.create(channel=self.b, telegram_id=1, date=_DATE)
        self.post_out = Message.objects.create(channel=self.out, telegram_id=1, date=_DATE)
        self._ids = itertools.count(1)

    def reply(self, post: Message, sender_id: int, n: int = 1) -> None:
        MessageReply.objects.bulk_create(
            MessageReply(parent_message=post, telegram_id=next(self._ids), date=_DATE, text="hi", sender_id=sender_id)
            for _ in range(n)
        )


class ParticipationTests(_Corpus):
    def test_scope_is_in_target_channels_inside_their_periods_without_left_out_accounts(self) -> None:
        self.reply(self.post_a, 10, n=3)
        self.reply(self.post_b, 10)
        self.reply(self.post_b, 11)
        self.reply(self.old_a, 12)  # before A's in-target period
        self.reply(self.post_out, 13)  # out-of-target channel
        self.reply(self.post_b, -1005)  # a channel posting as itself
        self.reply(self.post_b, 14, n=commenters.BULK_THREAD_COMMENTS)  # bulk poster

        data = audience.participation()
        self.assertEqual((data["overall"]["accounts"], data["overall"]["replies"]), (2, 5))
        self.assertEqual(data["left_out_accounts"], 1)
        self.assertEqual((data["scope_channels"], data["channels_with_comments"]), (2, 2))
        rows = {row["channel_id"]: row for row in data["channels"]}
        self.assertEqual((rows[self.a.pk]["accounts"], rows[self.a.pk]["replies"]), (1, 3))
        self.assertEqual(rows[self.b.pk]["commenter_rate"], 2 / 50)
        self.assertIsNone(rows[self.b.pk]["gini"])  # below MIN_CONCENTRATION_COMMENTERS

    def test_concentration_needs_enough_commenters(self) -> None:
        for sender in range(audience.MIN_CONCENTRATION_COMMENTERS):
            self.reply(self.post_b, 100 + sender)
        row = audience.participation()["channels"][0]
        self.assertAlmostEqual(row["gini"], 0.0)
        self.assertAlmostEqual(row["effective_number"], audience.MIN_CONCENTRATION_COMMENTERS)

    def test_hyperactive_accounts_are_the_adjusted_boxplot_outliers(self) -> None:
        for sender in range(30):
            self.reply(self.post_b, 100 + sender, n=1 + sender % 3)
        self.reply(self.post_a, 999, n=40)
        hyper = audience.participation()["overall"]["hyperactive"]
        self.assertEqual(hyper["accounts"], 1)
        self.assertGreater(hyper["min_replies"], hyper["fences"]["upper"])
        self.assertLessEqual(hyper["min_replies"], 40)
        rows = {row["channel_id"]: row for row in audience.participation()["channels"]}
        self.assertEqual(rows[self.a.pk]["hyperactive_reply_share"], 1.0)
        self.assertEqual(rows[self.b.pk]["hyperactive_reply_share"], 0.0)

    def test_scope_filter_limits_to_a_container_label(self) -> None:
        continents = LabelGroup.objects.create(name="Continent", is_partition=True, is_container=True)
        europe = make_label("Europe", is_in_target=False, group=continents)
        nation = make_label("Nation A", group=LabelGroup.objects.create(name="Nation", is_partition=True))
        LabelParent.objects.create(label=nation, parent=europe)
        attribute(self.b, nation)
        self.reply(self.post_a, 10)
        self.reply(self.post_b, 11)
        data = audience.participation(europe)
        self.assertEqual([row["channel_id"] for row in data["channels"]], [self.b.pk])

    def test_no_reply(self) -> None:
        data = audience.participation()
        self.assertEqual(data["overall"]["accounts"], 0)
        self.assertIsNone(data["overall"]["hyperactive"]["fences"])
        self.assertEqual(data["lorenz"], [])


class ParticipationPageTests(_Corpus):
    def test_page_renders_with_and_without_replies(self) -> None:
        resp = self.client.get(reverse("audience"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No reply in scope yet")
        self.reply(self.post_b, 10, n=2)
        self.reply(self.post_b, 11)
        resp = self.client.get(reverse("audience"))
        self.assertContains(resp, "Participation inequality")
        self.assertContains(resp, 'id="audience-chart-data"')
        self.assertContains(resp, 'href="/audience/"')  # the top-menu link

    def test_csv(self) -> None:
        self.reply(self.post_b, 10, n=2)
        self.reply(self.post_a, 11)
        resp = self.client.get(reverse("audience-csv", kwargs={"section": "participation"}))
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
        # One commenter each: the channel with more replies first.
        self.assertEqual([r["channel_title"] for r in rows], ["B", "A"])
        self.assertEqual((rows[0]["commenters"], rows[0]["replies"], rows[0]["gini"]), ("1", "2", ""))
        self.assertEqual(rows[1]["commenters_per_subscriber"], "0.005")


class NumberFilterTests(TestCase):
    def render(self, text: str, **context) -> str:
        return Template("{% load numbers %}" + text).render(Context(context))

    def test_filters(self) -> None:
        self.assertEqual(self.render("{{ v|pct }} {{ v|pct:1 }}", v=0.2573), "26% 25.7%")
        self.assertEqual(self.render("{{ v|thousands }}", v=13379), "13,379")
        self.assertEqual(self.render("{{ v|decimal:2 }}", v=0.6061), "0.61")
        self.assertEqual(self.render("{{ v|pct }}{{ v|thousands }}{{ v|decimal }}", v=None), "———")


# ── The other sections ───────────────────────────────────────────────────────


def _at(day: datetime.date, hour: int = 12) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, hour, 0, tzinfo=datetime.timezone.utc)


D0 = datetime.date(2024, 1, 10)


class _LabelledCorpus(TestCase):
    """Three in-target channels under two nations, each with one post; replies added per test."""

    def setUp(self) -> None:
        nation = LabelGroup.objects.create(name="Nation", is_partition=True)
        self.de = make_label("Germany", group=nation)
        self.it = make_label("Italy", group=nation)
        org = make_label("Org")
        self.a = make_channel(telegram_id=1, title="A", label=org, participants_count=100)
        self.b = make_channel(telegram_id=2, title="B", label=org, participants_count=50)
        self.c = make_channel(telegram_id=3, title="C", label=org, participants_count=10)
        for ch, nat in ((self.a, self.de), (self.b, self.de), (self.c, self.it)):
            attribute(ch, nat)
        self.posts = {
            ch.pk: Message.objects.create(channel=ch, telegram_id=1, date=_at(D0)) for ch in (self.a, self.b, self.c)
        }
        self._ids = itertools.count(1)

    def reply(
        self, channel, sender_id: int, n: int = 1, when: datetime.datetime | None = None, text: str = "hi", post=None
    ):
        MessageReply.objects.bulk_create(
            MessageReply(
                parent_message=post or self.posts[channel.pk],
                telegram_id=next(self._ids),
                date=when or _at(D0),
                text=text,
                sender_id=sender_id,
            )
            for _ in range(n)
        )


# ── Breadth ──────────────────────────────────────────────────────────────────


class RarefactionTests(TestCase):
    def test_known_values(self) -> None:
        self.assertAlmostEqual(rarefaction([5, 5], 1), 1.0)
        self.assertAlmostEqual(rarefaction([5, 5], 6), 2.0)  # 6 > 5: both must be drawn
        # Two draws from [1, 1]: always both.
        self.assertAlmostEqual(rarefaction([1, 1], 2), 2.0)
        # Two draws from [2, 2]: P(both from one) = 2 · C(2,2)/C(4,2) = 1/3 → E = 2 − 1/3.
        self.assertAlmostEqual(rarefaction([2, 2], 2), 2 - 1 / 3)

    def test_matches_simulation(self) -> None:
        totals = [30, 10, 5, 2]
        pool = [i for i, t in enumerate(totals) for _ in range(t)]
        rng = random.Random(3)
        simulated = np.mean([len(set(rng.sample(pool, 6))) for _ in range(20000)])
        self.assertAlmostEqual(rarefaction(totals, 6), simulated, delta=0.02)

    def test_hill_one(self) -> None:
        self.assertAlmostEqual(hill_one([5]), 1.0)
        self.assertAlmostEqual(hill_one([3, 3]), 2.0)


class BreadthTests(_LabelledCorpus):
    def test_channels_and_labels_per_account(self) -> None:
        self.reply(self.a, 10, n=3)
        self.reply(self.b, 10)  # 10: two German channels
        self.reply(self.a, 11)
        self.reply(self.c, 11)  # 11: Germany and Italy
        self.reply(self.c, 12)  # 12: one reply
        data = audience.breadth()
        self.assertEqual(data["accounts"], 3)
        self.assertAlmostEqual(data["multi_channel_share"], 2 / 3)
        spread = data["channel_spread"]
        self.assertEqual(spread["accounts"], 2)  # the one-reply account is left out
        self.assertAlmostEqual(spread["observed_mean"], 2.0)
        nation = next(g for g in data["groups"] if g["name"] == "Nation")
        self.assertAlmostEqual(nation["multi_label_share"], 0.5)  # 11 of {10, 11}
        germany = next(lab for lab in nation["labels"] if lab["name"] == "Germany")
        self.assertEqual((germany["commenters"], germany["replies"]), (2, 5))  # 3 + 1 by 10, 1 by 11
        self.assertAlmostEqual(germany["elsewhere_share"], 0.5)


# ── Audience overlap ─────────────────────────────────────────────────────────


class FixedSizeNullTests(TestCase):
    def _sample(self, lam: np.ndarray, k: int, rng) -> set[int]:
        """One draw of k units with P(S) ∝ Π λ: independent Bernoulli(λ/(1+λ)), kept when the size is k."""
        p = lam / (1 + lam)
        while True:
            chosen = set(np.nonzero(rng.random(len(lam)) < p)[0])
            if len(chosen) == k:
                return chosen

    def test_fit_reproduces_the_unit_degrees(self) -> None:
        degrees = np.array([40.0, 25.0, 12.0, 6.0])
        accounts = {1: 51, 2: 10, 3: 4}  # 51 + 2·10 + 3·4 = 83 = Σ degrees
        lam = fit_fixed_size_weights(degrees, accounts)
        e = _elementary(lam, 3)
        minus = _without_one(lam, e)
        expected = sum(n * lam * minus[:, k - 1] / e[k] for k, n in accounts.items())
        np.testing.assert_allclose(expected, degrees, rtol=1e-8)

    def test_expected_shared_matches_simulation(self) -> None:
        rng = np.random.default_rng(5)
        per_unit = {u: set() for u in range(4)}
        account = 0
        lam_true = np.array([3.0, 1.5, 0.6, 0.3])
        for k, count in ((1, 120), (2, 60), (3, 20)):
            for _ in range(count):
                for u in self._sample(lam_true, k, rng):
                    per_unit[u].add(account)
                account += 1
        result = overlap_pairs(per_unit)
        degrees = np.array([len(per_unit[u]) for u in result["units"]], dtype=float)
        lam = fit_fixed_size_weights(degrees, {1: 120, 2: 60, 3: 20})
        # Simulate the fitted null and compare the mean shared accounts of the first pair.
        units = result["units"]
        a, b = 0, 1
        shared = []
        for _ in range(400):
            pair = 0
            for k, count in ((2, 60), (3, 20)):
                for _ in range(count):
                    chosen = self._sample(lam, k, rng)
                    pair += a in chosen and b in chosen
            shared.append(pair)
        first = next(pr for pr in result["pairs"] if {pr["a"], pr["b"]} == {units[a], units[b]})
        self.assertAlmostEqual(first["expected"], np.mean(shared), delta=0.6)

    def test_one_channel_commenters_never_create_overlap(self) -> None:
        per_unit = {1: {1, 2, 3, 4}, 2: {5, 6, 7, 8}}
        pair = overlap_pairs(per_unit)["pairs"][0]
        self.assertEqual((pair["shared"], pair["expected"], pair["p"]), (0, 0.0, 1.0))

    def test_strong_overlap_is_significant(self) -> None:
        per_unit = {1: set(range(0, 30)), 2: set(range(0, 30)), 3: set(range(100, 160)), 4: set(range(200, 260))}
        for extra in range(30, 60):  # broaden: some two-channel accounts elsewhere
            per_unit[3].add(extra + 300)
            per_unit[4].add(extra + 300)
        pairs = {frozenset((pr["a"], pr["b"])): pr for pr in overlap_pairs(per_unit)["pairs"]}
        self.assertTrue(pairs[frozenset((1, 2))]["significant"])
        self.assertFalse(pairs[frozenset((1, 3))]["significant"])

    def test_qap_correlation(self) -> None:
        units = [1, 2, 3, 4, 5]
        shared = {
            frozenset(p): v
            for p, v in zip(itertools.combinations(units, 2), [9, 0, 0, 0, 7, 0, 0, 5, 0, 3], strict=True)
        }
        citations = dict(shared)
        result = qap_correlation(units, shared, citations)
        self.assertAlmostEqual(result["r"], 1.0)
        self.assertLess(result["p"], 0.05)


class OverlapSectionTests(_LabelledCorpus):
    def test_overlap_section(self) -> None:
        for sender in range(10, 20):
            self.reply(self.a, sender)
            self.reply(self.b, sender)
        self.reply(self.c, 30)
        Message.objects.create(channel=self.a, telegram_id=2, date=_at(D0), forwarded_from=self.b)
        data = audience.overlap()
        ab = next(pr for pr in data["pairs"] if {pr["a"], pr["b"]} == {self.a.pk, self.b.pk})
        self.assertEqual(ab["shared"], 10)
        self.assertEqual(len(data["channel_rows"]), 3)
        nation = next(g for g in data["label_groups"] if g["name"] == "Nation")
        self.assertEqual({lab["name"] for lab in nation["labels"]}, {"Germany", "Italy"})
        self.assertEqual(citation_counts([self.a.pk, self.b.pk])[frozenset((self.a.pk, self.b.pk))], 1)


# ── Retention ────────────────────────────────────────────────────────────────


class RetentionSectionTests(_LabelledCorpus):
    def test_monthly_cohorts_and_survival(self) -> None:
        self.reply(self.a, 10, when=_at(datetime.date(2024, 1, 5)))
        self.reply(self.a, 10, when=_at(datetime.date(2024, 4, 20)))  # comes back the next quarter
        self.reply(self.a, 11, when=_at(datetime.date(2024, 1, 7)))
        self.reply(self.b, 12, when=_at(datetime.date(2024, 9, 30)))  # the data ends on a quarter's last day
        data = audience.retention()
        months = {m["month"]: m for m in data["monthly"]}
        self.assertEqual((months["2024-01"]["active"], months["2024-01"]["new"]), (2, 2))
        self.assertEqual(months["2024-02"]["active"], 0)
        q1 = data["cohorts"][0]
        self.assertEqual((q1["quarter"], q1["size"]), ("2024Q1", 2))
        self.assertEqual(q1["cells"][0], 0.5)  # one of two came back in 2024Q2
        self.assertIsNotNone(q1["cells"][1])  # 2024Q3 is complete
        self.assertIsNone(q1["cells"][2])  # 2024Q4 is not
        self.assertAlmostEqual(data["returning_share"], 1 / 3)


# ── Channels as commenters ───────────────────────────────────────────────────


class ChannelCommentersTests(_LabelledCorpus):
    def test_marked_ids(self) -> None:
        self.assertEqual(channel_telegram_id(-(MARKED_CHANNEL_OFFSET + 42)), 42)
        self.assertIsNone(channel_telegram_id(42))
        self.assertIsNone(channel_telegram_id(-42))  # a basic group

    def test_kinds_and_citation(self) -> None:
        group_tid = 777
        type(self.a).objects.filter(pk=self.a.pk).update(linked_chat_id=group_tid)
        marked = lambda tid: -(MARKED_CHANNEL_OFFSET + tid)  # noqa: E731
        self.reply(self.a, marked(self.a.telegram_id))  # own post
        self.reply(self.a, marked(group_tid))  # the discussion group's anonymous admins
        self.reply(self.a, marked(self.b.telegram_id), n=2)  # B comments on A
        self.reply(self.a, marked(999))  # an uncrawled channel
        data = audience.channel_commenters()
        self.assertEqual(data["kinds"], {"own": 1, "group": 1, "other": 3})
        pairs = {(r["sender_tid"], r["channel"].pk): r for r in data["pairs"]}
        self.assertEqual(pairs[(self.b.telegram_id, self.a.pk)]["comments"], 2)
        self.assertIs(pairs[(self.b.telegram_id, self.a.pk)]["cited"], False)
        self.assertIsNone(pairs[(999, self.a.pk)]["cited"])
        Message.objects.create(channel=self.b, telegram_id=9, date=_at(D0), forwarded_from=self.a)
        data = audience.channel_commenters()
        self.assertIs(next(r for r in data["pairs"] if r["sender_tid"] == self.b.telegram_id)["cited"], True)


# ── Subscriber history ───────────────────────────────────────────────────────


class SubscriberHistoryTests(_LabelledCorpus):
    def test_record_keeps_one_count_a_day(self) -> None:
        ChannelSubscriberCount.record(self.b, 10)
        ChannelSubscriberCount.record(self.b, 12)
        ChannelSubscriberCount.record(self.b, None)
        self.assertEqual(
            list(ChannelSubscriberCount.objects.filter(channel=self.b).values_list("count", flat=True)), [12]
        )


# ── Pages and CSVs ───────────────────────────────────────────────────────────


class AudiencePageTests(_LabelledCorpus):
    def setUp(self) -> None:
        super().setUp()
        self.reply(self.a, 10, n=2)
        self.reply(self.b, 10)
        self.reply(self.c, 11)

    def test_every_section_renders(self) -> None:
        for slug, title, _fn in audience.SECTIONS:
            url = (
                reverse("audience")
                if slug == "participation"
                else reverse("audience-section", kwargs={"section": slug})
            )
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, slug)
            self.assertContains(resp, f">{title}</a>")  # the sub-menu
        self.assertEqual(self.client.get("/audience/nope/").status_code, 404)

    def test_every_section_csv(self) -> None:
        for slug, _title, _fn in audience.SECTIONS:
            resp = self.client.get(reverse("audience-csv", kwargs={"section": slug}))
            self.assertEqual(resp.status_code, 200, slug)
            header = next(csv.reader(io.StringIO(resp.content.decode())))
            self.assertTrue(header, slug)
        self.assertEqual(self.client.get("/audience/nope.csv").status_code, 404)
