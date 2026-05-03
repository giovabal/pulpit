(function () {
    "use strict";

    var API_CH  = "/manage/api/channels/" + CHANNEL_PK + "/";
    var API_ORG = "/manage/api/organizations/?limit=500";
    var API_GRP = "/manage/api/groups/?limit=500";

    var $root = document.getElementById("bo-ch-update");
    var _picUrls  = [];
    var _picIndex = 0;
    var _picModal = null;
    var $picModalEl, $picImg, $picCounter, $picFooter, $picPrev, $picNext;

    function _showPic(index) {
        _picIndex = index;
        $picImg.src = _picUrls[_picIndex];
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
                '<div class="modal-body text-center p-3"><img id="cu-pic-img" src="" alt="" class="bo-pic-modal-img"></div>' +
                '<div class="modal-footer py-2 justify-content-between" id="cu-pic-footer">' +
                  '<button class="bo-btn bo-btn--sm" id="cu-pic-prev">←</button>' +
                  '<span class="text-muted small" id="cu-pic-counter"></span>' +
                  '<button class="bo-btn bo-btn--sm" id="cu-pic-next">→</button>' +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild($picModalEl);
        $picImg     = document.getElementById("cu-pic-img");
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
        if (typeof bootstrap !== "undefined") _picModal = new bootstrap.Modal($picModalEl);
    }

    function render(ch, orgs, groups) {
        $root.innerHTML = "";

        /* ── Back link + title ────────────────────────────────────── */
        var header = document.createElement("div"); header.className = "bo-ch-update-header";
        var back = document.createElement("a");
        back.href = "/manage/channels/"; back.className = "bo-btn bo-btn--ghost bo-btn--sm";
        back.innerHTML = '<i class="bi bi-arrow-left me-1"></i>Channels';
        header.appendChild(back);

        var titleWrap = document.createElement("div"); titleWrap.className = "bo-ch-update-title";
        if (ch.profile_picture_url) {
            var picWrap = document.createElement("div"); picWrap.className = "bo-ch-update-pic-wrap";
            var pic = document.createElement("img");
            pic.className = "bo-ch-update-pic bo-ch-pic--clickable"; pic.src = ch.profile_picture_url; pic.alt = "";
            pic.addEventListener("click", function () {
                _showPic(0);
                _openPicModal();
            });
            picWrap.appendChild(pic);
            /* fetch all pictures to show count badge */
            apiFetch("/manage/api/channels/" + ch.id + "/pictures/").then(function (data) {
                _picUrls = data.pictures.length ? data.pictures : [ch.profile_picture_url];
                if (_picUrls.length > 1) {
                    var badge = document.createElement("span"); badge.className = "bo-pic-badge";
                    badge.textContent = _picUrls.length;
                    picWrap.appendChild(badge);
                }
            }).catch(function () { _picUrls = [ch.profile_picture_url]; });
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
        form.addEventListener("submit", function (e) { e.preventDefault(); saveChannel(ch, form, orgs, groups); });

        /* Organization */
        var fgOrg = makeFieldGroup("Organization");
        var selOrg = document.createElement("select"); selOrg.name = "organization_id"; selOrg.className = "bo-select";
        selOrg.appendChild(new Option("— unassigned —", ""));
        orgs.forEach(function (o) {
            var opt = new Option(o.name, o.id);
            if (o.id === ch.organization_id) opt.selected = true;
            selOrg.appendChild(opt);
        });
        fgOrg.appendChild(selOrg); form.appendChild(fgOrg);

        /* Groups */
        var fgGrp = makeFieldGroup("Groups");
        var grpWrap = document.createElement("div"); grpWrap.className = "bo-ch-update-groups";
        groups.forEach(function (g) {
            var lbl = document.createElement("label"); lbl.className = "bo-check-label";
            var chk = document.createElement("input"); chk.type = "checkbox"; chk.value = g.id;
            chk.name = "group_ids";
            if ((ch.group_ids || []).indexOf(g.id) !== -1) chk.checked = true;
            lbl.appendChild(chk); lbl.appendChild(document.createTextNode(" " + g.name));
            grpWrap.appendChild(lbl);
        });
        fgGrp.appendChild(grpWrap); form.appendChild(fgGrp);

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

        /* Buttons */
        var btnRow = document.createElement("div"); btnRow.className = "bo-ch-update-btns";
        var saveBtn = document.createElement("button"); saveBtn.type = "submit"; saveBtn.className = "bo-btn";
        saveBtn.innerHTML = '<i class="bi bi-check me-1"></i>Save';
        var cancelBtn = document.createElement("a"); cancelBtn.href = "/manage/channels/"; cancelBtn.className = "bo-btn bo-btn--ghost";
        cancelBtn.textContent = "Cancel";
        btnRow.appendChild(saveBtn); btnRow.appendChild(cancelBtn);
        form.appendChild(btnRow);

        $root.appendChild(form);
    }

    function makeFieldGroup(label) {
        var fg = document.createElement("div"); fg.className = "bo-field-group";
        var lbl = document.createElement("label"); lbl.className = "bo-field-label"; lbl.textContent = label;
        fg.appendChild(lbl);
        return fg;
    }

    function saveChannel(ch, form, orgs, groups) {
        var fd = new FormData(form);
        var orgVal = fd.get("organization_id");
        var groupIds = Array.from(form.querySelectorAll("input[name=group_ids]:checked")).map(function (el) { return parseInt(el.value); });
        var body = {
            organization_id: orgVal ? parseInt(orgVal) : null,
            group_ids: groupIds,
            is_lost: form.querySelector("input[name=is_lost]").checked,
            is_private: form.querySelector("input[name=is_private]").checked,
        };
        apiFetch(API_CH, { method: "PATCH", body: body })
            .then(function () { showToast("Saved."); })
            .catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    _buildPicModal();

    Promise.all([
        apiFetch(API_CH),
        apiFetch(API_ORG),
        apiFetch(API_GRP),
    ]).then(function (res) {
        var ch = res[0];
        /* set modal title */
        var titleEl = document.getElementById("cu-pic-title");
        if (titleEl) titleEl.textContent = ch.title || ("Channel #" + ch.id);
        render(ch, res[1].results, res[2].results);
    }).catch(function (e) {
        var p = document.createElement('p');
        p.className = 'bo-empty';
        p.textContent = 'Error loading channel: ' + e.message;
        $root.innerHTML = '';
        $root.appendChild(p);
    });
})();
