// The period switcher above every table page: "All periods" plus one choice per exported timeline period.
// periods: timeline periods ({key, label, start, …}, already filtered to those that have the relevant data).
// cur:     current value — a period key or "all".
// onSelect: callback called with the selected key (or "all").
// events:  optional timeline events ({date, subject, period_key, …}); a period containing one is marked.
// Up to BUTTON_LIMIT periods show as a row of buttons; more (a quarterly or monthly timeline) as
// "All periods" + previous / next + a select grouped by year, so the control stays one line.
// Clears the container on each call so it can be used to refresh active state; the keyboard focus a reader had
// on the control is put back on the period now shown (or on the same arrow / select).
var BUTTON_LIMIT = 12;
var ROLE_ATTR = "data-period-control";

function _eventsByPeriod(events) {
    var out = {};
    (events || []).forEach(function(e) {
        if (!e.period_key) return;
        (out[e.period_key] = out[e.period_key] || []).push(e.date + " — " + e.subject);
    });
    return out;
}

// role: what the control is, for giving the focus back after a rebuild — "period" (pressed = the one on show),
// "prev", "next".
function _button(text, role, active, onClick) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm " + (active ? "btn-primary" : "btn-outline-secondary");
    btn.textContent = text;
    btn.setAttribute(ROLE_ATTR, role);
    if (role === "period") btn.setAttribute("aria-pressed", active ? "true" : "false");
    btn.addEventListener("click", onClick);
    return btn;
}

function _focusedRole(target) {
    var active = document.activeElement;
    return active && target.contains(active) ? active.getAttribute(ROLE_ATTR) : null;
}

function _restoreFocus(target, role) {
    if (!role) return;
    var selector = role === "period" ? "[" + ROLE_ATTR + "=\"period\"][aria-pressed=\"true\"]" : "[" + ROLE_ATTR + "=\"" + role + "\"]";
    var control = target.querySelector(selector) || target.querySelector("[" + ROLE_ATTR + "=\"select\"]");
    if (control) control.focus();
}

export function build_year_nav(periods, cur, onSelect, events) {
    var target = document.getElementById("timeline-nav");
    if (!target || !periods.length) return;
    var focused = _focusedRole(target);
    target.innerHTML = "";
    var marks = _eventsByPeriod(events);
    var wrap = document.createElement("div");
    wrap.className = "d-flex flex-wrap align-items-center gap-1";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Period navigator");
    var label = document.createElement("span");
    label.className = "export-period-label";
    label.textContent = "Period";
    wrap.appendChild(label);
    wrap.appendChild(_button("All periods", "period", cur === "all", function() { onSelect("all"); }));

    if (periods.length <= BUTTON_LIMIT) {
        periods.forEach(function(p) {
            var evs = marks[p.key];
            var btn = _button(p.label + (evs ? " •" : ""), "period", cur === p.key, function() { onSelect(p.key); });
            if (evs) btn.title = "Events: " + evs.join("; ");
            wrap.appendChild(btn);
        });
        target.appendChild(wrap);
        _restoreFocus(target, focused);
        return;
    }

    var idx = -1;
    periods.forEach(function(p, i) { if (p.key === cur) idx = i; });
    var prev = _button("◀", "prev", false, function() { onSelect(idx <= 0 ? periods[periods.length - 1].key : periods[idx - 1].key); });
    prev.setAttribute("aria-label", "Previous period");
    var next = _button("▶", "next", false, function() { onSelect(idx === -1 || idx >= periods.length - 1 ? periods[0].key : periods[idx + 1].key); });
    next.setAttribute("aria-label", "Next period");
    var sel = document.createElement("select");
    sel.className = "form-select form-select-sm";
    sel.style.width = "auto";
    sel.setAttribute("aria-label", "Period");
    sel.setAttribute(ROLE_ATTR, "select");
    sel.appendChild(new Option("Choose a period…", "", cur === "all", cur === "all"));
    var groups = {};
    periods.forEach(function(p) {
        var year = String(p.start || p.key).slice(0, 4);
        if (!groups[year]) {
            groups[year] = document.createElement("optgroup");
            groups[year].label = year;
            sel.appendChild(groups[year]);
        }
        var evs = marks[p.key];
        var opt = new Option(p.label + (evs ? " •" : ""), p.key, false, p.key === cur);
        if (evs) opt.title = "Events: " + evs.join("; ");
        groups[year].appendChild(opt);
    });
    sel.addEventListener("change", function() { if (sel.value) onSelect(sel.value); });
    wrap.appendChild(prev);
    wrap.appendChild(sel);
    wrap.appendChild(next);
    if (idx !== -1 && marks[periods[idx].key]) {
        var note = document.createElement("span");
        note.className = "small text-muted ms-2";
        note.textContent = "Events: " + marks[periods[idx].key].join("; ");
        wrap.appendChild(note);
    }
    target.appendChild(wrap);
    _restoreFocus(target, focused);
}
