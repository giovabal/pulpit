import { measure_label, strategy_label as _strat_label } from './labels.js';
import { build_year_nav } from './year_nav.js';
import { histogram, mini_hist as _mini_hist, power_law_fit } from './charts.js';
import { arrMax, arrMin, fetchJson, fetchJsonOrNull, isCompareDataDir, loadFailed, loadRecovered, periodDataDir, readTimeline, scopeLine } from './utils.js';
import { render_label_mixing, render_mrqap } from './label_mixing.js';

var _dd = window.DATA_DIR || "data/";
// A compare page (data_2/) shows the full range only: it carries no timeline of its own.
var _base_dd = _dd;
var _no_timeline = isCompareDataDir(_dd);
var _tl_events = [];

// ── Sparkline data — loaded once at startup, never changes ─────────────────────
var _all_map = {},
    _yr_map = {},
    _all_mod_map = {},
    _yr_mod_map = {},
    _all_years = [];
var _ty = [],
    _has_tl = false;

// ── Per-year state — updated on every year switch ──────────────────────────────
var _current_year = "all";
var _nodes = [],
    _measures = [],
    _labelOf = {};
var _cache = {};
var _loading = false;

// ── Chart object references — built once, data updated on switch ───────────────
var _distChart = null,
    _distInitialized = false,
    _distSel = null;
var _scatterChart = null,
    _xSel = null,
    _ySel = null,
    _countNote = null;

// ── Data fetching ──────────────────────────────────────────────────────────────
function _fetch_year(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : periodDataDir("data/", year);
    return Promise.all([
        fetchJson(dd + "network_metrics.json"),
        fetchJson(dd + "channels.json"),
        fetchJsonOrNull(dd + "meta.json"),
    ]).then(function(res) {
        var d = { data: res[0], channels: res[1], meta: res[2] };
        _cache[year] = d;
        return d;
    });
}

// ── Chart helpers — use module-scope _nodes ────────────────────────────────────
function _build_dist_data(key) {
    var bins = histogram([_nodes.map(function(n) { return n[key] || 0; })]);
    return { labels: bins.labels, counts: bins.counts[0] };
}

// The measures' display labels, by key.
function _read_measure_labels() {
    _labelOf = {};
    _measures.forEach(function(m) { _labelOf[m[0]] = measure_label(m[0], m[1]); });
}

function _build_scatter_data(xKey, yKey) {
    var pts = _nodes.filter(function(n) { return n[xKey] > 0 && n[yKey] > 0; })
        .map(function(n) { return { x: n[xKey], y: n[yKey], label: n.label || n.id, fans: n.fans || 0, msgs: n.messages_count || 0 }; });
    var fit = power_law_fit(pts);
    var regData = [];
    if (fit) {
        var xs = pts.map(function(p) { return p.x; });
        var xMin = arrMin(xs),
            xMax = arrMax(xs);
        regData = [{ x: xMin, y: Math.exp(fit.intercept) * Math.pow(xMin, fit.slope) },
            { x: xMax, y: Math.exp(fit.intercept) * Math.pow(xMax, fit.slope) }
        ];
    }
    return { pts: pts, regData: regData };
}

function _update_dist_chart() {
    if (!_distChart || !_distSel) return;
    var dd = _build_dist_data(_distSel.value);
    _distChart.data.labels = dd.labels;
    _distChart.data.datasets[0].data = dd.counts;
    _distChart.options.scales.x.title.text = _distAxisLabel(_distSel.value);
    _distChart.update();
}

function _update_scatter_chart() {
    if (!_scatterChart || !_xSel) return;
    var xKey = _xSel.value,
        yKey = _ySel.value;
    var ds = _build_scatter_data(xKey, yKey);
    _scatterChart.data.datasets[0].data = ds.pts;
    _scatterChart.data.datasets[1].data = ds.regData;
    _scatterChart.options.scales.x.title.text = _labelOf[xKey];
    _scatterChart.options.scales.y.title.text = _labelOf[yKey];
    _scatterChart.resetZoom();
    _scatterChart.update();
    if (_countNote) _countNote.textContent = _scatterNote(ds.pts.length);
}

function _scatterNote(n) {
    return fmtInt(n) + " channel" + (n === 1 ? "" : "s") + " (zeros left out of the log scale)";
}

function _distAxisLabel(key) {
    return key === "out_deg" ? "Out-strength" : "In-strength";
}

// ── Table renders — re-run on every year switch ────────────────────────────────
// Keyed by the statistic's name; looked up without regard to case (see _metric_tooltip).
var METRIC_TOOLTIPS = {
    "Channels": "Number of channels in the network.",
    "Ties": "Number of directed ties between channels.",
    "Ties per channel": "Mean degree: ties per channel, a rough indicator of overall connectivity.",
    "Density": "Share of all possible directed ties that exist; 0 = no tie, 1 = every channel cites every other.",
    "Reciprocity": "Share of ties that are returned; 0 = all one-way, 1 = all mutual.",
    "Mean clustering": "Mean probability that two neighbours of a channel are also tied to each other.",
    "Mean path length": "Mean undirected shortest-path distance between channels in the largest weakly connected component.",
    "Diameter": "Longest undirected shortest path in the largest weakly connected component.",
    "Directed mean path length": "Mean directed shortest-path distance, following the ties' direction, in the largest strongly connected component.",
    "Directed diameter": "Longest directed shortest path in the largest strongly connected component.",
    "Weakly connected components": "Number of weakly connected components; 1 = every channel is reachable ignoring the ties' direction.",
    "Largest weakly connected component, share": "Share of the channels in the largest weakly connected component.",
    "Strongly connected components": "Number of strongly connected components; 1 = every channel reaches every other following the ties' direction.",
    "Largest strongly connected component, share": "Share of the channels in the largest strongly connected component.",
    "Assortativity in→in": "Pearson correlation of in-degree between citing and cited channels across all ties; +1 = hubs cite hubs.",
    "Assortativity in→out": "Correlation between the citing channel's in-degree and the cited channel's out-degree.",
    "Assortativity out→in": "Correlation between the citing channel's out-degree and the cited channel's in-degree.",
    "Assortativity out→out": "Pearson correlation of out-degree between citing and cited channels; +1 = heavy citers cite heavy citers.",
    "Transitivity": "Share of connected triples that close into triangles: the global clustering coefficient, which complements mean clustering (an average of the channels' own coefficients). Luce & Perry 1949; Watts & Strogatz 1998.",
    "Global efficiency": "Mean reciprocal directed shortest-path length over all ordered pairs of channels; unreachable pairs count 0. How efficiently information can flow between any two channels, without restricting to a component. Latora & Marchiori 2001.",
    "Algebraic connectivity": "Second-smallest eigenvalue of the undirected Laplacian (Fiedler value): zero for a disconnected network; larger values signal stronger cohesion and greater resistance to fragmentation. Fiedler 1973.",
    "In-degree CV": "Coefficient of variation (σ/μ) of the in-degrees. Low = citations spread evenly; high = a few hubs absorb most of them.",
    "Out-degree CV": "Coefficient of variation (σ/μ) of the out-degrees. Low = channels cite equally; high = a few channels make most citations.",
    "Mean Burt's constraint": "Mean of the channels' Burt constraint; lower = more brokerage across structural holes.",
    "Content originality": "Share of messages that are not forwards; higher = more original content.",
    "Amplification ratio": "Mean number of times each message is re-shared within the network.",
};

// Tooltips of the per-label-group homophily rows, matched on the part after "<group>: ".
var HOMOPHILY_TOOLTIPS = {
    "assortativity r, ties": "Nominal assortativity (Newman 2003) of the ties between labelled channels: 1 = every tie stays inside its label, 0 = labels unrelated to ties, negative = ties prefer other labels. Tested against random relabellings of the same channels.",
    "assortativity r, citations": "The same assortativity weighted by the citations on each tie.",
    "E-I index, labelled ties": "Krackhardt & Stern's (1988) E-I over the ties between labelled channels: (external − internal) / (external + internal). Compare it with its expected value under random relabellings: a large label is inward-looking by chance too.",
};

// Column headers of the significance block: the baselines a whole-network row is tested against.
var SIGNIFICANCE_TOOLTIPS = {
    "configuration": "Random networks with every channel's in/out-degree (and, approximately, strength): z and two-sided p of the statistic against them. Degree statistics are held fixed by construction.",
    "reciprocal": "As the configuration baseline, also keeping every channel's reciprocated ties: a deviation that survives is not explained by mutual citation alone.",
    "random": "A random network with the same channels and number of ties (channels that are only cited never cite) — the baseline for the degree statistics.",
    "label_permutation": "The labels shuffled over the same channels, the network fixed.",
};

var _METRIC_TOOLTIPS_LC = {};
Object.keys(METRIC_TOOLTIPS).forEach(function(name) { _METRIC_TOOLTIPS_LC[name.toLowerCase()] = METRIC_TOOLTIPS[name]; });

function _metric_tooltip(name) {
    return _METRIC_TOOLTIPS_LC[String(name).toLowerCase()];
}

function _significance_cell(test) {
    var td = document.createElement("td");
    td.className = "number nowrap";
    if (!test) {
        td.textContent = MISSING;
        td.classList.add("text-muted");
        td.title = "Not tested against this baseline";
        return td;
    }
    if (test.fixed) {
        td.textContent = "held fixed";
        td.classList.add("text-muted");
        td.title = "This baseline keeps the statistic constant by construction";
        return td;
    }
    if (isNil(test.z)) {
        td.textContent = isNil(test.p) ? MISSING : pText(test.p);
    } else {
        td.textContent = "z = " + sigFig(test.z, 3) + (isNil(test.p) ? "" : " (" + pText(test.p) + ")");
    }
    if (test.mean !== null && test.mean !== undefined) td.title = "Mean under the baseline: " + sigFig(test.mean, 3);
    return td;
}

var STRATEGY_COL_TOOLTIPS = {
    "Modularity": "Newman & Girvan (2004): share of the ties that fall within communities minus the share expected at random. Range −0.5–1. A high value alone is not evidence of communities — sparse random networks reach 0.3–0.8 too (Guimerà et al. 2004); read it with the z column.",
    "Modularity z": "How many standard deviations this modularity lies above the best modularity Leiden reaches on random networks with the same in/out-degrees and strengths but no community structure. Large and positive → real community structure; near 0 or negative → no more modular than chance. Shown for the modularity-maximising methods (Leiden, Leiden directed, Louvain) only.",
    "p (random)": "One-sided Monte-Carlo p-value of the modularity against those random networks: (number of random networks at least as modular + 1) / (random networks + 1). Its floor is set by the number of random networks.",
    "Inter-community ratio": "Share of all directed ties whose two channels belong to different communities. 0 = every tie internal; 1 = every tie crosses a community boundary. High values indicate a fragmented, competitive structure.",
    "Mean E-I index": "Weighted mean of community E-I indices (Krackhardt & Stern 1988): (external − internal) / (external + internal) per community, aggregated by connection volume. Range −1 (fully cohesive) to +1 (fully competitive).",
};

function _render_preamble(meta) {
    var el = document.getElementById("network-preamble");
    if (!el) return;
    el.innerHTML = "";
    if (!meta) return;
    el.appendChild(scopeLine(meta));
}

function _render_summary(data) {
    var section = document.getElementById("summary-section");
    section.innerHTML = "";
    var h2 = document.createElement("h2");
    h2.textContent = "Whole-network statistics";
    section.appendChild(h2);
    if (!(data.summary_rows || []).length) {
        var empty = document.createElement("p");
        empty.className = "text-muted small";
        empty.textContent = "No whole-network statistic was computed in this run (no network statistics group was selected).";
        section.appendChild(empty);
        return;
    }
    var table = document.createElement("table");
    table.className = "table table-sm table-hover table-fit";
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    var sigCols = data.significance_columns || [];
    ["Statistic", "Value"].concat(sigCols.map(function(c) { return c[1]; })).forEach(function(lbl, i) {
        var th = document.createElement("th");
        th.scope = "col";
        if (i >= 1) th.className = "number";
        th.textContent = lbl;
        if (i >= 2) th.title = SIGNIFICANCE_TOOLTIPS[sigCols[i - 2][0]] || "";
        htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    var curGroup = null;
    data.summary_rows.forEach(function(row) {
        if (row.group && row.group !== curGroup) {
            curGroup = row.group;
            var gtr = document.createElement("tr");
            gtr.className = "summary-group-header";
            var gtd = document.createElement("td");
            gtd.colSpan = 2 + sigCols.length;
            gtd.textContent = row.group;
            gtr.appendChild(gtd);
            tbody.appendChild(gtr);
        }
        var tr = document.createElement("tr");
        var td1 = document.createElement("td");
        td1.textContent = row.label;
        var baseLabel = row.label.replace(/\s*\(.*\)$/, "").replace(/\s*[†‡]\s*$/, "").trim();
        var tip = _metric_tooltip(baseLabel);
        if (!tip) {
            var m = baseLabel.match(/^(.*)\s+centralisation$/);
            if (m) tip = "Freeman (1978) network centralisation of " + m[1] + "; 0 = evenly spread, 1 = a star.";
        }
        if (!tip && row.group === "Homophily") tip = HOMOPHILY_TOOLTIPS[baseLabel.replace(/^.*?:\s*/, "")];
        if (tip) td1.title = tip;
        var td2 = document.createElement("td");
        td2.className = "number";
        if (_has_tl) {
            var inner = document.createElement("span");
            inner.className = "spark-cell";
            var hist = _mini_hist(_all_map[row.label], _yr_map[row.label], _current_year, _all_years);
            if (hist) inner.appendChild(hist);
            var vspan = document.createElement("span");
            vspan.className = "spark-val";
            vspan.textContent = row.value;
            inner.appendChild(vspan);
            td2.appendChild(inner);
        } else { td2.textContent = row.value; }
        tr.appendChild(td1);
        tr.appendChild(td2);
        sigCols.forEach(function(c) {
            tr.appendChild(_significance_cell((row.significance || {})[c[0]]));
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var wrap = document.createElement("div");
    wrap.className = "table-responsive";
    wrap.appendChild(table);
    section.appendChild(wrap);
    if (data.wcc_note_visible) {
        var note = document.createElement("p");
        note.className = "text-muted small mt-1";
        note.textContent = "† Computed on the largest weakly connected component (undirected)";
        section.appendChild(note);
    }
    if (data.scc_note_visible) {
        var note2 = document.createElement("p");
        note2.className = "text-muted small mt-1";
        note2.textContent = "‡ Computed on the largest strongly connected component (directed)";
        section.appendChild(note2);
    }
}

function _render_modularity(data) {
    var section = document.getElementById("modularity-section");
    section.innerHTML = "";
    if (!data.modularity_rows || !data.modularity_rows.length) {
        section.classList.add("d-none");
        return;
    }
    section.classList.remove("d-none");
    var h2 = document.createElement("h2");
    h2.textContent = "Modularity by method";
    section.appendChild(h2);
    var table = document.createElement("table");
    table.className = "table table-sm table-hover table-fit sortable";
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    ["Method", "Modularity", "Modularity z", "p (random)", "Inter-community ratio", "Mean E-I index"].forEach(function(lbl, i) {
        var th = document.createElement("th");
        th.scope = "col";
        if (i > 0) th.className = "number";
        th.textContent = lbl;
        var tip = STRATEGY_COL_TOOLTIPS[lbl];
        if (tip) th.title = tip;
        htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    data.modularity_rows.forEach(function(row) {
        var tr = document.createElement("tr");
        var td1 = document.createElement("td");
        td1.className = "nowrap";
        td1.textContent = _strat_label(row.strategy);
        var td2 = document.createElement("td");
        td2.className = "number";
        if (_has_tl) {
            var inner = document.createElement("span");
            inner.className = "spark-cell";
            var hist = _mini_hist(_all_mod_map[row.strategy], _yr_mod_map[row.strategy], _current_year, _all_years);
            if (hist) inner.appendChild(hist);
            var vspan = document.createElement("span");
            vspan.className = "spark-val";
            vspan.textContent = row.modularity;
            inner.appendChild(vspan);
            td2.appendChild(inner);
            td2.setAttribute("data-sort-value", row.modularity);
        } else { td2.textContent = row.modularity; }
        var tdZ = document.createElement("td");
        tdZ.className = "number";
        tdZ.textContent = row.modularity_z || MISSING;
        var tdP = document.createElement("td");
        tdP.className = "number";
        tdP.textContent = row.modularity_p || MISSING;
        var td3 = document.createElement("td");
        td3.className = "number";
        td3.textContent = row.inter_community_ratio || MISSING;
        var td4 = document.createElement("td");
        td4.className = "number";
        td4.textContent = row.mean_ei || MISSING;
        tr.appendChild(td1);
        tr.appendChild(td2);
        tr.appendChild(tdZ);
        tr.appendChild(tdP);
        tr.appendChild(td3);
        tr.appendChild(td4);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var wrap = document.createElement("div");
    wrap.className = "table-responsive";
    wrap.appendChild(table);
    section.appendChild(wrap);
    initSortableTables();
}

function _render_inference(data) {
    var mixing = document.getElementById("homophily-section");
    if (mixing) render_label_mixing(mixing, data.label_mixing);
    var regression = document.getElementById("mrqap-section");
    if (regression) render_mrqap(regression, data.mrqap);
}

// ── Build degree-distribution section (once on initial load) ───────────────────
function _build_dist_section() {
    var distSection = document.getElementById("degree-dist-section");
    var distWrapper = document.getElementById("degree-distribution");
    if (distWrapper) distWrapper.classList.remove("d-none");
    var controls = document.createElement("div");
    controls.className = "d-flex align-items-end gap-3 mb-3";
    var dirWrap = document.createElement("div");
    var dirLbl = document.createElement("label");
    dirLbl.className = "form-label mb-1 d-block fw-semibold small";
    dirLbl.htmlFor = "deg-dir-select";
    dirLbl.textContent = "Direction";
    _distSel = document.createElement("select");
    _distSel.className = "form-select form-select-sm";
    _distSel.id = "deg-dir-select";
    _distSel.style.width = "auto";
    [
        ["in_deg", "In-strength"],
        ["out_deg", "Out-strength"]
    ].forEach(function(opt) { _distSel.appendChild(new Option(opt[1], opt[0])); });
    dirWrap.appendChild(dirLbl);
    dirWrap.appendChild(_distSel);
    controls.appendChild(dirWrap);
    distSection.appendChild(controls);

    var canvasWrap = document.createElement("div");
    canvasWrap.style.cssText = "height:280px;position:relative;";
    var canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Histogram of the channels by in-strength or out-strength");
    canvasWrap.appendChild(canvas);
    distSection.appendChild(canvasWrap);

    _distSel.addEventListener("change", _update_dist_chart);

    function _init() {
        if (_distInitialized) return;
        _distInitialized = true;
        var dd = _build_dist_data(_distSel.value);
        _distChart = new Chart(canvas, {
            type: "bar",
            data: { labels: dd.labels, datasets: [{ label: "Channels", data: dd.counts, backgroundColor: pulpitTheme().series[0], borderRadius: 3 }] },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { title: { display: true, text: _distAxisLabel(_distSel.value), font: { size: 12 } }, grid: { display: false }, ticks: { font: { size: 11 } } },
                    y: { title: { display: true, text: "Channels", font: { size: 12 } }, ticks: { font: { size: 11 }, precision: 0 } },
                },
            },
        });
    }

    if ("IntersectionObserver" in window) {
        var obs = new IntersectionObserver(function(entries, o) {
            if (entries[0].isIntersecting) {
                o.disconnect();
                _init();
            }
        }, { threshold: 0.1 });
        obs.observe(distSection);
    } else { _init(); }
}

// ── Build scatter section (once on initial load) ───────────────────────────────
function _build_scatter_section() {
    if (_measures.length < 2) return;
    var scatterSection = document.getElementById("scatter-section");
    var scatterWrapper = document.getElementById("measure-comparison");
    if (scatterWrapper) scatterWrapper.classList.remove("d-none");

    var controls = document.createElement("div");
    controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";

    function makeSelect(id, labelText) {
        var wrap = document.createElement("div");
        var lbl = document.createElement("label");
        lbl.className = "form-label mb-1 d-block fw-semibold small";
        lbl.htmlFor = id;
        lbl.textContent = labelText;
        var sel = document.createElement("select");
        sel.className = "form-select form-select-sm scatter-select";
        sel.id = id;
        _measures.forEach(function(m) { sel.appendChild(new Option(_labelOf[m[0]], m[0])); });
        wrap.appendChild(lbl);
        wrap.appendChild(sel);
        controls.appendChild(wrap);
        return sel;
    }
    _xSel = makeSelect("x-axis-select", "X axis");
    _ySel = makeSelect("y-axis-select", "Y axis");

    var resetWrap = document.createElement("div");
    resetWrap.className = "scatter-reset-wrap";
    var resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.className = "btn btn-outline-secondary btn-sm";
    resetBtn.textContent = "Reset zoom";
    resetWrap.appendChild(resetBtn);
    controls.appendChild(resetWrap);

    _countNote = document.createElement("div");
    _countNote.className = "text-muted small ms-auto scatter-count-note";
    controls.appendChild(_countNote);
    scatterSection.appendChild(controls);

    var canvasWrap = document.createElement("div");
    canvasWrap.className = "scatter-canvas-wrap";
    var canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Scatter plot of the channels on two measures, both axes on log scales");
    canvasWrap.appendChild(canvas);
    scatterSection.appendChild(canvasWrap);

    var defaultX = _measures[0][0],
        defaultY = _measures[1][0];
    _measures.forEach(function(m) { if (m[0] === "in_deg") defaultX = m[0]; });
    _measures.forEach(function(m) { if (m[0] === "pagerank") defaultY = m[0]; });
    if (defaultX === defaultY) defaultY = _measures.find(function(m) { return m[0] !== defaultX; })[0];
    _xSel.value = defaultX;
    _ySel.value = defaultY;

    var initial = _build_scatter_data(defaultX, defaultY);
    _countNote.textContent = _scatterNote(initial.pts.length);

    _scatterChart = new Chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                { label: "Channels", data: initial.pts, backgroundColor: pulpitTheme().series[0], pointRadius: 4, pointHoverRadius: 7 },
                { label: "Power-law fit", data: initial.regData, type: "line", borderColor: pulpitTheme().text, borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
            ],
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { type: "logarithmic", title: { display: true, text: _labelOf[defaultX], font: { size: 12 } }, ticks: { font: { size: 11 } } },
                y: { type: "logarithmic", title: { display: true, text: _labelOf[defaultY], font: { size: 12 } }, ticks: { font: { size: 11 } } },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    filter: function(item) { return item.datasetIndex === 0; },
                    callbacks: {
                        label: function(ctx) {
                            var d = ctx.raw,
                                xLbl = _scatterChart.options.scales.x.title.text,
                                yLbl = _scatterChart.options.scales.y.title.text;
                            return ["Channel: " + d.label, xLbl + ": " + sigFig(d.x, 4), yLbl + ": " + sigFig(d.y, 4), "Subscribers: " + fmtInt(d.fans), "Messages: " + fmtInt(d.msgs)];
                        },
                    },
                },
                zoom: { pan: { enabled: true, mode: "xy" }, zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "xy" } },
            },
        },
    });

    _xSel.addEventListener("change", _update_scatter_chart);
    _ySel.addEventListener("change", _update_scatter_chart);
    resetBtn.addEventListener("click", function() { _scatterChart.resetZoom(); });
}

// ── Year switching ─────────────────────────────────────────────────────────────
function _switch_year(year) {
    if (year === _current_year || _loading) return;
    var prev = _current_year;
    _current_year = year;
    _loading = true;
    build_year_nav(_ty, _current_year, _switch_year, _tl_events);
    _fetch_year(year).then(function(d) {
        loadRecovered();
        _nodes = d.channels.nodes;
        _measures = d.channels.measures || [];
        _read_measure_labels();
        _render_preamble(d.meta);
        _render_summary(d.data);
        _render_modularity(d.data);
        _render_inference(d.data);
        _update_dist_chart();
        _update_scatter_chart();
        _loading = false;
    }).catch(function(err) {
        // The page still shows the previous period: the selector goes back to it.
        _current_year = prev;
        _loading = false;
        build_year_nav(_ty, _current_year, _switch_year, _tl_events);
        loadFailed(err, "the statistics of " + year);
    });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetchJson(_dd + "network_metrics.json"),
    fetchJson(_dd + "channels.json"),
    fetchJsonOrNull(_dd + "meta.json"),
    fetchJsonOrNull(_base_dd + "timeline.json"),
    fetchJsonOrNull(_base_dd + "network_metrics.json"),
]).then(function(results) {
    var data = results[0],
        channels = results[1],
        meta = results[2],
        timeline = results[3],
        all_metrics = results[4];

    _cache[_current_year] = { data: data, channels: channels, meta: meta };
    _nodes = channels.nodes;
    _measures = channels.measures || [];
    _read_measure_labels();

    var _tl = readTimeline(_no_timeline ? null : timeline);
    _tl_events = _tl.events;
    _ty = _tl.periods.filter(function(y) { return y.has_network_html; });
    _has_tl = _ty.length > 0;
    _all_years = _ty.map(function(y) { return y.key; });

    if (all_metrics && all_metrics.summary_rows)
        all_metrics.summary_rows.forEach(function(r) { _all_map[r.label] = r.value; });
    if (all_metrics && all_metrics.modularity_rows)
        all_metrics.modularity_rows.forEach(function(r) { _all_mod_map[r.strategy] = r.modularity; });

    return (_has_tl ?
        Promise.all(_ty.map(function(y) {
            return fetchJson(periodDataDir("data/", y.key) + "network_metrics.json")
                .then(function(d) { return { year: y.key, rows: d.summary_rows, mod_rows: d.modularity_rows || [] }; })
                .catch(function() { return null; });
        })).then(function(list) { return list.filter(Boolean); }) :
        Promise.resolve([])
    ).then(function(year_metrics) {
        year_metrics.forEach(function(ym) {
            ym.rows.forEach(function(row) {
                (_yr_map[row.label] = _yr_map[row.label] || []).push({ year: ym.year, value: row.value });
            });
            (ym.mod_rows || []).forEach(function(row) {
                (_yr_mod_map[row.strategy] = _yr_mod_map[row.strategy] || []).push({ year: ym.year, value: row.modularity });
            });
        });

        if (_has_tl) build_year_nav(_ty, _current_year, _switch_year, _tl_events);
        _render_preamble(meta);
        _render_summary(data);
        _render_modularity(data);
        _render_inference(data);
        _build_dist_section();
        _build_scatter_section();
    });
}).catch(function(err) {
    loadFailed(err);
});
