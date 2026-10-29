(function() {
    "use strict";
    var API_ET = "/manage/api/event-types/";
    var API_EV = "/manage/api/events/";
    var API_LABELS = "/manage/api/labels/";

    var _types = [];
    // Every label, grouped by label group, for the scope selectors (an event may concern part of the network).
    var _labels = [];

    /* ── Event types ──────────────────────────────────────────────────── */
    var $etTbody = document.getElementById("et-tbody");
    var $etAddBtn = document.getElementById("et-add-btn");
    var $etAddForm = document.getElementById("et-add-form");
    var $etCancel = document.getElementById("et-add-cancel");
    var $evTypeFilter = document.getElementById("ev-type-filter");
    var $evTypeSelect = document.getElementById("ev-type-select");
    var $evYearFilter = document.getElementById("ev-year-filter");

    function renderTypeRow(et, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = et.id;
        if (editing) {
            var tdC = document.createElement("td");
            var cIn = document.createElement("input");
            cIn.type = "color";
            cIn.className = "bo-input bo-input--color";
            cIn.value = et.color || "#4338ca";
            tdC.appendChild(cIn);
            tr.appendChild(tdC);
            var tdN = document.createElement("td");
            var nIn = document.createElement("input");
            nIn.className = "bo-input";
            nIn.value = et.name;
            tdN.appendChild(nIn);
            tr.appendChild(tdN);
            var tdCnt = document.createElement("td");
            tdCnt.className = "bo-td--num";
            tdCnt.textContent = fmtInt(et.event_count);
            tr.appendChild(tdCnt);
            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button");
            saveBtn.className = "bo-btn bo-btn--sm";
            saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button");
            cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost";
            cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function() {
                apiFetch(API_ET + et.id + "/", { method: "PATCH", body: { name: nIn.value.trim(), color: cIn.value } })
                    .then(function(updated) {
                        Object.assign(et, updated);
                        refreshTypeRow(tr, et);
                        showToast("Saved.");
                    })
                    .catch(function(e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function() { refreshTypeRow(tr, et); });
            tdA.appendChild(saveBtn);
            tdA.appendChild(cancelBtn);
            tr.appendChild(tdA);
        } else {
            var tdCd = document.createElement("td");
            var dot = document.createElement("span");
            dot.className = "bo-org-dot";
            dot.style.background = et.color || "#ccc";
            tdCd.appendChild(dot);
            tr.appendChild(tdCd);
            var tdNd = document.createElement("td");
            tdNd.textContent = et.name;
            tr.appendChild(tdNd);
            var tdCntd = document.createElement("td");
            tdCntd.className = "bo-td--num";
            tdCntd.textContent = fmtInt(et.event_count);
            tr.appendChild(tdCntd);
            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function() { refreshTypeRow(tr, et, true); });
            var delBtn = makeDeleteBtn(et.name);
            delBtn.addEventListener("click", function() {
                confirmDelete(et.name).then(function(ok) {
                    if (!ok) return;
                    apiFetch(API_ET + et.id + "/", { method: "DELETE" })
                        .then(function() {
                            tr.remove();
                            _types = _types.filter(function(t) { return t.id !== et.id; });
                            rebuildTypeSelects();
                            showToast("Deleted.");
                        })
                        .catch(function(e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn);
            tdAd.appendChild(delBtn);
            tr.appendChild(tdAd);
        }
        return tr;
    }

    function refreshTypeRow(tr, et, editing) {
        var newTr = renderTypeRow(et, !!editing);
        $etTbody.replaceChild(newTr, tr);
    }

    function rebuildTypeSelects() {
        [$evTypeFilter, $evTypeSelect].forEach(function(sel) {
            while (sel.options.length > (sel === $evTypeFilter ? 1 : 0)) sel.remove(sel.options.length - 1);
            _types.forEach(function(t) { sel.appendChild(new Option(t.name, t.id)); });
        });
    }

    function loadTypes() {
        return apiFetch(API_ET + "?limit=500").then(function(data) {
            _types = data.results;
            $etTbody.innerHTML = "";
            if (!_types.length) { $etTbody.innerHTML = '<tr><td colspan="4" class="bo-empty">No event types yet.</td></tr>'; } else { _types.forEach(function(t) { $etTbody.appendChild(renderTypeRow(t, false)); }); }
            rebuildTypeSelects();
        }).catch(function(e) { showToast("Error: " + e.message, "error"); });
    }

    // Populate year filter once from the full event list (separate from the
    // paginated table fetch, which would otherwise only ever see the first page).
    function loadYearFilter() {
        return apiFetch(API_EV + "?limit=10000&fields=date").then(function(data) {
            var years = new Set((data.results || []).map(function(e) { return e.date.slice(0, 4); }));
            Array.from(years).sort().reverse().forEach(function(y) {
                $evYearFilter.appendChild(new Option(y, y));
            });
        }).catch(function() { /* non-fatal — filter just stays empty */ });
    }

    $etAddBtn.addEventListener("click", function() {
        $etAddForm.classList.remove("d-none");
        $etAddBtn.classList.add("d-none");
    });
    $etCancel.addEventListener("click", function() {
        $etAddForm.classList.add("d-none");
        $etAddBtn.classList.remove("d-none");
        $etAddForm.reset();
    });
    $etAddForm.addEventListener("submit", function(e) {
        e.preventDefault();
        var fd = new FormData($etAddForm);
        apiFetch(API_ET, { method: "POST", body: { name: fd.get("name").trim(), color: fd.get("color") } })
            .then(function(et) {
                et.event_count = 0;
                _types.push(et);
                var empty = $etTbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $etTbody.appendChild(renderTypeRow(et, false));
                rebuildTypeSelects();
                $etAddForm.reset();
                $etAddForm.classList.add("d-none");
                $etAddBtn.classList.remove("d-none");
                showToast("Event type created.");
            }).catch(function(e) { showToast("Error: " + e.message, "error"); });
    });

    /* ── Events ───────────────────────────────────────────────────────── */
    var $evTbody = document.getElementById("ev-tbody");
    var $evAddBtn = document.getElementById("ev-add-btn");
    var $evAddForm = document.getElementById("ev-add-form");
    var $evCancel = document.getElementById("ev-add-cancel");
    var $evPaginTop = document.getElementById("ev-pagination-top");
    var $evPaginBottom = document.getElementById("ev-pagination-bottom");
    var $evCount = document.getElementById("ev-count");
    var _evOffset = 0;
    var _evTotal = 0;

    function _evGoToPage(offset) {
        _evOffset = offset;
        loadEvents();
    }

    function _evRenderPagination() {
        renderPagination($evPaginTop, _evOffset, _evTotal, BACKOFFICE_PAGE_SIZE, _evGoToPage);
        renderPagination($evPaginBottom, _evOffset, _evTotal, BACKOFFICE_PAGE_SIZE, _evGoToPage);
        $evCount.textContent = _evTotal + " event" + (_evTotal !== 1 ? "s" : "");
    }

    // Fill a <select multiple> with the labels, one <optgroup> per label group, selecting `selected` ids.
    function fillScopeSelect(sel, selected) {
        var chosen = new Set((selected || []).map(Number));
        sel.innerHTML = "";
        var groups = {};
        _labels.forEach(function(l) {
            if (!groups[l.group_name]) {
                groups[l.group_name] = document.createElement("optgroup");
                groups[l.group_name].label = l.group_name;
                sel.appendChild(groups[l.group_name]);
            }
            var opt = new Option(l.name, l.id, false, chosen.has(l.id));
            groups[l.group_name].appendChild(opt);
        });
    }

    function selectedIds(sel) {
        return Array.from(sel.selectedOptions).map(function(o) { return parseInt(o.value, 10); });
    }

    function scopeCell(ev) {
        var td = document.createElement("td");
        if (!ev.labels || !ev.labels.length) {
            td.className = "text-muted";
            td.textContent = "Whole network";
            return td;
        }
        td.textContent = ev.labels.map(function(l) { return l.group + ": " + l.name; }).join(", ");
        return td;
    }

    function renderEventEditRow(ev, tr) {
        var row = document.createElement("tr");
        row.dataset.id = ev.id;
        var dIn = document.createElement("input");
        dIn.type = "date";
        dIn.className = "bo-input";
        dIn.value = ev.date;
        dIn.setAttribute("aria-label", "Event date");
        var tIn = document.createElement("select");
        tIn.className = "bo-select";
        tIn.setAttribute("aria-label", "Event type");
        _types.forEach(function(t) { tIn.appendChild(new Option(t.name, t.id, false, t.id === ev.action_id)); });
        var sIn = document.createElement("input");
        sIn.className = "bo-input bo-input--wide";
        sIn.value = ev.subject;
        sIn.setAttribute("aria-label", "Event subject");
        var scIn = document.createElement("select");
        scIn.className = "bo-select bo-select--multi";
        scIn.multiple = true;
        scIn.size = 4;
        scIn.setAttribute("aria-label", "Labels the event concerns (none = the whole network)");
        fillScopeSelect(scIn, (ev.labels || []).map(function(l) { return l.id; }));
        [dIn, tIn, sIn, scIn].forEach(function(el) {
            var td = document.createElement("td");
            td.appendChild(el);
            row.appendChild(td);
        });
        var tdA = document.createElement("td");
        var saveBtn = document.createElement("button");
        saveBtn.className = "bo-btn bo-btn--sm";
        saveBtn.textContent = "Save";
        var cancelBtn = document.createElement("button");
        cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost";
        cancelBtn.textContent = "Cancel";
        saveBtn.addEventListener("click", function() {
            var body = {
                date: dIn.value,
                subject: sIn.value.trim(),
                action_id: parseInt(tIn.value, 10),
                label_ids: selectedIds(scIn),
            };
            apiFetch(API_EV + ev.id + "/", { method: "PATCH", body: body })
                .then(function(updated) {
                    $evTbody.replaceChild(renderEventRow(updated), row);
                    showToast("Saved.");
                })
                .catch(function(e) { showToast("Error: " + e.message, "error"); });
        });
        cancelBtn.addEventListener("click", function() { $evTbody.replaceChild(tr, row); });
        tdA.appendChild(saveBtn);
        tdA.appendChild(cancelBtn);
        row.appendChild(tdA);
        return row;
    }

    function renderEventRow(ev) {
        var tr = document.createElement("tr");
        tr.dataset.id = ev.id;
        var tdD = document.createElement("td");
        tdD.textContent = fmtDate(ev.date);
        tr.appendChild(tdD);
        var tdT = document.createElement("td");
        var dot = document.createElement("span");
        dot.className = "bo-org-dot";
        dot.style.background = ev.action_color || "#ccc";
        tdT.appendChild(dot);
        tdT.appendChild(document.createTextNode(ev.action_name));
        tr.appendChild(tdT);
        var tdS = document.createElement("td");
        tdS.textContent = ev.subject;
        tr.appendChild(tdS);
        tr.appendChild(scopeCell(ev));
        var tdA = document.createElement("td");
        var editBtn = makeEditBtn();
        editBtn.addEventListener("click", function() {
            $evTbody.replaceChild(renderEventEditRow(ev, tr), tr);
        });
        var delBtn = makeDeleteBtn(ev.subject);
        delBtn.addEventListener("click", function() {
            confirmDelete(ev.subject).then(function(ok) {
                if (!ok) return;
                apiFetch(API_EV + ev.id + "/", { method: "DELETE" })
                    .then(function() {
                        tr.remove();
                        _evTotal--;
                        _evRenderPagination();
                        showToast("Deleted.");
                    })
                    .catch(function(e) { showToast("Error: " + e.message, "error"); });
            });
        });
        tdA.appendChild(editBtn);
        tdA.appendChild(delBtn);
        tr.appendChild(tdA);
        return tr;
    }

    function loadLabels() {
        return apiFetch(API_LABELS + "?limit=10000").then(function(data) {
            _labels = data.results || [];
            fillScopeSelect(document.getElementById("ev-scope-select"), []);
        }).catch(function() { /* non-fatal — events stay network-wide */ });
    }

    function loadEvents() {
        var params = new URLSearchParams({ limit: BACKOFFICE_PAGE_SIZE, offset: _evOffset });
        var t = $evTypeFilter.value;
        if (t) params.set("type", t);
        var y = $evYearFilter.value;
        if (y) params.set("year", y);
        apiFetch(API_EV + "?" + params.toString()).then(function(data) {
            _evTotal = data.count;
            $evTbody.innerHTML = "";
            if (!data.results.length) {
                $evTbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No events found.</td></tr>';
            } else {
                data.results.forEach(function(ev) { $evTbody.appendChild(renderEventRow(ev)); });
            }
            _evRenderPagination();
        }).catch(function(e) { showToast("Error: " + e.message, "error"); });
    }

    [$evTypeFilter, $evYearFilter].forEach(function(el) {
        el.addEventListener("change", function() {
            _evOffset = 0;
            loadEvents();
        });
    });

    $evAddBtn.addEventListener("click", function() {
        $evAddForm.classList.remove("d-none");
        $evAddBtn.classList.add("d-none");
    });
    $evCancel.addEventListener("click", function() {
        $evAddForm.classList.add("d-none");
        $evAddBtn.classList.remove("d-none");
        $evAddForm.reset();
    });
    $evAddForm.addEventListener("submit", function(e) {
        e.preventDefault();
        var fd = new FormData($evAddForm);
        var body = {
            date: fd.get("date"),
            subject: fd.get("subject").trim(),
            action_id: parseInt(fd.get("action_id"), 10),
            label_ids: selectedIds(document.getElementById("ev-scope-select")),
        };
        apiFetch(API_EV, { method: "POST", body: body })
            .then(function(ev) {
                var empty = $evTbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $evTbody.insertBefore(renderEventRow(ev), $evTbody.firstChild);
                _evTotal++;
                _evRenderPagination();
                $evAddForm.reset();
                $evAddForm.classList.add("d-none");
                $evAddBtn.classList.remove("d-none");
                showToast("Event created.");
            }).catch(function(e) { showToast("Error: " + e.message, "error"); });
    });

    // Sequence the init so the type filter is populated before the user can
    // interact with it. Year filter loads in parallel — it does not gate
    // anything in the events table.
    loadYearFilter();
    Promise.all([loadTypes(), loadLabels()]).then(loadEvents);
})();
