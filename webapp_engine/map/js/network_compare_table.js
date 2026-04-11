Promise.all([
    fetch("data/network_metrics.json").then(function(r) { return r.json(); }),
    fetch("data_2/network_metrics.json").then(function(r) { return r.json(); }),
    fetch("data/channels.json").then(function(r) { return r.json(); }),
    fetch("data_2/channels.json").then(function(r) { return r.json(); }),
]).then(function(results) {
    var dataA = results[0], dataB = results[1], channelsA = results[2], channelsB = results[3];
    var nodesA = channelsA.nodes;
    var nodesB = channelsB.nodes;
    var measuresA = channelsA.measures || [];
    var measuresB = channelsB.measures || [];

    // --- Comparison table ---
    var tablesSection = document.getElementById("compare-tables-section");

    var aValueOf = {};
    dataA.summary_rows.forEach(function(row) { aValueOf[row.label] = row.value; });
    var bValueOf = {};
    dataB.summary_rows.forEach(function(row) { bValueOf[row.label] = row.value; });

    // Merge labels: preserve A order, append B-only labels at the end
    var allLabels = [];
    var seen = {};
    dataA.summary_rows.forEach(function(row) {
        if (!seen[row.label]) { seen[row.label] = true; allLabels.push(row.label); }
    });
    dataB.summary_rows.forEach(function(row) {
        if (!seen[row.label]) { seen[row.label] = true; allLabels.push(row.label); }
    });

    var h5 = document.createElement("h5"); h5.className = "mb-2"; h5.textContent = "Whole-network metrics";
    tablesSection.appendChild(h5);
    var table = document.createElement("table");
    table.className = "table table-sm table-hover";
    var thead = document.createElement("thead"); var tr = document.createElement("tr");
    ["Metric", "This network", "Compare network"].forEach(function(label, i) {
        var th = document.createElement("th"); th.scope = "col";
        if (i > 0) th.className = "number";
        th.textContent = label; tr.appendChild(th);
    });
    thead.appendChild(tr); table.appendChild(thead);
    var tbody = document.createElement("tbody");
    allLabels.forEach(function(label) {
        var tr2 = document.createElement("tr");
        var td1 = document.createElement("td"); td1.textContent = label;
        var td2 = document.createElement("td"); td2.className = "number"; td2.textContent = aValueOf[label] !== undefined ? aValueOf[label] : "N/A";
        var td3 = document.createElement("td"); td3.className = "number"; td3.textContent = bValueOf[label] !== undefined ? bValueOf[label] : "N/A";
        tr2.appendChild(td1); tr2.appendChild(td2); tr2.appendChild(td3);
        tbody.appendChild(tr2);
    });
    table.appendChild(tbody); tablesSection.appendChild(table);

    if (dataA.wcc_note_visible || dataB.wcc_note_visible) {
        var note = document.createElement("p"); note.className = "text-muted small mt-1";
        note.textContent = "* Computed on the largest weakly connected component (undirected)";
        tablesSection.appendChild(note);
    }

    // --- Modularity comparison ---
    if ((dataA.modularity_rows && dataA.modularity_rows.length) || (dataB.modularity_rows && dataB.modularity_rows.length)) {
        var h5m = document.createElement("h5"); h5m.className = "mb-2 mt-4"; h5m.textContent = "Modularity by strategy";
        tablesSection.appendChild(h5m);

        var aMod = {}, bMod = {};
        (dataA.modularity_rows || []).forEach(function(row) { aMod[row.strategy] = row.value; });
        (dataB.modularity_rows || []).forEach(function(row) { bMod[row.strategy] = row.value; });

        var allStrategies = [], seenS = {};
        (dataA.modularity_rows || []).forEach(function(row) {
            if (!seenS[row.strategy]) { seenS[row.strategy] = true; allStrategies.push(row.strategy); }
        });
        (dataB.modularity_rows || []).forEach(function(row) {
            if (!seenS[row.strategy]) { seenS[row.strategy] = true; allStrategies.push(row.strategy); }
        });

        var modTable = document.createElement("table"); modTable.className = "table table-sm table-hover sortable";
        var mThead = document.createElement("thead"); var mTr = document.createElement("tr");
        ["Strategy", "This network", "Compare network"].forEach(function(label, i) {
            var th = document.createElement("th"); th.scope = "col";
            if (i > 0) th.className = "number";
            th.textContent = label; mTr.appendChild(th);
        });
        mThead.appendChild(mTr); modTable.appendChild(mThead);
        var mTbody = document.createElement("tbody");
        allStrategies.forEach(function(strategy) {
            var tr3 = document.createElement("tr");
            var td1 = document.createElement("td"); td1.textContent = strategy;
            var td2 = document.createElement("td"); td2.className = "number"; td2.textContent = aMod[strategy] !== undefined ? aMod[strategy] : "N/A";
            var td3 = document.createElement("td"); td3.className = "number"; td3.textContent = bMod[strategy] !== undefined ? bMod[strategy] : "N/A";
            tr3.appendChild(td1); tr3.appendChild(td2); tr3.appendChild(td3);
            mTbody.appendChild(tr3);
        });
        modTable.appendChild(mTbody); tablesSection.appendChild(modTable);
    }

    initSortableTables();

    // --- Degree distribution histogram (lazy, both networks) ---
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

    function buildCompareDistData(key) {
        var valsA = nodesA.map(function(n) { return n[key] || 0; });
        var valsB = nodesB.map(function(n) { return n[key] || 0; });
        var maxVal = Math.max.apply(null, valsA.concat(valsB));
        var binSize = 10;
        var numBins = Math.max(1, Math.ceil((maxVal + 1) / binSize));
        var countsA = new Array(numBins).fill(0);
        var countsB = new Array(numBins).fill(0);
        valsA.forEach(function(v) { countsA[Math.floor(v / binSize)]++; });
        valsB.forEach(function(v) { countsB[Math.floor(v / binSize)]++; });
        while (numBins > 1 && countsA[numBins - 1] === 0 && countsB[numBins - 1] === 0) {
            countsA.pop(); countsB.pop(); numBins--;
        }
        var labels = countsA.map(function(_, i) {
            return (i * binSize) + "\u2013" + (i * binSize + binSize - 1);
        });
        return { labels: labels, countsA: countsA, countsB: countsB };
    }

    var distChart = null;
    var distInitialized = false;

    function initDistChart() {
        if (distInitialized) return;
        distInitialized = true;
        var dd = buildCompareDistData(dirSel.value);
        distChart = new Chart(distCanvas, {
            type: "bar",
            data: {
                labels: dd.labels,
                datasets: [
                    { label: "This network", data: dd.countsA, backgroundColor: "rgba(37,99,235,0.65)", borderRadius: 3 },
                    { label: "Compare network", data: dd.countsB, backgroundColor: "rgba(220,38,38,0.65)", borderRadius: 3 }
                ]
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true, position: "top" } },
                scales: {
                    x: { title: { display: true, text: "Links per node", font: { size: 12 } }, grid: { display: false }, ticks: { font: { size: 11 } } },
                    y: { title: { display: true, text: "Nodes", font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 }, precision: 0 } }
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

    // --- Scatter plots ---
    // Use the intersection of measures available in both exports
    var keysB = new Set(measuresB.map(function(m) { return m[0]; }));
    var commonMeasures = measuresA.filter(function(m) { return keysB.has(m[0]); });
    if (commonMeasures.length < 2) return;

    var scatterSection = document.getElementById("scatter-section");
    var labelOf = {};
    commonMeasures.forEach(function(m) { labelOf[m[0]] = m[1]; });

    // Controls
    var controls = document.createElement("div");
    controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";

    function makeSelect(id, labelText) {
        var wrap = document.createElement("div");
        var lbl = document.createElement("label"); lbl.className = "form-label mb-1 d-block fw-semibold small"; lbl.htmlFor = id; lbl.textContent = labelText;
        var sel = document.createElement("select"); sel.className = "form-select form-select-sm scatter-select"; sel.id = id;
        commonMeasures.forEach(function(m) { sel.appendChild(new Option(m[1], m[0])); });
        wrap.appendChild(lbl); wrap.appendChild(sel);
        controls.appendChild(wrap);
        return sel;
    }

    var xSelect = makeSelect("x-axis-select", "X axis");
    var ySelect = makeSelect("y-axis-select", "Y axis");

    var normalizeWrap = document.createElement("div"); normalizeWrap.className = "d-flex align-items-center gap-2";
    var normalizeChk = document.createElement("input"); normalizeChk.type = "checkbox"; normalizeChk.className = "form-check-input"; normalizeChk.id = "normalize-chk";
    var normalizeLbl = document.createElement("label"); normalizeLbl.className = "form-check-label small fw-semibold"; normalizeLbl.htmlFor = "normalize-chk"; normalizeLbl.textContent = "Normalize axes [0–1] per network";
    normalizeWrap.appendChild(normalizeChk); normalizeWrap.appendChild(normalizeLbl);
    controls.appendChild(normalizeWrap);

    var resetWrap = document.createElement("div"); resetWrap.className = "scatter-reset-wrap";
    var resetBtn = document.createElement("button"); resetBtn.className = "btn btn-outline-secondary btn-sm"; resetBtn.textContent = "Reset zoom";
    resetWrap.appendChild(resetBtn); controls.appendChild(resetWrap);

    var countNote = document.createElement("div"); countNote.className = "text-muted small ms-auto scatter-count-note";
    controls.appendChild(countNote);

    scatterSection.appendChild(controls);

    var canvasWrap = document.createElement("div"); canvasWrap.className = "scatter-canvas-wrap";
    var canvas = document.createElement("canvas"); canvasWrap.appendChild(canvas);
    scatterSection.appendChild(canvasWrap);

    // Default axes: prefer in_deg vs pagerank
    var defaultX = commonMeasures[0][0], defaultY = commonMeasures[1][0];
    commonMeasures.forEach(function(m) { if (m[0] === "in_deg") defaultX = m[0]; });
    commonMeasures.forEach(function(m) { if (m[0] === "pagerank") defaultY = m[0]; });
    if (defaultX === defaultY) defaultY = commonMeasures.find(function(m) { return m[0] !== defaultX; })[0];
    xSelect.value = defaultX; ySelect.value = defaultY;

    function buildPts(nodes, xKey, yKey, xMin, xRange, yMin, yRange) {
        return nodes
            .filter(function(n) { return n[xKey] > 0 && n[yKey] > 0; })
            .map(function(n) {
                var x = xRange ? (n[xKey] - xMin) / xRange : n[xKey];
                var y = yRange ? (n[yKey] - yMin) / yRange : n[yKey];
                return { x: x, y: y, label: n.label || n.id, fans: n.fans || 0, msgs: n.messages_count || 0,
                         xRaw: n[xKey], yRaw: n[yKey] };
            });
    }

    function minMax(nodes, key) {
        var vals = nodes.map(function(n) { return n[key] || 0; });
        var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
        return { min: mn, range: mx - mn || 1 };
    }

    function powerLawFit(pts) {
        var valid = pts.filter(function(p) { return p.x > 0 && p.y > 0; });
        if (valid.length < 2) return null;
        var n = valid.length, sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
        valid.forEach(function(p) { var lx = Math.log(p.x), ly = Math.log(p.y); sumX += lx; sumY += ly; sumXY += lx * ly; sumX2 += lx * lx; });
        var d = n * sumX2 - sumX * sumX;
        if (!d) return null;
        var slope = (n * sumXY - sumX * sumY) / d;
        return { slope: slope, intercept: (sumY - slope * sumX) / n };
    }

    function buildRegLine(pts) {
        var valid = pts.filter(function(p) { return p.x > 0 && p.y > 0; });
        var fit = powerLawFit(valid);
        if (!fit) return [];
        var xs = valid.map(function(p) { return p.x; });
        var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
        return [
            { x: xMin, y: Math.exp(fit.intercept) * Math.pow(xMin, fit.slope) },
            { x: xMax, y: Math.exp(fit.intercept) * Math.pow(xMax, fit.slope) }
        ];
    }

    function buildDatasets(xKey, yKey) {
        var normalize = normalizeChk.checked;
        var axA = normalize ? { x: minMax(nodesA, xKey), y: minMax(nodesA, yKey) } : null;
        var axB = normalize ? { x: minMax(nodesB, xKey), y: minMax(nodesB, yKey) } : null;
        var ptsA = buildPts(nodesA, xKey, yKey, axA && axA.x.min, axA && axA.x.range, axA && axA.y.min, axA && axA.y.range);
        var ptsB = buildPts(nodesB, xKey, yKey, axB && axB.x.min, axB && axB.x.range, axB && axB.y.min, axB && axB.y.range);
        return { ptsA: ptsA, ptsB: ptsB, regA: buildRegLine(ptsA), regB: buildRegLine(ptsB) };
    }

    var initial = buildDatasets(xSelect.value, ySelect.value);
    countNote.textContent = initial.ptsA.length + " + " + initial.ptsB.length + " nodes (zero values excluded)";

    function scaleType() { return normalizeChk.checked ? "linear" : "logarithmic"; }

    var chart = new Chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                { label: "This network", data: initial.ptsA, backgroundColor: "rgba(37,99,235,0.55)", pointRadius: 4, pointHoverRadius: 6 },
                { label: "Trend A", data: initial.regA, type: "line", borderColor: "rgba(37,99,235,0.75)", borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
                { label: "Compare network", data: initial.ptsB, backgroundColor: "rgba(220,38,38,0.55)", pointRadius: 4, pointHoverRadius: 6 },
                { label: "Trend B", data: initial.regB, type: "line", borderColor: "rgba(220,38,38,0.75)", borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, tension: 0 },
            ],
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { type: scaleType(), title: { display: true, text: labelOf[xSelect.value], font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } } },
                y: { type: scaleType(), title: { display: true, text: labelOf[ySelect.value], font: { size: 12 } }, grid: { color: "#e5e7eb" }, ticks: { font: { size: 11 } } },
            },
            plugins: {
                legend: { display: true, position: "top", labels: { filter: function(item) { return item.datasetIndex % 2 === 0; } } },
                tooltip: {
                    filter: function(item) { return item.datasetIndex % 2 === 0; },
                    callbacks: {
                        label: function(ctx) {
                            var d = ctx.raw, xLbl = chart.options.scales.x.title.text, yLbl = chart.options.scales.y.title.text;
                            var xVal = d.xRaw !== undefined ? d.xRaw.toFixed(4) : d.x.toFixed(4);
                            var yVal = d.yRaw !== undefined ? d.yRaw.toFixed(4) : d.y.toFixed(4);
                            return ["Channel: " + d.label, xLbl + ": " + xVal, yLbl + ": " + yVal, "Subscribers: " + d.fans.toLocaleString(), "Messages: " + d.msgs.toLocaleString()];
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
        var note = normalizeChk.checked ? " nodes (normalized to [0–1] per network)" : " nodes (zero values excluded)";
        countNote.textContent = ds.ptsA.length + " + " + ds.ptsB.length + note;
    }

    xSelect.addEventListener("change", updateChart);
    ySelect.addEventListener("change", updateChart);
    normalizeChk.addEventListener("change", updateChart);
    resetBtn.addEventListener("click", function() { chart.resetZoom(); });
});
