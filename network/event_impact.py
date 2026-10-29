"""Event impact: did the network change when a recorded event happened? (``--event-impact``)

The analyst records events (Manage → Events: a date, a subject, a type and, optionally, the labels the
event concerns). For each event this module fits an **interrupted time series** to the weekly activity
of the network around the event's date:

* an **unscoped** event (no labels) — segmented regression on the whole network's series,
  ``y = β0 + β1·t + β2·post + β3·t·post`` with t in weeks from the event's week (Wagner et al. 2002;
  Bernal, Cummins & Gasparrini 2017): β2 is the **level change** at the event, β3 the **slope change**;
* a **scoped** event (e.g. Nation: Germany) — a *comparative* interrupted time series (Linden 2015):
  the series of the channels holding one of the event's labels at each message's date (*affected*)
  stacked with the series of the other observed channels (*comparison*), with the group and its
  interactions added; the effects are the group × post terms, so a movement-wide shift that hits both
  groups alike cancels out.

Weeks run Monday to Sunday in ``TIME_ZONE`` local days, the convention of every ``__date`` filter in the
pipeline. Count metrics are modelled on log(1 + count) — a level change is then about a proportional
change, robust to the network's growth — and share metrics on the share itself, a week whose
denominator is below ``MIN_SHARE_DENOMINATOR`` left missing.

**Inference.** Weekly series are autocorrelated, so the OLS standard errors are replaced by Newey–West
heteroskedasticity- and autocorrelation-consistent ones (Bartlett kernel, lag ⌊4(T/100)^{2/9}⌋; Newey &
West 1987, 1994), computed within each stacked series. And because short, bursty series strain any
distributional assumption, each effect also gets an **in-time placebo** p-value (Abadie, Diamond &
Hainmueller 2015; Bernal et al. 2018): the same model refitted with the break at every other admissible
week — its whole window inside the data and more than half a window from any recorded event — and the
share of placebo effects at least as large as the observed one. Benjamini–Hochberg q-values control the
false-discovery rate across events × metrics, per effect.

Everything is read inside the export's scope: the observed channels of the full-range graph, the
in-target period gate (``channel_cutoff_q``), the date window, and the citation events ``build_graph``
counts (:func:`network.graph_builder.forward_messages_qs` / :func:`~network.graph_builder.reference_rows_qs`).
"""

import datetime
import math
from collections import defaultdict
from typing import Any

from django.db.models import BooleanField, ExpressionWrapper
from django.utils import timezone

from network import periods as _periods
from network.graph_builder import forward_messages_qs, reference_rows_qs
from network.near_copies import forward_header_q
from network.parameters import FixedParameter
from network.robustness.null_model import bh_adjust
from network.utils import channel_cutoff_q, dead_leaf_ids, make_date_q

import networkx as nx
import numpy as np

#: Weeks on each side of the event's week (``--event-window-weeks``).
EVENT_WINDOW_WEEKS_DEFAULT = 26
#: A weekly share whose denominator is smaller is missing rather than noise.
MIN_SHARE_DENOMINATOR = 5
#: Non-missing weeks needed on each side of the break for a fit.
MIN_WEEKS_PER_SIDE = 8
#: Placebo breaks are kept this fraction of a window away from every recorded event.
PLACEBO_EXCLUSION_FRACTION = 0.5
#: Fewer admissible placebo weeks than this and the placebo p is reported as too coarse to read.
MIN_PLACEBOS = 19

#: (key, label, kind): ``count`` metrics are modelled on log(1 + count), ``share`` metrics on the share.
METRICS: tuple[tuple[str, str, str], ...] = (
    ("messages", "Messages posted", "count"),
    ("forwards", "Forwards posted", "count"),
    ("active_channels", "Active channels", "count"),
    ("new_channels", "New channels (first message)", "count"),
    ("citations", "In-scope citations", "count"),
    ("imported_share", "Imported share (forwards from outside the scope)", "share"),
    ("concentration", "Citation concentration (Herfindahl)", "share"),
)
#: Prefix of the per-partition-group cross-label share metrics (``cross_label:<group id>``).
CROSS_LABEL_PREFIX = "cross_label:"

WEEK_RULE = "Monday–Sunday weeks of local calendar days (TIME_ZONE); the event's own week counts as post"
PLACEBO_RULE = (
    "every week whose full ±window lies inside the data and that is more than half a window from every recorded event"
)
MEMBERSHIP_RULE = (
    "a channel is affected by a scoped event when it holds one of the event's labels — or a child of a container "
    "label — at the message's date; the comparison group is every other observed channel"
)

_SOURCE = "network/event_impact.py"

#: The values fixed in this module (``PARAMETERS.md``); the window is a run option.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Event impact: weeks",
        value=WEEK_RULE,
        scope="event_impact",
        affects="How messages are bucketed into the weekly series and on which side of the break the event falls.",
        source=f"{_SOURCE}: WEEK_RULE",
    ),
    FixedParameter(
        name="Event impact: minimum share denominator",
        value=MIN_SHARE_DENOMINATOR,
        scope="event_impact",
        affects="A weekly share (imported, cross-label, concentration) resting on fewer events is left missing.",
        source=f"{_SOURCE}: MIN_SHARE_DENOMINATOR",
    ),
    FixedParameter(
        name="Event impact: minimum weeks per side",
        value=MIN_WEEKS_PER_SIDE,
        scope="event_impact",
        affects="A metric needs this many non-missing weeks before and after the event to be fitted.",
        source=f"{_SOURCE}: MIN_WEEKS_PER_SIDE",
    ),
    FixedParameter(
        name="Event impact: placebo breaks",
        value=PLACEBO_RULE,
        scope="event_impact",
        affects="The in-time placebo distribution each effect's empirical p-value is read from.",
        source=f"{_SOURCE}: PLACEBO_RULE",
        note="In-time placebo: Abadie, Diamond & Hainmueller (2015).",
    ),
    FixedParameter(
        name="Event impact: affected channels",
        value=MEMBERSHIP_RULE,
        scope="event_impact",
        affects="The two groups of a scoped event's comparative interrupted time series.",
        source=f"{_SOURCE}: MEMBERSHIP_RULE",
        note="Comparative ITS: Linden (2015).",
    ),
    FixedParameter(
        name="Event impact: standard errors",
        value="Newey–West HAC, Bartlett kernel, lag floor(4 (T/100)^(2/9)), within each stacked series",
        scope="event_impact",
        affects="The HAC p-values of the level and slope changes.",
        source=f"{_SOURCE}: _ols_hac",
        note="Newey & West (1987, 1994).",
    ),
)


# ── Events ────────────────────────────────────────────────────────────────────────────────────────


def load_events(start: datetime.date | None = None, end: datetime.date | None = None) -> list[dict[str, Any]]:
    """The recorded events inside ``[start, end]``, oldest first, each with its type and label scope."""
    from events.models import Event

    qs = Event.objects.select_related("action").prefetch_related("labels__group").order_by("date", "pk")
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    return [
        {
            "id": e.pk,
            "date": e.date,
            "subject": e.subject,
            "type": e.action.name,
            "color": e.action.color,
            "labels": [{"id": label.pk, "name": label.name, "group": label.group.name} for label in e.labels.all()],
        }
        for e in qs
    ]


def timeline_events(timeline: "list[_periods.Period]", step: str) -> list[dict[str, Any]]:
    """The events inside the timeline, for ``timeline.json``: date, subject, type, colour, scope and the key
    of the step containing the date (the period a viewer marks)."""
    if not timeline:
        return []
    return [
        {
            "date": e["date"].isoformat(),
            "subject": e["subject"],
            "type": e["type"],
            "color": e["color"],
            "labels": [f"{label['group']}: {label['name']}" for label in e["labels"]],
            "period_key": _periods.step_key(e["date"], step),
        }
        for e in load_events(timeline[0].start, timeline[-1].end)
    ]


# ── Weekly records ────────────────────────────────────────────────────────────────────────────────


class _Records:
    """The message and citation rows of the observed channels, with their local week and date."""

    def __init__(
        self,
        graph: nx.DiGraph,
        *,
        start_date: datetime.date | None,
        end_date: datetime.date | None,
        environment_depth: int | None,
        include_mentions: bool,
    ) -> None:
        from webapp.models import Message

        dead = dead_leaf_ids(graph)
        self.observed = sorted(int(n) for n in graph if n not in dead)
        observed_set = set(self.observed)
        # Messages: (channel, local day, week, is forward, forward source in scope).
        self.messages: list[tuple[int, datetime.date, datetime.date, bool, bool]] = []
        for channel_id, moment, source_id, is_forward in (
            Message.objects.alive()
            .filter(make_date_q(start_date, end_date), channel_cutoff_q(environment_depth=environment_depth))
            .filter(channel_id__in=self.observed, date__isnull=False)
            .annotate(is_forward=ExpressionWrapper(forward_header_q(), output_field=BooleanField()))
            .values_list("channel_id", "date", "forwarded_from_id", "is_forward")
            .iterator(chunk_size=5000)
        ):
            day = timezone.localdate(moment)
            self.messages.append(
                (
                    channel_id,
                    day,
                    day - datetime.timedelta(days=day.weekday()),
                    bool(is_forward),
                    source_id in observed_set and source_id != channel_id,
                )
            )
        # In-scope citations: (citer, cited, local day, week), self-citations excluded.
        self.citations: list[tuple[int, int, datetime.date, datetime.date]] = []
        sources = [
            forward_messages_qs(self.observed, start_date, end_date, environment_depth).values_list(
                "channel_id", "forwarded_from_id", "date"
            )
        ]
        if include_mentions:
            sources.append(
                reference_rows_qs(self.observed, start_date, end_date, environment_depth).values_list(
                    "message__channel_id", "channel_id", "message__date"
                )
            )
        for qs in sources:
            for citer, cited, moment in qs.iterator(chunk_size=5000):
                if citer == cited or moment is None:
                    continue
                day = timezone.localdate(moment)
                self.citations.append((citer, cited, day, day - datetime.timedelta(days=day.weekday())))
        first_seen: dict[int, datetime.date] = {}
        for channel_id, day, _week, _fwd, _in in self.messages:
            if channel_id not in first_seen or day < first_seen[channel_id]:
                first_seen[channel_id] = day
        self.first_week = {c: d - datetime.timedelta(days=d.weekday()) for c, d in first_seen.items()}
        all_weeks = [m[2] for m in self.messages]
        if all_weeks:
            lo, hi = min(all_weeks), max(all_weeks)
            n = (hi - lo).days // 7 + 1
            self.weeks = [lo + datetime.timedelta(weeks=i) for i in range(n)]
        else:
            self.weeks = []
        self.week_index = {w: i for i, w in enumerate(self.weeks)}


def _partition_groups() -> list[tuple[int, str, bool]]:
    from webapp.models import LabelGroup

    return list(
        LabelGroup.objects.filter(is_partition=True)
        .order_by("-is_primary", "name")
        .values_list("pk", "name", "is_container")
    )


class _Membership:
    """Label held by a channel at a date, for one partition group (container groups via their children)."""

    def __init__(self, channel_ids: list[int], group_id: int, is_container: bool) -> None:
        from webapp.models import ChannelLabel, LabelParent

        self.caches: list[tuple[dict, dict[int, int] | None]] = []
        if is_container:
            child_groups: dict[int, dict[int, int]] = defaultdict(dict)
            for child_id, parent_id, child_group in LabelParent.objects.filter(parent_group_id=group_id).values_list(
                "label_id", "parent_id", "label__group_id"
            ):
                child_groups[child_group][child_id] = parent_id
            for child_group, parent_of in child_groups.items():
                self.caches.append((ChannelLabel.build_cache(channel_ids, group_id=child_group), parent_of))
        else:
            self.caches.append((ChannelLabel.build_cache(channel_ids, group_id=group_id), None))

    def at(self, channel_id: int, day: datetime.date) -> int | None:
        from webapp.models import ChannelLabel

        for cache, parent_of in self.caches:
            label = ChannelLabel.label_at(cache, channel_id, day)
            if label is not None:
                return parent_of.get(label) if parent_of is not None else label
        return None


def _scope_test(event: dict[str, Any], channel_ids: list[int]):
    """A ``(channel, day) -> bool`` membership test for a scoped event's labels (containers expanded)."""
    from webapp.models import ChannelLabel, LabelParent

    label_ids = {label["id"] for label in event["labels"]}
    children = set(LabelParent.objects.filter(parent_id__in=label_ids).values_list("label_id", flat=True))
    wanted = label_ids | children
    cache = ChannelLabel.build_cache(channel_ids)

    def test(channel_id: int, day: datetime.date) -> bool:
        for label_id, start, end in cache.get(channel_id, ()):
            if label_id in wanted and (start is None or start <= day) and (end is None or end >= day):
                return True
        return False

    return test


def _series(records: _Records, groups: list[tuple[int, str, _Membership]], keep=None) -> dict[str, np.ndarray]:
    """The weekly metric arrays for the channels ``keep(channel, day)`` selects (all when ``None``)."""
    n = len(records.weeks)
    idx = records.week_index
    messages = np.zeros(n)
    forwards = np.zeros(n)
    imported = np.zeros(n)
    active: list[set] = [set() for _ in range(n)]
    new = np.zeros(n)
    for channel_id, day, week, is_forward, in_scope in records.messages:
        if keep is not None and not keep(channel_id, day):
            continue
        i = idx[week]
        messages[i] += 1
        active[i].add(channel_id)
        if is_forward:
            forwards[i] += 1
            if not in_scope:
                imported[i] += 1
    seen_new: set[int] = set()
    for channel_id, day, week, _f, _s in records.messages:
        if channel_id in seen_new or records.first_week.get(channel_id) != week:
            continue
        if keep is not None and not keep(channel_id, day):
            continue
        seen_new.add(channel_id)
        new[idx[week]] += 1
    citations = np.zeros(n)
    received: list[dict[int, int]] = [defaultdict(int) for _ in range(n)]
    cross = {gid: np.zeros(n) for gid, _name, _m in groups}
    labelled = {gid: np.zeros(n) for gid, _name, _m in groups}
    for citer, cited, day, week in records.citations:
        if keep is not None and not keep(citer, day):
            continue
        i = idx.get(week)
        if i is None:
            continue
        citations[i] += 1
        received[i][cited] += 1
        for gid, _name, membership in groups:
            a, b = membership.at(citer, day), membership.at(cited, day)
            if a is not None and b is not None:
                labelled[gid][i] += 1
                if a != b:
                    cross[gid][i] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        imported_share = np.where(forwards >= MIN_SHARE_DENOMINATOR, imported / forwards, np.nan)
        hhi = np.array(
            [
                sum((c / citations[i]) ** 2 for c in received[i].values())
                if citations[i] >= MIN_SHARE_DENOMINATOR
                else np.nan
                for i in range(n)
            ]
        )
    out = {
        "messages": messages,
        "forwards": forwards,
        "active_channels": np.array([len(s) for s in active], dtype=float),
        "new_channels": new,
        "citations": citations,
        "imported_share": imported_share,
        "concentration": hhi,
    }
    for gid, _name, _m in groups:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"{CROSS_LABEL_PREFIX}{gid}"] = np.where(
                labelled[gid] >= MIN_SHARE_DENOMINATOR, cross[gid] / labelled[gid], np.nan
            )
    return out


# ── Interrupted time series ───────────────────────────────────────────────────────────────────────


def _nw_lag(n: int) -> int:
    """Newey & West's (1994) automatic lag: ⌊4 (T/100)^(2/9)⌋."""
    return int(math.floor(4 * (n / 100) ** (2 / 9))) if n > 0 else 0


def _ols_hac(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and Newey–West standard errors, autocovariances taken within each group (series)."""
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    xtx_inv = np.linalg.pinv(x.T @ x)
    k = x.shape[1]
    s = np.zeros((k, k))
    for g in np.unique(groups):
        rows = np.flatnonzero(groups == g)
        u = x[rows] * resid[rows, None]
        s += u.T @ u
        lag = _nw_lag(rows.size)
        for lag_k in range(1, lag + 1):
            weight = 1.0 - lag_k / (lag + 1)
            gamma = u[lag_k:].T @ u[:-lag_k]
            s += weight * (gamma + gamma.T)
    cov = xtx_inv @ s @ xtx_inv
    return beta, np.sqrt(np.clip(np.diag(cov), 0.0, None))


def _transform(values: np.ndarray, kind: str) -> np.ndarray:
    return np.log1p(values) if kind == "count" else values


def _design(t: np.ndarray, comparative: bool, group: np.ndarray | None) -> np.ndarray:
    post = (t >= 0).astype(float)
    cols = [np.ones_like(t), t, post, t * post]
    if comparative:
        cols += [group, group * t, group * post, group * t * post]
    return np.column_stack(cols)


def _fit_at(
    center: int,
    window: int,
    series: dict[str, np.ndarray],
    kind: str,
) -> dict[str, Any] | None:
    """Fit the (comparative) ITS with the break at week index ``center``; ``None`` when data are insufficient.

    ``series`` holds ``"network"`` (unscoped) or ``"affected"`` + ``"comparison"`` arrays over all weeks. The
    window is cut at the edges of the data (``lo`` / ``hi`` in the result); each side still needs
    ``MIN_WEEKS_PER_SIDE`` non-missing weeks.
    """
    comparative = "affected" in series
    names = ("affected", "comparison") if comparative else ("network",)
    t_all, y_all, g_all = [], [], []
    counts = {"pre": [], "post": []}
    size = series[names[0]].size
    lo, hi = max(0, center - window), min(size, center + window)
    for gi, name in enumerate(names):
        values = series[name]
        t = np.arange(lo, hi) - center
        y = _transform(values[lo:hi], kind)
        ok = np.isfinite(y)
        counts["pre"].append(int(np.count_nonzero(ok & (t < 0))))
        counts["post"].append(int(np.count_nonzero(ok & (t >= 0))))
        t_all.append(t[ok])
        y_all.append(y[ok])
        g_all.append(np.full(int(ok.sum()), 1.0 if gi == 0 else 0.0))
    if min(counts["pre"]) < MIN_WEEKS_PER_SIDE or min(counts["post"]) < MIN_WEEKS_PER_SIDE:
        return None
    t = np.concatenate(t_all).astype(float)
    y = np.concatenate(y_all)
    group = np.concatenate(g_all)
    x = _design(t, comparative, group if comparative else None)
    if np.linalg.matrix_rank(x) < x.shape[1]:
        return None
    beta, se = _ols_hac(x, y, group)
    level, slope = (6, 7) if comparative else (2, 3)
    return {
        "beta": beta,
        "se": se,
        "level": (float(beta[level]), float(se[level])),
        "slope": (float(beta[slope]), float(se[slope])),
        "n_pre": min(counts["pre"]),
        "n_post": min(counts["post"]),
        "lo": lo,
        "hi": hi,
    }


def _hac_p(coef: float, se: float) -> float | None:
    if not se or not np.isfinite(se):
        return None
    return math.erfc(abs(coef / se) / math.sqrt(2))


def _placebo_p(observed: float, placebos: list[float]) -> float | None:
    if not placebos:
        return None
    return (sum(1 for v in placebos if abs(v) >= abs(observed)) + 1) / (len(placebos) + 1)


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(float(value), digits) if value is not None and np.isfinite(value) else None


def _lines(fit: dict[str, Any], center: int, comparative: bool) -> dict[str, list]:
    """Fitted values and the affected / network counterfactual over the fitted window (for the charts)."""
    t = (np.arange(fit["lo"], fit["hi"]) - center).astype(float)
    beta = fit["beta"]
    post = (t >= 0).astype(float)
    base = beta[0] + beta[1] * t
    if comparative:
        affected = base + beta[2] * post + beta[3] * t * post + beta[4] + beta[5] * t
        counterfactual = affected.copy()
        affected = affected + beta[6] * post + beta[7] * t * post
        comparison = base + beta[2] * post + beta[3] * t * post
        return {
            "fit_affected": [_round(v) for v in affected],
            "fit_comparison": [_round(v) for v in comparison],
            "counterfactual": [_round(v) if p else None for v, p in zip(counterfactual, post, strict=True)],
        }
    fitted = base + beta[2] * post + beta[3] * t * post
    return {
        "fit": [_round(v) for v in fitted],
        "counterfactual": [_round(v) if p else None for v, p in zip(base, post, strict=True)],
    }


def compute_event_impact(
    graph: nx.DiGraph,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    environment_depth: int | None = None,
    include_mentions: bool = False,
    window_weeks: int = EVENT_WINDOW_WEEKS_DEFAULT,
) -> dict[str, Any]:
    """The event-impact payload (module docstring): the network's weekly series and, per recorded event
    inside the data, per metric, the level and slope changes with their HAC and placebo p-values."""
    window = max(int(window_weeks), MIN_WEEKS_PER_SIDE)
    records = _Records(
        graph,
        start_date=start_date,
        end_date=end_date,
        environment_depth=environment_depth,
        include_mentions=include_mentions,
    )
    groups = [
        (gid, name, _Membership(records.observed, gid, is_container)) for gid, name, is_container in _partition_groups()
    ]
    metrics = list(METRICS) + [
        (f"{CROSS_LABEL_PREFIX}{gid}", f"Cross-label citation share ({name})", "share") for gid, name, _m in groups
    ]
    payload: dict[str, Any] = {
        "window_weeks": window,
        "weeks": [w.isoformat() for w in records.weeks],
        "metrics": [{"key": k, "label": label, "kind": kind} for k, label, kind in metrics],
        "events": [],
    }
    if not records.weeks:
        payload["series"] = {}
        return payload
    network = _series(records, groups)
    payload["series"] = {key: [_round(v, 6) for v in network[key]] for key, _l, _k in metrics}

    first_week, last_week = records.weeks[0], records.weeks[-1]
    events = [e for e in load_events() if first_week <= e["date"] <= last_week + datetime.timedelta(days=6)]
    event_weeks = {
        e["id"]: records.week_index.get(e["date"] - datetime.timedelta(days=e["date"].weekday())) for e in events
    }
    exclusion = window * PLACEBO_EXCLUSION_FRACTION
    all_event_centers = [c for c in event_weeks.values() if c is not None]
    candidates = [
        c
        for c in range(window, len(records.weeks) - window + 1)
        if all(abs(c - e) > exclusion for e in all_event_centers)
    ]

    for event in events:
        center = event_weeks[event["id"]]
        scoped = bool(event["labels"])
        if scoped:
            test = _scope_test(event, records.observed)
            affected = _series(records, groups, keep=test)
            comparison = _series(records, groups, keep=lambda c, d, test=test: not test(c, d))
        confounded = [
            other["subject"]
            for other in events
            if other["id"] != event["id"]
            and event_weeks[other["id"]] is not None
            and center is not None
            and abs(event_weeks[other["id"]] - center) <= window
        ]
        entry: dict[str, Any] = {
            "id": event["id"],
            "date": event["date"].isoformat(),
            "week": records.weeks[center].isoformat() if center is not None else None,
            "subject": event["subject"],
            "type": event["type"],
            "color": event["color"],
            "labels": [f"{label['group']}: {label['name']}" for label in event["labels"]],
            "design": "comparative" if scoped else "single",
            "confounded_by": confounded,
            "metrics": [],
        }
        for key, label, kind in metrics:
            series = {"affected": affected[key], "comparison": comparison[key]} if scoped else {"network": network[key]}
            fit = _fit_at(center, window, series, kind) if center is not None else None
            result: dict[str, Any] = {"key": key, "label": label, "kind": kind}
            if fit is None:
                result["insufficient"] = True
                entry["metrics"].append(result)
                continue
            placebo_level: list[float] = []
            placebo_slope: list[float] = []
            for c in candidates:
                if c == center:
                    continue
                placebo = _fit_at(c, window, series, kind)
                if placebo is not None:
                    placebo_level.append(placebo["level"][0])
                    placebo_slope.append(placebo["slope"][0])
            result.update(
                {
                    "insufficient": False,
                    "n_pre": fit["n_pre"],
                    "n_post": fit["n_post"],
                    "truncated": fit["hi"] - fit["lo"] < 2 * window,
                    "weeks": [w.isoformat() for w in records.weeks[fit["lo"] : fit["hi"]]],
                    "placebos": len(placebo_level),
                    "placebo_coarse": len(placebo_level) < MIN_PLACEBOS,
                }
            )
            for effect, placebos in (("level", placebo_level), ("slope", placebo_slope)):
                coef, se = fit[effect]
                result[effect] = {
                    "coef": _round(coef),
                    "se": _round(se),
                    "p_hac": _round(_hac_p(coef, se), 4),
                    "p_placebo": _round(_placebo_p(coef, placebos), 4),
                    "q": None,
                }
                if kind == "count" and effect == "level":
                    result[effect]["pct"] = _round((math.exp(coef) - 1) * 100, 2)
            lo, hi = fit["lo"], fit["hi"]
            if scoped:
                result["observed_affected"] = [_round(v) for v in _transform(affected[key][lo:hi], kind)]
                result["observed_comparison"] = [_round(v) for v in _transform(comparison[key][lo:hi], kind)]
            else:
                result["observed"] = [_round(v) for v in _transform(network[key][lo:hi], kind)]
            result.update(_lines(fit, center, scoped))
            entry["metrics"].append(result)
        payload["events"].append(entry)

    # Benjamini–Hochberg across events × metrics, per effect, on the placebo p-values.
    for effect in ("level", "slope"):
        cells = [
            m[effect]
            for e in payload["events"]
            for m in e["metrics"]
            if not m.get("insufficient") and m[effect]["p_placebo"] is not None
        ]
        for cell, q in zip(cells, bh_adjust([c["p_placebo"] for c in cells]), strict=True):
            cell["q"] = _round(q, 4)
    return payload


# ── Flat rows for XLSX / CSV ──────────────────────────────────────────────────────────────────────

EFFECT_COLUMNS: tuple[str, ...] = (
    "event_date",
    "event",
    "type",
    "scope",
    "design",
    "metric",
    "unit",
    "weeks_pre",
    "weeks_post",
    "level_change",
    "level_change_pct",
    "level_se",
    "level_p_hac",
    "level_p_placebo",
    "level_q",
    "slope_change",
    "slope_se",
    "slope_p_hac",
    "slope_p_placebo",
    "slope_q",
    "placebos",
    "confounded_by",
)


def effect_rows(payload: dict[str, Any]) -> list[list[Any]]:
    """One :data:`EFFECT_COLUMNS` row per event × metric (insufficient metrics with empty effects)."""
    rows = []
    for event in payload.get("events") or []:
        for metric in event["metrics"]:
            level = metric.get("level") or {}
            slope = metric.get("slope") or {}
            rows.append(
                [
                    event["date"],
                    event["subject"],
                    event["type"],
                    "; ".join(event["labels"]) or "whole network",
                    event["design"],
                    metric["label"],
                    "log(1 + count)" if metric["kind"] == "count" else "share",
                    metric.get("n_pre"),
                    metric.get("n_post"),
                    level.get("coef"),
                    level.get("pct"),
                    level.get("se"),
                    level.get("p_hac"),
                    level.get("p_placebo"),
                    level.get("q"),
                    slope.get("coef"),
                    slope.get("se"),
                    slope.get("p_hac"),
                    slope.get("p_placebo"),
                    slope.get("q"),
                    metric.get("placebos"),
                    "; ".join(event["confounded_by"]),
                ]
            )
    return rows


def series_rows(payload: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """The network's weekly series: a ``week`` column then one column per metric."""
    metrics = payload.get("metrics") or []
    header = ["week", *(m["label"] for m in metrics)]
    series = payload.get("series") or {}
    rows = [
        [week, *((series.get(m["key"]) or [None] * len(payload["weeks"]))[i] for m in metrics)]
        for i, week in enumerate(payload.get("weeks") or [])
    ]
    return header, rows
