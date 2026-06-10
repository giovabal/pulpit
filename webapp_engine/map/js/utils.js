export function escHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Fetch JSON, rejecting on any non-2xx response. Use for required resources.
export function fetchJson(url) {
    return fetch(url).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
    });
}

// Fetch JSON, resolving to null on a missing resource or network error.
// Use for optional resources (meta.json, timeline.json, …) the page tolerates.
export function fetchJsonOrNull(url) {
    return fetch(url)
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
}

// communities[strategy].groups holds rows of [id, count, label, hexColor];
// build a {strategy: {label: hexColor}} lookup used for node colouring.
export function buildCommunityColorMaps(communities) {
    var maps = {};
    for (var strategy in communities) {
        maps[strategy] = {};
        var groups = communities[strategy].groups;
        for (var i = 0; i < groups.length; i++) {
            maps[strategy][groups[i][2]] = groups[i][3];
        }
    }
    return maps;
}

// Component-wise average of two [r, g, b] colours, scaled by `factor`
// (used to darken blended edge colours). Returns unrounded floats; callers
// round for 0–255 space or pass straight into 0–1 colour objects.
export function avgColor(c1, c2, factor) {
    return [
        (c1[0] + c2[0]) / 2 * factor,
        (c1[1] + c2[1]) / 2 * factor,
        (c1[2] + c2[2]) / 2 * factor,
    ];
}

// Build an outlier-robust, log-scaled mapping from raw edge weights to a line
// thickness in [minPx, maxPx]. Returns a function weight → thickness.
//
// Edge weights are heavily right-skewed and their absolute scale depends on the
// export's edge-weight strategy (unweighted → every weight 1, raw counts →
// integers, the partial strategies → small fractions spanning several orders of
// magnitude). To stay "visually acceptable at any scale" the mapping:
//   1. takes logarithms, compressing the long upper tail so a handful of very
//      heavy edges don't flatten everyone else to a hairline;
//   2. clamps to the [p2, p98] percentile band so a single extreme edge can't
//      stretch the whole scale;
//   3. linearly maps the clamped log value into [minPx, maxPx].
// When there is no usable spread (every weight equal — e.g. the unweighted
// strategy, or a graph with a single edge) every edge maps to basePx, so the
// "show edge weight" toggle degrades to a sensible uniform thickness instead of
// dividing by zero.
export function makeEdgeWidthScale(weights, minPx, maxPx, basePx) {
    var positive = [];
    for (var i = 0; i < weights.length; i++) {
        var w = weights[i];
        if (w > 0 && isFinite(w)) positive.push(w);
    }
    if (positive.length < 2) return function () { return basePx; };

    positive.sort(function (a, b) { return a - b; });
    function quantile(p) {
        var idx = Math.round(p * (positive.length - 1));
        return positive[Math.min(positive.length - 1, Math.max(0, idx))];
    }
    var lo = quantile(0.02);
    var hi = quantile(0.98);
    // Percentile band collapsed (most weights identical): fall back to the full
    // range; if that is degenerate too, give up and return a uniform thickness.
    if (hi <= lo) { lo = positive[0]; hi = positive[positive.length - 1]; }
    if (hi <= lo) return function () { return basePx; };

    var loLog = Math.log(lo);
    var span = Math.log(hi) - loLog;
    return function (w) {
        if (!(w > 0) || !isFinite(w)) return minPx;
        var clamped = w < lo ? lo : (w > hi ? hi : w);
        var t = (Math.log(clamped) - loLog) / span;
        return minPx + t * (maxPx - minPx);
    };
}
