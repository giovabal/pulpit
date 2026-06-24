(function () {
    "use strict";

    var $root   = document.getElementById("bo-ch-update");
    var API_CH  = "/manage/api/channels/" + $root.dataset.channelPk + "/";
    var API_LABELS = "/manage/api/labels/?limit=500";
    var API_LABELGROUPS = "/manage/api/label-groups/?limit=500";
    var API_SRC = "/manage/api/sources/?limit=500";
    var _picUrls  = [];
    var _picIndex = 0;
    var _picModal = null;
    var $picModalEl, $picImg, $picVideo, $picCounter, $picFooter, $picPrev, $picNext;

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
        $picCounter.textContent = _picUrls.length > 1 ? (_picIndex + 1) + " / " + _picUrls.length : "";
        $picPrev.disabled = _picIndex === 0;
        $picNext.disabled = _picIndex === _picUrls.length - 1;
        $picFooter.style.display = _picUrls.length > 1 ? "" : "none";
    }

    function _openPicModal() {
        if (_picModal) _picModal.show();
    }

    function _buildPicModal() {
        $picModalEl = document.createElement("div");
        $picModalEl.className = "modal fade"; $picModalEl.tabIndex = -1; $picModalEl.setAttribute("aria-hidden", "true");
        $picModalEl.innerHTML =
            '<div class="modal-dialog modal-dialog-centered">' +
              '<div class="modal-content">' +
                '<div class="modal-header py-2">' +
                  '<span class="modal-title fw-semibold" id="cu-pic-title"></span>' +
                  '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
                '</div>' +
                '<div class="modal-body text-center p-3">' +
                  '<img id="cu-pic-img" src="" alt="" class="bo-pic-modal-img">' +
                  '<video id="cu-pic-video" class="bo-pic-modal-img" controls autoplay loop muted playsinline style="display:none"></video>' +
                '</div>' +
                '<div class="modal-footer py-2 justify-content-between" id="cu-pic-footer">' +
                  '<button class="bo-btn bo-btn--sm" id="cu-pic-prev">←</button>' +
                  '<span class="text-muted small" id="cu-pic-counter"></span>' +
                  '<button class="bo-btn bo-btn--sm" id="cu-pic-next">→</button>' +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild($picModalEl);
        $picImg     = document.getElementById("cu-pic-img");
        $picVideo   = document.getElementById("cu-pic-video");
        $picCounter = document.getElementById("cu-pic-counter");
        $picFooter  = document.getElementById("cu-pic-footer");
        $picPrev    = document.getElementById("cu-pic-prev");
        $picNext    = document.getElementById("cu-pic-next");
        $picPrev.addEventListener("click", function () { if (_picIndex > 0) _showPic(_picIndex - 1); });
        $picNext.addEventListener("click", function () { if (_picIndex < _picUrls.length - 1) _showPic(_picIndex + 1); });
        $picModalEl.addEventListener("keydown", function (e) {
            if (e.key === "ArrowLeft" && _picIndex > 0) _showPic(_picIndex - 1);
            if (e.key === "ArrowRight" && _picIndex < _picUrls.length - 1) _showPic(_picIndex + 1);
        });
        $picModalEl.addEventListener("hidden.bs.modal", function () {
            $picVideo.pause();
            $picVideo.removeAttribute("src");
            $picVideo.load();
        });
        if (typeof bootstrap !== "undefined") _picModal = new bootstrap.Modal($picModalEl);
    }

    function render(ch, labels, labelGroups, channelSources) {
        $root.innerHTML = "";

        /* ── Back link + title ────────────────────────────────────── */
        var header = document.createElement("div"); header.className = "bo-ch-update-header";
        var back = document.createElement("a");
        back.href = "/manage/channels/"; back.className = "bo-btn bo-btn--ghost bo-btn--sm";
        back.innerHTML = '<i class="bi bi-arrow-left me-1"></i>Channels';
        header.appendChild(back);

        var titleWrap = document.createElement("div"); titleWrap.className = "bo-ch-update-title";
        var pic = makeProfilePicEl(ch, "bo-ch-update-pic bo-ch-pic--clickable");
        if (pic) {
            var picWrap = document.createElement("div"); picWrap.className = "bo-ch-update-pic-wrap";
            pic.addEventListener("click", function () {
                _showPic(0);
                _openPicModal();
            });
            picWrap.appendChild(pic);
            /* seed with the channel's current picture so the modal can open
             * before the API responds (or if it fails) */
            var _seed = [{
                url: ch.profile_picture_url,
                mime_type: ch.profile_picture_mime_type || "",
                thumbnail_url: ch.profile_picture_thumbnail_url || null,
            }];
            _picUrls = _seed;
            /* fetch all pictures to show count badge */
            apiFetch("/manage/api/channels/" + ch.id + "/pictures/").then(function (data) {
                _picUrls = data.pictures.length ? data.pictures : _seed;
                if (_picUrls.length > 1) {
                    var badge = document.createElement("span"); badge.className = "bo-pic-badge";
                    badge.textContent = _picUrls.length;
                    picWrap.appendChild(badge);
                }
            }).catch(function () { _picUrls = _seed; });
            titleWrap.appendChild(picWrap);
        }
        var nameBlock = document.createElement("div");
        var h2 = document.createElement("h2"); h2.className = "bo-ch-update-name";
        h2.textContent = ch.title || ("Channel #" + ch.id);
        nameBlock.appendChild(h2);
        if (ch.username) {
            var usernameLink = document.createElement("a");
            usernameLink.className = "bo-ch-username";
            usernameLink.href = "https://t.me/" + ch.username;
            usernameLink.target = "_blank"; usernameLink.rel = "noopener noreferrer";
            usernameLink.textContent = "@" + ch.username;
            nameBlock.appendChild(usernameLink);
        }
        titleWrap.appendChild(nameBlock);
        header.appendChild(titleWrap);
        $root.appendChild(header);

        /* ── Info row ─────────────────────────────────────────────── */
        var info = document.createElement("div"); info.className = "bo-ch-update-info";
        [
            ["Type",        ch.channel_type || "—"],
            ["Subscribers", fmtInt(ch.participants_count)],
            ["In-degree",   fmtInt(ch.in_degree)],
            ["Out-degree",  fmtInt(ch.out_degree)],
            ["Created",     fmtDate(ch.date)],
            ["DB id",       String(ch.id)],
        ].forEach(function (pair) {
            var cell = document.createElement("div"); cell.className = "bo-info-cell";
            var lbl = document.createElement("div"); lbl.className = "bo-info-label"; lbl.textContent = pair[0];
            var val = document.createElement("div"); val.className = "bo-info-value"; val.textContent = pair[1];
            cell.appendChild(lbl); cell.appendChild(val); info.appendChild(cell);
        });
        $root.appendChild(info);

        /* ── Edit form ────────────────────────────────────────────── */
        var form = document.createElement("form"); form.className = "bo-ch-update-form";
        form.addEventListener("submit", function (e) { e.preventDefault(); saveChannel(ch, form); });

        /* Label periods — one section per label group (partition groups: one label at a time) */
        var fgLabels = makeFieldGroup("Labels");
        var labelsHelp = document.createElement("div");
        labelsHelp.className = "bo-field-help text-muted small mb-2";
        labelsHelp.textContent =
            "Attribute the channel to labels over optional date ranges (empty start = from creation, " +
            "empty end = to present). In a partition group a channel holds one label at a time, so its " +
            "periods there must not overlap; other groups allow concurrent labels.";
        fgLabels.appendChild(labelsHelp);

        /* group id → its labels (for the per-section <select>) */
        var labelsByGroup = {};
        labels.forEach(function (l) {
            (labelsByGroup[l.group_id] = labelsByGroup[l.group_id] || []).push(l);
        });

        function addLabelRow(rowsWrap, group, channelLabel) {
            var row = document.createElement("div");
            row.className = "bo-period-row d-flex gap-2 align-items-center mb-2";
            row.dataset.groupId = group.id;
            row.dataset.partition = group.is_partition ? "1" : "";
            var sel = document.createElement("select"); sel.className = "bo-select bo-period-label";
            (labelsByGroup[group.id] || []).forEach(function (l) {
                var opt = new Option(l.name, l.id);
                if (channelLabel && l.id === channelLabel.label_id) opt.selected = true;
                sel.appendChild(opt);
            });
            var start = document.createElement("input");
            start.type = "date"; start.className = "bo-input bo-period-start";
            if (channelLabel && channelLabel.start) start.value = channelLabel.start;
            var sep = document.createElement("span"); sep.textContent = "→"; sep.className = "text-muted";
            var end = document.createElement("input");
            end.type = "date"; end.className = "bo-input bo-period-end";
            if (channelLabel && channelLabel.end) end.value = channelLabel.end;
            var rm = document.createElement("button");
            rm.type = "button"; rm.className = "bo-btn bo-btn--ghost bo-btn--sm";
            rm.innerHTML = '<i class="bi bi-trash"></i>';
            rm.addEventListener("click", function () { rowsWrap.removeChild(row); });
            row.appendChild(sel); row.appendChild(start); row.appendChild(sep); row.appendChild(end); row.appendChild(rm);
            rowsWrap.appendChild(row);
        }

        /* Groups already ordered by the API (primary first, then alphabetical). */
        labelGroups.forEach(function (group) {
            if (!(labelsByGroup[group.id] || []).length) return;  /* no labels to assign in this group */
            var section = document.createElement("div"); section.className = "bo-label-group-section mb-3";
            var head = document.createElement("div");
            head.className = "bo-label-group-head d-flex align-items-center gap-2 mb-1";
            var nameEl = document.createElement("span"); nameEl.className = "fw-semibold"; nameEl.textContent = group.name;
            var kindEl = document.createElement("span"); kindEl.className = "text-muted small";
            kindEl.textContent = group.is_partition ? "(one at a time)" : "(multiple allowed)";
            head.appendChild(nameEl); head.appendChild(kindEl); section.appendChild(head);
            var rowsWrap = document.createElement("div"); rowsWrap.className = "bo-label-group-rows";
            section.appendChild(rowsWrap);
            (ch.labels || []).filter(function (cl) { return cl.group_id === group.id; }).forEach(function (cl) {
                addLabelRow(rowsWrap, group, cl);
            });
            var addBtn = document.createElement("button");
            addBtn.type = "button"; addBtn.className = "bo-btn bo-btn--ghost bo-btn--sm";
            addBtn.innerHTML = '<i class="bi bi-plus me-1"></i>Add period';
            addBtn.addEventListener("click", function () { addLabelRow(rowsWrap, group, null); });
            section.appendChild(addBtn);
            fgLabels.appendChild(section);
        });
        form.appendChild(fgLabels);

        /* Sources */
        var fgSrc = makeFieldGroup("Sources");
        var srcWrap = document.createElement("div"); srcWrap.className = "bo-ch-update-sources";
        channelSources.forEach(function (s) {
            var lbl = document.createElement("label"); lbl.className = "bo-check-label";
            var chk = document.createElement("input"); chk.type = "checkbox"; chk.value = s.id;
            chk.name = "source_ids";
            if ((ch.source_ids || []).indexOf(s.id) !== -1) chk.checked = true;
            lbl.appendChild(chk); lbl.appendChild(document.createTextNode(" " + s.name));
            srcWrap.appendChild(lbl);
        });
        fgSrc.appendChild(srcWrap); form.appendChild(fgSrc);

        /* Flags */
        var fgFlags = makeFieldGroup("Flags");
        var flagsWrap = document.createElement("div"); flagsWrap.className = "d-flex gap-4";
        [["is_lost", "Lost"], ["is_private", "Private"]].forEach(function (pair) {
            var lbl = document.createElement("label"); lbl.className = "bo-check-label";
            var chk = document.createElement("input"); chk.type = "checkbox"; chk.name = pair[0];
            if (ch[pair[0]]) chk.checked = true;
            lbl.appendChild(chk); lbl.appendChild(document.createTextNode(" " + pair[1]));
            flagsWrap.appendChild(lbl);
        });
        fgFlags.appendChild(flagsWrap); form.appendChild(fgFlags);

        /* To-inspect */
        var fgInspect = makeFieldGroup("Inspect");
        var inspectWrap = document.createElement("label"); inspectWrap.className = "bo-check-label";
        var chkInspect = document.createElement("input");
        chkInspect.type = "checkbox"; chkInspect.name = "to_inspect";
        if (ch.to_inspect) chkInspect.checked = true;
        inspectWrap.appendChild(chkInspect);
        inspectWrap.appendChild(document.createTextNode(" Crawl this channel even when it isn't in target (for discovery; excluded from analysis)"));
        fgInspect.appendChild(inspectWrap); form.appendChild(fgInspect);

        /* Buttons */
        var btnRow = document.createElement("div"); btnRow.className = "bo-ch-update-btns";
        var saveBtn = document.createElement("button"); saveBtn.type = "submit"; saveBtn.className = "bo-btn";
        saveBtn.innerHTML = '<i class="bi bi-check me-1"></i>Save';
        var cancelBtn = document.createElement("a"); cancelBtn.href = "/manage/channels/"; cancelBtn.className = "bo-btn bo-btn--ghost";
        cancelBtn.textContent = "Cancel";
        btnRow.appendChild(saveBtn); btnRow.appendChild(cancelBtn);
        if (ch.detail_url) {
            var detailLink = document.createElement("a");
            detailLink.href = ch.detail_url;
            detailLink.className = "bo-btn bo-btn--ghost";
            detailLink.style.marginLeft = "auto";
            detailLink.innerHTML = '<i class="bi bi-eye me-1" aria-hidden="true"></i>View detail';
            btnRow.appendChild(detailLink);
        }
        form.appendChild(btnRow);

        $root.appendChild(form);
    }

    function makeFieldGroup(label) {
        var fg = document.createElement("div"); fg.className = "bo-field-group";
        var lbl = document.createElement("label"); lbl.className = "bo-field-label"; lbl.textContent = label;
        fg.appendChild(lbl);
        return fg;
    }

    function collectLabels(form) {
        return Array.from(form.querySelectorAll(".bo-period-row")).map(function (row) {
            return {
                label_id: parseInt(row.querySelector(".bo-period-label").value, 10),
                start: row.querySelector(".bo-period-start").value || null,
                end: row.querySelector(".bo-period-end").value || null,
                group_id: parseInt(row.dataset.groupId, 10),
                partition: row.dataset.partition === "1",
            };
        });
    }

    function validateLabels(rows) {
        var LO = "0000-01-01", HI = "9999-12-31";
        for (var i = 0; i < rows.length; i++) {
            if (!rows[i].label_id) return "Pick a label for every period row.";
            if (rows[i].start && rows[i].end && rows[i].start > rows[i].end) {
                return "A period's end date is before its start date.";
            }
        }
        /* Overlap is constrained only within a partition group. */
        for (var a = 0; a < rows.length; a++) {
            if (!rows[a].partition) continue;
            for (var b = a + 1; b < rows.length; b++) {
                if (rows[b].group_id !== rows[a].group_id) continue;
                var s1 = rows[a].start || LO, e1 = rows[a].end || HI;
                var s2 = rows[b].start || LO, e2 = rows[b].end || HI;
                if (s1 <= e2 && s2 <= e1) return "Label periods within a partition group must not overlap.";
            }
        }
        return null;
    }

    function saveChannel(ch, form) {
        var sourceIds = Array.from(form.querySelectorAll("input[name=source_ids]:checked")).map(function (el) { return parseInt(el.value, 10); });
        var rows = collectLabels(form);
        var lerr = validateLabels(rows);
        if (lerr) { showToast(lerr, "error"); return; }
        // Single atomic save: the flags, sources, and label periods are all replaced inside one
        // server-side transaction, so a label failure can never leave the flags/sources committed
        // while the toast says the save failed. On error apiFetch rejects and nothing is persisted.
        apiFetch("/manage/api/channels/" + ch.id + "/replace-labels/", {
            method: "POST",
            body: {
                source_ids: sourceIds,
                is_lost: form.querySelector("input[name=is_lost]").checked,
                is_private: form.querySelector("input[name=is_private]").checked,
                to_inspect: form.querySelector("input[name=to_inspect]").checked,
                periods: rows.map(function (r) {
                    return { label_id: r.label_id, start: r.start, end: r.end };
                }),
            },
        })
            .then(function (data) { ch.labels = data.labels || []; showToast("Saved."); })
            .catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    _buildPicModal();

    Promise.all([
        apiFetch(API_CH),
        apiFetch(API_LABELS),
        apiFetch(API_LABELGROUPS),
        apiFetch(API_SRC),
    ]).then(function (res) {
        var ch = res[0];
        /* set modal title */
        var titleEl = document.getElementById("cu-pic-title");
        if (titleEl) titleEl.textContent = ch.title || ("Channel #" + ch.id);
        render(ch, res[1].results, res[2].results, res[3].results);
    }).catch(function (e) {
        var p = document.createElement('p');
        p.className = 'bo-empty';
        p.textContent = 'Error loading channel: ' + e.message;
        $root.appendChild(p);
    });
})();
