fetch("data/communities.json").then(function(r) { return r.json(); }).then(function(data) {
    var container = document.getElementById("community-tables");
    var strategies = Object.keys(data.strategies);

    strategies.forEach(function(strategyKey) {
        var rows = data.strategies[strategyKey].rows;

        // Heatmap ranges per column
        var hmCols = ["node_count", "internal_edges", "external_edges", "density", "reciprocity", "avg_clustering", "avg_path_length", "diameter"];
        var hmRanges = {};
        hmCols.forEach(function(col) {
            var vals = rows.map(function(r) {
                return col === "node_count" ? r.node_count : r.metrics[col];
            }).filter(function(v) { return v !== null && v !== undefined; });
            if (vals.length) hmRanges[col] = [Math.min.apply(null, vals), Math.max.apply(null, vals)];
        });

        // Heading
        var h3 = document.createElement("h3");
        h3.id = "strategy-" + strategyKey;
        h3.className = "mt-4 mb-3";
        h3.textContent = strategyKey.charAt(0).toUpperCase() + strategyKey.slice(1);
        container.appendChild(h3);

        var note = document.createElement("p");
        note.className = "text-muted small";
        note.textContent = "Avg Path Length and Diameter are computed on the largest weakly connected component (undirected).";
        container.appendChild(note);

        // Table
        var tableDiv = document.createElement("div");
        tableDiv.className = "table-responsive";

        var table = document.createElement("table");
        table.className = "table table-hover table-sm sortable";
        table.setAttribute("aria-labelledby", "strategy-" + strategyKey);

        var thead = document.createElement("thead");
        var htr = document.createElement("tr");
        [
            ["Community", ""], ["Nodes", "number"], ["Internal Edges", "number"],
            ["External Edges", "number"], ["Density", "number"], ["Reciprocity", "number"],
            ["Avg Clustering", "number"], ["Avg Path Length", "number"], ["Diameter", "number"],
        ].forEach(function(h) {
            var th = document.createElement("th");
            th.scope = "col";
            if (h[1]) th.className = h[1];
            th.textContent = h[0];
            htr.appendChild(th);
        });
        thead.appendChild(htr);
        table.appendChild(thead);

        var tbody = document.createElement("tbody");
        rows.forEach(function(row) {
            var tr = document.createElement("tr");

            var nameTd = document.createElement("td");
            nameTd.setAttribute("data-sort-value", row.label);
            var swatch = document.createElement("span");
            swatch.className = "color-swatch color-swatch--lg";
            swatch.style.background = row.hex_color;
            swatch.setAttribute("aria-hidden", "true");
            nameTd.appendChild(swatch);
            nameTd.appendChild(document.createTextNode(row.label));
            tr.appendChild(nameTd);

            function addNumTd(val, col, decimals) {
                var td = document.createElement("td");
                td.className = "number";
                var range = hmRanges[col];
                if (range) td.setAttribute("style", heatmapBg(val, range[0], range[1]));
                var sv = numSortVal(val);
                if (sv) td.setAttribute("data-sort-value", sv);
                td.textContent = fmtNum(val, decimals);
                tr.appendChild(td);
            }

            addNumTd(row.node_count, "node_count", 0);
            addNumTd(row.metrics.internal_edges, "internal_edges", 0);
            addNumTd(row.metrics.external_edges, "external_edges", 0);
            addNumTd(row.metrics.density, "density", 4);
            addNumTd(row.metrics.reciprocity, "reciprocity", 4);
            addNumTd(row.metrics.avg_clustering, "avg_clustering", 4);
            addNumTd(row.metrics.avg_path_length, "avg_path_length", 4);
            addNumTd(row.metrics.diameter, "diameter", 0);

            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        tableDiv.appendChild(table);
        container.appendChild(tableDiv);

        // Channel list
        var details = document.createElement("details");
        details.className = "community-channels mt-2 mb-4";
        var summary = document.createElement("summary");
        summary.className = "text-muted small";
        summary.textContent = "Channel list";
        details.appendChild(summary);

        rows.forEach(function(row) {
            if (!row.channels || !row.channels.length) return;
            var group = document.createElement("div");
            group.className = "community-channels-group mt-2";

            var labelSpan = document.createElement("span");
            labelSpan.className = "community-channels-label";
            var labelSwatch = document.createElement("span");
            labelSwatch.className = "color-swatch color-swatch--sm";
            labelSwatch.style.background = row.hex_color;
            labelSwatch.setAttribute("aria-hidden", "true");
            labelSpan.appendChild(labelSwatch);
            labelSpan.appendChild(document.createTextNode(row.label));
            group.appendChild(labelSpan);

            var listSpan = document.createElement("span");
            listSpan.className = "community-channels-list";
            row.channels.forEach(function(ch) {
                var a = document.createElement("a");
                a.href = ch.url || "#";
                a.className = "community-channel-chip";
                a.textContent = ch.label;
                listSpan.appendChild(a);
            });
            group.appendChild(listSpan);
            details.appendChild(group);
        });

        container.appendChild(details);
    });

    initSortableTables();
});
