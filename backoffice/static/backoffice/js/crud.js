/* Shared backoffice utilities */

var BACKOFFICE_PAGE_SIZE = 100;

function renderPagination(container, offset, total, pageSize, onPageChange) {
    container.innerHTML = "";
    if (total <= pageSize) return;
    var prevBtn = document.createElement("button"); prevBtn.textContent = "←";
    prevBtn.disabled = offset === 0;
    prevBtn.addEventListener("click", function () { onPageChange(Math.max(0, offset - pageSize)); });
    var nextBtn = document.createElement("button"); nextBtn.textContent = "→";
    nextBtn.disabled = offset + pageSize >= total;
    nextBtn.addEventListener("click", function () { onPageChange(offset + pageSize); });
    var info = document.createElement("span");
    var from = total ? offset + 1 : 0;
    var to = Math.min(offset + pageSize, total);
    info.textContent = from + "–" + to + " of " + total;
    container.appendChild(prevBtn);
    container.appendChild(info);
    container.appendChild(nextBtn);
}

function getCsrfToken() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
}

async function apiFetch(url, options) {
    options = options || {};
    var method = options.method || "GET";
    var body = options.body !== undefined ? options.body : null;

    var init = { method: method, headers: { "Content-Type": "application/json" } };
    if (method !== "GET" && method !== "HEAD") {
        init.headers["X-CSRFToken"] = getCsrfToken();
    }
    if (body !== null) {
        init.body = JSON.stringify(body);
    }

    var r = await fetch(url, init);
    if (!r.ok) {
        var msg = r.status + " " + r.statusText;
        try { var err = await r.json(); msg = err.detail || err.error || JSON.stringify(err); } catch (_) {}
        throw new Error(msg);
    }
    if (r.status === 204) return null;
    return r.json();
}

var _toastContainer = null;
function showToast(message, type) {
    type = type || "success";
    if (!_toastContainer) {
        _toastContainer = document.createElement("div");
        _toastContainer.className = "bo-toast-container";
        document.body.appendChild(_toastContainer);
    }
    var toast = document.createElement("div");
    toast.className = "bo-toast bo-toast--" + type;
    toast.textContent = message;
    _toastContainer.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 3200);
}

function confirmDelete(name) {
    return Promise.resolve(confirm('Delete "' + name + '"? This cannot be undone.'));
}

function fmtInt(n) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString();
}

function fmtDate(d) {
    if (!d) return "—";
    return d.slice(0, 10);
}

function makeDeleteBtn(title) {
    var btn = document.createElement("button");
    btn.className = "bo-btn bo-btn--icon bo-btn--danger";
    btn.title = "Delete";
    btn.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i>';
    return btn;
}

function makeEditBtn() {
    var btn = document.createElement("button");
    btn.className = "bo-btn bo-btn--icon";
    btn.title = "Edit";
    btn.innerHTML = '<i class="bi bi-pencil" aria-hidden="true"></i>';
    return btn;
}
