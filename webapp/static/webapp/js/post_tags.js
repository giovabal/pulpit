/* Message-tag editor on post cards (webapp/_post_card.html).

   The tag button and panel are rendered only for users who may edit tags
   (CAN_EDIT_TAGS); everyone who may see tags gets the read-only chip row. The
   editor talks to the backoffice API — /manage/api/message-taggings/ for one
   post's tags, /manage/api/message-tags/ for the shared tag list — and rebuilds
   chip rows with the same markup the template renders. The tag field is an
   ARIA combobox: it lists the existing tags and filters them as you type; a
   name matching an existing tag (ignoring case) reuses it, any other creates a
   new tag (the server makes the final match, by webapp.models.tag_models.tag_key). A tag belongs to the post (its original and every share), so other
   cards on the page may be the same post: after each change every chip row on
   the page is refreshed in one call (message-taggings/for-messages/). */
(function() {
    'use strict';

    var API_TAGS = '/manage/api/message-tags/';
    var API_TAGGINGS = '/manage/api/message-taggings/';
    var MANAGE_URL = '/manage/tags/';

    var allTags = [];
    var tagsPromise = null;
    var combos = [];

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

    // Close enough to the server's tag_key (NFKC, collapsed whitespace, case-folded)
    // for the field's hints; the server decides the actual match.
    function tagKey(name) {
        return String(name || '').normalize('NFKC').trim().split(/\s+/).join(' ').toLowerCase();
    }

    // The shared tag list behind every editor's combobox. Fetched once per page;
    // refreshed after a tag is created on the fly.
    function loadTags(refresh) {
        if (!tagsPromise || refresh) {
            tagsPromise = api(API_TAGS + '?limit=1000').then(function(data) {
                allTags = data.results;
                combos.forEach(function(combo) { combo.refresh(); });
            }).catch(function() { tagsPromise = null; });
        }
        return tagsPromise;
    }

    function swatch(color) {
        var dot = document.createElement('span');
        dot.className = 'tag-swatch';
        dot.style.background = color;
        dot.setAttribute('aria-hidden', 'true');
        return dot;
    }

    /* The tag field: lists the existing tags (minus those already on the post),
       filters them as you type, and offers to create a tag when the text matches
       none. Picking an option fills the field; Enter on the option already in the
       field (or with the list closed) submits the form. ``onState`` hears
       'empty' | 'existing' | 'new' | 'present' (already on this post). */
    function createTagCombo(postPk, onState) {
        var listId = 'ptc-' + postPk;
        var input = document.createElement('input');
        input.className = 'form-control form-control-sm';
        input.maxLength = 64;
        input.required = true;
        input.autocomplete = 'off';
        input.placeholder = 'Tag — pick one or type a new name';
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-controls', listId);
        input.setAttribute('aria-label', 'Tag: pick one or type a new name');

        var listbox = document.createElement('ul');
        listbox.className = 'tag-combo-list list-unstyled';
        listbox.id = listId;
        listbox.setAttribute('role', 'listbox');
        listbox.setAttribute('aria-label', 'Tags');
        listbox.hidden = true;
        // Keep focus in the field when the list (or its scrollbar) is clicked.
        listbox.addEventListener('mousedown', function(e) { e.preventDefault(); });

        var options = [];
        var active = -1;
        var present = {};

        function exactMatch() {
            var key = tagKey(input.value);
            if (!key) return null;
            return allTags.find(function(t) { return tagKey(t.name) === key; }) || null;
        }

        function state() {
            if (!input.value.trim()) return 'empty';
            var exact = exactMatch();
            if (!exact) return 'new';
            return present[tagKey(exact.name)] ? 'present' : 'existing';
        }

        function info(text) {
            var li = document.createElement('li');
            li.className = 'tag-combo-info';
            li.textContent = text;
            listbox.appendChild(li);
        }

        function render() {
            var query = tagKey(input.value);
            var exact = exactMatch();
            var matches = allTags.filter(function(t) {
                var key = tagKey(t.name);
                return !present[key] && (!query || key.indexOf(query) !== -1);
            });
            // Names starting with the query first, then the other matches (each alphabetical).
            matches.sort(function(a, b) {
                var pa = tagKey(a.name).indexOf(query) === 0 ? 0 : 1;
                var pb = tagKey(b.name).indexOf(query) === 0 ? 0 : 1;
                return pa - pb || a.name.localeCompare(b.name);
            });
            options = matches.map(function(t) { return { name: t.name, tag: t }; });
            if (query && !exact) options.push({ name: input.value.trim(), tag: null });

            listbox.innerHTML = '';
            if (exact && present[tagKey(exact.name)]) info('“' + exact.name + '” is already on this post.');
            options.forEach(function(option, i) {
                var li = document.createElement('li');
                li.id = listId + '-' + i;
                li.className = 'tag-combo-option' + (option.tag ? '' : ' is-create');
                li.setAttribute('role', 'option');
                if (option.tag) {
                    li.appendChild(swatch(option.tag.color));
                    li.appendChild(document.createTextNode(option.tag.name));
                    var count = document.createElement('span');
                    count.className = 'tag-combo-count';
                    count.textContent = option.tag.message_count;
                    count.title = option.tag.message_count + ' message(s)';
                    li.appendChild(count);
                } else {
                    li.innerHTML = '<i class="bi bi-plus-lg" aria-hidden="true"></i>';
                    li.appendChild(document.createTextNode('Create tag “' + option.name + '”'));
                }
                li.addEventListener('click', function() { pick(i); });
                option.el = li;
                listbox.appendChild(li);
            });
            if (!options.length && !listbox.childNodes.length) {
                info(allTags.length ? 'No other tags.' : 'No tags yet — type a name to create one.');
            }
            // Prefer reusing a tag: the exact match, else the first match, else "create".
            active = options.length ? 0 : -1;
            options.forEach(function(option, i) { if (option.tag && option.tag === exact) active = i; });
            if (!query) active = -1;
            highlight();
            onState(state());
        }

        function highlight() {
            options.forEach(function(option, i) {
                option.el.classList.toggle('is-active', i === active);
                option.el.setAttribute('aria-selected', i === active ? 'true' : 'false');
            });
            if (active >= 0) {
                input.setAttribute('aria-activedescendant', options[active].el.id);
                options[active].el.scrollIntoView({ block: 'nearest' });
            } else {
                input.removeAttribute('aria-activedescendant');
            }
        }

        function open() {
            if (!listbox.hidden) return;
            listbox.hidden = false;
            input.setAttribute('aria-expanded', 'true');
            render();
        }

        function close() {
            listbox.hidden = true;
            input.setAttribute('aria-expanded', 'false');
            input.removeAttribute('aria-activedescendant');
        }

        function pick(i) {
            input.value = options[i].name;
            close();
            onState(state());
        }

        input.addEventListener('focus', open);
        input.addEventListener('click', open);
        input.addEventListener('blur', close);
        input.addEventListener('input', function() {
            if (listbox.hidden) open();
            else render();
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                if (listbox.hidden) {
                    open();
                    return;
                }
                if (!options.length) return;
                if (e.key === 'ArrowDown') active = (active + 1) % options.length;
                else active = active <= 0 ? options.length - 1 : active - 1;
                highlight();
            } else if (e.key === 'Enter' && !listbox.hidden && active >= 0) {
                // Enter on an option other than what the field holds picks it; on the
                // one already typed it falls through and submits the form.
                if (tagKey(options[active].name) !== tagKey(input.value)) {
                    e.preventDefault();
                    pick(active);
                } else {
                    close();
                }
            } else if (e.key === 'Escape' && !listbox.hidden) {
                e.preventDefault();
                close();
            }
        });

        var combo = {
            input: input,
            listbox: listbox,
            // The tags already on this post leave the list.
            setPresent: function(taggings) {
                present = {};
                taggings.forEach(function(t) { present[tagKey(t.tag.name)] = true; });
                combo.refresh();
            },
            refresh: function() {
                if (!listbox.hidden) render();
                else onState(state());
            },
            clear: function() {
                input.value = '';
                combo.refresh();
            },
        };
        combos.push(combo);
        return combo;
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
        var addBtn = document.createElement('button');
        var combo = createTagCombo(postPk, function(state) {
            // The button says whether Add reuses a tag or creates one.
            addBtn.textContent = state === 'new' ? 'Create & add' : 'Add';
            addBtn.disabled = state === 'present';
            addBtn.title = state === 'present' ? 'This post already carries that tag' : '';
        });
        var nameIn = combo.input;
        var noteIn = document.createElement('input');
        noteIn.className = 'form-control form-control-sm';
        noteIn.placeholder = 'Note (optional)';
        noteIn.setAttribute('aria-label', 'Note');
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
        inner.appendChild(combo.listbox);
        inner.appendChild(hint);
        inner.appendChild(list);
        inner.appendChild(foot);
        panel.appendChild(inner);

        function say(text, isError) {
            status.textContent = text;
            status.classList.toggle('is-error', !!isError);
        }

        function sync() {
            combo.setPresent(taggings);
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
                    combo.clear();
                    say('Tagged “' + created.tag.name + '”' + reachText(created, 'on') + '.');
                    loadTags(true);
                })
                .catch(function(err) { say(err.message, true); })
                .then(function() {
                    addBtn.disabled = false;
                    nameIn.focus();
                });
        });

        function load() {
            say('Loading…');
            loadTags(false);
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
