// Partition-comparison matrices for the community table page.
//
// Renders the four strategy×strategy heat-maps (ARI, AMI, NMI, VI) from a network_metrics.json
// `partition_comparison` payload ({strategies, metrics}). The data is computed server-side by
// network.community_stats.compute_community_metrics (one payload per timeline year).

import { strategy_label as _strat_label } from './labels.js';

// Mirror of PARTITION_COMPARISON_METRICS in network/community_stats.py: the four pairwise
// partition-comparison indices, in display order. `dist` flags Variation of Information — a distance
// where lower = more similar. `dec` is the display precision; `tip`/`desc` are the heading tooltip
// and the under-heading explainer.
var PARTITION_COMPARISON_METRICS = [
    {
        key: "ari", abbr: "ARI", name: "Adjusted Rand Index", dist: false, dec: 3,
        tip: "Adjusted Rand Index (Hubert & Arabie 1985): chance-corrected agreement on which channel "
            + "pairs share a community. 1 = identical, 0 = random, < 0 = worse than random.",
        desc: "Chance-corrected agreement on co-grouped channel pairs. 1 = identical, 0 = chance, "
            + "negative = worse than chance.",
    },
    {
        key: "ami", abbr: "AMI", name: "Adjusted Mutual Information", dist: false, dec: 3,
        tip: "Adjusted Mutual Information (Vinh, Epps & Bailey 2010): shared information corrected for "
            + "chance. 1 = identical, ≈ 0 = random.",
        desc: "Shared information, corrected for chance. 1 = identical, ≈ 0 = independent.",
    },
    {
        key: "nmi", abbr: "NMI", name: "Normalised Mutual Information", dist: false, dec: 3,
        tip: "Normalised Mutual Information, arithmetic mean (Kvalseth 1987): 2·I /(H_a + H_b) ∈ [0, 1]. "
            + "1 = identical, 0 = independent.",
        desc: "Shared information normalised to [0, 1]. 1 = identical, 0 = independent. Not chance-corrected.",
    },
    {
        key: "vi", abbr: "VI", name: "Variation of Information", dist: true, dec: 2,
        tip: "Variation of Information (Meilă 2003), in bits: H(a) + H(b) − 2·I. A true metric on "
            + "partitions. 0 = identical, larger = more different (upper bound log₂ N).",
        desc: "Information distance, in bits. 0 = identical, larger = more different — a true metric "
            + "(obeys the triangle inequality).",
    },
];

// White → muted blue ramp; `t` in [0, 1], higher = more agreement = more saturated.
function _comparison_cell_color(t) {
    t = Math.max(0, Math.min(1, t));
    var r = Math.round(255 - t * 70), g = Math.round(255 - t * 40), b = Math.round(255 - t * 20);
    return "rgb(" + r + "," + g + "," + b + ")";
}

function _comparison_matrix_el(strats, cells, metric) {
    // For the VI distance, normalise colour intensity by the largest off-diagonal value so the
    // heatmap stays readable and consistent with the similarity indices (darker = more agreement).
    var vmax = 0;
    if (metric.dist) {
        for (var a = 0; a < strats.length; a++) {
            for (var b2 = 0; b2 < strats.length; b2++) {
                if (a !== b2 && cells[a][b2] != null && cells[a][b2] > vmax) vmax = cells[a][b2];
            }
        }
    }
    var wrap = document.createElement("div"); wrap.style.overflowX = "auto";
    var table = document.createElement("table");
    table.className = "table table-sm table-bordered comparison-matrix";
    table.style.cssText = "width:auto;min-width:0;";

    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    htr.appendChild(document.createElement("th"));
    strats.forEach(function(sk) {
        var th = document.createElement("th"); th.scope = "col"; th.className = "number";
        th.textContent = _strat_label(sk);
        htr.appendChild(th);
    });
    thead.appendChild(htr); table.appendChild(thead);

    var tbody = document.createElement("tbody");
    strats.forEach(function(sk_a, i) {
        var tr = document.createElement("tr");
        var td0 = document.createElement("td"); td0.textContent = _strat_label(sk_a);
        td0.style.fontWeight = "500";
        tr.appendChild(td0);
        strats.forEach(function(_sk_b, j) {
            var val = cells[i][j];
            var td = document.createElement("td"); td.className = "number";
            if (i === j || val === null || val === undefined) {
                td.textContent = "—";
                td.style.color = "#adb5bd";
            } else {
                td.textContent = val.toFixed(metric.dec);
                var t = metric.dist ? (vmax > 0 ? 1 - val / vmax : 1) : val;
                td.style.backgroundColor = _comparison_cell_color(t);
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody); wrap.appendChild(table);
    return wrap;
}

// Render the four comparison-matrix heat-maps into `target` (cleared first). `pc` is the
// network_metrics.json `partition_comparison` object; renders a muted note when it is absent or has
// fewer than two comparable strategies.
export function render_partition_comparison(target, pc) {
    target.innerHTML = "";
    if (!pc || !pc.strategies || pc.strategies.length < 2 || !pc.metrics) {
        var note = document.createElement("p");
        note.className = "text-muted";
        note.textContent = "Partition comparison needs at least two comparable strategies for this selection.";
        target.appendChild(note);
        return;
    }
    var strats = pc.strategies;
    var grid = document.createElement("div"); grid.className = "row g-4";
    PARTITION_COMPARISON_METRICS.forEach(function(metric) {
        var cells = pc.metrics[metric.key];
        if (!cells) return;
        var col = document.createElement("div"); col.className = "col-12 col-xl-6";
        var h5 = document.createElement("h5"); h5.className = "mb-1";
        h5.textContent = metric.name + " (" + metric.abbr + ")";
        h5.title = metric.tip;
        col.appendChild(h5);
        var p = document.createElement("p"); p.className = "text-muted small mb-2"; p.textContent = metric.desc;
        col.appendChild(p);
        col.appendChild(_comparison_matrix_el(strats, cells, metric));
        grid.appendChild(col);
    });
    target.appendChild(grid);
}
