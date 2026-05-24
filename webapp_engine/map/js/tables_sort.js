/* exported heatmapBg, sigFig, fmtInt, divergingHeatmapBg, numSortVal, initSortableTables */
function heatmapBg(val, min, max) {
    if (val === null || val === undefined || min >= max) return "";
    var ratio = (val - min) / (max - min);
    return "background-color:rgb(" + Math.round(255 - ratio * 35) + "," + Math.round(255 - ratio * 21) + "," + Math.round(255 - ratio * 6) + ")";
}
function sigFig(val, n) {
    if (val === null || val === undefined) return "—";
    if (!isFinite(val) || val === 0) return "0";
    return parseFloat(val.toPrecision(n)).toString();
}
function fmtInt(val) {
    if (val === null || val === undefined) return "—";
    return Math.round(val).toLocaleString();
}
function divergingHeatmapBg(val, center, lo, hi) {
    if (val === null || val === undefined) return "";
    if (val <= center) {
        if (center <= lo) return "";
        var r = (center - val) / (center - lo);
        return "background-color:rgb(" + Math.round(255 - r * 155) + "," + Math.round(255 - r * 100) + ",255)";
    } else {
        if (hi <= center) return "";
        var r2 = (val - center) / (hi - center);
        return "background-color:rgb(255," + Math.round(255 - r2 * 165) + "," + Math.round(255 - r2 * 175) + ")";
    }
}
function numSortVal(val) {
    return val !== null && val !== undefined ? String(val) : "";
}
function initSortableTables() {
    var tables = document.querySelectorAll("table.sortable:not([data-sort-initialized])"), table, thead, headers, i, j;
    for (i = 0; i < tables.length; i++) {
        table = tables[i];
        if ((thead = table.querySelector("thead"))) {
            headers = thead.querySelectorAll("th");
            if (headers.length === 0) continue;
            table.setAttribute('data-sort-initialized', 'true');
            for (j = 0; j < headers.length; j++) {
                if (!headers[j].hasAttribute('scope')) headers[j].setAttribute('scope', 'col');
                headers[j].setAttribute('aria-sort', 'none');
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'th-sort-btn';
                btn.textContent = headers[j].textContent;
                headers[j].textContent = '';
                headers[j].appendChild(btn);
            }
            if (table._sortListener) thead.removeEventListener("click", table._sortListener);
            table._sortListener = sortTableFunction(table);
            thead.addEventListener("click", table._sortListener);
        }
    }
}
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSortableTables);
} else {
    initSortableTables();
}
function sortTableFunction(table) {
    return function(ev) {
        var target = ev.target;
        var trigger = target.closest && target.closest('button.th-sort-btn, a');
        if (!trigger) return;
        var header = trigger.parentNode;
        if (!header || header.tagName.toLowerCase() !== 'th') return;
        var currentDirection = header.getAttribute('data-sort-direction');
        var direction = currentDirection === 'desc' ? 'asc' : 'desc';
        var siblingHeaders = header.parentNode.children;
        for (var i = 0; i < siblingHeaders.length; i++) {
            if (siblingHeaders[i] !== header) {
                siblingHeaders[i].removeAttribute('data-sort-direction');
                siblingHeaders[i].setAttribute('aria-sort', 'none');
            }
        }
        header.setAttribute('data-sort-direction', direction);
        header.setAttribute('aria-sort', direction === 'asc' ? 'ascending' : 'descending');
        sortRows(table, siblingIndex(header), direction);
        if (window.PulpitA11y) {
            var label = trigger.textContent.trim() || 'column';
            window.PulpitA11y.announce('Sorted by ' + label + ', ' + (direction === 'asc' ? 'ascending' : 'descending'));
        }
        ev.preventDefault();
    };
}
function siblingIndex(node) {
    var count = 0;
    while ((node = node.previousElementSibling)) count++;
    return count;
}
function sortRows(table, columnIndex, direction) {
    var rows = table.querySelectorAll("tbody tr"),
        sel  = "thead th:nth-child(" + (columnIndex + 1) + ")",
        sel2 = "td:nth-child(" + (columnIndex + 1) + ")",
        classList = table.querySelector(sel).classList,
        values = [], cls = "", sortDirection = direction || "asc", allNum = true, val, index, node;
    if (classList) {
        if (classList.contains("date")) cls = "date";
        else if (classList.contains("number")) cls = "number";
    }
    // Number() is stricter than parseFloat — "123abc" returns NaN instead of 123,
    // so a mixed text/number column is correctly classified as non-numeric.
    for (index = 0; index < rows.length; index++) {
        node = rows[index].querySelector(sel2);
        val = node.getAttribute("data-sort-value");
        if (val === null || val === "") val = node.textContent;
        var trimmed = (typeof val === "string") ? val.trim() : val;
        var numericVal = trimmed === "" ? NaN : Number(trimmed);
        if (Number.isFinite(numericVal)) val = numericVal; else allNum = false;
        values.push({ value: val, row: rows[index] });
    }
    if (cls === "" && allNum) cls = "number";
    if (cls === "number") values.sort(function(a, b) {
        var an = typeof a.value === "number", bn = typeof b.value === "number";
        if (an && bn) return a.value - b.value;
        return an ? -1 : bn ? 1 : 0;
    });
    else if (cls === "date") values.sort(function(a, b) {
        var an = Date.parse(a.value), bn = Date.parse(b.value);
        if (!isNaN(an) && !isNaN(bn)) return an - bn;
        return !isNaN(an) ? -1 : !isNaN(bn) ? 1 : 0;
    });
    else values.sort(function(a, b) {
        var ta = (a.value + "").toUpperCase(), tb = (b.value + "").toUpperCase();
        return ta < tb ? -1 : ta > tb ? 1 : 0;
    });
    if (sortDirection === "desc") values = values.reverse();
    for (var idx = 0; idx < values.length; idx++) table.querySelector("tbody").appendChild(values[idx].row);
}
