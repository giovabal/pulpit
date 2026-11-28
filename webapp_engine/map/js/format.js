/* exported MISSING, isNil, sigFig, fmtInt, fmtFixed, fmtShare, fmtP, pText, sigStars, sigLegend, qHtml, heatmapBg, divergingHeatmapBg, pulpitTheme */
// One way to write every number of the export pages, loaded by every table page before the page scripts.
//
//   missing      "—" for a value that does not exist (null, undefined, NaN, ±∞, text that is no number):
//                never "0", never "n/a", never "NaN"
//   zero         "0", "0.00", "0.0%": a value that rounds to zero carries no minus sign
//   integers     fmtInt: thousands separators, the same whatever the reader's browser language
//   decimals     sigFig (3 significant figures by default), fmtFixed (a fixed number of decimals)
//   shares       fmtShare: a 0–1 fraction as a percentage with one decimal
//   p and q      fmtP: three decimals, "< 0.001" below that; pText writes it in a sentence ("p < 0.001")
//   significance sigStars on q (Benjamini–Hochberg) wherever a q exists, on p otherwise; sigLegend says which;
//                qHtml is a q-value with its stars, for a table cell
//
// Tints and chart colours come from the theme's CSS custom properties (tables.css), so they follow the light and
// dark themes; pulpitTheme() reads them, and Chart.js defaults are set from them as soon as this script runs.

var MISSING = "—";
// Strongest cell tint, in percent of the tint colour over the surface: enough to rank, light enough to read.
var HEAT_MAX = 26;
var DIVERGING_MAX = 32;
var NUMBER_LOCALE = "en-GB";

function isNil(val) {
    return val === null || val === undefined || (typeof val === "number" && !isFinite(val)) || val === "";
}

// The value as a finite number, or null when there is none to write: a missing value, or text that is no number.
function _number(val) {
    if (isNil(val) || (typeof val === "string" && val.trim() === "")) return null;
    var num = Number(val);
    return isFinite(num) ? num : null;
}

// "-0", "-0.00": a value that rounds to zero is written without its sign.
function _unsignedZero(text) {
    return /^-0(\.0*)?$/.test(text) ? text.slice(1) : text;
}

var _intFormat = new Intl.NumberFormat(NUMBER_LOCALE, { maximumFractionDigits: 0 });

function fmtInt(val) {
    var num = _number(val);
    if (num === null) return MISSING;
    return _unsignedZero(_intFormat.format(Math.round(num)));
}

function sigFig(val, n) {
    var num = _number(val);
    if (num === null) return MISSING;
    if (num === 0) return "0";
    var digits = n || 3;
    if (Math.abs(num) < 1e-4) return num.toExponential(digits - 1);
    return Number(num.toPrecision(digits)).toLocaleString(NUMBER_LOCALE, { maximumSignificantDigits: digits });
}

function fmtFixed(val, decimals) {
    var num = _number(val);
    if (num === null) return MISSING;
    var d = decimals === undefined ? 2 : decimals;
    return _unsignedZero(num.toLocaleString(NUMBER_LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d }));
}

function fmtShare(val, decimals) {
    var num = _number(val);
    if (num === null) return MISSING;
    var places = decimals === undefined ? 1 : decimals;
    var pct = num * 100;
    // A share too small to show at this precision is not a zero: "< 0.1%".
    var floor = Math.pow(10, -places);
    if (pct > 0 && pct < floor / 2) return "< " + fmtFixed(floor, places) + "%";
    return fmtFixed(pct, places) + "%";
}

function fmtP(val) {
    var num = _number(val);
    if (num === null) return MISSING;
    if (num < 0.001) return "< 0.001";
    return num.toFixed(3);
}

// A p-value (or, with `symbol`, a q-value) inside a sentence: "p < 0.001", "p = 0.012".
function pText(val, symbol) {
    var name = symbol || "p";
    var num = _number(val);
    if (num === null) return name + " = " + MISSING;
    return num < 0.001 ? name + " < 0.001" : name + " = " + num.toFixed(3);
}

function sigStars(val) {
    var num = _number(val);
    if (num === null) return "";
    if (num < 0.001) return "***";
    if (num < 0.01) return "**";
    if (num < 0.05) return "*";
    return "";
}

// The legend line under a table that marks significance: basis "q" (corrected) or "p" (uncorrected).
function sigLegend(basis) {
    var symbol = basis === "p" ? "p" : "q";
    var tail = basis === "p" ? ", uncorrected for multiple tests" : " (Benjamini–Hochberg)";
    return "* " + symbol + " < 0.05 · ** " + symbol + " < 0.01 · *** " + symbol + " < 0.001" + tail + ".";
}

// A q-value (or a p-value) with its significance stars, as the HTML of a table cell.
function qHtml(val) {
    var stars = sigStars(val);
    return fmtP(val) + (stars ? " <span class=\"text-muted\">" + stars + "</span>" : "");
}

// Sequential tint of a cell, from the surface to --tint (stronger in a dark theme, where tints read weaker).
function heatmapBg(val, min, max) {
    if (isNil(val) || !(min < max)) return "";
    var ratio = Math.max(0, Math.min(1, (val - min) / (max - min)));
    return "background-color:color-mix(in srgb, var(--tint) " + Math.round(ratio * HEAT_MAX) + "%, var(--surface))";
}

// Diverging tint around `center`: --div-neg below it, --div-pos above, the surface at the centre.
function divergingHeatmapBg(val, center, lo, hi) {
    if (isNil(val)) return "";
    var ratio, token;
    if (val <= center) {
        if (!(lo < center)) return "";
        ratio = (center - val) / (center - lo);
        token = "--div-neg";
    } else {
        if (!(hi > center)) return "";
        ratio = (val - center) / (hi - center);
        token = "--div-pos";
    }
    ratio = Math.max(0, Math.min(1, ratio));
    return "background-color:color-mix(in srgb, var(" + token + ") " + Math.round(ratio * DIVERGING_MAX) + "%, var(--surface))";
}

// The theme's colours for charts drawn in canvas or SVG, read from the CSS custom properties. A chart with one
// series draws it in series[0] and shows no legend; a second series takes series[1], a reference line `muted`.
function pulpitTheme() {
    var style = getComputedStyle(document.documentElement);

    function token(name, fallback) {
        var value = style.getPropertyValue(name).trim();
        return value || fallback;
    }
    var series = [];
    for (var i = 1; i <= 8; i++) series.push(token("--series-" + i, "#888888"));
    return {
        text: token("--text", "#1c1917"),
        muted: token("--muted", "#6b6560"),
        grid: token("--chart-grid", "#e7e5e4"),
        border: token("--border", "#e3e0d8"),
        surface: token("--surface", "#ffffff"),
        accent: token("--accent", "#4338ca"),
        tint: token("--tint", "#4338ca"),
        divPos: token("--div-pos", "#4338ca"),
        divNeg: token("--div-neg", "#c2410c"),
        band: token("--chart-band", "rgba(120, 113, 108, 0.18)"),
        series: series,
        fontSans: token("--font-sans", "sans-serif"),
    };
}

(function applyChartTheme() {
    if (!window.Chart || !window.Chart.defaults) return;
    var theme = pulpitTheme();
    var defaults = window.Chart.defaults;
    // Axis ticks in the same number style as the tables, whatever the reader's browser language.
    defaults.locale = NUMBER_LOCALE;
    defaults.color = theme.muted;
    defaults.borderColor = theme.grid;
    defaults.font.family = theme.fontSans;
    if (defaults.plugins && defaults.plugins.tooltip) {
        defaults.plugins.tooltip.backgroundColor = theme.text;
        defaults.plugins.tooltip.titleColor = theme.surface;
        defaults.plugins.tooltip.bodyColor = theme.surface;
    }
})();
