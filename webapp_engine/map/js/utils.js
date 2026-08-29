export function escHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Fetch JSON, rejecting on any non-2xx response. Use for required resources.
export function fetchJson(url) {
    return fetch(url).then(function(r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
    });
}

// Fetch JSON, resolving to null on a missing resource or network error.
// Use for optional resources (meta.json, timeline.json, …) the page tolerates.
export function fetchJsonOrNull(url) {
    return fetch(url)
        .then(function(r) { return r.ok ? r.json() : null; })
        .catch(function() { return null; });
}

// Min / max over an array WITHOUT spreading it through Function.prototype.apply.
// `Math.min.apply(null, arr)` / `Math.max.apply(null, arr)` push every element as a
// separate argument and throw a RangeError once the array exceeds the engine's
// argument-count limit (~10^5) — reachable on large graphs, where these run over
// one value per node. The reduce-style loop has no such ceiling. Semantics match
// Math.min/Math.max on the empty array (Infinity / -Infinity).
export function arrMin(arr) {
    var m = Infinity;
    for (var i = 0; i < arr.length; i++) { if (arr[i] < m) m = arr[i]; }
    return m;
}
export function arrMax(arr) {
    var m = -Infinity;
    for (var i = 0; i < arr.length; i++) { if (arr[i] > m) m = arr[i]; }
    return m;
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

// ── Environment-depth colouring ───────────────────────────────────────────────
// communities.json may carry, next to `strategies`, a `colorings` object with the
// environment-depth entry (key ENV_DEPTH_KEY; mirrors network.exporter.ENVIRONMENT_DEPTH_KEY).
// It has the strategy shape — groups of [depth, count, label, hexColor] — but is not a community
// partition: nodes carry the numeric `environment_depth` attribute instead of a `communities`
// entry, and its colours are left empty by the exporter so they can be derived at runtime from the
// active theme's canvas (see depthPalette). The viewers merge it into their colour-by selector.
export var ENV_DEPTH_KEY = 'environment_depth';

// Legend label of one depth value; mirrors network.exporter.environment_depth_label.
export function envDepthLabel(depth) {
    return Number(depth) === 0 ? 'In target' : 'Depth ' + depth;
}

// The group label a node falls under for `strategy` — a community label for a real strategy, the
// depth label for the environment-depth colouring. One lookup for colouring, legend filtering,
// anchors and tooltips so they can never disagree.
export function groupLabelOf(node, strategy) {
    if (strategy === ENV_DEPTH_KEY) {
        var d = node.environment_depth;
        return (d === null || d === undefined) ? '' : envDepthLabel(d);
    }
    return (node.communities && node.communities[strategy]) || '';
}

// Parse '#rrggbb', '#rgb', 'rgb(...)' or 'rgba(...)' into [r, g, b] (0–255).
export function cssColorToRgb(css) {
    var s = String(css || '').trim();
    var m = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (m) {
        var h = m[1].length === 3 ? m[1].split('').map(function(c) { return c + c; }).join('') : m[1];
        return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    m = s.match(/(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    return m ? [+m[1], +m[2], +m[3]] : [17, 34, 51];
}

function _rgbToHsl(rgb) {
    var r = rgb[0] / 255,
        g = rgb[1] / 255,
        b = rgb[2] / 255;
    var max = Math.max(r, g, b),
        min = Math.min(r, g, b);
    var l = (max + min) / 2,
        h = 0,
        s = 0;
    if (max !== min) {
        var d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        else if (max === g) h = ((b - r) / d + 2) / 6;
        else h = ((r - g) / d + 4) / 6;
    }
    return [h * 360, s, l];
}

function _hslToHex(h, s, l) {
    h = ((h % 360) + 360) % 360 / 360;

    function f(p, q, t) {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1 / 6) return p + (q - p) * 6 * t;
        if (t < 1 / 2) return q;
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
        return p;
    }
    var q = l < 0.5 ? l * (1 + s) : l + s - l * s,
        p = 2 * l - q;
    var rgb = [f(p, q, h + 1 / 3), f(p, q, h), f(p, q, h - 1 / 3)];
    return '#' + rgb.map(function(v) { return ('0' + Math.round(v * 255).toString(16)).slice(-2); }).join('');
}

// `n` colours that stay apart from each other and from the background `bgCss`: hues evenly spread
// around the wheel and rotated so the background's own hue falls midway between two of them (as far
// from every palette hue as n allows), fully saturated, with the lightness chosen against the
// background — light colours on a dark canvas, dark ones on a light canvas — so the contrast holds
// in every theme. Deterministic: the same n and background always give the same colours.
export function depthPalette(n, bgCss) {
    var hsl = _rgbToHsl(cssColorToRgb(bgCss));
    var darkBg = hsl[2] < 0.5;
    var lightness = darkBg ? 0.68 : 0.40;
    var colors = [];
    for (var i = 0; i < n; i++) {
        var hue = hsl[0] + 180 / n + i * 360 / n;
        colors.push(_hslToHex(hue, 0.85, lightness));
    }
    return colors;
}

// `strategies` merged with the runtime-coloured colourings of a communities.json payload: every
// colouring's groups get their colour from depthPalette() against `bgCss`. Returns a new object;
// the strategies themselves are shared, the colouring entries are copies.
export function mergeColorings(communities, bgCss) {
    var merged = {};
    for (var key in communities.strategies || {}) merged[key] = communities.strategies[key];
    var colorings = communities.colorings || {};
    for (var ckey in colorings) {
        var groups = (colorings[ckey].groups || []);
        var palette = depthPalette(groups.length, bgCss);
        merged[ckey] = Object.assign({}, colorings[ckey], {
            groups: groups.map(function(g, i) { return [g[0], g[1], g[2], palette[i]]; }),
        });
    }
    return merged;
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
    if (positive.length < 2) return function() { return basePx; };

    positive.sort(function(a, b) { return a - b; });

    function quantile(p) {
        var idx = Math.round(p * (positive.length - 1));
        return positive[Math.min(positive.length - 1, Math.max(0, idx))];
    }
    var lo = quantile(0.02);
    var hi = quantile(0.98);
    // Percentile band collapsed (most weights identical): fall back to the full
    // range; if that is degenerate too, give up and return a uniform thickness.
    if (hi <= lo) {
        lo = positive[0];
        hi = positive[positive.length - 1];
    }
    if (hi <= lo) return function() { return basePx; };

    var loLog = Math.log(lo);
    var span = Math.log(hi) - loLog;
    return function(w) {
        if (!(w > 0) || !isFinite(w)) return minPx;
        var clamped = w < lo ? lo : (w > hi ? hi : w);
        var t = (Math.log(clamped) - loLog) / span;
        return minPx + t * (maxPx - minPx);
    };
}
