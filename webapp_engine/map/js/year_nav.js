// Build the "All | 2018 | 2019 | …" year-switcher pill row.
// years: array of timeline year objects (already filtered to those that have the relevant data).
// cur:   current value — integer or "all".
// onSelect: callback called with the selected year (integer or "all") when a button is clicked.
// Clears the container on each call so it can be used to refresh active state.
export function build_year_nav(years, cur, onSelect) {
    var target = document.getElementById("timeline-nav");
    if (!target || !years.length) return;
    target.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "d-flex flex-wrap gap-1";
    var all_btn = document.createElement("button");
    all_btn.type = "button";
    all_btn.className = "btn btn-sm " + (cur === "all" ? "btn-primary" : "btn-outline-secondary");
    all_btn.textContent = "All";
    all_btn.addEventListener("click", function() { onSelect("all"); });
    wrap.appendChild(all_btn);
    years.forEach(function(y) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-sm " + (cur === y.year ? "btn-primary" : "btn-outline-secondary");
        btn.textContent = y.year;
        btn.addEventListener("click", function() { onSelect(y.year); });
        wrap.appendChild(btn);
    });
    target.appendChild(wrap);
}
