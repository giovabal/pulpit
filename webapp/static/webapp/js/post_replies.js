(function () {
  'use strict';

  function fmtDate(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'}); }
    catch (e) { return iso; }
  }

  function renderReplies(panel, data) {
    var inner = panel.querySelector('.post-replies-inner');
    inner.innerHTML = '';
    if (!data.fetched) {
      var hint = document.createElement('p');
      hint.className = 'post-replies-hint';
      hint.textContent = 'Replies have not been fetched yet. Run the crawler with "Fetch replies" enabled.';
      inner.appendChild(hint);
      return;
    }
    if (!data.replies || !data.replies.length) {
      var empty = document.createElement('p');
      empty.className = 'post-replies-hint';
      empty.textContent = 'No replies stored.';
      inner.appendChild(empty);
      return;
    }
    var list = document.createElement('ol');
    list.className = 'post-replies-list list-unstyled';
    data.replies.forEach(function (r) {
      var item = document.createElement('li');
      item.className = 'post-reply-item';
      var hdr = document.createElement('div');
      hdr.className = 'post-reply-header';
      var who = document.createElement('span');
      who.className = 'post-reply-sender';
      who.textContent = r.sender_name || 'Anonymous';
      var when = document.createElement('time');
      when.className = 'post-reply-date';
      when.textContent = fmtDate(r.date);
      if (r.date) when.setAttribute('datetime', r.date);
      hdr.appendChild(who);
      hdr.appendChild(when);
      if (r.views != null) {
        var views = document.createElement('span');
        views.className = 'post-reply-views';
        views.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i> ' + r.views.toLocaleString();
        hdr.appendChild(views);
      }
      var body = document.createElement('div');
      body.className = 'post-reply-body';
      body.textContent = r.text;
      item.appendChild(hdr);
      item.appendChild(body);
      list.appendChild(item);
    });
    inner.appendChild(list);
  }

  document.querySelectorAll('.post-replies-btn').forEach(function (btn) {
    var postPk = btn.dataset.postPk;
    var panel = document.getElementById('pr-' + postPk);
    var loaded = false;
    var open = false;
    btn.addEventListener('click', function () {
      open = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      panel.style.display = open ? '' : 'none';
      if (open && !loaded) {
        loaded = true;
        var inner = panel.querySelector('.post-replies-inner');
        inner.innerHTML = '<div class="post-replies-spinner"><div class="spinner-border spinner-border-sm text-secondary" role="status"><span class="visually-hidden">Loading…</span></div></div>';
        fetch(btn.dataset.repliesUrl)
          .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function (data) { renderReplies(panel, data); })
          .catch(function () {
            inner.innerHTML = '<p class="post-replies-hint">Failed to load replies.</p>';
            loaded = false;
          });
      }
    });
  });
})();
