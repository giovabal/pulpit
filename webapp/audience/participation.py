"""Participation inequality — the Audience page's first section (``/audience/``). Scope: :mod:`.scope`.

**Participation inequality** — how unevenly the replies are spread over the accounts writing them:

* Gini coefficient of replies per account, with the small-sample correction n/(n−1) (Deltas 2003),
  so a channel with few commenters is not read as more equal than it is.
* Top 1% / top 10% share: the replies written by the most active ⌈p·n⌉ accounts.
* Effective number of commenters, 1 / Σ sᵢ² over the accounts' reply shares — the Laakso &
  Taagepera (1979) effective number of parties: the replies are as concentrated as if that many
  accounts had written them in equal parts.
* One-time commenters: accounts with a single reply.
* Hyperactive accounts — Papakyriakopoulos et al. (2019, 2020): outliers of the activity distribution
  by the skewness-adjusted boxplot of Hubert & Vandervieren (2008), i.e. more replies than
  Q3 + 1.5·e^(3·MC)·IQR, MC the medcouple (Brys, Hubert & Struyf 2004). Defined once over the whole
  scope; a channel's row reports the share of its replies those accounts wrote.

The per-channel concentration figures need at least :data:`MIN_CONCENTRATION_COMMENTERS` accounts.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from django.db.models import Count

from webapp.commenters import excluded_sender_ids
from webapp.models import Label

from .scope import coverage, scope_channels, scope_replies

import numpy as np

MIN_CONCENTRATION_COMMENTERS = 20
TOP_SHARES = (0.01, 0.10)
# (low, high) inclusive bounds of the replies-per-account classes; None = no upper bound.
ACTIVITY_BINS = ((1, 1), (2, 2), (3, 5), (6, 10), (11, 20), (21, 50), (51, 100), (101, None))
LORENZ_POINTS = 200
# Hubert & Vandervieren (2008) adjusted boxplot: whiskers 1.5·e^(a·MC)·IQR below Q1 and
# 1.5·e^(b·MC)·IQR above Q3 for MC ≥ 0 (a and b swap sign and place for MC < 0).
ADJBOX_COEF = 1.5
ADJBOX_A = -4.0
ADJBOX_B = 3.0


# ── Concentration measures ───────────────────────────────────────────────────


def gini(counts: Sequence[int]) -> float | None:
    """Gini coefficient with the small-sample correction n/(n−1) (Deltas 2003); None below 2 values."""
    x = np.sort(np.asarray(counts, dtype=float))
    n = len(x)
    if n < 2 or x.sum() == 0:
        return None
    ranks = np.arange(1, n + 1)
    g = float(((2 * ranks - n - 1) * x).sum() / (n * x.sum()))
    return g * n / (n - 1)


def top_share(counts: Sequence[int], p: float) -> float | None:
    """The share of the total held by the largest ⌈p·n⌉ values."""
    x = np.sort(np.asarray(counts, dtype=float))[::-1]
    if not len(x) or x.sum() == 0:
        return None
    k = max(1, math.ceil(p * len(x)))
    return float(x[:k].sum() / x.sum())


def effective_number(counts: Sequence[int]) -> float | None:
    """1 / Σ sᵢ², sᵢ each value's share of the total (Laakso & Taagepera 1979)."""
    x = np.asarray(counts, dtype=float)
    if not len(x) or x.sum() == 0:
        return None
    shares = x / x.sum()
    return float(1.0 / (shares**2).sum())


def medcouple(values: Sequence[float]) -> float:
    """The medcouple (Brys, Hubert & Struyf 2004), exactly, over the distinct values and their counts.

    MC = median of h(xᵢ, xⱼ) = ((xᵢ − m) − (m − xⱼ)) / (xᵢ − xⱼ) over the pairs xᵢ ≥ m ≥ xⱼ, m the
    median; for a pair of values both tied at m, h is −1, 0 or +1 by the tied observations' indices,
    which over the k² such pairs gives k(k−1)/2 times −1, k times 0 and k(k−1)/2 times +1. Grouping
    the observations by value makes the cost quadratic in the *distinct* values, so it stays cheap
    on count data however many observations there are.
    """
    x = np.asarray(values, dtype=float)
    if not len(x):
        raise ValueError("medcouple of an empty sample")
    m = float(np.median(x))
    distinct, counts = np.unique(x, return_counts=True)
    upper = [(v, c) for v, c in zip(distinct, counts, strict=True) if v >= m]
    lower = [(v, c) for v, c in zip(distinct, counts, strict=True) if v <= m]
    kernel: list[float] = []
    weights: list[int] = []
    for u, cu in upper:
        for low, cl in lower:
            if u == low:  # both tied at the median
                k = int(cu)
                kernel += [-1.0, 0.0, 1.0]
                weights += [k * (k - 1) // 2, k, k * (k - 1) // 2]
            else:
                kernel.append(((u - m) - (m - low)) / (u - low))
                weights.append(int(cu) * int(cl))
    order = np.argsort(kernel, kind="stable")
    h = np.asarray(kernel)[order]
    cumulative = np.cumsum(np.asarray(weights, dtype=np.int64)[order])
    total = int(cumulative[-1])
    # The median of `total` kernel values: the (total−1)//2-th and total//2-th, 0-based.
    lo = h[np.searchsorted(cumulative, (total - 1) // 2, side="right")]
    hi = h[np.searchsorted(cumulative, total // 2, side="right")]
    return float((lo + hi) / 2)


def adjusted_fences(values: Sequence[float]) -> dict:
    """Hubert & Vandervieren (2008) adjusted-boxplot fences, with the quartiles and medcouple used."""
    x = np.asarray(values, dtype=float)
    q1, q3 = (float(q) for q in np.percentile(x, [25, 75]))
    iqr = q3 - q1
    mc = medcouple(x)
    if mc >= 0:
        low, high = q1 - ADJBOX_COEF * math.exp(ADJBOX_A * mc) * iqr, q3 + ADJBOX_COEF * math.exp(ADJBOX_B * mc) * iqr
    else:
        low, high = q1 - ADJBOX_COEF * math.exp(-ADJBOX_B * mc) * iqr, q3 + ADJBOX_COEF * math.exp(-ADJBOX_A * mc) * iqr
    return {"q1": q1, "q3": q3, "iqr": iqr, "medcouple": mc, "lower": low, "upper": high}


def lorenz_points(counts: Sequence[int], max_points: int = LORENZ_POINTS) -> list[list[float]]:
    """The Lorenz curve, (share of accounts, share of replies) from the least active up, ≤ *max_points*
    points plus the origin."""
    x = np.sort(np.asarray(counts, dtype=float))
    n = len(x)
    if not n or x.sum() == 0:
        return []
    cumulative = np.cumsum(x) / x.sum()
    idx = np.unique(np.linspace(0, n - 1, min(n, max_points)).round().astype(int))
    return [[0.0, 0.0]] + [[round((i + 1) / n, 5), round(float(cumulative[i]), 5)] for i in idx]


def concentration(counts: Sequence[int]) -> dict:
    """The concentration figures for one set of per-account reply counts."""
    x = list(counts)
    total = sum(x)
    one_time = sum(1 for c in x if c == 1)
    return {
        "accounts": len(x),
        "replies": total,
        "mean": total / len(x) if x else None,
        "median": float(np.median(x)) if x else None,
        "gini": gini(x),
        "top_shares": {p: top_share(x, p) for p in TOP_SHARES},
        "effective_number": effective_number(x),
        "one_time_share": one_time / len(x) if x else None,
        "one_time_reply_share": one_time / total if total else None,
    }


def activity_bins(counts: Sequence[int]) -> list[dict]:
    """Accounts and replies per class of :data:`ACTIVITY_BINS`, with their shares."""
    x = np.asarray(counts)
    accounts, replies = len(x), int(x.sum()) if len(x) else 0
    rows = []
    for low, high in ACTIVITY_BINS:
        mask = (x >= low) & (x <= high) if high is not None else x >= low
        n, r = int(mask.sum()), int(x[mask].sum())
        rows.append(
            {
                "label": str(low) if low == high else (f"{low}–{high}" if high is not None else f"{low}+"),
                "accounts": n,
                "account_share": n / accounts if accounts else 0.0,
                "replies": r,
                "reply_share": r / replies if replies else 0.0,
            }
        )
    return rows


# ── The page ─────────────────────────────────────────────────────────────────


def participation(voice: Label | None = None) -> dict:
    """Everything the Audience page's participation-inequality section shows, for one scope."""
    excluded = excluded_sender_ids()
    replies = scope_replies(voice, excluded)
    per_channel: dict[int, dict[int, int]] = defaultdict(dict)
    per_account: dict[int, int] = defaultdict(int)
    for row in replies.values("parent_message__channel", "sender_id").annotate(n=Count("id")):
        per_channel[row["parent_message__channel"]][row["sender_id"]] = row["n"]
        per_account[row["sender_id"]] += row["n"]
    counts = list(per_account.values())
    overall = concentration(counts)

    hyperactive: set[int] = set()
    fences = adjusted_fences(counts) if counts else None
    if fences is not None:
        hyperactive = {sender for sender, n in per_account.items() if n > fences["upper"]}
    hyper_replies = sum(per_account[s] for s in hyperactive)
    overall["hyperactive"] = {
        "accounts": len(hyperactive),
        "account_share": len(hyperactive) / len(counts) if counts else None,
        "reply_share": hyper_replies / overall["replies"] if overall["replies"] else None,
        "fences": fences,
        # Replies are counts: "more than the fence" reads as this many or more.
        "min_replies": math.floor(fences["upper"]) + 1 if fences is not None else None,
    }

    channel_qs = scope_channels(voice)
    channels = {c.pk: c for c in channel_qs.filter(pk__in=list(per_channel))}
    channel_rows = []
    for channel_id, accounts in per_channel.items():
        values = list(accounts.values())
        stats = concentration(values)
        enough = stats["accounts"] >= MIN_CONCENTRATION_COMMENTERS
        channel = channels.get(channel_id)
        subscribers = channel.participants_count if channel else None
        channel_rows.append(
            {
                "channel": channel,
                "channel_id": channel_id,
                "subscribers": subscribers,
                "accounts": stats["accounts"],
                "replies": stats["replies"],
                "mean": stats["mean"],
                "commenter_rate": stats["accounts"] / subscribers if subscribers else None,
                "one_time_share": stats["one_time_share"],
                "gini": stats["gini"] if enough else None,
                "top10_share": stats["top_shares"][0.10] if enough else None,
                "effective_number": stats["effective_number"] if enough else None,
                "hyperactive_reply_share": (
                    sum(n for s, n in accounts.items() if s in hyperactive) / stats["replies"]
                    if stats["replies"]
                    else None
                ),
            }
        )
    channel_rows.sort(key=lambda r: (-r["accounts"], -r["replies"], r["channel_id"]))

    return {
        "overall": overall,
        "bins": activity_bins(counts),
        "lorenz": lorenz_points(counts),
        "channels": channel_rows,
        **coverage(voice),
    }
