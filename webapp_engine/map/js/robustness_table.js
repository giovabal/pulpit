// Render the robustness analysis page from data/robustness.json.
//
// Layout:
//   - top text:  one-line summary (graph size, alpha, # strategies, # nulls)
//   - summary:   one table row per (strategy × metric) — R, R_null mean/std, z, f_c
//   - curves:    three Chart.js line charts (WCC / SCC / REACH), one line per strategy
//   - modular:   per-partition section with intra/inter curves per strategy
//
// The null model details live in the summary table rather than in the charts so the
// charts stay legible when several strategies are active.  A per-strategy null band
// would clutter the line chart with 3 extra datasets per strategy.

var _dd = window.DATA_DIR || "data/";

var _METRICS = ["wcc", "scc", "reach"];
var _METRIC_LABEL = { wcc: "WCC", scc: "SCC", reach: "REACH" };

// Strategy ordering (matches network.robustness.attacks.ALL_STRATEGIES) so the
// rendered tables and charts present the same order as the CLI / docs.
var _STRATEGY_ORDER = [
    "random", "in_strength", "out_strength", "pagerank", "betweenness",
    "in_strength_dyn", "pagerank_dyn", "betweenness_dyn",
];
var _STRATEGY_LABEL = {
    "random": "Random",
    "in_strength": "In-strength",
    "out_strength": "Out-strength",
    "pagerank": "PageRank",
    "betweenness": "Betweenness",
    "in_strength_dyn": "In-strength (dyn)",
    "pagerank_dyn": "PageRank (dyn)",
    "betweenness_dyn": "Betweenness (dyn)",
};

// Distinct, accessible colour palette (matching the rest of Pulpit's table charts).
var _STRATEGY_COLOR = {
    "random": "#94a3b8",
    "in_strength": "#3b82f6",
    "out_strength": "#06b6d4",
    "pagerank": "#ef4444",
    "betweenness": "#f59e0b",
    "in_strength_dyn": "#1d4ed8",
    "pagerank_dyn": "#b91c1c",
    "betweenness_dyn": "#b45309",
};

function _fmt(v, dp) {
    if (v === null || v === undefined) return "—";
    if (typeof v !== "number" || !isFinite(v)) return "—";
    return v.toFixed(dp == null ? 4 : dp);
}

function _fmtZ(z) {
    if (z === null || z === undefined || !isFinite(z)) return "—";
    var cls = Math.abs(z) >= 2 ? " rb-z-significant " + (z > 0 ? "rb-z-pos" : "rb-z-neg") : "";
    var sign = z > 0 ? "+" : "";
    return "<span class=\"" + cls + "\">" + sign + z.toFixed(2) + "</span>";
}

function _fmtFc(fc) {
    return fc === null || fc === undefined ? "—" : fc.toFixed(3);
}

function _orderedStrategies(payload) {
    var present = new Set(Object.keys(payload.strategies || {}));
    return _STRATEGY_ORDER.filter(function (s) { return present.has(s); });
}

// ── Header summary ───────────────────────────────────────────────────────────

function _renderHeaderSummary(payload) {
    var g = payload.graph || {};
    var c = payload.config || {};
    var parts = [
        g.n + " nodes / " + g.m + " edges",
        g.filtered ? "backbone " + g.backbone_n + "/" + g.backbone_m + " edges (α=" + c.alpha + ")" : "no disparity filter",
        Object.keys(payload.strategies || {}).length + " strategies",
        c.n_null > 0 ? c.n_null + " null simulations" : "no null model",
        "seed=" + c.seed,
    ];
    if (payload.efficiency && payload.efficiency.baseline !== undefined) {
        parts.push("baseline efficiency=" + _fmt(payload.efficiency.baseline, 3));
    }
    document.getElementById("rb-summary").textContent = parts.join(" · ");
}

// ── Summary table ───────────────────────────────────────────────────────────

function _renderSummaryTable(payload) {
    var strategies = _orderedStrategies(payload);
    var hasNull = strategies.some(function (s) { return payload.strategies[s].null; });
    var thead = document.querySelector("#rb-summary-table thead");
    var tbody = document.querySelector("#rb-summary-table tbody");

    var headerCells = [
        "<th>Strategy</th>",
        "<th>Metric</th>",
        "<th class=\"text-end\">R</th>",
    ];
    if (hasNull) {
        headerCells.push("<th class=\"text-end\">R_null μ</th>");
        headerCells.push("<th class=\"text-end\">R_null σ</th>");
        headerCells.push("<th class=\"text-end\">z</th>");
    }
    headerCells.push("<th class=\"text-end\">f<sub>c</sub> (5%)</th>");
    thead.innerHTML = "<tr>" + headerCells.join("") + "</tr>";

    var rows = [];
    strategies.forEach(function (s) {
        var p = payload.strategies[s];
        var nullData = p.null || {};
        _METRICS.forEach(function (m) {
            var nullM = nullData["r_" + m] || {};
            var r = p["r_" + m];
            var fc = p["fc_" + m];
            var cells = [
                "<td>" + _STRATEGY_LABEL[s] + "</td>",
                "<td><code>" + _METRIC_LABEL[m] + "</code></td>",
                "<td class=\"text-end\">" + _fmt(r) + "</td>",
            ];
            if (hasNull) {
                cells.push("<td class=\"text-end\">" + _fmt(nullM.mean) + "</td>");
                cells.push("<td class=\"text-end\">" + _fmt(nullM.std) + "</td>");
                cells.push("<td class=\"text-end\">" + _fmtZ(nullM.z) + "</td>");
            }
            cells.push("<td class=\"text-end\">" + _fmtFc(fc) + "</td>");
            rows.push("<tr>" + cells.join("") + "</tr>");
        });
    });
    tbody.innerHTML = rows.join("");
}

// ── Curve charts (one per metric) ───────────────────────────────────────────

function _buildLineDataset(label, color, data, fractionRemoved) {
    return {
        label: label,
        data: data.map(function (y, i) { return { x: fractionRemoved[i], y: y }; }),
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
    };
}

function _renderCurves(payload) {
    var container = document.getElementById("rb-curves");
    var strategies = _orderedStrategies(payload);
    if (!strategies.length) {
        container.innerHTML = "<p class=\"rb-empty\">No attack strategies were run.</p>";
        return;
    }

    var firstStrategy = payload.strategies[strategies[0]];
    var n_points = firstStrategy.curve_wcc.length;
    var fractionRemoved = [];
    for (var i = 0; i < n_points; i++) fractionRemoved.push(i / (n_points - 1));

    _METRICS.forEach(function (m) {
        var card = document.createElement("div");
        card.className = "rb-chart-card";
        var title = document.createElement("h5");
        title.textContent = "S(f) — " + _METRIC_LABEL[m];
        card.appendChild(title);
        var wrap = document.createElement("div");
        wrap.className = "rb-chart-canvas";
        var canvas = document.createElement("canvas");
        wrap.appendChild(canvas);
        card.appendChild(wrap);
        container.appendChild(card);

        var datasets = strategies.map(function (s) {
            return _buildLineDataset(_STRATEGY_LABEL[s], _STRATEGY_COLOR[s],
                                     payload.strategies[s]["curve_" + m], fractionRemoved);
        });

        new Chart(canvas, {
            type: "line",
            data: { datasets: datasets },
            options: {
                animation: false, responsive: true, maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 14, font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            title: function (items) {
                                var f = items[0].parsed.x;
                                return "Removed: " + (f * 100).toFixed(1) + "%";
                            },
                            label: function (ctx) {
                                return ctx.dataset.label + ": " + ctx.parsed.y.toFixed(4);
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        type: "linear", min: 0, max: 1,
                        title: { display: true, text: "Fraction of nodes removed", font: { size: 12 } },
                        grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } },
                    },
                    y: {
                        min: 0,
                        title: { display: true, text: "S(f)", font: { size: 12 } },
                        grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } },
                    },
                },
            },
        });
    });
}

// ── Modular section ─────────────────────────────────────────────────────────

function _renderModular(payload) {
    var modular = payload.modular;
    if (!modular || !Object.keys(modular).length) return;

    document.getElementById("rb-modular-section").classList.remove("d-none");
    var container = document.getElementById("rb-modular-tabs");
    var strategies = _orderedStrategies(payload);
    var partitions = Object.keys(modular);

    // One Bootstrap nav-tabs strip per partition, with one row of charts inside each tab.
    var navHtml = "<ul class=\"nav nav-tabs mb-3\" role=\"tablist\">";
    var paneHtml = "<div class=\"tab-content\">";
    partitions.forEach(function (p, i) {
        var id = "rb-modular-" + p.replace(/[^a-z0-9_-]/gi, "_");
        navHtml += "<li class=\"nav-item\"><a class=\"nav-link" + (i === 0 ? " active" : "") + "\"" +
            " data-bs-toggle=\"tab\" href=\"#" + id + "\" role=\"tab\">" + p + "</a></li>";
        paneHtml += "<div class=\"tab-pane fade" + (i === 0 ? " show active" : "") + "\" id=\"" + id + "\" role=\"tabpanel\">" +
            "<div class=\"rb-grid\" data-partition=\"" + p + "\"></div></div>";
    });
    navHtml += "</ul>";
    paneHtml += "</div>";
    container.innerHTML = navHtml + paneHtml;

    var n_points = payload.strategies[strategies[0]].curve_wcc.length;
    var fractionRemoved = [];
    for (var i = 0; i < n_points; i++) fractionRemoved.push(i / (n_points - 1));

    partitions.forEach(function (p) {
        var grid = container.querySelector("[data-partition=\"" + p + "\"]");
        strategies.forEach(function (s) {
            var curves = modular[p][s];
            if (!curves) return;
            var card = document.createElement("div");
            card.className = "rb-chart-card";
            var title = document.createElement("h5");
            title.innerHTML = _STRATEGY_LABEL[s] + " <span class=\"text-muted small\">(" + p + ")</span>";
            card.appendChild(title);
            var wrap = document.createElement("div");
            wrap.className = "rb-chart-canvas";
            var canvas = document.createElement("canvas");
            wrap.appendChild(canvas);
            card.appendChild(wrap);
            grid.appendChild(card);

            new Chart(canvas, {
                type: "line",
                data: {
                    datasets: [
                        _buildLineDataset("intra-community", "#3b82f6", curves.intra, fractionRemoved),
                        _buildLineDataset("inter-community", "#ef4444", curves.inter, fractionRemoved),
                    ],
                },
                options: {
                    animation: false, responsive: true, maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    plugins: {
                        legend: { position: "bottom", labels: { boxWidth: 14, font: { size: 11 } } },
                        tooltip: {
                            callbacks: {
                                title: function (items) {
                                    return "Removed: " + (items[0].parsed.x * 100).toFixed(1) + "%";
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            type: "linear", min: 0, max: 1,
                            title: { display: true, text: "Fraction of nodes removed", font: { size: 12 } },
                            grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } },
                        },
                        y: {
                            min: 0,
                            title: { display: true, text: "Fraction of edges surviving", font: { size: 12 } },
                            grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } },
                        },
                    },
                },
            });
        });
    });
}

// ── Main entry point ────────────────────────────────────────────────────────

fetch(_dd + "robustness.json")
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
    .then(function (payload) {
        _renderHeaderSummary(payload);
        _renderSummaryTable(payload);
        _renderCurves(payload);
        _renderModular(payload);
    })
    .catch(function () {
        document.getElementById("rb-summary").textContent = "Failed to load robustness.json.";
    });
