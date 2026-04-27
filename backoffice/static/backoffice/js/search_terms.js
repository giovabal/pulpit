(function () {
    "use strict";
    var API = "/manage/api/search-terms/";

    var $tbody  = document.getElementById("st-tbody");
    var $form   = document.getElementById("st-add-form");
    var $input  = document.getElementById("st-input");

    function renderRow(term) {
        var tr = document.createElement("tr");
        tr.dataset.id = term.id;

        var tdW = document.createElement("td");
        tdW.style.fontFamily = "var(--font-mono)"; tdW.textContent = term.word; tr.appendChild(tdW);

        var tdD = document.createElement("td"); tdD.className = "text-muted"; tdD.style.fontSize = ".875rem";
        tdD.textContent = term.last_check ? fmtDate(term.last_check) : "—"; tr.appendChild(tdD);

        var tdA = document.createElement("td");
        var delBtn = makeDeleteBtn(term.word);
        delBtn.addEventListener("click", function () {
            confirmDelete(term.word).then(function (ok) {
                if (!ok) return;
                apiFetch(API + term.id + "/", { method: "DELETE" })
                    .then(function () { tr.remove(); showToast("Deleted."); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
        });
        tdA.appendChild(delBtn); tr.appendChild(tdA);
        return tr;
    }

    apiFetch(API + "?limit=500").then(function (data) {
        $tbody.innerHTML = "";
        if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="3" class="bo-empty">No search terms yet.</td></tr>'; return; }
        data.results.forEach(function (t) { $tbody.appendChild(renderRow(t)); });
    }).catch(function (e) { showToast("Error: " + e.message, "error"); });

    $form.addEventListener("submit", function (e) {
        e.preventDefault();
        var word = $input.value.trim();
        if (!word) return;
        apiFetch(API, { method: "POST", body: { word: word } })
            .then(function (term) {
                /* Remove empty-state row if present */
                var empty = $tbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $tbody.insertBefore(renderRow(term), $tbody.firstChild);
                $input.value = "";
                showToast("Term added.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });
})();
