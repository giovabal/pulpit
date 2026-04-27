(function () {
    "use strict";
    var API = "/manage/api/search-terms/";
    var _offset = 0;
    var _total  = 0;

    var $tbody       = document.getElementById("st-tbody");
    var $count       = document.getElementById("st-count");
    var $paginTop    = document.getElementById("st-pagination-top");
    var $paginBottom = document.getElementById("st-pagination-bottom");
    var $form        = document.getElementById("st-add-form");
    var $input       = document.getElementById("st-input");

    function _goToPage(offset) { _offset = offset; loadTerms(); }

    function _renderPagination() {
        renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        $count.textContent = _total + " term" + (_total !== 1 ? "s" : "");
    }

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
                    .then(function () { tr.remove(); _total--; _renderPagination(); showToast("Deleted."); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
        });
        tdA.appendChild(delBtn); tr.appendChild(tdA);
        return tr;
    }

    function loadTerms() {
        apiFetch(API + "?limit=" + BACKOFFICE_PAGE_SIZE + "&offset=" + _offset)
            .then(function (data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="3" class="bo-empty">No search terms yet.</td></tr>'; }
                else { data.results.forEach(function (t) { $tbody.appendChild(renderRow(t)); }); }
                _renderPagination();
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    $form.addEventListener("submit", function (e) {
        e.preventDefault();
        var word = $input.value.trim();
        if (!word) return;
        apiFetch(API, { method: "POST", body: { word: word } })
            .then(function (term) {
                _total++;
                _renderPagination();
                var empty = $tbody.querySelector(".bo-empty");
                if (empty) empty.parentNode.remove();
                $tbody.insertBefore(renderRow(term), $tbody.firstChild);
                $input.value = "";
                showToast("Term added.");
            }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadTerms();
})();
