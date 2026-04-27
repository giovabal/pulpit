(function () {
    "use strict";

    var API_CH  = "/manage/api/channels/" + CHANNEL_PK + "/";
    var API_ORG = "/manage/api/organizations/?limit=500";
    var API_GRP = "/manage/api/groups/?limit=500";

    var $root = document.getElementById("bo-ch-update");

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
            var pic = document.createElement("img");
            pic.className = "bo-ch-update-pic"; pic.src = ch.profile_picture_url; pic.alt = "";
            titleWrap.appendChild(pic);
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

    Promise.all([
        apiFetch(API_CH),
        apiFetch(API_ORG),
        apiFetch(API_GRP),
    ]).then(function (res) {
        render(res[0], res[1].results, res[2].results);
    }).catch(function (e) {
        $root.innerHTML = '<p class="bo-empty">Error loading channel: ' + e.message + '</p>';
    });
})();
