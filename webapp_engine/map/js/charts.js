// Mini histogram SVG shared across table pages.
// all_val_str: string value for the "All" (full-range) bar, or null.
// yr_vals:     [{year: period key, value: string|null}] — per-period values.
// cur:         currently highlighted period key (or "all").
// all_years:   ordered array of period keys; reserves a slot per period so all
//              SVGs have identical width even when some periods have no data.
// Bars narrow as periods multiply (a quarterly or monthly timeline) so a sparkline stays about
// MAX_W pixels wide.
var MAX_W = 160;

import { arrMax, arrMin } from './utils.js';

// ── Histogram bins ──────────────────────────────────────────────────────────────
// Bins for one or more series of non-negative values (a strength, a degree), shared by the network and the
// comparison pages. The bin width is a "nice" number (1, 2, 2.5 or 5 × a power of ten) picked from the largest
// value so the range falls into about HISTOGRAM_BINS bins; whole numbers get whole bins ("0–9", or "3" when
// the width is 1). Returns {labels, counts: [one array per series]}.
var HISTOGRAM_BINS = 20;

function _binWidth(max, whole) {
    var raw = max / HISTOGRAM_BINS;
    var magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    var best = null,
        bestGap = Infinity;
    [1, 2, 2.5, 5, 10, 20, 25, 50].forEach(function(step) {
        var width = step * magnitude;
        if (whole && (width < 1 || width !== Math.round(width))) return;
        var gap = Math.abs(Math.ceil(max / width) - HISTOGRAM_BINS);
        if (gap < bestGap) {
            best = width;
            bestGap = gap;
        }
    });
    return best || (whole ? 1 : raw);
}

// Decimals needed to write a bin edge of this width exactly (0.25 → 2).
function _edgeDecimals(width) {
    for (var d = 0; d < 8; d++) {
        var scaled = width * Math.pow(10, d);
        if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return d;
    }
    return 8;
}

export function histogram(series) {
    var max = 0,
        whole = true;
    series.forEach(function(values) {
        values.forEach(function(v) {
            if (v > max) max = v;
            if (v !== Math.round(v)) whole = false;
        });
    });
    if (!(max > 0)) return { labels: ["0"], counts: series.map(function(values) { return [values.length]; }) };
    var width = _binWidth(max, whole);
    var bins = Math.floor(max / width + 1e-9) + 1;
    var decimals = _edgeDecimals(width);
    var labels = [];
    for (var i = 0; i < bins; i++) {
        if (whole && width === 1) labels.push(fmtInt(i));
        else if (whole) labels.push(fmtInt(i * width) + "–" + fmtInt((i + 1) * width - 1));
        else labels.push(fmtFixed(i * width, decimals) + "–" + fmtFixed((i + 1) * width, decimals));
    }
    var counts = series.map(function(values) {
        var c = new Array(bins).fill(0);
        values.forEach(function(v) { c[Math.min(bins - 1, Math.max(0, Math.floor(v / width + 1e-9)))]++; });
        return c;
    });
    return { labels: labels, counts: counts };
}

// ── Power-law fit ───────────────────────────────────────────────────────────────
// Least-squares line through the points on log–log axes ({slope, intercept} of log y on log x), over the points
// with both coordinates positive; null with fewer than two of them or no spread in x.
export function power_law_fit(points) {
    var pts = points.filter(function(p) { return p.x > 0 && p.y > 0; });
    if (pts.length < 2) return null;
    var n = pts.length,
        sumX = 0,
        sumY = 0,
        sumXY = 0,
        sumX2 = 0;
    pts.forEach(function(p) {
        var lx = Math.log(p.x),
            ly = Math.log(p.y);
        sumX += lx;
        sumY += ly;
        sumXY += lx * ly;
        sumX2 += lx * lx;
    });
    var d = n * sumX2 - sumX * sumX;
    if (!d) return null;
    var slope = (n * sumXY - sumX * sumY) / d;
    return { slope: slope, intercept: (sumY - slope * sumX) / n };
}

// A value as the tables write it ("5,183", "0.3427", "—") as a number; NaN when it is none.
function _number(raw) {
    return parseFloat(String(raw == null ? "" : raw).replace(/,/g, ""));
}

export function mini_hist(all_val_str, yr_vals, cur, all_years) {
    var slots = (all_years || []).length + 1;
    var GAP = slots > 40 ? 1 : 2;
    var BAR_W = Math.max(1, Math.min(7, Math.floor((MAX_W + GAP) / slots) - GAP)),
        H = 20,
        ns = "http://www.w3.org/2000/svg";
    var yr_val_map = {};
    (yr_vals || []).forEach(function(y) { yr_val_map[y.year] = y.value; });
    var bars = [{ year: "all", raw: all_val_str }]
        .concat((all_years || []).map(function(yr) {
            return { year: yr, raw: yr_val_map[yr] !== undefined ? yr_val_map[yr] : null };
        }));
    var valid = bars.map(function(b) { return _number(b.raw); }).filter(Number.isFinite);
    if (!valid.length) return null;
    var lo = Math.min(0, arrMin(valid));
    var hi = Math.max(0, arrMax(valid));
    var span = hi - lo;
    if (!span) return null;
    var base = Math.round(hi / span * H);
    var W = bars.length * (BAR_W + GAP) - GAP;
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.style.cssText = "display:block;flex-shrink:0";
    bars.forEach(function(b, i) {
        var v = _number(b.raw);
        if (!isFinite(v)) return;
        var bh = Math.max(1, Math.round(Math.abs(v) / span * H));
        var by = v >= 0 ? base - bh : base;
        var is_all = b.year === "all";
        var is_cur = is_all ? cur === "all" : cur === b.year;
        var r = document.createElementNS(ns, "rect");
        r.setAttribute("x", i * (BAR_W + GAP));
        r.setAttribute("y", by);
        r.setAttribute("width", BAR_W);
        r.setAttribute("height", bh);
        // Theme colours: the period on show in the accent, the whole range lighter, the other periods muted.
        r.style.fill = is_cur ? "var(--accent)" : (is_all ? "color-mix(in srgb, var(--accent) 45%, var(--surface))" : "var(--muted)");
        if (!is_cur && !is_all) r.style.opacity = "0.55";
        var t = document.createElementNS(ns, "title");
        t.textContent = (is_all ? "All periods" : b.year) + ": " + b.raw;
        r.appendChild(t);
        svg.appendChild(r);
    });
    if (lo < 0 && hi > 0) {
        var line = document.createElementNS(ns, "line");
        line.setAttribute("x1", 0);
        line.setAttribute("y1", base);
        line.setAttribute("x2", W);
        line.setAttribute("y2", base);
        line.style.stroke = "var(--muted)";
        line.setAttribute("stroke-width", "0.5");
        svg.appendChild(line);
    }
    return svg;
}
