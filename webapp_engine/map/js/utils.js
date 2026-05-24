export function escHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Fetch JSON, rejecting on any non-2xx response. Use for required resources.
export function fetchJson(url) {
    return fetch(url).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
    });
}

// Fetch JSON, resolving to null on a missing resource or network error.
// Use for optional resources (meta.json, timeline.json, …) the page tolerates.
export function fetchJsonOrNull(url) {
    return fetch(url)
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
}

// communities[strategy].groups holds rows of [id, count, label, hexColor];
// build a {strategy: {label: hexColor}} lookup used for node colouring.
export function buildCommunityColorMaps(communities) {
    var maps = {};
    for (var strategy in communities) {
        maps[strategy] = {};
        var groups = communities[strategy].groups;
        for (var i = 0; i < groups.length; i++) {
            maps[strategy][groups[i][2]] = groups[i][3];
        }
    }
    return maps;
}

// Component-wise average of two [r, g, b] colours, scaled by `factor`
// (used to darken blended edge colours). Returns unrounded floats; callers
// round for 0–255 space or pass straight into 0–1 colour objects.
export function avgColor(c1, c2, factor) {
    return [
        (c1[0] + c2[0]) / 2 * factor,
        (c1[1] + c2[1]) / 2 * factor,
        (c1[2] + c2[2]) / 2 * factor,
    ];
}
