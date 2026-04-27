import { build_year_nav } from './year_nav.js';

// ── Hungarian matching (column ordering for cross-tabs) ─────────────────────────
function _hungarianMaxAssign(mat) {
    var nR = mat.length;
    if (!nR) return [];
    var nC = mat[0] ? mat[0].length : 0;
    if (!nC) return new Array(nR).fill(-1);
    var n = Math.max(nR, nC);
    var INF = 1e15;
    var u = new Array(n + 1).fill(0);
    var v = new Array(n + 1).fill(0);
    var p = new Array(n + 1).fill(0);
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
        do { var jPrev = way[j0]; p[j0] = p[jPrev]; j0 = jPrev; } while (j0);
    }
    var ans = new Array(nR).fill(-1);
    for (var j = 1; j <= n; j++) {
        if (p[j] >= 1 && p[j] <= nR && j <= nC) ans[p[j] - 1] = j - 1;
    }
    return ans;
}

function _hungarianColPerm(matrix, nCols) {
    var assign = _hungarianMaxAssign(matrix);
    var used = new Array(nCols).fill(false);
    var perm = [];
    assign.forEach(function(j) { if (j >= 0 && j < nCols && !used[j]) { perm.push(j); used[j] = true; } });
    for (var j = 0; j < nCols; j++) { if (!used[j]) perm.push(j); }
    return perm;
}

// ── Module-level state ─────────────────────────────────────────────────────────
var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d{4,})\//);
var _current_year = _ym ? parseInt(_ym[1]) : "all";
var _base_dd = _ym ? "data/" : _dd;
var _ty = [];
var _cache = {};
var _loading = false;

// ── Data fetching ──────────────────────────────────────────────────────────────
function _fetch_year(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return Promise.all([
        fetch(dd + "communities.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(dd + "meta.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    ]).then(function(res) {
        var d = { data: res[0], meta: res[1] };
        _cache[year] = d;
        return d;
    });
}

// ── Render ─────────────────────────────────────────────────────────────────────
function _render(d) {
    var data = d.data, meta = d.meta;
    var container = document.getElementById("community-tables");
    container.innerHTML = "";
    var strategies = Object.keys(data.strategies);

    // Preamble
    if (meta) {
        var pEl = document.createElement("p"); pEl.className = "table-preamble";
        var parts = ["Network of " + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
        parts.push("Edges represent " + meta.edge_weight_label + "; " + meta.edge_direction + ".");
        if (meta.start_date || meta.end_date)
            parts.push("Data range: " + (meta.start_date || "–") + " to " + (meta.end_date || "present") + ".");
        parts.push("Exported " + meta.export_date + ".");
        pEl.textContent = parts.join(" ");
        container.appendChild(pEl);
    }

    strategies.forEach(function(strategyKey) {
        var stratData = data.strategies[strategyKey];
        var rows = stratData.rows;

        rows.sort(function(a, b) { return (b.node_count || 0) - (a.node_count || 0); });

        rows.forEach(function(r) {
            var total = r.metrics.external_edges + 2 * r.metrics.internal_edges;
            r._ext_frac = total > 0 ? r.metrics.external_edges / total : 0;
        });

        var hmKeys = ["node_count", "internal_edges", "external_edges", "_ext_frac", "density",
                      "reciprocity", "avg_clustering", "avg_path_length", "diameter", "modularity_contribution"];
        var hmRanges = {};
        hmKeys.forEach(function(key) {
            var mn = Infinity, mx = -Infinity, hasVal = false;
            rows.forEach(function(r) {
                var v = key === "node_count" ? r.node_count : key === "_ext_frac" ? r._ext_frac : r.metrics[key];
                if (v !== null && v !== undefined) { if (v < mn) mn = v; if (v > mx) mx = v; hasVal = true; }
            });
            if (hasVal) hmRanges[key] = [mn, mx];
        });

        var hasMod = rows.some(function(r) {
            return r.metrics && r.metrics.modularity_contribution !== null && r.metrics.modularity_contribution !== undefined;
        });

        var COL_DEFS = [
            {key: null,                   label: "Community",               cls: "",       fmt: null,    tip: "Community name and color swatch"},
            {key: "node_count",           label: "Nodes",                   cls: "number", fmt: "int",   tip: "Number of channels in this community"},
            {key: "internal_edges",       label: "Internal Edges",          cls: "number", fmt: "int",   tip: "Directed edges between channels within this community"},
            {key: "external_edges",       label: "Ext. Edges",              cls: "number", fmt: "int",   tip: "Sum of external connections crossing community boundaries (external in-degrees + out-degrees)"},
            {key: "_ext_frac",            label: "Ext. Fraction (0–1)",     cls: "number", fmt: "sig3",  tip: "Share of all connections that cross community boundaries; 0 = isolated cluster, 1 = fully peripheral"},
            {key: "density",              label: "Int. Density (0–1)",      cls: "number", fmt: "sig3",  tip: "Fraction of possible directed within-community edges that exist"},
            {key: "reciprocity",          label: "Reciprocity (0–1)",       cls: "number", fmt: "sig3",  tip: "Proportion of within-community directed edges that are bidirectional"},
            {key: "avg_clustering",       label: "Avg Clustering (0–1)",    cls: "number", fmt: "sig3",  tip: "Mean local clustering coefficient of community nodes"},
            {key: "avg_path_length",      label: "Avg Path Length",         cls: "number", fmt: "sig3",  tip: "Average shortest path in the largest weakly connected component (undirected)"},
            {key: "diameter",             label: "Diameter",                cls: "number", fmt: "int",   tip: "Longest shortest path in the largest weakly connected component (undirected)"},
        ];
        if (hasMod) {
            COL_DEFS.push({
                key: "modularity_contribution", label: "Mod. Contribution", cls: "number", fmt: "sig3",
                tip: "Community's contribution to network modularity (Leicht & Newman 2008 directed formula)",
            });
        }

        var h3 = document.createElement("h3");
        h3.id = "strategy-" + strategyKey;
        h3.className = "mt-4 mb-1";
        h3.textContent = strategyKey.charAt(0).toUpperCase() + strategyKey.slice(1);
        container.appendChild(h3);

        var stratNote = document.createElement("p");
        stratNote.className = "text-muted small mb-2";
        var nComm = rows.length;
        var modStr = (stratData.modularity !== null && stratData.modularity !== undefined)
            ? " Network modularity Q = " + sigFig(stratData.modularity, 3) + "." : "";
        stratNote.textContent = nComm + " " + (nComm === 1 ? "community" : "communities") + "." + modStr
            + " Avg Path Length and Diameter computed on the largest weakly connected component (undirected).";
        container.appendChild(stratNote);

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
                var chip;
                if (ch.url) {
                    chip = document.createElement("a");
                    chip.href = ch.url;
                    chip.target = "_blank";
                    chip.rel = "noopener noreferrer";
                } else {
                    chip = document.createElement("span");
                }
                chip.className = "community-channel-chip";
                chip.textContent = ch.label;
                chipsFrag.appendChild(chip);
            });
            listSpan.appendChild(chipsFrag); group.appendChild(listSpan); details.appendChild(group);
        });
        container.appendChild(details);

        // Organisation × community cross-tab
        var orgCross = stratData.org_cross_tab;
        if (strategyKey !== "ORGANIZATION" && orgCross && orgCross.orgs && orgCross.orgs.length > 1) {
            var crossDetails = document.createElement("details");
            crossDetails.className = "community-channels mt-2 mb-4";
            var crossSummary = document.createElement("summary");
            crossSummary.className = "text-muted small";
            crossSummary.textContent = "Organisation × community distribution";
            crossDetails.appendChild(crossSummary);

            var crossWrapper = document.createElement("div");
            crossWrapper.style.cssText = "display:flex;flex-direction:column;gap:1.5rem;margin-top:.75rem;";

            var colPerm = _hungarianColPerm(orgCross.pct_by_org, orgCross.communities.length);
            var crossComm = colPerm.map(function(j) { return orgCross.communities[j]; });
            var crossColors = colPerm.map(function(j) { return orgCross.comm_colors[j]; });
            function reorderCols(matrix) {
                return matrix.map(function(row) { return colPerm.map(function(j) { return row[j]; }); });
            }
            var crossPctByOrg = reorderCols(orgCross.pct_by_org);
            var crossPctByCommunity = reorderCols(orgCross.pct_by_community);

            var buildCrossTable = function(matrix, tableTitle, tableTooltip) {
                var distThreshold = (meta && meta.community_distribution_threshold != null) ? meta.community_distribution_threshold : 10;
                var visCols = crossComm.reduce(function(acc, _, ci) {
                    if (matrix.some(function(row) { return row[ci] !== null && row[ci] !== undefined && row[ci] >= distThreshold; }))
                        acc.push(ci);
                    return acc;
                }, []);
                var hiddenCount = crossComm.length - visCols.length;
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
                var th0 = document.createElement("th"); th0.scope = "col"; th0.textContent = "Organisation"; htr.appendChild(th0);
                visCols.forEach(function(ci) {
                    var th = document.createElement("th"); th.scope = "col"; th.className = "number";
                    var sw = document.createElement("span");
                    sw.className = "color-swatch color-swatch--sm";
                    sw.style.background = crossColors[ci];
                    sw.setAttribute("aria-hidden", "true");
                    th.appendChild(sw);
                    th.appendChild(document.createTextNode(crossComm[ci]));
                    htr.appendChild(th);
                });
                thead.appendChild(htr); tbl.appendChild(thead);
                var tbody = document.createElement("tbody");
                var frag = document.createDocumentFragment();
                orgCross.orgs.forEach(function(org, oi) {
                    var tr = document.createElement("tr");
                    var tdOrg = document.createElement("td"); tdOrg.textContent = org; tr.appendChild(tdOrg);
                    visCols.forEach(function(ci) {
                        var val = matrix[oi][ci];
                        var td = document.createElement("td"); td.className = "number";
                        if (val !== null && val !== undefined && val >= 5) {
                            td.setAttribute("style", heatmapBg(val, 0, 100));
                            td.textContent = val.toFixed(1) + "%";
                        } else { td.textContent = "—"; }
                        tr.appendChild(td);
                    });
                    frag.appendChild(tr);
                });
                tbody.appendChild(frag); tbl.appendChild(tbody);
                outerDiv.appendChild(tbl);
                if (hiddenCount > 0) {
                    var hiddenNote = document.createElement("p");
                    hiddenNote.className = "small text-muted mt-1 mb-0";
                    hiddenNote.textContent = hiddenCount + " communit" + (hiddenCount === 1 ? "y" : "ies") +
                        " hidden — all values < " + distThreshold + "%.";
                    outerDiv.appendChild(hiddenNote);
                }
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

    initSortableTables();
}

// ── Year switching ─────────────────────────────────────────────────────────────
function _switch_year(year) {
    if (year === _current_year || _loading) return;
    _current_year = year;
    _loading = true;
    build_year_nav(_ty, _current_year, _switch_year);
    _fetch_year(year).then(function(d) { _render(d); _loading = false; }).catch(function() { _loading = false; });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetch(_dd + "communities.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
    fetch(_dd + "meta.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    fetch(_base_dd + "timeline.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
]).then(function(results) {
    _cache[_current_year] = { data: results[0], meta: results[1] };
    var timeline = results[2];
    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_community_html; }) : [];

    _render(_cache[_current_year]);
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);

    // Consensus matrix button — injected once based on full-range meta
    var meta = results[1];
    if (meta && meta.has_consensus_matrix) {
        var nav = document.querySelector(".d-flex.gap-2");
        if (nav) {
            var cmLink = document.createElement("a");
            var _cmpSuffix = (window.DATA_DIR || "").match(/^data_\d{1,3}\/$/) ? "_2" : "";
            cmLink.href = "consensus_matrix" + _cmpSuffix + ".html";
            cmLink.className = "btn btn-outline-secondary btn-sm";
            cmLink.innerHTML = '<i class="bi bi-grid" aria-hidden="true"></i> Consensus matrix';
            nav.insertBefore(cmLink, nav.firstChild);
        }
    }
}).catch(function(err) {
    var el = document.getElementById("community-tables");
    if (el) el.textContent = "Failed to load data.";
    console.error("community_table:", err);
});
