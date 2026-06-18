// Community-flow alluvial diagram for the community table page.
//
// Given the per-year communities.json for one strategy, build an alluvial (stacked-bar Sankey)
// with one column per timeline year. Each column's boxes are that year's communities; a ribbon
// between consecutive years carries the channels that sat in community A one year and community B
// the next. Because every year is partitioned independently, community *labels* don't carry across
// years — continuity is read from the ribbon geometry: a single thick A->B ribbon means that cohort
// stayed together (whatever it got re-labelled), a community fanning into many ribbons means it
// fragmented, and several ribbons converging means cohorts merged.
//
// Custom SVG (no chart dependency), matching the consensus / equivalence matrices: a white canvas,
// the shared hover tooltip, and box colours straight from each year's community palette. Ribbons
// take their source community's colour, so you can see where each community's members disperse to.

import { showTip, moveTip, hideTip } from './_zoom_pan.js';

var NS = "http://www.w3.org/2000/svg";

// ── Layout constants ────────────────────────────────────────────────────────────
var BOX_W = 16;            // community-box width (px)
var COL_SPACING = 170;     // distance between consecutive column left edges (px)
var PLOT_H = 360;          // vertical plotting area for the tallest column (px)
var GAP_V = 3;             // vertical gap between stacked boxes in a column (px)
var PAD_TOP = 10, PAD_BOTTOM = 30, PAD_LEFT = 10, PAD_RIGHT = 10;
var ORDER_SWEEPS = 6;      // barycentre crossing-reduction passes
var RIBBON_OPACITY = 0.42;

// ── Pure helpers ─────────────────────────────────────────────────────────────────
// Black or white box-label text, whichever contrasts better with the box colour.
function _textOn(hex) {
    var h = String(hex || "").replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return "#1a1a1a";
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#1a1a1a" : "#ffffff";
}

function _truncate(s, n) { s = String(s); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s; }

// Per-year community membership for one strategy. Returns [{year, comms:[{label,hex,count}], nodeComm}]
// keeping only years where the strategy produced at least one non-empty community.
function _yearStages(strategyKey, yearComms) {
    var stages = [];
    yearComms.forEach(function(yc) {
        var sd = yc.data && yc.data.strategies && yc.data.strategies[strategyKey];
        if (!sd || !sd.rows || !sd.rows.length) return;
        var comms = [], nodeComm = {};
        sd.rows.forEach(function(row) {
            var members = 0;
            (row.channels || []).forEach(function(ch) {
                var id = (ch.pk != null) ? String(ch.pk) : ch.label;
                nodeComm[id] = String(row.label);
                members++;
            });
            if (members > 0) comms.push({ label: String(row.label), hex: row.hex_color || "#888888", count: members });
        });
        if (comms.length) stages.push({ year: yc.year, comms: comms, nodeComm: nodeComm });
    });
    return stages;
}

// flows[bi] is a nested map src-label -> dst-label -> channel count for the boundary between stage bi
// and bi+1 (nested rather than a joined string key, since community labels may contain any character).
function _computeFlows(stages) {
    var flows = [];
    for (var bi = 0; bi < stages.length - 1; bi++) {
        var a = stages[bi], b = stages[bi + 1], f = {};
        Object.keys(a.nodeComm).forEach(function(pk) {
            var dst = b.nodeComm[pk];
            if (dst === undefined) return;                       // left the dataset next year
            var row = f[a.nodeComm[pk]] || (f[a.nodeComm[pk]] = {});
            row[dst] = (row[dst] || 0) + 1;
        });
        flows.push(f);
    }
    return flows;
}

// Reorder one stage's communities by the barycentre of their flows to an already-placed neighbour.
function _reorderByNeighbor(stages, flows, target, neighbor, forward) {
    var tStage = stages[target], nStage = stages[neighbor];
    var nPos = {};
    nStage.comms.forEach(function(c, i) { nPos[c.label] = i; });
    var f = flows[Math.min(target, neighbor)] || {};
    function flow(src, dst) { return (f[src] && f[src][dst]) || 0; }
    tStage.comms.forEach(function(c, idx) {
        var num = 0, den = 0;
        nStage.comms.forEach(function(nc) {
            var w = forward ? flow(nc.label, c.label) : flow(c.label, nc.label);
            if (w > 0) { num += w * nPos[nc.label]; den += w; }
        });
        c._bary = den > 0 ? num / den : idx;                     // no flow → keep current position
    });
    tStage.comms.sort(function(a, b) { return (a._bary - b._bary) || (b.count - a.count); });
}

// Crossing reduction: seed each column by descending size, then sweep barycentres back and forth.
function _orderStages(stages, flows) {
    stages.forEach(function(st) { st.comms.sort(function(a, b) { return b.count - a.count; }); });
    for (var s = 0; s < ORDER_SWEEPS; s++) {
        if (s % 2 === 0) {
            for (var k = 1; k < stages.length; k++) _reorderByNeighbor(stages, flows, k, k - 1, true);
        } else {
            for (var k2 = stages.length - 2; k2 >= 0; k2--) _reorderByNeighbor(stages, flows, k2, k2 + 1, false);
        }
    }
}

// Assign box geometry. One vertical unit (px per channel) is the largest value that keeps every
// column within PLOT_H; columns are then centred vertically. Populates c.{x,y,h} and st.byLabel.
function _layout(stages) {
    var unit = Infinity;
    stages.forEach(function(st) {
        var total = st.comms.reduce(function(s, c) { return s + c.count; }, 0);
        var avail = PLOT_H - (st.comms.length - 1) * GAP_V;
        if (total > 0) unit = Math.min(unit, avail / total);
    });
    if (!isFinite(unit) || unit <= 0) unit = 1;

    stages.forEach(function(st, si) {
        var total = st.comms.reduce(function(s, c) { return s + c.count; }, 0);
        var colH = total * unit + (st.comms.length - 1) * GAP_V;
        var x = PAD_LEFT + si * COL_SPACING;
        var y = PAD_TOP + (PLOT_H - colH) / 2;
        st.x = x;
        st.byLabel = {};
        st.comms.forEach(function(c) {
            c.x = x; c.y = y; c.h = c.count * unit;
            st.byLabel[c.label] = c;
            y += c.h + GAP_V;
        });
    });
    return unit;
}

// Build the ribbon descriptors for one boundary, with stacked source/target y-offsets.
// Outgoing ribbons stack within a source box ordered by target position; incoming ribbons stack
// within a target box ordered by source position — the standard ordering that minimises ribbon
// crossings in the gap.
function _boundaryRibbons(flowMap, srcStage, dstStage, unit) {
    var srcIdx = {}, dstIdx = {};
    srcStage.comms.forEach(function(c, i) { srcIdx[c.label] = i; });
    dstStage.comms.forEach(function(c, i) { dstIdx[c.label] = i; });
    var ribbons = [];
    Object.keys(flowMap).forEach(function(src) {
        Object.keys(flowMap[src]).forEach(function(dst) {
            var cnt = flowMap[src][dst];
            ribbons.push({ src: src, dst: dst, cnt: cnt, h: cnt * unit });
        });
    });
    var srcCur = {}, dstCur = {};
    srcStage.comms.forEach(function(c) { srcCur[c.label] = c.y; });
    dstStage.comms.forEach(function(c) { dstCur[c.label] = c.y; });
    ribbons.slice().sort(function(a, b) { return (srcIdx[a.src] - srcIdx[b.src]) || (dstIdx[a.dst] - dstIdx[b.dst]); })
        .forEach(function(r) { r.sy = srcCur[r.src]; srcCur[r.src] += r.h; });
    ribbons.slice().sort(function(a, b) { return (dstIdx[a.dst] - dstIdx[b.dst]) || (srcIdx[a.src] - srcIdx[b.src]); })
        .forEach(function(r) { r.dy = dstCur[r.dst]; dstCur[r.dst] += r.h; });
    return ribbons;
}

function _ribbonPath(x0, x1, sy, dy, h) {
    var xm = (x0 + x1) / 2;
    return "M" + x0 + "," + sy + " C" + xm + "," + sy + " " + xm + "," + dy + " " + x1 + "," + dy +
        " L" + x1 + "," + (dy + h) + " C" + xm + "," + (dy + h) + " " + xm + "," + (sy + h) + " " + x0 + "," + (sy + h) + " Z";
}

function _svgEl(name, attrs) {
    var el = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function(k) { el.setAttribute(k, attrs[k]); });
    return el;
}

// ── Public entry point ───────────────────────────────────────────────────────────
// Returns a DOM section for one strategy's year-over-year community flow, or null when fewer than
// two timeline years carry the strategy (nothing to connect).
export function build_community_alluvial(strategyKey, yearComms) {
    var stages = _yearStages(strategyKey, yearComms);
    if (stages.length < 2) return null;

    var flows = _computeFlows(stages);
    _orderStages(stages, flows);
    var unit = _layout(stages);

    var width = PAD_LEFT + (stages.length - 1) * COL_SPACING + BOX_W + PAD_RIGHT;
    var height = PAD_TOP + PLOT_H + PAD_BOTTOM;

    var svg = _svgEl("svg", {
        viewBox: "0 0 " + width + " " + height, width: width, height: height, role: "img",
        "aria-label": "Community flow across " + stages.length + " years for this strategy",
    });
    svg.style.cssText = "display:block;background:#fff;border-radius:4px;max-width:100%;height:auto;";

    // Ribbons first (under the boxes), per boundary.
    for (var bi = 0; bi < stages.length - 1; bi++) {
        var src = stages[bi], dst = stages[bi + 1];
        _boundaryRibbons(flows[bi], src, dst, unit).forEach(function(r) {
            var sc = src.byLabel[r.src], dc = dst.byLabel[r.dst];
            if (!sc || !dc) return;
            var path = _svgEl("path", {
                d: _ribbonPath(sc.x + BOX_W, dc.x, r.sy, r.dy, r.h),
                fill: sc.hex, "fill-opacity": RIBBON_OPACITY, stroke: "none",
            });
            var tip = r.src + " (" + src.year + ") → " + r.dst + " (" + dst.year + "): " +
                fmtInt(r.cnt) + " channel" + (r.cnt === 1 ? "" : "s");
            path.addEventListener("mouseenter", function(e) { path.setAttribute("fill-opacity", "0.7"); showTip(e, tip); });
            path.addEventListener("mousemove", moveTip);
            path.addEventListener("mouseleave", function() { path.setAttribute("fill-opacity", RIBBON_OPACITY); hideTip(); });
            svg.appendChild(path);
        });
    }

    // Boxes + labels on top.
    stages.forEach(function(st) {
        st.comms.forEach(function(c) {
            var tip = c.label + " — " + fmtInt(c.count) + " channel" + (c.count === 1 ? "" : "s") + " (" + st.year + ")";
            var rect = _svgEl("rect", {
                x: c.x, y: c.y, width: BOX_W, height: Math.max(1, c.h), fill: c.hex,
                stroke: "rgba(0,0,0,0.28)", "stroke-width": "0.5", role: "img", "aria-label": tip,
            });
            rect.addEventListener("mouseenter", function(e) { showTip(e, tip); });
            rect.addEventListener("mousemove", moveTip);
            rect.addEventListener("mouseleave", hideTip);
            svg.appendChild(rect);
            if (c.h >= 26) {
                var cx = c.x + BOX_W / 2, cy = c.y + c.h / 2;
                var txt = _svgEl("text", {
                    x: cx, y: cy, "text-anchor": "middle", "dominant-baseline": "middle",
                    transform: "rotate(-90 " + cx + " " + cy + ")", "font-size": "9",
                    fill: _textOn(c.hex), "pointer-events": "none",
                });
                txt.textContent = _truncate(c.label, Math.floor((c.h - 6) / 6));
                svg.appendChild(txt);
            }
        });
        var yl = _svgEl("text", {
            x: st.x + BOX_W / 2, y: PAD_TOP + PLOT_H + 18, "text-anchor": "middle",
            "font-size": "12", "font-weight": "500", fill: "#333",
        });
        yl.textContent = st.year;
        svg.appendChild(yl);
    });

    var section = document.createElement("div");
    section.className = "community-alluvial mt-2 mb-4";
    var title = document.createElement("p");
    title.className = "small fw-semibold mb-1";
    title.textContent = "Community flow across years";
    title.title = "Each column is a year's communities under this strategy; ribbons follow channels from " +
        "one year's community into the next. Communities are re-detected (and re-labelled) every year, so " +
        "read continuity from the ribbons: one thick ribbon = a cohort held together, many thin ribbons = it split.";
    section.appendChild(title);
    var scroll = document.createElement("div");
    scroll.style.cssText = "overflow-x:auto;";
    scroll.appendChild(svg);
    section.appendChild(scroll);
    return section;
}
