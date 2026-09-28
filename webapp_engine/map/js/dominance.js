// Render the dominance page from data/dominance.json.
//
// Three blocks (see network/dominance.py for the definitions):
//   - hierarchy: SpringRank energy, triangle transitivity and rank consistency against orientation-shuffled nulls
//   - channels:  one row per ranked channel — role, David's score, SpringRank, satellites, dependences
//   - pairs:     one row per connected pair, oriented dependent → dominant
//
// Year switcher: same pattern as robustness_table.js — when opened from a per-year data
// dir the "All" button fetches the global payload from data/.

import { build_year_nav } from './year_nav.js';
import { escHtml, fetchJson, fetchJsonOrNull } from './utils.js';

var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d{4,})\//);
var _current_year = _ym ? parseInt(_ym[1]) : "all";
var _base_dd = _ym ? "data/" : _dd;
var _cache = {};
var _ty = [];
var _loading = false;
var _payload = null;

var RELATION_LABEL = { dependence: "Dependence", alliance: "Alliance", unvalidated: "Unvalidated" };
var RELATION_CLASS = { dependence: "text-bg-warning", alliance: "text-bg-success", unvalidated: "text-bg-secondary" };
var ROLE_LABEL = { dominant: "Dominant", dependent: "Dependent", broker: "Broker", allied: "Allied", peripheral: "Peripheral" };
var ROLE_CLASS = { dominant: "text-bg-danger", dependent: "text-bg-warning", broker: "text-bg-info", allied: "text-bg-success", peripheral: "text-bg-secondary" };

var NODE_COLUMNS = [
    { label: "Rank", number: true },
    { label: "Channel", number: false },
    { label: "Role", number: false },
    { label: "David's score", number: true },
    { label: "SpringRank", number: true },
    { label: "Satellites", number: true },
    { label: "Supplies", number: true },
    { label: "Relies", number: true },
    { label: "Reach conc.", number: true },
    { label: "Cited", number: true },
    { label: "Citing", number: true },
    { label: "Partners", number: true },
];

var PAIR_COLUMNS = [
    { label: "Dependent", number: false },
    { label: "Dominant", number: false },
    { label: "Relation", number: false },
    { label: "Dep → Dom citations", number: true },
    { label: "Dep content share", number: true },
    { label: "Dom reach share", number: true },
    { label: "Dep → Dom q", number: true },
    { label: "Dom → Dep citations", number: true },
    { label: "Dom content share", number: true },
    { label: "Dep reach share", number: true },
    { label: "Dom → Dep q", number: true },
    { label: "Dependence (dep)", number: true },
    { label: "Dependence (dom)", number: true },
    { label: "Net balance", number: true },
];

function _isNil(v) {
    return v === null || v === undefined;
}

function _fmtShare(v) {
    return _isNil(v) ? "—" : (100 * v).toFixed(1) + "%";
}

function _fmtNum(v, digits) {
    return _isNil(v) ? "—" : Number(v).toFixed(digits);
}

function _fmtQ(v) {
    if (_isNil(v)) return "—";
    if (v < 0.001) return v.toExponential(1);
    return v.toFixed(3);
}

function _fmtP(v) {
    if (_isNil(v)) return "n/a";
    return v < 0.001 ? "p < 0.001" : "p = " + v.toFixed(3);
}

function _numCell(v, text, style) {
    return "<td class=\"text-end\" data-sort-value=\"" + (_isNil(v) ? "" : v) + "\"" + (style ? " style=\"" + style + "\"" : "") + ">" + text + "</td>";
}

function _shareCell(v) {
    return _numCell(v, _fmtShare(v), _isNil(v) ? "" : heatmapBg(v, 0, 1));
}

function _qCell(stat, thr) {
    if (!stat || _isNil(stat.q)) return _numCell(null, "—");
    var sig = stat.q < thr;
    return "<td class=\"text-end" + (sig ? " fw-semibold" : "") + "\" data-sort-value=\"" + stat.q + "\">" +
        _fmtQ(stat.q) + (sig ? " <span title=\"validated (q < " + thr + ")\">★</span>" : "") + "</td>";
}

function _channelCell(ref) {
    var org = ref.organization ? " <span class=\"text-muted small\">(" + escHtml(ref.organization) + ")</span>" : "";
    return "<td data-sort-value=\"" + escHtml(ref.label) + "\">" + escHtml(ref.label) + org + "</td>";
}

function _badge(label, cls) {
    return "<span class=\"badge " + cls + "\">" + label + "</span>";
}

function _matches(needle, parts) {
    if (!needle) return true;
    return parts.join(" ").toLowerCase().indexOf(needle) !== -1;
}

function _header(table, columns) {
    table.removeAttribute("data-sort-initialized");
    table.querySelector("thead").innerHTML = "<tr>" + columns.map(function(c) {
        return "<th" + (c.number ? " class=\"number text-end\"" : "") + ">" + c.label + "</th>";
    }).join("") + "</tr>";
}

// ── Hierarchy summary ────────────────────────────────────────────────────────

function _renderHierarchy(meta) {
    var target = document.getElementById("dm-hierarchy");
    target.innerHTML = "";
    var h = meta && meta.hierarchy;
    if (!h) return;
    var rows = [
        ["Is there a ranking? SpringRank energy", _fmtNum(h.springrank_energy, 3) + " (" + _fmtP(h.springrank_p) + "; random orientations ≈ " + _fmtNum(h.springrank_null_mean, 3) + ")",
            "Spring energy per interaction of the fitted ranking; lower = the interactions are better explained by one order (De Bacco et al. 2018)."
        ],
        ["Is it transitive? Triangle transitivity", (_isNil(h.transitivity) ? "n/a — no triad with three decided dyads" : _fmtNum(h.transitivity, 3) + " (" + _fmtP(h.transitivity_p) + "; random ≈ " + _fmtNum(h.transitivity_null_mean, 3) + "; " + fmtInt(h.triads) + " triads)"),
            "Share of fully known triads that are transitive rather than cyclic, rescaled so random = 0 and a perfect order = 1 (Shizuka & McDonald 2012); unbiased by the " + _fmtShare(h.unknown_share) + " of dyads that never interact."
        ],
        ["How strict is it? Rank consistency", _fmtShare(h.consistency) + " (" + _fmtP(h.consistency_p) + "; random ≈ " + _fmtShare(h.consistency_null_mean) + ")",
            "Share of dependence-weighted interactions flowing toward the higher-ranked side: 50% = no order, 100% = every pair's dependence runs entirely toward its higher-ranked side (mutual pairs pull it down even when the order is perfect)."
        ],
    ];
    var html = "<div class=\"card\"><div class=\"card-body py-2\"><h4 class=\"h6 mb-2\">Is there a hierarchy? " +
        "<span class=\"text-muted fw-normal small\">" + fmtInt(h.n_ranked) + " ranked channels · " + fmtInt(h.permutations) + " orientation-shuffled nulls</span></h4>" +
        "<table class=\"table table-sm mb-0\"><tbody>";
    rows.forEach(function(r) {
        html += "<tr><th scope=\"row\" class=\"fw-semibold\">" + r[0] + "</th><td>" + r[1] + "</td><td class=\"text-muted small\">" + r[2] + "</td></tr>";
    });
    html += "</tbody></table></div></div>";
    target.innerHTML = html;
}

function _renderPreamble(meta) {
    var target = document.getElementById("dm-preamble");
    target.innerHTML = "";
    if (!meta) return;
    var p = document.createElement("p");
    p.className = "table-preamble";
    var roles = meta.roles || {};
    var rel = meta.relations || {};
    var parts = [
        fmtInt(meta.pairs) + " connected pairs, " + fmtInt(meta.links) + " directed links, " + fmtInt(meta.total_events) + " citation events; " +
        fmtInt(meta.validated_links) + " links validated at q < " + meta.q_threshold + " (links under " + meta.min_events + " citations are not tested).",
        "Roles: " + fmtInt(roles.dominant || 0) + " dominant, " + fmtInt(roles.dependent || 0) + " dependent, " + fmtInt(roles.broker || 0) + " broker, " + fmtInt(roles.allied || 0) + " allied, " + fmtInt(roles.peripheral || 0) + " peripheral.",
        "Pairs: " + fmtInt(rel.dependence || 0) + " dependence, " + fmtInt(rel.alliance || 0) + " alliance, " + fmtInt(rel.unvalidated || 0) + " unvalidated.",
    ];
    if (meta.share_basis === "graph_events") {
        parts.push("Content shares are normalised by each channel's citation events inside the graph (no citing-message counts available).");
    }
    p.textContent = parts.join(" ");
    target.appendChild(p);
}

// ── Channels table ───────────────────────────────────────────────────────────

function _renderNodes() {
    if (!_payload) return;
    var role = document.getElementById("dm-role").value;
    var needle = (document.getElementById("dm-node-search").value || "").trim().toLowerCase();
    var table = document.getElementById("dm-nodes");
    _header(table, NODE_COLUMNS);
    var nodes = _payload.nodes || [];
    var dsMin = Infinity,
        dsMax = -Infinity;
    nodes.forEach(function(n) {
        if (n.david_score < dsMin) dsMin = n.david_score;
        if (n.david_score > dsMax) dsMax = n.david_score;
    });
    var rows = [];
    nodes.forEach(function(n) {
        if (role !== "all" && n.role !== role) return;
        if (!_matches(needle, [n.label, n.organization])) return;
        rows.push("<tr>" +
            _numCell(n.david_rank, fmtInt(n.david_rank)) +
            _channelCell(n) +
            "<td data-sort-value=\"" + n.role + "\">" + _badge(ROLE_LABEL[n.role] || n.role, ROLE_CLASS[n.role] || "text-bg-secondary") + "</td>" +
            _numCell(n.david_score, _fmtNum(n.david_score, 2), divergingHeatmapBg(n.david_score, 0, dsMin, dsMax)) +
            _numCell(n.springrank, _fmtNum(n.springrank, 2) + " <span class=\"text-muted small\">#" + n.springrank_rank + "</span>") +
            _numCell(n.satellites, fmtInt(n.satellites)) +
            _numCell(n.supplies, _fmtNum(n.supplies, 2)) +
            _shareCell(n.relies) +
            _shareCell(n.reach_concentration) +
            _numCell(n.cited, fmtInt(n.cited)) +
            _numCell(n.citing, fmtInt(n.citing)) +
            _numCell(n.partners, fmtInt(n.partners)) +
            "</tr>");
    });
    table.querySelector("tbody").innerHTML = rows.join("");
    document.getElementById("dm-node-count").textContent = fmtInt(rows.length) + " of " + fmtInt(nodes.length) + " ranked channels shown.";
    initSortableTables();
}

// ── Pairs table ──────────────────────────────────────────────────────────────

function _visiblePair(pair, relation, minCount, needle) {
    if (relation === "validated" && pair.relation === "unvalidated") return false;
    if (relation !== "all" && relation !== "validated" && pair.relation !== relation) return false;
    var c = Math.max(pair.ds ? pair.ds.count : 0, pair.sd ? pair.sd.count : 0);
    if (c < minCount) return false;
    return _matches(needle, [pair.dependent.label, pair.dependent.organization, pair.dominant.label, pair.dominant.organization]);
}

function _renderPairs() {
    if (!_payload) return;
    var thr = (_payload.meta && _payload.meta.q_threshold) || 0.05;
    var relation = document.getElementById("dm-relation").value;
    var minCount = parseInt(document.getElementById("dm-min-count").value, 10) || 1;
    var needle = (document.getElementById("dm-pair-search").value || "").trim().toLowerCase();
    var table = document.getElementById("dm-pairs");
    _header(table, PAIR_COLUMNS);
    var pairs = _payload.pairs || [];
    var rows = [];
    pairs.forEach(function(pair) {
        if (!_visiblePair(pair, relation, minCount, needle)) return;
        var ds = pair.ds,
            sd = pair.sd;
        rows.push("<tr>" +
            _channelCell(pair.dependent) +
            _channelCell(pair.dominant) +
            "<td data-sort-value=\"" + pair.relation + "\">" + _badge(RELATION_LABEL[pair.relation] || pair.relation, RELATION_CLASS[pair.relation] || "text-bg-secondary") +
            (pair.mutual ? "" : " <span class=\"text-muted small\" title=\"one-way: only one side ever cites the other\">one-way</span>") +
            (pair.below_floor ? " <span class=\"text-muted small\" title=\"fewer interactions than the evidence floor: listed, not ranked, not tested\">below floor</span>" : "") + "</td>" +
            _numCell(ds ? ds.count : 0, fmtInt(ds ? ds.count : 0)) +
            _shareCell(ds ? ds.share : null) +
            _shareCell(ds ? ds.reach : null) +
            _qCell(ds, thr) +
            _numCell(sd ? sd.count : 0, fmtInt(sd ? sd.count : 0)) +
            _shareCell(sd ? sd.share : null) +
            _shareCell(sd ? sd.reach : null) +
            _qCell(sd, thr) +
            _shareCell(pair.dependence_of_dependent) +
            _shareCell(pair.dependence_of_dominant) +
            _numCell(pair.net, (pair.net >= 0 ? "+" : "") + (100 * pair.net).toFixed(1) + " pt", divergingHeatmapBg(pair.net, 0, -1, 1)) +
            "</tr>");
    });
    table.querySelector("tbody").innerHTML = rows.join("");
    document.getElementById("dm-pair-count").textContent = fmtInt(rows.length) + " of " + fmtInt(pairs.length) + " pairs shown.";
    initSortableTables();
}

function _render(payload) {
    _payload = payload;
    _renderPreamble(payload.meta);
    _renderHierarchy(payload.meta);
    _renderNodes();
    _renderPairs();
}

function _load(year) {
    if (_cache[year]) return Promise.resolve(_cache[year]);
    var dd = (year === "all") ? _base_dd : ("data_" + year + "/");
    return fetchJson(dd + "dominance.json").then(function(payload) {
        _cache[year] = payload;
        return payload;
    });
}

function _switch_year(year) {
    if (year === _current_year || _loading) return;
    _loading = true;
    _load(year).then(function(payload) {
        _current_year = year;
        _render(payload);
        if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
    }).catch(function() {
        document.getElementById("dm-node-count").textContent = "Failed to load dominance data for " + year + ".";
    }).finally(function() {
        _loading = false;
    });
}

["dm-role", "dm-node-search"].forEach(function(id) {
    var el = document.getElementById(id);
    el.addEventListener("input", _renderNodes);
    el.addEventListener("change", _renderNodes);
});
["dm-relation", "dm-min-count", "dm-pair-search"].forEach(function(id) {
    var el = document.getElementById(id);
    el.addEventListener("input", _renderPairs);
    el.addEventListener("change", _renderPairs);
});

Promise.all([
    _load(_current_year),
    fetchJsonOrNull(_base_dd + "timeline.json"),
]).then(function(results) {
    _render(results[0]);
    var timeline = results[1];
    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_dominance; }) : [];
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
}).catch(function(err) {
    console.error("dominance: failed to load or render", err);
    var msg = "Failed to load dominance.json.";
    if (window.location.protocol === "file:") {
        msg += " The export bundle uses fetch() to load its JSON payloads, which most browsers refuse on file:// URLs. " +
            "Open the bundle via the bundled start.sh (\"python -m http.server\") and browse it over http://localhost:8001 instead.";
    } else if (err && err.message) {
        msg += " (" + err.message + ")";
    }
    document.getElementById("dm-node-count").textContent = msg;
});
