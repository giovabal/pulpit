/* exported numSortVal, initSortableTables */
// Sortable tables: every table.sortable gets a button in each column heading. The number formatters and cell
// tints this file used to hold live in format.js, loaded before it.
//
// A cell sorts on its data-sort-value, else on its text; a number written for reading ("1,234", "12.5%",
// "< 0.001", "0.012 **") still sorts as a number. Cells with no value ("—", empty) stay at the bottom whichever
// way the column is sorted. The order a reader chose is kept on the table by column label, so a page that
// rebuilds the heading and the rows of the same table (a filter, another period) shows them in that order again.

function numSortVal(val) {
    return val !== null && val !== undefined ? String(val) : "";
}

var SORT_HINT = "Click a column heading to sort.";
var SORT_MISSING = "—";

// One visible hint per page, above its first sortable table.
function _addSortHint(table) {
    if (document.querySelector(".export-sort-hint")) return;
    var anchor = table.closest(".table-responsive") || table;
    var hint = document.createElement("p");
    hint.className = "export-sort-hint";
    hint.textContent = SORT_HINT;
    anchor.parentNode.insertBefore(hint, anchor);
}

function _markSorted(headers, header, direction) {
    for (var i = 0; i < headers.length; i++) {
        if (headers[i] !== header) {
            headers[i].removeAttribute('data-sort-direction');
            headers[i].setAttribute('aria-sort', 'none');
        }
    }
    header.setAttribute('data-sort-direction', direction);
    header.setAttribute('aria-sort', direction === 'asc' ? 'ascending' : 'descending');
}

// Put a rebuilt table back in the order the reader had chosen, when the column is still there.
function _reapplySort(table, headers) {
    var state = table._sortState;
    if (!state) return;
    for (var j = 0; j < headers.length; j++) {
        if (headers[j].textContent.trim() === state.label) {
            _markSorted(headers, headers[j], state.direction);
            sortRows(table, j, state.direction);
            return;
        }
    }
}

function initSortableTables() {
    var tables = document.querySelectorAll("table.sortable:not([data-sort-initialized])"),
        table, thead, headers, i, j;
    for (i = 0; i < tables.length; i++) {
        table = tables[i];
        if (table.closest("[hidden], .d-none") === null && table.querySelector("tbody tr")) _addSortHint(table);
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
            _reapplySort(table, headers);
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
        _markSorted(header.parentNode.children, header, direction);
        table._sortState = { label: header.textContent.trim(), direction: direction };
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

// What a cell sorts on: {missing} for a cell with no value, else its text and, when the text reads as one, its
// number. Number() is strict ("123abc" is no number), so a column mixing words and numbers sorts as text.
function _sortKey(cell) {
    if (!cell) return { missing: true };
    var raw = cell.getAttribute("data-sort-value");
    if (raw === null || raw === "") raw = cell.textContent;
    raw = String(raw).trim();
    if (raw === "" || raw === SORT_MISSING) return { missing: true };
    var plain = raw.replace(/,/g, "").replace(/^<\s*/, "").replace(/[\s%*]+$/, "");
    var num = plain === "" ? NaN : Number(plain);
    return { missing: false, text: raw, num: Number.isFinite(num) ? num : null };
}

function sortRows(table, columnIndex, direction) {
    var tbody = table.querySelector("tbody"),
        rows = table.querySelectorAll("tbody tr"),
        th = table.querySelector("thead th:nth-child(" + (columnIndex + 1) + ")"),
        cls = "",
        present = [],
        missing = [],
        allNum = true,
        index, key;
    if (!tbody) return;
    if (th && th.classList.contains("date")) cls = "date";
    else if (th && th.classList.contains("number")) cls = "number";
    for (index = 0; index < rows.length; index++) {
        key = _sortKey(rows[index].children[columnIndex]);
        key.row = rows[index];
        if (key.missing) missing.push(key);
        else {
            present.push(key);
            if (key.num === null) allNum = false;
        }
    }
    if (cls === "" && allNum && present.length) cls = "number";
    if (cls === "number" || cls === "date") {
        // A cell that is no number (no date) in a column of them goes with the cells that have no value.
        var usable = [];
        present.forEach(function(k) {
            var value = cls === "number" ? k.num : Date.parse(k.text);
            if (value === null || isNaN(value)) missing.push(k);
            else {
                k.value = value;
                usable.push(k);
            }
        });
        present = usable;
        present.sort(function(a, b) { return a.value - b.value; });
    } else {
        present.sort(function(a, b) {
            return a.text.localeCompare(b.text, "en", { numeric: true, sensitivity: "base" });
        });
    }
    if (direction === "desc") present.reverse();
    present.concat(missing).forEach(function(k) { tbody.appendChild(k.row); });
}
