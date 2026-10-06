(function() {
    "use strict";
    var API = "/manage/api/message-tags/";
    var SEARCH_URL = window.MESSAGE_SEARCH_URL || "/search/";

    var _tags = [];

    var $tbody = document.getElementById("tag-tbody");
    var $addBtn = document.getElementById("tag-add-btn");
    var $addForm = document.getElementById("tag-add-form");
    var $cancel = document.getElementById("tag-add-cancel");

    function emptyRow() {
        $tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No tags yet — add one here or from a post card.</td></tr>';
    }

    function cell(tr, content, className) {
        var td = document.createElement("td");
        if (className) td.className = className;
        if (content instanceof Node) td.appendChild(content);
        else if (content !== undefined) td.textContent = content;
        tr.appendChild(td);
        return td;
    }

    function smallBtn(label, ghost) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "bo-btn bo-btn--sm" + (ghost ? " bo-btn--ghost" : "");
        b.textContent = label;
        return b;
    }

    function countLink(tag) {
        if (!tag.message_count) return document.createTextNode("0");
        var a = document.createElement("a");
        a.href = SEARCH_URL + "?tag=" + tag.id;
        a.textContent = fmtInt(tag.message_count);
        a.title = "Show the messages tagged “" + tag.name + "”";
        return a;
    }

    function renderView(tr, tag) {
        var dot = document.createElement("span");
        dot.className = "bo-org-dot";
        dot.style.background = tag.color;
        cell(tr, dot);
        cell(tr, tag.name);
        cell(tr, tag.description || "");
        cell(tr, countLink(tag), "bo-td--num");
        var tdA = cell(tr);
        var editBtn = makeEditBtn();
        editBtn.addEventListener("click", function() { refreshRow(tr, tag, "edit"); });
        var mergeBtn = document.createElement("button");
        mergeBtn.className = "bo-btn bo-btn--icon";
        mergeBtn.title = "Merge “" + tag.name + "” into another tag";
        mergeBtn.setAttribute("aria-label", mergeBtn.title);
        mergeBtn.innerHTML = '<i class="bi bi-intersect" aria-hidden="true"></i>';
        mergeBtn.disabled = _tags.length < 2;
        mergeBtn.addEventListener("click", function() { refreshRow(tr, tag, "merge"); });
        var delBtn = makeDeleteBtn(tag.name);
        delBtn.addEventListener("click", function() {
            var what = tag.message_count ?
                "Delete “" + tag.name + "”? It is removed from " + fmtInt(tag.message_count) + " message(s). This cannot be undone." :
                "Delete “" + tag.name + "”? This cannot be undone.";
            if (!confirm(what)) return;
            apiFetch(API + tag.id + "/", { method: "DELETE" })
                .then(function() {
                    _tags = _tags.filter(function(t) { return t.id !== tag.id; });
                    renderAll();
                    showToast("Deleted.");
                })
                .catch(function(e) { showToast("Error: " + e.message, "error"); });
        });
        tdA.appendChild(editBtn);
        tdA.appendChild(mergeBtn);
        tdA.appendChild(delBtn);
    }

    function renderEdit(tr, tag) {
        var cIn = document.createElement("input");
        cIn.type = "color";
        cIn.className = "bo-input bo-input--color";
        cIn.value = tag.color;
        cIn.setAttribute("aria-label", "Tag colour");
        cell(tr, cIn);
        var nIn = document.createElement("input");
        nIn.className = "bo-input";
        nIn.maxLength = 64;
        nIn.value = tag.name;
        nIn.setAttribute("aria-label", "Tag name");
        cell(tr, nIn);
        var dIn = document.createElement("input");
        dIn.className = "bo-input bo-input--wide";
        dIn.value = tag.description || "";
        dIn.setAttribute("aria-label", "Tag description");
        cell(tr, dIn);
        cell(tr, fmtInt(tag.message_count), "bo-td--num");
        var tdA = cell(tr);
        var save = smallBtn("Save");
        var cancel = smallBtn("Cancel", true);
        save.addEventListener("click", function() {
            apiFetch(API + tag.id + "/", {
                    method: "PATCH",
                    body: { name: nIn.value.trim(), color: cIn.value, description: dIn.value.trim() }
                })
                .then(function(updated) {
                    Object.assign(tag, updated);
                    _tags.sort(byName);
                    renderAll();
                    showToast("Saved.");
                })
                .catch(function(e) { showToast("Error: " + e.message, "error"); });
        });
        cancel.addEventListener("click", function() { refreshRow(tr, tag); });
        tdA.appendChild(save);
        tdA.appendChild(cancel);
        nIn.focus();
    }

    function renderMerge(tr, tag) {
        var dot = document.createElement("span");
        dot.className = "bo-org-dot";
        dot.style.background = tag.color;
        cell(tr, dot);
        cell(tr, tag.name);
        var sel = document.createElement("select");
        sel.className = "bo-select bo-select--sm";
        sel.setAttribute("aria-label", "Merge “" + tag.name + "” into");
        sel.appendChild(new Option("Merge into…", ""));
        _tags.forEach(function(t) {
            if (t.id !== tag.id) sel.appendChild(new Option(t.name, t.id));
        });
        cell(tr, sel);
        cell(tr, fmtInt(tag.message_count), "bo-td--num");
        var tdA = cell(tr);
        var go = smallBtn("Merge");
        var cancel = smallBtn("Cancel", true);
        go.addEventListener("click", function() {
            var target = _tags.find(function(t) { return String(t.id) === sel.value; });
            if (!target) { showToast("Pick the tag to merge into.", "error"); return; }
            if (!confirm("Move the messages tagged “" + tag.name + "” to “" + target.name + "” and delete “" + tag.name + "”?")) return;
            apiFetch(API + tag.id + "/merge/", { method: "POST", body: { into: target.id } })
                .then(function(res) {
                    _tags = _tags.filter(function(t) { return t.id !== tag.id; });
                    Object.assign(target, res.tag);
                    renderAll();
                    showToast("Merged — " + fmtInt(res.moved) + " message(s) moved.");
                })
                .catch(function(e) { showToast("Error: " + e.message, "error"); });
        });
        cancel.addEventListener("click", function() { refreshRow(tr, tag); });
        tdA.appendChild(go);
        tdA.appendChild(cancel);
        sel.focus();
    }

    function renderRow(tag, mode) {
        var tr = document.createElement("tr");
        tr.dataset.id = tag.id;
        if (mode === "edit") renderEdit(tr, tag);
        else if (mode === "merge") renderMerge(tr, tag);
        else renderView(tr, tag);
        return tr;
    }

    function refreshRow(tr, tag, mode) {
        var fresh = renderRow(tag, mode);
        $tbody.replaceChild(fresh, tr);
    }

    function byName(a, b) { return a.name.localeCompare(b.name); }

    function renderAll() {
        $tbody.innerHTML = "";
        if (!_tags.length) { emptyRow(); return; }
        _tags.forEach(function(t) { $tbody.appendChild(renderRow(t)); });
    }

    function load() {
        return apiFetch(API + "?limit=10000").then(function(data) {
            _tags = data.results;
            renderAll();
        }).catch(function(e) { showToast("Error: " + e.message, "error"); });
    }

    // A new tag defaults to the first palette colour no tag uses yet.
    function suggestColor() {
        return apiFetch(API + "next-color/").then(function(data) {
            $addForm.elements.color.value = data.color;
        }).catch(function() { /* keep the current swatch */ });
    }

    function closeAddForm() {
        $addForm.classList.add("d-none");
        $addBtn.classList.remove("d-none");
        $addForm.reset();
    }

    $addBtn.addEventListener("click", function() {
        suggestColor();
        $addForm.classList.remove("d-none");
        $addBtn.classList.add("d-none");
        $addForm.elements.name.focus();
    });
    $cancel.addEventListener("click", closeAddForm);
    $addForm.addEventListener("submit", function(e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API, {
                method: "POST",
                body: { name: fd.get("name").trim(), color: fd.get("color"), description: fd.get("description").trim() }
            })
            .then(function(tag) {
                tag.message_count = 0;
                _tags.push(tag);
                _tags.sort(byName);
                renderAll();
                closeAddForm();
                showToast("Tag created.");
            })
            .catch(function(err) { showToast("Error: " + err.message, "error"); });
    });

    load();
})();
