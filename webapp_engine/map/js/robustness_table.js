// Render the robustness analysis page from data/robustness.json.
//
// Layout:
//   - top text:  one-line summary (graph size, alpha, # strategies, # nulls)
//   - summary:   one table row per (strategy × metric) — R, R_null mean/std, z, f_c
//   - curves:    four Chart.js line charts (WCC / SCC / REACH / STRENGTH), one
//                line per strategy, plus the coarse weighted-efficiency chart
//   - ban wave:  per-partition table — residual sizes after removing each whole
//                community, next to the equal-q random baseline
//   - modular:   per-partition section with intra/inter curves per strategy
//
// Every chart card carries a discreet "expand" button in the top-right corner;
// clicking it opens the same chart in a large Bootstrap modal so dense plots
// can be inspected without zooming the browser.

import { build_year_nav } from './year_nav.js';
import { strategy_label } from './labels.js';
import { escHtml, fetchJson, fetchJsonOrNull } from './utils.js';

var _dd = window.DATA_DIR || "data/";

// Year-switcher state — mirrors the pattern used by community_table.js and
// network_table.js: when the page was opened from a per-year data dir (e.g.
// data_2019/), _current_year holds that year and _base_dd points back at the
// global data/ root so the "All" button can fetch the global payload.
var _ym = _dd.match(/data_(\d{4,})\//);
var _current_year = _ym ? parseInt(_ym[1]) : "all";
var _base_dd = _ym ? "data/" : _dd;
var _cache = {};
var _ty = [];  // timeline years filtered to those with robustness data
var _loading = false;
var _modalChart = null;  // tracks the modal's current Chart.js instance for clean teardown

var _METRICS = ["wcc", "scc", "reach", "strength"];
var _METRIC_LABEL = { wcc: "WCC", scc: "SCC", reach: "REACH", strength: "STRENGTH" };

// Strategy ordering — matches network.robustness.attacks.ALL_STRATEGIES.
var _STRATEGY_ORDER = [
    "random",
    "in_strength", "out_strength",
    "pagerank",
    "betweenness",
    "subscribers",
    "in_strength_dyn", "out_strength_dyn",
    "pagerank_dyn",
    "betweenness_dyn",
];

// Compact short labels — kept terse so the legend stays readable when many
// strategies overlap.  The full label comes from the payload's per-strategy
// "label" field; this map is the fallback.
var _STRATEGY_SHORT = {
    "random": "Random",
    "in_strength": "In-strength", "out_strength": "Out-strength",
    "pagerank": "PageRank",
    "betweenness": "Betweenness",
    "subscribers": "Subscribers",
    "in_strength_dyn": "In-strength dyn", "out_strength_dyn": "Out-strength dyn",
    "pagerank_dyn": "PageRank dyn",
    "betweenness_dyn": "Betweenness dyn",
};

// Accessible palette grouped by attack-family hue.
var _STRATEGY_COLOR = {
    "random": "#94a3b8",
    "in_strength": "#3b82f6", "out_strength": "#06b6d4",
    "pagerank": "#ef4444",
    "betweenness": "#8b5cf6",
    "subscribers": "#f59e0b",
    "in_strength_dyn": "#1d4ed8", "out_strength_dyn": "#0e7490",
    "pagerank_dyn": "#b91c1c",
    "betweenness_dyn": "#6d28d9",
};

function _labelOf(payload, key) {
    var s = payload && payload.strategies && payload.strategies[key];
    if (s && s.label) return s.label;
    return _STRATEGY_SHORT[key] || key;
}

function _colorOf(key) {
    return _STRATEGY_COLOR[key] || "#6b7280";
}

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

// Two-sided add-one empirical p — bold at the conventional 0.05 cut.  Older
// payloads (pre-p) simply miss the key and render a dash.
function _fmtP(p) {
    if (p === null || p === undefined || typeof p !== "number" || !isFinite(p)) return "—";
    var cls = p <= 0.05 ? " class=\"rb-z-significant\"" : "";
    return "<span" + cls + ">" + p.toFixed(3) + "</span>";
}

// Metrics actually present in the payload — older robustness.json files
// (pre-STRENGTH) miss the newer curves, so render only what is there.
function _presentMetrics(payload, strategies) {
    if (!strategies.length) return _METRICS;
    var first = payload.strategies[strategies[0]];
    return _METRICS.filter(function (m) { return Array.isArray(first["curve_" + m]); });
}

function _orderedStrategies(payload) {
    var present = new Set(Object.keys(payload.strategies || {}));
    var ordered = [];
    _STRATEGY_ORDER.forEach(function (s) {
        if (present.has(s)) {
            ordered.push(s);
            present.delete(s);
        }
    });
    // Anything else (custom keys) lands at the end in alphabetical order.
    Array.from(present).sort().forEach(function (s) { ordered.push(s); });
    return ordered;
}

// ── Header summary ───────────────────────────────────────────────────────────

function _renderHeaderSummary(payload) {
    var g = payload.graph || {};
    var c = payload.config || {};
    var parts = [
        g.n + " nodes / " + g.m + " edges",
        g.filtered ? "backbone " + g.backbone_n + "/" + g.backbone_m + " edges (α=" + c.alpha + ")" : "no disparity filter",
        Object.keys(payload.strategies || {}).length + " strategies",
        c.n_null > 0
            ? c.n_null + " null simulations (" + (c.null_model || "configuration") + ")"
            : "no null model",
        "seed=" + c.seed,
    ];
    if (payload.efficiency && payload.efficiency.baseline !== undefined) {
        parts.push("baseline SCC efficiency=" + _fmt(payload.efficiency.baseline, 3));
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
        headerCells.push("<th class=\"text-end\">p</th>");
        headerCells.push("<th class=\"text-end\">q</th>");
    }
    headerCells.push("<th class=\"text-end\">f<sub>c</sub> (5%)</th>");
    thead.innerHTML = "<tr>" + headerCells.join("") + "</tr>";

    var rows = [];
    var metrics = _presentMetrics(payload, strategies);
    strategies.forEach(function (s) {
        var p = payload.strategies[s];
        var nullData = p.null || {};
        metrics.forEach(function (m) {
            var nullM = nullData["r_" + m] || {};
            var r = p["r_" + m];
            var fc = p["fc_" + m];
            var cells = [
                "<td>" + _labelOf(payload, s) + "</td>",
                "<td><code>" + _METRIC_LABEL[m] + "</code></td>",
                "<td class=\"text-end\">" + _fmt(r) + "</td>",
            ];
            if (hasNull) {
                cells.push("<td class=\"text-end\">" + _fmt(nullM.mean) + "</td>");
                cells.push("<td class=\"text-end\">" + _fmt(nullM.std) + "</td>");
                cells.push("<td class=\"text-end\">" + _fmtZ(nullM.z) + "</td>");
                cells.push("<td class=\"text-end\">" + _fmtP(nullM.p) + "</td>");
                cells.push("<td class=\"text-end\">" + _fmtP(nullM.q) + "</td>");
            }
            cells.push("<td class=\"text-end\">" + _fmtFc(fc) + "</td>");
            rows.push("<tr>" + cells.join("") + "</tr>");
        });
    });
    tbody.innerHTML = rows.join("");
}

// ── Chart config builders (pure — used for both small cards and modal) ──────

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

function _baseChartOptions(yAxisTitle) {
    return {
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
                title: { display: true, text: yAxisTitle, font: { size: 12 } },
                grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } },
            },
        },
    };
}

function _curveChartConfig(payload, metric, strategies, fractionRemoved) {
    var datasets = strategies.map(function (s) {
        return _buildLineDataset(
            _labelOf(payload, s),
            _colorOf(s),
            payload.strategies[s]["curve_" + metric],
            fractionRemoved
        );
    });
    var options = _baseChartOptions("S(f)");
    options.plugins.tooltip.callbacks.label = function (ctx) {
        return ctx.dataset.label + ": " + ctx.parsed.y.toFixed(4);
    };
    return { type: "line", data: { datasets: datasets }, options: options };
}

function _modularChartConfig(curves, fractionRemoved) {
    return {
        type: "line",
        data: {
            datasets: [
                _buildLineDataset("intra-community", "#3b82f6", curves.intra, fractionRemoved),
                _buildLineDataset("inter-community", "#ef4444", curves.inter, fractionRemoved),
            ],
        },
        options: _baseChartOptions("Fraction of edges surviving"),
    };
}

function _efficiencyChartConfig(payload, strategies) {
    var eff = payload.efficiency;
    var datasets = strategies.filter(function (s) { return eff.curves[s]; }).map(function (s) {
        return _buildLineDataset(_labelOf(payload, s), _colorOf(s), eff.curves[s], eff.fractions);
    });
    var options = _baseChartOptions("E(f)");
    options.plugins.tooltip.callbacks.label = function (ctx) {
        return ctx.dataset.label + ": " + ctx.parsed.y.toFixed(4);
    };
    return { type: "line", data: { datasets: datasets }, options: options };
}

// ── Modal expansion of charts ─────────────────────────────────────────────────

function _attachExpandButton(card, title, configBuilder) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rb-expand-btn";
    btn.title = "Expand chart";
    btn.setAttribute("aria-label", "Expand chart");
    btn.innerHTML = '<i class="bi bi-arrows-fullscreen" aria-hidden="true"></i>';
    btn.addEventListener("click", function () { _openChartModal(title, configBuilder); });
    card.appendChild(btn);
}

function _openChartModal(title, configBuilder) {
    if (_modalChart) { _modalChart.destroy(); _modalChart = null; }
    document.getElementById("rb-chart-modal-title").textContent = title;
    var canvas = document.getElementById("rb-chart-modal-canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", title);
    // Build a fresh config each time so the modal chart is fully independent of
    // the small card chart (no shared dataset arrays).
    _modalChart = new Chart(canvas, configBuilder());
    var modalEl = document.getElementById("rb-chart-modal");
    if (window.bootstrap) bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

function _closeChartModal() {
    var modalEl = document.getElementById("rb-chart-modal");
    var inst = window.bootstrap && bootstrap.Modal.getInstance(modalEl);
    if (inst) inst.hide();
}

// Free the modal chart instance once the modal finishes its hide animation.
document.addEventListener("DOMContentLoaded", function () {
    var modalEl = document.getElementById("rb-chart-modal");
    if (modalEl) {
        modalEl.addEventListener("hidden.bs.modal", function () {
            if (_modalChart) { _modalChart.destroy(); _modalChart = null; }
        });
    }
});

// ── Curve charts (one per metric) ───────────────────────────────────────────

function _renderCurves(payload) {
    var container = document.getElementById("rb-curves");
    container.innerHTML = "";  // idempotent — wipe stale charts when re-rendering on year switch
    var strategies = _orderedStrategies(payload);
    if (!strategies.length) {
        container.innerHTML = "<p class=\"rb-empty\">No attack strategies were run.</p>";
        return;
    }

    var firstStrategy = payload.strategies[strategies[0]];
    var n_points = firstStrategy.curve_wcc.length;
    var fractionRemoved = [];
    for (var i = 0; i < n_points; i++) fractionRemoved.push(i / (n_points - 1));

    function _addChartCard(titleText, summary, buildConfig) {
        var card = document.createElement("div");
        card.className = "rb-chart-card";
        var title = document.createElement("h5");
        title.textContent = titleText;
        card.appendChild(title);
        var wrap = document.createElement("div");
        wrap.className = "rb-chart-canvas";
        var canvas = document.createElement("canvas");
        wrap.appendChild(canvas);
        card.appendChild(wrap);
        container.appendChild(card);

        if (window.PulpitA11y) {
            window.PulpitA11y.accessibleChart(canvas, { label: titleText, summary: summary });
        }
        new Chart(canvas, buildConfig());
        _attachExpandButton(card, titleText, buildConfig);
    }

    _presentMetrics(payload, strategies).forEach(function (m) {
        _addChartCard(
            "S(f) — " + _METRIC_LABEL[m],
            strategies.length + " strategies, " + fractionRemoved.length + " removal steps",
            function () { return _curveChartConfig(payload, m, strategies, fractionRemoved); }
        );
    });

    // Coarse weighted-efficiency curves (observed backbone only, no null band).
    var eff = payload.efficiency;
    if (eff && eff.curves && eff.fractions && Object.keys(eff.curves).length) {
        _addChartCard(
            "Weighted efficiency — E(f)",
            Object.keys(eff.curves).length + " strategies, " + eff.fractions.length + " evaluation points",
            function () { return _efficiencyChartConfig(payload, strategies); }
        );
    }
}

// ── Ban-wave section ─────────────────────────────────────────────────────────

function _renderBanWaves(payload) {
    var section = document.getElementById("rb-banwave-section");
    var container = document.getElementById("rb-banwave-tables");
    if (!section || !container) return;
    container.innerHTML = "";
    var banWaves = payload.ban_waves;
    if (!banWaves || !Object.keys(banWaves).length) {
        section.classList.add("d-none");
        return;
    }
    section.classList.remove("d-none");

    // A residual-size cell shows S after the block ban next to the equal-q
    // random baseline; S far below the baseline (red) marks a load-bearing
    // block whose ban damages the network beyond what its size explains.
    function _cell(s, rnd) {
        if (s === null || s === undefined) return "<td class=\"text-end\">—</td>";
        var cls = "";
        if (typeof rnd === "number" && isFinite(rnd)) {
            if (s < rnd) cls = " class=\"text-end rb-z-significant rb-z-neg\"";
            else cls = " class=\"text-end\"";
        } else {
            cls = " class=\"text-end\"";
        }
        var base = (typeof rnd === "number" && isFinite(rnd)) ? " <span class=\"text-muted\">(rnd " + _fmt(rnd, 3) + ")</span>" : "";
        return "<td" + cls + ">" + _fmt(s, 3) + base + "</td>";
    }

    Object.keys(banWaves).forEach(function (p) {
        var rows = banWaves[p];
        if (!rows || !rows.length) return;
        var metrics = _METRICS.filter(function (m) { return ("s_" + m) in rows[0]; });
        var html = "<h5 class=\"mt-3\">" + strategy_label(p) + "</h5>";
        html += "<div class=\"table-responsive mb-3\"><table class=\"table table-sm rb-summary-table\">";
        html += "<thead><tr><th>Community</th><th class=\"text-end\">Channels</th><th class=\"text-end\">% of network</th>";
        metrics.forEach(function (m) {
            html += "<th class=\"text-end\">S<sub>" + _METRIC_LABEL[m].toLowerCase() + "</sub></th>";
        });
        html += "</tr></thead><tbody>";
        rows.forEach(function (row) {
            // Label-group communities carry a human name; algorithmic ones fall back to the id.
            html += "<tr><td>" + escHtml(row.community_label || row.community) + "</td>";
            html += "<td class=\"text-end\">" + row.n + "</td>";
            html += "<td class=\"text-end\">" + (row.fraction * 100).toFixed(1) + "%</td>";
            metrics.forEach(function (m) {
                html += _cell(row["s_" + m], row["random_" + m]);
            });
            html += "</tr>";
        });
        html += "</tbody></table></div>";
        container.insertAdjacentHTML("beforeend", html);
    });
}

// ── Ban-replay section ───────────────────────────────────────────────────────

function _renderBanReplay(payload) {
    var section = document.getElementById("rb-replay-section");
    var container = document.getElementById("rb-replay-tables");
    if (!section || !container) return;
    container.innerHTML = "";
    var rows = payload.ban_replay;
    if (!rows || !rows.length) {
        section.classList.add("d-none");
        return;
    }
    section.classList.remove("d-none");

    // For a wave year, show predicted / random / observed residual side by side
    // per metric. Observed far below predicted (red) = the ban cascaded beyond
    // the block; observed above predicted (green) = the network rewired around it.
    function _cell(pred, rnd, obs) {
        var predTxt = _fmt(pred, 3);
        var rndTxt = (typeof rnd === "number" && isFinite(rnd)) ? _fmt(rnd, 3) : "—";
        if (obs === null || obs === undefined) {
            return "<td class=\"text-end\">" + predTxt + " / " + rndTxt + " / —</td>";
        }
        var cls = " class=\"text-end\"";
        if (typeof pred === "number" && isFinite(pred)) {
            if (obs < pred - 1e-9) cls = " class=\"text-end rb-z-significant rb-z-neg\"";
            else if (obs > pred + 1e-9) cls = " class=\"text-end rb-z-significant rb-z-pos\"";
        }
        return "<td" + cls + ">" + predTxt + " / " + rndTxt + " / <strong>" + _fmt(obs, 3) + "</strong></td>";
    }

    var metrics = _METRICS.filter(function (m) { return ("predicted_" + m) in rows[0]; });
    var html = "<p class=\"text-muted small mb-2\">Each cell shows " +
        "<em>predicted</em> / <em>random baseline</em> / <strong>observed</strong> residual size. " +
        "Observed below predicted (red) = the wave cascaded beyond the banned block; " +
        "observed above predicted (green) = survivors re-wired around the gap.</p>";
    html += "<div class=\"table-responsive mb-3\"><table class=\"table table-sm rb-summary-table\">";
    html += "<thead><tr><th>Wave year</th><th class=\"text-end\">Pre-wave nodes</th>" +
        "<th class=\"text-end\">Closed</th><th class=\"text-end\">% of network</th>";
    metrics.forEach(function (m) {
        html += "<th class=\"text-end\">S<sub>" + _METRIC_LABEL[m].toLowerCase() + "</sub></th>";
    });
    html += "</tr></thead><tbody>";
    rows.forEach(function (row) {
        html += "<tr><td>" + row.year + "</td>";
        html += "<td class=\"text-end\">" + row.n_pre + "</td>";
        html += "<td class=\"text-end\">" + row.n_closed + "</td>";
        html += "<td class=\"text-end\">" + (row.fraction * 100).toFixed(1) + "%</td>";
        metrics.forEach(function (m) {
            html += _cell(row["predicted_" + m], row["random_" + m], row["observed_" + m]);
        });
        html += "</tr>";
    });
    html += "</tbody></table></div>";
    container.insertAdjacentHTML("beforeend", html);
}

// ── Backbone α-sensitivity section ───────────────────────────────────────────

function _renderAlphaSensitivity(payload) {
    var section = document.getElementById("rb-alpha-section");
    var container = document.getElementById("rb-alpha-tables");
    if (!section || !container) return;
    container.innerHTML = "";
    var sens = payload.alpha_sensitivity;
    if (!sens || !sens.rows || !sens.rows.length) {
        section.classList.add("d-none");
        return;
    }
    section.classList.remove("d-none");

    var strategies = (sens.strategies || []).filter(function (s) { return payload.strategies[s]; });
    // One sub-table per metric: rows = α values, columns = strategies, cells = R.
    var metrics = _METRICS.filter(function (m) {
        return sens.rows[0].r && sens.rows[0].r[strategies[0]] && (m in sens.rows[0].r[strategies[0]]);
    });
    metrics.forEach(function (m) {
        var html = "<h5 class=\"mt-3\">R<sub>" + _METRIC_LABEL[m].toLowerCase() + "</sub> across α</h5>";
        html += "<div class=\"table-responsive mb-3\"><table class=\"table table-sm rb-summary-table\">";
        html += "<thead><tr><th>α</th><th class=\"text-end\">Backbone edges</th>";
        strategies.forEach(function (s) {
            html += "<th class=\"text-end\">" + _labelOf(payload, s) + "</th>";
        });
        html += "</tr></thead><tbody>";
        sens.rows.forEach(function (row) {
            var aTxt = row.alpha === 0 ? "full graph" : row.alpha;
            html += "<tr><td>" + aTxt + "</td>";
            html += "<td class=\"text-end\">" + row.backbone_m + "</td>";
            strategies.forEach(function (s) {
                var r = row.r && row.r[s] ? row.r[s][m] : null;
                html += "<td class=\"text-end\">" + _fmt(r, 3) + "</td>";
            });
            html += "</tr>";
        });
        html += "</tbody></table></div>";
        container.insertAdjacentHTML("beforeend", html);
    });
}

// ── Modular section ─────────────────────────────────────────────────────────

function _renderModular(payload) {
    var section = document.getElementById("rb-modular-section");
    var container = document.getElementById("rb-modular-tabs");
    container.innerHTML = "";
    var modular = payload.modular;
    if (!modular || !Object.keys(modular).length) {
        section.classList.add("d-none");
        return;
    }
    section.classList.remove("d-none");
    var strategies = _orderedStrategies(payload);
    var partitions = Object.keys(modular);

    // One Bootstrap nav-tabs strip per partition, with one row of charts inside each tab.
    var navHtml = "<ul class=\"nav nav-tabs mb-3\" role=\"tablist\">";
    var paneHtml = "<div class=\"tab-content\">";
    partitions.forEach(function (p, i) {
        var id = "rb-modular-" + p.replace(/[^a-z0-9_-]/gi, "_");
        navHtml += "<li class=\"nav-item\"><a class=\"nav-link" + (i === 0 ? " active" : "") + "\"" +
            " data-bs-toggle=\"tab\" href=\"#" + id + "\" role=\"tab\">" + strategy_label(p) + "</a></li>";
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
            title.innerHTML = _labelOf(payload, s) + " <span class=\"text-muted small\">(" + strategy_label(p) + ")</span>";
            card.appendChild(title);
            var wrap = document.createElement("div");
            wrap.className = "rb-chart-canvas";
            var canvas = document.createElement("canvas");
            wrap.appendChild(canvas);
            card.appendChild(wrap);
            grid.appendChild(card);

            var buildConfig = function () { return _modularChartConfig(curves, fractionRemoved); };
            var modularTitle = _labelOf(payload, s) + " (" + strategy_label(p) + ")";
            if (window.PulpitA11y) {
                window.PulpitA11y.accessibleChart(canvas, {
                    label: "Modular robustness: " + modularTitle,
                    summary: "Intra- vs inter-community edge survival across " + fractionRemoved.length + " removal steps",
                });
            }
            new Chart(canvas, buildConfig());
            // Plain-text title (HTML in the card heading; modal needs a string).
            _attachExpandButton(card, modularTitle, buildConfig);
        });
    });
}

// ── Year-aware load / render / switch ───────────────────────────────────────

function _render(payload) {
    _renderHeaderSummary(payload);
    _renderSummaryTable(payload);
    _renderCurves(payload);
    _renderBanReplay(payload);
    _renderAlphaSensitivity(payload);
    _renderBanWaves(payload);
    _renderModular(payload);
}

function _load(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return fetchJson(dd + "robustness.json")
        .then(function (payload) { _cache[year] = payload; return payload; });
}

function _switch_year(year) {
    if (year === _current_year || _loading) return;
    _loading = true;
    // Close any open modal — its chart is built from the previous year's data.
    _closeChartModal();
    _load(year).then(function (payload) {
        _current_year = year;
        _render(payload);
        if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
    }).catch(function () {
        document.getElementById("rb-summary").textContent = "Failed to load robustness data for " + year + ".";
    }).finally(function () {
        _loading = false;
    });
}

// ── Main entry point ────────────────────────────────────────────────────────

Promise.all([
    _load(_current_year),
    fetchJsonOrNull(_base_dd + "timeline.json"),
]).then(function (results) {
    var payload = results[0];
    var timeline = results[1];
    _render(payload);
    _ty = timeline ? (timeline.years || []).filter(function (y) { return y.has_robustness; }) : [];
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
}).catch(function (err) {
    // Surface the actual exception in the console — silently swallowing it here
    // hides whether the failure is fetch (network / file:// scheme / 404) or a
    // downstream render bug.
    console.error("robustness_table: failed to load or render", err);
    var msg = "Failed to load robustness.json.";
    if (window.location.protocol === "file:") {
        msg += " The export bundle uses fetch() to load its JSON payloads, which most browsers refuse on file:// URLs. " +
               "Open the bundle via the bundled start.sh (\"python -m http.server\") and browse it over http://localhost:8001 instead.";
    } else if (err && err.message) {
        msg += " (" + err.message + ")";
    }
    document.getElementById("rb-summary").textContent = msg;
});
