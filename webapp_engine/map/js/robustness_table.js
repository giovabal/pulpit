// Render the robustness analysis page from data/robustness.json.
//
// Layout:
//   - top text:  the scope line (network size, backbone, strategies, random networks)
//   - summary:   one table row per (strategy × metric) — R, R_null mean/std, z, p, q, f_c
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
import { escHtml, fetchJson, fetchJsonOrNull, isCompareDataDir, loadFailed, loadRecovered, periodDataDir, readTimeline, scopeLine } from './utils.js';
import { signed } from './table_cells.js';

var _dd = window.DATA_DIR || "data/";

// Year-switcher state — mirrors the pattern used by community_table.js and
// network_table.js: when the page was opened from a per-year data dir (e.g.
// data_2019/), _current_year holds that year and _base_dd points back at the
// global data/ root so the "All" button can fetch the global payload.
var _current_year = "all";
// A compare page (data_2/) shows the full range only: it carries no timeline of its own.
var _base_dd = _dd;
var _no_timeline = isCompareDataDir(_dd);
var _tl_events = [];
var _cache = {};
var _ty = []; // timeline years filtered to those with robustness data
var _loading = false;
var _modalChart = null; // tracks the modal's current Chart.js instance for clean teardown
var _charts = []; // the page's card charts, destroyed before a period's charts replace them

// What each family of random networks keeps of the observed one, for the scope line.
var _NULL_MODEL_TEXT = {
    configuration: "keeping every channel's tie strengths",
    reciprocal: "keeping every channel's tie strengths and its mutual ties",
};

var _METRICS = ["wcc", "scc", "reach", "strength"];
var _METRIC_LABEL = { wcc: "WCC", scc: "SCC", reach: "Reach", strength: "Strength" };

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
    "in_strength": "In-strength",
    "out_strength": "Out-strength",
    "pagerank": "PageRank",
    "betweenness": "Betweenness",
    "subscribers": "Subscribers",
    "in_strength_dyn": "In-strength dyn",
    "out_strength_dyn": "Out-strength dyn",
    "pagerank_dyn": "PageRank dyn",
    "betweenness_dyn": "Betweenness dyn",
};

// One hue per removal criterion, from the theme's validated series in fixed order; the dynamic variant of a
// criterion (recomputed after every removal) keeps its hue and is drawn dashed. Random is the neutral grey.
var _CRITERIA = ["in_strength", "out_strength", "pagerank", "betweenness", "subscribers", "collective_influence", "fragmentation"];

function _isDynamic(key) {
    return /_dyn$/.test(key);
}

function _labelOf(payload, key) {
    var s = payload && payload.strategies && payload.strategies[key];
    if (s && s.label) return s.label;
    return _STRATEGY_SHORT[key] || key;
}

function _colorOf(key) {
    var theme = pulpitTheme();
    var criterion = key.replace(/_dyn$/, "");
    if (criterion === "random") return theme.muted;
    var i = _CRITERIA.indexOf(criterion);
    return theme.series[i === -1 ? theme.series.length - 1 : i % theme.series.length];
}

// "#rrggbb" at the given opacity, for the null-model bands (canvas colours take no color-mix()).
function _withAlpha(hex, alpha) {
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
    if (!m) return hex;
    return "rgba(" + parseInt(m[1], 16) + "," + parseInt(m[2], 16) + "," + parseInt(m[3], 16) + "," + alpha + ")";
}

function _fmt(v, dp) {
    return fmtFixed(v, dp == null ? 3 : dp);
}

// Every card chart goes through here so a period switch can destroy the previous period's instances.
function _newChart(canvas, config) {
    _charts.push(new Chart(canvas, config));
}

function _destroyCharts() {
    _charts.forEach(function(chart) { chart.destroy(); });
    _charts = [];
}

// Metrics actually present in the payload — older robustness.json files
// (pre-STRENGTH) miss the newer curves, so render only what is there.
function _presentMetrics(payload, strategies) {
    if (!strategies.length) return _METRICS;
    var first = payload.strategies[strategies[0]];
    return _METRICS.filter(function(m) { return Array.isArray(first["curve_" + m]); });
}

function _orderedStrategies(payload) {
    var present = new Set(Object.keys(payload.strategies || {}));
    var ordered = [];
    _STRATEGY_ORDER.forEach(function(s) {
        if (present.has(s)) {
            ordered.push(s);
            present.delete(s);
        }
    });
    // Anything else (custom keys) lands at the end in alphabetical order.
    Array.from(present).sort().forEach(function(s) { ordered.push(s); });
    return ordered;
}

// ── Scope line ───────────────────────────────────────────────────────────────
// The shared scope line of the export pages, followed by what the attacks ran on. `meta` is the period's
// meta.json; without it the network's size comes from the robustness payload itself.

function _renderScope(payload, meta) {
    var g = payload.graph || {};
    var c = payload.config || {};
    var extra = [];
    if (g.filtered) {
        extra.push("The attacks run on its backbone, the " + fmtInt(g.backbone_n) + " channels and " + fmtInt(g.backbone_m) +
            " ties the disparity filter keeps at α = " + c.alpha + ".");
    } else if (g.filter_skipped === "uniform_weights") {
        extra.push("Every tie weighs the same, so no backbone was extracted: the attacks run on the whole network.");
    } else {
        extra.push("The attacks run on the whole network, with no backbone extracted.");
    }
    var n = Object.keys(payload.strategies || {}).length;
    extra.push(fmtInt(n) + " attack " + (n === 1 ? "strategy" : "strategies") +
        (c.n_null > 0 ? ", each compared with " + fmtInt(c.n_null) + " random networks " +
            (_NULL_MODEL_TEXT[c.null_model || "configuration"] || _NULL_MODEL_TEXT.configuration) : ", with no random networks to compare with") + ".");
    if (payload.efficiency && payload.efficiency.baseline !== undefined) {
        extra.push("Weighted efficiency of the intact strongly connected core: " + _fmt(payload.efficiency.baseline, 3) + ".");
    }
    var target = document.getElementById("rb-preamble");
    target.innerHTML = "";
    target.appendChild(scopeLine(meta || { total_nodes: g.n, total_edges: g.m }, extra));
}

// ── Summary table ───────────────────────────────────────────────────────────

function _renderSummaryTable(payload) {
    var strategies = _orderedStrategies(payload);
    var hasNull = strategies.some(function(s) { return payload.strategies[s].null; });
    var thead = document.querySelector("#rb-summary-table thead");
    var tbody = document.querySelector("#rb-summary-table tbody");

    var headerCells = [
        "<th>Strategy</th>",
        "<th>Measure</th>",
        "<th class=\"number\" title=\"R-index: the area under the residual-size curve; lower = the network breaks faster\">R</th>",
    ];
    if (hasNull) {
        headerCells.push("<th class=\"number\" title=\"Mean R over the random networks\">Random R, mean</th>");
        headerCells.push("<th class=\"number\" title=\"Standard deviation of R over the random networks\">Random R, SD</th>");
        headerCells.push("<th class=\"number\">z</th>");
        headerCells.push("<th class=\"number\">p</th>");
        headerCells.push("<th class=\"number\">q</th>");
    }
    headerCells.push("<th class=\"number\" title=\"Share of the channels removed when the residual size falls to 5%\">Critical share</th>");
    thead.innerHTML = "<tr>" + headerCells.join("") + "</tr>";
    var table = thead.closest("table");
    table.removeAttribute("data-sort-initialized");

    var rows = [];
    var metrics = _presentMetrics(payload, strategies);
    strategies.forEach(function(s) {
        var p = payload.strategies[s];
        var nullData = p.null || {};
        metrics.forEach(function(m) {
            var nullM = nullData["r_" + m] || {};
            var r = p["r_" + m];
            var fc = p["fc_" + m];
            var cells = [
                "<td>" + escHtml(_labelOf(payload, s)) + "</td>",
                "<td>" + _METRIC_LABEL[m] + "</td>",
                "<td class=\"number\" data-sort-value=\"" + numSortVal(r) + "\">" + _fmt(r) + "</td>",
            ];
            if (hasNull) {
                cells.push("<td class=\"number\" data-sort-value=\"" + numSortVal(nullM.mean) + "\">" + _fmt(nullM.mean) + "</td>");
                cells.push("<td class=\"number\" data-sort-value=\"" + numSortVal(nullM.std) + "\">" + _fmt(nullM.std) + "</td>");
                cells.push("<td class=\"number\" data-sort-value=\"" + numSortVal(nullM.z) + "\">" + signed(nullM.z, 2) + "</td>");
                cells.push("<td class=\"number\" data-sort-value=\"" + numSortVal(nullM.p) + "\">" + fmtP(nullM.p) + "</td>");
                cells.push("<td class=\"number\" data-sort-value=\"" + numSortVal(nullM.q) + "\">" + qHtml(nullM.q) + "</td>");
            }
            cells.push("<td class=\"number\" data-sort-value=\"" + numSortVal(fc) + "\">" + fmtShare(fc) + "</td>");
            rows.push("<tr>" + cells.join("") + "</tr>");
        });
    });
    tbody.innerHTML = rows.join("");
    var legend = document.getElementById("rb-summary-legend");
    if (legend) legend.textContent = hasNull ? sigLegend("q") : "";
    initSortableTables();
}

// ── Chart config builders (pure — used for both small cards and modal) ──────

function _buildLineDataset(label, color, data, fractionRemoved, dashed) {
    return {
        label: label,
        data: data.map(function(y, i) { return { x: fractionRemoved[i], y: y }; }),
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        borderDash: dashed ? [6, 4] : [],
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
    };
}

// The random networks' mean ± one standard deviation of a strategy's curve, as a band in its colour: two
// datasets (upper, then lower filled up to it) kept out of the legend and the tooltip.
function _bandDatasets(color, mean, std, fractionRemoved) {
    if (!mean || !std || mean.length !== fractionRemoved.length) return [];

    function edge(sign) {
        return mean.map(function(v, i) {
            return { x: fractionRemoved[i], y: Math.max(0, v + sign * (std[i] || 0)) };
        });
    }
    var common = { borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, tension: 0.1, _band: true };
    return [
        Object.assign({ label: "", data: edge(1), fill: false }, common),
        Object.assign({ label: "", data: edge(-1), fill: "-1", backgroundColor: _withAlpha(color, 0.13) }, common),
    ];
}

function _baseChartOptions(yAxisTitle) {
    return {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
            legend: {
                position: "bottom",
                labels: {
                    boxWidth: 14,
                    font: { size: 11 },
                    filter: function(item, data) { return !data.datasets[item.datasetIndex]._band; },
                },
            },
            tooltip: {
                filter: function(item) { return !item.dataset._band; },
                callbacks: {
                    title: function(items) {
                        return "Removed: " + fmtShare(items[0].parsed.x);
                    },
                },
            },
        },
        scales: {
            x: {
                type: "linear",
                min: 0,
                max: 1,
                title: { display: true, text: "Share of channels removed", font: { size: 12 } },
                ticks: { font: { size: 11 } },
            },
            y: {
                min: 0,
                title: { display: true, text: yAxisTitle, font: { size: 12 } },
                ticks: { font: { size: 11 } },
            },
        },
    };
}

function _curveChartConfig(payload, metric, strategies, fractionRemoved) {
    var bands = [];
    strategies.forEach(function(s) {
        var nul = payload.strategies[s].null;
        if (nul) bands = bands.concat(_bandDatasets(_colorOf(s), nul["curve_" + metric + "_mean"], nul["curve_" + metric + "_std"], fractionRemoved));
    });
    var lines = strategies.map(function(s) {
        return _buildLineDataset(
            _labelOf(payload, s),
            _colorOf(s),
            payload.strategies[s]["curve_" + metric],
            fractionRemoved,
            _isDynamic(s)
        );
    });
    var datasets = bands.concat(lines);
    var options = _baseChartOptions("S(f)");
    options.plugins.tooltip.callbacks.label = function(ctx) {
        return ctx.dataset.label + ": " + fmtFixed(ctx.parsed.y, 3);
    };
    return { type: "line", data: { datasets: datasets }, options: options };
}

function _modularChartConfig(curves, fractionRemoved) {
    return {
        type: "line",
        data: {
            datasets: [
                _buildLineDataset("Within communities", pulpitTheme().series[0], curves.intra, fractionRemoved),
                _buildLineDataset("Between communities", pulpitTheme().series[1], curves.inter, fractionRemoved),
            ],
        },
        options: _baseChartOptions("Share of ties surviving"),
    };
}

function _efficiencyChartConfig(payload, strategies) {
    var eff = payload.efficiency;
    var datasets = strategies.filter(function(s) { return eff.curves[s]; }).map(function(s) {
        return _buildLineDataset(_labelOf(payload, s), _colorOf(s), eff.curves[s], eff.fractions, _isDynamic(s));
    });
    var options = _baseChartOptions("E(f)");
    options.plugins.tooltip.callbacks.label = function(ctx) {
        return ctx.dataset.label + ": " + fmtFixed(ctx.parsed.y, 3);
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
    btn.addEventListener("click", function() { _openChartModal(title, configBuilder); });
    card.appendChild(btn);
}

function _openChartModal(title, configBuilder) {
    if (_modalChart) {
        _modalChart.destroy();
        _modalChart = null;
    }
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
document.addEventListener("DOMContentLoaded", function() {
    var modalEl = document.getElementById("rb-chart-modal");
    if (modalEl) {
        modalEl.addEventListener("hidden.bs.modal", function() {
            if (_modalChart) {
                _modalChart.destroy();
                _modalChart = null;
            }
        });
    }
});

// ── Curve charts (one per metric) ───────────────────────────────────────────

function _renderCurves(payload) {
    var container = document.getElementById("rb-curves");
    container.innerHTML = ""; // idempotent: the previous period's charts were destroyed by _render
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
        var title = document.createElement("h3");
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
        _newChart(canvas, buildConfig());
        _attachExpandButton(card, titleText, buildConfig);
    }

    _presentMetrics(payload, strategies).forEach(function(m) {
        _addChartCard(
            "S(f) — " + _METRIC_LABEL[m],
            strategies.length + " strategies, " + fractionRemoved.length + " removal steps",
            function() { return _curveChartConfig(payload, m, strategies, fractionRemoved); }
        );
    });

    // Coarse weighted-efficiency curves (observed backbone only, no null band).
    var eff = payload.efficiency;
    if (eff && eff.curves && eff.fractions && Object.keys(eff.curves).length) {
        _addChartCard(
            "Weighted efficiency — E(f)",
            Object.keys(eff.curves).length + " strategies, " + eff.fractions.length + " evaluation points",
            function() { return _efficiencyChartConfig(payload, strategies); }
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

    // A residual-size cell shows S after the block ban next to the equal-size random baseline, and sorts on S.
    // S below its baseline marks a load-bearing block, whose ban damages the network beyond what its size explains.
    function _cell(s, rnd) {
        if (isNil(s)) return "<td class=\"number\">" + MISSING + "</td>";
        var base = isNil(rnd) ? "" : " <span class=\"text-muted\">(random " + _fmt(rnd, 3) + ")</span>";
        return "<td class=\"number nowrap\" data-sort-value=\"" + numSortVal(s) + "\">" + _fmt(s, 3) + base + "</td>";
    }

    Object.keys(banWaves).forEach(function(p) {
        var rows = banWaves[p];
        if (!rows || !rows.length) return;
        var metrics = _METRICS.filter(function(m) { return ("s_" + m) in rows[0]; });
        var html = "<h3>" + escHtml(strategy_label(p)) + "</h3>";
        html += "<div class=\"table-responsive mb-3\"><table class=\"table table-sm sortable rb-summary-table\">";
        html += "<thead><tr><th>Community</th><th class=\"number\">Channels</th><th class=\"number\">Share of the network</th>";
        metrics.forEach(function(m) {
            html += "<th class=\"number\">S<sub>" + _METRIC_LABEL[m].toLowerCase() + "</sub></th>";
        });
        html += "</tr></thead><tbody>";
        rows.forEach(function(row) {
            // Label-group communities carry a human name; algorithmic ones fall back to the id.
            html += "<tr><td>" + escHtml(row.community_label || row.community) + "</td>";
            html += "<td class=\"number\" data-sort-value=\"" + numSortVal(row.n) + "\">" + fmtInt(row.n) + "</td>";
            html += "<td class=\"number\" data-sort-value=\"" + numSortVal(row.fraction) + "\">" + fmtShare(row.fraction) + "</td>";
            metrics.forEach(function(m) {
                html += _cell(row["s_" + m], row["random_" + m]);
            });
            html += "</tr>";
        });
        html += "</tbody></table></div>";
        container.insertAdjacentHTML("beforeend", html);
    });
    initSortableTables();
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

    // For a wave period, the predicted / random / observed residual sizes side by side per metric; the cell
    // sorts on the predicted one.
    function _cell(pred, rnd, obs) {
        return "<td class=\"number nowrap\" data-sort-value=\"" + numSortVal(pred) + "\">" +
            _fmt(pred, 3) + " / " + _fmt(rnd, 3) + " / " + _fmt(obs, 3) + "</td>";
    }

    var metrics = _METRICS.filter(function(m) { return ("predicted_" + m) in rows[0]; });
    var html = "<p class=\"text-muted small mb-2\">Each cell shows the predicted / random-baseline / observed " +
        "residual size, in that order. Observed below predicted: the wave cascaded beyond the closed channels. " +
        "Observed above predicted: the survivors re-wired around the gap.</p>";
    html += "<div class=\"table-responsive mb-3\"><table class=\"table table-sm sortable rb-summary-table\">";
    html += "<thead><tr><th>Wave period</th><th class=\"number\">Channels before</th>" +
        "<th class=\"number\">Closed</th><th class=\"number\">Share of the network</th>";
    metrics.forEach(function(m) {
        html += "<th class=\"number\">S<sub>" + _METRIC_LABEL[m].toLowerCase() + "</sub></th>";
    });
    html += "</tr></thead><tbody>";
    rows.forEach(function(row) {
        html += "<tr><td data-sort-value=\"" + escHtml(String(row.period || row.label)) + "\">" + escHtml(String(row.label || row.period)) + "</td>";
        html += "<td class=\"number\" data-sort-value=\"" + numSortVal(row.n_pre) + "\">" + fmtInt(row.n_pre) + "</td>";
        html += "<td class=\"number\" data-sort-value=\"" + numSortVal(row.n_closed) + "\">" + fmtInt(row.n_closed) + "</td>";
        html += "<td class=\"number\" data-sort-value=\"" + numSortVal(row.fraction) + "\">" + fmtShare(row.fraction) + "</td>";
        metrics.forEach(function(m) {
            html += _cell(row["predicted_" + m], row["random_" + m], row["observed_" + m]);
        });
        html += "</tr>";
    });
    html += "</tbody></table></div>";
    container.insertAdjacentHTML("beforeend", html);
    initSortableTables();
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

    var strategies = (sens.strategies || []).filter(function(s) { return payload.strategies[s]; });
    // One sub-table per metric: rows = α values, columns = strategies, cells = R.
    var metrics = _METRICS.filter(function(m) {
        return sens.rows[0].r && sens.rows[0].r[strategies[0]] && (m in sens.rows[0].r[strategies[0]]);
    });
    metrics.forEach(function(m) {
        var html = "<h3>R<sub>" + _METRIC_LABEL[m].toLowerCase() + "</sub> across α</h3>";
        html += "<div class=\"table-responsive mb-3\"><table class=\"table table-sm sortable rb-summary-table\">";
        html += "<thead><tr><th class=\"number\">α</th><th class=\"number\">Backbone ties</th>";
        strategies.forEach(function(s) {
            html += "<th class=\"number\">" + escHtml(_labelOf(payload, s)) + "</th>";
        });
        html += "</tr></thead><tbody>";
        sens.rows.forEach(function(row) {
            var aTxt = row.alpha === 0 ? "whole network" : row.alpha;
            html += "<tr><td class=\"number\" data-sort-value=\"" + numSortVal(row.alpha) + "\">" + aTxt + "</td>";
            html += "<td class=\"number\" data-sort-value=\"" + numSortVal(row.backbone_m) + "\">" + fmtInt(row.backbone_m) + "</td>";
            strategies.forEach(function(s) {
                var r = row.r && row.r[s] ? row.r[s][m] : null;
                html += "<td class=\"number\" data-sort-value=\"" + numSortVal(r) + "\">" + _fmt(r, 3) + "</td>";
            });
            html += "</tr>";
        });
        html += "</tbody></table></div>";
        container.insertAdjacentHTML("beforeend", html);
    });
    initSortableTables();
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
    partitions.forEach(function(p, i) {
        var id = "rb-modular-" + p.replace(/[^a-z0-9_-]/gi, "_");
        navHtml += "<li class=\"nav-item\"><a class=\"nav-link" + (i === 0 ? " active" : "") + "\"" +
            " data-bs-toggle=\"tab\" href=\"#" + id + "\" role=\"tab\">" + escHtml(strategy_label(p)) + "</a></li>";
        paneHtml += "<div class=\"tab-pane fade" + (i === 0 ? " show active" : "") + "\" id=\"" + id + "\" role=\"tabpanel\">" +
            "<div class=\"rb-grid\" data-partition=\"" + p + "\"></div></div>";
    });
    navHtml += "</ul>";
    paneHtml += "</div>";
    container.innerHTML = navHtml + paneHtml;

    var n_points = payload.strategies[strategies[0]].curve_wcc.length;
    var fractionRemoved = [];
    for (var i = 0; i < n_points; i++) fractionRemoved.push(i / (n_points - 1));

    partitions.forEach(function(p) {
        var grid = container.querySelector("[data-partition=\"" + p + "\"]");
        strategies.forEach(function(s) {
            var curves = modular[p][s];
            if (!curves) return;
            var card = document.createElement("div");
            card.className = "rb-chart-card";
            var title = document.createElement("h3");
            title.innerHTML = escHtml(_labelOf(payload, s)) + " <span class=\"text-muted small\">(" + escHtml(strategy_label(p)) + ")</span>";
            card.appendChild(title);
            var wrap = document.createElement("div");
            wrap.className = "rb-chart-canvas";
            var canvas = document.createElement("canvas");
            wrap.appendChild(canvas);
            card.appendChild(wrap);
            grid.appendChild(card);

            var buildConfig = function() { return _modularChartConfig(curves, fractionRemoved); };
            var modularTitle = _labelOf(payload, s) + " (" + strategy_label(p) + ")";
            if (window.PulpitA11y) {
                window.PulpitA11y.accessibleChart(canvas, {
                    label: "Modular robustness: " + modularTitle,
                    summary: "Share of the ties within and between communities surviving across " + fractionRemoved.length + " removal steps",
                });
            }
            _newChart(canvas, buildConfig());
            // Plain-text title (HTML in the card heading; modal needs a string).
            _attachExpandButton(card, modularTitle, buildConfig);
        });
    });
}

// ── Year-aware load / render / switch ───────────────────────────────────────

function _render(loaded) {
    var payload = loaded.payload;
    _destroyCharts();
    _renderScope(payload, loaded.meta);
    _renderSummaryTable(payload);
    _renderCurves(payload);
    _renderBanReplay(payload);
    _renderAlphaSensitivity(payload);
    _renderBanWaves(payload);
    _renderModular(payload);
}

function _load(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : periodDataDir("data/", year);
    return Promise.all([fetchJson(dd + "robustness.json"), fetchJsonOrNull(dd + "meta.json")])
        .then(function(res) {
            _cache[year] = { payload: res[0], meta: res[1] };
            return _cache[year];
        });
}

function _switch_year(year) {
    if (year === _current_year || _loading) return;
    _loading = true;
    // Close any open modal — its chart is built from the previous year's data.
    _closeChartModal();
    _load(year).then(function(loaded) {
        _current_year = year;
        loadRecovered();
        _render(loaded);
        if (_ty.length) build_year_nav(_ty, _current_year, _switch_year, _tl_events);
    }).catch(function(err) {
        loadFailed(err, "the robustness analysis of " + year);
    }).finally(function() {
        _loading = false;
    });
}

// ── Main entry point ────────────────────────────────────────────────────────

Promise.all([
    _load(_current_year),
    fetchJsonOrNull(_base_dd + "timeline.json"),
]).then(function(results) {
    var timeline = results[1];
    _render(results[0]);
    var _tl = readTimeline(_no_timeline ? null : timeline);
    _tl_events = _tl.events;
    _ty = _tl.periods.filter(function(y) { return y.has_robustness; });
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year, _tl_events);
}).catch(function(err) {
    loadFailed(err);
});
