// Mini histogram SVG shared across table pages.
// all_val_str: string value for the "All" (full-range) bar, or null.
// yr_vals:     [{year: int, value: string|null}] — per-year values.
// cur:         currently highlighted year (integer or "all").
// all_years:   ordered array of year integers; reserves a slot per year so all
//              SVGs have identical width even when some years have no data.
export function mini_hist(all_val_str, yr_vals, cur, all_years) {
    var BAR_W = 7, GAP = 2, H = 20, ns = "http://www.w3.org/2000/svg";
    var yr_val_map = {};
    (yr_vals || []).forEach(function(y) { yr_val_map[y.year] = y.value; });
    var bars = [{ year: "all", raw: all_val_str }]
        .concat((all_years || []).map(function(yr) {
            return { year: yr, raw: yr_val_map[yr] !== undefined ? yr_val_map[yr] : null };
        }));
    var valid = bars.map(function(b) { return parseFloat(b.raw); }).filter(Number.isFinite);
    if (!valid.length) return null;
    var lo = Math.min(0, Math.min.apply(null, valid));
    var hi = Math.max(0, Math.max.apply(null, valid));
    var span = hi - lo;
    if (!span) return null;
    var base = Math.round(hi / span * H);
    var W = bars.length * (BAR_W + GAP) - GAP;
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.style.cssText = "display:block;flex-shrink:0";
    bars.forEach(function(b, i) {
        var v = parseFloat(b.raw);
        if (!isFinite(v)) return;
        var bh = Math.max(1, Math.round(Math.abs(v) / span * H));
        var by = v >= 0 ? base - bh : base;
        var is_all = b.year === "all";
        var is_cur = is_all ? cur === "all" : cur === b.year;
        var r = document.createElementNS(ns, "rect");
        r.setAttribute("x", i * (BAR_W + GAP)); r.setAttribute("y", by);
        r.setAttribute("width", BAR_W); r.setAttribute("height", bh);
        r.setAttribute("fill", is_cur ? "#1d4ed8" : (is_all ? "#60a5fa" : "#94a3b8"));
        var t = document.createElementNS(ns, "title");
        t.textContent = (is_all ? "All" : b.year) + ": " + b.raw;
        r.appendChild(t); svg.appendChild(r);
    });
    if (lo < 0 && hi > 0) {
        var line = document.createElementNS(ns, "line");
        line.setAttribute("x1", 0); line.setAttribute("y1", base);
        line.setAttribute("x2", W); line.setAttribute("y2", base);
        line.setAttribute("stroke", "#94a3b8"); line.setAttribute("stroke-width", "0.5");
        svg.appendChild(line);
    }
    return svg;
}
