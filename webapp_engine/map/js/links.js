// Render the outbound-links page from data/links.json (network/link_layer.py).
//
// Five blocks:
//   - categories: the share of link events per domain category (a stacked bar + table)
//   - matrix:     labels × categories for one partition label group
//   - channels:   one row per observed channel with its link measures
//   - sites:      one row per linked site
//   - pairs:      co-linking pairs, validated by the hypergeometric test
//
// Period switcher: same pattern as dominance.js — when opened from a per-period data dir the
// "All" button fetches the global payload from data/.

import { build_year_nav } from './year_nav.js';
import { escHtml, fetchJson, fetchJsonOrNull, isCompareDataDir, periodDataDir, readTimeline } from './utils.js';

var _dd = window.DATA_DIR || "data/";
var _base_dd = _dd;
var _no_timeline = isCompareDataDir(_dd);
var _current = "all";
var _cache = {};
var _periods = [];
var _events = [];
var _loading = false;
var _payload = null;

var UNCATEGORISED = "Uncategorised";

var CHANNEL_COLUMNS = [
    { label: "Channel", number: false },
    { label: "Messages", number: true },
    { label: "Linking posts", number: true, title: "Share of the channel's messages carrying at least one outbound link" },
    { label: "Distinct sites", number: true },
    { label: "Platform diversity", number: true, title: "Effective number of equally used link categories (Hill number of order 2 over the categorised links)" },
    { label: "Monetisation", number: true, title: "Share of the channel's links pointing to monetisation sites (donations, shops)" },
    { label: "Mainstream", number: true, title: "Share of the channel's links pointing to mainstream platforms" },
    { label: "Alternative", number: true, title: "Share of the channel's links pointing to alternative platforms" },
    { label: "Categorised", number: true, title: "Share of the channel's links whose site has a category" },
    { label: "Top sites", number: false },
];

var SITE_COLUMNS = [
    { label: "Site", number: false },
    { label: "Category", number: false },
    { label: "Messages", number: true },
    { label: "Channels", number: true },
    { label: "First link", number: false },
    { label: "Last link", number: false },
    { label: "Labels linking most", number: false },
];

var PAIR_COLUMNS = [
    { label: "Channel A", number: false },
    { label: "Channel B", number: false },
    { label: "Shared sites", number: true },
    { label: "Expected", number: true, title: "Shared sites expected under the bipartite configuration model: random channel × site links keeping, on average, each channel's number of sites and each site's number of channels" },
    { label: "q", number: true, title: "Benjamini–Hochberg adjusted p-value of the hypergeometric test, over every pair of linking channels" },
    { label: "Shared sites (rarest first)", number: false },
];

function _isNil(v) {
    return v === null || v === undefined;
}

function _fmtShare(v) {
    return _isNil(v) ? "—" : (100 * v).toFixed(1) + "%";
}

function _fmtQ(v) {
    if (_isNil(v)) return "—";
    if (v < 0.001) return v.toExponential(1);
    return v.toFixed(3);
}

function _numCell(v, text, style) {
    return "<td class=\"text-end\" data-sort-value=\"" + (_isNil(v) ? "" : v) + "\"" + (style ? " style=\"" + style + "\"" : "") + ">" + text + "</td>";
}

function _shareCell(v) {
    return _numCell(v, _fmtShare(v), _isNil(v) ? "" : heatmapBg(v, 0, 1));
}

function _channelCell(ref) {
    var org = ref.organization ? " <span class=\"text-muted small\">(" + escHtml(ref.organization) + ")</span>" : "";
    return "<td data-sort-value=\"" + escHtml(ref.label) + "\">" + escHtml(ref.label) + org + "</td>";
}

function _swatch(color) {
    return "<span class=\"d-inline-block rounded-1 me-1 align-middle\" style=\"width:.8em;height:.8em;background:" + escHtml(color || "#9ca3af") + "\" aria-hidden=\"true\"></span>";
}

function _header(table, columns) {
    table.removeAttribute("data-sort-initialized");
    table.querySelector("thead").innerHTML = "<tr>" + columns.map(function(c) {
        return "<th" + (c.number ? " class=\"number text-end\"" : "") + (c.title ? " title=\"" + escHtml(c.title) + "\"" : "") + ">" + escHtml(c.label) + "</th>";
    }).join("") + "</tr>";
}

function _matches(needle, parts) {
    if (!needle) return true;
    return parts.join(" ").toLowerCase().indexOf(needle) !== -1;
}

function _categoryColors() {
    var out = {};
    (_payload.categories || []).forEach(function(c) { out[c.name] = c.color; });
    return out;
}

// ── Summary + categories ─────────────────────────────────────────────────────

function _renderPreamble() {
    var s = _payload.summary || {};
    var co = _payload.colinking || {};
    var p = document.createElement("p");
    p.className = "table-preamble";
    p.textContent = fmtInt(s.linking_channels) + " of " + fmtInt(s.channels) + " observed channels link out; " +
        fmtInt(s.linking_messages) + " of " + fmtInt(s.messages) + " messages (" + _fmtShare(s.link_share) + ") carry " +
        fmtInt(s.link_events) + " links to " + fmtInt(s.sites) + " sites, " + _fmtShare(s.categorised_share) +
        " of them to a categorised site. " + fmtInt(co.validated) + " co-linking pairs validated at q < " + co.q_threshold +
        " out of " + fmtInt(co.tested) + " pairs of linking channels.";
    var target = document.getElementById("ln-preamble");
    target.innerHTML = "";
    target.appendChild(p);
}

function _renderCategories() {
    var cats = (_payload.categories || []).filter(function(c) { return c.events > 0; });
    var bar = document.getElementById("ln-category-bar");
    // One stacked bar of link-event shares; segments under 8% carry no direct label (the table below is the legend).
    bar.innerHTML = cats.length ? "<div class=\"d-flex w-100 rounded overflow-hidden\" style=\"height:1.6rem;gap:2px\" role=\"img\" aria-label=\"Share of link events by category\">" +
        cats.map(function(c) {
            var pct = 100 * (c.share || 0);
            var label = pct >= 8 ? "<span class=\"small text-truncate px-1\" style=\"color:#fff;text-shadow:0 0 2px rgba(0,0,0,.6)\">" + escHtml(c.name) + "</span>" : "";
            return "<div class=\"d-flex align-items-center\" style=\"flex:" + pct.toFixed(3) + " 1 0;min-width:2px;background:" + escHtml(c.color) + "\" title=\"" +
                escHtml(c.name) + ": " + _fmtShare(c.share) + " of link events (" + fmtInt(c.events) + ")\">" + label + "</div>";
        }).join("") + "</div>" : "<p class=\"text-muted\">No outbound links in this period.</p>";

    var table = document.getElementById("ln-categories");
    _header(table, [
        { label: "Category", number: false },
        { label: "Role", number: false },
        { label: "Link events", number: true },
        { label: "Share", number: true },
        { label: "Channels", number: true },
        { label: "Sites", number: true },
    ]);
    table.querySelector("tbody").innerHTML = (_payload.categories || []).map(function(c) {
        return "<tr><td data-sort-value=\"" + escHtml(c.name) + "\">" + _swatch(c.color) + escHtml(c.name) + "</td>" +
            "<td>" + escHtml(c.role || "") + "</td>" +
            _numCell(c.events, fmtInt(c.events)) +
            _shareCell(c.share) +
            _numCell(c.channels, fmtInt(c.channels)) +
            _numCell(c.sites, fmtInt(c.sites)) + "</tr>";
    }).join("");
}

// ── Label × category matrix ──────────────────────────────────────────────────

function _fillGroups() {
    var sel = document.getElementById("ln-group");
    var previous = sel.value;
    var matrices = _payload.matrices || [];
    sel.innerHTML = matrices.map(function(m, i) {
        return "<option value=\"" + i + "\">" + escHtml(m.group) + "</option>";
    }).join("");
    var keep = matrices.findIndex(function(m, i) { return String(i) === previous; });
    if (keep >= 0) sel.value = previous;
}

function _renderMatrix() {
    var table = document.getElementById("ln-matrix");
    var note = document.getElementById("ln-matrix-note");
    var matrices = _payload.matrices || [];
    var m = matrices[parseInt(document.getElementById("ln-group").value, 10) || 0];
    if (!m) {
        table.querySelector("thead").innerHTML = "";
        table.querySelector("tbody").innerHTML = "";
        note.textContent = "No labelled channel links out.";
        return;
    }
    var mode = document.getElementById("ln-matrix-mode").value;
    var colors = _categoryColors();
    var cols = [{ label: m.group, number: false }];
    m.categories.forEach(function(c) { cols.push({ label: c, number: true }); });
    cols.push({ label: "Links", number: true });
    _header(table, cols);
    var max = 0;
    m.counts.forEach(function(row) { row.forEach(function(v) { if (v > max) max = v; }); });
    table.querySelector("tbody").innerHTML = m.labels.map(function(label, i) {
        var row = m.counts[i];
        var total = row.reduce(function(a, b) { return a + b; }, 0);
        return "<tr><td data-sort-value=\"" + escHtml(label) + "\">" + escHtml(label) + "</td>" + row.map(function(v, j) {
            var share = total ? v / total : null;
            var tip = escHtml(label + " → " + m.categories[j] + ": " + fmtInt(v) + " links (" + _fmtShare(share) + " of the label's links)");
            if (mode === "count") {
                return "<td class=\"text-end\" data-sort-value=\"" + v + "\" title=\"" + tip + "\" style=\"" + heatmapBg(v, 0, max || 1) + "\">" + (v ? fmtInt(v) : "·") + "</td>";
            }
            return "<td class=\"text-end\" data-sort-value=\"" + (share === null ? "" : share) + "\" title=\"" + tip + "\" style=\"" + (share === null ? "" : heatmapBg(share, 0, 1)) + "\">" + (v ? _fmtShare(share) : "·") + "</td>";
        }).join("") + _numCell(total, fmtInt(total)) + "</tr>";
    }).join("");
    note.innerHTML = "Rows: the " + escHtml(m.group) + " label of the linking channel in the period. Columns: " +
        m.categories.map(function(c) { return _swatch(colors[c]) + escHtml(c); }).join(" · ") + ".";
    initSortableTables();
}

// ── Channels ─────────────────────────────────────────────────────────────────

function _renderChannels() {
    var needle = (document.getElementById("ln-channel-search").value || "").trim().toLowerCase();
    var table = document.getElementById("ln-channels");
    _header(table, CHANNEL_COLUMNS);
    var rows = [];
    var all = _payload.channels || [];
    var maxSites = 0,
        maxDiv = 0;
    all.forEach(function(c) {
        if ((c.distinct_sites || 0) > maxSites) maxSites = c.distinct_sites;
        if ((c.platform_diversity || 0) > maxDiv) maxDiv = c.platform_diversity;
    });
    all.forEach(function(c) {
        var sites = c.sites || [];
        if (!_matches(needle, [c.label, c.organization].concat(sites.map(function(s) { return s[0]; })))) return;
        rows.push("<tr>" + _channelCell(c) +
            _numCell(c.messages, fmtInt(c.messages)) +
            _shareCell(c.link_share) +
            _numCell(c.distinct_sites, fmtInt(c.distinct_sites), _isNil(c.distinct_sites) ? "" : heatmapBg(c.distinct_sites, 0, maxSites || 1)) +
            _numCell(c.platform_diversity, _isNil(c.platform_diversity) ? "—" : c.platform_diversity.toFixed(2), _isNil(c.platform_diversity) ? "" : heatmapBg(c.platform_diversity, 1, Math.max(maxDiv, 1.0001))) +
            _shareCell(c.monetisation_share) +
            _shareCell(c.mainstream_share) +
            _shareCell(c.alternative_share) +
            _shareCell(c.categorised_share) +
            "<td class=\"small\">" + sites.slice(0, 5).map(function(s) { return escHtml(s[0]) + " <span class=\"text-muted\">" + fmtInt(s[1]) + "</span>"; }).join(", ") + "</td>" +
            "</tr>");
    });
    table.querySelector("tbody").innerHTML = rows.join("");
    document.getElementById("ln-channel-count").textContent = fmtInt(rows.length) + " of " + fmtInt(all.length) + " observed channels shown.";
    initSortableTables();
}

// ── Sites ────────────────────────────────────────────────────────────────────

function _fillSiteCategories() {
    var sel = document.getElementById("ln-site-category");
    var previous = sel.value || "all";
    var names = (_payload.categories || []).map(function(c) { return c.name; });
    sel.innerHTML = "<option value=\"all\">All categories</option>" + names.map(function(n) {
        return "<option value=\"" + escHtml(n) + "\">" + escHtml(n) + "</option>";
    }).join("");
    sel.value = names.indexOf(previous) >= 0 ? previous : "all";
}

function _renderSites() {
    var cat = document.getElementById("ln-site-category").value;
    var minCh = parseInt(document.getElementById("ln-site-min").value, 10) || 1;
    var needle = (document.getElementById("ln-site-search").value || "").trim().toLowerCase();
    var colors = _categoryColors();
    var table = document.getElementById("ln-sites");
    _header(table, SITE_COLUMNS);
    var all = _payload.sites || [];
    var rows = [];
    all.forEach(function(s) {
        var name = s.category || UNCATEGORISED;
        if (cat !== "all" && name !== cat) return;
        if (s.channels < minCh) return;
        var groups = Object.keys(s.labels || {});
        var first = groups.length ? s.labels[groups[0]] : [];
        if (!_matches(needle, [s.site].concat(first.map(function(l) { return l[0]; })))) return;
        rows.push("<tr><td data-sort-value=\"" + escHtml(s.site) + "\">" + escHtml(s.site) + "</td>" +
            "<td data-sort-value=\"" + escHtml(name) + "\">" + _swatch(colors[name]) + escHtml(name) + "</td>" +
            _numCell(s.posts, fmtInt(s.posts)) +
            _numCell(s.channels, fmtInt(s.channels)) +
            "<td>" + escHtml(s.first || "—") + "</td><td>" + escHtml(s.last || "—") + "</td>" +
            "<td class=\"small\">" + first.map(function(l) { return escHtml(l[0]) + " <span class=\"text-muted\">" + fmtInt(l[1]) + "</span>"; }).join(", ") + "</td></tr>");
    });
    table.querySelector("tbody").innerHTML = rows.join("");
    document.getElementById("ln-site-count").textContent = fmtInt(rows.length) + " of " + fmtInt(all.length) + " sites shown." +
        (all.length && Object.keys(all[0].labels || {}).length ? " Labels: " + Object.keys(all[0].labels)[0] + "." : "");
    initSortableTables();
}

// ── Co-linking pairs ─────────────────────────────────────────────────────────

function _renderPairs() {
    var filter = document.getElementById("ln-pair-filter").value;
    var needle = (document.getElementById("ln-pair-search").value || "").trim().toLowerCase();
    var co = _payload.colinking || {};
    var table = document.getElementById("ln-pairs");
    _header(table, PAIR_COLUMNS);
    var all = co.pairs || [];
    var rows = [];
    all.forEach(function(p) {
        if (filter !== "all" && !p.validated) return;
        if (filter === "cross" && p.a.organization === p.b.organization) return;
        if (!_matches(needle, [p.a.label, p.a.organization, p.b.label, p.b.organization].concat(p.common))) return;
        rows.push("<tr>" + _channelCell(p.a) + _channelCell(p.b) +
            _numCell(p.shared, fmtInt(p.shared)) +
            _numCell(p.expected, p.expected.toFixed(1)) +
            "<td class=\"text-end" + (p.validated ? " fw-semibold" : "") + "\" data-sort-value=\"" + p.q + "\">" + _fmtQ(p.q) +
            (p.validated ? " <span title=\"validated (q < " + co.q_threshold + ")\">★</span>" : "") + "</td>" +
            "<td class=\"small\">" + p.common.map(escHtml).join(", ") + "</td></tr>");
    });
    table.querySelector("tbody").innerHTML = rows.join("");
    document.getElementById("ln-pair-count").textContent = fmtInt(rows.length) + " of " + fmtInt(all.length) +
        " listed pairs shown (pairs sharing at least " + co.min_shared + " sites).";
    initSortableTables();
}

function _render(payload) {
    _payload = payload;
    _renderPreamble();
    _renderCategories();
    _fillGroups();
    _renderMatrix();
    _renderChannels();
    _fillSiteCategories();
    _renderSites();
    _renderPairs();
}

function _load(key) {
    if (_cache[key]) return Promise.resolve(_cache[key]);
    var dd = (key === "all") ? _base_dd : periodDataDir("data/", key);
    return fetchJson(dd + "links.json").then(function(payload) {
        _cache[key] = payload;
        return payload;
    });
}

function _switch(key) {
    if (key === _current || _loading) return;
    _loading = true;
    _load(key).then(function(payload) {
        _current = key;
        _render(payload);
        if (_periods.length) build_year_nav(_periods, _current, _switch, _events);
    }).catch(function() {
        document.getElementById("ln-channel-count").textContent = "Failed to load the outbound links of " + key + ".";
    }).finally(function() {
        _loading = false;
    });
}

[
    ["ln-group", _renderMatrix],
    ["ln-matrix-mode", _renderMatrix],
    ["ln-channel-search", _renderChannels],
    ["ln-site-category", _renderSites],
    ["ln-site-min", _renderSites],
    ["ln-site-search", _renderSites],
    ["ln-pair-filter", _renderPairs],
    ["ln-pair-search", _renderPairs],
].forEach(function(pair) {
    var el = document.getElementById(pair[0]);
    el.addEventListener("input", pair[1]);
    el.addEventListener("change", pair[1]);
});

Promise.all([
    _load(_current),
    fetchJsonOrNull(_base_dd + "timeline.json"),
]).then(function(results) {
    _render(results[0]);
    var tl = readTimeline(_no_timeline ? null : results[1]);
    _events = tl.events;
    _periods = tl.periods.filter(function(p) { return p.has_links; });
    if (_periods.length) build_year_nav(_periods, _current, _switch, _events);
}).catch(function(err) {
    console.error("links: failed to load or render", err);
    var msg = "Failed to load links.json.";
    if (window.location.protocol === "file:") {
        msg += " The export bundle uses fetch() to load its JSON payloads, which most browsers refuse on file:// URLs. " +
            "Open the bundle via the bundled start.sh (\"python -m http.server\") and browse it over http://localhost:8001 instead.";
    } else if (err && err.message) {
        msg += " (" + err.message + ")";
    }
    document.getElementById("ln-channel-count").textContent = msg;
});
