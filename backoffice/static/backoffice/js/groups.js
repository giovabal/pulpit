(function () {
    "use strict";
    var API = "/manage/api/groups/";
    var _offset = 0;
    var _total  = 0;

    var $tbody       = document.getElementById("grp-tbody");
    var $count       = document.getElementById("grp-count");
    var $paginTop    = document.getElementById("grp-pagination-top");
    var $paginBottom = document.getElementById("grp-pagination-bottom");
    var $addBtn      = document.getElementById("grp-add-btn");
    var $addForm     = document.getElementById("grp-add-form");
    var $addCancel   = document.getElementById("grp-add-cancel");

    function _goToPage(offset) { _offset = offset; loadGroups(); }

    function _renderPagination() {
        renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        $count.textContent = _total + " group" + (_total !== 1 ? "s" : "");
    }

    function renderRow(grp, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = grp.id;

        if (editing) {
            var tdN = document.createElement("td");
            var nameInput = document.createElement("input"); nameInput.className = "bo-input"; nameInput.value = grp.name;
            tdN.appendChild(nameInput); tr.appendChild(tdN);

            var tdD = document.createElement("td");
            var descInput = document.createElement("textarea"); descInput.className = "bo-input bo-input--wide bo-input--full"; descInput.rows = 4; descInput.value = grp.description || "";
            tdD.appendChild(descInput); tr.appendChild(tdD);

            var tdNo = document.createElement("td");
            var noteInput = document.createElement("textarea"); noteInput.className = "bo-input bo-input--wide bo-input--full"; noteInput.rows = 4; noteInput.value = grp.note || "";
            tdNo.appendChild(noteInput); tr.appendChild(tdNo);

            var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num"; tdCnt.textContent = fmtInt(grp.channel_count); tr.appendChild(tdCnt);

            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                apiFetch(API + grp.id + "/", { method: "PATCH", body: { name: nameInput.value.trim(), description: descInput.value.trim(), note: noteInput.value.trim() } })
                    .then(function (updated) {
                        Object.assign(grp, updated);
                        $tbody.replaceChild(renderRow(grp, false), tr);
                        showToast("Saved.");
                    }).catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(grp, false), tr); });
            tdA.appendChild(saveBtn); tdA.appendChild(cancelBtn); tr.appendChild(tdA);
        } else {
            var tdNd = document.createElement("td"); tdNd.textContent = grp.name; tr.appendChild(tdNd);
            var tdDd = document.createElement("td"); tdDd.className = "text-muted"; tdDd.style.fontSize = ".875rem"; tdDd.textContent = grp.description || ""; tr.appendChild(tdDd);
            var tdNod = document.createElement("td"); tdNod.className = "text-muted"; tdNod.style.fontSize = ".875rem"; tdNod.textContent = grp.note || ""; tr.appendChild(tdNod);
            var tdCd = document.createElement("td"); tdCd.className = "bo-td--num"; tdCd.textContent = fmtInt(grp.channel_count); tr.appendChild(tdCd);

            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(grp, true), tr); });
            var delBtn = makeDeleteBtn(grp.name);
            delBtn.addEventListener("click", function () {
                confirmDelete(grp.name).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API + grp.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); _total--; _renderPagination(); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn); tdAd.appendChild(delBtn); tr.appendChild(tdAd);
        }
        return tr;
    }

    function loadGroups() {
        apiFetch(API + "?limit=" + BACKOFFICE_PAGE_SIZE + "&offset=" + _offset)
            .then(function (data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No groups yet.</td></tr>'; }
                else { data.results.forEach(function (g) { $tbody.appendChild(renderRow(g, false)); }); }
                _renderPagination();
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API, { method: "POST", body: { name: fd.get("name").trim(), description: fd.get("description").trim(), note: fd.get("note").trim() } })
            .then(function (grp) {
                grp.channel_count = 0;
                $tbody.appendChild(renderRow(grp, false));
                _total++;
                _renderPagination();
                $addForm.reset(); $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("Group created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadGroups();
})();
