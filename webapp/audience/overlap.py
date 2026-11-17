"""Audience overlap — which channels share commenters beyond chance (``/audience/overlap/``).

The audience-duplication networks of political communication research (Webster & Ksiazek 2012;
Mukerjee, Majó-Vázquez & González-Bailón 2018), built from commenters:

* **Pairs.** Two channels' shared commenters are tested against a null that keeps **every commenter's
  number of channels exactly** and every channel's number of commenters on average: each commenter's set of
  k channels is drawn with probability ∝ Πₐ λₐ over the set — maximum-entropy sampling of a fixed size
  (conditional Poisson sampling; Chen, Dempster & Liu 1994) — with the λ fitted so that each channel's
  expected commenters equal its observed ones. Two big channels, or a few very broad commenters, then do
  not make a pair look linked. A pair's shared commenters are a sum of binomials, one per commenter degree
  k, so p is exact; Benjamini–Hochberg over every pair gives q.

  Why not the bipartite configuration model (BiCM; Saracco et al. 2015) the co-linking test uses: it fixes
  the commenters' degrees only on average, so in the null a one-channel commenter can sit on two channels.
  With most commenters on a single channel, that inflates every expected overlap — on a real corpus every
  large pair fell below its BiCM expectation, an artefact. Fixing the commenter side exactly is the
  account-side half of the fixed-degree-sequence model of bipartite projections (Neal 2014).
* **Exclusivity.** The share of a channel's commenters who comment on no other channel in scope, against
  its expectation under the same null: the one-channel commenters it would draw, n₁ · λₐ / Σλ, over its
  commenters.
* **Labels.** The same test on the label × commenter incidence of each partition label group (labels at
  each post's date): do the commenters of one nation's channels also comment on another's?
* **Audience vs citations.** Does the audience network follow the elite one? The correlation between the
  pairs' shared commenters and their citations (forwards + mentions, either way, inside the channels'
  in-target periods), both log(1 + x), with a QAP p-value — the citation matrix's channels permuted
  :data:`QAP_PERMUTATIONS` times (Krackhardt 1987, 1988).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from django.db.models import Count, F

from network.link_layer import _bh
from webapp.models import Channel, Label, Message

from .scope import MIN_GROUP_COVERAGE, LabelResolver, coverage, reply_records, scope_posts

import numpy as np

OVERLAP_Q_THRESHOLD = 0.05
QAP_PERMUTATIONS = 9999
QAP_SEED = 42
FIT_TOLERANCE = 1e-10
FIT_MAX_ITERATIONS = 10_000


def _elementary(lam: np.ndarray, kmax: int) -> np.ndarray:
    """e₀…e_kmax, the elementary symmetric polynomials of *lam*."""
    e = np.zeros(kmax + 1)
    e[0] = 1.0
    for x in lam:
        e[1:] = e[1:] + x * e[:-1]
    return e


def _without(lam: np.ndarray, kmax: int, skip: int | None = None) -> np.ndarray:
    """E[b, j] = e_j of *lam* without its b-th weight — and without the *skip*-th too when given (row
    ``skip`` then leaves out that one weight only).

    Built by adding the weights one at a time to every row but their own: sums of positive terms only.
    The shortcut e_j(λ₋ᵦ) = e_j(λ) − λᵦ e_{j−1}(λ₋ᵦ) subtracts numbers of the same size and loses every
    digit once an account's degree reaches a few dozen.
    """
    n = len(lam)
    out = np.zeros((n, kmax + 1))
    out[:, 0] = 1.0
    rows = np.arange(n)
    for x in range(n):
        if x == skip:
            continue
        others = rows != x
        out[others, 1:] = out[others, 1:] + lam[x] * out[others, :-1]
    return out


def fit_fixed_size_weights(unit_degrees: np.ndarray, account_degrees: Counter) -> np.ndarray:
    """λ such that, when each account of degree k draws k units with P(S) ∝ Π_{a∈S} λₐ, unit a's expected
    accounts equal *unit_degrees*[a] (iterative scaling)."""
    kmax = max(account_degrees)
    lam = unit_degrees / unit_degrees.mean()
    for _ in range(FIT_MAX_ITERATIONS):
        e = _elementary(lam, kmax)
        minus = _without(lam, kmax)
        expected = sum(n * lam * minus[:, k - 1] / e[k] for k, n in account_degrees.items())
        ratio = unit_degrees / np.where(expected > 0, expected, 1.0)
        lam = lam * ratio
        lam = lam / lam.mean()
        if np.max(np.abs(ratio - 1.0)) < FIT_TOLERANCE:
            break
    return lam


def _sum_of_binomials_sf(observed: int, terms: list[tuple[int, float]]) -> float:
    """P(Σ Binomial(nₖ, pₖ) ≥ observed), exactly, by convolving the pmfs truncated below *observed*."""
    from scipy.stats import binom

    if observed <= 0:
        return 1.0
    dist = np.zeros(observed)
    dist[0] = 1.0
    support = np.arange(observed)
    for n, prob in terms:
        if n == 0 or prob <= 0:
            continue
        pmf = binom.pmf(support, n, min(prob, 1.0))
        dist = np.convolve(dist, pmf)[:observed]
    return float(np.clip(1.0 - dist.sum(), 0.0, 1.0))


def overlap_pairs(per_unit: dict[int, set[int]]) -> dict:
    """Every pair of units with its shared commenters, expectation under the fixed-account-degree null,
    ratio, p and BH q; plus each unit's observed and expected exclusive share."""
    units = sorted(per_unit, key=lambda u: (-len(per_unit[u]), u))
    n = len(units)
    result = {"units": units, "pairs": [], "exclusive": {}, "tested": n * (n - 1) // 2}
    if n < 2:
        return result
    degree_of: Counter = Counter()
    for members in per_unit.values():
        degree_of.update(members)
    account_degrees = Counter(degree_of.values())
    unit_degrees = np.array([len(per_unit[u]) for u in units], dtype=float)
    lam = fit_fixed_size_weights(unit_degrees, account_degrees)
    kmax = max(account_degrees)
    e = _elementary(lam, kmax)
    pvals, rows = [], []
    for i in range(n):
        both = _without(lam, kmax, skip=i)  # row j: e_m of λ without units i and j
        for j in range(i + 1, n):
            terms = [
                (count, lam[i] * lam[j] * both[j, k - 2] / e[k] if k >= 2 else 0.0)
                for k, count in account_degrees.items()
            ]
            shared = len(per_unit[units[i]] & per_unit[units[j]])
            expected = sum(count * prob for count, prob in terms)
            pvals.append(_sum_of_binomials_sf(shared, terms) if shared else 1.0)
            rows.append((units[i], units[j], shared, expected))
    qvals = _bh(np.array(pvals), len(pvals))
    for (a, b, shared, expected), pv, qv in zip(rows, pvals, qvals, strict=True):
        result["pairs"].append(
            {
                "a": a,
                "b": b,
                "shared": shared,
                "expected": float(expected),
                "ratio": float(shared / expected) if expected > 0 else None,
                "p": float(pv),
                "q": float(qv),
                "significant": bool(shared >= 1 and qv < OVERLAP_Q_THRESHOLD),
            }
        )
    single = account_degrees.get(1, 0)
    for i, unit in enumerate(units):
        members = per_unit[unit]
        observed = sum(1 for a in members if degree_of[a] == 1) / len(members) if members else None
        expected_share = float(single * lam[i] / e[1] / len(members)) if members and e[1] > 0 else None
        result["exclusive"][unit] = {"observed": observed, "expected": expected_share}
    return result


def citation_counts(channel_ids: list[int]) -> Counter:
    """Forwards + mentions between the channels, either way, inside their in-target periods."""
    ids = set(channel_ids)
    posts = scope_posts().filter(channel_id__in=ids)
    counts: Counter = Counter()
    forwards = (
        posts.filter(forwarded_from_id__in=ids)
        .exclude(forwarded_from_id=F("channel_id"))
        .values("channel_id", "forwarded_from_id")
        .annotate(n=Count("id"))
    )
    for row in forwards:
        counts[frozenset((row["channel_id"], row["forwarded_from_id"]))] += row["n"]
    mentions = (
        Message.references.through.objects.filter(message__in=posts.values("pk"), channel_id__in=ids)
        .exclude(channel_id=F("message__channel_id"))
        .values("message__channel_id", "channel_id")
        .annotate(n=Count("id"))
    )
    for row in mentions:
        counts[frozenset((row["message__channel_id"], row["channel_id"]))] += row["n"]
    return counts


def qap_correlation(units: list[int], shared: dict[frozenset, int], citations: Counter) -> dict | None:
    """Pearson r of log(1 + shared commenters) and log(1 + citations) over the unit pairs, QAP p-value."""
    n = len(units)
    if n < 4:
        return None
    s = np.zeros((n, n))
    c = np.zeros((n, n))
    for i, a in enumerate(units):
        for j, b in enumerate(units):
            if i != j:
                key = frozenset((a, b))
                s[i, j] = math.log1p(shared.get(key, 0))
                c[i, j] = math.log1p(citations.get(key, 0))
    iu = np.triu_indices(n, k=1)
    x, y = s[iu], c[iu]
    if x.std() == 0 or y.std() == 0:
        return None
    observed = float(np.corrcoef(x, y)[0, 1])
    rng = np.random.default_rng(QAP_SEED)
    hits = 0
    for _ in range(QAP_PERMUTATIONS):
        perm = rng.permutation(n)
        yp = c[np.ix_(perm, perm)][iu]
        if abs(np.corrcoef(x, yp)[0, 1]) >= abs(observed) - 1e-12:
            hits += 1
    return {
        "r": observed,
        "p": (hits + 1) / (QAP_PERMUTATIONS + 1),
        "permutations": QAP_PERMUTATIONS,
        "pairs": len(x),
        "cited_pairs": int((y > 0).sum()),
    }


def overlap(voice: Label | None = None) -> dict:
    """Everything the audience-overlap section shows, for one scope."""
    replies = reply_records(voice)
    per_channel: dict[int, set[int]] = defaultdict(set)
    for r in replies:
        per_channel[r.channel_id].add(r.sender_id)
    channel_result = overlap_pairs(per_channel)
    units = channel_result["units"]
    channels = Channel.objects.in_bulk(units)
    index = {unit: i + 1 for i, unit in enumerate(units)}
    pair_lookup = {(pr["a"], pr["b"]): pr for pr in channel_result["pairs"]}
    pair_lookup.update({(pr["b"], pr["a"]): pr for pr in channel_result["pairs"]})
    channel_rows = [
        {
            "index": index[u],
            "channel": channels.get(u),
            "channel_id": u,
            "commenters": len(per_channel[u]),
            "exclusive": channel_result["exclusive"].get(u, {}),
            "cells": [pair_lookup.get((u, v)) if u != v else None for v in units],
        }
        for u in units
    ]
    pairs = sorted(
        (pr for pr in channel_result["pairs"] if pr["shared"]),
        key=lambda pr: (pr["p"], -pr["shared"]),
    )
    for pr in pairs:
        pr["channel_a"], pr["channel_b"] = channels.get(pr["a"]), channels.get(pr["b"])

    resolver = LabelResolver(units)
    label_groups = []
    for gi, (group_id, group_name, _m) in enumerate(resolver.groups):
        per_label: dict[int, set[int]] = defaultdict(set)
        labelled = 0
        for r in replies:
            label = resolver.label(gi, r.channel_id, r.post_day)
            if label is not None:
                per_label[label].add(r.sender_id)
                labelled += 1
        if len(per_label) < 2 or labelled < MIN_GROUP_COVERAGE * len(replies):
            continue  # one label in scope, or the group covers too few replies
        result = overlap_pairs(per_label)
        for pr in result["pairs"]:
            pr["name_a"] = resolver.label_names.get(pr["a"], "?")
            pr["name_b"] = resolver.label_names.get(pr["b"], "?")
        label_groups.append(
            {
                "group_id": group_id,
                "name": group_name,
                "labels": [
                    {
                        "label_id": lab,
                        "name": resolver.label_names.get(lab, "?"),
                        "color": resolver.label_colors.get(lab),
                        "commenters": len(per_label[lab]),
                        "exclusive": result["exclusive"].get(lab, {}),
                    }
                    for lab in result["units"]
                ],
                "pairs": sorted(
                    (pr for pr in result["pairs"] if pr["shared"]), key=lambda pr: (pr["p"], -pr["shared"])
                ),
                "tested": result["tested"],
            }
        )

    shared_counts = {frozenset((pr["a"], pr["b"])): pr["shared"] for pr in channel_result["pairs"]}
    return {
        "channel_rows": channel_rows,
        "pairs": pairs,
        "tested": channel_result["tested"],
        "validated": sum(1 for pr in channel_result["pairs"] if pr["significant"]),
        "q_threshold": OVERLAP_Q_THRESHOLD,
        "label_groups": label_groups,
        "qap": qap_correlation(units, shared_counts, citation_counts(units)),
        **coverage(voice),
    }
