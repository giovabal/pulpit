/* Home page charts split by label (?split=<label group id>, stats/split.py): one line per label, the other
   labels together, and the channels without a label. A panel holds one chart or two (own posts and forwards).
   Colours are the --split-* tokens in the page's fixed line order, so a label keeps its colour on every chart;
   point shapes repeat the identity for readers who cannot tell the colours apart. */
(function(global) {
    "use strict";

    var SHAPES = ["circle", "rectRot", "triangle", "rect", "star"];

    function token(css, name) {
        return css.getPropertyValue(name).trim();
    }

    function datasetsOf(chart, css) {
        var labelIndex = 0;
        return chart.lines.map(function(line) {
            var own = line.kind === "label";
            var index = own ? labelIndex++ : 0;
            var color = token(css, own ? "--split-" + (index + 1) : "--split-rest");
            return {
                label: line.label,
                data: line.values,
                borderColor: color,
                backgroundColor: color,
                borderWidth: own ? 2 : 1.5,
                borderDash: line.kind === "none" ? [2, 3] : [],
                pointStyle: own ? SHAPES[index] : "circle",
                pointRadius: own ? 2.5 : 1.5,
                pointHoverRadius: 5,
                fill: false,
                tension: 0.3
            };
        });
    }

    function drawSplitChart(canvas, data, chart, name, events) {
        var css = getComputedStyle(document.documentElement);
        var gridColor = token(css, "--chart-grid");
        var textColor = token(css, "--chart-label");
        var tickFont = { size: 11 };
        if (global.PulpitA11y) {
            PulpitA11y.accessibleChart(canvas, {
                label: name + " by " + data.split,
                summary: data.labels.length + " periods: " +
                    chart.lines.map(function(line) { return line.label; }).join(", ")
            });
        }
        new Chart(canvas, {
            type: "line",
            data: { labels: data.labels, datasets: datasetsOf(chart, css) },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { font: tickFont, color: textColor, usePointStyle: true, boxHeight: 7 }
                    },
                    tooltip: {
                        // The largest value first: the order the lines have at that month.
                        itemSort: function(a, b) { return b.raw - a.raw; },
                        callbacks: {
                            label: function(ctx) {
                                return ctx.dataset.label + ": " +
                                    ctx.raw.toLocaleString(undefined, { maximumFractionDigits: 1 });
                            }
                        }
                    },
                    annotation: { annotations: global.buildEventAnnotations(data.labels, events) }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { font: tickFont, color: textColor } },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: data.y_label, font: tickFont, color: textColor },
                        grid: { color: gridColor },
                        ticks: { font: tickFont, color: textColor }
                    }
                }
            }
        });
    }

    global.renderSplitCharts = function(wrap, data, events) {
        var first = wrap.querySelector("canvas");
        var panelName = global._pulpitChartLabel(first) || data.y_label;
        if (data.charts.length === 1) {
            drawSplitChart(first, data, data.charts[0], panelName, events);
            return;
        }
        wrap.classList.add("chart-canvas-wrap--split");
        wrap.replaceChildren();
        data.charts.forEach(function(chart) {
            var cell = document.createElement("div");
            var title = document.createElement("p");
            title.className = "chart-split-title";
            title.textContent = chart.title;
            var box = document.createElement("div");
            box.className = "chart-split-canvas";
            var canvas = document.createElement("canvas");
            box.appendChild(canvas);
            cell.append(title, box);
            wrap.appendChild(cell);
            drawSplitChart(canvas, data, chart, panelName + ", " + chart.title, events);
        });
    };
})(window);
