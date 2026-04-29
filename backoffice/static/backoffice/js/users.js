(function () {
    "use strict";
    var API = "/manage/api/users/";
    var _offset = 0;
    var _total  = 0;

    var $tbody       = document.getElementById("usr-tbody");
    var $count       = document.getElementById("usr-count");
    var $paginTop    = document.getElementById("usr-pagination-top");
    var $paginBottom = document.getElementById("usr-pagination-bottom");
    var $addBtn      = document.getElementById("usr-add-btn");
    var $addForm     = document.getElementById("usr-add-form");
    var $addCancel   = document.getElementById("usr-add-cancel");

    function _goToPage(offset) { _offset = offset; loadUsers(); }

    function _renderPagination() {
        renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        $count.textContent = _total + " user" + (_total !== 1 ? "s" : "");
    }

    function boolIcon(val) {
        var i = document.createElement("i");
        i.className = val ? "bi bi-check-circle-fill text-success" : "bi bi-x-circle text-secondary";
        return i;
    }

    function renderRow(user, editing) {
        var tr = document.createElement("tr");
        tr.dataset.id = user.id;

        if (editing) {
            var tdE = document.createElement("td");
            var eIn = document.createElement("input"); eIn.type = "email"; eIn.className = "bo-input bo-input--wide"; eIn.value = user.email || "";
            tdE.appendChild(eIn); tr.appendChild(tdE);

            var tdSt = document.createElement("td"); tdSt.className = "bo-td--center";
            var stChk = document.createElement("input"); stChk.type = "checkbox"; stChk.checked = user.is_staff;
            tdSt.appendChild(stChk); tr.appendChild(tdSt);

            var tdAc = document.createElement("td"); tdAc.className = "bo-td--center";
            var acChk = document.createElement("input"); acChk.type = "checkbox"; acChk.checked = user.is_active;
            tdAc.appendChild(acChk); tr.appendChild(tdAc);

            var tdJ = document.createElement("td"); tdJ.textContent = fmtDate(user.date_joined); tr.appendChild(tdJ);

            var tdPw = document.createElement("td");
            var pwIn = document.createElement("input"); pwIn.type = "password"; pwIn.className = "bo-input"; pwIn.placeholder = "New password (optional)"; pwIn.autocomplete = "new-password";
            var saveBtn = document.createElement("button"); saveBtn.className = "bo-btn bo-btn--sm"; saveBtn.textContent = "Save";
            var cancelBtn = document.createElement("button"); cancelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancelBtn.textContent = "Cancel";
            saveBtn.addEventListener("click", function () {
                var body = {
                    email: eIn.value.trim(),
                    is_staff: stChk.checked,
                    is_active: acChk.checked,
                };
                if (pwIn.value) body.password = pwIn.value;
                apiFetch(API + user.id + "/", { method: "PATCH", body: body })
                    .then(function (updated) {
                        Object.assign(user, updated);
                        $tbody.replaceChild(renderRow(user, false), tr);
                        showToast("Saved.");
                    }).catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
            cancelBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(user, false), tr); });
            tdPw.appendChild(pwIn); tdPw.appendChild(saveBtn); tdPw.appendChild(cancelBtn); tr.appendChild(tdPw);
        } else {
            var tdEd = document.createElement("td"); tdEd.textContent = user.email || "—"; tr.appendChild(tdEd);
            var tdStd = document.createElement("td"); tdStd.className = "bo-td--center"; tdStd.appendChild(boolIcon(user.is_staff)); tr.appendChild(tdStd);
            var tdAcd = document.createElement("td"); tdAcd.className = "bo-td--center"; tdAcd.appendChild(boolIcon(user.is_active)); tr.appendChild(tdAcd);
            var tdJd = document.createElement("td"); tdJd.textContent = fmtDate(user.date_joined); tr.appendChild(tdJd);

            var tdAd = document.createElement("td");
            var editBtn = makeEditBtn();
            editBtn.addEventListener("click", function () { $tbody.replaceChild(renderRow(user, true), tr); });
            var delBtn = makeDeleteBtn(user.username);
            delBtn.addEventListener("click", function () {
                confirmDelete(user.username).then(function (ok) {
                    if (!ok) return;
                    apiFetch(API + user.id + "/", { method: "DELETE" })
                        .then(function () { tr.remove(); _total--; _renderPagination(); showToast("Deleted."); })
                        .catch(function (e) { showToast("Error: " + e.message, "error"); });
                });
            });
            tdAd.appendChild(editBtn); tdAd.appendChild(delBtn); tr.appendChild(tdAd);
        }
        return tr;
    }

    function loadUsers() {
        apiFetch(API + "?limit=" + BACKOFFICE_PAGE_SIZE + "&offset=" + _offset)
            .then(function (data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No users found.</td></tr>'; }
                else { data.results.forEach(function (u) { $tbody.appendChild(renderRow(u, false)); }); }
                _renderPagination();
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        var body = {
            email: fd.get("email").trim(),
            password: fd.get("password"),
            is_staff: fd.get("is_staff") === "on",
            is_active: fd.get("is_active") === "on",
        };
        apiFetch(API, { method: "POST", body: body })
            .then(function (user) {
                _total++;
                _renderPagination();
                var empty = $tbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $tbody.appendChild(renderRow(user, false));
                $addForm.reset(); $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
                showToast("User created.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadUsers();
})();
