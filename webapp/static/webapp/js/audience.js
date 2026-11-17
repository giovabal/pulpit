/* Audience page (/audience/): the charts of its sections — the Lorenz curve and accounts-by-activity bars
   (participation), channels reached vs chance (breadth) and commenters per month (retention).
   Data comes from the audience-chart-data json_script (webapp/views.py AudienceView, webapp/audience/).
   Chart.js and PulpitA11y are loaded by the base template; colours are the --chart-* tokens, re-read
   on the reload a theme change triggers. */
(function() {
    "use strict";
    var source = document.getElementById("audience-chart-data");
    if (!source || typeof Chart === "undefined") return;
    var data = JSON.parse(source.textContent);
    var css = getComputedStyle(document.documentElement);
    var line = css.getPropertyValue("--chart-line").trim();
    var fill = css.getPropertyValue("--chart-fill").trim();
    var grid = css.getPropertyValue("--chart-grid").trim();
    var label = css.getPropertyValue("--chart-label").trim();
    var tickFont = { size: 11 };

    function pct(value, digits) {
        return (value * 100).toFixed(digits === undefined ? 0 : digits) + "%";
    }

    function axisTitle(text) {
        return { display: true, text: text, font: tickFont, color: label };
    }

    function lorenz(canvas) {
        if (!canvas || !data.lorenz || !data.lorenz.length) return;
        var points = data.lorenz.map(function(p) { return { x: p[0], y: p[1] }; });
        if (window.PulpitA11y) {
            var gini = data.gini === null ? "" : "Gini coefficient " + data.gini.toFixed(2) + ". ";
            var tenth = points.filter(function(p) { return p.x >= 0.9; })[0];
            PulpitA11y.accessibleChart(canvas, {
                label: "Lorenz curve of replies per account",
                summary: gini + (tenth ? "The least active 90% of accounts wrote " + pct(tenth.y) + " of the replies." : "")
            });
        }
        new Chart(canvas, {
            type: "scatter",
            data: {
                datasets: [{
                    label: "Replies",
                    data: points,
                    showLine: true,
                    borderColor: line,
                    backgroundColor: fill,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: line,
                    fill: "+1"
                }, {
                    label: "Perfect equality",
                    data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
                    showLine: true,
                    borderColor: label,
                    borderWidth: 1,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false
                }]
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "nearest", axis: "x", intersect: false },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { usePointStyle: true, pointStyle: "line", color: label, font: tickFont }
                    },
                    tooltip: {
                        filter: function(item) { return item.datasetIndex === 0; },
                        callbacks: {
                            title: function() { return ""; },
                            label: function(ctx) {
                                var p = ctx.raw;
                                return [
                                    "Least active " + pct(p.x) + " of accounts: " + pct(p.y, 1) + " of replies",
                                    "Most active " + pct(1 - p.x) + ": " + pct(1 - p.y, 1)
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: "linear",
                        min: 0,
                        max: 1,
                        title: axisTitle("Share of accounts, least to most active"),
                        grid: { color: grid },
                        ticks: { font: tickFont, color: label, stepSize: 0.2, callback: function(v) { return pct(v); } }
                    },
                    y: {
                        min: 0,
                        max: 1,
                        title: axisTitle("Share of replies"),
                        grid: { color: grid },
                        ticks: { font: tickFont, color: label, stepSize: 0.2, callback: function(v) { return pct(v); } }
                    }
                }
            }
        });
    }

    function activity(canvas) {
        if (!canvas || !data.bins || !data.bins.length) return;
        var bins = data.bins;
        if (window.PulpitA11y) {
            PulpitA11y.accessibleChart(canvas, {
                label: "Accounts by replies written",
                summary: bins.map(function(b) { return b.label + ": " + b.accounts.toLocaleString() + " accounts"; }).join("; ")
            });
        }
        new Chart(canvas, {
            type: "bar",
            data: {
                labels: bins.map(function(b) { return b.label; }),
                datasets: [{
                    data: bins.map(function(b) { return b.accounts; }),
                    backgroundColor: line,
                    hoverBackgroundColor: line,
                    borderRadius: { topLeft: 4, topRight: 4 },
                    borderSkipped: "start",
                    maxBarThickness: 24
                }]
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function(items) { return items[0].label + " replies"; },
                            label: function(ctx) {
                                var b = bins[ctx.dataIndex];
                                return [
                                    b.accounts.toLocaleString() + " accounts",
                                    "writing " + pct(b.reply_share, 1) + " of replies"
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: axisTitle("Replies per account"),
                        grid: { display: false },
                        ticks: { font: tickFont, color: label }
                    },
                    y: {
                        beginAtZero: true,
                        title: axisTitle("Accounts"),
                        grid: { color: grid },
                        ticks: { font: tickFont, color: label, precision: 0 }
                    }
                }
            }
        });
    }

    // A token colour with an alpha, for de-emphasised marks (hex tokens only).
    function withAlpha(hex, alpha) {
        var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
        if (!m) return hex;
        return "rgba(" + parseInt(m[1], 16) + ", " + parseInt(m[2], 16) + ", " + parseInt(m[3], 16) + ", " + alpha + ")";
    }

    // A legend under the chart whose keys mirror each series' mark (the dataset's own pointStyle).
    function legendBottom() {
        return { position: "bottom", labels: { usePointStyle: true, color: label, font: tickFont } };
    }

    function breadth(canvas) {
        if (!canvas || !data.breadth || !data.breadth.length) return;
        var rows = data.breadth;
        if (window.PulpitA11y) {
            PulpitA11y.accessibleChart(canvas, {
                label: "Channels reached, observed and by chance",
                summary: rows.map(function(r) {
                    return r.label + " replies: " + r.observed.toFixed(2) + " observed, " + r.expected.toFixed(2) + " by chance";
                }).join("; ")
            });
        }
        new Chart(canvas, {
            type: "bar",
            data: {
                labels: rows.map(function(r) { return r.label; }),
                datasets: [{
                    label: "Observed",
                    pointStyle: "rect",
                    data: rows.map(function(r) { return r.observed; }),
                    backgroundColor: line,
                    borderRadius: { topLeft: 4, topRight: 4 },
                    borderSkipped: "start",
                    maxBarThickness: 24
                }, {
                    label: "By chance",
                    pointStyle: "rect",
                    data: rows.map(function(r) { return r.expected; }),
                    backgroundColor: withAlpha(label, 0.45),
                    borderRadius: { topLeft: 4, topRight: 4 },
                    borderSkipped: "start",
                    maxBarThickness: 24
                }]
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: legendBottom(),
                    tooltip: {
                        callbacks: {
                            title: function(items) { return items[0].label + " replies"; },
                            label: function(ctx) { return ctx.dataset.label + ": " + ctx.raw.toFixed(2) + " channels"; }
                        }
                    }
                },
                scales: {
                    x: { title: axisTitle("Replies per account"), grid: { display: false }, ticks: { font: tickFont, color: label } },
                    y: { beginAtZero: true, title: axisTitle("Channels reached"), grid: { color: grid }, ticks: { font: tickFont, color: label } }
                }
            }
        });
    }

    function monthly(canvas) {
        if (!canvas || !data.monthly || !data.monthly.length) return;
        var rows = data.monthly;
        if (window.PulpitA11y) {
            PulpitA11y.accessibleChart(canvas, {
                label: "Commenters per month",
                summary: rows.length + " months, from " + rows[0].month + " to " + rows[rows.length - 1].month
            });
        }
        new Chart(canvas, {
            data: {
                labels: rows.map(function(r) { return r.month; }),
                datasets: [{
                    type: "line",
                    label: "Active commenters",
                    pointStyle: "line",
                    data: rows.map(function(r) { return r.active; }),
                    borderColor: line,
                    backgroundColor: line,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.2
                }, {
                    type: "bar",
                    label: "First-time commenters",
                    pointStyle: "rect",
                    data: rows.map(function(r) { return r.new; }),
                    backgroundColor: withAlpha(label, 0.45),
                    maxBarThickness: 24
                }]
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: { legend: legendBottom() },
                scales: {
                    x: { grid: { display: false }, ticks: { font: tickFont, color: label, maxTicksLimit: 12 } },
                    y: { beginAtZero: true, title: axisTitle("Accounts"), grid: { color: grid }, ticks: { font: tickFont, color: label, precision: 0 } }
                }
            }
        });
    }

    lorenz(document.getElementById("audience-lorenz"));
    activity(document.getElementById("audience-activity"));
    breadth(document.getElementById("audience-breadth"));
    monthly(document.getElementById("audience-monthly"));
})();
