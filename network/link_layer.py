"""The outbound-link layer (``--links``): which web sites the observed channels send their readers to.

A movement that lives on Telegram still depends on the open web — for donations, merchandise, video
hosting, mirrors on mainstream platforms and its own sites. This layer reads the outbound links of the
observed channels' messages inside the analysis (their in-target periods and the date window; one count
per message and site — :mod:`network.links`) against the analyst's domain categories (Manage → Domains)
and reports:

* **per channel** (node measures, in the channel table): the share of its messages carrying an outbound
  link, the number of distinct sites, the **platform diversity** — the Hill number of order 2 over the
  categories of its categorised links (Hill 1973; Jost 2006: the effective number of equally used
  categories) — and the shares of its links pointing to **monetisation**, **mainstream** and
  **alternative** platforms (the category roles; uncategorised links count in the denominator, so the
  shares are lower bounds while sites stay uncategorised);
* **per site**: posts, channels, first and last link, and which labels link to it;
* a **label × category matrix** per partition label group: who relies on which infrastructure;
* **co-linking pairs**: two channels linking to more of the same sites than their activity and the sites'
  popularity explain. The channel × site bipartite graph is projected on the channels and validated pair
  by pair against the **bipartite configuration model** (BiCM; Saracco et al. 2015, 2017) — the
  maximum-entropy ensemble of channel × site graphs in which every channel links, on average, to as many
  sites as observed and every site is linked by as many channels as observed. A pair's shared sites are
  then a sum of independent Bernoulli variables (one per site, probability p_ia · p_ja), and its p-value
  the exact Poisson-binomial tail; Benjamini–Hochberg-corrected over every pair of linking channels. A
  uniform-draw null (the hypergeometric test of Tumminello et al. 2011) is not used: it ignores that a
  few sites (a video platform, a mainstream network, a donation service) are linked by most channels, and
  on real data it validates most pairs of active channels for sharing them.

One-degree reading: a link is a pointer a channel published, not a visit, a payment or an affiliation.
"""

import collections
import datetime
from typing import Any

from django.db.models import Q

from network.links import category_for, domain_categories, scan_message_sites
from network.parameters import FixedParameter
from network.utils import GraphData, channel_cutoff_q, dead_leaf_ids, make_date_q

import networkx as nx
import numpy as np

#: Benjamini–Hochberg level at which a co-linking pair counts as validated.
COLINK_Q_THRESHOLD = 0.05
#: BiCM fixed point: relative change at which the multipliers count as converged, and the iteration cap.
BICM_TOLERANCE = 1e-10
BICM_MAX_ITERATIONS = 10_000
#: Exact Poisson-binomial tails while Σ (shared sites) × sites over the tested pairs stays under this many
#: operations; above it (very large networks), the Poisson approximation with the same mean.
COLINK_EXACT_BUDGET = 500_000_000
#: Pairs per block of the vectorised Poisson-binomial recursion.
_PAIR_CHUNK = 2048
#: Pairs sharing fewer sites are not listed (still in the test family: their p-value is high).
COLINK_MIN_SHARED = 2
#: Most co-linking pairs written (the most significant first).
COLINK_MAX_PAIRS = 2000
#: Shared sites listed per co-linking pair (rarest first).
COLINK_SITES_LISTED = 8
#: Top sites listed per channel in the XLSX sheet.
CHANNEL_TOP_SITES = 10
#: Label breakdown kept per site.
SITE_TOP_LABELS = 6
#: Decimal places of the share measures.
SHARE_DECIMALS = 4

UNCATEGORISED = "Uncategorised"

#: Node attributes this layer adds, with their labels (``measures_labels``).
NODE_MEASURES: tuple[tuple[str, str], ...] = (
    ("link_share", "Linking posts share"),
    ("distinct_sites", "Distinct sites"),
    ("platform_diversity", "Platform diversity"),
    ("monetisation_share", "Monetisation link share"),
    ("mainstream_share", "Mainstream link share"),
    ("alternative_share", "Alternative link share"),
)

_SOURCE = "network/link_layer.py"

#: The values fixed in this module (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Co-linking: validation level",
        value=COLINK_Q_THRESHOLD,
        scope="links",
        affects="BH-adjusted q below which a co-linking pair is validated.",
        source=f"{_SOURCE}: COLINK_Q_THRESHOLD",
        note="Validated projection of a bipartite network: Saracco et al. (2017); BH over every pair of linking "
        "channels.",
    ),
    FixedParameter(
        name="Co-linking: null model",
        value="bipartite configuration model (channel and site degrees fixed on average); exact Poisson-binomial "
        "tail of the shared sites",
        scope="links",
        affects="What a co-linking pair is tested against: the overlap expected from each channel's activity and "
        "each site's popularity.",
        source=f"{_SOURCE}: bicm_probabilities, _shared_site_pvalues",
        note="Saracco, Di Clemente, Gabrielli & Squartini (2015); Saracco et al. (2017).",
    ),
    FixedParameter(
        name="Co-linking: BiCM convergence",
        value=f"relative change < {BICM_TOLERANCE:g}, at most {BICM_MAX_ITERATIONS} iterations",
        scope="links",
        affects="Precision of the fitted link probabilities.",
        source=f"{_SOURCE}: BICM_TOLERANCE, BICM_MAX_ITERATIONS",
    ),
    FixedParameter(
        name="Co-linking: exact-tail budget",
        value=COLINK_EXACT_BUDGET,
        scope="links",
        affects="Above this many operations the p-values use the Poisson approximation of the shared-site count "
        "(the run records which: colinking.p_method).",
        source=f"{_SOURCE}: COLINK_EXACT_BUDGET",
    ),
    FixedParameter(
        name="Co-linking: minimum shared sites listed",
        value=COLINK_MIN_SHARED,
        scope="links",
        affects="Pairs sharing fewer sites are not listed; they stay in the multiple-testing family.",
        source=f"{_SOURCE}: COLINK_MIN_SHARED",
    ),
    FixedParameter(
        name="Co-linking: pairs written",
        value=COLINK_MAX_PAIRS,
        scope="links",
        affects="Most co-linking pairs written to links.json, most significant first.",
        source=f"{_SOURCE}: COLINK_MAX_PAIRS",
    ),
    FixedParameter(
        name="Platform diversity",
        value="Hill number of order 2 over the categories of the channel's categorised links",
        scope="links",
        affects="The effective number of equally used link categories; uncategorised links are left out.",
        source=f"{_SOURCE}: _hill2",
        note="Hill (1973); Jost (2006).",
    ),
)


def _hill2(counts: "collections.Counter[Any]") -> float | None:
    total = sum(counts.values())
    if not total:
        return None
    return 1.0 / sum((c / total) ** 2 for c in counts.values())


def _share(part: int, total: int) -> float | None:
    return round(part / total, SHARE_DECIMALS) if total else None


def _iso(moment: datetime.datetime | None) -> str | None:
    return moment.date().isoformat() if moment else None


def _partition_labels(
    graph: nx.DiGraph, observed: list[str]
) -> tuple[list[tuple[int, str]], dict[int, dict[str, str]]]:
    """``([(group id, name)], {group id: {node: label name}})`` for the partition groups, primary first."""
    from webapp.models import Label, LabelGroup

    groups = list(
        LabelGroup.objects.filter(is_partition=True).order_by("-is_primary", "name").values_list("pk", "name")
    )
    per_group: dict[int, dict[str, int]] = collections.defaultdict(dict)
    for node in observed:
        for group_id, resolved in ((graph.nodes[node].get("data") or {}).get("group_partitions") or {}).items():
            if resolved and resolved[0] is not None:
                per_group[int(group_id)][node] = int(resolved[0])
    names = dict(
        Label.objects.filter(pk__in={pk for labels in per_group.values() for pk in labels.values()}).values_list(
            "pk", "name"
        )
    )
    return groups, {gid: {n: names.get(pk, "") for n, pk in labels.items()} for gid, labels in per_group.items()}


def _fit_bicm(k: np.ndarray, d: np.ndarray) -> np.ndarray:
    """BiCM link probabilities for row degrees *k* and column degrees *d*, none of them zero or full."""
    total = float(k.sum())
    x = k / np.sqrt(total)
    y = d / np.sqrt(total)
    for _ in range(BICM_MAX_ITERATIONS):
        x_new = k / (y[None, :] / (1.0 + np.outer(x, y))).sum(axis=1)
        y_new = d / (x_new[:, None] / (1.0 + np.outer(x_new, y))).sum(axis=0)
        x_new = np.clip(x_new, 1e-300, 1e150)
        y_new = np.clip(y_new, 1e-300, 1e150)
        change = max(np.max(np.abs(x_new - x) / x_new), np.max(np.abs(y_new - y) / y_new))
        x, y = x_new, y_new
        if change < BICM_TOLERANCE:
            break
    xy = np.outer(x, y)
    return xy / (1.0 + xy)


def bicm_probabilities(incidence: np.ndarray) -> np.ndarray:
    """Link probabilities p_ia of the bipartite configuration model (Saracco et al. 2015) of a binary
    rows × columns *incidence* matrix: p_ia = x_i y_a / (1 + x_i y_a), with the multipliers solved so that
    every row's and every column's expected degree equals its observed degree (fixed-point iteration).

    A row or column linked to everything has probability 1 on all its cells, one linked to nothing 0; the
    rest are fitted on their degrees net of those.
    """
    incidence = np.asarray(incidence, dtype=float)
    n_rows, n_cols = incidence.shape
    k = incidence.sum(axis=1)
    d = incidence.sum(axis=0)
    p = np.zeros((n_rows, n_cols))
    full_rows, full_cols = k >= n_cols, d >= n_rows
    p[full_rows, :] = 1.0
    p[:, full_cols] = 1.0
    rows = ~full_rows & (k - full_cols.sum() > 0)
    cols = ~full_cols & (d - full_rows.sum() > 0)
    if rows.any() and cols.any():
        sub_k = incidence[np.ix_(rows, cols)].sum(axis=1)
        sub_d = incidence[np.ix_(rows, cols)].sum(axis=0)
        keep_r, keep_c = sub_k > 0, sub_d > 0
        r_idx, c_idx = np.nonzero(rows)[0][keep_r], np.nonzero(cols)[0][keep_c]
        if len(r_idx) and len(c_idx):
            p[np.ix_(r_idx, c_idx)] = _fit_bicm(sub_k[keep_r], sub_d[keep_c])
    return p


def _shared_site_pvalues(p: np.ndarray, a: np.ndarray, b: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, str]:
    """``(P(V_ab ≥ k_ab) per pair, method)`` with V_ab = Σ_s Bernoulli(p[a, s] · p[b, s]): the exact
    Poisson-binomial tail by recursion over the sites, vectorised over blocks of pairs of similar k (the
    Poisson approximation with the same mean above ``COLINK_EXACT_BUDGET``)."""
    n_sites = p.shape[1]
    if not len(k):
        return np.zeros(0), "exact"
    if float(k.sum()) * n_sites > COLINK_EXACT_BUDGET:
        from scipy.stats import poisson

        lam = np.einsum("ij,ij->i", p[a], p[b])
        return poisson.sf(k - 1, lam), "poisson"
    out = np.empty(len(k))
    order = np.argsort(k, kind="stable")
    for start in range(0, len(order), _PAIR_CHUNK):
        block = order[start : start + _PAIR_CHUNK]
        kmax = int(k[block].max())
        q = p[a[block]] * p[b[block]]  # pairs × sites
        dist = np.zeros((len(block), kmax))  # P(V = j) for j < kmax, over the sites seen so far
        dist[:, 0] = 1.0
        for s in range(n_sites):
            qs = q[:, s : s + 1]
            if kmax > 1:
                dist[:, 1:] = dist[:, 1:] * (1.0 - qs) + dist[:, :-1] * qs
            dist[:, :1] *= 1.0 - qs
        below = np.arange(kmax)[None, :] < k[block][:, None]
        out[block] = np.clip(1.0 - (dist * below).sum(axis=1), 0.0, 1.0)
    return out, "exact"


def _bh(pvals: np.ndarray, family: int) -> np.ndarray:
    """Benjamini–Hochberg q-values of *pvals* in a family of *family* tests (the untested ones have p = 1)."""
    m = max(int(family), len(pvals))
    if not len(pvals):
        return pvals
    order = np.argsort(pvals)
    ranked = pvals[order] * m / np.arange(1, len(pvals) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(q)
    out[order] = np.minimum(q, 1.0)
    return out


def _colinking(
    channel_sites: dict[str, "collections.Counter[str]"],
    site_channels: dict[str, set[str]],
    node_info: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    from scipy import sparse

    channels = sorted(n for n, sites in channel_sites.items() if sites)
    sites = sorted(site_channels)
    payload: dict[str, Any] = {
        "channels": len(channels),
        "sites": len(sites),
        "tested": len(channels) * (len(channels) - 1) // 2,
        "validated": 0,
        "q_threshold": COLINK_Q_THRESHOLD,
        "min_shared": COLINK_MIN_SHARED,
        "null": "bicm",
        "p_method": "exact",
        "pairs": [],
    }
    if len(channels) < 2 or not sites:
        return payload
    c_index = {n: i for i, n in enumerate(channels)}
    s_index = {s: j for j, s in enumerate(sites)}
    rows, cols = [], []
    for n in channels:
        for site in channel_sites[n]:
            rows.append(c_index[n])
            cols.append(s_index[site])
    incidence = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(channels), len(sites)))
    shared = sparse.triu(incidence @ incidence.T, k=1).tocoo()
    degree = np.asarray(incidence.sum(axis=1)).ravel()
    keep = shared.data >= 1
    a, b, k = shared.row[keep], shared.col[keep], shared.data[keep].astype(int)
    probabilities = bicm_probabilities(incidence.toarray())
    expected = np.einsum("ij,ij->i", probabilities[a], probabilities[b])
    p, payload["p_method"] = _shared_site_pvalues(probabilities, a, b, k)
    q = _bh(p, payload["tested"])
    payload["validated"] = int((q < COLINK_Q_THRESHOLD).sum())
    listed = np.nonzero(k >= COLINK_MIN_SHARED)[0]
    listed = listed[np.lexsort((-k[listed], p[listed]))][:COLINK_MAX_PAIRS]
    rarity = {s: len(site_channels[s]) for s in sites}
    for idx in listed.tolist():
        na, nb = channels[a[idx]], channels[b[idx]]
        common = sorted(set(channel_sites[na]) & set(channel_sites[nb]), key=lambda s: (rarity[s], s))
        payload["pairs"].append(
            {
                "a": node_info[na],
                "b": node_info[nb],
                "shared": int(k[idx]),
                "sites_a": int(degree[a[idx]]),
                "sites_b": int(degree[b[idx]]),
                "expected": round(float(expected[idx]), 3),
                "p": float(p[idx]),
                "q": float(q[idx]),
                "validated": bool(q[idx] < COLINK_Q_THRESHOLD),
                "common": common[:COLINK_SITES_LISTED],
            }
        )
    return payload


def compute_links(
    graph: nx.DiGraph,
    graph_data: GraphData,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    environment_depth: int | None = None,
) -> dict[str, Any]:
    """The outbound-link payload of *graph*'s observed channels (module docstring) — ``data/links.json``."""
    from webapp.models import Message

    dead = dead_leaf_ids(graph)
    observed = sorted((n for n in graph if n not in dead), key=int)
    info = {n["id"]: n for n in graph_data["nodes"]}
    node_info = {
        n: {
            "id": n,
            "label": (info.get(n) or {}).get("label") or n,
            "organization": (info.get(n) or {}).get("organization") or "",
        }
        for n in observed
    }
    window_q = channel_cutoff_q(environment_depth=environment_depth) & make_date_q(start_date, end_date)
    ids = [int(n) for n in observed]
    message_counts = dict(
        collections.Counter(
            Message.objects.alive().filter(window_q, channel_id__in=ids).values_list("channel_id", flat=True)
        )
    )
    site_categories, categories = domain_categories()

    def _category(site: str) -> int | None:
        cid = category_for(site, site_categories)
        return cid if cid in categories else None

    channel_sites: dict[str, collections.Counter[str]] = {n: collections.Counter() for n in observed}
    channel_categories: dict[str, collections.Counter[int | None]] = {n: collections.Counter() for n in observed}
    linking: collections.Counter[str] = collections.Counter()
    site_posts: collections.Counter[str] = collections.Counter()
    site_channels: dict[str, set[str]] = collections.defaultdict(set)
    site_first: dict[str, datetime.datetime] = {}
    site_last: dict[str, datetime.datetime] = {}
    groups, labels = _partition_labels(graph, observed)
    site_labels: dict[int, dict[str, collections.Counter[str]]] = {
        gid: collections.defaultdict(collections.Counter) for gid, _ in groups
    }
    matrix: dict[int, dict[str, collections.Counter[int | None]]] = {
        gid: collections.defaultdict(collections.Counter) for gid, _ in groups
    }
    for _mid, channel_id, date, sites in scan_message_sites(window_q & Q(channel_id__in=ids)):
        node = str(channel_id)
        linking[node] += 1
        for site in sites:
            cid = _category(site)
            channel_sites[node][site] += 1
            channel_categories[node][cid] += 1
            site_posts[site] += 1
            site_channels[site].add(node)
            if date is not None:
                if site not in site_first or date < site_first[site]:
                    site_first[site] = date
                if site not in site_last or date > site_last[site]:
                    site_last[site] = date
            for gid, _ in groups:
                label = labels.get(gid, {}).get(node)
                if label:
                    site_labels[gid][site][label] += 1
                    matrix[gid][label][cid] += 1

    roles = {cid: c.role for cid, c in categories.items()}
    channel_rows = []
    for n in observed:
        events = sum(channel_categories[n].values())
        categorised = collections.Counter({c: v for c, v in channel_categories[n].items() if c is not None})
        by_role: collections.Counter[str] = collections.Counter()
        for cid, count in channel_categories[n].items():
            if cid is not None and roles.get(cid):
                by_role[roles[cid]] += count
        diversity = _hill2(categorised)
        channel_rows.append(
            {
                **node_info[n],
                "messages": message_counts.get(int(n), 0),
                "linking_messages": linking[n],
                "link_events": events,
                "link_share": _share(linking[n], message_counts.get(int(n), 0)),
                "distinct_sites": len(channel_sites[n]) if message_counts.get(int(n)) else None,
                "platform_diversity": round(diversity, 3) if diversity is not None else None,
                "monetisation_share": _share(by_role["monetisation"], events),
                "mainstream_share": _share(by_role["mainstream"], events),
                "alternative_share": _share(by_role["alternative"], events),
                "categorised_share": _share(sum(categorised.values()), events),
                "sites": channel_sites[n].most_common(),
                "categories": {
                    (categories[cid].name if cid is not None else UNCATEGORISED): count
                    for cid, count in channel_categories[n].most_common()
                },
            }
        )

    channel_rows.sort(key=lambda row: (-row["link_events"], -(row["messages"] or 0), row["label"]))
    group_names = dict(groups)
    site_rows = []
    for site, posts in site_posts.most_common():
        cid = _category(site)
        site_rows.append(
            {
                "site": site,
                "category": categories[cid].name if cid is not None else None,
                "posts": posts,
                "channels": len(site_channels[site]),
                "first": _iso(site_first.get(site)),
                "last": _iso(site_last.get(site)),
                "labels": {
                    group_names[gid]: site_labels[gid][site].most_common(SITE_TOP_LABELS)
                    for gid, _ in groups
                    if site_labels[gid].get(site)
                },
            }
        )

    category_rows = []
    totals: collections.Counter[int | None] = collections.Counter()
    category_channels: dict[int | None, set[str]] = collections.defaultdict(set)
    category_sites: dict[int | None, set[str]] = collections.defaultdict(set)
    for n in observed:
        for cid, count in channel_categories[n].items():
            totals[cid] += count
            category_channels[cid].add(n)
    for site in site_posts:
        category_sites[_category(site)].add(site)
    all_events = sum(totals.values())
    ordered = sorted(categories.values(), key=lambda c: (-totals.get(c.pk, 0), c.name))
    for c in ordered:
        category_rows.append(
            {
                "id": c.pk,
                "name": c.name,
                "color": c.color,
                "role": c.role,
                "events": totals.get(c.pk, 0),
                "share": _share(totals.get(c.pk, 0), all_events),
                "channels": len(category_channels.get(c.pk, ())),
                "sites": len(category_sites.get(c.pk, ())),
            }
        )
    category_rows.append(
        {
            "id": None,
            "name": UNCATEGORISED,
            "color": "#9ca3af",
            "role": "",
            "events": totals.get(None, 0),
            "share": _share(totals.get(None, 0), all_events),
            "channels": len(category_channels.get(None, ())),
            "sites": len(category_sites.get(None, ())),
        }
    )

    column_ids = [c["id"] for c in category_rows]
    matrices = []
    for gid, gname in groups:
        rows = matrix[gid]
        if not rows:
            continue
        label_order = sorted(rows, key=lambda lbl: (-sum(rows[lbl].values()), lbl))
        matrices.append(
            {
                "group_id": gid,
                "group": gname,
                "labels": label_order,
                "categories": [c["name"] for c in category_rows],
                "counts": [[rows[lbl].get(cid, 0) for cid in column_ids] for lbl in label_order],
            }
        )

    total_messages = sum(message_counts.get(int(n), 0) for n in observed)
    return {
        "summary": {
            "channels": len(observed),
            "linking_channels": sum(1 for n in observed if linking[n]),
            "messages": total_messages,
            "linking_messages": sum(linking.values()),
            "link_share": _share(sum(linking.values()), total_messages),
            "link_events": all_events,
            "sites": len(site_posts),
            "categorised_share": _share(all_events - totals.get(None, 0), all_events),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
        "categories": category_rows,
        "channels": channel_rows,
        "sites": site_rows,
        "matrices": matrices,
        "colinking": _colinking(channel_sites, site_channels, node_info),
    }


def inject_node_scores(graph_data: GraphData, payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Write the per-channel link measures onto ``graph_data`` (``None`` outside the observed channels) and
    return their ``(key, label)`` pairs for ``measures_labels``."""
    by_id = {row["id"]: row for row in payload.get("channels", [])}
    for node in graph_data["nodes"]:
        row = by_id.get(node["id"]) or {}
        for key, _label in NODE_MEASURES:
            node[key] = row.get(key)
    return list(NODE_MEASURES)


# ── Flat row layouts shared by the XLSX sheets and channel_sites.csv ─────────────────────────────

CHANNEL_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Channel", lambda r: r["label"]),
    ("Label", lambda r: r["organization"]),
    ("Messages", lambda r: r["messages"]),
    ("Linking messages", lambda r: r["linking_messages"]),
    ("Linking posts share", lambda r: r["link_share"]),
    ("Link events", lambda r: r["link_events"]),
    ("Distinct sites", lambda r: r["distinct_sites"]),
    ("Platform diversity", lambda r: r["platform_diversity"]),
    ("Monetisation share", lambda r: r["monetisation_share"]),
    ("Mainstream share", lambda r: r["mainstream_share"]),
    ("Alternative share", lambda r: r["alternative_share"]),
    ("Categorised share", lambda r: r["categorised_share"]),
    ("Top sites", lambda r: ", ".join(f"{s} ({c})" for s, c in r["sites"][:CHANNEL_TOP_SITES])),
)
SITE_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Site", lambda r: r["site"]),
    ("Category", lambda r: r["category"] or UNCATEGORISED),
    ("Posts", lambda r: r["posts"]),
    ("Channels", lambda r: r["channels"]),
    ("First link", lambda r: r["first"]),
    ("Last link", lambda r: r["last"]),
    (
        "Labels",
        lambda r: "; ".join(
            f"{group}: " + ", ".join(f"{label} ({count})" for label, count in rows)
            for group, rows in r["labels"].items()
        ),
    ),
)
CATEGORY_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Category", lambda r: r["name"]),
    ("Role", lambda r: r["role"]),
    ("Link events", lambda r: r["events"]),
    ("Share", lambda r: r["share"]),
    ("Channels", lambda r: r["channels"]),
    ("Sites", lambda r: r["sites"]),
)
PAIR_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Channel A", lambda r: r["a"]["label"]),
    ("Label A", lambda r: r["a"]["organization"]),
    ("Channel B", lambda r: r["b"]["label"]),
    ("Label B", lambda r: r["b"]["organization"]),
    ("Shared sites", lambda r: r["shared"]),
    ("Sites A", lambda r: r["sites_a"]),
    ("Sites B", lambda r: r["sites_b"]),
    ("Expected shared", lambda r: r["expected"]),
    ("p", lambda r: r["p"]),
    ("q", lambda r: r["q"]),
    ("Validated", lambda r: r["validated"]),
    ("Common sites (rarest first)", lambda r: ", ".join(r["common"])),
)


def flat_rows(columns: tuple[tuple[str, Any], ...], rows: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    return [name for name, _ in columns], [[get(row) for _, get in columns] for row in rows]


def channel_site_rows(payload: dict[str, Any]) -> list[list[Any]]:
    """Long format for ``channel_sites.csv``: one row per (channel, site) with its message count."""
    category = {row["site"]: row["category"] or UNCATEGORISED for row in payload.get("sites", [])}
    out = []
    for row in payload.get("channels", []):
        for site, count in row["sites"]:
            out.append([row["label"], row["id"], row["organization"], site, category.get(site, UNCATEGORISED), count])
    return out
