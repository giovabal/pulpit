// Homophily by label group and the dyadic regression, for the network table page.
//
// Renders the `label_mixing` and `mrqap` blocks of network_metrics.json (one file per timeline year):
// computed server-side by network/label_mixing.py (assortativity, inbreeding homophily, label flows,
// all tested against label permutations) and network/mrqap.py (MRQAP with double semi-partialling).

// Above this many labels the flow matrix starts collapsed.
var FLOW_OPEN_MAX_LABELS = 12;

function _el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
}

function _test_text(test) {
    if (!test || isNil(test.value)) return MISSING;
    var s = sigFig(test.value, 3);
    if (test.null_mean !== null && test.null_mean !== undefined)
        s += " (expected " + sigFig(test.null_mean, 3) + (isNil(test.p) ? "" : ", " + pText(test.p)) + ")";
    return s;
}

var LABEL_COLUMNS = [{
    key: "label",
    label: "Label",
    num: false,
    tip: "A label of this group"
}, {
    key: "channels",
    label: "Channels",
    num: true,
    int: true,
    tip: "Labelled, observed channels carrying the label"
}, {
    key: "baseline_share",
    label: "Baseline w",
    num: true,
    tip: "Share of partners expected inside the label if partners were chosen regardless of label: (n − 1)/(N − 1)"
}, {
    key: "ih_out",
    q: "ih_out_q",
    label: "Homophily, citing",
    num: true,
    tip: "Inbreeding homophily of the label's sent ties (Coleman 1958; Currarini, Jackson & Pin 2009): (H − w)/(1 − w), H = share of its citations of labelled channels that stay inside. 0 = no preference beyond its size, 1 = cites only its own label. Stars: BH q < 0.05 / 0.01 / 0.001 against label permutations"
}, {
    key: "ih_in",
    q: "ih_in_q",
    label: "Homophily, cited",
    num: true,
    tip: "Inbreeding homophily of the label's received ties: how much of the attention it gets comes from inside, beyond what its size predicts. Stars as for the citing side"
}, {
    key: "net_exporter_ties",
    label: "Net exporter",
    num: true,
    tip: "(cross-label ties received − given) / (received + given): positive = channels of other labels cite this label more than it cites them"
}, {
    key: "out_of_scope_citations_share",
    label: "Out-of-scope share",
    num: true,
    share: true,
    tip: "Share of the label's citations going to channels with no label in this group or to channels outside the studied set (descriptive)"
}];

function _label_table(group, idPrefix) {
    var wrap = _el("div", "table-responsive");
    var table = _el("table", "table table-sm table-hover sortable");
    table.setAttribute("aria-labelledby", idPrefix + "-labels-h");
    var thead = _el("thead");
    var htr = _el("tr");
    LABEL_COLUMNS.forEach(function(col) {
        var th = _el("th", col.num ? "number" : "", col.label);
        th.scope = "col";
        th.title = col.tip;
        htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    var tbody = _el("tbody");
    var rows = group.rows.slice().sort(function(a, b) { return b.channels - a.channels; });
    rows.forEach(function(row) {
        var tr = _el("tr");
        LABEL_COLUMNS.forEach(function(col) {
            var val = row[col.key];
            var td = _el("td", col.num ? "number" : "");
            if (!col.num) {
                td.textContent = val;
            } else {
                td.textContent = col.int ? fmtInt(val) : (col.share ? fmtShare(val) : sigFig(val, 3));
                if (col.q) {
                    var star = sigStars(row[col.q]);
                    if (star) td.appendChild(_el("span", "text-muted ms-1", star));
                    var p = row[col.q.replace(/_q$/, "_p")];
                    if (row[col.q] !== null && row[col.q] !== undefined)
                        td.title = "H = " + sigFig(row[col.key.replace("ih_", "h_")], 3) + ", " + pText(p) + ", " + pText(row[col.q], "q");
                }
                if (val !== null && val !== undefined) td.setAttribute("data-sort-value", String(val));
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
}

function _flow_matrix(group) {
    var flows = group.flows;
    var labels = group.labels;
    var size = {};
    group.rows.forEach(function(r) { size[r.label] = r.channels; });
    var order = labels.map(function(_l, i) { return i; }).sort(function(a, b) {
        return (size[labels[b]] || 0) - (size[labels[a]] || 0) || labels[a].localeCompare(labels[b]);
    });
    var extent = 0;
    order.forEach(function(i) {
        order.forEach(function(j) {
            var ratio = flows.ratio[i][j];
            if (flows.q[i][j] !== null && ratio !== null && ratio > 0) extent = Math.max(extent, Math.abs(Math.log2(ratio)));
        });
    });
    extent = Math.max(extent, 1);
    var wrap = _el("div");
    wrap.style.overflowX = "auto";
    var table = _el("table", "table table-sm table-bordered comparison-matrix label-flow-matrix");
    table.style.cssText = "width:auto;min-width:0;font-size:.8rem;";
    var cap = _el("caption", "text-muted small", "Rows cite columns. Cell = ties between the labels' channels; colour = observed / expected under label permutations (blue over-, orange under-represented), for tested cells only. " + sigLegend("q") + " Hover a cell for the counts.");
    cap.style.captionSide = "top";
    table.appendChild(cap);
    var thead = _el("thead");
    var htr = _el("tr");
    htr.appendChild(_el("th", "", "Citing ↓ / cited →"));
    order.forEach(function(j) {
        var th = _el("th", "number", labels[j]);
        th.scope = "col";
        htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    var tbody = _el("tbody");
    order.forEach(function(i) {
        var tr = _el("tr");
        var th = _el("th", "", labels[i]);
        th.scope = "row";
        tr.appendChild(th);
        order.forEach(function(j) {
            var ties = flows.ties[i][j],
                q = flows.q[i][j],
                ratio = flows.ratio[i][j];
            var td = _el("td", "number", fmtInt(ties || 0));
            var tested = q !== null && q !== undefined;
            if (tested && ratio !== null && ratio > 0) {
                var style = divergingHeatmapBg(Math.log2(ratio), 0, -extent, extent);
                if (style) td.setAttribute("style", style);
            } else if (tested && ratio === 0) {
                td.setAttribute("style", divergingHeatmapBg(-extent, 0, -extent, extent));
            } else {
                td.classList.add("text-muted");
            }
            if (tested && sigStars(q)) td.appendChild(_el("span", "text-muted ms-1", sigStars(q)));
            var tip = labels[i] + " → " + labels[j] + ": " + fmtInt(ties) + " ties, " + fmtInt(flows.citations[i][j]) + " citations; expected " +
                sigFig(flows.expected_ties[i][j], 3) + " ties";
            if (tested) tip += " (ratio " + sigFig(ratio, 3) + ", z = " + sigFig(flows.z[i][j], 3) + ", " + pText(q, "q") + ")";
            else tip += " (not tested: fewer than 3 ties observed and expected)";
            td.title = tip;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
}

// Render every label group of the `label_mixing` payload into `target` (cleared first); hides it when absent.
export function render_label_mixing(target, payload) {
    target.innerHTML = "";
    if (!payload || !payload.groups || !payload.groups.length) {
        target.classList.add("d-none");
        return;
    }
    target.classList.remove("d-none");
    target.appendChild(_el("h2", "", "Homophily by label group"));
    target.appendChild(_el("p", "text-muted small mb-3",
        "Do citations stay inside the analyst's labels (nation, region, …) more than the labels' sizes predict? " +
        "Every statistic is compared with " + fmtInt(payload.permutations) + " random relabellings of the same channels " +
        "(the network fixed), so a large label is not mistaken for an inward-looking one. Only observed channels holding a " +
        "label in the group take part."));
    payload.groups.forEach(function(group) {
        var idPrefix = "mixing-" + group.key;
        var h3 = _el("h3", "", group.group);
        h3.id = idPrefix + "-h";
        target.appendChild(h3);
        target.appendChild(_el("p", "small mb-2",
            fmtInt(group.channels) + " channels, " + fmtInt(group.ties) + " ties between them (" + fmtInt(group.citations) + " citations). " +
            "Assortativity r: " + _test_text(group.assortativity.ties) + " on ties, " + _test_text(group.assortativity.citations) +
            " on citations. E-I index: " + _test_text(group.ei_index) + "."));
        var h4 = _el("h4", "", "Per label");
        h4.id = idPrefix + "-labels-h";
        target.appendChild(h4);
        target.appendChild(_label_table(group, idPrefix));
        target.appendChild(_el("p", "text-muted small mt-1", sigLegend("q")));
        var details = _el("details", "mb-4");
        if (group.labels.length <= FLOW_OPEN_MAX_LABELS) details.open = true;
        details.appendChild(_el("summary", "small", "Citation flows between labels (" + group.labels.length + " × " + group.labels.length + ")"));
        details.appendChild(_flow_matrix(group));
        target.appendChild(details);
    });
    initSortableTables();
}

// Render the `mrqap` payload into `target` (cleared first); hides it when absent.
export function render_mrqap(target, payload) {
    target.innerHTML = "";
    if (!payload) {
        target.classList.add("d-none");
        return;
    }
    target.classList.remove("d-none");
    target.appendChild(_el("h2", "", "Dyadic regression (MRQAP)"));
    if (payload.skipped) {
        target.appendChild(_el("p", "text-muted", "Not computed: " + payload.skipped + "."));
        return;
    }
    var intro = "Every ordered pair of " + fmtInt(payload.actors) + " channels (" + fmtInt(payload.dyads) + " dyads): does i cite j, " +
        "and how often, given the predictors below together. p-values from " + fmtInt(payload.permutations) +
        " relabellings of the channels per predictor (MRQAP, double semi-partialling; Dekker, Krackhardt & Snijders 2007).";
    if (payload.dropped_actors) intro += " " + fmtInt(payload.dropped_actors) + " observed channels without a label in every group used were left out.";
    if (payload.groups_skipped && payload.groups_skipped.length) intro += " Label groups left out (labelling too few channels): " + payload.groups_skipped.join(", ") + ".";
    target.appendChild(_el("p", "text-muted small mb-2", intro));
    var row = _el("div", "row g-4");
    payload.models.forEach(function(model, m) {
        var col = _el("div", "col-lg-6");
        var h3 = _el("h3", "", model.label + " — R² = " + sigFig(model.r2, 3));
        h3.id = "mrqap-model-" + m;
        col.appendChild(h3);
        var wrap = _el("div", "table-responsive");
        var table = _el("table", "table table-sm table-hover sortable");
        table.setAttribute("aria-labelledby", h3.id);
        var thead = _el("thead");
        var htr = _el("tr");
        [
            ["Predictor", "", ""],
            ["Coefficient", "number", "Change in the dependent variable per unit of the predictor, the others held fixed"],
            ["Std. β", "number", "Coefficient in standard deviations of predictor and outcome: comparable across predictors"],
            ["t", "number", "OLS t-statistic (its ordinary p-value is not valid for dyadic data)"],
            ["p", "number", "Two-sided permutation p-value (MRQAP, double semi-partialling)"],
        ].forEach(function(h) {
            var th = _el("th", h[1], h[0]);
            th.scope = "col";
            if (h[2]) th.title = h[2];
            htr.appendChild(th);
        });
        thead.appendChild(htr);
        table.appendChild(thead);
        var tbody = _el("tbody");
        model.coefficients.forEach(function(c) {
            var tr = _el("tr");
            tr.appendChild(_el("td", "", c.label));
            [c.coef, c.beta, c.t].forEach(function(value) {
                var td = _el("td", "number", sigFig(value, 3));
                if (!isNil(value)) td.setAttribute("data-sort-value", String(value));
                tr.appendChild(td);
            });
            var pTd = _el("td", "number", fmtP(c.p));
            if (!isNil(c.p)) pTd.setAttribute("data-sort-value", String(c.p));
            var star = sigStars(c.p);
            if (star) pTd.appendChild(_el("span", "text-muted ms-1", star));
            tr.appendChild(pTd);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        col.appendChild(wrap);
        row.appendChild(col);
    });
    target.appendChild(row);
    target.appendChild(_el("p", "text-muted small mt-2",
        "The tie model is a linear probability model; the reverse tie is endogenous and is read as a control for reciprocity, " +
        "not as a cause. With nested groups (nation inside continent) the finer one reads as the effect beyond the coarser. " +
        sigLegend("p")));
    initSortableTables();
}
