var BASE_KEYS = ["fans", "messages_count", "in_deg", "out_deg"];

Promise.all([
    fetch("data/channels.json").then(function(r) { return r.json(); }),
    fetch("data/communities.json").then(function(r) { return r.json(); }),
]).then(function(results) {
    var channels = results[0], communities = results[1];
    var nodes = channels.nodes;
    var strategies = Object.keys(communities.strategies);

    // Sort by in_deg descending
    nodes.sort(function(a, b) { return (b.in_deg || 0) - (a.in_deg || 0); });

    // Extra measures: not in BASE_KEYS; pagerank ordered first
    var extraMeasures = (channels.measures || []).filter(function(m) { return BASE_KEYS.indexOf(m[0]) === -1; });
    var orderedExtra = extraMeasures.filter(function(m) { return m[0] === "pagerank"; })
        .concat(extraMeasures.filter(function(m) { return m[0] !== "pagerank"; }));

    // Heatmap ranges
    var hmKeys = BASE_KEYS.concat(orderedExtra.map(function(m) { return m[0]; }));
    var hmRanges = {};
    hmKeys.forEach(function(key) {
        var vals = nodes.map(function(n) { return n[key]; }).filter(function(v) { return v !== null && v !== undefined; });
        if (vals.length) hmRanges[key] = [Math.min.apply(null, vals), Math.max.apply(null, vals)];
    });

    // Build thead
    var thead = document.querySelector("#channel-table thead");
    var htr = document.createElement("tr");
    function addTh(label, cls) {
        var th = document.createElement("th");
        th.scope = "col";
        if (cls) th.className = cls;
        th.textContent = label;
        htr.appendChild(th);
    }
    addTh("Channel", "");
    addTh("Users", "number");
    addTh("Messages", "number");
    addTh("Inbound", "number");
    addTh("Outbound", "number");
    orderedExtra.forEach(function(m) { addTh(m[1], "number"); });
    strategies.forEach(function(s) { addTh(s.charAt(0).toUpperCase() + s.slice(1), ""); });
    addTh("Activity start", "");
    addTh("Activity end", "");
    thead.appendChild(htr);

    // Build tbody
    var tbody = document.querySelector("#channel-table tbody");
    nodes.forEach(function(node) {
        var tr = document.createElement("tr");

        function addTd(display, cls, sortVal, bg, link) {
            var td = document.createElement("td");
            if (cls) td.className = cls;
            if (sortVal !== "") td.setAttribute("data-sort-value", sortVal);
            if (bg) td.setAttribute("style", bg);
            if (link) {
                var a = document.createElement("a");
                a.href = link; a.target = "_blank"; a.rel = "noopener noreferrer";
                a.textContent = display; td.appendChild(a);
            } else {
                td.textContent = display;
            }
            tr.appendChild(td);
        }

        addTd(node.label || node.id, "", "", "", node.url || "");

        BASE_KEYS.forEach(function(key) {
            var val = node[key];
            var range = hmRanges[key];
            var bg = range ? heatmapBg(val, range[0], range[1]) : "";
            var s = val !== null && val !== undefined ? String(val) : "";
            addTd(s, "number", s, bg, "");
        });

        orderedExtra.forEach(function(m) {
            var val = node[m[0]];
            var range = hmRanges[m[0]];
            var bg = range ? heatmapBg(val, range[0], range[1]) : "";
            addTd(fmtNum(val, 4), "number", numSortVal(val), bg, "");
        });

        strategies.forEach(function(s) {
            var comm = (node.communities || {})[s];
            addTd(comm !== undefined ? String(comm) : "", "", "", "", "");
        });

        addTd(node.activity_start || "", "", "", "", "");
        addTd(node.activity_end || "", "", "", "", "");

        tbody.appendChild(tr);
    });

    document.getElementById("channel-count").textContent =
        nodes.length + " channel" + (nodes.length !== 1 ? "s" : "") + ". Click column headers to sort.";

    initSortableTables();
});
