/* Manage → Emoji: mark custom emoji packs in target and annotate them.
   Every change saves at once (PATCH /manage/api/emoji-packs/<id>/). The previews are
   server-rendered custom emoji (webapp/templatetags/custom_emoji.py), animated by
   webapp/js/custom_emoji.js, which the base template loads. */
(function() {
    "use strict";
    var API = "/manage/api/emoji-packs/";
    var PACK_URL = window.EMOJI_PACK_URL || "/channels/emoji-packs/0/";
    var _offset = 0;
    var _total = 0;
    var _searchTimer = null;

    var $tbody = document.getElementById("ep-tbody");
    var $count = document.getElementById("ep-count");
    var $search = document.getElementById("ep-search");
    var $target = document.getElementById("ep-target");
    var $paginTop = document.getElementById("ep-pagination-top");
    var $paginBottom = document.getElementById("ep-pagination-bottom");

    function cell(tr, content, className) {
        var td = document.createElement("td");
        if (className) td.className = className;
        if (content instanceof Node) td.appendChild(content);
        else if (content !== undefined) td.textContent = content;
        tr.appendChild(td);
        return td;
    }

    function save(pack, changes, done) {
        apiFetch(API + pack.id + "/", { method: "PATCH", body: changes })
            .then(function(updated) {
                Object.assign(pack, updated);
                showToast("Saved.");
                if (done) done(true);
            })
            .catch(function(e) {
                showToast("Error: " + e.message, "error");
                if (done) done(false);
            });
    }

    function packLink(pack) {
        var wrap = document.createElement("span");
        var a = document.createElement("a");
        a.href = PACK_URL.replace(/0\/$/, pack.id + "/");
        a.textContent = pack.display_title;
        a.title = "Usage of this pack";
        wrap.appendChild(a);
        if (pack.telegram_url) {
            var tg = document.createElement("a");
            tg.href = pack.telegram_url;
            tg.target = "_blank";
            tg.rel = "noopener noreferrer";
            tg.className = "ms-2";
            tg.title = "Open the pack on Telegram";
            tg.setAttribute("aria-label", "Open " + pack.display_title + " on Telegram");
            tg.innerHTML = '<i class="bi bi-telegram" aria-hidden="true"></i>';
            wrap.appendChild(tg);
        }
        if (pack.group_channels && pack.group_channels.length) {
            var groups = document.createElement("div");
            groups.className = "text-muted small";
            groups.appendChild(document.createTextNode("Group pack of "));
            pack.group_channels.forEach(function(group, i) {
                if (i) groups.appendChild(document.createTextNode(", "));
                var g = document.createElement("a");
                g.href = group.url;
                g.textContent = group.title;
                groups.appendChild(g);
            });
            wrap.appendChild(groups);
        }
        if (pack.is_unavailable) {
            var gone = document.createElement("span");
            gone.className = "text-muted small ms-2";
            gone.textContent = "no longer on Telegram";
            wrap.appendChild(gone);
        }
        return wrap;
    }

    function targetToggle(pack) {
        var label = document.createElement("label");
        label.className = "bo-check-label";
        var box = document.createElement("input");
        box.type = "checkbox";
        box.checked = pack.is_in_target;
        box.setAttribute("aria-label", "In target: " + pack.display_title);
        box.addEventListener("change", function() {
            box.disabled = true;
            save(pack, { is_in_target: box.checked }, function(ok) {
                box.disabled = false;
                if (!ok) box.checked = pack.is_in_target;
            });
        });
        label.appendChild(box);
        label.appendChild(document.createTextNode("In target"));
        return label;
    }

    function noteInput(pack) {
        var input = document.createElement("input");
        input.className = "bo-input bo-input--wide";
        input.value = pack.note || "";
        input.placeholder = "Note (optional)";
        input.setAttribute("aria-label", "Note on " + pack.display_title);
        input.addEventListener("change", function() {
            save(pack, { note: input.value.trim() });
        });
        return input;
    }

    function renderRow(pack) {
        var tr = document.createElement("tr");
        var preview = document.createElement("span");
        preview.className = "bo-emoji-preview";
        preview.innerHTML = pack.preview_html;
        cell(tr, preview);
        cell(tr, packLink(pack));
        cell(tr, pack.short_name || "—");
        cell(tr, fmtInt(pack.emoji_used), "bo-td--num");
        cell(tr, fmtInt(pack.uses), "bo-td--num");
        cell(tr, fmtInt(pack.channels), "bo-td--num");
        cell(tr, targetToggle(pack));
        cell(tr, noteInput(pack));
        return tr;
    }

    function load() {
        var params = new URLSearchParams({ limit: BACKOFFICE_PAGE_SIZE, offset: _offset });
        if ($search.value.trim()) params.set("q", $search.value.trim());
        if ($target.value) params.set("target", $target.value);
        apiFetch(API + "?" + params.toString())
            .then(function(data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) {
                    $tbody.innerHTML = '<tr><td colspan="8" class="bo-empty">No pack matches. Packs appear as the crawler records custom emoji.</td></tr>';
                }
                data.results.forEach(function(pack) {
                    $tbody.appendChild(renderRow(pack));
                });
                if (window.PulpitCustomEmoji) window.PulpitCustomEmoji.scan($tbody);
                renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, goTo);
                renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, goTo);
                $count.textContent = fmtInt(_total) + " pack" + (_total !== 1 ? "s" : "");
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
    $target.addEventListener("change", function() { goTo(0); });

    load();
})();
