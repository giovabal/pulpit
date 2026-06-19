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
// Clicking a ribbon (a "flow") lists the channels travelling along it as /channels/-style cards in a
// panel beneath the diagram (assembled by _buildFigure; cards enriched from channels.json when given).

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
var RIBBON_SELECTED_OPACITY = 0.85;  // a clicked (selected) ribbon stays highlighted while its panel is open

// ── Pure helpers ─────────────────────────────────────────────────────────────────
function _truncate(s, n) { s = String(s); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s; }

// One stage (column) from a strategy's communities.json rows. `colLabel` is shown under the column.
// Returns null when the strategy assigned no channels.
function _rowsToStage(rows, colLabel) {
    var comms = [], nodeComm = {}, nodeMeta = {};
    (rows || []).forEach(function(row) {
        var members = 0;
        (row.channels || []).forEach(function(ch) {
            var id = (ch.pk != null) ? String(ch.pk) : ch.label;
            nodeComm[id] = String(row.label);
            nodeMeta[id] = { label: ch.label || id, url: ch.url || "" };   // for the click-to-list channel panel
            members++;
        });
        if (members > 0) comms.push({ label: String(row.label), hex: row.hex_color || "#888888", count: members });
    });
    return comms.length ? { colLabel: colLabel, comms: comms, nodeComm: nodeComm, nodeMeta: nodeMeta } : null;
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

// part/whole as a rounded percent, with <1% / >99% guards so a non-empty flow never reads "0%" and a
// partial one never reads "100%". "—" when the community is empty (shouldn't happen for a real ribbon).
function _pct(part, whole) {
    if (!whole) return "—";
    if (part >= whole) return "100%";
    var p = part / whole * 100;
    if (p < 1) return "<1%";
    if (p > 99) return ">99%";
    return Math.round(p) + "%";
}

// The channels travelling along one ribbon: those assigned to community `r.src` on the left stage and
// `r.dst` on the right. Returns the flow descriptor (labels, colours, column labels, sorted channels)
// the channels panel renders when the ribbon is clicked — plus the share of each community the flow
// represents (srcPct = of the left community, dstPct = of the right one).
function _ribbonInfo(srcStage, dstStage, r, srcHex, dstHex) {
    var channels = [];
    Object.keys(srcStage.nodeComm).forEach(function(pk) {
        if (srcStage.nodeComm[pk] === r.src && dstStage.nodeComm[pk] === r.dst) {
            var m = srcStage.nodeMeta[pk] || dstStage.nodeMeta[pk] || { label: pk, url: "" };
            channels.push({ pk: pk, label: m.label, url: m.url });
        }
    });
    channels.sort(function(a, b) {
        return String(a.label).toLowerCase().localeCompare(String(b.label).toLowerCase());
    });
    var cnt = channels.length;
    var srcTotal = (srcStage.byLabel && srcStage.byLabel[r.src] && srcStage.byLabel[r.src].count) || 0;
    var dstTotal = (dstStage.byLabel && dstStage.byLabel[r.dst] && dstStage.byLabel[r.dst].count) || 0;
    return {
        srcLabel: r.src, dstLabel: r.dst, srcCol: srcStage.colLabel, dstCol: dstStage.colLabel,
        srcHex: srcHex, dstHex: dstHex, channels: channels,
        srcTotal: srcTotal, dstTotal: dstTotal, srcPct: _pct(cnt, srcTotal), dstPct: _pct(cnt, dstTotal),
    };
}

// ── Generic stages → SVG renderer ─────────────────────────────────────────────────
// `stages` is an ordered list of columns; `availWidth` is the page width to fill (columns spread to
// span it, down to MIN_COL_SPACING, then it scrolls). `onSelect(info|null)` is called when a ribbon is
// clicked (info) or the selection is cleared (null). Returns { svg, deselect } — deselect() clears any
// current ribbon selection (wired to the panel's close button).
function _render_stages_svg(stages, availWidth, ariaLabel, onSelect) {
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

    // Ribbon selection: clicking a ribbon highlights it and reports its channels via onSelect; clicking
    // it again (or closing the panel, via the returned deselect) clears it. One ribbon selected at a time.
    var _selected = null;
    function _selectRibbon(path, info) {
        if (_selected === path) {                       // toggle the current selection off
            path.setAttribute("fill-opacity", RIBBON_OPACITY);
            _selected = null;
            if (onSelect) onSelect(null);
            return;
        }
        if (_selected) _selected.setAttribute("fill-opacity", RIBBON_OPACITY);
        _selected = path;
        path.setAttribute("fill-opacity", RIBBON_SELECTED_OPACITY);
        if (onSelect) onSelect(info);
    }

    // Ribbons first (under the boxes), per boundary. Each ribbon is a clickable "flow".
    for (var bi = 0; bi < stages.length - 1; bi++) {
        var src = stages[bi], dst = stages[bi + 1];
        _boundaryRibbons(flows[bi], src, dst, unit).forEach(function(r) {
            var sc = src.byLabel[r.src], dc = dst.byLabel[r.dst];
            if (!sc || !dc) return;
            var path = _svgEl("path", {
                d: _ribbonPath(sc.x + BOX_W, dc.x, r.sy, r.dy, r.h),
                fill: sc.hex, "fill-opacity": RIBBON_OPACITY, stroke: "none",
                role: "button", tabindex: "0",
            });
            path.style.cursor = "pointer";
            var info = _ribbonInfo(src, dst, r, sc.hex, dc.hex);
            var tip = r.src + " [" + src.colLabel + "] → " + r.dst + " [" + dst.colLabel + "]: " +
                fmtInt(r.cnt) + " channel" + (r.cnt === 1 ? "" : "s") + " — click to list";
            path.setAttribute("aria-label", tip);
            path.addEventListener("mouseenter", function(e) { if (path !== _selected) path.setAttribute("fill-opacity", "0.7"); showTip(e, tip); });
            path.addEventListener("mousemove", moveTip);
            path.addEventListener("mouseleave", function() { path.setAttribute("fill-opacity", path === _selected ? RIBBON_SELECTED_OPACITY : RIBBON_OPACITY); hideTip(); });
            path.addEventListener("click", function() { _selectRibbon(path, info); });
            path.addEventListener("keydown", function(e) {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); _selectRibbon(path, info); }
            });
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

    return { svg: svg, deselect: function() { if (_selected) _selectRibbon(_selected); } };
}

// ── Involved-channels panel (click a flow to list its channels) ──────────────────
// Cards mirror the /channels/ list layout (tables.css .channel-row*). Identity/metrics come from the
// channels.json node when available (passed in as nodeById, keyed by id); the ribbon's own
// {pk,label,url} is the fallback, so a basic card still renders without channels.json.
function _rgbCss(c) { return /^\s*\d+\s*,\s*\d+\s*,\s*\d+\s*$/.test(c || "") ? "rgb(" + c + ")" : (c || ""); }

// "2022-04" → "04/22" (compact m/y, matching the /channels/ card date range).
function _ymShort(s) { var m = /^(\d{4})-(\d{2})/.exec(String(s || "")); return m ? m[2] + "/" + m[1].slice(2) : ""; }

function _usernameFromUrl(url) { var m = /t\.me\/(?:s\/)?\+?([^/?#]+)/i.exec(String(url || "")); return m ? m[1] : ""; }

function _metaItem(iconCls, text) {
    var span = document.createElement("span");
    var i = document.createElement("i"); i.className = "bi " + iconCls; i.setAttribute("aria-hidden", "true");
    span.appendChild(i); span.appendChild(document.createTextNode(" " + text));
    return span;
}

function _metaSep() { var s = document.createElement("span"); s.className = "channel-row-meta-sep"; s.textContent = "·"; return s; }

// One channel card. `ch` = {pk,label,url}; `node` = the richer channels.json node (or null/undefined).
function _channelCard(ch, node, fallbackHex) {
    var card = document.createElement(ch.url ? "a" : "div");
    card.className = "channel-row-link";
    if (ch.url) { card.href = ch.url; card.target = "_blank"; card.rel = "noopener noreferrer"; }

    var dot = document.createElement("span");
    dot.className = "org-dot channel-row-dot";
    dot.style.background = (node && _rgbCss(node.color)) || fallbackHex || "var(--muted)";
    dot.setAttribute("aria-hidden", "true");
    card.appendChild(dot);

    var body = document.createElement("span"); body.className = "channel-row-body";
    var title = document.createElement("span"); title.className = "channel-row-title";
    title.textContent = ch.label || ch.pk;
    body.appendChild(title);

    var uname = _usernameFromUrl(ch.url), org = node && node.organization;
    if (uname || org) {
        var meta1 = document.createElement("span"); meta1.className = "channel-row-meta";
        if (uname) { var tag = document.createElement("span"); tag.className = "channel-row-tag"; tag.textContent = "@" + uname; meta1.appendChild(tag); }
        if (uname && org) meta1.appendChild(_metaSep());
        if (org) { var orgEl = document.createElement("span"); orgEl.textContent = org; meta1.appendChild(orgEl); }
        body.appendChild(meta1);
    }

    if (node) {
        var meta2 = document.createElement("span"); meta2.className = "channel-row-meta";
        meta2.appendChild(_metaItem("bi-chat-left-text", fmtInt(node.messages_count || 0)));
        if (node.fans) { meta2.appendChild(_metaSep()); meta2.appendChild(_metaItem("bi-people", fmtInt(node.fans))); }
        var start = _ymShort(node.activity_start);
        if (start) { meta2.appendChild(_metaSep()); meta2.appendChild(_metaItem("bi-calendar-range", start + " – " + (_ymShort(node.activity_end) || "now"))); }
        body.appendChild(meta2);
    }
    card.appendChild(body);

    if (node && node.pic) {
        var img = document.createElement("img");
        img.className = "channel-row-pic"; img.src = node.pic; img.alt = "";
        img.setAttribute("aria-hidden", "true"); img.loading = "lazy";
        card.appendChild(img);
    }
    return card;
}

// Fill the panel with a flow header (src → dst communities, channel count) and a card per channel.
// Returns the close button so the caller can wire it to clear the ribbon selection.
function _renderChannelsPanel(panel, info, nodeById) {
    panel.textContent = "";
    panel.hidden = false;

    var head = document.createElement("div"); head.className = "alluvial-channels-head";
    var titleEl = document.createElement("div"); titleEl.className = "alluvial-channels-title";
    function commTag(label, col, hex) {
        var sw = document.createElement("span"); sw.className = "color-swatch color-swatch--sm";
        sw.style.background = hex; sw.setAttribute("aria-hidden", "true");
        var strong = document.createElement("strong"); strong.textContent = label;
        var colEl = document.createElement("span"); colEl.className = "text-muted"; colEl.textContent = "[" + col + "]";
        titleEl.appendChild(sw); titleEl.appendChild(strong); titleEl.appendChild(colEl);
    }
    commTag(info.srcLabel, info.srcCol, info.srcHex);
    var arrow = document.createElement("span"); arrow.className = "alluvial-channels-arrow"; arrow.textContent = "→";
    titleEl.appendChild(arrow);
    commTag(info.dstLabel, info.dstCol, info.dstHex);
    var n = info.channels.length;
    var cnt = document.createElement("span"); cnt.className = "text-muted"; cnt.textContent = "· " + n + " channel" + (n === 1 ? "" : "s");
    titleEl.appendChild(cnt);
    if (info.srcTotal && info.dstTotal) {
        var share = document.createElement("span"); share.className = "text-muted";
        share.textContent = "· (" + info.srcPct + " → " + info.dstPct + ")";
        share.title = info.srcPct + " of " + info.srcLabel + " [" + info.srcCol + "] flows here; this is "
            + info.dstPct + " of " + info.dstLabel + " [" + info.dstCol + "]";
        titleEl.appendChild(share);
    }
    head.appendChild(titleEl);

    var close = document.createElement("button");
    close.type = "button"; close.className = "alluvial-channels-close"; close.setAttribute("aria-label", "Close channel list");
    close.textContent = "×";
    head.appendChild(close);
    panel.appendChild(head);

    var grid = document.createElement("div"); grid.className = "alluvial-channels-grid";
    var frag = document.createDocumentFragment();
    info.channels.forEach(function(ch) { frag.appendChild(_channelCard(ch, nodeById && nodeById[ch.pk], info.srcHex)); });
    grid.appendChild(frag);
    panel.appendChild(grid);
    return close;
}

// Assemble the scroll-wrapped SVG plus the (initially hidden) channels panel, wiring ribbon selection
// to the panel. `nodeById` enriches the cards (channels.json nodes keyed by id); may be omitted.
function _buildFigure(stages, availWidth, ariaLabel, nodeById) {
    var panel = document.createElement("div"); panel.className = "alluvial-channels"; panel.hidden = true;
    var api = _render_stages_svg(stages, availWidth, ariaLabel, function(info) {
        if (!info) { panel.hidden = true; panel.textContent = ""; return; }
        var close = _renderChannelsPanel(panel, info, nodeById);
        close.addEventListener("click", function() { api.deselect(); });
        panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    var fig = document.createElement("div"); fig.className = "alluvial-figure";
    fig.appendChild(_scrollWrap(api.svg));
    fig.appendChild(panel);
    return fig;
}

// ── Public entry points ────────────────────────────────────────────────────────────
// One strategy's year-over-year community flow. Returns a titled DOM section, or null when fewer
// than two timeline years carry the strategy (nothing to connect). `availWidth` is the page width;
// `nodeById` (channels.json nodes keyed by id) enriches the click-to-list channel cards.
export function build_community_alluvial(strategyKey, yearComms, availWidth, nodeById) {
    var stages = _yearStages(strategyKey, yearComms);
    if (stages.length < 2) return null;

    var section = document.createElement("div");
    section.className = "community-alluvial mt-2 mb-4";
    var title = document.createElement("p");
    title.className = "small fw-semibold mb-1";
    title.textContent = "Community flow across years";
    title.title = "Each column is a year's communities under this strategy; ribbons follow channels from " +
        "one year's community into the next. Communities are re-detected (and re-labelled) every year, so " +
        "read continuity from the ribbons: one thick ribbon = a cohort held together, many thin ribbons = it " +
        "split. Click a ribbon to list the channels travelling along that flow.";
    section.appendChild(title);
    section.appendChild(_buildFigure(stages, availWidth,
        "Community flow across " + stages.length + " years for this strategy", nodeById));
    return section;
}

// Two strategies' communities for one snapshot, side by side, with ribbons sized by the channels
// they share (the cross-tabulation of the two partitions). Returns the figure (scroll-wrapped <svg>
// plus its channels panel), or null when either strategy assigned no channels in `data`. `availWidth`
// is the page width to fill; `nodeById` enriches the click-to-list channel cards.
export function build_strategy_intersection_sankey(data, keyA, keyB, labelA, labelB, availWidth, nodeById) {
    var sdA = data && data.strategies && data.strategies[keyA];
    var sdB = data && data.strategies && data.strategies[keyB];
    var stageA = sdA ? _rowsToStage(sdA.rows, labelA) : null;
    var stageB = sdB ? _rowsToStage(sdB.rows, labelB) : null;
    if (!stageA || !stageB) return null;
    return _buildFigure([stageA, stageB], availWidth,
        "Community intersection between " + labelA + " and " + labelB, nodeById);
}
