// Build the "All | 2018 | 2019 | …" year-switcher pill row.
// years: array of timeline year objects (already filtered to those that have the relevant HTML).
// cur:   current_year value — integer or "all".
// baseName: file stem, e.g. "channel_table" → "channel_table.html" / "channel_table_2021.html".
export function build_year_nav(years, cur, baseName) {
    var target = document.getElementById("timeline-nav");
    if (!target || !years.length) return;
    var wrap = document.createElement("div");
    wrap.className = "d-flex flex-wrap gap-1";
    var all_a = document.createElement("a");
    all_a.href = baseName + ".html";
    all_a.className = "btn btn-sm " + (cur === "all" ? "btn-primary" : "btn-outline-secondary");
    all_a.textContent = "All";
    wrap.appendChild(all_a);
    years.forEach(function(y) {
        var a = document.createElement("a");
        a.href = baseName + "_" + y.year + ".html";
        a.className = "btn btn-sm " + (cur === y.year ? "btn-primary" : "btn-outline-secondary");
        a.textContent = y.year;
        wrap.appendChild(a);
    });
    target.appendChild(wrap);
}
