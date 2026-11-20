"""Breadth — over how many channels, and across how many labels, each commenter spreads (``/audience/breadth/``).

Raw counts mislead in two ways, and both are corrected:

* **Activity.** An account with 300 replies reaches more channels by chance alone. Each account is set
  against its **rarefaction** expectation (Hurlbert 1971): the distinct channels expected if its n replies
  were drawn without replacement from all the replies in scope, E[Sₙ] = Σᵢ [1 − C(N − Nᵢ, n) / C(N, n)],
  Nᵢ the replies on channel i and N their total. Observed below expected = the account keeps to fewer
  channels than the channels' popularity would spread it over — the selective exposure Schmidt et al.
  (2017) found in news consumption on Facebook.
* **Count vs spread.** 99 replies on German channels and 1 on an Italian one are not "2 nations". Per
  partition label group the account's spread is the **effective number of labels**, the Hill number of
  order 1, exp(−Σ sₗ ln sₗ) (Hill 1973), and its **cross-label share**, the replies outside its main label.
  Labels are read at each post's date (container groups through their child labels); replies on channels
  without a label in the group are left out of that group, and a group covering less than
  ``MIN_GROUP_COVERAGE`` of the replies is not reported.

One-reply accounts are left out of the activity-adjusted figures: one reply reaches one channel.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from network.parameters import FixedParameter

from .scope import MIN_GROUP_COVERAGE, LabelResolver, Scope, coverage, reply_records

# Classes of replies per account for the observed-vs-expected table; (low, high) inclusive, None = open.
BREADTH_ACTIVITY_BINS = ((2, 2), (3, 5), (6, 10), (11, 20), (21, 50), (51, None))
# Classes of distinct channels per account.
CHANNEL_COUNT_BINS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, None))


def _bin_label(low: int, high: int | None) -> str:
    return str(low) if low == high else (f"{low}–{high}" if high is not None else f"{low}+")


FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Breadth: activity classes",
        value=", ".join(_bin_label(lo, hi) for lo, hi in BREADTH_ACTIVITY_BINS),
        scope="audience",
        affects="The replies-per-account classes the observed channels (and labels) reached are compared with "
        "their rarefaction expectation in; one-reply accounts are left out.",
        source="webapp/audience/breadth.py: BREADTH_ACTIVITY_BINS",
        note="Rarefaction: Hurlbert (1971).",
    ),
)


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def rarefaction(totals: list[int], n: int) -> float:
    """Expected distinct categories in *n* draws without replacement from a pool of *totals* per category
    (Hurlbert 1971)."""
    pool = sum(totals)
    if n <= 0 or pool == 0:
        return 0.0
    n = min(n, pool)
    expected = 0.0
    for size in totals:
        if size <= 0:
            continue
        rest = pool - size
        missing = math.exp(_log_comb(rest, n) - _log_comb(pool, n)) if rest >= n else 0.0
        expected += 1.0 - missing
    return expected


def hill_one(counts: list[int]) -> float:
    """Hill number of order 1, exp(Shannon entropy) of the shares (Hill 1973)."""
    total = sum(counts)
    if total == 0:
        return 0.0
    return math.exp(-sum((c / total) * math.log(c / total) for c in counts if c))


def _in_bin(value: int, low: int, high: int | None) -> bool:
    return value >= low and (high is None or value <= high)


def _spread(per_account: dict[int, Counter], totals: list[int]) -> dict:
    """Observed vs rarefaction-expected categories per account, overall and by activity class."""
    expected_cache: dict[int, float] = {}
    rows = []
    for counts in per_account.values():
        n = sum(counts.values())
        if n < 2:
            continue
        if n not in expected_cache:
            expected_cache[n] = rarefaction(totals, n)
        rows.append((n, len(counts), expected_cache[n]))
    classes = []
    for low, high in BREADTH_ACTIVITY_BINS:
        members = [r for r in rows if _in_bin(r[0], low, high)]
        if not members:
            continue
        observed = sum(r[1] for r in members) / len(members)
        expected = sum(r[2] for r in members) / len(members)
        classes.append(
            {
                "label": _bin_label(low, high),
                "accounts": len(members),
                "observed": observed,
                "expected": expected,
                "ratio": observed / expected if expected else None,
                "below_share": sum(1 for r in members if r[1] < r[2] - 1e-9) / len(members),
            }
        )
    observed_total = sum(r[1] for r in rows)
    expected_total = sum(r[2] for r in rows)
    return {
        "accounts": len(rows),
        "observed_mean": observed_total / len(rows) if rows else None,
        "expected_mean": expected_total / len(rows) if rows else None,
        "ratio": observed_total / expected_total if expected_total else None,
        "below_share": (sum(1 for r in rows if r[1] < r[2] - 1e-9) / len(rows)) if rows else None,
        "classes": classes,
    }


def breadth(scope: Scope | None = None) -> dict:
    """Everything the breadth section shows, for one scope."""
    replies = reply_records(scope)
    per_account: dict[int, Counter] = defaultdict(Counter)
    for r in replies:
        per_account[r.sender_id][r.channel_id] += 1
    channel_totals = Counter()
    for counts in per_account.values():
        channel_totals.update(counts)

    distinct = [len(c) for c in per_account.values()]
    channel_bins = []
    for low, high in CHANNEL_COUNT_BINS:
        n = sum(1 for d in distinct if _in_bin(d, low, high))
        channel_bins.append(
            {"label": _bin_label(low, high), "accounts": n, "share": n / len(distinct) if distinct else 0.0}
        )

    resolver = LabelResolver(list(channel_totals))
    groups = []
    for index, (group_id, group_name, _membership) in enumerate(resolver.groups):
        by_account: dict[int, Counter] = defaultdict(Counter)
        unlabelled = 0
        for r in replies:
            label = resolver.label(index, r.channel_id, r.post_day)
            if label is None:
                unlabelled += 1
            else:
                by_account[r.sender_id][label] += 1
        label_totals = Counter()
        for counts in by_account.values():
            label_totals.update(counts)
        if len(label_totals) < 2 or unlabelled > (1 - MIN_GROUP_COVERAGE) * len(replies):
            continue  # one label in scope, or the group covers too few replies
        active = {s: c for s, c in by_account.items() if sum(c.values()) >= 2}
        effective = [hill_one(list(c.values())) for c in active.values()]
        cross = [1 - max(c.values()) / sum(c.values()) for c in active.values()]
        per_label = []
        for label_id, replies_on_label in label_totals.most_common():
            commenters = [s for s, c in by_account.items() if c[label_id]]
            elsewhere = sum(1 for s in commenters if len(by_account[s]) > 1)
            per_label.append(
                {
                    "label_id": label_id,
                    "name": resolver.label_names.get(label_id, "?"),
                    "color": resolver.label_colors.get(label_id),
                    "commenters": len(commenters),
                    "replies": replies_on_label,
                    "elsewhere_share": elsewhere / len(commenters) if commenters else None,
                }
            )
        groups.append(
            {
                "group_id": group_id,
                "name": group_name,
                "labels_in_scope": len(label_totals),
                "accounts": len(by_account),
                "unlabelled_replies": unlabelled,
                "multi_label_share": (sum(1 for c in active.values() if len(c) > 1) / len(active)) if active else None,
                "effective_mean": sum(effective) / len(effective) if effective else None,
                "cross_share_mean": sum(cross) / len(cross) if cross else None,
                "spread": _spread(by_account, list(label_totals.values())),
                "labels": per_label,
            }
        )

    return {
        "accounts": len(per_account),
        "channel_bins": channel_bins,
        "multi_channel_share": (sum(1 for d in distinct if d > 1) / len(distinct)) if distinct else None,
        "channel_spread": _spread(per_account, list(channel_totals.values())),
        "groups": groups,
        **coverage(scope),
    }
