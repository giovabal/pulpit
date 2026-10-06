/* Message-tag editor on post cards (webapp/_post_card.html).

   The tag button and panel are rendered only for users who may edit tags
   (CAN_EDIT_TAGS); everyone who may see tags gets the read-only chip row. The
   editor talks to the backoffice API — /manage/api/message-taggings/ for one
   post's tags, /manage/api/message-tags/ for the shared tag list offered as
   name suggestions — and rebuilds chip rows with the same markup the template
   renders. A tag belongs to the post (its original and every share), so other
   cards on the page may be the same post: after each change every chip row on
   the page is refreshed in one call (message-taggings/for-messages/). */
(function() {
    'use strict';

    var API_TAGS = '/manage/api/message-tags/';
    var API_TAGGINGS = '/manage/api/message-taggings/';
    var MANAGE_URL = '/manage/tags/';
    var DATALIST_ID = 'message-tag-names';

    var tagNamesPromise = null;

    function errorText(data, r) {
        if (data && data.detail) return data.detail;
        var parts = [];
        Object.keys(data || {}).forEach(function(k) {
            var v = data[k];
            parts.push(Array.isArray(v) ? v.join(' ') : String(v));
        });
        return parts.join(' ') || r.status + ' ' + r.statusText;
    }

    function api(url, method, body) {
        var init = { method: method || 'GET', headers: { 'Content-Type': 'application/json' } };
        if (init.method !== 'GET') init.headers['X-CSRFToken'] = getCsrfToken();
        if (body !== undefined) init.body = JSON.stringify(body);
        return fetch(url, init).then(function(r) {
            if (r.status === 204) return null;
            return r.json().catch(function() { return {}; }).then(function(data) {
                if (!r.ok) throw new Error(errorText(data, r));
                return data;
            });
        });
    }

    // The shared tag list, offered as <datalist> suggestions in every panel.
    // Fetched once per page; refreshed after a tag is created on the fly.
    function loadTagNames(refresh) {
        if (!tagNamesPromise || refresh) {
            tagNamesPromise = api(API_TAGS + '?limit=1000').then(function(data) {
                var list = document.getElementById(DATALIST_ID);
                if (!list) {
                    list = document.createElement('datalist');
                    list.id = DATALIST_ID;
                    document.body.appendChild(list);
                }
                list.innerHTML = '';
                data.results.forEach(function(t) {
                    var opt = document.createElement('option');
                    opt.value = t.name;
                    list.appendChild(opt);
                });
            }).catch(function() { tagNamesPromise = null; });
        }
        return tagNamesPromise;
    }

    function chipTitle(tagging) {
        var date = (tagging.tagged_at || '').slice(0, 10);
        return (tagging.note ? tagging.note + ' — ' : '') +
            'tagged' + (tagging.tagged_by ? ' by ' + tagging.tagged_by : '') + ' on ' + date;
    }

    function makeChip(tagging, searchUrl) {
        var a = document.createElement('a');
        a.className = 'post-tag' + (tagging.tag.is_dark ? ' is-dark' : '');
        a.style.setProperty('--tag-color', tagging.tag.color);
        a.href = searchUrl + '?tag=' + tagging.tag.id;
        a.title = chipTitle(tagging);
        if (tagging.note) {
            var icon = document.createElement('i');
            icon.className = 'bi bi-sticky';
            icon.setAttribute('aria-hidden', 'true');
            a.appendChild(icon);
        }
        a.appendChild(document.createTextNode(tagging.tag.name));
        return a;
    }

    function renderChips(postPk, taggings) {
        var row = document.getElementById('pt-' + postPk);
        if (!row) return;
        row.innerHTML = '';
        taggings.forEach(function(t) { row.appendChild(makeChip(t, row.dataset.searchUrl)); });
        row.hidden = !taggings.length;
    }

    // Re-render every chip row on the page: the edited post may also be shown
    // as its original or another share elsewhere in the list.
    function refreshAllChips() {
        var ids = Array.prototype.map.call(document.querySelectorAll('.post-tags[id^="pt-"]'), function(row) {
            return row.id.slice(3);
        });
        if (!ids.length) return Promise.resolve();
        return api(API_TAGGINGS + 'for-messages/?ids=' + ids.join(',')).then(function(byMessage) {
            Object.keys(byMessage).forEach(function(pk) { renderChips(pk, byMessage[pk]); });
        }).catch(function() { /* chips catch up on the next page load */ });
    }

    // " here and on 3 other messages of the same post" — empty when only this one carries it.
    function reachText(tagging, preposition) {
        var others = (tagging.member_count || 1) - 1;
        if (others < 1) return '';
        return ' here and ' + preposition + ' ' + others + ' other message' + (others === 1 ? '' : 's') + ' of the same post';
    }

    function initEditor(btn) {
        var postPk = btn.dataset.postPk;
        var panel = document.getElementById('ptp-' + postPk);
        if (!panel) return;
        var row = document.getElementById('pt-' + postPk);
        var searchUrl = row ? row.dataset.searchUrl : '/search/';
        var taggings = null;

        var inner = document.createElement('div');
        inner.className = 'post-tags-inner';

        var form = document.createElement('form');
        form.className = 'post-tags-form';
        form.autocomplete = 'off';
        var nameIn = document.createElement('input');
        nameIn.className = 'form-control form-control-sm';
        nameIn.setAttribute('list', DATALIST_ID);
        nameIn.maxLength = 64;
        nameIn.required = true;
        nameIn.placeholder = 'Tag — pick or type a new one';
        nameIn.setAttribute('aria-label', 'Tag name');
        var noteIn = document.createElement('input');
        noteIn.className = 'form-control form-control-sm';
        noteIn.placeholder = 'Note (optional)';
        noteIn.setAttribute('aria-label', 'Note');
        var addBtn = document.createElement('button');
        addBtn.type = 'submit';
        addBtn.className = 'btn btn-sm btn-primary';
        addBtn.textContent = 'Add';
        form.appendChild(nameIn);
        form.appendChild(noteIn);
        form.appendChild(addBtn);

        var hint = document.createElement('p');
        hint.className = 'post-tags-hint';
        hint.textContent = 'A tag goes on the whole post: its original and every share of it.';

        var list = document.createElement('ul');
        list.className = 'post-tags-list list-unstyled';

        var foot = document.createElement('div');
        foot.className = 'post-tags-foot';
        var status = document.createElement('span');
        status.className = 'post-tags-status';
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        var manage = document.createElement('a');
        manage.href = MANAGE_URL;
        manage.className = 'post-tags-manage';
        manage.textContent = 'Manage tags';
        foot.appendChild(status);
        foot.appendChild(manage);

        inner.appendChild(form);
        inner.appendChild(hint);
        inner.appendChild(list);
        inner.appendChild(foot);
        panel.appendChild(inner);

        function say(text, isError) {
            status.textContent = text;
            status.classList.toggle('is-error', !!isError);
        }

        function sync() {
            renderList();
            renderChips(postPk, taggings);
            refreshAllChips();
        }

        function renderList() {
            list.innerHTML = '';
            taggings.forEach(function(tagging) {
                var li = document.createElement('li');
                li.className = 'post-tags-item';
                li.appendChild(makeChip(tagging, searchUrl));

                var note = document.createElement('input');
                note.className = 'form-control form-control-sm post-tags-note';
                note.value = tagging.note || '';
                note.placeholder = 'Note';
                note.setAttribute('aria-label', 'Note for tag ' + tagging.tag.name);
                note.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        note.blur();
                    }
                });
                note.addEventListener('change', function() {
                    api(API_TAGGINGS + tagging.id + '/', 'PATCH', { note: note.value.trim() })
                        .then(function(updated) {
                            Object.assign(tagging, updated);
                            renderChips(postPk, taggings);
                            refreshAllChips();
                            say('Note saved' + reachText(tagging, 'on') + '.');
                        })
                        .catch(function(e) { say(e.message, true); });
                });
                li.appendChild(note);

                var remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'post-tags-remove';
                remove.title = 'Remove tag ' + tagging.tag.name;
                remove.setAttribute('aria-label', remove.title);
                remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
                remove.addEventListener('click', function() {
                    api(API_TAGGINGS + tagging.id + '/', 'DELETE')
                        .then(function() {
                            taggings = taggings.filter(function(t) { return t.id !== tagging.id; });
                            sync();
                            say('Removed “' + tagging.tag.name + '”' + reachText(tagging, 'from') + '.');
                            nameIn.focus();
                        })
                        .catch(function(e) { say(e.message, true); });
                });
                li.appendChild(remove);
                list.appendChild(li);
            });
        }

        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var name = nameIn.value.trim();
            if (!name) return;
            addBtn.disabled = true;
            api(API_TAGGINGS, 'POST', { message: Number(postPk), tag_name: name, note: noteIn.value.trim() })
                .then(function(created) {
                    taggings.push(created);
                    taggings.sort(function(a, b) { return a.tag.name.localeCompare(b.tag.name); });
                    sync();
                    form.reset();
                    say('Tagged “' + created.tag.name + '”' + reachText(created, 'on') + '.');
                    loadTagNames(true);
                })
                .catch(function(err) { say(err.message, true); })
                .then(function() {
                    addBtn.disabled = false;
                    nameIn.focus();
                });
        });

        function load() {
            say('Loading…');
            loadTagNames(false);
            return api(API_TAGGINGS + '?message=' + postPk + '&limit=1000')
                .then(function(data) {
                    taggings = data.results;
                    sync();
                    say('');
                })
                .catch(function(e) { say(e.message, true); });
        }

        // Reloaded on every open: another card may have changed this post's tags.
        btn.addEventListener('click', function() {
            var open = panel.hidden;
            panel.hidden = !open;
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (!open) return;
            load();
            nameIn.focus();
        });
    }

    document.querySelectorAll('.post-tags-btn').forEach(initEditor);
})();
