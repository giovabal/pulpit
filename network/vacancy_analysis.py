"""Vacancy succession analysis: score replacement candidates for dead channels."""

from __future__ import annotations

import calendar
import datetime
import math
from collections import defaultdict
from typing import Any, Callable

from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from network.utils import channel_cutoff_q
from webapp.models import Channel, ChannelLabel, ChannelVacancy, LabelGroup, Message

VALID_VACANCY_MEASURES: frozenset[str] = frozenset(
    {"AMPLIFIER_JACCARD", "NEW_ADOPTERS", "STRUCTURAL_EQUIV", "BROKERAGE", "ORIGIN_OVERLAP", "TEMPORAL"}
)

ALL_VACANCY_MEASURES: list[str] = [
    "AMPLIFIER_JACCARD",
    "NEW_ADOPTERS",
    "STRUCTURAL_EQUIV",
    "BROKERAGE",
    "ORIGIN_OVERLAP",
    "TEMPORAL",
]

MEASURE_LABELS: dict[str, str] = {
    "AMPLIFIER_JACCARD": "Amplifier Coverage",
    "NEW_ADOPTERS": "New-adopter Coverage",
    "STRUCTURAL_EQUIV": "Neighbour-set Equivalence",
    "BROKERAGE": "Brokerage overlap",
    "ORIGIN_OVERLAP": "Content Continuity",
    "TEMPORAL": "Temporal Adoption",
}

# Reserved key carrying per-candidate companions (counts, significance) through the
# scores dict returned by _scores_abc; callers pop it before treating the rest as
# measure-token → score pairs.
EXTRAS_KEY = "_extras"


# ── Utilities ─────────────────────────────────────────────────────────────────


def _shift_months(d: datetime.date, n: int) -> datetime.date:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def orphaned_amplifier_pks(
    channel: Channel,
    closure_date: datetime.date,
    months_before: int = 12,
) -> set[int]:
    """Channel PKs of a vacancy's *orphaned amplifiers*.

    The single canonical definition shared by the vacancies list, the
    vacancy-analysis card, and the structural-analysis export: in-target channels
    that forwarded from ``channel`` within the before-window
    ``[closure_date - months_before, closure_date)``, counted period-aware
    (``channel_cutoff_q``) over alive messages — so all three surfaces agree by
    construction rather than by replicating the query.
    """
    before_start = datetime.datetime.combine(
        _shift_months(closure_date, -months_before), datetime.time.min, tzinfo=datetime.timezone.utc
    )
    closure_dt = datetime.datetime.combine(closure_date, datetime.time.min, tzinfo=datetime.timezone.utc)
    return set(
        Message.objects.alive()
        .filter(
            channel__in=Channel.objects.in_target(),
            forwarded_from=channel,
            date__gte=before_start,
            date__lt=closure_dt,
        )
        .filter(channel_cutoff_q())
        .values_list("channel_id", flat=True)
        .distinct()
    )


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _cosine(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / (math.sqrt(len(a)) * math.sqrt(len(b)))


def _hypergeom_sf(k: int, population: int, successes: int, draws: int) -> float:
    """One-tailed hypergeometric tail probability P(X ≥ k).

    X counts the marked items (``successes`` marked out of ``population``) in a
    uniform draw of ``draws`` items without replacement — the chance that an overlap
    at least as large as the observed ``k`` arises if the candidate's neighbour set
    were assembled at random from the universe. Exact (``math.comb``), no SciPy;
    the universes here are at most a few thousand channels. Degenerate inputs
    (empty universe/sets, inconsistent sizes) return 1.0 — "no evidence", never
    spurious significance.
    """
    if population <= 0 or successes <= 0 or draws <= 0 or successes > population or draws > population:
        return 1.0
    if k <= 0:
        return 1.0
    k_max = min(successes, draws)
    if k > k_max:
        return 0.0
    tail = sum(math.comb(successes, i) * math.comb(population - successes, draws - i) for i in range(k, k_max + 1))
    return tail / math.comb(population, draws)


def _bh_adjust(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), order-preserving.

    Standard step-up adjustment: q_(i) = min over j ≥ i of p_(j) · m / j, capped at 1.
    Controls the false-discovery rate across the candidates tested for one vacancy
    (Benjamini & Hochberg 1995).
    """
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adjusted = [0.0] * m
    running_min = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running_min = min(running_min, pvals[i] * m / (rank + 1))
        adjusted[i] = running_min
    return adjusted


def _round_p(p: float) -> float:
    return float(f"{p:.4g}")


# ── Per-algorithm scorers ─────────────────────────────────────────────────────


def _scores_abc(
    vacancy_pk: int,
    orphaned_pks: set[int],
    candidate_pks: list[int],
    before_start: datetime.datetime,
    closure_dt: datetime.datetime,
    after_end: datetime.datetime,
    selected: set[str],
) -> dict[int, dict[str, float | None]]:
    """Scores A (Amplifier Coverage), N (New-adopter Coverage), B (Neighbour-set
    Equivalence), C (Brokerage overlap), plus per-candidate significance.

    Note: score B here is a *binary* (Ochiai) cosine over in/out neighbour **sets** —
    it ignores tie strength and is computed between one vacancy and each candidate. It
    is deliberately distinct from the weighted Lorrain & White (1971) structural-
    equivalence *matrix* computed across all graph nodes in
    :func:`network.community_stats._compute_structural_equivalence`; the two answer
    related questions with different maths, hence the separate "Neighbour-set
    Equivalence" label.

    Each candidate's scores dict also carries an :data:`EXTRAS_KEY` entry with the
    new-adopter count and the null-model calibration: exact hypergeometric tail
    probabilities for the amplifier-set and source-set overlaps (how surprising the
    observed overlap is if the candidate drew its neighbours at random from the
    active universe), BH-adjusted across the candidate list.
    """
    total_orphaned = len(orphaned_pks)

    # Distinct (orphan, candidate) forward pairs in the after-window — the raw
    # material for both Amplifier Coverage and New-adopter Coverage.
    after_pairs: set[tuple[int, int]] = set()
    amp_counts: dict[int, int] = defaultdict(int)
    if selected & {"AMPLIFIER_JACCARD", "NEW_ADOPTERS"}:
        after_pairs = set(
            Message.objects.alive()
            .filter(
                channel__in=orphaned_pks,
                forwarded_from__in=candidate_pks,
                date__gte=closure_dt,
                date__lte=after_end,
            )
            .filter(channel_cutoff_q())
            .values_list("channel_id", "forwarded_from_id")
            .distinct()
        )
        for _, fwd_id in after_pairs:
            amp_counts[fwd_id] += 1

    # (orphan, candidate) pairs already present in the BEFORE window: an orphan that
    # forwarded the candidate before the closure is a pre-existing habit, not a new
    # adoption. Windowed on the same before-window that defines the orphans, so the
    # before/after comparison is symmetric in design.
    new_counts: dict[int, int] = defaultdict(int)
    if "NEW_ADOPTERS" in selected:
        prior_pairs = set(
            Message.objects.alive()
            .filter(
                channel__in=orphaned_pks,
                forwarded_from__in=candidate_pks,
                date__gte=before_start,
                date__lt=closure_dt,
            )
            .filter(channel_cutoff_q())
            .values_list("channel_id", "forwarded_from_id")
            .distinct()
        )
        for pair in after_pairs:
            if pair not in prior_pairs:
                new_counts[pair[1]] += 1

    # Each candidate's in-amplifier set: in-target channels that forwarded from the
    # candidate in the after-window. Restricted to in-target so it shares the universe
    # of the vacancy's amplifier set (orphaned_pks ⊆ in-target), giving a well-defined
    # cosine for STRUCTURAL_EQUIV. Note |orphaned_pks ∩ cand_in_pks[cid]| == amp_count.
    # Also fetched for AMPLIFIER_JACCARD / NEW_ADOPTERS: the amplifier-overlap
    # significance test needs each candidate's full amplifier-set size.
    amp_test_selected = bool(selected & {"AMPLIFIER_JACCARD", "NEW_ADOPTERS", "STRUCTURAL_EQUIV"})
    cand_in_pks: dict[int, set[int]] = defaultdict(set)
    if amp_test_selected:
        for fwd_id, ch_id in (
            Message.objects.alive()
            .filter(
                channel__in=Channel.objects.in_target(),
                forwarded_from__in=candidate_pks,
                date__gte=closure_dt,
                date__lte=after_end,
            )
            .filter(channel_cutoff_q())
            .values_list("forwarded_from_id", "channel_id")
            .distinct()
        ):
            cand_in_pks[fwd_id].add(ch_id)

    # Forwarded-from edges out of the vacancy in the BEFORE window (org resolved at each forward's date).
    vacancy_out_pks: set[int] = set()
    vacancy_out_rows: list[tuple[int, datetime.date]] = []
    if selected & {"STRUCTURAL_EQUIV", "BROKERAGE"}:
        for fwd_id, fwd_date in (
            Message.objects.alive()
            .filter(channel=vacancy_pk, forwarded_from__isnull=False, date__gte=before_start, date__lt=closure_dt)
            .filter(channel_cutoff_q())
            .values_list("forwarded_from_id", "date")
        ):
            vacancy_out_pks.add(fwd_id)
            if fwd_date is not None:
                # localdate(): label_at must see the same TIME_ZONE calendar day the
                # period filter (channel_cutoff_q) used to admit this forward.
                vacancy_out_rows.append((fwd_id, timezone.localdate(fwd_date)))

    # Forwarded-from edges out of each candidate in the AFTER window.
    cand_out_pks: dict[int, set[int]] = defaultdict(set)
    cand_out_rows: list[tuple[int, int, datetime.date]] = []
    if selected & {"STRUCTURAL_EQUIV", "BROKERAGE"}:
        for ch_id, fwd_id, fwd_date in (
            Message.objects.alive()
            .filter(channel__in=candidate_pks, forwarded_from__isnull=False, date__gte=closure_dt, date__lte=after_end)
            .filter(channel_cutoff_q())
            .values_list("channel_id", "forwarded_from_id", "date")
        ):
            cand_out_pks[ch_id].add(fwd_id)
            if fwd_date is not None:
                cand_out_rows.append((ch_id, fwd_id, timezone.localdate(fwd_date)))

    orphaned_org_map: dict[int, int] = {}
    vacancy_org_pairs: frozenset[tuple[int, int]] = frozenset()
    cand_src_org_pks: dict[int, set[int]] = defaultdict(set)
    cand_amp_org_pks: dict[int, set[int]] = defaultdict(set)
    if "BROKERAGE" in selected:
        # The brokerage "org" identity is a channel's primary-group label, resolved as of the
        # relevant date (the forward's date for source edges, the closure date for the orphaned
        # amplifiers). Scope the cache to the primary group so its periods can't overlap.
        closure_date = timezone.localdate(closure_dt)
        primary_group_id = LabelGroup.objects.filter(is_primary=True).values_list("id", flat=True).first()
        attr_cache = ChannelLabel.build_cache(
            vacancy_out_pks | {fwd_id for _, fwd_id, _ in cand_out_rows} | set(orphaned_pks),
            group_id=primary_group_id,
        )
        vacancy_src_org_pks = {
            org for fwd_id, when in vacancy_out_rows if (org := ChannelLabel.label_at(attr_cache, fwd_id, when))
        }
        orphaned_org_map = {
            pk: org for pk in orphaned_pks if (org := ChannelLabel.label_at(attr_cache, pk, closure_date))
        }
        vacancy_amp_org_pks = set(orphaned_org_map.values())
        vacancy_org_pairs = frozenset((s, a) for s in vacancy_src_org_pks for a in vacancy_amp_org_pks)
        for ch_id, fwd_id, when in cand_out_rows:
            org = ChannelLabel.label_at(attr_cache, fwd_id, when)
            if org is not None:
                cand_src_org_pks[ch_id].add(org)
        for r in (
            Message.objects.alive()
            .filter(
                channel__in=orphaned_pks,
                forwarded_from__in=candidate_pks,
                date__gte=closure_dt,
                date__lte=after_end,
            )
            .filter(channel_cutoff_q())
            .values("forwarded_from_id", "channel_id")
            .distinct()
        ):
            org = orphaned_org_map.get(r["channel_id"])
            if org:
                cand_amp_org_pks[r["forwarded_from_id"]].add(org)

    # ── Null-model calibration ────────────────────────────────────────────────
    # Exact hypergeometric tests of the two set overlaps the scores are built on,
    # against a uniform-draw null over the active universe: a big, indiscriminately
    # amplified candidate overlaps any orphan set somewhat by chance alone, and these
    # p-values say how surprising the observed overlap actually is. BH-adjusted
    # (q-values) across the candidates tested for this vacancy.
    amp_sig: dict[int, dict[str, float]] = {}
    src_sig: dict[int, dict[str, float]] = {}
    if amp_test_selected and candidate_pks:
        in_target = Channel.objects.in_target()
        # Universe: in-target channels that made ≥1 (alive, period-aware) forward from
        # an in-target channel in the after-window — the pool a candidate's amplifier
        # set is drawn from. Marked items: the orphans still active in that pool.
        active_amplifiers = (
            Message.objects.alive()
            .filter(channel__in=in_target, forwarded_from__in=in_target, date__gte=closure_dt, date__lte=after_end)
            .filter(channel_cutoff_q())
        )
        amp_population = active_amplifiers.values("channel_id").distinct().count()
        active_orphans = active_amplifiers.filter(channel__in=orphaned_pks).values("channel_id").distinct().count()
        amp_p = {
            cid: _hypergeom_sf(
                len(orphaned_pks & cand_in_pks.get(cid, set())),
                amp_population,
                active_orphans,
                len(cand_in_pks.get(cid, set())),
            )
            for cid in candidate_pks
        }
        for cid, q in zip(candidate_pks, _bh_adjust([amp_p[c] for c in candidate_pks]), strict=True):
            amp_sig[cid] = {"p": _round_p(amp_p[cid]), "q": _round_p(q)}

    if selected & {"STRUCTURAL_EQUIV", "BROKERAGE"} and candidate_pks and vacancy_out_pks:
        # Universe: every channel forwarded from by an in-target channel (alive,
        # period-aware) across the combined before+after span — the common frame the
        # vacancy's before-window sources and each candidate's after-window sources
        # are both drawn from. Candidates with no sources at all are not tested
        # (no data ≠ evidence of independence).
        src_population = (
            Message.objects.alive()
            .filter(
                channel__in=Channel.objects.in_target(),
                forwarded_from__isnull=False,
                date__gte=before_start,
                date__lte=after_end,
            )
            .filter(channel_cutoff_q())
            .values("forwarded_from_id")
            .distinct()
            .count()
        )
        tested = [cid for cid in candidate_pks if cand_out_pks.get(cid)]
        src_p = {
            cid: _hypergeom_sf(
                len(vacancy_out_pks & cand_out_pks[cid]),
                src_population,
                len(vacancy_out_pks),
                len(cand_out_pks[cid]),
            )
            for cid in tested
        }
        for cid, q in zip(tested, _bh_adjust([src_p[c] for c in tested]), strict=True):
            src_sig[cid] = {"p": _round_p(src_p[cid]), "q": _round_p(q)}

    result: dict[int, dict[str, Any]] = {}
    for cid in candidate_pks:
        scores: dict[str, Any] = {}
        a_count = amp_counts.get(cid, 0)

        if "AMPLIFIER_JACCARD" in selected:
            # Coverage / recall — the fraction of the vacancy's orphaned amplifiers
            # that also amplify this candidate, i.e. |A ∩ B| / |A|. This is an
            # asymmetric overlap measure, NOT a Jaccard (which divides by |A ∪ B|);
            # the token is kept verbatim only for saved-config / JS compatibility.
            scores["AMPLIFIER_JACCARD"] = round(a_count / total_orphaned, 3) if total_orphaned else 0.0

        if "NEW_ADOPTERS" in selected:
            # Coverage restricted to orphans that did NOT forward the candidate in the
            # before-window — genuinely new adoption after the closure, the succession-
            # specific complement of Amplifier Coverage (which counts habit and new
            # adoption alike). A − N is the pre-existing-habit share.
            scores["NEW_ADOPTERS"] = round(new_counts.get(cid, 0) / total_orphaned, 3) if total_orphaned else 0.0

        if "STRUCTURAL_EQUIV" in selected:
            # Binary (Ochiai) cosine of in-neighbour sets (who amplifies them) and
            # out-neighbour sets (whom they source from), averaged. Set-based, so tie
            # strength is ignored — distinct from the weighted Lorrain & White matrix.
            cos_in = _cosine(orphaned_pks, cand_in_pks.get(cid, set()))
            cos_out = _cosine(vacancy_out_pks, cand_out_pks.get(cid, set()))
            scores["STRUCTURAL_EQUIV"] = round(0.5 * cos_in + 0.5 * cos_out, 3)

        if "BROKERAGE" in selected:
            # Overlap (Jaccard) of the (source-org, amplifier-org) pairs the channel spans — the
            # cross-product of the orgs it directly forwards *from* and the orgs that directly
            # amplify it. Both are one-degree citation facts about the channel, so this is a
            # structural *position* (same source ecosystem on one side, same audience ecosystem on
            # the other), NOT content flowing between those orgs through it: under one-degree
            # attribution a forward records a direct citation, not a relay. Operationalises the
            # *concept* of brokerage (Gould & Fernandez 1989) as positional org-pair overlap, not
            # their flow-based census — hence the label "Brokerage overlap".
            cand_org_pairs = frozenset(
                (s, a) for s in cand_src_org_pks.get(cid, set()) for a in cand_amp_org_pks.get(cid, set())
            )
            scores["BROKERAGE"] = round(_jaccard(vacancy_org_pairs, cand_org_pairs), 3) if vacancy_org_pairs else None

        scores[EXTRAS_KEY] = {
            "new_adopter_count": new_counts.get(cid, 0) if "NEW_ADOPTERS" in selected else None,
            "significance": {
                "amplifiers": amp_sig.get(cid),
                "sources": src_sig.get(cid),
            },
        }
        result[cid] = scores

    return result


def _origin_key(fwd_id: int, post_id: int | None, fwd_date: datetime.datetime | None) -> tuple | None:
    """Identity of a forward's origin message — the coordination layer's rules verbatim:
    ``(channel, post id)``, fallback ``(channel, original date)``; ``None`` (skip) when
    the row carries neither."""
    if post_id is not None:
        return (fwd_id, post_id)
    if fwd_date is not None:
        return (fwd_id, fwd_date)
    return None


def _scores_origin(
    vacancy_pk: int,
    candidate_pks: list[int],
    before_start: datetime.datetime,
    closure_dt: datetime.datetime,
    after_end: datetime.datetime,
) -> dict[int, dict[str, Any]]:
    """Score O (Content Continuity): does the candidate circulate the *vacancy's
    content stream* — the same origin messages, not merely the same neighbours?

    The structural scores measure role succession, which an unrelated opportunist can
    inherit; shared origin messages are identity-flavoured evidence (the ban-evasion
    account-linking tradition: Niverthi, Verma & Kumar 2022). Origin identity is the
    coordination layer's (:func:`_origin_key`).

    Origins are temporally censored across the closure — content posted after it did
    not exist before it, so a naive before/after origin intersection is empty by
    construction. Both sides are therefore conditioned on origins that predate the
    closure: the vacancy's **content universe** (origins it forwarded in the
    before-window, plus posts it authored) against each candidate's after-window
    forwards of pre-closure-dated origins (the *old* content it circulates). Ochiai
    over the two sets, Score-B style; ``None`` when the universe is empty (nothing to
    continue), ``0.0`` when the candidate circulates no old content.

    Each candidate also carries the **archive-forward count** — shared origins
    *authored by the vacancy itself*, i.e. the candidate re-seeding the closed
    channel's own back-catalogue, the single strongest rebrand tell — and the usual
    hypergeometric/BH calibration of the overlap against the pool of pre-closure
    origins still circulating in the after-window. Blind spot: re-*uploads* get fresh
    authorship from Telegram, so only true forwards register here.
    """
    # The vacancy's content universe: origins it curated (forwarded) in the before-window …
    universe: set[tuple] = set()
    for fwd_id, post_id, fwd_date in (
        Message.objects.alive()
        .filter(channel=vacancy_pk, forwarded_from__isnull=False, date__gte=before_start, date__lt=closure_dt)
        .filter(channel_cutoff_q())
        .values_list("forwarded_from_id", "fwd_from_channel_post", "fwd_from_date")
    ):
        if (key := _origin_key(fwd_id, post_id, fwd_date)) is not None:
            universe.add(key)

    # … plus the posts it authored: its own crawled originals in the before-window …
    universe.update(
        (vacancy_pk, tid)
        for tid in Message.objects.alive()
        .filter(
            channel=vacancy_pk,
            forwarded_from__isnull=True,
            fwd_from_date__isnull=True,
            date__gte=before_start,
            date__lt=closure_dt,
        )
        .filter(channel_cutoff_q())
        .values_list("telegram_id", flat=True)
    )

    # … plus its posts as testified by others' forwards: Telegram attributes every
    # forward to the original author, so an in-target forward of the vacancy whose
    # origin provably predates the closure (origin timestamp before it, or the forward
    # itself made before it) establishes that origin as the vacancy's pre-closure
    # content — including forwards made *after* the closure, because authorship, not
    # co-occurrence, is the claim (archive re-seeding testifies to it just as well).
    for fwd_id, post_id, fwd_date in (
        Message.objects.alive()
        .filter(
            channel__in=Channel.objects.in_target(),
            forwarded_from=vacancy_pk,
            date__gte=before_start,
            date__lte=after_end,
        )
        .filter(Q(fwd_from_date__lt=closure_dt) | Q(date__lt=closure_dt))
        .filter(channel_cutoff_q())
        .values_list("forwarded_from_id", "fwd_from_channel_post", "fwd_from_date")
    ):
        if (key := _origin_key(fwd_id, post_id, fwd_date)) is not None:
            universe.add(key)

    # Each candidate's re-circulated old content: after-window forwards whose origin is
    # dated before the closure. ``fwd_from_date`` is required — an undatable origin
    # cannot be shown to be old, so those rows sit outside both sides of the test.
    cand_origins: dict[int, set[tuple]] = defaultdict(set)
    for ch_id, fwd_id, post_id, fwd_date in (
        Message.objects.alive()
        .filter(
            channel__in=candidate_pks,
            forwarded_from__isnull=False,
            date__gte=closure_dt,
            date__lte=after_end,
            fwd_from_date__lt=closure_dt,
        )
        .filter(channel_cutoff_q())
        .values_list("channel_id", "forwarded_from_id", "fwd_from_channel_post", "fwd_from_date")
    ):
        if (key := _origin_key(fwd_id, post_id, fwd_date)) is not None:
            cand_origins[ch_id].add(key)

    # Null calibration, same scheme as the amplifier/source tests: the pool a
    # candidate's old-content set is drawn from is every pre-closure-dated origin any
    # in-target channel still circulated in the after-window; marked items are the
    # pool origins belonging to the vacancy's universe. Candidates circulating no old
    # content are not tested (no data ≠ evidence of independence), and an empty
    # universe leaves nothing to test at all.
    origin_sig: dict[int, dict[str, float]] = {}
    if candidate_pks and universe:
        population_keys: set[tuple] = set()
        for fwd_id, post_id, fwd_date in (
            Message.objects.alive()
            .filter(
                channel__in=Channel.objects.in_target(),
                forwarded_from__isnull=False,
                date__gte=closure_dt,
                date__lte=after_end,
                fwd_from_date__lt=closure_dt,
            )
            .filter(channel_cutoff_q())
            .values_list("forwarded_from_id", "fwd_from_channel_post", "fwd_from_date")
        ):
            if (key := _origin_key(fwd_id, post_id, fwd_date)) is not None:
                population_keys.add(key)
        marked = len(population_keys & universe)
        tested = [cid for cid in candidate_pks if cand_origins.get(cid)]
        origin_p = {
            cid: _hypergeom_sf(
                len(universe & cand_origins[cid]),
                len(population_keys),
                marked,
                len(cand_origins[cid]),
            )
            for cid in tested
        }
        for cid, q in zip(tested, _bh_adjust([origin_p[c] for c in tested]), strict=True):
            origin_sig[cid] = {"p": _round_p(origin_p[cid]), "q": _round_p(q)}

    result: dict[int, dict[str, Any]] = {}
    u_size = len(universe)
    for cid in candidate_pks:
        r = cand_origins.get(cid, set())
        shared = universe & r
        if not u_size:
            score = None
        elif not r:
            score = 0.0
        else:
            score = round(len(shared) / math.sqrt(u_size * len(r)), 3)
        result[cid] = {
            "score": score,
            "archive_forward_count": sum(1 for key in shared if key[0] == vacancy_pk),
            "significance": origin_sig.get(cid),
        }
    return result


def _scores_temporal(
    orphaned_pks: set[int],
    candidate_pks: list[int],
    closure_dt: datetime.datetime,
    after_end: datetime.datetime,
) -> dict[int, float]:
    """
    Temporal adoption: coverage of the orphaned amplifier set discounted by the mean
    delay before each adopter's first forward.

    For each candidate C: score = coverage / (1 + mean_days_to_first_adoption / 30),
    where coverage = fraction of orphaned channels that adopted C. The denominator is
    the hyperbolic discount function V = A / (1 + kd) of Mazur (1987) with
    k = 1/30 days⁻¹ — the score halves at a 30-day mean delay, but this is NOT an
    exponential half-life (hyperbolic decay is much slower past d = 30 days).
    Mean-then-discount is deliberate: by Jensen's inequality on the convex 1/(1+x),
    1/(1 + mean(d)/30) ≤ mean(1/(1 + d_i/30)), so Pulpit's score is more pessimistic
    on bimodal (fast + slow) adopter sets than the alternative would be.
    """
    total_orphaned = len(orphaned_pks)
    if not total_orphaned or not candidate_pks:
        return dict.fromkeys(candidate_pks, 0.0)

    rows = list(
        Message.objects.alive()
        .filter(
            channel__in=orphaned_pks,
            forwarded_from__in=candidate_pks,
            date__gte=closure_dt,
            date__lte=after_end,
        )
        .filter(channel_cutoff_q())
        .values("forwarded_from_id", "channel_id")
        .annotate(first_date=Min("date"))
    )

    death_ts = closure_dt.timestamp()
    adoption_days: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        fd = r["first_date"]
        if fd.tzinfo is None:
            fd = fd.replace(tzinfo=datetime.timezone.utc)
        days = max(0.0, (fd.timestamp() - death_ts) / 86400)
        adoption_days[r["forwarded_from_id"]].append(days)

    scores: dict[int, float] = {}
    for cid in candidate_pks:
        days_list = adoption_days.get(cid, [])
        if not days_list:
            scores[cid] = 0.0
        else:
            mean_days = sum(days_list) / len(days_list)
            coverage = len(days_list) / total_orphaned
            scores[cid] = round(coverage / (1.0 + mean_days / 30.0), 3)

    return scores


def _successor_ranks(candidates: list[dict[str, Any]], successor_pk: int, measures: set[str]) -> dict[str, int | None]:
    """Competition rank (1-based, ties share the best rank) of the known successor
    on each measure; ``None`` when the successor is unscored on that measure."""
    ranks: dict[str, int | None] = {}
    for m in sorted(measures):
        succ_score = next((c["scores"].get(m) for c in candidates if c["pk"] == successor_pk), None)
        if succ_score is None:
            ranks[m] = None
        else:
            ranks[m] = 1 + sum(1 for c in candidates if (v := c["scores"].get(m)) is not None and v > succ_score)
    return ranks


# ── Per-vacancy analysis ──────────────────────────────────────────────────────


def _analyze_vacancy(
    vac: "ChannelVacancy",
    selected_measures: set[str],
    months_before: int,
    months_after: int,
    max_candidates: int,
) -> dict[str, Any]:
    ch = vac.channel
    closure_date = vac.closure_date
    before_start = datetime.datetime.combine(
        _shift_months(closure_date, -months_before), datetime.time.min, tzinfo=datetime.timezone.utc
    )
    closure_dt = datetime.datetime.combine(closure_date, datetime.time.min, tzinfo=datetime.timezone.utc)
    after_end = datetime.datetime.combine(
        _shift_months(closure_date, months_after), datetime.time.max, tzinfo=datetime.timezone.utc
    )

    # Orphaned amplifiers: in-target channels that forwarded from the vacancy in the
    # before window *while they were in-target at that date* (period-aware) — the shared
    # canonical definition, so the card, the list, and this export agree by construction.
    orphaned_pks = orphaned_amplifier_pks(ch, closure_date, months_before)

    raw_cands = list(
        Message.objects.alive()
        .filter(
            channel__in=orphaned_pks,
            forwarded_from__in=Channel.objects.in_target(),
            date__gte=closure_dt,
            date__lte=after_end,
        )
        .filter(channel_cutoff_q())
        .exclude(forwarded_from=ch)
        .values("forwarded_from")
        .annotate(amplifier_count=Count("channel", distinct=True), last_forwarded=Max("date"))
        .order_by("-amplifier_count", "forwarded_from")[:max_candidates]
    )

    cand_pks = [r["forwarded_from"] for r in raw_cands]
    cand_meta: dict[int, dict] = {r["forwarded_from"]: r for r in raw_cands}

    cand_channels: dict[int, Channel] = {
        c.pk: c
        for c in Channel.objects.filter(pk__in=cand_pks)
        .prefetch_related("channel_labels__label__group")
        .annotate(first_msg=Min("message_set__date"))
    }

    score_map: dict[int, dict[str, Any]] = {cid: {} for cid in cand_pks}

    abc_sel = selected_measures & {"AMPLIFIER_JACCARD", "NEW_ADOPTERS", "STRUCTURAL_EQUIV", "BROKERAGE"}
    if abc_sel:
        for cid, s in _scores_abc(ch.pk, orphaned_pks, cand_pks, before_start, closure_dt, after_end, abc_sel).items():
            score_map[cid].update(s)

    origin_map: dict[int, dict[str, Any]] = {}
    if "ORIGIN_OVERLAP" in selected_measures:
        origin_map = _scores_origin(ch.pk, cand_pks, before_start, closure_dt, after_end)
        for cid, o in origin_map.items():
            score_map[cid]["ORIGIN_OVERLAP"] = o["score"]

    if "TEMPORAL" in selected_measures:
        for cid, s in _scores_temporal(orphaned_pks, cand_pks, closure_dt, after_end).items():
            score_map[cid]["TEMPORAL"] = s

    candidates = []
    for cid in cand_pks:
        c = cand_channels.get(cid)
        if not c:
            continue
        lf = cand_meta[cid]["last_forwarded"]
        fm = c.first_msg
        extras = score_map[cid].get(EXTRAS_KEY) or {}
        origin = origin_map.get(cid) or {}
        significance = extras.get("significance") or {"amplifiers": None, "sources": None}
        significance["origins"] = origin.get("significance")
        rec: dict[str, Any] = {
            "pk": c.pk,
            "title": c.title,
            "url": c.get_absolute_url(),
            "org_color": c.current_label.color if c.current_label else None,
            "amplifier_count": cand_meta[cid]["amplifier_count"],
            "last_forwarded": lf.strftime("%b %-d, %Y") if lf else None,
            "last_forwarded_iso": lf.date().isoformat() if lf else None,
            "first_activity": fm.strftime("%b %-d, %Y") if fm else None,
            "first_activity_iso": fm.date().isoformat() if fm else None,
            "scores": {m: score_map[cid].get(m) for m in sorted(selected_measures)},
            "new_adopter_count": extras.get("new_adopter_count"),
            "archive_forward_count": origin.get("archive_forward_count"),
            "significance": significance,
        }
        if vac.successor_id and cid == vac.successor_id:
            rec["is_successor"] = True
        candidates.append(rec)

    candidates.sort(key=lambda r: r["first_activity_iso"] or "")

    successor: dict[str, Any] | None = None
    if vac.successor_id:
        successor = {
            "pk": vac.successor_id,
            "title": vac.successor.title,
            "in_candidates": any(r.get("is_successor") for r in candidates),
            "ranks": _successor_ranks(candidates, vac.successor_id, selected_measures),
        }

    return {
        "pk": ch.pk,
        "title": ch.title,
        "url": ch.get_absolute_url(),
        "closure_date": closure_date.isoformat(),
        "note": vac.note or "",
        "orphaned_count": len(orphaned_pks),
        "candidates": candidates,
        "successor": successor,
    }


# ── Main entry point ──────────────────────────────────────────────────────────


def compute_vacancy_analysis(
    selected_measures: set[str],
    months_before: int = 12,
    months_after: int = 24,
    max_candidates: int = 30,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Score replacement candidates for all vacancies.

    Returns a payload dict suitable for serialisation to vacancy_analysis.json.
    """
    vacancies = list(ChannelVacancy.objects.select_related("channel", "successor").all())
    results: list[dict[str, Any]] = []

    for vac in vacancies:
        if progress_callback:
            progress_callback(vac.channel.title or str(vac.channel.pk))
        results.append(
            _analyze_vacancy(
                vac,
                selected_measures,
                months_before,
                months_after,
                max_candidates,
            )
        )

    return {
        "selected_measures": sorted(selected_measures),
        "measure_labels": {k: MEASURE_LABELS[k] for k in sorted(selected_measures)},
        "months_before": months_before,
        "months_after": months_after,
        "vacancies": results,
        "validation": _validation_summary(results, selected_measures),
    }


def _validation_summary(results: list[dict[str, Any]], selected_measures: set[str]) -> dict[str, Any] | None:
    """Retrieval-style validation against the analyst-labelled known successors.

    For each measure, over the vacancies whose known successor is set: how often the
    successor ranks first / in the top 3 / in the top 5 among the scored candidates
    (hits@k), and the mean reciprocal rank. A successor missing from the candidate
    list (or unscored on a measure) counts as a miss — the honest denominator is all
    labelled vacancies, not just the retrievable ones.
    """
    labelled = [r for r in results if r.get("successor")]
    if not labelled:
        return None
    per_measure: dict[str, dict[str, float | int]] = {}
    for m in sorted(selected_measures):
        ranks = [r["successor"]["ranks"].get(m) for r in labelled]
        per_measure[m] = {
            "hits_at_1": sum(1 for rk in ranks if rk is not None and rk <= 1),
            "hits_at_3": sum(1 for rk in ranks if rk is not None and rk <= 3),
            "hits_at_5": sum(1 for rk in ranks if rk is not None and rk <= 5),
            "mrr": round(sum(1.0 / rk for rk in ranks if rk) / len(labelled), 3),
        }
    return {"n_labelled": len(labelled), "per_measure": per_measure}
