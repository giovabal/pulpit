fetch("data/network_metrics.json").then(function(r) { return r.json(); }).then(function(data) {
    // Summary table
    var summarySection = document.getElementById("summary-section");
    var h5s = document.createElement("h5");
    h5s.className = "mb-2";
    h5s.textContent = "Whole-network metrics";
    summarySection.appendChild(h5s);

    var summaryTable = document.createElement("table");
    summaryTable.className = "table table-sm table-hover sortable";
    var sThead = document.createElement("thead");
    var sTr = document.createElement("tr");
    ["Metric", "Value"].forEach(function(label, i) {
        var th = document.createElement("th");
        th.scope = "col";
        if (i === 1) th.className = "number";
        th.textContent = label;
        sTr.appendChild(th);
    });
    sThead.appendChild(sTr);
    summaryTable.appendChild(sThead);

    var sTbody = document.createElement("tbody");
    data.summary_rows.forEach(function(row) {
        var tr = document.createElement("tr");
        var td1 = document.createElement("td");
        td1.textContent = row.label;
        var td2 = document.createElement("td");
        td2.className = "number";
        td2.textContent = row.value;
        tr.appendChild(td1);
        tr.appendChild(td2);
        sTbody.appendChild(tr);
    });
    summaryTable.appendChild(sTbody);
    summarySection.appendChild(summaryTable);

    if (data.wcc_note_visible) {
        var note = document.createElement("p");
        note.className = "text-muted small mt-1";
        note.textContent = "* Computed on the largest weakly connected component (undirected)";
        summarySection.appendChild(note);
    }

    // Modularity table
    if (data.modularity_rows && data.modularity_rows.length) {
        var modSection = document.getElementById("modularity-section");
        modSection.classList.remove("d-none");

        var h5m = document.createElement("h5");
        h5m.className = "mb-2";
        h5m.textContent = "Modularity by strategy";
        modSection.appendChild(h5m);

        var modTable = document.createElement("table");
        modTable.className = "table table-sm table-hover sortable";
        var mThead = document.createElement("thead");
        var mTr = document.createElement("tr");
        ["Strategy", "Modularity"].forEach(function(label, i) {
            var th = document.createElement("th");
            th.scope = "col";
            if (i === 1) th.className = "number";
            th.textContent = label;
            mTr.appendChild(th);
        });
        mThead.appendChild(mTr);
        modTable.appendChild(mThead);

        var mTbody = document.createElement("tbody");
        data.modularity_rows.forEach(function(row) {
            var tr = document.createElement("tr");
            var td1 = document.createElement("td");
            td1.textContent = row.strategy;
            var td2 = document.createElement("td");
            td2.className = "number";
            td2.textContent = row.value;
            tr.appendChild(td1);
            tr.appendChild(td2);
            mTbody.appendChild(tr);
        });
        modTable.appendChild(mTbody);
        modSection.appendChild(modTable);
    }

    initSortableTables();
});
