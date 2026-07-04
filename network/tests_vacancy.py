"""Tests for the vacancy succession scorers (network.vacancy_analysis).

The scorers had two real bugs in their history (a wrong cos_in formula that
over-scored broad-audience candidates, and a card/export disagreement on deleted
messages) with no unit coverage; these tests pin the maths of every measure, the
null-model calibration, the new-vs-habit distinction, and the card/export
agreement contract.
"""

import datetime

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from network.vacancy_analysis import (
    ALL_VACANCY_MEASURES,
    _bh_adjust,
    _hypergeom_sf,
    _shift_months,
    _successor_ranks,
    compute_vacancy_analysis,
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
    before — a habit) and o2 (new); it sources from s1, as the vacancy did.
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
        # c1 sources from s1 in the after-window (its own first message).
        Message.objects.create(
            telegram_id=1, channel=cls.c1, forwarded_from=cls.s1, date=datetime.datetime(2024, 2, 15, tzinfo=UTC)
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
        # c1: cos_in = 2/√(3·2), cos_out = 1/√(2·1); c2: cos_in = 1/√3, cos_out = 0.
        self.assertEqual(
            self.by_pk[self.c1.pk]["scores"]["STRUCTURAL_EQUIV"],
            round(0.5 * (2 / 6**0.5) + 0.5 * (1 / 2**0.5), 3),
        )
        self.assertEqual(self.by_pk[self.c2.pk]["scores"]["STRUCTURAL_EQUIV"], round(0.5 * (1 / 3**0.5), 3))

    def test_brokerage_overlap(self) -> None:
        # Vacancy spans {(src-org, amp-org)}; c1 spans the same single pair → 1.0;
        # c2 has no sources → empty pair set → 0.0.
        self.assertEqual(self.by_pk[self.c1.pk]["scores"]["BROKERAGE"], 1.0)
        self.assertEqual(self.by_pk[self.c2.pk]["scores"]["BROKERAGE"], 0.0)

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
        # c1: 1 draw hits → p = 2/5 · … = 1 − 3/5 = 0.4, sole test → q = p.
        sig1 = self.by_pk[self.c1.pk]["significance"]["sources"]
        self.assertAlmostEqual(sig1["p"], 0.4)
        self.assertAlmostEqual(sig1["q"], 0.4)
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
            amp_sig = export_by_pk[pk]["significance"]["amplifiers"]
            self.assertEqual(card["q_amp"], amp_sig["q"] if amp_sig else None)

    def test_only_after_filters_display_not_scores(self) -> None:
        unfiltered = self._get(only_after_vacancy="0")
        filtered = self._get(only_after_vacancy="1")
        # c1's first own message is after the closure → kept; c2 has none → dropped.
        self.assertEqual({c["pk"] for c in unfiltered["candidates"]}, {self.c1.pk, self.c2.pk})
        self.assertEqual({c["pk"] for c in filtered["candidates"]}, {self.c1.pk})
        c1_unfiltered = next(c for c in unfiltered["candidates"] if c["pk"] == self.c1.pk)
        c1_filtered = filtered["candidates"][0]
        for key in ("score_a", "score_new", "score_b", "score_c", "q_amp", "new_adopter_count"):
            self.assertEqual(c1_filtered[key], c1_unfiltered[key])

    def test_successor_flag(self) -> None:
        data = self._get(only_after_vacancy="0")
        flags = {c["pk"]: c["is_successor"] for c in data["candidates"]}
        self.assertTrue(flags[self.c1.pk])
        self.assertFalse(flags[self.c2.pk])
