/* Pulpit accessibility helpers — live Django UI.
   Mirror lives at webapp_engine/map/js/a11y.js. Keep the public API in sync. */
(function (global) {
  "use strict";

  var POLITE_ID = "a11y-live-polite";
  var ASSERTIVE_ID = "a11y-live-assertive";

  function ensureRegion(id, politeness) {
    var el = document.getElementById(id);
    if (el) return el;
    el = document.createElement("div");
    el.id = id;
    el.className = "sr-only";
    el.setAttribute("aria-live", politeness);
    el.setAttribute("aria-atomic", "true");
    document.body.appendChild(el);
    return el;
  }

  function announce(text, politeness) {
    if (!text) return;
    var id = politeness === "assertive" ? ASSERTIVE_ID : POLITE_ID;
    var region = ensureRegion(id, politeness === "assertive" ? "assertive" : "polite");
    // Clear first so duplicate announcements still re-fire.
    region.textContent = "";
    setTimeout(function () {
      region.textContent = String(text);
    }, 50);
  }

  function accessibleChart(canvas, opts) {
    if (!canvas) return;
    opts = opts || {};
    var label = opts.label || "Chart";
    var summary = opts.summary ? label + ". " + opts.summary : label;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", summary);
  }

  function enhanceSortableHeaders(table, opts) {
    if (!table) return;
    opts = opts || {};
    var headers = table.querySelectorAll("thead th[data-sortable], thead th.sortable, thead th[data-sort-key]");
    Array.prototype.forEach.call(headers, function (th) {
      if (th.dataset.a11yEnhanced === "1") return;
      th.dataset.a11yEnhanced = "1";
      var existing = th.querySelector("a, button.th-sort-btn");
      var labelText = (existing ? existing.textContent : th.textContent).trim();
      th.textContent = "";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "th-sort-btn";
      btn.textContent = labelText;
      th.appendChild(btn);
      if (!th.hasAttribute("aria-sort")) th.setAttribute("aria-sort", "none");
      btn.addEventListener("click", function () {
        // Direction is updated by the caller; announce the final state after a microtask.
        setTimeout(function () {
          var dir = th.getAttribute("aria-sort") || "none";
          if (dir === "none") return;
          var name = opts.colName ? opts.colName(th, labelText) : labelText;
          announce("Sorted by " + name + ", " + dir);
        }, 0);
      });
    });
  }

  global.PulpitA11y = {
    announce: announce,
    accessibleChart: accessibleChart,
    enhanceSortableHeaders: enhanceSortableHeaders,
  };
})(window);
