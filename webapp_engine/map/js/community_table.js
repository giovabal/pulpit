function _hungarianMaxAssign(mat) {
    // Optimal maximum-weight assignment for a rectangular matrix (rows × cols).
    // Returns col index (0-based) for each row; -1 if the row is unmatched (nR > nC).
    var nR = mat.length;
    if (!nR) return [];
    var nC = mat[0] ? mat[0].length : 0;
    if (!nC) return new Array(nR).fill(-1);
    var n = Math.max(nR, nC);
    var INF = 1e15;
    var u = new Array(n + 1).fill(0);
    var v = new Array(n + 1).fill(0);
    var p = new Array(n + 1).fill(0);   // p[j] = row (1-indexed) assigned to col j
    var way = new Array(n + 1).fill(0);
    function getCost(i, j) {
        return (i < nR && j < nC && mat[i][j] != null) ? -mat[i][j] : 0;
    }
    for (var row = 1; row <= n; row++) {
        p[0] = row;
        var j0 = 0;
        var minVal = new Array(n + 1).fill(INF);
        var used = new Array(n + 1).fill(false);
        do {
            used[j0] = true;
            var i0 = p[j0], delta = INF, j1 = 0;
            for (var j = 1; j <= n; j++) {
                if (!used[j]) {
                    var cur = getCost(i0 - 1, j - 1) - u[i0] - v[j];
                    if (cur < minVal[j]) { minVal[j] = cur; way[j] = j0; }
                    if (minVal[j] < delta) { delta = minVal[j]; j1 = j; }
                }
            }
            for (var jj = 0; jj <= n; jj++) {
                if (used[jj]) { u[p[jj]] += delta; v[jj] -= delta; }
                else { minVal[jj] -= delta; }
            }
            j0 = j1;
        } while (p[j0] !== 0);
        do {
            var jPrev = way[j0];
            p[j0] = p[jPrev];
            j0 = jPrev;
        } while (j0);
    }
    var ans = new Array(nR).fill(-1);
    for (var j = 1; j <= n; j++) {
        if (p[j] >= 1 && p[j] <= nR && j <= nC) ans[p[j] - 1] = j - 1;
    }
    return ans;
}

function _hungarianColPerm(matrix, nCols) {
    // Column permutation that puts Hungarian-assigned cols first (in row order),
    // then any unassigned cols, for near-diagonal table layout.
    var assign = _hungarianMaxAssign(matrix);
    var used = new Array(nCols).fill(false);
    var perm = [];
    assign.forEach(function(j) {
        if (j >= 0 && j < nCols && !used[j]) { perm.push(j); used[j] = true; }
    });
    for (var j = 0; j < nCols; j++) { if (!used[j]) perm.push(j); }
    return perm;
}

function _pluralityComm(label, stratMaps, stratKeys) {
    // Most-frequent community assignment for a channel across the given strategies.
    var counts = {};
    stratKeys.forEach(function(sk) {
        var comm = stratMaps[sk] && stratMaps[sk][label];
        if (comm != null) counts[comm] = (counts[comm] || 0) + 1;
    });
    var best = "", bestN = 0;
    Object.keys(counts).forEach(function(c) { if (counts[c] > bestN) { best = c; bestN = counts[c]; } });
    return best;
}

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

            // Reorder columns via Hungarian algorithm for near-diagonal legibility
            var colPerm = _hungarianColPerm(orgCross.pct_by_org, orgCross.communities.length);
            var crossComm = colPerm.map(function(j) { return orgCross.communities[j]; });
            var crossColors = colPerm.map(function(j) { return orgCross.comm_colors[j]; });
            function reorderCols(matrix) {
                return matrix.map(function(row) { return colPerm.map(function(j) { return row[j]; }); });
            }
            var crossPctByOrg = reorderCols(orgCross.pct_by_org);
            var crossPctByCommunity = reorderCols(orgCross.pct_by_community);

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
                crossComm.forEach(function(commLabel, ci) {
                    var th = document.createElement("th"); th.className = "number";
                    var sw = document.createElement("span");
                    sw.className = "color-swatch color-swatch--sm";
                    sw.style.background = crossColors[ci];
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
                        if (val !== null && val !== undefined && val >= 5) {
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
                crossPctByOrg,
                "% of organisation nodes per community",
                "For each organisation: share of its nodes assigned to each community. Rows sum to 100%."
            ));
            crossWrapper.appendChild(buildCrossTable(
                crossPctByCommunity,
                "% of community nodes per organisation",
                "For each community: share of its nodes coming from each organisation. Columns sum to 100%."
            ));

            crossDetails.appendChild(crossWrapper);
            container.appendChild(crossDetails);
        }
    });

    // ── Consensus matrix ────────────────────────────────────────────────────────
    (function () {
        var nonOrgKeys = strategies.filter(function(s) { return s !== "ORGANIZATION"; });
        if (nonOrgKeys.length < 2) return;

        // Build channel-label → community-label map per strategy
        var stratMaps = {};
        var labelSet  = {};
        nonOrgKeys.forEach(function(sk) {
            var sd = data.strategies[sk];
            if (!sd || !sd.rows) return;
            var map = {};
            sd.rows.forEach(function(row) {
                (row.channels || []).forEach(function(ch) {
                    map[ch.label] = row.label;
                    labelSet[ch.label] = true;
                });
            });
            stratMaps[sk] = map;
        });

        var channelList = Object.keys(labelSet);

        // Sort by plurality community across non-ORGANIZATION strategies, then name
        var pComm = {};
        channelList.forEach(function(lbl) { pComm[lbl] = _pluralityComm(lbl, stratMaps, nonOrgKeys); });
        channelList.sort(function(a, b) {
            if (pComm[a] !== pComm[b]) return pComm[a].localeCompare(pComm[b]);
            return a.localeCompare(b);
        });

        var n        = channelList.length;
        var maxCount = nonOrgKeys.length;

        // Index map
        var chanIdx = {};
        channelList.forEach(function(lbl, i) { chanIdx[lbl] = i; });

        // Consensus matrix — diagonal stays 0 (not rendered)
        var consensus = [];
        for (var ci = 0; ci < n; ci++) consensus.push(new Int16Array(n));
        nonOrgKeys.forEach(function(sk) {
            var sd = data.strategies[sk];
            if (!sd || !sd.rows) return;
            sd.rows.forEach(function(row) {
                var members = [];
                (row.channels || []).forEach(function(ch) {
                    var ix = chanIdx[ch.label];
                    if (ix !== undefined) members.push(ix);
                });
                for (var a = 0; a < members.length; a++) {
                    for (var b = a + 1; b < members.length; b++) {
                        consensus[members[a]][members[b]]++;
                        consensus[members[b]][members[a]]++;
                    }
                }
            });
        });

        // ── Render ──────────────────────────────────────────────────────────────
        var cellSize = Math.max(6, Math.min(16, Math.floor(520 / n)));
        var labelW   = 140;
        var topPad   = 110;
        var maxR     = cellSize / 2 - 0.5;
        var fontSize = Math.max(7, Math.min(11, cellSize - 1));
        var FILL     = "#4a85c0";
        var FILL_MAX = "#1a5496";
        var NS       = "http://www.w3.org/2000/svg";

        var h3 = document.createElement("h3");
        h3.id = "consensus-matrix"; h3.className = "mt-5 mb-1";
        h3.textContent = "Consensus matrix";
        container.appendChild(h3);

        var note = document.createElement("p");
        note.className = "text-muted small mb-2";
        note.textContent = n + " \u00d7 " + n + " channels \u2014 " +
            maxCount + " partition" + (maxCount !== 1 ? "s" : "") +
            " compared (ORGANIZATION excluded). Balloon area \u221d agreement count; diagonal omitted.";
        container.appendChild(note);

        // Legend
        var legendDiv = document.createElement("div");
        legendDiv.className = "mb-3";
        legendDiv.style.cssText = "display:flex;align-items:center;gap:10px;font-size:11px;color:#555;";
        legendDiv.appendChild(document.createTextNode("Agreement\u00a0\u2192"));
        for (var k = 1; k <= maxCount; k++) {
            var r  = Math.max(1, maxR * Math.sqrt(k / maxCount));
            var diam = maxR * 2 + 2;
            var svgL = document.createElementNS(NS, "svg");
            svgL.setAttribute("width", diam); svgL.setAttribute("height", diam);
            svgL.style.cssText = "vertical-align:middle;flex-shrink:0;";
            var cL = document.createElementNS(NS, "circle");
            cL.setAttribute("cx", maxR + 1); cL.setAttribute("cy", maxR + 1); cL.setAttribute("r", r);
            cL.setAttribute("fill", k === maxCount ? FILL_MAX : FILL); cL.setAttribute("opacity", "0.8");
            svgL.appendChild(cL); legendDiv.appendChild(svgL);
            legendDiv.appendChild(document.createTextNode(k + "/" + maxCount));
        }
        container.appendChild(legendDiv);

        // Tooltip
        var tip = document.createElement("div");
        tip.style.cssText = "position:fixed;background:rgba(0,0,0,.78);color:#fff;font-size:11px;" +
            "padding:3px 8px;border-radius:3px;pointer-events:none;display:none;z-index:9999;white-space:nowrap;";
        document.body.appendChild(tip);
        function showTip(e, txt) {
            tip.textContent = txt; tip.style.display = "block";
            tip.style.left = (e.clientX + 14) + "px"; tip.style.top = (e.clientY - 30) + "px";
        }
        function moveTip(e) {
            tip.style.left = (e.clientX + 14) + "px"; tip.style.top = (e.clientY - 30) + "px";
        }
        function hideTip() { tip.style.display = "none"; }

        // SVG
        var scrollDiv = document.createElement("div");
        scrollDiv.style.cssText = "overflow-x:auto;";
        var svgW = labelW + n * cellSize;
        var svgH = topPad + n * cellSize;
        var svg = document.createElementNS(NS, "svg");
        svg.setAttribute("width", svgW); svg.setAttribute("height", svgH);
        svg.style.cssText = "display:block;";

        // Grid lines
        var gridG = document.createElementNS(NS, "g");
        gridG.setAttribute("stroke", "#e4e4e4"); gridG.setAttribute("stroke-width", "0.5");
        for (var gi = 0; gi <= n; gi++) {
            var hl = document.createElementNS(NS, "line");
            hl.setAttribute("x1", labelW); hl.setAttribute("y1", topPad + gi * cellSize);
            hl.setAttribute("x2", labelW + n * cellSize); hl.setAttribute("y2", topPad + gi * cellSize);
            gridG.appendChild(hl);
            var vl = document.createElementNS(NS, "line");
            vl.setAttribute("x1", labelW + gi * cellSize); vl.setAttribute("y1", topPad);
            vl.setAttribute("x2", labelW + gi * cellSize); vl.setAttribute("y2", topPad + n * cellSize);
            gridG.appendChild(vl);
        }
        svg.appendChild(gridG);

        // Diagonal shading
        var diagG = document.createElementNS(NS, "g");
        diagG.setAttribute("fill", "#f2f2f2");
        for (var di = 0; di < n; di++) {
            var dr = document.createElementNS(NS, "rect");
            dr.setAttribute("x", labelW + di * cellSize); dr.setAttribute("y", topPad + di * cellSize);
            dr.setAttribute("width", cellSize); dr.setAttribute("height", cellSize);
            diagG.appendChild(dr);
        }
        svg.appendChild(diagG);

        // Row labels
        channelList.forEach(function(lbl, i) {
            var tx = document.createElementNS(NS, "text");
            tx.setAttribute("x", labelW - 4);
            tx.setAttribute("y", topPad + i * cellSize + cellSize / 2);
            tx.setAttribute("dy", "0.35em"); tx.setAttribute("text-anchor", "end");
            tx.setAttribute("font-size", fontSize); tx.setAttribute("fill", "#333");
            var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "\u2026" : lbl;
            tx.textContent = trunc;
            if (trunc !== lbl) { var ttl = document.createElementNS(NS, "title"); ttl.textContent = lbl; tx.appendChild(ttl); }
            svg.appendChild(tx);
        });

        // Column labels (rotated −45°)
        channelList.forEach(function(lbl, j) {
            var cx = labelW + j * cellSize + cellSize / 2;
            var cy = topPad - 4;
            var tx = document.createElementNS(NS, "text");
            tx.setAttribute("x", cx); tx.setAttribute("y", cy);
            tx.setAttribute("text-anchor", "start");
            tx.setAttribute("font-size", fontSize); tx.setAttribute("fill", "#333");
            tx.setAttribute("transform", "rotate(-45 " + cx + " " + cy + ")");
            var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "\u2026" : lbl;
            tx.textContent = trunc;
            if (trunc !== lbl) { var ttl = document.createElementNS(NS, "title"); ttl.textContent = lbl; tx.appendChild(ttl); }
            svg.appendChild(tx);
        });

        // Balloons
        var circleG = document.createElementNS(NS, "g");
        for (var ri = 0; ri < n; ri++) {
            for (var rj = 0; rj < n; rj++) {
                if (ri === rj) continue;
                var cnt = consensus[ri][rj];
                if (cnt === 0) continue;
                var ccx  = labelW + rj * cellSize + cellSize / 2;
                var ccy  = topPad + ri * cellSize + cellSize / 2;
                var cr   = Math.max(0.5, maxR * Math.sqrt(cnt / maxCount));
                var circ = document.createElementNS(NS, "circle");
                circ.setAttribute("cx", ccx); circ.setAttribute("cy", ccy); circ.setAttribute("r", cr);
                circ.setAttribute("fill", cnt === maxCount ? FILL_MAX : FILL);
                circ.setAttribute("opacity", "0.8");
                (function(lA, lB, c) {
                    circ.addEventListener("mouseenter", function(e) {
                        showTip(e, lA + " \u00d7 " + lB + ": " + c + "/" + maxCount + " partitions agree");
                    });
                    circ.addEventListener("mousemove", moveTip);
                })(channelList[ri], channelList[rj], cnt);
                circleG.appendChild(circ);
            }
        }
        circleG.addEventListener("mouseleave", hideTip);
        svg.appendChild(circleG);

        scrollDiv.appendChild(svg);
        container.appendChild(scrollDiv);
    })();

    initSortableTables();
});
