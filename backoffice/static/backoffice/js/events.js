(function () {
    "use strict";
    var API_ET = "/manage/api/event-types/";
    var API_EV = "/manage/api/events/";

    var _types = [];

    /* ── Event types ──────────────────────────────────────────────────── */
    var $etTbody   = document.getElementById("et-tbody");
    var $etAddBtn  = document.getElementById("et-add-btn");
    var $etAddForm = document.getElementById("et-add-form");
    var $etCancel  = document.getElementById("et-add-cancel");
    var $evTypeFilter = document.getElementById("ev-type-filter");
    var $evTypeSelect = document.getElementById("ev-type-select");
    var $evYearFilter = document.getElementById("ev-year-filter");

    function renderTypeRow(et, editing) {
        var tr = document.createElement("tr"); tr.dataset.id = et.id;
        if (editing) {
            var tdC = document.createElement("td");
            var cIn = document.createElement("input"); cIn.type = "color"; cIn.className = "bo-input bo-input--color"; cIn.value = et.color || "#4338ca";
            tdC.appendChild(cIn); tr.appendChild(tdC);
            var tdN = document.createElement("td");
            var nIn = document.createElement("input"); nIn.className = "bo-input"; nIn.value = et.name;
            tdN.appendChild(nIn); tr.appendChild(tdN);
            var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num"; tdCnt.textContent = fmtInt(et.event_count); tr.appendChild(tdCnt);
            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                apiFetch(API_ET + et.id + "/", { method: "PATCH", body: { name: nIn.value.trim(), color: cIn.value } })
                    .then(function (updated) { Object.assign(et, updated); refreshTypeRow(tr, et); showToast("Saved."); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () { refreshTypeRow(tr, et); });
            tdA.appendChild(saveBtn); tdA.appendChild(cancelBtn); tr.appendChild(tdA);
        } else {
            var tdCd = document.createElement("td");
            var dot = document.createElement("span"); dot.className = "bo-org-dot"; dot.style.background = et.color || "#ccc";
            tdCd.appendChild(dot); tr.appendChild(tdCd);
            var tdNd = document.createElement("td"); tdNd.textContent = et.name; tr.appendChild(tdNd);
            var tdCntd = document.createElement("td"); tdCntd.className = "bo-td--num"; tdCntd.textContent = fmtInt(et.event_count); tr.appendChild(tdCntd);
            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn(); editBtn.addEventListener("click", function () { refreshTypeRow(tr, et, true); });
            var delBtn = makeDeleteBtn(et.name); delBtn.addEventListener("click", function () {
                confirmDelete(et.name).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API_ET + et.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); _types = _types.filter(function (t) { return t.id !== et.id; }); rebuildTypeSelects(); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn); tdAd.appendChild(delBtn); tr.appendChild(tdAd);
        }
        return tr;
    }

    function refreshTypeRow(tr, et, editing) {
        var newTr = renderTypeRow(et, !!editing);
        $etTbody.replaceChild(newTr, tr);
    }

    function rebuildTypeSelects() {
        [$evTypeFilter, $evTypeSelect].forEach(function (sel) {
            while (sel.options.length > (sel === $evTypeFilter ? 1 : 0)) sel.remove(sel.options.length - 1);
            _types.forEach(function (t) { sel.appendChild(new Option(t.name, t.id)); });
        });
    }

    function loadTypes() {
        apiFetch(API_ET + "?limit=500").then(function (data) {
            _types = data.results;
            $etTbody.innerHTML = "";
            if (!_types.length) { $etTbody.innerHTML = '<tr><td colspan="4" class="bo-empty">No event types yet.</td></tr>'; }
            else { _types.forEach(function (t) { $etTbody.appendChild(renderTypeRow(t, false)); }); }
            rebuildTypeSelects();
        }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    $etAddBtn.addEventListener("click", function () { $etAddForm.classList.remove("d-none"); $etAddBtn.classList.add("d-none"); });
    $etCancel.addEventListener("click", function () { $etAddForm.classList.add("d-none"); $etAddBtn.classList.remove("d-none"); $etAddForm.reset(); });
    $etAddForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($etAddForm);
        apiFetch(API_ET, { method: "POST", body: { name: fd.get("name").trim(), color: fd.get("color") } })
            .then(function (et) {
                et.event_count = 0; _types.push(et);
                var empty = $etTbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $etTbody.appendChild(renderTypeRow(et, false));
                rebuildTypeSelects();
                $etAddForm.reset(); $etAddForm.classList.add("d-none"); $etAddBtn.classList.remove("d-none");
                showToast("Event type created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    /* ── Events ───────────────────────────────────────────────────────── */
    var $evTbody      = document.getElementById("ev-tbody");
    var $evAddBtn     = document.getElementById("ev-add-btn");
    var $evAddForm    = document.getElementById("ev-add-form");
    var $evCancel     = document.getElementById("ev-add-cancel");
    var $evPaginTop   = document.getElementById("ev-pagination-top");
    var $evPaginBottom= document.getElementById("ev-pagination-bottom");
    var $evCount      = document.getElementById("ev-count");
    var _evOffset = 0;
    var _evTotal  = 0;

    function _evGoToPage(offset) { _evOffset = offset; loadEvents(); }
    function _evRenderPagination() {
        renderPagination($evPaginTop, _evOffset, _evTotal, BACKOFFICE_PAGE_SIZE, _evGoToPage);
        renderPagination($evPaginBottom, _evOffset, _evTotal, BACKOFFICE_PAGE_SIZE, _evGoToPage);
        $evCount.textContent = _evTotal + " event" + (_evTotal !== 1 ? "s" : "");
    }

    function renderEventRow(ev) {
        var tr = document.createElement("tr"); tr.dataset.id = ev.id;
        var tdD = document.createElement("td"); tdD.textContent = fmtDate(ev.date); tr.appendChild(tdD);
        var tdT = document.createElement("td");
        var dot = document.createElement("span"); dot.className = "bo-org-dot"; dot.style.background = ev.action_color || "#ccc";
        tdT.appendChild(dot); tdT.appendChild(document.createTextNode(ev.action_name)); tr.appendChild(tdT);
        var tdS = document.createElement("td"); tdS.textContent = ev.subject; tr.appendChild(tdS);
        var tdA = document.createElement("td");
        var delBtn = makeDeleteBtn(ev.subject); delBtn.addEventListener("click", function () {
            confirmDelete(ev.subject).then(function (ok) {
                if (!ok) return;
                apiFetch(API_EV + ev.id + "/", { method: "DELETE" })
                    .then(function () { tr.remove(); _evTotal--; _evRenderPagination(); showToast("Deleted."); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
        });
        tdA.appendChild(delBtn); tr.appendChild(tdA);
        return tr;
    }

    function loadEvents() {
        var params = new URLSearchParams({ limit: BACKOFFICE_PAGE_SIZE, offset: _evOffset });
        var t = $evTypeFilter.value; if (t) params.set("type", t);
        var y = $evYearFilter.value; if (y) params.set("year", y);
        apiFetch(API_EV + "?" + params.toString()).then(function (data) {
            _evTotal = data.count;
            $evTbody.innerHTML = "";
            if (!data.results.length) { $evTbody.innerHTML = '<tr><td colspan="4" class="bo-empty">No events found.</td></tr>'; }
            else {
                /* Populate year filter from full result set first time */
                if ($evYearFilter.options.length <= 1) {
                    var years = new Set(data.results.map(function (e) { return e.date.slice(0, 4); }));
                    Array.from(years).sort().reverse().forEach(function (y) { $evYearFilter.appendChild(new Option(y, y)); });
                }
                data.results.forEach(function (ev) { $evTbody.appendChild(renderEventRow(ev)); });
            }
            _evRenderPagination();
        }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    [$evTypeFilter, $evYearFilter].forEach(function (el) {
        el.addEventListener("change", function () { _evOffset = 0; loadEvents(); });
    });

    $evAddBtn.addEventListener("click", function () { $evAddForm.classList.remove("d-none"); $evAddBtn.classList.add("d-none"); });
    $evCancel.addEventListener("click", function () { $evAddForm.classList.add("d-none"); $evAddBtn.classList.remove("d-none"); $evAddForm.reset(); });
    $evAddForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($evAddForm);
        apiFetch(API_EV, { method: "POST", body: { date: fd.get("date"), subject: fd.get("subject").trim(), action_id: parseInt(fd.get("action_id"), 10) } })
            .then(function (ev) {
                var empty = $evTbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $evTbody.insertBefore(renderEventRow(ev), $evTbody.firstChild);
                $evAddForm.reset(); $evAddForm.classList.add("d-none"); $evAddBtn.classList.remove("d-none");
                showToast("Event created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadTypes();
    loadEvents();
})();
