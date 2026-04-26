import { build_year_nav } from './year_nav.js';

var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d+)\//);
var current_year = _ym ? parseInt(_ym[1]) : "all";

var BASE_KEYS = ["fans", "messages_count", "in_deg", "out_deg"];

// Column group membership — keys not listed here go into "other"
var INFLUENCE_KEYS = {"pagerank":1,"hits_hub":1,"hits_auth":1,"katz":1,"harmonic_centrality":1,"in_deg_centrality":1,"out_deg_centrality":1};
var STRUCTURAL_KEYS = {"betweenness":1,"flow_betweenness":1,"bridging":1,"burt_constraint":1};
var CONTENT_KEYS = {"content_originality":1,"amplification":1,"spreading":1};

// Within the Network-position group: desired sub-ordering
var POSITION_ORDER = ["in_deg","out_deg","fans","messages_count"];
var POSITION_LABELS = {"in_deg":"Inbound","out_deg":"Outbound","fans":"Users","messages_count":"Messages"};

// Tooltip definitions (proposal 18)
var COL_TOOLTIPS = {
    "in_deg":             "Inbound connections (in-degree): number of channels that forward to or cite this channel",
    "out_deg":            "Outbound connections (out-degree): number of channels this channel forwards or cites",
    "fans":               "Number of subscribers / followers at crawl time",
    "messages_count":     "Number of messages collected in the analysis period",
    "pagerank":           "PageRank: steady-state visit probability in a random walk; higher \u2192 more central",
    "hits_hub":           "HITS hub score: propensity to link to authoritative channels; high \u2192 important aggregator",
    "hits_auth":          "HITS authority score: propensity to be cited by hub channels; high \u2192 important source",
    "betweenness":        "Betweenness centrality (normalized): fraction of shortest paths passing through this node",
    "flow_betweenness":   "Random-walk betweenness centrality; less sensitive to specific path structure",
    "in_deg_centrality":  "Normalized in-degree centrality: in-degree / (n\u22121)",
    "out_deg_centrality": "Normalized out-degree centrality: out-degree / (n\u22121)",
    "harmonic_centrality":"Harmonic centrality: sum of inverse distances to all other nodes; handles disconnected graphs",
    "katz":               "Katz centrality: counts all directed paths with exponential penalization for length",
    "bridging":           "Bridging centrality: betweenness \u00d7 cross-community Shannon entropy; high \u2192 information broker",
    "burt_constraint":    "Burt\u2019s constraint (0\u20131): 0 \u2192 structural-hole broker, 1 \u2192 embedded in a closed clique",
    "content_originality":"Content originality (0\u20131): share of messages that are not forwards",
    "amplification":      "Amplification factor: forwards received from tracked channels per own message",
    "spreading":          "Spreading efficiency (SIR Monte Carlo): mean fraction of network reached when seeding from this channel",
};

Promise.all([
    fetch(_dd+"channels.json").then(function(r) { return r.json(); }),
    fetch(_dd+"communities.json").then(function(r) { return r.json(); }),
    fetch(_dd+"meta.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
    fetch("data/timeline.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
]).then(function(results) {
    var channels = results[0], communities = results[1], meta = results[2], timeline = results[3];
    var nodes = channels.nodes;
    var strategies = Object.keys(communities.strategies);

    // Preamble (proposal 16)
    if (meta) {
        var preambleEl = document.createElement("p"); preambleEl.className = "table-preamble";
        var parts = ["Network of " + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
        parts.push("Edges represent " + meta.edge_weight_label + "; " + meta.edge_direction + ".");
        if (meta.start_date || meta.end_date) {
            parts.push("Data range: " + (meta.start_date || "\u2013") + " to " + (meta.end_date || "present") + ".");
        }
        parts.push("Exported " + meta.export_date + ".");
        preambleEl.textContent = parts.join(" ");
        var preambleTarget = document.getElementById("channel-preamble");
        if (preambleTarget) preambleTarget.appendChild(preambleEl);
    }

    if (timeline) {
        var _ty = (timeline.years || []).filter(function(y) { return y.has_channel_html; });
        build_year_nav(_ty, current_year, "channel_table");
    }

    // Sort by in_deg descending (determines initial rank)
    nodes.sort(function(a, b) { return (b.in_deg || 0) - (a.in_deg || 0); });

    // Categorise extra measures (not BASE_KEYS)
    var extraMeasures = (channels.measures || []).filter(function(m) { return BASE_KEYS.indexOf(m[0]) === -1; });
    var influenceCols  = extraMeasures.filter(function(m) { return INFLUENCE_KEYS[m[0]]; });
    var structuralCols = extraMeasures.filter(function(m) { return STRUCTURAL_KEYS[m[0]]; });
    var contentCols    = extraMeasures.filter(function(m) { return CONTENT_KEYS[m[0]]; });
    var otherCols      = extraMeasures.filter(function(m) { return !INFLUENCE_KEYS[m[0]] && !STRUCTURAL_KEYS[m[0]] && !CONTENT_KEYS[m[0]]; });

    // Build ordered column list {key, label, group, isBase, groupStart}
    var cols = [];
    POSITION_ORDER.forEach(function(key) {
        cols.push({key: key, label: POSITION_LABELS[key], group: "network_position", isBase: true});
    });
    influenceCols.forEach(function(m)  { cols.push({key: m[0], label: m[1], group: "influence",  isBase: false}); });
    structuralCols.forEach(function(m) { cols.push({key: m[0], label: m[1], group: "structural", isBase: false}); });
    contentCols.forEach(function(m)    { cols.push({key: m[0], label: m[1], group: "content",    isBase: false}); });
    otherCols.forEach(function(m)      { cols.push({key: m[0], label: m[1], group: "other",      isBase: false}); });

    // Heatmap ranges (single pass per key)
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
    cols.forEach(function(col) {
        if (!seenGroups[col.group]) { seenGroups[col.group] = true; col.groupStart = true; }
    });

    // Cell background for a column value
    function colBg(col, val) {
        if (col.key === "burt_constraint") return divergingHeatmapBg(val, 0.5, 0, 1);
        var range = hmRanges[col.key];
        return range ? heatmapBg(val, range[0], range[1]) : "";
    }

    // Build thead
    var thead = document.querySelector("#channel-table thead");
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
    cols.forEach(function(col) {
        addTh(col.label, "number", col.groupStart || false, COL_TOOLTIPS[col.key] || "");
    });
    var stratGroupStart = true;
    strategies.forEach(function(s) {
        var tip = "Community label assigned by " + s + " detection algorithm";
        addTh(s.charAt(0).toUpperCase() + s.slice(1), "", stratGroupStart, tip);
        stratGroupStart = false;
    });
    addTh("Activity", "", true, "Date range of channel activity in the crawled dataset (start\u2013end)");
    thead.appendChild(htr);

    // Build tbody via DocumentFragment (single DOM insertion)
    var tbody = document.querySelector("#channel-table tbody");
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
            if (link) {
                var a = document.createElement("a");
                a.href = link; a.target = "_blank"; a.rel = "noopener noreferrer";
                a.textContent = display; td.appendChild(a);
            } else { td.textContent = display; }
            tr.appendChild(td);
        }

        // Rank (#)
        var rank = String(idx + 1);
        addTd(rank, "number", rank, "", "", false);

        // Channel name
        addTd(node.label || node.id, "", "", "", node.url || "", false);

        cols.forEach(function(col) {
            var val = node[col.key];
            var bg = colBg(col, val);
            var display, sortV;
            if (col.isBase) {
                // Integers: display with thousands separator; sort value is the raw number
                display = fmtInt(val);
                sortV = val !== null && val !== undefined ? String(val) : "";
            } else {
                display = sigFig(val, 3);
                sortV = numSortVal(val);
            }
            addTd(display, "number", sortV, bg, "", col.groupStart || false);
        });

        var firstStrategy = true;
        strategies.forEach(function(s) {
            var comm = (node.communities || {})[s];
            addTd(comm !== undefined ? String(comm) : "", "", "", "", "", firstStrategy);
            firstStrategy = false;
        });

        // Merged Activity column (proposal 7)
        var start = node.activity_start || "", end = node.activity_end || "";
        var actDisplay = start && end ? start + "\u2013" + end : start || end || "\u2014";
        addTd(actDisplay, "", start || end || "", "", "", true);

        fragment.appendChild(tr);
    });
    tbody.appendChild(fragment);

    // Build tfoot with mean ± SD (proposal 8)
    function colMeanSd(key) {
        var vals = nodes.map(function(n) { return n[key]; }).filter(function(v) { return v !== null && v !== undefined; });
        if (!vals.length) return "\u2014";
        var mean = vals.reduce(function(a, b) { return a + b; }, 0) / vals.length;
        var sd = Math.sqrt(vals.reduce(function(a, b) { return a + (b - mean) * (b - mean); }, 0) / vals.length);
        return sigFig(mean, 3) + " \u00b1 " + sigFig(sd, 3);
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
    addFtd("Mean \u00b1 SD", "", false);
    cols.forEach(function(col) { addFtd(colMeanSd(col.key), "number", col.groupStart || false); });
    var firstStratFoot = true;
    strategies.forEach(function(s) { addFtd("", "", firstStratFoot); firstStratFoot = false; });
    addFtd("", "", true);
    tfoot.appendChild(ftr);
    document.querySelector("#channel-table").appendChild(tfoot);

    document.getElementById("channel-count").textContent =
        nodes.length + " channel" + (nodes.length !== 1 ? "s" : "") + ". Click column headers to sort.";

    initSortableTables();
});
