Promise.all([
    fetch("data/network_metrics.json").then(function(r) { return r.json(); }),
    fetch("data/channels.json").then(function(r) { return r.json(); }),
]).then(function(results) {
    var data = results[0], channels = results[1];
    var nodes = channels.nodes;
    var measures = channels.measures || []; // [[key, label], ...]

    // --- Summary table ---
    var summarySection = document.getElementById("summary-section");
    var h5s = document.createElement("h5"); h5s.className = "mb-2"; h5s.textContent = "Whole-network metrics";
    summarySection.appendChild(h5s);
    var summaryTable = document.createElement("table");
    summaryTable.className = "table table-sm table-hover";
    var sThead = document.createElement("thead"); var sTr = document.createElement("tr");
    ["Metric", "Value"].forEach(function(label, i) {
        var th = document.createElement("th"); th.scope = "col";
        if (i === 1) th.className = "number";
        th.textContent = label; sTr.appendChild(th);
    });
    sThead.appendChild(sTr); summaryTable.appendChild(sThead);
    var sTbody = document.createElement("tbody");
    data.summary_rows.forEach(function(row) {
        var tr = document.createElement("tr");
        var td1 = document.createElement("td"); td1.textContent = row.label;
        var td2 = document.createElement("td"); td2.className = "number"; td2.textContent = row.value;
        tr.appendChild(td1); tr.appendChild(td2); sTbody.appendChild(tr);
    });
    summaryTable.appendChild(sTbody); summarySection.appendChild(summaryTable);
    if (data.wcc_note_visible) {
        var note = document.createElement("p"); note.className = "text-muted small mt-1";
        note.textContent = "* Computed on the largest weakly connected component (undirected)";
        summarySection.appendChild(note);
    }

    // --- Modularity table ---
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
            var td2 = document.createElement("td"); td2.className = "number"; td2.textContent = row.value;
            tr.appendChild(td1); tr.appendChild(td2); mTbody.appendChild(tr);
        });
        modTable.appendChild(mTbody); modSection.appendChild(modTable);
    }

    initSortableTables();

    // --- Dynamic scatter plot ---
    if (measures.length < 2) return;

    var scatterSection = document.getElementById("scatter-section");

    // Build a label lookup
    var labelOf = {};
    measures.forEach(function(m) { labelOf[m[0]] = m[1]; });

    // Controls
    var controls = document.createElement("div");
    controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";

    function makeSelect(id, labelText) {
        var wrap = document.createElement("div");
        var lbl = document.createElement("label"); lbl.className = "form-label mb-1 d-block fw-semibold small"; lbl.htmlFor = id; lbl.textContent = labelText;
        var sel = document.createElement("select"); sel.className = "form-select form-select-sm"; sel.id = id; sel.style.minWidth = "200px";
        measures.forEach(function(m) { sel.appendChild(new Option(m[1], m[0])); });
        wrap.appendChild(lbl); wrap.appendChild(sel);
        controls.appendChild(wrap);
        return sel;
    }

    var xSelect = makeSelect("x-axis-select", "X axis");
    var ySelect = makeSelect("y-axis-select", "Y axis");

    var resetWrap = document.createElement("div"); resetWrap.style.paddingBottom = "2px";
    var resetBtn = document.createElement("button"); resetBtn.className = "btn btn-outline-secondary btn-sm"; resetBtn.textContent = "Reset zoom";
    resetWrap.appendChild(resetBtn); controls.appendChild(resetWrap);

    var countNote = document.createElement("div"); countNote.className = "text-muted small ms-auto"; countNote.style.paddingBottom = "4px";
    controls.appendChild(countNote);

    scatterSection.appendChild(controls);

    // Canvas — full width, fixed height
    var canvasWrap = document.createElement("div"); canvasWrap.style.cssText = "width:100%;height:600px;position:relative;";
    var canvas = document.createElement("canvas"); canvasWrap.appendChild(canvas);
    scatterSection.appendChild(canvasWrap);

    // Default selection: prefer in_deg vs pagerank, else first two
    var defaultX = measures[0][0], defaultY = measures[1][0];
    measures.forEach(function(m) { if (m[0] === "in_deg") defaultX = m[0]; });
    measures.forEach(function(m) { if (m[0] === "pagerank") defaultY = m[0]; });
    if (defaultX === defaultY) defaultY = measures.find(function(m) { return m[0] !== defaultX; })[0];
    xSelect.value = defaultX; ySelect.value = defaultY;

    // Power-law fit in log space
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
});
