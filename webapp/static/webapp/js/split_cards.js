/* Home page summary cards split by label (webapp/home_split.py): each card's split button shows or hides the
   tables of every card at once. The choice is kept in this browser, so switching scope or split keeps it. */
(function() {
    "use strict";
    var STORAGE_KEY = "pulpit_home_split_open";
    var page = document.querySelector(".home-page");
    var toggles = page ? page.querySelectorAll(".sc-split-toggle") : [];
    if (!toggles.length) return;

    function remembered() {
        try { return localStorage.getItem(STORAGE_KEY) === "1"; } catch (e) { return false; }
    }

    function remember(open) {
        try { localStorage.setItem(STORAGE_KEY, open ? "1" : "0"); } catch (e) {}
    }

    function setOpen(open) {
        page.classList.toggle("split-open", open);
        toggles.forEach(function(toggle) { toggle.setAttribute("aria-expanded", String(open)); });
    }

    toggles.forEach(function(toggle) {
        toggle.addEventListener("click", function() {
            var open = !page.classList.contains("split-open");
            setOpen(open);
            remember(open);
        });
    });
    setOpen(remembered());
})();
