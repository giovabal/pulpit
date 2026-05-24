/* Shared HTTP helpers for the live web UI.
   Loaded as a plain <script> (not a module), so these are globals shared by
   every template that extends webapp/index.html. The static HTML export bundle
   has module equivalents in webapp_engine/map/js/utils.js. */

/* exported fetchJson, fetchJsonOrNull, getCsrfToken */

// Read Django's CSRF cookie for unsafe (POST/PUT/DELETE) requests.
function getCsrfToken() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
}

// Fetch JSON, rejecting on any non-2xx response. Use for required resources.
function fetchJson(url, options) {
    return fetch(url, options).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
    });
}

// Fetch JSON, resolving to null on a missing resource or network error.
// Use for optional resources a page can render without.
function fetchJsonOrNull(url, options) {
    return fetch(url, options)
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
}
