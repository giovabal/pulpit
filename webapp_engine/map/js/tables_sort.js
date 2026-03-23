function heatmapBg(val, min, max) {
    if (val === null || val === undefined || min >= max) return "";
    var ratio = (val - min) / (max - min);
    return "background-color:rgb(" + Math.round(255 - ratio * 35) + "," + Math.round(255 - ratio * 21) + "," + Math.round(255 - ratio * 6) + ")";
}
function fmtNum(val, decimals) {
    if (val === null || val === undefined) return "N/A";
    return decimals === 0 ? String(Math.round(val)) : val.toFixed(decimals);
}
function numSortVal(val) {
    return val !== null && val !== undefined ? String(val) : "";
}
function initSortableTables() {
    var tables = document.querySelectorAll("table.sortable:not([data-sort-initialized])"), table, thead, headers, i, j;
    for (i = 0; i < tables.length; i++) {
        table = tables[i];
        if (thead = table.querySelector("thead")) {
            headers = thead.querySelectorAll("th");
            if (headers.length === 0) continue;
            table.setAttribute('data-sort-initialized', 'true');
            for (j = 0; j < headers.length; j++) {
                headers[j].setAttribute('aria-sort', 'none');
                headers[j].innerHTML = "<a href='#'>" + headers[j].innerText + "</a>";
            }
            thead.addEventListener("click", sortTableFunction(table));
        }
    }
}
initSortableTables();
function sortTableFunction(table) {
    return function(ev) {
        if (ev.target.tagName.toLowerCase() == 'a') {
            var header = ev.target.parentNode;
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
            ev.preventDefault();
        }
    };
}
function siblingIndex(node) {
    var count = 0;
    while (node = node.previousElementSibling) count++;
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
    for (index = 0; index < rows.length; index++) {
        node = rows[index].querySelector(sel2);
        val = node.getAttribute("data-sort-value");
        if (val === null || val === "") val = node.innerText;
        var numericVal = parseFloat(val);
        if (!Number.isNaN(numericVal) && isFinite(numericVal)) val = numericVal; else allNum = false;
        values.push({ value: val, row: rows[index] });
    }
    if (cls == "" && allNum) cls = "number";
    if (cls == "number") values.sort(function(a, b) { return a.value - b.value; });
    else if (cls == "date") values.sort(function(a, b) { return Date.parse(a.value) - Date.parse(b.value); });
    else values.sort(function(a, b) {
        var ta = (a.value + "").toUpperCase(), tb = (b.value + "").toUpperCase();
        return ta < tb ? -1 : ta > tb ? 1 : 0;
    });
    if (sortDirection === "desc") values = values.reverse();
    for (var idx = 0; idx < values.length; idx++) table.querySelector("tbody").appendChild(values[idx].row);
}
