"""Tests for the vacancy succession scorers (network.vacancy_analysis).

The scorers had two real bugs in their history (a wrong cos_in formula that
over-scored broad-audience candidates, and a card/export disagreement on deleted
messages) with no unit coverage; these tests pin the maths of every measure, the
null-model calibration, the new-vs-habit distinction, and the card/export
agreement contract.
"""

import datetime

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from network.vacancy_analysis import (
    ALL_VACANCY_MEASURES,
    DEFAULT_MAX_CANDIDATES,
    _bh_adjust,
    _hypergeom_sf,
    _scores_origin,
    _shift_months,
    _successor_ranks,
    compute_vacancy_analysis,
    configured_max_candidates,
    orphaned_amplifier_pks,
)
from webapp.models import ChannelVacancy, Message
from webapp.test_helpers import make_channel, make_label

UTC = datetime.timezone.utc


class ShiftMonthsTests(TestCase):
    def test_shift_back_and_forward(self) -> None:
        self.assertEqual(_shift_months(datetime.date(2024, 1, 1), -12), datetime.date(2023, 1, 1))
        self.assertEqual(_shift_months(datetime.date(2024, 1, 1), 24), datetime.date(2026, 1, 1))

    def test_month_end_clamps(self) -> None:
        # Jan 31 − 1 month → Dec 31; Mar 31 − 1 month → Feb 29 (2024 is a leap year).
        self.assertEqual(_shift_months(datetime.date(2024, 1, 31), -1), datetime.date(2023, 12, 31))
        self.assertEqual(_shift_months(datetime.date(2024, 3, 31), -1), datetime.date(2024, 2, 29))


class HypergeomSfTests(TestCase):
    def test_exact_tail(self) -> None:
        # X ~ Hypergeom(N=10, K=5, n=4): P(X ≥ 4) = C(5,4)·C(5,0)/C(10,4) = 5/210.
        self.assertAlmostEqual(_hypergeom_sf(4, 10, 5, 4), 5 / 210)
        # P(X ≥ 1) with N=4, K=3, n=1 = 3/4 (single draw hits a marked item).
        self.assertAlmostEqual(_hypergeom_sf(1, 4, 3, 1), 0.75)

    def test_boundaries(self) -> None:
        self.assertEqual(_hypergeom_sf(0, 10, 5, 4), 1.0)  # ≥0 is certain
        self.assertEqual(_hypergeom_sf(5, 10, 5, 4), 0.0)  # more than min(K, n) is impossible
        self.assertAlmostEqual(_hypergeom_sf(4, 10, 4, 4), 1 / 210)  # all marked drawn

    def test_degenerate_inputs_are_conservative(self) -> None:
        for args in [(1, 0, 0, 0), (1, 10, 0, 4), (1, 10, 5, 0), (1, 4, 5, 2), (1, 4, 2, 5)]:
            self.assertEqual(_hypergeom_sf(*args), 1.0)


class BhAdjustTests(TestCase):
    def test_known_vector(self) -> None:
        adjusted = _bh_adjust([0.01, 0.04, 0.03, 0.5])
        expected = [0.04, 0.04 * 4 / 3, 0.04 * 4 / 3, 0.5]  # step-up with monotonicity
        for got, want in zip(adjusted, expected, strict=True):
            self.assertAlmostEqual(got, want)

    def test_single_p_unchanged(self) -> None:
        self.assertEqual(_bh_adjust([0.2]), [0.2])

    def test_empty(self) -> None:
        self.assertEqual(_bh_adjust([]), [])


class SuccessorRanksTests(TestCase):
    def test_competition_rank_with_ties_and_nulls(self) -> None:
        candidates = [
            {"pk": 1, "scores": {"A": 0.9, "B": None}},
            {"pk": 2, "scores": {"A": 0.5, "B": 0.4}},
            {"pk": 3, "scores": {"A": 0.5, "B": 0.7}},
        ]
        self.assertEqual(_successor_ranks(candidates, 2, {"A", "B"}), {"A": 2, "B": 2})
        self.assertEqual(_successor_ranks(candidates, 3, {"A", "B"}), {"A": 2, "B": 1})
        # Unscored measure and absent successor → None ranks.
        self.assertEqual(_successor_ranks(candidates, 1, {"B"}), {"B": None})
        self.assertEqual(_successor_ranks(candidates, 99, {"A"}), {"A": None})


class VacancyScorerFixture(TestCase):
    """One vacancy, three orphans, two candidates — every score hand-computed.

    Closure 2024-01-01; before-window [2023-01-01, 2024-01-01); after-window
    [2024-01-01, 2026-01-01]. Orphans o1..o3 forwarded the vacancy in the before
    window. Candidate c1 is forwarded after closure by o1 (who already forwarded it
    before — a habit) and o2 (new); it sources from s1, as the vacancy did, and
    archive-forwards the vacancy's own authored post (tg3) after the closure —
    the content universe is {(vacancy, 3)}, so c1's Content Continuity is 1.0.
    Candidate c2 is forwarded by o3 only and has no sources.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        cls.org_amp = make_label(name="Amplifier org")
        cls.org_src = make_label(name="Source org")
        cls.vacancy_ch = make_channel(telegram_id=1, label=cls.org_amp, title="Vacancy")
        cls.o1 = make_channel(telegram_id=2, label=cls.org_amp, title="Orphan 1")
        cls.o2 = make_channel(telegram_id=3, label=cls.org_amp, title="Orphan 2")
        cls.o3 = make_channel(telegram_id=4, label=cls.org_amp, title="Orphan 3")
        cls.s1 = make_channel(telegram_id=5, label=cls.org_src, title="Source 1")
        cls.s2 = make_channel(telegram_id=6, label=cls.org_src, title="Source 2")
        cls.c1 = make_channel(telegram_id=7, label=cls.org_amp, title="Candidate 1")
        cls.c2 = make_channel(telegram_id=8, label=cls.org_amp, title="Candidate 2")

        before = datetime.datetime(2023, 6, 15, tzinfo=UTC)
        # Orphans: each forwards the vacancy inside the before-window.
        for tid, orphan in enumerate([cls.o1, cls.o2, cls.o3], start=1):
            Message.objects.create(telegram_id=tid, channel=orphan, forwarded_from=cls.vacancy_ch, date=before)
        # The vacancy's before-window source portfolio: s1 and s2.
        Message.objects.create(
            telegram_id=1, channel=cls.vacancy_ch, forwarded_from=cls.s1, date=datetime.datetime(2023, 5, 1, tzinfo=UTC)
        )
        Message.objects.create(
            telegram_id=2, channel=cls.vacancy_ch, forwarded_from=cls.s2, date=datetime.datetime(2023, 5, 2, tzinfo=UTC)
        )
        # The vacancy's own authored post — its content universe for Content Continuity.
        # (Its two forwards above carry no origin fields, so they are skipped.)
        Message.objects.create(telegram_id=3, channel=cls.vacancy_ch, date=datetime.datetime(2023, 11, 15, tzinfo=UTC))
        # o1 already forwarded c1 before the closure → pre-existing habit, not adoption.
        Message.objects.create(
            telegram_id=10, channel=cls.o1, forwarded_from=cls.c1, date=datetime.datetime(2023, 7, 1, tzinfo=UTC)
        )
        # After closure (2024-01-01): o1 and o2 forward c1 exactly 30 days in;
        # o3 forwards c2 on 2024-06-01 (152 days in — 2024 is a leap year).
        after_30d = datetime.datetime(2024, 1, 31, tzinfo=UTC)
        Message.objects.create(telegram_id=11, channel=cls.o1, forwarded_from=cls.c1, date=after_30d)
        Message.objects.create(telegram_id=12, channel=cls.o2, forwarded_from=cls.c1, date=after_30d)
        Message.objects.create(
            telegram_id=13, channel=cls.o3, forwarded_from=cls.c2, date=datetime.datetime(2024, 6, 1, tzinfo=UTC)
        )
        # c1 sources from s1 in the after-window (its own first message) and
        # archive-forwards the vacancy's authored post tg3 — the rebrand tell.
        Message.objects.create(
            telegram_id=1, channel=cls.c1, forwarded_from=cls.s1, date=datetime.datetime(2024, 2, 15, tzinfo=UTC)
        )
        Message.objects.create(
            telegram_id=2,
            channel=cls.c1,
            forwarded_from=cls.vacancy_ch,
            date=datetime.datetime(2024, 2, 1, tzinfo=UTC),
            fwd_from_channel_post=3,
            fwd_from_date=datetime.datetime(2023, 11, 15, tzinfo=UTC),
        )
        cls.vacancy = ChannelVacancy.objects.create(
            channel=cls.vacancy_ch, closure_date=datetime.date(2024, 1, 1), successor=cls.c1
        )


class ComputeVacancyAnalysisTests(VacancyScorerFixture):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.payload = compute_vacancy_analysis(selected_measures=set(ALL_VACANCY_MEASURES))
        vac = cls.payload["vacancies"][0]
        cls.by_pk = {c["pk"]: c for c in vac["candidates"]}
        cls.vac = vac

    def test_orphans_and_candidates(self) -> None:
        self.assertEqual(self.vac["orphaned_count"], 3)
        self.assertEqual(set(self.by_pk), {self.c1.pk, self.c2.pk})

    def test_amplifier_coverage(self) -> None:
        self.assertEqual(self.by_pk[self.c1.pk]["scores"]["AMPLIFIER_JACCARD"], round(2 / 3, 3))
        self.assertEqual(self.by_pk[self.c2.pk]["scores"]["AMPLIFIER_JACCARD"], round(1 / 3, 3))

    def test_new_adopter_coverage_excludes_habit(self) -> None:
        # o1's re-adoption of c1 is a before-window habit; only o2 is a new adopter.
        c1 = self.by_pk[self.c1.pk]
        self.assertEqual(c1["scores"]["NEW_ADOPTERS"], round(1 / 3, 3))
        self.assertEqual(c1["new_adopter_count"], 1)
        c2 = self.by_pk[self.c2.pk]
        self.assertEqual(c2["scores"]["NEW_ADOPTERS"], round(1 / 3, 3))
        self.assertEqual(c2["new_adopter_count"], 1)

    def test_neighbour_set_equivalence(self) -> None:
        # c1: cos_in = 2/√(3·2), cos_out = 1/√(2·2) (its sources are {s1, vacancy} —
        # the archive forward counts); c2: cos_in = 1/√3, cos_out = 0.
        self.assertEqual(
            self.by_pk[self.c1.pk]["scores"]["STRUCTURAL_EQUIV"],
            round(0.5 * (2 / 6**0.5) + 0.5 * (1 / 2), 3),
        )
        self.assertEqual(self.by_pk[self.c2.pk]["scores"]["STRUCTURAL_EQUIV"], round(0.5 * (1 / 3**0.5), 3))

    def test_brokerage_overlap(self) -> None:
        # Vacancy spans {(src-org, amp-org)}; c1 spans that pair plus (amp-org, amp-org)
        # via its archive forward of the vacancy → Jaccard 1/2; c2 has no sources →
        # empty pair set → 0.0.
        self.assertEqual(self.by_pk[self.c1.pk]["scores"]["BROKERAGE"], 0.5)
        self.assertEqual(self.by_pk[self.c2.pk]["scores"]["BROKERAGE"], 0.0)

    def test_content_continuity(self) -> None:
        # Content universe = {(vacancy, 3)} (the authored post; the vacancy's own
        # forwards carry no origin fields and are skipped). c1 re-circulates exactly
        # that origin → 1/√(1·1) = 1.0, one archive forward; c2 circulates no
        # pre-closure content → 0.0.
        c1 = self.by_pk[self.c1.pk]
        self.assertEqual(c1["scores"]["ORIGIN_OVERLAP"], 1.0)
        self.assertEqual(c1["archive_forward_count"], 1)
        c2 = self.by_pk[self.c2.pk]
        self.assertEqual(c2["scores"]["ORIGIN_OVERLAP"], 0.0)
        self.assertEqual(c2["archive_forward_count"], 0)

    def test_origin_significance(self) -> None:
        # Population = {(vacancy, 3)} (c1's archive forward is the only after-window
        # row with a pre-closure origin date), all of it marked → c1: 1 draw, 1 hit
        # over a fully marked pool → p = q = 1.0. c2 circulates no old content: not
        # tested.
        sig1 = self.by_pk[self.c1.pk]["significance"]["origins"]
        self.assertAlmostEqual(sig1["p"], 1.0)
        self.assertAlmostEqual(sig1["q"], 1.0)
        self.assertIsNone(self.by_pk[self.c2.pk]["significance"]["origins"])

    def test_temporal_adoption(self) -> None:
        # c1: coverage 2/3, mean delay 30 days → (2/3)/2; c2: 1/3 over 152 days.
        self.assertEqual(self.by_pk[self.c1.pk]["scores"]["TEMPORAL"], round((2 / 3) / 2, 3))
        self.assertEqual(self.by_pk[self.c2.pk]["scores"]["TEMPORAL"], round((1 / 3) / (1 + 152 / 30), 3))

    def test_amplifier_significance(self) -> None:
        # Active-amplifier universe = {o1, o2, o3, c1} (c1 forwards s1), marked = 3 orphans.
        # c1: overlap 2 of a 2-set → p = C(3,2)/C(4,2) = 0.5; c2: 1 of 1 → p = 3/4.
        # BH over [0.5, 0.75] → both q = 0.75.
        sig1 = self.by_pk[self.c1.pk]["significance"]["amplifiers"]
        sig2 = self.by_pk[self.c2.pk]["significance"]["amplifiers"]
        self.assertAlmostEqual(sig1["p"], 0.5)
        self.assertAlmostEqual(sig2["p"], 0.75)
        self.assertAlmostEqual(sig1["q"], 0.75)
        self.assertAlmostEqual(sig2["q"], 0.75)

    def test_source_significance(self) -> None:
        # Source universe = {vacancy, s1, s2, c1, c2}; vacancy sources = 2.
        # c1 draws {s1, vacancy} (2 draws, 1 hit) → p = 1 − C(3,2)/C(5,2) = 0.7,
        # sole test → q = p.
        sig1 = self.by_pk[self.c1.pk]["significance"]["sources"]
        self.assertAlmostEqual(sig1["p"], 0.7)
        self.assertAlmostEqual(sig1["q"], 0.7)
        # c2 has no sources: no data ≠ evidence, so it is not tested.
        self.assertIsNone(self.by_pk[self.c2.pk]["significance"]["sources"])

    def test_successor_and_validation(self) -> None:
        self.assertTrue(self.by_pk[self.c1.pk].get("is_successor"))
        succ = self.vac["successor"]
        self.assertEqual(succ["pk"], self.c1.pk)
        self.assertTrue(succ["in_candidates"])
        self.assertEqual(
            succ["ranks"],
            dict.fromkeys(ALL_VACANCY_MEASURES, 1),
        )
        validation = self.payload["validation"]
        self.assertEqual(validation["n_labelled"], 1)
        for m in ALL_VACANCY_MEASURES:
            self.assertEqual(validation["per_measure"][m]["hits_at_1"], 1)
            self.assertEqual(validation["per_measure"][m]["mrr"], 1.0)

    def test_no_successor_yields_null_validation(self) -> None:
        self.vacancy.successor = None
        self.vacancy.save()
        payload = compute_vacancy_analysis(selected_measures={"AMPLIFIER_JACCARD"})
        self.assertIsNone(payload["validation"])
        self.assertIsNone(payload["vacancies"][0]["successor"])


class VacancyAnalysisCardTests(VacancyScorerFixture):
    """The interactive card shares the scorer with the export; the only difference is
    display filtering — only_after_vacancy must not change any candidate's scores."""

    def setUp(self) -> None:
        cache.clear()

    def _get(self, **params) -> dict:
        url = reverse("channel-vacancy-analysis", kwargs={"pk": self.vacancy_ch.pk})
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_card_scores_match_export(self) -> None:
        data = self._get(only_after_vacancy="0")
        by_pk = {c["pk"]: c for c in data["candidates"]}
        export = compute_vacancy_analysis(selected_measures=set(ALL_VACANCY_MEASURES))
        export_by_pk = {c["pk"]: c for c in export["vacancies"][0]["candidates"]}
        for pk, card in by_pk.items():
            self.assertEqual(card["score_a"], export_by_pk[pk]["scores"]["AMPLIFIER_JACCARD"])
            self.assertEqual(card["score_new"], export_by_pk[pk]["scores"]["NEW_ADOPTERS"])
            self.assertEqual(card["score_b"], export_by_pk[pk]["scores"]["STRUCTURAL_EQUIV"])
            self.assertEqual(card["score_c"], export_by_pk[pk]["scores"]["BROKERAGE"])
            self.assertEqual(card["score_o"], export_by_pk[pk]["scores"]["ORIGIN_OVERLAP"])
            self.assertEqual(card["archive_forward_count"], export_by_pk[pk]["archive_forward_count"])
            amp_sig = export_by_pk[pk]["significance"]["amplifiers"]
            self.assertEqual(card["q_amp"], amp_sig["q"] if amp_sig else None)
            origin_sig = export_by_pk[pk]["significance"]["origins"]
            self.assertEqual(card["q_origin"], origin_sig["q"] if origin_sig else None)

    def test_only_after_filters_display_not_scores(self) -> None:
        unfiltered = self._get(only_after_vacancy="0")
        filtered = self._get(only_after_vacancy="1")
        # c1's first own message is after the closure → kept; c2 has none → dropped.
        self.assertEqual({c["pk"] for c in unfiltered["candidates"]}, {self.c1.pk, self.c2.pk})
        self.assertEqual({c["pk"] for c in filtered["candidates"]}, {self.c1.pk})
        c1_unfiltered = next(c for c in unfiltered["candidates"] if c["pk"] == self.c1.pk)
        c1_filtered = filtered["candidates"][0]
        keys = ("score_a", "score_new", "score_b", "score_c", "score_o", "q_amp", "q_origin", "new_adopter_count")
        for key in keys:
            self.assertEqual(c1_filtered[key], c1_unfiltered[key])

    def test_successor_flag(self) -> None:
        data = self._get(only_after_vacancy="0")
        flags = {c["pk"]: c["is_successor"] for c in data["candidates"]}
        self.assertTrue(flags[self.c1.pk])
        self.assertFalse(flags[self.c2.pk])

    @override_settings(SA_VACANCY_MAX_CANDIDATES=1)
    def test_card_uses_configured_candidate_cap(self) -> None:
        # The cap is the BH family size: the card used to hard-code 30 candidates, so
        # with any other configured cap its q-values disagreed with the export's. With
        # a cap of 1 only c1 (2 orphaned amplifiers) is scored, and its amplifier q is
        # its raw p = 0.5 (a family of one) — not the 0.75 a 2-candidate family gives.
        data = self._get(only_after_vacancy="0")
        self.assertEqual([c["pk"] for c in data["candidates"]], [self.c1.pk])
        self.assertAlmostEqual(data["candidates"][0]["q_amp"], 0.5)
        self.assertEqual(data["max_candidates"], 1)
        export = compute_vacancy_analysis(selected_measures=set(ALL_VACANCY_MEASURES))
        self.assertEqual(export["max_candidates"], 1)
        (export_c1,) = export["vacancies"][0]["candidates"]
        self.assertEqual(data["candidates"][0]["q_amp"], export_c1["significance"]["amplifiers"]["q"])
        self.assertEqual(data["candidates"][0]["q_origin"], export_c1["significance"]["origins"]["q"])


class ConfiguredMaxCandidatesTests(TestCase):
    """The card and the export's default share one candidate cap source."""

    @override_settings(SA_VACANCY_MAX_CANDIDATES=7)
    def test_reads_configured_value(self) -> None:
        self.assertEqual(configured_max_candidates(), 7)

    def test_invalid_values_fall_back_to_factory_default(self) -> None:
        for bad in (None, 0, -3, "x"):
            with self.subTest(value=bad), override_settings(SA_VACANCY_MAX_CANDIDATES=bad):
                self.assertEqual(configured_max_candidates(), DEFAULT_MAX_CANDIDATES)


class SelfForwardExclusionTests(TestCase):
    """Self-forwards are not amplification anywhere in the vacancy analysis.

    Closure 2024-01-01. Orphans o1 (org A) and o2 (org B) forward the vacancy in the
    before-window; the vacancy — not lost, so in-target — also forwards *itself* there
    and must not become its own orphan. Its sources are s1 (out of target) and o2 (the
    o2 forward carries origin (o2, 5), the whole content universe). After the closure o1 adopts
    o2 (30 days in) and o2 sources from s1 — the legitimate signal. The traps: o2
    self-forwards its old post (o2, 5) 10 days in (must not count o2 as its own
    adopter, amplifier, source or re-circulated origin), and o1 self-forwards (must not
    put o1 in the candidate list on its own re-posts). Every expected value below is
    the self-forward-free one.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        org_a = make_label(name="Org A")
        org_b = make_label(name="Org B")
        # Out of target, so s1 has an org for Brokerage but is never itself a candidate.
        org_src = make_label(name="Source org", is_in_target=False)
        cls.vacancy_ch = make_channel(telegram_id=1, label=org_a, title="Vacancy")
        cls.o1 = make_channel(telegram_id=2, label=org_a, title="Orphan 1")
        cls.o2 = make_channel(telegram_id=3, label=org_b, title="Orphan 2")
        cls.s1 = make_channel(telegram_id=4, label=org_src, title="Source 1")

        def msg(tid, channel, date, fwd=None, post=None, fwd_date=None):
            Message.objects.create(
                telegram_id=tid,
                channel=channel,
                date=date,
                forwarded_from=fwd,
                fwd_from_channel_post=post,
                fwd_from_date=fwd_date,
            )

        def dt(*args):
            return datetime.datetime(*args, tzinfo=UTC)

        # Before-window.
        msg(1, cls.o1, dt(2023, 6, 15), fwd=cls.vacancy_ch)
        msg(1, cls.o2, dt(2023, 6, 15), fwd=cls.vacancy_ch)
        msg(1, cls.vacancy_ch, dt(2023, 5, 1), fwd=cls.s1)
        msg(2, cls.vacancy_ch, dt(2023, 5, 2), fwd=cls.o2, post=5, fwd_date=dt(2023, 4, 30))
        msg(3, cls.vacancy_ch, dt(2023, 6, 20), fwd=cls.vacancy_ch)  # trap: vacancy self-forward
        # After-window.
        msg(2, cls.o1, dt(2024, 1, 31), fwd=cls.o2)
        msg(2, cls.o2, dt(2024, 2, 15), fwd=cls.s1)
        msg(3, cls.o2, dt(2024, 1, 11), fwd=cls.o2, post=5, fwd_date=dt(2023, 4, 30))  # trap: o2 self-forward
        msg(3, cls.o1, dt(2024, 3, 1), fwd=cls.o1)  # trap: o1 self-forward
        ChannelVacancy.objects.create(channel=cls.vacancy_ch, closure_date=datetime.date(2024, 1, 1))

        cls.payload = compute_vacancy_analysis(selected_measures=set(ALL_VACANCY_MEASURES))
        cls.vac = cls.payload["vacancies"][0]
        cls.by_pk = {c["pk"]: c for c in cls.vac["candidates"]}

    def test_vacancy_self_forward_is_not_its_own_orphan(self) -> None:
        self.assertEqual(orphaned_amplifier_pks(self.vacancy_ch, datetime.date(2024, 1, 1)), {self.o1.pk, self.o2.pk})
        self.assertEqual(self.vac["orphaned_count"], 2)

    def test_orphan_does_not_enter_candidates_on_own_self_forwards(self) -> None:
        self.assertEqual(set(self.by_pk), {self.o2.pk})

    def test_orphan_is_not_its_own_adopter(self) -> None:
        o2 = self.by_pk[self.o2.pk]
        self.assertEqual(o2["amplifier_count"], 1)  # o1 only
        self.assertEqual(o2["scores"]["AMPLIFIER_JACCARD"], 0.5)
        self.assertEqual(o2["scores"]["NEW_ADOPTERS"], 0.5)
        self.assertEqual(o2["new_adopter_count"], 1)
        # Coverage 1/2 at o1's 30-day delay; o2's own 10-day re-post doesn't count.
        self.assertEqual(o2["scores"]["TEMPORAL"], 0.25)

    def test_neighbour_sets_exclude_self(self) -> None:
        # cos_in = |{o1,o2} ∩ {o1}| / √(2·1); cos_out = |{s1,o2} ∩ {s1}| / √(2·1) —
        # neither the vacancy nor o2 is its own source or amplifier.
        self.assertEqual(self.by_pk[self.o2.pk]["scores"]["STRUCTURAL_EQUIV"], round(1 / 2**0.5, 3))

    def test_brokerage_excludes_self(self) -> None:
        # Vacancy pairs {src, B} × {A, B} = 4; o2 spans only (src, A) — not (B, ·) via
        # its self-source nor (·, B) via its self-amplification → 1/4.
        self.assertEqual(self.by_pk[self.o2.pk]["scores"]["BROKERAGE"], 0.25)

    def test_self_forward_is_not_recirculated_origin(self) -> None:
        # Universe {(o2, 5)}: o2 re-posting its own old post is not continuing the
        # vacancy's stream, so it circulates no old content at all → 0.0, untested.
        o2 = self.by_pk[self.o2.pk]
        self.assertEqual(o2["scores"]["ORIGIN_OVERLAP"], 0.0)
        self.assertEqual(o2["archive_forward_count"], 0)
        self.assertIsNone(o2["significance"]["origins"])

    def test_source_null_excludes_self(self) -> None:
        # Source universe {vacancy, s1, o2} (no self-forward targets), marked {s1, o2};
        # o2 draws {s1}, 1 hit → p = 2/3, sole test → q = p.
        sig = self.by_pk[self.o2.pk]["significance"]["sources"]
        self.assertAlmostEqual(sig["p"], 0.6667)
        self.assertAlmostEqual(sig["q"], 0.6667)

    def test_card_matches(self) -> None:
        cache.clear()
        url = reverse("channel-vacancy-analysis", kwargs={"pk": self.vacancy_ch.pk})
        data = self.client.get(url, {"only_after_vacancy": "0"}).json()
        self.assertEqual(data["orphaned_count"], 2)
        self.assertEqual([c["pk"] for c in data["candidates"]], [self.o2.pk])
        card = data["candidates"][0]
        self.assertEqual(card["amplifier_count"], 1)
        self.assertEqual(card["score_a"], 0.5)
        self.assertEqual(card["score_o"], 0.0)


class LostVacancySourceNullTests(TestCase):
    """The source-overlap null when the vacancy is marked lost.

    A closed vacancy is typically ``is_lost`` — out of ``in_target()`` — while its
    messages stay alive. Its four before-window sources s1..s4 are cited by no one else
    except s1 (by candidate c after the closure). The universe must still contain all
    four (marked ⊆ universe): {vacancy, c, s1, s2, s3, s4} = 6, marked 4, c draws {s1}
    with 1 hit → p = 4/6. Built from in-target citers only, the universe was
    {vacancy, c, s1} = 3 < 4 marked — inconsistent, degenerating to p = 1.0.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        org = make_label(name="Org")
        src_org = make_label(name="Source org")
        cls.vacancy_ch = make_channel(telegram_id=1, label=org, title="Vacancy", is_lost=True)
        cls.o1 = make_channel(telegram_id=2, label=org, title="Orphan")
        cls.c = make_channel(telegram_id=3, label=org, title="Candidate")
        sources = [make_channel(telegram_id=10 + i, label=src_org, title=f"Source {i}") for i in range(1, 5)]
        Message.objects.create(
            telegram_id=1,
            channel=cls.o1,
            forwarded_from=cls.vacancy_ch,
            date=datetime.datetime(2023, 6, 15, tzinfo=UTC),
        )
        for i, src in enumerate(sources, start=1):
            Message.objects.create(
                telegram_id=i,
                channel=cls.vacancy_ch,
                forwarded_from=src,
                date=datetime.datetime(2023, 5, i, tzinfo=UTC),
            )
        Message.objects.create(
            telegram_id=2, channel=cls.o1, forwarded_from=cls.c, date=datetime.datetime(2024, 2, 1, tzinfo=UTC)
        )
        Message.objects.create(
            telegram_id=1, channel=cls.c, forwarded_from=sources[0], date=datetime.datetime(2024, 2, 15, tzinfo=UTC)
        )
        ChannelVacancy.objects.create(channel=cls.vacancy_ch, closure_date=datetime.date(2024, 1, 1))

    def test_vacancy_sources_are_in_the_universe(self) -> None:
        payload = compute_vacancy_analysis(selected_measures={"STRUCTURAL_EQUIV"})
        (cand,) = payload["vacancies"][0]["candidates"]
        self.assertEqual(cand["pk"], self.c.pk)
        sig = cand["significance"]["sources"]
        self.assertAlmostEqual(sig["p"], 0.6667)
        self.assertAlmostEqual(sig["q"], 0.6667)


class ScoresOriginTests(TestCase):
    """Content-continuity scorer (_scores_origin), every quantity hand-computed.

    Closure 2024-01-01. The vacancy's content universe holds 4 origins: (a, 101)
    curated (forwarded in the before-window), (v, 7) authored and crawled, (v, 55)
    authored and testified by w's before-window forward, (v, 88) authored and
    testified only by candidate z's post-closure archive forward. A fieldless
    vacancy forward exercises the skip path. Candidate x re-circulates (a, 101),
    (v, 55) and the out-of-universe (b, 201); its forward of (c, 301) has a
    post-closure origin date and is excluded. y circulates only (b, 201); z only
    the archive origin (v, 88). w's three after-window forwards of d enrich the
    null population to 7 origins, 3 of them marked.
    """

    BEFORE_START = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    CLOSURE = datetime.datetime(2024, 1, 1, tzinfo=UTC)
    AFTER_END = datetime.datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def setUpTestData(cls) -> None:
        org = make_label(name="Org")
        cls.v = make_channel(telegram_id=1, label=org, title="Vacancy")
        cls.w = make_channel(telegram_id=2, label=org, title="Witness")
        cls.x = make_channel(telegram_id=3, label=org, title="Candidate X")
        cls.y = make_channel(telegram_id=4, label=org, title="Candidate Y")
        cls.z = make_channel(telegram_id=5, label=org, title="Candidate Z")
        cls.a = make_channel(telegram_id=6, title="Origin A")
        cls.b = make_channel(telegram_id=7, title="Origin B")
        cls.c = make_channel(telegram_id=8, title="Origin C")
        cls.d = make_channel(telegram_id=9, title="Origin D")

        def msg(tid, channel, date, fwd=None, post=None, fwd_date=None):
            Message.objects.create(
                telegram_id=tid,
                channel=channel,
                date=date,
                forwarded_from=fwd,
                fwd_from_channel_post=post,
                fwd_from_date=fwd_date,
            )

        def dt(*args):
            return datetime.datetime(*args, tzinfo=UTC)

        # Universe: curated (a, 101); a fieldless forward (skipped); authored (v, 7).
        msg(1, cls.v, dt(2023, 5, 1), fwd=cls.a, post=101, fwd_date=dt(2023, 4, 30))
        msg(2, cls.v, dt(2023, 5, 2), fwd=cls.a)
        msg(7, cls.v, dt(2023, 8, 1))
        # (v, 55) testified before the closure by w; (v, 88) only by z's archive forward.
        msg(1, cls.w, dt(2023, 3, 5), fwd=cls.v, post=55, fwd_date=dt(2023, 3, 1))
        msg(1, cls.z, dt(2024, 2, 1), fwd=cls.v, post=88, fwd_date=dt(2023, 12, 15))
        # Candidate x: two universe origins plus one out-of-universe old origin; the
        # (c, 301) forward's origin postdates the closure, so it sits outside the test.
        msg(1, cls.x, dt(2024, 1, 15), fwd=cls.a, post=101, fwd_date=dt(2023, 4, 30))
        msg(2, cls.x, dt(2024, 1, 20), fwd=cls.v, post=55, fwd_date=dt(2023, 3, 1))
        msg(3, cls.x, dt(2024, 2, 10), fwd=cls.b, post=201, fwd_date=dt(2023, 9, 1))
        msg(4, cls.x, dt(2024, 6, 1), fwd=cls.c, post=301, fwd_date=dt(2024, 5, 1))
        # Candidate y: only the out-of-universe old origin.
        msg(1, cls.y, dt(2024, 3, 1), fwd=cls.b, post=201, fwd_date=dt(2023, 9, 1))
        # w's after-window circulation of d: population-only origins.
        msg(2, cls.w, dt(2024, 4, 1), fwd=cls.d, post=401, fwd_date=dt(2023, 10, 1))
        msg(3, cls.w, dt(2024, 4, 2), fwd=cls.d, post=402, fwd_date=dt(2023, 10, 2))
        msg(4, cls.w, dt(2024, 4, 3), fwd=cls.d, post=403, fwd_date=dt(2023, 10, 3))

        cls.result = _scores_origin(
            cls.v.pk, [cls.x.pk, cls.y.pk, cls.z.pk], cls.BEFORE_START, cls.CLOSURE, cls.AFTER_END
        )

    def test_scores(self) -> None:
        # x: 2 of its 3 old origins in the 4-origin universe → 2/√(4·3);
        # y: no shared origin → 0.0; z: 1 of 1 → 1/√(4·1) = 0.5.
        self.assertEqual(self.result[self.x.pk]["score"], round(2 / 12**0.5, 3))
        self.assertEqual(self.result[self.y.pk]["score"], 0.0)
        self.assertEqual(self.result[self.z.pk]["score"], 0.5)

    def test_archive_forward_counts(self) -> None:
        # Shared origins authored by the vacancy itself: (v, 55) for x, (v, 88) for z.
        self.assertEqual(self.result[self.x.pk]["archive_forward_count"], 1)
        self.assertEqual(self.result[self.y.pk]["archive_forward_count"], 0)
        self.assertEqual(self.result[self.z.pk]["archive_forward_count"], 1)

    def test_significance(self) -> None:
        # Population 7, marked 3. x: P(X≥2 | n=3) = 13/35; z: P(X≥1 | n=1) = 3/7;
        # y: 1.0. BH over the three: q = 9/14 for x and z, 1.0 for y.
        sig_x = self.result[self.x.pk]["significance"]
        sig_y = self.result[self.y.pk]["significance"]
        sig_z = self.result[self.z.pk]["significance"]
        self.assertAlmostEqual(sig_x["p"], 0.3714)
        self.assertAlmostEqual(sig_z["p"], 0.4286)
        self.assertAlmostEqual(sig_y["p"], 1.0)
        self.assertAlmostEqual(sig_x["q"], 0.6429)
        self.assertAlmostEqual(sig_z["q"], 0.6429)
        self.assertAlmostEqual(sig_y["q"], 1.0)

    def test_empty_universe_scores_none(self) -> None:
        # c has no pre-closure content at all (x's forward of it carries a
        # post-closure origin date): nothing to continue → None score, no test.
        result = _scores_origin(self.c.pk, [self.x.pk], self.BEFORE_START, self.CLOSURE, self.AFTER_END)
        self.assertEqual(result[self.x.pk], {"score": None, "archive_forward_count": 0, "significance": None})
