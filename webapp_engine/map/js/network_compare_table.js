Promise.all([
    fetch("data/network_metrics.json").then(function(r) { return r.json(); }),
    fetch("data_compare/network_metrics.json").then(function(r) { return r.json(); }),
    fetch("data/channels.json").then(function(r) { return r.json(); }),
    fetch("data_compare/channels.json").then(function(r) { return r.json(); }),
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

    function buildPts(nodes, xKey, yKey) {
        return nodes
            .filter(function(n) { return n[xKey] > 0 && n[yKey] > 0; })
            .map(function(n) { return { x: n[xKey], y: n[yKey], label: n.label || n.id, fans: n.fans || 0, msgs: n.messages_count || 0 }; });
    }

    function buildDatasets(xKey, yKey) {
        return { ptsA: buildPts(nodesA, xKey, yKey), ptsB: buildPts(nodesB, xKey, yKey) };
    }

    var initial = buildDatasets(xSelect.value, ySelect.value);
    countNote.textContent = initial.ptsA.length + " + " + initial.ptsB.length + " nodes (zero values excluded from log scale)";

    var chart = new Chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                { label: "This network", data: initial.ptsA, backgroundColor: "rgba(37,99,235,0.55)", pointRadius: 4, pointHoverRadius: 6 },
                { label: "Compare network", data: initial.ptsB, backgroundColor: "rgba(220,38,38,0.55)", pointRadius: 4, pointHoverRadius: 6 },
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
                legend: { display: true, position: "top" },
                tooltip: {
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
        chart.data.datasets[0].data = ds.ptsA;
        chart.data.datasets[1].data = ds.ptsB;
        chart.options.scales.x.title.text = labelOf[xKey];
        chart.options.scales.y.title.text = labelOf[yKey];
        chart.resetZoom();
        chart.update();
        countNote.textContent = ds.ptsA.length + " + " + ds.ptsB.length + " nodes (zero values excluded from log scale)";
    }

    xSelect.addEventListener("change", updateChart);
    ySelect.addEventListener("change", updateChart);
    resetBtn.addEventListener("click", function() { chart.resetZoom(); });
});
