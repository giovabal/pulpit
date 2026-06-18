// Stacked-bar Sankey / alluvial diagrams for the community table page.
//
// Two views share one renderer:
//   • build_community_alluvial — one column per timeline year, ribbons following channels from a
//     strategy's community one year into the next (continuity over time).
//   • build_strategy_intersection_sankey — two columns, one per chosen strategy, ribbons = the
//     channels shared by a community on each side (the cross-tabulation of two partitions).
//
// Both reduce to a generic list of "stages" (an ordered column of communities plus a node->community
// map) fed to _render_stages_svg. Custom SVG (no chart dependency), matching the consensus /
// equivalence matrices: a white canvas, the shared hover tooltip, box colours from the community
// palette, and ribbons in their source community's colour. Because partitions are independent,
// community labels carry no meaning between columns — continuity/overlap is read from the ribbons.

import { showTip, moveTip, hideTip } from './_zoom_pan.js';

var NS = "http://www.w3.org/2000/svg";

// ── Layout constants ────────────────────────────────────────────────────────────
var BOX_W = 16;            // community-box width (px)
var MIN_COL_SPACING = 90;  // minimum distance between columns; below the page-fit width it scrolls (px)
var PLOT_H = 560;          // vertical plotting area for the tallest column (px) — total height = 600
var GAP_V = 3;             // vertical gap between stacked boxes in a column (px)
var LABEL_MIN_H = 14;      // a box gets a text label only when at least this tall (else: tooltip only)
var LABEL_CHAR_W = 6.2;    // approx. px per character at the 11px label font, for fit-to-space truncation
// Generous left/right margins hold the first/last columns' horizontal labels.
var PAD_TOP = 10, PAD_BOTTOM = 30, PAD_LEFT = 130, PAD_RIGHT = 130;
var ORDER_SWEEPS = 6;      // barycentre crossing-reduction passes
var RIBBON_OPACITY = 0.42;

// ── Pure helpers ─────────────────────────────────────────────────────────────────
function _truncate(s, n) { s = String(s); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s; }

// One stage (column) from a strategy's communities.json rows. `colLabel` is shown under the column.
// Returns null when the strategy assigned no channels.
function _rowsToStage(rows, colLabel) {
    var comms = [], nodeComm = {};
    (rows || []).forEach(function(row) {
        var members = 0;
        (row.channels || []).forEach(function(ch) {
            var id = (ch.pk != null) ? String(ch.pk) : ch.label;
            nodeComm[id] = String(row.label);
            members++;
        });
        if (members > 0) comms.push({ label: String(row.label), hex: row.hex_color || "#888888", count: members });
    });
    return comms.length ? { colLabel: colLabel, comms: comms, nodeComm: nodeComm } : null;
}

// Per-year stages for one strategy (the timeline alluvial), keeping only years that produced
// communities for it.
function _yearStages(strategyKey, yearComms) {
    var stages = [];
    yearComms.forEach(function(yc) {
        var sd = yc.data && yc.data.strategies && yc.data.strategies[strategyKey];
        if (!sd) return;
        var stage = _rowsToStage(sd.rows, yc.year);
        if (stage) stages.push(stage);
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
            if (dst === undefined) return;                       // not assigned by the other side
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
function _layout(stages, colSpacing) {
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
        var x = PAD_LEFT + si * colSpacing;
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

function _scrollWrap(svg) {
    var d = document.createElement("div");
    d.style.cssText = "overflow-x:auto;";
    d.appendChild(svg);
    return d;
}

// ── Generic stages → SVG renderer ─────────────────────────────────────────────────
// `stages` is an ordered list of columns; `availWidth` is the page width to fill (columns spread to
// span it, down to MIN_COL_SPACING, then it scrolls). Returns the <svg> element.
function _render_stages_svg(stages, availWidth, ariaLabel) {
    var flows = _computeFlows(stages);
    _orderStages(stages, flows);

    var gaps = stages.length - 1;
    var fitSpacing = ((availWidth || 0) - PAD_LEFT - PAD_RIGHT - BOX_W) / gaps;
    var colSpacing = Math.max(MIN_COL_SPACING, fitSpacing);
    var unit = _layout(stages, colSpacing);

    var width = PAD_LEFT + gaps * colSpacing + BOX_W + PAD_RIGHT;
    var height = PAD_TOP + PLOT_H + PAD_BOTTOM;

    var svg = _svgEl("svg", {
        viewBox: "0 0 " + width + " " + height, width: width, height: height, role: "img",
        "aria-label": ariaLabel,
    });
    svg.style.cssText = "display:block;background:#fff;border-radius:4px;";

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
            var tip = r.src + " [" + src.colLabel + "] → " + r.dst + " [" + dst.colLabel + "]: " +
                fmtInt(r.cnt) + " channel" + (r.cnt === 1 ? "" : "s");
            path.addEventListener("mouseenter", function(e) { path.setAttribute("fill-opacity", "0.7"); showTip(e, tip); });
            path.addEventListener("mousemove", moveTip);
            path.addEventListener("mouseleave", function() { path.setAttribute("fill-opacity", RIBBON_OPACITY); hideTip(); });
            svg.appendChild(path);
        });
    }

    // Boxes, with a horizontal label beside each tall-enough box. Labels are drawn with a white halo
    // (paint-order stroke) so they stay legible over the ribbons: the first column's labels sit in the
    // left margin, the last column's in the right margin, and any middle column's just right of its box.
    stages.forEach(function(st, si) {
        var isFirst = (si === 0), isLast = (si === stages.length - 1);
        st.comms.forEach(function(c) {
            var tip = c.label + " — " + fmtInt(c.count) + " channel" + (c.count === 1 ? "" : "s") + " [" + st.colLabel + "]";
            var rect = _svgEl("rect", {
                x: c.x, y: c.y, width: BOX_W, height: Math.max(1, c.h), fill: c.hex,
                stroke: "rgba(0,0,0,0.28)", "stroke-width": "0.5", role: "img", "aria-label": tip,
            });
            rect.addEventListener("mouseenter", function(e) { showTip(e, tip); });
            rect.addEventListener("mousemove", moveTip);
            rect.addEventListener("mouseleave", hideTip);
            svg.appendChild(rect);
            if (c.h >= LABEL_MIN_H) {
                var space = isFirst ? (PAD_LEFT - 8) : (isLast ? (PAD_RIGHT - 8) : (colSpacing - BOX_W - 10));
                var txt = _svgEl("text", {
                    x: isFirst ? c.x - 5 : c.x + BOX_W + 5, y: c.y + c.h / 2,
                    "text-anchor": isFirst ? "end" : "start", "dominant-baseline": "middle",
                    "font-size": "11", fill: "#1a1a1a", "pointer-events": "none",
                    stroke: "#ffffff", "stroke-width": "3", "paint-order": "stroke",
                });
                txt.textContent = _truncate(c.label, Math.max(4, Math.floor(space / LABEL_CHAR_W)));
                svg.appendChild(txt);
            }
        });
        var cl = _svgEl("text", {
            x: st.x + BOX_W / 2, y: PAD_TOP + PLOT_H + 18, "text-anchor": "middle",
            "font-size": "12", "font-weight": "500", fill: "#333",
        });
        cl.textContent = st.colLabel;
        svg.appendChild(cl);
    });

    return svg;
}

// ── Public entry points ────────────────────────────────────────────────────────────
// One strategy's year-over-year community flow. Returns a titled DOM section, or null when fewer
// than two timeline years carry the strategy (nothing to connect). `availWidth` is the page width.
export function build_community_alluvial(strategyKey, yearComms, availWidth) {
    var stages = _yearStages(strategyKey, yearComms);
    if (stages.length < 2) return null;
    var svg = _render_stages_svg(stages, availWidth, "Community flow across " + stages.length + " years for this strategy");

    var section = document.createElement("div");
    section.className = "community-alluvial mt-2 mb-4";
    var title = document.createElement("p");
    title.className = "small fw-semibold mb-1";
    title.textContent = "Community flow across years";
    title.title = "Each column is a year's communities under this strategy; ribbons follow channels from " +
        "one year's community into the next. Communities are re-detected (and re-labelled) every year, so " +
        "read continuity from the ribbons: one thick ribbon = a cohort held together, many thin ribbons = it split.";
    section.appendChild(title);
    section.appendChild(_scrollWrap(svg));
    return section;
}

// Two strategies' communities for one snapshot, side by side, with ribbons sized by the channels
// they share (the cross-tabulation of the two partitions). Returns a scroll-wrapped <svg>, or null
// when either strategy assigned no channels in `data`. `availWidth` is the page width to fill.
export function build_strategy_intersection_sankey(data, keyA, keyB, labelA, labelB, availWidth) {
    var sdA = data && data.strategies && data.strategies[keyA];
    var sdB = data && data.strategies && data.strategies[keyB];
    var stageA = sdA ? _rowsToStage(sdA.rows, labelA) : null;
    var stageB = sdB ? _rowsToStage(sdB.rows, labelB) : null;
    if (!stageA || !stageB) return null;
    var svg = _render_stages_svg([stageA, stageB], availWidth, "Community intersection between " + labelA + " and " + labelB);
    return _scrollWrap(svg);
}
