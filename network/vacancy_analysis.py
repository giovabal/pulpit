"""Vacancy succession analysis: score replacement candidates for dead channels."""

from __future__ import annotations

import calendar
import datetime
import math
from collections import defaultdict
from typing import Any, Callable

from django.db.models import Count, Max, Min

from network.utils import channel_cutoff_q
from webapp.models import Channel, ChannelAttribution, ChannelVacancy, Message

VALID_VACANCY_MEASURES: frozenset[str] = frozenset({"AMPLIFIER_JACCARD", "STRUCTURAL_EQUIV", "BROKERAGE", "TEMPORAL"})

ALL_VACANCY_MEASURES: list[str] = [
    "AMPLIFIER_JACCARD",
    "STRUCTURAL_EQUIV",
    "BROKERAGE",
    "TEMPORAL",
]

MEASURE_LABELS: dict[str, str] = {
    "AMPLIFIER_JACCARD": "Amplifier Coverage",
    "STRUCTURAL_EQUIV": "Neighbour-set Equivalence",
    "BROKERAGE": "Brokerage overlap",
    "TEMPORAL": "Temporal Adoption",
}


# ── Utilities ─────────────────────────────────────────────────────────────────


def _shift_months(d: datetime.date, n: int) -> datetime.date:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _cosine(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / (math.sqrt(len(a)) * math.sqrt(len(b)))


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
    """Scores A (Amplifier Coverage), B (Neighbour-set Equivalence), C (Brokerage overlap).

    Note: score B here is a *binary* (Ochiai) cosine over in/out neighbour **sets** —
    it ignores tie strength and is computed between one vacancy and each candidate. It
    is deliberately distinct from the weighted Lorrain & White (1971) structural-
    equivalence *matrix* computed across all graph nodes in
    :func:`network.community_stats._compute_structural_equivalence`; the two answer
    related questions with different maths, hence the separate "Neighbour-set
    Equivalence" label.
    """
    total_orphaned = len(orphaned_pks)

    amp_counts: dict[int, int] = {}
    if "AMPLIFIER_JACCARD" in selected:
        for r in (
            Message.objects.alive()
            .filter(
                channel__in=orphaned_pks,
                forwarded_from__in=candidate_pks,
                date__gte=closure_dt,
                date__lte=after_end,
            )
            .filter(channel_cutoff_q())
            .values("forwarded_from_id")
            .annotate(amp_count=Count("channel", distinct=True))
        ):
            amp_counts[r["forwarded_from_id"]] = r["amp_count"]

    # Each candidate's in-amplifier set: in-target channels that forwarded from the
    # candidate in the after-window. Restricted to in-target so it shares the universe
    # of the vacancy's amplifier set (orphaned_pks ⊆ in-target), giving a well-defined
    # cosine for STRUCTURAL_EQUIV. Note |orphaned_pks ∩ cand_in_pks[cid]| == amp_count.
    cand_in_pks: dict[int, set[int]] = defaultdict(set)
    if "STRUCTURAL_EQUIV" in selected:
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
                vacancy_out_rows.append((fwd_id, fwd_date.date()))

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
                cand_out_rows.append((ch_id, fwd_id, fwd_date.date()))

    orphaned_org_map: dict[int, int] = {}
    vacancy_org_pairs: frozenset[tuple[int, int]] = frozenset()
    cand_src_org_pks: dict[int, set[int]] = defaultdict(set)
    cand_amp_org_pks: dict[int, set[int]] = defaultdict(set)
    if "BROKERAGE" in selected:
        # Attribution is time-bounded: resolve each channel's org as of the relevant date — the
        # forward's date for source edges, the closure date for the orphaned amplifiers themselves.
        closure_date = closure_dt.date()
        attr_cache = ChannelAttribution.build_cache(
            vacancy_out_pks | {fwd_id for _, fwd_id, _ in cand_out_rows} | set(orphaned_pks)
        )
        vacancy_src_org_pks = {
            org for fwd_id, when in vacancy_out_rows if (org := ChannelAttribution.org_at(attr_cache, fwd_id, when))
        }
        orphaned_org_map = {
            pk: org for pk in orphaned_pks if (org := ChannelAttribution.org_at(attr_cache, pk, closure_date))
        }
        vacancy_amp_org_pks = set(orphaned_org_map.values())
        vacancy_org_pairs = frozenset((s, a) for s in vacancy_src_org_pks for a in vacancy_amp_org_pks)
        for ch_id, fwd_id, when in cand_out_rows:
            org = ChannelAttribution.org_at(attr_cache, fwd_id, when)
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

    result: dict[int, dict[str, float | None]] = {}
    for cid in candidate_pks:
        scores: dict[str, float | None] = {}
        a_count = amp_counts.get(cid, 0)

        if "AMPLIFIER_JACCARD" in selected:
            # Coverage / recall — the fraction of the vacancy's orphaned amplifiers
            # that also amplify this candidate, i.e. |A ∩ B| / |A|. This is an
            # asymmetric overlap measure, NOT a Jaccard (which divides by |A ∪ B|);
            # the token is kept verbatim only for saved-config / JS compatibility.
            scores["AMPLIFIER_JACCARD"] = round(a_count / total_orphaned, 3) if total_orphaned else 0.0

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

        result[cid] = scores

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
    # before window *while they were in-target at that date* — period-aware, matching the
    # graph pipeline's channel_cutoff_q() chokepoint (built from the Message side so the
    # cutoff applies to each forwarding message's own channel and date).
    orphaned_pks: set[int] = set(
        Message.objects.alive()
        .filter(
            channel__in=Channel.objects.in_target(),
            forwarded_from=ch,
            date__gte=before_start,
            date__lt=closure_dt,
        )
        .filter(channel_cutoff_q())
        .values_list("channel_id", flat=True)
        .distinct()
    )

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
        .order_by("-amplifier_count")[:max_candidates]
    )

    cand_pks = [r["forwarded_from"] for r in raw_cands]
    cand_meta: dict[int, dict] = {r["forwarded_from"]: r for r in raw_cands}

    cand_channels: dict[int, Channel] = {
        c.pk: c
        for c in Channel.objects.filter(pk__in=cand_pks)
        .prefetch_related("attributions__organization")
        .annotate(first_msg=Min("message_set__date"))
    }

    score_map: dict[int, dict[str, float | None]] = {cid: {} for cid in cand_pks}

    abc_sel = selected_measures & {"AMPLIFIER_JACCARD", "STRUCTURAL_EQUIV", "BROKERAGE"}
    if abc_sel:
        for cid, s in _scores_abc(ch.pk, orphaned_pks, cand_pks, before_start, closure_dt, after_end, abc_sel).items():
            score_map[cid].update(s)

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
        rec: dict[str, Any] = {
            "pk": c.pk,
            "title": c.title,
            "url": c.get_absolute_url(),
            "org_color": c.current_organization.color if c.current_organization else None,
            "amplifier_count": cand_meta[cid]["amplifier_count"],
            "last_forwarded": lf.strftime("%b %-d, %Y") if lf else None,
            "last_forwarded_iso": lf.date().isoformat() if lf else None,
            "first_activity": fm.strftime("%b %-d, %Y") if fm else None,
            "first_activity_iso": fm.date().isoformat() if fm else None,
            "scores": {m: score_map[cid].get(m) for m in sorted(selected_measures)},
        }
        candidates.append(rec)

    candidates.sort(key=lambda r: r["first_activity_iso"] or "")

    return {
        "pk": ch.pk,
        "title": ch.title,
        "url": ch.get_absolute_url(),
        "closure_date": closure_date.isoformat(),
        "note": vac.note or "",
        "orphaned_count": len(orphaned_pks),
        "candidates": candidates,
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
    vacancies = list(ChannelVacancy.objects.select_related("channel").all())
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
    }
