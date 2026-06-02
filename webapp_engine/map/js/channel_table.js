import { build_year_nav } from './year_nav.js';
import { mini_hist } from './charts.js';
import { fetchJson, fetchJsonOrNull } from './utils.js';

// ── Column definitions ─────────────────────────────────────────────────────────
var BASE_KEYS = ["fans", "messages_count", "in_deg", "out_deg"];
var INFLUENCE_KEYS = {"pagerank":1,"hits_hub":1,"hits_authority":1,"harmonic_centrality":1,"in_degree_centrality":1,"out_degree_centrality":1};
var STRUCTURAL_KEYS = {"betweenness":1,"bridging_centrality":1,"community_bridging":1,"burt_constraint":1,"coreness":1,"collective_influence":1,"trophic_level":1,"within_module_z":1,"brokerage_total":1};
var CONTENT_KEYS = {"content_originality":1,"amplification_factor":1,"diffusion_lag":1,"spreading_efficiency":1};
var POSITION_ORDER = ["in_deg","out_deg","fans","messages_count"];
var POSITION_LABELS = {"in_deg":"In-strength","out_deg":"Out-strength","fans":"Users","messages_count":"Messages"};
var COL_TOOLTIPS = {
    "in_deg":             "In-strength: summed raw weights of incoming ties (forwards + mentions received); higher → more heavily cited",
    "out_deg":            "Out-strength: summed raw weights of outgoing ties (forwards + mentions made); higher → cites more heavily",
    "fans":               "Number of subscribers / followers at crawl time",
    "messages_count":     "Number of messages collected in the analysis period",
    "pagerank":           "PageRank: steady-state visit probability in a random walk; higher → more central",
    "hits_hub":           "HITS hub score: propensity to link to authoritative channels; high → important aggregator",
    "hits_authority":      "HITS authority score: propensity to be cited by hub channels; high → important source",
    "betweenness":         "Betweenness centrality (normalized): fraction of shortest paths passing through this node",
    "in_degree_centrality":"Normalized in-degree centrality: in-degree / (n−1)",
    "out_degree_centrality":"Normalized out-degree centrality: out-degree / (n−1)",
    "harmonic_centrality": "Harmonic centrality (Boldi & Vigna 2014): Σ 1/d(v,u) ÷ (n−1), mean reciprocal incoming distance — how easily the rest of the network reaches this channel via short citation chains. A multi-hop generalisation of in-degree; handles disconnected graphs (unreachable pairs contribute 0).",
    "bridging_centrality": "Bridging centrality (Hwang et al. 2008): betweenness × bridging coefficient [(1/d(v)) ÷ Σ 1/d(i) over neighbours]; high → bridge sitting between high-degree regions",
    "community_bridging":  "Community bridging: betweenness × neighbour-community participation coefficient (Guimerà & Amaral 2005); high → broker spanning distinct communities",
    "burt_constraint":     "Burt’s constraint (0–1): 0 → structural-hole broker, 1 → embedded in a closed clique",
    "coreness":            "K-core coreness (Kitsak et al. 2010): deepest k-core a channel survives in; high → dense reinforcing nucleus, low → peripheral amplifier",
    "collective_influence":"Collective Influence (Morone & Makse 2015): (k−1) × Σ(k−1) over nodes two hops away; high → an optimal-percolation key spreader whose removal most fragments the network. Symmetrised, unweighted; read ordinally.",
    "trophic_level":       "Trophic level (MacKay, Johnson & Sansom 2020): structural source→sink position; low → original source, high → terminal amplifier",
    "within_module_z":     "Within-module degree z-score (Guimerà & Amaral 2005): how much of a hub the channel is inside its own community; pairs with the Role column",
    "brokerage_total":     "Brokerage (Gould & Fernandez 1989): count of directed citation 2-paths i→this→j the channel mediates between groups; pairs with the Brokerage role column. The five role counts are in nodes.csv / GEXF.",
    "content_originality": "Content originality (0–1): share of messages that are not forwards",
    "amplification_factor":"Amplification factor: forwards received from tracked channels per own message",
    "diffusion_lag":       "Diffusion lag (median hours): typical delay between original post and this channel's forward — median, not mean, because forwarding lags are heavy-tailed. Low → early adopter, high → late amplifier; null for channels with no dated forwards.",
    "spreading_efficiency":"Spreading efficiency (SIR Monte Carlo): mean fraction of network reached when seeding from this channel",
};

// Parameterised measures may be requested more than once, each producing a parameter-suffixed
// column key (e.g. "spreading_efficiency_runs_2000", "community_bridging_basis_leiden_directed").
// canonicalKey strips that suffix back to the base so column grouping and tooltips still match;
// it mirrors network.measures._registry.canonical_measure_key. (Longest-first so the most specific
// base wins; the five here are the numeric measure keys that can carry a suffix.)
var PARAM_BASE_KEYS = ["spreading_efficiency", "community_bridging", "within_module_z", "brokerage_total", "diffusion_lag"]
    .sort(function(a, b) { return b.length - a.length; });
function canonicalKey(key) {
    for (var i = 0; i < PARAM_BASE_KEYS.length; i++) {
        var base = PARAM_BASE_KEYS[i];
        if (key === base || key.indexOf(base + "_") === 0) return base;
    }
    return key;
}
// Trailing " (param=value)" of a measure label, for annotating the categorical role column that
// rides alongside a within_module_z* / brokerage_total* numeric column.
function labelAnnotation(label) {
    var i = label.indexOf(" (");
    return i !== -1 ? label.slice(i) : "";
}
// Categorical companion (the suffixed module_role / brokerage_role node attribute) of a numeric
// role-measure column key; mirrors network.measures._registry.role_companions.
function roleCompanion(numericKey) {
    var base = canonicalKey(numericKey);
    var suffix = numericKey.slice(base.length);
    if (base === "within_module_z")
        return { roleKey: "module_role" + suffix, roleLabel: "Module role",
                 tip: "Guimerà–Amaral within-module role (from the MODULEROLE measure)" };
    if (base === "brokerage_total")
        return { roleKey: "brokerage_role" + suffix, roleLabel: "Brokerage role",
                 tip: "Gould–Fernandez dominant brokerage role (from the BROKERAGEROLES measure)" };
    return null;
}

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
        return fetchJson("data_" + yr + "/channels.json")
            .then(function(d) {
                var m = {};
                (d.nodes || []).forEach(function(n) { m[n.id] = n; });
                _yr_channels[yr] = m;
            })
            .catch(function() { _yr_channels[yr] = {}; });
    }));
    return _yr_channels_promise;
}

// Columns that have no meaningful per-year data and are excluded from sparklines.
var _SPARK_SKIP = { fans: true };
// IDs of channels whose sparkline row is currently expanded (survives year switches).
var _open_nodes = {};

function _expand_row(btn, tr, node) {
    return _load_year_channels().then(function() {
        tr.querySelectorAll("td[data-col-key]").forEach(function(td) {
            var key = td.dataset.colKey;
            var all_node = _yr_channels["all"] && _yr_channels["all"][node.id];
            var all_val = all_node ? all_node[key] : null;
            var yr_vals = _all_years.map(function(yr) {
                var yn = _yr_channels[yr] && _yr_channels[yr][node.id];
                var v = yn ? yn[key] : null;
                return { year: yr, value: v != null ? String(v) : null };
            });
            var svg = mini_hist(all_val != null ? String(all_val) : null, yr_vals, _current_year, _all_years);
            td.innerHTML = "";
            var inner = document.createElement("span");
            inner.className = "spark-cell";
            if (svg) inner.appendChild(svg);
            var vspan = document.createElement("span");
            vspan.className = "spark-val";
            vspan.textContent = td.dataset.displayVal;
            inner.appendChild(vspan);
            td.appendChild(inner);
        });
        btn.classList.add("open");
    });
}

function _toggle_row(btn, tr, node) {
    if (btn.classList.contains("open")) {
        tr.querySelectorAll("td[data-col-key]").forEach(function(td) {
            td.innerHTML = "";
            td.textContent = td.dataset.displayVal;
        });
        btn.classList.remove("open");
        delete _open_nodes[node.id];
        return;
    }
    _open_nodes[node.id] = true;
    _expand_row(btn, tr, node);
}

// ── Data fetching ──────────────────────────────────────────────────────────────
function _fetch_year(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return Promise.all([
        fetchJson(dd + "channels.json"),
        fetchJson(dd + "communities.json"),
        fetchJsonOrNull(dd + "meta.json"),
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
    // Categorical role columns (Module role / Brokerage role), one per role-measure instance,
    // derived from the within_module_z* / brokerage_total* numeric columns so each carries its
    // own community-basis annotation when a role measure is requested more than once.
    var roleCols = [];
    (channels.measures || []).forEach(function(m) {
        var comp = roleCompanion(m[0]);
        if (comp) roleCols.push({ key: comp.roleKey, label: comp.roleLabel + labelAnnotation(m[1]), tip: comp.tip });
    });

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
    var influenceCols  = extraMeasures.filter(function(m) { return INFLUENCE_KEYS[canonicalKey(m[0])]; });
    var structuralCols = extraMeasures.filter(function(m) { return STRUCTURAL_KEYS[canonicalKey(m[0])]; });
    var contentCols    = extraMeasures.filter(function(m) { return CONTENT_KEYS[canonicalKey(m[0])]; });
    var otherCols      = extraMeasures.filter(function(m) { var c = canonicalKey(m[0]); return !INFLUENCE_KEYS[c] && !STRUCTURAL_KEYS[c] && !CONTENT_KEYS[c]; });

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
    cols.forEach(function(col) { addTh(col.label, "number", col.groupStart || false, COL_TOOLTIPS[canonicalKey(col.key)] || ""); });
    roleCols.forEach(function(rc, i) { addTh(rc.label, "", i === 0, rc.tip); });
    var stratGroupStart = true;
    strategies.forEach(function(s) {
        addTh(s.charAt(0).toUpperCase() + s.slice(1), "", stratGroupStart, "Community label assigned by " + s + " detection algorithm");
        stratGroupStart = false;
    });
    addTh("Activity", "", true, "Date range of channel activity in the crawled dataset (start–end)");
    thead.appendChild(htr);

    // tbody
    var fragment = document.createDocumentFragment();
    var nodeById = {};
    nodes.forEach(function(n) { nodeById[n.id] = n; });

    nodes.forEach(function(node, idx) {
        var tr = document.createElement("tr");
        if (has_spark) tr.dataset.nodeId = node.id;
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
            return td;
        }
        var rank = String(idx + 1);
        addTd(rank, "number", rank, "", "", false);

        // Channel name cell — button inside when timeline is present
        var nameTd = document.createElement("td");
        if (has_spark) {
            nameTd.style.cssText = "white-space:nowrap";
            var nameWrap = document.createElement("span");
            nameWrap.className = "channel-name-wrap";
            if (node.url) {
                var a = document.createElement("a"); a.href = node.url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = node.label || node.id; nameWrap.appendChild(a);
            } else { nameWrap.appendChild(document.createTextNode(node.label || node.id)); }
            var btn = document.createElement("button");
            btn.type = "button"; btn.className = "channel-toggle"; btn.title = "Year-by-year charts";
            btn.innerHTML = '<i class="bi bi-bar-chart-steps" aria-hidden="true"></i>';
            (function(b, row, n) { b.addEventListener("click", function() { _toggle_row(b, row, n); }); })(btn, tr, node);
            nameWrap.appendChild(btn);
            nameTd.appendChild(nameWrap);
        } else {
            if (node.url) { var a2 = document.createElement("a"); a2.href = node.url; a2.target = "_blank"; a2.rel = "noopener noreferrer"; a2.textContent = node.label || node.id; nameTd.appendChild(a2); }
            else { nameTd.textContent = node.label || node.id; }
        }
        tr.appendChild(nameTd);

        cols.forEach(function(col) {
            var val = node[col.key];
            var displayStr = col.isBase ? fmtInt(val) : sigFig(val, 3);
            var sortV = col.isBase ? (val !== null && val !== undefined ? String(val) : "") : numSortVal(val);
            var td = addTd(displayStr, "number", sortV, colBg(col, val), "", col.groupStart || false);
            if (has_spark && !_SPARK_SKIP[col.key]) {
                td.dataset.colKey = col.key;
                td.dataset.displayVal = displayStr;
            }
        });
        roleCols.forEach(function(rc, i) { addTd(node[rc.key] || "—", "", node[rc.key] || "", "", "", i === 0); });
        var firstStrategy = true;
        strategies.forEach(function(s) {
            var comm = (node.communities || {})[s];
            addTd(comm !== undefined ? String(comm) : "", "", "", "", "", firstStrategy);
            firstStrategy = false;
        });
        var start = node.activity_start || "", end = node.activity_end || "";
        addTd(start && end ? start + "–" + end : start || end || "—", "", start || end || "", "", "", true);

        fragment.appendChild(tr);
    });
    tbody.appendChild(fragment);

    // tfoot — Mean ± SD per numeric column
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
    roleCols.forEach(function(rc, i) { addFtd("", "", i === 0); });
    var firstStratFoot = true;
    strategies.forEach(function() { addFtd("", "", firstStratFoot); firstStratFoot = false; });
    addFtd("", "", true);
    tfoot.appendChild(ftr);
    table.appendChild(tfoot);

    document.getElementById("channel-count").textContent =
        nodes.length + " channel" + (nodes.length !== 1 ? "s" : "") + ". Click column headers to sort.";
    initSortableTables();

    // Re-expand rows that were open before this render (year switch keeps sparklines alive).
    // Collect promises so _switch_year can wait for all re-expansions before clearing _loading.
    var reexpand = [];
    if (has_spark && Object.keys(_open_nodes).length) {
        tbody.querySelectorAll("tr[data-node-id]").forEach(function(tr) {
            var nid = tr.dataset.nodeId;
            if (_open_nodes[nid] && nodeById[nid]) {
                var btn = tr.querySelector(".channel-toggle");
                if (btn) reexpand.push(_expand_row(btn, tr, nodeById[nid]));
            }
        });
    }
    return Promise.all(reexpand);
}

// ── Year switching ─────────────────────────────────────────────────────────────
function _switch_year(year) {
    if (year === _current_year || _loading) return;
    _current_year = year;
    _loading = true;
    build_year_nav(_ty, _current_year, _switch_year);
    _fetch_year(year).then(function(d) { return _render(d); }).then(function() { _loading = false; }).catch(function() { _loading = false; });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetchJson(_dd + "channels.json"),
    fetchJson(_dd + "communities.json"),
    fetchJsonOrNull(_dd + "meta.json"),
    fetchJsonOrNull(_base_dd + "timeline.json"),
]).then(function(results) {
    _cache[_current_year] = { channels: results[0], communities: results[1], meta: results[2] };
    var timeline = results[3];
    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_channel_html; }) : [];
    _all_years = _ty.map(function(y) { return y.year; });
    _render(_cache[_current_year]);
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
}).catch(function(err) {
    var el = document.getElementById("channel-preamble");
    if (el) el.textContent = "Failed to load data.";
    console.error("channel_table:", err);
});
