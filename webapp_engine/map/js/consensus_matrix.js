import { addSvgZoomPan as _addSvgZoomPan, showTip as _showTip, moveTip as _moveTip, hideTip as _hideTip } from './_zoom_pan.js';
import { fetchJson, fetchJsonOrNull, loadFailed, plurality, scopeLine } from './utils.js';

// ── Pure helpers ───────────────────────────────────────────────────────────────
// The community most of the methods put the channel in.
function _pluralityComm(label, stratMaps, stratKeys) {
    return plurality(stratKeys.map(function(sk) { return stratMaps[sk] ? stratMaps[sk][label] : null; }));
}

// From the theme's blue (one method agrees) to its red (all agree), as a CSS colour.
function _agreementColor(count, maxCount) {
    var t = maxCount > 1 ? (count - 1) / (maxCount - 1) : 1;
    return "color-mix(in srgb, var(--series-8) " + Math.round(t * 100) + "%, var(--series-1))";
}

// ── Module-level state ─────────────────────────────────────────────────────────
// The consensus matrix is a full-range-only artifact: the export pipeline never
// emits per-year consensus matrices, so there is no per-year switching here.
var _dd = window.DATA_DIR || "data/";

// ── Render ─────────────────────────────────────────────────────────────────────
function _render(d) {
    var data = d.data,
        meta = d.meta;
    var container = document.getElementById("consensus-matrix-container");
    container.innerHTML = "";
    var strategies = Object.keys(data.strategies);

    if (meta) container.appendChild(scopeLine(meta));

    // Exclude the manual LABELGROUP<id> partitions (metadata labels, keyed `labelgroup<id>`), the
    // structural decomposition KCORE — a shell partition, not community detection, that would
    // bias the co-association count — the derived CONSENSUS partitions (keyed
    // `consensus_threshold_*`), which summarise these very inputs and would double-count them,
    // and LEIDEN_TEMPORAL, whose full-range column is a plurality summary across timeline slices
    // rather than an independent detection of this graph.
    // Mirrors network.community.consensus_eligible. Keys in communities.json are lowercase.
    function _consensusExcluded(s) {
        var k = String(s).toLowerCase();
        return k === "kcore" || /^labelgroup\d+$/.test(k) ||
            k === "consensus" || k.indexOf("consensus_") === 0 ||
            k === "leiden_temporal" || k.indexOf("leiden_temporal_") === 0;
    }
    var nonOrgKeys = strategies.filter(function(s) { return !_consensusExcluded(s); });
    if (nonOrgKeys.length < 2) {
        var msg = document.createElement("p");
        msg.className = "text-muted";
        msg.textContent = "The consensus matrix needs at least two algorithmic grouping methods (label groups do not count).";
        container.appendChild(msg);
        return;
    }

    // Identify each channel by its pk (stable + unique). Two channels can share a
    // title, so keying the co-association on the label alone silently merged them;
    // `idLabel` maps the pk back to its title for display. Older communities.json
    // files predate the `pk` field — fall back to the label there.
    function _chanId(ch) { return (ch.pk != null) ? String(ch.pk) : ch.label; }
    var stratMaps = {},
        idLabel = {};
    nonOrgKeys.forEach(function(sk) {
        var sd = data.strategies[sk];
        if (!sd || !sd.rows) return;
        var map = {};
        sd.rows.forEach(function(row) {
            (row.channels || []).forEach(function(ch) {
                var id = _chanId(ch);
                map[id] = row.label;
                idLabel[id] = ch.label;
            });
        });
        stratMaps[sk] = map;
    });

    var channelList = Object.keys(idLabel);
    var pComm = {};
    channelList.forEach(function(id) { pComm[id] = _pluralityComm(id, stratMaps, nonOrgKeys); });
    channelList.sort(function(a, b) {
        if (pComm[a] !== pComm[b]) return pComm[a].localeCompare(pComm[b]);
        return idLabel[a].localeCompare(idLabel[b]);
    });

    var n = channelList.length,
        maxCount = nonOrgKeys.length;
    var chanIdx = {};
    channelList.forEach(function(id, i) { chanIdx[id] = i; });

    var consensus = [];
    for (var ci = 0; ci < n; ci++) consensus.push(new Int16Array(n));
    nonOrgKeys.forEach(function(sk) {
        var sd = data.strategies[sk];
        if (!sd || !sd.rows) return;
        sd.rows.forEach(function(row) {
            var members = [];
            (row.channels || []).forEach(function(ch) { var ix = chanIdx[_chanId(ch)]; if (ix !== undefined) members.push(ix); });
            for (var a = 0; a < members.length; a++)
                for (var b = a + 1; b < members.length; b++) {
                    consensus[members[a]][members[b]]++;
                    consensus[members[b]][members[a]]++;
                }
        });
    });

    var cellSize = Math.max(6, Math.min(16, Math.floor(520 / n)));
    var labelW = 140,
        topPad = 4,
        bottomPad = 110;
    var maxR = cellSize / 2 - 0.5,
        fontSize = Math.max(7, Math.min(11, cellSize - 1));
    var NS = "http://www.w3.org/2000/svg";

    var noteEl = document.createElement("p");
    noteEl.className = "text-muted small mb-2";
    noteEl.textContent = n + " × " + n + " channels — " + maxCount + " partition" + (maxCount !== 1 ? "s" : "") +
        " compared (label groups, k-core shells and the consensus partition itself left out). A circle's area grows with the number of methods putting the two channels together, and its colour shifts from blue to red as they agree. Lower triangle only; the diagonal is left out.";
    container.appendChild(noteEl);

    var legendDiv = document.createElement("div");
    legendDiv.className = "mb-3";
    legendDiv.style.cssText = "display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted);max-width:min(100%,1340px);margin-left:auto;margin-right:auto;";
    legendDiv.appendChild(document.createTextNode("Agreement → "));
    for (var k = 1; k <= maxCount; k++) {
        var legR = Math.max(1, maxR * Math.sqrt(k / maxCount));
        var diam = maxR * 2 + 2;
        var svgL = document.createElementNS(NS, "svg");
        svgL.setAttribute("width", diam);
        svgL.setAttribute("height", diam);
        svgL.style.cssText = "vertical-align:middle;flex-shrink:0;";
        var cL = document.createElementNS(NS, "circle");
        cL.setAttribute("cx", maxR + 1);
        cL.setAttribute("cy", maxR + 1);
        cL.setAttribute("r", legR);
        cL.style.fill = _agreementColor(k, maxCount);
        cL.setAttribute("opacity", "0.85");
        svgL.appendChild(cL);
        legendDiv.appendChild(svgL);
        legendDiv.appendChild(document.createTextNode(k + "/" + maxCount));
    }
    container.appendChild(legendDiv);

    var scrollDiv = document.createElement("div");
    scrollDiv.style.cssText = "overflow-x:auto;";
    var svgW = labelW + n * cellSize,
        svgH = topPad + n * cellSize + bottomPad;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", svgW);
    svg.setAttribute("height", svgH);
    svg.style.cssText = "display:block;background:var(--surface);";
    svg.setAttribute("role", "grid");
    svg.setAttribute("aria-label", "Consensus matrix, " + n + " by " + n + " channels, " + maxCount + " partitions");

    var gridG = document.createElementNS(NS, "g");
    gridG.style.stroke = "var(--chart-grid)";
    gridG.setAttribute("stroke-width", "0.5");
    for (var gi = 0; gi <= n; gi++) {
        var hl = document.createElementNS(NS, "line");
        hl.setAttribute("x1", labelW);
        hl.setAttribute("y1", topPad + gi * cellSize);
        hl.setAttribute("x2", labelW + n * cellSize);
        hl.setAttribute("y2", topPad + gi * cellSize);
        gridG.appendChild(hl);
        var vl = document.createElementNS(NS, "line");
        vl.setAttribute("x1", labelW + gi * cellSize);
        vl.setAttribute("y1", topPad);
        vl.setAttribute("x2", labelW + gi * cellSize);
        vl.setAttribute("y2", topPad + n * cellSize);
        gridG.appendChild(vl);
    }
    svg.appendChild(gridG);

    var triPts = [labelW + "," + topPad, (labelW + n * cellSize) + "," + topPad, (labelW + n * cellSize) + "," + (topPad + n * cellSize)];
    for (var si = n - 1; si >= 0; si--) {
        triPts.push((labelW + si * cellSize) + "," + (topPad + (si + 1) * cellSize));
        triPts.push((labelW + si * cellSize) + "," + (topPad + si * cellSize));
    }
    var triPoly = document.createElementNS(NS, "polygon");
    triPoly.setAttribute("points", triPts.join(" "));
    triPoly.style.fill = "color-mix(in srgb, var(--text) 5%, var(--surface))";
    svg.appendChild(triPoly);

    channelList.forEach(function(id, i) {
        var lbl = idLabel[id];
        var tx = document.createElementNS(NS, "text");
        tx.setAttribute("x", labelW - 4);
        tx.setAttribute("y", topPad + i * cellSize + cellSize / 2);
        tx.setAttribute("dy", "0.35em");
        tx.setAttribute("text-anchor", "end");
        tx.setAttribute("font-size", fontSize);
        tx.style.fill = "var(--text)";
        var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "…" : lbl;
        tx.textContent = trunc;
        if (trunc !== lbl) {
            var ttl = document.createElementNS(NS, "title");
            ttl.textContent = lbl;
            tx.appendChild(ttl);
        }
        svg.appendChild(tx);
    });

    channelList.forEach(function(id, j) {
        var lbl = idLabel[id];
        var cx = labelW + j * cellSize + cellSize / 2,
            cy = topPad + n * cellSize + 4;
        var tx = document.createElementNS(NS, "text");
        tx.setAttribute("x", cx);
        tx.setAttribute("y", cy);
        tx.setAttribute("text-anchor", "end");
        tx.setAttribute("font-size", fontSize);
        tx.style.fill = "var(--text)";
        tx.setAttribute("transform", "rotate(-45 " + cx + " " + cy + ")");
        var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "…" : lbl;
        tx.textContent = trunc;
        if (trunc !== lbl) {
            var ttl = document.createElementNS(NS, "title");
            ttl.textContent = lbl;
            tx.appendChild(ttl);
        }
        svg.appendChild(tx);
    });

    var circleG = document.createElementNS(NS, "g");
    for (var ri = 0; ri < n; ri++) {
        for (var rj = 0; rj < n; rj++) {
            if (ri <= rj) continue;
            var cnt = consensus[ri][rj];
            if (cnt === 0) continue;
            var ccx = labelW + rj * cellSize + cellSize / 2,
                ccy = topPad + ri * cellSize + cellSize / 2;
            var cr = Math.max(0.5, maxR * Math.sqrt(cnt / maxCount));
            var circ = document.createElementNS(NS, "circle");
            circ.setAttribute("cx", ccx);
            circ.setAttribute("cy", ccy);
            circ.setAttribute("r", cr);
            circ.style.fill = _agreementColor(cnt, maxCount);
            circ.setAttribute("opacity", "0.85");
            circ.setAttribute("role", "gridcell");
            circ.setAttribute("tabindex", "0");
            circ.setAttribute("aria-label", idLabel[channelList[ri]] + " and " + idLabel[channelList[rj]] + ", " + cnt + " of " + maxCount + " partitions agree");
            (function(lA, lB, c) {
                circ.addEventListener("mouseenter", function(e) { _showTip(e, lA + " × " + lB + ": " + c + "/" + maxCount + " partitions agree"); });
                circ.addEventListener("mousemove", _moveTip);
                circ.addEventListener("focus", function(e) { _showTip(e, lA + " × " + lB + ": " + c + "/" + maxCount + " partitions agree"); });
                circ.addEventListener("blur", _hideTip);
            })(idLabel[channelList[ri]], idLabel[channelList[rj]], cnt);
            circleG.appendChild(circ);
        }
    }
    circleG.addEventListener("mouseleave", _hideTip);
    svg.appendChild(circleG);
    scrollDiv.appendChild(svg);
    container.appendChild(scrollDiv);
    _addSvgZoomPan(container, scrollDiv, svg);
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetchJson(_dd + "communities.json"),
    fetchJsonOrNull(_dd + "meta.json"),
]).then(function(results) {
    _render({ data: results[0], meta: results[1] });
}).catch(function(err) {
    loadFailed(err);
});
