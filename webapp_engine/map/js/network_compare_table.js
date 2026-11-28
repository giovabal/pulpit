import { measure_label, strategy_label } from './labels.js';
import { histogram, power_law_fit } from './charts.js';
import { fetchJson, arrMin, arrMax, loadFailed } from './utils.js';

// Statistics renamed after an analysis may have been exported: an older export's row, read under its new
// name, still lines up with the same statistic of a newer one.
// How the two analyses are named in every table, legend and tooltip of the page.
var THIS_ANALYSIS = "This analysis";
var COMPARED_ANALYSIS = "Compared analysis";

var LEGACY_LABELS = {
    "Nodes": "Channels",
    "Edges": "Ties",
    "Edges / Nodes": "Ties per channel",
    "Avg Clustering (0–1)": "Mean clustering (0–1)",
    "Avg Path Length": "Mean path length",
    "Avg Path Length †": "Mean path length †",
    "Directed Avg Path Length": "Directed mean path length",
    "Directed Avg Path Length ‡": "Directed mean path length ‡",
    "Directed Diameter": "Directed diameter",
    "Directed Diameter ‡": "Directed diameter ‡",
    "Global Efficiency (0–1)": "Global efficiency (0–1)",
    "Algebraic Connectivity": "Algebraic connectivity",
    "Algebraic Connectivity †": "Algebraic connectivity †",
    "WCC count": "Weakly connected components",
    "Largest WCC fraction (0–1)": "Largest weakly connected component, share (0–1)",
    "SCC count": "Strongly connected components",
    "Largest SCC fraction (0–1)": "Largest strongly connected component, share (0–1)",
    "Mean Burt's Constraint (~0–1)": "Mean Burt's constraint (~0–1)",
    "Content Originality (0–1)": "Content originality (0–1)",
    "Amplification Ratio": "Amplification ratio",
};

// Looked up without regard to case: the capitals of a statistic's name changed between releases too.
var _LEGACY_LABELS_LC = {};
Object.keys(LEGACY_LABELS).forEach(function(old) { _LEGACY_LABELS_LC[old.toLowerCase()] = LEGACY_LABELS[old]; });

function _currentLabel(label) {
    var text = String(label);
    var renamed = _LEGACY_LABELS_LC[text.toLowerCase()];
    if (renamed) return renamed;
    return text.replace(/ Centralization \(approx\., 0–1\)$/i, " centralisation (approx., 0–1)")
        .replace(/^HITS Hub\b/, "HITS hub").replace(/^HITS Authority\b/, "HITS authority");
}

// Two exports' rows are the same statistic when their names match, whatever the capitals.
function _labelKey(label) {
    return String(label).toLowerCase();
}

function _measureLabels(measures) {
    return measures.map(function(m) { return [m[0], measure_label(m[0], m[1])]; });
}

Promise.all([
    fetchJson("data/network_metrics.json"),
    fetchJson("data_2/network_metrics.json"),
    fetchJson("data/channels.json"),
    fetchJson("data_2/channels.json"),
]).then(function(results) {
    var dataA = results[0],
        dataB = results[1],
        channelsA = results[2],
        channelsB = results[3];
    var nodesA = channelsA.nodes;
    var nodesB = channelsB.nodes;
    var measuresA = _measureLabels(channelsA.measures || []);
    var measuresB = _measureLabels(channelsB.measures || []);

    // --- Comparison table ---
    var tablesSection = document.getElementById("compare-tables-section");

    [dataA, dataB].forEach(function(d) {
        d.summary_rows.forEach(function(row) { row.label = _currentLabel(row.label); });
    });
    var aValueOf = {};
    dataA.summary_rows.forEach(function(row) { aValueOf[_labelKey(row.label)] = row.value; });
    var bValueOf = {};
    dataB.summary_rows.forEach(function(row) { bValueOf[_labelKey(row.label)] = row.value; });

    // Merge labels: preserve A order, append B-only labels at the end
    var allLabels = [];
    var seen = {};
    dataA.summary_rows.concat(dataB.summary_rows).forEach(function(row) {
        var key = _labelKey(row.label);
        if (!seen[key]) {
            seen[key] = true;
            allLabels.push(row.label);
        }
    });

    var h2 = document.createElement("h2");
    h2.textContent = "Whole-network statistics";
    tablesSection.appendChild(h2);
    var table = document.createElement("table");
    table.className = "table table-sm table-hover table-fit";
    var thead = document.createElement("thead");
    var tr = document.createElement("tr");
    ["Statistic", THIS_ANALYSIS, COMPARED_ANALYSIS].forEach(function(label, i) {
        var th = document.createElement("th");
        th.scope = "col";
        if (i > 0) th.className = "number";
        th.textContent = label;
        tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    allLabels.forEach(function(label) {
        var tr2 = document.createElement("tr");
        var td1 = document.createElement("td");
        td1.textContent = label;
        var td2 = document.createElement("td");
        td2.className = "number";
        var key = _labelKey(label);
        td2.textContent = aValueOf[key] !== undefined ? aValueOf[key] : MISSING;
        var td3 = document.createElement("td");
        td3.className = "number";
        td3.textContent = bValueOf[key] !== undefined ? bValueOf[key] : MISSING;
        tr2.appendChild(td1);
        tr2.appendChild(td2);
        tr2.appendChild(td3);
        tbody.appendChild(tr2);
    });
    table.appendChild(tbody);
    var tableWrap = document.createElement("div");
    tableWrap.className = "table-responsive";
    tableWrap.appendChild(table);
    tablesSection.appendChild(tableWrap);

    if (dataA.wcc_note_visible || dataB.wcc_note_visible) {
        var note = document.createElement("p");
        note.className = "text-muted small mt-1";
        note.textContent = "† Computed on the largest weakly connected component (undirected)";
        tablesSection.appendChild(note);
    }
    if (dataA.scc_note_visible || dataB.scc_note_visible) {
        var note2 = document.createElement("p");
        note2.className = "text-muted small mt-1";
        note2.textContent = "‡ Computed on the largest strongly connected component (directed)";
        tablesSection.appendChild(note2);
    }

    // --- Modularity comparison ---
    if ((dataA.modularity_rows && dataA.modularity_rows.length) || (dataB.modularity_rows && dataB.modularity_rows.length)) {
        var h2m = document.createElement("h2");
        h2m.textContent = "Modularity by method";
        tablesSection.appendChild(h2m);

        var aMod = {},
            bMod = {};
        (dataA.modularity_rows || []).forEach(function(row) { aMod[row.strategy] = row.modularity; });
        (dataB.modularity_rows || []).forEach(function(row) { bMod[row.strategy] = row.modularity; });

        var allStrategies = [],
            seenS = {};
        (dataA.modularity_rows || []).forEach(function(row) {
            if (!seenS[row.strategy]) {
                seenS[row.strategy] = true;
                allStrategies.push(row.strategy);
            }
        });
        (dataB.modularity_rows || []).forEach(function(row) {
            if (!seenS[row.strategy]) {
                seenS[row.strategy] = true;
                allStrategies.push(row.strategy);
            }
        });

        var modTable = document.createElement("table");
        modTable.className = "table table-sm table-hover table-fit sortable";
        var mThead = document.createElement("thead");
        var mTr = document.createElement("tr");
        ["Method", THIS_ANALYSIS, COMPARED_ANALYSIS].forEach(function(label, i) {
            var th = document.createElement("th");
            th.scope = "col";
            if (i > 0) th.className = "number";
            th.textContent = label;
            mTr.appendChild(th);
        });
        mThead.appendChild(mTr);
        modTable.appendChild(mThead);
        var mTbody = document.createElement("tbody");
        allStrategies.forEach(function(strategy) {
            var tr3 = document.createElement("tr");
            var td1 = document.createElement("td");
            td1.className = "nowrap";
            td1.textContent = strategy_label(strategy);
            var td2 = document.createElement("td");
            td2.className = "number";
            td2.textContent = aMod[strategy] !== undefined ? aMod[strategy] : MISSING;
            var td3 = document.createElement("td");
            td3.className = "number";
            td3.textContent = bMod[strategy] !== undefined ? bMod[strategy] : MISSING;
            tr3.appendChild(td1);
            tr3.appendChild(td2);
            tr3.appendChild(td3);
            mTbody.appendChild(tr3);
        });
        modTable.appendChild(mTbody);
        var modWrap = document.createElement("div");
        modWrap.className = "table-responsive";
        modWrap.appendChild(modTable);
        tablesSection.appendChild(modWrap);
    }

    initSortableTables();

    // --- Degree distribution histogram (lazy, both networks) ---
    var distSection = document.getElementById("degree-dist-section");
    var distWrapper = document.getElementById("degree-distribution");
    if (distWrapper) distWrapper.classList.remove("d-none");

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
    [
        ["in_deg", "In-strength"],
        ["out_deg", "Out-strength"]
    ].forEach(function(opt) {
        dirSel.appendChild(new Option(opt[1], opt[0]));
    });
    dirWrap.appendChild(dirLbl);
    dirWrap.appendChild(dirSel);
    distControls.appendChild(dirWrap);
    distSection.appendChild(distControls);

    var distCanvasWrap = document.createElement("div");
    distCanvasWrap.style.cssText = "height:280px;position:relative;";
    var distCanvas = document.createElement("canvas");
    distCanvas.setAttribute("role", "img");
    distCanvas.setAttribute("aria-label", "Histogram of the channels of the two analyses by in-strength or out-strength");
    distCanvasWrap.appendChild(distCanvas);
    distSection.appendChild(distCanvasWrap);

    // Both analyses on the same bins (charts.js histogram).
    function buildCompareDistData(key) {
        var bins = histogram([
            nodesA.map(function(n) { return n[key] || 0; }),
            nodesB.map(function(n) { return n[key] || 0; }),
        ]);
        return { labels: bins.labels, countsA: bins.counts[0], countsB: bins.counts[1] };
    }

    var distChart = null;
    var distInitialized = false;

    function _distLabel() {
        return dirSel.value === "out_deg" ? "Out-strength" : "In-strength";
    }

    function initDistChart() {
        if (distInitialized) return;
        distInitialized = true;
        var dd = buildCompareDistData(dirSel.value);
        distChart = new Chart(distCanvas, {
            type: "bar",
            data: {
                labels: dd.labels,
                datasets: [
                    { label: THIS_ANALYSIS, data: dd.countsA, backgroundColor: pulpitTheme().series[0], borderRadius: 3 },
                    { label: COMPARED_ANALYSIS, data: dd.countsB, backgroundColor: pulpitTheme().series[1], borderRadius: 3 }
                ]
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true, position: "top" } },
                scales: {
                    x: { title: { display: true, text: _distLabel(), font: { size: 12 } }, grid: { display: false }, ticks: { font: { size: 11 } } },
                    y: { title: { display: true, text: "Channels", font: { size: 12 } }, ticks: { font: { size: 11 }, precision: 0 } }
                }
            }
        });
    }

    dirSel.addEventListener("change", function() {
        if (!distChart) return;
        var dd = buildCompareDistData(dirSel.value);
        distChart.data.labels = dd.labels;
        distChart.data.datasets[0].data = dd.countsA;
        distChart.data.datasets[1].data = dd.countsB;
        distChart.options.scales.x.title.text = _distLabel();
        distChart.update();
    });

    if ("IntersectionObserver" in window) {
        var distObs = new IntersectionObserver(function(entries, obs) {
            if (entries[0].isIntersecting) {
                obs.disconnect();
                initDistChart();
            }
        }, { threshold: 0.1 });
        distObs.observe(distSection);
    } else {
        initDistChart();
    }

    // --- Scatter plots ---
    // Use the intersection of measures available in both exports
    var keysB = new Set(measuresB.map(function(m) { return m[0]; }));
    var commonMeasures = measuresA.filter(function(m) { return keysB.has(m[0]); });
    if (commonMeasures.length < 2) return;

    var scatterSection = document.getElementById("scatter-section");
    var scatterWrapper = document.getElementById("measure-comparison");
    if (scatterWrapper) scatterWrapper.classList.remove("d-none");
    var labelOf = {};
    commonMeasures.forEach(function(m) { labelOf[m[0]] = m[1]; });

    // Controls
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
        commonMeasures.forEach(function(m) { sel.appendChild(new Option(m[1], m[0])); });
        wrap.appendChild(lbl);
        wrap.appendChild(sel);
        controls.appendChild(wrap);
        return sel;
    }

    var xSelect = makeSelect("x-axis-select", "X axis");
    var ySelect = makeSelect("y-axis-select", "Y axis");

    var normalizeWrap = document.createElement("div");
    normalizeWrap.className = "d-flex align-items-center gap-2";
    var normalizeChk = document.createElement("input");
    normalizeChk.type = "checkbox";
    normalizeChk.className = "form-check-input";
    normalizeChk.id = "normalize-chk";
    var normalizeLbl = document.createElement("label");
    normalizeLbl.className = "form-check-label small fw-semibold";
    normalizeLbl.htmlFor = "normalize-chk";
    normalizeLbl.textContent = "Normalise axes to 0–1 per analysis";
    normalizeWrap.appendChild(normalizeChk);
    normalizeWrap.appendChild(normalizeLbl);
    controls.appendChild(normalizeWrap);

    var resetWrap = document.createElement("div");
    resetWrap.className = "scatter-reset-wrap";
    var resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.className = "btn btn-outline-secondary btn-sm";
    resetBtn.textContent = "Reset zoom";
    resetWrap.appendChild(resetBtn);
    controls.appendChild(resetWrap);

    var countNote = document.createElement("div");
    countNote.className = "text-muted small ms-auto scatter-count-note";
    controls.appendChild(countNote);

    scatterSection.appendChild(controls);

    var canvasWrap = document.createElement("div");
    canvasWrap.className = "scatter-canvas-wrap";
    var canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Scatter plot of the channels of the two analyses on two measures");
    canvasWrap.appendChild(canvas);
    scatterSection.appendChild(canvasWrap);

    // Default axes: prefer in_deg vs pagerank
    var defaultX = commonMeasures[0][0],
        defaultY = commonMeasures[1][0];
    commonMeasures.forEach(function(m) { if (m[0] === "in_deg") defaultX = m[0]; });
    commonMeasures.forEach(function(m) { if (m[0] === "pagerank") defaultY = m[0]; });
    if (defaultX === defaultY) defaultY = commonMeasures.find(function(m) { return m[0] !== defaultX; })[0];
    xSelect.value = defaultX;
    ySelect.value = defaultY;

    function buildPts(nodes, xKey, yKey, xMin, xRange, yMin, yRange) {
        return nodes
            .filter(function(n) { return n[xKey] > 0 && n[yKey] > 0; })
            .map(function(n) {
                var x = xRange ? (n[xKey] - xMin) / xRange : n[xKey];
                var y = yRange ? (n[yKey] - yMin) / yRange : n[yKey];
                return {
                    x: x,
                    y: y,
                    label: n.label || n.id,
                    fans: n.fans || 0,
                    msgs: n.messages_count || 0,
                    xRaw: n[xKey],
                    yRaw: n[yKey]
                };
            });
    }

    function minMax(nodes, key) {
        var vals = nodes.map(function(n) { return n[key] || 0; });
        var mn = arrMin(vals),
            mx = arrMax(vals);
        return { min: mn, range: mx - mn || 1 };
    }

    // Fit on RAW values (which every point carries) so a node normalized to exactly
    // 0 is not dropped by the log filter, then map the two endpoints back into the
    // plotted (optionally normalized) coordinate space. `ax` is null in raw mode.
    function buildRegLine(pts, ax) {
        var valid = pts.filter(function(p) { return p.xRaw > 0 && p.yRaw > 0; });
        var fit = power_law_fit(valid.map(function(p) { return { x: p.xRaw, y: p.yRaw }; }));
        if (!fit) return [];
        var xs = valid.map(function(p) { return p.xRaw; });
        var xMin = arrMin(xs),
            xMax = arrMax(xs);
        var endpoints = [
            { x: xMin, y: Math.exp(fit.intercept) * Math.pow(xMin, fit.slope) },
            { x: xMax, y: Math.exp(fit.intercept) * Math.pow(xMax, fit.slope) }
        ];
        if (!ax) return endpoints;
        return endpoints.map(function(p) {
            return {
                x: ax.x.range ? (p.x - ax.x.min) / ax.x.range : p.x,
                y: ax.y.range ? (p.y - ax.y.min) / ax.y.range : p.y
            };
        });
    }

    function buildDatasets(xKey, yKey) {
        var normalize = normalizeChk.checked;
        var axA = normalize ? { x: minMax(nodesA, xKey), y: minMax(nodesA, yKey) } : null;
        var axB = normalize ? { x: minMax(nodesB, xKey), y: minMax(nodesB, yKey) } : null;
        var ptsA = buildPts(nodesA, xKey, yKey, axA && axA.x.min, axA && axA.x.range, axA && axA.y.min, axA && axA.y.range);
        var ptsB = buildPts(nodesB, xKey, yKey, axB && axB.x.min, axB && axB.x.range, axB && axB.y.min, axB && axB.y.range);
        return { ptsA: ptsA, ptsB: ptsB, regA: buildRegLine(ptsA, axA), regB: buildRegLine(ptsB, axB) };
    }

    var initial = buildDatasets(xSelect.value, ySelect.value);
    countNote.textContent = fmtInt(initial.ptsA.length) + " + " + fmtInt(initial.ptsB.length) + " channels (zeros left out)";

    function scaleType() { return normalizeChk.checked ? "linear" : "logarithmic"; }

    var chart = new Chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                { label: THIS_ANALYSIS, data: initial.ptsA, backgroundColor: pulpitTheme().series[0], pointRadius: 4, pointHoverRadius: 6 },
                { label: "Trend, " + THIS_ANALYSIS.toLowerCase(), data: initial.regA, type: "line", borderColor: pulpitTheme().series[0], borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
                { label: COMPARED_ANALYSIS, data: initial.ptsB, backgroundColor: pulpitTheme().series[1], pointRadius: 4, pointHoverRadius: 6 },
                { label: "Trend, " + COMPARED_ANALYSIS.toLowerCase(), data: initial.regB, type: "line", borderColor: pulpitTheme().series[1], borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
            ],
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { type: scaleType(), title: { display: true, text: labelOf[xSelect.value], font: { size: 12 } }, ticks: { font: { size: 11 } } },
                y: { type: scaleType(), title: { display: true, text: labelOf[ySelect.value], font: { size: 12 } }, ticks: { font: { size: 11 } } },
            },
            plugins: {
                legend: { display: true, position: "top", labels: { filter: function(item) { return item.datasetIndex % 2 === 0; } } },
                tooltip: {
                    filter: function(item) { return item.datasetIndex % 2 === 0; },
                    callbacks: {
                        label: function(ctx) {
                            var d = ctx.raw,
                                xLbl = chart.options.scales.x.title.text,
                                yLbl = chart.options.scales.y.title.text;
                            var xVal = sigFig(d.xRaw !== undefined ? d.xRaw : d.x, 4);
                            var yVal = sigFig(d.yRaw !== undefined ? d.yRaw : d.y, 4);
                            return ["Channel: " + d.label, xLbl + ": " + xVal, yLbl + ": " + yVal, "Subscribers: " + fmtInt(d.fans), "Messages: " + fmtInt(d.msgs)];
                        },
                    },
                },
                zoom: { pan: { enabled: true, mode: "xy" }, zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "xy" } },
            },
        },
    });

    function updateChart() {
        var xKey = xSelect.value,
            yKey = ySelect.value;
        var ds = buildDatasets(xKey, yKey);
        chart.data.datasets[0].data = ds.ptsA;
        chart.data.datasets[1].data = ds.regA;
        chart.data.datasets[2].data = ds.ptsB;
        chart.data.datasets[3].data = ds.regB;
        chart.options.scales.x.type = scaleType();
        chart.options.scales.y.type = scaleType();
        chart.options.scales.x.title.text = labelOf[xKey];
        chart.options.scales.y.title.text = labelOf[yKey];
        chart.resetZoom();
        chart.update();
        var note = normalizeChk.checked ? " channels (normalised to 0–1 per analysis)" : " channels (zeros left out)";
        countNote.textContent = fmtInt(ds.ptsA.length) + " + " + fmtInt(ds.ptsB.length) + note;
    }

    xSelect.addEventListener("change", updateChart);
    ySelect.addEventListener("change", updateChart);
    normalizeChk.addEventListener("change", updateChart);
    resetBtn.addEventListener("click", function() { chart.resetZoom(); });
}).catch(function(err) {
    loadFailed(err, "the data of the two analyses");
});
