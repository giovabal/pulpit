(function () {
    "use strict";

    var API_BASE = "/manage/api/";
    var PAGE_SIZE = BACKOFFICE_PAGE_SIZE;

    /* ── State ──────────────────────────────────────────────────────────── */
    var _labels = [];
    var _groups = [];
    var _channels = [];
    var _total = 0;
    var _offset = 0;
    var _loading = false;
    var _searchTimer = null;
    var _sortField = "id";
    var _sortDir   = "desc";

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
        var label = $orgFilter.value;
        if (label) params.set("label", label);
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
        "ch-th-first-seen":  "_created",
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
                th.setAttribute("aria-sort", _sortDir === "asc" ? "ascending" : "descending");
            } else {
                indicator.textContent = " ⇅";
                th.classList.remove("bo-th--sorted");
                th.setAttribute("aria-sort", "none");
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
        loadChannels("push");
        if (window.PulpitA11y) {
            var th = document.querySelector('[id^="ch-th-"].bo-th--sorted');
            var labelEl = th && (th.querySelector(".bo-th-sort-btn") || th);
            var label = labelEl ? labelEl.textContent.replace(/[⇅▲▼]/g, "").trim() : field;
            window.PulpitA11y.announce("Sorted by " + label + ", " + (_sortDir === "asc" ? "ascending" : "descending"));
        }
    }

    /* ── URL state ──────────────────────────────────────────────────────── */
    function _buildQueryString() {
        var p = new URLSearchParams();
        var s = $search.value.trim(); if (s) p.set("search", s);
        var st = $status.value; if (st) p.set("status", st);
        var label = $orgFilter.value; if (label) p.set("label", label);
        var grp = $groupFilter.value; if (grp) p.set("group", grp);
        if (_sortField !== "id") p.set("sort", _sortField);
        if (_sortDir !== "desc") p.set("dir", _sortDir);
        var page = Math.floor(_offset / PAGE_SIZE) + 1; if (page > 1) p.set("page", page);
        var qs = p.toString();
        return qs ? window.location.pathname + "?" + qs : window.location.pathname;
    }

    function _syncFormFromUrl() {
        var p = new URLSearchParams(window.location.search);
        $search.value = p.get("search") || "";
        $status.value = p.get("status") || "";
        $orgFilter.value = p.get("label") || "";
        $groupFilter.value = p.get("group") || "";
        _sortField = p.get("sort") || "id";
        _sortDir = p.get("dir") || "desc";
        var page = parseInt(p.get("page") || "1", 10);
        _offset = (isNaN(page) || page < 1 ? 0 : page - 1) * PAGE_SIZE;
        _updateSortHeaders();
    }

    function selectedIds() {
        return Array.from($tbody.querySelectorAll("input[type=checkbox]:checked"))
            .map(function (cb) { return parseInt(cb.dataset.id, 10); });
    }

    /* ── Render ─────────────────────────────────────────────────────────── */
    function renderFilters() {
        /* labels (grouped into <optgroup> by label group) */
        [$orgFilter, $bulkOrg].forEach(function (sel) {
            sel.innerHTML = "";
            sel.appendChild(sel === $orgFilter ? new Option("All labels", "") : new Option("— Unassign —", "null"));
            var currentGroup = null, og = null;
            _labels.forEach(function (l) {
                if (l.group_name !== currentGroup) {
                    currentGroup = l.group_name;
                    og = document.createElement("optgroup"); og.label = currentGroup;
                    sel.appendChild(og);
                }
                og.appendChild(new Option(l.name, l.id));
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
            $tbody.innerHTML = '<tr><td colspan="10" class="bo-empty">No channels found.</td></tr>';
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
            var idLink = document.createElement("a"); idLink.href = "/manage/channels/" + ch.id + "/";
            idLink.textContent = ch.id;
            tdId.appendChild(idLink); tr.appendChild(tdId);

            /* name */
            var tdName = document.createElement("td"); tdName.className = "bo-ch-cell";
            var nameWrap = document.createElement("div"); nameWrap.className = "bo-ch-name-wrap";
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
            if (ch.detail_url) {
                var detailBtn = document.createElement("a");
                detailBtn.className = "bo-btn bo-btn--icon bo-detail-btn";
                detailBtn.href = ch.detail_url;
                detailBtn.title = "View detail page";
                detailBtn.setAttribute("aria-label", "View detail page for " + (ch.title || ch.id));
                detailBtn.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i>';
                tdName.appendChild(detailBtn);
            }
            var picEl = makeProfilePicEl(ch, "bo-ch-pic bo-ch-pic--clickable");
            if (picEl) {
                picEl.title = "View profile pictures";
                picEl.addEventListener("click", function (e) { e.stopPropagation(); _openPicModal(ch); });
                tdName.appendChild(picEl);
            }
            tr.appendChild(tdName);

            /* type */
            var tdType = document.createElement("td");
            var badge = document.createElement("span"); badge.className = "bo-type-badge";
            badge.textContent = ch.channel_type || "—";
            tdType.appendChild(badge); tr.appendChild(tdType);

            /* labels (read-only current label per group; edit time-bounded periods on the channel page) */
            var tdLabels = document.createElement("td");
            tdLabels.className = "bo-org-cell";
            renderLabelsCell(tdLabels, ch);
            tr.appendChild(tdLabels);

            /* to-inspect */
            var tdInspect = document.createElement("td");
            renderInspectCell(tdInspect, ch);
            tr.appendChild(tdInspect);

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

            /* first seen (DB registration timestamp; full datetime on hover) */
            var tdSeen = document.createElement("td"); tdSeen.className = "bo-td--date";
            tdSeen.textContent = fmtDate(ch.first_seen);
            if (ch.first_seen) tdSeen.title = new Date(ch.first_seen).toLocaleString();
            tr.appendChild(tdSeen);

            frag.appendChild(tr);
        });
        $tbody.appendChild(frag);
    }

    function renderLabelsCell(td, ch) {
        td.innerHTML = "";
        var labels = ch.current_labels || [];
        if (!labels.length) {
            var un = document.createElement("span"); un.className = "bo-org-unassigned";
            un.textContent = "— unassigned";
            td.appendChild(un);
            return;
        }
        var wrap = document.createElement("div"); wrap.className = "bo-labels-cell";
        labels.forEach(function (l) {
            var chip = document.createElement("span"); chip.className = "bo-label-chip";
            chip.title = l.group_name;   /* which group this label belongs to */
            var dot = document.createElement("span"); dot.className = "bo-org-dot";
            dot.style.background = l.color || "#ccc";
            var name = document.createElement("span"); name.className = "bo-org-name";
            name.textContent = l.name;
            chip.appendChild(dot); chip.appendChild(name);
            wrap.appendChild(chip);
        });
        td.appendChild(wrap);
    }

    function renderInspectCell(td, ch) {
        td.innerHTML = "";
        var chk = document.createElement("input");
        chk.type = "checkbox";
        chk.className = "bo-inspect-checkbox";
        chk.checked = !!ch.to_inspect;
        chk.title = "Crawl this channel even when it isn't in target";
        chk.addEventListener("change", function () {
            var newVal = chk.checked;
            var prev = ch.to_inspect;
            ch.to_inspect = newVal;
            apiFetch(API_BASE + "channels/" + ch.id + "/", {
                method: "PATCH",
                body: { to_inspect: newVal },
            }).then(function () {
                showToast("Inspect flag updated.");
            }).catch(function (err) {
                ch.to_inspect = prev;
                renderInspectCell(td, ch);
                showToast("Error: " + err.message, "error");
            });
        });
        td.appendChild(chk);
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

    function bulkApplyLabel() {
        var ids = selectedIds();
        if (!ids.length) return;
        var val = $bulkOrg.value;
        var labelId = val === "null" ? null : (val ? parseInt(val, 10) : undefined);
        if (labelId === undefined) { showToast("Select a label first.", "error"); return; }
        apiFetch(API_BASE + "channels/bulk-assign/", {
            method: "POST",
            body: { ids: ids, label_id: labelId },
        }).then(function (data) {
            showToast("Updated " + data.updated + " channels.");
            loadChannels(null);
        }).catch(function (err) { showToast("Error: " + err.message, "error"); });
    }

    function bulkApplyGroup(action) {
        var ids = selectedIds();
        if (!ids.length) return;
        var sel = action === "add" ? $bulkAddGrp : $bulkRmGrp;
        var groupId = parseInt(sel.value, 10);
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
    function _goToPage(newOffset) { _offset = newOffset; loadChannels("push"); }
    function _renderPagination() {
        renderPagination($pagination, _offset, _total, PAGE_SIZE, _goToPage);
        renderPagination($paginationBottom, _offset, _total, PAGE_SIZE, _goToPage);
    }

    /* ── Data loading ───────────────────────────────────────────────────── */
    function loadChannels(updateUrl) {
        if (_loading) return;
        _loading = true;
        $tbody.innerHTML = '<tr><td colspan="10" class="bo-empty">Loading…</td></tr>';
        $selectAll.checked = false;
        $bulkBar.classList.add("d-none");

        apiFetch(buildUrl())
            .then(function (data) {
                _channels = data.results;
                _total = data.count;
                $count.textContent = _total + " channel" + (_total !== 1 ? "s" : "");
                renderTable(_channels);
                _renderPagination();
                if (updateUrl === "push")    history.pushState(null, "", _buildQueryString());
                if (updateUrl === "replace") history.replaceState(null, "", _buildQueryString());
            })
            .catch(function (err) {
                // textContent (via replaceChildren) — apiFetch threads DRF's error
                // string through err.message, and DRF sometimes echoes request-supplied
                // values (e.g. an invalid `ordering` param). Building the row with
                // innerHTML would turn that into an XSS via a crafted /manage/channels/ URL.
                var tr = document.createElement("tr");
                var td = document.createElement("td");
                td.colSpan = 10;
                td.className = "bo-empty";
                td.textContent = "Error loading channels: " + err.message;
                tr.appendChild(td);
                $tbody.replaceChildren(tr);
            })
            .finally(function () { _loading = false; });
    }

    /* ── Init ───────────────────────────────────────────────────────────── */
    Promise.all([
        apiFetch(API_BASE + "labels/?limit=500"),
        apiFetch(API_BASE + "groups/?limit=500"),
    ]).then(function (results) {
        _labels = results[0].results;
        _groups = results[1].results;
        renderFilters();
        _syncFormFromUrl();
        loadChannels("replace");
    }).catch(function (err) { showToast("Error loading data: " + err.message, "error"); });

    /* ── Event listeners ────────────────────────────────────────────────── */
    $search.addEventListener("input", function () {
        clearTimeout(_searchTimer);
        _searchTimer = setTimeout(function () { _offset = 0; loadChannels("push"); }, 300);
    });
    [$status, $orgFilter, $groupFilter].forEach(function (el) {
        el.addEventListener("change", function () { _offset = 0; loadChannels("push"); });
    });
    window.addEventListener("popstate", function () {
        _syncFormFromUrl();
        loadChannels(null);
    });
    $selectAll.addEventListener("change", function () {
        $tbody.querySelectorAll("input[type=checkbox]").forEach(function (cb) { cb.checked = $selectAll.checked; });
        updateBulkBar();
    });
    document.getElementById("ch-bulk-org-apply").addEventListener("click", bulkApplyLabel);
    document.getElementById("ch-bulk-add-group-apply").addEventListener("click", function () { bulkApplyGroup("add"); });
    document.getElementById("ch-bulk-rm-group-apply").addEventListener("click", function () { bulkApplyGroup("remove"); });
    Object.keys(_SORT_COLS).forEach(function (id) {
        var th = document.getElementById(id);
        if (th) th.addEventListener("click", function () { _onSortClick(_SORT_COLS[id]); });
    });
    _updateSortHeaders();

    /* ── Picture modal ──────────────────────────────────────────────────── */
    var _picUrls   = [];
    var _picIndex  = 0;
    var _picModal  = null;
    var _picCache  = {};   /* channel id → urls array */

    var $picModalEl  = document.getElementById("pic-modal");
    var $picImg      = document.getElementById("pic-modal-img");
    var $picVideo    = document.getElementById("pic-modal-video");
    var $picTitle    = document.getElementById("pic-modal-title");
    var $picCounter  = document.getElementById("pic-modal-counter");
    var $picFooter   = document.getElementById("pic-modal-footer");
    var $picPrev     = document.getElementById("pic-modal-prev");
    var $picNext     = document.getElementById("pic-modal-next");

    if ($picModalEl && typeof bootstrap !== "undefined") {
        _picModal = new bootstrap.Modal($picModalEl);
    }

    function _normalizeItem(item) {
        // The pictures API returns {url, mime_type, thumbnail_url} objects.
        // Tolerate plain URL strings from legacy fallbacks.
        if (!item) return {url: "", mime_type: "", thumbnail_url: null};
        if (typeof item === "string") return {url: item, mime_type: "", thumbnail_url: null};
        return {
            url: item.url || "",
            mime_type: item.mime_type || "",
            thumbnail_url: item.thumbnail_url || null,
        };
    }

    function _renderItem(item) {
        var isVideo = item.mime_type.indexOf("video/") === 0;
        if (isVideo) {
            $picImg.style.display = "none";
            $picImg.src = "";
            $picVideo.style.display = "";
            $picVideo.src = item.url;
            if (item.thumbnail_url) $picVideo.setAttribute("poster", item.thumbnail_url);
            else $picVideo.removeAttribute("poster");
            $picVideo.play().catch(function () { /* autoplay may be blocked */ });
        } else {
            $picVideo.pause();
            $picVideo.removeAttribute("src");
            $picVideo.style.display = "none";
            $picImg.style.display = "";
            $picImg.src = item.url;
        }
    }

    function _showPic(index) {
        _picIndex = index;
        _renderItem(_normalizeItem(_picUrls[_picIndex]));
        $picCounter.textContent = (_picUrls.length > 1) ? (_picIndex + 1) + " / " + _picUrls.length : "";
        $picPrev.disabled = _picIndex === 0;
        $picNext.disabled = _picIndex === _picUrls.length - 1;
        $picFooter.style.display = _picUrls.length > 1 ? "" : "none";
    }

    function _chSeed(ch) {
        return {
            url: ch.profile_picture_url,
            mime_type: ch.profile_picture_mime_type || "",
            thumbnail_url: ch.profile_picture_thumbnail_url || null,
        };
    }

    function _openPicModal(ch) {
        if (!_picModal) return;
        $picTitle.textContent = ch.title || ("Channel #" + ch.id);
        $picCounter.textContent = "";
        $picFooter.style.display = "none";
        _picUrls = [_chSeed(ch)];
        _renderItem(_normalizeItem(_picUrls[0]));  /* show channel avatar immediately */
        _picModal.show();

        if (_picCache[ch.id]) {
            _picUrls = _picCache[ch.id];
            _showPic(0);
            return;
        }
        apiFetch("/manage/api/channels/" + ch.id + "/pictures/")
            .then(function (data) {
                _picCache[ch.id] = data.pictures.length ? data.pictures : [_chSeed(ch)];
                _picUrls = _picCache[ch.id];
                _showPic(0);
            })
            .catch(function () {
                _picUrls = [_chSeed(ch)];
                _showPic(0);
            });
    }

    $picPrev.addEventListener("click", function () { if (_picIndex > 0) _showPic(_picIndex - 1); });
    $picNext.addEventListener("click", function () { if (_picIndex < _picUrls.length - 1) _showPic(_picIndex + 1); });
    $picModalEl.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft")  { if (_picIndex > 0) _showPic(_picIndex - 1); }
        if (e.key === "ArrowRight") { if (_picIndex < _picUrls.length - 1) _showPic(_picIndex + 1); }
    });
    $picModalEl.addEventListener("hidden.bs.modal", function () {
        $picVideo.pause();
        $picVideo.removeAttribute("src");
        $picVideo.load();
    });
})();
