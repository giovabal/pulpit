Promise.all([
    fetch((window.DATA_DIR||"data/")+"communities.json").then(function(r) { return r.json(); }),
    fetch((window.DATA_DIR||"data/")+"meta.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
]).then(function(results) {
    var data = results[0], meta = results[1];
    var container = document.getElementById("community-tables");
    var strategies = Object.keys(data.strategies);

    // Preamble (proposal 16)
    if (meta) {
        var pEl = document.createElement("p"); pEl.className = "table-preamble";
        var parts = ["Network of " + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
        parts.push("Edges represent " + meta.edge_weight_label + "; " + meta.edge_direction + ".");
        if (meta.start_date || meta.end_date) {
            parts.push("Data range: " + (meta.start_date || "\u2013") + " to " + (meta.end_date || "present") + ".");
        }
        parts.push("Exported " + meta.export_date + ".");
        pEl.textContent = parts.join(" ");
        container.appendChild(pEl);
    }

    strategies.forEach(function(strategyKey) {
        var stratData = data.strategies[strategyKey];
        var rows = stratData.rows;

        // Default sort by node_count descending (proposal 14)
        rows.sort(function(a, b) { return (b.node_count || 0) - (a.node_count || 0); });

        // Pre-compute external fraction for each row (proposal 13)
        rows.forEach(function(r) {
            var total = r.metrics.external_edges + 2 * r.metrics.internal_edges;
            r._ext_frac = total > 0 ? r.metrics.external_edges / total : 0;
        });

        // Heatmap ranges
        var hmKeys = ["node_count", "internal_edges", "external_edges", "_ext_frac", "density",
                      "reciprocity", "avg_clustering", "avg_path_length", "diameter", "modularity_contribution"];
        var hmRanges = {};
        hmKeys.forEach(function(key) {
            var mn = Infinity, mx = -Infinity, hasVal = false;
            rows.forEach(function(r) {
                var v = key === "node_count" ? r.node_count : key === "_ext_frac" ? r._ext_frac : r.metrics[key];
                if (v !== null && v !== undefined) {
                    if (v < mn) mn = v; if (v > mx) mx = v; hasVal = true;
                }
            });
            if (hasVal) hmRanges[key] = [mn, mx];
        });

        // Check if any row has modularity_contribution
        var hasMod = rows.some(function(r) {
            return r.metrics && r.metrics.modularity_contribution !== null && r.metrics.modularity_contribution !== undefined;
        });

        // Column definitions (proposals 12, 13, 15, 18)
        var COL_DEFS = [
            {key: null,                   label: "Community",              cls: "",       fmt: null,      tip: "Community name and color swatch"},
            {key: "node_count",           label: "Nodes",                  cls: "number", fmt: "int",     tip: "Number of channels in this community"},
            {key: "internal_edges",       label: "Internal Edges",         cls: "number", fmt: "int",     tip: "Directed edges between channels within this community"},
            {key: "external_edges",       label: "Ext. Edges",             cls: "number", fmt: "int",     tip: "Sum of external connections crossing community boundaries (external in-degrees + out-degrees)"},
            {key: "_ext_frac",            label: "Ext. Fraction (0\u20131)", cls: "number", fmt: "sig3", tip: "Share of all connections that cross community boundaries; 0 = isolated cluster, 1 = fully peripheral"},
            {key: "density",              label: "Int. Density (0\u20131)", cls: "number", fmt: "sig3",   tip: "Fraction of possible directed within-community edges that exist"},
            {key: "reciprocity",          label: "Reciprocity (0\u20131)",  cls: "number", fmt: "sig3",   tip: "Proportion of within-community directed edges that are bidirectional"},
            {key: "avg_clustering",       label: "Avg Clustering (0\u20131)", cls: "number", fmt: "sig3", tip: "Mean local clustering coefficient of community nodes"},
            {key: "avg_path_length",      label: "Avg Path Length",        cls: "number", fmt: "sig3",   tip: "Average shortest path in the largest weakly connected component (undirected)"},
            {key: "diameter",             label: "Diameter",               cls: "number", fmt: "int",    tip: "Longest shortest path in the largest weakly connected component (undirected)"},
        ];
        if (hasMod) {
            COL_DEFS.push({
                key: "modularity_contribution", label: "Mod. Contribution", cls: "number", fmt: "sig3",
                tip: "Community\u2019s contribution to network modularity (Leicht \u0026 Newman 2008 directed formula)",
            });
        }

        // Heading
        var h3 = document.createElement("h3");
        h3.id = "strategy-" + strategyKey;
        h3.className = "mt-4 mb-1";
        h3.textContent = strategyKey.charAt(0).toUpperCase() + strategyKey.slice(1);
        container.appendChild(h3);

        var stratNote = document.createElement("p");
        stratNote.className = "text-muted small mb-2";
        var nComm = rows.length;
        var modStr = (stratData.modularity !== null && stratData.modularity !== undefined)
            ? " Network modularity Q\u2009=\u2009" + sigFig(stratData.modularity, 3) + "." : "";
        stratNote.textContent = nComm + " " + (nComm === 1 ? "community" : "communities") + "." + modStr
            + " Avg Path Length and Diameter computed on the largest weakly connected component (undirected).";
        container.appendChild(stratNote);

        // Table
        var tableDiv = document.createElement("div"); tableDiv.className = "table-responsive";
        var table = document.createElement("table");
        table.className = "table table-hover table-sm sortable";
        table.setAttribute("aria-labelledby", "strategy-" + strategyKey);

        var thead = document.createElement("thead");
        var htr = document.createElement("tr");
        COL_DEFS.forEach(function(col) {
            var th = document.createElement("th"); th.scope = "col";
            if (col.cls) th.className = col.cls;
            th.textContent = col.label;
            if (col.tip) th.title = col.tip;
            htr.appendChild(th);
        });
        thead.appendChild(htr); table.appendChild(thead);

        var tbody = document.createElement("tbody");
        var tbodyFrag = document.createDocumentFragment();
        rows.forEach(function(row) {
            var tr = document.createElement("tr");

            function getVal(col) {
                if (col.key === null) return null;
                if (col.key === "node_count") return row.node_count;
                if (col.key === "_ext_frac") return row._ext_frac;
                return row.metrics[col.key];
            }

            COL_DEFS.forEach(function(col) {
                if (col.key === null) {
                    // Community name cell
                    var nameTd = document.createElement("td");
                    nameTd.setAttribute("data-sort-value", row.label);
                    var swatch = document.createElement("span");
                    swatch.className = "color-swatch color-swatch--lg";
                    swatch.style.background = row.hex_color;
                    swatch.setAttribute("aria-hidden", "true");
                    nameTd.appendChild(swatch);
                    nameTd.appendChild(document.createTextNode(row.label));
                    tr.appendChild(nameTd);
                    return;
                }
                var val = getVal(col);
                var td = document.createElement("td"); td.className = "number";
                var range = hmRanges[col.key];
                if (range) td.setAttribute("style", heatmapBg(val, range[0], range[1]));
                var sv = numSortVal(val); if (sv) td.setAttribute("data-sort-value", sv);
                td.textContent = col.fmt === "int" ? fmtInt(val) : sigFig(val, 3);
                tr.appendChild(td);
            });

            tbodyFrag.appendChild(tr);
        });
        tbody.appendChild(tbodyFrag);
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
            var group = document.createElement("div"); group.className = "community-channels-group mt-2";
            var labelSpan = document.createElement("span"); labelSpan.className = "community-channels-label";
            var labelSwatch = document.createElement("span");
            labelSwatch.className = "color-swatch color-swatch--sm"; labelSwatch.style.background = row.hex_color;
            labelSwatch.setAttribute("aria-hidden", "true");
            labelSpan.appendChild(labelSwatch); labelSpan.appendChild(document.createTextNode(row.label));
            group.appendChild(labelSpan);
            var listSpan = document.createElement("span"); listSpan.className = "community-channels-list";
            var chipsFrag = document.createDocumentFragment();
            row.channels.forEach(function(ch) {
                var a = document.createElement("a"); a.href = ch.url || "#";
                a.className = "community-channel-chip"; a.textContent = ch.label;
                chipsFrag.appendChild(a);
            });
            listSpan.appendChild(chipsFrag); group.appendChild(listSpan); details.appendChild(group);
        });

        container.appendChild(details);

        // Organisation × community cross-tab (skip for ORGANIZATION strategy: it is trivially org×org)
        var orgCross = stratData.org_cross_tab;
        if (strategyKey !== "ORGANIZATION" && orgCross && orgCross.orgs && orgCross.orgs.length > 1) {
            var crossDetails = document.createElement("details");
            crossDetails.className = "community-channels mt-2 mb-4";
            var crossSummary = document.createElement("summary");
            crossSummary.className = "text-muted small";
            crossSummary.textContent = "Organisation \u00d7 community distribution";
            crossDetails.appendChild(crossSummary);

            var crossWrapper = document.createElement("div");
            crossWrapper.style.cssText = "display:flex;flex-direction:column;gap:1.5rem;margin-top:.75rem;";

            var buildCrossTable = function(matrix, tableTitle, tableTooltip) {
                var outerDiv = document.createElement("div");
                outerDiv.style.cssText = "overflow-x:auto;";
                var titleP = document.createElement("p");
                titleP.className = "small fw-semibold mb-1";
                titleP.title = tableTooltip;
                titleP.textContent = tableTitle;
                outerDiv.appendChild(titleP);
                var tbl = document.createElement("table");
                tbl.className = "table table-sm table-hover";
                tbl.style.cssText = "font-size:.8rem;white-space:nowrap;";
                var thead = document.createElement("thead");
                var htr = document.createElement("tr");
                var th0 = document.createElement("th"); th0.textContent = "Organisation"; htr.appendChild(th0);
                orgCross.communities.forEach(function(commLabel, ci) {
                    var th = document.createElement("th"); th.className = "number";
                    var sw = document.createElement("span");
                    sw.className = "color-swatch color-swatch--sm";
                    sw.style.background = orgCross.comm_colors[ci];
                    sw.setAttribute("aria-hidden", "true");
                    th.appendChild(sw);
                    th.appendChild(document.createTextNode(commLabel));
                    htr.appendChild(th);
                });
                thead.appendChild(htr); tbl.appendChild(thead);
                var tbody = document.createElement("tbody");
                var frag = document.createDocumentFragment();
                orgCross.orgs.forEach(function(org, oi) {
                    var tr = document.createElement("tr");
                    var tdOrg = document.createElement("td"); tdOrg.textContent = org; tr.appendChild(tdOrg);
                    matrix[oi].forEach(function(val) {
                        var td = document.createElement("td"); td.className = "number";
                        if (val !== null && val !== undefined) {
                            td.setAttribute("style", heatmapBg(val, 0, 100));
                            td.textContent = val.toFixed(1) + "%";
                        } else {
                            td.textContent = "\u2014";
                        }
                        tr.appendChild(td);
                    });
                    frag.appendChild(tr);
                });
                tbody.appendChild(frag); tbl.appendChild(tbody);
                outerDiv.appendChild(tbl);
                return outerDiv;
            };

            crossWrapper.appendChild(buildCrossTable(
                orgCross.pct_by_org,
                "% of organisation nodes per community",
                "For each organisation: share of its nodes assigned to each community. Rows sum to 100%."
            ));
            crossWrapper.appendChild(buildCrossTable(
                orgCross.pct_by_community,
                "% of community nodes per organisation",
                "For each community: share of its nodes coming from each organisation. Columns sum to 100%."
            ));

            crossDetails.appendChild(crossWrapper);
            container.appendChild(crossDetails);
        }
    });

    initSortableTables();
});
