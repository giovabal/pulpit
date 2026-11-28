export function escHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// An algorithmic community is stored as "<n>-<method key>" ("3-leiden_directed"): pages show its number. A label
// group's community is the label's own name and is shown as it is.
export function communityName(label) {
    var m = /^(\d+)-[a-z0-9_]+$/.exec(String(label == null ? "" : label));
    return m ? m[1] : String(label == null ? "" : label);
}

// The scope line a table page opens with: what the figures below cover. `extra` adds the page's own sentences.
export function scopeLine(meta, extra) {
    var p = document.createElement("p");
    p.className = "table-preamble";
    if (!meta) return p;
    var text = fmtInt(meta.total_nodes) + " channels and " + fmtInt(meta.total_edges) + " ties";
    if (meta.start_date || meta.end_date) text += ", " + (meta.start_date || "…") + " to " + (meta.end_date || "…");
    text += ". A tie points from the citing channel to the cited one";
    if (meta.edge_weight_label) text += "; its weight is the " + meta.edge_weight_label;
    text += ".";
    (extra || []).forEach(function(sentence) {
        if (sentence) text += " " + sentence;
    });
    p.textContent = text;
    return p;
}

// One way to say a page could not read its data, used by every page: a notice at the top of the page, with every
// "Loading…" placeholder cleared. `what` names what failed for the reader ("the data of 2024"), by default the
// page's data. (A page opened straight from a folder gets its own notice from page.js.)
var LOAD_FAILURE_ID = "export-load-failure";

export function loadFailed(err, what) {
    if (err) console.error("Pulpit page:", err);
    var main = document.getElementById("main-content");
    if (!main) return;
    var notice = document.getElementById(LOAD_FAILURE_ID);
    if (!notice) {
        notice = document.createElement("p");
        notice.id = LOAD_FAILURE_ID;
        notice.className = "export-notice export-notice--error";
        notice.setAttribute("role", "alert");
        var head = main.querySelector(".export-page-head");
        main.insertBefore(notice, head ? head.nextSibling : main.firstChild);
    }
    var status = err && /^\d+$/.test(String(err.message || "")) ? " (the server answered " + err.message + ")" : "";
    notice.textContent = "This page could not load " + (what || "its data") + status +
        ". Reload the page; if it still fails, a data file of the analysis is missing.";
    Array.prototype.forEach.call(main.querySelectorAll("p, span, div, td"), function(el) {
        if (el.children.length === 0 && el.textContent.trim() === "Loading…") el.textContent = "";
    });
}

// A later load worked (another period): the failure notice goes.
export function loadRecovered() {
    var notice = document.getElementById(LOAD_FAILURE_ID);
    if (notice) notice.remove();
}

// The most frequent of `values` (null and undefined left out), the first met on a tie; "" when there is none.
export function plurality(values) {
    var counts = {};
    var best = "",
        bestN = 0;
    values.forEach(function(v) {
        if (v === null || v === undefined) return;
        counts[v] = (counts[v] || 0) + 1;
    });
    Object.keys(counts).forEach(function(v) {
        if (counts[v] > bestN) {
            best = v;
            bestN = counts[v];
        }
    });
    return best;
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

// ── Timeline ────────────────────────────────────────────────────────────────────
// timeline.json (data/timeline.json, data_coordination/timeline.json) lists the exported periods —
// calendar years, quarters, months or sliding windows — each with a `key` (its data_<key>/ directory) and a
// display `label`. Older exports listed `years: [{year, …}]`; both shapes normalise to
// {step, windowMonths, overlapping, periods: [{key, label, …}], events: [{date, subject, period_key, …}]}.
export function readTimeline(json) {
    if (!json) return { step: null, windowMonths: null, overlapping: false, periods: [], events: [] };
    var periods = json.periods || (json.years || []).map(function(y) {
        return Object.assign({}, y, { key: String(y.year), label: String(y.year) });
    });
    return {
        step: json.step || "year",
        windowMonths: json.window_months || null,
        overlapping: !!json.overlapping,
        periods: periods.map(function(p) { return Object.assign({}, p, { key: String(p.key) }); }),
        events: json.events || [],
    };
}

// The data directory of one period of the page's base directory: data/ → data_<key>/,
// data_coordination/ → data_coordination_<key>/.
export function periodDataDir(base, key) {
    return String(base).replace(/\/+$/, "") + "_" + key + "/";
}

// A compare page reads the other export from data_2/ — it carries no timeline of its own (its period
// directories were never copied), so it shows the full range only.
export function isCompareDataDir(dd) {
    return /(^|\/)data_2\/$/.test(String(dd || ""));
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

// Black or white, whichever reads better as text on the colour `css` (WCAG relative luminance).
export function readableTextOn(css) {
    var lin = cssColorToRgb(css).map(function(v) {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    var luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
    // Contrast with black is (L + 0.05) / 0.05, with white 1.05 / (L + 0.05): black wins above L ≈ 0.179.
    return luminance > 0.179 ? "#000000" : "#ffffff";
}

// ── Map theme ────────────────────────────────────────────────────────────────────
// A map starts in the light or dark theme the reader chose on the export's other pages (the shared
// ``pulpit_theme`` key), dark when no choice was made; picking light or dark on a map becomes that choice.
// The other map themes are display styles of the map alone and are not remembered.
var THEME_STORAGE_KEY = 'pulpit_theme';

export function initialMapTheme() {
    var pref = null;
    try { pref = localStorage.getItem(THEME_STORAGE_KEY); } catch (e) { pref = null; }
    if (pref === 'light') return 'light';
    if (pref === 'auto') return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    return 'dark';
}

export function rememberMapTheme(themeKey) {
    if (themeKey !== 'light' && themeKey !== 'dark') return;
    try { localStorage.setItem(THEME_STORAGE_KEY, themeKey); } catch (e) { /* storage refused: nothing to remember */ }
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
