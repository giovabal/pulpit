/* Manage → Commenters: review the accounts behind the stored replies and decide which ones the
   audience statistics leave out (webapp/commenters.py). Every change saves at once
   (PATCH /manage/api/commenters/<sender_id>/ with {decision} or {note}). */
(function() {
    "use strict";
    var API = "/manage/api/commenters/";
    var DECISIONS = [
        ["auto", "Automatic"],
        ["exclude", "Exclude"],
        ["keep", "Keep"]
    ];
    var _offset = 0;
    var _total = 0;
    var _searchTimer = null;

    var $tbody = document.getElementById("cm-tbody");
    var $count = document.getElementById("cm-count");
    var $search = document.getElementById("cm-search");
    var $status = document.getElementById("cm-status");
    var $paginTop = document.getElementById("cm-pagination-top");
    var $paginBottom = document.getElementById("cm-pagination-bottom");

    function cell(tr, content, className) {
        var td = document.createElement("td");
        if (className) td.className = className;
        if (content instanceof Node) td.appendChild(content);
        else if (content !== undefined) td.textContent = content;
        tr.appendChild(td);
        return td;
    }

    function displayName(account) {
        return account.name || "Account " + account.sender_id;
    }

    function save(account, changes, done) {
        apiFetch(API + account.sender_id + "/", { method: "PATCH", body: changes })
            .then(function(updated) {
                Object.assign(account, updated);
                showToast("Saved.");
                if (done) done(true);
            })
            .catch(function(e) {
                showToast("Error: " + e.message, "error");
                if (done) done(false);
            });
    }

    function accountCell(account) {
        var wrap = document.createElement("span");
        wrap.appendChild(document.createTextNode(displayName(account)));
        var id = document.createElement("div");
        id.className = "text-muted small";
        id.textContent = "id " + account.sender_id;
        wrap.appendChild(id);
        return wrap;
    }

    function badge(text, modifier, title) {
        var b = document.createElement("span");
        b.className = "bo-badge" + (modifier ? " bo-badge--" + modifier : "");
        b.textContent = text;
        if (title) b.title = title;
        return b;
    }

    function statusCell(account) {
        var wrap = document.createElement("span");
        wrap.className = "bo-commenter-status";
        wrap.appendChild(account.excluded ? badge("Left out", "danger") : badge("Kept"));
        account.reasons.forEach(function(reason) {
            wrap.appendChild(document.createTextNode(" "));
            wrap.appendChild(badge(reason.label, null, "Flagged automatically"));
        });
        if (account.telegram_bot === null) {
            var unknown = document.createElement("div");
            unknown.className = "text-muted small";
            unknown.textContent = "bot flag not captured";
            wrap.appendChild(unknown);
        }
        return wrap;
    }

    function activeRange(account) {
        if (!account.first) return "—";
        var first = fmtDate(account.first);
        var last = fmtDate(account.last);
        return first === last ? first : first + " – " + last;
    }

    function decisionSelect(account, row) {
        var sel = document.createElement("select");
        sel.className = "bo-select";
        sel.setAttribute("aria-label", "Decision on " + displayName(account));
        DECISIONS.forEach(function(d) {
            var o = document.createElement("option");
            o.value = d[0];
            o.textContent = d[1];
            sel.appendChild(o);
        });
        sel.value = account.decision;
        sel.addEventListener("change", function() {
            sel.disabled = true;
            save(account, { decision: sel.value }, function(ok) {
                sel.disabled = false;
                if (!ok) {
                    sel.value = account.decision;
                    return;
                }
                row.replaceWith(renderRow(account));
            });
        });
        return sel;
    }

    function noteInput(account) {
        var input = document.createElement("input");
        input.className = "bo-input bo-input--wide";
        input.value = account.note || "";
        input.placeholder = "Note (optional)";
        input.setAttribute("aria-label", "Note on " + displayName(account));
        input.addEventListener("change", function() {
            save(account, { note: input.value.trim() });
        });
        return input;
    }

    function renderRow(account) {
        var tr = document.createElement("tr");
        cell(tr, accountCell(account));
        cell(tr, fmtInt(account.comments), "bo-td--num");
        cell(tr, fmtInt(account.posts), "bo-td--num");
        cell(tr, fmtInt(account.channels), "bo-td--num");
        cell(tr, fmtInt(account.max_per_post), "bo-td--num");
        cell(tr, Math.round(account.no_text_share * 100) + "%", "bo-td--num");
        cell(tr, activeRange(account));
        cell(tr, statusCell(account));
        cell(tr, decisionSelect(account, tr));
        cell(tr, noteInput(account));
        return tr;
    }

    function load() {
        var params = new URLSearchParams({ limit: BACKOFFICE_PAGE_SIZE, offset: _offset });
        if ($search.value.trim()) params.set("q", $search.value.trim());
        if ($status.value) params.set("status", $status.value);
        apiFetch(API + "?" + params.toString())
            .then(function(data) {
                _total = data.count;
                $tbody.innerHTML = "";
                if (!data.results.length) {
                    $tbody.innerHTML = '<tr><td colspan="10" class="bo-empty">No account matches. Accounts appear as the crawler fetches replies.</td></tr>';
                }
                data.results.forEach(function(account) {
                    $tbody.appendChild(renderRow(account));
                });
                renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, goTo);
                renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, goTo);
                $count.textContent = fmtInt(_total) + " account" + (_total !== 1 ? "s" : "");
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
    $status.addEventListener("change", function() { goTo(0); });

    load();
})();
