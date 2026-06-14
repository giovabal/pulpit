(function () {
    "use strict";

    var API_GROUPS = "/manage/api/label-groups/";
    var API_LABELS = "/manage/api/labels/";

    var $groups    = document.getElementById("lbl-groups");
    var $count     = document.getElementById("lbl-count");
    var $addBtn    = document.getElementById("lblgrp-add-btn");
    var $addForm   = document.getElementById("lblgrp-add-form");
    var $addCancel = document.getElementById("lblgrp-add-cancel");

    var _groups = [];
    var _labelsByGroup = {};   /* group id → [label, …] */

    /* ── Data ───────────────────────────────────────────────────────────── */
    function loadAll() {
        Promise.all([
            apiFetch(API_GROUPS + "?limit=500"),
            apiFetch(API_LABELS + "?limit=500"),
        ]).then(function (res) {
            _groups = res[0].results;
            _labelsByGroup = {};
            res[1].results.forEach(function (l) {
                (_labelsByGroup[l.group_id] = _labelsByGroup[l.group_id] || []).push(l);
            });
            render();
        }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    /* ── Render ─────────────────────────────────────────────────────────── */
    function render() {
        $groups.innerHTML = "";
        $count.textContent = _groups.length + " group" + (_groups.length !== 1 ? "s" : "");
        if (!_groups.length) {
            $groups.innerHTML = '<p class="bo-empty">No label groups yet.</p>';
            return;
        }
        _groups.forEach(function (g) { $groups.appendChild(renderGroupCard(g)); });
    }

    function badge(text, extra) {
        var b = document.createElement("span");
        b.className = "bo-badge" + (extra ? " " + extra : "");
        b.textContent = text;
        return b;
    }

    function renderGroupCard(group) {
        var card = document.createElement("div"); card.className = "bo-label-group-card";
        card.appendChild(groupHeadView(card, group));

        var wrap = document.createElement("div"); wrap.className = "table-responsive";
        var table = document.createElement("table"); table.className = "bo-table bo-label-table";
        table.innerHTML =
            '<thead><tr>' +
            '<th scope="col">Color</th><th scope="col">Name</th>' +
            '<th class="bo-th--center" scope="col">In target</th>' +
            '<th class="bo-th--num" scope="col">Channels</th>' +
            '<th scope="col"><span class="sr-only">Actions</span></th>' +
            '</tr></thead>';
        var tbody = document.createElement("tbody");
        var labels = _labelsByGroup[group.id] || [];
        if (!labels.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="bo-empty">No labels in this group yet.</td></tr>';
        } else {
            labels.forEach(function (l) { tbody.appendChild(labelRowView(tbody, group, l)); });
        }
        table.appendChild(tbody);
        wrap.appendChild(table);
        card.appendChild(wrap);
        return card;
    }

    /* ── Group head (view / edit) ───────────────────────────────────────── */
    function groupHeadView(card, group) {
        var head = document.createElement("div"); head.className = "bo-label-group-head";

        var dot = document.createElement("span"); dot.className = "bo-org-dot"; dot.style.background = group.color || "#ccc";
        var name = document.createElement("span"); name.className = "bo-label-group-name fw-semibold"; name.textContent = group.name;
        head.appendChild(dot); head.appendChild(name);
        if (group.is_partition) head.appendChild(badge("Partition"));
        if (group.is_primary) head.appendChild(badge("Primary", "bo-badge--primary"));
        var cnt = document.createElement("span"); cnt.className = "text-muted small ms-2";
        cnt.textContent = fmtInt(group.label_count) + " label" + (group.label_count !== 1 ? "s" : "");
        head.appendChild(cnt);

        var actions = document.createElement("span"); actions.className = "bo-label-group-actions ms-auto";
        var addLabelBtn = document.createElement("button"); addLabelBtn.className = "bo-btn bo-btn--sm bo-btn--ghost";
        addLabelBtn.innerHTML = '<i class="bi bi-plus me-1"></i>Add label';
        addLabelBtn.addEventListener("click", function () { startAddLabel(card, group); });
        var editBtn = makeEditBtn();
        editBtn.addEventListener("click", function () { card.replaceChild(groupHeadEdit(card, group), head); });
        var delBtn = makeDeleteBtn(group.name);
        delBtn.addEventListener("click", function () {
            confirmDelete(group.name + " (and all its labels)").then(function (ok) {
                if (!ok) return;
                apiFetch(API_GROUPS + group.id + "/", { method: "DELETE" })
                    .then(function () { showToast("Group deleted."); loadAll(); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
        });
        actions.appendChild(addLabelBtn); actions.appendChild(editBtn); actions.appendChild(delBtn);
        head.appendChild(actions);
        return head;
    }

    function groupHeadEdit(card, group) {
        var head = document.createElement("div"); head.className = "bo-label-group-head";

        var color = document.createElement("input");
        color.type = "color"; color.className = "bo-input bo-input--color"; color.value = group.color || "#4338ca";
        var name = document.createElement("input");
        name.className = "bo-input bo-input--wide"; name.value = group.name;
        var partLbl = document.createElement("label"); partLbl.className = "bo-check-label";
        var part = document.createElement("input"); part.type = "checkbox"; part.checked = group.is_partition;
        partLbl.appendChild(part); partLbl.appendChild(document.createTextNode(" Partition"));
        var primLbl = document.createElement("label"); primLbl.className = "bo-check-label";
        var prim = document.createElement("input"); prim.type = "checkbox"; prim.checked = group.is_primary;
        primLbl.appendChild(prim); primLbl.appendChild(document.createTextNode(" Primary"));

        var save = document.createElement("button"); save.className = "bo-btn bo-btn--sm ms-auto"; save.textContent = "Save";
        var cancel = document.createElement("button"); cancel.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancel.textContent = "Cancel";
        save.addEventListener("click", function () {
            apiFetch(API_GROUPS + group.id + "/", {
                method: "PATCH",
                body: { name: name.value.trim(), color: color.value, is_partition: part.checked, is_primary: prim.checked },
            }).then(function () { showToast("Group saved."); loadAll(); })
              .catch(function (e) { showToast("Error: " + e.message, "error"); });
        });
        cancel.addEventListener("click", function () { card.replaceChild(groupHeadView(card, group), head); });

        head.appendChild(color); head.appendChild(name);
        head.appendChild(partLbl); head.appendChild(primLbl);
        head.appendChild(save); head.appendChild(cancel);
        return head;
    }

    /* ── Label rows (view / edit / add) ─────────────────────────────────── */
    function startAddLabel(card, group) {
        var tbody = card.querySelector("tbody");
        var empty = tbody.querySelector(".bo-empty");
        if (empty) empty.parentNode.remove();
        tbody.insertBefore(labelRowEdit(tbody, group, null), tbody.firstChild);
    }

    function labelRowView(tbody, group, label) {
        var tr = document.createElement("tr"); tr.dataset.id = label.id;

        var tdC = document.createElement("td");
        var dot = document.createElement("span"); dot.className = "bo-org-dot"; dot.style.background = label.color || "#ccc";
        tdC.appendChild(dot); tr.appendChild(tdC);

        var tdN = document.createElement("td"); tdN.textContent = label.name; tr.appendChild(tdN);

        var tdI = document.createElement("td"); tdI.className = "bo-td--center";
        var icon = document.createElement("i");
        icon.className = label.is_in_target ? "bi bi-check-circle-fill text-success" : "bi bi-x-circle text-secondary";
        tdI.appendChild(icon); tr.appendChild(tdI);

        var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num";
        tdCnt.textContent = fmtInt(label.channel_count); tr.appendChild(tdCnt);

        var tdA = document.createElement("td");
        var editBtn = makeEditBtn();
        editBtn.addEventListener("click", function () { tbody.replaceChild(labelRowEdit(tbody, group, label), tr); });
        var delBtn = makeDeleteBtn(label.name);
        delBtn.addEventListener("click", function () {
            confirmDelete(label.name).then(function (ok) {
                if (!ok) return;
                apiFetch(API_LABELS + label.id + "/", { method: "DELETE" })
                    .then(function () { showToast("Label deleted."); loadAll(); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
        });
        tdA.appendChild(editBtn); tdA.appendChild(delBtn); tr.appendChild(tdA);
        return tr;
    }

    function labelRowEdit(tbody, group, label) {
        var tr = document.createElement("tr");

        var tdC = document.createElement("td");
        var color = document.createElement("input");
        color.type = "color"; color.className = "bo-input bo-input--color";
        color.value = (label && label.color) || group.color || "#4338ca";
        tdC.appendChild(color); tr.appendChild(tdC);

        var tdN = document.createElement("td");
        var name = document.createElement("input");
        name.className = "bo-input bo-input--wide"; name.value = label ? label.name : ""; name.placeholder = "Label name";
        tdN.appendChild(name); tr.appendChild(tdN);

        var tdI = document.createElement("td"); tdI.className = "bo-td--center";
        var inTarget = document.createElement("input");
        inTarget.type = "checkbox"; inTarget.checked = label ? label.is_in_target : false;
        tdI.appendChild(inTarget); tr.appendChild(tdI);

        var tdCnt = document.createElement("td"); tdCnt.className = "bo-td--num";
        tdCnt.textContent = label ? fmtInt(label.channel_count) : "—"; tr.appendChild(tdCnt);

        var tdA = document.createElement("td");
        var save = document.createElement("button"); save.className = "bo-btn bo-btn--sm"; save.textContent = "Save";
        var cancel = document.createElement("button"); cancel.className = "bo-btn bo-btn--sm bo-btn--ghost"; cancel.textContent = "Cancel";
        save.addEventListener("click", function () {
            var body = { name: name.value.trim(), color: color.value, is_in_target: inTarget.checked };
            var req = label
                ? apiFetch(API_LABELS + label.id + "/", { method: "PATCH", body: body })
                : apiFetch(API_LABELS, { method: "POST", body: Object.assign({ group_id: group.id }, body) });
            req.then(function () { showToast(label ? "Label saved." : "Label created."); loadAll(); })
               .catch(function (e) { showToast("Error: " + e.message, "error"); });
        });
        cancel.addEventListener("click", function () {
            if (label) tbody.replaceChild(labelRowView(tbody, group, label), tr);
            else render();   /* discard the unsaved add-row */
        });
        tdA.appendChild(save); tdA.appendChild(cancel); tr.appendChild(tdA);
        return tr;
    }

    /* ── Add group ──────────────────────────────────────────────────────── */
    $addBtn.addEventListener("click", function () { $addForm.classList.remove("d-none"); $addBtn.classList.add("d-none"); });
    $addCancel.addEventListener("click", function () { $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none"); $addForm.reset(); });
    $addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var fd = new FormData($addForm);
        apiFetch(API_GROUPS, {
            method: "POST",
            body: {
                name: fd.get("name").trim(),
                color: fd.get("color"),
                is_partition: fd.get("is_partition") === "on",
                is_primary: fd.get("is_primary") === "on",
            },
        }).then(function () {
            $addForm.reset(); $addForm.classList.add("d-none"); $addBtn.classList.remove("d-none");
            showToast("Group created.");
            loadAll();
        }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    });

    loadAll();
})();
