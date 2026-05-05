import { strategy_label as _strat_label } from './labels.js';

var _dd = window.DATA_DIR || "data/";

// ── Tooltip — created once ─────────────────────────────────────────────────────
var _tip = document.createElement("div");
_tip.style.cssText = "position:fixed;background:rgba(0,0,0,.78);color:#fff;font-size:11px;" +
    "padding:3px 8px;border-radius:3px;pointer-events:none;display:none;z-index:9999;white-space:nowrap;";
document.body.appendChild(_tip);
function _showTip(e, txt) { _tip.textContent = txt; _tip.style.display = "block"; _tip.style.left = (e.clientX + 14) + "px"; _tip.style.top = (e.clientY - 30) + "px"; }
function _moveTip(e) { _tip.style.left = (e.clientX + 14) + "px"; _tip.style.top = (e.clientY - 30) + "px"; }
function _hideTip() { _tip.style.display = "none"; }

// ── Color scale: white (0) → steel-blue (1) ───────────────────────────────────
function _simColor(v) {
    return "rgb(" + Math.round(255 - v * 185) + "," + Math.round(255 - v * 125) + "," + Math.round(255 - v * 75) + ")";
}

// ── Similarity lookup from lower-triangle ─────────────────────────────────────
function _sim(cells_lower, i, j) {
    var a = Math.max(i, j), b = Math.min(i, j);
    return cells_lower[a][b];
}

// ── Plurality community for a node id ─────────────────────────────────────────
function _pluralityComm(node_id, nodeById, communities, stratKeys) {
    var nd = nodeById[node_id];
    if (!nd || !nd.communities) return "";
    var counts = {};
    stratKeys.forEach(function(sk) {
        var c = nd.communities[sk];
        if (c != null) counts[c] = (counts[c] || 0) + 1;
    });
    var best = "", bestN = 0;
    Object.keys(counts).forEach(function(c) { if (counts[c] > bestN) { best = c; bestN = counts[c]; } });
    return best;
}

// ── Sorted index array ─────────────────────────────────────────────────────────
function _sorted_indices(simData, channelNodes, communities, sortMode, sortMeasureKey, stratKey) {
    var n = simData.node_ids.length;
    var order = Array.from({length: n}, function(_, i) { return i; });

    if (sortMode === "community") {
        var stratKeys = stratKey
            ? [stratKey]
            : (communities ? Object.keys(communities.strategies || {}) : []);
        var nodeById = {};
        if (channelNodes) channelNodes.forEach(function(nd) { nodeById[nd.id] = nd; });
        var comm = {};
        for (var i = 0; i < n; i++) {
            comm[i] = _pluralityComm(simData.node_ids[i], nodeById, communities, stratKeys);
        }
        order.sort(function(a, b) {
            if (comm[a] !== comm[b]) return comm[a].localeCompare(comm[b]);
            return (simData.node_labels[a] || "").localeCompare(simData.node_labels[b] || "");
        });
    } else if (sortMode === "measure" && sortMeasureKey) {
        var nodeById2 = {};
        if (channelNodes) channelNodes.forEach(function(nd) { nodeById2[nd.id] = nd; });
        order.sort(function(a, b) {
            var va = (nodeById2[simData.node_ids[a]] || {})[sortMeasureKey] || 0;
            var vb = (nodeById2[simData.node_ids[b]] || {})[sortMeasureKey] || 0;
            return vb - va;  // descending
        });
    }
    return order;
}

// ── Main render ────────────────────────────────────────────────────────────────
function _render(simData, channelData, communities, meta, sortMode, sortMeasureKey, stratKey) {
    var container = document.getElementById("structural-similarity-container");
    container.innerHTML = "";

    if (!simData || !simData.node_ids || simData.node_ids.length < 2) {
        var msg = document.createElement("p"); msg.className = "text-muted";
        msg.textContent = "Not enough data to build a structural similarity matrix (requires at least 2 channels with computed measures).";
        container.appendChild(msg);
        return;
    }

    var n = simData.node_ids.length;
    var m = (simData.measures || []).length;

    // ── Preamble ──────────────────────────────────────────────────────────────
    if (meta) {
        var pEl = document.createElement("p"); pEl.className = "table-preamble";
        var parts = ["Network of " + fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " edges."];
        if (meta.start_date || meta.end_date)
            parts.push("Data range: " + (meta.start_date || "–") + " to " + (meta.end_date || "present") + ".");
        parts.push("Exported " + meta.export_date + ".");
        pEl.textContent = parts.join(" ");
        container.appendChild(pEl);
    }

    var noteEl = document.createElement("p"); noteEl.className = "text-muted small mb-2";
    noteEl.textContent = n + " × " + n + " channels — " + m + " measure" + (m !== 1 ? "s" : "") +
        " used (min-max normalised per measure; None → 0). Cosine similarity; range 0–1." +
        " Lower triangle; diagonal = 1 (self-similarity).";
    container.appendChild(noteEl);

    // ── Sort controls ─────────────────────────────────────────────────────────
    var stratKeys = communities ? Object.keys(communities.strategies || {}) : [];
    var controlsDiv = document.createElement("div");
    controlsDiv.className = "d-flex flex-wrap align-items-end gap-3 mb-3";

    // Sort-by select
    var sortWrap = document.createElement("div");
    var sortLbl = document.createElement("label");
    sortLbl.className = "form-label mb-1 d-block fw-semibold small"; sortLbl.textContent = "Sort by";
    var sortSel = document.createElement("select"); sortSel.className = "form-select form-select-sm"; sortSel.style.width = "auto";
    sortSel.appendChild(new Option("Community", "community"));
    (simData.measures || []).forEach(function(m) { sortSel.appendChild(new Option(m[1], "measure:" + m[0])); });
    sortSel.value = (sortMode === "community") ? "community" : ("measure:" + sortMeasureKey);
    sortWrap.appendChild(sortLbl); sortWrap.appendChild(sortSel); controlsDiv.appendChild(sortWrap);

    // Community-strategy select (shown only when Sort = Community)
    var stratWrap = document.createElement("div");
    var stratLbl = document.createElement("label");
    stratLbl.className = "form-label mb-1 d-block fw-semibold small"; stratLbl.textContent = "Strategy";
    var stratSel = document.createElement("select"); stratSel.className = "form-select form-select-sm"; stratSel.style.width = "auto";
    stratSel.appendChild(new Option("All", ""));
    stratKeys.forEach(function(sk) { stratSel.appendChild(new Option(_strat_label(sk), sk)); });
    stratSel.value = stratKey || "";
    if (sortMode !== "community") stratWrap.style.display = "none";
    stratWrap.appendChild(stratLbl); stratWrap.appendChild(stratSel); controlsDiv.appendChild(stratWrap);

    container.appendChild(controlsDiv);

    // ── Color legend ──────────────────────────────────────────────────────────
    var legDiv = document.createElement("div");
    legDiv.className = "mb-3 d-flex align-items-center gap-2";
    legDiv.style.fontSize = "11px";
    legDiv.appendChild(document.createTextNode("Similarity → "));
    var gradBox = document.createElement("div");
    gradBox.style.cssText = "width:120px;height:12px;background:linear-gradient(to right,#fff,rgb(70,130,180));border:1px solid #ccc;display:inline-block;vertical-align:middle;";
    legDiv.appendChild(gradBox);
    var legLbls = document.createElement("span"); legLbls.textContent = "0 – 1.0"; legLbls.style.color = "#555";
    legDiv.appendChild(legLbls);
    container.appendChild(legDiv);

    // ── Build sorted order ────────────────────────────────────────────────────
    var channelNodes = (channelData && channelData.nodes) ? channelData.nodes : null;
    var order = _sorted_indices(simData, channelNodes, communities, sortMode, sortMeasureKey, stratKey);

    // ── SVG heatmap ───────────────────────────────────────────────────────────
    var NS = "http://www.w3.org/2000/svg";
    var cellSize = Math.max(4, Math.min(14, Math.floor(520 / n)));
    var labelW = 140, topPad = 4, bottomPad = 110;
    var fontSize = Math.max(7, Math.min(11, cellSize - 1));

    var scrollDiv = document.createElement("div"); scrollDiv.style.cssText = "overflow-x:auto;";
    var svgW = labelW + n * cellSize, svgH = topPad + n * cellSize + bottomPad;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", svgW); svg.setAttribute("height", svgH); svg.style.cssText = "display:block;";

    // Grid lines
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

    // Upper-right triangle mask (same polygon as consensus_matrix.js)
    var triPts = [labelW + "," + topPad, (labelW + n * cellSize) + "," + topPad, (labelW + n * cellSize) + "," + (topPad + n * cellSize)];
    for (var si = n - 1; si >= 0; si--) {
        triPts.push((labelW + si * cellSize) + "," + (topPad + (si + 1) * cellSize));
        triPts.push((labelW + si * cellSize) + "," + (topPad + si * cellSize));
    }
    var triPoly = document.createElementNS(NS, "polygon");
    triPoly.setAttribute("points", triPts.join(" ")); triPoly.setAttribute("fill", "#f2f2f2");
    svg.appendChild(triPoly);

    // Row labels (left)
    for (var li = 0; li < n; li++) {
        var lbl = simData.node_labels[order[li]] || simData.node_ids[order[li]];
        var tx = document.createElementNS(NS, "text");
        tx.setAttribute("x", labelW - 4); tx.setAttribute("y", topPad + li * cellSize + cellSize / 2);
        tx.setAttribute("dy", "0.35em"); tx.setAttribute("text-anchor", "end");
        tx.setAttribute("font-size", fontSize); tx.setAttribute("fill", "#333");
        var trunc = lbl.length > 22 ? lbl.slice(0, 20) + "…" : lbl;
        tx.textContent = trunc;
        if (trunc !== lbl) { var ttl = document.createElementNS(NS, "title"); ttl.textContent = lbl; tx.appendChild(ttl); }
        svg.appendChild(tx);
    }

    // Column labels (bottom, rotated)
    for (var lj = 0; lj < n; lj++) {
        var lbl2 = simData.node_labels[order[lj]] || simData.node_ids[order[lj]];
        var cx = labelW + lj * cellSize + cellSize / 2, cy2 = topPad + n * cellSize + 4;
        var tx2 = document.createElementNS(NS, "text");
        tx2.setAttribute("x", cx); tx2.setAttribute("y", cy2); tx2.setAttribute("text-anchor", "end");
        tx2.setAttribute("font-size", fontSize); tx2.setAttribute("fill", "#333");
        tx2.setAttribute("transform", "rotate(-45 " + cx + " " + cy2 + ")");
        var trunc2 = lbl2.length > 22 ? lbl2.slice(0, 20) + "…" : lbl2;
        tx2.textContent = trunc2;
        if (trunc2 !== lbl2) { var ttl2 = document.createElementNS(NS, "title"); ttl2.textContent = lbl2; tx2.appendChild(ttl2); }
        svg.appendChild(tx2);
    }

    // Heatmap cells (lower triangle only: row > col)
    var rectG = document.createElementNS(NS, "g");
    for (var ri = 0; ri < n; ri++) {
        for (var rj = 0; rj < n; rj++) {
            if (ri < rj) continue;  // upper triangle → masked
            var origI = order[ri], origJ = order[rj];
            var v = _sim(simData.cells_lower, origI, origJ);
            var rect = document.createElementNS(NS, "rect");
            rect.setAttribute("x", labelW + rj * cellSize);
            rect.setAttribute("y", topPad + ri * cellSize);
            rect.setAttribute("width", cellSize);
            rect.setAttribute("height", cellSize);
            rect.setAttribute("fill", ri === rj ? "#64748b" : _simColor(v));
            if (ri !== rj) {
                (function(lA, lB, val) {
                    rect.addEventListener("mouseenter", function(e) { _showTip(e, lA + " × " + lB + ": " + val.toFixed(4)); });
                    rect.addEventListener("mousemove", _moveTip);
                })(simData.node_labels[origI] || origI, simData.node_labels[origJ] || origJ, v);
            }
            rectG.appendChild(rect);
        }
    }
    rectG.addEventListener("mouseleave", _hideTip);
    svg.appendChild(rectG);

    scrollDiv.appendChild(svg);
    container.appendChild(scrollDiv);

    // ── Wire up controls ──────────────────────────────────────────────────────
    sortSel.addEventListener("change", function() {
        var val = sortSel.value;
        if (val === "community") {
            stratWrap.style.display = "";
            _render(simData, channelData, communities, meta, "community", null, stratSel.value || null);
        } else {
            stratWrap.style.display = "none";
            _render(simData, channelData, communities, meta, "measure", val.replace("measure:", ""), null);
        }
    });
    stratSel.addEventListener("change", function() {
        _render(simData, channelData, communities, meta, "community", null, stratSel.value || null);
    });
}

// ── Initial load ───────────────────────────────────────────────────────────────
Promise.all([
    fetch(_dd + "structural_similarity.json").then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
    fetch(_dd + "channels.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    fetch(_dd + "communities.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    fetch(_dd + "meta.json").then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
]).then(function(results) {
    _render(results[0], results[1], results[2], results[3], "community", null, null);
}).catch(function(err) {
    var el = document.getElementById("structural-similarity-container");
    if (el) el.textContent = "Failed to load data.";
    console.error("structural_similarity:", err);
});
