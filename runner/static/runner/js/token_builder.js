// Reusable drag-and-drop "token builder" for the Operations panel, used by both the Measures and
// the Community-strategies selectors. A palette of draggable chips feeds an ordered drop-zone;
// parameterised chips (data-multi="1") can be added repeatedly, each with inline parameter inputs
// and its own hidden <input> whose value is the composed token (e.g. "DIFFUSIONLAG(window=60)" or
// "LEIDEN_CPM(resolution=0.05)"). The form submits one hidden input per chip, in visual order, so
// order and repeats survive to the server unchanged.
//
//   var b = initTokenBuilder(opts);  // -> { rebuild(tokens) }
//
//   opts.paletteId / dropzoneId / countId : element ids (countId optional)
//   opts.seedId        : id of a json_script element holding the initial ordered token list
//   opts.fieldName     : name of the hidden <input> each selected chip owns ("measures", …)
//   opts.itemKey       : dataset key / kebab attribute naming a chip's token ("measure"/"strategy")
//   opts.actionSelector/actionKey : All/None buttons selector + their dataset key ('all'|'none')
//   opts.selectOptions : optional fn(kind) -> <option> HTML for enum params (else a number input)
//   opts.onChange      : optional fn(api) called after any add/remove/reorder/parameter change
(function () {
    "use strict";

    function initTokenBuilder(opts) {
        var palette = document.getElementById(opts.paletteId);
        var dropzone = document.getElementById(opts.dropzoneId);
        if (!palette || !dropzone) return { rebuild: function () {} };

        var emptyMsg = dropzone.querySelector(".ops-dropzone-empty");
        var countEl = opts.countId ? document.getElementById(opts.countId) : null;
        var itemKey = opts.itemKey;
        var fieldName = opts.fieldName;
        var dndType = "text/" + itemKey;
        var selectOptions = opts.selectOptions || function () { return ""; };
        var api = { rebuild: rebuild };

        function nameOf(el) { return el.dataset[itemKey]; }
        function selectedSelector(key) { return '.ops-selchip[data-' + itemKey + '="' + key + '"]'; }
        function notify() { if (opts.onChange) opts.onChange(api); }

        var META = {};
        palette.querySelectorAll(".ops-mchip").forEach(function (chip) {
            var dir = chip.querySelector(".ops-dir");
            META[nameOf(chip)] = {
                label: chip.dataset.label || nameOf(chip),
                dirIcon: dir ? dir.outerHTML : "",
                multi: chip.dataset.multi === "1",
                params: chip.dataset.params ? JSON.parse(chip.dataset.params) : [],
            };
        });

        function composeToken(chip) {
            var parts = [];
            chip.querySelectorAll(".ops-mparam-input").forEach(function (inp) {
                var v = String(inp.value).trim();
                if (v !== "") parts.push(inp.dataset.pname + "=" + v);
            });
            return parts.length ? nameOf(chip) + "(" + parts.join(",") + ")" : nameOf(chip);
        }
        function updateToken(chip) {
            var hidden = chip.querySelector('input[name="' + fieldName + '"]');
            if (hidden) hidden.value = composeToken(chip);
        }

        function refreshState() {
            var chips = dropzone.querySelectorAll(".ops-selchip");
            if (emptyMsg) emptyMsg.style.display = chips.length ? "none" : "";
            if (countEl) countEl.textContent = chips.length ? chips.length + " selected" : "";
            var present = {};
            chips.forEach(function (c) { present[nameOf(c)] = true; });
            palette.querySelectorAll(".ops-mchip").forEach(function (pc) {
                var used = pc.dataset.multi !== "1" && present[nameOf(pc)];
                pc.classList.toggle("ops-mchip--used", !!used);
                pc.setAttribute("draggable", used ? "false" : "true");
                var add = pc.querySelector(".ops-mchip-add");
                if (add) add.disabled = !!used;
            });
        }

        function makeParam(p, value) {
            var wrap = document.createElement("label");
            wrap.className = "ops-mparam";
            wrap.appendChild(document.createTextNode(p.label || p.name));
            var input;
            if (p.kind === "int" || p.kind === "float") {
                input = document.createElement("input");
                input.type = "number";
                if (p.min != null) input.min = p.min;
                if (p.max != null) input.max = p.max;
                if (p.step != null) input.step = p.step;
                input.value = value != null && value !== "" ? value : p.default;
            } else {
                input = document.createElement("select");
                input.innerHTML = selectOptions(p.kind);
                input.value = value != null && value !== "" ? String(value).toUpperCase() : p.default || "";
            }
            input.className = "ops-mparam-input";
            input.dataset.pname = p.name;
            wrap.appendChild(input);
            return wrap;
        }

        function addItem(key, params) {
            var meta = META[key];
            if (!meta) return null;
            var existing = dropzone.querySelector(selectedSelector(key));
            if (!meta.multi && existing) return existing;

            var chip = document.createElement("div");
            chip.className = "ops-selchip";
            chip.dataset[itemKey] = key;
            chip.setAttribute("draggable", "true");

            var head = document.createElement("span");
            head.className = "ops-selchip-head";
            head.innerHTML =
                '<i class="bi bi-grip-vertical ops-selchip-grip" aria-hidden="true"></i>' +
                meta.dirIcon +
                '<span class="ops-selchip-label"></span>';
            head.querySelector(".ops-selchip-label").textContent = meta.label;
            chip.appendChild(head);

            if (meta.params.length) {
                var pwrap = document.createElement("span");
                pwrap.className = "ops-selchip-params";
                meta.params.forEach(function (p) {
                    pwrap.appendChild(makeParam(p, params ? params[p.name] : undefined));
                });
                chip.appendChild(pwrap);
            }

            var ctrls = document.createElement("span");
            ctrls.className = "ops-selchip-ctrls";
            ctrls.innerHTML =
                '<button type="button" class="ops-selchip-btn" data-move="up" aria-label="Move up" title="Move up"><i class="bi bi-arrow-up" aria-hidden="true"></i></button>' +
                '<button type="button" class="ops-selchip-btn" data-move="down" aria-label="Move down" title="Move down"><i class="bi bi-arrow-down" aria-hidden="true"></i></button>' +
                '<button type="button" class="ops-selchip-btn ops-selchip-remove" data-remove="1" aria-label="Remove ' +
                meta.label +
                '" title="Remove"><i class="bi bi-x-lg" aria-hidden="true"></i></button>';
            chip.appendChild(ctrls);

            var hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = fieldName;
            chip.appendChild(hidden);

            dropzone.appendChild(chip);
            chip.querySelectorAll(".ops-mparam-input").forEach(function (inp) {
                inp.addEventListener("change", function () { updateToken(chip); notify(); });
                inp.addEventListener("input", function () { updateToken(chip); });
            });
            updateToken(chip);
            refreshState();
            return chip;
        }

        function parseToken(token) {
            var m = String(token).match(/^\s*([A-Za-z_]+)\s*(?:\(\s*(.*?)\s*\))?\s*$/);
            if (!m) return null;
            var key = m[1].toUpperCase();
            var params = {};
            var meta = META[key];
            (m[2] || "").split(",").forEach(function (piece, i) {
                piece = piece.trim();
                if (!piece) return;
                var eq = piece.indexOf("=");
                if (eq !== -1) params[piece.slice(0, eq).trim().toLowerCase()] = piece.slice(eq + 1).trim();
                else if (meta && meta.params[i]) params[meta.params[i].name] = piece; // legacy positional
            });
            return { key: key, params: params };
        }

        // Rebuild the drop zone from an ordered list of tokens (first load + load-defaults paths).
        function rebuild(tokens) {
            dropzone.querySelectorAll(".ops-selchip").forEach(function (c) { c.remove(); });
            (tokens || []).forEach(function (tok) {
                var parsed = parseToken(tok);
                if (parsed && META[parsed.key]) addItem(parsed.key, parsed.params);
            });
            refreshState();
            notify();
        }

        function getDragAfter(y) {
            var els = Array.prototype.slice.call(
                dropzone.querySelectorAll(".ops-selchip:not(.ops-selchip--dragging)")
            );
            var closest = { offset: -Infinity, el: null };
            els.forEach(function (el) {
                var box = el.getBoundingClientRect();
                var offset = y - box.top - box.height / 2;
                if (offset < 0 && offset > closest.offset) closest = { offset: offset, el: el };
            });
            return closest.el;
        }

        palette.addEventListener("dragstart", function (e) {
            var chip = e.target.closest(".ops-mchip");
            if (!chip || chip.getAttribute("draggable") === "false") return;
            e.dataTransfer.setData(dndType, nameOf(chip));
            e.dataTransfer.effectAllowed = "copy";
            chip.classList.add("ops-mchip--dragging");
        });
        palette.addEventListener("dragend", function (e) {
            var chip = e.target.closest(".ops-mchip");
            if (chip) chip.classList.remove("ops-mchip--dragging");
        });

        var draggingChip = null;
        dropzone.addEventListener("dragstart", function (e) {
            var chip = e.target.closest(".ops-selchip");
            if (!chip) return;
            draggingChip = chip;
            chip.classList.add("ops-selchip--dragging");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/reorder", "1");
        });
        dropzone.addEventListener("dragend", function () {
            if (draggingChip) draggingChip.classList.remove("ops-selchip--dragging");
            draggingChip = null;
            dropzone.classList.remove("ops-dropzone--over");
        });
        dropzone.addEventListener("dragover", function (e) {
            e.preventDefault();
            dropzone.classList.add("ops-dropzone--over");
            if (draggingChip) {
                var after = getDragAfter(e.clientY);
                if (after == null) dropzone.appendChild(draggingChip);
                else dropzone.insertBefore(draggingChip, after);
            }
        });
        dropzone.addEventListener("dragleave", function (e) {
            if (e.target === dropzone) dropzone.classList.remove("ops-dropzone--over");
        });
        dropzone.addEventListener("drop", function (e) {
            e.preventDefault();
            dropzone.classList.remove("ops-dropzone--over");
            if (draggingChip) { notify(); return; } // a reorder drop; order already updated live
            var key = e.dataTransfer.getData(dndType);
            if (key) {
                var chip = addItem(key);
                if (chip) {
                    var after = getDragAfter(e.clientY);
                    if (after == null) dropzone.appendChild(chip);
                    else dropzone.insertBefore(chip, after);
                    notify();
                }
            }
        });

        palette.addEventListener("click", function (e) {
            var add = e.target.closest(".ops-mchip-add");
            if (!add || add.disabled) return;
            var chip = add.closest(".ops-mchip");
            if (chip && addItem(nameOf(chip))) notify();
        });
        dropzone.addEventListener("click", function (e) {
            var btn = e.target.closest(".ops-selchip-btn");
            if (!btn) return;
            var chip = btn.closest(".ops-selchip");
            if (!chip) return;
            if (btn.dataset.remove) {
                chip.remove();
                refreshState();
                notify();
                return;
            }
            var sib;
            if (btn.dataset.move === "up") {
                sib = chip.previousElementSibling;
                if (sib && sib.classList.contains("ops-selchip")) dropzone.insertBefore(chip, sib);
            } else if (btn.dataset.move === "down") {
                sib = chip.nextElementSibling;
                if (sib && sib.classList.contains("ops-selchip")) dropzone.insertBefore(sib, chip);
            }
            notify();
        });

        if (opts.actionSelector) {
            document.querySelectorAll(opts.actionSelector).forEach(function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.dataset[opts.actionKey] === "none") {
                        dropzone.querySelectorAll(".ops-selchip").forEach(function (c) { c.remove(); });
                        refreshState();
                    } else {
                        palette.querySelectorAll(".ops-mchip").forEach(function (pc) {
                            if (!dropzone.querySelector(selectedSelector(nameOf(pc)))) addItem(nameOf(pc));
                        });
                    }
                    notify();
                });
            });
        }

        var initEl = opts.seedId ? document.getElementById(opts.seedId) : null;
        var initial = [];
        if (initEl) {
            try {
                initial = JSON.parse(initEl.textContent) || [];
            } catch (err) {
                initial = [];
            }
        }
        rebuild(initial);
        return api;
    }

    window.initTokenBuilder = initTokenBuilder;
})();
