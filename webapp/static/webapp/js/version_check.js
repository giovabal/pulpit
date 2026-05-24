/* New-version indicator for the live web UI.
   Loaded as a plain <script> right after http.js, so it can use the global
   fetchJsonOrNull helper and runs once every [data-update-dot] in the page
   shell (Manage button, Maintenance menu) has already been parsed.

   Publishes window.pulpitVersion = { ready, dismiss } so the Maintenance page
   (backoffice/.../maintenance.js) can reuse this single lookup for its banner
   without fetching again. */
(function () {
    "use strict";

    var DISMISS_KEY = "pulpit_dismissed_version";
    var url = document.body.dataset.versionCheckUrl;
    var status = null;

    function dismissedVersion() {
        try {
            return localStorage.getItem(DISMISS_KEY);
        } catch (e) {
            return null;
        }
    }

    function eachDot(fn) {
        var dots = document.querySelectorAll("[data-update-dot]");
        for (var i = 0; i < dots.length; i++) {
            fn(dots[i]);
        }
    }

    function setDots(show) {
        eachDot(function (dot) {
            dot.hidden = !show;
            var host = dot.parentElement;
            if (!host) return;
            if (show) {
                host.setAttribute("title", "A new version of Pulpit is available");
            } else {
                host.removeAttribute("title");
            }
        });
    }

    // Light up the attention dots, unless the operator already dismissed *this*
    // version — dismissal is per-version, so a newer release lights them again.
    function refreshDots() {
        var show = !!status && status.update_available && dismissedVersion() !== status.latest;
        setDots(show);
    }

    // Acknowledge the current version: remember the choice and hide the dots.
    // The Maintenance banner is intentionally left in place (handled there).
    function dismiss() {
        if (status && status.latest) {
            try {
                localStorage.setItem(DISMISS_KEY, status.latest);
            } catch (e) {
                /* storage disabled (private mode) — dots simply reappear next load */
            }
        }
        setDots(false);
    }

    var ready = (url ? fetchJsonOrNull(url) : Promise.resolve(null)).then(function (data) {
        status = data;
        refreshDots();
        return data;
    });

    window.pulpitVersion = { ready: ready, dismiss: dismiss };
})();
