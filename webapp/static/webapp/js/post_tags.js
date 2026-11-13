/* Message-tag editor on post cards (webapp/_post_card.html).

   The tag button and panel are rendered only for users who may edit tags
   (CAN_EDIT_TAGS); everyone who may see tags gets the read-only chip row. The
   editor talks to the backoffice API — /manage/api/message-taggings/ for one
   post's tags, /manage/api/message-tags/ for the shared tag list — and rebuilds
   chip rows with the same markup the template renders. The tag field is an
   ARIA combobox: it lists the existing tags — as a tree while the field is
   empty — and filters them by path as you type ("salute", "gestures/nazi").
   Tags nest: a name or path naming an existing tag (ignoring case) reuses it,
   any other creates the missing part ("Hand gestures/Kühnen salute" adds a
   sub-tag); the server makes the final match (webapp.models.tag_models.
   plan_tag_path), and this file mirrors its TagTree.match. Adding a sub-tag of
   a tag on the post refines that tagging; a tag implied by a sub-tag on the
   post can't be added. A tag belongs to the post (its original and every
   share), so other cards on the page may be the same post: after each change
   every chip row on the page is refreshed in one call
   (message-taggings/for-messages/). */
(function() {
    'use strict';

    var API_TAGS = '/manage/api/message-tags/';
    var API_TAGGINGS = '/manage/api/message-taggings/';
    var MANAGE_URL = '/manage/tags/';

    var allTags = [];
    var tagsById = {};
    var tagsPromise = null;
    var combos = [];
    var PATH_SEPARATOR = ' › ';

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

    // "Hand gestures / Nazi salute" or "Hand gestures › Nazi salute" → its names
    // (split_tag_path on the server).
    function splitPath(text) {
        return String(text || '').split(/[/›]/).map(function(part) {
            return part.trim().split(/\s+/).join(' ');
        }).filter(Boolean);
    }

    function pathKeys(text) {
        return splitPath(text).map(tagKey);
    }

    function endsWith(keys, tail) {
        if (tail.length > keys.length) return false;
        var offset = keys.length - tail.length;
        return tail.every(function(key, i) { return keys[offset + i] === key; });
    }

    // The tags a typed path names (TagTree.match): the one reached from the top
    // level, else every tag whose path ends with it.
    function matchTags(text) {
        var keys = pathKeys(text);
        if (!keys.length) return [];
        var full = keys.join('/');
        var exact = allTags.filter(function(t) { return t.pathKey === full; });
        if (exact.length) return exact;
        return allTags.filter(function(t) { return endsWith(t.keys, keys); });
    }

    function ancestorIds(tag) {
        var out = [];
        var seen = {};
        var parent = tag ? tagsById[tag.parent] : null;
        while (parent && !seen[parent.id]) {
            seen[parent.id] = true;
            out.push(parent.id);
            parent = tagsById[parent.parent];
        }
        return out;
    }

    // "Hand gestures › " for the sub-tag "Nazi salute" (the path minus the name).
    function ancestry(tag) {
        var path = tag.path || tag.name;
        return path.length > tag.name.length ? path.slice(0, path.length - tag.name.length) : '';
    }

    // The shared tag list behind every editor's combobox, depth-first. Fetched once
    // per page; refreshed after a tag is created on the fly.
    function loadTags(refresh) {
        if (!tagsPromise || refresh) {
            tagsPromise = api(API_TAGS + '?limit=1000').then(function(data) {
                allTags = data.results;
                tagsById = {};
                allTags.forEach(function(t) {
                    t.keys = pathKeys(t.path);
                    t.pathKey = t.keys.join('/');
                    tagsById[t.id] = t;
                });
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

    /* The tag field: lists the existing tags (minus those on the post and those
       a sub-tag on the post implies), filters them by path as you type, and offers
       to create the tag when the text names none. Picking an option fills the
       field with its path; Enter on the option already in the field (or with the
       list closed) submits the form. ``onState`` hears 'empty' | 'existing' |
       'refine' (replaces a broader tag on the post) | 'new' | 'present' (already
       on the post) | 'implied' (a sub-tag on the post implies it) | 'ambiguous'. */
    function createTagCombo(postPk, onState) {
        var listId = 'ptc-' + postPk;
        var input = document.createElement('input');
        input.className = 'form-control form-control-sm';
        input.maxLength = 255;
        input.required = true;
        input.autocomplete = 'off';
        input.placeholder = 'Tag — pick one, or type a name or Parent/Sub-tag';
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-controls', listId);
        input.setAttribute('aria-label', 'Tag: pick one, or type a name or a Parent/Sub-tag path');

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

        // Tags a sub-tag on the post implies: they can't be added.
        function implied() {
            var out = {};
            Object.keys(present).forEach(function(id) {
                ancestorIds(tagsById[id]).forEach(function(a) { out[a] = true; });
            });
            return out;
        }

        // The tag on the post a pick would refine (one of its ancestors), if any.
        function broaderOnPost(tag) {
            var ids = ancestorIds(tag).filter(function(id) { return present[id]; });
            return ids.length ? tagsById[ids[0]] : null;
        }

        function state() {
            if (!input.value.trim()) return 'empty';
            var found = matchTags(input.value);
            if (found.length > 1) return 'ambiguous';
            if (!found.length) return 'new';
            var tag = found[0];
            if (present[tag.id]) return 'present';
            if (implied()[tag.id]) return 'implied';
            return broaderOnPost(tag) ? 'refine' : 'existing';
        }

        function info(text) {
            var li = document.createElement('li');
            li.className = 'tag-combo-info';
            li.textContent = text;
            listbox.appendChild(li);
        }

        function optionValue(option) {
            return option.tag ? option.tag.path : option.name;
        }

        function render() {
            var keys = pathKeys(input.value);
            var query = keys.join('/');
            var found = matchTags(input.value);
            var exact = found.length === 1 ? found[0] : null;
            var blocked = implied();
            Object.keys(present).forEach(function(id) { blocked[id] = true; });
            var matches = allTags.filter(function(t) {
                return !blocked[t.id] && (!query || t.pathKey.indexOf(query) !== -1);
            });
            if (query) {
                // Names starting with the query first, then paths starting with it,
                // then the other matches (each by path).
                var rank = function(t) {
                    if (keys.length === 1 && t.keys[t.keys.length - 1].indexOf(query) === 0) return 0;
                    return t.pathKey.indexOf(query) === 0 ? 1 : 2;
                };
                matches.sort(function(a, b) { return rank(a) - rank(b) || a.pathKey.localeCompare(b.pathKey); });
            }
            options = matches.map(function(t) { return { name: t.path, tag: t }; });
            if (query && !found.length) options.push({ name: splitPath(input.value).join(PATH_SEPARATOR), tag: null });

            listbox.innerHTML = '';
            if (exact && present[exact.id]) info('“' + exact.path + '” is already on this post.');
            else if (exact && blocked[exact.id]) info('A sub-tag of “' + exact.path + '” is on this post, which implies it.');
            else if (found.length > 1) info('Several tags are named “' + input.value.trim() + '” — pick one, or type its full path.');
            var shown = {};
            options.forEach(function(option) { if (option.tag) shown[option.tag.id] = true; });
            options.forEach(function(option, i) {
                var li = document.createElement('li');
                li.id = listId + '-' + i;
                li.className = 'tag-combo-option' + (option.tag ? '' : ' is-create');
                li.setAttribute('role', 'option');
                if (option.tag) {
                    var tag = option.tag;
                    li.appendChild(swatch(tag.color));
                    // As a tree (empty field) a sub-tag sits under its parent; a flat
                    // filtered list, or a parent left out, names the ancestors instead.
                    var asTree = !query && (!tag.parent || shown[tag.parent]);
                    if (!query) {
                        li.dataset.depth = tag.depth;
                        li.style.setProperty('--tag-depth', asTree ? tag.depth : 0);
                    }
                    if (!asTree && ancestry(tag)) {
                        var path = document.createElement('span');
                        path.className = 'tag-combo-path';
                        path.textContent = ancestry(tag);
                        li.appendChild(path);
                    }
                    li.appendChild(document.createTextNode(tag.name));
                    var broader = broaderOnPost(tag);
                    if (broader) {
                        var note = document.createElement('span');
                        note.className = 'tag-combo-note';
                        note.textContent = 'replaces “' + broader.name + '”';
                        li.appendChild(note);
                    }
                    var count = document.createElement('span');
                    count.className = 'tag-combo-count';
                    count.textContent = tag.message_count;
                    count.title = tag.message_count + ' message(s)' +
                        (tag.message_count !== tag.own_count ? ', ' + tag.own_count + ' without a sub-tag' : '');
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
            input.value = optionValue(options[i]);
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
                if (pathKeys(optionValue(options[active])).join('/') !== pathKeys(input.value).join('/')) {
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
            // The tags already on this post (and those they imply) leave the list.
            setPresent: function(taggings) {
                present = {};
                taggings.forEach(function(t) { present[t.tag.id] = true; });
                combo.refresh();
            },
            // The one existing tag the field names, if any: sent by id.
            matched: function() {
                var found = matchTags(input.value);
                return found.length === 1 ? found[0] : null;
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
        return (ancestry(tagging.tag) ? tagging.tag.path + ' — ' : '') +
            (tagging.note ? tagging.note + ' — ' : '') +
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
        var prefix = ancestry(tagging.tag);
        if (prefix) {
            var path = document.createElement('span');
            path.className = 'post-tag-path';
            path.textContent = prefix;
            a.appendChild(path);
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
            // The button says whether Add reuses a tag, creates one, or refines one.
            addBtn.textContent = state === 'new' ? 'Create & add' : state === 'refine' ? 'Refine' : 'Add';
            addBtn.disabled = state === 'present' || state === 'implied' || state === 'ambiguous';
            addBtn.title = {
                present: 'This post already carries that tag',
                implied: 'A sub-tag of that tag is on this post, which implies it',
                ambiguous: 'Several tags have that name: pick one, or type its full path',
                refine: 'Replaces the broader tag on this post with this more specific one',
            } [state] || '';
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
        hint.textContent = 'A tag goes on the whole post: its original and every share of it. Type Parent/Sub-tag to make a sub-tag.';

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
                note.setAttribute('aria-label', 'Note for tag ' + tagging.tag.path);
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
                remove.title = 'Remove tag ' + tagging.tag.path;
                remove.setAttribute('aria-label', remove.title);
                remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
                remove.addEventListener('click', function() {
                    api(API_TAGGINGS + tagging.id + '/', 'DELETE')
                        .then(function() {
                            taggings = taggings.filter(function(t) { return t.id !== tagging.id; });
                            sync();
                            say('Removed “' + tagging.tag.path + '”' + reachText(tagging, 'from') + '.');
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
            var body = { message: Number(postPk), note: noteIn.value.trim() };
            var known = combo.matched();
            if (known) body.tag_id = known.id;
            else body.tag_name = name;
            api(API_TAGGINGS, 'POST', body)
                .then(function(created) {
                    // A refined tagging keeps its id: replace it rather than add a second chip.
                    taggings = taggings.filter(function(t) { return t.id !== created.id; });
                    taggings.push(created);
                    taggings.sort(function(a, b) { return a.tag.path.localeCompare(b.tag.path); });
                    sync();
                    form.reset();
                    combo.clear();
                    var what = created.replaced && created.replaced.length ?
                        'Refined “' + created.replaced.join('”, “') + '” to “' + created.tag.path + '”' :
                        'Tagged “' + created.tag.path + '”';
                    say(what + reachText(created, 'on') + '.');
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
