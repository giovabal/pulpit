(function () {
    "use strict";
    var API      = "/manage/api/vacancies/";
    var CH_API   = "/manage/api/channels/?status=in_target&";
    var _total   = 0;

    var $tbody    = document.getElementById("vac-tbody");
    var $count    = document.getElementById("vac-count");
    var $addBtn   = document.getElementById("vac-add-btn");
    var $addForm  = document.getElementById("vac-add-form");
    var $addCancel = document.getElementById("vac-add-cancel");
    var $chSearch = document.getElementById("vac-ch-search");
    var $chId     = document.getElementById("vac-ch-id");
    var $chDrop   = document.getElementById("vac-ch-dropdown");
    var $succSearch = document.getElementById("vac-succ-search");
    var $succId   = document.getElementById("vac-succ-id");
    var $succDrop = document.getElementById("vac-succ-dropdown");
    var $closureDate = document.getElementById("vac-closure-date");
    var $note     = document.getElementById("vac-note");

    // ---- channel typeahead (shared by the channel and successor fields) ----
    // Returns a teardown function removing the outside-click listener.
    function wireTypeahead(input, hiddenInput, drop) {
        var timer = null;
        input.addEventListener("input", function () {
            clearTimeout(timer);
            var q = input.value.trim();
            hiddenInput.value = "";
            if (!q) { drop.style.display = "none"; return; }
            timer = setTimeout(function () {
                apiFetch(CH_API + "search=" + encodeURIComponent(q) + "&limit=10")
                    .then(function (data) {
                        var items = (data.results || []);
                        if (!items.length) { drop.style.display = "none"; return; }
                        drop.innerHTML = "";
                        items.forEach(function (ch) {
                            var d = document.createElement("div");
                            d.className = "bo-typeahead-item";
                            d.textContent = ch.title + (ch.username ? " (@" + ch.username + ")" : "");
                            d.addEventListener("mousedown", function (e) {
                                e.preventDefault();
                                input.value = ch.title;
                                hiddenInput.value = ch.id;
                                drop.style.display = "none";
                            });
                            drop.appendChild(d);
                        });
                        drop.style.display = "block";
                    }).catch(function () {});
            }, 250);
        });
        function closeHandler(e) {
            if (!drop.contains(e.target) && e.target !== input) drop.style.display = "none";
        }
        document.addEventListener("click", closeHandler);
        return function () { document.removeEventListener("click", closeHandler); };
    }

    wireTypeahead($chSearch, $chId, $chDrop);
    wireTypeahead($succSearch, $succId, $succDrop);

    // Builds an inline typeahead-backed channel picker for an edit row.
    function editPicker(title, id) {
        var input = document.createElement("input"); input.className = "bo-input"; input.value = title || "";
        var hidden = document.createElement("input"); hidden.type = "hidden"; hidden.value = id || "";
        var drop = document.createElement("div"); drop.className = "bo-typeahead"; drop.style.display = "none";
        var wrap = document.createElement("div"); wrap.style.position = "relative";
        wrap.appendChild(input); wrap.appendChild(drop); wrap.appendChild(hidden);
        var teardown = wireTypeahead(input, hidden, drop);
        return { wrap: wrap, input: input, hidden: hidden, teardown: teardown };
    }

    var _closeOpenEdit = null;   // reverts the currently-open edit row (per-row closure)

    // ---- render row ----
    function renderRow(vac, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = vac.id;

        if (editing) {
            if (_closeOpenEdit) _closeOpenEdit();

            var chPicker = editPicker(vac.channel_title, vac.channel_id);
            chPicker.input.style.minWidth = "22rem";
            var tdCh = document.createElement("td");
            tdCh.appendChild(chPicker.wrap); tr.appendChild(tdCh);

            var tdDate = document.createElement("td");
            var dateInput = document.createElement("input"); dateInput.className = "bo-input"; dateInput.type = "date"; dateInput.value = vac.closure_date || "";
            tdDate.appendChild(dateInput); tr.appendChild(tdDate);

            var succPicker = editPicker(vac.successor_title, vac.successor_id);
            succPicker.input.placeholder = "Known successor (optional)";
            var tdSucc = document.createElement("td");
            tdSucc.appendChild(succPicker.wrap); tr.appendChild(tdSucc);

            var tdNote = document.createElement("td");
            var noteInput = document.createElement("textarea"); noteInput.className = "bo-input bo-input--wide bo-input--full"; noteInput.rows = 2; noteInput.value = vac.note || "";
            tdNote.appendChild(noteInput); tr.appendChild(tdNote);

            // Per-row teardown (idempotent): drop this row's outside-click listeners and
            // release the shared "currently-open edit" slot if it still points here.
            var endEdit = function () {
                chPicker.teardown();
                succPicker.teardown();
                if (_closeOpenEdit === revertToDisplay) _closeOpenEdit = null;
            };
            // Revert this row to display mode; called when another row's edit opens.
            var revertToDisplay = function () {
                endEdit();
                $tbody.replaceChild(renderRow(vac, false), tr);
            };
            _closeOpenEdit = revertToDisplay;

            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                var body = { closure_date: dateInput.value, note: noteInput.value.trim() };
                if (chPicker.hidden.value) body.channel_id = parseInt(chPicker.hidden.value, 10);
                // Successor: cleared text → null; a fresh pick → its id; text left
                // untouched without a pick → leave the stored successor alone.
                if (!succPicker.input.value.trim()) body.successor_id = null;
                else if (succPicker.hidden.value) body.successor_id = parseInt(succPicker.hidden.value, 10);
                apiFetch(API + vac.id + "/", { method: "PATCH", body: body })
                    .then(function (updated) {
                        endEdit();
                        Object.assign(vac, updated);
                        $tbody.replaceChild(renderRow(vac, false), tr);
                        showToast("Saved.");
                    })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () {
                endEdit();
                $tbody.replaceChild(renderRow(vac, false), tr);
            });
            tdA.appendChild(saveBtn); tdA.appendChild(cancelBtn); tr.appendChild(tdA);
        } else {
            var tdChd = document.createElement("td"); tdChd.textContent = vac.channel_title || ""; tr.appendChild(tdChd);
            var tdDd = document.createElement("td"); tdDd.textContent = vac.closure_date || ""; tr.appendChild(tdDd);
            var tdSd = document.createElement("td"); tdSd.textContent = vac.successor_title || "—"; tr.appendChild(tdSd);
            var tdNd = document.createElement("td"); tdNd.className = "text-muted"; tdNd.style.fontSize = ".875rem"; tdNd.textContent = vac.note || ""; tr.appendChild(tdNd);

            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(vac, true), tr); });
            var delBtn = makeDeleteBtn(vac.channel_title);
            delBtn.addEventListener("click", function () {
                confirmDelete(vac.channel_title).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API + vac.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); _total--; $count.textContent = _total + " vacanc" + (_total !== 1 ? "ies" : "y"); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn); tdAd.appendChild(delBtn); tr.appendChild(tdAd);
        }
        return tr;
    }

    // ---- load ----
    function load() {
        apiFetch(API + "?limit=200")
            .then(function (data) {
                _total = data.count;
                $count.textContent = _total + " vacanc" + (_total !== 1 ? "ies" : "y");
                $tbody.innerHTML = "";
                if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No vacancies yet.</td></tr>'; return; }
                data.results.forEach(function (v) { $tbody.appendChild(renderRow(v, false)); });
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    // ---- add form ----
    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () {
        $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset();
        $chId.value = ""; $chSearch.value = ""; $succId.value = ""; $succSearch.value = "";
    });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!$chId.value) { showToast("Select a channel from the dropdown.", "error"); return; }
        if (!$closureDate.value) { showToast("Closure date is required.", "error"); return; }
        var body = { channel_id: parseInt($chId.value, 10), closure_date: $closureDate.value, note: $note.value.trim() };
        if ($succId.value) body.successor_id = parseInt($succId.value, 10);
        apiFetch(API, { method: "POST", body: body })
            .then(function (vac) {
                $tbody.insertBefore(renderRow(vac, false), $tbody.firstChild);
                _total++;
                $count.textContent = _total + " vacanc" + (_total !== 1 ? "ies" : "y");
                $addForm.reset(); $chId.value = ""; $chSearch.value = ""; $succId.value = ""; $succSearch.value = "";
                $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("Vacancy added.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    load();
})();
