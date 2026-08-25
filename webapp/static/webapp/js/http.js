/* Shared HTTP helpers for the live web UI.
   Loaded as a plain <script> (not a module), so these are globals shared by
   every template that extends webapp/index.html. The static HTML export bundle
   has module equivalents in webapp_engine/map/js/utils.js. */

/* exported fetchJson, fetchJsonOrNull, getCsrfToken, formDataWithCsrf */

// Read Django's CSRF cookie for unsafe (POST/PUT/DELETE) requests. The name is
// anchored to a cookie boundary so a cookie merely *ending* in "csrftoken" (or a
// value containing the string) can't be picked up instead.
function getCsrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return m ? m[1] : "";
}

// Serialize a form for an unsafe request, refreshing its CSRF field from the
// cookie. Django reads "csrfmiddlewaretoken" from the body in preference to the
// X-CSRFToken header, so a page left open while the cookie is replaced would
// otherwise keep posting the token frozen at render time and get a 403 until
// someone reloads it by hand.
function formDataWithCsrf(form) {
    var fd = new FormData(form);
    var token = getCsrfToken();
    if (token) fd.set("csrfmiddlewaretoken", token);
    else fd.delete("csrfmiddlewaretoken");
    return fd;
}

// Fetch JSON, rejecting on any non-2xx response. Use for required resources.
function fetchJson(url, options) {
    return fetch(url, options).then(function(r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
    });
}

// Fetch JSON, resolving to null on a missing resource or network error.
// Use for optional resources a page can render without.
function fetchJsonOrNull(url, options) {
    return fetch(url, options)
        .then(function(r) { return r.ok ? r.json() : null; })
        .catch(function() { return null; });
}
