/* Manage → Tags: the shared message-tag tree.

   The API lists the tags depth-first (each tag followed by its sub-tags, see
   webapp.models.tag_models.TagTree), with depth, path and two counts: the
   messages carrying the tag or a sub-tag (message_count, what ?tag=<id> lists)
   and those carrying the tag itself (own_count). Moving, merging, creating and
   deleting change paths, order and counts, so each reloads the list. */
(function() {
    "use strict";
    var API = "/manage/api/message-tags/";
    var SEARCH_URL = window.MESSAGE_SEARCH_URL || "/search/";

    var _tags = [];

    var $tbody = document.getElementById("tag-tbody");
    var $addBtn = document.getElementById("tag-add-btn");
    var $addForm = document.getElementById("tag-add-form");
    var $addParent = document.getElementById("tag-add-parent");
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

    function iconBtn(icon, title) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "bo-btn bo-btn--icon";
        b.title = title;
        b.setAttribute("aria-label", title);
        b.innerHTML = '<i class="bi ' + icon + '" aria-hidden="true"></i>';
        return b;
    }

    function byId(id) {
        return _tags.find(function(t) { return t.id === id; }) || null;
    }

    function hasChildren(tag) {
        return _tags.some(function(t) { return t.parent === tag.id; });
    }

    // The tag and all its sub-tags (ids): where it can't move, or merge into.
    function branchIds(tag) {
        var out = {};
        out[tag.id] = true;
        // _tags is depth-first, so a branch is the run of deeper rows after the tag.
        var i = _tags.indexOf(tag);
        for (var j = i + 1; j < _tags.length && _tags[j].depth > tag.depth; j++) out[_tags[j].id] = true;
        return out;
    }

    // <option>s for every tag by path, minus ``skip`` (an id → true map).
    function tagOptions(sel, skip, selected) {
        _tags.forEach(function(t) {
            if (skip && skip[t.id]) return;
            var opt = new Option(t.path, t.id);
            if (t.id === selected) opt.selected = true;
            sel.appendChild(opt);
        });
    }

    function parentSelect(tag) {
        var sel = document.createElement("select");
        sel.className = "bo-select bo-select--sm";
        sel.setAttribute("aria-label", "Parent of “" + tag.name + "”");
        sel.appendChild(new Option("— top level —", ""));
        tagOptions(sel, branchIds(tag), tag.parent);
        return sel;
    }

    function searchLink(tag, count, exact, title) {
        if (!count) return document.createTextNode("0");
        var a = document.createElement("a");
        a.href = SEARCH_URL + "?tag=" + tag.id + (exact ? "&tag_exact=1" : "");
        a.textContent = fmtInt(count);
        a.title = title;
        return a;
    }

    // "21" (the branch), and for a tag with sub-tags "· 5 direct": the posts
    // still carrying the broad tag, waiting for a more specific one.
    function countCell(tag) {
        var wrap = document.createElement("span");
        wrap.appendChild(searchLink(tag, tag.message_count, false,
            "Show the messages tagged “" + tag.path + "”" + (hasChildren(tag) ? " or one of its sub-tags" : "")));
        if (hasChildren(tag) && tag.own_count) {
            var direct = document.createElement("span");
            direct.className = "bo-tag-direct";
            direct.appendChild(document.createTextNode(" · "));
            direct.appendChild(searchLink(tag, tag.own_count, true,
                "Show the messages tagged “" + tag.path + "” itself, not a sub-tag"));
            direct.appendChild(document.createTextNode(" direct"));
            wrap.appendChild(direct);
        }
        return wrap;
    }

    function nameCell(tr, tag, content) {
        var td = cell(tr, content);
        td.className = "bo-tag-name";
        td.style.setProperty("--tag-depth", tag.depth);
        return td;
    }

    function renderView(tr, tag) {
        var dot = document.createElement("span");
        dot.className = "bo-org-dot";
        dot.style.background = tag.color;
        cell(tr, dot);
        var name = document.createElement("span");
        if (tag.depth) {
            var mark = document.createElement("span");
            mark.className = "bo-tag-branch";
            mark.setAttribute("aria-hidden", "true");
            mark.textContent = "↳ ";
            name.appendChild(mark);
            name.title = tag.path;
        }
        name.appendChild(document.createTextNode(tag.name));
        nameCell(tr, tag, name);
        cell(tr, tag.description || "");
        cell(tr, countCell(tag), "bo-td--num");
        var tdA = cell(tr);
        var editBtn = makeEditBtn();
        editBtn.title = "Edit or move “" + tag.name + "”";
        editBtn.setAttribute("aria-label", editBtn.title);
        editBtn.addEventListener("click", function() { refreshRow(tr, tag, "edit"); });
        var subBtn = iconBtn("bi-diagram-2", "Add a sub-tag under “" + tag.name + "”");
        subBtn.addEventListener("click", function() { openAddForm(tag); });
        var mergeBtn = iconBtn("bi-intersect", "Merge “" + tag.name + "” into another tag");
        mergeBtn.disabled = _tags.length < 2;
        mergeBtn.addEventListener("click", function() { refreshRow(tr, tag, "merge"); });
        var delBtn = makeDeleteBtn(tag.name);
        if (hasChildren(tag)) {
            delBtn.disabled = true;
            delBtn.title = "“" + tag.name + "” has sub-tags: move or delete them first";
            delBtn.setAttribute("aria-label", delBtn.title);
        }
        delBtn.addEventListener("click", function() {
            var what = tag.message_count ?
                "Delete “" + tag.path + "”? It is removed from " + fmtInt(tag.message_count) + " message(s). This cannot be undone." :
                "Delete “" + tag.path + "”? This cannot be undone.";
            if (!confirm(what)) return;
            apiFetch(API + tag.id + "/", { method: "DELETE" })
                .then(function() {
                    showToast("Deleted.");
                    return load();
                })
                .catch(function(e) { showToast("Error: " + e.message, "error"); });
        });
        tdA.appendChild(editBtn);
        tdA.appendChild(subBtn);
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
        var box = document.createElement("div");
        box.className = "bo-tag-edit";
        var nIn = document.createElement("input");
        nIn.className = "bo-input";
        nIn.maxLength = 64;
        nIn.value = tag.name;
        nIn.setAttribute("aria-label", "Tag name");
        var pSel = parentSelect(tag);
        var under = document.createElement("label");
        under.className = "bo-tag-under";
        under.appendChild(document.createTextNode("under "));
        under.appendChild(pSel);
        box.appendChild(nIn);
        box.appendChild(under);
        nameCell(tr, tag, box);
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
                    body: {
                        name: nIn.value.trim(),
                        color: cIn.value,
                        description: dIn.value.trim(),
                        parent: pSel.value ? Number(pSel.value) : null
                    }
                })
                .then(function() {
                    showToast("Saved.");
                    return load();
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
        nameCell(tr, tag, tag.name);
        var sel = document.createElement("select");
        sel.className = "bo-select bo-select--sm";
        sel.setAttribute("aria-label", "Merge “" + tag.name + "” into");
        sel.appendChild(new Option("Merge into…", ""));
        // Not into its own branch: the tag's sub-tags move to the target.
        tagOptions(sel, branchIds(tag));
        cell(tr, sel);
        cell(tr, fmtInt(tag.message_count), "bo-td--num");
        var tdA = cell(tr);
        var go = smallBtn("Merge");
        var cancel = smallBtn("Cancel", true);
        go.addEventListener("click", function() {
            var target = byId(Number(sel.value));
            if (!target) {
                showToast("Pick the tag to merge into.", "error");
                return;
            }
            var subs = hasChildren(tag) ? ", move its sub-tags under “" + target.path + "” (merging those with the same name)," : "";
            if (!confirm("Move the messages tagged “" + tag.path + "” to “" + target.path + "”" + subs + " and delete “" + tag.path + "”?")) return;
            apiFetch(API + tag.id + "/merge/", { method: "POST", body: { into: target.id } })
                .then(function(res) {
                    showToast("Merged — " + fmtInt(res.moved) + " message(s) moved.");
                    return load();
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

    function renderAll() {
        $tbody.innerHTML = "";
        if (!_tags.length) {
            emptyRow();
            return;
        }
        _tags.forEach(function(t) { $tbody.appendChild(renderRow(t)); });
    }

    function load() {
        return apiFetch(API + "?limit=10000").then(function(data) {
            _tags = data.results;
            renderAll();
        }).catch(function(e) { showToast("Error: " + e.message, "error"); });
    }

    // A new top-level tag defaults to the first palette colour no tag uses yet;
    // a sub-tag to its parent's colour, so a family reads as one hue.
    function suggestColor() {
        var parent = byId(Number($addParent.value));
        if (parent) {
            $addForm.elements.color.value = parent.color;
            return Promise.resolve();
        }
        return apiFetch(API + "next-color/").then(function(data) {
            $addForm.elements.color.value = data.color;
        }).catch(function() { /* keep the current swatch */ });
    }

    function fillParentSelect(selected) {
        $addParent.innerHTML = "";
        $addParent.appendChild(new Option("Top level", ""));
        tagOptions($addParent, null, selected ? selected.id : null);
    }

    function closeAddForm() {
        $addForm.classList.add("d-none");
        $addBtn.classList.remove("d-none");
        $addForm.reset();
    }

    function openAddForm(parent) {
        fillParentSelect(parent);
        suggestColor();
        $addForm.classList.remove("d-none");
        $addBtn.classList.add("d-none");
        $addForm.elements.name.focus();
    }

    $addBtn.addEventListener("click", function() { openAddForm(null); });
    $addParent.addEventListener("change", suggestColor);
    $cancel.addEventListener("click", closeAddForm);
    $addForm.addEventListener("submit", function(e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API, {
                method: "POST",
                body: {
                    name: fd.get("name").trim(),
                    color: fd.get("color"),
                    description: fd.get("description").trim(),
                    parent: fd.get("parent") ? Number(fd.get("parent")) : null
                }
            })
            .then(function() {
                closeAddForm();
                showToast("Tag created.");
                return load();
            })
            .catch(function(err) { showToast("Error: " + err.message, "error"); });
    });

    load();
})();
