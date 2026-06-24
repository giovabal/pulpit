import { build_year_nav } from './year_nav.js';
import { fetchJson, fetchJsonOrNull } from './utils.js';
import { strategy_label as _strat_label, canonical_strategy_key } from './labels.js';
import { build_community_alluvial, build_strategy_intersection_sankey } from './community_alluvial.js';
import { render_partition_comparison } from './partition_comparison.js';

// Mirrors network.community.UNDIRECTED_BASIS_STRATEGIES — strategies optimised on the undirected
// W+Wᵀ projection, whose modularity (and per-community contributions) community_stats.py computes
// with the undirected null model rather than the directed Leicht & Newman one.
var UNDIRECTED_BASIS_STRATEGIES = ['leiden', 'leiden_cpm', 'louvain', 'labelpropagation', 'kcore'];

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
    for (var k = 1; k <= n; k++) {
        if (p[k] >= 1 && p[k] <= nR && k <= nC) ans[p[k] - 1] = k - 1;
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
// All timeline years' communities.json, [{year, data}] ascending — backs the per-strategy
// community-flow alluvials, which need every year at once (the per-year/All views load one year).
var _yearComms = null;
var _yearCommsLoading = false;
// Alluvial sections currently mounted (strategyKey -> element), so a window resize can re-fit them to
// the new page width without rebuilding the whole table (which would reset sorting and expanded panels).
var _alluvialEls = {};
var _resizeTimer = null;
// Redraw closure for the standalone strategy-intersection Sankey at the foot of the page (set once it
// is built), so a window resize can re-fit it to the new page width.
var _redrawStrategySankey = null;
// Per-year network_metrics.json cache (backs the Partition comparison matrices, which live in that
// file alongside the whole-network stats).
var _nmCache = {};
// Full-range channels.json nodes keyed by id (the union of every year's channels), loaded once at
// init. Enriches the alluvial/Sankey click-to-list channel cards (avatar, org, message/fan counts,
// activity span). Empty until loaded; the cards fall back to the ribbon's own {label, url}.
var _nodeById = {};

// ── Data fetching ──────────────────────────────────────────────────────────────
function _fetch_year(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return Promise.all([
        fetchJson(dd + "communities.json"),
        fetchJsonOrNull(dd + "meta.json"),
    ]).then(function(res) {
        var d = { data: res[0], meta: res[1] };
        _cache[year] = d;
        return d;
    });
}

// Load every timeline year's communities.json once, then (if the full-range view is showing) re-render
// so the alluvials appear. No-op without a ≥2-year timeline.
function _load_year_comms() {
    if (_yearComms || _yearCommsLoading || _ty.length < 2) return;
    _yearCommsLoading = true;
    var years = _ty.map(function(y) { return y.year; }).sort(function(a, b) { return a - b; });
    Promise.all(years.map(function(yr) {
        return fetchJson("data_" + yr + "/communities.json")
            .then(function(d) { return { year: yr, data: d }; })
            .catch(function() { return null; });
    })).then(function(list) {
        _yearComms = list.filter(Boolean);
        _yearCommsLoading = false;
        if (_current_year === "all" && _cache["all"]) _render(_cache["all"]);
    });
}

// Re-fit the mounted alluvials to the current page width (after a window resize). Only the SVGs are
// rebuilt — the tables, their sort order, and any expanded panels are left untouched.
function _refit_alluvials() {
    if (_current_year !== "all" || !_yearComms) return;
    var container = document.getElementById("community-tables");
    if (!container) return;
    Object.keys(_alluvialEls).forEach(function(sk) {
        var old = _alluvialEls[sk];
        if (!old || !old.parentNode) return;
        // Carry an open channel-list panel across the rebuild by re-selecting the same ribbon, so a
        // resize no longer silently closes it (honouring this function's "expanded panels untouched").
        var openKey = old.alluvialSelectedKey ? old.alluvialSelectedKey() : null;
        var fresh = build_community_alluvial(sk, _yearComms, container.clientWidth, _nodeById, openKey);
        if (fresh) { old.replaceWith(fresh); _alluvialEls[sk] = fresh; }
    });
}

window.addEventListener("resize", function() {
    if (_resizeTimer) clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(function() {
        _refit_alluvials();
        if (_redrawStrategySankey) _redrawStrategySankey();
    }, 200);
});

// ── Partition comparison (ARI / AMI / NMI / VI matrices, with a year selector) ───
// Loads the partition_comparison block from network_metrics.json for the chosen year ("all" = the
// full-range partition). Each timeline year has its own network_metrics.json, so the selector simply
// swaps which one is rendered.
function _fetch_network_metrics(year) {
    if (year in _nmCache) return Promise.resolve(_nmCache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return fetchJsonOrNull(dd + "network_metrics.json").then(function(d) { _nmCache[year] = d; return d; });
}

function _build_partition_comparison_section() {
    var section = document.getElementById("partition-comparison");
    if (!section) return;
    _fetch_network_metrics("all").then(function(nm) {
        var pc = nm && nm.partition_comparison;
        if (!pc || !pc.strategies || pc.strategies.length < 2) return;  // nothing comparable → stay empty
        section.innerHTML = "";

        var h3 = document.createElement("h3");
        h3.className = "mt-4 mb-1";
        h3.textContent = "Partition comparison";
        section.appendChild(h3);
        var intro = document.createElement("p");
        intro.className = "text-muted small mb-3";
        intro.textContent = "Pairwise agreement between every community strategy and every label-group "
            + "partition, under four standard clustering-comparison indices. Each pair is scored on the "
            + "channels assigned by both partitions. Read a label-group row against the algorithmic "
            + "strategies to see how closely the analyst's manual grouping matches the structural communities.";
        section.appendChild(intro);

        var body = document.createElement("div");
        body.id = "partition-comparison-body";

        if (_ty.length) {
            var controls = document.createElement("div");
            controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";
            var wrap = document.createElement("div");
            var lbl = document.createElement("label");
            lbl.className = "form-label mb-1 d-block fw-semibold small";
            var selYear = document.createElement("select");
            selYear.className = "form-select form-select-sm"; selYear.style.width = "auto";
            selYear.id = "partition-comparison-year";
            lbl.htmlFor = selYear.id; lbl.textContent = "Year";
            [{ value: "all", label: "All years" }].concat(
                _ty.map(function(y) { return { value: String(y.year), label: String(y.year) }; })
            ).forEach(function(o) { selYear.appendChild(new Option(o.label, o.value)); });
            wrap.appendChild(lbl); wrap.appendChild(selYear); controls.appendChild(wrap);
            section.appendChild(controls);
            selYear.addEventListener("change", function() {
                var year = (selYear.value === "all") ? "all" : parseInt(selYear.value);
                _fetch_network_metrics(year).then(function(d) {
                    if (String(selYear.value) !== String(year)) return;  // superseded by a newer selection
                    render_partition_comparison(body, d && d.partition_comparison);
                });
            });
        }

        section.appendChild(body);
        render_partition_comparison(body, pc);   // initial view = all years (already fetched)
    });
}

// ── Strategy-intersection Sankey (standalone widget at the foot of the page) ─────
// Pick any two strategies and a year (or all years); ribbons show how many channels each pair of
// communities shares. It owns its controls and year selector — independent of the table year nav —
// and persists across table re-renders. Needs the strategy keys (any snapshot has the same set).
function _build_strategy_sankey_section(stratKeys) {
    var section = document.getElementById("strategy-sankey");
    if (!section || stratKeys.length < 2) return;
    section.innerHTML = "";

    var h3 = document.createElement("h3");
    h3.className = "mt-4 mb-1";
    h3.textContent = "Community intersection";
    section.appendChild(h3);
    var intro = document.createElement("p");
    intro.className = "text-muted small mb-3";
    intro.textContent = "Pick two strategies and a year to see how their communities overlap: each ribbon's "
        + "thickness is the number of channels shared by a community on the left and a community on the right. "
        + "Click a ribbon to list those channels beneath the diagram.";
    section.appendChild(intro);

    var controls = document.createElement("div");
    controls.className = "d-flex flex-wrap align-items-end gap-3 mb-3";
    function makeSelect(idSuffix, labelText, options, selectedValue) {
        var wrap = document.createElement("div");
        var lbl = document.createElement("label");
        lbl.className = "form-label mb-1 d-block fw-semibold small";
        var sel = document.createElement("select");
        sel.className = "form-select form-select-sm";
        sel.style.width = "auto";
        sel.id = "strategy-sankey-" + idSuffix;
        lbl.htmlFor = sel.id; lbl.textContent = labelText;
        options.forEach(function(o) { sel.appendChild(new Option(o.label, o.value)); });
        if (selectedValue != null) sel.value = selectedValue;
        wrap.appendChild(lbl); wrap.appendChild(sel); controls.appendChild(wrap);
        return sel;
    }

    var stratOptions = stratKeys.map(function(k) { return { value: k, label: _strat_label(k) }; });
    var yearOptions = [{ value: "all", label: "All years" }].concat(
        _ty.map(function(y) { return { value: String(y.year), label: String(y.year) }; })
    );
    var selA = makeSelect("a", "Strategy A", stratOptions, stratKeys[0]);
    var selB = makeSelect("b", "Strategy B", stratOptions, stratKeys[1]);
    var selYear = makeSelect("year", "Year", yearOptions, "all");
    section.appendChild(controls);

    var diagram = document.createElement("div");
    diagram.id = "strategy-sankey-diagram";
    section.appendChild(diagram);

    function setMessage(text) {
        diagram.innerHTML = "";
        var msg = document.createElement("p"); msg.className = "text-muted"; msg.textContent = text;
        diagram.appendChild(msg);
    }
    var _sankeyReq = 0;
    function redraw() {
        var a = selA.value, b = selB.value;
        var year = (selYear.value === "all") ? "all" : parseInt(selYear.value);
        var myReq = ++_sankeyReq;
        _fetch_year(year).then(function(d) {
            if (myReq !== _sankeyReq) return;  // a newer redraw (year/strategy change or resize) superseded this
            var fig = build_strategy_intersection_sankey(d.data, a, b, _strat_label(a), _strat_label(b), diagram.clientWidth, _nodeById);
            if (fig) { diagram.innerHTML = ""; diagram.appendChild(fig); }
            else setMessage("One of the selected strategies assigned no channels for this selection.");
        }).catch(function() {
            if (myReq !== _sankeyReq) return;
            setMessage("Failed to load data for the selected year.");
        });
    }
    selA.addEventListener("change", redraw);
    selB.addEventListener("change", redraw);
    selYear.addEventListener("change", redraw);
    _redrawStrategySankey = redraw;
    redraw();
}

// ── Render ─────────────────────────────────────────────────────────────────────
function _render(d) {
    var data = d.data, meta = d.meta;
    var container = document.getElementById("community-tables");
    container.innerHTML = "";
    _alluvialEls = {};
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

        var hmKeys = ["node_count", "internal_edges", "external_edges", "ei_index", "_ext_frac", "density",
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
            {key: "ei_index",             label: "E-I Index (−1–1)",        cls: "number", fmt: "sig3",  tip: "Krackhardt & Stern (1988): (external − internal) / (external + internal). −1 = fully cohesive (no external ties); +1 = fully competitive (no internal ties)"},
            {key: "_ext_frac",            label: "Ext. Fraction (0–1)",     cls: "number", fmt: "sig3",  tip: "Share of all connections that cross community boundaries; 0 = isolated cluster, 1 = fully peripheral"},
            {key: "density",              label: "Int. Density (0–1)",      cls: "number", fmt: "sig3",  tip: "Fraction of possible directed within-community edges that exist"},
            {key: "reciprocity",          label: "Reciprocity (0–1)",       cls: "number", fmt: "sig3",  tip: "Proportion of within-community directed edges that are bidirectional"},
            {key: "avg_clustering",       label: "Avg Clustering (0–1)",    cls: "number", fmt: "sig3",  tip: "Mean local clustering coefficient of community nodes"},
            {key: "avg_path_length",      label: "Avg Path Length",         cls: "number", fmt: "sig3",  tip: "Average shortest path in the largest weakly connected component (undirected)"},
            {key: "diameter",             label: "Diameter",                cls: "number", fmt: "int",   tip: "Longest shortest path in the largest weakly connected component (undirected)"},
        ];
        if (hasMod) {
            var modTip = UNDIRECTED_BASIS_STRATEGIES.indexOf(canonical_strategy_key(strategyKey)) !== -1
                ? "Community's contribution to network modularity (undirected Newman formula, computed on the symmetrised graph this strategy optimised)"
                : "Community's contribution to network modularity (Leicht & Newman 2008 directed formula)";
            COL_DEFS.push({
                key: "modularity_contribution", label: "Mod. Contribution", cls: "number", fmt: "sig3",
                tip: modTip,
            });
        }

        var h3 = document.createElement("h3");
        h3.id = "strategy-" + strategyKey;
        h3.className = "mt-4 mb-1";
        h3.textContent = _strat_label(strategyKey);
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

        // Community-flow alluvial across the timeline years (full-range view only — it summarises every
        // year at once). Needs all years' data, loaded lazily by _load_year_comms after the first paint.
        if (_current_year === "all" && _yearComms) {
            var alluvial = build_community_alluvial(strategyKey, _yearComms, container.clientWidth, _nodeById);
            if (alluvial) { container.appendChild(alluvial); _alluvialEls[strategyKey] = alluvial; }
        }

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

        // Distribution cross-tabs shown under the strategy table: Organisation first, then one per
        // label-group partition (Area, Nation, …). Each is precomputed server-side as
        // {label, label_lc, orgs (row labels), communities, comm_colors, pct_by_org, pct_by_community}.
        // Label-group strategy tables carry no cross_tabs (cross-tabbing a label partition is uninformative).
        (stratData.cross_tabs || []).forEach(function(ct) {
            if (!ct || !ct.orgs || ct.orgs.length < 2) return;
            var dimLabel = ct.label || "Organisation";
            var dimLabelLc = ct.label_lc || dimLabel;
            var crossDetails = document.createElement("details");
            crossDetails.className = "community-channels mt-2 mb-4";
            var crossSummary = document.createElement("summary");
            crossSummary.className = "text-muted small";
            crossSummary.textContent = dimLabel + " × community distribution";
            crossDetails.appendChild(crossSummary);

            var crossWrapper = document.createElement("div");
            crossWrapper.style.cssText = "display:flex;flex-direction:column;gap:1.5rem;margin-top:.75rem;";

            var colPerm = _hungarianColPerm(ct.pct_by_org, ct.communities.length);
            var crossComm = colPerm.map(function(j) { return ct.communities[j]; });
            var crossColors = colPerm.map(function(j) { return ct.comm_colors[j]; });
            var reorderCols = function(matrix) {
                return matrix.map(function(row) { return colPerm.map(function(j) { return row[j]; }); });
            };
            var crossPctByOrg = reorderCols(ct.pct_by_org);
            var crossPctByCommunity = reorderCols(ct.pct_by_community);

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
                var th0 = document.createElement("th"); th0.scope = "col"; th0.textContent = dimLabel; htr.appendChild(th0);
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
                ct.orgs.forEach(function(org, oi) {
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
                "% of " + dimLabelLc + " nodes per community",
                "For each " + dimLabelLc + ": share of its nodes assigned to each community. Rows sum to 100%."
            ));
            crossWrapper.appendChild(buildCrossTable(
                crossPctByCommunity,
                "% of community nodes per " + dimLabelLc,
                "For each community: share of its nodes coming from each " + dimLabelLc + ". Columns sum to 100%."
            ));

            crossDetails.appendChild(crossWrapper);
            container.appendChild(crossDetails);
        });
    });

    initSortableTables();
}

// ── Year switching ─────────────────────────────────────────────────────────────
function _switch_year(year) {
    if (year === _current_year || _loading) return;
    var prev = _current_year;
    _current_year = year;
    _loading = true;
    build_year_nav(_ty, _current_year, _switch_year);
    _fetch_year(year).then(function(d) { _render(d); _loading = false; }).catch(function() {
        // Fetch failed: roll back to the year still on screen so the nav highlight matches the
        // displayed table and a re-click on the failed year (now != _current_year) can retry it.
        _current_year = prev;
        _loading = false;
        build_year_nav(_ty, _current_year, _switch_year);
    });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetchJson(_dd + "communities.json"),
    fetchJsonOrNull(_dd + "meta.json"),
    fetchJsonOrNull(_base_dd + "timeline.json"),
    fetchJsonOrNull(_base_dd + "channels.json"),
]).then(function(results) {
    _cache[_current_year] = { data: results[0], meta: results[1] };
    var timeline = results[2];
    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_community_html; }) : [];
    var nodes = results[3] && results[3].nodes;
    if (nodes) nodes.forEach(function(n) { _nodeById[String(n.id)] = n; });

    _render(_cache[_current_year]);
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
    _load_year_comms();
    _build_partition_comparison_section();
    _build_strategy_sankey_section(Object.keys(results[0].strategies || {}));

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
