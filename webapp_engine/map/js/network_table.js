var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d+)\//);
var current_year = _ym ? parseInt(_ym[1]) : "all";

Promise.all([
    fetch(_dd + "network_metrics.json").then(function(r) { return r.json(); }),
    fetch(_dd + "channels.json").then(function(r) { return r.json(); }),
    fetch(_dd + "meta.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
    fetch("data/timeline.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    fetch("data/network_metrics.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
]).then(function(results) {
    var data = results[0], channels = results[1], meta = results[2], timeline = results[3], all_metrics = results[4];

    var _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_network_html; }) : [];
    var has_tl = _ty.length > 0;

    return (has_tl
        ? Promise.all(_ty.map(function(y) {
            return fetch("data_" + y.year + "/network_metrics.json")
                .then(function(r) { return r.json(); })
                .then(function(d) { return { year: y.year, rows: d.summary_rows, mod_rows: d.modularity_rows || [] }; })
                .catch(function() { return null; });
          })).then(function(list) { return list.filter(Boolean); })
        : Promise.resolve([])
    ).then(function(year_metrics) {

        // Build metric lookups for histograms
        var all_map = {};  // label → value string (full-range)
        if (all_metrics && all_metrics.summary_rows) {
            all_metrics.summary_rows.forEach(function(r) { all_map[r.label] = r.value; });
        }
        var yr_map = {};   // label → [{year, value}]
        year_metrics.forEach(function(ym) {
            ym.rows.forEach(function(row) {
                (yr_map[row.label] = yr_map[row.label] || []).push({ year: ym.year, value: row.value });
            });
        });

        // Modularity lookups
        var all_mod_map = {};  // strategy → value string (full-range)
        if (all_metrics && all_metrics.modularity_rows) {
            all_metrics.modularity_rows.forEach(function(r) { all_mod_map[r.strategy] = r.value; });
        }
        var yr_mod_map = {};   // strategy → [{year, value}]
        year_metrics.forEach(function(ym) {
            (ym.mod_rows || []).forEach(function(row) {
                (yr_mod_map[row.strategy] = yr_mod_map[row.strategy] || []).push({ year: ym.year, value: row.value });
            });
        });

        // Year nav
        if (has_tl) _build_year_nav(_ty, current_year);

        // ── Preamble ───────────────────────────────────────────────────────────
        if (meta) {
            var preambleTarget = document.getElementById("network-preamble");
            if (preambleTarget) {
                var pEl = document.createElement("p"); pEl.className = "table-preamble";
                var parts = ["Whole-network structural metrics for a graph of "
                    + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
                parts.push("Edges represent " + meta.edge_weight_label + "; " + meta.edge_direction + ".");
                if (meta.start_date || meta.end_date) {
                    parts.push("Data range: " + (meta.start_date || "–") + " to " + (meta.end_date || "present") + ".");
                }
                parts.push("Exported " + meta.export_date + ".");
                pEl.textContent = parts.join(" ");
                preambleTarget.appendChild(pEl);
            }
        }
        var nodes = channels.nodes;
        var measures = channels.measures || [];

        // ── Summary table ──────────────────────────────────────────────────────
        var summarySection = document.getElementById("summary-section");
        var h5s = document.createElement("h5"); h5s.className = "mb-2"; h5s.textContent = "Whole-network metrics";
        summarySection.appendChild(h5s);
        var summaryTable = document.createElement("table");
        summaryTable.className = "table table-sm table-hover";
        var sThead = document.createElement("thead"); var sTr = document.createElement("tr");
        var _headers = has_tl ? ["Metric", "", "Value"] : ["Metric", "Value"];
        _headers.forEach(function(label, i) {
            var th = document.createElement("th"); th.scope = "col";
            if (i === _headers.length - 1) th.className = "number";
            th.textContent = label; sTr.appendChild(th);
        });
        sThead.appendChild(sTr); summaryTable.appendChild(sThead);
        var METRIC_TOOLTIPS = {
            "Nodes": "Total number of nodes (channels) in the graph.",
            "Edges": "Total number of directed edges (links) between channels.",
            "Edges / Nodes": "Mean degree — average links per node; a rough indicator of overall connectivity.",
            "Density": "Fraction of all possible directed edges that are present; 0 = sparse, 1 = fully connected.",
            "Reciprocity": "Proportion of edges that have a reciprocal edge; 0 = unidirectional, 1 = fully bidirectional.",
            "Avg Clustering": "Mean probability that two neighbours of a node are also connected to each other.",
            "Avg Path Length": "Average shortest-path distance between nodes in the largest weakly connected component.",
            "Diameter": "Longest shortest path (maximum eccentricity) in the largest weakly connected component.",
            "WCC count": "Number of weakly connected components; 1 = all nodes reachable ignoring edge direction.",
            "Largest WCC fraction": "Share of all nodes that belong to the largest weakly connected component.",
            "SCC count": "Number of strongly connected components; 1 = every node can reach every other following directed edges.",
            "Largest SCC fraction": "Share of all nodes that belong to the largest strongly connected component.",
            "Assortativity in→in": "Pearson correlation of in-degree between source and target nodes across all edges; +1 = hubs connect to hubs.",
            "Assortativity in→out": "Correlation between in-degree of the source node and out-degree of the target node.",
            "Assortativity out→in": "Correlation between out-degree of the source node and in-degree of the target node.",
            "Assortativity out→out": "Pearson correlation of out-degree between source and target nodes; +1 = high-senders link to high-senders.",
            "Mean Burt’s Constraint": "Network-average Burt constraint; lower = more structural-hole brokerage on average.",
            "Content Originality": "Share of messages that are not forwards; higher = more original content production.",
            "Amplification Ratio": "Mean number of times each message is re-shared within the network.",
        };

        var sTbody = document.createElement("tbody");
        var currentGroup = null;
        data.summary_rows.forEach(function(row) {
            if (row.group && row.group !== currentGroup) {
                currentGroup = row.group;
                var gtr = document.createElement("tr"); gtr.className = "summary-group-header";
                var gtd = document.createElement("td"); gtd.colSpan = has_tl ? 3 : 2; gtd.textContent = row.group;
                gtr.appendChild(gtd); sTbody.appendChild(gtr);
            }
            var tr = document.createElement("tr");
            var td1 = document.createElement("td");
            td1.textContent = row.label;
            var baseLabel = row.label.replace(/\s*\(.*\)$/, "").replace(/\s*†\s*$/, "").trim();
            var tip = METRIC_TOOLTIPS[baseLabel];
            if (!tip) {
                var centrMatch = baseLabel.match(/^(.*)\s+Centralization$/);
                if (centrMatch) tip = "Freeman (1978) graph-level centralization for " + centrMatch[1] + "; 0 = uniform distribution, 1 = star graph.";
            }
            if (tip) td1.title = tip;
            var td2 = document.createElement("td"); td2.className = "number"; td2.textContent = row.value;
            tr.appendChild(td1);
            if (has_tl) {
                var td_hist = document.createElement("td");
                td_hist.style.cssText = "padding:2px 8px;vertical-align:middle;white-space:nowrap";
                var hist = _mini_hist(all_map[row.label], yr_map[row.label], current_year);
                if (hist) td_hist.appendChild(hist);
                tr.appendChild(td_hist);
            }
            tr.appendChild(td2);
            sTbody.appendChild(tr);
        });
        summaryTable.appendChild(sTbody); summarySection.appendChild(summaryTable);
        if (data.wcc_note_visible) {
            var note = document.createElement("p"); note.className = "text-muted small mt-1";
            note.textContent = "† Computed on the largest weakly connected component (undirected)";
            summarySection.appendChild(note);
        }

        // ── Modularity table ───────────────────────────────────────────────────
        if (data.modularity_rows && data.modularity_rows.length) {
            var modSection = document.getElementById("modularity-section");
            modSection.classList.remove("d-none");
            var h5m = document.createElement("h5"); h5m.className = "mb-2"; h5m.textContent = "Modularity by strategy";
            modSection.appendChild(h5m);
            var modTable = document.createElement("table"); modTable.className = "table table-sm table-hover sortable";
            var mThead = document.createElement("thead"); var mTr = document.createElement("tr");
            ["Strategy", "Modularity"].forEach(function(label, i) {
                var th = document.createElement("th"); th.scope = "col";
                if (i === 1) th.className = "number";
                th.textContent = label; mTr.appendChild(th);
            });
            mThead.appendChild(mTr); modTable.appendChild(mThead);
            var mTbody = document.createElement("tbody");
            data.modularity_rows.forEach(function(row) {
                var tr = document.createElement("tr");
                var td1 = document.createElement("td"); td1.textContent = row.strategy;
                var td2 = document.createElement("td"); td2.className = "number";
                if (has_tl) {
                    // Histogram placed inline in the value cell, right-aligned next to the number
                    var inner = document.createElement("span");
                    inner.style.cssText = "display:inline-flex;align-items:flex-end;justify-content:flex-end;gap:5px;width:100%";
                    var hist = _mini_hist(all_mod_map[row.strategy], yr_mod_map[row.strategy], current_year);
                    if (hist) inner.appendChild(hist);
                    var vspan = document.createElement("span"); vspan.textContent = row.value;
                    inner.appendChild(vspan);
                    td2.appendChild(inner);
                    td2.dataset.sort = row.value;  // keep sortable working on the raw value
                } else {
                    td2.textContent = row.value;
                }
                tr.appendChild(td1); tr.appendChild(td2); mTbody.appendChild(tr);
            });
            modTable.appendChild(mTbody); modSection.appendChild(modTable);
        }

        initSortableTables();

        // ── Degree distribution ────────────────────────────────────────────────
        var distSection = document.getElementById("degree-dist-section");
        var distControls = document.createElement("div");
        distControls.className = "d-flex align-items-end gap-3 mb-3";
        var dirWrap = document.createElement("div");
        var dirLbl = document.createElement("label");
        dirLbl.className = "form-label mb-1 d-block fw-semibold small";
        dirLbl.htmlFor = "deg-dir-select";
        dirLbl.textContent = "Direction";
        var dirSel = document.createElement("select");
        dirSel.className = "form-select form-select-sm";
        dirSel.id = "deg-dir-select";
        dirSel.style.width = "auto";
        [["in_deg", "Forwards received"], ["out_deg", "Forwards sent"]].forEach(function(opt) {
            dirSel.appendChild(new Option(opt[1], opt[0]));
        });
        dirWrap.appendChild(dirLbl);
        dirWrap.appendChild(dirSel);
        distControls.appendChild(dirWrap);
        distSection.appendChild(distControls);

        var distCanvasWrap = document.createElement("div");
        distCanvasWrap.style.cssText = "height:280px;position:relative;";
        var distCanvas = document.createElement("canvas");
        distCanvasWrap.appendChild(distCanvas);
        distSection.appendChild(distCanvasWrap);

        function buildDistData(key) {
            var vals = nodes.map(function(n) { return n[key] || 0; });
            var maxVal = Math.max.apply(null, vals);
            var binSize = 10;
            var numBins = Math.max(1, Math.ceil((maxVal + 1) / binSize));
            var counts = new Array(numBins).fill(0);
            vals.forEach(function(v) { counts[Math.floor(v / binSize)]++; });
            while (counts.length > 1 && counts[counts.length - 1] === 0) counts.pop();
            var labels = counts.map(function(_, i) {
                return (i * binSize) + "–" + (i * binSize + binSize - 1);
            });
            return { labels: labels, counts: counts };
        }

        var distChart = null;
        var distInitialized = false;

        function initDistChart() {
            if (distInitialized) return;
            distInitialized = true;
            var dd = buildDistData(dirSel.value);
            distChart = new Chart(distCanvas, {
                type: "bar",
                data: {
                    labels: dd.labels,
                    datasets: [{ label: "Nodes", data: dd.counts, backgroundColor: "rgba(30,41,59,0.7)", borderRadius: 3 }]
                },
                options: {
                    animation: false,
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { title: { display: true, text: "Links per node", font: { size: 12 } }, grid: { display: false }, ticks: { font: { size: 11 } } },
                        y: { title: { display: true, text: "Nodes", font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 }, precision: 0 } }
                    }
                }
            });
        }

        dirSel.addEventListener("change", function() {
            if (!distChart) return;
            var dd = buildDistData(dirSel.value);
            distChart.data.labels = dd.labels;
            distChart.data.datasets[0].data = dd.counts;
            distChart.update();
        });

        if ("IntersectionObserver" in window) {
            var distObs = new IntersectionObserver(function(entries, obs) {
                if (entries[0].isIntersecting) { obs.disconnect(); initDistChart(); }
            }, { threshold: 0.1 });
            distObs.observe(distSection);
        } else {
            initDistChart();
        }

        // ── Scatter plot ───────────────────────────────────────────────────────
        if (measures.length < 2) return;

        var scatterSection = document.getElementById("scatter-section");
        var labelOf = {};
        measures.forEach(function(m) { labelOf[m[0]] = m[1]; });

        var controls = document.createElement("div");
        controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";

        function makeSelect(id, labelText) {
            var wrap = document.createElement("div");
            var lbl = document.createElement("label"); lbl.className = "form-label mb-1 d-block fw-semibold small"; lbl.htmlFor = id; lbl.textContent = labelText;
            var sel = document.createElement("select"); sel.className = "form-select form-select-sm scatter-select"; sel.id = id;
            measures.forEach(function(m) { sel.appendChild(new Option(m[1], m[0])); });
            wrap.appendChild(lbl); wrap.appendChild(sel);
            controls.appendChild(wrap);
            return sel;
        }

        var xSelect = makeSelect("x-axis-select", "X axis");
        var ySelect = makeSelect("y-axis-select", "Y axis");

        var resetWrap = document.createElement("div"); resetWrap.className = "scatter-reset-wrap";
        var resetBtn = document.createElement("button"); resetBtn.className = "btn btn-outline-secondary btn-sm"; resetBtn.textContent = "Reset zoom";
        resetWrap.appendChild(resetBtn); controls.appendChild(resetWrap);

        var countNote = document.createElement("div"); countNote.className = "text-muted small ms-auto scatter-count-note";
        controls.appendChild(countNote);

        scatterSection.appendChild(controls);

        var canvasWrap = document.createElement("div"); canvasWrap.className = "scatter-canvas-wrap";
        var canvas = document.createElement("canvas"); canvasWrap.appendChild(canvas);
        scatterSection.appendChild(canvasWrap);

        var defaultX = measures[0][0], defaultY = measures[1][0];
        measures.forEach(function(m) { if (m[0] === "in_deg") defaultX = m[0]; });
        measures.forEach(function(m) { if (m[0] === "pagerank") defaultY = m[0]; });
        if (defaultX === defaultY) defaultY = measures.find(function(m) { return m[0] !== defaultX; })[0];
        xSelect.value = defaultX; ySelect.value = defaultY;

        function powerLawFit(pts) {
            if (pts.length < 2) return null;
            var n = pts.length, sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
            pts.forEach(function(p) { var lx = Math.log(p.x), ly = Math.log(p.y); sumX += lx; sumY += ly; sumXY += lx * ly; sumX2 += lx * lx; });
            var d = n * sumX2 - sumX * sumX;
            if (!d) return null;
            var slope = (n * sumXY - sumX * sumY) / d;
            return { slope: slope, intercept: (sumY - slope * sumX) / n };
        }

        function buildDatasets(xKey, yKey) {
            var pts = nodes.filter(function(n) { return n[xKey] > 0 && n[yKey] > 0; })
                .map(function(n) { return { x: n[xKey], y: n[yKey], label: n.label || n.id, fans: n.fans || 0, msgs: n.messages_count || 0 }; });
            var regData = [];
            var fit = powerLawFit(pts);
            if (fit) {
                var xs = pts.map(function(p) { return p.x; });
                var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
                regData = [{ x: xMin, y: Math.exp(fit.intercept) * Math.pow(xMin, fit.slope) }, { x: xMax, y: Math.exp(fit.intercept) * Math.pow(xMax, fit.slope) }];
            }
            return { pts: pts, regData: regData };
        }

        var initial = buildDatasets(xSelect.value, ySelect.value);
        countNote.textContent = initial.pts.length + " nodes (zero values excluded from log scale)";

        var chart = new Chart(canvas, {
            type: "scatter",
            data: {
                datasets: [
                    { label: "Channels", data: initial.pts, backgroundColor: "rgba(30,41,59,0.55)", pointRadius: 5, pointHoverRadius: 7 },
                    { label: "Trend", data: initial.regData, type: "line", borderColor: "#ef4444", borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
                ],
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: "logarithmic", title: { display: true, text: labelOf[xSelect.value], font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } } },
                    y: { type: "logarithmic", title: { display: true, text: labelOf[ySelect.value], font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } } },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        filter: function(item) { return item.datasetIndex === 0; },
                        callbacks: {
                            label: function(ctx) {
                                var d = ctx.raw, xLbl = chart.options.scales.x.title.text, yLbl = chart.options.scales.y.title.text;
                                return ["Channel: " + d.label, xLbl + ": " + d.x.toFixed(4), yLbl + ": " + d.y.toFixed(4), "Subscribers: " + d.fans.toLocaleString(), "Messages: " + d.msgs.toLocaleString()];
                            },
                        },
                    },
                    zoom: { pan: { enabled: true, mode: "xy" }, zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "xy" } },
                },
            },
        });

        function updateChart() {
            var xKey = xSelect.value, yKey = ySelect.value;
            var ds = buildDatasets(xKey, yKey);
            chart.data.datasets[0].data = ds.pts;
            chart.data.datasets[1].data = ds.regData;
            chart.options.scales.x.title.text = labelOf[xKey];
            chart.options.scales.y.title.text = labelOf[yKey];
            chart.resetZoom();
            chart.update();
            countNote.textContent = ds.pts.length + " nodes (zero values excluded from log scale)";
        }

        xSelect.addEventListener("change", updateChart);
        ySelect.addEventListener("change", updateChart);
        resetBtn.addEventListener("click", function() { chart.resetZoom(); });

    }); // year_metrics chain
}); // outer Promise.all

// ── Year nav ───────────────────────────────────────────────────────────────────
function _build_year_nav(years, cur) {
    var target = document.getElementById("timeline-nav");
    if (!target) return;
    var wrap = document.createElement("div");
    wrap.className = "d-flex flex-wrap gap-1";
    var all_a = document.createElement("a");
    all_a.href = "network_table.html";
    all_a.className = "btn btn-sm " + (cur === "all" ? "btn-primary" : "btn-outline-secondary");
    all_a.textContent = "All";
    wrap.appendChild(all_a);
    years.forEach(function(y) {
        var a = document.createElement("a");
        a.href = "network_table_" + y.year + ".html";
        a.className = "btn btn-sm " + (cur === y.year ? "btn-primary" : "btn-outline-secondary");
        a.textContent = y.year;
        wrap.appendChild(a);
    });
    target.appendChild(wrap);
}

// ── Mini histogram SVG ─────────────────────────────────────────────────────────
function _mini_hist(all_val_str, yr_vals, cur) {
    var BAR_W = 7, GAP = 2, H = 20, ns = "http://www.w3.org/2000/svg";
    var bars = [{ year: "all", raw: all_val_str }]
        .concat((yr_vals || []).map(function(y) { return { year: y.year, raw: y.value }; }));
    var maxV = bars.reduce(function(m, b) {
        var v = parseFloat(b.raw); return (isFinite(v) && v > m) ? v : m;
    }, 0);
    if (!maxV) return null;
    var W = bars.length * (BAR_W + GAP) - GAP;
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.style.cssText = "display:block;flex-shrink:0";
    bars.forEach(function(b, i) {
        var v = parseFloat(b.raw);
        if (!isFinite(v) || v < 0) return;
        var bh = Math.max(1, Math.round(v / maxV * H));
        var is_all = b.year === "all";
        var is_cur = is_all ? cur === "all" : cur === b.year;
        var fill = is_cur ? "#1d4ed8" : (is_all ? "#bfdbfe" : "#cbd5e1");
        var r = document.createElementNS(ns, "rect");
        r.setAttribute("x", i * (BAR_W + GAP)); r.setAttribute("y", H - bh);
        r.setAttribute("width", BAR_W); r.setAttribute("height", bh);
        r.setAttribute("fill", fill);
        var t = document.createElementNS(ns, "title");
        t.textContent = (is_all ? "All" : b.year) + ": " + b.raw;
        r.appendChild(t); svg.appendChild(r);
    });
    return svg;
}
