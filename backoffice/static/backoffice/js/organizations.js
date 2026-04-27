(function () {
    "use strict";
    var API = "/manage/api/organizations/";
    var _orgs = [];

    var $tbody    = document.getElementById("org-tbody");
    var $addBtn   = document.getElementById("org-add-btn");
    var $addForm  = document.getElementById("org-add-form");
    var $addCancel= document.getElementById("org-add-cancel");

    function renderRow(org, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = org.id;

        if (editing) {
            /* inline edit */
            var tdColor = document.createElement("td");
            var colorInput = document.createElement("input");
            colorInput.type = "color"; colorInput.className = "bo-input bo-input--color";
            colorInput.value = org.color || "#4338ca";
            tdColor.appendChild(colorInput); tr.appendChild(tdColor);

            var tdName = document.createElement("td");
            var nameInput = document.createElement("input");
            nameInput.className = "bo-input bo-input--wide"; nameInput.value = org.name;
            tdName.appendChild(nameInput); tr.appendChild(tdName);

            var tdInt = document.createElement("td"); tdInt.className = "bo-td--center";
            var intChk = document.createElement("input");
            intChk.type = "checkbox"; intChk.checked = org.is_interesting;
            tdInt.appendChild(intChk); tr.appendChild(tdInt);

            var tdCount = document.createElement("td"); tdCount.className = "bo-td--num";
            tdCount.textContent = fmtInt(org.channel_count); tr.appendChild(tdCount);

            var tdAct = document.createElement("td");
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                apiFetch(API + org.id + "/", { method: "PATCH", body: { name: nameInput.value.trim(), color: colorInput.value, is_interesting: intChk.checked } })
                    .then(function (updated) {
                        Object.assign(org, updated);
                        var newTr = renderRow(org, false);
                        $tbody.replaceChild(newTr, tr);
                        showToast("Saved.");
                    }).catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () {
                var newTr = renderRow(org, false);
                $tbody.replaceChild(newTr, tr);
            });
            tdAct.appendChild(saveBtn); tdAct.appendChild(cancelBtn); tr.appendChild(tdAct);
        } else {
            /* display */
            var tdC = document.createElement("td");
            var dot = document.createElement("span"); dot.className = "bo-org-dot"; dot.style.background = org.color || "#ccc";
            tdC.appendChild(dot); tr.appendChild(tdC);

            var tdN = document.createElement("td"); tdN.textContent = org.name; tr.appendChild(tdN);

            var tdI = document.createElement("td"); tdI.className = "bo-td--center";
            var icon = document.createElement("i");
            icon.className = org.is_interesting ? "bi bi-check-circle-fill text-success" : "bi bi-x-circle text-secondary";
            tdI.appendChild(icon); tr.appendChild(tdI);

            var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num";
            tdCnt.textContent = fmtInt(org.channel_count); tr.appendChild(tdCnt);

            var tdA = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function () {
                var newTr = renderRow(org, true);
                $tbody.replaceChild(newTr, tr);
            });
            var delBtn = makeDeleteBtn(org.name);
            delBtn.addEventListener("click", function () {
                confirmDelete(org.name).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API + org.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdA.appendChild(editBtn); tdA.appendChild(delBtn); tr.appendChild(tdA);
        }
        return tr;
    }

    function loadOrgs() {
        apiFetch(API + "?limit=500")
            .then(function (data) {
                _orgs = data.results;
                $tbody.innerHTML = "";
                if (!_orgs.length) { $tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No organizations yet.</td></tr>'; return; }
                _orgs.forEach(function (org) { $tbody.appendChild(renderRow(org, false)); });
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API, { method: "POST", body: { name: fd.get("name").trim(), color: fd.get("color"), is_interesting: fd.get("is_interesting") === "on" } })
            .then(function (org) {
                org.channel_count = 0;
                $tbody.appendChild(renderRow(org, false));
                $addForm.reset(); $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("Organization created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadOrgs();
})();
