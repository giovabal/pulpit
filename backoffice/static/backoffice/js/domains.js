/* Manage → Domains: the categories linked sites are filed under, and the sites themselves.
   Categories: full CRUD (/manage/api/domain-categories/). Sites: PATCH of category and note
   (/manage/api/domains/<id>/), each change saved at once; "Rebuild index" re-counts them. */
(function() {
    "use strict";
    var CAT_API = "/manage/api/domain-categories/";
    var API = "/manage/api/domains/";
    var ROLES = [
        ["", "No role"],
        ["monetisation", "Monetisation"],
        ["mainstream", "Mainstream platform"],
        ["alternative", "Alternative platform"],
    ];
    var _categories = [];
    var _offset = 0;
    var _total = 0;
    var _searchTimer = null;

    var $catBody = document.getElementById("dc-tbody");
    var $catForm = document.getElementById("dc-add-form");
    var $tbody = document.getElementById("dm-tbody");
    var $count = document.getElementById("dm-count");
    var $search = document.getElementById("dm-search");
    var $category = document.getElementById("dm-category");
    var $seen = document.getElementById("dm-seen");
    var $reindex = document.getElementById("dm-reindex");
    var $paginTop = document.getElementById("dm-pagination-top");
    var $paginBottom = document.getElementById("dm-pagination-bottom");

    function cell(tr, content, className) {
        var td = document.createElement("td");
        if (className) td.className = className;
        if (content instanceof Node) td.appendChild(content);
        else if (content !== undefined) td.textContent = content;
        tr.appendChild(td);
        return td;
    }

    function patch(url, obj, changes, done) {
        apiFetch(url, { method: "PATCH", body: changes })
            .then(function(updated) {
                Object.assign(obj, updated);
                showToast("Saved.");
                if (done) done(true);
            })
            .catch(function(e) {
                showToast("Error: " + e.message, "error");
                if (done) done(false);
            });
    }

    function roleSelect(value, label) {
        var sel = document.createElement("select");
        sel.className = "bo-select";
        sel.setAttribute("aria-label", label);
        ROLES.forEach(function(r) {
            var o = document.createElement("option");
            o.value = r[0];
            o.textContent = r[1];
            sel.appendChild(o);
        });
        sel.value = value || "";
        return sel;
    }

    // ── Categories ───────────────────────────────────────────────────────────

    function renderCategoryRow(cat) {
        var tr = document.createElement("tr");
        var url = CAT_API + cat.id + "/";
        var color = document.createElement("input");
        color.type = "color";
        color.className = "bo-input bo-input--color";
        color.value = cat.color;
        color.setAttribute("aria-label", "Colour of " + cat.name);
        color.addEventListener("change", function() { patch(url, cat, { color: color.value }); });
        cell(tr, color);
        var name = document.createElement("input");
        name.className = "bo-input";
        name.value = cat.name;
        name.maxLength = 64;
        name.setAttribute("aria-label", "Name of category " + cat.name);
        name.addEventListener("change", function() {
            var value = name.value.trim();
            if (!value) {
                name.value = cat.name;
                return;
            }
            patch(url, cat, { name: value }, function(ok) {
                if (!ok) name.value = cat.name;
                else loadCategories();
            });
        });
        cell(tr, name);
        var role = roleSelect(cat.role, "Role of " + cat.name);
        role.addEventListener("change", function() { patch(url, cat, { role: role.value }); });
        cell(tr, role);
        var desc = document.createElement("input");
        desc.className = "bo-input bo-input--wide";
        desc.value = cat.description || "";
        desc.placeholder = "Description (optional)";
        desc.setAttribute("aria-label", "Description of " + cat.name);
        desc.addEventListener("change", function() { patch(url, cat, { description: desc.value.trim() }); });
        cell(tr, desc);
        cell(tr, fmtInt(cat.domain_count), "bo-td--num");
        var del = makeDeleteBtn(cat.name);
        del.addEventListener("click", function() {
            confirmDelete(cat.name).then(function(ok) {
                if (!ok) return;
                apiFetch(url, { method: "DELETE" })
                    .then(function() {
                        showToast("Deleted.");
                        loadCategories();
                        load();
                    })
                    .catch(function(e) { showToast("Error: " + e.message, "error"); });
            });
        });
        cell(tr, del);
        return tr;
    }

    function fillCategoryFilter() {
        var previous = $category.value;
        $category.innerHTML = "";
        [
            ["", "All categories"],
            ["none", "Uncategorised"]
        ].concat(_categories.map(function(c) {
            return [String(c.id), c.name];
        })).forEach(function(pair) {
            var o = document.createElement("option");
            o.value = pair[0];
            o.textContent = pair[1];
            $category.appendChild(o);
        });
        var values = Array.prototype.map.call($category.options, function(o) { return o.value; });
        $category.value = values.indexOf(previous) >= 0 ? previous : "";
    }

    function loadCategories() {
        return apiFetch(CAT_API)
            .then(function(data) {
                _categories = data;
                $catBody.innerHTML = "";
                if (!data.length) $catBody.innerHTML = '<tr><td colspan="6" class="bo-empty">No category yet.</td></tr>';
                data.forEach(function(cat) { $catBody.appendChild(renderCategoryRow(cat)); });
                fillCategoryFilter();
            })
            .catch(function(e) { showToast("Error: " + e.message, "error"); });
    }

    document.getElementById("dc-add-btn").addEventListener("click", function() {
        $catForm.classList.remove("d-none");
        $catForm.elements.name.focus();
    });
    document.getElementById("dc-add-cancel").addEventListener("click", function() {
        $catForm.reset();
        $catForm.classList.add("d-none");
    });
    $catForm.addEventListener("submit", function(ev) {
        ev.preventDefault();
        var body = {
            name: $catForm.elements.name.value.trim(),
            color: $catForm.elements.color.value,
            role: $catForm.elements.role.value,
            description: $catForm.elements.description.value.trim(),
        };
        apiFetch(CAT_API, { method: "POST", body: body })
            .then(function() {
                showToast("Category added.");
                $catForm.reset();
                $catForm.classList.add("d-none");
                loadCategories().then(load);
            })
            .catch(function(e) { showToast("Error: " + e.message, "error"); });
    });

    // ── Sites ────────────────────────────────────────────────────────────────

    function categorySelect(domain) {
        var sel = document.createElement("select");
        sel.className = "bo-select";
        sel.setAttribute("aria-label", "Category of " + domain.name);
        var none = document.createElement("option");
        none.value = "";
        none.textContent = "— Uncategorised —";
        sel.appendChild(none);
        _categories.forEach(function(c) {
            var o = document.createElement("option");
            o.value = String(c.id);
            o.textContent = c.name;
            sel.appendChild(o);
        });
        sel.value = domain.category === null ? "" : String(domain.category);
        sel.addEventListener("change", function() {
            sel.disabled = true;
            patch(API + domain.id + "/", domain, { category: sel.value ? parseInt(sel.value, 10) : null }, function(ok) {
                sel.disabled = false;
                if (!ok) sel.value = domain.category === null ? "" : String(domain.category);
            });
        });
        return sel;
    }

    function noteInput(domain) {
        var input = document.createElement("input");
        input.className = "bo-input bo-input--wide";
        input.value = domain.note || "";
        input.placeholder = "Note (optional)";
        input.setAttribute("aria-label", "Note on " + domain.name);
        input.addEventListener("change", function() {
            patch(API + domain.id + "/", domain, { note: input.value.trim() });
        });
        return input;
    }

    function siteLink(domain) {
        var a = document.createElement("a");
        a.href = "https://" + domain.name + "/";
        a.target = "_blank";
        a.rel = "noopener noreferrer nofollow";
        a.textContent = domain.name;
        a.title = "Open " + domain.name + " in a new tab";
        return a;
    }

    function renderRow(domain) {
        var tr = document.createElement("tr");
        cell(tr, siteLink(domain));
        cell(tr, categorySelect(domain));
        cell(tr, fmtInt(domain.posts), "bo-td--num");
        cell(tr, fmtInt(domain.channels), "bo-td--num");
        cell(tr, fmtDate(domain.first_seen));
        cell(tr, fmtDate(domain.last_seen));
        cell(tr, noteInput(domain));
        return tr;
    }

    function load() {
        var params = new URLSearchParams({ limit: BACKOFFICE_PAGE_SIZE, offset: _offset });
        if ($search.value.trim()) params.set("q", $search.value.trim());
        if ($category.value) params.set("category", $category.value);
        if ($seen.checked) params.set("seen", "1");
        apiFetch(API + "?" + params.toString())
            .then(function(data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) {
                    $tbody.innerHTML = '<tr><td colspan="7" class="bo-empty">No site matches. Sites appear once the domain index is built.</td></tr>';
                }
                data.results.forEach(function(domain) { $tbody.appendChild(renderRow(domain)); });
                renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, goTo);
                renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, goTo);
                $count.textContent = fmtInt(_total) + " site" + (_total !== 1 ? "s" : "");
            })
            .catch(function(e) { showToast("Error: " + e.message, "error"); });
    }

    function goTo(offset) {
        _offset = offset;
        load();
    }

    $search.addEventListener("input", function() {
        clearTimeout(_searchTimer);
        _searchTimer = setTimeout(function() { goTo(0); }, 250);
    });
    $category.addEventListener("change", function() { goTo(0); });
    $seen.addEventListener("change", function() { goTo(0); });
    $reindex.addEventListener("click", function() {
        $reindex.disabled = true;
        var label = $reindex.innerHTML;
        $reindex.innerHTML = '<i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>Indexing…';
        apiFetch(API + "reindex/", { method: "POST", body: {} })
            .then(function(data) {
                showToast("Indexed " + fmtInt(data.domains) + " sites over " + fmtInt(data.messages) + " messages (" + fmtInt(data.new) + " new).");
                loadCategories().then(function() { goTo(0); });
            })
            .catch(function(e) { showToast("Indexing failed: " + e.message, "error"); })
            .finally(function() {
                $reindex.disabled = false;
                $reindex.innerHTML = label;
            });
    });

    loadCategories().then(load);
})();
