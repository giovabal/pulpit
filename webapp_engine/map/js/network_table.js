import { strategy_label as _strat_label } from './labels.js';
import { build_year_nav } from './year_nav.js';
import { mini_hist as _mini_hist } from './charts.js';

var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d{4,})\//);
var _base_dd = _ym ? "data/" : _dd;

// ── Sparkline data — loaded once at startup, never changes ─────────────────────
var _all_map = {}, _yr_map = {}, _all_mod_map = {}, _yr_mod_map = {}, _all_years = [];
var _ty = [], _has_tl = false;

// ── Per-year state — updated on every year switch ──────────────────────────────
var _current_year = _ym ? parseInt(_ym[1]) : "all";
var _nodes = [], _measures = [], _labelOf = {};
var _cache = {};
var _loading = false;

// ── Chart object references — built once, data updated on switch ───────────────
var _distChart = null, _distInitialized = false, _distSel = null;
var _scatterChart = null, _xSel = null, _ySel = null, _countNote = null;

// ── Data fetching ──────────────────────────────────────────────────────────────
function _fetch_year(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return Promise.all([
        fetch(dd + "network_metrics.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(dd + "channels.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(dd + "meta.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    ]).then(function(res) {
        var d = { data: res[0], channels: res[1], meta: res[2] };
        _cache[year] = d;
        return d;
    });
}

// ── Chart helpers — use module-scope _nodes ────────────────────────────────────
function _build_dist_data(key) {
    var vals = _nodes.map(function(n) { return n[key] || 0; });
    var maxVal = Math.max.apply(null, vals);
    var binSize = 10;
    var numBins = Math.max(1, Math.ceil((maxVal + 1) / binSize));
    var counts = new Array(numBins).fill(0);
    vals.forEach(function(v) { counts[Math.floor(v / binSize)]++; });
    while (counts.length > 1 && counts[counts.length - 1] === 0) counts.pop();
    return {
        labels: counts.map(function(_, i) { return (i * binSize) + "–" + (i * binSize + binSize - 1); }),
        counts: counts,
    };
}

function _power_law_fit(pts) {
    if (pts.length < 2) return null;
    var n = pts.length, sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    pts.forEach(function(p) { var lx = Math.log(p.x), ly = Math.log(p.y); sumX += lx; sumY += ly; sumXY += lx * ly; sumX2 += lx * lx; });
    var d = n * sumX2 - sumX * sumX;
    if (!d) return null;
    var slope = (n * sumXY - sumX * sumY) / d;
    return { slope: slope, intercept: (sumY - slope * sumX) / n };
}

function _build_scatter_data(xKey, yKey) {
    var pts = _nodes.filter(function(n) { return n[xKey] > 0 && n[yKey] > 0; })
        .map(function(n) { return { x: n[xKey], y: n[yKey], label: n.label || n.id, fans: n.fans || 0, msgs: n.messages_count || 0 }; });
    var fit = _power_law_fit(pts);
    var regData = [];
    if (fit) {
        var xs = pts.map(function(p) { return p.x; });
        var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
        regData = [{ x: xMin, y: Math.exp(fit.intercept) * Math.pow(xMin, fit.slope) },
                   { x: xMax, y: Math.exp(fit.intercept) * Math.pow(xMax, fit.slope) }];
    }
    return { pts: pts, regData: regData };
}

function _update_dist_chart() {
    if (!_distChart || !_distSel) return;
    var dd = _build_dist_data(_distSel.value);
    _distChart.data.labels = dd.labels;
    _distChart.data.datasets[0].data = dd.counts;
    _distChart.update();
}

function _update_scatter_chart() {
    if (!_scatterChart || !_xSel) return;
    var xKey = _xSel.value, yKey = _ySel.value;
    var ds = _build_scatter_data(xKey, yKey);
    _scatterChart.data.datasets[0].data = ds.pts;
    _scatterChart.data.datasets[1].data = ds.regData;
    _scatterChart.options.scales.x.title.text = _labelOf[xKey];
    _scatterChart.options.scales.y.title.text = _labelOf[yKey];
    _scatterChart.resetZoom();
    _scatterChart.update();
    if (_countNote) _countNote.textContent = ds.pts.length + " nodes (zero values excluded from log scale)";
}

// ── Table renders — re-run on every year switch ────────────────────────────────
var METRIC_TOOLTIPS = {
    "Nodes": "Total number of nodes (channels) in the graph.",
    "Edges": "Total number of directed edges (links) between channels.",
    "Edges / Nodes": "Mean degree — average links per node; a rough indicator of overall connectivity.",
    "Density": "Fraction of all possible directed edges that are present; 0 = sparse, 1 = fully connected.",
    "Reciprocity": "Proportion of edges that have a reciprocal edge; 0 = unidirectional, 1 = fully bidirectional.",
    "Avg Clustering": "Mean probability that two neighbours of a node are also connected to each other.",
    "Avg Path Length": "Average undirected shortest-path distance between nodes in the largest weakly connected component.",
    "Diameter": "Longest undirected shortest path (maximum eccentricity) in the largest weakly connected component.",
    "Directed Avg Path Length": "Average directed shortest-path distance following edge direction; computed on the largest strongly connected component.",
    "Directed Diameter": "Longest directed shortest path (maximum eccentricity); computed on the largest strongly connected component.",
    "WCC count": "Number of weakly connected components; 1 = all nodes reachable ignoring edge direction.",
    "Largest WCC fraction": "Share of all nodes that belong to the largest weakly connected component.",
    "SCC count": "Number of strongly connected components; 1 = every node can reach every other following directed edges.",
    "Largest SCC fraction": "Share of all nodes that belong to the largest strongly connected component.",
    "Assortativity in→in": "Pearson correlation of in-degree between source and target nodes across all edges; +1 = hubs connect to hubs.",
    "Assortativity in→out": "Correlation between in-degree of the source node and out-degree of the target node.",
    "Assortativity out→in": "Correlation between out-degree of the source node and in-degree of the target node.",
    "Assortativity out→out": "Pearson correlation of out-degree between source and target nodes; +1 = high-senders link to high-senders.",
    "Transitivity": "Fraction of all connected triples that form closed triangles — the global clustering coefficient. Complements Avg Clustering (which averages local per-node coefficients). Luce & Perry 1949; Watts & Strogatz 1998.",
    "Global Efficiency": "Mean reciprocal directed shortest-path length over all ordered node pairs; unreachable pairs contribute 0. Measures how efficiently information can flow between any two channels without restricting to a component. Latora & Marchiori 2001.",
    "Algebraic Connectivity": "Second-smallest eigenvalue of the undirected graph Laplacian (Fiedler value). Zero for disconnected graphs; larger values signal stronger structural cohesion and greater resistance to fragmentation. Fiedler 1973.",
    "In-degree CV": "Coefficient of variation (σ/μ) of the in-degree distribution. Low = citations spread evenly; high = a few hubs absorb most incoming references.",
    "Out-degree CV": "Coefficient of variation (σ/μ) of the out-degree distribution. Low = all channels equally active forwarders; high = a few channels drive most references.",
    "Mean Burt's Constraint": "Network-average Burt constraint; lower = more structural-hole brokerage on average.",
    "Content Originality": "Share of messages that are not forwards; higher = more original content production.",
    "Amplification Ratio": "Mean number of times each message is re-shared within the network.",
};

var STRATEGY_COL_TOOLTIPS = {
    "Modularity": "Newman & Girvan (2004): fraction of edges within communities minus the expected fraction under a random null model. Range −0.5–1; >0.3 is conventionally considered meaningful community structure.",
    "Inter-comm. Ratio": "Fraction of all directed edges whose endpoints belong to different communities. 0 = all edges internal; 1 = all edges cross community boundaries. High values indicate fragmented, competitive structure.",
    "Mean E-I Index": "Weighted mean of community E-I indices (Krackhardt & Stern 1988): (external − internal) / (external + internal) per community, aggregated by connection volume. Range −1 (fully cohesive) to +1 (fully competitive).",
};

function _render_preamble(meta) {
    var el = document.getElementById("network-preamble");
    if (!el) return;
    el.innerHTML = "";
    if (!meta) return;
    var pEl = document.createElement("p"); pEl.className = "table-preamble";
    var parts = ["Whole-network structural metrics for a graph of "
        + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
    parts.push("Edges represent " + meta.edge_weight_label + "; " + meta.edge_direction + ".");
    if (meta.start_date || meta.end_date)
        parts.push("Data range: " + (meta.start_date || "–") + " to " + (meta.end_date || "present") + ".");
    parts.push("Exported " + meta.export_date + ".");
    pEl.textContent = parts.join(" ");
    el.appendChild(pEl);
}

function _render_summary(data) {
    var section = document.getElementById("summary-section");
    section.innerHTML = "";
    var h5 = document.createElement("h5"); h5.className = "mb-2"; h5.textContent = "Whole-network metrics";
    section.appendChild(h5);
    var table = document.createElement("table"); table.className = "table table-sm table-hover";
    var thead = document.createElement("thead"); var htr = document.createElement("tr");
    ["Metric", "Value"].forEach(function(lbl, i) {
        var th = document.createElement("th"); th.scope = "col"; if (i === 1) th.className = "number";
        th.textContent = lbl; htr.appendChild(th);
    });
    thead.appendChild(htr); table.appendChild(thead);
    var tbody = document.createElement("tbody");
    var curGroup = null;
    data.summary_rows.forEach(function(row) {
        if (row.group && row.group !== curGroup) {
            curGroup = row.group;
            var gtr = document.createElement("tr"); gtr.className = "summary-group-header";
            var gtd = document.createElement("td"); gtd.colSpan = 2; gtd.textContent = row.group;
            gtr.appendChild(gtd); tbody.appendChild(gtr);
        }
        var tr = document.createElement("tr");
        var td1 = document.createElement("td"); td1.textContent = row.label;
        var baseLabel = row.label.replace(/\s*\(.*\)$/, "").replace(/\s*[†‡]\s*$/, "").trim();
        var tip = METRIC_TOOLTIPS[baseLabel];
        if (!tip) {
            var m = baseLabel.match(/^(.*)\s+Centralization$/);
            if (m) tip = "Freeman (1978) graph-level centralization for " + m[1] + "; 0 = uniform distribution, 1 = star graph.";
        }
        if (tip) td1.title = tip;
        var td2 = document.createElement("td"); td2.className = "number";
        if (_has_tl) {
            var inner = document.createElement("span");
            inner.className = "spark-cell";
            var hist = _mini_hist(_all_map[row.label], _yr_map[row.label], _current_year, _all_years);
            if (hist) inner.appendChild(hist);
            var vspan = document.createElement("span");
            vspan.className = "spark-val";
            vspan.textContent = row.value;
            inner.appendChild(vspan); td2.appendChild(inner);
        } else { td2.textContent = row.value; }
        tr.appendChild(td1); tr.appendChild(td2); tbody.appendChild(tr);
    });
    table.appendChild(tbody); section.appendChild(table);
    if (data.wcc_note_visible) {
        var note = document.createElement("p"); note.className = "text-muted small mt-1";
        note.textContent = "† Computed on the largest weakly connected component (undirected)";
        section.appendChild(note);
    }
    if (data.scc_note_visible) {
        var note2 = document.createElement("p"); note2.className = "text-muted small mt-1";
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
    var h5 = document.createElement("h5"); h5.className = "mb-2"; h5.textContent = "Modularity by strategy";
    section.appendChild(h5);
    var table = document.createElement("table"); table.className = "table table-sm table-hover sortable";
    var thead = document.createElement("thead"); var htr = document.createElement("tr");
    ["Strategy", "Modularity", "Inter-comm. Ratio", "Mean E-I Index"].forEach(function(lbl, i) {
        var th = document.createElement("th"); th.scope = "col";
        if (i > 0) th.className = "number";
        th.textContent = lbl;
        var tip = STRATEGY_COL_TOOLTIPS[lbl];
        if (tip) th.title = tip;
        htr.appendChild(th);
    });
    thead.appendChild(htr); table.appendChild(thead);
    var tbody = document.createElement("tbody");
    data.modularity_rows.forEach(function(row) {
        var tr = document.createElement("tr");
        var td1 = document.createElement("td"); td1.textContent = _strat_label(row.strategy);
        var td2 = document.createElement("td"); td2.className = "number";
        if (_has_tl) {
            var inner = document.createElement("span");
            inner.className = "spark-cell";
            var hist = _mini_hist(_all_mod_map[row.strategy], _yr_mod_map[row.strategy], _current_year, _all_years);
            if (hist) inner.appendChild(hist);
            var vspan = document.createElement("span");
            vspan.className = "spark-val";
            vspan.textContent = row.modularity;
            inner.appendChild(vspan); td2.appendChild(inner);
            td2.setAttribute("data-sort-value", row.modularity);
        } else { td2.textContent = row.modularity; }
        var td3 = document.createElement("td"); td3.className = "number"; td3.textContent = row.inter_community_ratio || "—";
        var td4 = document.createElement("td"); td4.className = "number"; td4.textContent = row.mean_ei || "—";
        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody); section.appendChild(table);
    initSortableTables();
}

function _render_nmi_matrix(data) {
    var section = document.getElementById("nmi-section");
    section.innerHTML = "";
    var nm = data.nmi_matrix;
    if (!nm || !nm.strategies || nm.strategies.length < 2) {
        section.classList.add("d-none");
        return;
    }
    section.classList.remove("d-none");
    var strats = nm.strategies;
    var cells = nm.cells;

    var h5 = document.createElement("h5"); h5.className = "mb-1";
    h5.textContent = "Partition agreement (NMI)";
    h5.title = "Normalized Mutual Information between each pair of community strategies. "
             + "NMI = 1: identical partitions; NMI = 0: statistically independent groupings. "
             + "Computed on nodes assigned in both strategies. Kvalseth 1987 / Fred & Jain 2003.";
    section.appendChild(h5);

    var p = document.createElement("p"); p.className = "text-muted small mb-2";
    p.textContent = "How much knowing one partition tells you about another. "
                  + "High NMI means your organisations map well onto structural clusters; "
                  + "low NMI means the network topology cuts across your manual labels.";
    section.appendChild(p);

    var tableWrap = document.createElement("div"); tableWrap.style.overflowX = "auto";
    var table = document.createElement("table");
    table.className = "table table-sm table-bordered nmi-table";
    table.style.cssText = "width:auto;min-width:0;";

    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    var th0 = document.createElement("th"); th0.scope = "col"; htr.appendChild(th0);
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
            if (i === j) {
                td.textContent = "—";
                td.style.color = "#adb5bd";
            } else if (val === null || val === undefined) {
                td.textContent = "—";
            } else {
                td.textContent = val.toFixed(4);
                var r = Math.round(255 - val * 70);
                var g = Math.round(255 - val * 40);
                var b = Math.round(255 - val * 20);
                td.style.backgroundColor = "rgb(" + r + "," + g + "," + b + ")";
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    section.appendChild(tableWrap);
}

// ── Build degree-distribution section (once on initial load) ───────────────────
function _build_dist_section() {
    var distSection = document.getElementById("degree-dist-section");
    var controls = document.createElement("div"); controls.className = "d-flex align-items-end gap-3 mb-3";
    var dirWrap = document.createElement("div");
    var dirLbl = document.createElement("label");
    dirLbl.className = "form-label mb-1 d-block fw-semibold small"; dirLbl.htmlFor = "deg-dir-select"; dirLbl.textContent = "Direction";
    _distSel = document.createElement("select"); _distSel.className = "form-select form-select-sm"; _distSel.id = "deg-dir-select"; _distSel.style.width = "auto";
    [["in_deg", "Forwards received"], ["out_deg", "Forwards sent"]].forEach(function(opt) { _distSel.appendChild(new Option(opt[1], opt[0])); });
    dirWrap.appendChild(dirLbl); dirWrap.appendChild(_distSel); controls.appendChild(dirWrap);
    distSection.appendChild(controls);

    var canvasWrap = document.createElement("div"); canvasWrap.style.cssText = "height:280px;position:relative;";
    var canvas = document.createElement("canvas"); canvasWrap.appendChild(canvas); distSection.appendChild(canvasWrap);

    _distSel.addEventListener("change", _update_dist_chart);

    function _init() {
        if (_distInitialized) return;
        _distInitialized = true;
        var dd = _build_dist_data(_distSel.value);
        _distChart = new Chart(canvas, {
            type: "bar",
            data: { labels: dd.labels, datasets: [{ label: "Nodes", data: dd.counts, backgroundColor: "rgba(30,41,59,0.7)", borderRadius: 3 }] },
            options: {
                animation: false, responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { title: { display: true, text: "Links per node", font: { size: 12 } }, grid: { display: false }, ticks: { font: { size: 11 } } },
                    y: { title: { display: true, text: "Nodes", font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 }, precision: 0 } },
                },
            },
        });
    }

    if ("IntersectionObserver" in window) {
        var obs = new IntersectionObserver(function(entries, o) { if (entries[0].isIntersecting) { o.disconnect(); _init(); } }, { threshold: 0.1 });
        obs.observe(distSection);
    } else { _init(); }
}

// ── Build scatter section (once on initial load) ───────────────────────────────
function _build_scatter_section() {
    if (_measures.length < 2) return;
    var scatterSection = document.getElementById("scatter-section");

    var controls = document.createElement("div"); controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";
    function makeSelect(id, labelText) {
        var wrap = document.createElement("div");
        var lbl = document.createElement("label"); lbl.className = "form-label mb-1 d-block fw-semibold small"; lbl.htmlFor = id; lbl.textContent = labelText;
        var sel = document.createElement("select"); sel.className = "form-select form-select-sm scatter-select"; sel.id = id;
        _measures.forEach(function(m) { sel.appendChild(new Option(m[1], m[0])); });
        wrap.appendChild(lbl); wrap.appendChild(sel); controls.appendChild(wrap);
        return sel;
    }
    _xSel = makeSelect("x-axis-select", "X axis");
    _ySel = makeSelect("y-axis-select", "Y axis");

    var resetWrap = document.createElement("div"); resetWrap.className = "scatter-reset-wrap";
    var resetBtn = document.createElement("button"); resetBtn.className = "btn btn-outline-secondary btn-sm"; resetBtn.textContent = "Reset zoom";
    resetWrap.appendChild(resetBtn); controls.appendChild(resetWrap);

    _countNote = document.createElement("div"); _countNote.className = "text-muted small ms-auto scatter-count-note";
    controls.appendChild(_countNote);
    scatterSection.appendChild(controls);

    var canvasWrap = document.createElement("div"); canvasWrap.className = "scatter-canvas-wrap";
    var canvas = document.createElement("canvas"); canvasWrap.appendChild(canvas); scatterSection.appendChild(canvasWrap);

    var defaultX = _measures[0][0], defaultY = _measures[1][0];
    _measures.forEach(function(m) { if (m[0] === "in_deg") defaultX = m[0]; });
    _measures.forEach(function(m) { if (m[0] === "pagerank") defaultY = m[0]; });
    if (defaultX === defaultY) defaultY = _measures.find(function(m) { return m[0] !== defaultX; })[0];
    _xSel.value = defaultX; _ySel.value = defaultY;

    var initial = _build_scatter_data(defaultX, defaultY);
    _countNote.textContent = initial.pts.length + " nodes (zero values excluded from log scale)";

    _scatterChart = new Chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                { label: "Channels", data: initial.pts, backgroundColor: "rgba(30,41,59,0.55)", pointRadius: 5, pointHoverRadius: 7 },
                { label: "Trend", data: initial.regData, type: "line", borderColor: "#ef4444", borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
            ],
        },
        options: {
            animation: false, responsive: true, maintainAspectRatio: false,
            scales: {
                x: { type: "logarithmic", title: { display: true, text: _labelOf[defaultX], font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } } },
                y: { type: "logarithmic", title: { display: true, text: _labelOf[defaultY], font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } } },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    filter: function(item) { return item.datasetIndex === 0; },
                    callbacks: {
                        label: function(ctx) {
                            var d = ctx.raw, xLbl = _scatterChart.options.scales.x.title.text, yLbl = _scatterChart.options.scales.y.title.text;
                            return ["Channel: " + d.label, xLbl + ": " + d.x.toFixed(4), yLbl + ": " + d.y.toFixed(4), "Subscribers: " + d.fans.toLocaleString(), "Messages: " + d.msgs.toLocaleString()];
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
    _current_year = year;
    _loading = true;
    build_year_nav(_ty, _current_year, _switch_year);
    _fetch_year(year).then(function(d) {
        _nodes = d.channels.nodes;
        _measures = d.channels.measures || [];
        _labelOf = {};
        _measures.forEach(function(m) { _labelOf[m[0]] = m[1]; });
        _render_preamble(d.meta);
        _render_summary(d.data);
        _render_modularity(d.data);
        _render_nmi_matrix(d.data);
        _update_dist_chart();
        _update_scatter_chart();
        _loading = false;
    }).catch(function() { _loading = false; });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetch(_dd + "network_metrics.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
    fetch(_dd + "channels.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
    fetch(_dd + "meta.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    fetch(_base_dd + "timeline.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    fetch(_base_dd + "network_metrics.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }).catch(function() { return null; }),
]).then(function(results) {
    var data = results[0], channels = results[1], meta = results[2], timeline = results[3], all_metrics = results[4];

    _cache[_current_year] = { data: data, channels: channels, meta: meta };
    _nodes = channels.nodes;
    _measures = channels.measures || [];
    _measures.forEach(function(m) { _labelOf[m[0]] = m[1]; });

    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_network_html; }) : [];
    _has_tl = _ty.length > 0;
    _all_years = _ty.map(function(y) { return y.year; });

    if (all_metrics && all_metrics.summary_rows)
        all_metrics.summary_rows.forEach(function(r) { _all_map[r.label] = r.value; });
    if (all_metrics && all_metrics.modularity_rows)
        all_metrics.modularity_rows.forEach(function(r) { _all_mod_map[r.strategy] = r.modularity; });

    return (_has_tl
        ? Promise.all(_ty.map(function(y) {
            return fetch("data_" + y.year + "/network_metrics.json")
                .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
                .then(function(d) { return { year: y.year, rows: d.summary_rows, mod_rows: d.modularity_rows || [] }; })
                .catch(function() { return null; });
          })).then(function(list) { return list.filter(Boolean); })
        : Promise.resolve([])
    ).then(function(year_metrics) {
        year_metrics.forEach(function(ym) {
            ym.rows.forEach(function(row) {
                (_yr_map[row.label] = _yr_map[row.label] || []).push({ year: ym.year, value: row.value });
            });
            (ym.mod_rows || []).forEach(function(row) {
                (_yr_mod_map[row.strategy] = _yr_mod_map[row.strategy] || []).push({ year: ym.year, value: row.modularity });
            });
        });

        if (_has_tl) build_year_nav(_ty, _current_year, _switch_year);
        _render_preamble(meta);
        _render_summary(data);
        _render_modularity(data);
        _render_nmi_matrix(data);
        _build_dist_section();
        _build_scatter_section();
    });
}).catch(function(err) {
    var el = document.getElementById("network-preamble");
    if (el) el.textContent = "Failed to load data.";
    console.error("network_table:", err);
});
