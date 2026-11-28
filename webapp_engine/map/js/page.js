// A page opened straight from a folder (file://): browsers block the scripts that read the page's data, so it
// would stay on "Loading…" with nothing said. This script is a classic one, which still runs there, so it says it.
// Only on the pages that read data (they load a module script); a page that already carries the notice keeps it.
(function() {
    if (window.location.protocol !== "file:") return;
    var main = document.getElementById("main-content");
    if (!main || document.getElementById("export-file-notice")) return;
    if (!document.querySelector("script[type=\"module\"]")) return;
    var notice = document.createElement("p");
    notice.id = "export-file-notice";
    notice.className = "export-notice";
    notice.setAttribute("role", "alert");
    notice.textContent = "This page reads its data through scripts that browsers block when a page is opened straight " +
        "from a folder. Serve the folder over HTTP — for instance run \"python3 -m http.server\" inside it and open " +
        "http://localhost:8000 — or publish it on a web server.";
    main.insertBefore(notice, main.firstChild);
    // Nothing will load: the "Loading…" placeholders would wait for ever.
    Array.prototype.forEach.call(main.querySelectorAll("p, span, div, td"), function(el) {
        if (el.children.length === 0 && el.textContent.trim() === "Loading…") el.textContent = "";
    });
})();

// "On this page": the section headings (h2) of the page as links, in #export-toc when the page has one.
// Page scripts draw most sections after the data arrive, so the list follows the page as it fills in.
(function() {
    var toc = document.getElementById("export-toc");
    var main = document.getElementById("main-content");
    if (!toc || !main) return;

    function slug(text) {
        return "section-" + text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    }

    function headings() {
        return Array.prototype.filter.call(main.querySelectorAll("h2"), function(h) {
            if (h.closest(".export-page-head, .modal, .dropdown-menu, [hidden], .d-none")) return false;
            return h.textContent.trim() !== "";
        });
    }

    function refresh() {
        var list = headings();
        var signature = list.map(function(h) {
            return h.textContent.trim();
        }).join("\u0000");
        if (toc.getAttribute("data-signature") === signature) return;
        toc.setAttribute("data-signature", signature);
        toc.textContent = "";
        if (list.length < 2) return;
        var label = document.createElement("span");
        label.className = "export-toc-label";
        label.textContent = "On this page";
        toc.appendChild(label);
        list.forEach(function(h) {
            if (!h.id) h.id = slug(h.textContent.trim());
            var a = document.createElement("a");
            a.href = "#" + h.id;
            a.textContent = h.textContent.trim();
            toc.appendChild(a);
        });
    }

    var pending = null;
    new MutationObserver(function() {
        if (pending) clearTimeout(pending);
        pending = setTimeout(refresh, 150);
    }).observe(main, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "hidden"] });
    refresh();
})();
