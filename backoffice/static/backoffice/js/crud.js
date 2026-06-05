/* Shared backoffice utilities */
/* exported BACKOFFICE_PAGE_SIZE, renderPagination, getCsrfToken, apiFetch, showToast, confirmDelete, fmtInt, fmtDate, makeDeleteBtn, makeEditBtn, makeProfilePicEl */

const BACKOFFICE_PAGE_SIZE = 100;

/* Digg-style page list: always the first and last page, a window of pages
   around the current one, and single "…" gaps. A gap of exactly one page is
   rendered as that page rather than an ellipsis, matching the server-side
   DiggPaginator on the public site. */
function _buildPageList(current, totalPages) {
    var WINDOW = 2; /* pages shown on each side of the current page */
    var show = {};
    show[1] = true;
    show[totalPages] = true;
    for (var p = current - WINDOW; p <= current + WINDOW; p++) {
        if (p >= 1 && p <= totalPages) show[p] = true;
    }
    var items = [];
    var prev = 0;
    for (var n = 1; n <= totalPages; n++) {
        if (!show[n]) continue;
        if (n - prev === 2) items.push(prev + 1);
        else if (n - prev > 1) items.push("…");
        items.push(n);
        prev = n;
    }
    return items;
}

function renderPagination(container, offset, total, pageSize, onPageChange) {
    container.innerHTML = "";
    if (total <= pageSize) return;

    var totalPages = Math.ceil(total / pageSize);
    var current = Math.min(totalPages, Math.floor(offset / pageSize) + 1);
    container.setAttribute("role", "navigation");
    container.setAttribute("aria-label", "Pagination");

    function navTo(page) {
        return function () { onPageChange((page - 1) * pageSize); };
    }

    var info = document.createElement("span");
    info.className = "bo-pagination-info";
    var from = offset + 1;
    var to = Math.min(offset + pageSize, total);
    info.textContent = from.toLocaleString() + "–" + to.toLocaleString() + " of " + total.toLocaleString();
    container.appendChild(info);

    var prevBtn = document.createElement("button");
    prevBtn.type = "button"; prevBtn.textContent = "←";
    prevBtn.setAttribute("aria-label", "Previous page");
    prevBtn.disabled = current === 1;
    if (!prevBtn.disabled) prevBtn.addEventListener("click", navTo(current - 1));
    container.appendChild(prevBtn);

    _buildPageList(current, totalPages).forEach(function (item) {
        if (item === "…") {
            var gap = document.createElement("span");
            gap.className = "bo-page-gap"; gap.textContent = "…";
            gap.setAttribute("aria-hidden", "true");
            container.appendChild(gap);
            return;
        }
        var b = document.createElement("button");
        b.type = "button"; b.className = "bo-page-btn";
        b.textContent = item.toLocaleString();
        if (item === current) {
            b.classList.add("bo-page-btn--active");
            b.disabled = true;
            b.setAttribute("aria-current", "page");
            b.setAttribute("aria-label", "Page " + item + ", current");
        } else {
            b.setAttribute("aria-label", "Go to page " + item);
            b.addEventListener("click", navTo(item));
        }
        container.appendChild(b);
    });

    var nextBtn = document.createElement("button");
    nextBtn.type = "button"; nextBtn.textContent = "→";
    nextBtn.setAttribute("aria-label", "Next page");
    nextBtn.disabled = current === totalPages;
    if (!nextBtn.disabled) nextBtn.addEventListener("click", navTo(current + 1));
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

function makeDeleteBtn(name) {
    var btn = document.createElement("button");
    btn.className = "bo-btn bo-btn--icon bo-btn--danger";
    btn.title = name ? 'Delete "' + name + '"' : 'Delete';
    btn.setAttribute('aria-label', btn.title);
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

function makeProfilePicEl(ch, className) {
    if (!ch || !ch.profile_picture_url) return null;
    var mime = ch.profile_picture_mime_type || "";
    var thumb = ch.profile_picture_thumbnail_url;
    var el;
    if (mime.indexOf("video/") === 0) {
        el = document.createElement("video");
        el.src = ch.profile_picture_url;
        if (thumb) el.setAttribute("poster", thumb);
        el.autoplay = true;
        el.loop = true;
        el.muted = true;
        el.playsInline = true;
        el.setAttribute("aria-hidden", "true");
    } else {
        el = document.createElement("img");
        el.src = ch.profile_picture_url;
        el.alt = "";
    }
    if (className) el.className = className;
    return el;
}
