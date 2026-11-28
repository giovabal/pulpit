// Render the Audience page (audience.html) from data/audience.json (network/audience_layer.py).
//
// The five sections of the web app's /audience/ page, over the export's scope:
//   - participation: concentration figures, Lorenz curve, accounts by activity, per-channel table
//   - breadth:       channels reached vs the rarefaction expectation, spread across each label group
//   - overlap:       channel × channel shared-commenter matrix (tinted vs the fixed-account-degree null),
//                    pairs, label pairs, audience-vs-citations QAP
//   - retention:     commenters per month, quarterly cohorts
//   - channel commenters: channels commenting as themselves on other channels' posts
//
// The tints are computed by the exporter (webapp/audience/tables.py) so the page and the export share
// one rule; Chart.js comes from the CDN like events.html.
//
// Period switcher: same pattern as links.js — on a timeline export each period with comments has its own
// data_<key>/audience.json (has_audience in timeline.json); "All" is the full range in data/.
import { build_year_nav } from './year_nav.js';
import { escHtml, fetchJson, fetchJsonOrNull, isCompareDataDir, loadFailed, loadRecovered, periodDataDir, readTimeline } from './utils.js';

var _dd = window.DATA_DIR || "data/";
var _no_timeline = isCompareDataDir(_dd);
var PAIR_LIMIT = 30;
var _current = "all";
var _cache = {};
var _periods = [];
var _events = [];
var _loading = false;
var _charts = [];

// The shared formatters of format.js under this page's names.
var _isNil = isNil;
var _pct = fmtShare;
var _dec = fmtFixed;

// "2024-03-01" → "2024-03": year and month, the date form of every export page.
function _month(iso) {
    return iso ? String(iso).slice(0, 7) : MISSING;
}

function _channel(ref) {
    if (!ref) return MISSING;
    var org = ref.organization ? " <span class=\"text-muted small\">(" + escHtml(ref.organization) + ")</span>" : "";
    return escHtml(ref.label) + org;
}

function _swatch(color) {
    return color ? "<span class=\"d-inline-block rounded-1 me-1 align-middle\" style=\"width:.8em;height:.8em;background:" + escHtml(color) + "\" aria-hidden=\"true\"></span>" : "";
}

// ── Building blocks ──────────────────────────────────────────────────────────

function _card(label, value, note, secondary) {
    return "<div class=\"audience-card\"><span class=\"audience-card-label\">" + escHtml(label) + "</span>" +
        "<span class=\"audience-card-value\">" + value + "</span>" +
        (note ? "<span class=\"audience-card-note\">" + note + "</span>" : "") +
        (secondary || []).map(function(s) { return "<span class=\"audience-card-secondary\">" + s + "</span>"; }).join("") +
        "</div>";
}

function _cards(items) {
    return "<div class=\"audience-cards\">" + items.join("") + "</div>";
}

// columns: [{label, number, title}]; rows: arrays of cell HTML (already escaped) or {html, sort, cls, style, title}.
function _table(caption, columns, rows, opts) {
    opts = opts || {};
    var head = "<tr>" + columns.map(function(c) {
        return "<th scope=\"col\"" + (c.number ? " class=\"number text-end\"" : "") + (c.title ? " title=\"" + escHtml(c.title) + "\"" : "") + ">" + escHtml(c.label) + "</th>";
    }).join("") + "</tr>";
    var body = rows.map(function(row) {
        return "<tr>" + row.map(function(cell, i) {
            var c = (cell !== null && typeof cell === "object") ? cell : { html: cell };
            var cls = [columns[i] && columns[i].number ? "number" : "", c.cls || ""].join(" ").trim();
            return "<td" + (cls ? " class=\"" + cls + "\"" : "") +
                (_isNil(c.sort) ? "" : " data-sort-value=\"" + escHtml(String(c.sort)) + "\"") +
                (c.style ? " style=\"" + c.style + "\"" : "") +
                (c.title ? " title=\"" + escHtml(c.title) + "\"" : "") + ">" + c.html + "</td>";
        }).join("") + "</tr>";
    }).join("");
    return "<div class=\"table-responsive" + (opts.wide ? " export-wide" : "") + "\"><table class=\"table table-hover table-sm" + (opts.sortable === false ? "" : " sortable") + "\" aria-label=\"" + escHtml(caption) + "\">" +
        "<caption class=\"small text-muted\">" + escHtml(caption) + "</caption><thead>" + head + "</thead><tbody>" + body + "</tbody></table></div>";
}

function _num(v, text) {
    return { html: text, sort: _isNil(v) ? "" : v };
}

function _chartBox(id, title) {
    return "<div><h3 class=\"audience-chart-title\" id=\"" + id + "-title\">" + escHtml(title) + "</h3><div class=\"audience-chart\"><canvas id=\"" + id + "\" aria-labelledby=\"" + id + "-title\"></canvas></div></div>";
}

// Every chart goes through here so a period switch can destroy the previous period's instances.
function _chart(canvas, config) {
    _charts.push(new Chart(canvas, config));
}

function _empty(text) {
    return "<p class=\"text-muted\">" + escHtml(text) + "</p>";
}

function _axes(xTitle, yTitle, pctX, pctY) {
    var theme = pulpitTheme();
    var text = theme.text,
        grid = theme.grid;

    function axis(title, pct) {
        var a = { title: { display: true, text: title, color: text }, ticks: { color: text }, grid: { color: grid } };
        if (pct) {
            a.min = 0;
            a.max = 1;
            a.ticks.stepSize = 0.2;
            a.ticks.callback = function(v) { return _pct(v, 0); };
        }
        return a;
    }
    return { x: axis(xTitle, pctX), y: axis(yTitle, pctY) };
}

function _legend() {
    return { labels: { color: pulpitTheme().text, boxWidth: 14 } };
}

// ── Participation ────────────────────────────────────────────────────────────

function _participation(target, data) {
    var o = data.overall;
    if (!o.accounts) {
        target.innerHTML = _empty("No reply in scope: no comment was collected under the posts of the channels in this export.");
        return;
    }
    var hyper = o.hyperactive || {};
    var html = _cards([
        _card("Commenters", fmtInt(o.accounts), "", ["<strong>" + fmtInt(o.replies) + "</strong> replies", "<strong>" + _dec(o.mean, 1) + "</strong> per account, median <strong>" + _dec(o.median, 0) + "</strong>"]),
        _card("Most active 10%", _pct(o.top10_share), "of replies", ["most active 1%: <strong>" + _pct(o.top1_share) + "</strong>"]),
        _card("Gini coefficient", _dec(o.gini, 2), "", ["0 = every account writes as much; 1 = one account writes everything"]),
        _card("Effective commenters", fmtInt(o.effective_number), "", ["the replies are as concentrated as if this many accounts wrote equal shares"]),
        _card("One-time commenters", _pct(o.one_time_share), "of accounts", ["writing <strong>" + _pct(o.one_time_reply_share) + "</strong> of replies"]),
        _card("Hyperactive accounts", fmtInt(hyper.accounts), _pct(hyper.account_share, 1) + " of accounts", ["writing <strong>" + _pct(hyper.reply_share) + "</strong> of replies", "<strong>" + fmtInt(hyper.min_replies) + "</strong> or more replies each (adjusted boxplot)"]),
    ]);
    html += "<div class=\"audience-charts\">" + _chartBox("au-lorenz", "Lorenz curve") + _chartBox("au-activity", "Accounts by replies written") + "</div>";
    html += _table("Accounts and replies by replies written per account", [
        { label: "Replies per account" },
        { label: "Accounts", number: true },
        { label: "Share of accounts", number: true },
        { label: "Replies", number: true },
        { label: "Share of replies", number: true },
    ], data.bins.map(function(b) {
        return [escHtml(b.label), _num(b.accounts, fmtInt(b.accounts)), _num(b.account_share, _pct(b.account_share, 1)), _num(b.replies, fmtInt(b.replies)), _num(b.reply_share, _pct(b.reply_share, 1))];
    }));
    html += "<h3>By channel</h3>";
    html += _table("Participation per channel, most commenters first. The top-10% share, Gini and effective commenters need at least " +
        data.min_concentration_commenters + " commenters. Hyperactive = the share of the channel's replies written by the hyperactive accounts above.", [
            { label: "Channel" },
            { label: "Subscribers", number: true, title: "At the last crawl" },
            { label: "Commenters", number: true },
            { label: "Per 100 subs.", number: true, title: "Commenters over the whole period per 100 subscribers at the last crawl. Commenters need not subscribe." },
            { label: "Replies", number: true },
            { label: "Per commenter", number: true },
            { label: "One-time", number: true, title: "Share of commenters who replied once" },
            { label: "Top 10%", number: true, title: "Share of the replies written by the channel's most active 10% of commenters" },
            { label: "Gini", number: true },
            { label: "Effective", number: true, title: "Effective number of commenters" },
            { label: "Hyperactive", number: true, title: "Share of the channel's replies written by hyperactive accounts" },
        ], data.channels.map(function(r) {
            return [
                { html: _channel(r.channel), sort: r.channel ? r.channel.label : "" },
                _num(r.subscribers, fmtInt(r.subscribers)),
                _num(r.accounts, fmtInt(r.accounts)),
                _num(r.commenter_rate, _isNil(r.commenter_rate) ? MISSING : fmtFixed(100 * r.commenter_rate, 1)),
                _num(r.replies, fmtInt(r.replies)),
                _num(r.mean, _dec(r.mean, 1)),
                _num(r.one_time_share, _pct(r.one_time_share)),
                _num(r.top10_share, _pct(r.top10_share)),
                _num(r.gini, _dec(r.gini, 2)),
                _num(r.effective_number, _dec(r.effective_number, 0)),
                _num(r.hyperactive_reply_share, _pct(r.hyperactive_reply_share)),
            ];
        }), { wide: true });
    target.innerHTML = html;
    _lorenzChart(document.getElementById("au-lorenz"), data.lorenz, o.gini);
    _activityChart(document.getElementById("au-activity"), data.bins);
}

function _lorenzChart(canvas, lorenz, gini) {
    if (!canvas || typeof Chart === "undefined" || !lorenz.length) return;
    var points = lorenz.map(function(p) { return { x: p[0], y: p[1] }; });
    var theme = pulpitTheme();
    if (window.PulpitA11y) {
        var tenth = points.filter(function(p) { return p.x >= 0.9; })[0];
        PulpitA11y.accessibleChart(canvas, {
            label: "Lorenz curve of replies per account",
            summary: (_isNil(gini) ? "" : "Gini coefficient " + fmtFixed(gini, 2) + ". ") + (tenth ? "The least active 90% of accounts wrote " + _pct(tenth.y) + " of the replies." : ""),
        });
    }
    _chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                { label: "Replies", data: points, showLine: true, borderColor: theme.series[0], backgroundColor: theme.series[0], borderWidth: 2, pointRadius: 0 },
                { label: "Perfect equality", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], showLine: true, borderColor: theme.muted, backgroundColor: theme.muted, borderWidth: 1, pointRadius: 0 },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: _legend(),
                tooltip: {
                    filter: function(item) { return item.datasetIndex === 0; },
                    callbacks: {
                        label: function(ctx) {
                            return "Least active " + _pct(ctx.raw.x) + " of accounts: " + _pct(ctx.raw.y, 1) + " of replies";
                        },
                    },
                },
            },
            scales: _axes("Share of accounts, least to most active", "Share of replies", true, true),
        },
    });
}

function _activityChart(canvas, bins) {
    if (!canvas || typeof Chart === "undefined" || !bins.length) return;
    if (window.PulpitA11y) {
        PulpitA11y.accessibleChart(canvas, {
            label: "Accounts by replies written",
            summary: bins.map(function(b) { return b.label + ": " + fmtInt(b.accounts) + " accounts"; }).join("; "),
        });
    }
    _chart(canvas, {
        type: "bar",
        data: {
            labels: bins.map(function(b) { return b.label; }),
            datasets: [{ label: "Accounts", data: bins.map(function(b) { return b.accounts; }), backgroundColor: pulpitTheme().series[0] }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: { display: false } },
            scales: _axes("Replies per account", "Accounts", false, false),
        },
    });
}

// ── Breadth ──────────────────────────────────────────────────────────────────

function _breadth(target, data) {
    if (!data.accounts) {
        target.innerHTML = _empty("No reply in scope.");
        return;
    }
    var spread = data.channel_spread || {};
    var html = _cards([
        _card("On more than one channel", _pct(data.multi_channel_share), "of " + fmtInt(data.accounts) + " commenters"),
        _card("Channels reached", _dec(spread.observed_mean, 2), "on average", ["chance would give <strong>" + _dec(spread.expected_mean, 2) + "</strong> for the same replies (accounts with 2+ replies)"]),
        _card("Narrower than chance", _pct(spread.below_share), "of accounts", ["reach fewer channels than their replies would by chance"]),
    ]);
    var classes = spread.classes || [];
    if (classes.length) {
        html += "<div class=\"audience-charts\">" + _chartBox("au-breadth-chart", "Channels reached, observed and by chance") + "<div>" +
            _table("Channels per commenter", [{ label: "Channels" }, { label: "Accounts", number: true }, { label: "Share", number: true }],
                data.channel_bins.map(function(b) { return [escHtml(b.label), _num(b.accounts, fmtInt(b.accounts)), _num(b.share, _pct(b.share, 1))]; })) +
            "</div></div>";
        html += _table("Channels reached by replies written. Below chance: the share of the class's accounts reaching fewer channels than the expectation.", [
            { label: "Replies per account" },
            { label: "Accounts", number: true },
            { label: "Channels reached", number: true },
            { label: "By chance", number: true },
            { label: "Observed / chance", number: true },
            { label: "Below chance", number: true },
        ], classes.map(function(c) {
            return [escHtml(c.label), _num(c.accounts, fmtInt(c.accounts)), _num(c.observed, _dec(c.observed, 2)), _num(c.expected, _dec(c.expected, 2)), _num(c.ratio, _dec(c.ratio, 2)), _num(c.below_share, _pct(c.below_share))];
        }));
    }
    (data.groups || []).forEach(function(g) {
        var name = escHtml(g.name.toLowerCase());
        html += "<h3>Across " + name + " labels</h3>";
        html += "<p class=\"small\">Of the " + fmtInt(g.accounts) + " commenters on channels with a " + name + " label, <strong>" + _pct(g.multi_label_share, 1) +
            "</strong> of those with 2+ replies comment under more than one label; their effective number of labels averages <strong>" + _dec(g.effective_mean, 2) +
            "</strong>, and <strong>" + _pct(g.cross_share_mean, 1) + "</strong> of their replies fall outside their main label. They reach <strong>" +
            _dec((g.spread || {}).ratio, 2) + "</strong> times the labels chance would give." +
            (g.unlabelled_replies ? " " + fmtInt(g.unlabelled_replies) + " replies on channels without a " + name + " label are left out." : "") + "</p>";
        html += _table(g.name + " labels", [
            { label: g.name },
            { label: "Commenters", number: true },
            { label: "Replies", number: true },
            { label: "Also elsewhere", number: true, title: "Share of the label's commenters who also comment under another label of the group" },
        ], g.labels.map(function(lab) {
            return [{ html: _swatch(lab.color) + escHtml(lab.name), sort: lab.name }, _num(lab.commenters, fmtInt(lab.commenters)), _num(lab.replies, fmtInt(lab.replies)), _num(lab.elsewhere_share, _pct(lab.elsewhere_share, 1))];
        }));
    });
    target.innerHTML = html;
    _breadthChart(document.getElementById("au-breadth-chart"), classes);
}

function _breadthChart(canvas, classes) {
    if (!canvas || typeof Chart === "undefined" || !classes.length) return;
    if (window.PulpitA11y) {
        PulpitA11y.accessibleChart(canvas, {
            label: "Channels reached, observed and by chance",
            summary: classes.map(function(c) { return c.label + " replies: " + _dec(c.observed, 2) + " channels, " + _dec(c.expected, 2) + " by chance"; }).join("; "),
        });
    }
    _chart(canvas, {
        type: "bar",
        data: {
            labels: classes.map(function(c) { return c.label; }),
            datasets: [
                { label: "Observed", data: classes.map(function(c) { return c.observed; }), backgroundColor: pulpitTheme().series[0] },
                { label: "By chance", data: classes.map(function(c) { return c.expected; }), backgroundColor: pulpitTheme().muted },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: _legend() },
            scales: _axes("Replies per account", "Mean channels reached", false, false),
        },
    });
}

// ── Audience overlap ─────────────────────────────────────────────────────────

function _pairRows(pairs, nameA, nameB) {
    return pairs.map(function(pr) {
        return [
            { html: nameA(pr) + " · " + nameB(pr) },
            _num(pr.shared, fmtInt(pr.shared)),
            _num(pr.expected, _dec(pr.expected, 1)),
            _num(pr.ratio, _dec(pr.ratio, 2)),
            _num(pr.q, qHtml(pr.q)),
        ];
    });
}

var PAIR_COLUMNS = [
    { label: "Pair" },
    { label: "Shared", number: true },
    { label: "Expected", number: true, title: "Shared commenters expected under the null that keeps every commenter's number of channels" },
    { label: "Ratio", number: true },
    { label: "q", number: true, title: "Benjamini–Hochberg adjusted p-value over every pair" },
];

function _overlap(target, data) {
    var channels = data.channels || [];
    if (channels.length < 2) {
        target.innerHTML = _empty("Fewer than two channels in scope have commenters.");
        return;
    }
    var html = [];
    var cards = [_card("Pairs sharing more than chance", fmtInt(data.validated), "of " + fmtInt(data.tested) + " channel pairs", ["q &lt; " + data.q_threshold + " (Benjamini–Hochberg)"])];
    if (data.qap) {
        cards.push(_card("Audience follows citations", "r = " + _dec(data.qap.r, 2), "QAP " + pText(data.qap.p),
            ["shared commenters vs forwards + mentions, over " + fmtInt(data.qap.pairs) + " pairs (" + fmtInt(data.qap.cited_pairs) + " citing)"]));
    }
    html.push(_cards(cards));

    var byId = {};
    channels.forEach(function(c) { byId[c.id] = c; });
    var lookup = {};
    data.pairs.forEach(function(pr) {
        lookup[pr.a + "|" + pr.b] = pr;
        lookup[pr.b + "|" + pr.a] = pr;
    });
    var columns = [{ label: "Channel" }, { label: "Commenters", number: true }, { label: "Exclusive", number: true, title: "Share of its commenters who comment on no other channel in scope / the share expected by chance" }]
        .concat(channels.map(function(c) { return { label: String(c.index) }; }));
    var rows = channels.map(function(row) {
        var cells = [
            { html: "<span class=\"text-muted me-1\">" + row.index + "</span>" + _channel(row.channel) },
            _num(row.commenters, fmtInt(row.commenters)),
            _num(row.exclusive.observed, _pct(row.exclusive.observed) + " <span class=\"text-muted\">/ " + _pct(row.exclusive.expected) + "</span>"),
        ];
        channels.forEach(function(col) {
            if (col.id === row.id) {
                cells.push({ html: "", cls: "audience-cell audience-cell--self", title: "same channel" });
                return;
            }
            var pr = lookup[row.id + "|" + col.id];
            if (!pr) {
                // A pair that is not listed shares no commenter: a zero, not a missing value.
                cells.push({ html: "0", cls: "audience-cell text-center text-muted", title: "no shared commenter" });
                return;
            }
            cells.push({
                html: fmtInt(pr.shared) + (sigStars(pr.q) ? "<span class=\"audience-sig\">" + sigStars(pr.q) + "</span>" : ""),
                cls: "audience-cell text-center" + (pr.heat ? " audience-cell--" + pr.heat.side : ""),
                style: pr.heat ? "--heat: " + pr.heat.percent + "%;" : "",
                title: pr.shared + " shared, " + _dec(pr.expected, 1) + " expected, " + pText(pr.q, "q"),
            });
        });
        return cells;
    });
    html.push("<p class=\"small text-muted mb-1\">Shared commenters per pair of channels; the tint is the ratio to the expectation — <span class=\"audience-key audience-key--pos\">more than chance</span>, " +
        "<span class=\"audience-key audience-key--neg\">fewer</span> — and the stars mark significance: " + escHtml(sigLegend("q")) +
        " Pairs with fewer than 3 commenters shared and expected stay untinted. Hover a cell for the figures. Columns follow the rows' numbers.</p>");
    html.push(_table("Channel × channel shared commenters", columns, rows, { sortable: false, wide: true }));

    function chName(key) {
        return function(pr) { return byId[pr[key]] ? _channel(byId[pr[key]].channel) : escHtml(pr[key]); };
    }
    html.push("<h3>Pairs, most significant first</h3>");
    html.push(_table("The " + Math.min(PAIR_LIMIT, data.pairs.length) + " most significant of " + fmtInt(data.pairs.length) + " pairs with shared commenters" +
        (data.pairs.length > PAIR_LIMIT ? (_current === "all" ? "; audience.xlsx and audience_overlap.csv list them all." :
            "; the period's Overlap pairs sheet of audience.xlsx lists them all.") : "."), PAIR_COLUMNS, _pairRows(data.pairs.slice(0, PAIR_LIMIT), chName("a"), chName("b"))));
    var legend = "<p class=\"text-muted small\">" + escHtml(sigLegend("q")) + "</p>";
    html.push(legend);

    (data.label_groups || []).forEach(function(g) {
        html.push("<h3>Between " + escHtml(g.name.toLowerCase()) + " labels</h3>");
        html.push(g.pairs.length ?
            _table(g.name + " label pairs, most significant first", PAIR_COLUMNS, _pairRows(g.pairs, function(pr) { return escHtml(pr.name_a); }, function(pr) { return escHtml(pr.name_b); })) + legend :
            _empty("No two labels share a commenter."));
    });
    target.innerHTML = html.join("");
}

// ── Retention ────────────────────────────────────────────────────────────────

function _retention(target, data) {
    if (!data.accounts) {
        target.innerHTML = _empty("No reply in scope.");
        return;
    }
    var html = _cards([
        _card("Came back", _pct(data.returning_share), "of " + fmtInt(data.accounts) + " commenters", ["commented in more than one month"]),
        _card("Comments from", _month(data.first_day) + " – " + _month(data.last_day), ""),
    ]);
    html += "<div class=\"audience-charts\">" + _chartBox("au-monthly", "Commenters per month") + "</div>";
    html += "<h3>Cohorts</h3>";
    var quarters = data.cohort_quarters || [];
    html += _table("Accounts by the quarter of their first reply, and the share of each cohort commenting again 1, 2, … quarters later. Darker = more of the cohort; blank = not over yet.",
        [{ label: "First reply" }, { label: "Accounts", number: true }].concat(quarters.map(function(q) { return { label: "+" + q }; })),
        data.cohorts.map(function(c) {
            return [escHtml(c.quarter), _num(c.size, fmtInt(c.size))].concat(c.cells.map(function(cell) {
                return cell ? { html: _pct(cell.value), sort: cell.value, cls: "audience-cell audience-cell--seq text-center", style: "--heat: " + cell.percent + "%;" } : { html: "", cls: "audience-cell" };
            }));
        }));
    target.innerHTML = html;
    _monthlyChart(document.getElementById("au-monthly"), data.monthly);
}

function _monthlyChart(canvas, monthly) {
    if (!canvas || typeof Chart === "undefined" || !monthly.length) return;
    if (window.PulpitA11y) {
        var peak = monthly.reduce(function(a, b) { return b.active > a.active ? b : a; });
        PulpitA11y.accessibleChart(canvas, {
            label: "Commenters per month",
            summary: monthly.length + " months from " + monthly[0].month + " to " + monthly[monthly.length - 1].month + "; most active month " + peak.month + " with " + fmtInt(peak.active) + " commenters.",
        });
    }
    _chart(canvas, {
        type: "line",
        data: {
            labels: monthly.map(function(m) { return m.month; }),
            datasets: [
                { label: "Active commenters", data: monthly.map(function(m) { return m.active; }), borderColor: pulpitTheme().series[0], backgroundColor: pulpitTheme().series[0], pointRadius: 0, borderWidth: 2 },
                { label: "First-time commenters", data: monthly.map(function(m) { return m.new; }), borderColor: pulpitTheme().series[1], backgroundColor: pulpitTheme().series[1], pointRadius: 0, borderWidth: 2 },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: _legend() },
            scales: _axes("Month", "Accounts", false, false),
        },
    });
}

// ── Channels as commenters ───────────────────────────────────────────────────

function _channelCommenters(target, data) {
    var kinds = data.kinds || {};
    var html = _cards([
        _card("On other channels' posts", fmtInt(kinds.other), "comments", ["by <strong>" + fmtInt(data.commenting_channels) + "</strong> channels, over <strong>" + fmtInt(data.pairs.length) + "</strong> pairs"]),
        _card("Ties the citations miss", fmtInt(data.uncited_pairs), "pairs", ["neither forwards nor mentions the other"]),
        _card("On their own posts", fmtInt(kinds.own), "comments", ["plus <strong>" + fmtInt(kinds.group) + "</strong> by discussion groups' anonymous admins"]),
    ]);
    if (!data.pairs.length) {
        target.innerHTML = html + _empty("No channel commented as itself on another channel's posts.");
        return;
    }
    html += _table("Channel → channel comments", [
        { label: "Commenting channel" },
        { label: "On the posts of" },
        { label: "Comments", number: true },
        { label: "When" },
        { label: "Also cited", title: "Whether the two channels forward or mention each other, either way, in any collected message" },
    ], data.pairs.map(function(r) {
        var sender = r.sender ? _channel(r.sender) + (r.sender_in_target ? "" : " <span class=\"badge text-bg-secondary\">outside the studied set</span>") :
            escHtml(r.sender_name || "Unnamed channel") + " <span class=\"text-muted small\">(not collected; Telegram id " + escHtml(String(r.sender_tid)) + ")</span>";
        var first = _month(r.first),
            last = _month(r.last);
        return [
            { html: sender, sort: r.sender ? r.sender.label : r.sender_name },
            { html: _channel(r.channel), sort: r.channel ? r.channel.label : "" },
            _num(r.comments, fmtInt(r.comments)),
            { html: first === last ? first : first + " – " + last, sort: r.first || "" },
            { html: _isNil(r.cited) ? "<span class=\"text-muted\">" + MISSING + "</span>" : (r.cited ? "yes" : "no"), sort: _isNil(r.cited) ? "" : (r.cited ? 1 : 0) },
        ];
    }), { wide: true });
    target.innerHTML = html;
}

// ── Page ─────────────────────────────────────────────────────────────────────

function _preamble(payload) {
    var c = payload.coverage;
    var span = payload.start_date || payload.end_date ? " Posts dated " + (payload.start_date ? "from " + payload.start_date : "") +
        (payload.end_date ? " to " + payload.end_date : "") + "." : "";
    var p = document.createElement("p");
    p.className = "table-preamble";
    p.textContent = fmtInt(c.channels_with_comments) + " of the " + fmtInt(c.scope_channels) + " observed channels have comments (" +
        fmtInt(c.channels_with_discussion) + " have a discussion group): the figures describe their commenters, not the whole network's audience." +
        (c.left_out_accounts ? " " + fmtInt(c.left_out_accounts) + " account" + (c.left_out_accounts === 1 ? " flagged as a Telegram bot or bulk poster is" : "s flagged as Telegram bots or bulk posters are") + " left out." : "") + span;
    var target = document.getElementById("au-preamble");
    target.innerHTML = "";
    target.appendChild(p);
}

function _render(payload) {
    _charts.forEach(function(chart) { chart.destroy(); });
    _charts = [];
    _preamble(payload);
    _participation(document.getElementById("au-participation"), payload.participation);
    _breadth(document.getElementById("au-breadth"), payload.breadth);
    _overlap(document.getElementById("au-overlap"), payload.overlap);
    _retention(document.getElementById("au-retention"), payload.retention);
    _channelCommenters(document.getElementById("au-channel-commenters"), payload.channel_commenters);
    initSortableTables();
}

function _load(key) {
    if (_cache[key]) return Promise.resolve(_cache[key]);
    var dd = (key === "all") ? _dd : periodDataDir("data/", key);
    return fetchJson(dd + "audience.json").then(function(payload) {
        _cache[key] = payload;
        return payload;
    });
}

function _switch(key) {
    if (key === _current || _loading) return;
    _loading = true;
    _load(key).then(function(payload) {
        _current = key;
        loadRecovered();
        _render(payload);
        build_year_nav(_periods, _current, _switch, _events);
    }).catch(function(err) {
        loadFailed(err, "the audience of " + key);
    }).finally(function() {
        _loading = false;
    });
}

Promise.all([
    _load(_current),
    fetchJsonOrNull(_dd + "timeline.json"),
]).then(function(results) {
    _render(results[0]);
    var tl = readTimeline(_no_timeline ? null : results[1]);
    _events = tl.events;
    _periods = tl.periods.filter(function(p) { return p.has_audience; });
    if (_periods.length) build_year_nav(_periods, _current, _switch, _events);
}).catch(function(err) {
    loadFailed(err);
});
