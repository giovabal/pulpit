/* Pulpit accessibility helpers — static export bundle.
   Mirror lives at webapp/static/webapp/js/a11y.js. Keep the public API in sync. */
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
    region.textContent = "";
    setTimeout(function () {
      region.textContent = String(text);
    }, 50);
  }

  function _buildSrTable(opts) {
    var table = document.createElement("table");
    // No sr-only here: the surrounding .sr-chart-table-wrap owns the hide/show
    // behaviour. If we duplicated sr-only on the table, removing the class from
    // the wrap would still leave the table itself absolutely positioned and
    // clipped to 1×1, so toggling the button would just open empty space.
    table.className = "sr-chart-table";
    if (opts.label) {
      var caption = document.createElement("caption");
      caption.textContent = opts.label;
      table.appendChild(caption);
    }
    if (Array.isArray(opts.columns) && opts.columns.length) {
      var thead = document.createElement("thead");
      var trh = document.createElement("tr");
      opts.columns.forEach(function (c) {
        var th = document.createElement("th");
        th.scope = "col";
        th.textContent = c;
        trh.appendChild(th);
      });
      thead.appendChild(trh);
      table.appendChild(thead);
    }
    var tbody = document.createElement("tbody");
    (opts.rows || []).forEach(function (row) {
      var tr = document.createElement("tr");
      row.forEach(function (cell, idx) {
        var td = idx === 0 ? document.createElement("th") : document.createElement("td");
        if (idx === 0) td.scope = "row";
        td.textContent = cell == null ? "" : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function accessibleChart(canvas, opts) {
    if (!canvas) return null;
    opts = opts || {};
    var label = opts.label || "Chart";
    var summary = opts.summary ? label + ". " + opts.summary : label;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", summary);
    if (!Array.isArray(opts.rows) || opts.rows.length === 0) return null;

    // Where to mount the button + data-table wrap. By default we sit them
    // alongside the canvas in its direct parent; callers that wrap the canvas
    // inside a fixed-height container (e.g. .rb-chart-canvas with height:
    // 280px) must pass an outer `host` so the data table doesn't overflow the
    // chart container and bleed onto the next card.
    var host = opts.host || canvas.parentNode;
    if (!host) return null;
    var anchor = canvas;
    while (anchor && anchor.parentNode !== host) anchor = anchor.parentNode;
    if (!anchor) return null;

    var table = _buildSrTable(opts);
    var wrap = document.createElement("div");
    wrap.className = "sr-chart-table-wrap sr-only";
    wrap.hidden = !opts.visible;
    wrap.appendChild(table);
    host.insertBefore(wrap, anchor.nextSibling);
    if (opts.toggle) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-sm btn-outline-secondary sr-chart-toggle";
      btn.textContent = "Show data table";
      btn.setAttribute("aria-expanded", "false");
      btn.addEventListener("click", function () {
        var nowHidden = !wrap.hidden;
        wrap.hidden = nowHidden;
        wrap.classList.toggle("sr-only", nowHidden);
        btn.setAttribute("aria-expanded", nowHidden ? "false" : "true");
        btn.textContent = nowHidden ? "Show data table" : "Hide data table";
      });
      host.insertBefore(btn, anchor);
    }
    return table;
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
