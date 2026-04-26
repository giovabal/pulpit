import { build_year_nav } from './year_nav.js';
import { mini_hist } from './charts.js';

// ── Column definitions ─────────────────────────────────────────────────────────
var BASE_KEYS = ["fans", "messages_count", "in_deg", "out_deg"];
var INFLUENCE_KEYS = {"pagerank":1,"hits_hub":1,"hits_auth":1,"katz":1,"harmonic_centrality":1,"in_deg_centrality":1,"out_deg_centrality":1};
var STRUCTURAL_KEYS = {"betweenness":1,"flow_betweenness":1,"bridging":1,"burt_constraint":1};
var CONTENT_KEYS = {"content_originality":1,"amplification":1,"spreading":1};
var POSITION_ORDER = ["in_deg","out_deg","fans","messages_count"];
var POSITION_LABELS = {"in_deg":"Inbound","out_deg":"Outbound","fans":"Users","messages_count":"Messages"};
var COL_TOOLTIPS = {
    "in_deg":             "Inbound connections (in-degree): number of channels that forward to or cite this channel",
    "out_deg":            "Outbound connections (out-degree): number of channels this channel forwards or cites",
    "fans":               "Number of subscribers / followers at crawl time",
    "messages_count":     "Number of messages collected in the analysis period",
    "pagerank":           "PageRank: steady-state visit probability in a random walk; higher → more central",
    "hits_hub":           "HITS hub score: propensity to link to authoritative channels; high → important aggregator",
    "hits_auth":          "HITS authority score: propensity to be cited by hub channels; high → important source",
    "betweenness":        "Betweenness centrality (normalized): fraction of shortest paths passing through this node",
    "flow_betweenness":   "Random-walk betweenness centrality; less sensitive to specific path structure",
    "in_deg_centrality":  "Normalized in-degree centrality: in-degree / (n−1)",
    "out_deg_centrality": "Normalized out-degree centrality: out-degree / (n−1)",
    "harmonic_centrality":"Harmonic centrality: sum of inverse distances to all other nodes; handles disconnected graphs",
    "katz":               "Katz centrality: counts all directed paths with exponential penalization for length",
    "bridging":           "Bridging centrality: betweenness × cross-community Shannon entropy; high → information broker",
    "burt_constraint":    "Burt’s constraint (0–1): 0 → structural-hole broker, 1 → embedded in a closed clique",
    "content_originality":"Content originality (0–1): share of messages that are not forwards",
    "amplification":      "Amplification factor: forwards received from tracked channels per own message",
    "spreading":          "Spreading efficiency (SIR Monte Carlo): mean fraction of network reached when seeding from this channel",
};

// ── Module-level state ─────────────────────────────────────────────────────────
var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d{4,})\//);   // 4+ digit = calendar year, not compare suffix
var _current_year = _ym ? parseInt(_ym[1]) : "all";
var _base_dd = _ym ? "data/" : _dd;        // "all" always resolves to the full-range dir
var _ty = [];
var _all_years = [];          // ordered year numbers, derived from _ty
var _cache = {};
var _loading = false;

// ── Per-channel timeline data (lazy, loaded on first expand) ───────────────────
var _yr_channels = {};        // year (int or "all") → { nodeId: nodeObj }
var _yr_channels_promise = null;

function _load_year_channels() {
    if (_yr_channels_promise) return _yr_channels_promise;
    // Seed "all" from the already-loaded full-range cache (free, no extra fetch).
    if (!_yr_channels["all"] && _cache["all"] && _cache["all"].channels) {
        var m = {};
        (_cache["all"].channels.nodes || []).forEach(function(n) { m[n.id] = n; });
        _yr_channels["all"] = m;
    }
    if (!_all_years.length) { _yr_channels_promise = Promise.resolve(); return _yr_channels_promise; }
    _yr_channels_promise = Promise.all(_all_years.map(function(yr) {
        if (_yr_channels[yr]) return Promise.resolve();
        return fetch("data_" + yr + "/channels.json")
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var m = {};
                (d.nodes || []).forEach(function(n) { m[n.id] = n; });
                _yr_channels[yr] = m;
            })
            .catch(function() { _yr_channels[yr] = {}; });
    }));
    return _yr_channels_promise;
}

function _render_detail(td, node, cols) {
    td.innerHTML = "";
    var grid = document.createElement("div");
    grid.className = "channel-spark-grid";
    cols.forEach(function(col) {
        var all_node = _yr_channels["all"] && _yr_channels["all"][node.id];
        var all_val = all_node ? all_node[col.key] : null;
        var yr_vals = _all_years.map(function(yr) {
            var yn = _yr_channels[yr] && _yr_channels[yr][node.id];
            var v = yn ? yn[col.key] : null;
            return { year: yr, value: v != null ? String(v) : null };
        });
        var svg = mini_hist(all_val != null ? String(all_val) : null, yr_vals, _current_year, _all_years);
        if (!svg) return;
        var item = document.createElement("div");
        item.className = "channel-spark-item";
        var lbl = document.createElement("div");
        lbl.className = "channel-spark-label";
        lbl.textContent = col.label;
        item.appendChild(lbl); item.appendChild(svg);
        grid.appendChild(item);
    });
    td.appendChild(grid.children.length ? grid : document.createTextNode("No timeline data for this channel."));
}

function _toggle_detail(btn, detail_tr, node, cols) {
    if (detail_tr.style.display !== "none") {
        detail_tr.style.display = "none";
        btn.classList.remove("open");
        return;
    }
    _load_year_channels().then(function() {
        _render_detail(detail_tr.querySelector("td"), node, cols);
        detail_tr.style.display = "";
        btn.classList.add("open");
    });
}

// ── Data fetching ──────────────────────────────────────────────────────────────
function _fetch_year(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return Promise.all([
        fetch(dd + "channels.json").then(function(r) { return r.json(); }),
        fetch(dd + "communities.json").then(function(r) { return r.json(); }),
        fetch(dd + "meta.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
    ]).then(function(res) {
        var d = { channels: res[0], communities: res[1], meta: res[2] };
        _cache[year] = d;
        return d;
    });
}

// ── Render ─────────────────────────────────────────────────────────────────────
function _render(d) {
    var channels = d.channels, communities = d.communities, meta = d.meta;
    var nodes = channels.nodes;
    var strategies = Object.keys(communities.strategies);

    // Preamble
    var preambleTarget = document.getElementById("channel-preamble");
    if (preambleTarget) {
        preambleTarget.innerHTML = "";
        if (meta) {
            var pEl = document.createElement("p"); pEl.className = "table-preamble";
            var parts = ["Network of " + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
            parts.push("Edges represent " + meta.edge_weight_label + "; " + meta.edge_direction + ".");
            if (meta.start_date || meta.end_date)
                parts.push("Data range: " + (meta.start_date || "–") + " to " + (meta.end_date || "present") + ".");
            parts.push("Exported " + meta.export_date + ".");
            pEl.textContent = parts.join(" ");
            preambleTarget.appendChild(pEl);
        }
    }

    // Sort by in_deg descending
    nodes.sort(function(a, b) { return (b.in_deg || 0) - (a.in_deg || 0); });

    // Categorise extra measures
    var extraMeasures = (channels.measures || []).filter(function(m) { return BASE_KEYS.indexOf(m[0]) === -1; });
    var influenceCols  = extraMeasures.filter(function(m) { return INFLUENCE_KEYS[m[0]]; });
    var structuralCols = extraMeasures.filter(function(m) { return STRUCTURAL_KEYS[m[0]]; });
    var contentCols    = extraMeasures.filter(function(m) { return CONTENT_KEYS[m[0]]; });
    var otherCols      = extraMeasures.filter(function(m) { return !INFLUENCE_KEYS[m[0]] && !STRUCTURAL_KEYS[m[0]] && !CONTENT_KEYS[m[0]]; });

    var cols = [];
    POSITION_ORDER.forEach(function(key) { cols.push({key: key, label: POSITION_LABELS[key], group: "network_position", isBase: true}); });
    influenceCols.forEach(function(m)  { cols.push({key: m[0], label: m[1], group: "influence",  isBase: false}); });
    structuralCols.forEach(function(m) { cols.push({key: m[0], label: m[1], group: "structural", isBase: false}); });
    contentCols.forEach(function(m)    { cols.push({key: m[0], label: m[1], group: "content",    isBase: false}); });
    otherCols.forEach(function(m)      { cols.push({key: m[0], label: m[1], group: "other",      isBase: false}); });

    // Heatmap ranges
    var hmRanges = {};
    cols.forEach(function(col) {
        var mn = Infinity, mx = -Infinity, hasVal = false;
        nodes.forEach(function(n) {
            var v = n[col.key];
            if (v !== null && v !== undefined) { if (v < mn) mn = v; if (v > mx) mx = v; hasVal = true; }
        });
        if (hasVal) hmRanges[col.key] = [mn, mx];
    });

    // Mark first column of each group
    var seenGroups = {};
    cols.forEach(function(col) { if (!seenGroups[col.group]) { seenGroups[col.group] = true; col.groupStart = true; } });

    function colBg(col, val) {
        if (col.key === "burt_constraint") return divergingHeatmapBg(val, 0.5, 0, 1);
        var range = hmRanges[col.key];
        return range ? heatmapBg(val, range[0], range[1]) : "";
    }

    // Clear and rebuild table
    var table = document.getElementById("channel-table");
    table.removeAttribute("data-sort-initialized");
    var thead = table.querySelector("thead");
    var tbody = table.querySelector("tbody");
    thead.innerHTML = "";
    tbody.innerHTML = "";
    var existingFoot = table.querySelector("tfoot");
    if (existingFoot) table.removeChild(existingFoot);

    var has_spark = _all_years.length > 0;

    // thead
    var htr = document.createElement("tr");
    function addTh(label, cls, isGroupStart, tip) {
        var th = document.createElement("th"); th.scope = "col";
        var c = cls || "";
        if (isGroupStart) c = (c ? c + " " : "") + "col-group-start";
        if (c) th.className = c;
        th.textContent = label;
        if (tip) th.title = tip;
        htr.appendChild(th);
    }
    addTh("#", "number", false, "Initial rank by inbound links");
    addTh("Channel", "", false);
    cols.forEach(function(col) { addTh(col.label, "number", col.groupStart || false, COL_TOOLTIPS[col.key] || ""); });
    var stratGroupStart = true;
    strategies.forEach(function(s) {
        addTh(s.charAt(0).toUpperCase() + s.slice(1), "", stratGroupStart, "Community label assigned by " + s + " detection algorithm");
        stratGroupStart = false;
    });
    addTh("Activity", "", true, "Date range of channel activity in the crawled dataset (start–end)");
    if (has_spark) addTh("", "channel-toggle-col", false, "Expand year-by-year sparklines for this channel");
    thead.appendChild(htr);
    var totalCols = htr.cells.length;

    // tbody
    var fragment = document.createDocumentFragment();
    nodes.forEach(function(node, idx) {
        var tr = document.createElement("tr");
        function addTd(display, cls, sortVal, bg, link, isGroupStart) {
            var td = document.createElement("td");
            var c = cls || "";
            if (isGroupStart) c = (c ? c + " " : "") + "col-group-start";
            if (c) td.className = c;
            if (sortVal !== "") td.setAttribute("data-sort-value", sortVal);
            if (bg) td.setAttribute("style", bg);
            if (link) { var a = document.createElement("a"); a.href = link; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = display; td.appendChild(a); }
            else { td.textContent = display; }
            tr.appendChild(td);
        }
        var rank = String(idx + 1);
        addTd(rank, "number", rank, "", "", false);
        addTd(node.label || node.id, "", "", "", node.url || "", false);
        cols.forEach(function(col) {
            var val = node[col.key];
            addTd(
                col.isBase ? fmtInt(val) : sigFig(val, 3),
                "number",
                col.isBase ? (val !== null && val !== undefined ? String(val) : "") : numSortVal(val),
                colBg(col, val), "", col.groupStart || false
            );
        });
        var firstStrategy = true;
        strategies.forEach(function(s) {
            var comm = (node.communities || {})[s];
            addTd(comm !== undefined ? String(comm) : "", "", "", "", "", firstStrategy);
            firstStrategy = false;
        });
        var start = node.activity_start || "", end = node.activity_end || "";
        addTd(start && end ? start + "–" + end : start || end || "—", "", start || end || "", "", "", true);

        var detail_tr = null;
        if (has_spark) {
            var toggle_td = document.createElement("td");
            toggle_td.className = "channel-toggle-col";
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "channel-toggle";
            btn.title = "Show year-by-year charts";
            btn.innerHTML = '<i class="bi bi-chevron-right" aria-hidden="true"></i>';
            detail_tr = document.createElement("tr");
            detail_tr.className = "channel-detail-row";
            detail_tr.style.display = "none";
            var detail_td = document.createElement("td");
            detail_td.className = "channel-detail-cell";
            detail_td.colSpan = totalCols;
            detail_tr.appendChild(detail_td);
            (function(b, dtr, n, c) {
                b.addEventListener("click", function() { _toggle_detail(b, dtr, n, c); });
            })(btn, detail_tr, node, cols);
            toggle_td.appendChild(btn);
            tr.appendChild(toggle_td);
        }

        fragment.appendChild(tr);
        if (detail_tr) fragment.appendChild(detail_tr);
    });
    tbody.appendChild(fragment);

    // tfoot
    function colMeanSd(key) {
        var vals = nodes.map(function(n) { return n[key]; }).filter(function(v) { return v !== null && v !== undefined; });
        if (!vals.length) return "—";
        var mean = vals.reduce(function(a, b) { return a + b; }, 0) / vals.length;
        var sd = Math.sqrt(vals.reduce(function(a, b) { return a + (b - mean) * (b - mean); }, 0) / vals.length);
        return sigFig(mean, 3) + " ± " + sigFig(sd, 3);
    }
    var tfoot = document.createElement("tfoot");
    var ftr = document.createElement("tr"); ftr.className = "tfoot-stats";
    function addFtd(display, cls, isGroupStart) {
        var td = document.createElement("td");
        var c = cls || "";
        if (isGroupStart) c = (c ? c + " " : "") + "col-group-start";
        if (c) td.className = c;
        td.textContent = display;
        ftr.appendChild(td);
    }
    addFtd("", "number", false);
    addFtd("Mean ± SD", "", false);
    cols.forEach(function(col) { addFtd(colMeanSd(col.key), "number", col.groupStart || false); });
    var firstStratFoot = true;
    strategies.forEach(function(s) { addFtd("", "", firstStratFoot); firstStratFoot = false; });
    addFtd("", "", true);
    if (has_spark) addFtd("", "", false);
    tfoot.appendChild(ftr);
    table.appendChild(tfoot);

    document.getElementById("channel-count").textContent =
        nodes.length + " channel" + (nodes.length !== 1 ? "s" : "") + ". Click column headers to sort.";
    initSortableTables();
}

// ── Year switching ─────────────────────────────────────────────────────────────
function _switch_year(year) {
    if (year === _current_year || _loading) return;
    _current_year = year;
    _loading = true;
    build_year_nav(_ty, _current_year, _switch_year);
    _fetch_year(year).then(function(d) { _render(d); _loading = false; });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetch(_dd + "channels.json").then(function(r) { return r.json(); }),
    fetch(_dd + "communities.json").then(function(r) { return r.json(); }),
    fetch(_dd + "meta.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
    fetch(_base_dd + "timeline.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
]).then(function(results) {
    _cache[_current_year] = { channels: results[0], communities: results[1], meta: results[2] };
    var timeline = results[3];
    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_channel_html; }) : [];
    _all_years = _ty.map(function(y) { return y.year; });
    _render(_cache[_current_year]);
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
});
