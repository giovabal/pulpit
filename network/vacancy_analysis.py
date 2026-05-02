"""Vacancy succession analysis: score replacement candidates for dead channels."""

from __future__ import annotations

import calendar
import datetime
import math
from collections import defaultdict
from typing import Any, Callable

from django.db.models import Count, Max, Min

from webapp.models import Channel, ChannelVacancy, Message

import networkx as nx
import numpy as np

VALID_VACANCY_MEASURES: frozenset[str] = frozenset(
    {"AMPLIFIER_JACCARD", "STRUCTURAL_EQUIV", "BROKERAGE", "CASCADE_OVERLAP", "PPR", "TEMPORAL"}
)

ALL_VACANCY_MEASURES: list[str] = [
    "AMPLIFIER_JACCARD",
    "STRUCTURAL_EQUIV",
    "BROKERAGE",
    "CASCADE_OVERLAP",
    "PPR",
    "TEMPORAL",
]

MEASURE_LABELS: dict[str, str] = {
    "AMPLIFIER_JACCARD": "Amplifier Jaccard",
    "STRUCTURAL_EQUIV": "Structural Equivalence",
    "BROKERAGE": "Brokerage",
    "CASCADE_OVERLAP": "Cascade Overlap (SIR)",
    "PPR": "Pers. PageRank",
    "TEMPORAL": "Temporal Adoption",
}

_SIR_GAMMA = 0.3
_SIR_REACH_THRESHOLD = 0.25  # fraction of runs a node must be infected to count as "reached"


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


# ── SIR for Cascade Overlap ───────────────────────────────────────────────────


def _run_sir_pks(
    adj: dict[int, list[tuple[int, float]]],
    all_nodes: set[int],
    seed: int,
    rng: np.random.Generator,
) -> set[int]:
    """Single SIR run keyed by channel PKs. Returns the set of ever-infected nodes."""
    susceptible = all_nodes - {seed}
    infected = {seed}
    ever: set[int] = {seed}

    while infected:
        infected_list = list(infected)
        newly_recovered = {
            n for n, r in zip(infected_list, rng.random(len(infected_list)) < _SIR_GAMMA, strict=True) if r
        }
        newly_infected: set[int] = set()
        for node in infected_list:
            neighbors = adj.get(node, [])
            if not neighbors:
                continue
            succs = [s for s, _ in neighbors]
            weights = np.array([w for _, w in neighbors])
            hits = rng.random(len(succs)) < weights
            for succ, hit in zip(succs, hits, strict=True):
                if hit and succ in susceptible:
                    newly_infected.add(succ)
        susceptible -= newly_infected
        infected = (infected | newly_infected) - newly_recovered
        ever |= newly_infected

    return ever


def _build_spread_adj(
    channel_pks: list[int],
    date_from: datetime.datetime,
    date_to: datetime.datetime,
) -> tuple[dict[int, list[tuple[int, float]]], set[int]]:
    """
    Build spread adjacency: source_pk → [(amplifier_pk, weight), …]

    Direction matches information flow: source is forwarded by amplifier.
    Weight = forward_count_by_amplifier / total_forwards_by_amplifier in window.
    """
    if date_from >= date_to or not channel_pks:
        return {pk: [] for pk in channel_pks}, set(channel_pks)

    rows = list(
        Message.objects.filter(
            channel__in=channel_pks,
            forwarded_from__in=channel_pks,
            date__gte=date_from,
            date__lt=date_to,
        )
        .values("channel_id", "forwarded_from_id")
        .annotate(count=Count("id"))
    )

    total_per_amplifier: dict[int, int] = defaultdict(int)
    for r in rows:
        total_per_amplifier[r["channel_id"]] += r["count"]

    adj: dict[int, list[tuple[int, float]]] = {pk: [] for pk in channel_pks}
    for r in rows:
        w = r["count"] / total_per_amplifier[r["channel_id"]]
        adj.setdefault(r["forwarded_from_id"], []).append((r["channel_id"], min(w, 1.0)))

    return adj, set(channel_pks)


def _majority_reach(
    adj: dict[int, list[tuple[int, float]]],
    all_nodes: set[int],
    seed: int,
    runs: int,
    rng: np.random.Generator,
) -> frozenset[int]:
    """Run SIR `runs` times from seed; return nodes infected in ≥ threshold fraction of runs."""
    if seed not in all_nodes:
        return frozenset()
    counts: dict[int, int] = defaultdict(int)
    for _ in range(runs):
        for n in _run_sir_pks(adj, all_nodes, seed, rng):
            counts[n] += 1
    min_count = max(1, int(runs * _SIR_REACH_THRESHOLD))
    return frozenset(n for n, c in counts.items() if c >= min_count and n != seed)


# ── Per-algorithm scorers ─────────────────────────────────────────────────────


def _scores_abc(
    vacancy_pk: int,
    orphaned_pks: set[int],
    candidate_pks: list[int],
    before_start: datetime.datetime,
    death_dt: datetime.datetime,
    after_end: datetime.datetime,
    selected: set[str],
) -> dict[int, dict[str, float | None]]:
    """Scores A (Amplifier Jaccard), B (Structural Equivalence), C (Brokerage)."""
    total_orphaned = len(orphaned_pks)

    amp_counts: dict[int, int] = {}
    if selected & {"AMPLIFIER_JACCARD", "STRUCTURAL_EQUIV"}:
        for r in (
            Message.objects.filter(
                channel__in=orphaned_pks,
                forwarded_from__in=candidate_pks,
                date__gte=death_dt,
                date__lte=after_end,
            )
            .values("forwarded_from_id")
            .annotate(amp_count=Count("channel", distinct=True))
        ):
            amp_counts[r["forwarded_from_id"]] = r["amp_count"]

    vacancy_out_pks: set[int] = set()
    vacancy_src_org_pks: set[int] = set()
    if selected & {"STRUCTURAL_EQUIV", "BROKERAGE"}:
        for r in (
            Message.objects.filter(
                channel=vacancy_pk,
                forwarded_from__isnull=False,
                date__gte=before_start,
                date__lt=death_dt,
            )
            .values("forwarded_from_id", "forwarded_from__organization_id")
            .distinct()
        ):
            vacancy_out_pks.add(r["forwarded_from_id"])
            if r["forwarded_from__organization_id"]:
                vacancy_src_org_pks.add(r["forwarded_from__organization_id"])

    orphaned_org_map: dict[int, int] = {}
    vacancy_org_pairs: frozenset[tuple[int, int]] = frozenset()
    if "BROKERAGE" in selected:
        orphaned_org_map = dict(
            Channel.objects.filter(pk__in=orphaned_pks, organization__isnull=False).values_list("pk", "organization_id")
        )
        vacancy_amp_org_pks = set(orphaned_org_map.values())
        vacancy_org_pairs = frozenset((s, a) for s in vacancy_src_org_pks for a in vacancy_amp_org_pks)

    cand_out_pks: dict[int, set[int]] = defaultdict(set)
    cand_src_org_pks: dict[int, set[int]] = defaultdict(set)
    if selected & {"STRUCTURAL_EQUIV", "BROKERAGE"}:
        for r in (
            Message.objects.filter(
                channel__in=candidate_pks,
                forwarded_from__isnull=False,
                date__gte=death_dt,
                date__lte=after_end,
            )
            .values("channel_id", "forwarded_from_id", "forwarded_from__organization_id")
            .distinct()
        ):
            cand_out_pks[r["channel_id"]].add(r["forwarded_from_id"])
            if r["forwarded_from__organization_id"]:
                cand_src_org_pks[r["channel_id"]].add(r["forwarded_from__organization_id"])

    cand_amp_org_pks: dict[int, set[int]] = defaultdict(set)
    if "BROKERAGE" in selected:
        for r in (
            Message.objects.filter(
                channel__in=orphaned_pks,
                forwarded_from__in=candidate_pks,
                date__gte=death_dt,
                date__lte=after_end,
            )
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
            scores["AMPLIFIER_JACCARD"] = round(a_count / total_orphaned, 3) if total_orphaned else 0.0

        if "STRUCTURAL_EQUIV" in selected:
            cos_in = math.sqrt(a_count / total_orphaned) if total_orphaned else 0.0
            cos_out = _cosine(vacancy_out_pks, cand_out_pks.get(cid, set()))
            scores["STRUCTURAL_EQUIV"] = round(0.5 * cos_in + 0.5 * cos_out, 3)

        if "BROKERAGE" in selected:
            cand_org_pairs = frozenset(
                (s, a) for s in cand_src_org_pks.get(cid, set()) for a in cand_amp_org_pks.get(cid, set())
            )
            scores["BROKERAGE"] = round(_jaccard(vacancy_org_pairs, cand_org_pairs), 3) if vacancy_org_pairs else None

        result[cid] = scores

    return result


def _scores_cascade(
    vacancy_pk: int,
    candidate_pks: list[int],
    all_channel_pks: list[int],
    before_start: datetime.datetime,
    death_dt: datetime.datetime,
    after_end: datetime.datetime,
    sir_runs: int,
    rng: np.random.Generator,
) -> dict[int, float]:
    """Cascade Overlap: Jaccard similarity of SIR content-reach sets (vacancy before vs candidate after)."""
    before_channels = list({*all_channel_pks, vacancy_pk})
    before_adj, before_nodes = _build_spread_adj(before_channels, before_start, death_dt)
    after_channels = [pk for pk in all_channel_pks if pk != vacancy_pk]
    after_adj, after_nodes = _build_spread_adj(after_channels, death_dt, after_end)

    v_reach = _majority_reach(before_adj, before_nodes, vacancy_pk, sir_runs, rng)
    if not v_reach:
        return dict.fromkeys(candidate_pks, 0.0)

    scores: dict[int, float] = {}
    for cid in candidate_pks:
        c_reach = _majority_reach(after_adj, after_nodes, cid, sir_runs, rng)
        intersection = len(v_reach & c_reach)
        union = len(v_reach | c_reach)
        scores[cid] = round(intersection / union, 3) if union else 0.0

    return scores


def _scores_ppr(
    graph: nx.DiGraph,
    pk_to_node: dict[int, str],
    orphaned_pks: set[int],
    candidate_pks: list[int],
    ppr_alpha: float,
) -> dict[int, float]:
    """
    Personalized PageRank from orphaned amplifiers on the reversed graph.

    The reversed graph is used so the random walk travels upstream from orphaned
    channels toward their content sources; candidates with high PPR are structurally
    situated in the same upstream supply chain as the vacancy.
    """
    orphaned_nodes = [pk_to_node[pk] for pk in orphaned_pks if pk in pk_to_node]
    if not orphaned_nodes or graph.number_of_nodes() <= 1:
        return dict.fromkeys(candidate_pks, 0.0)

    rev = graph.reverse(copy=False)
    per_node = 1.0 / len(orphaned_nodes)
    personalization = dict.fromkeys(rev.nodes(), 0.0)
    for n in orphaned_nodes:
        personalization[n] = per_node

    try:
        ppr = nx.pagerank(rev, alpha=ppr_alpha, personalization=personalization, max_iter=200, tol=1e-6)
    except nx.PowerIterationFailedConvergence:
        return dict.fromkeys(candidate_pks, 0.0)

    raw = {cid: ppr.get(pk_to_node.get(cid, ""), 0.0) for cid in candidate_pks}
    max_val = max(raw.values(), default=0.0)
    if max_val <= 0.0:
        return dict.fromkeys(candidate_pks, 0.0)
    return {cid: round(v / max_val, 3) for cid, v in raw.items()}


def _scores_temporal(
    orphaned_pks: set[int],
    candidate_pks: list[int],
    death_dt: datetime.datetime,
    after_end: datetime.datetime,
) -> dict[int, float]:
    """
    Temporal adoption: recency-weighted coverage fraction.

    For each candidate C, score = (fraction of orphaned channels that adopted C)
    divided by (1 + mean_days_to_first_adoption / 30).  A 30-day half-life rewards
    candidates adopted quickly by the orphaned audience.
    """
    total_orphaned = len(orphaned_pks)
    if not total_orphaned or not candidate_pks:
        return dict.fromkeys(candidate_pks, 0.0)

    rows = list(
        Message.objects.filter(
            channel__in=orphaned_pks,
            forwarded_from__in=candidate_pks,
            date__gte=death_dt,
            date__lte=after_end,
        )
        .values("forwarded_from_id", "channel_id")
        .annotate(first_date=Min("date"))
    )

    death_ts = death_dt.timestamp()
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
    graph: nx.DiGraph,
    pk_to_node: dict[int, str],
    all_channel_pks: list[int],
    selected_measures: set[str],
    months_before: int,
    months_after: int,
    max_candidates: int,
    sir_runs: int,
    ppr_alpha: float,
    only_after_vacancy: bool,
    rng: np.random.Generator,
) -> dict[str, Any]:
    ch = vac.channel
    death = vac.death_date
    before_start = datetime.datetime.combine(
        _shift_months(death, -months_before), datetime.time.min, tzinfo=datetime.timezone.utc
    )
    death_dt = datetime.datetime.combine(death, datetime.time.min, tzinfo=datetime.timezone.utc)
    after_end = datetime.datetime.combine(
        _shift_months(death, months_after), datetime.time.max, tzinfo=datetime.timezone.utc
    )

    orphaned_pks: set[int] = set(
        Channel.objects.interesting()
        .filter(
            message_set__forwarded_from=ch,
            message_set__date__gte=before_start,
            message_set__date__lt=death_dt,
        )
        .distinct()
        .values_list("pk", flat=True)
    )

    raw_cands = list(
        Message.objects.filter(
            channel__in=orphaned_pks,
            forwarded_from__in=Channel.objects.interesting(),
            date__gte=death_dt,
            date__lte=after_end,
        )
        .exclude(forwarded_from=ch)
        .values("forwarded_from")
        .annotate(amplifier_count=Count("channel", distinct=True), last_forwarded=Max("date"))
        .order_by("-amplifier_count")[:max_candidates]
    )

    cand_pks = [r["forwarded_from"] for r in raw_cands]
    cand_meta: dict[int, dict] = {r["forwarded_from"]: r for r in raw_cands}

    cand_qs = (
        Channel.objects.filter(pk__in=cand_pks)
        .select_related("organization")
        .annotate(first_msg=Min("message_set__date"))
    )
    if only_after_vacancy:
        cand_qs = cand_qs.filter(first_msg__gte=death_dt)
    cand_channels: dict[int, Channel] = {c.pk: c for c in cand_qs}

    score_map: dict[int, dict[str, float | None]] = {cid: {} for cid in cand_pks}

    abc_sel = selected_measures & {"AMPLIFIER_JACCARD", "STRUCTURAL_EQUIV", "BROKERAGE"}
    if abc_sel:
        for cid, s in _scores_abc(ch.pk, orphaned_pks, cand_pks, before_start, death_dt, after_end, abc_sel).items():
            score_map[cid].update(s)

    if "CASCADE_OVERLAP" in selected_measures:
        for cid, s in _scores_cascade(
            ch.pk, cand_pks, all_channel_pks, before_start, death_dt, after_end, sir_runs, rng
        ).items():
            score_map[cid]["CASCADE_OVERLAP"] = s

    if "PPR" in selected_measures:
        for cid, s in _scores_ppr(graph, pk_to_node, orphaned_pks, cand_pks, ppr_alpha).items():
            score_map[cid]["PPR"] = s

    if "TEMPORAL" in selected_measures:
        for cid, s in _scores_temporal(orphaned_pks, cand_pks, death_dt, after_end).items():
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
            "org_color": c.organization.color if c.organization else None,
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
        "death_date": death.isoformat(),
        "note": vac.note or "",
        "orphaned_count": len(orphaned_pks),
        "candidates": candidates,
    }


# ── Main entry point ──────────────────────────────────────────────────────────


def compute_vacancy_analysis(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    selected_measures: set[str],
    months_before: int = 12,
    months_after: int = 24,
    max_candidates: int = 30,
    sir_runs: int = 200,
    ppr_alpha: float = 0.85,
    only_after_vacancy: bool = True,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Score replacement candidates for all vacancies.

    Returns a payload dict suitable for serialisation to vacancy_analysis.json.
    """
    vacancies = list(ChannelVacancy.objects.select_related("channel__organization").all())

    pk_to_node: dict[int, str] = {data["channel"].pk: node_id for node_id, data in channel_dict.items()}
    all_channel_pks: list[int] = [data["channel"].pk for data in channel_dict.values()]

    rng = np.random.default_rng(42)
    results: list[dict[str, Any]] = []

    for vac in vacancies:
        if progress_callback:
            progress_callback(vac.channel.title or str(vac.channel.pk))
        results.append(
            _analyze_vacancy(
                vac,
                graph,
                pk_to_node,
                all_channel_pks,
                selected_measures,
                months_before,
                months_after,
                max_candidates,
                sir_runs,
                ppr_alpha,
                only_after_vacancy,
                rng,
            )
        )

    return {
        "selected_measures": sorted(selected_measures),
        "measure_labels": {k: MEASURE_LABELS[k] for k in sorted(selected_measures)},
        "months_before": months_before,
        "months_after": months_after,
        "only_after_vacancy": only_after_vacancy,
        "vacancies": results,
    }
