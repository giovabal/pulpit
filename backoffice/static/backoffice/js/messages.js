(function () {
    "use strict";
    var API = "/manage/api/messages/";
    var API_CHANNELS = "/manage/api/channels/";
    var _offset = 0;
    var _total  = 0;
    var _searchTimer = null;

    var $tbody       = document.getElementById("msg-tbody");
    var $count       = document.getElementById("msg-count");
    var $paginTop    = document.getElementById("msg-pagination-top");
    var $paginBottom = document.getElementById("msg-pagination-bottom");
    var $channelFilter = document.getElementById("msg-channel-filter");
    var $fwdFilter   = document.getElementById("msg-fwd-filter");
    var $search      = document.getElementById("msg-search");

    function _goToPage(offset) { _offset = offset; loadMessages(); }

    function _renderPagination() {
        renderPagination($paginTop, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        renderPagination($paginBottom, _offset, _total, BACKOFFICE_PAGE_SIZE, _goToPage);
        $count.textContent = fmtInt(_total) + " message" + (_total !== 1 ? "s" : "");
    }

    function renderRow(msg) {
        var tr = document.createElement("tr");
        tr.dataset.id = msg.id;

        var tdCh = document.createElement("td"); tdCh.textContent = msg.channel_title || msg.channel_id; tr.appendChild(tdCh);
        var tdDt = document.createElement("td"); tdDt.textContent = fmtDate(msg.date); tr.appendChild(tdDt);

        var tdTx = document.createElement("td"); tdTx.className = "bo-td--text";
        var a = document.createElement("a");
        a.href = msg.telegram_url; a.target = "_blank"; a.rel = "noopener noreferrer";
        a.textContent = msg.text || "—";
        tdTx.appendChild(a); tr.appendChild(tdTx);

        var tdFw = document.createElement("td"); tdFw.textContent = msg.forwarded_from_title || "—"; tr.appendChild(tdFw);
        var tdVw = document.createElement("td"); tdVw.className = "bo-td--num"; tdVw.textContent = fmtInt(msg.views); tr.appendChild(tdVw);
        var tdFd = document.createElement("td"); tdFd.className = "bo-td--num"; tdFd.textContent = fmtInt(msg.forwards); tr.appendChild(tdFd);
        var tdMd = document.createElement("td"); tdMd.textContent = msg.media_type || "—"; tr.appendChild(tdMd);

        var tdAc = document.createElement("td");
        var delBtn = makeDeleteBtn("this message");
        delBtn.addEventListener("click", function () {
            confirmDelete("this message").then(function (ok) {
                if (!ok) return;
                apiFetch(API + msg.id + "/", { method: "DELETE" })
                    .then(function () { tr.remove(); _total--; _renderPagination(); showToast("Deleted."); })
                    .catch(function (e) { showToast("Error: " + e.message, "error"); });
            });
        });
        tdAc.appendChild(delBtn); tr.appendChild(tdAc);
        return tr;
    }

    function loadMessages() {
        var params = new URLSearchParams({ limit: BACKOFFICE_PAGE_SIZE, offset: _offset, ordering: "-date" });
        var ch = $channelFilter.value; if (ch) params.set("channel", ch);
        var q = $search.value.trim(); if (q) params.set("search", q);
        if ($fwdFilter.checked) params.set("forwarded", "1");
        apiFetch(API + "?" + params.toString()).then(function (data) {
            _total = data.count;
            $tbody.innerHTML = "";
            if (!data.results.length) { $tbody.innerHTML = '<tr><td colspan="8" class="bo-empty">No messages found.</td></tr>'; }
            else { data.results.forEach(function (m) { $tbody.appendChild(renderRow(m)); }); }
            _renderPagination();
        }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    function loadChannels() {
        apiFetch(API_CHANNELS + "?limit=2000&ordering=title").then(function (data) {
            data.results.forEach(function (ch) {
                $channelFilter.appendChild(new Option(ch.title || ch.username || ch.id, ch.id));
            });
        });
    }

    $channelFilter.addEventListener("change", function () { _offset = 0; loadMessages(); });
    $fwdFilter.addEventListener("change", function () { _offset = 0; loadMessages(); });
    $search.addEventListener("input", function () {
        clearTimeout(_searchTimer);
        _searchTimer = setTimeout(function () { _offset = 0; loadMessages(); }, 300);
    });

    loadChannels();
    loadMessages();
})();
