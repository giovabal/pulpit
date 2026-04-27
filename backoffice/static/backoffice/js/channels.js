(function () {
    "use strict";

    var API_BASE = "/manage/api/";
    var PAGE_SIZE = BACKOFFICE_PAGE_SIZE;

    /* ── State ──────────────────────────────────────────────────────────── */
    var _orgs = [];
    var _groups = [];
    var _channels = [];
    var _total = 0;
    var _offset = 0;
    var _loading = false;
    var _searchTimer = null;
    var _sortField = "title";
    var _sortDir   = "asc";

    /* ── DOM refs ───────────────────────────────────────────────────────── */
    var $search     = document.getElementById("ch-search");
    var $status     = document.getElementById("ch-status");
    var $orgFilter  = document.getElementById("ch-org-filter");
    var $groupFilter= document.getElementById("ch-group-filter");
    var $count      = document.getElementById("ch-count");
    var $pagination       = document.getElementById("ch-pagination");
    var $paginationBottom = document.getElementById("ch-pagination-bottom");
    var $tbody      = document.getElementById("ch-tbody");
    var $selectAll  = document.getElementById("ch-select-all");
    var $bulkBar    = document.getElementById("ch-bulk-bar");
    var $bulkCount  = document.getElementById("ch-bulk-count");
    var $bulkOrg    = document.getElementById("ch-bulk-org");
    var $bulkAddGrp = document.getElementById("ch-bulk-add-group");
    var $bulkRmGrp  = document.getElementById("ch-bulk-rm-group");

    /* ── Query helpers ──────────────────────────────────────────────────── */
    function buildUrl(extraOffset) {
        var off = extraOffset !== undefined ? extraOffset : _offset;
        var params = new URLSearchParams({ limit: PAGE_SIZE, offset: off });
        var s = $search.value.trim();
        if (s) params.set("search", s);
        var st = $status.value;
        if (st) params.set("status", st);
        var org = $orgFilter.value;
        if (org) params.set("organization", org);
        var grp = $groupFilter.value;
        if (grp) params.set("group", grp);
        params.set("ordering", (_sortDir === "desc" ? "-" : "") + _sortField);
        return API_BASE + "channels/?" + params.toString();
    }

    /* ── Sort helpers ───────────────────────────────────────────────────── */
    var _SORT_COLS = {
        "ch-th-id":          "id",
        "ch-th-name":        "title",
        "ch-th-subscribers": "participants_count",
        "ch-th-indegree":    "in_degree",
    };

    function _updateSortHeaders() {
        Object.keys(_SORT_COLS).forEach(function (id) {
            var th = document.getElementById(id);
            if (!th) return;
            var field = _SORT_COLS[id];
            var indicator = th.querySelector(".bo-sort-icon");
            if (!indicator) return;
            if (field === _sortField) {
                indicator.textContent = _sortDir === "asc" ? " ▲" : " ▼";
                th.classList.add("bo-th--sorted");
            } else {
                indicator.textContent = " ⇅";
                th.classList.remove("bo-th--sorted");
            }
        });
    }

    function _onSortClick(field) {
        if (_sortField === field) {
            _sortDir = _sortDir === "asc" ? "desc" : "asc";
        } else {
            _sortField = field;
            _sortDir = "asc";
        }
        _offset = 0;
        _updateSortHeaders();
        loadChannels();
    }

    function selectedIds() {
        return Array.from($tbody.querySelectorAll("input[type=checkbox]:checked"))
            .map(function (cb) { return parseInt(cb.dataset.id); });
    }

    /* ── Render ─────────────────────────────────────────────────────────── */
    function renderFilters() {
        /* organizations */
        [$orgFilter, $bulkOrg].forEach(function (sel) {
            while (sel.options.length > (sel === $orgFilter ? 1 : 0)) sel.remove(sel.options.length - 1);
            if (sel === $bulkOrg) {
                var optUnassign = new Option("— Unassign —", "null");
                sel.appendChild(optUnassign);
            }
            _orgs.forEach(function (o) {
                sel.appendChild(new Option(o.name, o.id));
            });
        });
        /* groups */
        [$groupFilter, $bulkAddGrp, $bulkRmGrp].forEach(function (sel) {
            while (sel.options.length > (sel === $groupFilter ? 1 : 0)) sel.remove(sel.options.length - 1);
            _groups.forEach(function (g) {
                sel.appendChild(new Option(g.name, g.id));
            });
        });
    }

    function renderTable(channels) {
        $tbody.innerHTML = "";
        if (!channels.length) {
            $tbody.innerHTML = '<tr><td colspan="8" class="bo-empty">No channels found.</td></tr>';
            return;
        }
        var frag = document.createDocumentFragment();
        channels.forEach(function (ch) {
            var tr = document.createElement("tr");
            tr.dataset.id = ch.id;

            /* checkbox */
            var tdChk = document.createElement("td");
            var chk = document.createElement("input");
            chk.type = "checkbox"; chk.dataset.id = ch.id;
            chk.addEventListener("change", updateBulkBar);
            tdChk.appendChild(chk); tr.appendChild(tdChk);

            /* id */
            var tdId = document.createElement("td"); tdId.className = "bo-td--num bo-td--id";
            tdId.textContent = ch.id; tr.appendChild(tdId);

            /* name */
            var tdName = document.createElement("td"); tdName.className = "bo-ch-cell";
            var nameWrap = document.createElement("div");
            var nameEl = document.createElement("div"); nameEl.className = "bo-ch-name";
            nameEl.textContent = ch.title || ("ID " + ch.id);
            nameWrap.appendChild(nameEl);
            if (ch.username) {
                var unEl = document.createElement("a"); unEl.className = "bo-ch-username";
                unEl.href = "https://t.me/" + ch.username;
                unEl.target = "_blank"; unEl.rel = "noopener noreferrer";
                unEl.textContent = "@" + ch.username;
                nameWrap.appendChild(unEl);
            }
            tdName.appendChild(nameWrap);
            if (ch.profile_picture_url) {
                var img = document.createElement("img");
                img.className = "bo-ch-pic";
                img.src = ch.profile_picture_url;
                img.alt = "";
                tdName.appendChild(img);
            }
            tr.appendChild(tdName);

            /* type */
            var tdType = document.createElement("td");
            var badge = document.createElement("span"); badge.className = "bo-type-badge";
            badge.textContent = ch.channel_type || "—";
            tdType.appendChild(badge); tr.appendChild(tdType);

            /* org */
            var tdOrg = document.createElement("td");
            tdOrg.className = "bo-org-cell";
            renderOrgCell(tdOrg, ch);
            tdOrg.addEventListener("click", function (e) {
                if (e.target.classList.contains("bo-org-select")) return;
                openOrgSelect(tdOrg, ch);
            });
            tr.appendChild(tdOrg);

            /* groups */
            var tdGrp = document.createElement("td");
            renderGroupChips(tdGrp, ch);
            tr.appendChild(tdGrp);

            /* subscribers */
            var tdSub = document.createElement("td"); tdSub.className = "bo-td--num";
            tdSub.textContent = fmtInt(ch.participants_count); tr.appendChild(tdSub);

            /* in-degree */
            var tdIn = document.createElement("td"); tdIn.className = "bo-td--num";
            tdIn.textContent = fmtInt(ch.in_degree); tr.appendChild(tdIn);

            frag.appendChild(tr);
        });
        $tbody.appendChild(frag);
    }

    function renderOrgCell(td, ch) {
        td.innerHTML = "";
        if (ch.organization_id) {
            var dot = document.createElement("span"); dot.className = "bo-org-dot";
            dot.style.background = ch.organization_color || "#ccc";
            var name = document.createElement("span"); name.className = "bo-org-name";
            name.textContent = ch.organization_name;
            td.appendChild(dot); td.appendChild(name);
        } else {
            var un = document.createElement("span"); un.className = "bo-org-unassigned";
            un.textContent = "— unassigned";
            td.appendChild(un);
        }
    }

    function openOrgSelect(td, ch) {
        var sel = document.createElement("select"); sel.className = "bo-org-select";
        sel.appendChild(new Option("— unassign —", ""));
        _orgs.forEach(function (o) {
            var opt = new Option(o.name, o.id);
            if (o.id === ch.organization_id) opt.selected = true;
            sel.appendChild(opt);
        });
        td.innerHTML = "";
        td.appendChild(sel);
        sel.focus();

        sel.addEventListener("change", function () {
            var newOrgId = sel.value ? parseInt(sel.value) : null;
            assignOrg(ch, newOrgId, td);
        });
        sel.addEventListener("keydown", function (e) {
            if (e.key === "Escape") renderOrgCell(td, ch);
        });
        sel.addEventListener("blur", function () {
            setTimeout(function () { renderOrgCell(td, ch); }, 150);
        });
    }

    function assignOrg(ch, newOrgId, td) {
        var prevOrgId = ch.organization_id;
        var prevOrgName = ch.organization_name;
        var prevOrgColor = ch.organization_color;

        /* optimistic update */
        var org = _orgs.find(function (o) { return o.id === newOrgId; });
        ch.organization_id = newOrgId;
        ch.organization_name = org ? org.name : null;
        ch.organization_color = org ? org.color : null;
        renderOrgCell(td, ch);

        apiFetch(API_BASE + "channels/" + ch.id + "/", {
            method: "PATCH",
            body: { organization_id: newOrgId },
        }).then(function () {
            showToast("Organization updated.");
        }).catch(function (err) {
            ch.organization_id = prevOrgId;
            ch.organization_name = prevOrgName;
            ch.organization_color = prevOrgColor;
            renderOrgCell(td, ch);
            showToast("Error: " + err.message, "error");
        });
    }

    function renderGroupChips(td, ch) {
        td.innerHTML = "";
        var wrap = document.createElement("div"); wrap.className = "bo-chips";
        (ch.group_ids || []).forEach(function (gid) {
            var grp = _groups.find(function (g) { return g.id === gid; });
            if (!grp) return;
            var chip = document.createElement("span");
            chip.className = "bo-chip";
            chip.style.background = "#6366f1"; /* default group color */
            chip.textContent = grp.name;

            var rmBtn = document.createElement("button"); rmBtn.className = "bo-chip-remove";
            rmBtn.innerHTML = "&times;"; rmBtn.title = "Remove from group";
            rmBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                removeGroup(ch, gid, td);
            });
            chip.appendChild(rmBtn);
            wrap.appendChild(chip);
        });

        /* + button */
        var available = _groups.filter(function (g) { return !(ch.group_ids || []).includes(g.id); });
        if (available.length) {
            var addBtn = document.createElement("button"); addBtn.className = "bo-chip-add";
            addBtn.innerHTML = "+"; addBtn.title = "Add to group";
            addBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                openGroupDropdown(addBtn, ch, td, available);
            });
            wrap.appendChild(addBtn);
        }
        td.appendChild(wrap);
    }

    function openGroupDropdown(anchor, ch, td, available) {
        document.querySelectorAll(".bo-chip-dropdown").forEach(function (el) { el.remove(); });
        var dropdown = document.createElement("div"); dropdown.className = "bo-chip-dropdown";
        available.forEach(function (g) {
            var btn = document.createElement("button"); btn.textContent = g.name;
            btn.addEventListener("click", function () {
                dropdown.remove();
                addGroup(ch, g.id, td);
            });
            dropdown.appendChild(btn);
        });
        anchor.parentNode.style.position = "relative";
        anchor.parentNode.appendChild(dropdown);
        document.addEventListener("click", function handler(e) {
            if (!dropdown.contains(e.target)) { dropdown.remove(); document.removeEventListener("click", handler); }
        });
    }

    function addGroup(ch, groupId, td) {
        var newIds = (ch.group_ids || []).concat([groupId]);
        apiFetch(API_BASE + "channels/" + ch.id + "/", {
            method: "PATCH",
            body: { group_ids: newIds },
        }).then(function (data) {
            ch.group_ids = data.group_ids;
            renderGroupChips(td, ch);
            showToast("Group added.");
        }).catch(function (err) { showToast("Error: " + err.message, "error"); });
    }

    function removeGroup(ch, groupId, td) {
        var newIds = (ch.group_ids || []).filter(function (id) { return id !== groupId; });
        apiFetch(API_BASE + "channels/" + ch.id + "/", {
            method: "PATCH",
            body: { group_ids: newIds },
        }).then(function (data) {
            ch.group_ids = data.group_ids;
            renderGroupChips(td, ch);
            showToast("Group removed.");
        }).catch(function (err) { showToast("Error: " + err.message, "error"); });
    }

    /* ── Bulk actions ───────────────────────────────────────────────────── */
    function updateBulkBar() {
        var ids = selectedIds();
        $selectAll.indeterminate = ids.length > 0 && ids.length < $tbody.querySelectorAll("input[type=checkbox]").length;
        $selectAll.checked = ids.length > 0 && ids.length === $tbody.querySelectorAll("input[type=checkbox]").length;

        if (ids.length) {
            $bulkBar.classList.remove("d-none");
            $bulkCount.textContent = ids.length + " selected";
        } else {
            $bulkBar.classList.add("d-none");
        }
    }

    function bulkApplyOrg() {
        var ids = selectedIds();
        if (!ids.length) return;
        var orgVal = $bulkOrg.value;
        var orgId = orgVal === "null" ? null : (orgVal ? parseInt(orgVal) : undefined);
        if (orgId === undefined) { showToast("Select an organization first.", "error"); return; }
        apiFetch(API_BASE + "channels/bulk-assign/", {
            method: "POST",
            body: { ids: ids, organization_id: orgId },
        }).then(function (data) {
            showToast("Updated " + data.updated + " channels.");
            loadChannels();
        }).catch(function (err) { showToast("Error: " + err.message, "error"); });
    }

    function bulkApplyGroup(action) {
        var ids = selectedIds();
        if (!ids.length) return;
        var sel = action === "add" ? $bulkAddGrp : $bulkRmGrp;
        var groupId = parseInt(sel.value);
        if (!groupId) { showToast("Select a group first.", "error"); return; }
        var key = action === "add" ? "add_group_ids" : "remove_group_ids";
        var body = { ids: ids };
        body[key] = [groupId];
        apiFetch(API_BASE + "channels/bulk-assign/", { method: "POST", body: body })
            .then(function (data) {
                showToast("Updated " + data.updated + " channels.");
                loadChannels();
            }).catch(function (err) { showToast("Error: " + err.message, "error"); });
    }

    /* ── Pagination ─────────────────────────────────────────────────────── */
    function _goToPage(newOffset) { _offset = newOffset; loadChannels(); }
    function _renderPagination() {
        renderPagination($pagination, _offset, _total, PAGE_SIZE, _goToPage);
        renderPagination($paginationBottom, _offset, _total, PAGE_SIZE, _goToPage);
    }

    /* ── Data loading ───────────────────────────────────────────────────── */
    function loadChannels() {
        if (_loading) return;
        _loading = true;
        $tbody.innerHTML = '<tr><td colspan="7" class="bo-empty">Loading…</td></tr>';
        $selectAll.checked = false;
        $bulkBar.classList.add("d-none");

        apiFetch(buildUrl())
            .then(function (data) {
                _channels = data.results;
                _total = data.count;
                $count.textContent = _total + " channel" + (_total !== 1 ? "s" : "");
                renderTable(_channels);
                _renderPagination();
            })
            .catch(function (err) {
                $tbody.innerHTML = '<tr><td colspan="7" class="bo-empty">Error loading channels: ' + err.message + "</td></tr>";
            })
            .finally(function () { _loading = false; });
    }

    /* ── Init ───────────────────────────────────────────────────────────── */
    Promise.all([
        apiFetch(API_BASE + "organizations/?limit=500"),
        apiFetch(API_BASE + "groups/?limit=500"),
    ]).then(function (results) {
        _orgs = results[0].results;
        _groups = results[1].results;
        renderFilters();
        loadChannels();
    }).catch(function (err) { showToast("Error loading data: " + err.message, "error"); });

    /* ── Event listeners ────────────────────────────────────────────────── */
    $search.addEventListener("input", function () {
        clearTimeout(_searchTimer);
        _searchTimer = setTimeout(function () { _offset = 0; loadChannels(); }, 300);
    });
    [$status, $orgFilter, $groupFilter].forEach(function (el) {
        el.addEventListener("change", function () { _offset = 0; loadChannels(); });
    });
    $selectAll.addEventListener("change", function () {
        $tbody.querySelectorAll("input[type=checkbox]").forEach(function (cb) { cb.checked = $selectAll.checked; });
        updateBulkBar();
    });
    document.getElementById("ch-bulk-org-apply").addEventListener("click", bulkApplyOrg);
    document.getElementById("ch-bulk-add-group-apply").addEventListener("click", function () { bulkApplyGroup("add"); });
    document.getElementById("ch-bulk-rm-group-apply").addEventListener("click", function () { bulkApplyGroup("remove"); });
    Object.keys(_SORT_COLS).forEach(function (id) {
        var th = document.getElementById(id);
        if (th) th.addEventListener("click", function () { _onSortClick(_SORT_COLS[id]); });
    });
    _updateSortHeaders();
})();
