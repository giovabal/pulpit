// Shared SVG zoom/pan and tooltip helpers used by structural_similarity.js
// and consensus_matrix.js. Drag listeners are bound to `document` only while
// the user is actively dragging, so calling addSvgZoomPan on each render does
// not leak listeners.

var NS = "http://www.w3.org/2000/svg";

export function addSvgZoomPan(container, scrollDiv, svg) {
    var g = document.createElementNS(NS, "g");
    while (svg.firstChild) g.appendChild(svg.firstChild);
    svg.appendChild(g);

    var scale = 1, tx = 0, ty = 0;
    var startX = 0, startY = 0, startTx = 0, startTy = 0;

    function applyTransform() {
        g.setAttribute("transform", "translate(" + tx + "," + ty + ") scale(" + scale + ")");
    }
    function zoomTo(factor, cx, cy) {
        var ns = Math.max(0.1, Math.min(50, scale * factor));
        tx = cx - (cx - tx) * (ns / scale);
        ty = cy - (cy - ty) * (ns / scale);
        scale = ns; applyTransform();
    }

    function onMouseMove(e) {
        tx = startTx + (e.clientX - startX);
        ty = startTy + (e.clientY - startY);
        applyTransform();
    }
    function onMouseUp() {
        svg.style.cursor = "grab";
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
    }

    svg.addEventListener("wheel", function(e) {
        e.preventDefault();
        var r = svg.getBoundingClientRect();
        zoomTo(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    svg.addEventListener("mousedown", function(e) {
        if (e.button !== 0) return;
        startX = e.clientX; startY = e.clientY; startTx = tx; startTy = ty;
        svg.style.cursor = "grabbing"; e.preventDefault();
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    });
    svg.style.cursor = "grab";

    var ctrl = document.createElement("div");
    ctrl.style.cssText = "display:flex;gap:4px;margin-bottom:6px;";
    [["＋", "Zoom in",  function() { var r = svg.getBoundingClientRect(); zoomTo(1.4, r.width / 2, r.height / 2); }],
     ["－", "Zoom out", function() { var r = svg.getBoundingClientRect(); zoomTo(1 / 1.4, r.width / 2, r.height / 2); }],
     ["↺",  "Reset",    function() { scale = 1; tx = 0; ty = 0; applyTransform(); }]
    ].forEach(function(b) {
        var btn = document.createElement("button");
        btn.type = "button"; btn.className = "btn btn-outline-secondary btn-sm";
        btn.style.cssText = "padding:1px 10px;font-size:13px;line-height:1.4;";
        btn.textContent = b[0]; btn.title = b[1];
        btn.addEventListener("click", b[2]);
        ctrl.appendChild(btn);
    });
    container.insertBefore(ctrl, scrollDiv);
}

// Lazily-created shared tooltip. Lives at document.body level so it can sit
// above any SVG; reused across renders.
var _tip = null;
function _ensure_tip() {
    if (_tip) return _tip;
    _tip = document.createElement("div");
    _tip.style.cssText = "position:fixed;background:rgba(0,0,0,.78);color:#fff;font-size:11px;"
        + "padding:3px 8px;border-radius:3px;pointer-events:none;display:none;z-index:9999;white-space:nowrap;";
    document.body.appendChild(_tip);
    return _tip;
}
export function showTip(e, txt) {
    var t = _ensure_tip();
    t.textContent = txt;
    t.style.display = "block";
    // Mouse events carry clientX/Y; focus events (keyboard a11y, wired by the matrix views) do not —
    // fall back to the focused element's box so the tooltip isn't positioned at NaNpx.
    var x = e.clientX, y = e.clientY;
    if (x === undefined || y === undefined) {
        var r = e.target && e.target.getBoundingClientRect ? e.target.getBoundingClientRect() : null;
        if (r) { x = r.left + r.width / 2; y = r.top; }
        else { x = 0; y = 0; }
    }
    t.style.left = (x + 14) + "px";
    t.style.top  = (y - 30) + "px";
}
export function moveTip(e) {
    var t = _ensure_tip();
    t.style.left = (e.clientX + 14) + "px";
    t.style.top  = (e.clientY - 30) + "px";
}
export function hideTip() {
    if (_tip) _tip.style.display = "none";
}
