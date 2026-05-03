(function () {
    "use strict";
    var API      = "/manage/api/vacancies/";
    var CH_API   = "/manage/api/channels/?status=interesting&";
    var _total   = 0;

    var $tbody    = document.getElementById("vac-tbody");
    var $count    = document.getElementById("vac-count");
    var $addBtn   = document.getElementById("vac-add-btn");
    var $addForm  = document.getElementById("vac-add-form");
    var $addCancel = document.getElementById("vac-add-cancel");
    var $chSearch = document.getElementById("vac-ch-search");
    var $chId     = document.getElementById("vac-ch-id");
    var $chDrop   = document.getElementById("vac-ch-dropdown");
    var $closureDate = document.getElementById("vac-closure-date");
    var $note     = document.getElementById("vac-note");

    // ---- channel typeahead ----
    var _chTimer = null;
    $chSearch.addEventListener("input", function () {
        clearTimeout(_chTimer);
        var q = this.value.trim();
        $chId.value = "";
        if (!q) { $chDrop.style.display = "none"; return; }
        _chTimer = setTimeout(function () {
            apiFetch(CH_API + "search=" + encodeURIComponent(q) + "&limit=10")
                .then(function (data) {
                    var items = (data.results || []);
                    if (!items.length) { $chDrop.style.display = "none"; return; }
                    $chDrop.innerHTML = "";
                    items.forEach(function (ch) {
                        var d = document.createElement("div");
                        d.className = "bo-typeahead-item";
                        d.textContent = ch.title + (ch.username ? " (@" + ch.username + ")" : "");
                        d.addEventListener("mousedown", function (e) {
                            e.preventDefault();
                            $chSearch.value = ch.title;
                            $chId.value = ch.id;
                            $chDrop.style.display = "none";
                        });
                        $chDrop.appendChild(d);
                    });
                    $chDrop.style.display = "block";
                }).catch(function () {});
        }, 250);
    });
    document.addEventListener("click", function (e) {
        if (!$chDrop.contains(e.target) && e.target !== $chSearch) $chDrop.style.display = "none";
    });

    // ---- render row ----
    function renderRow(vac, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = vac.id;

        if (editing) {
            var tdCh = document.createElement("td");
            var chInput = document.createElement("input"); chInput.className = "bo-input"; chInput.style.minWidth = "27rem"; chInput.value = vac.channel_title || "";
            var chIdInput = document.createElement("input"); chIdInput.type = "hidden"; chIdInput.value = vac.channel_id || "";
            var drop = document.createElement("div"); drop.className = "bo-typeahead"; drop.style.display = "none";
            var wrap = document.createElement("div"); wrap.style.position = "relative";
            wrap.appendChild(chInput); wrap.appendChild(drop); wrap.appendChild(chIdInput);
            chInput.addEventListener("input", function () {
                chIdInput.value = "";
                var q = chInput.value.trim();
                if (!q) { drop.style.display = "none"; return; }
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
                                chInput.value = ch.title;
                                chIdInput.value = ch.id;
                                drop.style.display = "none";
                            });
                            drop.appendChild(d);
                        });
                        drop.style.display = "block";
                    }).catch(function () {});
            });
            document.addEventListener("click", function (e) {
                if (!drop.contains(e.target) && e.target !== chInput) drop.style.display = "none";
            });
            tdCh.appendChild(wrap); tr.appendChild(tdCh);

            var tdDate = document.createElement("td");
            var dateInput = document.createElement("input"); dateInput.className = "bo-input"; dateInput.type = "date"; dateInput.value = vac.closure_date || "";
            tdDate.appendChild(dateInput); tr.appendChild(tdDate);

            var tdNote = document.createElement("td");
            var noteInput = document.createElement("textarea"); noteInput.className = "bo-input bo-input--wide bo-input--full"; noteInput.rows = 2; noteInput.value = vac.note || "";
            tdNote.appendChild(noteInput); tr.appendChild(tdNote);

            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                var body = { closure_date: dateInput.value, note: noteInput.value.trim() };
                if (chIdInput.value) body.channel_id = parseInt(chIdInput.value, 10);
                apiFetch(API + vac.id + "/", { method: "PATCH", body: body })
                    .then(function (updated) { Object.assign(vac, updated); $tbody.replaceChild(renderRow(vac, false), tr); showToast("Saved."); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(vac, false), tr); });
            tdA.appendChild(saveBtn); tdA.appendChild(cancelBtn); tr.appendChild(tdA);
        } else {
            var tdChd = document.createElement("td"); tdChd.textContent = vac.channel_title || ""; tr.appendChild(tdChd);
            var tdDd = document.createElement("td"); tdDd.textContent = vac.closure_date || ""; tr.appendChild(tdDd);
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
                if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="4" class="bo-empty">No vacancies yet.</td></tr>'; return; }
                data.results.forEach(function (v) { $tbody.appendChild(renderRow(v, false)); });
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    // ---- add form ----
    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); $chId.value = ""; $chSearch.value = ""; });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!$chId.value) { showToast("Select a channel from the dropdown.", "error"); return; }
        if (!$closureDate.value) { showToast("Closure date is required.", "error"); return; }
        apiFetch(API, { method: "POST", body: { channel_id: parseInt($chId.value, 10), closure_date: $closureDate.value, note: $note.value.trim() } })
            .then(function (vac) {
                $tbody.insertBefore(renderRow(vac, false), $tbody.firstChild);
                _total++;
                $count.textContent = _total + " vacanc" + (_total !== 1 ? "ies" : "y");
                $addForm.reset(); $chId.value = ""; $chSearch.value = "";
                $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("Vacancy added.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    load();
})();
