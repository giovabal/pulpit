(function () {
    "use strict";
    var API = "/manage/api/groups/";

    var $tbody    = document.getElementById("grp-tbody");
    var $addBtn   = document.getElementById("grp-add-btn");
    var $addForm  = document.getElementById("grp-add-form");
    var $addCancel= document.getElementById("grp-add-cancel");

    function renderRow(grp, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = grp.id;

        if (editing) {
            var tdN = document.createElement("td");
            var nameInput = document.createElement("input"); nameInput.className = "bo-input"; nameInput.value = grp.name;
            tdN.appendChild(nameInput); tr.appendChild(tdN);

            var tdD = document.createElement("td");
            var descInput = document.createElement("input"); descInput.className = "bo-input bo-input--wide"; descInput.value = grp.description || "";
            tdD.appendChild(descInput); tr.appendChild(tdD);

            var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num"; tdCnt.textContent = fmtInt(grp.channel_count); tr.appendChild(tdCnt);

            var tdA = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                apiFetch(API + grp.id + "/", { method: "PATCH", body: { name: nameInput.value.trim(), description: descInput.value.trim() } })
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
            var tdCd = document.createElement("td"); tdCd.className = "bo-td--num"; tdCd.textContent = fmtInt(grp.channel_count); tr.appendChild(tdCd);

            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(grp, true), tr); });
            var delBtn = makeDeleteBtn(grp.name);
            delBtn.addEventListener("click", function () {
                confirmDelete(grp.name).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API + grp.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn); tdAd.appendChild(delBtn); tr.appendChild(tdAd);
        }
        return tr;
    }

    apiFetch(API + "?limit=500").then(function (data) {
        $tbody.innerHTML = "";
        if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="4" class="bo-empty">No groups yet.</td></tr>'; return; }
        data.results.forEach(function (g) { $tbody.appendChild(renderRow(g, false)); });
    }).catch(function (e) { showToast("Error: " + e.message, "error"); });

    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API, { method: "POST", body: { name: fd.get("name").trim(), description: fd.get("description").trim() } })
            .then(function (grp) {
                grp.channel_count = 0;
                $tbody.appendChild(renderRow(grp, false));
                $addForm.reset(); $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("Group created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });
})();
