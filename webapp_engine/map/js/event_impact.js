// Event impact page (event_impact.html).
//
// Renders data/event_impact.json, written by network/event_impact.py: the network's weekly series with the
// recorded events marked, and per event the interrupted-time-series fit of every metric — level and slope
// changes, HAC and placebo p-values, BH q — with a chart of the observed series, the fitted segments and the
// counterfactual continuation of the pre-event trend.
import { fetchJson, loadFailed } from './utils.js';

var _charts = {};

function _el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
}

function _fmt(v, n) {
    return sigFig(v, n || 3);
}

function _unit(metric) {
    return metric.kind === "count" ? "log(1 + " + metric.label.toLowerCase() + ")" : metric.label;
}

function _eventLines(events, weeks) {
    var lines = {};
    events.forEach(function(e, i) {
        if (!e.week || weeks.indexOf(e.week) === -1) return;
        lines["ev" + i] = {
            type: "line",
            xMin: e.week,
            xMax: e.week,
            borderColor: e.color || pulpitTheme().series[7],
            borderWidth: 1.5,
            borderDash: [5, 4],
            label: { display: false, content: e.subject },
        };
    });
    return lines;
}

// A chart with a single series needs no legend: its title and axis say what it shows.
function _chart(canvas, labels, datasets, annotations, yTitle) {
    var theme = pulpitTheme();
    var text = theme.text,
        grid = theme.grid;
    return new Chart(canvas, {
        type: "line",
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: datasets.length > 1, labels: { color: text, boxWidth: 14 } },
                annotation: { annotations: annotations || {} },
            },
            scales: {
                x: { ticks: { color: text, maxTicksLimit: 12 }, grid: { color: grid } },
                y: { title: { display: true, text: yTitle, color: text }, ticks: { color: text }, grid: { color: grid } },
            },
        },
    });
}

function _overview(target, data) {
    target.innerHTML = "";
    if (!data.weeks || !data.weeks.length) return;
    target.appendChild(_el("h2", "", "Weekly series of the network"));
    var row = _el("div", "d-flex align-items-end gap-2 mb-2");
    var label = _el("label", "form-label mb-0 small", "Metric");
    label.setAttribute("for", "ei-overview-metric");
    var sel = _el("select", "form-select form-select-sm");
    sel.id = "ei-overview-metric";
    sel.style.maxWidth = "28rem";
    data.metrics.forEach(function(m) { sel.appendChild(new Option(m.label, m.key)); });
    row.appendChild(label);
    row.appendChild(sel);
    target.appendChild(row);
    var box = _el("div");
    box.style.height = "260px";
    var canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Weekly series of the selected metric with the recorded events marked");
    box.appendChild(canvas);
    target.appendChild(box);

    function draw() {
        var metric = data.metrics.find(function(m) { return m.key === sel.value; });
        if (_charts.overview) _charts.overview.destroy();
        _charts.overview = _chart(canvas, data.weeks, [{
            label: metric.label,
            data: data.series[metric.key],
            borderColor: pulpitTheme().series[0],
            backgroundColor: pulpitTheme().series[0],
            pointRadius: 0,
            borderWidth: 1.5,
            spanGaps: false,
        }], _eventLines(data.events, data.weeks), metric.kind === "count" ? metric.label : "Share");
    }
    sel.addEventListener("change", draw);
    draw();
}

// A coefficient, for a count with its reading as a percentage change; the cell sorts on the coefficient.
function _effectCell(effect, pct) {
    var td = _el("td", "number nowrap");
    if (!effect || isNil(effect.coef)) {
        td.textContent = MISSING;
        return td;
    }
    var text = _fmt(effect.coef, 3);
    if (pct && !isNil(effect.pct)) text += " (" + (effect.pct > 0 ? "+" : "") + sigFig(effect.pct, 3) + "%)";
    td.textContent = text;
    td.setAttribute("data-sort-value", String(effect.coef));
    td.title = "standard error " + _fmt(effect.se, 3);
    return td;
}

function _pCell(p) {
    var td = _el("td", "number", fmtP(p));
    if (!isNil(p)) td.setAttribute("data-sort-value", String(p));
    return td;
}

// The q-value (Benjamini–Hochberg over events × metrics) with the stars of every export page.
function _qCell(q) {
    var td = _pCell(q);
    var star = sigStars(q);
    if (star) td.appendChild(_el("span", "text-muted ms-1", star));
    return td;
}

function _effectsTable(event, idx) {
    var wrap = _el("div", "table-responsive");
    var table = _el("table", "table table-sm table-hover sortable");
    table.setAttribute("aria-labelledby", "ei-event-" + idx);
    var thead = _el("thead");
    var head = _el("tr");
    // One header row (a grouped two-row header cannot be sorted): the level change at the event's week, then the
    // change of slope per week after it, each with its two p-values and the corrected q.
    ["Metric", "Level change", "Level p (HAC)", "Level p (placebo)", "Level q", "Slope change per week", "Slope p (HAC)",
        "Slope p (placebo)", "Slope q", "Notes"
    ].forEach(function(lbl, i) {
        var th = _el("th", i > 0 && i < 9 ? "number" : "", lbl);
        th.scope = "col";
        head.appendChild(th);
    });
    thead.appendChild(head);
    table.appendChild(thead);
    var tbody = _el("tbody");
    event.metrics.forEach(function(m) {
        var tr = _el("tr");
        tr.appendChild(_el("td", "", m.label));
        if (m.insufficient) {
            // Every cell kept, so the table still sorts: the effects are missing, the note says why.
            for (var k = 0; k < 8; k++) tr.appendChild(_el("td", "number text-muted", MISSING));
            tr.appendChild(_el("td", "small text-muted", "not enough weeks with data around the event"));
            tbody.appendChild(tr);
            return;
        }
        tr.appendChild(_effectCell(m.level, m.kind === "count"));
        tr.appendChild(_pCell(m.level.p_hac));
        tr.appendChild(_pCell(m.level.p_placebo));
        tr.appendChild(_qCell(m.level.q));
        tr.appendChild(_effectCell(m.slope, false));
        tr.appendChild(_pCell(m.slope.p_hac));
        tr.appendChild(_pCell(m.slope.p_placebo));
        tr.appendChild(_qCell(m.slope.q));
        var notes = [];
        if (m.truncated) notes.push("window cut short by the start or the end of the data");
        if (m.placebo_coarse) notes.push("few placebo dates (" + m.placebos + ")");
        tr.appendChild(_el("td", "small text-muted", notes.join("; ")));
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    wrap.appendChild(_el("p", "text-muted small mt-1", sigLegend("q")));
    return wrap;
}

function _eventChart(box, event, metric, key) {
    var accent = pulpitTheme().series[0],
        muted = pulpitTheme().muted;
    var datasets;
    if (event.design === "comparative") {
        datasets = [
            { label: "Affected (observed)", data: metric.observed_affected, borderColor: accent, pointRadius: 2, borderWidth: 1, showLine: false },
            { label: "Comparison (observed)", data: metric.observed_comparison, borderColor: muted, pointRadius: 2, borderWidth: 1, showLine: false },
            { label: "Affected (fit)", data: metric.fit_affected, borderColor: accent, pointRadius: 0, borderWidth: 2 },
            { label: "Comparison (fit)", data: metric.fit_comparison, borderColor: muted, pointRadius: 0, borderWidth: 2 },
            { label: "Affected without the event", data: metric.counterfactual, borderColor: accent, borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 },
        ];
    } else {
        datasets = [
            { label: "Observed", data: metric.observed, borderColor: muted, pointRadius: 2, borderWidth: 1, showLine: false },
            { label: "Fit", data: metric.fit, borderColor: accent, pointRadius: 0, borderWidth: 2 },
            { label: "Without the event", data: metric.counterfactual, borderColor: accent, borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 },
        ];
    }
    datasets.forEach(function(d) {
        d.backgroundColor = d.borderColor;
        d.spanGaps = false;
    });
    var canvas = box.querySelector("canvas");
    if (_charts[key]) _charts[key].destroy();
    _charts[key] = _chart(canvas, metric.weeks, datasets, _eventLines([event], metric.weeks), _unit(metric));
}

function _eventCard(event, idx) {
    var card = _el("section", "card mb-4");
    var body = _el("div", "card-body");
    var h = _el("h2", "card-title");
    h.id = "ei-event-" + idx;
    var dot = _el("span", "color-swatch color-swatch--sm me-2");
    dot.style.background = event.color || pulpitTheme().series[7];
    dot.setAttribute("aria-hidden", "true");
    h.appendChild(dot);
    h.appendChild(document.createTextNode(event.date + " — " + event.subject));
    body.appendChild(h);
    var meta = event.type + " · " + (event.labels.length ? "scoped to " + event.labels.join(", ") + " (comparative design)" : "whole network");
    if (event.week) meta += " · event week " + event.week;
    body.appendChild(_el("p", "small text-muted mb-2", meta));
    if (event.confounded_by.length) {
        body.appendChild(_el("p", "small text-warning-emphasis mb-2",
            "Other events fall inside this window (" + event.confounded_by.join("; ") + "): the effects mix them."));
    }
    var fitted = event.metrics.filter(function(m) { return !m.insufficient; });
    if (fitted.length) {
        var row = _el("div", "d-flex align-items-end gap-2 mb-2");
        var label = _el("label", "form-label mb-0 small", "Metric");
        label.setAttribute("for", "ei-metric-" + idx);
        var sel = _el("select", "form-select form-select-sm");
        sel.id = "ei-metric-" + idx;
        sel.style.maxWidth = "28rem";
        fitted.forEach(function(m) { sel.appendChild(new Option(m.label, m.key)); });
        row.appendChild(label);
        row.appendChild(sel);
        body.appendChild(row);
        var box = _el("div", "mb-3");
        box.style.height = "260px";
        var canvas = document.createElement("canvas");
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", "Observed weekly series around " + event.subject + ", fitted segments and the trend without the event");
        box.appendChild(canvas);
        body.appendChild(box);
        var draw = function() {
            var m = fitted.find(function(x) { return x.key === sel.value; });
            _eventChart(box, event, m, "event" + idx);
        };
        sel.addEventListener("change", draw);
        draw();
    }
    body.appendChild(_effectsTable(event, idx));
    card.appendChild(body);
    return card;
}

function _render(data) {
    var pre = document.getElementById("ei-preamble");
    var n = data.events.length;
    pre.innerHTML = "";
    pre.appendChild(_el("p", "small mb-0",
        fmtInt(n) + " event" + (n === 1 ? "" : "s") + " inside the data, " + fmtInt((data.weeks || []).length) + " weeks, a window of ±" +
        data.window_weeks + " weeks around each event."));
    if (!n) pre.appendChild(_el("p", "text-muted small", "No recorded event falls inside the period of this analysis."));
    _overview(document.getElementById("ei-overview"), data);
    var list = document.getElementById("ei-events");
    list.innerHTML = "";
    data.events.forEach(function(e, i) { list.appendChild(_eventCard(e, i)); });
    initSortableTables();
}

var _dataDir = window.DATA_DIR || "data/";

fetchJson(_dataDir + "event_impact.json").then(_render).catch(function(err) {
    loadFailed(err);
});
