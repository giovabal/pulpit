// Table cells shared by the pages that build their tables as HTML strings (dominance, outbound links).
// Numbers go through format.js, so every page writes a missing value, a share and a q-value the same way.
import { escHtml } from './utils.js';

export function numCell(v, text, style) {
    return "<td class=\"number\" data-sort-value=\"" + (isNil(v) ? "" : v) + "\"" + (style ? " style=\"" + style + "\"" : "") + ">" +
        (isNil(text) ? MISSING : text) + "</td>";
}

export function shareCell(v) {
    return numCell(v, fmtShare(v), isNil(v) ? "" : heatmapBg(v, 0, 1));
}

// A signed number with a fixed number of decimals ("+1.25", "-0.40"); a value that rounds to zero has no sign.
export function signed(v, decimals) {
    var text = fmtFixed(v, decimals);
    return v > 0 && /[1-9]/.test(text) ? "+" + text : text;
}

// A q-value (Benjamini–Hochberg) with its significance stars, the convention of every export page.
export function qCell(q) {
    if (isNil(q)) return numCell(null, MISSING);
    return numCell(q, qHtml(q));
}

export function channelCell(ref) {
    var org = ref.organization ? " <span class=\"text-muted small\">(" + escHtml(ref.organization) + ")</span>" : "";
    return "<td data-sort-value=\"" + escHtml(ref.label) + "\">" + escHtml(ref.label) + org + "</td>";
}

// Rewrite a table's heading row from `columns` ({label, number, title}). The rows are rewritten by the caller,
// which then calls initSortableTables(): the order the reader had chosen is applied again (tables_sort.js).
export function header(table, columns) {
    table.removeAttribute("data-sort-initialized");
    table.querySelector("thead").innerHTML = "<tr>" + columns.map(function(c) {
        return "<th" + (c.number ? " class=\"number\"" : "") + (c.title ? " title=\"" + escHtml(c.title) + "\"" : "") + ">" +
            escHtml(c.label) + "</th>";
    }).join("") + "</tr>";
}

export function matches(needle, parts) {
    if (!needle) return true;
    return parts.join(" ").toLowerCase().indexOf(needle) !== -1;
}
