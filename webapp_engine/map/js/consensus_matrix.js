import { build_year_nav } from './year_nav.js';

// ── Pure helpers ───────────────────────────────────────────────────────────────
function _pluralityComm(label, stratMaps, stratKeys) {
    var counts = {};
    stratKeys.forEach(function(sk) {
        var comm = stratMaps[sk] && stratMaps[sk][label];
        if (comm != null) counts[comm] = (counts[comm] || 0) + 1;
    });
    var best = "", bestN = 0;
    Object.keys(counts).forEach(function(c) { if (counts[c] > bestN) { best = c; bestN = counts[c]; } });
    return best;
}

function _agreementColor(count, maxCount) {
    var t = maxCount > 1 ? (count - 1) / (maxCount - 1) : 1;
    return "rgb(" + Math.round(74 + t * (220 - 74)) + "," + Math.round(133 + t * (53 - 133)) + "," + Math.round(192 + t * (69 - 192)) + ")";
}

// ── Module-level state ─────────────────────────────────────────────────────────
var _dd = window.DATA_DIR || "data/";
var _ym = _dd.match(/data_(\d{4,})\//);
var _current_year = _ym ? parseInt(_ym[1]) : "all";
var _base_dd = _ym ? "data/" : _dd;
var _ty = [], _cache = {}, _loading = false;

// Tooltip — created once, reused across year switches
var _tip = document.createElement("div");
_tip.style.cssText = "position:fixed;background:rgba(0,0,0,.78);color:#fff;font-size:11px;" +
    "padding:3px 8px;border-radius:3px;pointer-events:none;display:none;z-index:9999;white-space:nowrap;";
document.body.appendChild(_tip);
function _showTip(e, txt) { _tip.textContent = txt; _tip.style.display = "block"; _tip.style.left = (e.clientX + 14) + "px"; _tip.style.top = (e.clientY - 30) + "px"; }
function _moveTip(e) { _tip.style.left = (e.clientX + 14) + "px"; _tip.style.top = (e.clientY - 30) + "px"; }
function _hideTip() { _tip.style.display = "none"; }

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
    var container = document.getElementById("consensus-matrix-container");
    container.innerHTML = "";
    var strategies = Object.keys(data.strategies);

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

    var nonOrgKeys = strategies.filter(function(s) { return s !== "ORGANIZATION"; });
    if (nonOrgKeys.length < 2) {
        var msg = document.createElement("p"); msg.className = "text-muted";
        msg.textContent = "At least two non-ORGANIZATION community detection strategies are required to build a consensus matrix.";
        container.appendChild(msg);
        return;
    }

    var stratMaps = {}, labelSet = {};
    nonOrgKeys.forEach(function(sk) {
        var sd = data.strategies[sk];
        if (!sd || !sd.rows) return;
        var map = {};
        sd.rows.forEach(function(row) {
            (row.channels || []).forEach(function(ch) { map[ch.label] = row.label; labelSet[ch.label] = true; });
        });
        stratMaps[sk] = map;
    });

    var channelList = Object.keys(labelSet);
    var pComm = {};
    channelList.forEach(function(lbl) { pComm[lbl] = _pluralityComm(lbl, stratMaps, nonOrgKeys); });
    channelList.sort(function(a, b) {
        if (pComm[a] !== pComm[b]) return pComm[a].localeCompare(pComm[b]);
        return a.localeCompare(b);
    });

    var n = channelList.length, maxCount = nonOrgKeys.length;
    var chanIdx = {};
    channelList.forEach(function(lbl, i) { chanIdx[lbl] = i; });

    var consensus = [];
    for (var ci = 0; ci < n; ci++) consensus.push(new Int16Array(n));
    nonOrgKeys.forEach(function(sk) {
        var sd = data.strategies[sk];
        if (!sd || !sd.rows) return;
        sd.rows.forEach(function(row) {
            var members = [];
            (row.channels || []).forEach(function(ch) { var ix = chanIdx[ch.label]; if (ix !== undefined) members.push(ix); });
            for (var a = 0; a < members.length; a++)
                for (var b = a + 1; b < members.length; b++) { consensus[members[a]][members[b]]++; consensus[members[b]][members[a]]++; }
        });
    });

    var cellSize = Math.max(6, Math.min(16, Math.floor(520 / n)));
    var labelW = 140, topPad = 4, bottomPad = 110;
    var maxR = cellSize / 2 - 0.5, fontSize = Math.max(7, Math.min(11, cellSize - 1));
    var NS = "http://www.w3.org/2000/svg";

    var noteEl = document.createElement("p");
    noteEl.className = "text-muted small mb-2";
    noteEl.textContent = n + " × " + n + " channels — " + maxCount + " partition" + (maxCount !== 1 ? "s" : "") +
        " compared (ORGANIZATION excluded). Balloon area ∝ agreement count; colour shifts blue→red with increasing agreement. Lower triangle; diagonal omitted.";
    container.appendChild(noteEl);

    var legendDiv = document.createElement("div");
    legendDiv.className = "mb-3";
    legendDiv.style.cssText = "display:flex;align-items:center;gap:10px;font-size:11px;color:#555;";
    legendDiv.appendChild(document.createTextNode("Agreement → "));
    for (var k = 1; k <= maxCount; k++) {
        var legR = Math.max(1, maxR * Math.sqrt(k / maxCount));
        var diam = maxR * 2 + 2;
        var svgL = document.createElementNS(NS, "svg");
        svgL.setAttribute("width", diam); svgL.setAttribute("height", diam); svgL.style.cssText = "vertical-align:middle;flex-shrink:0;";
        var cL = document.createElementNS(NS, "circle");
        cL.setAttribute("cx", maxR + 1); cL.setAttribute("cy", maxR + 1); cL.setAttribute("r", legR);
        cL.setAttribute("fill", _agreementColor(k, maxCount)); cL.setAttribute("opacity", "0.85");
        svgL.appendChild(cL); legendDiv.appendChild(svgL);
        legendDiv.appendChild(document.createTextNode(k + "/" + maxCount));
    }
    container.appendChild(legendDiv);

    var scrollDiv = document.createElement("div"); scrollDiv.style.cssText = "overflow-x:auto;";
    var svgW = labelW + n * cellSize, svgH = topPad + n * cellSize + bottomPad;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", svgW); svg.setAttribute("height", svgH); svg.style.cssText = "display:block;";

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

    var triPts = [labelW + "," + topPad, (labelW + n * cellSize) + "," + topPad, (labelW + n * cellSize) + "," + (topPad + n * cellSize)];
    for (var si = n - 1; si >= 0; si--) {
        triPts.push((labelW + si * cellSize) + "," + (topPad + (si + 1) * cellSize));
        triPts.push((labelW + si * cellSize) + "," + (topPad + si * cellSize));
    }
    var triPoly = document.createElementNS(NS, "polygon");
    triPoly.setAttribute("points", triPts.join(" ")); triPoly.setAttribute("fill", "#f2f2f2");
    svg.appendChild(triPoly);

    channelList.forEach(function(lbl, i) {
        var tx = document.createElementNS(NS, "text");
        tx.setAttribute("x", labelW - 4); tx.setAttribute("y", topPad + i * cellSize + cellSize / 2);
        tx.setAttribute("dy", "0.35em"); tx.setAttribute("text-anchor", "end");
        tx.setAttribute("font-size", fontSize); tx.setAttribute("fill", "#333");
        var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "…" : lbl;
        tx.textContent = trunc;
        if (trunc !== lbl) { var ttl = document.createElementNS(NS, "title"); ttl.textContent = lbl; tx.appendChild(ttl); }
        svg.appendChild(tx);
    });

    channelList.forEach(function(lbl, j) {
        var cx = labelW + j * cellSize + cellSize / 2, cy = topPad + n * cellSize + 4;
        var tx = document.createElementNS(NS, "text");
        tx.setAttribute("x", cx); tx.setAttribute("y", cy); tx.setAttribute("text-anchor", "end");
        tx.setAttribute("font-size", fontSize); tx.setAttribute("fill", "#333");
        tx.setAttribute("transform", "rotate(-45 " + cx + " " + cy + ")");
        var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "…" : lbl;
        tx.textContent = trunc;
        if (trunc !== lbl) { var ttl = document.createElementNS(NS, "title"); ttl.textContent = lbl; tx.appendChild(ttl); }
        svg.appendChild(tx);
    });

    var circleG = document.createElementNS(NS, "g");
    for (var ri = 0; ri < n; ri++) {
        for (var rj = 0; rj < n; rj++) {
            if (ri <= rj) continue;
            var cnt = consensus[ri][rj];
            if (cnt === 0) continue;
            var ccx = labelW + rj * cellSize + cellSize / 2, ccy = topPad + ri * cellSize + cellSize / 2;
            var cr = Math.max(0.5, maxR * Math.sqrt(cnt / maxCount));
            var circ = document.createElementNS(NS, "circle");
            circ.setAttribute("cx", ccx); circ.setAttribute("cy", ccy); circ.setAttribute("r", cr);
            circ.setAttribute("fill", _agreementColor(cnt, maxCount)); circ.setAttribute("opacity", "0.85");
            (function(lA, lB, c) {
                circ.addEventListener("mouseenter", function(e) { _showTip(e, lA + " × " + lB + ": " + c + "/" + maxCount + " partitions agree"); });
                circ.addEventListener("mousemove", _moveTip);
            })(channelList[ri], channelList[rj], cnt);
            circleG.appendChild(circ);
        }
    }
    circleG.addEventListener("mouseleave", _hideTip);
    svg.appendChild(circleG);
    scrollDiv.appendChild(svg);
    container.appendChild(scrollDiv);
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
    fetch(_dd + "communities.json").then(function(r) { return r.json(); }),
    fetch(_dd + "meta.json").then(function(r) { return r.json(); }).catch(function() { return null; }),
    fetch(_base_dd + "timeline.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
]).then(function(results) {
    _cache[_current_year] = { data: results[0], meta: results[1] };
    var timeline = results[2];
    _ty = timeline ? (timeline.years || []).filter(function(y) { return y.has_consensus_matrix_html; }) : [];
    _render(_cache[_current_year]);
    if (_ty.length) build_year_nav(_ty, _current_year, _switch_year);
}).catch(function(err) {
    var el = document.getElementById("consensus-matrix-container");
    if (el) el.textContent = "Failed to load data.";
    console.error("consensus_matrix:", err);
});
