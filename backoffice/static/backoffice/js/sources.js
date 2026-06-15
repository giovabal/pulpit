(function () {
    "use strict";
    var API = "/manage/api/sources/";
    var _offset = 0;
    var _total  = 0;

    var $tbody       = document.getElementById("src-tbody");
    var $count       = document.getElementById("src-count");
    var $paginTop    = document.getElementById("src-pagination-top");
    var $paginBottom = document.getElementById("src-pagination-bottom");
    var $addBtn      = document.getElementById("src-add-btn");
    var $addForm     = document.getElementById("src-add-form");
    var $addCancel   = document.getElementById("src-add-cancel");

    function _goToPage(offset) { _offset = offset; loadSources(); }

    function _renderPagination() {
        renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        $count.textContent = _total + " source" + (_total !== 1 ? "s" : "");
    }

    function renderRow(src, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = src.id;

        if (editing) {
            var tdN = document.createElement("td");
            var nameInput = document.createElement("input"); nameInput.className = "bo-input"; nameInput.value = src.name;
            tdN.appendChild(nameInput); tr.appendChild(tdN);

            var tdD = document.createElement("td");
            var descInput = document.createElement("textarea"); descInput.className = "bo-input bo-input--wide bo-input--full"; descInput.rows = 4; descInput.value = src.description || "";
            tdD.appendChild(descInput); tr.appendChild(tdD);

            var tdNo = document.createElement("td");
            var noteInput = document.createElement("textarea"); noteInput.className = "bo-input bo-input--wide bo-input--full"; noteInput.rows = 4; noteInput.value = src.note || "";
            tdNo.appendChild(noteInput); tr.appendChild(tdNo);

            var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num"; tdCnt.textContent = fmtInt(src.channel_count); tr.appendChild(tdCnt);

            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                apiFetch(API + src.id + "/", { method: "PATCH", body: { name: nameInput.value.trim(), description: descInput.value.trim(), note: noteInput.value.trim() } })
                    .then(function (updated) {
                        Object.assign(src, updated);
                        $tbody.replaceChild(renderRow(src, false), tr);
                        showToast("Saved.");
                    }).catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(src, false), tr); });
            tdA.appendChild(saveBtn); tdA.appendChild(cancelBtn); tr.appendChild(tdA);
        } else {
            var tdNd = document.createElement("td"); tdNd.textContent = src.name; tr.appendChild(tdNd);
            var tdDd = document.createElement("td"); tdDd.className = "text-muted"; tdDd.style.fontSize = ".875rem"; tdDd.textContent = src.description || ""; tr.appendChild(tdDd);
            var tdNod = document.createElement("td"); tdNod.className = "text-muted"; tdNod.style.fontSize = ".875rem"; tdNod.textContent = src.note || ""; tr.appendChild(tdNod);
            var tdCd = document.createElement("td"); tdCd.className = "bo-td--num"; tdCd.textContent = fmtInt(src.channel_count); tr.appendChild(tdCd);

            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(src, true), tr); });
            var delBtn = makeDeleteBtn(src.name);
            delBtn.addEventListener("click", function () {
                confirmDelete(src.name).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API + src.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); _total--; _renderPagination(); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn); tdAd.appendChild(delBtn); tr.appendChild(tdAd);
        }
        return tr;
    }

    function loadSources() {
        apiFetch(API + "?limit=" + BACKOFFICE_PAGE_SIZE + "&offset=" + _offset)
            .then(function (data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No sources yet.</td></tr>'; }
                else { data.results.forEach(function (s) { $tbody.appendChild(renderRow(s, false)); }); }
                _renderPagination();
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API, { method: "POST", body: { name: fd.get("name").trim(), description: fd.get("description").trim(), note: fd.get("note").trim() } })
            .then(function (src) {
                src.channel_count = 0;
                var empty = $tbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $tbody.appendChild(renderRow(src, false));
                _total++;
                _renderPagination();
                $addForm.reset(); $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("Source created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadSources();
})();
