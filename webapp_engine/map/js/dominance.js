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
import { fetchJson, fetchJsonOrNull, isCompareDataDir, loadFailed, loadRecovered, periodDataDir, readTimeline } from './utils.js';
import { channelCell as _channelCell, header as _header, matches as _matches, numCell as _numCell, qCell, shareCell as _shareCell, signed } from './table_cells.js';

var _isNil = isNil;
var _fmtShare = fmtShare;
var _fmtNum = fmtFixed;

// "p = 0.012" / "p < 0.001", for the hierarchy tests' sentences.
function _fmtP(v) {
    return isNil(v) ? "no p-value" : pText(v);
}

// A link's q-value cell: the shared convention (format.js), whatever the threshold the link was validated at.
function _qCell(stat) {
    return qCell(stat ? stat.q : null);
}

var _dd = window.DATA_DIR || "data/";
var _current_year = "all";
// A compare page (data_2/) shows the full range only: it carries no timeline of its own.
var _base_dd = _dd;
var _no_timeline = isCompareDataDir(_dd);
var _tl_events = [];
var _cache = {};
var _ty = [];
var _loading = false;
var _payload = null;

var RELATION_LABEL = { dependence: "Dependence", alliance: "Alliance", unvalidated: "Unvalidated" };
var RELATION_CLASS = { dependence: "text-bg-warning", alliance: "text-bg-success", unvalidated: "text-bg-secondary" };
var ROLE_LABEL = { dominant: "Dominant", dependent: "Dependent", broker: "Broker", allied: "Allied", peripheral: "Peripheral" };
var ROLE_CLASS = { dominant: "text-bg-danger", dependent: "text-bg-warning", broker: "text-bg-info", allied: "text-bg-success", peripheral: "text-bg-secondary" };

var NODE_COLUMNS = [
    { label: "Rank", number: true, title: "Rank by David's score: 1 is the channel its partners depend on most" },
    { label: "Channel", number: false, title: "The channel, with its label" },
    { label: "Role", number: false, title: "Dominant: has satellites and is nobody's satellite. Dependent: a satellite of another channel. Broker: both. Allied: neither, but in a validated mutual pair. Peripheral: none of these" },
    { label: "David's score", number: true, title: "Sum, over the channel's citation partners, of the part of each pair's citations it wins, minus the part it loses; a pair's citations are split by the dependence each side places on the other, corrected for pairs with few citations (David 1987; de Vries et al. 2006). Positive: its partners rely on it more than it relies on them" },
    { label: "SpringRank", number: true, title: "Position in the single ordering that best explains who depends on whom (De Bacco et al. 2018), with the channel's rank in it" },
    { label: "Satellites", number: true, title: "Partners that get at least half of their cited content from this channel, or at least half of their received citations, in a clearly one-sided pair" },
    { label: "Supplies", number: true, title: "How much its partners depend on it, summed over them: the share of each partner's citing output that goes to this channel, plus the share of each cited partner's received citations that come from it. It can exceed 1" },
    { label: "Relies", number: true, title: "Its largest dependence on a single partner, as the dependent side of a clearly one-sided pair: the larger of the share of its citing output going to that partner and the share of its received citations coming from it. Empty when it is on the dependent side of no such pair" },
    { label: "Reach conc.", number: true, title: "Reach concentration: the largest share of its received citations that comes from a single channel. High = its visibility in the network rests on one amplifier" },
    { label: "Cited", number: true, title: "Citations received from channels of the network" },
    { label: "Citing", number: true, title: "Its messages citing a channel of the network" },
    { label: "Partners", number: true, title: "Channels it cites or is cited by" },
];

var PAIR_COLUMNS = [
    { label: "Dependent", number: false, title: "The side of the pair that depends more on the other" },
    { label: "Dominant", number: false, title: "The side the other depends on more" },
    { label: "Relation", number: false, title: "Alliance: both directions validated. Dependence: one direction validated. Unvalidated: none" },
    { label: "Dep → Dom citations", number: true, title: "Citations of the dominant channel by the dependent one" },
    { label: "Dep content share", number: true, title: "Share of the dependent channel's citing output that goes to the dominant one" },
    { label: "Dom reach share", number: true, title: "Share of the dominant channel's received citations that come from the dependent one" },
    { label: "Dep → Dom q", number: true, title: "Benjamini–Hochberg adjusted p-value of the dependent → dominant link: more citations than the two channels' activity explains" },
    { label: "Dom → Dep citations", number: true, title: "Citations of the dependent channel by the dominant one" },
    { label: "Dom content share", number: true, title: "Share of the dominant channel's citing output that goes to the dependent one" },
    { label: "Dep reach share", number: true, title: "Share of the dependent channel's received citations that come from the dominant one" },
    { label: "Dom → Dep q", number: true, title: "Benjamini–Hochberg adjusted p-value of the dominant → dependent link" },
    { label: "Dependence (dep)", number: true, title: "Dependence of the dependent channel on the dominant one: the mean of its content share and its reach share" },
    { label: "Dependence (dom)", number: true, title: "Dependence of the dominant channel on the dependent one" },
    { label: "Net balance", number: true, title: "Difference between the two dependences, in percentage points: the larger, the more one-sided the pair" },
];

function _badge(label, cls) {
    return "<span class=\"badge " + cls + "\">" + label + "</span>";
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
        ["Is it transitive? Triangle transitivity", (_isNil(h.transitivity) ? MISSING + " (no triad with three decided dyads)" : _fmtNum(h.transitivity, 3) + " (" + _fmtP(h.transitivity_p) + "; random ≈ " + _fmtNum(h.transitivity_null_mean, 3) + "; " + fmtInt(h.triads) + " triads)"),
            "Share of fully known triads that are transitive rather than cyclic, rescaled so random = 0 and a perfect order = 1 (Shizuka & McDonald 2012); unbiased by the " + _fmtShare(h.unknown_share) + " of dyads that never interact."
        ],
        ["How strict is it? Rank consistency", _fmtShare(h.consistency) + " (" + _fmtP(h.consistency_p) + "; random ≈ " + _fmtShare(h.consistency_null_mean) + ")",
            "Share of dependence-weighted interactions flowing toward the higher-ranked side: 50% = no order, 100% = every pair's dependence runs entirely toward its higher-ranked side (mutual pairs pull it down even when the order is perfect)."
        ],
    ];
    var html = "<h2 id=\"hierarchy\">Hierarchy</h2>" +
        "<p class=\"text-muted small mb-2\">Is there a hierarchy? " + fmtInt(h.n_ranked) + " ranked channels, each test against " +
        fmtInt(h.permutations) + " random orientations of the same pairs.</p>" +
        "<div class=\"table-responsive\"><table class=\"table table-sm mb-0\"><tbody>";
    rows.forEach(function(r) {
        html += "<tr><th scope=\"row\" class=\"fw-semibold\">" + r[0] + "</th><td>" + r[1] + "</td><td class=\"text-muted small\">" + r[2] + "</td></tr>";
    });
    html += "</tbody></table></div>";
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
        parts.push("Content shares are normalised by each channel's citation events inside the network (no count of its citing messages is available).");
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
            _qCell(ds) +
            _numCell(sd ? sd.count : 0, fmtInt(sd ? sd.count : 0)) +
            _shareCell(sd ? sd.share : null) +
            _shareCell(sd ? sd.reach : null) +
            _qCell(sd) +
            _shareCell(pair.dependence_of_dependent) +
            _shareCell(pair.dependence_of_dominant) +
            _numCell(pair.net, isNil(pair.net) ? MISSING : signed(100 * pair.net, 1) + " pt", divergingHeatmapBg(pair.net, 0, -1, 1)) +
            "</tr>");
    });
    table.querySelector("tbody").innerHTML = rows.join("");
    document.getElementById("dm-pair-count").textContent = fmtInt(rows.length) + " of " + fmtInt(pairs.length) + " pairs shown. " +
        sigLegend("q");
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
    var dd = (year === "all") ? _base_dd : periodDataDir("data/", year);
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
        loadRecovered();
        _render(payload);
        if (_ty.length) build_year_nav(_ty, _current_year, _switch_year, _tl_events);
    }).catch(function(err) {
        loadFailed(err, "the dominance analysis of " + year);
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
    var _tl = readTimeline(_no_timeline ? null : timeline);
    _tl_events = _tl.events;
    _ty = _tl.periods.filter(function(y) { return y.has_dominance; });
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year, _tl_events);
}).catch(function(err) {
    loadFailed(err);
});
